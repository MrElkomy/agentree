"""Alert Owners and Admins when an AI key goes down (its circuit breaker opened).

The worker claims each newly opened breaker once (SECURITY DEFINER `agentree_claim_provider_
outages`, migration 0014); closing the breaker clears the mark, so the next outage alerts
again. A flapping key alerts at most once per ALERT_WINDOW per business and slot. Emails and
pushes name the business, the slot and the kind of error: never keys or conversation content.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core import ratelimit
from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailAction, EmailContent
from agentree.core.webpush import PushMessage, PushSender
from agentree.notifications import service as notifications
from agentree.providers.service import CredentialInfo, Health, Slot, list_credentials
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

BATCH = 100
ALERT_WINDOW_SECONDS = 6 * 3600

REASON = {
    "auth": "the provider rejected the key",
    "quota": "the provider account is out of credit or quota",
    "rate_limit": "the provider is rate-limiting the key",
    "unavailable": "the provider is having an outage",
    "transient": "the provider could not be reached",
}


async def alert_provider_outages(
    factory: Factory, settings: Settings, mailer: EmailSender, push: PushSender,
    *, now: datetime | None = None,
) -> int:  # fmt: skip
    """One pass: alert every newly opened breaker. Returns how many outages were alerted."""
    async with factory() as session, session.begin():
        claimed = (
            await session.execute(
                text("SELECT business_id, slot FROM agentree_claim_provider_outages(:now, :n)"),
                {"now": now or datetime.now(UTC), "n": BATCH},
            )
        ).all()
    alerted = 0
    for business_id, slot in claimed:
        ctx = TenantContext(business_id, TenantSource.JOB)
        key = ratelimit.key_for("provider-outage-alert", f"{business_id}:{slot}")
        if not await ratelimit.hit(factory, key, limit=1, window_seconds=ALERT_WINDOW_SECONDS):
            continue
        try:
            if await _alert(factory, settings, mailer, push, ctx, Slot(slot)):
                alerted += 1
        except Exception as exc:  # one business never blocks the others
            logger.error("provider outage alert failed", extra={"error_type": type(exc).__name__})
    return alerted


async def _alert(
    factory: Factory, settings: Settings, mailer: EmailSender, push: PushSender,
    ctx: TenantContext, slot: Slot,
) -> bool:  # fmt: skip
    keys = await list_credentials(factory, ctx)
    down = next((c for c in keys if c.slot == slot), None)
    if down is None or down.health not in (Health.DOWN, Health.RECOVERING):
        return False  # removed, replaced or already recovered
    covered = any(c.slot != slot and c.health in (Health.HEALTHY, Health.DEGRADED) for c in keys)
    business = await tenancy.get_business(factory, ctx)
    members = await tenancy.list_members(factory, ctx)
    url = f"{settings.public_base_url}/b/{ctx.business_id}/ai-providers"
    for m in members:
        if m.role in (Role.OWNER, Role.ADMIN):
            await send_safely(mailer, _email(m.email, business.name, down, covered, url),
                              kind="provider_outage")  # fmt: skip
    await notifications.push_to_admins(factory, push, ctx, PushMessage(
        title=f"{business.name}: {slot} AI key is down",
        body="Your backup key is answering." if covered
        else "Your agents can't answer until it recovers. Tap to check.",
        url=f"/b/{ctx.business_id}/ai-providers", tag=f"provider-{ctx.business_id}-{slot}",
    ))  # fmt: skip
    logger.warning(
        "provider outage alerted",
        extra={"business_id": str(ctx.business_id), "slot": slot,
               "error_kind": down.last_error_kind, "covered": covered},
    )  # fmt: skip
    return True


def _email(to: str, business: str, key: CredentialInfo, covered: bool, url: str) -> OutgoingEmail:
    why = REASON.get(key.last_error_kind or "", "it keeps failing")
    impact = (
        "Your backup key is answering in the meantime, and Agentree switches back automatically "
        "when this key recovers."
        if covered
        else "Your agents can't answer customers until it recovers. Agentree keeps testing it "
        "automatically. Adding a backup key keeps your agents answering during outages."
    )
    return branded_email(
        to,
        EmailContent(
            subject=f"{business}: your {key.slot} AI key is down",
            preheader=f"Your {key.slot} AI key stopped working: {why}.",
            heading=f"Your {key.slot} AI key is down",
            paragraphs=[f"Agentree paused your {key.slot} AI key ({key.provider}) for "
                        f"{business} because {why}.", impact],
            action=EmailAction("Check AI Providers", url),
            footnote="If the key was revoked or ran out of credit, replace it or top up your "
            "provider account, then press Test key.",
            reason=f"You're receiving this because you're an owner or admin of {business} "
            "on Agentree.",
        ),
    )  # fmt: skip


async def run_outage_alert_loop(
    factory: Factory, settings: Settings, mailer: EmailSender, push: PushSender, *,
    interval_seconds: float, stop: asyncio.Event,
) -> None:  # fmt: skip
    """Alert new outages every `interval_seconds` until `stop` is set."""
    while not stop.is_set():
        try:
            await alert_provider_outages(factory, settings, mailer, push)
        except Exception as exc:  # keep the worker alive; next run retries
            logger.error("outage alert pass failed", extra={"error_type": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
