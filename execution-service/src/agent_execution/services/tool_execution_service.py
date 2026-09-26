from __future__ import annotations

import json

from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.platform.platform_clients import PlatformClients
from agent_execution.schemas.runtime import KnowledgeBaseRef, RuntimeManifest, ToolType
from agent_execution.services.tool_definition_service import ToolDefinitionService


class ToolExecutionService:
    def __init__(self, platform: PlatformClients) -> None:
        self._platform = platform

    async def run(
        self,
        manifest: RuntimeManifest,
        tool_name: str,
        arguments: dict,
        bearer_token: str | None,
        user_input: str,
    ) -> str:
        resolved = ToolDefinitionService.resolve_llm_tool_name(manifest, tool_name)
        if resolved is None:
            raise ServiceError("TOOL_ERROR", f"Unknown tool: {tool_name}", 400)
        kind, ref = resolved
        if kind == "kb":
            kb = ref
            assert isinstance(kb, KnowledgeBaseRef)
            query = arguments.get("query") or arguments.get("input") or user_input
            result = await self._platform.rag_ask.ask(kb.knowledge_base_id, query, bearer_token)
            return json.dumps(result.get("evidence", []), ensure_ascii=True)
        tool = ref
        if tool.tool_type == ToolType.REMOTE:
            meta = await self._platform.tools.get_remote_tool(tool.tool_id, bearer_token)
        else:
            meta = await self._platform.tools.get_local_tool(tool.tool_id, bearer_token)
        url = meta.get("invokeUrl") or meta.get("endpoint") or meta.get("url")
        if not url:
            raise ServiceError("TOOL_ERROR", f"Tool {tool.tool_id} has no invoke URL.", 400)
        result = await self._platform.tools.invoke_tool(url, bearer_token, arguments)
        return json.dumps(result, ensure_ascii=True)
