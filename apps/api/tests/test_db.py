from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentree.core.ids import uuid7
from tests.conftest import DbUrls, alembic_config


async def test_database_is_migrated_to_head(app_engine: AsyncEngine, db_urls: DbUrls) -> None:
    head = ScriptDirectory.from_config(alembic_config(db_urls.migrator)).get_current_head()
    async with app_engine.connect() as conn:
        current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert current == head


async def test_db_session_changes_are_isolated_and_not_committed(
    db_session: AsyncSession, migrator_engine: AsyncEngine
) -> None:
    bid = uuid7()
    await db_session.execute(
        text("SELECT set_config('agentree.business_id', :b, true)"), {"b": str(bid)}
    )
    await db_session.execute(
        text("INSERT INTO businesses (id, name, slug) VALUES (:b, 'Probe', :s)"),
        {"b": bid, "s": f"probe-{bid.hex[:8]}"},
    )
    assert (await db_session.execute(text("SELECT count(*) FROM businesses"))).scalar() == 1

    # The owner role is not subject to RLS, so it would see the row if it were committed.
    async with migrator_engine.connect() as other:
        found = (
            await other.execute(text("SELECT count(*) FROM businesses WHERE id = :b"), {"b": bid})
        ).scalar()
    assert found == 0
