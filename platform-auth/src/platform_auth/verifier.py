from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass

import httpx

from platform_auth.principal import PlatformPrincipal, parse_codes

logger = logging.getLogger(__name__)

_NAME_URI = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
_NAME_ID_URI = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
_ROLE_URI = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"

_USERNAME_CLAIMS = ("unique_name", "preferred_username", "username", "name", "tokenkey", _NAME_URI)
_SUBJECT_CLAIMS = ("sub", "nameid", "userid", "user_id", _NAME_ID_URI)
_PERMISSION_CLAIMS = ("roles", "role", "permissions", "category", _ROLE_URI)


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
    """Read the caller from the platform JWT instead of GET /api/v1/auth/me."""

    def __init__(
        self,
        *,
        configured: bool = True,
        me_path: str = "/api/v1/auth/me",
        cache_ttl_seconds: int = 0,
        required_permissions: tuple[str, ...] = (),
        base_url: str = "",
        verify_ssl: bool = True,
        timeout_seconds: float = 10.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        del configured, me_path, base_url, verify_ssl, timeout_seconds
        self._cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._required_permissions = required_permissions
        self._owns_http = http is None
        self._http = http
        self._cache: dict[str, _CacheEntry] = {}

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def authenticate(self, authorization: str | None) -> PlatformPrincipal:
        token = _bearer(authorization)
        if not token:
            raise AuthError("UNAUTHORIZED", "Authorization bearer token is required.", 401)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        cached = self._cached(digest)
        if cached is not None:
            return cached
        principal = _principal_from_token(token)
        if not principal.has_all(self._required_permissions):
            logger.info("auth.forbidden user=%s", principal.username or principal.subject or principal.user_id)
            raise AuthError("FORBIDDEN", "Caller is missing a required platform permission.", 403)
        logger.info("auth.accepted user=%s", principal.username or principal.subject or principal.user_id)
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


def _bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    value = authorization.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def _principal_from_token(token: str) -> PlatformPrincipal:
    claims = _claims(token)
    _reject_if_expired(claims)
    username = _first(claims, _USERNAME_CLAIMS)
    subject = _first(claims, _SUBJECT_CLAIMS)
    user_id = _first(claims, ("userid", "user_id", "nameid", "sub", _NAME_ID_URI)) or subject
    permissions = ()
    for key in _PERMISSION_CLAIMS:
        permissions = parse_codes(_claim(claims, key))
        if permissions:
            break
    return PlatformPrincipal(
        token=token,
        subject=subject,
        username=username,
        user_id=user_id,
        groups=parse_codes(_claim(claims, "groups")),
        permissions=permissions,
    )


def _claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        raise AuthError("UNAUTHORIZED", "Platform token could not be read.", 401)
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError) as exc:
        raise AuthError("UNAUTHORIZED", "Platform token could not be read.", 401) from exc
    if not isinstance(payload, dict):
        raise AuthError("UNAUTHORIZED", "Platform token could not be read.", 401)
    return payload


def _reject_if_expired(claims: dict) -> None:
    raw = _claim(claims, "exp")
    if raw in (None, ""):
        return
    try:
        expires_at = float(raw)
    except (TypeError, ValueError):
        return
    if expires_at <= time.time():
        raise AuthError("UNAUTHORIZED", "Platform token has expired.", 401)


def _claim(claims: dict, name: str):
    for key, value in claims.items():
        if str(key).lower() == name.lower():
            return value
    return None


def _first(claims: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = _claim(claims, name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
