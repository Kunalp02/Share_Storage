from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Channel(str, Enum):
    STUDIO = "STUDIO"
    API = "API"


class ExecutionType(str, Enum):
    TEST = "TEST"
    PRODUCTION = "PRODUCTION"


class ThreadStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class RetentionPolicy(str, Enum):
    TEMPORARY = "TEMPORARY"
    DAYS_30 = "30_DAYS"
    DAYS_90 = "90_DAYS"
    YEAR_1 = "1_YEAR"
    PERMANENT = "PERMANENT"


class CreateThreadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    execution_type: ExecutionType = Field(alias="executionType")
    revision_id: UUID | None = Field(default=None, alias="revisionId")


class ResolveThreadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID | None = Field(default=None, alias="threadId")
    execution_id: UUID | None = Field(default=None, alias="executionId")
    mode: ExecutionType = ExecutionType.TEST

    def resolved_thread_id(self) -> UUID | None:
        return self.thread_id or self.execution_id


class ThreadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    execution_id: UUID = Field(alias="executionId")
    agent_id: UUID = Field(alias="agentId")
    channel: Channel
    execution_type: ExecutionType = Field(alias="executionType")
    status: ThreadStatus
    revision_id: UUID | None = Field(default=None, alias="revisionId")
    manifest_hash: str = Field(alias="manifestHash")
    deployment_id: UUID | None = Field(default=None, alias="deploymentId")
    retention_policy: RetentionPolicy = Field(alias="retentionPolicy")
    triggered_by: str = Field(default="", alias="triggeredBy")
    session_id: str = Field(alias="sessionId")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")
