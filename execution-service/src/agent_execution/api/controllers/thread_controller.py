from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from platform_auth import PlatformPrincipal

from agent_execution.api.controller import ApiController
from agent_execution.api.dependencies import get_platform_principal, get_thread_service
from agent_execution.schemas.threads import (
    Channel,
    CreateThreadRequest,
    ExecutionType,
    ResolveThreadRequest,
    ThreadResponse,
)
from agent_execution.services.thread_service import ThreadService


class ThreadController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.post("/agents/{agent_id}/threads", response_model=ThreadResponse, tags=["threads"])(self.create)
        router.post("/agents/{agent_id}/threads/resolve", response_model=ThreadResponse, tags=["threads"])(self.resolve)
        router.get("/agents/{agent_id}/threads/{thread_id}", response_model=ThreadResponse, tags=["threads"])(self.get)
        router.get("/agents/{agent_id}/threads", response_model=list[ThreadResponse], tags=["threads"])(self.list_threads)
        router.post("/agents/{agent_id}/executions", response_model=ThreadResponse, tags=["threads"])(self.create_legacy)
        router.post("/agents/{agent_id}/executions/resolve", response_model=ThreadResponse, tags=["threads"])(self.resolve)
        router.get("/agents/{agent_id}/executions/{thread_id}", response_model=ThreadResponse, tags=["threads"])(self.get)

    async def create(
        self,
        agent_id: UUID,
        body: CreateThreadRequest,
        service: Annotated[ThreadService, Depends(get_thread_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ) -> ThreadResponse:
        return await service.create(
            agent_id,
            body,
            channel=Channel.STUDIO,
            bearer_token=principal.token,
            triggered_by=principal.username or principal.subject,
        )

    async def create_legacy(
        self,
        agent_id: UUID,
        body: CreateThreadRequest,
        service: Annotated[ThreadService, Depends(get_thread_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ) -> ThreadResponse:
        return await self.create(agent_id, body, service, principal)

    async def resolve(
        self,
        agent_id: UUID,
        body: ResolveThreadRequest,
        service: Annotated[ThreadService, Depends(get_thread_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ) -> ThreadResponse:
        return await service.resolve(
            agent_id,
            body.resolved_thread_id(),
            body.mode,
            principal.token,
            principal.username or principal.subject,
        )

    async def get(
        self,
        agent_id: UUID,
        thread_id: UUID,
        service: Annotated[ThreadService, Depends(get_thread_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ) -> ThreadResponse:
        return await service.get(agent_id, thread_id, principal.token)

    async def list_threads(
        self,
        agent_id: UUID,
        service: Annotated[ThreadService, Depends(get_thread_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
        execution_type: ExecutionType | None = Query(default=None, alias="executionType"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[ThreadResponse]:
        return await service.list(agent_id, execution_type, principal.token, limit, offset)
