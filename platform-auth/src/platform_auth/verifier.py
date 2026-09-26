from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx

from platform_auth.principal import PlatformPrincipal, parse_codes

logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    principal: PlatformPrincipal


class PlatformTokenVerifier:
    """Confirm a caller token by asking the existing .NET auth service."""

    def __init__(
        self,
        *,
        configured: bool,
        me_path: str = "/api/v1/auth/me",
        cache_ttl_seconds: int = 0,
        required_permissions: tuple[str, ...] = (),
        base_url: str = "",
        verify_ssl: bool = True,
        timeout_seconds: float = 10.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._configured = configured
        self._me_path = me_path if me_path.startswith("/") else f"/{me_path}"
        self._cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._required_permissions = required_permissions
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            verify=verify_ssl,
            timeout=timeout_seconds,
        )
        self._cache: dict[str, _CacheEntry] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def authenticate(self, authorization: str | None) -> PlatformPrincipal:
        token = _bearer(authorization)
        if not token:
            raise AuthError("UNAUTHORIZED", "Authorization bearer token is required.", 401)
        if not self._configured:
            raise AuthError(
                "AUTH_NOT_CONFIGURED",
                "AUTH_SERVICE_BASE_URL is required to accept platform tokens.",
                503,
            )
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        cached = self._cached(digest)
        if cached is not None:
            return cached
        principal = await self._load(token)
        if self._cache_ttl_seconds:
            self._cache[digest] = _CacheEntry(time.monotonic() + self._cache_ttl_seconds, principal)
        return principal

    def _cached(self, digest: str) -> PlatformPrincipal | None:
        entry = self._cache.get(digest)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._cache.pop(digest, None)
            return None
        return entry.principal

    async def _load(self, token: str) -> PlatformPrincipal:
        try:
            response = await self._http.get(
                self._me_path,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning("auth.unavailable")
            raise AuthError("AUTH_UNAVAILABLE", "Auth service is unreachable.", 503) from exc
        if response.status_code == 401:
            logger.info("auth.rejected status=401")
            raise AuthError("UNAUTHORIZED", "Platform token was rejected.", 401)
        if response.status_code == 403:
            logger.info("auth.rejected status=403")
            raise AuthError("FORBIDDEN", "Platform token was rejected.", 403)
        if response.status_code >= 400:
            logger.warning("auth.unavailable status=%s", response.status_code)
            raise AuthError("AUTH_UNAVAILABLE", "Auth service could not validate the token.", 503)
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError("AUTH_UNAVAILABLE", "Auth service returned an unreadable identity.", 503) from exc
        if not isinstance(body, dict):
            raise AuthError("AUTH_UNAVAILABLE", "Auth service returned an unreadable identity.", 503)
        principal = _principal(token, body)
        if not principal.username and not principal.subject:
            raise AuthError("AUTH_UNAVAILABLE", "Auth service returned an empty identity.", 503)
        if not principal.has_all(self._required_permissions):
            logger.info("auth.forbidden user=%s", principal.username or principal.subject)
            raise AuthError("FORBIDDEN", "Caller is missing a required platform permission.", 403)
        logger.info("auth.accepted user=%s", principal.username or principal.subject)
        return principal


def _bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    prefix = "bearer "
    value = authorization.strip()
    if value.lower().startswith(prefix):
        value = value[len(prefix) :].strip()
    return value


def _principal(token: str, body: dict) -> PlatformPrincipal:
    subject = str(body.get("sub") or "").strip()
    username = str(body.get("username") or body.get("name") or "").strip()
    user_id = str(body.get("userId") or body.get("UserId") or subject).strip()
    permissions = parse_codes(body.get("permissions"))
    if not permissions:
        permissions = parse_codes(body.get("roles"))
    return PlatformPrincipal(
        token=token,
        subject=subject,
        username=username,
        user_id=user_id,
        groups=parse_codes(body.get("groups")),
        permissions=permissions,
    )
