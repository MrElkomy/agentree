"""Human inbox for business members: see public conversations, take over, reply, hand back."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from agentree.agents import inbox
from agentree.agents.schemas import (
    InboxAssignIn,
    InboxConversationOut,
    InboxItemOut,
    InboxMessageOut,
    InboxPageOut,
    InboxReplyIn,
)
from agentree.tenancy.deps import Member

router = APIRouter(prefix="/api/businesses/{business_id}/inbox", tags=["inbox"])

Status = Literal["open", "needs_human", "human_active", "resolved"]


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


def _wrong_state() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "conversation_state")


@router.get("")
async def list_inbox(
    member: Member,
    request: Request,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=inbox.MAX_PAGE)] = 50,
) -> InboxPageOut:
    factory = request.app.state.session_factory
    rows = await inbox.list_inbox(factory, member.tenant, status=status_filter, before=before,
                                  limit=limit + 1)  # fmt: skip
    page, more = rows[:limit], len(rows) > limit
    return InboxPageOut(
        items=[InboxItemOut(**asdict(r)) for r in page],
        counts=await inbox.counts(factory, member.tenant),
        next_before=page[-1].last_message_at if more and page else None,
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, member: Member, request: Request
) -> InboxConversationOut:
    try:
        item, messages = await inbox.get_conversation(
            request.app.state.session_factory, member.tenant, conversation_id
        )
    except inbox.NotFoundError:
        raise _not_found() from None
    return InboxConversationOut(
        conversation=InboxItemOut(**asdict(item)),
        messages=[InboxMessageOut(**asdict(m)) for m in messages],
    )


@router.post("/{conversation_id}/take-over", status_code=status.HTTP_204_NO_CONTENT)
async def take_over(conversation_id: UUID, member: Member, request: Request) -> None:
    try:
        await inbox.take_over(request.app.state.session_factory, member.tenant, conversation_id,
                              actor_id=member.user.id)  # fmt: skip
    except inbox.NotFoundError:
        raise _not_found() from None


@router.post("/{conversation_id}/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign(
    conversation_id: UUID, body: InboxAssignIn, member: Member, request: Request
) -> None:
    try:
        await inbox.assign(
            request.app.state.session_factory,
            member.tenant,
            conversation_id,
            actor_id=member.user.id,
            assignee_user_id=body.assignee_user_id,
        )
    except inbox.NotFoundError:
        raise _not_found() from None
    except inbox.InvalidAssigneeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_assignee") from None


@router.post("/{conversation_id}/reply", status_code=status.HTTP_201_CREATED)
async def reply(
    conversation_id: UUID, body: InboxReplyIn, member: Member, request: Request
) -> InboxMessageOut:
    try:
        msg = await inbox.reply(request.app.state.session_factory, member.tenant, conversation_id,
                                actor_id=member.user.id, content=body.content)  # fmt: skip
    except inbox.NotFoundError:
        raise _not_found() from None
    except inbox.InvalidStateError:
        raise _wrong_state() from None
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_content") from None
    return InboxMessageOut(**asdict(msg))


@router.post("/{conversation_id}/release", status_code=status.HTTP_204_NO_CONTENT)
async def release(conversation_id: UUID, member: Member, request: Request) -> None:
    try:
        await inbox.release(request.app.state.session_factory, member.tenant, conversation_id,
                            actor_id=member.user.id)  # fmt: skip
    except inbox.NotFoundError:
        raise _not_found() from None
    except inbox.InvalidStateError:
        raise _wrong_state() from None


@router.post("/{conversation_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve(conversation_id: UUID, member: Member, request: Request) -> None:
    try:
        await inbox.resolve(request.app.state.session_factory, member.tenant, conversation_id,
                            actor_id=member.user.id)  # fmt: skip
    except inbox.NotFoundError:
        raise _not_found() from None
