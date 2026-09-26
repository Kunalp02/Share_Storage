from __future__ import annotations

from dataclasses import dataclass


def parse_codes(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_parts: list[str]
    if isinstance(value, str):
        raw_parts = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_parts = [str(item) for item in value]
    else:
        raw_parts = [str(value)]
    codes: list[str] = []
    for part in raw_parts:
        for piece in part.split(","):
            code = piece.strip()
            if code and code not in codes:
                codes.append(code)
    return tuple(codes)


@dataclass(frozen=True, slots=True)
class PlatformPrincipal:
    token: str
    subject: str
    username: str
    user_id: str
    groups: tuple[str, ...]
    permissions: tuple[str, ...]

    def has_all(self, required: tuple[str, ...]) -> bool:
        if not required:
            return True
        owned = set(self.permissions)
        return all(code in owned for code in required)
