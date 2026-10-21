"""Sales Agent runtime (dashboard test console, public page and website widget).

Turn: load history -> retrieve published knowledge -> build prompt -> call the customer's
primary provider, falling back to the backup slot on availability errors -> persist both
messages. Message content is never logged.
"""

import logging
from collections.abc import Callable
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
    LLMProvider,
    ProviderError,
    ProviderName,
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


async def _call_with_fallback(
    factory: Factory, vault: Vault | None, ctx: TenantContext,
    provider_factories: ProviderFactories, messages: list[ChatMessage],
) -> tuple[ChatResult, str, bool]:  # fmt: skip
    configured = {c.slot for c in await providers.list_credentials(factory, ctx)}
    order = [s for s in (providers.Slot.PRIMARY, providers.Slot.BACKUP) if s in configured]
    if not order:
        raise NoProviderConfiguredError
    failures: list[str] = []
    for i, slot in enumerate(order):
        cred = await providers.resolve_credential(factory, vault, ctx, slot)
        llm = provider_factories[cred.provider]()
        try:
            result = await llm.chat(cred.api_key, ChatRequest(model=cred.model, messages=messages))
        except ProviderError as exc:
            failures.append(exc.kind)
            await providers.record_check(factory, ctx, slot, exc)
            logger.warning(
                "provider call failed",
                extra={"slot": slot, "provider": cred.provider, "kind": exc.kind},
            )
            if exc.kind.availability_problem:
                continue
            break  # our request is wrong; another provider will not fix it
        return result, slot, i > 0
    raise ProvidersUnavailableError(failures)


async def _complete_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, conv_id: UUID, history: list[ChatMessage], message: str, public: bool,
) -> tuple[ChatResult, list[tuple[UUID, str]], str, bool, LeadSuggestion | None, bool]:  # fmt: skip
    """Retrieve published knowledge, call the provider(s), persist both messages.

    Lead markers are stripped before the reply is stored or returned; in public conversations a
    vetted suggestion is returned so the visitor can confirm their details in a form.
    """
    business = await tenancy.get_business(factory, ctx)
    entries = await knowledge.retrieve(factory, ctx, message)
    prompt = sales_messages(business.name, entries, history, message, public=public)
    result, slot, fallback = await _call_with_fallback(
        factory, vault, ctx, provider_factories, prompt
    )
    visitor = [m.content for m in history if m.role == "user"] + [message]
    reply, suggestion = split_lead_marker(result.text, visitor)
    reply, handoff = take_handoff_marker(reply)
    result = replace(result, text=reply)

    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        session.add(Message(id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id,
                            role="user", content=message, created_at=now))  # fmt: skip
        session.add(
            Message(
                id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id, role="assistant",
                agent=SALES, content=result.text, provider=result.provider, model=result.model,
                provider_slot=slot, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        conv_row = await session.get(Conversation, conv_id)
        if conv_row is not None:
            conv_row.last_message_at = now
    return (
        result,
        [(e.id, e.title) for e in entries],
        slot,
        fallback,
        suggestion if public else None,
        handoff and public,
    )


async def sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
) -> TurnResult:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        conv = await _conversation(session, ctx, conversation_id, user_id)
        history = await _history(session, ctx, conv.id)
        conv_id = conv.id
    result, sources, slot, fallback, _suggestion, _handoff = await _complete_turn(
        factory, vault, provider_factories, ctx, conv_id=conv_id, history=history,
        message=message, public=False,
    )  # fmt: skip
    return TurnResult(conv_id, result.text, sources, result.provider, result.model, slot,
                      fallback)  # fmt: skip


# --- public page / website widget (anonymous guest sessions) -----------------------------


async def _guest_conversation(
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID, guest_session_id: UUID
) -> Conversation:
    """The conversation, only if it belongs to this guest session (else NotFoundError)."""
    conv = await _existing(session, ctx, conversation_id)
    if conv.guest_session_id is None or conv.guest_session_id != guest_session_id:
        raise NotFoundError
    return conv


async def public_sales_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, guest_session_id: UUID, message: str, conversation_id: UUID | None,
    channel: str,
) -> GuestTurnResult:  # fmt: skip
    """One Sales Agent turn for an anonymous visitor.

    The caller must have authenticated `guest_session_id` within `ctx`'s business. A
    conversation id that does not belong to that guest session is treated as not found.
    Only the reply is returned: provider, model, slot and sources stay internal.
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
        if conv.status in PAUSED_STATUSES:
            # A person is (or will be) answering: keep the message for them; the AI stays quiet.
            now = datetime.now(UTC)
            session.add(Message(id=uuid7(), business_id=ctx.business_id, conversation_id=conv.id,
                                role="user", content=message, created_at=now))  # fmt: skip
            conv.last_message_at = now
            return GuestTurnResult(conv.id, "", status=conv.status)
        if conv.status == "resolved":
            conv.status = "open"  # the visitor came back: the AI answers again
        history = await _history(session, ctx, conv.id)
        conv_id = conv.id
    try:
        result, _sources, _slot, _fallback, suggestion, handoff = await _complete_turn(
            factory, vault, provider_factories, ctx, conv_id=conv_id, history=history,
            message=message, public=True,
        )  # fmt: skip
    except (NoProviderConfiguredError, ProvidersUnavailableError, providers.NotFoundError,
            VaultUnavailableError, VaultDecryptError) as exc:  # fmt: skip
        # Visitors never learn why (no provider, outage, quota, vault): owners see the
        # provider status in the dashboard. Only the error type is logged.
        logger.warning("public agent unavailable", extra={"error_type": type(exc).__name__,
                       "business_id": str(ctx.business_id)})  # fmt: skip
        raise AgentUnavailableError from None
    if handoff:
        requested = await mark_handoff_requested(factory, ctx, conv_id, reason="agent")
        return GuestTurnResult(conv_id, result.text, suggestion, status="needs_human",
                               handoff_requested=requested)  # fmt: skip
    return GuestTurnResult(conv_id, result.text, suggestion)


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
