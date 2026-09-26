from __future__ import annotations

from typing import Literal

from agent_execution.agents.graph.state import AgentGraphState


def route_after_llm(state: AgentGraphState) -> Literal["run_tools", "finalize_answer", "persist_memory"]:
    if not state.get("has_tools"):
        return "persist_memory"
    tool_round = state.get("tool_round", 0)
    max_rounds = state.get("max_tool_rounds", 5)
    if not state.get("tool_calls"):
        return "persist_memory"
    if tool_round >= max_rounds:
        return "finalize_answer"
    return "run_tools"
