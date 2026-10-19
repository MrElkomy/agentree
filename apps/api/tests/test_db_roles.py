import pytest
from httpx import AsyncClient

from agentree.core.db import create_engine
from agentree.core.db_roles import UnsafeDatabaseRoleError, assert_safe_app_role
from agentree.core.ids import uuid7
from agentree.main import create_app
from tests.conftest import DbUrls, make_settings, running_app


async def test_app_role_is_safe(db_urls: DbUrls) -> None:
    engine = create_engine(db_urls.app)
    try:
        safety = await assert_safe_app_role(engine)
    finally:
        await engine.dispose()
    assert safety.role == "agentree_app"
    assert safety.safe


@pytest.mark.parametrize("which", ["admin", "migrator"])
async def test_privileged_roles_are_rejected(db_urls: DbUrls, which: str) -> None:
    engine = create_engine(getattr(db_urls, which))
    try:
        with pytest.raises(UnsafeDatabaseRoleError):
            await assert_safe_app_role(engine)
    finally:
        await engine.dispose()


async def test_app_refuses_to_start_with_privileged_role(db_urls: DbUrls) -> None:
    app = create_app(make_settings(database_url=db_urls.migrator))
    with pytest.raises(UnsafeDatabaseRoleError):
        async with running_app(app):
            pass


async def test_readyz_reports_ok_for_app_role(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_uuid7_is_version_7_and_time_ordered() -> None:
    ids = [uuid7() for _ in range(50)]
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)
    assert ids == sorted(ids) or len({i.int >> 80 for i in ids}) == 1
