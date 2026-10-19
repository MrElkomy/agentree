"""Tenancy foundation: businesses table under row-level security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import (
    CURRENT_BUSINESS_FUNCTION,
    DROP_CURRENT_BUSINESS_FUNCTION,
    disable_tenant_rls,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Narrow, audited cross-tenant lookup: slug -> id only. Runs as the table owner
# (migrator), which is not subject to RLS because tables are not FORCE'd.
RESOLVE_SLUG_FUNCTION = """
CREATE FUNCTION agentree_resolve_business_slug(p_slug text) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$ SELECT id FROM public.businesses WHERE slug = p_slug $$
"""


def upgrade() -> None:
    op.execute(CURRENT_BUSINESS_FUNCTION)
    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_businesses"),
        sa.UniqueConstraint("slug", name="uq_businesses_slug"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_businesses_name_not_blank"),
    )
    # The business row is its own tenant key: isolate on `id`.
    op.execute("ALTER TABLE businesses ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON businesses "
        "USING (id = agentree_current_business_id()) "
        "WITH CHECK (id = agentree_current_business_id())"
    )
    op.execute(RESOLVE_SLUG_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION agentree_resolve_business_slug(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION agentree_resolve_business_slug(text) TO agentree_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS agentree_resolve_business_slug(text)")
    for stmt in disable_tenant_rls("businesses"):
        op.execute(stmt)
    op.drop_table("businesses")
    op.execute(DROP_CURRENT_BUSINESS_FUNCTION)
