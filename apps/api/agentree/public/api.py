"""Public AI page + website widget endpoints, and the owner's public page settings.

Public routes (`/api/public/{slug}/...`) need no login: the tenant comes only from the slug
of an *enabled* public page. Unknown slugs and disabled pages both return 404 `not_found`.
Visitors get an opaque guest token (sent in the `X-Agentree-Guest` header) and only ever
see their own conversations. Responses never include provider, model, key slot or knowledge
sources, and every failure of the customer's AI setup is reported as a generic 503
`agent_unavailable`.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

from agentree.actions import service as gateway
from agentree.actions.service import Action
from agentree.agents import configs as agent_configs
from agentree.agents import events as agent_events
from agentree.agents import inbox
from agentree.agents import service as agents
from agentree.agents.prompts import CustomerFacts, RememberedFact
from agentree.agents.registry import AgentRole
from agentree.core import ratelimit, sse
from agentree.core.client_ip import client_ip, rate_limit_bucket
from agentree.core.config import Environment
from agentree.core.email import EmailSender, OutgoingEmail, branded_email, send_safely
from agentree.core.email_layout import EmailContent
from agentree.customers import service as customers
from agentree.leads import service as leads
from agentree.public import service
from agentree.public.schemas import (
    GuestChatIn,
    GuestChatOut,
    GuestConversationOut,
    GuestLeadIn,
    GuestLeadOut,
    GuestMessageOut,
    GuestReplyOut,
    GuestSessionOut,
    IdentityConfirmIn,
    IdentityOut,
    IdentityStartIn,
    IdentityStartOut,
    LeadSuggestionOut,
    LinkOut,
    PublicAgentOut,
    PublicPageOut,
    PublicProfileIn,
    PublicProfileOut,
    WidgetConfigOut,
)
from agentree.reports import service as reports
from agentree.tenancy import service as tenancy
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

owner_router = APIRouter(prefix="/api/businesses/{business_id}", tags=["public-page"])
public_router = APIRouter(prefix="/api/public/{slug}", tags=["public"])

# A dedicated header, not `Authorization`: browsers reuse `Authorization` for HTTP basic auth
# in front of the app (e.g. the staging gate), and a Bearer value would replace it.
GUEST_HEADER = "X-Agentree-Guest"
_guest_header = APIKeyHeader(
    name=GUEST_HEADER, auto_error=False, description="Guest session token from POST /sessions"
)
GuestToken = Annotated[str | None, Depends(_guest_header)]


def _links(links: list[service.Link]) -> list[LinkOut]:
    return [LinkOut(label=x.label, url=x.url, description=x.description) for x in links]


# --- owner (dashboard) ------------------------------------------------------------------


async def _profile_out(
    request: Request, member: Member, p: service.ProfileInfo
) -> PublicProfileOut:
    business = await tenancy.get_business(request.app.state.session_factory, member.tenant)
    return PublicProfileOut(
        slug=business.slug, enabled=p.enabled, display_name=p.display_name, bio=p.bio,
        links=_links(p.links), widget_origins=p.widget_origins,
        daily_reply_budget=p.daily_reply_budget, customer_memory=p.customer_memory,
        updated_at=p.updated_at,
    )  # fmt: skip


@owner_router.get("/public-profile")
async def get_public_profile(member: Member, request: Request) -> PublicProfileOut:
    p = await service.get_profile(request.app.state.session_factory, member.tenant)
    return await _profile_out(request, member, p)


@owner_router.put("/public-profile")
async def put_public_profile(
    body: PublicProfileIn, member: Member, request: Request
) -> PublicProfileOut:
    member.require(Role.ADMIN)
    st = request.app.state
    try:
        p = await service.save_profile(
            st.session_factory, member.tenant, enabled=body.enabled,
            display_name=body.display_name, bio=body.bio,
            links=[service.Link(link.label, link.url, link.description) for link in body.links],
            widget_origins=body.widget_origins, daily_reply_budget=body.daily_reply_budget,
            customer_memory=body.customer_memory,
            allow_localhost=st.settings.environment in (Environment.DEV, Environment.TEST),
        )  # fmt: skip
    except service.InvalidOriginError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_widget_origin"
        ) from None
    except service.InvalidLinkError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_link") from None
    return await _profile_out(request, member, p)


# --- public (anonymous visitors) --------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


def _busy() -> HTTPException:
    # One generic answer for every limit: callers learn nothing about which one tripped.
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "busy")


def _invalid_session() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "guest_session_invalid")


async def _page(request: Request, slug: str) -> service.PublicPage:
    page = await service.resolve_page(request.app.state.session_factory, slug)
    if page is None:
        raise _not_found()
    return page


async def _within(request: Request, scope: str, ident: str, limit: int, window: int) -> bool:
    return await ratelimit.hit(
        request.app.state.session_factory, ratelimit.key_for(scope, ident),
        limit=limit, window_seconds=window,
    )  # fmt: skip


def _ip(request: Request) -> str:
    """Per-IP rate limit bucket (IPv6: the /64 network)."""
    return rate_limit_bucket(client_ip(request, request.app.state.settings.trusted_proxy_count))


@public_router.get("")
async def public_page(slug: str, request: Request) -> PublicPageOut:
    page = await _page(request, slug)
    roster = await agent_configs.roster(request.app.state.session_factory, page.tenant)
    reachable = [c for c in roster.all() if roster.allowed(c.role, guest=True)]
    sales = roster.config(AgentRole.SALES)
    return PublicPageOut(
        slug=page.slug, display_name=page.display_name, bio=page.bio, links=_links(page.links),
        chat_enabled=bool(reachable),
        agents=[PublicAgentOut(role=c.role, name=c.name) for c in reachable],
        lead_capture=sales is not None and Action.CREATE_LEAD in sales.effective_tools,
        retention_days=request.app.state.settings.retention_days,
        customer_memory=page.customer_memory,
    )  # fmt: skip


@public_router.get("/widget-config")
async def widget_config(slug: str, request: Request) -> WidgetConfigOut:
    page = await _page(request, slug)
    return WidgetConfigOut(widget_origins=page.widget_origins)


@public_router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_guest_session(slug: str, request: Request) -> GuestSessionOut:
    page = await _page(request, slug)
    bid = str(page.tenant.business_id)
    if not await _within(request, "public-session:ip", _ip(request),
                         service.SESSIONS_PER_IP_PER_HOUR, 3600):  # fmt: skip
        raise _busy()
    if not await _within(request, "public-session:business", bid,
                         service.SESSIONS_PER_BUSINESS_PER_DAY, 86400):  # fmt: skip
        raise _busy()
    new = await service.create_guest_session(request.app.state.session_factory, page.tenant)
    return GuestSessionOut(token=new.token, expires_at=new.expires_at)


async def _guest(
    request: Request, page: service.PublicPage, token: str | None, *, touch: bool
) -> UUID:
    guest = await service.authenticate_guest(
        request.app.state.session_factory, page.tenant, token, touch=touch
    )
    if guest is None:
        raise _invalid_session()
    return guest


async def _chat_admission(
    request: Request, slug: str, creds: GuestToken
) -> tuple[service.PublicPage, UUID]:
    """Page and guest session for one chat turn, after every abuse limit (else 429/401/404)."""
    page = await _page(request, slug)
    if not await _within(request, "public-chat:ip", _ip(request),
                         service.CHAT_PER_IP_PER_HOUR, 3600):  # fmt: skip
        raise _busy()
    guest = await _guest(request, page, creds, touch=True)
    if not (
        await _within(request, "public-chat:session-10m", str(guest),
                      service.CHAT_PER_SESSION_PER_10_MIN, 600)
        and await _within(request, "public-chat:session-day", str(guest),
                          service.CHAT_PER_SESSION_PER_DAY, 86400)
    ):  # fmt: skip
        raise _busy()
    # Daily reply budget protects the customer's AI quota: one counter per business per UTC day.
    day = datetime.now(UTC).date().isoformat()
    if not await ratelimit.hit(request.app.state.session_factory,
                               ratelimit.daily_ai_budget_key(page.tenant.business_id, day),
                               limit=page.daily_reply_budget, window_seconds=86400):  # fmt: skip
        # Owners and Admins learn it once a day (Task 20c); the visitor only sees "busy".
        st = request.app.state
        await reports.budget_reached(st.session_factory, page.tenant, reports.Deps(
            st.settings, st.mailer, st.push, st.vault, st.llm_providers))  # fmt: skip
        raise _busy()
    return page, guest


def _guest_turn_error(exc: Exception) -> HTTPException | None:
    if isinstance(exc, agents.NotFoundError):
        return _not_found()
    if isinstance(exc, agents.AgentNotAllowedError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_agent")
    if isinstance(exc, agents.AgentUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent_unavailable")
    return None


def _chat_out(turn: agents.GuestTurnResult) -> GuestChatOut:
    suggestion = turn.lead_suggestion
    return GuestChatOut(
        conversation_id=turn.conversation_id, reply=turn.reply, status=turn.status,
        lead_suggestion=LeadSuggestionOut(name=suggestion.name, email=suggestion.email,
                                          phone=suggestion.phone, need=suggestion.need)
        if suggestion else None,
        agent=turn.agent, agent_name=turn.agent_name,
        replies=[GuestReplyOut(agent=r.agent, agent_name=r.name, content=r.content)
                 for r in turn.replies],
        can_resolve=turn.can_resolve,
    )  # fmt: skip


async def _facts(
    request: Request, page: service.PublicPage, conversation_id: UUID | None
) -> CustomerFacts | None:
    """What this visitor confirmed in this conversation (team context; never contact data)."""
    if conversation_id is None:
        return None
    lead = await leads.lead_for_conversation(request.app.state.session_factory, page.tenant,
                                             conversation_id)  # fmt: skip
    if lead is None:
        return None
    return CustomerFacts(name=lead.name, need=lead.need, has_contact=bool(lead.email or lead.phone))


async def _remembered(
    request: Request, page: service.PublicPage, guest: UUID
) -> list[RememberedFact]:
    """Memory of the verified customer behind this guest session (empty for anyone else);
    each agent then sees only the categories its role may read. Nothing when the business
    turned "Remember customers" off."""
    if not page.customer_memory:
        return []
    facts = await customers.memory_for_guest(request.app.state.session_factory, page.tenant,
                                             guest)  # fmt: skip
    return [RememberedFact(f.category, f.value) for f in facts]


def _notify_if_handoff(
    request: Request, page: service.PublicPage, turn: agents.GuestTurnResult, tasks: BackgroundTasks
) -> None:
    if turn.handoff_requested:  # the agent brought in a person: tell the team (after replying)
        st = request.app.state
        tasks.add_task(inbox.notify_handoff, st.session_factory, st.settings, st.mailer, st.push,
                       page.tenant, turn.conversation_id, reason="agent")  # fmt: skip


@public_router.post("/chat")
async def guest_chat(
    slug: str, body: GuestChatIn, creds: GuestToken, request: Request, tasks: BackgroundTasks
) -> GuestChatOut:
    page, guest = await _chat_admission(request, slug, creds)
    st = request.app.state
    try:
        turn = await agents.public_sales_turn(
            st.session_factory, st.vault, st.llm_providers, page.tenant,
            guest_session_id=guest, message=body.message, conversation_id=body.conversation_id,
            channel=body.channel, agent=body.agent,
            facts=await _facts(request, page, body.conversation_id),
            remembered=await _remembered(request, page, guest),
        )  # fmt: skip
    except Exception as exc:
        if (err := _guest_turn_error(exc)) is None:
            raise
        raise err from None
    _notify_if_handoff(request, page, turn, tasks)
    return _chat_out(turn)


@public_router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def guest_chat_stream(
    slug: str, body: GuestChatIn, creds: GuestToken, request: Request
) -> StreamingResponse:
    """The chat turn as server-sent events (`agents/events.py`), then `done` or `error`.

    `done` carries the same body as POST /chat; its `reply` is final (it replaces the streamed
    text). After `error` nothing was stored and the visitor can send the message again.
    """
    page, guest = await _chat_admission(request, slug, creds)
    st = request.app.state
    items = agents.stream_public_sales_turn(
        st.session_factory, st.vault, st.llm_providers, page.tenant,
        guest_session_id=guest, message=body.message, conversation_id=body.conversation_id,
        channel=body.channel, agent=body.agent,
        facts=await _facts(request, page, body.conversation_id),
        remembered=await _remembered(request, page, guest),
    )  # fmt: skip
    try:
        first = await anext(items)
    except Exception as exc:
        if (err := _guest_turn_error(exc)) is None:
            raise
        raise err from None
    tasks = BackgroundTasks()  # run after the stream ends

    def encode(item: agents.StreamEvent | agents.GuestTurnResult) -> bytes:
        if not isinstance(item, agents.GuestTurnResult):
            return agent_events.encode(item)
        _notify_if_handoff(request, page, item, tasks)
        return sse.event("done", _chat_out(item).model_dump(mode="json"))

    def on_error(exc: Exception) -> bytes | None:
        if (err := _guest_turn_error(exc)) is None:
            return None
        return sse.event("error", {"code": err.detail})

    return sse.stream_response(first, items, encode, on_error, background=tasks)


@public_router.post("/leads")
async def guest_lead(
    slug: str, body: GuestLeadIn, creds: GuestToken, request: Request
) -> GuestLeadOut:
    """The visitor confirms their contact details and consent; the team gets a lead."""
    page = await _page(request, slug)
    if not await _within(request, "public-lead:ip", _ip(request),
                         service.CHAT_PER_IP_PER_HOUR, 3600):  # fmt: skip
        raise _busy()
    guest = await _guest(request, page, creds, touch=True)
    if not await _within(request, "public-lead:session", str(guest),
                         leads.SUBMITS_PER_SESSION_PER_HOUR, 3600):  # fmt: skip
        raise _busy()
    try:
        fields = leads.validate_fields(name=body.name, email=body.email, phone=body.phone,
                                       need=body.need)  # fmt: skip
    except leads.InvalidLeadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc}") from None
    st = request.app.state
    try:
        await leads.submit_guest_lead(
            st.session_factory, st.settings, st.mailer, st.push, page.tenant,
            guest_session_id=guest, conversation_id=body.conversation_id, fields=fields,
            idempotency_key=body.idempotency_key,
        )  # fmt: skip
    except agents.NotFoundError:
        raise _not_found() from None
    except gateway.IdempotencyConflictError:
        raise HTTPException(status.HTTP_409_CONFLICT, "idempotency_conflict") from None
    except leads.LeadCaptureOffError:
        raise HTTPException(status.HTTP_409_CONFLICT, "lead_capture_off") from None
    return GuestLeadOut(received=True)


@public_router.get("/conversations/{conversation_id}/messages")
async def guest_messages(
    slug: str, conversation_id: UUID, creds: GuestToken, request: Request
) -> list[GuestMessageOut]:
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=False)
    try:
        rows = await agents.list_guest_messages(
            request.app.state.session_factory, page.tenant, guest_session_id=guest,
            conversation_id=conversation_id,
        )  # fmt: skip
    except agents.NotFoundError:
        raise _not_found() from None
    names = await _agent_names(request, page)
    return [_message_out(m, names) for m in rows]


@public_router.get("/conversations/{conversation_id}")
async def guest_conversation(
    slug: str, conversation_id: UUID, creds: GuestToken, request: Request
) -> GuestConversationOut:
    """Status and messages of the visitor's own conversation (polled while a person helps)."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=False)
    factory = request.app.state.session_factory
    try:
        rows = await agents.list_guest_messages(factory, page.tenant, guest_session_id=guest,
                                                conversation_id=conversation_id)  # fmt: skip
        current, can_resolve = await inbox.guest_state(factory, page.tenant, conversation_id)
    except (agents.NotFoundError, inbox.NotFoundError):
        raise _not_found() from None
    names = await _agent_names(request, page)
    return GuestConversationOut(status=current, messages=[_message_out(m, names) for m in rows],
                                can_resolve=can_resolve)  # fmt: skip


async def _agent_names(request: Request, page: service.PublicPage) -> dict[str, str]:
    roster = await agent_configs.roster(request.app.state.session_factory, page.tenant)
    return {c.role: c.name for c in roster.all()}


def _message_out(m: agents.MessageInfo, names: dict[str, str]) -> GuestMessageOut:
    name = names.get(m.agent) if m.agent else None
    return GuestMessageOut(role=m.role, content=m.content, created_at=m.created_at,
                           agent=m.agent, agent_name=name)  # fmt: skip


@public_router.post("/conversations/{conversation_id}/handoff")
async def guest_request_handoff(
    slug: str, conversation_id: UUID, creds: GuestToken, request: Request, tasks: BackgroundTasks
) -> GuestConversationOut:
    """The visitor asks to talk to a person: the AI pauses and the team is alerted."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    if not await _within(request, "public-handoff:session", str(guest), 10, 3600):
        raise _busy()
    st = request.app.state
    try:
        await agents.guest_conversation_channel(st.session_factory, page.tenant,
                                                guest_session_id=guest,
                                                conversation_id=conversation_id)  # fmt: skip
        requested = await inbox.mark_handoff_requested(
            st.session_factory, page.tenant, conversation_id, reason="visitor"
        )
    except (agents.NotFoundError, inbox.NotFoundError):
        raise _not_found() from None
    if requested:
        tasks.add_task(inbox.notify_handoff, st.session_factory, st.settings, st.mailer, st.push,
                       page.tenant, conversation_id, reason="visitor")  # fmt: skip
    return await guest_conversation(slug, conversation_id, creds, request)


@public_router.delete("/conversations/{conversation_id}/handoff")
async def guest_cancel_handoff(
    slug: str, conversation_id: UUID, creds: GuestToken, request: Request
) -> GuestConversationOut:
    """The visitor continues with the assistant (only before someone took over)."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    st = request.app.state
    try:
        await agents.guest_conversation_channel(st.session_factory, page.tenant,
                                                guest_session_id=guest,
                                                conversation_id=conversation_id)  # fmt: skip
        await inbox.cancel_handoff_by_guest(st.session_factory, page.tenant, conversation_id)
    except (agents.NotFoundError, inbox.NotFoundError):
        raise _not_found() from None
    return await guest_conversation(slug, conversation_id, creds, request)


@public_router.post("/conversations/{conversation_id}/resolve")
async def guest_resolve(
    slug: str, conversation_id: UUID, creds: GuestToken, request: Request
) -> GuestConversationOut:
    """The visitor marks their own Customer Service conversation resolved (Task 15).

    403 `resolve_not_allowed` for conversations only the team may resolve (Sales);
    409 `conversation_state` while a team member is handling it.
    """
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    if not await _within(request, "public-resolve:session", str(guest), 10, 3600):
        raise _busy()
    st = request.app.state
    try:
        await agents.guest_conversation_channel(st.session_factory, page.tenant,
                                                guest_session_id=guest,
                                                conversation_id=conversation_id)  # fmt: skip
        await inbox.resolve_by_visitor(st.session_factory, page.tenant, conversation_id)
    except (agents.NotFoundError, inbox.NotFoundError):
        raise _not_found() from None
    except inbox.ResolveNotAllowedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resolve_not_allowed") from None
    except inbox.InvalidStateError:
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation_state") from None
    return await guest_conversation(slug, conversation_id, creds, request)


# --- customer identity (Task 16): email one-time code ------------------------------------------

CODE_STARTS_PER_SESSION_PER_HOUR = 3
CODE_STARTS_PER_IP_PER_HOUR = 10
CODE_STARTS_PER_EMAIL_PER_DAY = 5
CODE_CHECKS_PER_SESSION_PER_10_MIN = 10


def _require_memory(page: service.PublicPage) -> None:
    if not page.customer_memory:
        raise HTTPException(status.HTTP_409_CONFLICT, "customer_memory_off")


def _identity_out(identity: customers.Identity) -> IdentityOut:
    return IdentityOut(verified=identity.verified, email_hint=identity.email_hint)


@public_router.get("/identity")
async def guest_identity(slug: str, creds: GuestToken, request: Request) -> IdentityOut:
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=False)
    return _identity_out(
        await customers.identity(request.app.state.session_factory, page.tenant, guest)
    )


def _code_email(to: str, business: str, code: str) -> OutgoingEmail:
    return branded_email(to, EmailContent(
        subject=f"Your {business} verification code",
        preheader=f"Your code is {code}. It expires in 10 minutes.",
        heading="Confirm your email",
        paragraphs=[
            f"Enter this code in the {business} chat so its assistants can remember you next "
            "time:",
            code,
            "It expires in 10 minutes. If you didn't ask for it, ignore this email: nothing "
            "happens without the code.",
        ],
        reason=f"You're receiving this because someone entered this address in the {business} "
        "chat on Agentree.",
    ))  # fmt: skip


@public_router.post("/identity/start", status_code=status.HTTP_202_ACCEPTED)
async def guest_identity_start(
    slug: str, body: IdentityStartIn, creds: GuestToken, request: Request, tasks: BackgroundTasks
) -> IdentityStartOut:
    """Email a one-time code. Entering an email unlocks nothing until the code is confirmed.
    409 `customer_memory_off` when the business does not remember customers."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    _require_memory(page)
    try:
        email = customers.normalize_email(body.email)
    except customers.InvalidEmailError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_email") from None
    bid = str(page.tenant.business_id)
    if not (
        await _within(request, "identity-start:ip", _ip(request),
                      CODE_STARTS_PER_IP_PER_HOUR, 3600)
        and await _within(request, "identity-start:session", str(guest),
                          CODE_STARTS_PER_SESSION_PER_HOUR, 3600)
        and await _within(request, "identity-start:email", f"{bid}:{email}",
                          CODE_STARTS_PER_EMAIL_PER_DAY, 86400)
    ):  # fmt: skip
        raise _busy()
    st = request.app.state
    address, code = await customers.start_verification(
        st.session_factory, page.tenant, guest_session_id=guest, email=email
    )
    mailer: EmailSender = st.mailer
    tasks.add_task(send_safely, mailer, _code_email(address, page.display_name, code),
                   kind="customer_code")  # fmt: skip
    return IdentityStartOut(sent=True)


@public_router.post("/identity/confirm")
async def guest_identity_confirm(
    slug: str, body: IdentityConfirmIn, creds: GuestToken, request: Request
) -> IdentityOut:
    """422 `invalid_code` for a wrong, expired, used or exhausted code (indistinguishable)."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    _require_memory(page)
    if not await _within(request, "identity-confirm:session", str(guest),
                         CODE_CHECKS_PER_SESSION_PER_10_MIN, 600):  # fmt: skip
        raise _busy()
    try:
        identity = await customers.confirm_verification(
            request.app.state.session_factory, page.tenant, guest_session_id=guest, code=body.code
        )
    except customers.InvalidCodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_code") from None
    return _identity_out(identity)


@public_router.delete("/identity")
async def guest_identity_forget(slug: str, creds: GuestToken, request: Request) -> IdentityOut:
    """ "Not you?": this browser stops being the verified customer."""
    page = await _page(request, slug)
    guest = await _guest(request, page, creds, touch=True)
    await customers.forget_identity(request.app.state.session_factory, page.tenant, guest)
    return IdentityOut(verified=False)
