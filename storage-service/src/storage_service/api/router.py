from __future__ import annotations

from fastapi import APIRouter

from storage_service.api.controllers.artifacts_controller import ArtifactsController
from storage_service.api.controllers.health_controller import HealthController
from storage_service.api.controllers.internal_controller import InternalController


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    HealthController(router)
    ArtifactsController(router)
    InternalController(router)
    return router
