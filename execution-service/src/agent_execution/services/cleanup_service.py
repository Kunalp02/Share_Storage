from __future__ import annotations

import logging

from agent_execution.infrastructure.conversation_store.postgres_store import PostgresConversationHistoryStore
from agent_execution.infrastructure.persistence.run_repository import RunRepository
from agent_execution.infrastructure.persistence.thread_repository import ThreadRepository
from agent_execution.schemas.threads import ThreadStatus
from agent_execution.services.storage_client import StorageClient

logger = logging.getLogger(__name__)


class CleanupService:
    def __init__(
        self,
        threads: ThreadRepository,
        runs: RunRepository,
        conversations: PostgresConversationHistoryStore,
        storage: StorageClient,
    ) -> None:
        self._threads = threads
        self._runs = runs
        self._conversations = conversations
        self._storage = storage

    async def expire_batch(self) -> int:
        rows = await self._threads.find_expired(limit=50)
        count = 0
        for row in rows:
            thread_id = row["thread_id"]
            try:
                await self._storage.delete_thread_artifacts(thread_id)
            except Exception:
                logger.exception("Storage cleanup failed for thread %s", thread_id)
            await self._conversations.delete_for_thread(row["agent_id"], thread_id)
            await self._threads.mark_status(thread_id, ThreadStatus.EXPIRED.value)
            count += 1
        return count

    async def fail_expired_sync_runs(self) -> int:
        return await self._runs.fail_expired_sync()
