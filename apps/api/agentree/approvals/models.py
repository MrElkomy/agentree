"""Approvals (Task 19). RLS: both tables are tenant-scoped on business_id.

An approval request is one sensitive agent action waiting for a person (Owner or Admin), bound
to the exact parameters that were approved (`approved_hash`). A rule is a standing "always
allow" for one agent and one action in one business (PO decision 2026-10-22: approve once or
always, so owners are not asked again and again), revocable at any time.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentree.core.models import Base

STATUSES = ("pending", "approved", "rejected", "expired", "executing", "executed", "failed",
            "canceled")  # fmt: skip
DECISIONS = ("once", "always", "rule", "reject")
_STATUS_SQL = ", ".join(f"'{s}'" for s in STATUSES)
_DECISION_SQL = ", ".join(f"'{d}'" for d in DECISIONS)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_approval_requests_business_id_idempotency_key",
        ),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="status"),
        CheckConstraint(f"decision IS NULL OR decision IN ({_DECISION_SQL})", name="decision"),
        CheckConstraint("char_length(params_hash) = 64", name="params_hash"),
        Index("ix_approval_requests_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    # The action's parameters (may hold a lead's name and a drafted message: never logged).
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    params_hash: Mapped[str] = mapped_column(String(64))
    approved_hash: Mapped[str | None] = mapped_column(String(64))  # what the person approved
    summary: Mapped[str] = mapped_column(String(200))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[UUID | None] = mapped_column()
    # A request the backend's own checks flagged (e.g. a number not found in the knowledge):
    # it always waits for a person, even under an "always allow" rule.
    flag: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str | None] = mapped_column(String(8))
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rule_id: Mapped[UUID | None] = mapped_column()
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(64))


class ApprovalRule(Base):
    """ "Always allow": this agent may run this action without asking (until revoked)."""

    __tablename__ = "approval_rules"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "agent", "action", name="uq_approval_rules_business_id_agent_action"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    business_id: Mapped[UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    # Who allowed it; replies to messages sent under the rule go to this person.
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
