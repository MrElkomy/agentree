"""Approvals (Task 19): sensitive agent actions wait for an Owner or Admin.

Flow: an agent's sensitive action (`gateway.APPROVALS`) becomes a request bound to its exact
parameters. A person approves it **once**, approves it and **always allows** that agent the
action (a rule, revocable), or rejects it; a pending request expires after the action's TTL.
Requests the backend's own checks flagged (`flag`) always wait for a person, even under a rule.

Execution is exactly once: whoever runs it (the API right after the decision, or the worker as
a safety net) first moves the request from `approved` to `executing` in one conditional UPDATE,
so only one runner wins. The approved parameter hash must still match the stored parameters,
and the agent must still hold the tool. A runner that dies mid-way leaves the request
`executing`; after `STUCK_AFTER` it shows as `unknown` and is never retried (it may have taken
effect). Requests are deleted 30 days after they were made (they may hold a lead's details).
Parameters are never logged; the audit trail records action, agent and decision only.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.actions import service as gateway
from agentree.actions.service import Action
from agentree.agents import configs as agent_configs
from agentree.agents.registry import AgentRole, definition
from agentree.approvals.models import ApprovalRequest, ApprovalRule
from agentree.audit.service import AuditAction, record
from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailAction, EmailContent
from agentree.core.ids import uuid7
from agentree.core.webpush import PushMessage, PushSender
from agentree.notifications import service as notifications
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from agentree.tenancy.roles import Role, at_least

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

STUCK_AFTER = timedelta(minutes=10)
RETENTION = timedelta(days=30)
MAX_SUMMARY = 200
MAX_PAGE = 100
BATCH = 50


class NotFoundError(Exception):
    pass


class InvalidStateError(Exception):
    """`str(exc)`: not_pending, expired or always_not_allowed."""


class InvalidEditError(ValueError):
    """`str(exc)` names the field the person's edit got wrong."""


class ExecutionCanceledError(Exception):
    """The action is no longer needed (e.g. the lead was contacted meanwhile): `str(exc)` code."""


class ExecutionFailedError(Exception):
    """The action could not run (e.g. the email server refused it): `str(exc)` code."""


@dataclass(frozen=True)
class Deps:
    """What executors and notifications need (the API and the worker both provide it)."""

    settings: Settings
    mailer: EmailSender
    push: PushSender | None = None


@dataclass(frozen=True)
class Execution:
    approval_id: UUID
    agent: str
    action: Action
    params: dict[str, Any]
    authorized_by: UUID | None  # the approver, or the member who created the rule


Executor = Callable[[Factory, TenantContext, Deps, Execution], Awaitable[UUID | None]]
EditValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class _Handler:
    execute: Executor
    edit: EditValidator | None


_HANDLERS: dict[Action, _Handler] = {}


def register(action: Action, execute: Executor, *, edit: EditValidator | None = None) -> None:
    """The module owning a sensitive action registers how it runs (and how a person may edit
    its parameters before approving)."""
    if not gateway.requires_approval(action):
        raise ValueError(f"{action} does not need an approval")
    _HANDLERS[action] = _Handler(execute, edit)


def registered() -> frozenset[Action]:
    return frozenset(_HANDLERS)


@dataclass(frozen=True)
class ApprovalInfo:
    id: UUID
    action: str
    agent: str
    summary: str
    params: dict[str, Any]
    target_type: str | None
    target_id: UUID | None
    flag: str | None
    status: str  # pending | approved | rejected | expired | executing | executed | failed |
    #              canceled | unknown
    decision: str | None  # once | always | rule | reject
    decided_by_user_id: UUID | None
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    finished_at: datetime | None
    error: str | None
    editable: bool  # a person may edit the parameters before approving
    allow_always: bool  # "Always allow" is offered for this action


@dataclass(frozen=True)
class RuleInfo:
    id: UUID
    agent: str
    action: str
    created_by_user_id: UUID | None
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _status(r: ApprovalRequest, now: datetime) -> str:
    if r.status == "pending" and r.expires_at <= now:
        return "expired"
    if r.status == "executing" and r.started_at is not None and r.started_at < now - STUCK_AFTER:
        return "unknown"  # may have taken effect: never retried
    return r.status


def _info(r: ApprovalRequest) -> ApprovalInfo:
    policy = gateway.APPROVALS.get(Action(r.action))
    handler = _HANDLERS.get(Action(r.action))
    return ApprovalInfo(
        r.id, r.action, r.agent, r.summary, dict(r.params), r.target_type, r.target_id, r.flag,
        _status(r, _now()), r.decision, r.decided_by_user_id, r.requested_at, r.expires_at,
        r.decided_at, r.finished_at, r.error,
        editable=handler is not None and handler.edit is not None,
        allow_always=policy is not None and policy.allow_always and r.flag is None,
    )  # fmt: skip


def _rule_info(r: ApprovalRule) -> RuleInfo:
    return RuleInfo(r.id, r.agent, r.action, r.created_by_user_id, r.created_at)


# --- requests (agents, inside trusted server code) ----------------------------------------------


async def request(
    factory: Factory, ctx: TenantContext, deps: Deps, *, agent: str, action: Action,
    params: Mapping[str, Any], summary: str, idempotency_key: str,
    target_type: str | None = None, target_id: UUID | None = None, flag: str | None = None,
    granted: frozenset[Action] | None = None, use_rules: bool = True,
) -> tuple[ApprovalInfo, bool]:  # fmt: skip
    """Ask for a person's approval (or approve under an "always allow" rule).

    `use_rules=False` always waits for a person: the request came from someone who may not
    approve it themselves (an Executive proposal asked for by a Member).

    Returns (request, created). Idempotent per `idempotency_key`: a repeat with the same
    parameters returns the first request; different parameters raise IdempotencyConflictError.
    Owners and Admins are told about a new pending request by email and push.
    """
    gateway.authorize(agent, action, granted)
    policy = gateway.APPROVALS.get(action)
    if policy is None:
        raise ValueError(f"{action} does not need an approval")
    if not idempotency_key or len(idempotency_key) > gateway.MAX_KEY_LEN:
        raise ValueError("invalid idempotency key")
    digest = gateway.params_hash(params)
    now = _now()
    async with tenant_session(factory, ctx) as session:
        rule = None
        if policy.allow_always and flag is None and use_rules:
            rule = (
                await session.execute(
                    select(ApprovalRule).where(ApprovalRule.business_id == ctx.business_id,
                                               ApprovalRule.agent == agent,
                                               ApprovalRule.action == action)
                )
            ).scalar_one_or_none()  # fmt: skip
        values: dict[str, Any] = dict(
            id=uuid7(), business_id=ctx.business_id, action=action, agent=agent,
            idempotency_key=idempotency_key, params=dict(params), params_hash=digest,
            summary=" ".join(summary.split())[:MAX_SUMMARY], target_type=target_type,
            target_id=target_id, flag=flag, status="pending", requested_at=now,
            expires_at=now + policy.ttl,
        )  # fmt: skip
        if rule is not None:
            values.update(status="approved", decision="rule", rule_id=rule.id,
                          approved_hash=digest, decided_at=now)  # fmt: skip
        inserted = (
            await session.execute(
                insert(ApprovalRequest).values(**values)
                .on_conflict_do_nothing(index_elements=["business_id", "idempotency_key"])
                .returning(ApprovalRequest.id)
            )
        ).scalar_one_or_none()  # fmt: skip
        row = (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.business_id == ctx.business_id,
                    ApprovalRequest.idempotency_key == idempotency_key)
            )
        ).scalar_one()  # fmt: skip
        if inserted is None:
            if row.agent != agent or row.action != action or row.params_hash != digest:
                raise gateway.IdempotencyConflictError
            return _info(row), False
        details = {"agent": agent, "kind": str(action)}
        await record(session, ctx, action=AuditAction.APPROVAL_REQUESTED, actor_user_id=None,
                     target_type="approval", target_id=row.id,
                     details=details | ({"flagged": True} if flag else {}))  # fmt: skip
        if rule is not None:
            await record(session, ctx, action=AuditAction.APPROVAL_DECIDED, actor_user_id=None,
                         target_type="approval", target_id=row.id,
                         details=details | {"decision": "rule"})  # fmt: skip
        info = _info(row)
    if info.status == "pending":
        await _notify(factory, ctx, deps, info)
    return info, True


async def _notify(factory: Factory, ctx: TenantContext, deps: Deps, info: ApprovalInfo) -> None:
    business = await tenancy.get_business(factory, ctx)
    members = await tenancy.list_members(factory, ctx)
    d = definition(info.agent)
    agent = d.title if d else "An agent"
    label = gateway.APPROVALS[Action(info.action)].label
    url = f"{deps.settings.public_base_url}/b/{ctx.business_id}/approvals"
    for m in members:
        if m.role in (Role.OWNER, Role.ADMIN):
            await send_safely(deps.mailer, _email(m.email, business.name, agent, label, url),
                              kind="approval_requested")  # fmt: skip
    if deps.push is not None:
        # Lock screens are public: no names, no message text.
        await notifications.push_to_admins(factory, deps.push, ctx, PushMessage(
            title=f"Approval needed for {business.name}",
            body=f"{agent} wants to {label}.", url=f"/b/{ctx.business_id}/approvals",
            tag=f"approval-{info.id}",
        ))  # fmt: skip


def _email(to: str, business: str, agent: str, label: str, url: str) -> OutgoingEmail:
    return branded_email(to, EmailContent(
        subject=f"Approval needed: {agent} wants to {label}",
        preheader=f"Review it in Agentree — {business}",
        heading="An agent is waiting for your approval",
        paragraphs=[
            f"The {agent} of {business} wants to {label}. Nothing happens until you approve it.",
            "You can approve it once, always allow it, edit it first, or reject it.",
        ],
        action=EmailAction("Review", url),
        footnote="Requests you don't answer expire on their own.",
        reason=f"You're receiving this because you're an owner or admin of {business} on "
        "Agentree.",
    ))  # fmt: skip


# --- people (Owners and Admins decide; members may look) ----------------------------------------


async def _get(session: AsyncSession, ctx: TenantContext, approval_id: UUID, *,
               lock: bool = False) -> ApprovalRequest:  # fmt: skip
    query = select(ApprovalRequest).where(ApprovalRequest.business_id == ctx.business_id,
                                          ApprovalRequest.id == approval_id)  # fmt: skip
    row = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if row is None:
        raise NotFoundError
    return row


async def list_requests(
    factory: Factory, ctx: TenantContext, *, pending: bool, limit: int = 50
) -> list[ApprovalInfo]:
    """Pending requests (oldest first), or the history (newest first)."""
    now = _now()
    query = select(ApprovalRequest).where(ApprovalRequest.business_id == ctx.business_id)
    if pending:
        query = query.where(ApprovalRequest.status == "pending",
                            ApprovalRequest.expires_at > now).order_by(
            ApprovalRequest.requested_at)  # fmt: skip
    else:
        query = query.where(
            (ApprovalRequest.status != "pending") | (ApprovalRequest.expires_at <= now)
        ).order_by(ApprovalRequest.requested_at.desc())  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        rows = (await session.execute(query.limit(min(limit, MAX_PAGE)))).scalars().all()
    return [_info(r) for r in rows]


async def get_request(factory: Factory, ctx: TenantContext, approval_id: UUID) -> ApprovalInfo:
    async with tenant_session(factory, ctx) as session:
        return _info(await _get(session, ctx, approval_id))


async def decide(
    factory: Factory, ctx: TenantContext, approval_id: UUID, *, actor_id: UUID, decision: str,
    edits: dict[str, Any] | None = None,
) -> ApprovalInfo:  # fmt: skip
    """`decision`: once, always or reject. Edits (approve only) replace the parameters with the
    person's version, validated by the action's owner; the approval binds that exact version."""
    if decision not in ("once", "always", "reject"):
        raise ValueError("decision")
    now = _now()
    async with tenant_session(factory, ctx) as session:
        row = await _get(session, ctx, approval_id, lock=True)
        if row.status != "pending":
            raise InvalidStateError("not_pending")
        if row.expires_at <= now:
            raise InvalidStateError("expired")
        action = Action(row.action)
        policy = gateway.APPROVALS[action]
        details: dict[str, Any] = {"agent": row.agent, "kind": row.action, "decision": decision}
        if decision == "reject":
            row.status, row.decision = "rejected", "reject"
        else:
            if decision == "always" and (not policy.allow_always or row.flag is not None):
                raise InvalidStateError("always_not_allowed")
            if edits:
                handler = _HANDLERS.get(action)
                if handler is None or handler.edit is None:
                    raise InvalidEditError("not_editable")
                row.params = handler.edit(dict(row.params), edits)
                row.params_hash = gateway.params_hash(row.params)
                details["edited"] = True
            row.status, row.decision, row.approved_hash = "approved", decision, row.params_hash
            if decision == "always":
                rule_id = uuid7()
                created = (
                    await session.execute(
                        insert(ApprovalRule).values(
                            id=rule_id, business_id=ctx.business_id, agent=row.agent,
                            action=row.action, created_by_user_id=actor_id, created_at=now)
                        .on_conflict_do_nothing(
                            index_elements=["business_id", "agent", "action"])
                        .returning(ApprovalRule.id)
                    )
                ).scalar_one_or_none()  # fmt: skip
                if created is not None:
                    await record(session, ctx, action=AuditAction.APPROVAL_RULE_CREATED,
                                 actor_user_id=actor_id, target_type="approval_rule",
                                 target_id=created,
                                 details={"agent": row.agent, "kind": row.action})  # fmt: skip
        row.decided_by_user_id, row.decided_at = actor_id, now
        await record(session, ctx, action=AuditAction.APPROVAL_DECIDED, actor_user_id=actor_id,
                     target_type="approval", target_id=row.id, details=details)  # fmt: skip
        return _info(row)


async def list_rules(factory: Factory, ctx: TenantContext) -> list[RuleInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(ApprovalRule).where(ApprovalRule.business_id == ctx.business_id)
                .order_by(ApprovalRule.created_at)
            )
        ).scalars().all()  # fmt: skip
    return [_rule_info(r) for r in rows]


async def delete_rule(factory: Factory, ctx: TenantContext, rule_id: UUID, *,
                      actor_id: UUID) -> None:  # fmt: skip
    """Stop "always allow": the agent's next request waits for a person again."""
    async with tenant_session(factory, ctx) as session:
        rule = (
            await session.execute(
                select(ApprovalRule).where(ApprovalRule.business_id == ctx.business_id,
                                           ApprovalRule.id == rule_id)
            )
        ).scalar_one_or_none()  # fmt: skip
        if rule is None:
            raise NotFoundError
        await record(session, ctx, action=AuditAction.APPROVAL_RULE_REVOKED,
                     actor_user_id=actor_id, target_type="approval_rule", target_id=rule.id,
                     details={"agent": rule.agent, "kind": rule.action})  # fmt: skip
        await session.delete(rule)


# --- execution (exactly once) -------------------------------------------------------------------


async def execute(factory: Factory, ctx: TenantContext, deps: Deps, approval_id: UUID) -> str:
    """Run an approved request if this call wins it. Returns the request's resulting status
    (or its current one when another runner has it, or it is not approved)."""
    now = _now()
    async with tenant_session(factory, ctx) as session:
        won = (
            await session.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.business_id == ctx.business_id,
                       ApprovalRequest.id == approval_id, ApprovalRequest.status == "approved")
                .values(status="executing", started_at=now)
                .returning(ApprovalRequest.id)
            )
        ).scalar_one_or_none()  # fmt: skip
        row = await _get(session, ctx, approval_id)
        if won is None:
            return _status(row, now)
        job = Execution(row.id, row.agent, Action(row.action), dict(row.params),
                        await _authorized_by(session, ctx, row))  # fmt: skip
        intact = row.approved_hash == gateway.params_hash(row.params) == row.params_hash
    status, error = "executed", None
    if not intact:  # the parameters changed after approval: the approval is void
        status, error = "failed", "params_changed"
    else:
        try:
            # Only a current Owner or Admin's approval counts (the approver, or whoever created
            # the "always allow" rule, may have left or been demoted since).
            approver = (await tenancy.membership_role(factory, job.authorized_by, ctx.business_id)
                        if job.authorized_by is not None else None)  # fmt: skip
            if approver is None or not at_least(approver, Role.ADMIN):
                raise ExecutionCanceledError("approver_not_allowed")
            tools = await agent_configs.agent_tools(factory, ctx, _role(job.agent))
            gateway.authorize(job.agent, job.action, tools)
            handler = _HANDLERS.get(job.action)
            if handler is None:
                raise ExecutionFailedError("no_executor")
            await handler.execute(factory, ctx, deps, job)
        except gateway.ActionDeniedError:
            status, error = "canceled", "tool_turned_off"
        except ExecutionCanceledError as exc:
            status, error = "canceled", str(exc)[:64]
        except ExecutionFailedError as exc:
            status, error = "failed", str(exc)[:64]
        except Exception as exc:  # unexpected: recorded as failed, details only in the log type
            logger.error("approved action failed", extra={"error_type": type(exc).__name__,
                                                          "kind": str(job.action)})  # fmt: skip
            status, error = "failed", "error"
    async with tenant_session(factory, ctx) as session:
        row = await _get(session, ctx, approval_id, lock=True)
        row.status, row.error, row.finished_at = status, error, _now()
        await record(session, ctx, action=AuditAction.APPROVAL_EXECUTED, actor_user_id=None,
                     target_type="approval", target_id=row.id,
                     details={"agent": job.agent, "kind": str(job.action), "status": status,
                              "reason": error})  # fmt: skip
    return status


def _role(agent: str) -> AgentRole:
    d = definition(agent)
    if d is None:
        raise gateway.ActionDeniedError(agent)
    return d.role


async def _authorized_by(session: AsyncSession, ctx: TenantContext,
                         row: ApprovalRequest) -> UUID | None:  # fmt: skip
    if row.decided_by_user_id is not None or row.rule_id is None:
        return row.decided_by_user_id
    rule = (
        await session.execute(
            select(ApprovalRule.created_by_user_id).where(
                ApprovalRule.business_id == ctx.business_id, ApprovalRule.id == row.rule_id)
        )
    ).scalar_one_or_none()  # fmt: skip
    return rule


# --- worker -------------------------------------------------------------------------------------


async def run_due(factory: Factory, deps: Deps, *, now: datetime | None = None) -> int:
    """One pass: run approved requests the API did not run (safety net) and delete requests
    older than the retention window. Returns how many ran."""
    now = now or _now()
    async with factory() as session, session.begin():
        due = (
            await session.execute(text("SELECT business_id, id FROM agentree_due_approvals(:n)"),
                                  {"n": BATCH})
        ).all()  # fmt: skip
        await session.execute(text("SELECT agentree_purge_approvals(:cutoff)"),
                              {"cutoff": now - RETENTION})  # fmt: skip
    ran = 0
    for business_id, approval_id in due:
        ctx = TenantContext(business_id, TenantSource.JOB)
        try:
            if await execute(factory, ctx, deps, approval_id) not in ("approved", "executing"):
                ran += 1
        except Exception as exc:  # one business must not stop the others
            logger.error("approval run failed", extra={"error_type": type(exc).__name__})
    if due:
        logger.info("approvals run", extra={"due": len(due), "ran": ran})
    return ran


async def run_approvals_loop(factory: Factory, deps: Deps, *, interval_seconds: float,
                             stop: asyncio.Event) -> None:  # fmt: skip
    while not stop.is_set():
        try:
            await run_due(factory, deps)
        except Exception as exc:  # keep the worker alive; the next pass retries
            logger.error("approvals pass failed", extra={"error_type": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
