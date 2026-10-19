"""FastAPI dependencies for authenticated requests."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from agentree.identity.service import AuthenticatedUser, resolve_session


async def current_user(request: Request) -> AuthenticatedUser:
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie_name)
    if raw:
        user = await resolve_session(request.app.state.session_factory, settings, raw)
        if user is not None:
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")


async def verified_user(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    if not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email_not_verified")
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
VerifiedUser = Annotated[AuthenticatedUser, Depends(verified_user)]
