from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from agent_execution.services.conversation_models import ConversationHistory


@dataclass(frozen=True, slots=True)
class MemoryCacheKey:
    agent_id: UUID
    session_id: str | None
    org_id: str | None


@dataclass
class MemoryCacheEntry:
    history: ConversationHistory
    version: int | None


class MemoryCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, ttl_seconds)
        self._entries: dict[MemoryCacheKey, tuple[float, MemoryCacheEntry]] = {}

    def get(self, key: MemoryCacheKey) -> MemoryCacheEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: MemoryCacheKey, history: ConversationHistory, version: int | None) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, MemoryCacheEntry(history, version))

    def invalidate(self, key: MemoryCacheKey) -> None:
        self._entries.pop(key, None)
