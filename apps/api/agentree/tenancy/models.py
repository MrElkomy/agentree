"""Tenancy models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class Business(Base):
    """A tenant. RLS: a session sees only the business in its tenant context."""

    __tablename__ = "businesses"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
