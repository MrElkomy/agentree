"""Leads in the dashboard: every member can follow up; Admins and Owners can delete."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from agentree.agents import service as agents
from agentree.leads import service
from agentree.leads.schemas import (
    LeadDetailOut,
    LeadMessageOut,
    LeadOut,
    LeadPageOut,
    LeadUpdateIn,
)
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/leads", tags=["leads"])


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


@router.get("")
async def list_leads(
    member: Member,
    request: Request,
    status_filter: Annotated[service.LeadStatus | None, Query(alias="status")] = None,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE)] = 50,
) -> LeadPageOut:
    rows = await service.list_leads(
        request.app.state.session_factory, member.tenant, status=status_filter, before=before,
        limit=limit + 1,
    )  # fmt: skip
    page, more = rows[:limit], len(rows) > limit
    return LeadPageOut(
        leads=[LeadOut(**asdict(r)) for r in page],
        next_before=page[-1].id if more and page else None,
    )


@router.get("/{lead_id}")
async def get_lead(lead_id: UUID, member: Member, request: Request) -> LeadDetailOut:
    factory = request.app.state.session_factory
    try:
        lead = await service.get_lead(factory, member.tenant, lead_id)
    except service.NotFoundError:
        raise _not_found() from None
    messages: list[LeadMessageOut] = []
    if lead.conversation_id is not None:
        try:
            rows = await agents.list_messages(factory, member.tenant, lead.conversation_id)
            messages = [LeadMessageOut(role=m.role, content=m.content, created_at=m.created_at)
                        for m in rows]  # fmt: skip
        except agents.NotFoundError:
            pass  # deleted between the two reads
    return LeadDetailOut(**asdict(lead), messages=messages)


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: UUID, body: LeadUpdateIn, member: Member, request: Request
) -> LeadOut:
    try:
        lead = await service.update_lead(
            request.app.state.session_factory, member.tenant, lead_id, actor_id=member.user.id,
            status=body.status, notes=body.notes,
        )  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
    return LeadOut(**asdict(lead))


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_lead(
            request.app.state.session_factory, member.tenant, lead_id, actor_id=member.user.id
        )
    except service.NotFoundError:
        raise _not_found() from None
