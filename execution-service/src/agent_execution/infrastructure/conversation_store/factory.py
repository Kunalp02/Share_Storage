from __future__ import annotations

from agent_execution.infrastructure.conversation_store.memory_store import InMemoryConversationHistoryStore
from agent_execution.infrastructure.conversation_store.postgres_store import PostgresConversationHistoryStore
from agent_execution.infrastructure.persistence.database import Database


def create_conversation_history_store(database: Database | None):
    if database is None:
        return InMemoryConversationHistoryStore()
    return PostgresConversationHistoryStore(database)
