from __future__ import annotations

from uuid import UUID

import httpx

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.platform.base_client import BasePlatformClient


class RagAskClient(BasePlatformClient):
    async def ask(self, kb_id: UUID, question: str, bearer_token: str | None) -> dict:
        token = await self._resolve_token(bearer_token)
        try:
            response = await self._http.post(
                "/ask",
                params={"kb": str(kb_id)},
                headers={**self._headers_for(token), "Content-Type": "application/json"},
                json={"question": question},
            )
        except httpx.HTTPError as exc:
            raise ServiceError("RAG_UNAVAILABLE", "RAG ask service is unreachable.", 503) from exc
        if response.status_code >= 400:
            raise ServiceError(
                "RAG_UNAVAILABLE",
                f"RAG ask failed ({response.status_code}).",
                503,
            )
        return response.json()
