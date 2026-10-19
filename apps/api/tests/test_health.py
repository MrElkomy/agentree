from httpx import AsyncClient

from agentree.main import create_app
from tests.conftest import make_settings, running_app


async def test_healthz_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_ok_with_db(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_readyz_503_without_db() -> None:
    # Port 1 on localhost: nothing listens, connection is refused immediately.
    settings = make_settings(
        database_url="postgresql+asyncpg://nobody:not-a-real-password@127.0.0.1:1/none",
        db_connect_timeout_seconds=1,
    )
    async with running_app(create_app(settings)) as c:
        ready = await c.get("/readyz")
        alive = await c.get("/healthz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": "unreachable"}
    assert "not-a-real-password" not in ready.text
    assert alive.status_code == 200
