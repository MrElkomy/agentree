"""CSRF defense: SameSite cookies plus an Origin check on state-changing API requests."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _origin_of(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return origin
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return None


def csrf_middleware(
    allowed_origins: list[str],
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    allowed = frozenset(o.rstrip("/") for o in allowed_origins)

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            if _origin_of(request) not in allowed:
                return JSONResponse({"detail": "origin_not_allowed"}, status_code=403)
        return await call_next(request)

    return middleware
