from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class AgentMemoryScope(str, Enum):
    SESSION = "Session"
    USER = "User"
    AGENT = "Agent"
    ORGANIZATION = "Organization"


class KnowledgeBaseMode(str, Enum):
    CONTEXT = "Context"
    TOOL = "Tool"


class ToolType(str, Enum):
    REMOTE = "Remote"
    LOCAL = "Local"


class AgentToolRef(BaseModel):
    tool_id: UUID
    tool_name: str | None = None
    tool_type: ToolType


class KnowledgeBaseRef(BaseModel):
    knowledge_base_id: UUID
    knowledge_base_name: str | None = None
    mode: KnowledgeBaseMode


class MemoryConfig(BaseModel):
    enabled: bool = False
    scope: AgentMemoryScope | None = None
    retention: str | None = None
    instructions: str | None = None


class ModelConfig(BaseModel):
    model_id: UUID
    name: str | None = None
    model_identifier: str
    provider: str = "openai"
    base_url: str | None = None
    group_ids: list[UUID] = Field(default_factory=list)


class RuntimeManifest(BaseModel):
    agent_id: UUID
    name: str
    status: str
    group_ids: list[UUID] = Field(default_factory=list)
    system_prompt: str
    temperature: float = 0.7
    model: ModelConfig
    tools: list[AgentToolRef] = Field(default_factory=list)
    knowledge_bases: list[KnowledgeBaseRef] = Field(default_factory=list)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    manifest_hash: str = ""
    revision_id: UUID | None = None

    @property
    def is_published(self) -> bool:
        return self.status.lower() == "published"

    @property
    def has_tools(self) -> bool:
        tool_mode_kbs = any(kb.mode == KnowledgeBaseMode.TOOL for kb in self.knowledge_bases)
        return bool(self.tools) or tool_mode_kbs
