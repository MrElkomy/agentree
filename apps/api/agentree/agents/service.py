"""Sales Agent runtime (dashboard test console, public page and website widget).

Turn: load history -> retrieve published knowledge -> build prompt -> call the customer's
primary provider, falling back to the backup slot on availability errors -> persist both
messages. Message content is never logged.
"""

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.agents.inbox import mark_handoff_requested
from agentree.agents.models import Conversation, Message
from agentree.agents.prompts import (
    LeadSuggestion,
    sales_messages,
    split_lead_marker,
    take_handoff_marker,
)
from agentree.core.ids import uuid7
from agentree.core.vault import Vault, VaultDecryptError, VaultUnavailableError
from agentree.knowledge import service as knowledge
from agentree.llm.base import (
    ChatMessage,
    ChatRequest,
    ChatResult,
    ErrorKind,
    LLMProvider,
    ProviderError,
    ProviderName,
    TextDelta,
)
from agentree.providers import service as providers
from agentree.tenancy import service as tenancy
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]
ProviderFactories = dict[ProviderName, Callable[[], LLMProvider]]

HISTORY_TURNS = 20
SALES = "sales"
PUBLIC_CHANNELS = frozenset({"public", "widget"})
PAUSED_STATUSES = frozenset({"needs_human", "human_active"})  # the AI does not answer


class NoProviderConfiguredError(Exception):
    pass


class ProvidersUnavailableError(Exception):
    def __init__(self, kinds: list[str]) -> None:
        super().__init__("all configured providers failed")
        self.kinds = kinds


class NotFoundError(Exception):
    pass


class AgentUnavailableError(Exception):
    """Public channels: the agent cannot answer right now. Deliberately carries no detail."""


@dataclass(frozen=True)
class TurnResult:
    conversation_id: UUID
    reply: str
    sources: list[tuple[UUID, str]]
    provider: str
    model: str
    slot: str
    fallback_used: bool


@dataclass(frozen=True)
class GuestTurnResult:
    conversation_id: UUID
    reply: str  # empty when a person is handling the conversation (the AI did not answer)
    lead_suggestion: LeadSuggestion | None = None
    status: str = "open"  # conversation status after this turn
    handoff_requested: bool = False  # this turn moved the conversation to needs_human


@dataclass(frozen=True)
class MessageInfo:
    id: UUID
    role: str
    content: str
    created_at: datetime


async def _existing(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID
) -> Conversation:
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.business_id == ctx.business_id, Conversation.id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise NotFoundError
    return conv


async def _conversation(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID | None, user_id: UUID
) -> Conversation:
    if conversation_id is not None:
        return await _existing(session, ctx, conversation_id)
    conv = Conversation(id=uuid7(), business_id=ctx.business_id, channel="console",
                        active_agent=SALES, created_by_user_id=user_id)  # fmt: skip
    session.add(conv)
    await session.flush()
    return conv


async def _history(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID
) -> list[ChatMessage]:
    rows = (
        await session.execute(
            select(Message.role, Message.content)
            .where(
                Message.business_id == ctx.business_id, Message.conversation_id == conversation_id
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(HISTORY_TURNS)
        )
    ).all()
    # A team member's replies are context for the AI once the conversation returns to it.
    return [_as_chat(r.role, r.content) for r in reversed(rows)]


def _as_chat(role: str, content: str) -> ChatMessage:
    if role == "user":
        return ChatMessage("user", content)
    return ChatMessage("assistant", f"[Team member] {content}" if role == "human" else content)


@dataclass(frozen=True)
class Delta:
    """Visible reply text, streamed as the model writes it (markers withheld)."""

    text: str


@dataclass(frozen=True)
class Restart:
    """The provider failed mid-reply and the backup key answers: discard the partial text."""


@dataclass(frozen=True)
class _Answered:
    result: ChatResult
    slot: str
    fallback: bool


@dataclass(frozen=True)
class _TurnDone:
    result: ChatResult
    sources: list[tuple[UUID, str]]
    slot: str
    fallback: bool
    suggestion: LeadSuggestion | None
    handoff: bool


class _MarkerGuard:
    """Holds back streamed text from the first `<<` on: it may open a lead or handoff marker.

    The final reply (markers removed, see prompts.py) replaces the streamed text anyway, so
    withholding a legitimate `<<` only delays it until the end of the turn.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._held = False

    def feed(self, text: str) -> str:
        if self._held:
            return ""
        buf = self._pending + text
        cut = buf.find("<<")
        if cut >= 0:
            self._held, self._pending = True, ""
            return buf[:cut]
        if buf.endswith("<"):  # might become "<<" with the next piece
            self._pending = "<"
            return buf[:-1]
        self._pending = ""
        return buf


async def _stream_with_fallback(
    factory: Factory, vault: Vault | None, ctx: TenantContext,
    provider_factories: ProviderFactories, messages: list[ChatMessage],
) -> AsyncIterator[TextDelta | Restart | _Answered]:  # fmt: skip
    """Stream from the first usable key: primary, else backup.

    Keys whose circuit breaker is open are skipped; an open key past its cooldown gets this
    call as its probe. Availability errors move on to the next key, also mid-reply (after a
    Restart). Nothing is persisted here.
    """
    configured = {c.slot for c in await providers.list_credentials(factory, ctx)}
    order = [s for s in (providers.Slot.PRIMARY, providers.Slot.BACKUP) if s in configured]
    if not order:
        raise NoProviderConfiguredError
    failures: list[str] = []
    started = False
    for slot in order:
        admission = await providers.admit(factory, ctx, slot)
        if admission is providers.Admission.OPEN:
            failures.append("circuit_open")
            continue
        probe = admission is providers.Admission.PROBE
        cred = await providers.resolve_credential(factory, vault, ctx, slot)
        llm = provider_factories[cred.provider]()
        result: ChatResult | None = None
        try:
            async for item in llm.stream(cred.api_key, ChatRequest(model=cred.model,
                                                                   messages=messages)):  # fmt: skip
                if isinstance(item, TextDelta):
                    if not started:
                        started = True
                    yield item
                else:
                    result = item
            if result is None:  # stream ended without a final result
                raise ProviderError(cred.provider, ErrorKind.UNAVAILABLE)
        except ProviderError as exc:
            failures.append(exc.kind)
            await providers.record_outcome(factory, ctx, slot, exc, probe=probe)
            logger.warning(
                "provider call failed",
                extra={"slot": slot, "provider": cred.provider, "kind": exc.kind,
                       "mid_stream": started},
            )  # fmt: skip
            if not exc.kind.availability_problem:
                break  # our request is wrong; another provider will not fix it
            if started:
                yield Restart()
                started = False
            continue
        await providers.record_outcome(factory, ctx, slot, None, probe=probe)
        yield _Answered(result, slot, slot != order[0])
        return
    raise ProvidersUnavailableError(failures)


async def _stream_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, conv_id: UUID, history: list[ChatMessage], message: str, public: bool,
) -> AsyncIterator[Delta | Restart | _TurnDone]:  # fmt: skip
    """Retrieve published knowledge, stream the reply, persist both messages at the end.

    Lead and handoff markers are stripped before the reply is stored or returned; in public
    conversations a vetted lead suggestion is returned so the visitor can confirm it. A turn
    that fails stores nothing, so the visitor can simply send the message again.
    """
    business = await tenancy.get_business(factory, ctx)
    entries = await knowledge.retrieve(factory, ctx, message)
    prompt = sales_messages(business.name, entries, history, message, public=public)
    guard = _MarkerGuard()
    answered: _Answered | None = None
    async for item in _stream_with_fallback(factory, vault, ctx, provider_factories, prompt):
        if isinstance(item, TextDelta):
            visible = guard.feed(item.text)
            if visible:
                yield Delta(visible)
        elif isinstance(item, Restart):
            guard = _MarkerGuard()
            yield item
        else:
            answered = item
    if answered is None:  # _stream_with_fallback ends with _Answered or raises
        raise AssertionError("stream ended without an answer")
    visitor = [m.content for m in history if m.role == "user"] + [message]
    reply, suggestion = split_lead_marker(answered.result.text, visitor)
    reply, handoff = take_handoff_marker(reply)
    result = replace(answered.result, text=reply)

    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        session.add(Message(id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id,
                            role="user", content=message, created_at=now))  # fmt: skip
        session.add(
            Message(
                id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id, role="assistant",
                agent=SALES, content=result.text, provider=result.provider, model=result.model,
                provider_slot=answered.slot, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        conv_row = await session.get(Conversation, conv_id)
        if conv_row is not None:
            conv_row.last_message_at = now
    yield _TurnDone(
        result=result,
        sources=[(e.id, e.title) for e in entries],
        slot=answered.slot,
        fallback=answered.fallback,
        suggestion=suggestion if public else None,
        handoff=handoff and public,
    )


async def stream_sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
) -> AsyncIterator[Delta | Restart | TurnResult]:  # fmt: skip
    """Console turn as a stream: Delta/Restart items, then the TurnResult."""
    async with tenant_session(factory, ctx) as session:
        conv = await _conversation(session, ctx, conversation_id, user_id)
        history = await _history(session, ctx, conv.id)
        conv_id = conv.id
    async for item in _stream_turn(factory, vault, provider_factories, ctx, conv_id=conv_id,
                                   history=history, message=message, public=False):  # fmt: skip
        if isinstance(item, _TurnDone):
            yield TurnResult(conv_id, item.result.text, item.sources, item.result.provider,
                             item.result.model, item.slot, item.fallback)  # fmt: skip
        else:
            yield item


async def sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
) -> TurnResult:  # fmt: skip
    async for item in stream_sales_console_turn(
        factory, vault, provider_factories, ctx, user_id=user_id, message=message,
        conversation_id=conversation_id,
    ):  # fmt: skip
        if isinstance(item, TurnResult):
            return item
    raise AssertionError("turn ended without a result")


# --- public page / website widget (anonymous guest sessions) -----------------------------


async def _guest_conversation(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID, guest_session_id: UUID
) -> Conversation:
    """The conversation, only if it belongs to this guest session (else NotFoundError)."""
    conv = await _existing(session, ctx, conversation_id)
    if conv.guest_session_id is None or conv.guest_session_id != guest_session_id:
        raise NotFoundError
    return conv


async def stream_public_sales_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, guest_session_id: UUID, message: str, conversation_id: UUID | None,
    channel: str,
) -> AsyncIterator[Delta | Restart | GuestTurnResult]:  # fmt: skip
    """One Sales Agent turn for an anonymous visitor, as a stream ending in GuestTurnResult.

    The caller must have authenticated `guest_session_id` within `ctx`'s business. A
    conversation id that does not belong to that guest session is treated as not found.
    Only the reply is returned: provider, model, slot and sources stay internal. Any failure to
    answer surfaces as AgentUnavailableError, before or during the stream.
    """
    if channel not in PUBLIC_CHANNELS:
        raise ValueError("invalid public channel")
    async with tenant_session(factory, ctx) as session:
        if conversation_id is not None:
            conv = await _guest_conversation(session, ctx, conversation_id, guest_session_id)
        else:
            conv = Conversation(id=uuid7(), business_id=ctx.business_id, channel=channel,
                                active_agent=SALES, guest_session_id=guest_session_id)  # fmt: skip
            session.add(conv)
            await session.flush()
        paused = conv.status in PAUSED_STATUSES
        if paused:
            # A person is (or will be) answering: keep the message for them; the AI stays quiet.
            now = datetime.now(UTC)
            session.add(Message(id=uuid7(), business_id=ctx.business_id, conversation_id=conv.id,
                                role="user", content=message, created_at=now))  # fmt: skip
            conv.last_message_at = now
        elif conv.status == "resolved":
            conv.status = "open"  # the visitor came back: the AI answers again
        status, conv_id = conv.status, conv.id
        history = [] if paused else await _history(session, ctx, conv.id)
    if paused:
        yield GuestTurnResult(conv_id, "", status=status)
        return
    done: _TurnDone | None = None
    try:
        async for item in _stream_turn(factory, vault, provider_factories, ctx, conv_id=conv_id,
                                       history=history, message=message, public=True):  # fmt: skip
            if isinstance(item, _TurnDone):
                done = item
            else:
                yield item
    except (NoProviderConfiguredError, ProvidersUnavailableError, providers.NotFoundError,
            VaultUnavailableError, VaultDecryptError) as exc:  # fmt: skip
        # Visitors never learn why (no provider, outage, quota, vault): owners see the
        # provider status in the dashboard. Only the error type is logged.
        logger.warning("public agent unavailable", extra={"error_type": type(exc).__name__,
                       "business_id": str(ctx.business_id)})  # fmt: skip
        raise AgentUnavailableError from None
    if done is None:
        raise AssertionError("turn ended without a result")
    if done.handoff:
        requested = await mark_handoff_requested(factory, ctx, conv_id, reason="agent")
        yield GuestTurnResult(conv_id, done.result.text, done.suggestion, status="needs_human",
                              handoff_requested=requested)  # fmt: skip
        return
    yield GuestTurnResult(conv_id, done.result.text, done.suggestion)


async def public_sales_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, guest_session_id: UUID, message: str, conversation_id: UUID | None,
    channel: str,
) -> GuestTurnResult:  # fmt: skip
    async for item in stream_public_sales_turn(
        factory, vault, provider_factories, ctx, guest_session_id=guest_session_id,
        message=message, conversation_id=conversation_id, channel=channel,
    ):  # fmt: skip
        if isinstance(item, GuestTurnResult):
            return item
    raise AssertionError("turn ended without a result")


async def guest_conversation_channel(
    factory: Factory, ctx: TenantContext, *, guest_session_id: UUID, conversation_id: UUID
) -> str:
    """Channel of a conversation owned by this guest session (else NotFoundError)."""
    async with tenant_session(factory, ctx) as session:
        conv = await _guest_conversation(session, ctx, conversation_id, guest_session_id)
        return conv.channel


async def list_guest_messages(
    factory: Factory, ctx: TenantContext, *, guest_session_id: UUID, conversation_id: UUID
) -> list[MessageInfo]:
    """Messages of a conversation owned by this guest session (else NotFoundError)."""
    async with tenant_session(factory, ctx) as session:
        await _guest_conversation(session, ctx, conversation_id, guest_session_id)
        return await _messages(session, ctx, conversation_id)


async def _messages(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID
) -> list[MessageInfo]:
    rows = (
        await session.execute(
            select(Message)
            .where(
                Message.business_id == ctx.business_id, Message.conversation_id == conversation_id
            )
            .order_by(Message.created_at, Message.id)
        )
    ).scalars().all()  # fmt: skip
    return [MessageInfo(m.id, m.role, m.content, m.created_at) for m in rows]


async def list_messages(
    factory: Factory, ctx: TenantContext, conversation_id: UUID
) -> list[MessageInfo]:
    async with tenant_session(factory, ctx) as session:
        await _existing(session, ctx, conversation_id)
        return await _messages(session, ctx, conversation_id)
