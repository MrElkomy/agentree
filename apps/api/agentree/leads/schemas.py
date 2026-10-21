from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
