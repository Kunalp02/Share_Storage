from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID


class ModelCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, ttl_seconds)
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, model_id: UUID) -> dict[str, Any] | None:
        entry = self._entries.get(str(model_id))
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() > expires_at:
            del self._entries[str(model_id)]
            return None
        return payload

    def set(self, model_id: UUID, payload: dict[str, Any]) -> None:
        self._entries[str(model_id)] = (time.monotonic() + self._ttl, payload)

    async def get_or_fetch(
        self,
        model_id: UUID,
        bearer_token: str | None,
        fetch: Callable[[UUID, str | None], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        cached = self.get(model_id)
        if cached is not None:
            return cached
        payload = await fetch(model_id, bearer_token)
        self.set(model_id, payload)
        return payload
