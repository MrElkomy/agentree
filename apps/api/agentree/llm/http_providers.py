"""Thin HTTP adapters for supported providers (fixed vendor endpoints, no customer URLs)."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from agentree.llm.base import (
    ChatRequest,
    ChatResult,
    ErrorKind,
    ProviderError,
    ProviderName,
    StreamItem,
    TextDelta,
)

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def classify(status: int, body: str) -> ErrorKind:
    text = body.lower()
    # Gemini answers an invalid key with HTTP 400 (reason API_KEY_INVALID), not 401.
    if status in (401, 403) or "api_key_invalid" in text or "api key not valid" in text:
        return ErrorKind.AUTH
    if status == 402 or any(s in text for s in ("insufficient_quota", "credit balance", "billing")):
        return ErrorKind.QUOTA
    if status == 429:
        return ErrorKind.RATE_LIMIT
    if status >= 500:
        return ErrorKind.UNAVAILABLE
    return ErrorKind.BAD_REQUEST


async def _sse_data(resp: httpx.Response) -> AsyncIterator[str]:
    """`data:` payloads of a server-sent event stream (one per event)."""
    lines: list[str] = []
    async for line in resp.aiter_lines():
        if line.startswith("data:"):
            lines.append(line[5:].removeprefix(" "))
        elif not line and lines:
            yield "\n".join(lines)
            lines = []
    if lines:
        yield "\n".join(lines)


class _StreamState:
    """Accumulates one streamed reply across provider-specific events."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.finish_reason: str | None = None


class _HttpProvider:
    name: ProviderName
    url: str

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _headers(self, api_key: str) -> dict[str, str]:
        raise NotImplementedError

    def _url(self, request: ChatRequest) -> str:
        return self.url

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        raise NotImplementedError

    def _parse(self, request: ChatRequest, data: dict[str, Any]) -> ChatResult:
        raise NotImplementedError

    def _stream_url(self, request: ChatRequest) -> str:
        return self._url(request)

    def _stream_payload(self, request: ChatRequest) -> dict[str, Any]:
        return {**self._payload(request), "stream": True}

    def _stream_event(self, event: dict[str, Any], state: _StreamState) -> str:
        """Updates `state` from one event; returns the new text (may be empty)."""
        raise NotImplementedError

    async def stream(self, api_key: str, request: ChatRequest) -> AsyncIterator[StreamItem]:
        state = _StreamState()
        try:
            async with (
                httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client,
                client.stream(
                    "POST", self._stream_url(request), headers=self._headers(api_key),
                    json=self._stream_payload(request),
                ) as resp,
            ):  # fmt: skip
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    # Never propagate the body: it may echo request content.
                    raise ProviderError(self.name, classify(resp.status_code, body),
                                        resp.status_code)  # fmt: skip
                async for data in _sse_data(resp):
                    if data == "[DONE]":
                        break
                    try:
                        text = self._stream_event(json.loads(data), state)
                    except (KeyError, IndexError, TypeError, ValueError):
                        raise ProviderError(self.name, ErrorKind.UNAVAILABLE) from None
                    if text:
                        state.parts.append(text)
                        yield TextDelta(text)
        except httpx.HTTPError:
            raise ProviderError(self.name, ErrorKind.TRANSIENT) from None
        yield ChatResult(
            text="".join(state.parts), provider=self.name, model=request.model,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            raw_finish_reason=state.finish_reason,
        )  # fmt: skip

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client:
                resp = await client.post(
                    self._url(request), headers=self._headers(api_key), json=self._payload(request)
                )
        except httpx.HTTPError:
            raise ProviderError(self.name, ErrorKind.TRANSIENT) from None
        if resp.status_code >= 400:
            # Never propagate the body: it may echo request content.
            raise ProviderError(self.name, classify(resp.status_code, resp.text), resp.status_code)
        try:
            return self._parse(request, resp.json())
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(self.name, ErrorKind.UNAVAILABLE, resp.status_code) from None


class OpenAIProvider(_HttpProvider):
    name = ProviderName.OPENAI
    url = "https://api.openai.com/v1/chat/completions"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        return {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_completion_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

    def _parse(self, request: ChatRequest, data: dict[str, Any]) -> ChatResult:
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return ChatResult(
            text=choice["message"]["content"] or "", provider=self.name, model=request.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw_finish_reason=choice.get("finish_reason"),
        )  # fmt: skip

    def _stream_payload(self, request: ChatRequest) -> dict[str, Any]:
        return {**super()._stream_payload(request), "stream_options": {"include_usage": True}}

    def _stream_event(self, event: dict[str, Any], state: _StreamState) -> str:
        # Usage arrives in a final chunk (OpenAI: `usage`; Groq: `x_groq.usage`).
        usage = event.get("usage") or (event.get("x_groq") or {}).get("usage") or {}
        if usage:
            state.input_tokens = usage.get("prompt_tokens", state.input_tokens)
            state.output_tokens = usage.get("completion_tokens", state.output_tokens)
        choices = event.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        state.finish_reason = choice.get("finish_reason") or state.finish_reason
        return (choice.get("delta") or {}).get("content") or ""


class AnthropicProvider(_HttpProvider):
    name = ProviderName.ANTHROPIC
    url = "https://api.anthropic.com/v1/messages"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
                if m.role != "system"
            ],
        }
        if system:
            payload["system"] = system
        return payload

    def _parse(self, request: ChatRequest, data: dict[str, Any]) -> ChatResult:
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        usage = data.get("usage") or {}
        return ChatResult(
            text=text, provider=self.name, model=request.model,
            input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
            raw_finish_reason=data.get("stop_reason"),
        )  # fmt: skip

    def _stream_event(self, event: dict[str, Any], state: _StreamState) -> str:
        kind = event["type"]
        if kind == "error":  # e.g. overloaded_error mid-stream
            raise ProviderError(self.name, ErrorKind.UNAVAILABLE)
        if kind == "message_start":
            state.input_tokens = event["message"].get("usage", {}).get("input_tokens", 0)
        elif kind == "message_delta":
            state.output_tokens = event.get("usage", {}).get("output_tokens", state.output_tokens)
            state.finish_reason = event.get("delta", {}).get("stop_reason") or state.finish_reason
        elif kind == "content_block_delta" and event["delta"].get("type") == "text_delta":
            return str(event["delta"]["text"])
        return ""


class GeminiProvider(_HttpProvider):
    name = ProviderName.GEMINI
    url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key}  # header, never in the URL

    def _url(self, request: ChatRequest) -> str:
        return f"{self.url}/{request.model}:generateContent"  # model validated by ChatRequest

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in request.messages
                if m.role != "system"
            ],
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    def _parse(self, request: ChatRequest, data: dict[str, Any]) -> ChatResult:
        candidate = data["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            text=text, provider=self.name, model=request.model,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            raw_finish_reason=candidate.get("finishReason"),
        )  # fmt: skip

    def _stream_url(self, request: ChatRequest) -> str:
        return f"{self.url}/{request.model}:streamGenerateContent?alt=sse"

    def _stream_payload(self, request: ChatRequest) -> dict[str, Any]:
        return self._payload(request)  # the endpoint itself streams

    def _stream_event(self, event: dict[str, Any], state: _StreamState) -> str:
        usage = event.get("usageMetadata") or {}
        state.input_tokens = usage.get("promptTokenCount", state.input_tokens)
        state.output_tokens = usage.get("candidatesTokenCount", state.output_tokens)
        candidates = event.get("candidates") or []
        if not candidates:
            return ""
        candidate = candidates[0]
        state.finish_reason = candidate.get("finishReason") or state.finish_reason
        parts = (candidate.get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)


class GroqProvider(OpenAIProvider):
    """Groq's OpenAI-compatible endpoint (fixed URL); offers a free tier."""

    name = ProviderName.GROQ
    url = "https://api.groq.com/openai/v1/chat/completions"

    def _stream_payload(self, request: ChatRequest) -> dict[str, Any]:
        # Usage comes back in `x_groq`; no `stream_options` needed.
        return {**self._payload(request), "stream": True}


ProviderFactory = Callable[[], _HttpProvider]

PROVIDERS: dict[ProviderName, ProviderFactory] = {
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.ANTHROPIC: AnthropicProvider,
    ProviderName.GEMINI: GeminiProvider,
    ProviderName.GROQ: GroqProvider,
}
