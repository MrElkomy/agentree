from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomerOut(BaseModel):
    id: UUID
    verified: bool
    email: str | None  # verified customers only
    item_count: int
    created_at: datetime
    last_seen_at: datetime


class MemoryItemOut(BaseModel):
    id: UUID
    category: str
    value: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime  # deleted then at the latest (retention window)


class CustomerDetailOut(BaseModel):
    customer: CustomerOut
    memory: list[MemoryItemOut]


class MemoryItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=200)
