from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.persistence.thread_repository import ThreadRepository
from agent_execution.schemas.runtime import RuntimeManifest
from agent_execution.schemas.threads import (
    Channel,
    CreateThreadRequest,
    ExecutionType,
    RetentionPolicy,
    ThreadResponse,
    ThreadStatus,
)
from agent_execution.services.manifest_service import ManifestService
from agent_execution.services.run_policy import pins_manifest
from agent_execution.settings import Settings


class ThreadService:
    def __init__(self, settings: Settings, repo: ThreadRepository, manifests: ManifestService) -> None:
        self._settings = settings
        self._repo = repo
        self._manifests = manifests

    async def create(
        self,
        agent_id: UUID,
        request: CreateThreadRequest,
        *,
        channel: Channel,
        bearer_token: str | None,
        triggered_by: str,
        deployment_id: UUID | None = None,
        revision_id: UUID | None = None,
        retention_policy: RetentionPolicy | None = None,
    ) -> ThreadResponse:
        published_only = request.execution_type == ExecutionType.PRODUCTION or channel == Channel.API
        chosen_revision = revision_id or request.revision_id
        manifest = await self._manifests.resolve(
            agent_id,
            bearer_token,
            revision_id=chosen_revision,
            published_only=published_only,
        )
        policy = retention_policy or self._retention(request.execution_type)
        expires_at = self._expires_at(policy)
        thread_id = uuid4()
        snapshot = manifest.model_dump(mode="json") if pins_manifest(request.execution_type) else None
        await self._repo.insert(
            thread_id=thread_id,
            agent_id=agent_id,
            channel=channel.value,
            execution_type=request.execution_type.value,
            status=ThreadStatus.OPEN.value,
            revision_id=manifest.revision_id or chosen_revision,
            manifest_hash=manifest.manifest_hash,
            manifest_snapshot=snapshot,
            deployment_id=deployment_id,
            retention_policy=policy.value,
            triggered_by=triggered_by,
            expires_at=expires_at,
        )
        return self._to_response(
            thread_id=thread_id,
            agent_id=agent_id,
            channel=channel,
            execution_type=request.execution_type,
            status=ThreadStatus.OPEN,
            revision_id=manifest.revision_id or chosen_revision,
            manifest_hash=manifest.manifest_hash,
            deployment_id=deployment_id,
            retention_policy=policy,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )

    async def get(self, agent_id: UUID, thread_id: UUID, bearer_token: str | None) -> ThreadResponse:
        await self._manifests.resolve(agent_id, bearer_token)
        row = await self._repo.get(agent_id, thread_id)
        if row is None:
            raise ServiceError("NOT_FOUND", "Thread not found.", 404)
        return self._row_to_response(row)

    async def get_open(self, agent_id: UUID, thread_id: UUID) -> dict:
        row = await self._repo.get(agent_id, thread_id)
        if row is None:
            raise ServiceError("NOT_FOUND", "Thread not found.", 404)
        if row["status"] != ThreadStatus.OPEN.value:
            raise ServiceError("THREAD_CLOSED", f"Thread status is {row['status']}.", 409)
        return row

    async def list(
        self,
        agent_id: UUID,
        execution_type: ExecutionType | None,
        bearer_token: str | None,
        limit: int,
        offset: int,
    ) -> list[ThreadResponse]:
        await self._manifests.resolve(agent_id, bearer_token)
        rows = await self._repo.list_for_agent(
            agent_id, execution_type.value if execution_type else None, limit, offset
        )
        return [self._row_to_response(row) for row in rows]

    async def resolve(
        self,
        agent_id: UUID,
        thread_id: UUID | None,
        execution_type: ExecutionType,
        bearer_token: str | None,
        triggered_by: str,
    ) -> ThreadResponse:
        if thread_id is None:
            return await self.create(
                agent_id,
                CreateThreadRequest(execution_type=execution_type),
                channel=Channel.STUDIO,
                bearer_token=bearer_token,
                triggered_by=triggered_by,
            )
        return await self.get(agent_id, thread_id, bearer_token)

    async def manifest_for_run(self, row, bearer_token: str | None) -> RuntimeManifest:
        execution_type = ExecutionType(row["execution_type"])
        if pins_manifest(execution_type) and row["manifest_snapshot"]:
            raw = row["manifest_snapshot"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            return RuntimeManifest.model_validate(raw)
        revision_id = row["revision_id"]
        return await self._manifests.resolve(
            row["agent_id"],
            bearer_token,
            revision_id=revision_id,
            published_only=execution_type == ExecutionType.PRODUCTION,
        )

    def _retention(self, execution_type: ExecutionType) -> RetentionPolicy:
        if execution_type == ExecutionType.TEST:
            return RetentionPolicy.TEMPORARY
        return RetentionPolicy(self._settings.default_production_retention_policy)

    def _expires_at(self, policy: RetentionPolicy) -> datetime | None:
        now = datetime.now(timezone.utc)
        if policy == RetentionPolicy.TEMPORARY:
            return now + timedelta(hours=self._settings.test_thread_ttl_hours)
        if policy == RetentionPolicy.DAYS_30:
            return now + timedelta(days=30)
        if policy == RetentionPolicy.DAYS_90:
            return now + timedelta(days=90)
        if policy == RetentionPolicy.YEAR_1:
            return now + timedelta(days=365)
        return None

    def _row_to_response(self, row) -> ThreadResponse:
        return self._to_response(
            thread_id=row["thread_id"],
            agent_id=row["agent_id"],
            channel=Channel(row["channel"]),
            execution_type=ExecutionType(row["execution_type"]),
            status=ThreadStatus(row["status"]),
            revision_id=row["revision_id"],
            manifest_hash=row["manifest_hash"],
            deployment_id=row["deployment_id"],
            retention_policy=RetentionPolicy(row["retention_policy"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_response(**kwargs) -> ThreadResponse:
        thread_id = kwargs["thread_id"]
        return ThreadResponse(
            thread_id=thread_id,
            execution_id=thread_id,
            session_id=str(thread_id),
            **{key: value for key, value in kwargs.items() if key != "thread_id"},
        )
