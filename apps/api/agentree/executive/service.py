"""The Executive Assistant (Task 20): the owner's operational manager in the test chat.

It answers from the business's computed numbers (`agentree.analytics`, every number checked as
for the Data Analyst) and its current state: the AI team, the public page, recent leads, the
team and the requests waiting for approval. It can only **propose** a small set of changes, as
`<<ACTION {...}>>` lines. Model output is untrusted: each proposal is validated here against
this business's real agents, leads and members, then becomes an approval request (Task 19); a
person approves it once or always allows it. Nothing runs without that, and nothing reaches
outside Agentree.

The agents module receives this as a `RoleExtension` (it must not import leads or public).
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from agentree.actions import service as gateway
from agentree.actions.service import Action
from agentree.agents import configs as agent_configs
from agentree.agents.registry import DEFINITIONS, AgentRole
from agentree.agents.service import RoleExtension, RoleState
from agentree.analytics import service as analytics
from agentree.approvals import service as approvals
from agentree.core.config import Environment
from agentree.core.email_layout import clean_text
from agentree.core.ids import uuid7
from agentree.leads import follow_ups
from agentree.leads import service as leads
from agentree.public import service as public
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext

logger = logging.getLogger(__name__)
Factory = approvals.Factory

AGENT = AgentRole.EXECUTIVE
ACTIONS = frozenset({Action.SET_AGENT_ENABLED, Action.UPDATE_PUBLIC_PROFILE,
                     Action.UPDATE_LEAD_STATUS, Action.ASSIGN_LEAD})  # fmt: skip
RECENT_LEADS = 15
MAX_BIO = 500
ASSIGN_DUE = timedelta(days=1)
_LABEL = re.compile(r"^L-([0-9a-f]{6})$")

INSTRUCTIONS = """Changes you may propose (an owner or admin approves each one). After your \
answer, add one line per change, exactly in this form:
<<ACTION {"action": "set_agent_enabled", "agent": "customer_service", "enabled": false}>>
<<ACTION {"action": "update_public_profile", "enabled": true, "bio": "New description"}>>
<<ACTION {"action": "update_lead_status", "lead": "L-1a2b3c", "status": "contacted"}>>
<<ACTION {"action": "assign_lead", "lead": "L-1a2b3c", "member": "person@example.com"}>>
- agent: one of the roles listed under "AI team" (not executive). update_public_profile: \
"enabled" and/or "bio" (at most 500 characters). status: new, contacted, qualified, won or \
lost. lead: a label from "Recent leads". member: an email from "Team".
- Propose a change only when the person asks for it or agrees to your suggestion, at most 3 \
per reply."""


class InvalidProposalError(ValueError):
    """`str(exc)` says, in plain words, why a proposal could not become a request."""


def _label(lead_id: UUID) -> str:
    return f"L-{lead_id.hex[-6:]}"


def _flat(value: object, limit: int) -> str:
    return clean_text(str(value or "").replace("<<", "").replace(">>", ""))[:limit]


# --- context -----------------------------------------------------------------------------------


async def context(factory: Factory, ctx: TenantContext) -> RoleState:
    computed = await analytics.analyst_numbers(factory, ctx)
    roster = await agent_configs.roster(factory, ctx)
    profile = await public.get_profile(factory, ctx)
    recent = await leads.list_leads(factory, ctx, limit=RECENT_LEADS)
    members = await tenancy.list_members(factory, ctx)
    pending = await approvals.list_requests(factory, ctx, pending=True, limit=100)
    lines = ["AI team:"]
    for c in roster.all():
        if not c.definition.available or c.role == AGENT:
            continue
        shown = f', shown as "{_flat(c.display_name, 40)}"' if c.display_name else ""
        where = (", open to visitors" if c.public else ", team only") if c.enabled else ""
        lines.append(f"- {c.role} ({c.definition.title}{shown}): {'on' if c.enabled else 'off'}"
                     f"{where}")  # fmt: skip
    lines.append(f"Public page: {'on' if profile.enabled else 'off'}. Description: "
                 f'"{_flat(profile.bio, 300)}"')  # fmt: skip
    lines.append("Recent leads (newest first):" if recent else "Recent leads: none yet.")
    for lead in recent:
        due = f", follow-up due {lead.next_follow_up_at:%Y-%m-%d}" if lead.next_follow_up_at else ""
        need = f", needs: {_flat(lead.need, 80)}" if lead.need else ""
        lines.append(f"- {_label(lead.id)}: {_flat(lead.name, 60) or '(no name)'}, "
                     f"{lead.status}, received {lead.created_at:%Y-%m-%d}{due}{need}")  # fmt: skip
    lines.append("Team:")
    lines += [f"- {m.email} ({m.role})" for m in members]
    lines.append(f"Requests waiting for approval: {len(pending)}")
    state = "\n".join(lines)
    return RoleState(computed=computed, state=f"{state}\n\n{INSTRUCTIONS}", checked=state)


# --- proposals -> approval requests ------------------------------------------------------------


async def _lead_by_label(factory: Factory, ctx: TenantContext, label: object) -> leads.LeadInfo:
    match = _LABEL.match(str(label or ""))
    if match is None:
        raise InvalidProposalError("unknown lead")
    found = [x for x in await leads.list_leads(factory, ctx, limit=50)
             if x.id.hex.endswith(match.group(1))]  # fmt: skip
    if len(found) != 1:
        raise InvalidProposalError("unknown lead")
    return found[0]


async def validate(
    factory: Factory, ctx: TenantContext, raw: dict[str, Any]
) -> tuple[Action, dict[str, Any], str]:
    """Untrusted proposal -> (action, parameters, summary for people). Raises
    InvalidProposalError."""
    try:
        action = Action(str(raw.get("action")))
    except ValueError:
        raise InvalidProposalError("unknown change") from None
    if action not in ACTIONS:
        raise InvalidProposalError("unknown change")
    if action is Action.SET_AGENT_ENABLED:
        role = next((r for r in DEFINITIONS if r == raw.get("agent")), None)
        enabled = raw.get("enabled")
        if role is None or role == AGENT or not DEFINITIONS[role].available:
            raise InvalidProposalError("unknown agent")
        if not isinstance(enabled, bool):
            raise InvalidProposalError("say whether to turn it on or off")
        title = DEFINITIONS[role].title
        return action, {"agent": str(role), "enabled": enabled}, (
            f"Turn {'on' if enabled else 'off'} the {title}")  # fmt: skip
    if action is Action.UPDATE_PUBLIC_PROFILE:
        params: dict[str, Any] = {}
        if isinstance(raw.get("enabled"), bool):
            params["enabled"] = raw["enabled"]
        if isinstance(raw.get("bio"), str):
            bio = _flat(raw["bio"], MAX_BIO + 1)
            if len(bio) > MAX_BIO:
                raise InvalidProposalError("the description is too long")
            params["bio"] = bio
        if not params:
            raise InvalidProposalError("nothing to change on the public page")
        parts = []
        if "enabled" in params:
            parts.append(f"turn the public page {'on' if params['enabled'] else 'off'}")
        if "bio" in params:
            parts.append("change its description")
        return action, params, " and ".join(parts).capitalize()
    lead = await _lead_by_label(factory, ctx, raw.get("lead"))
    who = _flat(lead.name, 60) or "a lead"
    if action is Action.UPDATE_LEAD_STATUS:
        try:
            status = leads.LeadStatus(str(raw.get("status")))
        except ValueError:
            raise InvalidProposalError("unknown status") from None
        return action, {"lead_id": str(lead.id), "status": str(status)}, (
            f"Move lead {who} to {status}")  # fmt: skip
    members = await tenancy.list_members(factory, ctx)
    email = str(raw.get("member") or "").strip().lower()
    member = next((m for m in members if m.email.lower() == email), None)
    if member is None:
        raise InvalidProposalError("unknown team member")
    return action, {"lead_id": str(lead.id), "user_id": str(member.user_id)}, (
        f"Assign lead {who} to {member.email}")  # fmt: skip


def extension(factory: Factory, deps: approvals.Deps) -> RoleExtension:
    async def act(ctx: TenantContext, conversation_id: UUID,
                  proposals: list[dict[str, Any]]) -> list[str]:  # fmt: skip
        tools = await agent_configs.agent_tools(factory, ctx, AGENT)
        lines: list[str] = []
        for raw in proposals:
            try:
                action, params, summary = await validate(factory, ctx, raw)
                info, _ = await approvals.request(
                    factory, ctx, deps, agent=AGENT, action=action, params=params,
                    summary=summary, idempotency_key=f"executive:{uuid7()}", granted=tools,
                )  # fmt: skip
            except InvalidProposalError as exc:
                lines.append(f"I couldn't prepare that change: {exc}.")
                continue
            except gateway.ActionDeniedError:
                lines.append("I'm not allowed to make that change in this business.")
                continue
            if info.status == "approved":  # always allowed: runs now
                result = await approvals.execute(factory, ctx, deps, info.id)
                lines.append(f"Done (always allowed): {summary}." if result == "executed"
                             else f"Couldn't do it: {summary}.")  # fmt: skip
            else:
                lines.append(f"Waiting for approval: {summary}. An owner or admin can approve "
                             "it on the Approvals page.")  # fmt: skip
        logger.info("executive proposals", extra={"conversation_id": str(conversation_id),
                                                  "count": len(proposals)})  # fmt: skip
        return lines

    async def role_context(ctx: TenantContext) -> RoleState:
        return await context(factory, ctx)

    return RoleExtension(context=role_context, act=act)


# --- executors (run after approval) ------------------------------------------------------------


def _actor(job: approvals.Execution) -> UUID:
    if job.authorized_by is None:  # approvals.execute already refuses this
        raise approvals.ExecutionCanceledError("approver_not_allowed")
    return job.authorized_by


async def _set_agent_enabled(factory: Factory, ctx: TenantContext, deps: approvals.Deps,
                             job: approvals.Execution) -> UUID | None:  # fmt: skip
    role = AgentRole(str(job.params["agent"]))
    if role == AGENT:
        raise approvals.ExecutionCanceledError("not_allowed")
    cfg = next(c for c in (await agent_configs.roster(factory, ctx)).all() if c.role == role)
    enabled = bool(job.params["enabled"])
    if cfg.enabled == enabled:
        return None  # already as asked
    try:
        await agent_configs.update_config(
            factory, ctx, role, enabled=enabled, display_name=cfg.display_name, public=cfg.public,
            tools=sorted(cfg.tools), actor_id=_actor(job),
        )  # fmt: skip
    except agent_configs.AgentNotAvailableError:
        raise approvals.ExecutionCanceledError("agent_not_available") from None
    return None


async def _update_public_profile(factory: Factory, ctx: TenantContext, deps: approvals.Deps,
                                 job: approvals.Execution) -> UUID | None:  # fmt: skip
    p = await public.get_profile(factory, ctx)
    await public.save_profile(
        factory, ctx, enabled=bool(job.params.get("enabled", p.enabled)),
        display_name=p.display_name, bio=str(job.params.get("bio", p.bio)), links=p.links,
        widget_origins=p.widget_origins, daily_reply_budget=p.daily_reply_budget,
        customer_memory=p.customer_memory,
        allow_localhost=deps.settings.environment in (Environment.DEV, Environment.TEST),
    )  # fmt: skip
    return None


async def _update_lead_status(factory: Factory, ctx: TenantContext, deps: approvals.Deps,
                              job: approvals.Execution) -> UUID | None:  # fmt: skip
    lead_id = UUID(str(job.params["lead_id"]))
    try:
        await leads.update_lead(factory, ctx, lead_id, actor_id=_actor(job),
                                status=leads.LeadStatus(str(job.params["status"])))  # fmt: skip
    except leads.NotFoundError:
        raise approvals.ExecutionCanceledError("lead_deleted") from None
    return lead_id


async def _assign_lead(factory: Factory, ctx: TenantContext, deps: approvals.Deps,
                       job: approvals.Execution) -> UUID | None:  # fmt: skip
    lead_id, user_id = UUID(str(job.params["lead_id"])), UUID(str(job.params["user_id"]))
    try:
        lead = await leads.get_lead(factory, ctx, lead_id)
        tasks = [t for t in await follow_ups.list_tasks(factory, ctx, lead_id)
                 if t.status == "open"]  # fmt: skip
        for t in tasks:
            await follow_ups.update_task(factory, ctx, t.id, actor_id=_actor(job), reassign=True,
                                         assignee_user_id=user_id)  # fmt: skip
        if not tasks:  # nothing open: a reminder for the assignee
            await follow_ups.create_task(
                factory, ctx, lead_id, actor_id=_actor(job),
                title=f"Follow up with {lead.name or 'the lead'}",
                due_at=datetime.now(UTC) + ASSIGN_DUE, assignee_user_id=user_id,
            )  # fmt: skip
    except (leads.NotFoundError, follow_ups.NotFoundError):
        raise approvals.ExecutionCanceledError("lead_deleted") from None
    except follow_ups.InvalidTaskError:
        raise approvals.ExecutionCanceledError("member_left") from None
    return lead_id


approvals.register(Action.SET_AGENT_ENABLED, _set_agent_enabled)
approvals.register(Action.UPDATE_PUBLIC_PROFILE, _update_public_profile)
approvals.register(Action.UPDATE_LEAD_STATUS, _update_lead_status)
approvals.register(Action.ASSIGN_LEAD, _assign_lead)
