"""Public AI page profile and anonymous guest sessions. RLS: tenant-scoped on business_id."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class PublicProfile(Base):
    """What the public page (`/{slug}`) and the website widget show. One row per business."""

    __tablename__ = "public_profiles"
    __table_args__ = (
        CheckConstraint("daily_reply_budget BETWEEN 1 AND 5000", name="daily_reply_budget"),
        CheckConstraint(
            "jsonb_typeof(links) = 'array' AND jsonb_array_length(links) <= 10",
            name="links_array",
        ),
        CheckConstraint(
            "jsonb_typeof(widget_origins) = 'array' AND jsonb_array_length(widget_origins) <= 10",
            name="widget_origins_array",
        ),
    )

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())
    display_name: Mapped[str | None] = mapped_column(String(80))
    bio: Mapped[str] = mapped_column(String(500), server_default="")
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    widget_origins: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    daily_reply_budget: Mapped[int] = mapped_column(Integer, server_default="200")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuestSession(Base):
    """An anonymous visitor of the public page or widget. Only the token's SHA-256 is stored."""

    __tablename__ = "guest_sessions"
    __table_args__ = (
        UniqueConstraint("business_id", "id"),
        CheckConstraint("char_length(token_hash) = 64", name="token_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
