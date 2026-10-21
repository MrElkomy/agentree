"""Audit trail: who did what to which object in a business.

`record` writes inside the caller's `tenant_session`, so the event commits or rolls back with
the change it describes. Details are allowlisted scalars only: never passwords, API keys,
tokens, message content or other secrets. Reads are for Owners and Admins (enforced by the API).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.audit.models import AuditEvent
from agentree.core.ids import uuid7
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

MAX_PAGE = 100


class AuditAction(StrEnum):
    BUSINESS_CREATED = "business.created"
    INVITATION_CREATED = "invitation.created"
    INVITATION_REVOKED = "invitation.revoked"
    MEMBER_JOINED = "member.joined"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"
    MEMBER_LEFT = "member.left"
    PROVIDER_KEY_SAVED = "provider_key.saved"
    PROVIDER_KEY_REMOVED = "provider_key.removed"
    LEAD_CREATED = "lead.created"
    LEAD_UPDATED = "lead.updated"  # the visitor re-submitted their details
    LEAD_STATUS_CHANGED = "lead.status_changed"
    LEAD_NOTES_UPDATED = "lead.notes_updated"
    LEAD_DELETED = "lead.deleted"
    FOLLOW_UP_CREATED = "follow_up.created"
    FOLLOW_UP_UPDATED = "follow_up.updated"
    CONVERSATION_HANDOFF_REQUESTED = "conversation.handoff_requested"
    CONVERSATION_HANDOFF_CANCELED = "conversation.handoff_canceled"
    CONVERSATION_TAKEN_OVER = "conversation.taken_over"
    CONVERSATION_ASSIGNED = "conversation.assigned"
    CONVERSATION_RELEASED = "conversation.released"
    CONVERSATION_RESOLVED = "conversation.resolved"
    AGENT_CONFIG_UPDATED = "agent.config_updated"
    AGENT_HANDOFF = "agent.handoff"
    CUSTOMER_VERIFIED = "customer.verified"
    CUSTOMER_DELETED = "customer.deleted"
    CUSTOMER_MEMORY_UPDATED = "customer.memory_updated"
    CUSTOMER_MEMORY_DELETED = "customer.memory_deleted"
    KNOWLEDGE_FILE_UPLOADED = "knowledge_file.uploaded"
    KNOWLEDGE_FILE_DELETED = "knowledge_file.deleted"


# Detail keys that may be stored. Anything else is dropped, so a careless caller cannot leak a
# secret into the trail by passing a whole object.
ALLOWED_DETAILS = frozenset(
    {
        "email",
        "role",
        "from_role",
        "to_role",
        "slot",
        "provider",
        "model",
        "replaced",
        "verified",
        "channel",
        "agent",
        "from_status",
        "to_status",
        "kind",
        "due_at",
        "assigned",
        "reason",
        "from_agent",
        "to_agent",
        "enabled",
        "public",
        "version",
        "resolved_by",
        "category",
    }
)
MAX_DETAIL_LEN = 200


def _clean(details: Mapping[str, Any] | None) -> dict[str, str | int | bool]:
    out: dict[str, str | int | bool] = {}
    for key, value in (details or {}).items():
        if key not in ALLOWED_DETAILS or value is None:
            continue
        if isinstance(value, bool | int):
            out[key] = value
        else:
            out[key] = str(value)[:MAX_DETAIL_LEN]
    return out


async def record(
    session: AsyncSession, ctx: TenantContext, *, action: AuditAction, actor_user_id: UUID | None,
    target_type: str, target_id: UUID | str | None = None, details: Mapping[str, Any] | None = None,
) -> None:  # fmt: skip
    session.add(
        AuditEvent(
            id=uuid7(), business_id=ctx.business_id, actor_user_id=actor_user_id,
            action=action, target_type=target_type,
            target_id=str(target_id) if target_id is not None else None, details=_clean(details),
        )
    )  # fmt: skip


@dataclass(frozen=True)
class AuditEntry:
    id: UUID
    action: str
    actor_user_id: UUID | None
    target_type: str
    target_id: str | None
    details: dict[str, Any]
    created_at: datetime


async def list_events(
    factory: Factory, ctx: TenantContext, *, before: UUID | None = None, limit: int = 50
) -> list[AuditEntry]:
    """Newest first. Keyset pagination: pass the last id of a page as `before`."""
    limit = max(1, min(limit, MAX_PAGE))
    query = select(AuditEvent).where(AuditEvent.business_id == ctx.business_id)
    if before is not None:
        query = query.where(AuditEvent.id < before)
    async with tenant_session(factory, ctx) as session:
        rows = (await session.execute(query.order_by(AuditEvent.id.desc()).limit(limit))).scalars()
        return [
            AuditEntry(e.id, e.action, e.actor_user_id, e.target_type, e.target_id,
                       dict(e.details), e.created_at)
            for e in rows
        ]  # fmt: skip
