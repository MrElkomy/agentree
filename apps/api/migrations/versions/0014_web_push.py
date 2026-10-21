"""Web Push subscriptions and provider-outage alerts.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
SIGNATURE = "agentree_claim_provider_outages(timestamptz, integer)"

# SECURITY DEFINER (owned by the migrator), EXECUTE only for agentree_app: the worker claims keys
# whose circuit breaker is open and whose outage was not alerted yet, marking them alerted in the
# same statement so two workers never alert twice. Closing the breaker clears the mark. Returns
# ids only; the worker reads each key inside that business's tenant session.
CLAIM_FUNCTION = """
CREATE FUNCTION agentree_claim_provider_outages(p_now timestamptz, p_max_rows integer)
RETURNS TABLE (business_id uuid, slot text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_now IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 1000 THEN
    RAISE EXCEPTION 'invalid outage claim arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT c.id FROM public.provider_credentials c
     WHERE c.breaker_open_until IS NOT NULL AND c.outage_alerted_at IS NULL
     ORDER BY c.last_failure_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  )
  UPDATE public.provider_credentials c SET outage_alerted_at = p_now
    FROM due WHERE c.id = due.id
  RETURNING c.business_id, c.slot::text;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(1024), nullable=False),
        sa.Column("p256dh", sa.String(128), nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_success_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_push_subscriptions"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_push_subscriptions_business_id_businesses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_push_subscriptions_user_id_users"),
        sa.UniqueConstraint("business_id", "endpoint",
                            name="uq_push_subscriptions_business_id"),
    )  # fmt: skip
    op.create_index("ix_push_subscriptions_business_id_user_id", "push_subscriptions",
                    ["business_id", "user_id"])  # fmt: skip
    for stmt in enable_tenant_rls("push_subscriptions"):
        op.execute(stmt)

    op.add_column("provider_credentials", sa.Column("outage_alerted_at", TS))
    op.execute(CLAIM_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO agentree_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
    op.drop_column("provider_credentials", "outage_alerted_at")
    for stmt in disable_tenant_rls("push_subscriptions"):
        op.execute(stmt)
    op.drop_table("push_subscriptions")
