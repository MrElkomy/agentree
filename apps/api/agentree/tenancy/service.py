"""Tenancy service: the public interface of this module."""

import re
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.ids import uuid7
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from agentree.tenancy.models import Business

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
RESERVED_SLUGS = frozenset(
    {"api", "app", "admin", "login", "logout", "signup", "pricing", "docs", "help",
     "support", "status", "public", "hooks", "static", "assets", "widget", "www"}
)  # fmt: skip


class InvalidSlugError(ValueError):
    pass


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug) or "--" in slug or slug in RESERVED_SLUGS:
        raise InvalidSlugError(slug)
    return slug


async def create_business(
    factory: async_sessionmaker[AsyncSession], *, name: str, slug: str
) -> TenantContext:
    """Provision a new tenant. Callers must authorize the creator before calling."""
    ctx = TenantContext(uuid7(), TenantSource.PROVISIONING)
    async with tenant_session(factory, ctx) as session:
        session.add(Business(id=ctx.business_id, name=name.strip(), slug=validate_slug(slug)))
    return ctx


async def get_business(factory: async_sessionmaker[AsyncSession], ctx: TenantContext) -> Business:
    async with tenant_session(factory, ctx) as session:
        # Explicit filter as defense in depth on top of RLS.
        return (
            await session.execute(select(Business).where(Business.id == ctx.business_id))
        ).scalar_one()


async def resolve_public_business(
    factory: async_sessionmaker[AsyncSession], slug: str
) -> TenantContext | None:
    """Map a public page slug to a public tenant context (no internal privileges)."""
    async with factory() as session:
        business_id: UUID | None = (
            await session.execute(
                text("SELECT agentree_resolve_business_slug(:slug)"), {"slug": slug}
            )
        ).scalar()
    return TenantContext(business_id, TenantSource.PUBLIC) if business_id else None
