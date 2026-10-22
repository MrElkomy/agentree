"""Per-business agent configuration and the roster used to pick and route agents (Task 14).

Which agents exist, who may reach them and which tools they hold is decided here, from the
role definitions (`registry.py`) and the business's saved settings: never from model output,
display names or client input. A display name is cosmetic: it never affects identity,
permissions or routing.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.actions.service import OPT_IN, Action
from agentree.agents.models import AgentConfig
from agentree.agents.registry import DEFINITIONS, AgentDefinition, AgentRole, Audience
from agentree.audit.service import AuditAction, record
from agentree.core.ids import uuid7
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

MAX_DISPLAY_NAME = 40
# Letters and digits in any script, spaces and a little punctuation: no markup, no newlines.
_DISPLAY_NAME = re.compile(r"[\w .,'&()\-]+")


class InvalidAgentConfigError(ValueError):
    """`str(exc)` names the problem: display_name, public or tools."""


class AgentNotAvailableError(Exception):
    """The role is not built yet and cannot be enabled."""


@dataclass(frozen=True)
class AgentConfigInfo:
    definition: AgentDefinition
    enabled: bool
    display_name: str
    public: bool
    tools: frozenset[Action]
    version: int  # 0: never saved (the role's defaults)
    updated_at: datetime | None

    @property
    def role(self) -> AgentRole:
        return self.definition.role

    @property
    def name(self) -> str:
        return self.display_name or self.definition.title

    @property
    def effective_tools(self) -> frozenset[Action]:
        """What the Action Gateway lets this agent do now: role allowlist ∩ business choice."""
        if not self.enabled:
            return frozenset()
        return self.definition.tools & self.tools


def _default(d: AgentDefinition) -> AgentConfigInfo:
    return AgentConfigInfo(
        definition=d, enabled=d.enabled_by_default and d.available, display_name="",
        public=d.audience is Audience.PUBLIC, tools=d.tools - OPT_IN, version=0,
        updated_at=None,
    )  # fmt: skip


def _from_row(d: AgentDefinition, row: AgentConfig) -> AgentConfigInfo:
    return AgentConfigInfo(
        definition=d,
        enabled=row.enabled and d.available,
        display_name=row.display_name,
        public=row.public and d.audience is Audience.PUBLIC,
        tools=frozenset(Action(t) for t in row.tools if t in d.tools),
        version=row.version,
        updated_at=row.updated_at,
    )


class Roster:
    """A business's agents as configured for one request."""

    def __init__(self, configs: Iterable[AgentConfigInfo]) -> None:
        self._by_role = {c.role: c for c in configs}

    def config(self, role: str) -> AgentConfigInfo | None:
        try:
            return self._by_role.get(AgentRole(role))
        except ValueError:
            return None

    def allowed(self, role: str, *, guest: bool) -> bool:
        """May this conversation be answered by `role`? Guests reach public agents only."""
        cfg = self.config(role)
        if cfg is None or not cfg.enabled or not cfg.definition.available:
            return False
        if guest:
            return cfg.definition.audience is Audience.PUBLIC and cfg.public
        return True

    def entry(self, requested: str | None, *, guest: bool) -> AgentConfigInfo | None:
        """The agent that answers first: the requested one if allowed, else the default."""
        if requested is not None:
            return self.config(requested) if self.allowed(requested, guest=guest) else None
        for role in DEFINITIONS:  # Sales first, then the other public roles
            if self.allowed(role, guest=guest):
                return self.config(role)
        return None

    def targets(self, current: AgentRole, *, guest: bool) -> list[AgentConfigInfo]:
        """Teammates `current` may hand the conversation to."""
        return [
            c for c in self._by_role.values()
            if c.role is not current and self.allowed(c.role, guest=guest)
        ]  # fmt: skip

    def all(self) -> list[AgentConfigInfo]:
        return [self._by_role[r] for r in DEFINITIONS]


async def _rows(session: AsyncSession, ctx: TenantContext) -> dict[str, AgentConfig]:
    rows = (
        await session.execute(select(AgentConfig).where(AgentConfig.business_id == ctx.business_id))
    ).scalars().all()  # fmt: skip
    return {r.role: r for r in rows}


async def roster(factory: Factory, ctx: TenantContext) -> Roster:
    async with tenant_session(factory, ctx) as session:
        rows = await _rows(session, ctx)
    return Roster(
        _from_row(d, rows[d.role]) if d.role in rows else _default(d) for d in DEFINITIONS.values()
    )


async def agent_tools(factory: Factory, ctx: TenantContext, role: AgentRole) -> frozenset[Action]:
    """The tools a role may use in this business right now (empty when disabled)."""
    cfg = (await roster(factory, ctx)).config(role)
    return cfg.effective_tools if cfg else frozenset()


def validate_display_name(value: str) -> str:
    if any(not ch.isprintable() for ch in value):  # newlines, tabs, control characters
        raise InvalidAgentConfigError("display_name")
    name = " ".join(value.split())
    if len(name) > MAX_DISPLAY_NAME or (name and not _DISPLAY_NAME.fullmatch(name)):
        raise InvalidAgentConfigError("display_name")
    return name


async def update_config(
    factory: Factory, ctx: TenantContext, role: AgentRole, *, enabled: bool, display_name: str,
    public: bool, tools: Iterable[str], actor_id: UUID,
) -> AgentConfigInfo:  # fmt: skip
    d = DEFINITIONS[role]
    if enabled and not d.available:
        raise AgentNotAvailableError
    if public and d.audience is not Audience.PUBLIC:
        raise InvalidAgentConfigError("public")
    try:
        chosen = frozenset(Action(t) for t in tools)
    except ValueError:
        raise InvalidAgentConfigError("tools") from None
    if not chosen <= d.tools:
        raise InvalidAgentConfigError("tools")
    name = validate_display_name(display_name)
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        row = (
            await session.execute(
                select(AgentConfig)
                .where(AgentConfig.business_id == ctx.business_id, AgentConfig.role == role)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = AgentConfig(id=uuid7(), business_id=ctx.business_id, role=role, version=0)
            session.add(row)
        row.enabled, row.display_name, row.public = enabled, name, public
        row.tools = sorted(chosen)
        row.version = (row.version or 0) + 1
        row.updated_by_user_id, row.updated_at = actor_id, now
        await session.flush()
        await record(
            session, ctx, action=AuditAction.AGENT_CONFIG_UPDATED, actor_user_id=actor_id,
            target_type="agent", target_id=role,
            details={"agent": role, "enabled": enabled, "public": public, "version": row.version},
        )  # fmt: skip
        return _from_row(d, row)
