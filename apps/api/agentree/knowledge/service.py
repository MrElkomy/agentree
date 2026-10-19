"""Knowledge base: manual entries, manual publishing (MVP default), full-text retrieval.

Only published entries are ever retrievable by agents. Editing a published entry returns
it to draft until an admin publishes it again.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import String, delete, func, select, text
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


@dataclass(frozen=True)
class RetrievedEntry:
    id: UUID
    title: str
    body: str


def _info(e: KnowledgeEntry) -> EntryInfo:
    return EntryInfo(e.id, e.title, e.body, Status(e.status), e.published_at, e.updated_at)


async def create_entry(
    factory: Factory, ctx: TenantContext, *, title: str, body: str, actor_id: UUID
) -> EntryInfo:
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        entry = KnowledgeEntry(
            id=uuid7(), business_id=ctx.business_id, title=title.strip(), body=body.strip(),
            status=Status.DRAFT, created_by_user_id=actor_id, updated_at=now,
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
    factory: Factory, ctx: TenantContext, entry_id: UUID, *, title: str | None, body: str | None
) -> EntryInfo:
    async with tenant_session(factory, ctx) as session:
        entry = await _get(session, ctx, entry_id)
        if title is not None:
            entry.title = title.strip()
        if body is not None:
            entry.body = body.strip()
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
    factory: Factory, ctx: TenantContext, query: str, *, limit: int = 5
) -> list[RetrievedEntry]:
    """Published entries relevant to `query`, within a character budget."""
    published = (KnowledgeEntry.business_id == ctx.business_id) & (
        KnowledgeEntry.status == Status.PUBLISHED
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
