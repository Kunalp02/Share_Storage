from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agent_execution.core.exceptions import ServiceError
from agent_execution.settings import Settings


class RunSlots:
    def __init__(self, settings: Settings) -> None:
        self._sem = asyncio.Semaphore(max(1, settings.max_inflight_runs))
        self._timeout = settings.run_slot_wait_seconds

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except TimeoutError as exc:
            raise ServiceError(
                "BUSY",
                "Too many runs are in progress. Retry shortly.",
                429,
            ) from exc
        try:
            yield
        finally:
            self._sem.release()
