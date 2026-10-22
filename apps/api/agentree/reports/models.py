"""Email reports (Task 20c). RLS: tenant-scoped on business_id."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base

FREQUENCIES = ("off", "daily", "weekly")
_FREQUENCIES_SQL = ", ".join(f"'{f}'" for f in FREQUENCIES)


class ReportSettings(Base):
    """How often Owners and Admins get the business's report by email (no row: off)."""

    __tablename__ = "report_settings"
    __table_args__ = (
        CheckConstraint(f"frequency IN ({_FREQUENCIES_SQL})", name="frequency"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
    )

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    frequency: Mapped[str] = mapped_column(String(8), server_default="off")
    weekday: Mapped[int] = mapped_column(Integer, server_default="0")  # 0 Monday (weekly)
    # The Executive Assistant adds short notes (numbers checked) when it is turned on.
    include_notes: Mapped[bool] = mapped_column(Boolean, server_default=false())
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
