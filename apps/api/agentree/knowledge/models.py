"""Business knowledge base entries. RLS: tenant-scoped on business_id."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Computed, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = (
        Index("ix_knowledge_entries_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | published
    # Agent roles that may use this entry; empty means every agent (Task 15 knowledge scoping).
    agent_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), server_default=text("'{}'"), default=list
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))",
            persisted=True,
        ),
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
