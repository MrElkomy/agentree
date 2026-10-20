"""30-day raw conversation retention: legal-hold flag and a cross-tenant purge function.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "agentree_purge_expired_conversations(timestamptz, integer)"

# Narrow SECURITY DEFINER purge for the retention worker (AGT-010 / TD-18). Owned by the
# migrator (table owner, not subject to RLS); EXECUTE only for agentree_app. It deletes
# whole conversations (messages first, then the conversation) whose last activity is older
# than the cutoff and that are not on legal hold. Last activity is the latest of the
# conversation's created_at, last_message_at and every message's created_at, so a recent
# message always keeps its conversation. Returns only a count, never content.
# Cutoffs newer than one day are refused to bound the damage a misconfigured or
# compromised caller can do; rows locked by an in-flight turn are skipped, not waited on.
PURGE_FUNCTION = """
CREATE FUNCTION agentree_purge_expired_conversations(p_cutoff timestamptz, p_max_rows integer)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_deleted integer;
BEGIN
  IF p_cutoff IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 10000 THEN
    RAISE EXCEPTION 'invalid retention purge arguments';
  END IF;
  IF p_cutoff > now() - interval '1 day' THEN
    RAISE EXCEPTION 'retention cutoff must be at least one day in the past';
  END IF;
  WITH doomed AS (
    SELECT c.business_id, c.id FROM public.conversations c
     WHERE NOT c.legal_hold
       AND c.created_at < p_cutoff
       AND c.last_message_at < p_cutoff
       AND NOT EXISTS (
         SELECT 1 FROM public.conversation_messages m
          WHERE m.business_id = c.business_id AND m.conversation_id = c.id
            AND m.created_at >= p_cutoff)
     ORDER BY c.last_message_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  ), gone_messages AS (
    DELETE FROM public.conversation_messages m USING doomed d
     WHERE m.business_id = d.business_id AND m.conversation_id = d.id
  )
  DELETE FROM public.conversations c USING doomed d
   WHERE c.business_id = d.business_id AND c.id = d.id;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END
$$
"""


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("legal_hold", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(PURGE_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO agentree_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
    op.drop_column("conversations", "legal_hold")
