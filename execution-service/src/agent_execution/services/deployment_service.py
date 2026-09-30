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
from agent_execution.services.key_crypto import decrypt_key, encrypt_key
from agent_execution.services.manifest_service import ManifestService
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_DEV_SECRET = "dev-only-change-me"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "agent").lower()).strip("-")[:50].strip("-")
    return slug if len(slug) >= 2 else "agent"


class DeploymentService:
    """One published endpoint per agent. The API key is stored encrypted and always returned to the owner."""

    def __init__(self, repo: DeploymentRepository, manifests: ManifestService, settings: Settings) -> None:
        self._repo = repo
        self._manifests = manifests
        self._settings = settings
        if settings.api_key_encryption_secret == _DEV_SECRET:
            logger.warning(
                "API_KEY_ENCRYPTION_SECRET is the development default. Set a private secret before production."
            )

    async def create(
        self,
        agent_id: UUID,
        request: CreateDeploymentRequest,
        bearer_token: str | None,
        request_base: str,
    ) -> DeploymentResponse:
        retention = self._retention(request.retention_policy)
        manifest = await self._manifests.resolve(
            agent_id,
            bearer_token,
            revision_id=request.revision_id,
            published_only=True,
        )
        existing = await self._repo.get_by_agent(agent_id)
        if existing is not None:
            return await self._response_with_key(dict(existing), request_base)

        slug = await self._choose_slug(request.slug, manifest.name)
        api_key = self._new_key()
        deployment_id = uuid4()
        try:
            await self._repo.insert(
                deployment_id=deployment_id,
                agent_id=agent_id,
                slug=slug,
                revision_id=manifest.revision_id or request.revision_id,
                api_key_hash=hash_api_key(api_key),
                api_key_enc=encrypt_key(self._settings.api_key_encryption_secret, api_key),
                retention_policy=retention.value,
            )
        except Exception as exc:
            if "duplicate key" not in str(exc).lower() and "unique" not in str(exc).lower():
                raise
            raced = await self._repo.get_by_agent(agent_id)
            if raced is None:
                raise ServiceError("CONFLICT", f"Slug '{slug}' is already in use.", 409) from exc
            return await self._response_with_key(dict(raced), request_base)
        logger.info("deployment.created deploymentId=%s agentId=%s slug=%s", deployment_id, agent_id, slug)
        row = await self._repo.get_by_agent(agent_id)
        return self._row(dict(row), request_base, api_key, reissued=False)

    async def list(
        self, agent_id: UUID, bearer_token: str | None, request_base: str
    ) -> list[DeploymentResponse]:
        await self._manifests.resolve(agent_id, bearer_token)
        rows = await self._repo.list_for_agent(agent_id)
        return [await self._response_with_key(dict(row), request_base) for row in rows]

    async def rotate(
        self,
        agent_id: UUID,
        deployment_id: UUID,
        bearer_token: str | None,
        request_base: str,
    ) -> DeploymentResponse:
        await self._manifests.resolve(agent_id, bearer_token)
        row = await self._owned(agent_id, deployment_id)
        return await self._reissue(dict(row), request_base)

    async def authenticate(self, slug: str, api_key: str | None):
        row = await self._row_for_key(api_key)
        if row["slug"] != slug:
            raise ServiceError("UNAUTHORIZED", "API key is not valid for this agent.", 401)
        return row

    async def authenticate_for_agent(self, agent_id: UUID, api_key: str | None):
        row = await self._row_for_key(api_key)
        if row["agent_id"] != agent_id:
            raise ServiceError("UNAUTHORIZED", "API key is not valid for this agent.", 401)
        return row

    async def require_published(self, agent_id: UUID) -> None:
        await self._manifests.resolve(agent_id, None, published_only=True)

    async def _response_with_key(self, row: dict, request_base: str) -> DeploymentResponse:
        revealed = decrypt_key(self._settings.api_key_encryption_secret, row.get("api_key_enc"))
        if revealed:
            return self._row(row, request_base, revealed, reissued=False)
        logger.warning(
            "deployment.key_missing deploymentId=%s agentId=%s; issuing a replacement key",
            row["deployment_id"],
            row["agent_id"],
        )
        return await self._reissue(row, request_base)

    async def _reissue(self, row: dict, request_base: str) -> DeploymentResponse:
        api_key = self._new_key()
        await self._repo.rotate_key(
            row["deployment_id"],
            hash_api_key(api_key),
            encrypt_key(self._settings.api_key_encryption_secret, api_key),
        )
        return self._row(row, request_base, api_key, reissued=True)

    async def _owned(self, agent_id: UUID, deployment_id: UUID):
        for row in await self._repo.list_for_agent(agent_id):
            if row["deployment_id"] == deployment_id:
                return row
        raise ServiceError("NOT_FOUND", "Deployment not found.", 404)

    async def _row_for_key(self, api_key: str | None):
        if not api_key:
            raise ServiceError("UNAUTHORIZED", "X-Api-Key is required.", 401)
        row = await self._repo.get_by_api_key_hash(hash_api_key(api_key))
        if row is None or not row["enabled"]:
            raise ServiceError("UNAUTHORIZED", "API key is not valid for this agent.", 401)
        return row

    async def _choose_slug(self, requested: str | None, agent_name: str) -> str:
        if requested:
            slug = requested.strip().lower()
            if not _SLUG.match(slug):
                raise ServiceError(
                    "VALIDATION_FAILED",
                    "slug must be 2-63 characters of lowercase letters, numbers, and hyphens.",
                    400,
                )
            if await self._repo.get_by_slug(slug):
                raise ServiceError("CONFLICT", f"Slug '{slug}' is already in use.", 409)
            return slug
        wanted = _slugify(agent_name)
        slug, number = wanted, 1
        while await self._repo.get_by_slug(slug):
            number += 1
            slug = f"{wanted[:58]}-{number}"
        return slug

    def _row(self, row: dict, request_base: str, api_key: str, *, reissued: bool) -> DeploymentResponse:
        base = (self._settings.public_base_url or request_base).rstrip("/")
        agent_id = row["agent_id"]
        return DeploymentResponse(
            deployment_id=row["deployment_id"],
            agent_id=agent_id,
            slug=row["slug"],
            revision_id=row["revision_id"],
            retention_policy=row["retention_policy"],
            enabled=row["enabled"],
            created_at=row.get("created_at") or datetime.now(timezone.utc),
            api_key=api_key,
            key_reissued=reissued,
            chat_url=f"{base}/api/v1/agents/{agent_id}/chat",
        )

    @staticmethod
    def _new_key() -> str:
        return f"ak_{secrets.token_urlsafe(32)}"

    @staticmethod
    def _retention(value: str) -> RetentionPolicy:
        try:
            return RetentionPolicy(value)
        except ValueError as exc:
            raise ServiceError("VALIDATION_FAILED", "Unknown retention policy.", 400) from exc
