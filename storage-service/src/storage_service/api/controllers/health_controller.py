from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from storage_service.api.controller import ApiController
from storage_service.api.dependencies import get_artifact_service
from storage_service.application.artifact_service import ArtifactService
from storage_service.core.exceptions import ServiceError
from storage_service.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class HealthController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.get("/health/live", tags=["health"])(self.live)
        router.get("/health/ready", tags=["health"])(self.ready)

    async def live(self, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
        return {"status": "ok", "service": settings.app_name}

    async def ready(self, service: Annotated[ArtifactService, Depends(get_artifact_service)]) -> dict:
        try:
            await service.ping()
        except Exception as exc:
            logger.exception("readiness.failed")
            raise ServiceError("NOT_READY", "Database is unavailable.", 503) from exc
        return {"status": "ok"}
