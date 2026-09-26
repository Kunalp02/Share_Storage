from __future__ import annotations

import asyncio
import logging
import os
import socket

from agent_execution.infrastructure.persistence.run_repository import RunRepository
from agent_execution.services.agent_execution_service import AgentExecutionService
from agent_execution.services.cleanup_service import CleanupService
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


class ExecutionWorker:
    def __init__(
        self,
        settings: Settings,
        runs: RunRepository,
        execution: AgentExecutionService,
        cleanup: CleanupService,
    ) -> None:
        self._settings = settings
        self._runs = runs
        self._execution = execution
        self._cleanup = cleanup
        self._worker_id = settings.worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self._last_cleanup = 0.0

    async def run_forever(self) -> None:
        logger.info("Execution worker %s started", self._worker_id)
        while True:
            try:
                failed = await self._cleanup.fail_expired_sync_runs()
                if failed:
                    logger.info("Marked %s interrupted sync run(s) as failed", failed)
                claimed = await self._runs.claim_next(self._worker_id, self._settings.run_lease_seconds)
                if claimed is not None:
                    await self._execution.execute_claimed(claimed, self._worker_id)
                    continue
                await self._maybe_cleanup()
            except Exception:
                logger.exception("Worker iteration failed")
            await asyncio.sleep(self._settings.worker_poll_seconds)

    async def _maybe_cleanup(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_cleanup < self._settings.cleanup_interval_seconds:
            return
        self._last_cleanup = now
        expired = await self._cleanup.expire_batch()
        if expired:
            logger.info("Expired %s thread(s)", expired)
