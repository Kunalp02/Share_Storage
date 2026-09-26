from __future__ import annotations

import logging

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.conversation_store.base import ConversationHistoryStore
from agent_execution.infrastructure.conversation_store.memory_store import ConversationVersionConflict
from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.schemas.runtime import AgentMemoryScope, MemoryConfig
from agent_execution.services.conversation_models import ConversationHistory, MemoryContext
from agent_execution.services.memory_cache import MemoryCache, MemoryCacheKey
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


class ConversationMemoryService:
    def __init__(self, settings: Settings, store: ConversationHistoryStore) -> None:
        self._settings = settings
        self._store = store
        self._cache = MemoryCache(settings.memory_cache_ttl_seconds)

    @staticmethod
    def _cache_key(session_key: ConversationSessionKey) -> MemoryCacheKey:
        return MemoryCacheKey(
            agent_id=session_key.agent_id,
            session_id=session_key.session_id or None,
            org_id=session_key.org_id or None,
        )

    def validate_context(self, memory: MemoryConfig, context: MemoryContext) -> None:
        if not memory.enabled or memory.scope is None:
            return
        if memory.scope == AgentMemoryScope.SESSION and not context.session_id:
            raise ServiceError("MEMORY_CONTEXT_REQUIRED", "session_id is required for session memory.", 400)
        if memory.scope == AgentMemoryScope.ORGANIZATION and not context.org_id:
            raise ServiceError("MEMORY_CONTEXT_REQUIRED", "org_id is required for organization memory.", 400)

    async def load_history(self, agent_id, memory: MemoryConfig, context: MemoryContext) -> ConversationHistory:
        if not memory.enabled:
            return ConversationHistory()
        session_key = ConversationSessionKey.from_context(agent_id, memory, context)
        cache_key = self._cache_key(session_key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.history
        history, version = await self._store.get_history(session_key)
        self._cache.set(cache_key, history, version)
        return history

    async def append_exchange(
        self,
        agent_id,
        memory: MemoryConfig,
        context: MemoryContext,
        user_text: str,
        assistant_text: str,
        *,
        _allow_retry: bool = True,
    ) -> bool:
        if not memory.enabled:
            return False
        session_key = ConversationSessionKey.from_context(agent_id, memory, context)
        cache_key = self._cache_key(session_key)
        cached = self._cache.get(cache_key)
        expected_version = cached.version if cached else None
        try:
            history, version, _ = await self._store.append_exchange(
                session_key,
                user_text,
                assistant_text,
                max_turn_pairs=self._settings.conversation_max_turn_pairs,
                max_chars=self._settings.conversation_max_chars,
                expected_version=expected_version,
            )
        except ConversationVersionConflict:
            if not _allow_retry:
                logger.warning("Conversation version conflict for agent %s", agent_id)
                return False
            self._cache.invalidate(cache_key)
            history, version = await self._store.get_history(session_key)
            self._cache.set(cache_key, history, version)
            return await self.append_exchange(
                agent_id, memory, context, user_text, assistant_text, _allow_retry=False
            )
        self._cache.set(cache_key, history, version)
        return True

    async def append_exchange_safe(self, agent_id, memory, context, user_text, assistant_text) -> bool:
        try:
            return await self.append_exchange(agent_id, memory, context, user_text, assistant_text)
        except Exception:
            logger.exception("Conversation history append failed for agent %s", agent_id)
            return False

    def history_for_prompt(self, history: ConversationHistory) -> tuple[str | None, ConversationHistory, bool]:
        trimmed, truncated = history.trim(
            self._settings.conversation_max_turn_pairs,
            self._settings.conversation_max_chars,
        )
        if not trimmed.turns:
            return None, trimmed, truncated
        lines = [f"{'User' if turn.role == 'user' else 'Assistant'}: {turn.content}" for turn in trimmed.turns]
        return "Previous conversation (most recent last):\n" + "\n".join(lines), trimmed, truncated

    @staticmethod
    def optional_instructions_block(memory: MemoryConfig) -> str | None:
        if not memory.instructions or not memory.instructions.strip():
            return None
        return f"Memory behavior notes:\n{memory.instructions.strip()}"

    async def aclose(self) -> None:
        await self._store.aclose()
