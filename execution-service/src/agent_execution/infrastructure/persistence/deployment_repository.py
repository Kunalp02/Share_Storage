from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from agent_execution.infrastructure.persistence.database import Database


class DeploymentRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def insert(
        self,
        *,
        deployment_id: UUID,
        agent_id: UUID,
        slug: str,
        revision_id: UUID | None,
        api_key_hash: str,
        retention_policy: str,
    ) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO deployments (
                    deployment_id, agent_id, slug, revision_id,
                    api_key_hash, retention_policy, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                deployment_id,
                agent_id,
                slug,
                revision_id,
                api_key_hash,
                retention_policy,
                datetime.now(timezone.utc),
            )

    async def get_by_slug(self, slug: str):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM deployments WHERE slug = $1",
                slug,
            )

    async def get_by_api_key_hash(self, api_key_hash: str):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM deployments WHERE api_key_hash = $1 AND enabled = TRUE",
                api_key_hash,
            )

    async def list_for_agent(self, agent_id: UUID):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT * FROM deployments
                WHERE agent_id = $1
                ORDER BY created_at DESC
                """,
                agent_id,
            )
