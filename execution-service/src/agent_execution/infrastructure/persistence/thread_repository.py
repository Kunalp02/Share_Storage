from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from agent_execution.infrastructure.persistence.database import Database


class ThreadRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def insert(
        self,
        *,
        thread_id: UUID,
        agent_id: UUID,
        channel: str,
        execution_type: str,
        status: str,
        revision_id: UUID | None,
        manifest_hash: str,
        manifest_snapshot: dict | None,
        deployment_id: UUID | None,
        retention_policy: str,
        triggered_by: str,
        expires_at: datetime | None,
    ) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO threads (
                    thread_id, agent_id, channel, execution_type, status,
                    revision_id, manifest_hash, manifest_snapshot, deployment_id,
                    retention_policy, triggered_by, expires_at, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13)
                """,
                thread_id,
                agent_id,
                channel,
                execution_type,
                status,
                revision_id,
                manifest_hash,
                json.dumps(manifest_snapshot) if manifest_snapshot is not None else None,
                deployment_id,
                retention_policy,
                triggered_by,
                expires_at,
                datetime.now(timezone.utc),
            )

    async def get(self, agent_id: UUID, thread_id: UUID):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT * FROM threads
                WHERE thread_id = $1 AND agent_id = $2
                """,
                thread_id,
                agent_id,
            )

    async def get_by_id(self, thread_id: UUID):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM threads WHERE thread_id = $1",
                thread_id,
            )

    async def list_for_agent(
        self, agent_id: UUID, execution_type: str | None, limit: int, offset: int
    ):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            if execution_type:
                return await conn.fetch(
                    """
                    SELECT * FROM threads
                    WHERE agent_id = $1 AND execution_type = $2
                    ORDER BY created_at DESC
                    LIMIT $3 OFFSET $4
                    """,
                    agent_id,
                    execution_type,
                    limit,
                    offset,
                )
            return await conn.fetch(
                """
                SELECT * FROM threads
                WHERE agent_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                agent_id,
                limit,
                offset,
            )

    async def find_expired(self, limit: int = 50):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT thread_id, agent_id FROM threads
                WHERE expires_at IS NOT NULL
                  AND expires_at < $1
                  AND status = 'OPEN'
                ORDER BY expires_at
                LIMIT $2
                """,
                datetime.now(timezone.utc),
                limit,
            )

    async def mark_status(self, thread_id: UUID, status: str) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE threads SET status = $2 WHERE thread_id = $1",
                thread_id,
                status,
            )
