"""Test harness backed by a real PostgreSQL server.

AGENTREE_TEST_DATABASE_URL must point at a server where the user may CREATE DATABASE,
e.g. postgresql+asyncpg://postgres:postgres@localhost:5432/postgres. Each test run
creates a fresh database, migrates it to head, and drops it afterwards.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from agentree.core.config import Environment, Settings
from agentree.main import create_app

API_DIR = Path(__file__).resolve().parents[1]


def _in_thread[T](fn: Callable[[], T]) -> T:
    # Alembic's env.py and the admin helpers call asyncio.run(); keep them off the
    # pytest-asyncio event loop by running them in a separate thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()


async def _admin_execute(admin_url: str, sql: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
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


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    admin_url = os.environ.get("AGENTREE_TEST_DATABASE_URL")
    if not admin_url:
        pytest.fail("AGENTREE_TEST_DATABASE_URL is not set; DB tests need a real PostgreSQL.")
    name = f"agentree_test_{uuid.uuid4().hex[:12]}"
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)

    _in_thread(lambda: asyncio.run(_admin_execute(admin_url, f'CREATE DATABASE "{name}"')))
    try:
        _in_thread(lambda: command.upgrade(alembic_config(url), "head"))
        yield url
    finally:
        _in_thread(
            lambda: asyncio.run(
                _admin_execute(admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
        )


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(environment=Environment.TEST, database_url=database_url)


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction that is always rolled back."""
    async with engine.connect() as conn:
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
