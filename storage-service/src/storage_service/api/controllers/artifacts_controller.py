from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from storage_service.api.controller import ApiController
from storage_service.api.dependencies import get_artifact_service, get_bearer_token
from storage_service.api.schemas import CompleteArtifactRequest, InitArtifactRequest
from storage_service.application.artifact_service import ArtifactService
from storage_service.core.exceptions import ServiceError
from storage_service.domain.enums import ArtifactType


class ArtifactsController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.post("/agents/{agent_id}/artifacts/init", tags=["artifacts"])(self.init_upload_for_agent)
        router.post("/threads/{thread_id}/artifacts/init", tags=["artifacts"])(self.init_upload_for_thread)
        router.post("/executions/{thread_id}/artifacts/init", tags=["artifacts"])(self.init_upload_for_thread)
        router.post("/artifacts/{artifact_id}/complete", tags=["artifacts"])(self.complete)
        router.get("/artifacts/{artifact_id}", tags=["artifacts"])(self.get_one)
        router.get("/threads/{thread_id}/artifacts", tags=["artifacts"])(self.list_for_thread)
        router.get("/executions/{thread_id}/artifacts", tags=["artifacts"])(self.list_for_thread)

    async def init_upload_for_agent(
        self,
        agent_id: UUID,
        body: InitArtifactRequest,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> dict:
        if body.agent_id and body.agent_id != agent_id:
            raise ServiceError("VALIDATION_FAILED", "agentId in body must match path.", 400)
        return await service.init_upload(
            agent_id=agent_id,
            artifact_type=body.artifact_type,
            filename=body.filename,
            content_type=body.content_type,
            bearer_token=token,
            thread_id=body.resolved_thread_id(),
            run_id=body.run_id,
            mode=body.mode.value,
        )

    async def init_upload_for_thread(
        self,
        thread_id: UUID,
        body: InitArtifactRequest,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> dict:
        if not body.agent_id:
            raise ServiceError("VALIDATION_FAILED", "agentId is required.", 400)
        return await service.init_upload(
            agent_id=body.agent_id,
            artifact_type=body.artifact_type,
            filename=body.filename,
            content_type=body.content_type,
            bearer_token=token,
            thread_id=thread_id,
            run_id=body.run_id,
            mode=body.mode.value,
        )

    async def complete(
        self,
        artifact_id: UUID,
        body: CompleteArtifactRequest,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> dict:
        return await service.complete_upload(
            artifact_id,
            size_bytes=body.size_bytes,
            checksum_sha256=body.checksum_sha256,
            bearer_token=token,
        )

    async def get_one(
        self,
        artifact_id: UUID,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> dict:
        return await service.get_artifact(artifact_id, bearer_token=token)

    async def list_for_thread(
        self,
        thread_id: UUID,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        token: Annotated[str, Depends(get_bearer_token)],
        artifact_type: ArtifactType | None = None,
        agent_id: UUID | None = None,
    ) -> list[dict]:
        return await service.list_artifacts(
            thread_id,
            artifact_type=artifact_type,
            bearer_token=token,
            agent_id=agent_id,
        )
