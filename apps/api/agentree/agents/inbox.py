"""Human inbox: public conversations a person can take over from the AI.

Statuses: `open` (the AI answers), `needs_human` (the visitor or the agent asked for a person;
the AI is paused), `human_active` (a member is replying; the AI is paused), `resolved`.
A visitor writing to a resolved conversation reopens it for the AI. Every status change and
assignment is audited; message content never goes to the audit trail or the logs.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.agents.models import Conversation, Message
from agentree.audit.service import AuditAction, record
from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailAction, EmailContent
from agentree.core.ids import uuid7
from agentree.core.webpush import PushMessage, PushSender
from agentree.notifications import service as notifications
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

PUBLIC = ("public", "widget")
STATUSES = ("open", "needs_human", "human_active", "resolved")
MAX_REPLY = 4000
MAX_PAGE = 100
PREVIEW = 140


class NotFoundError(Exception):
    pass


class InvalidStateError(Exception):
    """The action does not apply to the conversation's current status."""


class InvalidAssigneeError(ValueError):
    pass


@dataclass(frozen=True)
class InboxItem:
    id: UUID
    channel: str
    status: str
    assignee_user_id: UUID | None
    handoff_reason: str | None
    handoff_requested_at: datetime | None
    last_message_at: datetime
    created_at: datetime
    preview: str  # start of the latest message (shown to members only)
    preview_role: str


@dataclass(frozen=True)
class InboxMessage:
    id: UUID
    role: str  # user | assistant | human
    author_user_id: UUID | None
    content: str
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


async def _public_conversation(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID, *, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(
        Conversation.business_id == ctx.business_id, Conversation.id == conversation_id,
        Conversation.channel.in_(PUBLIC),
    )  # fmt: skip
    conv = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if conv is None:
        raise NotFoundError
    return conv


async def _audit(session: AsyncSession, ctx: TenantContext, conv: Conversation,
                 action: AuditAction, actor: UUID | None, **details: object) -> None:  # fmt: skip
    await record(session, ctx, action=action, actor_user_id=actor, target_type="conversation",
                 target_id=conv.id, details={"channel": conv.channel, **details})  # fmt: skip


# --- handoff requests (visitor or agent) ------------------------------------------------------


async def mark_handoff_requested(
    factory: Factory, ctx: TenantContext, conversation_id: UUID, *, reason: str
) -> bool:
    """open -> needs_human. Returns True only on that transition (the caller alerts the team)."""
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status not in ("open", "resolved"):
            return False
        conv.status, conv.handoff_reason, conv.handoff_requested_at = "needs_human", reason, _now()
        await _audit(session, ctx, conv, AuditAction.CONVERSATION_HANDOFF_REQUESTED, None,
                     reason=reason)  # fmt: skip
        return True


async def cancel_handoff_by_guest(
    factory: Factory, ctx: TenantContext, conversation_id: UUID
) -> str:
    """The visitor chose to continue with the assistant while nobody had taken over yet."""
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status == "needs_human":
            conv.status = "open"
            await _audit(session, ctx, conv, AuditAction.CONVERSATION_HANDOFF_CANCELED, None)
        return conv.status


async def conversation_status(factory: Factory, ctx: TenantContext, conversation_id: UUID) -> str:
    async with tenant_session(factory, ctx) as session:
        return (await _public_conversation(session, ctx, conversation_id)).status


async def notify_handoff(
    factory: Factory, settings: Settings, mailer: EmailSender, push: PushSender,
    ctx: TenantContext, conversation_id: UUID, *, reason: str,
) -> None:  # fmt: skip
    """Email (and push to) Owners and Admins that a visitor is waiting for a person."""
    business = await tenancy.get_business(factory, ctx)
    members = await tenancy.list_members(factory, ctx)
    url = f"{settings.public_base_url}/b/{ctx.business_id}/inbox/{conversation_id}"
    for m in members:
        if m.role in (Role.OWNER, Role.ADMIN):
            await send_safely(mailer, _handoff_email(m.email, business.name, reason, url),
                              kind="handoff_request")  # fmt: skip
    await notifications.push_to_admins(factory, push, ctx, PushMessage(
        title=f"A visitor is waiting for {business.name}",
        body="They want to talk to your team. Tap to take over the conversation.",
        url=f"/b/{ctx.business_id}/inbox/{conversation_id}", tag=f"handoff-{conversation_id}",
    ))  # fmt: skip


def _handoff_email(to: str, business: str, reason: str, url: str) -> OutgoingEmail:
    why = (
        "asked to talk to a person"
        if reason == "visitor"
        else "has a question your Sales Agent couldn't answer"
    )
    return branded_email(
        to,
        EmailContent(
            subject=f"A visitor is waiting for {business}",
            preheader=f"A visitor {why}.",
            heading="A visitor wants to talk to your team",
            paragraphs=[
                f"A visitor on {business}'s page {why}. The AI has paused in this conversation "
                "until someone from your team takes over or hands it back.",
            ],
            action=EmailAction("Open the conversation", url),
            footnote="Reply in the inbox: the visitor sees your message in the same chat.",
            reason=f"You're receiving this because you're an owner or admin of {business} "
            "on Agentree.",
        ),
    )


# --- members --------------------------------------------------------------------------------


async def list_inbox(
    factory: Factory, ctx: TenantContext, *, status: str | None = None,
    before: datetime | None = None, limit: int = 50,
) -> list[InboxItem]:  # fmt: skip
    """Public and widget conversations, most recent activity first."""
    limit = max(1, min(limit, MAX_PAGE))
    latest = (
        select(Message.conversation_id, Message.content, Message.role,
               func.row_number().over(partition_by=Message.conversation_id,
                                      order_by=(Message.created_at.desc(), Message.id.desc()))
               .label("rn"))
        .where(Message.business_id == ctx.business_id)
        .subquery()
    )  # fmt: skip
    query = (
        select(Conversation, latest.c.content, latest.c.role)
        .outerjoin(latest, (latest.c.conversation_id == Conversation.id) & (latest.c.rn == 1))
        .where(Conversation.business_id == ctx.business_id, Conversation.channel.in_(PUBLIC))
    )
    if status is not None:
        query = query.where(Conversation.status == status)
    if before is not None:
        query = query.where(Conversation.last_message_at < before)
    query = query.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(limit)
    async with tenant_session(factory, ctx) as session:
        rows = (await session.execute(query)).all()
    return [
        InboxItem(c.id, c.channel, c.status, c.assignee_user_id, c.handoff_reason,
                  c.handoff_requested_at, c.last_message_at, c.created_at,
                  " ".join((content or "").split())[:PREVIEW], role or "")
        for c, content, role in rows
    ]  # fmt: skip


async def counts(factory: Factory, ctx: TenantContext) -> dict[str, int]:
    async with tenant_session(factory, ctx) as session:
        rows = await session.execute(
            select(Conversation.status, func.count())
            .where(Conversation.business_id == ctx.business_id, Conversation.channel.in_(PUBLIC))
            .group_by(Conversation.status)
        )
        found = {s: int(n) for s, n in rows.all()}
    return {s: found.get(s, 0) for s in STATUSES}


async def get_conversation(
    factory: Factory, ctx: TenantContext, conversation_id: UUID
) -> tuple[InboxItem, list[InboxMessage]]:
    async with tenant_session(factory, ctx) as session:
        c = await _public_conversation(session, ctx, conversation_id)
        rows = (
            await session.execute(
                select(Message)
                .where(Message.business_id == ctx.business_id,
                       Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        ).scalars().all()  # fmt: skip
        item = InboxItem(
            c.id, c.channel, c.status, c.assignee_user_id, c.handoff_reason,
            c.handoff_requested_at, c.last_message_at, c.created_at, "", "",
        )  # fmt: skip
        return item, [InboxMessage(m.id, m.role, m.author_user_id, m.content, m.created_at)
                      for m in rows]  # fmt: skip


async def _check_member(factory: Factory, ctx: TenantContext, user_id: UUID | None) -> None:
    if (
        user_id is not None
        and await tenancy.membership_role(factory, user_id, ctx.business_id) is None
    ):
        raise InvalidAssigneeError


async def take_over(factory: Factory, ctx: TenantContext, conversation_id: UUID, *,
                    actor_id: UUID) -> None:  # fmt: skip
    """The member starts handling the conversation: the AI pauses; they become the assignee."""
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status == "human_active" and conv.assignee_user_id == actor_id:
            return
        conv.status, conv.assignee_user_id = "human_active", actor_id
        await _audit(session, ctx, conv, AuditAction.CONVERSATION_TAKEN_OVER, actor_id)


async def assign(factory: Factory, ctx: TenantContext, conversation_id: UUID, *,
                 actor_id: UUID, assignee_user_id: UUID | None) -> None:  # fmt: skip
    await _check_member(factory, ctx, assignee_user_id)
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.assignee_user_id != assignee_user_id:
            conv.assignee_user_id = assignee_user_id
            await _audit(session, ctx, conv, AuditAction.CONVERSATION_ASSIGNED, actor_id,
                         assigned=assignee_user_id is not None)  # fmt: skip


async def reply(factory: Factory, ctx: TenantContext, conversation_id: UUID, *,
                actor_id: UUID, content: str) -> InboxMessage:  # fmt: skip
    """A member's message to the visitor. Only while a person is handling the conversation."""
    text = content.strip()
    if not text or len(text) > MAX_REPLY:
        raise ValueError("content")
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status != "human_active":
            raise InvalidStateError
        now = _now()
        msg = Message(
            id=uuid7(), business_id=ctx.business_id, conversation_id=conv.id, role="human",
            author_user_id=actor_id, content=text, created_at=now,
        )  # fmt: skip
        session.add(msg)
        conv.last_message_at = now
        return InboxMessage(msg.id, "human", actor_id, text, now)


async def release(factory: Factory, ctx: TenantContext, conversation_id: UUID, *,
                  actor_id: UUID) -> None:  # fmt: skip
    """Hand the conversation back to the AI."""
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status not in ("needs_human", "human_active"):
            raise InvalidStateError
        conv.status, conv.assignee_user_id = "open", None
        await _audit(session, ctx, conv, AuditAction.CONVERSATION_RELEASED, actor_id)


async def resolve(factory: Factory, ctx: TenantContext, conversation_id: UUID, *,
                  actor_id: UUID) -> None:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        conv = await _public_conversation(session, ctx, conversation_id, lock=True)
        if conv.status == "resolved":
            return
        conv.status = "resolved"
        await _audit(session, ctx, conv, AuditAction.CONVERSATION_RESOLVED, actor_id)
