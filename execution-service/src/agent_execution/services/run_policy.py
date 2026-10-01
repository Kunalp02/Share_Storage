from __future__ import annotations

from agent_execution.core.exceptions import ServiceError
from agent_execution.schemas.runs import RunStatus
from agent_execution.schemas.threads import ExecutionType

_PERMANENT_CODES = {
    "VALIDATION_FAILED",
    "CONTEXT_TOO_LARGE",
    "AGENT_NOT_PUBLISHED",
    "NOT_FOUND",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "MEMORY_CONTEXT_REQUIRED",
    "TOOL_ERROR",
    "THREAD_CLOSED",
}
_TRANSIENT_CODES = {"BUSY", "RAG_UNAVAILABLE", "LLM_UNAVAILABLE", "UPSTREAM_UNAVAILABLE", "TIMEOUT"}
_TRANSIENT_TYPES = {
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "NetworkError",
    "RemoteProtocolError",
}


def pins_manifest(execution_type: ExecutionType) -> bool:
    """Production and API threads keep the manifest captured when the thread opened."""
    return execution_type == ExecutionType.PRODUCTION


def status_after_failure(attempt: int, max_attempts: int, *, transient: bool = True) -> RunStatus:
    if transient and attempt < max_attempts:
        return RunStatus.QUEUED
    return RunStatus.FAILED


def retry_delay_seconds(attempt: int, base_seconds: float, max_seconds: float) -> float:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def describe_failure(exc: Exception) -> tuple[str, str, bool]:
    """Return an audit code, a readable reason, and whether a background run should retry."""
    if isinstance(exc, ServiceError):
        transient = exc.status_code >= 500 or exc.status_code in {408, 429} or exc.code in _TRANSIENT_CODES
        if exc.code in _PERMANENT_CODES:
            transient = False
        return exc.code, str(exc), transient
    type_name = type(exc).__name__
    if type_name == "TimeoutError":
        return "TIMEOUT", "The run timed out before it finished.", True
    if type_name in _TRANSIENT_TYPES:
        return "UPSTREAM_UNAVAILABLE", "A dependent service could not be reached.", True
    return "RUN_FAILED", f"The run stopped because of an unexpected {type_name}.", True
