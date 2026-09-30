from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent_execution.infrastructure.conversation_store.base import ConversationHistoryStore
from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.schemas.runtime import AgentMemoryScope, KnowledgeBaseMode, MemoryConfig, RuntimeManifest
from agent_execution.services.conversation_memory_service import ConversationMemoryService
from agent_execution.services.conversation_models import ConversationHistory, MemoryContext
from agent_execution.services.manifest_service import RagContextService
from agent_execution.services.prompt_composition_service import PromptCompositionService
from agent_execution.services.storage_client import StorageClient
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)

_RAG_FALLBACK = (
    "Knowledge base search is unavailable for this turn. "
    "Answer from the conversation you already have, and tell the user you could not look the knowledge base up."
)


@dataclass
class PreparedContext:
    system_prompt: str
    llm_input: str
    messages: list[dict[str, Any]]
    steps: list[str] = field(default_factory=list)
    history_turns: list[dict[str, str]] = field(default_factory=list)
    memory_scope: str | None = None
    history_total_turns: int = 0
    history_turns_in_prompt: int = 0
    history_truncated: bool = False
    retrieved_context: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""

    def as_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "system_prompt": self.system_prompt,
            "llm_input": self.llm_input,
            "messages": self.messages,
            "history_turns": self.history_turns,
            "memory_scope": self.memory_scope,
            "history_total_turns": self.history_total_turns,
            "history_turns_in_prompt": self.history_turns_in_prompt,
            "history_truncated": self.history_truncated,
            "retrieved_context": self.retrieved_context,
            "steps": list(self.steps),
        }


class ContextManager:
    """Builds one model context and keeps its memory on the same lifetime as the thread."""

    def __init__(
        self,
        settings: Settings,
        memory: ConversationMemoryService,
        store: ConversationHistoryStore,
        rag: RagContextService,
        storage: StorageClient,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._store = store
        self._rag = rag
        self._storage = storage

    @staticmethod
    def thread_memory(memory: MemoryConfig) -> MemoryConfig:
        """Conversation memory is the thread. Its retention is the thread retention policy."""
        if not memory.enabled:
            return memory
        return memory.model_copy(update={"scope": AgentMemoryScope.SESSION, "retention": None})

    async def prepare(
        self,
        *,
        manifest: RuntimeManifest,
        thread: dict[str, Any],
        user_input: str,
        artifact_ids: list[str],
        bearer_token: str | None,
    ) -> PreparedContext:
        session_id = str(thread["thread_id"])
        memory_cfg = self.thread_memory(manifest.memory)
        mem_context = MemoryContext(session_id=session_id, org_id=None)
        steps = ["context.prepare"]
        history = ConversationHistory()
        if memory_cfg.enabled:
            self._memory.validate_context(memory_cfg, mem_context)
            history = await self._memory.load_history(manifest.agent_id, memory_cfg, mem_context)

        artifact_block = await self._artifact_block(artifact_ids)
        kb_blocks, retrieved = await self._knowledge(manifest, user_input, bearer_token, steps)
        instructions = ConversationMemoryService.optional_instructions_block(manifest.memory)
        history_block, history_for_prompt, history_truncated = self._memory.history_for_prompt(history)
        memory_block = _join(instructions, history_block)
        system_prompt, trim_steps = PromptCompositionService.compose_within_budget(
            manifest,
            memory_block,
            kb_blocks,
            artifact_block,
            user_input,
            self._settings.context_input_budget_chars(),
        )
        steps.extend(trim_steps)
        if history_truncated:
            steps.append("context.history_capped")
        return PreparedContext(
            system_prompt=system_prompt,
            llm_input=user_input,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            steps=steps,
            history_turns=[{"role": turn.role, "content": turn.content} for turn in history.turns],
            memory_scope=AgentMemoryScope.SESSION.value if memory_cfg.enabled else None,
            history_total_turns=len(history.turns),
            history_turns_in_prompt=len(history_for_prompt.turns),
            history_truncated=history_truncated or bool(trim_steps),
            retrieved_context=retrieved,
            session_id=session_id,
        )

    async def remember(
        self,
        *,
        manifest: RuntimeManifest,
        thread: dict[str, Any],
        user_input: str,
        assistant_text: str,
    ) -> bool:
        memory_cfg = self.thread_memory(manifest.memory)
        if not self._settings.persist_conversation_memory or not memory_cfg.enabled:
            return False
        session_id = str(thread["thread_id"])
        persisted = await self._memory.append_exchange_safe(
            manifest.agent_id,
            memory_cfg,
            MemoryContext(session_id=session_id, org_id=None),
            user_input,
            assistant_text,
        )
        if not persisted:
            return False
        expires_at = thread.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        await self._store.set_retention(
            ConversationSessionKey(manifest.agent_id, session_id, ""),
            expires_at,
        )
        return True

    async def _knowledge(
        self,
        manifest: RuntimeManifest,
        user_input: str,
        bearer_token: str | None,
        steps: list[str],
    ) -> tuple[list[str], list[dict]]:
        context_kbs = [kb for kb in manifest.knowledge_bases if kb.mode == KnowledgeBaseMode.CONTEXT]
        if not context_kbs:
            return [], []
        try:
            blocks, retrieved = await self._rag.fetch_context(manifest, user_input, bearer_token)
        except Exception:
            logger.exception("Knowledge base lookup failed for agent %s", manifest.agent_id)
            blocks, retrieved = [], []
        for item in retrieved:
            trace = item.get("trace")
            if trace:
                steps.append(str(trace))
        if not blocks:
            steps.append("rag.unavailable")
            return [_RAG_FALLBACK], retrieved
        return blocks, retrieved

    async def _artifact_block(self, artifact_ids: list[str]) -> str | None:
        if not artifact_ids:
            return None
        sections: list[str] = []
        for raw_id in artifact_ids:
            payload = await self._storage.fetch_artifact_text(uuid.UUID(str(raw_id)))
            filename = payload.get("filename") or raw_id
            text = payload.get("text")
            if text:
                truncated = " (truncated)" if payload.get("truncated") else ""
                sections.append(f"File {filename}{truncated}:\n{text}")
            else:
                sections.append(f"File {filename} is attached and is not text.")
        return "Attached files:\n\n" + "\n\n".join(sections)


def _join(*parts: str | None) -> str | None:
    blocks = [part for part in parts if part]
    return "\n\n".join(blocks) if blocks else None
