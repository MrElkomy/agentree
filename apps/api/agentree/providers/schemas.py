from datetime import datetime

from pydantic import BaseModel, Field

from agentree.llm.base import ProviderName
from agentree.providers.service import Health, Slot


class CredentialIn(BaseModel):
    provider: ProviderName
    model: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=8, max_length=512)
    verify: bool = True  # make a minimal test call before saving


class CredentialOut(BaseModel):
    slot: Slot
    provider: ProviderName
    model: str
    key_hint: str  # last 4 characters; the key itself is never returned
    last_verified_at: datetime | None
    last_error_kind: str | None
    updated_at: datetime
    health: Health  # healthy | degraded | down (calls use the other key) | recovering
    last_failure_at: datetime | None
    breaker_open_until: datetime | None  # while down: when the next test call may run


class CheckOut(BaseModel):
    ok: bool
    error_kind: str | None = None
