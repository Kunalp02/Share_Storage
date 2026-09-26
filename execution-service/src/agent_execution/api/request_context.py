from __future__ import annotations

from fastapi import Request


def client_address(request: Request) -> str:
    """Address of the caller, using the first forwarded hop when a proxy sends one."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:128]
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real[:128]
    client = request.client
    if client is not None and client.host:
        return client.host[:128]
    return ""
