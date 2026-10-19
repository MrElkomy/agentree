"""Knowledge base entries (full-text search) and console conversations/messages, with RLS.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

from agentree.tenancy.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
TABLES = ("knowledge_entries", "conversations", "conversation_messages")


def upgrade() -> None:
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))",
                persisted=True,
            ),
        ),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("published_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_entries"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            ondelete="CASCADE",
            name="fk_knowledge_entries_business_id_businesses",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_knowledge_entries_created_by_user_id_users",
        ),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_knowledge_entries_status"),
    )
    op.create_index("ix_knowledge_entries_business_id", "knowledge_entries", ["business_id"])
    op.create_index(
        "ix_knowledge_entries_search_vector", "knowledge_entries", ["search_vector"],
        postgresql_using="gin",
    )  # fmt: skip

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("active_agent", sa.String(32), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                name="fk_conversations_business_id_businesses"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_conversations_created_by_user_id_users"),
        sa.UniqueConstraint("business_id", "id", name="uq_conversations_business_id"),
    )  # fmt: skip
    op.create_index("ix_conversations_business_id", "conversations", ["business_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("agent", sa.String(32)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("model", sa.String(100)),
        sa.Column("provider_slot", sa.String(16)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
        sa.ForeignKeyConstraint(
            ["business_id", "conversation_id"], ["conversations.business_id", "conversations.id"],
            ondelete="CASCADE", name="fk_conversation_messages_business_id_conversations",
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
    )  # fmt: skip
    op.create_index(
        "ix_conversation_messages_business_id", "conversation_messages", ["business_id"]
    )
    op.create_index(
        "ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]
    )
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])

    for table in TABLES:
        for stmt in enable_tenant_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls(table):
            op.execute(stmt)
        op.drop_table(table)
