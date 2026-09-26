from __future__ import annotations

from uuid import UUID

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.platform.base_client import BasePlatformClient


class RagAskClient(BasePlatformClient):
    async def ask(self, kb_id: UUID, question: str, bearer_token: str | None) -> dict:
        token = await self._resolve_token(bearer_token)
        response = await self._http.post(
            "/ask",
            params={"kb": str(kb_id)},
            headers={**self._headers_for(token), "Content-Type": "application/json"},
            json={"question": question},
        )
        if response.status_code >= 400:
            raise ServiceError(
                "TOOL_ERROR",
                f"RAG ask failed ({response.status_code}): {response.text[:300]}",
                response.status_code,
            )
        return response.json()
