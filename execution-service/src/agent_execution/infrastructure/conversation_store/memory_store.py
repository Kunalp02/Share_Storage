from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.services.conversation_models import ConversationHistory


class ConversationVersionConflict(Exception):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"conversation version conflict (current={current_version})")


@dataclass
class _StoredSession:
    history: ConversationHistory = field(default_factory=ConversationHistory)
    version: int = 0
    expires_at: datetime | None = None


class InMemoryConversationHistoryStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _StoredSession] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(key: ConversationSessionKey) -> str:
        return f"{key.agent_id}:{key.session_id}:{key.org_id}"

    async def get_history(self, key: ConversationSessionKey) -> tuple[ConversationHistory, int | None]:
        stored = self._sessions.get(self._key(key))
        if stored is None or _expired(stored.expires_at):
            return ConversationHistory(), None
        return ConversationHistory(turns=list(stored.history.turns)), stored.version or None

    async def append_exchange(
        self,
        key: ConversationSessionKey,
        user_text: str,
        assistant_text: str,
        *,
        max_turn_pairs: int,
        max_chars: int,
        expected_version: int | None = None,
    ) -> tuple[ConversationHistory, int, bool]:
        async with self._lock:
            storage_key = self._key(key)
            stored = self._sessions.get(storage_key)
            if stored is None:
                stored = _StoredSession()
                self._sessions[storage_key] = stored
            if expected_version is not None and stored.version != expected_version:
                raise ConversationVersionConflict(stored.version)
            stored.history.append_exchange(user_text, assistant_text)
            trimmed, truncated = stored.history.trim(max_turn_pairs, max_chars)
            stored.history = trimmed
            stored.version += 1
            return ConversationHistory(turns=list(trimmed.turns)), stored.version, truncated

    async def set_retention(self, key: ConversationSessionKey, expires_at: datetime | None) -> None:
        stored = self._sessions.get(self._key(key))
        if stored is not None:
            stored.expires_at = expires_at

    async def delete_expired(self) -> int:
        expired = [key for key, stored in self._sessions.items() if _expired(stored.expires_at)]
        for key in expired:
            del self._sessions[key]
        return len(expired)

    async def aclose(self) -> None:
        return None


def _expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)
