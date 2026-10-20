"""30-day raw conversation retention job (AGT-010), against real PostgreSQL.

Fixtures are written as the migrator (table owner) so ages can be back-dated; the purge
itself always runs as the unprivileged agentree_app role, exactly as in the worker.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentree import worker
from agentree.core.config import get_settings
from agentree.core.db_roles import UnsafeDatabaseRoleError
from agentree.core.ids import uuid7
from agentree.core.logging import JsonFormatter
from agentree.retention.service import (
    ADVISORY_LOCK_KEY,
    purge_expired_conversations,
    run_retention_loop,
)
from agentree.tenancy.service import create_business
from tests.conftest import DbUrls, make_settings

Factory = async_sessionmaker[AsyncSession]
FN = "agentree_purge_expired_conversations(timestamptz, integer)"
PRIVATE_CONTENT = "my private phone number is 555-0199"


def _now() -> datetime:
    return datetime.now(UTC)


async def _business(factory: Factory) -> uuid.UUID:
    ctx = await create_business(factory, name="Retention", slug=f"ret-{uuid.uuid4().hex[:8]}")
    return ctx.business_id


async def _conversation(
    engine: AsyncEngine,
    business_id: uuid.UUID,
    *,
    created: datetime,
    last: datetime | None = None,
    messages: tuple[datetime, ...] = (),
    legal_hold: bool = False,
) -> uuid.UUID:
    conv_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO conversations (id, business_id, channel, active_agent, created_at, "
                "last_message_at, legal_hold) VALUES (:id, :b, 'console', 'sales', :c, :l, :h)"
            ),
            {"id": conv_id, "b": business_id, "c": created, "l": last or created, "h": legal_hold},
        )
        for at in messages:
            await conn.execute(
                text(
                    "INSERT INTO conversation_messages (id, business_id, conversation_id, role, "
                    "content, created_at) VALUES (:id, :b, :c, 'user', :t, :at)"
                ),
                {"id": uuid7(), "b": business_id, "c": conv_id, "t": PRIVATE_CONTENT, "at": at},
            )
    return conv_id


async def _counts(engine: AsyncEngine, conv_id: uuid.UUID) -> tuple[int, int]:
    async with engine.connect() as conn:
        convs = (
            await conn.execute(
                text("SELECT count(*) FROM conversations WHERE id = :i"), {"i": conv_id}
            )
        ).scalar_one()
        msgs = (
            await conn.execute(
                text("SELECT count(*) FROM conversation_messages WHERE conversation_id = :i"),
                {"i": conv_id},
            )
        ).scalar_one()
    return int(convs), int(msgs)


async def test_retention_purges_only_expired_unheld_conversations_across_tenants(
    app_factory: Factory, migrator_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    a, b = await _business(app_factory), await _business(app_factory)
    old, recent = _now() - timedelta(days=31), _now() - timedelta(days=1)
    aged_a = await _conversation(migrator_engine, a, created=old, messages=(old, old))
    aged_b = await _conversation(migrator_engine, b, created=old, messages=(old,))
    aged_empty = await _conversation(migrator_engine, b, created=old)
    fresh = await _conversation(migrator_engine, a, created=recent, messages=(recent,))
    # Old conversation and stale last_message_at, but one recent message: still active.
    revived = await _conversation(migrator_engine, a, created=old, messages=(old, recent))
    held = await _conversation(migrator_engine, b, created=old, messages=(old,), legal_hold=True)

    with caplog.at_level(logging.DEBUG):
        result = await purge_expired_conversations(app_factory, retention_days=30)

    assert result.deleted == 3
    assert not result.skipped_locked
    for conv in (aged_a, aged_b, aged_empty):
        assert await _counts(migrator_engine, conv) == (0, 0)
    assert await _counts(migrator_engine, fresh) == (1, 1)
    assert await _counts(migrator_engine, revived) == (1, 2)
    assert await _counts(migrator_engine, held) == (1, 1)

    # Logs carry counts only, never message content.
    records = [r for r in caplog.records if r.name.startswith("agentree")]
    assert any(getattr(r, "rows_deleted", None) == 3 for r in records)
    formatter = JsonFormatter()
    dumped = json.dumps([formatter.format(r) for r in caplog.records])
    assert PRIVATE_CONTENT not in dumped
    assert "555-0199" not in dumped


async def test_retention_deletes_in_batches_until_a_short_batch(
    app_factory: Factory, migrator_engine: AsyncEngine
) -> None:
    biz = await _business(app_factory)
    old = _now() - timedelta(days=40)
    convs = [
        await _conversation(migrator_engine, biz, created=old, messages=(old,)) for _ in range(5)
    ]

    async with app_factory() as session, session.begin():
        first = (
            await session.execute(
                text("SELECT agentree_purge_expired_conversations(:c, 2)"),
                {"c": _now() - timedelta(days=30)},
            )
        ).scalar_one()
    assert first == 2

    result = await purge_expired_conversations(app_factory, retention_days=30, batch_size=2)
    assert (result.deleted, result.batches) == (3, 2)  # 2 + 1 (short batch stops the pass)
    for conv in convs:
        assert await _counts(migrator_engine, conv) == (0, 0)


async def test_only_one_worker_purges_at_a_time(
    app_factory: Factory, app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    biz = await _business(app_factory)
    old = _now() - timedelta(days=31)
    conv = await _conversation(migrator_engine, biz, created=old)
    async with app_engine.connect() as other_worker:
        await other_worker.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        try:
            result = await purge_expired_conversations(app_factory, retention_days=30)
        finally:
            await other_worker.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY}
            )
            await other_worker.commit()
    assert result.skipped_locked and result.deleted == 0
    assert await _counts(migrator_engine, conv) == (1, 0)
    assert (await purge_expired_conversations(app_factory, retention_days=30)).deleted == 1


async def test_purge_function_privileges_and_definition(migrator_engine: AsyncEngine) -> None:
    async with migrator_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    f"""
                    SELECT has_function_privilege('public', '{FN}', 'EXECUTE'),
                           has_function_privilege('agentree_app', '{FN}', 'EXECUTE'),
                           p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner)
                    FROM pg_proc p WHERE p.oid = '{FN}'::regprocedure
                    """
                )
            )
        ).one()
    public_exec, app_exec, secdef, config, owner = row
    assert public_exec is False
    assert app_exec is True
    assert secdef is True
    assert config == ["search_path=pg_catalog, public"]
    assert owner == "agentree_migrator"


@pytest.mark.parametrize(
    ("cutoff_days", "max_rows"),
    [(0, 10), (30, 0), (30, 100_000)],
    ids=["too-recent", "zero", "huge"],
)
async def test_purge_function_rejects_unsafe_arguments(
    app_factory: Factory, cutoff_days: int, max_rows: int
) -> None:
    async with app_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="retention"):
            await session.execute(
                text("SELECT agentree_purge_expired_conversations(:c, :n)"),
                {"c": _now() - timedelta(days=cutoff_days), "n": max_rows},
            )


@pytest.mark.parametrize("days", [0, 31, 365])
def test_retention_days_cannot_exceed_the_approved_window(days: int) -> None:
    with pytest.raises(ValidationError, match="retention_days"):
        make_settings(database_url="postgresql+asyncpg://u:p@h/d", retention_days=days)
    assert make_settings(database_url="postgresql+asyncpg://u:p@h/d").retention_days == 30


async def test_service_rejects_retention_longer_than_30_days(app_factory: Factory) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        await purge_expired_conversations(app_factory, retention_days=31)


async def test_retention_loop_runs_until_stopped(
    app_factory: Factory, migrator_engine: AsyncEngine
) -> None:
    biz = await _business(app_factory)
    conv = await _conversation(migrator_engine, biz, created=_now() - timedelta(days=31))
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_retention_loop(app_factory, retention_days=30, interval_seconds=60, stop=stop)
    )
    for _ in range(100):
        if await _counts(migrator_engine, conv) == (0, 0):
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert await _counts(migrator_engine, conv) == (0, 0)


async def test_worker_once_purges_as_app_role_and_refuses_privileged_role(
    monkeypatch: pytest.MonkeyPatch,
    db_urls: DbUrls,
    app_factory: Factory,
    migrator_engine: AsyncEngine,
) -> None:
    biz = await _business(app_factory)
    conv = await _conversation(migrator_engine, biz, created=_now() - timedelta(days=31))
    try:
        monkeypatch.setenv("AGENTREE_DATABASE_URL", db_urls.migrator)
        get_settings.cache_clear()
        with pytest.raises(UnsafeDatabaseRoleError):
            await worker.run(once=True)
        assert await _counts(migrator_engine, conv) == (1, 0)

        monkeypatch.setenv("AGENTREE_DATABASE_URL", db_urls.app)
        get_settings.cache_clear()
        await worker.run(once=True)
        assert await _counts(migrator_engine, conv) == (0, 0)
    finally:
        get_settings.cache_clear()
