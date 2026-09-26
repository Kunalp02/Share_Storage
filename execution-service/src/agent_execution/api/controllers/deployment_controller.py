from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from agent_execution.api.dependencies import get_bearer_token, get_deployment_service
from agent_execution.schemas.runs import CreateDeploymentRequest, DeploymentResponse
from agent_execution.services.deployment_service import DeploymentService


class DeploymentController:
    def __init__(self, router: APIRouter) -> None:
        router.post(
            "/agents/{agent_id}/deployments",
            response_model=DeploymentResponse,
            tags=["deployments"],
        )(self.create)
        router.get(
            "/agents/{agent_id}/deployments",
            response_model=list[DeploymentResponse],
            tags=["deployments"],
        )(self.list_deployments)

    async def create(
        self,
        agent_id: UUID,
        body: CreateDeploymentRequest,
        service: Annotated[DeploymentService, Depends(get_deployment_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> DeploymentResponse:
        return await service.create(agent_id, body, token)

    async def list_deployments(
        self,
        agent_id: UUID,
        service: Annotated[DeploymentService, Depends(get_deployment_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> list[DeploymentResponse]:
        return await service.list(agent_id, token)
