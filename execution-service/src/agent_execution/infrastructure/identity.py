from __future__ import annotations

import base64
import json


def caller_label(token: str | None) -> str:
    if not token:
        return ""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return ""
    for key in ("sub", "username", "unique_name", "preferred_username"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""
