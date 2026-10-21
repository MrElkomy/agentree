"""Customer memory controls: "Remember customers" per business; extraction counts toward the
daily AI budget (the claim returns the business's budget and skips businesses that turned it off).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLAIM = "agentree_claim_memory_extractions(timestamptz, integer)"

CLAIM_FUNCTION_V2 = """
CREATE FUNCTION agentree_claim_memory_extractions(p_idle_before timestamptz, p_max_rows integer)
RETURNS TABLE (business_id uuid, conversation_id uuid, daily_reply_budget integer)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_idle_before IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 500 THEN
    RAISE EXCEPTION 'invalid memory claim arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT c.business_id, c.id, p.daily_reply_budget FROM public.conversations c
      JOIN public.public_profiles p ON p.business_id = c.business_id AND p.customer_memory
     WHERE c.guest_session_id IS NOT NULL
       AND c.last_message_at < p_idle_before
       AND c.last_message_at > now() - interval '30 days'
       AND (c.memory_extracted_at IS NULL OR c.memory_extracted_at < c.last_message_at)
     ORDER BY c.last_message_at
     LIMIT p_max_rows
     FOR UPDATE OF c SKIP LOCKED
  )
  UPDATE public.conversations c SET memory_extracted_at = now()
    FROM due d
   WHERE c.business_id = d.business_id AND c.id = d.id
  RETURNING c.business_id, c.id, d.daily_reply_budget;
END
$$
"""

# Exact 0017 definition, restored on downgrade.
CLAIM_FUNCTION_V1 = """
CREATE FUNCTION agentree_claim_memory_extractions(p_idle_before timestamptz, p_max_rows integer)
RETURNS TABLE (business_id uuid, conversation_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_idle_before IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 500 THEN
    RAISE EXCEPTION 'invalid memory claim arguments';
  END IF;
  RETURN QUERY
  WITH due AS (
    SELECT c.business_id, c.id FROM public.conversations c
     WHERE c.guest_session_id IS NOT NULL
       AND c.last_message_at < p_idle_before
       AND c.last_message_at > now() - interval '30 days'
       AND (c.memory_extracted_at IS NULL OR c.memory_extracted_at < c.last_message_at)
     ORDER BY c.last_message_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  )
  UPDATE public.conversations c SET memory_extracted_at = now()
    FROM due d
   WHERE c.business_id = d.business_id AND c.id = d.id
  RETURNING c.business_id, c.id;
END
$$
"""


def _replace(definition: str) -> None:
    # The result columns change, so the function is dropped and created again (not replaced).
    op.execute(f"DROP FUNCTION IF EXISTS {CLAIM}")
    op.execute(definition)
    op.execute(f"REVOKE ALL ON FUNCTION {CLAIM} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {CLAIM} TO agentree_app")


def upgrade() -> None:
    op.add_column(
        "public_profiles",
        sa.Column("customer_memory", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    _replace(CLAIM_FUNCTION_V2)


def downgrade() -> None:
    _replace(CLAIM_FUNCTION_V1)
    op.drop_column("public_profiles", "customer_memory")
