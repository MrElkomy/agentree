"""Alembic environment (async, URL from Agentree settings)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Register every module's models on Base.metadata (used by autogenerate / alembic check).
import agentree.actions.models
import agentree.agents.models
import agentree.analytics.models
import agentree.audit.models
import agentree.customers.models
import agentree.identity.models
import agentree.knowledge.models
import agentree.leads.models
import agentree.notifications.models
import agentree.providers.models
import agentree.public.models
import agentree.tenancy.models  # noqa: F401
from agentree.core.config import Settings
from agentree.core.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    # Migrations must run as the schema owner (agentree_migrator), never the app role.
    migration_url = Settings().migration_database_url
    if migration_url is None:
        raise RuntimeError("AGENTREE_MIGRATION_DATABASE_URL is required to run migrations")
    return migration_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
