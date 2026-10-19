"""Sales Agent runtime (dashboard test console channel).

Turn: load history -> retrieve published knowledge -> build prompt -> call the customer's
primary provider, falling back to the backup slot on availability errors -> persist both
messages. Message content is never logged.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.agents.models import Conversation, Message
from agentree.agents.prompts import sales_messages
from agentree.core.ids import uuid7
from agentree.core.vault import Vault
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


class NoProviderConfiguredError(Exception):
    pass


class ProvidersUnavailableError(Exception):
    def __init__(self, kinds: list[str]) -> None:
        super().__init__("all configured providers failed")
        self.kinds = kinds


class NotFoundError(Exception):
    pass


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
    return [
        ChatMessage("user" if r.role == "user" else "assistant", r.content) for r in reversed(rows)
    ]


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


async def sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
) -> TurnResult:  # fmt: skip
    async with tenant_session(factory, ctx) as session:
        conv = await _conversation(session, ctx, conversation_id, user_id)
        history = await _history(session, ctx, conv.id)
        conv_id = conv.id
    business = await tenancy.get_business(factory, ctx)
    entries = await knowledge.retrieve(factory, ctx, message)
    prompt = sales_messages(business.name, entries, history, message)
    result, slot, fallback = await _call_with_fallback(
        factory, vault, ctx, provider_factories, prompt
    )

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
    return TurnResult(conv_id, result.text, [(e.id, e.title) for e in entries], result.provider,
                      result.model, slot, fallback)  # fmt: skip


async def list_messages(
    factory: Factory, ctx: TenantContext, conversation_id: UUID
) -> list[MessageInfo]:
    async with tenant_session(factory, ctx) as session:
        await _existing(session, ctx, conversation_id)
        rows = (
            await session.execute(
                select(Message)
                .where(
                    Message.business_id == ctx.business_id,
                    Message.conversation_id == conversation_id,
                )
                .order_by(Message.created_at, Message.id)
            )
        ).scalars().all()  # fmt: skip
    return [MessageInfo(m.id, m.role, m.content, m.created_at) for m in rows]
