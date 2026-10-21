"""Business, membership and invitation endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from agentree.core import ratelimit
from agentree.identity.deps import VerifiedUser
from agentree.tenancy import service
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role
from agentree.tenancy.schemas import (
    AcceptInvitationIn,
    BusinessCreateIn,
    BusinessOut,
    InvitationCreateIn,
    InvitationOut,
    MemberOut,
    RoleChangeIn,
)

router = APIRouter(prefix="/api", tags=["businesses"])


def _factory(request: Request) -> service.Factory:
    return request.app.state.session_factory  # type: ignore[no-any-return]


@router.post("/businesses", status_code=status.HTTP_201_CREATED)
async def create_business(
    body: BusinessCreateIn, user: VerifiedUser, request: Request
) -> BusinessOut:
    if not await ratelimit.hit(
        _factory(request), ratelimit.key_for("create-business:user", str(user.id)),
        limit=10, window_seconds=86400,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
    try:
        ctx = await service.create_business(
            _factory(request), name=body.name, slug=body.slug, owner_user_id=user.id
        )
    except service.InvalidSlugError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_slug") from None
    except service.SlugTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug_taken") from None
    return BusinessOut(id=ctx.business_id, name=body.name.strip(), slug=body.slug, role=Role.OWNER)


@router.get("/businesses")
async def list_businesses(user: VerifiedUser, request: Request) -> list[BusinessOut]:
    """Business switcher: every business the user belongs to, with their role."""
    rows = await service.list_user_businesses(_factory(request), user.id)
    return [BusinessOut(id=r.business_id, name=r.name, slug=r.slug, role=r.role) for r in rows]


@router.get("/businesses/{business_id}")
async def get_business(member: Member, request: Request) -> BusinessOut:
    b = await service.get_business(_factory(request), member.tenant)
    return BusinessOut(id=b.id, name=b.name, slug=b.slug, role=member.role)


@router.get("/businesses/{business_id}/members")
async def list_members(member: Member, request: Request) -> list[MemberOut]:
    rows = await service.list_members(_factory(request), member.tenant)
    return [MemberOut(user_id=r.user_id, email=r.email, role=r.role) for r in rows]


@router.patch("/businesses/{business_id}/members/{user_id}")
async def change_member_role(
    user_id: UUID, body: RoleChangeIn, member: Member, request: Request
) -> MemberOut:
    member.require(Role.ADMIN)
    try:
        await service.change_member_role(
            _factory(request), member.tenant, actor_id=member.user.id, actor_role=member.role,
            target_user_id=user_id, new_role=body.role,
        )  # fmt: skip
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    except service.ForbiddenError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_role") from None
    except service.LastOwnerError:
        raise HTTPException(status.HTTP_409_CONFLICT, "last_owner") from None
    members = await service.list_members(_factory(request), member.tenant)
    m = next(x for x in members if x.user_id == user_id)
    return MemberOut(user_id=m.user_id, email=m.email, role=m.role)


@router.delete(
    "/businesses/{business_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(user_id: UUID, member: Member, request: Request) -> None:
    try:
        await service.remove_member(
            _factory(request), member.tenant, actor_id=member.user.id, actor_role=member.role,
            target_user_id=user_id,
        )  # fmt: skip
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    except service.ForbiddenError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_role") from None
    except service.LastOwnerError:
        raise HTTPException(status.HTTP_409_CONFLICT, "last_owner") from None


@router.post("/businesses/{business_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: InvitationCreateIn, member: Member, request: Request
) -> InvitationOut:
    member.require(Role.ADMIN)
    if not await ratelimit.hit(
        _factory(request), ratelimit.key_for("invite:user", str(member.user.id)),
        limit=50, window_seconds=86400,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
    st = request.app.state
    try:
        inv = await service.create_invitation(
            st.session_factory, st.settings, st.mailer, member.tenant,
            actor_id=member.user.id, actor_role=member.role, email=body.email, role=body.role,
        )  # fmt: skip
    except service.ForbiddenError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_role") from None
    return InvitationOut(
        id=inv.id, email=inv.email, role=inv.role, expires_at=inv.expires_at,
        email_sent=inv.email_sent,
    )  # fmt: skip


@router.get("/businesses/{business_id}/invitations")
async def list_invitations(member: Member, request: Request) -> list[InvitationOut]:
    member.require(Role.ADMIN)
    rows = await service.list_invitations(_factory(request), member.tenant)
    return [
        InvitationOut(id=i.id, email=i.email, role=i.role, expires_at=i.expires_at) for i in rows
    ]


@router.delete(
    "/businesses/{business_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invitation(invitation_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.revoke_invitation(
            _factory(request), member.tenant, invitation_id, actor_id=member.user.id
        )
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None


@router.post("/invitations/accept")
async def accept_invitation(
    body: AcceptInvitationIn, user: VerifiedUser, request: Request
) -> BusinessOut:
    if not await ratelimit.hit(
        _factory(request), ratelimit.key_for("accept-invite:user", str(user.id)),
        limit=20, window_seconds=3600,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
    business_id = await service.accept_invitation(
        _factory(request), raw_token=body.token, user_id=user.id
    )
    if business_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_invitation")
    summaries = await service.list_user_businesses(_factory(request), user.id)
    s = next(x for x in summaries if x.business_id == business_id)
    return BusinessOut(id=s.business_id, name=s.name, slug=s.slug, role=s.role)
