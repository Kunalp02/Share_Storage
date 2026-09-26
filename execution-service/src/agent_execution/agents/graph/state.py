from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentGraphState(TypedDict, total=False):
    agent_id: str
    user_input: str
    session_id: str
    org_id: str | None
    bearer_token: str | None
    thread_id: str
    run_id: str
    execution_type: str | None
    input_artifact_ids: list[str]
    manifest: dict[str, Any]
    system_prompt: str
    llm_input: str
    output: str
    stop_reason: str | None
    messages: list[dict[str, Any]]
    history_turns: list[dict[str, str]]
    memory_scope: str | None
    history_total_turns: int
    history_turns_in_prompt: int
    history_truncated: bool
    memory_persisted: bool
    has_tools: bool
    tool_round: int
    max_tool_rounds: int
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    artifact_block: str | None
    steps: Annotated[list[str], operator.add]
