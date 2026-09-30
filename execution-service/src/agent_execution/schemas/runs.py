from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Dispatch(str, Enum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: str
    input_artifact_ids: list[UUID] = Field(default_factory=list, alias="inputArtifactIds")
    org_id: str | None = Field(default=None, alias="orgId")
    stream: bool = False
    background: bool = False
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")


class InvokeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: str
    thread_id: UUID | None = Field(default=None, alias="threadId")
    input_artifact_ids: list[UUID] = Field(default_factory=list, alias="inputArtifactIds")
    stream: bool = False
    background: bool = False
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")


class RunResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: UUID = Field(alias="runId")
    thread_id: UUID = Field(alias="threadId")
    agent_id: UUID = Field(alias="agentId")
    status: RunStatus
    dispatch: Dispatch
    input: str
    output: str | None = None
    error: str | None = None
    revision_id: UUID | None = Field(default=None, alias="revisionId")
    manifest_hash: str = Field(default="", alias="manifestHash")
    attempt: int = 0
    input_artifact_ids: list[UUID] = Field(default_factory=list, alias="inputArtifactIds")
    output_artifact_ids: list[UUID] = Field(default_factory=list, alias="outputArtifactIds")
    steps: list[str] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None, alias="stopReason")
    started_by: str = Field(default="", alias="startedBy")
    client_ip: str = Field(default="", alias="clientIp")
    created_at: datetime = Field(alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")


class ExecutionStep(BaseModel):
    name: str
    detail: str | None = None


class MemorySnapshot(BaseModel):
    scope: str | None = None
    total_turns: int = 0
    turns_in_prompt: int = 0
    truncated_for_context_window: bool = False
    persisted: bool = False


class RunResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: UUID = Field(alias="agentId")
    thread_id: UUID = Field(alias="threadId")
    execution_id: UUID = Field(alias="executionId")
    run_id: UUID = Field(alias="runId")
    session_id: str = Field(alias="sessionId")
    output: str
    output_artifact_ids: list[UUID] = Field(default_factory=list, alias="outputArtifactIds")
    steps: list[ExecutionStep] = Field(default_factory=list)
    memory: MemorySnapshot = Field(default_factory=MemorySnapshot)
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list, alias="retrievedContext")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateDeploymentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str | None = None
    revision_id: UUID | None = Field(default=None, alias="revisionId")
    retention_policy: str = Field(default="PERMANENT", alias="retentionPolicy")


class DeploymentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    deployment_id: UUID = Field(alias="deploymentId")
    agent_id: UUID = Field(alias="agentId")
    slug: str
    revision_id: UUID | None = Field(default=None, alias="revisionId")
    retention_policy: str = Field(alias="retentionPolicy")
    enabled: bool
    created_at: datetime = Field(alias="createdAt")
    api_key: str = Field(alias="apiKey")
    key_reissued: bool = Field(default=False, alias="keyReissued")
    chat_url: str = Field(alias="chatUrl")
