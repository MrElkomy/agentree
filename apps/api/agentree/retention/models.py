"""Retention run records (Task 21): one row per retention pass that ran, counts and times only.

Global (no tenant data). Written only through `agentree_record_retention_run`; the app role
can read but not change them.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class RetentionRun(Base):
    __tablename__ = "retention_runs"
    __table_args__ = (
        CheckConstraint("rows_deleted >= 0 AND batches >= 0", name="counts"),
        Index("ix_retention_runs_finished_at", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rows_deleted: Mapped[int] = mapped_column(Integer)
    batches: Mapped[int] = mapped_column(Integer)
