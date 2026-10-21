"""Web Push opt-in for Owners and Admins (one subscription per browser/device)."""

from fastapi import APIRouter, HTTPException, Request, status

from agentree.core import ratelimit
from agentree.core.webpush import InvalidSubscriptionError
from agentree.notifications import service
from agentree.notifications.schemas import (
    PushConfigOut,
    PushDeviceOut,
    PushSubscriptionIn,
    PushTestOut,
    PushUnsubscribeIn,
)
from agentree.tenancy import service as tenancy
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(
    prefix="/api/businesses/{business_id}/notifications/push", tags=["notifications"]
)


async def _limit(request: Request, member: Member, name: str, limit: int) -> None:
    key = ratelimit.key_for(f"push-{name}:user", f"{member.tenant.business_id}:{member.user.id}")
    if not await ratelimit.hit(request.app.state.session_factory, key, limit=limit,
                               window_seconds=3600):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")


@router.get("")
async def push_config(member: Member, request: Request) -> PushConfigOut:
    st = request.app.state
    devices = await service.device_count(st.session_factory, member.tenant, user_id=member.user.id)
    key = st.push.public_key
    return PushConfigOut(available=key is not None, public_key=key, devices=devices)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(body: PushSubscriptionIn, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)  # alerts go to Owners and Admins
    if request.app.state.push.public_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "push_unavailable")
    await _limit(request, member, "subscribe", 20)
    try:
        await service.subscribe(
            request.app.state.session_factory, member.tenant, user_id=member.user.id,
            endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth,
        )  # fmt: skip
    except InvalidSubscriptionError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_push_subscription"
        ) from None


@router.post("/subscriptions/check")
async def check(body: PushUnsubscribeIn, member: Member, request: Request) -> PushDeviceOut:
    """Is this device (its endpoint, sent in the body to keep it out of URLs) subscribed?"""
    subscribed = await service.is_subscribed(
        request.app.state.session_factory, member.tenant, user_id=member.user.id,
        endpoint=body.endpoint,
    )  # fmt: skip
    return PushDeviceOut(subscribed=subscribed)


@router.post("/subscriptions/remove", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(body: PushUnsubscribeIn, member: Member, request: Request) -> None:
    await service.unsubscribe(request.app.state.session_factory, member.tenant,
                              user_id=member.user.id, endpoint=body.endpoint)  # fmt: skip


@router.post("/test")
async def send_test(member: Member, request: Request) -> PushTestOut:
    member.require(Role.ADMIN)
    await _limit(request, member, "test", 10)
    st = request.app.state
    business = await tenancy.get_business(st.session_factory, member.tenant)
    sent = await service.send_test(st.session_factory, st.push, member.tenant,
                                   user_id=member.user.id, business=business.name)  # fmt: skip
    return PushTestOut(sent=sent)
