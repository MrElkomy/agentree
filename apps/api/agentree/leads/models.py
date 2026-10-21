"""Leads captured from public conversations. RLS: tenant-scoped on business_id.

A lead outlives its conversation: the retention job deleting the conversation only clears
`conversation_id` (migration 0010). Contact details are personal data: never log them.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("business_id", "conversation_id"),
        # Same-business conversation; deleting it (retention) clears only conversation_id.
        ForeignKeyConstraint(
            ["business_id", "conversation_id"],
            ["conversations.business_id", "conversations.id"],
            ondelete="SET NULL (conversation_id)",
        ),
        Index("ix_leads_business_id_id", "business_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)  # uuid7: time-ordered
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    conversation_id: Mapped[UUID | None] = mapped_column()
    channel: Mapped[str] = mapped_column(String(16))  # public | widget
    source_agent: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100), server_default="")
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(32))
    need: Mapped[str] = mapped_column(Text, server_default="")
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    notes: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
