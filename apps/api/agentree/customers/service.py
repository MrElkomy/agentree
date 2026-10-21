"""Customer identity and memory (Task 16).

Identity: a guest session (public page / widget visitor) gets a provisional profile the first
time memory is saved for it. Typing an email unlocks nothing: only a one-time code sent to that
address and entered in the same guest session links the session to the verified profile of that
email (one per business). Provisional memory then moves to the verified profile.

Memory: short structured facts in allowlisted categories, derived from conversations by the
worker (`extraction.py`) and validated here: never message text, never contact or payment data.
Each item expires with the raw conversation it came from (PO decision U-12: nothing derived from
a conversation outlives the retention window); idle profiles are deleted by the retention purge.
Agents read memory only for a verified customer, and only the categories their role allows
(`agents.registry`). Owners and Admins review, correct and delete memory. Audit rows never hold
emails, codes or memory values.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.audit.service import AuditAction, record
from agentree.core.ids import uuid7
from agentree.customers.models import (
    CATEGORIES,
    CustomerProfile,
    CustomerSession,
    CustomerVerification,
    MemoryItem,
)
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_VALUE = 120  # characters of one memory item
MAX_ITEMS_PER_CONVERSATION = 5
MAX_ITEMS_PER_CUSTOMER = 30
MAX_ITEMS_FOR_AGENT = 20
RETENTION_CAP = timedelta(days=30)  # U-12; settings.retention_days may be shorter

_EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
# Contact and payment data never become memory: emails, URLs, long digit runs (phones, cards).
_FORBIDDEN = re.compile(r"@|https?://|www\.|\d[\d\s().+-]{5,}\d")
_WORD = re.compile(r"\w+", re.UNICODE)
VERBATIM_RUN = 6  # an item sharing this many consecutive words with a message is rejected


class InvalidEmailError(ValueError):
    pass


class InvalidCodeError(Exception):
    """Wrong, expired, used or exhausted code. Deliberately one error for all of them."""


class NotFoundError(Exception):
    pass


class InvalidMemoryError(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    verified: bool
    email_hint: str | None  # masked email of the verified customer (shown to that visitor)


@dataclass(frozen=True)
class MemoryFact:
    category: str
    value: str


@dataclass(frozen=True)
class CustomerInfo:
    id: UUID
    verified: bool
    email: str | None
    item_count: int
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class ItemInfo:
    id: UUID
    category: str
    value: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise InvalidEmailError
    return email


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _code_hash(challenge_id: UUID, code: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest()


# --- memory validation (pure) ---------------------------------------------------------------


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _shares_run(value: str, texts: Sequence[str], run: int = VERBATIM_RUN) -> bool:
    words = _words(value)
    if len(words) < run:
        # Short items: verbatim only if the whole value appears as a phrase in a message.
        phrase = " ".join(words)
        return bool(phrase) and any(f" {phrase} " in f" {' '.join(_words(t))} " for t in texts)
    grams = {tuple(words[i : i + run]) for i in range(len(words) - run + 1)}
    for t in texts:
        tw = _words(t)
        if any(tuple(tw[i : i + run]) in grams for i in range(len(tw) - run + 1)):
            return True
    return False


def validate_fact(category: str, value: str, messages: Sequence[str] = ()) -> MemoryFact:
    """One memory item: allowlisted category, one short line in the model's own words.

    `messages`: the conversation's texts; an item quoting them (a run of VERBATIM_RUN words, or
    a short item that is a whole phrase of a message) is rejected. Owner edits pass none.
    """
    if category not in CATEGORIES:
        raise InvalidMemoryError("category")
    text = " ".join(value.split())
    if not 3 <= len(text) <= MAX_VALUE:
        raise InvalidMemoryError("value")
    if _FORBIDDEN.search(text) or "<<" in text or ">>" in text:
        raise InvalidMemoryError("value")
    if messages and _shares_run(text, messages):
        raise InvalidMemoryError("verbatim")
    return MemoryFact(category, text)


# --- profiles and guest sessions --------------------------------------------------------------


async def _linked(
    session: AsyncSession, ctx: TenantContext, guest_session_id: UUID
) -> CustomerProfile | None:
    return (
        await session.execute(
            select(CustomerProfile)
            .join(CustomerSession, (CustomerSession.business_id == CustomerProfile.business_id)
                  & (CustomerSession.customer_id == CustomerProfile.id))
            .where(CustomerSession.business_id == ctx.business_id,
                   CustomerSession.guest_session_id == guest_session_id)
        )
    ).scalar_one_or_none()  # fmt: skip


async def _link(
    session: AsyncSession, ctx: TenantContext, guest_session_id: UUID, customer_id: UUID
) -> None:
    await session.execute(
        delete(CustomerSession).where(CustomerSession.business_id == ctx.business_id,
                                      CustomerSession.guest_session_id == guest_session_id)
    )  # fmt: skip
    session.add(CustomerSession(guest_session_id=guest_session_id, business_id=ctx.business_id,
                                customer_id=customer_id, created_at=_now()))  # fmt: skip


async def _profile_for_session(
    session: AsyncSession, ctx: TenantContext, guest_session_id: UUID, now: datetime
) -> CustomerProfile:
    """The session's profile, creating a provisional one on first use."""
    profile = await _linked(session, ctx, guest_session_id)
    if profile is None:
        profile = CustomerProfile(id=uuid7(), business_id=ctx.business_id, created_at=now,
                                  last_seen_at=now)  # fmt: skip
        session.add(profile)
        await session.flush()
        await _link(session, ctx, guest_session_id, profile.id)
        await session.flush()
    return profile


async def identity(factory: Factory, ctx: TenantContext, guest_session_id: UUID) -> Identity:
    async with tenant_session(factory, ctx) as session:
        profile = await _linked(session, ctx, guest_session_id)
    if profile is None or profile.email is None:
        return Identity(False, None)
    return Identity(True, mask_email(profile.email))


async def forget_identity(factory: Factory, ctx: TenantContext, guest_session_id: UUID) -> None:
    """ "Not you?": this browser stops being the verified customer (their memory stays theirs)."""
    async with tenant_session(factory, ctx) as session:
        profile = await _linked(session, ctx, guest_session_id)
        if profile is not None and profile.email is not None:
            await session.execute(
                delete(CustomerSession).where(
                    CustomerSession.business_id == ctx.business_id,
                    CustomerSession.guest_session_id == guest_session_id)
            )  # fmt: skip


# --- email verification -----------------------------------------------------------------------


async def start_verification(
    factory: Factory, ctx: TenantContext, *, guest_session_id: UUID, email: str
) -> tuple[str, str]:
    """New code for this guest session and email; earlier codes of the session stop working.
    Returns (normalized email, code) for the caller to email. Unlocks nothing by itself."""
    address = normalize_email(email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = _now()
    async with tenant_session(factory, ctx) as session:
        await session.execute(
            update(CustomerVerification)
            .where(CustomerVerification.business_id == ctx.business_id,
                   CustomerVerification.guest_session_id == guest_session_id,
                   CustomerVerification.consumed_at.is_(None))
            .values(consumed_at=now)
        )  # fmt: skip
        cid = uuid7()
        session.add(CustomerVerification(
            id=cid, business_id=ctx.business_id, guest_session_id=guest_session_id,
            email=address, code_hash=_code_hash(cid, code), created_at=now,
            expires_at=now + CODE_TTL,
        ))  # fmt: skip
    return address, code


async def confirm_verification(
    factory: Factory, ctx: TenantContext, *, guest_session_id: UUID, code: str
) -> Identity:
    """Check the session's latest code; on success link the session to the verified profile of
    that email, moving the session's provisional memory to it. Else InvalidCodeError."""
    now = _now()
    ok = False
    async with tenant_session(factory, ctx) as session:
        challenge = (
            await session.execute(
                select(CustomerVerification)
                .where(CustomerVerification.business_id == ctx.business_id,
                       CustomerVerification.guest_session_id == guest_session_id,
                       CustomerVerification.consumed_at.is_(None),
                       CustomerVerification.expires_at > now)
                .order_by(CustomerVerification.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()  # fmt: skip
        if challenge is None or challenge.attempts >= MAX_ATTEMPTS:
            raise InvalidCodeError
        candidate = code.strip()
        if (
            candidate.isdigit()
            and len(candidate) == 6
            and hmac.compare_digest(challenge.code_hash, _code_hash(challenge.id, candidate))
        ):
            ok = True
            challenge.consumed_at = now
            await _verify(session, ctx, guest_session_id, challenge.email, now)
        else:
            challenge.attempts += 1  # committed: wrong guesses count even though we refuse
    if not ok:
        raise InvalidCodeError
    return Identity(True, mask_email(challenge.email))


async def _verify(
    session: AsyncSession, ctx: TenantContext, guest_session_id: UUID, email: str, now: datetime
) -> None:
    verified = (
        await session.execute(
            select(CustomerProfile).where(CustomerProfile.business_id == ctx.business_id,
                                          CustomerProfile.email == email)
        )
    ).scalar_one_or_none()  # fmt: skip
    if verified is None:
        verified = CustomerProfile(id=uuid7(), business_id=ctx.business_id, email=email,
                                   verified_at=now, created_at=now, last_seen_at=now)  # fmt: skip
        session.add(verified)
        await session.flush()
    verified.last_seen_at = now
    current = await _linked(session, ctx, guest_session_id)
    if current is not None and current.email is None and current.id != verified.id:
        # The visitor proved this email: what this session's provisional profile holds is theirs.
        await session.execute(
            update(MemoryItem)
            .where(MemoryItem.business_id == ctx.business_id,
                   MemoryItem.customer_id == current.id)
            .values(customer_id=verified.id)
        )  # fmt: skip
        await session.delete(current)
        await session.flush()
    await _link(session, ctx, guest_session_id, verified.id)
    await record(session, ctx, action=AuditAction.CUSTOMER_VERIFIED, actor_user_id=None,
                 target_type="customer", target_id=verified.id, details={})  # fmt: skip


# --- memory for agents and the extraction job --------------------------------------------------


async def memory_for_guest(
    factory: Factory, ctx: TenantContext, guest_session_id: UUID
) -> list[MemoryFact]:
    """Memory of the verified customer behind this guest session; nothing for anyone else."""
    now = _now()
    async with tenant_session(factory, ctx) as session:
        profile = await _linked(session, ctx, guest_session_id)
        if profile is None or profile.verified_at is None:
            return []
        profile.last_seen_at = now
        rows = (
            await session.execute(
                select(MemoryItem.category, MemoryItem.value)
                .where(MemoryItem.business_id == ctx.business_id,
                       MemoryItem.customer_id == profile.id, MemoryItem.expires_at > now)
                .order_by(MemoryItem.updated_at.desc())
                .limit(MAX_ITEMS_FOR_AGENT)
            )
        ).all()  # fmt: skip
    return [MemoryFact(r.category, r.value) for r in rows]


async def save_extracted(
    factory: Factory, ctx: TenantContext, *, guest_session_id: UUID, conversation_id: UUID,
    last_message_at: datetime, facts: Sequence[MemoryFact], retention_days: int,
) -> int:  # fmt: skip
    """Store validated facts on the session's profile. A fact already known is renewed (a new
    row, so its expiry follows the newest conversation). Returns how many were stored."""
    if not facts:
        return 0
    now = _now()
    window = min(timedelta(days=retention_days), RETENTION_CAP)
    expires = min(last_message_at, now) + window
    async with tenant_session(factory, ctx) as session:
        profile = await _profile_for_session(session, ctx, guest_session_id, now)
        profile.last_seen_at = now
        stored = 0
        for fact in facts[:MAX_ITEMS_PER_CONVERSATION]:
            await session.execute(
                delete(MemoryItem).where(
                    MemoryItem.business_id == ctx.business_id,
                    MemoryItem.customer_id == profile.id, MemoryItem.category == fact.category,
                    func.lower(MemoryItem.value) == fact.value.lower())
            )  # fmt: skip
            session.add(MemoryItem(
                id=uuid7(), business_id=ctx.business_id, customer_id=profile.id,
                category=fact.category, value=fact.value, source_conversation_id=conversation_id,
                created_at=now, updated_at=now, expires_at=expires,
            ))  # fmt: skip
            stored += 1
        await session.flush()
        surplus = (
            await session.execute(
                select(MemoryItem.id)
                .where(MemoryItem.business_id == ctx.business_id,
                       MemoryItem.customer_id == profile.id)
                .order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc())
                .offset(MAX_ITEMS_PER_CUSTOMER)
            )
        ).scalars().all()  # fmt: skip
        if surplus:
            await session.execute(delete(MemoryItem).where(MemoryItem.id.in_(surplus)))
    return stored


# --- owners and admins (dashboard) ------------------------------------------------------------


def _customer_info(p: CustomerProfile, count: int) -> CustomerInfo:
    return CustomerInfo(p.id, p.verified_at is not None, p.email, count, p.created_at,
                        p.last_seen_at)  # fmt: skip


async def list_customers(factory: Factory, ctx: TenantContext, *, limit: int = 200) -> list[
    CustomerInfo
]:  # fmt: skip
    counts = (
        select(MemoryItem.customer_id, func.count().label("n"))
        .where(MemoryItem.business_id == ctx.business_id)
        .group_by(MemoryItem.customer_id)
        .subquery()
    )
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(CustomerProfile, func.coalesce(counts.c.n, 0))
                .outerjoin(counts, counts.c.customer_id == CustomerProfile.id)
                .where(CustomerProfile.business_id == ctx.business_id)
                .order_by(CustomerProfile.last_seen_at.desc(), CustomerProfile.id.desc())
                .limit(limit)
            )
        ).all()  # fmt: skip
    return [_customer_info(p, int(n)) for p, n in rows]


async def _customer(
    session: AsyncSession, ctx: TenantContext, customer_id: UUID
) -> CustomerProfile:
    profile = (
        await session.execute(
            select(CustomerProfile).where(CustomerProfile.business_id == ctx.business_id,
                                          CustomerProfile.id == customer_id)
        )
    ).scalar_one_or_none()  # fmt: skip
    if profile is None:
        raise NotFoundError
    return profile


def _item_info(m: MemoryItem) -> ItemInfo:
    return ItemInfo(m.id, m.category, m.value, m.created_at, m.updated_at, m.expires_at)


async def get_customer(
    factory: Factory, ctx: TenantContext, customer_id: UUID
) -> tuple[CustomerInfo, list[ItemInfo]]:
    async with tenant_session(factory, ctx) as session:
        profile = await _customer(session, ctx, customer_id)
        items = (
            await session.execute(
                select(MemoryItem)
                .where(MemoryItem.business_id == ctx.business_id,
                       MemoryItem.customer_id == customer_id)
                .order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc())
            )
        ).scalars().all()  # fmt: skip
        return _customer_info(profile, len(items)), [_item_info(m) for m in items]


async def _item(
    session: AsyncSession, ctx: TenantContext, customer_id: UUID, item_id: UUID
) -> MemoryItem:
    item = (
        await session.execute(
            select(MemoryItem).where(MemoryItem.business_id == ctx.business_id,
                                     MemoryItem.customer_id == customer_id,
                                     MemoryItem.id == item_id)
        )
    ).scalar_one_or_none()  # fmt: skip
    if item is None:
        raise NotFoundError
    return item


async def update_item(
    factory: Factory, ctx: TenantContext, customer_id: UUID, item_id: UUID, *, value: str,
    actor_id: UUID,
) -> ItemInfo:  # fmt: skip
    """Correct an item. Its expiry does not move: a correction is not a new conversation."""
    async with tenant_session(factory, ctx) as session:
        item = await _item(session, ctx, customer_id, item_id)
        item.value = validate_fact(item.category, value).value
        item.updated_at = _now()
        await record(session, ctx, action=AuditAction.CUSTOMER_MEMORY_UPDATED,
                     actor_user_id=actor_id, target_type="customer", target_id=customer_id,
                     details={"category": item.category})  # fmt: skip
        await session.flush()
        return _item_info(item)


async def delete_item(factory: Factory, ctx: TenantContext, customer_id: UUID, item_id: UUID, *,
                      actor_id: UUID) -> None:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        item = await _item(session, ctx, customer_id, item_id)
        await session.delete(item)
        await record(session, ctx, action=AuditAction.CUSTOMER_MEMORY_DELETED,
                     actor_user_id=actor_id, target_type="customer", target_id=customer_id,
                     details={"category": item.category})  # fmt: skip


async def delete_customer(factory: Factory, ctx: TenantContext, customer_id: UUID, *,
                          actor_id: UUID) -> None:  # fmt: skip
    """Delete the profile: its memory and guest-session links go with it (cascade)."""
    async with tenant_session(factory, ctx) as session:
        profile = await _customer(session, ctx, customer_id)
        await session.delete(profile)
        await record(session, ctx, action=AuditAction.CUSTOMER_DELETED, actor_user_id=actor_id,
                     target_type="customer", target_id=customer_id,
                     details={"verified": profile.verified_at is not None})  # fmt: skip
