from __future__ import annotations

from fastapi import APIRouter

from agent_execution.api.controllers.deployment_controller import DeploymentController
from agent_execution.api.controllers.health_controller import HealthController
from agent_execution.api.controllers.invoke_controller import InvokeController
from agent_execution.api.controllers.run_controller import RunController
from agent_execution.api.controllers.thread_controller import ThreadController


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    HealthController(router)
    ThreadController(router)
    RunController(router)
    DeploymentController(router)
    InvokeController(router)
    return router
