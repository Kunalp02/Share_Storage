from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_execution.api.exception_handlers import register_exception_handlers
from agent_execution.api.middleware import RequestContextMiddleware
from agent_execution.api.router import create_api_router
from agent_execution.core.container import get_container, shutdown_container
from agent_execution.logging_config import configure_logging, uvicorn_log_config
from agent_execution.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("Execution service starting")
    container = get_container(settings)
    await container.database.ping()
    logger.info("Execution database is ready")
    yield
    logger.info("Execution service stopping")
    await shutdown_container()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(
        title="Agent Execution Service",
        version="4.0.0",
        description="Thread and run runtime for studio test and published agent APIs.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(create_api_router())
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    uvicorn.run(
        "agent_execution.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
        log_config=uvicorn_log_config(settings.log_level, settings.log_format),
    )


if __name__ == "__main__":
    main()
