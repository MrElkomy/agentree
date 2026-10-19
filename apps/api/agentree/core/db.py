"""Async database engine and session factory."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentree.core.config import Settings

# Custom GUCs that carry request/job context. They must never survive a connection's
# return to the pool.
CONTEXT_SETTINGS = ("agentree.business_id",)


def _reset_context_on_checkin(dbapi_connection: Any, _record: Any, _reset_state: Any) -> None:
    # Transaction-local values vanish at commit/rollback already; this also clears any
    # session-level SET so a pooled connection never carries a previous tenant.
    # RESET is transactional: roll back pending work first, then commit the RESET.
    dbapi_connection.rollback()
    cursor = dbapi_connection.cursor()
    try:
        for name in CONTEXT_SETTINGS:
            cursor.execute(f"RESET {name}")
    finally:
        cursor.close()
    dbapi_connection.commit()


def create_engine(url: str, *, connect_timeout: float = 3.0, **kwargs: Any) -> AsyncEngine:
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"timeout": connect_timeout},
        **kwargs,
    )
    event.listen(engine.sync_engine, "reset", _reset_context_on_checkin)
    return engine


def create_app_engine(settings: Settings) -> AsyncEngine:
    return create_engine(
        settings.database_url.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_seconds,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
