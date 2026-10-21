"""Audit trail API: Owners and Admins of the business only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from agentree.audit import service
from agentree.audit.schemas import AuditActorOut, AuditEventOut, AuditPageOut
from agentree.identity.service import emails_for
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["audit"])


@router.get("/audit-events")
async def list_audit_events(
    member: Member,
    request: Request,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE)] = 50,
) -> AuditPageOut:
    member.require(Role.ADMIN)
    factory = request.app.state.session_factory
    # One extra row tells whether an older page exists.
    rows = await service.list_events(factory, member.tenant, before=before, limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    user_ids = {e.actor_user_id for e in page if e.actor_user_id}
    user_ids |= {UUID(e.target_id) for e in page if e.target_type == "user" and e.target_id}
    emails = await emails_for(factory, user_ids)
    return AuditPageOut(
        events=[
            AuditEventOut(
                id=e.id, action=e.action,
                actor=AuditActorOut(user_id=e.actor_user_id, email=emails.get(e.actor_user_id))
                if e.actor_user_id else None,
                target_type=e.target_type, target_id=e.target_id,
                target_email=emails.get(UUID(e.target_id))
                if e.target_type == "user" and e.target_id else None,
                details=e.details, created_at=e.created_at,
            )
            for e in page
        ],
        next_before=page[-1].id if more and page else None,
    )  # fmt: skip
