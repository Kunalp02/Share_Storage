from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_execution.api.exception_handlers import register_exception_handlers
from agent_execution.api.middleware import RequestContextMiddleware
from agent_execution.core.exceptions import ServiceError
from agent_execution.logging_config import JsonFormatter, RequestIdFilter, request_id_var


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    @app.get("/reject")
    async def reject() -> None:
        raise ServiceError("BUSY", "Too many runs are in progress.", 429)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret database password")

    return app


def test_request_id_and_security_headers():
    response = TestClient(_app()).get("/ping", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_service_error_includes_request_id():
    response = TestClient(_app()).get("/reject", headers={"X-Request-ID": "req-429"})
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "BUSY"
    assert body["requestId"] == "req-429"


def test_unhandled_error_hides_exception_text():
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert "password" not in body["message"]
    assert body["requestId"] == "req-500"


def test_studio_thread_requires_platform_token(monkeypatch):
    monkeypatch.setenv("EXECUTION_DATABASE_URL", "postgresql://postgres:password@127.0.0.1:5432/execution")
    monkeypatch.setenv("AUTH_SERVICE_BASE_URL", "")
    from agent_execution.api.router import create_api_router
    from agent_execution.core import container as container_module
    from agent_execution.settings import get_settings

    get_settings.cache_clear()
    container_module._container = None
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(create_api_router())
    client = TestClient(app)
    missing = client.post(
        "/api/v1/agents/00000000-0000-0000-0000-000000000001/threads",
        json={"executionType": "TEST"},
    )
    rejected = client.post(
        "/api/v1/agents/00000000-0000-0000-0000-000000000001/threads",
        json={"executionType": "TEST"},
        headers={"Authorization": "Bearer not-a-platform-token"},
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "UNAUTHORIZED"
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "UNAUTHORIZED"
    asyncio.run(container_module.shutdown_container())
    get_settings.cache_clear()


def test_json_formatter_includes_request_id():
    request_id_var.set("req-json")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "run.started", (), None)
    RequestIdFilter().filter(record)
    line = JsonFormatter().format(record)
    assert '"requestId": "req-json"' in line
    assert "run.started" in line
