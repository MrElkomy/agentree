"""Email reports and alerts (Task 20c).

- `report_settings` (RLS): off / daily / weekly (weekday), optional Executive notes.
- `conversations.waiting_alerted_at`: a visitor still waiting for a person is alerted once.
- Two narrow SECURITY DEFINER functions for the worker, returning ids only:
  `agentree_claim_due_reports` picks businesses whose report is due in their own time zone
  (business hours' time zone, else UTC) from `p_hour` local on, marks them sent, and returns
  each business's daily reply budget (the notes count toward it);
  `agentree_claim_waiting_alerts` picks conversations waiting for a person since before the
  cutoff that were not alerted yet, and marks them.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
REPORTS = "agentree_claim_due_reports(integer, integer)"
WAITING = "agentree_claim_waiting_alerts(timestamptz, integer)"

REPORTS_FUNCTION = """
CREATE FUNCTION agentree_claim_due_reports(p_hour integer, p_max_rows integer)
RETURNS TABLE (business_id uuid, frequency text, daily_reply_budget integer)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_hour IS NULL OR p_hour < 0 OR p_hour > 23 OR p_max_rows IS NULL OR p_max_rows < 1
     OR p_max_rows > 500 THEN
    RAISE EXCEPTION 'invalid report claim arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT r.business_id, r.frequency::text AS frequency
      FROM public.report_settings r
      LEFT JOIN public.business_hours h ON h.business_id = r.business_id
     WHERE r.frequency <> 'off'
       AND extract(hour FROM now() AT TIME ZONE COALESCE(h.timezone, 'UTC')) >= p_hour
       AND (r.last_sent_at IS NULL
            OR (r.last_sent_at AT TIME ZONE COALESCE(h.timezone, 'UTC'))::date
               < (now() AT TIME ZONE COALESCE(h.timezone, 'UTC'))::date)
       AND (r.frequency = 'daily'
            OR extract(isodow FROM now() AT TIME ZONE COALESCE(h.timezone, 'UTC'))::integer - 1
               = r.weekday)
     LIMIT p_max_rows
     FOR UPDATE OF r SKIP LOCKED
  ), marked AS (
    UPDATE public.report_settings r SET last_sent_at = now()
      FROM due d
     WHERE r.business_id = d.business_id
    RETURNING r.business_id, d.frequency
  )
  SELECT m.business_id, m.frequency, COALESCE(p.daily_reply_budget, 200)
    FROM marked m LEFT JOIN public.public_profiles p ON p.business_id = m.business_id;
END
$$
"""

WAITING_FUNCTION = """
CREATE FUNCTION agentree_claim_waiting_alerts(p_before timestamptz, p_max_rows integer)
RETURNS TABLE (business_id uuid, conversation_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_before IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 500 THEN
    RAISE EXCEPTION 'invalid waiting alert arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT c.business_id, c.id FROM public.conversations c
     WHERE c.status = 'needs_human'
       AND c.handoff_requested_at < p_before
       AND (c.waiting_alerted_at IS NULL OR c.waiting_alerted_at < c.handoff_requested_at)
     ORDER BY c.handoff_requested_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  )
  UPDATE public.conversations c SET waiting_alerted_at = now()
    FROM due d
   WHERE c.business_id = d.business_id AND c.id = d.id
  RETURNING c.business_id, c.id;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "report_settings",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("frequency", sa.String(8), server_default="off", nullable=False),
        sa.Column("weekday", sa.Integer(), server_default="0", nullable=False),
        sa.Column("include_notes", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_sent_at", TS),
        sa.Column("updated_by_user_id", sa.Uuid()),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("business_id", name="pk_report_settings"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_report_settings_business_id_businesses"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_report_settings_updated_by_user_id_users"),
        sa.CheckConstraint("frequency IN ('off', 'daily', 'weekly')",
                           name="ck_report_settings_frequency"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_report_settings_weekday"),
    )  # fmt: skip
    for stmt in enable_tenant_rls("report_settings"):
        op.execute(stmt)
    op.add_column("conversations", sa.Column("waiting_alerted_at", TS, nullable=True))
    for fn, sig in ((REPORTS_FUNCTION, REPORTS), (WAITING_FUNCTION, WAITING)):
        op.execute(fn)
        op.execute(f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {sig} TO agentree_app")


def downgrade() -> None:
    for sig in (WAITING, REPORTS):
        op.execute(f"DROP FUNCTION IF EXISTS {sig}")
    op.drop_column("conversations", "waiting_alerted_at")
    for stmt in disable_tenant_rls("report_settings"):
        op.execute(stmt)
    op.drop_table("report_settings")
