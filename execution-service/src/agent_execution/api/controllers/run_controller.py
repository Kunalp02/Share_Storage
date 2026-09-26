from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from agent_execution.api.controller import ApiController
from agent_execution.api.dependencies import get_bearer_token, get_execution_service
from agent_execution.schemas.runs import CreateRunRequest, RunResponse, RunResult
from agent_execution.services.agent_execution_service import AgentExecutionService


class RunController(ApiController):
    def register(self, router: APIRouter) -> None:
        router.post("/agents/{agent_id}/threads/{thread_id}/runs", tags=["runs"])(self.create)
        router.get(
            "/agents/{agent_id}/threads/{thread_id}/runs/{run_id}",
            response_model=RunResponse,
            tags=["runs"],
        )(self.get)
        router.get(
            "/agents/{agent_id}/threads/{thread_id}/runs",
            response_model=list[RunResponse],
            tags=["runs"],
        )(self.list_runs)

    async def create(
        self,
        agent_id: UUID,
        thread_id: UUID,
        body: CreateRunRequest,
        request: Request,
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ):
        wants_stream = body.stream or "text/event-stream" in request.headers.get("accept", "")
        if wants_stream and not body.background:
            return StreamingResponse(
                service.stream(agent_id, thread_id, body, token),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        result = await service.start(agent_id, thread_id, body, token)
        if isinstance(result, RunResult):
            return result
        return result

    async def get(
        self,
        agent_id: UUID,
        thread_id: UUID,
        run_id: UUID,
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        token: Annotated[str, Depends(get_bearer_token)],
    ) -> RunResponse:
        return await service.get_run(agent_id, thread_id, run_id, token)

    async def list_runs(
        self,
        agent_id: UUID,
        thread_id: UUID,
        service: Annotated[AgentExecutionService, Depends(get_execution_service)],
        token: Annotated[str, Depends(get_bearer_token)],
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[RunResponse]:
        return await service.list_runs(agent_id, thread_id, limit, offset, token)
