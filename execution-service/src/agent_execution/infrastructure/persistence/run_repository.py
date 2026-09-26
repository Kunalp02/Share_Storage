from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from agent_execution.infrastructure.persistence.database import Database


def _loads(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


class RunRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def insert(
        self,
        *,
        run_id: UUID,
        thread_id: UUID,
        agent_id: UUID,
        status: str,
        dispatch: str,
        user_input: str,
        revision_id: UUID | None,
        manifest_hash: str,
        attempt: int,
        max_attempts: int,
        worker_id: str | None,
        lease_expires_at: datetime | None,
        idempotency_key: str | None,
        input_artifact_ids: list[str],
        org_id: str | None,
        started_at: datetime | None,
        started_by: str = "",
        client_ip: str = "",
    ):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            if idempotency_key:
                existing = await conn.fetchrow(
                    """
                    SELECT * FROM runs
                    WHERE thread_id = $1 AND idempotency_key = $2
                    """,
                    thread_id,
                    idempotency_key,
                )
                if existing is not None:
                    return existing, False
            await conn.execute(
                """
                INSERT INTO runs (
                    run_id, thread_id, agent_id, status, dispatch, input,
                    revision_id, manifest_hash, attempt, max_attempts, worker_id,
                    lease_expires_at, idempotency_key, input_artifact_ids, org_id,
                    started_by, client_ip, created_at, started_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15,$16,$17,$18,$19
                )
                """,
                run_id,
                thread_id,
                agent_id,
                status,
                dispatch,
                user_input,
                revision_id,
                manifest_hash,
                attempt,
                max_attempts,
                worker_id,
                lease_expires_at,
                idempotency_key,
                json.dumps(input_artifact_ids),
                org_id,
                started_by,
                client_ip,
                datetime.now(timezone.utc),
                started_at,
            )
            row = await conn.fetchrow("SELECT * FROM runs WHERE run_id = $1", run_id)
            return row, True

    async def get(self, run_id: UUID):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM runs WHERE run_id = $1", run_id)

    async def list_for_thread(self, thread_id: UUID, limit: int, offset: int):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT * FROM runs
                WHERE thread_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                thread_id,
                limit,
                offset,
            )

    async def claim_next(self, worker_id: str, lease_seconds: int):
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                """
                WITH candidate AS (
                    SELECT run_id
                    FROM runs
                    WHERE dispatch = 'ASYNC'
                      AND (
                        status = 'QUEUED'
                        OR (
                            status = 'RUNNING'
                            AND lease_expires_at IS NOT NULL
                            AND lease_expires_at < NOW()
                            AND attempt < max_attempts
                        )
                      )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE runs AS r
                SET status = 'RUNNING',
                    attempt = r.attempt + 1,
                    worker_id = $1,
                    lease_expires_at = NOW() + make_interval(secs => $2),
                    started_at = COALESCE(r.started_at, NOW()),
                    error = NULL
                FROM candidate AS c
                WHERE r.run_id = c.run_id
                RETURNING r.*
                """,
                worker_id,
                lease_seconds,
            )

    async def heartbeat(self, run_id: UUID, worker_id: str, lease_seconds: int) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE runs
                SET lease_expires_at = NOW() + make_interval(secs => $3)
                WHERE run_id = $1 AND worker_id = $2 AND status = 'RUNNING'
                """,
                run_id,
                worker_id,
                lease_seconds,
            )

    async def mark_succeeded(
        self,
        run_id: UUID,
        *,
        output: str,
        output_artifact_ids: list[str],
        steps: list[str],
        retrieved_context: list,
        stop_reason: str | None,
        manifest_hash: str,
        revision_id: UUID | None,
    ) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE runs
                SET status = 'SUCCEEDED',
                    output = $2,
                    output_artifact_ids = $3::jsonb,
                    steps = $4::jsonb,
                    retrieved_context = $5::jsonb,
                    stop_reason = $6,
                    manifest_hash = $7,
                    revision_id = COALESCE($8, revision_id),
                    completed_at = $9,
                    lease_expires_at = NULL
                WHERE run_id = $1
                """,
                run_id,
                output,
                json.dumps(output_artifact_ids),
                json.dumps(steps),
                json.dumps(retrieved_context),
                stop_reason,
                manifest_hash,
                revision_id,
                datetime.now(timezone.utc),
            )

    async def mark_failed(self, run_id: UUID, error: str, *, requeue: bool) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            if requeue:
                await conn.execute(
                    """
                    UPDATE runs
                    SET status = 'QUEUED',
                        error = $2,
                        worker_id = NULL,
                        lease_expires_at = NULL
                    WHERE run_id = $1
                    """,
                    run_id,
                    error[:2000],
                )
                return
            await conn.execute(
                """
                UPDATE runs
                SET status = 'FAILED',
                    error = $2,
                    completed_at = $3,
                    lease_expires_at = NULL
                WHERE run_id = $1
                """,
                run_id,
                error[:2000],
                datetime.now(timezone.utc),
            )

    async def fail_expired_sync(self) -> int:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE runs
                SET status = 'FAILED',
                    error = 'Run interrupted before completion.',
                    completed_at = NOW(),
                    lease_expires_at = NULL
                WHERE dispatch = 'SYNC'
                  AND status = 'RUNNING'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < NOW()
                """
            )
        return int(result.split()[-1])
