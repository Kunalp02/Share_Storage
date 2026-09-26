from __future__ import annotations

import httpx

from storage_service.core.exceptions import ServiceError
from storage_service.settings import Settings


class AgentConfigClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.agent_config_base_url.rstrip("/")
        self._verify = settings.verify_ssl

    async def assert_agent_access(self, agent_id, bearer_token: str) -> None:
        if not bearer_token:
            raise ServiceError("UNAUTHORIZED", "Authorization bearer token required.", 401)
        if not self._base:
            raise ServiceError("AGENT_CONFIG_ERROR", "Agent config URL is not configured.", 503)
        url = f"{self._base}/api/v1/agents/{agent_id}/runtime-manifest"
        async with httpx.AsyncClient(verify=self._verify, timeout=15.0) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {bearer_token}"})
        if response.status_code == 404:
            raise ServiceError("FORBIDDEN", "Agent not found or not accessible.", 403)
        if response.status_code >= 400:
            raise ServiceError("AGENT_CONFIG_ERROR", f"Agent Config returned {response.status_code}", 502)


class ExecutionClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.execution_service_base_url.rstrip("/")
        self._verify = settings.verify_ssl

    async def resolve_thread(self, agent_id, thread_id, mode: str, bearer_token: str) -> dict:
        if not self._base:
            raise ServiceError("EXECUTION_SERVICE_ERROR", "Execution service URL is not configured.", 503)
        url = f"{self._base}/api/v1/agents/{agent_id}/threads/resolve"
        payload: dict = {"mode": mode}
        if thread_id is not None:
            payload["threadId"] = str(thread_id)
        async with httpx.AsyncClient(verify=self._verify, timeout=15.0) as client:
            response = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {bearer_token}"}
            )
        if response.status_code >= 400:
            raise ServiceError(
                "EXECUTION_SERVICE_ERROR",
                f"Thread resolve failed ({response.status_code}): {response.text[:300]}",
                502,
            )
        return response.json()
