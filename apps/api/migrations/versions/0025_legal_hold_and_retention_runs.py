"""Legal hold, retention run records and per-agent outcomes (Task 21).

- `retention_runs` (global, no tenant data): one record per retention pass that ran (counts and
  times only), written through `agentree_record_retention_run` (SECURITY DEFINER, validated,
  keeps 400 days). The app role may read it; nobody can change a record.
- The daily metrics function also counts per-agent outcomes as `agent:<role>:<outcome>`
  (replies, conversations, resolved, to_team, handoffs_out) from messages and audit events.
- Legal hold itself already exists (`conversations.legal_hold`, honoured by the retention purge
  since 0006); Task 21 adds the Owner-only API.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
RECORD = "agentree_record_retention_run(timestamptz, timestamptz, timestamptz, integer, integer)"

RECORD_FUNCTION = """
CREATE FUNCTION agentree_record_retention_run(
  p_started timestamptz, p_finished timestamptz, p_cutoff timestamptz, p_rows integer,
  p_batches integer)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_started IS NULL OR p_finished IS NULL OR p_cutoff IS NULL OR p_rows IS NULL
     OR p_batches IS NULL OR p_rows < 0 OR p_batches < 0 OR p_finished < p_started
     OR p_finished > now() + interval '1 minute' OR p_cutoff > p_started THEN
    RAISE EXCEPTION 'invalid retention run record';
  END IF;
  INSERT INTO public.retention_runs (started_at, finished_at, cutoff, rows_deleted, batches)
  VALUES (p_started, p_finished, p_cutoff, p_rows, p_batches);
  DELETE FROM public.retention_runs WHERE finished_at < now() - interval '400 days';
END
$$
"""

# Metric names must match agentree/analytics/service.py (METRICS, agent outcomes).
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
    UNION ALL
    -- Per-agent outcomes (Task 21): "agent:<role>:<outcome>".
    SELECT m.business_id, concat_ws(':', 'agent', m.agent, 'replies'), count(*)
      FROM public.conversation_messages m
      JOIN public.conversations c ON c.business_id = m.business_id AND c.id = m.conversation_id
     WHERE c.channel IN ('public', 'widget') AND m.created_at >= v_from AND m.created_at < v_to
       AND m.role = 'assistant' AND m.provider IS NOT NULL AND m.agent IS NOT NULL
     GROUP BY m.business_id, m.agent
    UNION ALL
    SELECT m.business_id, concat_ws(':', 'agent', m.agent, 'conversations'),
           count(DISTINCT m.conversation_id)
      FROM public.conversation_messages m
      JOIN public.conversations c ON c.business_id = m.business_id AND c.id = m.conversation_id
     WHERE c.channel IN ('public', 'widget') AND m.created_at >= v_from AND m.created_at < v_to
       AND m.role = 'assistant' AND m.provider IS NOT NULL AND m.agent IS NOT NULL
     GROUP BY m.business_id, m.agent
    UNION ALL
    SELECT a.business_id,
           concat_ws(':', 'agent',
                     CASE a.action WHEN 'agent.handoff' THEN a.details->>'from_agent'
                                   ELSE a.details->>'agent' END,
                     CASE a.action WHEN 'conversation.resolved' THEN 'resolved'
                                   WHEN 'conversation.handoff_requested' THEN 'to_team'
                                   ELSE 'handoffs_out' END),
           count(*)
      FROM public.audit_events a
     WHERE a.created_at >= v_from AND a.created_at < v_to
       AND a.action IN ('conversation.resolved', 'conversation.handoff_requested', 'agent.handoff')
       AND (a.action <> 'agent.handoff' OR a.details->>'channel' IN ('public', 'widget'))
       AND COALESCE(CASE a.action WHEN 'agent.handoff' THEN a.details->>'from_agent'
                                  ELSE a.details->>'agent' END, '') <> ''
     GROUP BY 1, 2
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

# As in 0023 (restored on downgrade).
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


def upgrade() -> None:
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=False),
        sa.Column("cutoff", TS, nullable=False),
        sa.Column("rows_deleted", sa.Integer(), nullable=False),
        sa.Column("batches", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_retention_runs"),
        sa.CheckConstraint("rows_deleted >= 0 AND batches >= 0",
                           name="ck_retention_runs_counts"),
    )  # fmt: skip
    op.create_index("ix_retention_runs_finished_at", "retention_runs", ["finished_at"])
    # Default privileges give the app role write access to new tables: take it back, so a
    # record is only ever added through the validated function and never changed.
    op.execute("REVOKE ALL ON retention_runs FROM PUBLIC")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON retention_runs FROM agentree_app")
    op.execute("GRANT SELECT ON retention_runs TO agentree_app")
    op.execute(RECORD_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {RECORD} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD} TO agentree_app")
    op.execute(COMPUTE_FUNCTION)


def downgrade() -> None:
    op.execute(PREVIOUS_COMPUTE_FUNCTION)
    op.execute(f"DROP FUNCTION IF EXISTS {RECORD}")
    op.drop_table("retention_runs")
