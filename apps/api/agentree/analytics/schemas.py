from datetime import date

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


class SummaryOut(BaseModel):
    start: date
    end: date
    totals: list[MetricOut]
    rates: list[RateOut]
    days: list[DayOut]
    missing_days: list[date]  # not computed yet: unknown, not zero
