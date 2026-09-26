from __future__ import annotations

import asyncio
import logging

from agent_execution.core.container import get_container, shutdown_container
from agent_execution.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    container = get_container(settings)
    logger.info("Starting execution worker")
    try:
        asyncio.run(container.worker.run_forever())
    finally:
        asyncio.run(shutdown_container())


if __name__ == "__main__":
    main()
