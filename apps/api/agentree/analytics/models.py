"""Daily operational metrics (Task 18). RLS: tenant-scoped on business_id. Counts only."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        CheckConstraint("value >= 0", name="value"),
        Index("ix_daily_metrics_day", "day"),
    )

    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # UTC day
    metric: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


class MetricDay(Base):
    """UTC days the worker has computed (dates only, no tenant data)."""

    __tablename__ = "metric_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
