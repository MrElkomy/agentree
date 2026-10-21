"""BYOK provider credentials: store, list, verify, and resolve keys for model calls.

Plaintext keys exist only in memory: on the way in (encrypt) and when a model call needs
them (decrypt). They are never returned to clients, logged, or stored unencrypted.

Each stored key has a circuit breaker (state on its row, shared by every API process):
closed -> open after FAILURE_THRESHOLD consecutive availability failures (at once for auth or
quota errors) -> after the cooldown one request probes it (half-open) -> closed on success,
open again (longer cooldown) on failure. Calls skip open keys, so the business falls back to
its backup key and returns to the primary once a probe succeeds.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.audit.service import AuditAction, record
from agentree.core import metrics
from agentree.core.config import Settings
from agentree.core.ids import uuid7
from agentree.core.vault import SealedSecret, Vault, VaultUnavailableError, parse_master_key
from agentree.llm.base import (
    MODEL_RE,
    ChatMessage,
    ChatRequest,
    ErrorKind,
    LLMProvider,
    ProviderError,
    ProviderName,
)
from agentree.providers.models import ProviderCredential
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

FAILURE_THRESHOLD = 3  # consecutive availability failures that open the breaker
BASE_COOLDOWN = timedelta(seconds=30)  # doubles after each failed probe
MAX_COOLDOWN = timedelta(minutes=10)
KEY_COOLDOWN = timedelta(minutes=5)  # auth / quota: the key itself needs attention
PROBE_LEASE = timedelta(seconds=90)  # one probe at a time; a crashed probe frees it later


class Slot(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"


class Admission(StrEnum):
    CLOSED = "closed"  # call normally
    PROBE = "probe"  # half-open: this call tests whether the provider is back
    OPEN = "open"  # skip this key until its cooldown ends


class Health(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # recent errors, still in use
    DOWN = "down"  # breaker open: calls go to the other key
    RECOVERING = "recovering"  # cooldown over: the next call tests it


class Transition(StrEnum):
    OPENED = "opened"
    REOPENED = "reopened"  # a probe failed
    CLOSED = "closed"  # a probe (or a manual test) succeeded


class InvalidCredentialError(ValueError):
    pass


class NotFoundError(Exception):
    pass


@dataclass(frozen=True)
class CredentialInfo:
    slot: Slot
    provider: ProviderName
    model: str
    key_hint: str
    last_verified_at: datetime | None
    last_error_kind: str | None
    updated_at: datetime
    health: Health
    last_failure_at: datetime | None
    breaker_open_until: datetime | None


@dataclass(frozen=True)
class ResolvedCredential:
    slot: Slot
    provider: ProviderName
    model: str
    api_key: str


def build_vault(settings: Settings) -> Vault | None:
    if settings.master_key is None:
        return None
    keys = {settings.master_key_id: parse_master_key(settings.master_key.get_secret_value())}
    for kid, value in settings.previous_master_keys.items():
        keys[kid] = parse_master_key(value.get_secret_value())
    return Vault(settings.master_key_id, keys)


def _require(vault: Vault | None) -> Vault:
    if vault is None:
        raise VaultUnavailableError("AGENTREE_MASTER_KEY is not configured")
    return vault


def _aad(business_id: UUID, credential_id: UUID) -> bytes:
    return f"agentree:provider-credential:{business_id}:{credential_id}".encode()


def _hint(api_key: str) -> str:
    return api_key[-4:] if len(api_key) >= 12 else ""


def validate_input(provider: str, model: str, api_key: str) -> tuple[ProviderName, str, str]:
    try:
        name = ProviderName(provider)
    except ValueError:
        raise InvalidCredentialError("unsupported_provider") from None
    if not MODEL_RE.fullmatch(model):
        raise InvalidCredentialError("invalid_model")
    key = api_key.strip()
    if not 8 <= len(key) <= 512 or any(c.isspace() for c in key):
        raise InvalidCredentialError("invalid_api_key_format")
    return name, model, key


async def verify_key(provider: LLMProvider, api_key: str, model: str) -> None:
    """Make a minimal real call; raises ProviderError (e.g. kind=auth) if the key fails."""
    await provider.chat(
        api_key,
        ChatRequest(model=model, messages=[ChatMessage("user", "Reply with OK.")], max_tokens=5),
    )


async def save_credential(
    factory: Factory, vault: Vault | None, ctx: TenantContext, *, slot: Slot,
    provider: ProviderName, model: str, api_key: str, actor_id: UUID, verified: bool,
) -> CredentialInfo:  # fmt: skip
    v = _require(vault)
    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        # Replacing a slot creates a new row id, so old ciphertext can never be re-bound.
        replaced = await session.execute(
            delete(ProviderCredential).where(
                ProviderCredential.business_id == ctx.business_id, ProviderCredential.slot == slot
            )
        )
        cred_id = uuid7()
        sealed = v.encrypt(api_key, aad=_aad(ctx.business_id, cred_id))
        cred = ProviderCredential(
            id=cred_id, business_id=ctx.business_id, slot=slot, provider=provider, model=model,
            key_hint=_hint(api_key), ciphertext=sealed.ciphertext, wrapped_dek=sealed.wrapped_dek,
            master_key_id=sealed.key_id, created_by_user_id=actor_id,
            last_verified_at=now if verified else None, updated_at=now,
        )  # fmt: skip
        session.add(cred)
        # Never the key or its hint: only which slot, provider and model changed.
        await record(session, ctx, action=AuditAction.PROVIDER_KEY_SAVED, actor_user_id=actor_id,
                     target_type="provider_key", target_id=slot,
                     details={"slot": slot, "provider": provider, "model": model,
                              "replaced": replaced.rowcount > 0,  # type: ignore[attr-defined]
                              "verified": verified})  # fmt: skip
    return _info(cred)


def _now() -> datetime:
    return datetime.now(UTC)


def _health(c: ProviderCredential, now: datetime) -> Health:
    if c.breaker_open_until is not None:
        return Health.DOWN if now < c.breaker_open_until else Health.RECOVERING
    return Health.DEGRADED if c.last_error_kind else Health.HEALTHY


def _info(c: ProviderCredential) -> CredentialInfo:
    return CredentialInfo(
        slot=Slot(c.slot), provider=ProviderName(c.provider), model=c.model,
        key_hint=c.key_hint, last_verified_at=c.last_verified_at,
        last_error_kind=c.last_error_kind, updated_at=c.updated_at,
        health=_health(c, _now()), last_failure_at=c.last_failure_at,
        breaker_open_until=c.breaker_open_until,
    )  # fmt: skip


async def list_credentials(factory: Factory, ctx: TenantContext) -> list[CredentialInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(ProviderCredential)
                .where(ProviderCredential.business_id == ctx.business_id)
                .order_by(ProviderCredential.slot.desc())  # primary before backup
            )
        ).scalars().all()  # fmt: skip
    return [_info(c) for c in rows]


async def delete_credential(
    factory: Factory, ctx: TenantContext, slot: Slot, *, actor_id: UUID
) -> None:
    async with tenant_session(factory, ctx) as session:
        result = await session.execute(
            delete(ProviderCredential).where(
                ProviderCredential.business_id == ctx.business_id, ProviderCredential.slot == slot
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFoundError
        await record(
            session, ctx, action=AuditAction.PROVIDER_KEY_REMOVED, actor_user_id=actor_id,
            target_type="provider_key", target_id=slot, details={"slot": slot},
        )  # fmt: skip


async def resolve_credential(
    factory: Factory, vault: Vault | None, ctx: TenantContext, slot: Slot
) -> ResolvedCredential:
    """Decrypt a stored key for an outbound model call. Keep the result in memory only."""
    v = _require(vault)
    async with tenant_session(factory, ctx) as session:
        c = (
            await session.execute(
                select(ProviderCredential).where(
                    ProviderCredential.business_id == ctx.business_id,
                    ProviderCredential.slot == slot,
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise NotFoundError
        sealed = SealedSecret(c.ciphertext, c.wrapped_dek, c.master_key_id)
        api_key = v.decrypt(sealed, aad=_aad(ctx.business_id, c.id))
        if v.needs_rewrap(sealed):  # lazy rotation to the active master key
            fresh = v.encrypt(api_key, aad=_aad(ctx.business_id, c.id))
            c.ciphertext, c.wrapped_dek, c.master_key_id = (
                fresh.ciphertext, fresh.wrapped_dek, fresh.key_id,
            )  # fmt: skip
        return ResolvedCredential(Slot(c.slot), ProviderName(c.provider), c.model, api_key)


async def _locked(
    session: AsyncSession, ctx: TenantContext, slot: Slot
) -> ProviderCredential | None:
    return (
        await session.execute(
            select(ProviderCredential)
            .where(
                ProviderCredential.business_id == ctx.business_id, ProviderCredential.slot == slot
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


def _close(c: ProviderCredential, now: datetime) -> Transition | None:
    was_open = c.breaker_open_until is not None
    c.last_verified_at, c.last_error_kind = now, None
    c.failure_count, c.breaker_open_until, c.probe_until = 0, None, None
    return Transition.CLOSED if was_open else None


def _cooldown(kind: ErrorKind, failures: int) -> timedelta:
    if kind in (ErrorKind.AUTH, ErrorKind.QUOTA):
        return KEY_COOLDOWN
    doublings = min(max(0, failures - FAILURE_THRESHOLD), 10)
    return min(BASE_COOLDOWN * (1 << doublings), MAX_COOLDOWN)


async def admit(factory: Factory, ctx: TenantContext, slot: Slot) -> Admission:
    """May a model call use this key now? Claims the single half-open probe when due."""
    now = _now()
    async with tenant_session(factory, ctx) as session:
        c = await _locked(session, ctx, slot)
        if c is None:
            raise NotFoundError
        if c.breaker_open_until is None:
            return Admission.CLOSED
        if now < c.breaker_open_until or (c.probe_until is not None and now < c.probe_until):
            return Admission.OPEN
        c.probe_until = now + PROBE_LEASE
        return Admission.PROBE


async def record_outcome(
    factory: Factory, ctx: TenantContext, slot: Slot, error: ProviderError | None, *, probe: bool
) -> Transition | None:
    """Record a model call's result on the key's breaker; returns the transition, if any."""
    now = _now()
    async with tenant_session(factory, ctx) as session:
        c = await _locked(session, ctx, slot)
        if c is None:
            return None
        if error is None:
            transition = _close(c, now)
        elif not error.kind.availability_problem:
            # The provider answered; our request was wrong. Not a reason to trip the breaker.
            c.last_error_kind, c.probe_until = error.kind, None
            transition = None
        else:
            c.last_error_kind, c.last_failure_at = error.kind, now
            c.failure_count += 1
            trip = probe or c.failure_count >= FAILURE_THRESHOLD or error.kind in (
                ErrorKind.AUTH, ErrorKind.QUOTA)  # fmt: skip
            transition = None
            if trip:
                was_open = c.breaker_open_until is not None
                c.breaker_open_until = now + _cooldown(error.kind, c.failure_count)
                c.probe_until = None
                transition = Transition.REOPENED if was_open else Transition.OPENED
        provider = c.provider
    metrics.inc("agentree_llm_calls_total", provider=provider, slot=slot,
                outcome=error.kind if error else "ok")  # fmt: skip
    if transition is not None:
        metrics.inc("agentree_breaker_transitions_total", transition=transition)
        # Operational signal for monitoring: ids, provider and error kind only.
        logger.warning(
            "provider breaker %s", transition,
            extra={"business_id": str(ctx.business_id), "slot": slot, "provider": provider,
                   "error_kind": error.kind if error else None, "transition": transition},
        )  # fmt: skip
    return transition


async def record_check(
    factory: Factory, ctx: TenantContext, slot: Slot, error: ProviderError | None
) -> None:
    """Result of an owner's manual key test: success closes the breaker at once."""
    async with tenant_session(factory, ctx) as session:
        c = await _locked(session, ctx, slot)
        if c is None:
            return
        if error is None:
            _close(c, _now())
        else:
            c.last_error_kind = error.kind


async def health_counts(factory: Factory) -> dict[str, int]:
    """Platform-wide count of stored keys per breaker state (closed, open, half_open)."""
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text("SELECT state, keys FROM agentree_provider_health_counts(:now)"),
                {"now": _now()},
            )
        ).all()
    counts = {"closed": 0, "open": 0, "half_open": 0}
    counts.update({state: int(keys) for state, keys in rows})
    return counts
