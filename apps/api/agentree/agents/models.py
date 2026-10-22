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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
        CheckConstraint(
            "status IN ('open', 'needs_human', 'human_active', 'resolved')", name="status"
        ),
        CheckConstraint(
            "handoff_reason IS NULL OR handoff_reason IN ('visitor', 'agent')",
            name="handoff_reason",
        ),
        Index("ix_conversations_business_id_status", "business_id", "status"),
        CheckConstraint(
            "active_agent IN ('sales', 'customer_service', 'technical_support', 'data_analyst', "
            "'executive')",
            name="active_agent",
        ),
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
    # Customer memory (Task 16): when the worker last derived memory items from this conversation.
    memory_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Anonymous visitor that owns a public/widget conversation (NULL for the console).
    guest_session_id: Mapped[UUID | None] = mapped_column(index=True)
    # Exempts the conversation from retention deletion. Owner-only, audited API: not built yet.
    legal_hold: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Human inbox (Task 12). open: the AI answers; needs_human: the visitor or the agent asked
    # for a person (AI paused); human_active: a member is replying (AI paused); resolved.
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    assignee_user_id: Mapped[UUID | None] = mapped_column()  # no FK: kept if the member leaves
    handoff_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_reason: Mapped[str | None] = mapped_column(String(16))  # visitor | agent


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
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | human (a team member)
    agent: Mapped[str | None] = mapped_column(String(32))
    author_user_id: Mapped[UUID | None] = mapped_column()  # set only for role = human
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    provider_slot: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


AGENT_ROLES_SQL = "'sales', 'customer_service', 'technical_support', 'data_analyst', 'executive'"


class AgentConfig(Base):
    """A business's settings for one agent role (Task 14). No row: the role's defaults apply."""

    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("business_id", "role"),
        CheckConstraint(f"role IN ({AGENT_ROLES_SQL})", name="role"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean)
    display_name: Mapped[str] = mapped_column(String(40), server_default="")
    public: Mapped[bool] = mapped_column(Boolean)  # visitors may reach it (public roles only)
    tools: Mapped[list[str]] = mapped_column(ARRAY(String(64)))  # within the role's allowlist
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentHandoff(Base):
    """One agent handing a conversation to another (Task 14).

    `note` is the handing-off agent's summary for its teammate: model output derived from the
    conversation, so it is untrusted, shown to the next agent as delimited data only, and deleted
    with the conversation by the retention job (same 30-day rule as messages).
    """

    __tablename__ = "agent_handoffs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "conversation_id"],
            ["conversations.business_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"from_agent IN ({AGENT_ROLES_SQL})", name="from_agent"),
        CheckConstraint(f"to_agent IN ({AGENT_ROLES_SQL})", name="to_agent"),
        CheckConstraint("from_agent <> to_agent", name="distinct_agents"),
        Index("ix_agent_handoffs_business_id_conversation_id", "business_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column()
    conversation_id: Mapped[UUID] = mapped_column()
    from_agent: Mapped[str] = mapped_column(String(32))
    to_agent: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


HOURS_MODES = ("always", "business_hours", "outside_business_hours")
_HOURS_MODES_SQL = ", ".join(f"'{m}'" for m in HOURS_MODES)


class BusinessHours(Base):
    """When the business is open (Task 20b): one time zone and one range per weekday.

    `days` has 7 entries, Monday first: null (closed) or {"start": "HH:MM", "end": "HH:MM"}.
    """

    __tablename__ = "business_hours"

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64))
    days: Mapped[list[dict[str, str] | None]] = mapped_column(JSONB)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentAvailability(Base):
    """When one agent answers visitors (Task 20b, PO 2026-10-22): always, during business hours
    (e.g. the team covers the rest) or outside them (it covers the off hours), and an optional
    pause (e.g. a holiday). Otherwise visitors get a fixed message, never an AI reply."""

    __tablename__ = "agent_availability"
    __table_args__ = (
        UniqueConstraint("business_id", "role"),
        CheckConstraint(f"role IN ({AGENT_ROLES_SQL})", name="role"),
        CheckConstraint(f"mode IN ({_HOURS_MODES_SQL})", name="mode"),
        CheckConstraint(
            "paused_until IS NULL OR paused_from IS NULL OR paused_from < paused_until",
            name="pause_window",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32), server_default="always")
    away_message: Mapped[str] = mapped_column(String(500), server_default="")
    paused_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_message: Mapped[str] = mapped_column(String(500), server_default="")
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
