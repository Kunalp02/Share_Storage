from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from storage_service.api.exception_handlers import register_exception_handlers
from storage_service.api.middleware import RequestContextMiddleware
from storage_service.core.exceptions import ServiceError
from storage_service.logging_config import JsonFormatter, RequestIdFilter, request_id_var


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    @app.get("/deny")
    async def deny() -> None:
        raise ServiceError("FORBIDDEN", "Invalid internal API key.", 403)

    return app


def test_request_id_header_is_preserved():
    response = TestClient(_app()).get("/ping", headers={"X-Request-ID": "store-1"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "store-1"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_service_error_body():
    response = TestClient(_app()).get("/deny", headers={"X-Request-ID": "store-403"})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["requestId"] == "store-403"


def test_json_log_carries_request_id():
    request_id_var.set("store-json")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "artifact.stored", (), None)
    RequestIdFilter().filter(record)
    assert '"requestId": "store-json"' in JsonFormatter().format(record)
