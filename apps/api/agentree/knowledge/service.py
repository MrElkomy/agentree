"""Knowledge base: manual entries, manual publishing (MVP default), full-text retrieval.

Only published entries are ever retrievable by agents. Editing a published entry (its text or
which agents may use it) returns it to draft until an admin publishes it again. An entry can be
limited to some agent roles (`agent_roles`, Task 15); an empty list means every agent.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import String, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.ids import uuid7
from agentree.knowledge.models import KnowledgeEntry
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

MAX_BODY_CHARS = 20_000
# Small knowledge bases are given to the agent whole; larger ones are searched.
SMALL_KB_ENTRIES = 8
CONTEXT_CHAR_BUDGET = 12_000


class Status(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class NotFoundError(Exception):
    pass


@dataclass(frozen=True)
class EntryInfo:
    id: UUID
    title: str
    body: str
    status: Status
    published_at: datetime | None
    updated_at: datetime
    agent_roles: tuple[str, ...] = ()  # empty: every agent
    source_file_id: UUID | None = None  # extracted from this uploaded file (Task 17)


@dataclass(frozen=True)
class RetrievedEntry:
    id: UUID
    title: str
    body: str


def _info(e: KnowledgeEntry) -> EntryInfo:
    return EntryInfo(e.id, e.title, e.body, Status(e.status), e.published_at, e.updated_at,
                     tuple(e.agent_roles or ()), e.source_file_id)  # fmt: skip


def _roles(roles: Sequence[str]) -> list[str]:
    """Distinct, sorted (the caller validated the names against the agent registry)."""
    return sorted(set(roles))


async def create_entry(
    factory: Factory, ctx: TenantContext, *, title: str, body: str, actor_id: UUID,
    agent_roles: Sequence[str] = (),
) -> EntryInfo:  # fmt: skip
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        entry = KnowledgeEntry(
            id=uuid7(), business_id=ctx.business_id, title=title.strip(), body=body.strip(),
            status=Status.DRAFT, agent_roles=_roles(agent_roles), created_by_user_id=actor_id,
            updated_at=now,
        )  # fmt: skip
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        return _info(entry)


async def _get(session: AsyncSession, ctx: TenantContext, entry_id: UUID) -> KnowledgeEntry:
    entry = (
        await session.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.business_id == ctx.business_id, KnowledgeEntry.id == entry_id
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise NotFoundError
    return entry


async def list_entries(factory: Factory, ctx: TenantContext) -> list[EntryInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.business_id == ctx.business_id)
                .order_by(KnowledgeEntry.updated_at.desc())
            )
        ).scalars().all()  # fmt: skip
    return [_info(e) for e in rows]


async def get_entry(factory: Factory, ctx: TenantContext, entry_id: UUID) -> EntryInfo:
    async with tenant_session(factory, ctx) as session:
        return _info(await _get(session, ctx, entry_id))


async def update_entry(
    factory: Factory, ctx: TenantContext, entry_id: UUID, *, title: str | None, body: str | None,
    agent_roles: Sequence[str] | None = None,
) -> EntryInfo:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        entry = await _get(session, ctx, entry_id)
        if title is not None:
            entry.title = title.strip()
        if body is not None:
            entry.body = body.strip()
        if agent_roles is not None:
            entry.agent_roles = _roles(agent_roles)
        entry.status, entry.published_at = Status.DRAFT, None  # re-review after any edit
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(entry)
        return _info(entry)


async def set_status(
    factory: Factory, ctx: TenantContext, entry_id: UUID, status: Status
) -> EntryInfo:
    async with tenant_session(factory, ctx) as session:
        entry = await _get(session, ctx, entry_id)
        entry.status = status
        entry.published_at = datetime.now(UTC) if status is Status.PUBLISHED else None
        await session.flush()
        await session.refresh(entry)
        return _info(entry)


async def delete_entry(factory: Factory, ctx: TenantContext, entry_id: UUID) -> None:
    async with tenant_session(factory, ctx) as session:
        result = await session.execute(
            delete(KnowledgeEntry).where(
                KnowledgeEntry.business_id == ctx.business_id, KnowledgeEntry.id == entry_id
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFoundError


async def retrieve(
    factory: Factory, ctx: TenantContext, query: str, *, role: str | None = None, limit: int = 5
) -> list[RetrievedEntry]:
    """Published entries relevant to `query`, within a character budget.

    `role`: the answering agent; only entries open to every agent or to that role are used.
    None applies no role filter (agents always pass their role).
    """
    published = (KnowledgeEntry.business_id == ctx.business_id) & (
        KnowledgeEntry.status == Status.PUBLISHED
    )
    if role is not None:
        published = published & or_(
            func.cardinality(KnowledgeEntry.agent_roles) == 0,
            KnowledgeEntry.agent_roles.contains([role]),
        )
    async with tenant_session(factory, ctx) as session:
        total = (
            await session.execute(select(func.count()).select_from(KnowledgeEntry).where(published))
        ).scalar_one()
        if total <= SMALL_KB_ENTRIES:
            rows = (
                await session.execute(
                    select(KnowledgeEntry).where(published).order_by(KnowledgeEntry.updated_at.desc())
                )
            ).scalars().all()  # fmt: skip
        else:
            # Natural questions rarely contain every term of the answer: match ANY stemmed
            # term (stop words removed by plainto_tsquery), then rank by relevance.
            tsquery = func.replace(
                func.plainto_tsquery(text("'english'"), query).cast(String), "&", "|"
            ).cast(TSQUERY)
            rows = (
                await session.execute(
                    select(KnowledgeEntry)
                    .where(published, KnowledgeEntry.search_vector.op("@@")(tsquery))
                    .order_by(func.ts_rank(KnowledgeEntry.search_vector, tsquery).desc())
                    .limit(limit)
                )
            ).scalars().all()  # fmt: skip
    picked: list[RetrievedEntry] = []
    budget = CONTEXT_CHAR_BUDGET
    for e in rows:
        if budget <= 0:
            break
        body = e.body[:budget]
        budget -= len(body)
        picked.append(RetrievedEntry(e.id, e.title, body))
    return picked
