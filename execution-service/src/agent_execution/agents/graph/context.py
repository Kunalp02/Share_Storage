from __future__ import annotations

from dataclasses import dataclass

from agent_execution.infrastructure.auth.service_token_provider import ServiceAuthTokenProvider
from agent_execution.infrastructure.conversation_store.base import ConversationHistoryStore
from agent_execution.infrastructure.llm_gateway import BifrostLlmGateway
from agent_execution.infrastructure.platform.platform_clients import PlatformClients
from agent_execution.services.context_manager import ContextManager
from agent_execution.services.conversation_memory_service import ConversationMemoryService
from agent_execution.services.manifest_service import ManifestService, RagContextService
from agent_execution.services.storage_client import StorageClient
from agent_execution.services.tool_execution_service import ToolExecutionService
from agent_execution.settings import Settings


@dataclass(frozen=True, slots=True)
class AgentGraphContext:
    settings: Settings
    manifest_service: ManifestService
    memory_service: ConversationMemoryService
    context_manager: ContextManager
    conversation_store: ConversationHistoryStore
    rag_service: RagContextService
    llm_gateway: BifrostLlmGateway
    tool_service: ToolExecutionService
    storage: StorageClient

    @classmethod
    def create(
        cls,
        settings: Settings,
        platform: PlatformClients,
        conversation_store: ConversationHistoryStore,
        storage: StorageClient,
        token_provider: ServiceAuthTokenProvider | None = None,
    ) -> AgentGraphContext:
        memory = ConversationMemoryService(settings, conversation_store)
        rag = RagContextService(platform)
        return cls(
            settings=settings,
            manifest_service=ManifestService(settings, platform),
            memory_service=memory,
            context_manager=ContextManager(settings, memory, conversation_store, rag, storage),
            conversation_store=conversation_store,
            rag_service=rag,
            llm_gateway=BifrostLlmGateway(settings, token_provider),
            tool_service=ToolExecutionService(platform),
            storage=storage,
        )

    async def aclose(self) -> None:
        await self.memory_service.aclose()
        await self.llm_gateway.aclose()
