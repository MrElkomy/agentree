"""Business hours and when each agent answers visitors (Task 20b, PO decision 2026-10-22).

A business sets its hours once (a time zone and one range per weekday). Each agent then answers
visitors **always**, only **during business hours** (the team takes the rest) or only **outside
business hours** (it covers the off time), and can be **paused** for a period such as a holiday.
When an agent is not available, a visitor gets the agent's fixed message instead of an AI
reply: no provider call and no AI cost. The test chat is not affected (the team is testing).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.agents.models import HOURS_MODES, AgentAvailability, BusinessHours
from agentree.agents.registry import DEFINITIONS, AgentRole, Audience
from agentree.audit.service import AuditAction, record
from agentree.core.email_layout import clean_text
from agentree.core.ids import uuid7
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

MAX_MESSAGE = 500
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_AWAY = ("Thanks for your message! We're not available right now. Leave your question "
                "here and our team will get back to you as soon as we're back.")  # fmt: skip
DEFAULT_PAUSE = ("Thanks for your message! We're away for a short break. Leave your question "
                 "here and our team will get back to you when we're back.")  # fmt: skip


class InvalidHoursError(ValueError):
    """`str(exc)` names the field: timezone, days, mode, message, pause."""


class HoursNotSetError(Exception):
    """A business-hours mode needs the business's hours first."""


@dataclass(frozen=True)
class DayRange:
    start: time
    end: time


@dataclass(frozen=True)
class HoursInfo:
    timezone: str
    days: tuple[DayRange | None, ...]  # Monday first; None: closed
    updated_at: datetime | None


@dataclass(frozen=True)
class Availability:
    role: AgentRole
    mode: str  # always | business_hours | outside_business_hours
    away_message: str
    paused_from: datetime | None
    paused_until: datetime | None
    pause_message: str
    updated_at: datetime | None


def _default(role: AgentRole) -> Availability:
    return Availability(role, "always", "", None, None, "", None)


# --- validation ---------------------------------------------------------------------------------


def validate_timezone(value: str) -> str:
    name = value.strip()
    if name not in available_timezones():
        raise InvalidHoursError("timezone")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidHoursError("timezone") from None
    return name


def _time(value: Any) -> time:
    try:
        parsed = time.fromisoformat(str(value))
    except ValueError:
        raise InvalidHoursError("days") from None
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise InvalidHoursError("days")
    return parsed


def validate_days(days: list[Any]) -> tuple[DayRange | None, ...]:
    """7 entries, Monday first: None (closed) or {"start", "end"} with start before end."""
    if len(days) != len(DAYS):
        raise InvalidHoursError("days")
    out: list[DayRange | None] = []
    for day in days:
        if day is None:
            out.append(None)
            continue
        if not isinstance(day, dict):
            raise InvalidHoursError("days")
        r = DayRange(_time(day.get("start")), _time(day.get("end")))
        if r.start >= r.end:  # overnight ranges are not supported yet
            raise InvalidHoursError("days")
        out.append(r)
    return tuple(out)


def validate_message(value: str) -> str:
    """A fixed message visitors see: plain text, one paragraph, at most 500 characters."""
    text = clean_text(value.replace("<<", "").replace(">>", ""))
    if len(text) > MAX_MESSAGE:
        raise InvalidHoursError("message")
    return text


# --- availability (pure) ------------------------------------------------------------------------


def is_open(hours: HoursInfo, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(hours.timezone))
    day = hours.days[local.weekday()]
    return day is not None and day.start <= local.time().replace(tzinfo=None) < day.end


def away_message(a: Availability, hours: HoursInfo | None, now: datetime) -> str | None:
    """None when the agent answers now; else the fixed message visitors get."""
    if a.paused_from is not None and a.paused_until is not None:
        if a.paused_from <= now < a.paused_until:
            return a.pause_message or DEFAULT_PAUSE
    if a.mode == "always" or hours is None:  # no hours set: a schedule cannot apply
        return None
    open_now = is_open(hours, now)
    if (a.mode == "business_hours") == open_now:
        return None
    return a.away_message or DEFAULT_AWAY


# --- storage ------------------------------------------------------------------------------------


def _hours_info(row: BusinessHours) -> HoursInfo:
    days = tuple(
        DayRange(time.fromisoformat(d["start"]), time.fromisoformat(d["end"])) if d else None
        for d in row.days
    )  # fmt: skip
    return HoursInfo(row.timezone, days, row.updated_at)


def _availability(row: AgentAvailability) -> Availability:
    return Availability(AgentRole(row.role), row.mode, row.away_message, row.paused_from,
                        row.paused_until, row.pause_message, row.updated_at)  # fmt: skip


async def get_hours(factory: Factory, ctx: TenantContext) -> HoursInfo | None:
    async with tenant_session(factory, ctx) as session:
        row = await session.get(BusinessHours, ctx.business_id)
        return _hours_info(row) if row is not None else None


async def save_hours(
    factory: Factory, ctx: TenantContext, *, timezone: str, days: list[Any], actor_id: UUID
) -> HoursInfo:
    tz = validate_timezone(timezone)
    ranges = validate_days(days)
    stored = [{"start": r.start.strftime("%H:%M"), "end": r.end.strftime("%H:%M")} if r else None
              for r in ranges]  # fmt: skip
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        row = await session.get(BusinessHours, ctx.business_id, with_for_update=True)
        if row is None:
            row = BusinessHours(business_id=ctx.business_id)
            session.add(row)
        row.timezone, row.days, row.updated_by_user_id, row.updated_at = tz, stored, actor_id, now
        await record(session, ctx, action=AuditAction.BUSINESS_HOURS_UPDATED,
                     actor_user_id=actor_id, target_type="business", target_id=ctx.business_id,
                     details={"timezone": tz})  # fmt: skip
        await session.flush()
        return _hours_info(row)


async def availability(factory: Factory, ctx: TenantContext) -> dict[AgentRole, Availability]:
    """Every role's availability (defaults for roles never set)."""
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(AgentAvailability).where(AgentAvailability.business_id == ctx.business_id)
            )
        ).scalars().all()  # fmt: skip
    found = {AgentRole(r.role): _availability(r) for r in rows}
    return {role: found.get(role, _default(role)) for role in DEFINITIONS}


async def save_availability(
    factory: Factory, ctx: TenantContext, role: AgentRole, *, mode: str, away_message: str,
    paused_from: datetime | None, paused_until: datetime | None, pause_message: str,
    actor_id: UUID,
) -> Availability:  # fmt: skip
    """Raises InvalidHoursError, or HoursNotSetError for an hours mode without hours."""
    if DEFINITIONS[role].audience is not Audience.PUBLIC:
        raise InvalidHoursError("role")  # internal agents only answer the team
    if mode not in HOURS_MODES:
        raise InvalidHoursError("mode")
    away, pause = validate_message(away_message), validate_message(pause_message)
    if (paused_from is None) != (paused_until is None):
        raise InvalidHoursError("pause")
    for value in (paused_from, paused_until):
        if value is not None and value.tzinfo is None:
            raise InvalidHoursError("pause")
    if paused_from is not None and paused_until is not None and paused_from >= paused_until:
        raise InvalidHoursError("pause")
    if mode != "always" and await get_hours(factory, ctx) is None:
        raise HoursNotSetError
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        row = (
            await session.execute(
                select(AgentAvailability).where(AgentAvailability.business_id == ctx.business_id,
                                                AgentAvailability.role == role)
                .with_for_update()
            )
        ).scalar_one_or_none()  # fmt: skip
        if row is None:
            row = AgentAvailability(id=uuid7(), business_id=ctx.business_id, role=role)
            session.add(row)
        row.mode, row.away_message, row.pause_message = mode, away, pause
        row.paused_from, row.paused_until = paused_from, paused_until
        row.updated_by_user_id, row.updated_at = actor_id, now
        await record(session, ctx, action=AuditAction.AGENT_AVAILABILITY_UPDATED,
                     actor_user_id=actor_id, target_type="agent", target_id=role,
                     details={"agent": role, "mode": mode,
                              "paused": paused_from is not None})  # fmt: skip
        await session.flush()
        return _availability(row)


async def away_message_now(
    factory: Factory, ctx: TenantContext, role: AgentRole, now: datetime | None = None
) -> str | None:
    """For a visitor's turn: the fixed message when this agent does not answer now."""
    a = (await availability(factory, ctx))[role]
    if a.mode == "always" and a.paused_from is None:
        return None
    return away_message(a, await get_hours(factory, ctx), now or datetime.now(UTC))
