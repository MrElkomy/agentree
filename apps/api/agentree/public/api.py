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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from agentree.agents import service as agents
from agentree.core import ratelimit
from agentree.core.client_ip import client_ip
from agentree.core.config import Environment
from agentree.public import service
from agentree.public.schemas import (
    GuestChatIn,
    GuestChatOut,
    GuestMessageOut,
    GuestSessionOut,
    LinkOut,
    PublicPageOut,
    PublicProfileIn,
    PublicProfileOut,
    WidgetConfigOut,
)
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
        daily_reply_budget=p.daily_reply_budget, updated_at=p.updated_at,
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
    return client_ip(request, request.app.state.settings.trusted_proxy_count)


@public_router.get("")
async def public_page(slug: str, request: Request) -> PublicPageOut:
    page = await _page(request, slug)
    return PublicPageOut(slug=page.slug, display_name=page.display_name, bio=page.bio,
                         links=_links(page.links), chat_enabled=True)  # fmt: skip


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


@public_router.post("/chat")
async def guest_chat(
    slug: str, body: GuestChatIn, creds: GuestToken, request: Request
) -> GuestChatOut:
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
    if not await _within(request, "public-chat:business-day", f"{page.tenant.business_id}:{day}",
                         page.daily_reply_budget, 86400):  # fmt: skip
        raise _busy()
    st = request.app.state
    try:
        turn = await agents.public_sales_turn(
            st.session_factory, st.vault, st.llm_providers, page.tenant,
            guest_session_id=guest, message=body.message, conversation_id=body.conversation_id,
            channel=body.channel,
        )  # fmt: skip
    except agents.NotFoundError:
        raise _not_found() from None
    except agents.AgentUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent_unavailable") from None
    return GuestChatOut(conversation_id=turn.conversation_id, reply=turn.reply)


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
    return [GuestMessageOut(role=m.role, content=m.content, created_at=m.created_at) for m in rows]
