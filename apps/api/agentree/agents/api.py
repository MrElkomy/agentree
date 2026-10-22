"""Agent endpoints: Sales Agent test console for business members."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from agentree.agents import events, service
from agentree.agents.schemas import (
    AgentReplyOut,
    ConsoleMessageIn,
    ConsoleReplyOut,
    HandoffOut,
    MessageOut,
    SourceOut,
)
from agentree.core import ratelimit, sse
from agentree.core.vault import VaultDecryptError, VaultUnavailableError
from agentree.tenancy.deps import Member

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["agents"])


async def _console_limit(request: Request, member: Member) -> None:
    # Protects the customer's own AI quota from runaway usage.
    if not await ratelimit.hit(
        request.app.state.session_factory,
        ratelimit.key_for("agent-console:business", str(member.tenant.business_id)),
        limit=300, window_seconds=3600,
    ):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")


def _turn_error(exc: Exception) -> HTTPException | None:
    if isinstance(exc, service.NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if isinstance(exc, service.NoAgentEnabledError):
        return HTTPException(status.HTTP_409_CONFLICT, "no_agent_enabled")
    if isinstance(exc, service.AgentNotAllowedError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_unavailable")
    if isinstance(exc, service.NoProviderConfiguredError):
        return HTTPException(status.HTTP_409_CONFLICT, "no_ai_provider_configured")
    if isinstance(exc, service.ProvidersUnavailableError):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "ai_unavailable", "errors": exc.kinds}
        )
    if isinstance(exc, (VaultUnavailableError, VaultDecryptError)):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "key_vault_unavailable")
    return None


def _reply_out(turn: service.TurnResult) -> ConsoleReplyOut:
    return ConsoleReplyOut(
        conversation_id=turn.conversation_id, reply=turn.reply,
        sources=[SourceOut(id=i, title=t) for i, t in turn.sources], provider=turn.provider,
        model=turn.model, slot=turn.slot, fallback_used=turn.fallback_used,
        agent=turn.agent, agent_name=turn.agent_name,
        replies=[AgentReplyOut(agent=r.agent, agent_name=r.name, content=r.content)
                 for r in turn.replies],
        handoffs=[HandoffOut(from_agent=h.from_agent, to_agent=h.to_agent)
                  for h in turn.handoffs],
    )  # fmt: skip


@router.post("/agents/sales/console")
async def sales_console(
    body: ConsoleMessageIn, member: Member, request: Request
) -> ConsoleReplyOut:
    await _console_limit(request, member)
    st = request.app.state
    try:
        turn = await service.sales_console_turn(
            st.session_factory, st.vault, st.llm_providers, member.tenant,
            user_id=member.user.id, message=body.message, conversation_id=body.conversation_id,
            agent=body.agent, extensions=getattr(st, "agent_extensions", None),
        )  # fmt: skip
    except Exception as exc:
        if (err := _turn_error(exc)) is None:
            raise
        raise err from None
    return _reply_out(turn)


def _console_event(item: service.StreamEvent | service.TurnResult) -> bytes:
    if isinstance(item, service.TurnResult):
        return sse.event("done", _reply_out(item).model_dump(mode="json"))
    return events.encode(item)


def _console_stream_error(exc: Exception) -> bytes | None:
    if (err := _turn_error(exc)) is None:
        return None
    detail = err.detail if isinstance(err.detail, dict) else {"code": err.detail}
    return sse.event("error", detail)


@router.post(
    "/agents/sales/console/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def sales_console_stream(
    body: ConsoleMessageIn, member: Member, request: Request
) -> StreamingResponse:
    """The console turn as server-sent events (see `agents/events.py`), then `done` / `error`."""
    await _console_limit(request, member)
    st = request.app.state
    items = service.stream_sales_console_turn(
        st.session_factory, st.vault, st.llm_providers, member.tenant,
        user_id=member.user.id, message=body.message, conversation_id=body.conversation_id,
        agent=body.agent, extensions=getattr(st, "agent_extensions", None),
    )  # fmt: skip
    try:
        first = await anext(items)
    except Exception as exc:
        if (err := _turn_error(exc)) is None:
            raise
        raise err from None
    return sse.stream_response(first, items, _console_event, _console_stream_error)


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
        MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at, agent=m.agent)
        for m in rows
    ]
