"""SQL building blocks for tenant row-level security, shared by migrations and tests.

Policy contract (fail closed):
- `agentree_current_business_id()` returns NULL when no tenant context is set, so the
  policy predicate is NULL and no row is visible or writable.
- A malformed context value raises an error instead of matching anything.
- Policies cover SELECT, INSERT, UPDATE and DELETE (USING + WITH CHECK).
"""

# Tables intentionally outside tenant RLS (platform-level, not owned by one business).
# Adding a table here is a security decision: it must hold no tenant data.
GLOBAL_TABLES = frozenset(
    {"alembic_version", "users", "user_sessions", "auth_tokens", "rate_limit_buckets"}
)

CURRENT_BUSINESS_FUNCTION = """
CREATE OR REPLACE FUNCTION agentree_current_business_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('agentree.business_id', true), '')::uuid $$
"""

DROP_CURRENT_BUSINESS_FUNCTION = "DROP FUNCTION IF EXISTS agentree_current_business_id()"


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


def enable_tenant_rls(table: str, column: str = "business_id") -> list[str]:
    """Statements that put `table` under tenant isolation on `column`."""
    t, c = _ident(table), _ident(column)
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {t} "
        f"USING ({c} = agentree_current_business_id()) "
        f"WITH CHECK ({c} = agentree_current_business_id())",
    ]


def disable_tenant_rls(table: str) -> list[str]:
    t = _ident(table)
    return [
        f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
        f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
    ]
