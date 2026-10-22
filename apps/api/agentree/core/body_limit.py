"""Request body size limit, enforced while the body streams in.

Starlette spools a multipart body to disk before the endpoint (and its rate limit) runs, so an
endpoint-level size check comes too late to stop a multi-gigabyte upload filling the disk. This
ASGI middleware refuses a declared Content-Length over the limit at once and stops counting
bytes past the limit for chunked bodies; the answer is 413 `request_too_large` either way.
"""

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _TooLarge(Exception):
    pass


_BODY = json.dumps({"detail": "request_too_large"}).encode()


async def _refuse(send: Send) -> None:
    await send({"type": "http.response.start", "status": 413, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(_BODY)).encode()),
        (b"connection", b"close")]})  # fmt: skip
    await send({"type": "http.response.body", "body": _BODY})


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, default: int, large: int, large_paths: str) -> None:
        self.app = app
        self.default = default
        self.large = large
        self.large_paths = re.compile(large_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.large if self.large_paths.fullmatch(scope["path"]) else self.default
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = True
            if too_large:
                await _refuse(send)
                return
        received = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:  # the app answered its own parse error: answer 413 instead
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await _refuse(send)
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            if not started:
                await _refuse(send)
