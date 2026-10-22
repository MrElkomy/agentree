from datetime import date, datetime

from pydantic import BaseModel


class MetricOut(BaseModel):
    name: str
    label: str
    value: int


class RateOut(BaseModel):
    name: str
    label: str
    value: float | None  # percent; null when there were no conversations


class DayOut(BaseModel):
    day: date
    values: dict[str, int]


class AgentOutcomeOut(BaseModel):
    role: str
    outcomes: dict[str, int]  # conversations, replies, resolved, to_team, handoffs_out


class RetentionOut(BaseModel):
    retention_days: int  # raw conversations are deleted after this many days
    last_run_at: datetime | None  # when the deletion job last ran (null: not yet)


class SummaryOut(BaseModel):
    start: date
    end: date
    totals: list[MetricOut]
    rates: list[RateOut]
    days: list[DayOut]
    missing_days: list[date]  # not computed yet: unknown, not zero
    agents: list[AgentOutcomeOut]  # Task 21: per-agent outcomes (public conversations)
    agent_outcome_labels: dict[str, str]
