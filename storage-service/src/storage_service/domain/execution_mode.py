from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    TEST = "TEST"
    PRODUCTION = "PRODUCTION"
