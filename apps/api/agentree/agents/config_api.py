"""Agent configuration for business members (Task 14): read for all, change for Admins+.
Business hours and when each agent answers visitors (Task 20b) live here too."""

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status

from agentree.agents import configs, hours
from agentree.agents.registry import AgentRole
from agentree.agents.schemas import (
    AgentConfigIn,
    AgentConfigOut,
    AvailabilityIn,
    AvailabilityOut,
    BusinessHoursIO,
    DayHoursIO,
)
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/agents", tags=["agents"])
hours_router = APIRouter(prefix="/api/businesses/{business_id}", tags=["agents"])

DEFAULT_HOURS = BusinessHoursIO(
    timezone="UTC",
    days=[DayHoursIO(start="09:00", end="17:00")] * 5 + [None, None],
    configured=False,
)


def _out(c: configs.AgentConfigInfo, a: hours.Availability,
         business_hours: hours.HoursInfo | None) -> AgentConfigOut:  # fmt: skip
    d = c.definition
    a_out = asdict(a)
    a_out.pop("role")
    a_out.pop("updated_at")
    return AgentConfigOut(
        role=c.role, title=d.title, name=c.name, display_name=c.display_name,
        audience=d.audience, handles=d.handles, available=d.available, enabled=c.enabled,
        public=c.public, tools=sorted(c.tools), available_tools=sorted(d.tools),
        version=c.version, updated_at=c.updated_at, availability=AvailabilityOut(**a_out),
        answering_now=hours.away_message(a, business_hours, datetime.now(UTC)) is None,
    )  # fmt: skip


async def _all(request: Request, member: Member) -> list[AgentConfigOut]:
    factory = request.app.state.session_factory
    roster = await configs.roster(factory, member.tenant)
    avail = await hours.availability(factory, member.tenant)
    business_hours = await hours.get_hours(factory, member.tenant)
    return [_out(c, avail[c.role], business_hours) for c in roster.all()]


@router.get("")
async def list_agents(member: Member, request: Request) -> list[AgentConfigOut]:
    return await _all(request, member)


@router.put("/{role}/availability")
async def update_availability(
    role: AgentRole, body: AvailabilityIn, member: Member, request: Request
) -> AgentConfigOut:
    """When this agent answers visitors. 409 `business_hours_not_set` for an hours mode before
    the business saved its hours; 422 `invalid_<field>`."""
    member.require(Role.ADMIN)
    try:
        await hours.save_availability(
            request.app.state.session_factory, member.tenant, role, mode=body.mode,
            away_message=body.away_message, paused_from=body.paused_from,
            paused_until=body.paused_until, pause_message=body.pause_message,
            actor_id=member.user.id,
        )  # fmt: skip
    except hours.HoursNotSetError:
        raise HTTPException(status.HTTP_409_CONFLICT, "business_hours_not_set") from None
    except hours.InvalidHoursError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc}") from None
    return next(a for a in await _all(request, member) if a.role == role)


def _hours_out(h: hours.HoursInfo | None) -> BusinessHoursIO:
    if h is None:
        return DEFAULT_HOURS
    days = [DayHoursIO(start=d.start.strftime("%H:%M"), end=d.end.strftime("%H:%M")) if d
            else None for d in h.days]  # fmt: skip
    return BusinessHoursIO(timezone=h.timezone, days=days)


@hours_router.get("/business-hours")
async def get_business_hours(member: Member, request: Request) -> BusinessHoursIO:
    return _hours_out(await hours.get_hours(request.app.state.session_factory, member.tenant))


@hours_router.put("/business-hours")
async def put_business_hours(
    body: BusinessHoursIO, member: Member, request: Request
) -> BusinessHoursIO:
    """422 `invalid_timezone` or `invalid_days` (each open day needs start before end)."""
    member.require(Role.ADMIN)
    try:
        saved = await hours.save_hours(
            request.app.state.session_factory, member.tenant, timezone=body.timezone,
            days=[d.model_dump() if d else None for d in body.days], actor_id=member.user.id,
        )  # fmt: skip
    except hours.InvalidHoursError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc}") from None
    return _hours_out(saved)


@router.put("/{role}")
async def update_agent(
    role: AgentRole, body: AgentConfigIn, member: Member, request: Request
) -> AgentConfigOut:
    member.require(Role.ADMIN)
    try:
        saved = await configs.update_config(
            request.app.state.session_factory, member.tenant, role, enabled=body.enabled,
            display_name=body.display_name, public=body.public, tools=body.tools,
            actor_id=member.user.id,
        )  # fmt: skip
    except configs.AgentNotAvailableError:
        raise HTTPException(status.HTTP_409_CONFLICT, "agent_not_available") from None
    except configs.InvalidAgentConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc}") from None
    return next(a for a in await _all(request, member) if a.role == saved.role)
