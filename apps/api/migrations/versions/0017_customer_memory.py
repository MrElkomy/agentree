"""Customer identity and memory (Task 16): profiles, guest-session links, email codes, memory.

Every table is tenant-scoped (RLS). Two narrow SECURITY DEFINER functions for the worker:
- `agentree_claim_memory_extractions` returns idle public conversations with new messages and
  marks them claimed (ids only, never content);
- `agentree_purge_customer_data` deletes expired memory items, profiles idle past the retention
  window (their memory cascades) and old email codes (U-12: nothing derived from a conversation
  outlives the raw window). Returns a count, never content.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
TABLES = ("customer_profiles", "customer_sessions", "customer_verifications",
          "customer_memory_items")  # fmt: skip
CATEGORIES = "'interest', 'owned', 'issue', 'preference', 'constraint'"
CLAIM = "agentree_claim_memory_extractions(timestamptz, integer)"
PURGE = "agentree_purge_customer_data(timestamptz, integer)"

CLAIM_FUNCTION = """
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

PURGE_FUNCTION = """
CREATE FUNCTION agentree_purge_customer_data(p_cutoff timestamptz, p_max_rows integer)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_items integer;
  v_profiles integer;
  v_codes integer;
BEGIN
  IF p_cutoff IS NULL OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 10000 THEN
    RAISE EXCEPTION 'invalid customer purge arguments';
  END IF;
  IF p_cutoff > now() - interval '1 day' THEN
    RAISE EXCEPTION 'retention cutoff must be at least one day in the past';
  END IF;
  WITH doomed AS (
    SELECT m.id FROM public.customer_memory_items m
     WHERE m.expires_at < now() OR m.created_at < p_cutoff
     LIMIT p_max_rows FOR UPDATE SKIP LOCKED
  )
  DELETE FROM public.customer_memory_items m USING doomed d WHERE m.id = d.id;
  GET DIAGNOSTICS v_items = ROW_COUNT;
  WITH idle AS (
    SELECT p.business_id, p.id FROM public.customer_profiles p
     WHERE p.last_seen_at < p_cutoff
     LIMIT p_max_rows FOR UPDATE SKIP LOCKED
  )
  DELETE FROM public.customer_profiles p USING idle i
   WHERE p.business_id = i.business_id AND p.id = i.id;
  GET DIAGNOSTICS v_profiles = ROW_COUNT;
  WITH old AS (
    SELECT v.id FROM public.customer_verifications v
     WHERE v.expires_at < now() - interval '1 day'
     LIMIT p_max_rows FOR UPDATE SKIP LOCKED
  )
  DELETE FROM public.customer_verifications v USING old o WHERE v.id = o.id;
  GET DIAGNOSTICS v_codes = ROW_COUNT;
  RETURN v_items + v_profiles + v_codes;
END
$$
"""


def upgrade() -> None:
    op.add_column("conversations", sa.Column("memory_extracted_at", TS, nullable=True))

    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254)),
        sa.Column("verified_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customer_profiles"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_customer_profiles_business_id_businesses"),
        sa.UniqueConstraint("business_id", "id", name="uq_customer_profiles_business_id"),
        sa.UniqueConstraint("business_id", "email", name="uq_customer_profiles_business_id_email"),
        sa.CheckConstraint("(email IS NULL) = (verified_at IS NULL)",
                           name="ck_customer_profiles_verified_email"),
    )  # fmt: skip
    op.create_index("ix_customer_profiles_business_id", "customer_profiles", ["business_id"])
    op.create_index("ix_customer_profiles_last_seen_at", "customer_profiles", ["last_seen_at"])

    op.create_table(
        "customer_sessions",
        sa.Column("guest_session_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("guest_session_id", name="pk_customer_sessions"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_customer_sessions_business_id_businesses"),
        sa.ForeignKeyConstraint(["business_id", "guest_session_id"],
                                ["guest_sessions.business_id", "guest_sessions.id"],
                                ondelete="CASCADE",
                                name="fk_customer_sessions_business_id_guest_sessions"),
        sa.ForeignKeyConstraint(["business_id", "customer_id"],
                                ["customer_profiles.business_id", "customer_profiles.id"],
                                ondelete="CASCADE",
                                name="fk_customer_sessions_business_id_customer_profiles"),
    )  # fmt: skip
    op.create_index("ix_customer_sessions_business_id", "customer_sessions", ["business_id"])
    op.create_index("ix_customer_sessions_customer_id", "customer_sessions", ["customer_id"])

    op.create_table(
        "customer_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("guest_session_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_customer_verifications"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_customer_verifications_business_id_businesses"),
        sa.ForeignKeyConstraint(["business_id", "guest_session_id"],
                                ["guest_sessions.business_id", "guest_sessions.id"],
                                ondelete="CASCADE",
                                name="fk_customer_verifications_business_id_guest_sessions"),
        sa.CheckConstraint("char_length(code_hash) = 64",
                           name="ck_customer_verifications_code_hash"),
        sa.CheckConstraint("attempts >= 0", name="ck_customer_verifications_attempts"),
    )  # fmt: skip
    op.create_index("ix_customer_verifications_business_id", "customer_verifications",
                    ["business_id"])  # fmt: skip
    op.create_index("ix_customer_verifications_guest_session_id", "customer_verifications",
                    ["guest_session_id"])  # fmt: skip
    op.create_index("ix_customer_verifications_expires_at", "customer_verifications",
                    ["expires_at"])  # fmt: skip

    op.create_table(
        "customer_memory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customer_memory_items"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_customer_memory_items_business_id_businesses"),
        sa.ForeignKeyConstraint(["business_id", "customer_id"],
                                ["customer_profiles.business_id", "customer_profiles.id"],
                                ondelete="CASCADE",
                                name="fk_customer_memory_items_business_id_customer_profiles"),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.id"],
                                ondelete="SET NULL",
                                name="fk_customer_memory_items_source_conversation_id_conversations"),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name="ck_customer_memory_items_category"),
        sa.CheckConstraint("char_length(value) BETWEEN 1 AND 200",
                           name="ck_customer_memory_items_value"),
        sa.CheckConstraint("expires_at <= created_at + interval '30 days'",
                           name="ck_customer_memory_items_expires_at"),
    )  # fmt: skip
    op.create_index("ix_customer_memory_items_business_id", "customer_memory_items",
                    ["business_id"])  # fmt: skip
    op.create_index("ix_customer_memory_items_customer_id", "customer_memory_items",
                    ["customer_id"])  # fmt: skip
    op.create_index("ix_customer_memory_items_expires_at", "customer_memory_items",
                    ["expires_at"])  # fmt: skip

    for table in TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)

    for fn, sig in ((CLAIM_FUNCTION, CLAIM), (PURGE_FUNCTION, PURGE)):
        op.execute(fn)
        op.execute(f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {sig} TO agentree_app")


def downgrade() -> None:
    for sig in (PURGE, CLAIM):
        op.execute(f"DROP FUNCTION IF EXISTS {sig}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
    op.drop_column("conversations", "memory_extracted_at")
