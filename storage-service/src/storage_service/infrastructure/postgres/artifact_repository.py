from __future__ import annotations

import asyncio
import json

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id UUID PRIMARY KEY,
        agent_id UUID NOT NULL,
        execution_id UUID NOT NULL,
        thread_id UUID NULL,
        run_id UUID NULL,
        created_by TEXT NOT NULL DEFAULT '',
        artifact_type VARCHAR(32) NOT NULL,
        filename VARCHAR(512) NOT NULL,
        content_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
        size_bytes BIGINT NULL,
        storage_key TEXT NOT NULL,
        checksum_sha256 VARCHAR(128) NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        expires_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB NULL
    )
    """,
    "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS thread_id UUID NULL",
    "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS run_id UUID NULL",
    "UPDATE artifacts SET thread_id = execution_id WHERE thread_id IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_artifacts_thread ON artifacts (thread_id)",
    "CREATE INDEX IF NOT EXISTS ix_artifacts_run ON artifacts (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_artifacts_execution_id ON artifacts (execution_id)",
]


class ArtifactRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise RuntimeError("POSTGRES_URL is required.")
        self._database_url = database_url
        self._pool = None
        self._lock = asyncio.Lock()

    async def _pool_or_create(self):
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                import asyncpg

                self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=10)
                async with self._pool.acquire() as conn:
                    for statement in SCHEMA:
                        await conn.execute(statement)
        return self._pool

    async def insert_pending(
        self,
        *,
        artifact_id,
        agent_id,
        thread_id,
        run_id,
        created_by: str,
        artifact_type: str,
        filename: str,
        content_type: str,
        storage_key: str,
        expires_at,
        metadata: dict | None,
        status: str = "PENDING",
        size_bytes: int | None = None,
    ) -> None:
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, agent_id, execution_id, thread_id, run_id, created_by,
                    artifact_type, filename, content_type, storage_key, status,
                    expires_at, metadata, size_bytes
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14)
                """,
                artifact_id,
                agent_id,
                thread_id,
                thread_id,
                run_id,
                created_by,
                artifact_type,
                filename,
                content_type,
                storage_key,
                status,
                expires_at,
                json.dumps(metadata or {}),
                size_bytes,
            )

    async def get(self, artifact_id):
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM artifacts WHERE artifact_id = $1 AND status != 'DELETED'",
                artifact_id,
            )

    async def list_for_thread(self, thread_id, artifact_type: str | None):
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            if artifact_type:
                return await conn.fetch(
                    """
                    SELECT * FROM artifacts
                    WHERE (thread_id = $1 OR execution_id = $1)
                      AND status != 'DELETED' AND artifact_type = $2
                    ORDER BY created_at
                    """,
                    thread_id,
                    artifact_type,
                )
            return await conn.fetch(
                """
                SELECT * FROM artifacts
                WHERE (thread_id = $1 OR execution_id = $1) AND status != 'DELETED'
                ORDER BY created_at
                """,
                thread_id,
            )

    async def mark_ready(self, artifact_id, size_bytes: int, checksum: str | None) -> None:
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE artifacts
                SET status = 'READY', size_bytes = $2, checksum_sha256 = $3
                WHERE artifact_id = $1 AND status = 'PENDING'
                """,
                artifact_id,
                size_bytes,
                checksum,
            )

    async def list_keys_for_thread(self, thread_id):
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT artifact_id, storage_key FROM artifacts
                WHERE thread_id = $1 OR execution_id = $1
                """,
                thread_id,
            )

    async def mark_deleted_for_thread(self, thread_id) -> None:
        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE artifacts SET status = 'DELETED'
                WHERE thread_id = $1 OR execution_id = $1
                """,
                thread_id,
            )

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
