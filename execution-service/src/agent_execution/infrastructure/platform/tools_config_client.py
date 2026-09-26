from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.platform.base_client import BasePlatformClient


class ToolsConfigClient(BasePlatformClient):
    async def get_model(self, model_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/model-registry/{model_id}", bearer_token)

    async def get_remote_tool(self, tool_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/remote-tools/{tool_id}", bearer_token)

    async def get_local_tool(self, tool_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/local-tools/{tool_id}", bearer_token)

    async def invoke_tool(self, invoke_url: str, bearer_token: str | None, payload: dict[str, Any]) -> Any:
        token = await self._resolve_token(bearer_token)
        async with httpx.AsyncClient(timeout=self._http.timeout, verify=self._verify_ssl) as client:
            response = await client.post(
                invoke_url,
                headers={**self._headers_for(token), "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise ServiceError(
                "TOOL_ERROR",
                f"Tool invoke failed ({response.status_code}): {response.text[:300]}",
                response.status_code,
            )
        try:
            return response.json()
        except Exception:
            return {"text": response.text}
