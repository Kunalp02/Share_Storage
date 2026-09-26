from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from storage_service.api.controller import ApiController
from storage_service.api.dependencies import get_artifact_service
from storage_service.api.schemas import InternalTextRequest
from storage_service.application.artifact_service import ArtifactService
from storage_service.infrastructure.auth import require_internal_key
from storage_service.settings import Settings, get_settings


class InternalController(ApiController):
    def register(self, router: APIRouter) -> None:
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
