from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from agent_execution.agents.graph.builder import build_execution_graph
from agent_execution.agents.graph.context import AgentGraphContext
from agent_execution.agents.graph.nodes import AgentGraphNodes
from agent_execution.agents.graph.state import AgentGraphState
from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.persistence.run_repository import RunRepository
from agent_execution.schemas.runs import (
    CreateRunRequest,
    Dispatch,
    MemorySnapshot,
    RunResponse,
    RunResult,
    RunStatus,
    ExecutionStep,
)
from agent_execution.schemas.runtime import RuntimeManifest
from agent_execution.schemas.threads import ExecutionType
from agent_execution.services.run_policy import status_after_failure
from agent_execution.services.run_slots import RunSlots
from agent_execution.services.thread_service import ThreadService
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


class AgentExecutionService:
    def __init__(
        self,
        settings: Settings,
        context: AgentGraphContext,
        threads: ThreadService,
        runs: RunRepository,
        slots: RunSlots,
    ) -> None:
        self._settings = settings
        self._context = context
        self._threads = threads
        self._runs = runs
        self._slots = slots
        self._graph = build_execution_graph(context)
        self._nodes = AgentGraphNodes(context)
        self._api_worker = f"api-{os.getpid()}"

    async def aclose(self) -> None:
        await self._context.aclose()

    async def start(
        self,
        agent_id: UUID,
        thread_id: UUID,
        request: CreateRunRequest,
        bearer_token: str | None,
        *,
        started_by: str = "",
        client_ip: str = "",
    ) -> RunResult | RunResponse:
        thread = await self._threads.get_open(agent_id, thread_id)
        manifest = await self._threads.manifest_for_run(thread, bearer_token)
        if request.background:
            row, created = await self._insert(
                thread,
                request,
                manifest,
                Dispatch.ASYNC,
                bearer_token=None,
                worker_id=None,
                attempt=0,
                started_by=started_by,
                client_ip=client_ip,
            )
            if created:
                logger.info(
                    "run.queued runId=%s threadId=%s agentId=%s inputChars=%s",
                    row["run_id"],
                    row["thread_id"],
                    row["agent_id"],
                    len(request.input),
                )
            return self._run_response(row)
        if request.stream:
            raise ServiceError("USE_STREAM", "Set stream=true on the HTTP call and read the event stream.", 400)
        return await self._execute_sync(
            thread, request, manifest, bearer_token, started_by=started_by, client_ip=client_ip
        )

    async def stream(
        self,
        agent_id: UUID,
        thread_id: UUID,
        request: CreateRunRequest,
        bearer_token: str | None,
        *,
        started_by: str = "",
        client_ip: str = "",
    ) -> AsyncIterator[str]:
        thread = await self._threads.get_open(agent_id, thread_id)
        manifest = await self._threads.manifest_for_run(thread, bearer_token)
        row, created = await self._insert(
            thread,
            request,
            manifest,
            Dispatch.SYNC,
            bearer_token,
            worker_id=self._api_worker,
            attempt=1,
            started_by=started_by,
            client_ip=client_ip,
        )
        if not created:
            if row["status"] == RunStatus.SUCCEEDED.value:
                yield self._sse("done", self._result_from_row(row, manifest).model_dump(mode="json"))
            else:
                yield self._sse(
                    "error",
                    {"code": "RUN_IN_PROGRESS", "message": f"Run {row['run_id']} is {row['status']}."},
                )
            return
        run_id = row["run_id"]
        self._log_started(row, request, Dispatch.SYNC.value)
        beat = asyncio.create_task(self._heartbeat(run_id, self._api_worker))
        try:
            async with self._slots.acquire():
                state = self._initial_state(thread, request, bearer_token, manifest, run_id)
                if manifest.has_tools:
                    final_state = await self._graph.ainvoke(state)
                else:
                    prepared = await self._nodes.prepare_context(state)
                    parts: list[str] = []
                    async for token in self._context.llm_gateway.stream(
                        model=manifest.model.model_identifier,
                        system_prompt=prepared["system_prompt"],
                        user_input=request.input,
                        temperature=manifest.temperature,
                        bearer_token=bearer_token,
                        base_url=manifest.model.base_url,
                    ):
                        parts.append(token)
                        yield self._sse("token", {"text": token})
                    streamed = {**prepared, "output": "".join(parts)}
                    persisted = await self._nodes.persist_memory(streamed)
                    final_state = {
                        **streamed,
                        **persisted,
                        "steps": ["prepare_context", "call_llm_stream", "persist_memory"],
                    }
            result = await self._finish_success(thread, run_id, manifest, final_state)
            yield self._sse("done", result.model_dump(mode="json"))
        except Exception as exc:
            await self._finish_failure(row, exc)
            yield self._sse("error", {"code": getattr(exc, "code", "RUN_FAILED"), "message": str(exc)})
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def execute_claimed(self, row, worker_id: str) -> None:
        logger.info(
            "run.claimed runId=%s threadId=%s workerId=%s attempt=%s",
            row["run_id"],
            row["thread_id"],
            worker_id,
            row["attempt"],
        )
        thread = await self._threads.get_open(row["agent_id"], row["thread_id"])
        manifest = await self._threads.manifest_for_run(thread, None)
        beat = asyncio.create_task(self._heartbeat(row["run_id"], worker_id))
        request = CreateRunRequest(
            input=row["input"],
            input_artifact_ids=_uuid_list(row["input_artifact_ids"]),
            org_id=row["org_id"],
        )
        try:
            async with self._slots.acquire():
                final_state = await self._graph.ainvoke(
                    self._initial_state(thread, request, None, manifest, row["run_id"])
                )
            await self._finish_success(thread, row["run_id"], manifest, final_state)
        except Exception as exc:
            logger.exception("Background run %s failed", row["run_id"])
            await self._finish_failure(row, exc)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def get_run(
        self,
        agent_id: UUID,
        thread_id: UUID,
        run_id: UUID,
        bearer_token: str | None = None,
        *,
        authorize: bool = True,
    ) -> RunResponse:
        if authorize:
            await self._threads.get(agent_id, thread_id, bearer_token)
        row = await self._runs.get(run_id)
        if row is None or row["thread_id"] != thread_id or row["agent_id"] != agent_id:
            raise ServiceError("NOT_FOUND", "Run not found.", 404)
        return self._run_response(row)

    async def list_runs(
        self,
        agent_id: UUID,
        thread_id: UUID,
        limit: int,
        offset: int,
        bearer_token: str | None = None,
    ) -> list[RunResponse]:
        await self._threads.get(agent_id, thread_id, bearer_token)
        rows = await self._runs.list_for_thread(thread_id, limit, offset)
        return [self._run_response(row) for row in rows]

    async def _execute_sync(
        self, thread, request, manifest, bearer_token, *, started_by: str = "", client_ip: str = ""
    ) -> RunResult:
        row, created = await self._insert(
            thread,
            request,
            manifest,
            Dispatch.SYNC,
            bearer_token,
            worker_id=self._api_worker,
            attempt=1,
            started_by=started_by,
            client_ip=client_ip,
        )
        if not created:
            if row["status"] == RunStatus.SUCCEEDED.value:
                return self._result_from_row(row, manifest)
            raise ServiceError("RUN_IN_PROGRESS", f"Run {row['run_id']} is {row['status']}.", 409)
        self._log_started(row, request, Dispatch.SYNC.value)
        beat = asyncio.create_task(self._heartbeat(row["run_id"], self._api_worker))
        try:
            async with self._slots.acquire():
                final_state = await self._graph.ainvoke(
                    self._initial_state(thread, request, bearer_token, manifest, row["run_id"])
                )
            return await self._finish_success(thread, row["run_id"], manifest, final_state)
        except Exception as exc:
            await self._finish_failure(row, exc)
            raise
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _insert(
        self,
        thread,
        request,
        manifest,
        dispatch: Dispatch,
        bearer_token,
        worker_id,
        attempt: int,
        *,
        started_by: str = "",
        client_ip: str = "",
    ):
        del bearer_token
        lease = None
        started = None
        if dispatch == Dispatch.SYNC:
            started = datetime.now(timezone.utc)
            lease = started + timedelta(seconds=self._settings.run_lease_seconds)
        try:
            return await self._runs.insert(
                run_id=uuid4(),
                thread_id=thread["thread_id"],
                agent_id=thread["agent_id"],
                status=RunStatus.RUNNING.value if dispatch == Dispatch.SYNC else RunStatus.QUEUED.value,
                dispatch=dispatch.value,
                user_input=request.input,
                revision_id=manifest.revision_id,
                manifest_hash=manifest.manifest_hash,
                attempt=attempt,
                max_attempts=self._settings.run_max_attempts,
                worker_id=worker_id,
                lease_expires_at=lease,
                idempotency_key=request.idempotency_key,
                input_artifact_ids=[str(item) for item in request.input_artifact_ids],
                org_id=request.org_id,
                started_at=started,
                started_by=started_by,
                client_ip=client_ip,
            )
        except Exception as exc:
            if "ux_runs_idempotency" in str(exc) or "duplicate key" in str(exc).lower():
                raise ServiceError("CONFLICT", "A run with this idempotency key already exists.", 409) from exc
            raise

    async def _finish_success(self, thread, run_id: UUID, manifest: RuntimeManifest, state: AgentGraphState) -> RunResult:
        output = state.get("output") or ""
        output_ids: list[UUID] = []
        if self._settings.persist_output_artifacts and output:
            expires = thread["expires_at"].isoformat() if thread["expires_at"] else None
            artifact_id = await self._context.storage.put_text_artifact(
                thread_id=thread["thread_id"],
                agent_id=thread["agent_id"],
                run_id=run_id,
                filename=f"run-{run_id}.txt",
                text=output,
                expires_at=expires,
            )
            if artifact_id:
                output_ids.append(artifact_id)
        steps = list(state.get("steps") or [])
        retrieved = list(state.get("retrieved_context") or [])
        logger.info(
            "run.succeeded runId=%s threadId=%s stopReason=%s outputChars=%s",
            run_id,
            thread["thread_id"],
            state.get("stop_reason") or "completed",
            len(output),
        )
        await self._runs.mark_succeeded(
            run_id,
            output=output,
            output_artifact_ids=[str(item) for item in output_ids],
            steps=steps,
            retrieved_context=retrieved,
            stop_reason=state.get("stop_reason") or "completed",
            manifest_hash=manifest.manifest_hash,
            revision_id=manifest.revision_id,
        )
        return self._to_result(thread, run_id, manifest, state, output_ids)

    async def _finish_failure(self, row, exc: Exception) -> None:
        attempt = int(row["attempt"] or 0)
        requeue = (
            row["dispatch"] == Dispatch.ASYNC.value
            and status_after_failure(attempt, int(row["max_attempts"])) == RunStatus.QUEUED
        )
        logger.warning(
            "run.failed runId=%s attempt=%s requeue=%s error=%s",
            row["run_id"],
            attempt,
            requeue,
            type(exc).__name__,
        )
        await self._runs.mark_failed(row["run_id"], str(exc), requeue=requeue)

    @staticmethod
    def _log_started(row, request: CreateRunRequest, dispatch: str) -> None:
        logger.info(
            "run.started runId=%s threadId=%s agentId=%s dispatch=%s inputChars=%s startedBy=%s clientIp=%s",
            row["run_id"],
            row["thread_id"],
            row["agent_id"],
            dispatch,
            len(request.input),
            row["started_by"] or "",
            row["client_ip"] or "",
        )

    async def _heartbeat(self, run_id: UUID, worker_id: str) -> None:
        interval = max(5, self._settings.run_lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._runs.heartbeat(run_id, worker_id, self._settings.run_lease_seconds)
            except Exception:
                logger.exception("Run heartbeat failed for %s", run_id)

    def _initial_state(self, thread, request, bearer_token, manifest: RuntimeManifest, run_id: UUID) -> AgentGraphState:
        return {
            "agent_id": str(thread["agent_id"]),
            "user_input": request.input,
            "thread_id": str(thread["thread_id"]),
            "run_id": str(run_id),
            "execution_type": thread["execution_type"],
            "input_artifact_ids": [str(item) for item in request.input_artifact_ids],
            "session_id": str(thread["thread_id"]),
            "thread_expires_at": thread["expires_at"].isoformat() if thread["expires_at"] else None,
            "retention_policy": thread["retention_policy"],
            "org_id": request.org_id,
            "bearer_token": bearer_token,
            "manifest": manifest.model_dump(mode="json"),
            "steps": [],
        }

    def _to_result(self, thread, run_id, manifest: RuntimeManifest, state, output_ids: list[UUID]) -> RunResult:
        return RunResult(
            agent_id=thread["agent_id"],
            thread_id=thread["thread_id"],
            execution_id=thread["thread_id"],
            run_id=run_id,
            session_id=str(thread["thread_id"]),
            output=state.get("output") or "",
            output_artifact_ids=output_ids,
            steps=[ExecutionStep(name=name) for name in (state.get("steps") or [])],
            memory=MemorySnapshot(
                scope=state.get("memory_scope"),
                total_turns=state.get("history_total_turns", 0),
                turns_in_prompt=state.get("history_turns_in_prompt", 0),
                truncated_for_context_window=bool(state.get("history_truncated")),
                persisted=bool(state.get("memory_persisted")),
            ),
            retrieved_context=state.get("retrieved_context") or [],
            metadata={
                "agentName": manifest.name,
                "model": manifest.model.model_identifier,
                "manifestHash": manifest.manifest_hash,
                "revisionId": str(manifest.revision_id) if manifest.revision_id else None,
                "runtime": "langgraph",
                "toolRounds": state.get("tool_round", 0),
                "stopReason": state.get("stop_reason") or "completed",
                "executionType": thread["execution_type"],
            },
        )

    def _result_from_row(self, row, manifest: RuntimeManifest) -> RunResult:
        output_ids = _uuid_list(row["output_artifact_ids"])
        steps = row["steps"] if isinstance(row["steps"], list) else json.loads(row["steps"] or "[]")
        retrieved = row["retrieved_context"]
        if isinstance(retrieved, str):
            retrieved = json.loads(retrieved)
        return RunResult(
            agent_id=row["agent_id"],
            thread_id=row["thread_id"],
            execution_id=row["thread_id"],
            run_id=row["run_id"],
            session_id=str(row["thread_id"]),
            output=row["output"] or "",
            output_artifact_ids=output_ids,
            steps=[ExecutionStep(name=name) for name in steps],
            retrieved_context=retrieved or [],
            metadata={"manifestHash": row["manifest_hash"], "runtime": "langgraph"},
        )

    @staticmethod
    def _run_response(row) -> RunResponse:
        return RunResponse(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            agent_id=row["agent_id"],
            status=RunStatus(row["status"]),
            dispatch=Dispatch(row["dispatch"]),
            input=row["input"],
            output=row["output"],
            error=row["error"],
            revision_id=row["revision_id"],
            manifest_hash=row["manifest_hash"] or "",
            attempt=row["attempt"] or 0,
            input_artifact_ids=_uuid_list(row["input_artifact_ids"]),
            output_artifact_ids=_uuid_list(row["output_artifact_ids"]),
            steps=_str_list(row["steps"]),
            stop_reason=row["stop_reason"],
            started_by=row["started_by"] or "",
            client_ip=row["client_ip"] or "",
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


def _uuid_list(value) -> list[UUID]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    ids: list[UUID] = []
    for item in value or []:
        try:
            ids.append(UUID(str(item)))
        except ValueError:
            continue
    return ids


def _str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return [str(item) for item in value or []]
