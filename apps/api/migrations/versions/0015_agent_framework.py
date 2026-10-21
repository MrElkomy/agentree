"""Agent framework: per-business agent configuration and agent-to-agent handoffs.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
ROLES = "'sales', 'customer_service', 'technical_support', 'data_analyst', 'executive'"


def upgrade() -> None:
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("display_name", sa.String(40), server_default="", nullable=False),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("tools", ARRAY(sa.String(64)), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid()),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_configs"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_agent_configs_business_id_businesses"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_agent_configs_updated_by_user_id_users"),
        sa.UniqueConstraint("business_id", "role", name="uq_agent_configs_business_id"),
        sa.CheckConstraint(f"role IN ({ROLES})", name="ck_agent_configs_role"),
        sa.CheckConstraint("version >= 1", name="ck_agent_configs_version"),
    )  # fmt: skip
    for stmt in enable_tenant_rls("agent_configs"):
        op.execute(stmt)

    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("from_agent", sa.String(32), nullable=False),
        sa.Column("to_agent", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_handoffs"),
        # Same-business conversation; deleted with it (retention).
        sa.ForeignKeyConstraint(
            ["business_id", "conversation_id"], ["conversations.business_id", "conversations.id"],
            ondelete="CASCADE", name="fk_agent_handoffs_business_id_conversations",
        ),
        sa.CheckConstraint(f"from_agent IN ({ROLES})", name="ck_agent_handoffs_from_agent"),
        sa.CheckConstraint(f"to_agent IN ({ROLES})", name="ck_agent_handoffs_to_agent"),
        sa.CheckConstraint("from_agent <> to_agent", name="ck_agent_handoffs_distinct_agents"),
    )  # fmt: skip
    op.create_index("ix_agent_handoffs_business_id_conversation_id", "agent_handoffs",
                    ["business_id", "conversation_id"])  # fmt: skip
    for stmt in enable_tenant_rls("agent_handoffs"):
        op.execute(stmt)

    op.create_check_constraint(
        "ck_conversations_active_agent", "conversations", f"active_agent IN ({ROLES})"
    )


def downgrade() -> None:
    op.drop_constraint("ck_conversations_active_agent", "conversations", type_="check")
    for table in ("agent_handoffs", "agent_configs"):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
