from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
