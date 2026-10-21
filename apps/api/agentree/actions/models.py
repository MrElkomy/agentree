"""Idempotency ledger of the Action Gateway. RLS: tenant-scoped on business_id."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class ActionExecution(Base):
    __tablename__ = "action_executions"
    __table_args__ = (UniqueConstraint("business_id", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(32))
    params_hash: Mapped[str] = mapped_column(String(64))  # sha256 of canonical JSON params
    result_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
