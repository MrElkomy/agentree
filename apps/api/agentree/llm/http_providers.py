"""Thin HTTP adapters for supported providers (fixed vendor endpoints, no customer URLs)."""

from collections.abc import Callable
from typing import Any

import httpx

from agentree.llm.base import (
    ChatRequest,
    ChatResult,
    ErrorKind,
    ProviderError,
    ProviderName,
)

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def classify(status: int, body: str) -> ErrorKind:
    text = body.lower()
    if status in (401, 403):
        return ErrorKind.AUTH
    if status == 402 or any(s in text for s in ("insufficient_quota", "credit balance", "billing")):
        return ErrorKind.QUOTA
    if status == 429:
        return ErrorKind.RATE_LIMIT
    if status >= 500:
        return ErrorKind.UNAVAILABLE
    return ErrorKind.BAD_REQUEST


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


ProviderFactory = Callable[[], _HttpProvider]

PROVIDERS: dict[ProviderName, ProviderFactory] = {
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.ANTHROPIC: AnthropicProvider,
    ProviderName.GEMINI: GeminiProvider,
}
