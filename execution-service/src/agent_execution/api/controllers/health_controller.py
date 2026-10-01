from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from platform_auth import PlatformPrincipal

from agent_execution.api.controller import ApiController
from agent_execution.api.dependencies import get_app_container, get_platform_principal
from agent_execution.core.container import ApplicationContainer
from agent_execution.core.exceptions import ServiceError
from agent_execution.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class HealthController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.get("/health/live", tags=["health"])(self.live)
        router.get("/health/ready", tags=["health"])(self.ready)
        router.get("/workers", tags=["health"])(self.workers)

    async def live(self, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "runtime": "langgraph",
            "maxInflightRuns": settings.max_inflight_runs,
        }

    async def ready(self, container: Annotated[ApplicationContainer, Depends(get_app_container)]) -> dict:
        try:
            await container.database.ping()
        except Exception as exc:
            logger.exception("readiness.failed")
            raise ServiceError("NOT_READY", "Database is unavailable.", 503) from exc
        return {"status": "ok"}

    async def workers(
        self,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ) -> list[dict]:
        del principal
        settings = container.settings
        stale_after = max(15.0, settings.worker_poll_seconds * 3)
        now = datetime.now(timezone.utc)
        rows = await container.runs.list_workers()
        workers = []
        for row in rows:
            seen = row["last_seen_at"]
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            workers.append(
                {
                    "workerId": row["worker_id"],
                    "lastSeenAt": seen,
                    "startedAt": row["started_at"],
                    "alive": (now - seen).total_seconds() <= stale_after,
                }
            )
        return workers
