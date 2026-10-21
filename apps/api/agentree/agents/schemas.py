from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConsoleMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class SourceOut(BaseModel):
    id: UUID
    title: str


class ConsoleReplyOut(BaseModel):
    conversation_id: UUID
    reply: str
    sources: list[SourceOut]
    provider: str
    model: str
    slot: str
    fallback_used: bool


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


# --- human inbox ------------------------------------------------------------------------------


class InboxItemOut(BaseModel):
    id: UUID
    channel: str
    status: Literal["open", "needs_human", "human_active", "resolved"]
    assignee_user_id: UUID | None
    handoff_reason: str | None
    handoff_requested_at: datetime | None
    last_message_at: datetime
    created_at: datetime
    preview: str
    preview_role: str


class InboxPageOut(BaseModel):
    items: list[InboxItemOut]
    counts: dict[str, int]
    next_before: datetime | None  # pass as `before` for older conversations; None at the end


class InboxMessageOut(BaseModel):
    id: UUID
    role: str  # user (visitor) | assistant (AI) | human (team member)
    author_user_id: UUID | None
    content: str
    created_at: datetime


class InboxConversationOut(BaseModel):
    conversation: InboxItemOut
    messages: list[InboxMessageOut]


class InboxReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)


class InboxAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: UUID | None
