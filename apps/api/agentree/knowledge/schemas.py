from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentree.knowledge.service import MAX_BODY_CHARS, Status


class EntryCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    # Agent roles that may use the entry; empty: every agent.
    agent_roles: list[str] = Field(default_factory=list, max_length=8)


class EntryUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_BODY_CHARS)
    agent_roles: list[str] | None = Field(default=None, max_length=8)


class EntryOut(BaseModel):
    id: UUID
    title: str
    body: str
    status: Status
    published_at: datetime | None
    updated_at: datetime
    agent_roles: list[str]
    source_file_id: UUID | None = None


class KnowledgeFileOut(BaseModel):
    id: UUID
    filename: str
    kind: str  # detected from the content: pdf, docx, txt, md, csv, xlsx
    size_bytes: int
    status: str  # processing | ready (drafts created) | stored (kept for data analysis) | failed
    error: str | None
    entry_count: int
    created_at: datetime
    processed_at: datetime | None
