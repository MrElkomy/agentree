"""BYOK provider credentials (envelope-encrypted), tenant-scoped with RLS.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("key_hint", sa.String(8), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("master_key_id", sa.String(32), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("last_verified_at", TS),
        sa.Column("last_error_kind", sa.String(32)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_provider_credentials"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_provider_credentials_business_id_businesses"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_provider_credentials_created_by_user_id_users"),
        sa.UniqueConstraint("business_id", "slot", name="uq_provider_credentials_business_id"),
        sa.CheckConstraint("slot IN ('primary', 'backup')", name="ck_provider_credentials_slot"),
        sa.CheckConstraint("provider IN ('openai', 'anthropic', 'gemini')",
                           name="ck_provider_credentials_provider"),
    )  # fmt: skip
    op.create_index("ix_provider_credentials_business_id", "provider_credentials", ["business_id"])
    for stmt in enable_tenant_rls("provider_credentials"):
        op.execute(stmt)


def downgrade() -> None:
    for stmt in disable_tenant_rls("provider_credentials"):
        op.execute(stmt)
    op.drop_table("provider_credentials")
