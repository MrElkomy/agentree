"""Business knowledge base entries. RLS: tenant-scoped on business_id."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
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
    # The uploaded file this draft was extracted from (Task 17); kept when the file is deleted.
    source_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="SET NULL"), index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeFile(Base):
    """An uploaded knowledge file (Task 17). The bytes live in `knowledge_file_data`."""

    __tablename__ = "knowledge_files"
    __table_args__ = (
        UniqueConstraint("business_id", "id"),
        CheckConstraint("kind IN ('pdf', 'docx', 'txt', 'md', 'csv', 'xlsx')", name="kind"),
        CheckConstraint("status IN ('processing', 'ready', 'stored', 'failed')", name="status"),
        CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="size_bytes"),
        CheckConstraint("char_length(sha256) = 64", name="sha256"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))  # sanitized display name
    kind: Mapped[str] = mapped_column(String(8))  # detected from the content
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(32))  # stable code when failed
    entry_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # CSV/XLSX (Task 18b): {"columns": [{"name", "type"}], "rows": n}; never cell values.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeFileData(Base):
    """The stored bytes, apart from the metadata so listings never load them."""

    __tablename__ = "knowledge_file_data"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "file_id"],
            ["knowledge_files.business_id", "knowledge_files.id"],
            ondelete="CASCADE",
        ),
    )

    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
