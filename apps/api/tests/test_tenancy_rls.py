"""Tenant isolation against a real PostgreSQL with RLS, as the unprivileged app role."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentree.core.db import create_engine, create_session_factory
from agentree.core.ids import uuid7
from agentree.tenancy import rls
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from agentree.tenancy.models import Business
from agentree.tenancy.service import (
    InvalidSlugError,
    create_business,
    get_business,
    resolve_public_business,
    validate_slug,
)
from tests.conftest import DbUrls

Factory = async_sessionmaker[AsyncSession]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def two_tenants(app_factory: Factory) -> tuple[TenantContext, TenantContext]:
    a = await create_business(app_factory, name="Alpha", slug=_slug("alpha"))
    b = await create_business(app_factory, name="Beta", slug=_slug("beta"))
    return a, b


async def _count(session: AsyncSession, table: str = "businesses") -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


# --- fail closed without context -------------------------------------------------------


async def test_query_without_tenant_context_sees_nothing(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    async with app_factory() as session:
        assert await _count(session) == 0
        assert (await session.execute(select(Business))).scalars().all() == []


async def test_insert_without_tenant_context_is_rejected(app_factory: Factory) -> None:
    async with app_factory() as session:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await session.execute(
                text("INSERT INTO businesses (id, name, slug) VALUES (:i, 'X', :s)"),
                {"i": uuid7(), "s": _slug("nctx")},
            )


async def test_malformed_tenant_context_errors_instead_of_matching(app_factory: Factory) -> None:
    async with app_factory() as session, session.begin():
        await session.execute(text("SELECT set_config('agentree.business_id', 'nope', true)"))
        with pytest.raises(DBAPIError, match="invalid input syntax for type uuid"):
            await _count(session)


# --- cross-tenant isolation ------------------------------------------------------------


async def test_tenant_sees_only_its_own_business_even_with_unscoped_query(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, b = two_tenants
    async with tenant_session(app_factory, a) as session:
        rows = (await session.execute(select(Business))).scalars().all()  # no WHERE on purpose
    assert [r.id for r in rows] == [a.business_id]

    async with tenant_session(app_factory, a) as session:
        by_id = await session.get(Business, b.business_id)
    assert by_id is None


async def test_cannot_insert_row_for_another_tenant(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with tenant_session(app_factory, a) as session:
            await session.execute(
                text("INSERT INTO businesses (id, name, slug) VALUES (:i, 'Evil', :s)"),
                {"i": uuid7(), "s": _slug("evil")},
            )


async def test_cannot_update_or_delete_another_tenant(
    app_factory: Factory,
    migrator_engine: AsyncEngine,
    two_tenants: tuple[TenantContext, TenantContext],
) -> None:
    a, b = two_tenants
    async with tenant_session(app_factory, a) as session:
        upd = await session.execute(
            text("UPDATE businesses SET name = 'pwned' WHERE id = :b"), {"b": b.business_id}
        )
        dele = await session.execute(
            text("DELETE FROM businesses WHERE id = :b"), {"b": b.business_id}
        )
    assert upd.rowcount == 0  # type: ignore[attr-defined]
    assert dele.rowcount == 0  # type: ignore[attr-defined]
    async with migrator_engine.connect() as conn:
        name = (
            await conn.execute(
                text("SELECT name FROM businesses WHERE id = :b"), {"b": b.business_id}
            )
        ).scalar_one()
    assert name == "Beta"


async def test_cannot_move_own_row_into_another_tenant(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with tenant_session(app_factory, a) as session:
            await session.execute(
                text("UPDATE businesses SET id = :b WHERE id = :a"),
                {"a": a.business_id, "b": uuid7()},
            )


async def test_service_get_business_returns_only_context_tenant(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, b = two_tenants
    assert (await get_business(app_factory, a)).name == "Alpha"
    assert (await get_business(app_factory, b)).name == "Beta"


# --- pooling and transaction scope -----------------------------------------------------


@pytest.fixture
async def single_connection_factory(db_urls: DbUrls) -> AsyncIterator[Factory]:
    # pool_size=1 guarantees every session reuses the same physical connection.
    engine = create_engine(db_urls.app, pool_size=1, max_overflow=0)
    yield create_session_factory(engine)
    await engine.dispose()


async def _current_context(session: AsyncSession) -> str | None:
    value = (
        await session.execute(text("SELECT current_setting('agentree.business_id', true)"))
    ).scalar()
    return value or None


async def test_context_does_not_survive_commit_on_pooled_connection(
    single_connection_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    async with tenant_session(single_connection_factory, a) as session:
        pid_a = (await session.execute(text("SELECT pg_backend_pid()"))).scalar()
        assert await _current_context(session) == str(a.business_id)
    async with single_connection_factory() as session:
        assert (await session.execute(text("SELECT pg_backend_pid()"))).scalar() == pid_a
        assert await _current_context(session) is None
        assert await _count(session) == 0


async def test_context_does_not_survive_rollback(
    single_connection_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    with pytest.raises(RuntimeError):
        async with tenant_session(single_connection_factory, a):
            raise RuntimeError("boom")
    async with single_connection_factory() as session:
        assert await _current_context(session) is None


async def test_session_level_set_is_cleared_when_connection_returns_to_pool(
    single_connection_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    # Simulate a bug: session-level (not transaction-local) SET outside tenant_session.
    async with single_connection_factory() as session:
        await session.execute(text(f"SET agentree.business_id = '{a.business_id}'"))
        assert await _current_context(session) == str(a.business_id)
        assert await _count(session) == 1  # the leaked context would grant access
        await session.commit()
    async with single_connection_factory() as session:
        assert await _current_context(session) is None
        assert await _count(session) == 0


async def test_sequential_jobs_on_one_connection_see_only_their_tenant(
    single_connection_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    # Worker pattern: one tenant_session per job, built from the job's business id.
    seen = []
    for ctx in (*two_tenants, *two_tenants):
        job_ctx = TenantContext(ctx.business_id, TenantSource.JOB)
        async with tenant_session(single_connection_factory, job_ctx) as session:
            seen.append([b.id for b in (await session.execute(select(Business))).scalars()])
    a, b = two_tenants
    assert seen == [[a.business_id], [b.business_id], [a.business_id], [b.business_id]]


# --- privilege boundaries --------------------------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    [
        "ALTER TABLE businesses DISABLE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON businesses",
        "CREATE TABLE sneaky (id int)",
        "SET ROLE agentree_migrator",
        "TRUNCATE businesses",
    ],
)
async def test_app_role_cannot_escalate_or_disable_isolation(
    app_factory: Factory, stmt: str
) -> None:
    async with app_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text(stmt))


async def test_every_public_table_has_rls_unless_explicitly_global(app_factory: Factory) -> None:
    async with app_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                    """
                )
            )
        ).all()
    without_rls = {name for name, enabled in rows if not enabled}
    assert without_rls == set(rls.GLOBAL_TABLES), (
        "tables without RLS must be listed in GLOBAL_TABLES"
    )
    tenant_tables = {name for name, enabled in rows if enabled}
    assert {"businesses", "business_memberships", "business_invitations"} <= tenant_tables


async def test_enable_tenant_rls_helper_isolates_a_child_table(
    migrator_engine: AsyncEngine,
    app_factory: Factory,
    two_tenants: tuple[TenantContext, TenantContext],
) -> None:
    a, b = two_tenants
    table = f"probe_{uuid.uuid4().hex[:8]}"
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(f"CREATE TABLE {table} (id serial PRIMARY KEY, business_id uuid NOT NULL)")
        )
        for stmt in rls.enable_tenant_rls(table):
            await conn.execute(text(stmt))
        await conn.execute(
            text(f"INSERT INTO {table} (business_id) VALUES (:a), (:a), (:b)"),
            {"a": a.business_id, "b": b.business_id},
        )
    try:
        async with tenant_session(app_factory, a) as session:
            assert await _count(session, table) == 2
        async with tenant_session(app_factory, b) as session:
            assert await _count(session, table) == 1
        async with app_factory() as session:
            assert await _count(session, table) == 0
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE {table}"))


# --- public slug resolution ------------------------------------------------------------


async def test_public_slug_resolves_to_public_context_only(
    app_factory: Factory, two_tenants: tuple[TenantContext, TenantContext]
) -> None:
    a, _ = two_tenants
    business = await get_business(app_factory, a)
    resolved = await resolve_public_business(app_factory, business.slug)
    assert resolved == TenantContext(a.business_id, TenantSource.PUBLIC)
    assert await resolve_public_business(app_factory, "does-not-exist") is None


@pytest.mark.parametrize(
    "slug", ["api", "a", "-bad", "bad-", "Bad", "no--double", "x" * 64, "sp ace"]
)
def test_invalid_slugs_rejected(slug: str) -> None:
    with pytest.raises(InvalidSlugError):
        validate_slug(slug)


def test_tenant_context_requires_uuid() -> None:
    with pytest.raises(TypeError):
        TenantContext("not-a-uuid", TenantSource.JOB)  # type: ignore[arg-type]
