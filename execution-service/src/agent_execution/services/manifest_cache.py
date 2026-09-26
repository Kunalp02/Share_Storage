from __future__ import annotations

import time

from agent_execution.schemas.runtime import RuntimeManifest


class ManifestCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, ttl_seconds)
        self._entries: dict[str, tuple[float, RuntimeManifest]] = {}

    def get(self, key: str) -> RuntimeManifest | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, manifest = entry
        if time.monotonic() > expires_at:
            del self._entries[key]
            return None
        return manifest

    def set(self, key: str, manifest: RuntimeManifest) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, manifest)
