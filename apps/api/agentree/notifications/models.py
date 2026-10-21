"""Web Push subscriptions: one per browser/device that opted in. RLS: tenant-scoped.

The endpoint is a capability URL issued by the browser's push service: never log it.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("business_id", "endpoint"),
        Index("ix_push_subscriptions_business_id_user_id", "business_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(1024))
    p256dh: Mapped[str] = mapped_column(String(128))
    auth: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
