"""Follow-up tasks on leads (RLS) and a narrow cross-tenant claim function for due reminders.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
SIGNATURE = "agentree_claim_due_follow_ups(timestamptz, integer)"

# SECURITY DEFINER (owned by the migrator, which RLS does not restrict), EXECUTE only for
# agentree_app: the worker claims open tasks that are past due and not yet reminded, marking
# them reminded in the same statement so two workers never send the same reminder. Returns ids
# only, never content; the worker then reads each task inside that business's tenant session.
CLAIM_FUNCTION = """
CREATE FUNCTION agentree_claim_due_follow_ups(p_now timestamptz, p_max_rows integer)
RETURNS TABLE (business_id uuid, task_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_now IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 1000 THEN
    RAISE EXCEPTION 'invalid follow-up claim arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT t.business_id, t.id FROM public.follow_up_tasks t
     WHERE t.status = 'open' AND t.reminder_sent_at IS NULL AND t.due_at <= p_now
     ORDER BY t.due_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  )
  UPDATE public.follow_up_tasks t SET reminder_sent_at = p_now
    FROM due WHERE t.business_id = due.business_id AND t.id = due.id
  RETURNING t.business_id, t.id;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("assignee_user_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("kind", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_by_agent", sa.String(32)),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("reminder_sent_at", TS),
        sa.Column("completed_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_follow_up_tasks"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_follow_up_tasks_business_id_businesses"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE",
                                name="fk_follow_up_tasks_lead_id_leads"),
        sa.CheckConstraint("status IN ('open', 'done', 'canceled')",
                           name="ck_follow_up_tasks_status"),
        sa.CheckConstraint("kind IN ('first_contact', 'manual')", name="ck_follow_up_tasks_kind"),
        sa.CheckConstraint("(created_by_agent IS NULL) <> (created_by_user_id IS NULL)",
                           name="ck_follow_up_tasks_creator"),
    )  # fmt: skip
    op.create_index("ix_follow_up_tasks_business_id_lead_id", "follow_up_tasks",
                    ["business_id", "lead_id"])  # fmt: skip
    op.create_index("ix_follow_up_tasks_due", "follow_up_tasks", ["status", "due_at"])
    for stmt in enable_tenant_rls("follow_up_tasks"):
        op.execute(stmt)
    op.execute(CLAIM_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO agentree_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
    for stmt in disable_tenant_rls("follow_up_tasks"):
        op.execute(stmt)
    op.drop_table("follow_up_tasks")
