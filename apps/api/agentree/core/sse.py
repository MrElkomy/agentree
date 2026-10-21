"""Server-sent events for streamed replies.

Endpoints pull the first item before answering, so errors that happen before any text (no
provider, all providers down, not found) still map to normal HTTP status codes. After that the
response is `200 text/event-stream` and failures arrive as an `error` event.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from starlette.background import BackgroundTasks
from starlette.responses import StreamingResponse

# no-transform: proxies (Next.js, Caddy `encode`) must not compress or buffer the stream.
HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def stream_response[T](
    first: T,
    rest: AsyncIterator[T],
    encode: Callable[[T], bytes],
    on_error: Callable[[Exception], bytes | None],
    background: BackgroundTasks | None = None,
) -> StreamingResponse:
    """Streams `first` then `rest`, encoded as events.

    `on_error` turns an exception raised mid-stream into a final event; returning None
    re-raises it. The iterator is always closed, so an abandoned stream stops the work.
    """

    async def body() -> AsyncIterator[bytes]:
        try:
            yield encode(first)
            async for item in rest:
                yield encode(item)
        except Exception as exc:
            final = on_error(exc)
            if final is None:
                raise
            yield final
        finally:
            await _close(rest)

    return StreamingResponse(body(), media_type="text/event-stream", headers=HEADERS,
                             background=background)  # fmt: skip


async def _close(it: AsyncIterator[Any]) -> None:
    aclose: Callable[[], Awaitable[None]] | None = getattr(it, "aclose", None)
    if aclose is not None:
        await aclose()
