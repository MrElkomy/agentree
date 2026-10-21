"""Leads (linked to conversations) and the Action Gateway's idempotency ledger, both with RLS.

A lead outlives its conversation: when the 30-day retention job deletes the conversation, only
`conversation_id` is cleared (ON DELETE SET NULL on that column). One lead per conversation.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
STATUSES = "('new', 'contacted', 'qualified', 'won', 'lost')"


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid()),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("source_agent", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(32)),
        sa.Column("need", sa.Text(), nullable=False, server_default=""),
        sa.Column("consent_at", TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_leads_business_id_businesses"),
        sa.ForeignKeyConstraint(["business_id", "conversation_id"],
                                ["conversations.business_id", "conversations.id"],
                                ondelete="SET NULL (conversation_id)",
                                name="fk_leads_business_id_conversations"),
        sa.UniqueConstraint("business_id", "conversation_id", name="uq_leads_business_id"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_leads_status"),
        sa.CheckConstraint("channel IN ('public', 'widget')", name="ck_leads_channel"),
        sa.CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_leads_contact"),
        sa.CheckConstraint("char_length(need) <= 500 AND char_length(notes) <= 2000",
                           name="ck_leads_lengths"),
    )  # fmt: skip
    op.create_index("ix_leads_business_id_id", "leads", ["business_id", "id"])
    for stmt in enable_tenant_rls("leads"):
        op.execute(stmt)

    op.create_table(
        "action_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("result_id", sa.Uuid()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_action_executions"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_action_executions_business_id_businesses"),
        sa.UniqueConstraint("business_id", "idempotency_key",
                            name="uq_action_executions_business_id"),
    )  # fmt: skip
    for stmt in enable_tenant_rls("action_executions"):
        op.execute(stmt)


def downgrade() -> None:
    for table in ("action_executions", "leads"):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
