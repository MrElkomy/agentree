"""Business hours and agent availability (Task 20b, PO decision 2026-10-22).

- `business_hours`: one time zone and one range per weekday per business.
- `agent_availability`: per agent, answer always / during business hours / outside them, plus an
  optional pause (e.g. a holiday) and the fixed messages visitors get meanwhile.
- The daily metrics function now counts those fixed messages (assistant messages without a
  provider) as `away_replies`, never as AI replies.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
ROLES = "'sales', 'customer_service', 'technical_support', 'data_analyst', 'executive'"
MODES = "'always', 'business_hours', 'outside_business_hours'"

# Metric names must match agentree/analytics/service.py (METRICS).
COMPUTE_FUNCTION = """
CREATE OR REPLACE FUNCTION agentree_compute_daily_metrics(p_day date)
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
           CASE WHEN m.role = 'user' THEN 'visitor_messages'
                WHEN m.role = 'assistant' AND m.provider IS NULL THEN 'away_replies'
                WHEN m.role = 'assistant' THEN 'ai_replies'
                ELSE 'team_replies' END AS metric,
           count(*)
      FROM public.conversation_messages m
      JOIN public.conversations c ON c.business_id = m.business_id AND c.id = m.conversation_id
     WHERE c.channel IN ('public', 'widget') AND m.created_at >= v_from AND m.created_at < v_to
     GROUP BY m.business_id, 2
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

# As created in 0020 (restored on downgrade).
PREVIOUS_COMPUTE_FUNCTION = """
CREATE OR REPLACE FUNCTION agentree_compute_daily_metrics(p_day date)
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
        "business_hours",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("days", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid()),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("business_id", name="pk_business_hours"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_business_hours_business_id_businesses"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_business_hours_updated_by_user_id_users"),
    )  # fmt: skip
    op.create_table(
        "agent_availability",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), server_default="always", nullable=False),
        sa.Column("away_message", sa.String(500), server_default="", nullable=False),
        sa.Column("paused_from", TS),
        sa.Column("paused_until", TS),
        sa.Column("pause_message", sa.String(500), server_default="", nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid()),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_availability"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_agent_availability_business_id_businesses"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_agent_availability_updated_by_user_id_users"),
        sa.UniqueConstraint("business_id", "role", name="uq_agent_availability_business_id"),
        sa.CheckConstraint(f"role IN ({ROLES})", name="ck_agent_availability_role"),
        sa.CheckConstraint(f"mode IN ({MODES})", name="ck_agent_availability_mode"),
        sa.CheckConstraint(
            "paused_until IS NULL OR paused_from IS NULL OR paused_from < paused_until",
            name="ck_agent_availability_pause_window",
        ),
    )  # fmt: skip
    for table in ("business_hours", "agent_availability"):
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)
    op.execute(COMPUTE_FUNCTION)


def downgrade() -> None:
    op.execute(PREVIOUS_COMPUTE_FUNCTION)
    for table in ("agent_availability", "business_hours"):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
