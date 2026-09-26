from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass

import httpx

from agent_execution.core.exceptions import ServiceError
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CachedToken:
    token: str
    expires_at: float


class ServiceAuthTokenProvider:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._cached: _CachedToken | None = None
        self._lock = asyncio.Lock()

    def _is_configured(self) -> bool:
        return bool(self._settings.auth_service_username and self._settings.auth_service_password)

    async def get_token(self) -> str | None:
        if not self._is_configured():
            return None
        if self._still_valid(self._cached):
            return self._cached.token  # type: ignore[union-attr]
        async with self._lock:
            if self._still_valid(self._cached):
                return self._cached.token  # type: ignore[union-attr]
            return await self._login()

    def _still_valid(self, cached: _CachedToken | None) -> bool:
        if cached is None:
            return False
        return cached.expires_at - self._settings.auth_token_refresh_margin_seconds > time.time()

    async def _login(self) -> str:
        try:
            response = await self._http.post(
                "/api/v1/auth/login",
                json={
                    "username": self._settings.auth_service_username,
                    "password": self._settings.auth_service_password,
                },
            )
        except httpx.HTTPError as exc:
            raise ServiceError("AUTH_UNAVAILABLE", f"Auth service unreachable: {exc}", 503) from exc
        if response.status_code >= 400:
            raise ServiceError(
                "AUTH_FAILED",
                f"Service login failed ({response.status_code}): {response.text[:300]}",
                502,
            )
        data = response.json()
        token = data.get("accessToken")
        if not token:
            raise ServiceError("AUTH_FAILED", "Auth service response had no accessToken.", 502)
        self._cached = _CachedToken(token=token, expires_at=self._resolve_expiry(token, data.get("expiresIn")))
        return token

    @staticmethod
    def _resolve_expiry(token: str, expires_in: float | int | None) -> float:
        if expires_in:
            if expires_in > time.time():
                return float(expires_in)
            if 0 < expires_in < 10**7:
                return time.time() + float(expires_in)
        exp_from_jwt = ServiceAuthTokenProvider._exp_from_jwt(token)
        if exp_from_jwt:
            return exp_from_jwt
        return time.time() + 900

    @staticmethod
    def _exp_from_jwt(token: str) -> float | None:
        try:
            payload_b64 = token.split(".")[1]
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            exp = payload.get("exp")
            return float(exp) if exp else None
        except Exception:
            return None

    def invalidate(self) -> None:
        self._cached = None
