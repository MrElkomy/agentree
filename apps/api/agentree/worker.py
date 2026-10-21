"""Worker entrypoint.

The Postgres-backed job queue is introduced in a later task (TD-06). For now the worker
runs two periodic jobs as the unprivileged `agentree_app` role: the 30-day conversation
retention purge (AGT-010) and follow-up reminders for overdue lead tasks (Task 11b).

    python -m agentree.worker          # run until SIGTERM/SIGINT
    python -m agentree.worker --once   # one pass of each job, then exit (ops, CI)
"""

import argparse
import asyncio
import logging
import signal

from agentree.core.config import get_settings
from agentree.core.db import create_app_engine, create_session_factory
from agentree.core.db_roles import assert_safe_app_role
from agentree.core.email import SmtpEmailSender
from agentree.core.logging import configure_logging
from agentree.leads.follow_ups import run_follow_up_loop, send_due_reminders
from agentree.retention.service import purge_expired_conversations, run_retention_loop

logger = logging.getLogger("agentree.worker")


async def run(*, once: bool) -> None:
    settings = get_settings()
    engine = create_app_engine(settings)
    try:
        # Same guard as the API: refuse to run as a role that can bypass RLS.
        await assert_safe_app_role(engine)
        factory = create_session_factory(engine)
        mailer = SmtpEmailSender(settings)
        if once:
            await purge_expired_conversations(factory, retention_days=settings.retention_days)
            await send_due_reminders(factory, settings, mailer)
            return
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        logger.info(
            "worker started",
            extra={
                "retention_days": settings.retention_days,
                "retention_interval_seconds": settings.retention_interval_seconds,
                "follow_up_interval_seconds": settings.follow_up_interval_seconds,
            },
        )
        await asyncio.gather(
            run_retention_loop(
                factory,
                retention_days=settings.retention_days,
                interval_seconds=settings.retention_interval_seconds,
                stop=stop,
            ),
            run_follow_up_loop(
                factory,
                settings,
                mailer,
                interval_seconds=settings.follow_up_interval_seconds,
                stop=stop,
            ),
        )
        logger.info("worker stopped")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agentree.worker")
    parser.add_argument("--once", action="store_true", help="run one pass of each job and exit")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()
