from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from agent_execution.settings import Settings, get_settings


class HealthController:
    def __init__(self, router: APIRouter) -> None:
        router.get("/health/live", tags=["health"])(self.live)

    async def live(self, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "runtime": "langgraph",
            "maxInflightRuns": settings.max_inflight_runs,
        }
