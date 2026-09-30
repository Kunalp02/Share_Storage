from __future__ import annotations

from datetime import datetime
from typing import Protocol

from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.services.conversation_models import ConversationHistory


class ConversationHistoryStore(Protocol):
    async def get_history(self, key: ConversationSessionKey) -> tuple[ConversationHistory, int | None]: ...

    async def append_exchange(
        self,
        key: ConversationSessionKey,
        user_text: str,
        assistant_text: str,
        *,
        max_turn_pairs: int,
        max_chars: int,
        expected_version: int | None = None,
    ) -> tuple[ConversationHistory, int, bool]: ...

    async def set_retention(self, key: ConversationSessionKey, expires_at: datetime | None) -> None: ...

    async def delete_expired(self) -> int: ...

    async def aclose(self) -> None: ...
