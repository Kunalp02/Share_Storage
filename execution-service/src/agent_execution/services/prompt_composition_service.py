from __future__ import annotations

from agent_execution.schemas.runtime import RuntimeManifest


class PromptCompositionService:
    @staticmethod
    def compose(
        manifest: RuntimeManifest,
        memory_block: str | None,
        kb_blocks: list[str],
        artifact_block: str | None = None,
    ) -> str:
        sections = [manifest.system_prompt.strip()]
        if memory_block:
            sections.append(memory_block)
        if kb_blocks:
            sections.append("Retrieved knowledge base context:\n" + "\n\n".join(kb_blocks))
        if artifact_block:
            sections.append(artifact_block)
        sections.append("Respond to the user message.")
        return "\n\n".join(sections)
