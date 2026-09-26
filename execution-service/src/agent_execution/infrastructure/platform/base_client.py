from __future__ import annotations

from typing import Any, TYPE_CHECKING

import httpx

from agent_execution.core.exceptions import ServiceError

if TYPE_CHECKING:
    from agent_execution.infrastructure.auth.service_token_provider import ServiceAuthTokenProvider


class BasePlatformClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        token_provider: ServiceAuthTokenProvider | None = None,
        *,
        verify_ssl: bool = True,
    ) -> None:
        self._http = http
        self._token_provider = token_provider
        self._verify_ssl = verify_ssl

    async def _resolve_token(self, bearer_token: str | None) -> str | None:
        if bearer_token:
            return bearer_token
        if self._token_provider is not None:
            return await self._token_provider.get_token()
        return None

    @staticmethod
    def _headers_for(token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get_json(self, path: str, bearer_token: str | None) -> Any:
        token = await self._resolve_token(bearer_token)
        response = await self._http.get(path, headers=self._headers_for(token))
        if response.status_code == 404:
            raise ServiceError("NOT_FOUND", f"Resource not found: {path}", 404)
        if response.status_code in (401, 403):
            raise ServiceError("FORBIDDEN", "Access denied by upstream service.", response.status_code)
        if response.status_code >= 400:
            raise ServiceError(
                "UPSTREAM_ERROR",
                f"GET {path} failed ({response.status_code}): {response.text[:300]}",
                response.status_code,
            )
        return response.json()

    async def _post_json(self, path: str, bearer_token: str | None, payload: dict[str, Any] | None = None) -> Any:
        token = await self._resolve_token(bearer_token)
        response = await self._http.post(
            path,
            headers={**self._headers_for(token), "Content-Type": "application/json"},
            json=payload or {},
        )
        if response.status_code >= 400:
            raise ServiceError(
                "UPSTREAM_ERROR",
                f"POST {path} failed ({response.status_code}): {response.text[:300]}",
                response.status_code,
            )
        if response.status_code == 204:
            return None
        return response.json()
