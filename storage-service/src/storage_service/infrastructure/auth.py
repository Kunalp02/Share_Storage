from __future__ import annotations

from storage_service.core.exceptions import ServiceError


def require_internal_key(presented: str | None, expected: str) -> None:
    if not expected or not presented or presented != expected:
        raise ServiceError("FORBIDDEN", "Invalid internal API key.", 403)
