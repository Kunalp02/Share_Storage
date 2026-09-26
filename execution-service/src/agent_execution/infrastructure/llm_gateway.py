from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.auth.service_token_provider import ServiceAuthTokenProvider
from agent_execution.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LlmToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ChatCompletionResult:
    content: str
    tool_calls: list[LlmToolCall] = field(default_factory=list)


class BifrostLlmGateway:
    def __init__(self, settings: Settings, token_provider: ServiceAuthTokenProvider | None = None) -> None:
        self._settings = settings
        self._token_provider = token_provider
        timeout = httpx.Timeout(settings.llm_gateway_timeout_seconds, connect=10.0)
        self._client = httpx.AsyncClient(timeout=timeout, verify=settings.verify_ssl)
        self._default_base_url = settings.bifrost_gateway_base_url.rstrip("/") if settings.bifrost_gateway_base_url else ""

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_base_url(self, base_url: str | None) -> str:
        candidate = (base_url or "").strip().rstrip("/")
        return candidate or self._default_base_url

    def _use_mock(self, resolved_base_url: str) -> bool:
        return self._settings.llm_gateway_mock or not resolved_base_url

    def _full_url(self, resolved_base_url: str) -> str:
        path = self._settings.llm_chat_completions_path
        if not path.startswith("/"):
            path = "/" + path
        return f"{resolved_base_url}{path}"

    async def _headers(self, bearer_token: str | None, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = api_key or self._settings.bifrost_gateway_api_key or bearer_token
        if not token and self._token_provider is not None:
            token = await self._token_provider.get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _parse_tool_calls(message: dict[str, Any]) -> list[LlmToolCall]:
        parsed: list[LlmToolCall] = []
        for item in message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            function = item.get("function") or {}
            name = function.get("name")
            if not name:
                continue
            args_raw = function.get("arguments") or "{}"
            if isinstance(args_raw, dict):
                args = args_raw
            else:
                try:
                    args = json.loads(str(args_raw))
                except json.JSONDecodeError:
                    args = {"input": str(args_raw)}
            if not isinstance(args, dict):
                args = {"input": args}
            parsed.append(LlmToolCall(id=str(item.get("id") or name), name=str(name), arguments=args))
        return parsed

    @staticmethod
    def _extract_result(data: dict[str, Any]) -> ChatCompletionResult:
        choices = data.get("choices") or []
        if not choices:
            raise ServiceError("LLM_ERROR", "Gateway returned no choices.", 502)
        message = choices[0].get("message") or {}
        content = message.get("content")
        tool_calls = BifrostLlmGateway._parse_tool_calls(message)
        if content is None and not tool_calls:
            raise ServiceError("LLM_ERROR", "Gateway returned empty content.", 502)
        return ChatCompletionResult(content=str(content or ""), tool_calls=tool_calls)

    @staticmethod
    def _mock_content(model: str, messages: list[dict[str, Any]]) -> str:
        last_user = next(
            (msg.get("content", "") for msg in reversed(messages) if msg.get("role") == "user"),
            "",
        )
        return f"[mock-llm:{model}] {last_user}"

    async def chat_with_messages(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        bearer_token: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> ChatCompletionResult:
        resolved_base_url = self._resolve_base_url(base_url)
        if self._use_mock(resolved_base_url):
            return ChatCompletionResult(content=self._mock_content(model, messages))
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = await self._client.post(
            self._full_url(resolved_base_url),
            headers=await self._headers(bearer_token, api_key),
            json=payload,
        )
        if response.status_code >= 400:
            raise ServiceError(
                "LLM_ERROR",
                f"Gateway chat failed ({response.status_code}): {response.text[:300]}",
                response.status_code if response.status_code < 500 else 502,
            )
        return self._extract_result(response.json())

    async def stream(
        self,
        *,
        model: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        bearer_token: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        resolved_base_url = self._resolve_base_url(base_url)
        if self._use_mock(resolved_base_url):
            yield self._mock_content(
                model,
                [{"role": "user", "content": user_input}],
            )
            return
        headers = {**(await self._headers(bearer_token, api_key)), "Accept": "text/event-stream"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": temperature,
            "stream": True,
        }
        async with self._client.stream(
            "POST", self._full_url(resolved_base_url), headers=headers, json=payload
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise ServiceError(
                    "LLM_ERROR",
                    f"Gateway stream failed ({response.status_code}): {body.decode()[:300]}",
                    response.status_code if response.status_code < 500 else 502,
                )
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.debug("Skipping non-JSON SSE line")
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                text = (choices[0].get("delta") or {}).get("content")
                if text:
                    yield str(text)
