from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from storage_service.core.exceptions import ServiceError
from storage_service.logging_config import current_request_id

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, *, request: Request | None = None, details: list | None = None) -> dict:
    request_id = current_request_id()
    if request is not None:
        state = request.scope.get("state")
        if isinstance(state, dict) and state.get("request_id"):
            request_id = state["request_id"]
        elif getattr(state, "request_id", None):
            request_id = state.request_id
    body: dict = {"code": code, "message": message, "requestId": request_id}
    if details is not None:
        body["details"] = details
    return body


class ApiErrorHandler:
    def register(self, app: FastAPI) -> None:
        app.add_exception_handler(ServiceError, self.service_error)
        app.add_exception_handler(RequestValidationError, self.validation_error)
        app.add_exception_handler(Exception, self.unhandled)

    async def service_error(self, request: Request, exc: ServiceError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("service.error code=%s status=%s", exc.code, exc.status_code)
        else:
            logger.info("service.rejected code=%s status=%s", exc.code, exc.status_code)
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, str(exc), request=request))

    async def validation_error(self, request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(item.get("loc", ())), "message": item.get("msg"), "type": item.get("type")}
            for item in exc.errors()
        ]
        logger.info("request.invalid errors=%s", len(details))
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_FAILED", "Request validation failed.", request=request, details=details),
        )

    async def unhandled(self, request: Request, exc: Exception) -> JSONResponse:
        logger.exception("request.unhandled error=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "Unexpected server error.", request=request),
        )


def register_exception_handlers(app: FastAPI) -> None:
    ApiErrorHandler().register(app)
