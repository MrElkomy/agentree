"""BYOK provider credential endpoints. Keys are write-only from the client's perspective."""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from agentree.core import metrics, ratelimit
from agentree.core.vault import VaultDecryptError, VaultUnavailableError
from agentree.llm.base import ErrorKind, LLMProvider, ProviderError, ProviderName
from agentree.providers import service
from agentree.providers.schemas import CheckOut, CredentialIn, CredentialOut
from agentree.providers.service import Slot
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/businesses/{business_id}/ai-providers", tags=["ai-providers"])
metrics_router = APIRouter(prefix="/api/internal", tags=["monitoring"])


def _provider(request: Request, name: ProviderName) -> LLMProvider:
    return request.app.state.llm_providers[name]()  # type: ignore[no-any-return]


def _out(c: service.CredentialInfo) -> CredentialOut:
    return CredentialOut(
        slot=c.slot, provider=c.provider, model=c.model, key_hint=c.key_hint,
        last_verified_at=c.last_verified_at, last_error_kind=c.last_error_kind,
        updated_at=c.updated_at, health=c.health, last_failure_at=c.last_failure_at,
        breaker_open_until=c.breaker_open_until,
    )  # fmt: skip


def _vault_unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "key_vault_unavailable")


async def _limit(request: Request, member: Member) -> None:
    if not await ratelimit.hit(
        request.app.state.session_factory,
        ratelimit.key_for("ai-provider-write:business", str(member.tenant.business_id)),
        limit=30, window_seconds=3600,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")


@router.get("")
async def list_providers(member: Member, request: Request) -> list[CredentialOut]:
    rows = await service.list_credentials(request.app.state.session_factory, member.tenant)
    return [_out(c) for c in rows]


@router.put("/{slot}")
async def save_provider(
    slot: Slot, body: CredentialIn, member: Member, request: Request
) -> CredentialOut:
    member.require(Role.ADMIN)
    await _limit(request, member)
    try:
        name, model, key = service.validate_input(body.provider, body.model, body.api_key)
    except service.InvalidCredentialError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if body.verify:
        try:
            await service.verify_key(_provider(request, name), key, model)
        except ProviderError as exc:
            logger.info(
                "provider key verification failed", extra={"provider": name, "kind": exc.kind}
            )
            if exc.kind is ErrorKind.AUTH:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "key_rejected") from None
            if exc.kind is ErrorKind.BAD_REQUEST:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "model_rejected"
                ) from None
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"provider_{exc.kind}") from None
    try:
        info = await service.save_credential(
            request.app.state.session_factory, request.app.state.vault, member.tenant,
            slot=slot, provider=name, model=model, api_key=key, actor_id=member.user.id,
            verified=body.verify,
        )  # fmt: skip
    except VaultUnavailableError:
        raise _vault_unavailable() from None
    return _out(info)


@router.delete("/{slot}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(slot: Slot, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_credential(
            request.app.state.session_factory, member.tenant, slot, actor_id=member.user.id
        )
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None


@router.post("/{slot}/test")
async def test_provider(slot: Slot, member: Member, request: Request) -> CheckOut:
    member.require(Role.ADMIN)
    await _limit(request, member)
    factory = request.app.state.session_factory
    try:
        cred = await service.resolve_credential(
            factory, request.app.state.vault, member.tenant, slot
        )
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    except VaultUnavailableError:
        raise _vault_unavailable() from None
    except VaultDecryptError:
        logger.error("stored provider key cannot be decrypted", extra={"slot": slot})
        raise HTTPException(status.HTTP_409_CONFLICT, "key_unreadable_reenter") from None
    try:
        await service.verify_key(_provider(request, cred.provider), cred.api_key, cred.model)
    except ProviderError as exc:
        await service.record_check(factory, member.tenant, slot, exc)
        return CheckOut(ok=False, error_kind=exc.kind)
    await service.record_check(factory, member.tenant, slot, None)
    return CheckOut(ok=True)


@metrics_router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def monitoring_metrics(
    request: Request,
    token: Annotated[str | None, Header(alias="X-Agentree-Metrics-Token")] = None,
) -> str:
    """Prometheus-format counters for monitoring (token-protected; 404 when disabled)."""
    expected = request.app.state.settings.metrics_token
    if (
        expected is None
        or token is None
        or not secrets.compare_digest(token.encode(), expected.get_secret_value().encode())
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    counts = await service.health_counts(request.app.state.session_factory)
    return metrics.render(
        {
            "agentree_provider_keys": (
                "Stored provider keys by circuit breaker state.",
                [({"state": state}, n) for state, n in sorted(counts.items())],
            )
        }
    )
