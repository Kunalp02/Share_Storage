from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from agent_execution.schemas.runtime import AgentMemoryScope, MemoryConfig
from agent_execution.services.conversation_models import MemoryContext


@dataclass(frozen=True, slots=True)
class ConversationSessionKey:
    agent_id: UUID
    session_id: str
    org_id: str

    @classmethod
    def from_context(cls, agent_id: UUID, memory: MemoryConfig, context: MemoryContext) -> ConversationSessionKey:
        scope = memory.scope or AgentMemoryScope.SESSION
        if scope == AgentMemoryScope.ORGANIZATION:
            return cls(agent_id, context.session_id or "", context.org_id or "")
        if scope == AgentMemoryScope.AGENT:
            return cls(agent_id, "__agent__", "")
        if scope == AgentMemoryScope.USER:
            return cls(agent_id, context.session_id or "__user__", "")
        return cls(agent_id, context.session_id or "", "")
