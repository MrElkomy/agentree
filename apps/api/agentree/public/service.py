"""Public AI page, website widget configuration and anonymous guest sessions.

Tenant context for public requests comes only from the page slug
(`tenancy.resolve_public_business`, TenantSource.PUBLIC) and only while the business has
enabled its public page. Guest sessions are opaque bearer tokens; only their SHA-256 is
stored, and a token is looked up inside the slug's tenant, so a token issued for one
business is simply unknown to every other business. Conversations and messages stay owned
by `agentree.agents`, which enforces that a guest only reaches its own conversations.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.ids import uuid7
from agentree.core.tokens import hash_token, new_token
from agentree.public.models import GuestSession, PublicProfile
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

MAX_DISPLAY_NAME = 80
MAX_BIO = 500
MAX_LINKS = 10
MAX_LINK_LABEL = 60
MAX_LINK_URL = 500
MAX_LINK_DESCRIPTION = 160
MAX_ORIGINS = 10
MAX_ORIGIN = 300
MAX_REPLY_BUDGET = 5000
DEFAULT_REPLY_BUDGET = 200
MAX_GUEST_MESSAGE = 1000

SESSION_TTL = timedelta(days=30)
MAX_TOKEN_CHARS = 128  # longer bearer values are rejected without hashing

# Abuse limits (TD-12). Fixed windows in the Postgres rate-limit table.
SESSIONS_PER_IP_PER_HOUR = 20
SESSIONS_PER_BUSINESS_PER_DAY = 500
CHAT_PER_SESSION_PER_10_MIN = 20
CHAT_PER_SESSION_PER_DAY = 100
CHAT_PER_IP_PER_HOUR = 60

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_TLD = r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])"  # alphabetic start: IP literals are rejected
ORIGIN_RE = re.compile(rf"^https://((?:{_LABEL}\.)+{_TLD})(?::(\d{{1,5}}))?$")
LOCAL_ORIGIN_RE = re.compile(r"^http://localhost:(\d{1,5})$")
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f<>\"'\\]")


class InvalidOriginError(ValueError):
    pass


class InvalidLinkError(ValueError):
    pass


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    description: str = ""


@dataclass(frozen=True)
class ProfileInfo:
    enabled: bool
    display_name: str | None
    bio: str
    links: list[Link]
    widget_origins: list[str]
    daily_reply_budget: int
    updated_at: datetime | None


@dataclass(frozen=True)
class PublicPage:
    """A business's enabled public page, resolved from its slug."""

    tenant: TenantContext
    slug: str
    display_name: str
    bio: str
    links: list[Link]
    widget_origins: list[str]
    daily_reply_budget: int


@dataclass(frozen=True)
class NewGuestSession:
    token: str  # returned to the visitor once; never stored or logged
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


# --- validation -------------------------------------------------------------------------


def _port_ok(port: str | None) -> bool:
    return port is None or (not port.startswith("0") and 1 <= int(port) <= 65535)


def normalize_origin(value: str, *, allow_localhost: bool) -> str:
    """Validate one exact web origin for the widget's frame-ancestors allowlist.

    Accepts `https://host[:port]` (DNS names only, lowercased; no path, query, fragment,
    credentials or wildcard). `http://localhost:<port>` is accepted only when
    `allow_localhost` (dev/test). The result is safe to place in a CSP header.
    """
    v = value.strip().lower()
    if v.endswith("/"):
        v = v[:-1]
    if allow_localhost and (m := LOCAL_ORIGIN_RE.fullmatch(v)):
        if _port_ok(m.group(1)):
            return v
        raise InvalidOriginError(value)
    m = ORIGIN_RE.fullmatch(v)
    if m is None or len(m.group(1)) > 253 or not _port_ok(m.group(2)):
        raise InvalidOriginError(value)
    return f"https://{m.group(1)}" if m.group(2) in (None, "443") else v


def normalize_origins(values: list[str], *, allow_localhost: bool) -> list[str]:
    seen: list[str] = []
    for v in values:
        origin = normalize_origin(v, allow_localhost=allow_localhost)
        if origin not in seen:
            seen.append(origin)
    return seen


def validate_link_url(value: str) -> str:
    """Public page links: absolute https URLs with a host, no credentials or unsafe chars."""
    v = value.strip()
    if len(v) > MAX_LINK_URL or _UNSAFE_URL_CHARS.search(v):
        raise InvalidLinkError(value)
    try:
        parts = urlsplit(v)
    except ValueError:
        raise InvalidLinkError(value) from None
    if parts.scheme.lower() != "https" or not parts.hostname or "@" in parts.netloc:
        raise InvalidLinkError(value)
    return v


# --- owner profile ----------------------------------------------------------------------


def _links(raw: list[dict[str, Any]]) -> list[Link]:
    # Links saved before descriptions existed have no "description" key.
    return [
        Link(str(item["label"]), str(item["url"]), str(item.get("description") or ""))
        for item in raw
    ]


def _profile_info(p: PublicProfile | None) -> ProfileInfo:
    if p is None:
        return ProfileInfo(False, None, "", [], [], DEFAULT_REPLY_BUDGET, None)
    return ProfileInfo(p.enabled, p.display_name, p.bio, _links(p.links), list(p.widget_origins),
                       p.daily_reply_budget, p.updated_at)  # fmt: skip


async def _load(session: AsyncSession, ctx: TenantContext) -> PublicProfile | None:
    return (
        await session.execute(
            select(PublicProfile).where(PublicProfile.business_id == ctx.business_id)
        )
    ).scalar_one_or_none()


async def get_profile(factory: Factory, ctx: TenantContext) -> ProfileInfo:
    """The business's public page settings (defaults when never saved: disabled)."""
    async with tenant_session(factory, ctx) as session:
        return _profile_info(await _load(session, ctx))


async def save_profile(
    factory: Factory, ctx: TenantContext, *, enabled: bool, display_name: str | None, bio: str,
    links: list[Link], widget_origins: list[str], daily_reply_budget: int, allow_localhost: bool,
) -> ProfileInfo:  # fmt: skip
    """Replace the public page settings. Caller must have authorized an Admin or Owner."""
    if len(links) > MAX_LINKS:
        raise InvalidLinkError("too many links")
    for link in links:
        validate_link_url(link.url)
    origins = normalize_origins(widget_origins, allow_localhost=allow_localhost)
    if len(origins) > MAX_ORIGINS:
        raise InvalidOriginError("too many origins")
    values: dict[str, Any] = {
        "enabled": enabled,
        "display_name": display_name,
        "bio": bio,
        "links": [
            {"label": link.label, "url": link.url, "description": link.description}
            for link in links
        ],
        "widget_origins": origins,
        "daily_reply_budget": daily_reply_budget,
        "updated_at": _now(),
    }
    async with tenant_session(factory, ctx) as session:
        profile = await _load(session, ctx)
        if profile is None:
            profile = PublicProfile(business_id=ctx.business_id, **values)
            session.add(profile)
        else:
            for key, value in values.items():
                setattr(profile, key, value)
        await session.flush()
        await session.refresh(profile)
        return _profile_info(profile)


# --- public page ------------------------------------------------------------------------


async def resolve_page(factory: Factory, slug: str) -> PublicPage | None:
    """The enabled public page for `slug`, or None (unknown slug and disabled page alike)."""
    if len(slug) > 63:
        return None
    ctx = await tenancy.resolve_public_business(factory, slug)
    if ctx is None:
        return None
    async with tenant_session(factory, ctx) as session:
        profile = await _load(session, ctx)
    if profile is None or not profile.enabled:
        return None
    business = await tenancy.get_business(factory, ctx)
    return PublicPage(
        tenant=ctx, slug=business.slug, display_name=profile.display_name or business.name,
        bio=profile.bio, links=_links(profile.links),
        widget_origins=list(profile.widget_origins),
        daily_reply_budget=profile.daily_reply_budget,
    )  # fmt: skip


# --- guest sessions ---------------------------------------------------------------------


async def create_guest_session(factory: Factory, ctx: TenantContext) -> NewGuestSession:
    raw, digest = new_token()
    now = _now()
    expires = now + SESSION_TTL
    async with tenant_session(factory, ctx) as session:
        session.add(GuestSession(id=uuid7(), business_id=ctx.business_id, token_hash=digest,
                                 created_at=now, last_seen_at=now, expires_at=expires))  # fmt: skip
    return NewGuestSession(raw, expires)


async def authenticate_guest(
    factory: Factory, ctx: TenantContext, raw_token: str | None, *, touch: bool = False
) -> UUID | None:
    """The guest session id for a bearer token within this business, or None.

    Unknown, expired, malformed and other-business tokens are indistinguishable. With
    `touch`, records the visit (last_seen_at) for retention.
    """
    if not raw_token or len(raw_token) > MAX_TOKEN_CHARS:
        return None
    digest = hash_token(raw_token)
    now = _now()
    async with tenant_session(factory, ctx) as session:
        where = (
            (GuestSession.business_id == ctx.business_id)
            & (GuestSession.token_hash == digest)
            & (GuestSession.expires_at > now)
        )
        if touch:
            session_id: UUID | None = (
                await session.execute(
                    update(GuestSession).where(where).values(last_seen_at=now)
                    .returning(GuestSession.id)
                )
            ).scalar_one_or_none()  # fmt: skip
        else:
            session_id = (
                await session.execute(select(GuestSession.id).where(where))
            ).scalar_one_or_none()
    return session_id
