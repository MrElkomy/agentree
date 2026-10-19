"""Agent endpoints: Sales Agent test console for business members."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from agentree.agents import service
from agentree.agents.schemas import ConsoleMessageIn, ConsoleReplyOut, MessageOut, SourceOut
from agentree.core import ratelimit
from agentree.core.vault import VaultDecryptError, VaultUnavailableError
from agentree.tenancy.deps import Member

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["agents"])


@router.post("/agents/sales/console")
async def sales_console(
    body: ConsoleMessageIn, member: Member, request: Request
) -> ConsoleReplyOut:
    st = request.app.state
    # Protects the customer's own AI quota from runaway usage.
    if not await ratelimit.hit(
        st.session_factory,
        ratelimit.key_for("agent-console:business", str(member.tenant.business_id)),
        limit=300, window_seconds=3600,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")
    try:
        turn = await service.sales_console_turn(
            st.session_factory, st.vault, st.llm_providers, member.tenant,
            user_id=member.user.id, message=body.message, conversation_id=body.conversation_id,
        )  # fmt: skip
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    except service.NoProviderConfiguredError:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_ai_provider_configured") from None
    except service.ProvidersUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "ai_unavailable", "errors": exc.kinds}
        ) from None
    except (VaultUnavailableError, VaultDecryptError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "key_vault_unavailable") from None
    return ConsoleReplyOut(
        conversation_id=turn.conversation_id, reply=turn.reply,
        sources=[SourceOut(id=i, title=t) for i, t in turn.sources], provider=turn.provider,
        model=turn.model, slot=turn.slot, fallback_used=turn.fallback_used,
    )  # fmt: skip


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: UUID, member: Member, request: Request
) -> list[MessageOut]:
    try:
        rows = await service.list_messages(
            request.app.state.session_factory, member.tenant, conversation_id
        )
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    return [
        MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at) for m in rows
    ]
