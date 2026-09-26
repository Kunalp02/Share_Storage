from __future__ import annotations

from typing import Any, Literal

from agent_execution.schemas.runtime import AgentToolRef, KnowledgeBaseMode, KnowledgeBaseRef, RuntimeManifest


class ToolDefinitionService:
    @staticmethod
    def build_openai_tools(manifest: RuntimeManifest) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in manifest.tools:
            name = ToolDefinitionService.sanitize_name(tool.tool_name or str(tool.tool_id))
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Invoke configured tool {tool.tool_name or tool.tool_id}.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "Primary input for the tool."}
                            },
                            "additionalProperties": True,
                        },
                    },
                }
            )
        for kb in manifest.knowledge_bases:
            if kb.mode != KnowledgeBaseMode.TOOL:
                continue
            name = ToolDefinitionService.sanitize_name(kb.knowledge_base_name or f"kb_{kb.knowledge_base_id}")
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Search knowledge base {kb.knowledge_base_name or kb.knowledge_base_id}.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query."}
                            },
                            "required": ["query"],
                        },
                    },
                }
            )
        return tools

    @staticmethod
    def sanitize_name(raw: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw.strip())
        return cleaned[:64] or "tool"

    @staticmethod
    def resolve_llm_tool_name(
        manifest: RuntimeManifest, llm_name: str
    ) -> tuple[Literal["tool", "kb"], AgentToolRef | KnowledgeBaseRef] | None:
        normalized = llm_name.strip().lower()
        for tool in manifest.tools:
            candidates = {
                ToolDefinitionService.sanitize_name(tool.tool_name or str(tool.tool_id)).lower(),
                (tool.tool_name or "").lower(),
                str(tool.tool_id).lower(),
            }
            if normalized in candidates:
                return ("tool", tool)
        for kb in manifest.knowledge_bases:
            if kb.mode != KnowledgeBaseMode.TOOL:
                continue
            base = kb.knowledge_base_name or str(kb.knowledge_base_id)
            candidates = {
                ToolDefinitionService.sanitize_name(base).lower(),
                base.lower(),
                f"kb_{kb.knowledge_base_id}".lower(),
            }
            if normalized in candidates:
                return ("kb", kb)
        return None
