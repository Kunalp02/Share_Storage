from __future__ import annotations

from agent_execution.schemas.runs import RunStatus
from agent_execution.schemas.threads import ExecutionType


def pins_manifest(execution_type: ExecutionType) -> bool:
    """Production and API threads keep the manifest captured when the thread opened."""
    return execution_type == ExecutionType.PRODUCTION


def status_after_failure(attempt: int, max_attempts: int) -> RunStatus:
    if attempt < max_attempts:
        return RunStatus.QUEUED
    return RunStatus.FAILED
