from __future__ import annotations

from dataclasses import dataclass, field

from platform_auth import PlatformTokenVerifier, parse_codes

from agent_execution.agents.graph.context import AgentGraphContext
from agent_execution.infrastructure.auth.service_token_provider import ServiceAuthTokenProvider
from agent_execution.infrastructure.conversation_store.factory import create_conversation_history_store
from agent_execution.infrastructure.conversation_store.postgres_store import PostgresConversationHistoryStore
from agent_execution.infrastructure.http_pool import HttpClientPool
from agent_execution.infrastructure.persistence.database import Database
from agent_execution.infrastructure.persistence.deployment_repository import DeploymentRepository
from agent_execution.infrastructure.persistence.run_repository import RunRepository
from agent_execution.infrastructure.persistence.thread_repository import ThreadRepository
from agent_execution.infrastructure.platform.platform_clients import PlatformClients
from agent_execution.services.agent_execution_service import AgentExecutionService
from agent_execution.services.cleanup_service import CleanupService
from agent_execution.services.deployment_service import DeploymentService
from agent_execution.services.run_slots import RunSlots
from agent_execution.services.storage_client import StorageClient
from agent_execution.services.thread_service import ThreadService
from agent_execution.services.worker import ExecutionWorker
from agent_execution.settings import Settings


@dataclass
class ApplicationContainer:
    settings: Settings
    database: Database = field(init=False)
    http_pool: HttpClientPool = field(init=False)
    token_provider: ServiceAuthTokenProvider = field(init=False)
    platform_auth: PlatformTokenVerifier = field(init=False)
    platform: PlatformClients = field(init=False)
    graph_context: AgentGraphContext = field(init=False)
    threads: ThreadRepository = field(init=False)
    runs: RunRepository = field(init=False)
    deployments: DeploymentRepository = field(init=False)
    thread_service: ThreadService = field(init=False)
    deployment_service: DeploymentService = field(init=False)
    execution_service: AgentExecutionService = field(init=False)
    cleanup_service: CleanupService = field(init=False)
    worker: ExecutionWorker = field(init=False)

    def __post_init__(self) -> None:
        self.database = Database(self.settings.database_url())
        self.http_pool = HttpClientPool(self.settings)
        self.token_provider = ServiceAuthTokenProvider(self.settings, self.http_pool.auth)
        self.platform_auth = PlatformTokenVerifier(
            configured=bool(self.settings.auth_service_base_url.strip()),
            http=self.http_pool.auth,
            me_path=self.settings.auth_me_path,
            cache_ttl_seconds=self.settings.auth_principal_cache_seconds,
            required_permissions=parse_codes(self.settings.auth_required_permissions),
        )
        self.platform = PlatformClients.from_pool(
            self.http_pool, self.token_provider, verify_ssl=self.settings.verify_ssl
        )
        conversations = create_conversation_history_store(self.database)
        storage = StorageClient(self.settings)
        self.graph_context = AgentGraphContext.create(
            self.settings, self.platform, conversations, storage, self.token_provider
        )
        self.threads = ThreadRepository(self.database)
        self.runs = RunRepository(self.database)
        self.deployments = DeploymentRepository(self.database)
        self.thread_service = ThreadService(self.settings, self.threads, self.graph_context.manifest_service)
        self.deployment_service = DeploymentService(
            self.deployments, self.graph_context.manifest_service, self.settings
        )
        self.execution_service = AgentExecutionService(
            self.settings,
            self.graph_context,
            self.thread_service,
            self.runs,
            RunSlots(self.settings),
        )
        if not isinstance(conversations, PostgresConversationHistoryStore):
            raise RuntimeError("Conversation history must use the execution database.")
        self.cleanup_service = CleanupService(self.threads, self.runs, conversations, storage)
        self.worker = ExecutionWorker(self.settings, self.runs, self.execution_service, self.cleanup_service)

    async def shutdown(self) -> None:
        await self.graph_context.aclose()
        await self.database.aclose()
        await self.http_pool.aclose()


_container: ApplicationContainer | None = None


def get_container(settings: Settings) -> ApplicationContainer:
    global _container
    if _container is None:
        _container = ApplicationContainer(settings)
    return _container


async def shutdown_container() -> None:
    global _container
    if _container is not None:
        await _container.shutdown()
        _container = None
