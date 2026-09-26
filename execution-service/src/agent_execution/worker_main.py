from __future__ import annotations

import asyncio
import logging

from agent_execution.core.container import get_container, shutdown_container
from agent_execution.logging_config import configure_logging
from agent_execution.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    container = get_container(settings)
    logger.info("Starting execution worker")
    try:
        asyncio.run(container.worker.run_forever())
    finally:
        asyncio.run(shutdown_container())


if __name__ == "__main__":
    main()
