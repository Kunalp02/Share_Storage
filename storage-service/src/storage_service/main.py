from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from storage_service.api.exception_handlers import register_exception_handlers
from storage_service.api.middleware import RequestContextMiddleware
from storage_service.api.router import create_api_router
from storage_service.core.container import get_container, shutdown_container
from storage_service.logging_config import configure_logging, uvicorn_log_config
from storage_service.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("Storage service starting")
    await get_container(settings).artifact_service.ping()
    logger.info("Storage database is ready")
    yield
    logger.info("Storage service stopping")
    await shutdown_container()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(create_api_router())
    return app


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    uvicorn.run(
        "storage_service.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_config=uvicorn_log_config(settings.log_level, settings.log_format),
    )


if __name__ == "__main__":
    main()
