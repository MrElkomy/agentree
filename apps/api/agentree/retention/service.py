"""Retention job: hard-delete raw conversations older than the retention window.

Since migration 0008 the same purge also deletes anonymous guest sessions (public page /
widget) idle longer than the window once none of their conversations remain; conversations
on legal hold keep their session. Counts below are rows deleted (conversations + sessions).

Runs in the worker as the unprivileged `agentree_app` role. Cross-tenant deletion goes
only through the `agentree_purge_expired_conversations` SECURITY DEFINER function, which
returns a count and never content. Each batch is its own short transaction guarded by a
transaction-level advisory lock, so only one worker purges at a time.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Arbitrary constant identifying the retention purge among advisory locks.
ADVISORY_LOCK_KEY = 7_301_030_001
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class PurgeResult:
    deleted: int  # conversations + guest sessions
    batches: int
    skipped_locked: bool  # another worker held the lock


async def _purge_batch(
    factory: async_sessionmaker[AsyncSession], cutoff: datetime, batch_size: int
) -> int | None:
    """Delete one batch. Returns None when another worker holds the purge lock."""
    async with factory() as session, session.begin():
        locked = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY}
            )
        ).scalar_one()
        if not locked:
            return None
        deleted = (
            await session.execute(
                text("SELECT agentree_purge_expired_conversations(:cutoff, :n)"),
                {"cutoff": cutoff, "n": batch_size},
            )
        ).scalar_one()
        return int(deleted)


async def purge_expired_conversations(
    factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
) -> PurgeResult:
    """Run one retention pass: delete batches until a batch comes back short."""
    if not 1 <= retention_days <= 30:
        raise ValueError("retention_days must be between 1 and 30")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    started = time.monotonic()
    deleted = batches = 0
    skipped = False
    while True:
        n = await _purge_batch(factory, cutoff, batch_size)
        if n is None:
            skipped = True
            break
        batches += 1
        deleted += n
        if n < batch_size:
            break
    logger.info(
        "retention purge finished",
        extra={
            "rows_deleted": deleted,
            "batches": batches,
            "skipped_locked": skipped,
            "retention_days": retention_days,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return PurgeResult(deleted, batches, skipped)


async def run_retention_loop(
    factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int,
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Purge every `interval_seconds` until `stop` is set. Failures are logged and retried."""
    while not stop.is_set():
        try:
            await purge_expired_conversations(factory, retention_days=retention_days)
        except Exception as exc:  # keep the worker alive; next run retries
            logger.error("retention purge failed", extra={"error_type": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
