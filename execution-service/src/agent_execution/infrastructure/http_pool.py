from __future__ import annotations

import httpx

from agent_execution.settings import Settings


def _base(url: str) -> str:
    return url.rstrip("/") if url else "http://127.0.0.1:9"


class HttpClientPool:
    def __init__(self, settings: Settings) -> None:
        timeout = httpx.Timeout(60.0, connect=10.0)
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        verify = settings.verify_ssl
        self.agent = httpx.AsyncClient(
            base_url=_base(settings.agent_config_base_url), timeout=timeout, limits=limits, verify=verify
        )
        self.tools = httpx.AsyncClient(
            base_url=_base(settings.tools_config_base_url), timeout=timeout, limits=limits, verify=verify
        )
        self.rag = httpx.AsyncClient(
            base_url=_base(settings.rag_config_base_url), timeout=timeout, limits=limits, verify=verify
        )
        self.auth = httpx.AsyncClient(
            base_url=_base(settings.auth_service_base_url), timeout=timeout, limits=limits, verify=verify
        )
        self.rag_ask = httpx.AsyncClient(
            base_url=_base(settings.rag_ask_base_url), timeout=timeout, limits=limits, verify=verify
        )

    async def aclose(self) -> None:
        await self.agent.aclose()
        await self.tools.aclose()
        await self.rag.aclose()
        await self.auth.aclose()
        await self.rag_ask.aclose()
