from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from storage_service.application.artifact_service import ArtifactService
from storage_service.core.container import get_artifact_service_dep
from storage_service.core.exceptions import ServiceError
from storage_service.domain.enums import ArtifactType
from storage_service.domain.execution_mode import ExecutionMode
from storage_service.infrastructure.auth import require_internal_key
from storage_service.settings import Settings, get_settings


def get_artifact_service(settings: Annotated[Settings, Depends(get_settings)]) -> ArtifactService:
    return get_artifact_service_dep(settings)


class InitArtifactRequest(BaseModel):
    agent_id: UUID | None = Field(default=None, alias="agentId")
    thread_id: UUID | None = Field(default=None, alias="threadId")
    execution_id: UUID | None = Field(default=None, alias="executionId")
    run_id: UUID | None = Field(default=None, alias="runId")
    mode: ExecutionMode = ExecutionMode.TEST
    artifact_type: ArtifactType = Field(alias="artifactType")
    filename: str
    content_type: str = Field(default="application/octet-stream", alias="contentType")

    model_config = {"populate_by_name": True}

    def resolved_thread_id(self) -> UUID | None:
        return self.thread_id or self.execution_id


class CompleteArtifactRequest(BaseModel):
    size_bytes: int | None = Field(default=None, alias="sizeBytes")
    checksum_sha256: str | None = Field(default=None, alias="checksumSha256")

    model_config = {"populate_by_name": True}


class InternalTextRequest(BaseModel):
    agent_id: UUID = Field(alias="agentId")
    run_id: UUID | None = Field(default=None, alias="runId")
    filename: str
    content_type: str = Field(default="text/plain", alias="contentType")
    text: str
    artifact_type: ArtifactType = Field(default=ArtifactType.OUTPUT, alias="artifactType")
    expires_at: str | None = Field(default=None, alias="expiresAt")

    model_config = {"populate_by_name": True}


def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def register_exception_handlers(app) -> None:
    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": str(exc)})


class HealthController:
    def __init__(self, router: APIRouter) -> None:
        router.get("/health/live", tags=["health"])(self.live)

    async def live(self, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
        return {"status": "ok", "service": settings.app_name}


class ArtifactsController:
    def __init__(self, router: APIRouter) -> None:
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
        request: Request,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
    ) -> dict:
        if body.agent_id and body.agent_id != agent_id:
            raise ServiceError("VALIDATION_FAILED", "agentId in body must match path.", 400)
        return await service.init_upload(
            agent_id=agent_id,
            artifact_type=body.artifact_type,
            filename=body.filename,
            content_type=body.content_type,
            bearer_token=_bearer(request),
            thread_id=body.resolved_thread_id(),
            run_id=body.run_id,
            mode=body.mode.value,
        )

    async def init_upload_for_thread(
        self,
        thread_id: UUID,
        body: InitArtifactRequest,
        request: Request,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
    ) -> dict:
        if not body.agent_id:
            raise ServiceError("VALIDATION_FAILED", "agentId is required.", 400)
        return await service.init_upload(
            agent_id=body.agent_id,
            artifact_type=body.artifact_type,
            filename=body.filename,
            content_type=body.content_type,
            bearer_token=_bearer(request),
            thread_id=thread_id,
            run_id=body.run_id,
            mode=body.mode.value,
        )

    async def complete(
        self,
        artifact_id: UUID,
        body: CompleteArtifactRequest,
        request: Request,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
    ) -> dict:
        return await service.complete_upload(
            artifact_id,
            size_bytes=body.size_bytes,
            checksum_sha256=body.checksum_sha256,
            bearer_token=_bearer(request),
        )

    async def get_one(
        self,
        artifact_id: UUID,
        request: Request,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
    ) -> dict:
        return await service.get_artifact(artifact_id, bearer_token=_bearer(request))

    async def list_for_thread(
        self,
        thread_id: UUID,
        request: Request,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        artifact_type: ArtifactType | None = None,
        agent_id: UUID | None = None,
    ) -> list[dict]:
        return await service.list_artifacts(
            thread_id,
            artifact_type=artifact_type,
            bearer_token=_bearer(request),
            agent_id=agent_id,
        )


class InternalController:
    def __init__(self, router: APIRouter) -> None:
        router.delete("/internal/threads/{thread_id}/artifacts", tags=["internal"])(self.delete_thread)
        router.delete("/internal/executions/{thread_id}/artifacts", tags=["internal"])(self.delete_thread)
        router.get("/internal/artifacts/{artifact_id}/content", tags=["internal"])(self.content)
        router.post("/internal/threads/{thread_id}/artifacts", tags=["internal"])(self.store_text)

    async def delete_thread(
        self,
        thread_id: UUID,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        settings: Annotated[Settings, Depends(get_settings)],
        x_internal_api_key: Annotated[str | None, Header()] = None,
    ) -> dict:
        require_internal_key(x_internal_api_key, settings.internal_api_key)
        count = await service.delete_all_for_thread(thread_id)
        return {"threadId": str(thread_id), "executionId": str(thread_id), "deletedCount": count}

    async def content(
        self,
        artifact_id: UUID,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        settings: Annotated[Settings, Depends(get_settings)],
        x_internal_api_key: Annotated[str | None, Header()] = None,
        max_chars: int | None = Query(default=None, alias="maxChars"),
    ) -> dict:
        require_internal_key(x_internal_api_key, settings.internal_api_key)
        return await service.read_text(artifact_id, max_chars)

    async def store_text(
        self,
        thread_id: UUID,
        body: InternalTextRequest,
        service: Annotated[ArtifactService, Depends(get_artifact_service)],
        settings: Annotated[Settings, Depends(get_settings)],
        x_internal_api_key: Annotated[str | None, Header()] = None,
    ) -> dict:
        require_internal_key(x_internal_api_key, settings.internal_api_key)
        return await service.store_text(
            thread_id=thread_id,
            agent_id=body.agent_id,
            run_id=body.run_id,
            filename=body.filename,
            content_type=body.content_type,
            text=body.text,
            artifact_type=body.artifact_type,
            expires_at=body.expires_at,
        )


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    HealthController(router)
    ArtifactsController(router)
    InternalController(router)
    return router
