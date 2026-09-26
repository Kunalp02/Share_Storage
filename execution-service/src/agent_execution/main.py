from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_execution.api.exception_handlers import register_exception_handlers
from agent_execution.api.router import create_api_router
from agent_execution.core.container import shutdown_container
from agent_execution.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await shutdown_container()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agent Execution Service",
        version="4.0.0",
        description="Thread and run runtime for studio test and published agent APIs.",
        lifespan=lifespan,
    )
    origins = settings.cors_origin_list()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(create_api_router())
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "agent_execution.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
