"""BYOK provider credentials: store, list, verify, and resolve keys for model calls.

Plaintext keys exist only in memory: on the way in (encrypt) and when a model call needs
them (decrypt). They are never returned to clients, logged, or stored unencrypted.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.config import Settings
from agentree.core.ids import uuid7
from agentree.core.vault import SealedSecret, Vault, VaultUnavailableError, parse_master_key
from agentree.llm.base import (
    MODEL_RE,
    ChatMessage,
    ChatRequest,
    LLMProvider,
    ProviderError,
    ProviderName,
)
from agentree.providers.models import ProviderCredential
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

Factory = async_sessionmaker[AsyncSession]


class Slot(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"


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
        await session.execute(
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
    return _info(cred)


def _info(c: ProviderCredential) -> CredentialInfo:
    return CredentialInfo(
        slot=Slot(c.slot), provider=ProviderName(c.provider), model=c.model,
        key_hint=c.key_hint, last_verified_at=c.last_verified_at,
        last_error_kind=c.last_error_kind, updated_at=c.updated_at,
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


async def delete_credential(factory: Factory, ctx: TenantContext, slot: Slot) -> None:
    async with tenant_session(factory, ctx) as session:
        result = await session.execute(
            delete(ProviderCredential).where(
                ProviderCredential.business_id == ctx.business_id, ProviderCredential.slot == slot
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFoundError


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


async def record_check(
    factory: Factory, ctx: TenantContext, slot: Slot, error: ProviderError | None
) -> None:
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
            return
        if error is None:
            c.last_verified_at, c.last_error_kind = datetime.now(UTC), None
        else:
            c.last_error_kind = error.kind
