"""Human inbox: conversation status, assignee and handoff fields; human-written messages.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("conversations", sa.Column("status", sa.String(16), server_default="open",
                                             nullable=False))  # fmt: skip
    op.add_column("conversations", sa.Column("assignee_user_id", sa.Uuid()))
    op.add_column("conversations", sa.Column("handoff_requested_at", TS))
    op.add_column("conversations", sa.Column("handoff_reason", sa.String(16)))
    op.create_check_constraint(
        "ck_conversations_status", "conversations",
        "status IN ('open', 'needs_human', 'human_active', 'resolved')",
    )  # fmt: skip
    op.create_check_constraint(
        "ck_conversations_handoff_reason", "conversations",
        "handoff_reason IS NULL OR handoff_reason IN ('visitor', 'agent')",
    )  # fmt: skip
    op.create_index("ix_conversations_business_id_status", "conversations",
                    ["business_id", "status"])  # fmt: skip

    op.add_column("conversation_messages", sa.Column("author_user_id", sa.Uuid()))
    op.drop_constraint("ck_conversation_messages_role", "conversation_messages", type_="check")
    op.create_check_constraint(
        "ck_conversation_messages_role", "conversation_messages",
        "role IN ('user', 'assistant', 'human')",
    )  # fmt: skip
    op.create_check_constraint(
        "ck_conversation_messages_author", "conversation_messages",
        "(role = 'human') = (author_user_id IS NOT NULL)",
    )  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM conversation_messages WHERE role = 'human'")
    op.drop_constraint("ck_conversation_messages_author", "conversation_messages", type_="check")
    op.drop_constraint("ck_conversation_messages_role", "conversation_messages", type_="check")
    op.create_check_constraint(
        "ck_conversation_messages_role", "conversation_messages", "role IN ('user', 'assistant')"
    )
    op.drop_column("conversation_messages", "author_user_id")
    op.drop_index("ix_conversations_business_id_status", "conversations")
    op.drop_constraint("ck_conversations_handoff_reason", "conversations", type_="check")
    op.drop_constraint("ck_conversations_status", "conversations", type_="check")
    for column in ("handoff_reason", "handoff_requested_at", "assignee_user_id", "status"):
        op.drop_column("conversations", column)
