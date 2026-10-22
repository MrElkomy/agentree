"""Agent runtime (dashboard test console, public page and website widget).

Turn: pick the agent (the conversation's active agent if still allowed, else the entry agent)
-> load history and team context -> retrieve published knowledge -> stream the reply from the
customer's primary provider, falling back to the backup key -> if the agent hands the
conversation to an allowed teammate, that teammate answers the same message -> persist the
messages, handoffs and the new active agent. Which agents exist, who may reach them and what
tools they hold come from `configs` (never from model output). Message content is never logged.
"""

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.actions import service as gateway
from agentree.actions.service import Action
from agentree.agents import configs, inbox
from agentree.agents.inbox import mark_handoff_requested
from agentree.agents.models import AgentHandoff, Conversation, Message
from agentree.agents.prompts import (
    CustomerFacts,
    HandoffNote,
    LeadSuggestion,
    RememberedFact,
    Teammate,
    agent_messages,
    cited_numbers_ok,
    split_lead_marker,
    take_handoff_marker,
    take_resolve_marker,
    take_route_marker,
    take_sql_marker,
)
from agentree.agents.registry import DEFINITIONS, AgentRole
from agentree.analytics import service as analytics
from agentree.audit.service import AuditAction, record
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
SALES = AgentRole.SALES
MAX_ROUTES_PER_TURN = 1  # one handoff per visitor message: no ping-pong between agents
MAX_NOTES = 3  # latest handoff notes shown to the answering agent
QUERY_UNANSWERED = "I couldn't finish that calculation. Here are the computed numbers:\n\n"
MAX_QUERIES_PER_TURN = 1  # uploaded-table queries the Data Analyst may ask for (Task 18b)
MAX_RESULT_ROWS_SHOWN = 50
UNVERIFIED_NUMBERS = (
    "I can only share numbers computed from your data, and my answer had one I couldn't "
    "verify. Here are the computed numbers:\n\n"
)
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


class NoAgentEnabledError(Exception):
    """Console: no agent of this business may answer (all disabled)."""


class AgentNotAllowedError(Exception):
    """The requested entry agent is unknown, disabled or not reachable by this caller."""


@dataclass(frozen=True)
class AgentReply:
    agent: str  # role
    name: str  # display name (cosmetic)
    content: str


@dataclass(frozen=True)
class HandoffInfo:
    from_agent: str
    to_agent: str


@dataclass(frozen=True)
class TurnResult:
    conversation_id: UUID
    reply: str  # the last agent's reply
    sources: list[tuple[UUID, str]]
    provider: str
    model: str
    slot: str
    fallback_used: bool
    agent: str = SALES  # the agent that answered last (now active)
    agent_name: str = "Sales Agent"
    replies: list[AgentReply] = field(default_factory=list)
    handoffs: list[HandoffInfo] = field(default_factory=list)


@dataclass(frozen=True)
class GuestTurnResult:
    conversation_id: UUID
    reply: str  # empty when a person is handling the conversation (the AI did not answer)
    lead_suggestion: LeadSuggestion | None = None
    status: str = "open"  # conversation status after this turn
    handoff_requested: bool = False  # this turn moved the conversation to needs_human
    agent: str | None = None  # the agent that answered last (None: the AI did not answer)
    agent_name: str | None = None
    replies: list[AgentReply] = field(default_factory=list)
    can_resolve: bool = False  # the visitor may mark the conversation resolved now


@dataclass(frozen=True)
class MessageInfo:
    id: UUID
    role: str
    content: str
    created_at: datetime
    agent: str | None = None


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
    session: AsyncSession, ctx: TenantContext, conversation_id: UUID | None, user_id: UUID,
    entry: AgentRole,
) -> Conversation:  # fmt: skip
    if conversation_id is not None:
        return await _existing(session, ctx, conversation_id)
    conv = Conversation(id=uuid7(), business_id=ctx.business_id, channel="console",
                        active_agent=entry, created_by_user_id=user_id)  # fmt: skip
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
class AgentStart:
    """The text that follows comes from this agent (a new reply in the chat)."""

    agent: str
    name: str


@dataclass(frozen=True)
class Handoff:
    """The previous agent handed the conversation to `to_agent`, which now answers."""

    from_agent: str
    to_agent: str
    to_name: str


StreamEvent = AgentStart | Delta | Restart | Handoff


@dataclass(frozen=True)
class _TurnDone:
    agent: configs.AgentConfigInfo  # answered last; now the conversation's active agent
    result: ChatResult  # the last provider call
    replies: list[AgentReply]
    handoffs: list[HandoffInfo]
    sources: list[tuple[UUID, str]]
    slot: str
    fallback: bool
    suggestion: LeadSuggestion | None
    handoff: bool  # the agent asked for a person (public conversations)
    resolved: bool = False  # the last agent, allowed to, marked the conversation resolved


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
    call as its probe. Availability errors move on to the next key, also mid-reply: a Restart
    precedes the backup's first text, so if no key answers the partial text stays on screen
    for the error. Nothing is persisted here.
    """
    configured = {c.slot for c in await providers.list_credentials(factory, ctx)}
    order = [s for s in (providers.Slot.PRIMARY, providers.Slot.BACKUP) if s in configured]
    if not order:
        raise NoProviderConfiguredError
    failures: list[str] = []
    started = False  # text from the current key has been yielded
    shown = False  # text from an earlier, failed key is on screen
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
                    if shown and not started:
                        # Only now that the backup answers: replace the broken-off text.
                        yield Restart()
                        shown = False
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
                shown, started = True, False
            continue
        await providers.record_outcome(factory, ctx, slot, None, probe=probe)
        yield _Answered(result, slot, slot != order[0])
        return
    raise ProvidersUnavailableError(failures)


async def _notes(session: AsyncSession, ctx: TenantContext, conv_id: UUID) -> list[HandoffNote]:
    rows = (
        await session.execute(
            select(AgentHandoff.from_agent, AgentHandoff.note)
            .where(AgentHandoff.business_id == ctx.business_id,
                   AgentHandoff.conversation_id == conv_id)
            .order_by(AgentHandoff.created_at.desc(), AgentHandoff.id.desc())
            .limit(MAX_NOTES)
        )
    ).all()  # fmt: skip
    return [
        HandoffNote(DEFINITIONS[AgentRole(r.from_agent)].title, r.note)
        for r in reversed(rows) if r.note
    ]  # fmt: skip


def _may_resolve(agent: configs.AgentConfigInfo) -> bool:
    """Shared-resolution role holding the resolve tool in this business (Action Gateway)."""
    if not agent.definition.shared_resolution:
        return False
    try:
        gateway.authorize(agent.role, Action.RESOLVE_CONVERSATION, agent.effective_tools)
    except gateway.ActionDeniedError:
        return False
    return True


def _flat(value: object, limit: int = 80) -> str:
    """A file-provided value or name on one line, without markers (it is untrusted data)."""
    if isinstance(value, float):
        value = round(value, 2)
    return " ".join(str("" if value is None else value).replace("<<", "").replace(">>", "")
                    .split())[:limit]  # fmt: skip


def _tables_text(tables: dict[str, "knowledge.Dataset"]) -> tuple[str, str]:
    """The uploaded tables for the analyst's prompt, and their row counts (checked numbers).
    Names may contain digits, so only the counts count as computed numbers."""
    if not tables:
        return "", ""
    lines = ["", "Uploaded tables (query them with SQL on the table `data`):"]
    counts = [""]
    for label, d in tables.items():
        columns = ", ".join(f"{_flat(c.get('name'), 40)} ({_flat(c.get('type'), 10)})"
                            for c in d.columns)  # fmt: skip
        lines.append(f"- {label}: file {_flat(d.filename, 120)}; {d.rows} rows; columns: {columns}")
        counts.append(f"{d.rows}")
    return "\n".join(lines), "\n".join(counts)


async def _run_query(
    factory: Factory, ctx: TenantContext, tables: dict[str, "knowledge.Dataset"], label: str,
    sql: str,
) -> tuple[str, str]:  # fmt: skip
    """Run the analyst's query in the sandbox: (text for the prompt, result values to check)."""
    head = f"\nQuery on {label}: {_flat(sql, 4000)}\n"
    table = tables.get(label)
    if table is None:
        return head + "Result: failed (no table with that label).", ""
    result, error = await knowledge.query_dataset(factory, ctx, table.file_id, sql)
    logger.info("analyst table query", extra={"ok": result is not None, "error": error})
    if result is None:
        return head + f"Result: failed ({error}). Do not guess the answer.", ""
    rows = result.rows[:MAX_RESULT_ROWS_SHOWN]
    cells = [[_flat(v) for v in row] for row in rows]
    lines = [" | ".join(_flat(c, 40) for c in result.columns), *(" | ".join(r) for r in cells)]
    more = len(result.rows) > len(rows) or result.truncated
    note = f"Result ({len(rows)} rows{', more not shown' if more else ''}):\n"
    return head + note + "\n".join(lines), "\n".join(" ".join(r) for r in cells)


def _active(roster: configs.Roster, current: str, *, guest: bool) -> configs.AgentConfigInfo | None:
    """The conversation's active agent if it may still answer, else the default entry agent."""
    if roster.allowed(current, guest=guest):
        return roster.config(current)
    return roster.entry(None, guest=guest)


async def _stream_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, conv_id: UUID, channel: str, history: list[ChatMessage],
    message: str, roster: configs.Roster, agent: configs.AgentConfigInfo, guest: bool,
    public: bool, notes: list[HandoffNote], facts: CustomerFacts | None,
    remembered: Sequence[RememberedFact] = (),
) -> AsyncIterator[StreamEvent | _TurnDone]:  # fmt: skip
    """Stream one turn, routing at most once to an allowed teammate; persist at the end.

    The model can only propose a teammate by role name: `take_route_marker` accepts it only
    if it is in the roster's list of enabled agents this caller may reach (guests: public
    agents only). Lead and handoff markers are stripped; a lead suggestion is kept only from
    an agent holding the create_lead tool, and a resolve proposal only from the last agent if
    it may resolve (`_may_resolve`). Each agent sees only knowledge open to its role. A turn that
    fails stores nothing (no messages, no handoff, active agent unchanged), so the visitor can
    simply send the message again.
    """
    business = await tenancy.get_business(factory, ctx)
    entries: list[knowledge.RetrievedEntry] = []
    sources: dict[UUID, str] = {}
    visitor = [m.content for m in history if m.role == "user"] + [message]
    current = agent
    calls: list[tuple[configs.AgentConfigInfo, _Answered, str]] = []
    handoffs: list[tuple[configs.AgentConfigInfo, configs.AgentConfigInfo, str]] = []
    suggestion: LeadSuggestion | None = None
    wants_person = False
    resolved = False
    for hop in range(MAX_ROUTES_PER_TURN + 1):
        targets = roster.targets(current.role, guest=guest) if hop < MAX_ROUTES_PER_TURN else []
        lead_capture = public and Action.CREATE_LEAD in current.effective_tools
        can_resolve = public and _may_resolve(current)
        entries = await knowledge.retrieve(factory, ctx, message, role=current.role)
        sources.update((e.id, e.title) for e in entries)
        # The Data Analyst states only numbers the backend computed (Task 18): the Agentree
        # numbers, and what its uploaded-table queries return (Task 18b, run in a sandbox).
        computed, checked = "", ""
        tables: dict[str, knowledge.Dataset] = {}
        if current.role == AgentRole.DATA_ANALYST:
            computed = await analytics.analyst_numbers(factory, ctx)
            tables = {f"d{i}": d for i, d in enumerate(await knowledge.datasets(factory, ctx), 1)}
            listed, counts = _tables_text(tables)
            computed, checked = computed + listed, computed + counts
        queries = MAX_QUERIES_PER_TURN if tables else 0
        # Announced with its first text: errors before any text stay plain HTTP errors, and
        # an agent that only hands over shows no empty reply.
        start: AgentStart | None = AgentStart(current.role, current.name)
        used: list[ChatResult] = []
        while True:
            prompt = agent_messages(
                current.role, title=current.definition.title,
                display_name=current.display_name, business_name=business.name,
                knowledge=entries, history=history, user_message=message, public=public,
                lead_capture=lead_capture, can_resolve=can_resolve, joined=hop > 0,
                teammates=[Teammate(t.role, t.definition.handles) for t in targets],
                notes=notes, facts=facts,
                # Only the memory categories this role may read (registry), checked per agent.
                remembered=[r for r in remembered if r.category in current.definition.memory],
                computed=computed, can_query=queries > 0,
            )  # fmt: skip
            guard = _MarkerGuard()
            shown = False
            answered: _Answered | None = None
            async for item in _stream_with_fallback(
                factory, vault, ctx, provider_factories, prompt
            ):
                if isinstance(item, TextDelta):
                    visible = guard.feed(item.text)
                    if visible:
                        if start is not None:
                            yield start
                            start = None
                        shown = True
                        yield Delta(visible)
                elif isinstance(item, Restart):
                    guard = _MarkerGuard()
                    yield item
                else:
                    answered = item
            if answered is None:  # _stream_with_fallback ends with _Answered or raises
                raise AssertionError("stream ended without an answer")
            used.append(answered.result)
            reply, asked = take_sql_marker(answered.result.text)
            if asked is None or queries == 0:
                break
            queries -= 1
            shown_text, values = await _run_query(factory, ctx, tables, *asked)
            computed, checked = computed + shown_text, checked + values
            if shown:  # text written before the query is replaced by the answer
                yield Restart()
        # Every call of this agent counts toward its reply's usage.
        answered = replace(answered, result=replace(
            answered.result, input_tokens=sum(r.input_tokens for r in used),
            output_tokens=sum(r.output_tokens for r in used)))  # fmt: skip
        text, target, note = take_route_marker(reply, [t.role for t in targets])
        text, lead = split_lead_marker(text, visitor)
        if lead_capture and lead is not None:
            suggestion = lead
        text, person = take_handoff_marker(text)
        text, done_marker = take_resolve_marker(text)
        if computed and not text and target is None:
            text = QUERY_UNANSWERED + computed
        elif computed and not cited_numbers_ok(text, checked, message):
            # A number the backend did not compute: show the computed ones instead.
            text = UNVERIFIED_NUMBERS + computed
        wants_person = wants_person or (public and person and target is None)
        resolved = can_resolve and done_marker and target is None and not person
        calls.append((current, answered, text))
        nxt = roster.config(target) if target is not None else None
        if nxt is None:
            break
        handoffs.append((current, nxt, note))
        yield Handoff(current.role, nxt.role, nxt.name)
        notes = [*notes, HandoffNote(current.definition.title, note)][-MAX_NOTES:]
        current = nxt

    now = datetime.now(UTC)
    async with tenant_session(factory, ctx) as session:
        session.add(Message(id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id,
                            role="user", content=message, created_at=now))  # fmt: skip
        for i, (cfg, ans, text) in enumerate(calls, start=1):
            if not text:  # an agent that only handed over says nothing
                continue
            session.add(
                Message(
                    id=uuid7(), business_id=ctx.business_id, conversation_id=conv_id,
                    role="assistant", agent=cfg.role, content=text,
                    provider=ans.result.provider, model=ans.result.model,
                    provider_slot=ans.slot, input_tokens=ans.result.input_tokens,
                    output_tokens=ans.result.output_tokens,
                    created_at=now + timedelta(microseconds=i),  # keeps the order stable
                )
            )  # fmt: skip
        for src, dst, note in handoffs:
            session.add(AgentHandoff(id=uuid7(), business_id=ctx.business_id,
                                     conversation_id=conv_id, from_agent=src.role,
                                     to_agent=dst.role, note=note, created_at=now))  # fmt: skip
            # Roles and channel only: the note may quote the customer and stays with the
            # conversation (deleted by retention), never in the audit trail.
            await record(session, ctx, action=AuditAction.AGENT_HANDOFF, actor_user_id=None,
                         target_type="conversation", target_id=conv_id,
                         details={"from_agent": src.role, "to_agent": dst.role,
                                  "channel": channel})  # fmt: skip
        conv_row = await session.get(Conversation, conv_id)
        if conv_row is not None:
            conv_row.last_message_at = now
            conv_row.active_agent = current.role
    last_cfg, last, last_text = calls[-1]
    yield _TurnDone(
        agent=last_cfg,
        result=replace(last.result, text=last_text),
        replies=[AgentReply(c.role, c.name, t) for c, _a, t in calls if t],
        handoffs=[HandoffInfo(a.role, b.role) for a, b, _n in handoffs],
        sources=list(sources.items()),
        slot=last.slot,
        fallback=last.fallback,
        suggestion=suggestion,
        handoff=wants_person,
        resolved=resolved,
    )


async def stream_sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
    agent: str | None = None,
) -> AsyncIterator[StreamEvent | TurnResult]:  # fmt: skip
    """Console turn (a member testing their agents) as a stream ending in TurnResult.

    Members may reach every enabled agent, including ones not open to visitors. `agent`
    picks the entry agent of a new conversation.
    """
    roster = await configs.roster(factory, ctx)
    entry = roster.entry(agent, guest=False)
    if entry is None:
        raise AgentNotAllowedError if agent is not None else NoAgentEnabledError
    async with tenant_session(factory, ctx) as session:
        conv = await _conversation(session, ctx, conversation_id, user_id, entry.role)
        current = _active(roster, conv.active_agent, guest=False)
        if current is None:
            raise NoAgentEnabledError
        history = await _history(session, ctx, conv.id)
        notes = await _notes(session, ctx, conv.id)
        conv_id, channel = conv.id, conv.channel
    async for item in _stream_turn(factory, vault, provider_factories, ctx, conv_id=conv_id,
                                   channel=channel, history=history, message=message,
                                   roster=roster, agent=current, guest=False, public=False,
                                   notes=notes, facts=None):  # fmt: skip
        if isinstance(item, _TurnDone):
            yield TurnResult(
                conv_id, item.result.text, item.sources, item.result.provider,
                item.result.model, item.slot, item.fallback, agent=item.agent.role,
                agent_name=item.agent.name, replies=item.replies, handoffs=item.handoffs,
            )  # fmt: skip
        else:
            yield item


async def sales_console_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, user_id: UUID, message: str, conversation_id: UUID | None,
    agent: str | None = None,
) -> TurnResult:  # fmt: skip
    async for item in stream_sales_console_turn(
        factory, vault, provider_factories, ctx, user_id=user_id, message=message,
        conversation_id=conversation_id, agent=agent,
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
    channel: str, agent: str | None = None, facts: CustomerFacts | None = None,
    remembered: Sequence[RememberedFact] = (),
) -> AsyncIterator[StreamEvent | GuestTurnResult]:  # fmt: skip
    """One agent turn for an anonymous visitor, as a stream ending in GuestTurnResult.

    The caller must have authenticated `guest_session_id` within `ctx`'s business. A
    conversation id that does not belong to that guest session is treated as not found.
    Guests only ever reach enabled public agents: `agent` (entry choice for a new
    conversation) is refused otherwise. `facts` are details this visitor confirmed in this
    conversation; `remembered` is the memory of the verified customer behind this guest
    session (the caller passes nothing for anyone else). Only replies and agent names are
    returned: provider, model, slot and sources stay internal. Any failure to answer surfaces
    as AgentUnavailableError.
    """
    if channel not in PUBLIC_CHANNELS:
        raise ValueError("invalid public channel")
    roster = await configs.roster(factory, ctx)
    entry = roster.entry(agent, guest=True)
    if entry is None and agent is not None:
        raise AgentNotAllowedError
    async with tenant_session(factory, ctx) as session:
        if conversation_id is not None:
            conv = await _guest_conversation(session, ctx, conversation_id, guest_session_id)
        else:
            if entry is None:
                raise AgentUnavailableError  # no agent open to visitors
            conv = Conversation(id=uuid7(), business_id=ctx.business_id, channel=channel,
                                active_agent=entry.role,
                                guest_session_id=guest_session_id)  # fmt: skip
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
        status, conv_id, conv_channel = conv.status, conv.id, conv.channel
        active = conv.active_agent
        current = None if paused else _active(roster, conv.active_agent, guest=True)
        history = [] if paused else await _history(session, ctx, conv.id)
        notes = [] if paused else await _notes(session, ctx, conv.id)
    if paused:
        yield GuestTurnResult(conv_id, "", status=status,
                              can_resolve=inbox.visitor_may_resolve(status, active))  # fmt: skip
        return
    if current is None:
        raise AgentUnavailableError  # every public agent was disabled
    done: _TurnDone | None = None
    try:
        async for item in _stream_turn(factory, vault, provider_factories, ctx, conv_id=conv_id,
                                       channel=conv_channel, history=history, message=message,
                                       roster=roster, agent=current, guest=True, public=True,
                                       notes=notes, facts=facts,
                                       remembered=remembered):  # fmt: skip
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
    requested = False
    status = "open"
    if done.handoff:
        requested = await mark_handoff_requested(factory, ctx, conv_id, reason="agent")
        status = "needs_human"
    elif done.resolved:
        try:
            if await inbox.resolve_by_agent(factory, ctx, conv_id, agent=done.agent.role):
                status = "resolved"
        except inbox.ResolveNotAllowedError:  # cannot happen: _may_resolve checked the role
            logger.warning("agent resolve refused", extra={"agent": done.agent.role})
    yield GuestTurnResult(
        conv_id, done.result.text, done.suggestion, status=status, handoff_requested=requested,
        agent=done.agent.role, agent_name=done.agent.name, replies=done.replies,
        can_resolve=inbox.visitor_may_resolve(status, done.agent.role),
    )  # fmt: skip


async def public_sales_turn(
    factory: Factory, vault: Vault | None, provider_factories: ProviderFactories,
    ctx: TenantContext, *, guest_session_id: UUID, message: str, conversation_id: UUID | None,
    channel: str, agent: str | None = None, facts: CustomerFacts | None = None,
    remembered: Sequence[RememberedFact] = (),
) -> GuestTurnResult:  # fmt: skip
    async for item in stream_public_sales_turn(
        factory, vault, provider_factories, ctx, guest_session_id=guest_session_id,
        message=message, conversation_id=conversation_id, channel=channel, agent=agent,
        facts=facts, remembered=remembered,
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
    return [MessageInfo(m.id, m.role, m.content, m.created_at, m.agent) for m in rows]


async def list_messages(
    factory: Factory, ctx: TenantContext, conversation_id: UUID
) -> list[MessageInfo]:
    async with tenant_session(factory, ctx) as session:
        await _existing(session, ctx, conversation_id)
        return await _messages(session, ctx, conversation_id)


# --- background jobs (customer memory, Task 16) ------------------------------------------------


@dataclass(frozen=True)
class Transcript:
    guest_session_id: UUID
    last_message_at: datetime
    messages: list[tuple[str, str]]  # (role, content), oldest first


async def public_transcript(
    factory: Factory, ctx: TenantContext, conversation_id: UUID, *, limit: int = 40
) -> Transcript | None:
    """The latest messages of a public conversation for trusted jobs (None if not public)."""
    async with tenant_session(factory, ctx) as session:
        conv = await _existing(session, ctx, conversation_id)
        if conv.guest_session_id is None:
            return None
        rows = (
            await session.execute(
                select(Message.role, Message.content)
                .where(Message.business_id == ctx.business_id,
                       Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        ).all()  # fmt: skip
        return Transcript(conv.guest_session_id, conv.last_message_at,
                          [(r.role, r.content) for r in reversed(rows)])  # fmt: skip


async def complete(
    factory: Factory, vault: Vault | None, ctx: TenantContext,
    provider_factories: ProviderFactories, messages: list[ChatMessage],
) -> ChatResult:  # fmt: skip
    """One non-streamed call with the business's keys (primary, else backup), for jobs."""
    async for item in _stream_with_fallback(factory, vault, ctx, provider_factories, messages):
        if isinstance(item, _Answered):
            return item.result
    raise AssertionError("stream ended without an answer")


async def release_memory_claim(factory: Factory, ctx: TenantContext, conversation_id: UUID) -> None:
    """Make an idle conversation eligible for memory extraction again (e.g. budget used up)."""
    async with tenant_session(factory, ctx) as session:
        conv = await _existing(session, ctx, conversation_id)
        conv.memory_extracted_at = None
