from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id UUID PRIMARY KEY,
        agent_id UUID NOT NULL,
        channel VARCHAR(16) NOT NULL,
        execution_type VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        revision_id UUID NULL,
        manifest_hash TEXT NOT NULL DEFAULT '',
        manifest_snapshot JSONB NULL,
        deployment_id UUID NULL,
        retention_policy VARCHAR(32) NOT NULL,
        triggered_by TEXT NOT NULL DEFAULT '',
        expires_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_threads_agent_created
        ON threads (agent_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_threads_expires
        ON threads (expires_at) WHERE status = 'OPEN'
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id UUID PRIMARY KEY,
        thread_id UUID NOT NULL,
        agent_id UUID NOT NULL,
        status VARCHAR(32) NOT NULL,
        dispatch VARCHAR(16) NOT NULL,
        input TEXT NOT NULL,
        output TEXT NULL,
        error TEXT NULL,
        revision_id UUID NULL,
        manifest_hash TEXT NOT NULL DEFAULT '',
        attempt INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        worker_id TEXT NULL,
        lease_expires_at TIMESTAMPTZ NULL,
        idempotency_key TEXT NULL,
        input_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        output_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        steps JSONB NOT NULL DEFAULT '[]'::jsonb,
        retrieved_context JSONB NOT NULL DEFAULT '[]'::jsonb,
        stop_reason TEXT NULL,
        org_id TEXT NULL,
        started_by TEXT NOT NULL DEFAULT '',
        client_ip TEXT NOT NULL DEFAULT '',
        error_code TEXT NULL,
        available_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ NULL,
        completed_at TIMESTAMPTZ NULL
    )
    """,
    """
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_by TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS client_ip TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS error_code TEXT NULL
    """,
    """
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_heartbeats (
        worker_id TEXT PRIMARY KEY,
        last_seen_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_runs_thread_created
        ON runs (thread_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_runs_claim ON runs (status, created_at)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_idempotency
        ON runs (thread_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS deployments (
        deployment_id UUID PRIMARY KEY,
        agent_id UUID NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        revision_id UUID NULL,
        api_key_hash TEXT NOT NULL UNIQUE,
        retention_policy VARCHAR(32) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_histories (
        agent_id UUID NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        org_id TEXT NOT NULL DEFAULT '',
        turns JSONB NOT NULL DEFAULT '[]'::jsonb,
        version INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        execution_id UUID NULL,
        PRIMARY KEY (agent_id, session_id, org_id)
    )
    """,
    """
    ALTER TABLE conversation_histories
        ADD COLUMN IF NOT EXISTS execution_id UUID NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_conversation_execution
        ON conversation_histories (agent_id, execution_id)
    """,
    """
    ALTER TABLE deployments ADD COLUMN IF NOT EXISTS api_key_enc TEXT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_deployments_agent ON deployments (agent_id)
    """,
    """
    ALTER TABLE conversation_histories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_conversation_expires
        ON conversation_histories (expires_at)
        WHERE expires_at IS NOT NULL
    """,
]


class Database:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise RuntimeError("EXECUTION_DATABASE_URL is required.")
        self._database_url = database_url
        self._pool = None
        self._lock = asyncio.Lock()

    async def pool(self):
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                import asyncpg

                self._pool = await asyncpg.create_pool(
                    self._database_url, min_size=1, max_size=10
                )
                async with self._pool.acquire() as conn:
                    for statement in SCHEMA:
                        await conn.execute(statement)
                logger.info("Execution schema is ready")
        return self._pool

    async def ping(self) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
