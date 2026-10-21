"""Follow-up tasks: reminders for the team to contact a lead (people contact customers, not the AI).

Rules (fixed by Agentree for now; business-specific sales playbooks come with agent
configuration):
- A new lead gets one "first contact" task from the Sales Agent, due 24 hours later, created
  through the Action Gateway (idempotent per lead).
- Moving the lead past "new" (contacted, qualified, won, lost) closes its open first-contact task.
- The agent may hold at most 3 open tasks per lead; members at most 20. Due dates must be within
  the next year (agent: between 15 minutes and 30 days).
- The worker emails one reminder when an open task is past due: to the assignee, or to Owners
  and Admins when nobody is assigned. A failed send is retried on the next pass.
Task titles may contain a lead's name: they are never logged.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.actions import service as gateway
from agentree.audit.service import AuditAction, record
from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailAction, EmailContent, clean_text
from agentree.core.ids import uuid7
from agentree.leads.models import FollowUpTask, Lead
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

FIRST_CONTACT_DELAY = timedelta(hours=24)
AGENT_MIN_DUE, AGENT_MAX_DUE = timedelta(minutes=15), timedelta(days=30)
MEMBER_MAX_DUE = timedelta(days=365)
MAX_OPEN_AGENT_TASKS_PER_LEAD = 3
MAX_OPEN_TASKS_PER_LEAD = 20
MAX_TITLE = 200
REMINDER_BATCH = 100
CLOSED_STATUSES = frozenset({"contacted", "qualified", "won", "lost"})


class InvalidTaskError(ValueError):
    pass


class TaskLimitError(Exception):
    pass


class NotFoundError(Exception):
    pass


@dataclass(frozen=True)
class TaskInfo:
    id: UUID
    lead_id: UUID
    title: str
    due_at: datetime
    assignee_user_id: UUID | None
    status: str
    kind: str
    created_by_agent: str | None
    created_by_user_id: UUID | None
    completed_at: datetime | None
    created_at: datetime


def _info(t: FollowUpTask) -> TaskInfo:
    return TaskInfo(
        t.id,
        t.lead_id,
        t.title,
        t.due_at,
        t.assignee_user_id,
        t.status,
        t.kind,
        t.created_by_agent,
        t.created_by_user_id,
        t.completed_at,
        t.created_at,
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def _open_count(session: AsyncSession, ctx: TenantContext, lead_id: UUID,
                      *, agent_only: bool = False) -> int:  # fmt: skip
    query = select(func.count()).select_from(FollowUpTask).where(
        FollowUpTask.business_id == ctx.business_id, FollowUpTask.lead_id == lead_id,
        FollowUpTask.status == "open",
    )  # fmt: skip
    if agent_only:
        query = query.where(FollowUpTask.created_by_agent.is_not(None))
    return int((await session.execute(query)).scalar_one())


# --- agent (inside the lead transaction) ---------------------------------------------------


async def create_first_contact_task(session: AsyncSession, ctx: TenantContext, lead: Lead) -> None:
    """The Sales Agent's follow-up for a new lead, through the gateway (idempotent per lead)."""
    agent = lead.source_agent
    due = _now() + FIRST_CONTACT_DELAY
    title = clean_text(f"Contact {lead.name or 'the visitor'}")[:MAX_TITLE]
    key = f"follow-up:first-contact:{lead.id}"
    params = {"lead_id": str(lead.id), "kind": "first_contact"}
    prior = await gateway.claim(session, ctx, agent=agent,
                                action=gateway.Action.CREATE_FOLLOW_UP_TASK,
                                idempotency_key=key, params=params)  # fmt: skip
    if prior is not None:
        return
    if not AGENT_MIN_DUE <= due - _now() <= AGENT_MAX_DUE:
        raise InvalidTaskError("due_at")
    if await _open_count(session, ctx, lead.id, agent_only=True) >= MAX_OPEN_AGENT_TASKS_PER_LEAD:
        raise TaskLimitError
    task = FollowUpTask(id=uuid7(), business_id=ctx.business_id, lead_id=lead.id, title=title,
                        due_at=due, status="open", kind="first_contact", created_by_agent=agent,
                        created_at=_now())  # fmt: skip
    session.add(task)
    await session.flush()
    await gateway.complete(session, ctx, idempotency_key=key, result_id=task.id)
    await record(session, ctx, action=AuditAction.FOLLOW_UP_CREATED, actor_user_id=None,
                 target_type="follow_up", target_id=task.id,
                 details={"kind": "first_contact", "agent": agent})  # fmt: skip


async def close_first_contact(session: AsyncSession, ctx: TenantContext, lead_id: UUID,
                              new_status: str, actor_id: UUID) -> None:  # fmt: skip
    """The lead moved past "new": its open first-contact task is done."""
    if new_status not in CLOSED_STATUSES:
        return
    rows = (
        await session.execute(
            select(FollowUpTask).where(
                FollowUpTask.business_id == ctx.business_id, FollowUpTask.lead_id == lead_id,
                FollowUpTask.kind == "first_contact", FollowUpTask.status == "open",
            )
        )
    ).scalars().all()  # fmt: skip
    for task in rows:
        task.status, task.completed_at = "done", _now()
        await record(session, ctx, action=AuditAction.FOLLOW_UP_UPDATED, actor_user_id=actor_id,
                     target_type="follow_up", target_id=task.id,
                     details={"from_status": "open", "to_status": "done"})  # fmt: skip


# --- members ---------------------------------------------------------------------------------


async def _lead_exists(session: AsyncSession, ctx: TenantContext, lead_id: UUID) -> None:
    found = (
        await session.execute(
            select(Lead.id).where(Lead.business_id == ctx.business_id, Lead.id == lead_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise NotFoundError


async def _check_assignee(factory: Factory, ctx: TenantContext, user_id: UUID | None) -> None:
    if (
        user_id is not None
        and await tenancy.membership_role(factory, user_id, ctx.business_id) is None
    ):
        raise InvalidTaskError("assignee")


def _check_due(due_at: datetime) -> datetime:
    if due_at.tzinfo is None:
        raise InvalidTaskError("due_at")
    now = _now()
    if not now - timedelta(minutes=1) <= due_at <= now + MEMBER_MAX_DUE:
        raise InvalidTaskError("due_at")
    return due_at


async def list_tasks(factory: Factory, ctx: TenantContext, lead_id: UUID) -> list[TaskInfo]:
    async with tenant_session(factory, ctx) as session:
        await _lead_exists(session, ctx, lead_id)
        rows = (
            await session.execute(
                select(FollowUpTask)
                .where(FollowUpTask.business_id == ctx.business_id, FollowUpTask.lead_id == lead_id)
                .order_by(FollowUpTask.status != "open", FollowUpTask.due_at)
            )
        ).scalars()  # fmt: skip
        return [_info(t) for t in rows]


async def next_due(
    factory: Factory, ctx: TenantContext, lead_ids: list[UUID]
) -> dict[UUID, datetime]:
    """Earliest open follow-up per lead (for the leads list)."""
    if not lead_ids:
        return {}
    async with tenant_session(factory, ctx) as session:
        rows = await session.execute(
            select(FollowUpTask.lead_id, func.min(FollowUpTask.due_at))
            .where(FollowUpTask.business_id == ctx.business_id, FollowUpTask.status == "open",
                   FollowUpTask.lead_id.in_(lead_ids))
            .group_by(FollowUpTask.lead_id)
        )  # fmt: skip
        return {lead_id: due for lead_id, due in rows.all()}


async def create_task(
    factory: Factory, ctx: TenantContext, lead_id: UUID, *, actor_id: UUID, title: str,
    due_at: datetime, assignee_user_id: UUID | None,
) -> TaskInfo:  # fmt: skip
    title = clean_text(title)[:MAX_TITLE]
    if not title:
        raise InvalidTaskError("title")
    _check_due(due_at)
    await _check_assignee(factory, ctx, assignee_user_id)
    async with tenant_session(factory, ctx) as session:
        await _lead_exists(session, ctx, lead_id)
        if await _open_count(session, ctx, lead_id) >= MAX_OPEN_TASKS_PER_LEAD:
            raise TaskLimitError
        task = FollowUpTask(
            id=uuid7(),
            business_id=ctx.business_id,
            lead_id=lead_id,
            title=title,
            due_at=due_at,
            assignee_user_id=assignee_user_id,
            status="open",
            kind="manual",
            created_by_user_id=actor_id,
            created_at=_now(),
        )
        session.add(task)
        await session.flush()
        await record(
            session,
            ctx,
            action=AuditAction.FOLLOW_UP_CREATED,
            actor_user_id=actor_id,
            target_type="follow_up",
            target_id=task.id,
            details={"kind": "manual", "assigned": assignee_user_id is not None},
        )
        return _info(task)


async def update_task(
    factory: Factory, ctx: TenantContext, task_id: UUID, *, actor_id: UUID,
    status: str | None = None, due_at: datetime | None = None,
    reassign: bool = False, assignee_user_id: UUID | None = None,
) -> TaskInfo:  # fmt: skip
    """Change status, due date and/or assignee (`reassign=True`, None unassigns)."""
    if status is not None and status not in ("open", "done", "canceled"):
        raise InvalidTaskError("status")
    if due_at is not None:
        _check_due(due_at)
    if reassign:
        await _check_assignee(factory, ctx, assignee_user_id)
    async with tenant_session(factory, ctx) as session:
        task = (
            await session.execute(
                select(FollowUpTask).where(
                    FollowUpTask.business_id == ctx.business_id, FollowUpTask.id == task_id
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError
        details: dict[str, object] = {}
        if status is not None and status != task.status:
            details |= {"from_status": task.status, "to_status": status}
            task.status = status
            task.completed_at = _now() if status == "done" else None
        if due_at is not None and due_at != task.due_at:
            task.due_at, task.reminder_sent_at = due_at, None  # remind again for the new date
            details["due_at"] = due_at.isoformat()
        if reassign and assignee_user_id != task.assignee_user_id:
            task.assignee_user_id = assignee_user_id
            details["assigned"] = assignee_user_id is not None
        if details:
            await record(session, ctx, action=AuditAction.FOLLOW_UP_UPDATED,
                         actor_user_id=actor_id, target_type="follow_up", target_id=task.id,
                         details=details)  # fmt: skip
        return _info(task)


# --- worker: reminders ----------------------------------------------------------------------


async def send_due_reminders(
    factory: Factory, settings: Settings, mailer: EmailSender, *, now: datetime | None = None
) -> int:
    """Claim overdue open tasks across businesses and email one reminder each.

    Returns how many reminders went out.
    """
    async with factory() as session, session.begin():
        claimed = (
            await session.execute(
                text("SELECT business_id, task_id FROM agentree_claim_due_follow_ups(:now, :n)"),
                {"now": now or _now(), "n": REMINDER_BATCH},
            )
        ).all()
    sent = 0
    for business_id, task_id in claimed:
        ctx = TenantContext(business_id, TenantSource.JOB)
        try:
            ok = await _remind(factory, settings, mailer, ctx, task_id)
        except Exception as exc:  # one bad task must not stop the others
            logger.error("follow-up reminder failed", extra={"error_type": type(exc).__name__})
            ok = False
        if ok:
            sent += 1
        else:  # let the next pass retry
            async with tenant_session(factory, ctx) as session:
                task = await session.get(FollowUpTask, task_id)
                if task is not None and task.status == "open":
                    task.reminder_sent_at = None
    if claimed:
        logger.info("follow-up reminders", extra={"claimed": len(claimed), "sent": sent})
    return sent


async def _remind(factory: Factory, settings: Settings, mailer: EmailSender,
                  ctx: TenantContext, task_id: UUID) -> bool:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        row = (
            await session.execute(
                select(FollowUpTask, Lead).join(Lead, Lead.id == FollowUpTask.lead_id).where(
                    FollowUpTask.business_id == ctx.business_id, FollowUpTask.id == task_id)
            )
        ).one_or_none()  # fmt: skip
        if row is None:
            return True  # deleted meanwhile: nothing to remind about
        task, lead = row
        title, lead_id, assignee = task.title, lead.id, task.assignee_user_id
        lead_name, lead_need = lead.name, lead.need
    business = await tenancy.get_business(factory, ctx)
    members = await tenancy.list_members(factory, ctx)
    to = [m.email for m in members if m.user_id == assignee]
    if not to:  # unassigned, or the assignee left: owners and admins
        to = [m.email for m in members if m.role in (Role.OWNER, Role.ADMIN)]
    url = f"{settings.public_base_url}/b/{ctx.business_id}/leads/{lead_id}"
    results = await asyncio.gather(*(
        send_safely(mailer, _reminder_email(r, business.name, title, lead_name, lead_need, url),
                    kind="follow_up_reminder")
        for r in to
    ))  # fmt: skip
    return any(results)


def _reminder_email(
    to: str, business: str, title: str, name: str, need: str, url: str
) -> OutgoingEmail:
    paragraphs = [f"This follow-up for {business} is due: {title}."]
    if need:
        who = f"{name} needs" if name else "They need"
        paragraphs.append(f"{who}: {need[:300]}")
    return branded_email(
        to,
        EmailContent(
            subject=f"Follow-up due: {title}",
            preheader=f"{title} — {business}",
            heading="A follow-up is due",
            paragraphs=paragraphs,
            action=EmailAction("Open lead", url),
            footnote="Mark the task done or change its date once you've followed up.",
            reason=f"You're receiving this because you're assigned to this follow-up, or you're "
            f"an owner or admin of {business} on Agentree.",
        ),
    )


async def run_follow_up_loop(factory: Factory, settings: Settings, mailer: EmailSender, *,
                             interval_seconds: float, stop: asyncio.Event) -> None:  # fmt: skip
    """Send due reminders every `interval_seconds` until `stop` is set."""
    while not stop.is_set():
        try:
            await send_due_reminders(factory, settings, mailer)
        except Exception as exc:  # keep the worker alive; next run retries
            logger.error("follow-up pass failed", extra={"error_type": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
