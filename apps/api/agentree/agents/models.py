"""Conversations and messages. RLS: tenant-scoped on business_id.

Raw message content is subject to the 30-day retention policy (AGT-010): the worker's
retention job (`agentree.retention`) hard-deletes conversations whose last activity is older
than the window, unless `legal_hold` is set (no API sets it yet).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("business_id", "id"),
        # Composite FK: a conversation can only belong to a guest session of its own business.
        # The guest_sessions table is owned by `agentree.public`; only the FK lives here.
        ForeignKeyConstraint(
            ["business_id", "guest_session_id"],
            ["guest_sessions.business_id", "guest_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("channel IN ('console', 'public', 'widget')", name="channel"),
        CheckConstraint("(channel = 'console') = (guest_session_id IS NULL)", name="guest_channel"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))  # console | public | widget
    active_agent: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Anonymous visitor that owns a public/widget conversation (NULL for the console).
    guest_session_id: Mapped[UUID | None] = mapped_column(index=True)
    # Exempts the conversation from retention deletion. Owner-only, audited API: not built yet.
    legal_hold: Mapped[bool] = mapped_column(Boolean, server_default=false())


class Message(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        # Composite FK: a message can only reference a conversation of the same business.
        ForeignKeyConstraint(
            ["business_id", "conversation_id"],
            ["conversations.business_id", "conversations.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(index=True)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    agent: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    provider_slot: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
