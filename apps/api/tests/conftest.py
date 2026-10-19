"""Test harness backed by a real PostgreSQL server.

AGENTREE_TEST_DATABASE_URL must point at a server as a superuser (or a role allowed to
CREATE DATABASE and CREATE ROLE), e.g. postgresql+asyncpg://postgres:postgres@localhost/postgres.
Each run creates a fresh database, bootstraps the agentree_app / agentree_migrator roles,
migrates to head as the migrator, and drops the database afterwards. Application code
under test always connects as agentree_app, so RLS is enforced exactly as in production.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentree.core.config import Environment, Settings
from agentree.core.db import create_engine, create_session_factory
from agentree.core.db_roles import APP_ROLE, MIGRATOR_ROLE, bootstrap_roles
from agentree.main import create_app

API_DIR = Path(__file__).resolve().parents[1]
# Test-only credentials for throwaway roles on a throwaway database.
APP_PASSWORD = "app_test_only"  # noqa: S105
MIGRATOR_PASSWORD = "migrator_test_only"  # noqa: S105


@dataclass(frozen=True)
class DbUrls:
    admin: str
    migrator: str
    app: str


def _in_thread[T](fn: Callable[[], T]) -> T:
    # Alembic's env.py and the admin helpers call asyncio.run(); keep them off the
    # pytest-asyncio event loop by running them in a separate thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()


async def _admin_execute(admin_url: str, sql: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


def _with(url: str, **parts: Any) -> str:
    return make_url(url).set(**parts).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def db_urls() -> Iterator[DbUrls]:
    server_url = os.environ.get("AGENTREE_TEST_DATABASE_URL")
    if not server_url:
        pytest.fail("AGENTREE_TEST_DATABASE_URL is not set; DB tests need a real PostgreSQL.")
    name = f"agentree_test_{uuid.uuid4().hex[:12]}"
    urls = DbUrls(
        admin=_with(server_url, database=name),
        migrator=_with(
            server_url, database=name, username=MIGRATOR_ROLE, password=MIGRATOR_PASSWORD
        ),
        app=_with(server_url, database=name, username=APP_ROLE, password=APP_PASSWORD),
    )
    _in_thread(lambda: asyncio.run(_admin_execute(server_url, f'CREATE DATABASE "{name}"')))
    try:
        _in_thread(
            lambda: asyncio.run(bootstrap_roles(urls.admin, APP_PASSWORD, MIGRATOR_PASSWORD))
        )
        _in_thread(lambda: command.upgrade(alembic_config(urls.migrator), "head"))
        yield urls
    finally:
        _in_thread(
            lambda: asyncio.run(
                _admin_execute(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
        )


@pytest.fixture(scope="session")
def settings(db_urls: DbUrls) -> Settings:
    return Settings(environment=Environment.TEST, database_url=db_urls.app)


@pytest.fixture(scope="session")
async def app_engine(db_urls: DbUrls) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(db_urls.app)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
async def migrator_engine(db_urls: DbUrls) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(db_urls.migrator)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def app_factory(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


@pytest.fixture
async def db_session(app_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """App-role session inside an outer transaction that is always rolled back."""
    async with app_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@asynccontextmanager
async def running_app(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    async with running_app(create_app(settings)) as c:
        yield c


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"environment": Environment.TEST} | overrides
    return Settings(**values)
