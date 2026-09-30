from __future__ import annotations

from agent_execution.core.exceptions import ServiceError
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

    @staticmethod
    def compose_within_budget(
        manifest: RuntimeManifest,
        memory_block: str | None,
        kb_blocks: list[str],
        artifact_block: str | None,
        user_input: str,
        budget_chars: int,
    ) -> tuple[str, list[str]]:
        """Keep the system prompt and the new message. Drop files, then knowledge, then older history."""
        system = manifest.system_prompt.strip()
        if len(system) + len(user_input) > budget_chars:
            raise ServiceError(
                "CONTEXT_TOO_LARGE",
                "The system prompt and the new message are larger than the context budget.",
                400,
            )
        memory = memory_block
        knowledge = list(kb_blocks)
        files = artifact_block
        traces: list[str] = []

        def composed() -> str:
            return PromptCompositionService.compose(manifest, memory, knowledge, files)

        while len(composed()) + len(user_input) > budget_chars:
            if files and len(files) > 200:
                files = files[: max(200, len(files) // 2)]
                _add_trace(traces, "context.trimmed:files")
                continue
            if knowledge:
                knowledge.pop()
                _add_trace(traces, "context.trimmed:knowledge")
                continue
            if memory and len(memory) > 200:
                memory = memory[len(memory) // 2 :]
                _add_trace(traces, "context.trimmed:history")
                continue
            files = None
            knowledge = []
            memory = None
            break
        prompt = composed()
        if len(prompt) + len(user_input) > budget_chars:
            raise ServiceError(
                "CONTEXT_TOO_LARGE",
                "The system prompt and the new message are larger than the context budget.",
                400,
            )
        return prompt, traces


def _add_trace(traces: list[str], step: str) -> None:
    if step not in traces:
        traces.append(step)
