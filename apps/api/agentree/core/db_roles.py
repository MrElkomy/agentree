"""Database role model and bootstrap.

Two login roles per cluster:
- agentree_migrator: owns the schema objects; runs migrations. As table owner it is not
  subject to RLS (tables are not FORCE'd), which lets narrowly scoped SECURITY DEFINER
  functions it owns perform approved cross-tenant lookups.
- agentree_app: used by the API and worker. Not superuser, no BYPASSRLS, owns nothing,
  so every tenant table's RLS policy applies to it.

Bootstrap is run once per database by an administrator (or the dev/CI harness):
    python -m agentree.core.db_roles
with AGENTREE_ADMIN_DATABASE_URL, AGENTREE_APP_DB_PASSWORD and AGENTREE_MIGRATOR_DB_PASSWORD.
"""

import asyncio
import os
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

APP_ROLE = "agentree_app"
MIGRATOR_ROLE = "agentree_migrator"


class UnsafeDatabaseRoleError(RuntimeError):
    """The application is connected with a role that could bypass tenant isolation."""


@dataclass(frozen=True)
class RoleSafety:
    role: str
    superuser: bool
    bypass_rls: bool
    owns_tables: bool

    @property
    def safe(self) -> bool:
        return not (self.superuser or self.bypass_rls or self.owns_tables)


async def inspect_current_role(conn: AsyncConnection) -> RoleSafety:
    row = (
        await conn.execute(
            text(
                """
                SELECT r.rolname, r.rolsuper, r.rolbypassrls,
                       EXISTS (
                           SELECT 1 FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE c.relowner = r.oid AND c.relkind IN ('r', 'p')
                             AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                       ) AS owns_tables
                FROM pg_roles r WHERE r.rolname = current_user
                """
            )
        )
    ).one()
    return RoleSafety(role=row[0], superuser=row[1], bypass_rls=row[2], owns_tables=row[3])


async def assert_safe_app_role(engine: AsyncEngine) -> RoleSafety:
    async with engine.connect() as conn:
        safety = await inspect_current_role(conn)
    if not safety.safe:
        raise UnsafeDatabaseRoleError(
            f"database role {safety.role!r} can bypass tenant isolation "
            f"(superuser={safety.superuser}, bypassrls={safety.bypass_rls}, "
            f"owns_tables={safety.owns_tables}); use the {APP_ROLE!r} role"
        )
    return safety


async def _ensure_role(conn: AsyncConnection, role: str, password: str, attrs: str) -> None:
    exists = (
        await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    ).scalar()
    verb = "ALTER" if exists else "CREATE"
    # DDL cannot take bind parameters; let the server quote identifier and literal safely.
    stmt = (
        await conn.execute(
            text(
                f"SELECT format('{verb} ROLE %I WITH LOGIN {attrs} PASSWORD %L', "
                "CAST(:r AS text), CAST(:p AS text))"
            ),
            {"r": role, "p": password},
        )
    ).scalar_one()
    await conn.execute(text(stmt))


async def bootstrap_roles(admin_url: str, app_password: str, migrator_password: str) -> None:
    """Idempotently create both roles and grant privileges on the admin URL's database."""
    database = make_url(admin_url).database
    if not database:
        raise ValueError("admin URL must name the target database")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            common = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            await _ensure_role(conn, MIGRATOR_ROLE, migrator_password, common)
            await _ensure_role(conn, APP_ROLE, app_password, f"{common} NOINHERIT")
            quoted_db = (
                await conn.execute(text("SELECT quote_ident(:d)"), {"d": database})
            ).scalar_one()
            for stmt in (
                f"REVOKE ALL ON DATABASE {quoted_db} FROM PUBLIC",
                f"GRANT CONNECT, TEMPORARY ON DATABASE {quoted_db} TO {MIGRATOR_ROLE}",
                f"GRANT CONNECT ON DATABASE {quoted_db} TO {APP_ROLE}",
                "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
                f"ALTER SCHEMA public OWNER TO {MIGRATOR_ROLE}",
                f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
                # Objects the migrator creates become usable (DML only) by the app role.
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR_ROLE} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR_ROLE} IN SCHEMA public "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR_ROLE} IN SCHEMA public "
                "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR_ROLE} IN SCHEMA public "
                f"GRANT EXECUTE ON FUNCTIONS TO {APP_ROLE}",
            ):
                await conn.execute(text(stmt))
    finally:
        await engine.dispose()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> None:
    asyncio.run(
        bootstrap_roles(
            _require_env("AGENTREE_ADMIN_DATABASE_URL"),
            _require_env("AGENTREE_APP_DB_PASSWORD"),
            _require_env("AGENTREE_MIGRATOR_DB_PASSWORD"),
        )
    )
    print("database roles bootstrapped")


if __name__ == "__main__":
    main()
