from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from agent_execution.api.controller import ApiController
from agent_execution.api.dependencies import get_api_key, get_app_container, get_execution_service
from agent_execution.api.request_context import client_address
from agent_execution.core.container import ApplicationContainer
from agent_execution.core.exceptions import ServiceError
from agent_execution.schemas.runs import CreateRunRequest, InvokeRequest, RunResponse, RunResult
from agent_execution.schemas.threads import Channel, CreateThreadRequest, ExecutionType, RetentionPolicy, ThreadResponse
from agent_execution.services.agent_execution_service import AgentExecutionService


class InvokeController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.post("/invoke/{slug}/threads", response_model=ThreadResponse, tags=["invoke"])(self.open_thread)
        router.post("/invoke/{slug}/threads/{thread_id}/messages", tags=["invoke"])(self.message)
        router.post("/invoke/{slug}", tags=["invoke"])(self.invoke_once)
        router.get("/invoke/{slug}/runs/{run_id}", response_model=RunResponse, tags=["invoke"])(self.get_run)
        router.post("/agents/{agent_id}/execute", tags=["invoke"])(self.execute)

    async def open_thread(
        self,
        slug: str,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        api_key: Annotated[str, Depends(get_api_key)],
    ) -> ThreadResponse:
        deployment = await container.deployment_service.authenticate(slug, api_key)
        return await container.thread_service.create(
            deployment["agent_id"],
            CreateThreadRequest(execution_type=ExecutionType.PRODUCTION, revision_id=deployment["revision_id"]),
            channel=Channel.API,
            bearer_token=None,
            triggered_by=f"api:{slug}",
            deployment_id=deployment["deployment_id"],
            revision_id=deployment["revision_id"],
            retention_policy=RetentionPolicy(deployment["retention_policy"]),
        )

    async def message(
        self,
        slug: str,
        thread_id: UUID,
        body: InvokeRequest,
        request: Request,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        api_key: Annotated[str, Depends(get_api_key)],
    ):
        deployment = await container.deployment_service.authenticate(slug, api_key)
        await self._owned_thread(container, deployment, thread_id)
        run_request = _to_run_request(body)
        return await _dispatch(
            service, deployment["agent_id"], thread_id, run_request, request, started_by=f"api:{slug}"
        )

    async def invoke_once(
        self,
        slug: str,
        body: InvokeRequest,
        request: Request,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        api_key: Annotated[str, Depends(get_api_key)],
    ):
        deployment = await container.deployment_service.authenticate(slug, api_key)
        if body.thread_id:
            thread_id = body.thread_id
            await self._owned_thread(container, deployment, thread_id)
        else:
            thread = await self.open_thread(slug, container, api_key)
            thread_id = thread.thread_id
        return await _dispatch(
            service, deployment["agent_id"], thread_id, _to_run_request(body), request, started_by=f"api:{slug}"
        )

    async def execute(
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
        slug = deployment["slug"]
        if body.thread_id:
            thread_id = body.thread_id
            await self._owned_thread(container, deployment, thread_id)
        else:
            thread = await container.thread_service.create(
                agent_id,
                CreateThreadRequest(execution_type=ExecutionType.PRODUCTION, revision_id=deployment["revision_id"]),
                channel=Channel.API,
                bearer_token=None,
                triggered_by=f"api:{slug}",
                deployment_id=deployment["deployment_id"],
                revision_id=deployment["revision_id"],
                retention_policy=RetentionPolicy(deployment["retention_policy"]),
            )
            thread_id = thread.thread_id
        return await _dispatch(
            service, agent_id, thread_id, _to_run_request(body), request, started_by=f"api:{slug}"
        )

    async def get_run(
        self,
        slug: str,
        run_id: UUID,
        container: Annotated[ApplicationContainer, Depends(get_app_container)],
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        api_key: Annotated[str, Depends(get_api_key)],
    ) -> RunResponse:
        deployment = await container.deployment_service.authenticate(slug, api_key)
        row = await container.runs.get(run_id)
        if row is None or row["agent_id"] != deployment["agent_id"]:
            raise ServiceError("NOT_FOUND", "Run not found.", 404)
        thread = await container.threads.get(deployment["agent_id"], row["thread_id"])
        if thread is None or thread["deployment_id"] != deployment["deployment_id"]:
            raise ServiceError("NOT_FOUND", "Run not found.", 404)
        return await service.get_run(
            deployment["agent_id"], row["thread_id"], run_id, authorize=False
        )

    @staticmethod
    async def _owned_thread(container: ApplicationContainer, deployment, thread_id: UUID) -> None:
        thread = await container.threads.get(deployment["agent_id"], thread_id)
        if thread is None or thread["deployment_id"] != deployment["deployment_id"]:
            raise ServiceError("NOT_FOUND", "Thread not found.", 404)


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
    *,
    started_by: str,
):
    wants_stream = body.stream or "text/event-stream" in request.headers.get("accept", "")
    address = client_address(request)
    if wants_stream and not body.background:
        return StreamingResponse(
            service.stream(agent_id, thread_id, body, None, started_by=started_by, client_ip=address),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    result = await service.start(agent_id, thread_id, body, None, started_by=started_by, client_ip=address)
    if isinstance(result, (RunResult, RunResponse)):
        return result
    return result
