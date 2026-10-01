from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket

from agent_execution.infrastructure.persistence.run_repository import RunRepository
from agent_execution.services.agent_execution_service import AgentExecutionService
from agent_execution.services.cleanup_service import CleanupService
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)
_NOTIFY_CHANNEL = "execution_runs"


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
        self._capacity = max(1, settings.max_inflight_runs)
        self._inflight: set[asyncio.Task] = set()
        self._wake = asyncio.Event()

    async def run_forever(self) -> None:
        logger.info(
            "Execution worker %s started. It runs up to %s background jobs, retries temporary failures, and expires threads.",
            self._worker_id,
            self._capacity,
        )
        presence = asyncio.create_task(self._presence_loop())
        housekeeping = asyncio.create_task(self._housekeeping_loop())
        listener = asyncio.create_task(self._listen())
        try:
            while True:
                await self._fill()
                await self._wait_for_work()
        finally:
            for task in (presence, housekeeping, listener):
                task.cancel()
            for task in self._inflight:
                task.cancel()
            await asyncio.gather(presence, housekeeping, listener, *self._inflight, return_exceptions=True)

    async def _fill(self) -> None:
        while len(self._inflight) < self._capacity:
            claimed = await self._runs.claim_next(self._worker_id, self._settings.run_lease_seconds)
            if claimed is None:
                return
            task = asyncio.create_task(self._run_one(claimed))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _run_one(self, claimed) -> None:
        try:
            await self._execution.execute_claimed(claimed, self._worker_id)
        except Exception:
            logger.exception("Background run %s crashed outside the run handler", claimed["run_id"])
        self._wake.set()

    async def _wait_for_work(self) -> None:
        inflight = set(self._inflight)
        if len(inflight) >= self._capacity:
            await asyncio.wait(inflight, return_when=asyncio.FIRST_COMPLETED)
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=self._settings.worker_poll_seconds)
        except TimeoutError:
            return
        finally:
            self._wake.clear()

    async def _presence_loop(self) -> None:
        while True:
            try:
                await self._runs.touch_worker(self._worker_id)
                failed = await self._cleanup.fail_expired_sync_runs()
                if failed:
                    logger.info("Marked %s interrupted sync run(s) as failed", failed)
                abandoned = await self._runs.fail_abandoned_async()
                if abandoned:
                    logger.info("Marked %s abandoned background run(s) as failed", abandoned)
            except Exception:
                logger.exception("Worker presence update failed")
            await asyncio.sleep(max(5.0, self._settings.worker_poll_seconds))

    async def _housekeeping_loop(self) -> None:
        while True:
            try:
                expired = await self._cleanup.expire_batch()
                if expired:
                    logger.info("Expired %s thread(s)", expired)
            except Exception:
                logger.exception("Thread cleanup failed")
            await asyncio.sleep(self._settings.cleanup_interval_seconds)

    async def _listen(self) -> None:
        import asyncpg

        while True:
            connection = None
            try:
                connection = await asyncpg.connect(self._settings.database_url())

                def _on_notify(_connection, _pid, _channel, _payload) -> None:
                    self._wake.set()

                await connection.add_listener(_NOTIFY_CHANNEL, _on_notify)
                logger.info("Worker %s is listening for queued runs", self._worker_id)
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run notification listener stopped. Polling continues.")
                await asyncio.sleep(self._settings.worker_poll_seconds)
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
