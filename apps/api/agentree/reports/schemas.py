from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportSettingsIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: Literal["off", "daily", "weekly"]
    weekday: int = Field(default=0, ge=0, le=6)  # 0 Monday (weekly reports)
    include_notes: bool = False  # Executive Assistant notes (needs it turned on)
    last_sent_at: datetime | None = None  # read-only


class TestSendOut(BaseModel):
    sent: int
