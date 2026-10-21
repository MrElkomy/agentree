"""Web Push for Owners and Admins: device opt-in, and alerts that never carry customer data.

Alerts (new lead, visitor waiting for a person, AI key down) go to every device an Owner or
Admin of the business enabled. Roles are checked when sending, so a demoted or removed member
stops receiving them. Email remains the channel of record; push is best effort and never fails
the caller.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.ids import uuid7
from agentree.core.webpush import (
    Outcome,
    PushMessage,
    PushSender,
    Subscription,
    validate_subscription,
)
from agentree.notifications.models import PushSubscription
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

MAX_DEVICES_PER_USER = 10  # per business; the oldest is dropped beyond this


async def subscribe(
    factory: Factory, ctx: TenantContext, *, user_id: UUID, endpoint: str, p256dh: str, auth: str
) -> None:
    """Store this device for the user (raises webpush.InvalidSubscriptionError)."""
    sub = validate_subscription(endpoint, p256dh, auth)
    async with tenant_session(factory, ctx) as session:
        # A browser profile reused by another member moves the device to them.
        await session.execute(
            insert(PushSubscription)
            .values(id=uuid7(), business_id=ctx.business_id, user_id=user_id,
                    endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth)
            .on_conflict_do_update(
                index_elements=["business_id", "endpoint"],
                set_={"user_id": user_id, "p256dh": sub.p256dh, "auth": sub.auth},
            )
        )  # fmt: skip
        ids = (
            await session.execute(
                select(PushSubscription.id)
                .where(PushSubscription.business_id == ctx.business_id,
                       PushSubscription.user_id == user_id)
                .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc())
            )
        ).scalars().all()  # fmt: skip
        if len(ids) > MAX_DEVICES_PER_USER:
            await session.execute(
                delete(PushSubscription).where(
                    PushSubscription.business_id == ctx.business_id,
                    PushSubscription.id.in_(ids[MAX_DEVICES_PER_USER:]),
                )
            )


async def unsubscribe(
    factory: Factory, ctx: TenantContext, *, user_id: UUID, endpoint: str
) -> None:
    """Forget this device for the user (no error if it was not stored)."""
    async with tenant_session(factory, ctx) as session:
        await session.execute(
            delete(PushSubscription).where(
                PushSubscription.business_id == ctx.business_id,
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == endpoint,
            )
        )


async def is_subscribed(
    factory: Factory, ctx: TenantContext, *, user_id: UUID, endpoint: str
) -> bool:
    async with tenant_session(factory, ctx) as session:
        found = await session.scalar(
            select(PushSubscription.id).where(
                PushSubscription.business_id == ctx.business_id,
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == endpoint,
            )
        )
    return found is not None


async def device_count(factory: Factory, ctx: TenantContext, *, user_id: UUID) -> int:
    async with tenant_session(factory, ctx) as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(PushSubscription)
                .where(
                    PushSubscription.business_id == ctx.business_id,
                    PushSubscription.user_id == user_id,
                )
            )
            or 0
        )


async def _deliver(
    factory: Factory, sender: PushSender, ctx: TenantContext, user_ids: set[UUID],
    message: PushMessage,
) -> int:  # fmt: skip
    if sender.public_key is None or not user_ids:
        return 0
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(PushSubscription.id, PushSubscription.endpoint, PushSubscription.p256dh,
                       PushSubscription.auth)
                .where(PushSubscription.business_id == ctx.business_id,
                       PushSubscription.user_id.in_(user_ids))
            )
        ).all()  # fmt: skip

    async def one(endpoint: str, p256dh: str, auth: str) -> Outcome:
        try:
            return await sender.send(Subscription(endpoint, p256dh, auth), message)
        except Exception:  # best effort: one bad device never blocks the others
            logger.warning("web push delivery failed", extra={"reason": "error"}, exc_info=True)
            return Outcome.FAILED

    outcomes = await asyncio.gather(*(one(r.endpoint, r.p256dh, r.auth) for r in rows))
    sent = [r.id for r, o in zip(rows, outcomes, strict=True) if o is Outcome.SENT]
    gone = [r.id for r, o in zip(rows, outcomes, strict=True) if o is Outcome.GONE]
    if sent or gone:
        async with tenant_session(factory, ctx) as session:
            if gone:  # the browser unsubscribed or the subscription expired
                await session.execute(
                    delete(PushSubscription).where(
                        PushSubscription.business_id == ctx.business_id,
                        PushSubscription.id.in_(gone),
                    )
                )
            for sub_id in sent:
                row = await session.get(PushSubscription, sub_id)
                if row is not None:
                    row.last_success_at = datetime.now(UTC)
    logger.info("web push sent", extra={"business_id": str(ctx.business_id), "tag": message.tag,
                                        "sent": len(sent), "gone": len(gone),
                                        "devices": len(rows)})  # fmt: skip
    return len(sent)


async def push_to_admins(
    factory: Factory, sender: PushSender, ctx: TenantContext, message: PushMessage
) -> int:
    """Alert every opted-in device of the business's Owners and Admins. Never raises."""
    try:
        members = await tenancy.list_members(factory, ctx)
        admins = {m.user_id for m in members if m.role in (Role.OWNER, Role.ADMIN)}
        return await _deliver(factory, sender, ctx, admins, message)
    except Exception:
        logger.warning("web push alert failed", extra={"tag": message.tag}, exc_info=True)
        return 0


async def send_test(
    factory: Factory, sender: PushSender, ctx: TenantContext, *, user_id: UUID, business: str
) -> int:
    message = PushMessage(
        title="Notifications are on",
        body=f"You'll get alerts for {business} on this device.",
        url=f"/b/{ctx.business_id}/notifications",
        tag="agentree-test",
    )
    return await _deliver(factory, sender, ctx, {user_id}, message)
