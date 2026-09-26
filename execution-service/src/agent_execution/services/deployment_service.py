from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.persistence.deployment_repository import DeploymentRepository
from agent_execution.schemas.runs import CreateDeploymentRequest, DeploymentResponse
from agent_execution.schemas.threads import RetentionPolicy
from agent_execution.services.manifest_service import ManifestService

logger = logging.getLogger(__name__)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


class DeploymentService:
    def __init__(self, repo: DeploymentRepository, manifests: ManifestService) -> None:
        self._repo = repo
        self._manifests = manifests

    async def create(
        self, agent_id: UUID, request: CreateDeploymentRequest, bearer_token: str | None
    ) -> DeploymentResponse:
        slug = request.slug.strip().lower()
        if not _SLUG.match(slug):
            raise ServiceError(
                "VALIDATION_FAILED",
                "slug must be 2-63 characters of lowercase letters, numbers, and hyphens.",
                400,
            )
        try:
            retention = RetentionPolicy(request.retention_policy)
        except ValueError as exc:
            raise ServiceError("VALIDATION_FAILED", "Unknown retention policy.", 400) from exc
        manifest = await self._manifests.resolve(
            agent_id,
            bearer_token,
            revision_id=request.revision_id,
            published_only=True,
        )
        api_key = f"ak_{secrets.token_urlsafe(32)}"
        deployment_id = uuid4()
        await self._repo.insert(
            deployment_id=deployment_id,
            agent_id=agent_id,
            slug=slug,
            revision_id=manifest.revision_id or request.revision_id,
            api_key_hash=hash_api_key(api_key),
            retention_policy=retention.value,
        )
        logger.info(
            "deployment.created deploymentId=%s agentId=%s slug=%s revisionId=%s",
            deployment_id,
            agent_id,
            slug,
            manifest.revision_id or request.revision_id,
        )
        return DeploymentResponse(
            deployment_id=deployment_id,
            agent_id=agent_id,
            slug=slug,
            revision_id=manifest.revision_id or request.revision_id,
            retention_policy=retention.value,
            enabled=True,
            created_at=datetime.now(timezone.utc),
            api_key=api_key,
        )

    async def list(self, agent_id: UUID, bearer_token: str | None) -> list[DeploymentResponse]:
        await self._manifests.resolve(agent_id, bearer_token)
        return [self._row(row) for row in await self._repo.list_for_agent(agent_id)]

    async def authenticate(self, slug: str, api_key: str | None):
        if not api_key:
            raise ServiceError("UNAUTHORIZED", "X-Api-Key is required.", 401)
        row = await self._repo.get_by_api_key_hash(hash_api_key(api_key))
        if row is None or row["slug"] != slug or not row["enabled"]:
            raise ServiceError("UNAUTHORIZED", "API key is not valid for this agent.", 401)
        return row

    @staticmethod
    def _row(row, api_key: str | None = None) -> DeploymentResponse:
        return DeploymentResponse(
            deployment_id=row["deployment_id"],
            agent_id=row["agent_id"],
            slug=row["slug"],
            revision_id=row["revision_id"],
            retention_policy=row["retention_policy"],
            enabled=row["enabled"],
            created_at=row["created_at"],
            api_key=api_key,
        )
