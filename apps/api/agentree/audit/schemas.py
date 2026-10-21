from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditActorOut(BaseModel):
    user_id: UUID
    email: str | None  # None when the account no longer exists


class AuditEventOut(BaseModel):
    id: UUID
    action: str
    actor: AuditActorOut | None  # None for system actions
    target_type: str
    target_id: str | None
    target_email: str | None  # for user targets, when the account still exists
    details: dict[str, Any]
    created_at: datetime


class AuditPageOut(BaseModel):
    events: list[AuditEventOut]
    next_before: UUID | None  # pass as `before` for the next (older) page; None at the end
