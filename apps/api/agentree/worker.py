"""Worker entrypoint placeholder.

The Postgres-backed job queue is introduced in a later task (TD-06). This stub only
proves the worker process can load settings and start, then exits cleanly.
"""

import logging

from agentree.core.config import get_settings
from agentree.core.logging import configure_logging

logger = logging.getLogger("agentree.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("worker placeholder started; no job queue configured yet")


if __name__ == "__main__":
    main()
