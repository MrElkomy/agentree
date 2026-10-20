"""Tenancy service: businesses, memberships and invitations (public interface of the module)."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, send_safely
from agentree.core.ids import uuid7
from agentree.core.tokens import hash_token, new_token
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from agentree.tenancy.models import Business, Invitation, Membership
from agentree.tenancy.roles import Role, can_grant, can_manage

Factory = async_sessionmaker[AsyncSession]

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
# Public pages live at the web root (`/{slug}`), so a slug must never shadow a route of the
# web app or a well-known path. Checked only when a business is created; existing slugs are
# unaffected.
RESERVED_SLUGS = frozenset(
    {"api", "app", "admin", "login", "logout", "signup", "register", "pricing", "docs", "help",
     "support", "status", "public", "hooks", "static", "assets", "widget", "embed", "www",
     "verify-email", "reset-password", "forgot-password", "invite", "invitations",
     "dashboard", "settings", "b", "w", "p", "_next", "favicon.ico", "robots.txt",
     "sitemap.xml", "health", "healthz", "readyz", "about", "terms", "privacy", "auth",
     "account", "fonts"}
)  # fmt: skip


class InvalidSlugError(ValueError):
    pass


class SlugTakenError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class LastOwnerError(Exception):
    pass


@dataclass(frozen=True)
class BusinessSummary:
    business_id: UUID
    name: str
    slug: str
    role: Role


@dataclass(frozen=True)
class MemberInfo:
    user_id: UUID
    email: str
    role: Role


@dataclass(frozen=True)
class InvitationInfo:
    id: UUID
    email: str
    role: Role
    expires_at: datetime
    email_sent: bool | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug) or "--" in slug or slug in RESERVED_SLUGS:
        raise InvalidSlugError(slug)
    return slug


# --- businesses -------------------------------------------------------------------------


async def create_business(
    factory: Factory, *, name: str, slug: str, owner_user_id: UUID | None = None
) -> TenantContext:
    """Provision a new tenant with its first Owner. Caller must authorize the creator."""
    validate_slug(slug)
    async with factory() as session:
        taken = (
            await session.execute(text("SELECT agentree_resolve_business_slug(:s)"), {"s": slug})
        ).scalar()
    if taken:
        raise SlugTakenError(slug)
    ctx = TenantContext(uuid7(), TenantSource.PROVISIONING)
    async with tenant_session(factory, ctx) as session:
        session.add(Business(id=ctx.business_id, name=name.strip(), slug=slug))
        if owner_user_id is not None:
            await session.flush()
            session.add(
                Membership(business_id=ctx.business_id, user_id=owner_user_id, role=Role.OWNER)
            )
    return ctx


async def get_business(factory: Factory, ctx: TenantContext) -> Business:
    async with tenant_session(factory, ctx) as session:
        # Explicit filter as defense in depth on top of RLS.
        return (
            await session.execute(select(Business).where(Business.id == ctx.business_id))
        ).scalar_one()


async def resolve_public_business(factory: Factory, slug: str) -> TenantContext | None:
    """Map a public page slug to a public tenant context (no internal privileges)."""
    async with factory() as session:
        business_id: UUID | None = (
            await session.execute(
                text("SELECT agentree_resolve_business_slug(:slug)"), {"slug": slug}
            )
        ).scalar()
    return TenantContext(business_id, TenantSource.PUBLIC) if business_id else None


# --- memberships ------------------------------------------------------------------------


async def membership_role(factory: Factory, user_id: UUID, business_id: UUID) -> Role | None:
    """The user's role in a business, or None. Used to authorize before a context exists."""
    async with factory() as session:
        role = (
            await session.execute(
                text("SELECT agentree_membership_role(:u, :b)"), {"u": user_id, "b": business_id}
            )
        ).scalar()
    return Role(role) if role else None


async def list_user_businesses(factory: Factory, user_id: UUID) -> list[BusinessSummary]:
    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT business_id, name, slug, role FROM agentree_user_businesses(:u)"),
                {"u": user_id},
            )
        ).all()
    return [BusinessSummary(r[0], r[1], r[2], Role(r[3])) for r in rows]


async def list_members(factory: Factory, ctx: TenantContext) -> list[MemberInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT m.user_id, u.email_normalized, m.role FROM business_memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE m.business_id = :b "
                    "ORDER BY m.created_at"
                ),
                {"b": ctx.business_id},
            )
        ).all()
    return [MemberInfo(r[0], r[1], Role(r[2])) for r in rows]


async def _lock_memberships(session: AsyncSession, ctx: TenantContext, actor_id: UUID) -> Role:
    """Serialize membership changes per business and return the actor's *current* role.

    Locking the business row first gives every membership mutation the same lock order
    (no deadlocks) and re-reading the actor's role under the lock closes the gap between
    request authorization and the write (a just-demoted or removed actor is refused).
    """
    await session.execute(
        select(Business.id).where(Business.id == ctx.business_id).with_for_update()
    )
    role = (
        await session.execute(
            select(Membership.role).where(
                Membership.business_id == ctx.business_id, Membership.user_id == actor_id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise ForbiddenError
    return Role(role)


async def _membership(session: AsyncSession, ctx: TenantContext, user_id: UUID) -> Membership:
    m = (
        await session.execute(
            select(Membership).where(
                Membership.business_id == ctx.business_id, Membership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise NotFoundError
    return m


async def _ensure_other_owner(session: AsyncSession, ctx: TenantContext, user_id: UUID) -> None:
    owners = (
        (
            await session.execute(
                select(Membership.user_id).where(
                    Membership.business_id == ctx.business_id, Membership.role == Role.OWNER
                )
            )
        )
        .scalars()
        .all()
    )
    if [o for o in owners if o != user_id] == []:
        raise LastOwnerError


async def change_member_role(
    factory: Factory, ctx: TenantContext, *, actor_id: UUID, actor_role: Role,
    target_user_id: UUID, new_role: Role,
) -> None:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        actor_role = await _lock_memberships(session, ctx, actor_id)
        target = await _membership(session, ctx, target_user_id)
        current = Role(target.role)
        if not (can_manage(actor_role, current) and can_grant(actor_role, new_role)):
            raise ForbiddenError
        if current is Role.OWNER and new_role is not Role.OWNER:
            await _ensure_other_owner(session, ctx, target_user_id)
        target.role = new_role


async def remove_member(
    factory: Factory, ctx: TenantContext, *, actor_id: UUID, actor_role: Role, target_user_id: UUID
) -> None:
    async with tenant_session(factory, ctx) as session:
        actor_role = await _lock_memberships(session, ctx, actor_id)
        target = await _membership(session, ctx, target_user_id)
        current = Role(target.role)
        if target_user_id != actor_id and not can_manage(actor_role, current):
            raise ForbiddenError
        if current is Role.OWNER:
            await _ensure_other_owner(session, ctx, target_user_id)
        await session.delete(target)


# --- invitations ------------------------------------------------------------------------


async def create_invitation(
    factory: Factory, settings: Settings, mailer: EmailSender, ctx: TenantContext, *,
    actor_id: UUID, actor_role: Role, email: str, role: Role,
) -> InvitationInfo:  # fmt: skip
    normalized = email.strip().lower()
    raw, digest = new_token()
    expires = _now() + timedelta(days=settings.invitation_ttl_days)
    async with tenant_session(factory, ctx) as session:
        if not can_grant(await _lock_memberships(session, ctx, actor_id), role):
            raise ForbiddenError
        business = await session.get(Business, ctx.business_id)
        if business is None:
            raise NotFoundError
        # Replace any pending invitation for the same email.
        await session.execute(
            update(Invitation)
            .where(Invitation.business_id == ctx.business_id,
                   Invitation.email_normalized == normalized,
                   Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
            .values(revoked_at=_now())
        )  # fmt: skip
        inv = Invitation(
            id=uuid7(), business_id=ctx.business_id, email_normalized=normalized, role=role,
            token_hash=digest, invited_by_user_id=actor_id, expires_at=expires,
        )  # fmt: skip
        session.add(inv)
        business_name = business.name
    sent = await send_safely(
        mailer,
        OutgoingEmail(
            to=normalized,
            subject=f"You're invited to {business_name} on Agentree",
            body="Accept the invitation: "
            f"{settings.public_base_url}/invitations/accept?token={raw}",
        ),
        kind="invitation",
    )
    # If delivery failed the invitation stays pending; re-inviting issues a fresh token.
    return InvitationInfo(inv.id, normalized, role, expires, email_sent=sent)


async def list_invitations(factory: Factory, ctx: TenantContext) -> list[InvitationInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(Invitation).where(
                    Invitation.business_id == ctx.business_id,
                    Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
                    Invitation.expires_at > _now(),
                )
            )
        ).scalars().all()  # fmt: skip
    return [InvitationInfo(i.id, i.email_normalized, Role(i.role), i.expires_at) for i in rows]


async def revoke_invitation(factory: Factory, ctx: TenantContext, invitation_id: UUID) -> None:
    async with tenant_session(factory, ctx) as session:
        result = await session.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id, Invitation.business_id == ctx.business_id,
                   Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
            .values(revoked_at=_now())
        )  # fmt: skip
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFoundError


async def accept_invitation(factory: Factory, *, raw_token: str, user_id: UUID) -> UUID | None:
    """Atomically claim a valid invitation addressed to this user's verified email.

    The database function checks the user's stored, verified email itself.
    """
    async with factory() as session, session.begin():
        business_id: UUID | None = (
            await session.execute(
                text("SELECT agentree_claim_invitation(:t, :u)"),
                {"t": hash_token(raw_token), "u": user_id},
            )
        ).scalar()
    return business_id
