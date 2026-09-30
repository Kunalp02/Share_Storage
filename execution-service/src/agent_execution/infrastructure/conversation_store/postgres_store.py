from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from agent_execution.infrastructure.conversation_store.memory_store import ConversationVersionConflict
from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.infrastructure.persistence.database import Database
from agent_execution.services.conversation_models import ConversationHistory, ConversationTurn


class PostgresConversationHistoryStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _turns_to_json(history: ConversationHistory) -> str:
        return json.dumps([{"role": t.role, "content": t.content} for t in history.turns])

    @staticmethod
    def _turns_from_json(raw) -> ConversationHistory:
        items = json.loads(raw) if isinstance(raw, str) else raw
        turns: list[ConversationTurn] = []
        for item in items or []:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content is not None:
                turns.append(ConversationTurn(role, str(content)))
        return ConversationHistory(turns=turns)

    async def get_history(self, key: ConversationSessionKey) -> tuple[ConversationHistory, int | None]:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT turns, version, expires_at FROM conversation_histories
                WHERE agent_id = $1 AND session_id = $2 AND org_id = $3
                """,
                key.agent_id,
                key.session_id,
                key.org_id,
            )
        if row is None or _row_expired(row["expires_at"]):
            return ConversationHistory(), None
        version = int(row["version"])
        return self._turns_from_json(row["turns"]), version if version > 0 else None

    async def append_exchange(
        self,
        key: ConversationSessionKey,
        user_text: str,
        assistant_text: str,
        *,
        max_turn_pairs: int,
        max_chars: int,
        expected_version: int | None = None,
    ) -> tuple[ConversationHistory, int, bool]:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT turns, version, expires_at FROM conversation_histories
                    WHERE agent_id = $1 AND session_id = $2 AND org_id = $3
                    FOR UPDATE
                    """,
                    key.agent_id,
                    key.session_id,
                    key.org_id,
                )
                if row is None or _row_expired(row["expires_at"]):
                    current_version = 0 if row is None else int(row["version"])
                    history = ConversationHistory()
                else:
                    current_version = int(row["version"])
                    history = self._turns_from_json(row["turns"])
                if expected_version is not None and current_version != expected_version:
                    raise ConversationVersionConflict(current_version)
                history.append_exchange(user_text, assistant_text)
                trimmed, truncated = history.trim(max_turn_pairs, max_chars)
                next_version = current_version + 1
                execution_id = None
                try:
                    execution_id = uuid.UUID(key.session_id)
                except ValueError:
                    pass
                await conn.execute(
                    """
                    INSERT INTO conversation_histories (
                        agent_id, session_id, org_id, turns, version, updated_at, execution_id
                    ) VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7)
                    ON CONFLICT (agent_id, session_id, org_id)
                    DO UPDATE SET
                        turns = EXCLUDED.turns,
                        version = EXCLUDED.version,
                        updated_at = EXCLUDED.updated_at,
                        execution_id = COALESCE(EXCLUDED.execution_id, conversation_histories.execution_id)
                    """,
                    key.agent_id,
                    key.session_id,
                    key.org_id,
                    self._turns_to_json(trimmed),
                    next_version,
                    datetime.now(timezone.utc),
                    execution_id,
                )
        return ConversationHistory(turns=list(trimmed.turns)), next_version, truncated

    async def set_retention(self, key: ConversationSessionKey, expires_at: datetime | None) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversation_histories
                SET expires_at = $4
                WHERE agent_id = $1 AND session_id = $2 AND org_id = $3
                """,
                key.agent_id,
                key.session_id,
                key.org_id,
                expires_at,
            )

    async def delete_expired(self) -> int:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM conversation_histories
                WHERE expires_at IS NOT NULL AND expires_at <= NOW()
                """
            )
        return int(result.split()[-1])

    async def delete_for_thread(self, agent_id, thread_id) -> None:
        pool = await self._database.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM conversation_histories
                WHERE agent_id = $1 AND (execution_id = $2 OR session_id = $3)
                """,
                agent_id,
                thread_id,
                str(thread_id),
            )

    async def aclose(self) -> None:
        return None


def _row_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)
