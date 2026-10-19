"""Identity (users, sessions, one-time tokens, rate limits) and business memberships/invitations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)

# Narrow SECURITY DEFINER lookups that must work before a tenant context exists.
# Owned by the migrator (table owner, not subject to RLS); EXECUTE only for agentree_app.
FUNCTIONS = {
    "agentree_membership_role(uuid, uuid)": """
CREATE FUNCTION agentree_membership_role(p_user uuid, p_business uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$ SELECT role FROM public.business_memberships
      WHERE user_id = p_user AND business_id = p_business $$
""",
    "agentree_user_businesses(uuid)": """
CREATE FUNCTION agentree_user_businesses(p_user uuid)
RETURNS TABLE (business_id uuid, name text, slug text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$ SELECT b.id, b.name::text, b.slug::text, m.role::text
      FROM public.business_memberships m JOIN public.businesses b ON b.id = m.business_id
      WHERE m.user_id = p_user ORDER BY b.name $$
""",
    "agentree_claim_invitation(text, uuid)": """
CREATE FUNCTION agentree_claim_invitation(p_token_hash text, p_user uuid) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  v_email text;
  v_inv record;
BEGIN
  SELECT email_normalized INTO v_email FROM public.users
   WHERE id = p_user AND email_verified_at IS NOT NULL;
  IF v_email IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT id, business_id, role INTO v_inv FROM public.business_invitations
   WHERE token_hash = p_token_hash AND email_normalized = v_email
     AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
   FOR UPDATE;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  INSERT INTO public.business_memberships (business_id, user_id, role)
  VALUES (v_inv.business_id, p_user, v_inv.role)
  ON CONFLICT (business_id, user_id) DO NOTHING;
  UPDATE public.business_invitations SET accepted_at = now(), accepted_by_user_id = p_user
   WHERE id = v_inv.id;
  RETURN v_inv.business_id;
END
$$
""",
}

ROLE_CHECK = "role IN ('owner', 'admin', 'member')"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email_verified_at", TS),
        sa.Column("password_changed_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        sa.CheckConstraint(
            "email_normalized = lower(email_normalized)", name="ck_users_email_lower"
        ),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_user_sessions_user_id_users"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )  # fmt: skip
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_tokens"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_auth_tokens_user_id_users"),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
        sa.CheckConstraint("purpose IN ('verify_email', 'reset_password')",
                           name="ck_auth_tokens_purpose"),
    )  # fmt: skip
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("window_start", TS, nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_rate_limit_buckets"),
    )

    op.create_table(
        "business_memberships",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("business_id", "user_id", name="pk_business_memberships"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_business_memberships_business_id_businesses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_business_memberships_user_id_users"),
        sa.CheckConstraint(ROLE_CHECK, name="ck_business_memberships_role"),
    )  # fmt: skip
    op.create_index("ix_business_memberships_user_id", "business_memberships", ["user_id"])
    op.create_table(
        "business_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("accepted_at", TS),
        sa.Column("accepted_by_user_id", sa.Uuid()),
        sa.Column("revoked_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_business_invitations"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_business_invitations_business_id_businesses"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_business_invitations_invited_by_user_id_users"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_business_invitations_accepted_by_user_id_users"),
        sa.UniqueConstraint("token_hash", name="uq_business_invitations_token_hash"),
        sa.CheckConstraint(ROLE_CHECK, name="ck_business_invitations_role"),
    )  # fmt: skip
    op.create_index("ix_business_invitations_business_id", "business_invitations", ["business_id"])
    for table in ("business_memberships", "business_invitations"):
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)

    for signature, ddl in FUNCTIONS.items():
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO agentree_app")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    for table in ("business_invitations", "business_memberships"):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
    for table in ("rate_limit_buckets", "auth_tokens", "user_sessions", "users"):
        op.drop_table(table)
