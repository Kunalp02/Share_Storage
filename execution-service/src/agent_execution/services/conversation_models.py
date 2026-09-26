from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class MemoryContext:
    session_id: str | None = None
    org_id: str | None = None


@dataclass
class ConversationTurn:
    role: Role
    content: str


@dataclass
class ConversationHistory:
    turns: list[ConversationTurn] = field(default_factory=list)

    def append_exchange(self, user_text: str, assistant_text: str) -> None:
        self.turns.append(ConversationTurn("user", user_text.strip()))
        self.turns.append(ConversationTurn("assistant", assistant_text.strip()))

    def trim(self, max_turn_pairs: int, max_chars: int) -> tuple[ConversationHistory, bool]:
        turns = list(self.turns)
        truncated = False
        while len(turns) > max_turn_pairs * 2:
            turns = turns[2:]
            truncated = True
        while turns and sum(len(t.content) for t in turns) > max_chars:
            turns = turns[2:]
            truncated = True
        return ConversationHistory(turns=turns), truncated

    @classmethod
    def from_storage(cls, raw: Any) -> ConversationHistory:
        if raw is None:
            return cls()
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return cls()
        if not isinstance(raw, dict):
            return cls()
        turns_raw = raw.get("turns")
        if not isinstance(turns_raw, list):
            return cls()
        turns: list[ConversationTurn] = []
        for item in turns_raw:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content is not None:
                turns.append(ConversationTurn(role, content))
        return cls(turns=turns)
