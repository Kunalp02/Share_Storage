from __future__ import annotations

from enum import Enum


class ArtifactType(str, Enum):
    INPUT = "INPUT"
    INTERMEDIATE = "INTERMEDIATE"
    OUTPUT = "OUTPUT"


class ArtifactStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    DELETED = "DELETED"
