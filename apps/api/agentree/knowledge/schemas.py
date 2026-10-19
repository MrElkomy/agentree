from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentree.knowledge.service import MAX_BODY_CHARS, Status


class EntryCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)


class EntryUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_BODY_CHARS)


class EntryOut(BaseModel):
    id: UUID
    title: str
    body: str
    status: Status
    published_at: datetime | None
    updated_at: datetime
