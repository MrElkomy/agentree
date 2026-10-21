"""Knowledge base endpoints. Members draft; admins publish, unpublish and delete."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from agentree.agents.registry import ROLES
from agentree.knowledge import service
from agentree.knowledge.schemas import EntryCreateIn, EntryOut, EntryUpdateIn
from agentree.knowledge.service import Status
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/knowledge", tags=["knowledge"])


def _out(e: service.EntryInfo) -> EntryOut:
    return EntryOut(id=e.id, title=e.title, body=e.body, status=e.status,
                    published_at=e.published_at, updated_at=e.updated_at,
                    agent_roles=list(e.agent_roles), source_file_id=e.source_file_id)  # fmt: skip


def _404() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


def _check_roles(roles: list[str] | None) -> None:
    if roles is not None and any(r not in ROLES for r in roles):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_agent_roles")


@router.get("")
async def list_entries(member: Member, request: Request) -> list[EntryOut]:
    return [
        _out(e)
        for e in await service.list_entries(request.app.state.session_factory, member.tenant)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_entry(body: EntryCreateIn, member: Member, request: Request) -> EntryOut:
    _check_roles(body.agent_roles)
    e = await service.create_entry(
        request.app.state.session_factory, member.tenant, title=body.title, body=body.body,
        actor_id=member.user.id, agent_roles=body.agent_roles,
    )  # fmt: skip
    return _out(e)


@router.get("/{entry_id}")
async def get_entry(entry_id: UUID, member: Member, request: Request) -> EntryOut:
    try:
        return _out(
            await service.get_entry(request.app.state.session_factory, member.tenant, entry_id)
        )
    except service.NotFoundError:
        raise _404() from None


@router.patch("/{entry_id}")
async def update_entry(
    entry_id: UUID, body: EntryUpdateIn, member: Member, request: Request
) -> EntryOut:
    _check_roles(body.agent_roles)
    try:
        e = await service.update_entry(
            request.app.state.session_factory,
            member.tenant,
            entry_id,
            title=body.title,
            body=body.body,
            agent_roles=body.agent_roles,
        )
    except service.NotFoundError:
        raise _404() from None
    return _out(e)


async def _set(entry_id: UUID, member: Member, request: Request, st: Status) -> EntryOut:
    member.require(Role.ADMIN)
    try:
        return _out(
            await service.set_status(request.app.state.session_factory, member.tenant, entry_id, st)
        )
    except service.NotFoundError:
        raise _404() from None


@router.post("/{entry_id}/publish")
async def publish(entry_id: UUID, member: Member, request: Request) -> EntryOut:
    return await _set(entry_id, member, request, Status.PUBLISHED)


@router.post("/{entry_id}/unpublish")
async def unpublish(entry_id: UUID, member: Member, request: Request) -> EntryOut:
    return await _set(entry_id, member, request, Status.DRAFT)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_entry(request.app.state.session_factory, member.tenant, entry_id)
    except service.NotFoundError:
        raise _404() from None
