from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from platform_auth import PlatformPrincipal

from agent_execution.api.controller import ApiController
from agent_execution.api.dependencies import get_api_key, get_app_container, get_execution_service, get_platform_principal
from agent_execution.api.request_context import client_address
from agent_execution.core.container import ApplicationContainer
from agent_execution.core.exceptions import ServiceError
from agent_execution.schemas.runs import CreateRunRequest, InvokeRequest, RunResponse, RunResult
from agent_execution.schemas.threads import Channel, CreateThreadRequest, ExecutionType, RetentionPolicy
from agent_execution.services.agent_execution_service import AgentExecutionService


class ChatController(ApiController):
    """Two calls: studio test, and the published chat other people use."""

    def register(self, router: APIRouter) -> None:
        router.post("/agents/{agent_id}/test", tags=["chat"])(self.test)
        router.post("/agents/{agent_id}/chat", tags=["chat"])(self.chat)
        router.get("/agents/{agent_id}/chat/runs/{run_id}", response_model=RunResponse, tags=["chat"])(self.get_run)

    async def test(
        self,
        agent_id: UUID,
        body: InvokeRequest,
        request: Request,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)],
    ):
        thread_id = await self._test_thread(container, agent_id, body.thread_id, principal)
        return await _dispatch(
            service,
            agent_id,
            thread_id,
            _to_run_request(body),
            request,
            principal.token,
            started_by=principal.username or principal.subject,
        )

    async def chat(
        self,
        agent_id: UUID,
        body: InvokeRequest,
        request: Request,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        api_key: Annotated[str, Depends(get_api_key)],
    ):
        deployment = await container.deployment_service.authenticate_for_agent(agent_id, api_key)
        await container.deployment_service.require_published(agent_id)
        if body.thread_id:
            await self._production_thread(container, deployment, body.thread_id)
            thread_id = body.thread_id
        else:
            thread = await container.thread_service.create(
                agent_id,
                CreateThreadRequest(
                    execution_type=ExecutionType.PRODUCTION,
                    revision_id=deployment["revision_id"],
                ),
                channel=Channel.API,
                bearer_token=None,
                triggered_by=f"api:{deployment['slug']}",
                deployment_id=deployment["deployment_id"],
                revision_id=deployment["revision_id"],
                retention_policy=RetentionPolicy(deployment["retention_policy"]),
            )
            thread_id = thread.thread_id
        return await _dispatch(
            service,
            agent_id,
            thread_id,
            _to_run_request(body),
            request,
            None,
            started_by=f"api:{deployment['slug']}",
        )

    async def get_run(
        self,
        agent_id: UUID,
        run_id: UUID,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        api_key: Annotated[str, Depends(get_api_key)],
    ) -> RunResponse:
        deployment = await container.deployment_service.authenticate_for_agent(agent_id, api_key)
        row = await container.runs.get(run_id)
        if row is None or row["agent_id"] != agent_id:
            raise ServiceError("NOT_FOUND", "Run not found.", 404)
        await self._production_thread(container, deployment, row["thread_id"])
        return await service.get_run(agent_id, row["thread_id"], run_id, authorize=False)

    @staticmethod
    async def _test_thread(
        container: ApplicationContainer,
        agent_id: UUID,
        thread_id: UUID | None,
        principal: PlatformPrincipal,
    ) -> UUID:
        if thread_id is None:
            thread = await container.thread_service.create(
                agent_id,
                CreateThreadRequest(execution_type=ExecutionType.TEST),
                channel=Channel.STUDIO,
                bearer_token=principal.token,
                triggered_by=principal.username or principal.subject,
            )
            return thread.thread_id
        row = await container.threads.get(agent_id, thread_id)
        if row is None or row["execution_type"] != ExecutionType.TEST.value:
            raise ServiceError("NOT_FOUND", "Test thread not found.", 404)
        if row["status"] != "OPEN":
            raise ServiceError("THREAD_CLOSED", f"Thread status is {row['status']}.", 409)
        return thread_id

    @staticmethod
    async def _production_thread(container: ApplicationContainer, deployment, thread_id: UUID) -> None:
        thread = await container.threads.get(deployment["agent_id"], thread_id)
        if (
            thread is None
            or thread["deployment_id"] != deployment["deployment_id"]
            or thread["execution_type"] != ExecutionType.PRODUCTION.value
        ):
            raise ServiceError("NOT_FOUND", "Thread not found.", 404)
        if thread["status"] != "OPEN":
            raise ServiceError("THREAD_CLOSED", f"Thread status is {thread['status']}.", 409)


def _to_run_request(body: InvokeRequest) -> CreateRunRequest:
    return CreateRunRequest(
        input=body.input,
        input_artifact_ids=body.input_artifact_ids,
        stream=body.stream,
        background=body.background,
        idempotency_key=body.idempotency_key,
    )


async def _dispatch(
    service: AgentExecutionService,
    agent_id: UUID,
    thread_id: UUID,
    body: CreateRunRequest,
    request: Request,
    bearer_token: str | None,
    *,
    started_by: str,
):
    address = client_address(request)
    wants_stream = body.stream or "text/event-stream" in request.headers.get("accept", "")
    if wants_stream and not body.background:
        return StreamingResponse(
            service.stream(
                agent_id,
                thread_id,
                body,
                bearer_token,
                started_by=started_by,
                client_ip=address,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await service.start(
        agent_id,
        thread_id,
        body,
        bearer_token,
        started_by=started_by,
        client_ip=address,
    )
