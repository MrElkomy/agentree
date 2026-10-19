from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import alembic_config


async def test_database_is_migrated_to_head(engine: AsyncEngine, database_url: str) -> None:
    head = ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()
    async with engine.connect() as conn:
        current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert current == head


async def test_db_session_changes_are_isolated_and_not_committed(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    await db_session.execute(text("CREATE TABLE rollback_probe (id int)"))
    await db_session.execute(text("INSERT INTO rollback_probe VALUES (1)"))
    assert (await db_session.execute(text("SELECT count(*) FROM rollback_probe"))).scalar() == 1

    # An independent connection must not see the uncommitted table.
    async with engine.connect() as other:
        found = (await other.execute(text("SELECT to_regclass('rollback_probe')"))).scalar()
    assert found is None
