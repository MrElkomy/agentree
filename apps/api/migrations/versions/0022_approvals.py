"""Approvals (Task 19): approval requests and "always allow" rules.

Both tables are tenant-scoped (RLS). Two narrow SECURITY DEFINER functions for the worker:
- `agentree_due_approvals` returns the ids of approved requests not yet run (ids only; running
  one is a conditional UPDATE under the business's own tenant context);
- `agentree_purge_approvals` deletes requests made before the cutoff (they may hold a lead's
  details and a drafted message) and returns a count, never content.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
TABLES = ("approval_requests", "approval_rules")
STATUSES = ("'pending', 'approved', 'rejected', 'expired', 'executing', 'executed', 'failed', "
            "'canceled'")  # fmt: skip
DECISIONS = "'once', 'always', 'rule', 'reject'"
DUE = "agentree_due_approvals(integer)"
PURGE = "agentree_purge_approvals(timestamptz)"

DUE_FUNCTION = """
CREATE FUNCTION agentree_due_approvals(p_max_rows integer)
RETURNS TABLE (business_id uuid, id uuid)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 500 THEN
    RAISE EXCEPTION 'invalid approvals arguments';
  END IF;
  RETURN QUERY
  SELECT a.business_id, a.id FROM public.approval_requests a
   WHERE a.status = 'approved'
   ORDER BY a.decided_at
   LIMIT p_max_rows;
END
$$
"""

PURGE_FUNCTION = """
CREATE FUNCTION agentree_purge_approvals(p_cutoff timestamptz)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count integer;
BEGIN
  IF p_cutoff IS NULL OR p_cutoff > now() - interval '1 day' THEN
    RAISE EXCEPTION 'approvals cutoff must be at least one day in the past';
  END IF;
  WITH doomed AS (
    SELECT a.id FROM public.approval_requests a
     WHERE a.requested_at < p_cutoff
     LIMIT 10000 FOR UPDATE SKIP LOCKED
  )
  DELETE FROM public.approval_requests a USING doomed d WHERE a.id = d.id;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("approved_hash", sa.String(64)),
        sa.Column("summary", sa.String(200), nullable=False),
        sa.Column("target_type", sa.String(32)),
        sa.Column("target_id", sa.Uuid()),
        sa.Column("flag", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(8)),
        sa.Column("decided_by_user_id", sa.Uuid()),
        sa.Column("rule_id", sa.Uuid()),
        sa.Column("requested_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("decided_at", TS),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("error", sa.String(64)),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_approval_requests_business_id_businesses"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_approval_requests_decided_by_user_id_users"),
        sa.UniqueConstraint("business_id", "idempotency_key",
                            name="uq_approval_requests_business_id_idempotency_key"),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_approval_requests_status"),
        sa.CheckConstraint(f"decision IS NULL OR decision IN ({DECISIONS})",
                           name="ck_approval_requests_decision"),
        sa.CheckConstraint("char_length(params_hash) = 64",
                           name="ck_approval_requests_params_hash"),
    )  # fmt: skip
    op.create_index("ix_approval_requests_business_id", "approval_requests", ["business_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    op.create_table(
        "approval_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_approval_rules"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_approval_rules_business_id_businesses"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_approval_rules_created_by_user_id_users"),
        sa.UniqueConstraint("business_id", "agent", "action",
                            name="uq_approval_rules_business_id_agent_action"),
    )  # fmt: skip
    op.create_index("ix_approval_rules_business_id", "approval_rules", ["business_id"])

    for table in TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)

    for fn, sig in ((DUE_FUNCTION, DUE), (PURGE_FUNCTION, PURGE)):
        op.execute(fn)
        op.execute(f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {sig} TO agentree_app")


def downgrade() -> None:
    for sig in (PURGE, DUE):
        op.execute(f"DROP FUNCTION IF EXISTS {sig}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
