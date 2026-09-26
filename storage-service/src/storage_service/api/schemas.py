from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from storage_service.domain.enums import ArtifactType
from storage_service.domain.execution_mode import ExecutionMode


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
