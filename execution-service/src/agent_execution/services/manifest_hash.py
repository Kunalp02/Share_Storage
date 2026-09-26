from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_manifest_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
