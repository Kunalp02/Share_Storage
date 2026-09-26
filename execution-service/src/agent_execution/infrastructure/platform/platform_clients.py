from __future__ import annotations

from dataclasses import dataclass

from agent_execution.infrastructure.auth.service_token_provider import ServiceAuthTokenProvider
from agent_execution.infrastructure.http_pool import HttpClientPool
from agent_execution.infrastructure.platform.agent_config_client import AgentConfigClient
from agent_execution.infrastructure.platform.rag_ask_client import RagAskClient
from agent_execution.infrastructure.platform.rag_config_client import RagConfigClient
from agent_execution.infrastructure.platform.tools_config_client import ToolsConfigClient


@dataclass(frozen=True, slots=True)
class PlatformClients:
    agent: AgentConfigClient
    tools: ToolsConfigClient
    rag: RagConfigClient
    rag_ask: RagAskClient

    @classmethod
    def from_pool(
        cls,
        pool: HttpClientPool,
        token_provider: ServiceAuthTokenProvider | None = None,
        *,
        verify_ssl: bool = True,
    ) -> PlatformClients:
        return cls(
            agent=AgentConfigClient(pool.agent, token_provider, verify_ssl=verify_ssl),
            tools=ToolsConfigClient(pool.tools, token_provider, verify_ssl=verify_ssl),
            rag=RagConfigClient(pool.rag, token_provider, verify_ssl=verify_ssl),
            rag_ask=RagAskClient(pool.rag_ask, token_provider, verify_ssl=verify_ssl),
        )
