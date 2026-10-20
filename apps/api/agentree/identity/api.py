"""Authentication endpoints (/api/auth)."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from agentree.core import ratelimit
from agentree.core.client_ip import client_ip
from agentree.identity import service
from agentree.identity.deps import CurrentUser
from agentree.identity.passwords import WeakPasswordError
from agentree.identity.schemas import (
    ChangePasswordIn,
    EmailIn,
    LoginIn,
    MeOut,
    RegisterIn,
    ResetConfirmIn,
    StatusOut,
    TokenIn,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCEPTED = StatusOut(status="accepted")


def _client_ip(request: Request) -> str:
    return client_ip(request, request.app.state.settings.trusted_proxy_count)


async def _limit(request: Request, scope: str, identifier: str, limit: int, window: int) -> None:
    allowed = await ratelimit.hit(
        request.app.state.session_factory, ratelimit.key_for(scope, identifier),
        limit=limit, window_seconds=window,
    )  # fmt: skip
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited")


def _weak(exc: WeakPasswordError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(body: RegisterIn, request: Request) -> StatusOut:
    await _limit(request, "register:ip", _client_ip(request), 10, 3600)
    await _limit(request, "register:email", body.email, 3, 3600)
    st = request.app.state
    try:
        await service.register(
            st.session_factory, st.settings, st.mailer, email=body.email, password=body.password
        )
    except WeakPasswordError as exc:
        raise _weak(exc) from None
    return ACCEPTED


@router.post("/verify-email")
async def verify_email(body: TokenIn, request: Request) -> StatusOut:
    await _limit(request, "verify:ip", _client_ip(request), 30, 3600)
    if not await service.verify_email(request.app.state.session_factory, body.token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    return StatusOut(status="verified")


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(body: EmailIn, request: Request) -> StatusOut:
    await _limit(request, "resend:ip", _client_ip(request), 10, 3600)
    await _limit(request, "resend:email", body.email, 3, 3600)
    st = request.app.state
    await service.resend_verification(st.session_factory, st.settings, st.mailer, email=body.email)
    return ACCEPTED


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    await _limit(request, "login:ip", _client_ip(request), 30, 600)
    await _limit(request, "login:email", body.email, 10, 600)
    st = request.app.state
    try:
        user_id = await service.authenticate(
            st.session_factory, email=body.email, password=body.password
        )
    except service.EmailNotVerifiedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email_not_verified") from None
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    raw = await service.create_session(st.session_factory, st.settings, user_id)
    response.set_cookie(
        st.settings.session_cookie_name, raw,
        max_age=st.settings.session_absolute_timeout_hours * 3600,
        httponly=True, secure=st.settings.session_cookie_secure, samesite="lax", path="/",
    )  # fmt: skip
    return MeOut(id=user_id, email=service.normalize_email(body.email), email_verified=True)


def _clear_cookie(request: Request, response: Response) -> None:
    s = request.app.state.settings
    response.delete_cookie(
        s.session_cookie_name, path="/", secure=s.session_cookie_secure, httponly=True,
        samesite="lax",
    )  # fmt: skip


@router.post("/logout")
async def logout(user: CurrentUser, request: Request, response: Response) -> StatusOut:
    await service.revoke_session(request.app.state.session_factory, user.session_id)
    _clear_cookie(request, response)
    return StatusOut(status="logged_out")


@router.post("/logout-all")
async def logout_all(user: CurrentUser, request: Request, response: Response) -> StatusOut:
    await service.logout_everywhere(request.app.state.session_factory, user.id)
    _clear_cookie(request, response)
    return StatusOut(status="logged_out")


@router.get("/me")
async def me(user: CurrentUser) -> MeOut:
    return MeOut(id=user.id, email=user.email, email_verified=user.email_verified)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def password_reset_request(body: EmailIn, request: Request) -> StatusOut:
    await _limit(request, "reset:ip", _client_ip(request), 10, 3600)
    await _limit(request, "reset:email", body.email, 5, 3600)
    st = request.app.state
    await service.request_password_reset(
        st.session_factory, st.settings, st.mailer, email=body.email
    )
    return ACCEPTED


@router.post("/password-reset/confirm")
async def password_reset_confirm(body: ResetConfirmIn, request: Request) -> StatusOut:
    await _limit(request, "reset-confirm:ip", _client_ip(request), 20, 3600)
    try:
        ok = await service.confirm_password_reset(
            request.app.state.session_factory, raw_token=body.token, new_password=body.new_password
        )
    except WeakPasswordError as exc:
        raise _weak(exc) from None
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    return StatusOut(status="password_reset")


@router.post("/password/change")
async def change_password(body: ChangePasswordIn, user: CurrentUser, request: Request) -> StatusOut:
    await _limit(request, "change-pw:user", str(user.id), 10, 3600)
    try:
        ok = await service.change_password(
            request.app.state.session_factory, user,
            current_password=body.current_password, new_password=body.new_password,
        )  # fmt: skip
    except WeakPasswordError as exc:
        raise _weak(exc) from None
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_current_password")
    return StatusOut(status="password_changed")
