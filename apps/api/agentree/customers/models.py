"""Customer identity and memory (Task 16). RLS: every table is tenant-scoped on business_id.

A customer profile is provisional (an anonymous visitor's guest session) until the visitor
proves an email address with a one-time code; then it is verified. Memory items are short,
structured facts derived from conversations, never message text, and never outlive the raw
conversation retention window (PO decision U-12).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base

CATEGORIES = ("interest", "owned", "issue", "preference", "constraint")
_CATEGORY_SQL = ", ".join(f"'{c}'" for c in CATEGORIES)


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (
        UniqueConstraint("business_id", "id"),
        UniqueConstraint("business_id", "email", name="uq_customer_profiles_business_id_email"),
        CheckConstraint("(email IS NULL) = (verified_at IS NULL)", name="verified_email"),
        Index("ix_customer_profiles_last_seen_at", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str | None] = mapped_column(String(254))  # lower-case; set once verified
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Retention: a profile with no activity for the retention window is deleted with its memory.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CustomerSession(Base):
    """Which customer profile a guest session (public page / widget visitor) belongs to."""

    __tablename__ = "customer_sessions"
    __table_args__ = (
        # guest_sessions is owned by `agentree.public`; only the FK lives here.
        ForeignKeyConstraint(
            ["business_id", "guest_session_id"],
            ["guest_sessions.business_id", "guest_sessions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["business_id", "customer_id"],
            ["customer_profiles.business_id", "customer_profiles.id"],
            ondelete="CASCADE",
        ),
        Index("ix_customer_sessions_customer_id", "customer_id"),
    )

    guest_session_id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerVerification(Base):
    """A one-time code emailed to the visitor. Only its SHA-256 is stored."""

    __tablename__ = "customer_verifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "guest_session_id"],
            ["guest_sessions.business_id", "guest_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("char_length(code_hash) = 64", name="code_hash"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_customer_verifications_guest_session_id", "guest_session_id"),
        Index("ix_customer_verifications_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    guest_session_id: Mapped[UUID]
    email: Mapped[str] = mapped_column(String(254))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryItem(Base):
    __tablename__ = "customer_memory_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "customer_id"],
            ["customer_profiles.business_id", "customer_profiles.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"category IN ({_CATEGORY_SQL})", name="category"),
        CheckConstraint("char_length(value) BETWEEN 1 AND 200", name="value"),
        # U-12: nothing derived from a conversation outlives the 30-day raw window.
        CheckConstraint("expires_at <= created_at + interval '30 days'", name="expires_at"),
        Index("ix_customer_memory_items_customer_id", "customer_id"),
        Index("ix_customer_memory_items_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID]
    category: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(200))
    # The conversation it came from (owned by `agentree.agents`); cleared when that is purged.
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
