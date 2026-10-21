"""Daily operational metrics (Task 18): privacy-conscious aggregates per business per UTC day.

Counts only: no message text, no customer data, no ids of people. They outlive the 30-day raw
window by design (approved: daily aggregated operational metrics with their own retention) and
are kept 13 months. Computed by the worker through a SECURITY DEFINER function that returns a
count, never content.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPUTE = "agentree_compute_daily_metrics(date)"

# Metric names must match agentree/analytics/service.py (METRICS).
COMPUTE_FUNCTION = """
CREATE FUNCTION agentree_compute_daily_metrics(p_day date)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_from timestamptz;
  v_to timestamptz;
  v_rows integer;
BEGIN
  IF p_day IS NULL OR p_day > (now() AT TIME ZONE 'UTC')::date
     OR p_day < (now() AT TIME ZONE 'UTC')::date - 31 THEN
    RAISE EXCEPTION 'invalid metrics day';
  END IF;
  v_from := p_day::timestamp AT TIME ZONE 'UTC';
  v_to := v_from + interval '1 day';
  DELETE FROM public.daily_metrics WHERE day = p_day;
  INSERT INTO public.daily_metrics (business_id, day, metric, value)
  SELECT business_id, p_day, metric, n FROM (
    SELECT c.business_id, 'conversations' AS metric, count(*) AS n
      FROM public.conversations c
     WHERE c.channel IN ('public', 'widget') AND c.created_at >= v_from AND c.created_at < v_to
     GROUP BY c.business_id
    UNION ALL
    SELECT m.business_id,
           CASE m.role WHEN 'user' THEN 'visitor_messages' WHEN 'assistant' THEN 'ai_replies'
                       ELSE 'team_replies' END,
           count(*)
      FROM public.conversation_messages m
      JOIN public.conversations c ON c.business_id = m.business_id AND c.id = m.conversation_id
     WHERE c.channel IN ('public', 'widget') AND m.created_at >= v_from AND m.created_at < v_to
     GROUP BY m.business_id, m.role
    UNION ALL
    SELECT a.business_id,
           CASE a.action
             WHEN 'conversation.handoff_requested' THEN 'handoffs_to_team'
             WHEN 'agent.handoff' THEN 'agent_handoffs'
             WHEN 'conversation.resolved' THEN 'resolved'
             WHEN 'lead.created' THEN 'leads'
             WHEN 'customer.verified' THEN 'customers_verified'
           END,
           count(*)
      FROM public.audit_events a
     WHERE a.created_at >= v_from AND a.created_at < v_to
       AND a.action IN ('conversation.handoff_requested', 'agent.handoff',
                        'conversation.resolved', 'lead.created', 'customer.verified')
       AND (a.action <> 'agent.handoff' OR a.details->>'channel' IN ('public', 'widget'))
     GROUP BY a.business_id, a.action
  ) t
  WHERE n > 0;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  INSERT INTO public.metric_days (day, computed_at) VALUES (p_day, now())
  ON CONFLICT (day) DO UPDATE SET computed_at = EXCLUDED.computed_at;
  -- Own retention: 13 months.
  DELETE FROM public.daily_metrics WHERE day < (now() AT TIME ZONE 'UTC')::date - 400;
  DELETE FROM public.metric_days WHERE day < (now() AT TIME ZONE 'UTC')::date - 400;
  RETURN v_rows;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("business_id", "day", "metric", name="pk_daily_metrics"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_daily_metrics_business_id_businesses"),
        sa.CheckConstraint("value >= 0", name="ck_daily_metrics_value"),
    )  # fmt: skip
    op.create_index("ix_daily_metrics_day", "daily_metrics", ["day"])
    # Which UTC days the job has computed (no tenant data: dates only).
    op.create_table(
        "metric_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("day", name="pk_metric_days"),
    )
    for stmt in enable_tenant_rls("daily_metrics"):
        op.execute(stmt)
    op.execute(COMPUTE_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {COMPUTE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {COMPUTE} TO agentree_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {COMPUTE}")
    op.drop_table("metric_days")
    for stmt in disable_tenant_rls("daily_metrics"):
        op.execute(stmt)
    op.drop_table("daily_metrics")
