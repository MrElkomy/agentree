"""Worker entrypoint.

The Postgres-backed job queue is introduced in a later task (TD-06). For now the worker
runs periodic jobs as the unprivileged `agentree_app` role: the 30-day conversation
retention purge (AGT-010, with customer data since Task 16), follow-up reminders for overdue
lead tasks (Task 11b), alerts when an AI key goes down (Task 13b) and customer memory
extraction from idle public conversations (Task 16).

    python -m agentree.worker          # run until SIGTERM/SIGINT
    python -m agentree.worker --once   # one pass of each job, then exit (ops, CI)
"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Callable

import agentree.identity.models
import agentree.public.models  # noqa: F401
from agentree.core.config import get_settings
from agentree.core.db import create_app_engine, create_session_factory
from agentree.core.db_roles import assert_safe_app_role
from agentree.core.email import SmtpEmailSender
from agentree.core.logging import configure_logging
from agentree.core.webpush import build_push_sender
from agentree.customers.extraction import extract_due, run_memory_loop
from agentree.leads.follow_ups import run_follow_up_loop, send_due_reminders
from agentree.llm.base import LLMProvider, ProviderName
from agentree.llm.fake import DemoProvider
from agentree.llm.http_providers import PROVIDERS
from agentree.providers.outages import alert_provider_outages, run_outage_alert_loop
from agentree.providers.service import build_vault
from agentree.retention.service import purge_expired_conversations, run_retention_loop

logger = logging.getLogger("agentree.worker")


def _demo(name: ProviderName) -> Callable[[], LLMProvider]:
    return lambda: DemoProvider(name=name)


async def run(*, once: bool) -> None:
    settings = get_settings()
    engine = create_app_engine(settings)
    try:
        # Same guard as the API: refuse to run as a role that can bypass RLS.
        await assert_safe_app_role(engine)
        factory = create_session_factory(engine)
        mailer = SmtpEmailSender(settings)
        key = settings.vapid_private_key
        push = build_push_sender(key.get_secret_value() if key else None,
                                 settings.vapid_subject or settings.public_base_url)  # fmt: skip
        # Customer memory rows reference tables owned by other modules (users, guest_sessions):
        # their models are imported above so the ORM resolves those foreign keys here too.
        vault = build_vault(settings)
        llm: dict[ProviderName, Callable[[], LLMProvider]] = dict(PROVIDERS)
        if settings.llm_demo_mode:  # dev/E2E only (refused in deployed environments)
            llm = {n: _demo(n) for n in ProviderName}
        if once:
            await purge_expired_conversations(factory, retention_days=settings.retention_days)
            await send_due_reminders(factory, settings, mailer)
            await alert_provider_outages(factory, settings, mailer, push)
            await extract_due(factory, vault, settings, llm)
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
                "outage_alert_interval_seconds": settings.outage_alert_interval_seconds,
                "memory_interval_seconds": settings.memory_interval_seconds,
                "web_push": push.public_key is not None,
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
            run_outage_alert_loop(
                factory,
                settings,
                mailer,
                push,
                interval_seconds=settings.outage_alert_interval_seconds,
                stop=stop,
            ),
            run_memory_loop(
                factory,
                vault,
                settings,
                llm,
                interval_seconds=settings.memory_interval_seconds,
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
