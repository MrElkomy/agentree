from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agentree.leads.service import MAX_NOTES, LeadStatus


class LeadOut(BaseModel):
    id: UUID
    conversation_id: UUID | None  # None once the conversation was deleted (30-day retention)
    channel: str
    source_agent: str
    name: str
    email: str | None
    phone: str | None
    need: str
    consent_at: datetime
    status: LeadStatus
    notes: str
    created_at: datetime
    updated_at: datetime
    next_follow_up_at: datetime | None = None


class LeadPageOut(BaseModel):
    leads: list[LeadOut]
    next_before: UUID | None


class LeadMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime


class LeadDetailOut(LeadOut):
    messages: list[LeadMessageOut]  # empty once the conversation was deleted


class LeadUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES)


class FollowUpOut(BaseModel):
    id: UUID
    lead_id: UUID
    title: str
    due_at: datetime
    assignee_user_id: UUID | None
    status: str  # open | done | canceled
    kind: str  # first_contact | manual
    created_by_agent: str | None
    created_by_user_id: UUID | None
    completed_at: datetime | None
    created_at: datetime


class FollowUpCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime
    assignee_user_id: UUID | None = None


class FollowUpUpdateIn(BaseModel):
    """Only the fields sent are changed; send `assignee_user_id: null` to unassign."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "done", "canceled"] | None = None
    due_at: AwareDatetime | None = None
    assignee_user_id: UUID | None = None
