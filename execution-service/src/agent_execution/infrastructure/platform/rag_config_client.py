from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.platform.base_client import BasePlatformClient


class RagConfigClient(BasePlatformClient):
    async def retrieve(
        self,
        kb_id: UUID,
        query: str,
        bearer_token: str | None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            data = await self._post_json(
                f"/api/v1/knowledge-bases/{kb_id}/retrieve",
                bearer_token,
                {"query": query, "topK": top_k},
            )
        except ServiceError:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            chunks = data.get("chunks") or data.get("items") or data.get("results") or []
            return chunks if isinstance(chunks, list) else []
        return []
