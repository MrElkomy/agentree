from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ApprovalOut(BaseModel):
    id: UUID
    action: str
    agent: str
    summary: str
    # The action's parameters as the agent proposed them (or as a person edited them).
    params: dict[str, Any]
    target_type: str | None
    target_id: UUID | None
    flag: str | None  # the backend's checks want a person to look (never auto-approved)
    status: str  # pending | approved | rejected | expired | executing | executed | failed |
    #              canceled | unknown (stopped mid-way; never retried)
    decision: str | None  # once | always | rule | reject
    decided_by_user_id: UUID | None
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    finished_at: datetime | None
    error: str | None
    editable: bool
    allow_always: bool


class DecisionIn(BaseModel):
    decision: Literal["once", "always", "reject"]
    # Approve only: the person's version of editable fields (e.g. subject and body).
    edits: dict[str, str] | None = Field(default=None, max_length=8)


class RuleOut(BaseModel):
    id: UUID
    agent: str
    action: str
    created_by_user_id: UUID | None
    created_at: datetime
