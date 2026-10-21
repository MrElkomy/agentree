"""Leads: contact details a visitor confirmed in a public conversation, for the team to follow up.

Visitor submissions are agent actions of the Sales Agent and go through the Action Gateway
(authorization + idempotency). One lead per conversation: a second submission updates it.
Members manage status and notes from the dashboard. Every change is audited; contact details
are never written to logs or to the audit trail.
"""

import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.actions import service as gateway
from agentree.agents import service as agents
from agentree.audit.service import AuditAction, record
from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailAction, EmailContent, clean_text
from agentree.core.ids import uuid7
from agentree.leads import follow_ups
from agentree.leads.models import Lead
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

SOURCE_AGENT = "sales"
MAX_NAME = 100
MAX_EMAIL = 254
MAX_PHONE = 32
MAX_NEED = 500
MAX_NOTES = 2000
MAX_PAGE = 100
SUBMITS_PER_SESSION_PER_HOUR = 10

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
PHONE_RE = re.compile(r"^\+?[0-9 ().-]{7,32}$")


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    WON = "won"
    LOST = "lost"


class InvalidLeadError(ValueError):
    pass


class NotFoundError(Exception):
    pass


@dataclass(frozen=True)
class LeadFields:
    name: str
    email: str | None
    phone: str | None
    need: str


def validate_fields(*, name: str, email: str | None, phone: str | None, need: str) -> LeadFields:
    """Normalize and validate visitor-supplied contact details (all untrusted input)."""
    name = clean_text(name)[:MAX_NAME]
    need = " ".join(need.split())
    email = (email or "").strip().lower() or None
    phone = " ".join((phone or "").split()) or None
    if email is not None and (len(email) > MAX_EMAIL or not EMAIL_RE.fullmatch(email)):
        raise InvalidLeadError("email")
    if phone is not None and (
        not PHONE_RE.fullmatch(phone) or not 7 <= sum(c.isdigit() for c in phone) <= 15
    ):
        raise InvalidLeadError("phone")
    if email is None and phone is None:
        raise InvalidLeadError("contact")
    if len(need) > MAX_NEED:
        raise InvalidLeadError("need")
    return LeadFields(name, email, phone, need)


@dataclass(frozen=True)
class LeadInfo:
    id: UUID
    conversation_id: UUID | None
    channel: str
    source_agent: str
    name: str
    email: str | None
    phone: str | None
    need: str
    consent_at: datetime
    status: LeadStatus
    notes: str
    created_at: datetime
    updated_at: datetime
    next_follow_up_at: datetime | None = None  # earliest open follow-up (lists only)


def _info(lead: Lead) -> LeadInfo:
    return LeadInfo(
        lead.id, lead.conversation_id, lead.channel, lead.source_agent, lead.name, lead.email,
        lead.phone, lead.need, lead.consent_at, LeadStatus(lead.status), lead.notes,
        lead.created_at, lead.updated_at,
    )  # fmt: skip


def _now() -> datetime:
    return datetime.now(UTC)


# --- visitor submission (Sales Agent action through the gateway) -------------------------


async def _by_id(session: AsyncSession, ctx: TenantContext, lead_id: UUID) -> Lead:
    lead = (
        await session.execute(
            select(Lead).where(Lead.business_id == ctx.business_id, Lead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise NotFoundError
    return lead


async def _submit(
    factory: Factory, ctx: TenantContext, *, conversation_id: UUID, channel: str,
    fields: LeadFields, idempotency_key: str,
) -> tuple[LeadInfo, bool]:  # fmt: skip
    params = {"conversation_id": str(conversation_id), "name": fields.name,
              "email": fields.email, "phone": fields.phone, "need": fields.need}  # fmt: skip
    now = _now()
    async with tenant_session(factory, ctx) as session:
        existing = (
            await session.execute(
                select(Lead).where(Lead.business_id == ctx.business_id,
                                   Lead.conversation_id == conversation_id)
            )
        ).scalar_one_or_none()  # fmt: skip
        action = gateway.Action.UPDATE_LEAD if existing else gateway.Action.CREATE_LEAD
        prior = await gateway.claim(session, ctx, agent=SOURCE_AGENT, action=action,
                                    idempotency_key=idempotency_key, params=params)  # fmt: skip
        if prior is not None:  # a retry of a request that already succeeded
            return _info(await _by_id(session, ctx, prior)), False
        if existing is None:
            lead = Lead(
                id=uuid7(), business_id=ctx.business_id, conversation_id=conversation_id,
                channel=channel, source_agent=SOURCE_AGENT, name=fields.name, email=fields.email,
                phone=fields.phone, need=fields.need, consent_at=now, status=LeadStatus.NEW,
                created_at=now, updated_at=now,
            )  # fmt: skip
            session.add(lead)
            await session.flush()
            audit_action = AuditAction.LEAD_CREATED
            await follow_ups.create_first_contact_task(session, ctx, lead)
        else:
            lead = existing
            lead.name, lead.email, lead.phone = fields.name, fields.email, fields.phone
            lead.need, lead.consent_at, lead.updated_at = fields.need, now, now
            audit_action = AuditAction.LEAD_UPDATED
        await gateway.complete(session, ctx, idempotency_key=idempotency_key, result_id=lead.id)
        await record(
            session, ctx, action=audit_action, actor_user_id=None, target_type="lead",
            target_id=lead.id, details={"channel": channel, "agent": SOURCE_AGENT},
        )  # fmt: skip
        return _info(lead), existing is None


async def submit_guest_lead(
    factory: Factory, settings: Settings, mailer: EmailSender, ctx: TenantContext, *,
    guest_session_id: UUID, conversation_id: UUID, fields: LeadFields, idempotency_key: str,
) -> LeadInfo:  # fmt: skip
    """Record the details a visitor confirmed (with consent) in their own conversation.

    The caller must have authenticated `guest_session_id` within `ctx`'s business. A
    conversation that does not belong to that guest session raises `agents.NotFoundError`.
    """
    channel = await agents.guest_conversation_channel(
        factory, ctx, guest_session_id=guest_session_id, conversation_id=conversation_id
    )
    try:
        info, created = await _submit(factory, ctx, conversation_id=conversation_id,
                                      channel=channel, fields=fields,
                                      idempotency_key=idempotency_key)  # fmt: skip
    except IntegrityError:
        # A concurrent first submission (different key) created the lead: update it instead.
        info, created = await _submit(factory, ctx, conversation_id=conversation_id,
                                      channel=channel, fields=fields,
                                      idempotency_key=idempotency_key)  # fmt: skip
    if created:
        await _notify_new_lead(factory, settings, mailer, ctx, info)
    return info


async def _notify_new_lead(
    factory: Factory, settings: Settings, mailer: EmailSender, ctx: TenantContext, lead: LeadInfo
) -> None:
    business = await tenancy.get_business(factory, ctx)
    members = await tenancy.list_members(factory, ctx)
    recipients = [m.email for m in members if m.role in (Role.OWNER, Role.ADMIN)]
    for to in recipients:
        await send_safely(mailer, _new_lead_email(settings, business.name, ctx, lead, to),
                          kind="new_lead")  # fmt: skip


def _new_lead_email(
    settings: Settings, business_name: str, ctx: TenantContext, lead: LeadInfo, to: str
) -> OutgoingEmail:
    who = lead.name or "A visitor"
    where = "your website chat" if lead.channel == "widget" else "your public page"
    paragraphs = [f"{who} left their contact details for {business_name} on {where}."]
    if lead.need:
        paragraphs.append(f"What they need: {lead.need[:300]}")
    return branded_email(
        to,
        EmailContent(
            subject=f"New lead for {business_name}: {who}",
            preheader=f"{who} wants to hear from {business_name}.",
            heading="You have a new lead",
            paragraphs=paragraphs,
            action=EmailAction(
                "View lead", f"{settings.public_base_url}/b/{ctx.business_id}/leads/{lead.id}"
            ),
            footnote="They agreed to be contacted. Reply soon: fast follow-ups win more deals.",
            reason=f"You're receiving this because you're an owner or admin of {business_name} "
            "on Agentree.",
        ),
    )


# --- dashboard (members) ------------------------------------------------------------------


async def list_leads(
    factory: Factory, ctx: TenantContext, *, status: LeadStatus | None = None,
    before: UUID | None = None, limit: int = 50,
) -> list[LeadInfo]:  # fmt: skip
    """Newest first. Keyset pagination: pass the last id of a page as `before`."""
    limit = max(1, min(limit, MAX_PAGE))
    query = select(Lead).where(Lead.business_id == ctx.business_id)
    if status is not None:
        query = query.where(Lead.status == status)
    if before is not None:
        query = query.where(Lead.id < before)
    async with tenant_session(factory, ctx) as session:
        rows = (await session.execute(query.order_by(Lead.id.desc()).limit(limit))).scalars()
        leads = [_info(lead) for lead in rows]
    due = await follow_ups.next_due(factory, ctx, [lead.id for lead in leads])
    return [replace(lead, next_follow_up_at=due.get(lead.id)) for lead in leads]


async def get_lead(factory: Factory, ctx: TenantContext, lead_id: UUID) -> LeadInfo:
    async with tenant_session(factory, ctx) as session:
        return _info(await _by_id(session, ctx, lead_id))


async def update_lead(
    factory: Factory, ctx: TenantContext, lead_id: UUID, *, actor_id: UUID,
    status: LeadStatus | None = None, notes: str | None = None,
) -> LeadInfo:  # fmt: skip
    """Member edits: pipeline status and private notes. Caller authorizes the member."""
    if notes is not None and len(notes) > MAX_NOTES:
        raise InvalidLeadError("notes")
    async with tenant_session(factory, ctx) as session:
        lead = await _by_id(session, ctx, lead_id)
        changed = False
        if status is not None and status != lead.status:
            await record(session, ctx, action=AuditAction.LEAD_STATUS_CHANGED,
                         actor_user_id=actor_id, target_type="lead", target_id=lead.id,
                         details={"from_status": lead.status, "to_status": status})  # fmt: skip
            lead.status = status
            await follow_ups.close_first_contact(session, ctx, lead.id, status, actor_id)
            changed = True
        if notes is not None and notes != lead.notes:
            await record(session, ctx, action=AuditAction.LEAD_NOTES_UPDATED,
                         actor_user_id=actor_id, target_type="lead", target_id=lead.id)  # fmt: skip
            lead.notes = notes
            changed = True
        if changed:
            lead.updated_at = _now()
        return _info(lead)


async def delete_lead(
    factory: Factory, ctx: TenantContext, lead_id: UUID, *, actor_id: UUID
) -> None:
    """Erase a lead (e.g. a visitor's deletion request). Caller authorizes an Admin or Owner."""
    async with tenant_session(factory, ctx) as session:
        lead = await _by_id(session, ctx, lead_id)
        await record(
            session, ctx, action=AuditAction.LEAD_DELETED, actor_user_id=actor_id,
            target_type="lead", target_id=lead.id, details={"channel": lead.channel},
        )  # fmt: skip
        await session.delete(lead)
