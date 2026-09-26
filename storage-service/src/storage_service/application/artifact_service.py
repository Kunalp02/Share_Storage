from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from storage_service.core.exceptions import ServiceError
from storage_service.domain.enums import ArtifactStatus, ArtifactType
from storage_service.domain.paths import build_storage_key
from storage_service.infrastructure.clients.platform_clients import AgentConfigClient, ExecutionClient
from storage_service.infrastructure.postgres.artifact_repository import ArtifactRepository
from storage_service.infrastructure.s3.object_store import S3ObjectStore
from storage_service.settings import Settings

_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/csv")
_TEXT_SUFFIXES = (".txt", ".md", ".json", ".csv", ".log", ".xml", ".yaml", ".yml")


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ArtifactService:
    def __init__(
        self,
        settings: Settings,
        repo: ArtifactRepository,
        s3: S3ObjectStore,
        agent_config: AgentConfigClient,
        execution_client: ExecutionClient,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._s3 = s3
        self._agent_config = agent_config
        self._execution = execution_client

    async def init_upload(
        self,
        *,
        agent_id: UUID,
        artifact_type: ArtifactType,
        filename: str,
        content_type: str,
        bearer_token: str,
        thread_id: UUID | None = None,
        run_id: UUID | None = None,
        mode: str = "TEST",
        created_by: str = "",
    ) -> dict:
        await self._agent_config.assert_agent_access(agent_id, bearer_token)
        thread = await self._execution.resolve_thread(agent_id, thread_id, mode, bearer_token)
        resolved = thread.get("threadId") or thread.get("executionId")
        if not resolved:
            raise ServiceError("EXECUTION_SERVICE_ERROR", "No threadId in response.", 502)
        resolved_thread = UUID(str(resolved))
        exec_agent = thread.get("agentId") or thread.get("agent_id")
        if str(exec_agent) != str(agent_id):
            raise ServiceError("VALIDATION_FAILED", "agentId does not match the thread.", 400)
        return await self._create_pending(
            agent_id=agent_id,
            thread_id=resolved_thread,
            run_id=run_id,
            artifact_type=artifact_type,
            filename=filename,
            content_type=content_type,
            created_by=created_by,
            expires_at=_parse_dt(thread.get("expiresAt") or thread.get("expires_at")),
        )

    async def _create_pending(
        self,
        *,
        agent_id: UUID,
        thread_id: UUID,
        run_id: UUID | None,
        artifact_type: ArtifactType,
        filename: str,
        content_type: str,
        created_by: str,
        expires_at: datetime | None,
        status: str = ArtifactStatus.PENDING.value,
        size_bytes: int | None = None,
        body: bytes | None = None,
    ) -> dict:
        artifact_id = uuid4()
        storage_key = build_storage_key(agent_id, thread_id, artifact_type.value, artifact_id, filename)
        if body is not None:
            self._s3.put_bytes(storage_key, body, content_type)
            size_bytes = len(body)
            status = ArtifactStatus.READY.value
        await self._repo.insert_pending(
            artifact_id=artifact_id,
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
            created_by=created_by,
            artifact_type=artifact_type.value,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            storage_key=storage_key,
            expires_at=expires_at,
            metadata=None,
            status=status,
            size_bytes=size_bytes,
        )
        payload = {
            "artifactId": str(artifact_id),
            "threadId": str(thread_id),
            "executionId": str(thread_id),
            "runId": str(run_id) if run_id else None,
            "agentId": str(agent_id),
            "artifactType": artifact_type.value,
            "status": status,
            "storageKey": storage_key,
        }
        if status == ArtifactStatus.PENDING.value:
            payload["uploadUrl"] = self._s3.presign_put(storage_key, content_type or "application/octet-stream")
        return payload

    async def store_text(
        self,
        *,
        thread_id: UUID,
        agent_id: UUID,
        run_id: UUID | None,
        filename: str,
        content_type: str,
        text: str,
        artifact_type: ArtifactType,
        expires_at: str | None,
    ) -> dict:
        return await self._create_pending(
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
            artifact_type=artifact_type,
            filename=filename,
            content_type=content_type or "text/plain",
            created_by="execution-service",
            expires_at=_parse_dt(expires_at),
            body=text.encode("utf-8"),
        )

    async def complete_upload(
        self,
        artifact_id: UUID,
        *,
        size_bytes: int | None,
        checksum_sha256: str | None,
        bearer_token: str,
    ) -> dict:
        row = await self._require(artifact_id)
        if row["status"] != ArtifactStatus.PENDING.value:
            raise ServiceError("INVALID_STATE", "Artifact is not pending upload.", 409)
        await self._agent_config.assert_agent_access(row["agent_id"], bearer_token)
        actual_size = self._s3.head_object(row["storage_key"])
        await self._repo.mark_ready(artifact_id, size_bytes if size_bytes is not None else actual_size, checksum_sha256)
        return await self.get_artifact(artifact_id, bearer_token=bearer_token)

    async def get_artifact(self, artifact_id: UUID, *, bearer_token: str) -> dict:
        row = await self._require(artifact_id)
        await self._agent_config.assert_agent_access(row["agent_id"], bearer_token)
        download_url = None
        if row["status"] == ArtifactStatus.READY.value:
            download_url = self._s3.presign_get(row["storage_key"])
        return _row_to_dto(row, download_url)

    async def list_artifacts(
        self,
        thread_id: UUID,
        *,
        artifact_type: ArtifactType | None,
        bearer_token: str,
        agent_id: UUID | None = None,
    ) -> list[dict]:
        rows = await self._repo.list_for_thread(thread_id, artifact_type.value if artifact_type else None)
        if not rows:
            return []
        first_agent = rows[0]["agent_id"]
        if agent_id and str(agent_id) != str(first_agent):
            raise ServiceError("VALIDATION_FAILED", "agentId mismatch.", 400)
        await self._agent_config.assert_agent_access(first_agent, bearer_token)
        return [_row_to_dto(row, None) for row in rows]

    async def read_text(self, artifact_id: UUID, max_chars: int | None = None) -> dict:
        row = await self._require(artifact_id)
        if row["status"] != ArtifactStatus.READY.value:
            raise ServiceError("INVALID_STATE", "Artifact is not ready.", 409)
        limit = max_chars or self._settings.artifact_text_max_chars
        filename = row["filename"] or ""
        content_type = (row["content_type"] or "").lower()
        text_like = content_type.startswith(_TEXT_TYPES) or filename.lower().endswith(_TEXT_SUFFIXES)
        if not text_like:
            return {
                "artifactId": str(artifact_id),
                "filename": filename,
                "contentType": row["content_type"],
                "text": None,
                "truncated": False,
            }
        raw = self._s3.get_bytes(row["storage_key"], limit * 4)
        text = raw.decode("utf-8", errors="replace")
        truncated = len(text) > limit
        return {
            "artifactId": str(artifact_id),
            "filename": filename,
            "contentType": row["content_type"],
            "text": text[:limit],
            "truncated": truncated,
        }

    async def delete_all_for_thread(self, thread_id: UUID) -> int:
        rows = await self._repo.list_keys_for_thread(thread_id)
        for row in rows:
            self._s3.delete_object(row["storage_key"])
        await self._repo.mark_deleted_for_thread(thread_id)
        return len(rows)

    async def _require(self, artifact_id: UUID):
        row = await self._repo.get(artifact_id)
        if row is None:
            raise ServiceError("NOT_FOUND", "Artifact not found.", 404)
        return row


def _row_to_dto(row, download_url: str | None) -> dict:
    thread_id = row["thread_id"] or row["execution_id"]
    return {
        "artifactId": str(row["artifact_id"]),
        "agentId": str(row["agent_id"]),
        "threadId": str(thread_id),
        "executionId": str(thread_id),
        "runId": str(row["run_id"]) if row["run_id"] else None,
        "artifactType": row["artifact_type"],
        "filename": row["filename"],
        "contentType": row["content_type"],
        "sizeBytes": row["size_bytes"],
        "checksumSha256": row["checksum_sha256"],
        "status": row["status"],
        "expiresAt": row["expires_at"].isoformat() if row["expires_at"] else None,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        "downloadUrl": download_url,
    }
