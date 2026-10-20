"""Public AI page profile, anonymous guest sessions, guest-owned conversations, retention.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
TABLES = ("public_profiles", "guest_sessions")
SIGNATURE = "agentree_purge_expired_conversations(timestamptz, integer)"

# 0008: the purge additionally deletes stale guest sessions (last_seen_at before the cutoff).
# It runs as a second statement, after the conversation purge, so it sees what that purge
# left behind, and it only deletes sessions that own NO conversation any more. The
# ON DELETE CASCADE from conversations to guest_sessions therefore never removes anything:
# conversations on legal hold (or still active) keep their session row, and a session is
# only deleted once the conversation rule has already deleted all its conversations.
# Sessions have a fixed 30-day lifetime, so a session idle past the cutoff is already
# expired and cannot be in use. The return value is the total number of rows deleted
# (conversations + guest sessions), still never content. Guards are unchanged from 0006.
PURGE_FUNCTION_V2 = """
CREATE OR REPLACE FUNCTION agentree_purge_expired_conversations(
  p_cutoff timestamptz, p_max_rows integer)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_deleted integer;
  v_sessions integer;
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
  WITH stale AS (
    SELECT g.business_id, g.id FROM public.guest_sessions g
     WHERE g.last_seen_at < p_cutoff
       AND g.created_at < p_cutoff
       AND NOT EXISTS (
         SELECT 1 FROM public.conversations c
          WHERE c.business_id = g.business_id AND c.guest_session_id = g.id)
     ORDER BY g.last_seen_at
     LIMIT p_max_rows
     FOR UPDATE SKIP LOCKED
  )
  DELETE FROM public.guest_sessions g USING stale s
   WHERE g.business_id = s.business_id AND g.id = s.id;
  GET DIAGNOSTICS v_sessions = ROW_COUNT;
  RETURN v_deleted + v_sessions;
END
$$
"""

# Exact 0006 definition, restored on downgrade.
PURGE_FUNCTION_V1 = """
CREATE OR REPLACE FUNCTION agentree_purge_expired_conversations(
  p_cutoff timestamptz, p_max_rows integer)
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


def _secure_function() -> None:
    # CREATE OR REPLACE keeps owner and grants; re-assert them anyway (idempotent).
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO agentree_app")


def upgrade() -> None:
    op.create_table(
        "public_profiles",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("display_name", sa.String(80)),
        sa.Column("bio", sa.String(500), server_default="", nullable=False),
        sa.Column("links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column(
            "widget_origins", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("daily_reply_budget", sa.Integer(), server_default="200", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("business_id", name="pk_public_profiles"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_public_profiles_business_id_businesses"),
        sa.CheckConstraint("daily_reply_budget BETWEEN 1 AND 5000",
                           name="ck_public_profiles_daily_reply_budget"),
        sa.CheckConstraint("jsonb_typeof(links) = 'array' AND jsonb_array_length(links) <= 10",
                           name="ck_public_profiles_links_array"),
        sa.CheckConstraint(
            "jsonb_typeof(widget_origins) = 'array' AND jsonb_array_length(widget_origins) <= 10",
            name="ck_public_profiles_widget_origins_array",
        ),
    )  # fmt: skip

    op.create_table(
        "guest_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_guest_sessions"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_guest_sessions_business_id_businesses"),
        sa.UniqueConstraint("business_id", "id", name="uq_guest_sessions_business_id"),
        sa.UniqueConstraint("token_hash", name="uq_guest_sessions_token_hash"),
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_guest_sessions_token_hash"),
    )  # fmt: skip
    op.create_index("ix_guest_sessions_business_id", "guest_sessions", ["business_id"])
    op.create_index("ix_guest_sessions_last_seen_at", "guest_sessions", ["last_seen_at"])

    op.add_column("conversations", sa.Column("guest_session_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_business_id_guest_sessions", "conversations", "guest_sessions",
        ["business_id", "guest_session_id"], ["business_id", "id"], ondelete="CASCADE",
    )  # fmt: skip
    op.create_index("ix_conversations_guest_session_id", "conversations", ["guest_session_id"])
    op.create_check_constraint(
        "ck_conversations_channel", "conversations", "channel IN ('console', 'public', 'widget')"
    )
    # A public conversation always belongs to exactly one guest session; console ones never do.
    op.create_check_constraint(
        "ck_conversations_guest_channel",
        "conversations",
        "(channel = 'console') = (guest_session_id IS NULL)",
    )

    for table in TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)

    op.execute(PURGE_FUNCTION_V2)
    _secure_function()


def downgrade() -> None:
    op.execute(PURGE_FUNCTION_V1)
    _secure_function()
    # Guest conversations cannot be represented in the 0007 schema (no owner column).
    op.execute("DELETE FROM conversations WHERE guest_session_id IS NOT NULL")
    op.drop_constraint("ck_conversations_guest_channel", "conversations", type_="check")
    op.drop_constraint("ck_conversations_channel", "conversations", type_="check")
    op.drop_index("ix_conversations_guest_session_id", table_name="conversations")
    op.drop_constraint(
        "fk_conversations_business_id_guest_sessions", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "guest_session_id")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
