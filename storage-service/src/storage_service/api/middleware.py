from __future__ import annotations

import logging
import time
import uuid

from storage_service.logging_config import request_id_var

logger = logging.getLogger("storage_service.access")

_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        request_id = headers.get("x-request-id") or uuid.uuid4().hex
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                extra = [(b"x-request-id", request_id.encode()), *_SECURITY_HEADERS]
                message = {**message, "headers": list(message.get("headers") or []) + extra}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "request.completed method=%s path=%s status=%s durationMs=%s",
                scope.get("method"),
                scope.get("path"),
                status_code,
                elapsed_ms,
            )
            request_id_var.reset(token)
