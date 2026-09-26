from __future__ import annotations

import logging
from uuid import UUID

import httpx

from agent_execution.core.exceptions import ServiceError
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


class StorageClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.storage_service_base_url.rstrip("/")
        self._verify = settings.verify_ssl
        self._internal_key = settings.storage_internal_api_key
        self._max_chars = settings.artifact_prompt_max_chars

    def _enabled(self) -> bool:
        return bool(self._base and self._internal_key)

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Api-Key": self._internal_key}

    async def delete_thread_artifacts(self, thread_id: UUID) -> int:
        if not self._enabled():
            return 0
        url = f"{self._base}/api/v1/internal/threads/{thread_id}/artifacts"
        async with httpx.AsyncClient(verify=self._verify, timeout=60.0) as client:
            response = await client.delete(url, headers=self._headers())
        if response.status_code >= 400:
            response.raise_for_status()
        return int(response.json().get("deletedCount") or 0)

    async def fetch_artifact_text(self, artifact_id: UUID) -> dict:
        if not self._enabled():
            raise ServiceError("STORAGE_UNAVAILABLE", "Storage service is not configured.", 503)
        url = f"{self._base}/api/v1/internal/artifacts/{artifact_id}/content"
        async with httpx.AsyncClient(verify=self._verify, timeout=60.0) as client:
            response = await client.get(url, headers=self._headers(), params={"maxChars": self._max_chars})
        if response.status_code >= 400:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                f"Could not read artifact {artifact_id}: {response.text[:200]}",
                502,
            )
        return response.json()

    async def put_text_artifact(
        self,
        *,
        thread_id: UUID,
        agent_id: UUID,
        run_id: UUID,
        filename: str,
        text: str,
        artifact_type: str = "OUTPUT",
        expires_at: str | None = None,
    ) -> UUID | None:
        if not self._enabled():
            return None
        url = f"{self._base}/api/v1/internal/threads/{thread_id}/artifacts"
        payload = {
            "agentId": str(agent_id),
            "runId": str(run_id),
            "filename": filename,
            "contentType": "text/plain",
            "text": text,
            "artifactType": artifact_type,
            "expiresAt": expires_at,
        }
        async with httpx.AsyncClient(verify=self._verify, timeout=60.0) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            logger.warning("Output artifact upload failed: %s", response.text[:300])
            return None
        artifact_id = response.json().get("artifactId")
        return UUID(str(artifact_id)) if artifact_id else None
