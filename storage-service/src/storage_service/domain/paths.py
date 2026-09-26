from __future__ import annotations

import re
from uuid import UUID

_UNSAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_filename(name: str) -> str:
    base = name.split("/")[-1].split("\\")[-1].strip() or "file"
    cleaned = _UNSAFE.sub("_", base)
    return cleaned[:200] or "file"


def build_storage_key(
    agent_id: UUID,
    thread_id: UUID,
    artifact_type: str,
    artifact_id: UUID,
    filename: str,
) -> str:
    safe = sanitize_filename(filename)
    return f"agents/{agent_id}/threads/{thread_id}/{artifact_type.lower()}/{artifact_id}/{safe}"
