from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from agent_execution.agents.graph.context import AgentGraphContext
from agent_execution.agents.graph.state import AgentGraphState
from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.llm_gateway import LlmToolCall
from agent_execution.schemas.runtime import RuntimeManifest
from agent_execution.services.tool_definition_service import ToolDefinitionService

logger = logging.getLogger(__name__)

_FINALIZE_PROMPT = (
    "You have reached the maximum number of tool calls allowed for this request. "
    "Provide your best final answer using the information gathered so far."
)


def _tool_calls_to_state(calls: list[LlmToolCall]) -> list[dict[str, Any]]:
    return [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in calls]


def _assistant_message(content: str, tool_calls: list[LlmToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=True)},
            }
            for call in tool_calls
        ]
    return message


def _messages_for_llm(state: AgentGraphState) -> list[dict[str, Any]]:
    messages = state.get("messages")
    if messages:
        return list(messages)
    return [
        {"role": "system", "content": state["system_prompt"]},
        {"role": "user", "content": state["llm_input"]},
    ]


class AgentGraphNodes:
    def __init__(self, context: AgentGraphContext) -> None:
        self._ctx = context

    async def prepare_context(self, state: AgentGraphState) -> AgentGraphState:
        agent_id = uuid.UUID(state["agent_id"])
        bearer_token = state.get("bearer_token")
        if state.get("manifest"):
            manifest = RuntimeManifest.model_validate(state["manifest"])
        else:
            manifest = await self._ctx.manifest_service.resolve(agent_id, bearer_token)
        thread = {
            "thread_id": state.get("thread_id") or state.get("session_id") or str(uuid.uuid4()),
            "expires_at": state.get("thread_expires_at"),
            "retention_policy": state.get("retention_policy"),
        }
        prepared = await self._ctx.context_manager.prepare(
            manifest=manifest,
            thread=thread,
            user_input=state["user_input"],
            artifact_ids=state.get("input_artifact_ids") or [],
            bearer_token=bearer_token,
        )
        return {
            "manifest": manifest.model_dump(mode="json"),
            **prepared.as_state(),
            "has_tools": manifest.has_tools,
            "tool_round": 0,
            "max_tool_rounds": self._ctx.settings.max_tool_rounds,
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": None,
            "steps": ["prepare_context", *prepared.steps],
        }

    async def call_llm(self, state: AgentGraphState) -> AgentGraphState:
        manifest = RuntimeManifest.model_validate(state["manifest"])
        messages = _messages_for_llm(state)
        tool_round = state.get("tool_round", 0)
        tools = ToolDefinitionService.build_openai_tools(manifest) if manifest.has_tools else None
        result = await self._ctx.llm_gateway.chat_with_messages(
            model=manifest.model.model_identifier,
            messages=messages,
            temperature=manifest.temperature,
            bearer_token=state.get("bearer_token"),
            tools=tools,
            base_url=manifest.model.base_url,
        )
        updated = messages + [_assistant_message(result.content, result.tool_calls)]
        return {
            "output": result.content,
            "messages": updated,
            "tool_calls": _tool_calls_to_state(result.tool_calls),
            "stop_reason": "completed" if not result.tool_calls else None,
            "steps": [f"call_llm:r{tool_round}"],
        }

    async def run_tools(self, state: AgentGraphState) -> AgentGraphState:
        manifest = RuntimeManifest.model_validate(state["manifest"])
        messages = list(_messages_for_llm(state))
        tool_round = state.get("tool_round", 0) + 1

        async def execute_call(call: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            name = call.get("name")
            args = call.get("arguments") or {}
            call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}")
            if not name:
                raise ServiceError("TOOL_ERROR", "Tool call is missing a name.", 400)
            if not isinstance(args, dict):
                args = {"input": args}
            try:
                output = await self._ctx.tool_service.run(
                    manifest, str(name), args, state.get("bearer_token"), state["user_input"]
                )
            except ServiceError as exc:
                logger.warning("tool.failed name=%s code=%s detail=%s", name, exc.code, exc)
                output = json.dumps(
                    {
                        "status": "unavailable",
                        "tell_user": "Something went wrong while looking this up. Please try again.",
                    }
                )
                return {"id": call_id, "name": str(name), "output": output}, f"tool.failed:{name}:{exc.code}"
            return {"id": call_id, "name": str(name), "output": output}, None

        pairs = await asyncio.gather(*(execute_call(call) for call in state.get("tool_calls") or []))
        executed = [item for item, _ in pairs]
        failures = [step for _, step in pairs if step]
        for item in executed:
            messages.append({"role": "tool", "tool_call_id": item["id"], "content": item["output"]})
        return {
            "messages": messages,
            "tool_calls": [],
            "tool_results": list(state.get("tool_results") or []) + executed,
            "tool_round": tool_round,
            "steps": [f"run_tools:r{tool_round}", *failures],
        }

    async def finalize_answer(self, state: AgentGraphState) -> AgentGraphState:
        manifest = RuntimeManifest.model_validate(state["manifest"])
        messages = list(_messages_for_llm(state))
        messages.append({"role": "user", "content": _FINALIZE_PROMPT})
        result = await self._ctx.llm_gateway.chat_with_messages(
            model=manifest.model.model_identifier,
            messages=messages,
            temperature=manifest.temperature,
            bearer_token=state.get("bearer_token"),
            tools=None,
            base_url=manifest.model.base_url,
        )
        return {
            "output": result.content,
            "messages": messages + [{"role": "assistant", "content": result.content}],
            "tool_calls": [],
            "stop_reason": "max_tool_rounds",
            "steps": ["finalize_answer"],
        }

    async def persist_memory(self, state: AgentGraphState) -> AgentGraphState:
        manifest = RuntimeManifest.model_validate(state["manifest"])
        thread = {
            "thread_id": state.get("thread_id") or state.get("session_id"),
            "expires_at": state.get("thread_expires_at"),
        }
        persisted = await self._ctx.context_manager.remember(
            manifest=manifest,
            thread=thread,
            user_input=state["user_input"],
            assistant_text=state.get("output") or "",
        )
        prior_turns = len(state.get("history_turns") or [])
        return {
            "memory_persisted": persisted,
            "history_total_turns": prior_turns + 2 if persisted else prior_turns,
            "steps": ["persist_memory"],
        }
