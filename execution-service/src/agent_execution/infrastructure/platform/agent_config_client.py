from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_execution.infrastructure.platform.base_client import BasePlatformClient


class AgentConfigClient(BasePlatformClient):
    async def get_agent(self, agent_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/agents/{agent_id}", bearer_token)

    async def get_runtime_manifest(self, agent_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/agents/{agent_id}/runtime-manifest", bearer_token)

    async def get_revision_manifest(
        self, agent_id: UUID, revision_id: UUID, bearer_token: str | None
    ) -> dict[str, Any]:
        return await self._get_json(
            f"/api/v1/agents/{agent_id}/revisions/{revision_id}/runtime-manifest",
            bearer_token,
        )

    async def get_current_published_manifest(self, agent_id: UUID, bearer_token: str | None) -> dict[str, Any]:
        return await self._get_json(
            f"/api/v1/agents/{agent_id}/revisions/current/runtime-manifest",
            bearer_token,
        )
