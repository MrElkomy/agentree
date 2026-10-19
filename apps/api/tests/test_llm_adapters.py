"""Provider adapters against a mocked HTTP transport (no network)."""

import json
from collections.abc import Callable

import httpx
import pytest

from agentree.llm.base import ChatMessage, ChatRequest, ErrorKind, ProviderError
from agentree.llm.http_providers import AnthropicProvider, GeminiProvider, OpenAIProvider

KEY = "sk-test-key-abcdef123456"  # gitleaks:allow (fake test key)
REQ = ChatRequest(
    model="model-x",
    messages=[ChatMessage("system", "Be brief."), ChatMessage("user", "Hi"),
              ChatMessage("assistant", "Hello"), ChatMessage("user", "Price?")],
)  # fmt: skip

Handler = Callable[[httpx.Request], httpx.Response]


def _capture(
    response: dict[str, object], status: int = 200
) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=response)

    return seen, httpx.MockTransport(handler)


async def test_openai_request_and_parse() -> None:
    seen, transport = _capture(
        {"choices": [{"message": {"content": "It is $10."}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 12, "completion_tokens": 4}}
    )  # fmt: skip
    result = await OpenAIProvider(transport).chat(KEY, REQ)
    assert result.text == "It is $10." and result.input_tokens == 12 and result.output_tokens == 4
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "model-x" and body["messages"][0] == {
        "role": "system",
        "content": "Be brief.",
    }


async def test_anthropic_moves_system_prompt() -> None:
    seen, transport = _capture(
        {"content": [{"type": "text", "text": "Ten dollars."}], "stop_reason": "end_turn",
         "usage": {"input_tokens": 9, "output_tokens": 2}}
    )  # fmt: skip
    result = await AnthropicProvider(transport).chat(KEY, REQ)
    assert result.text == "Ten dollars."
    req = seen[0]
    assert req.headers["x-api-key"] == KEY and "anthropic-version" in req.headers
    body = json.loads(req.content)
    assert body["system"] == "Be brief."
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]


async def test_gemini_key_in_header_not_url() -> None:
    seen, transport = _capture(
        {"candidates": [{"content": {"parts": [{"text": "10 USD"}]}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 2}}
    )  # fmt: skip
    result = await GeminiProvider(transport).chat(KEY, REQ)
    assert result.text == "10 USD"
    req = seen[0]
    assert KEY not in str(req.url)
    assert req.headers["x-goog-api-key"] == KEY
    assert str(req.url).endswith("/models/model-x:generateContent")
    body = json.loads(req.content)
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, {"error": "invalid key"}, ErrorKind.AUTH),
        (403, {}, ErrorKind.AUTH),
        (429, {"error": {"code": "insufficient_quota"}}, ErrorKind.QUOTA),
        (400, {"error": {"message": "Your credit balance is too low"}}, ErrorKind.QUOTA),
        (429, {"error": "slow down"}, ErrorKind.RATE_LIMIT),
        (503, {}, ErrorKind.UNAVAILABLE),
        (529, {}, ErrorKind.UNAVAILABLE),
        (400, {"error": "unknown model"}, ErrorKind.BAD_REQUEST),
    ],
)
async def test_error_classification(status: int, body: dict[str, object], kind: ErrorKind) -> None:
    _, transport = _capture(body, status)
    with pytest.raises(ProviderError) as exc:
        await OpenAIProvider(transport).chat(KEY, REQ)
    assert exc.value.kind is kind
    assert KEY not in str(exc.value)


async def test_network_failure_is_transient_and_key_not_leaked() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError) as exc:
        await AnthropicProvider(httpx.MockTransport(boom)).chat(KEY, REQ)
    assert exc.value.kind is ErrorKind.TRANSIENT
    assert KEY not in str(exc.value) and exc.value.__cause__ is None


async def test_malformed_success_response_is_unavailable() -> None:
    _, transport = _capture({"unexpected": True})
    with pytest.raises(ProviderError) as exc:
        await GeminiProvider(transport).chat(KEY, REQ)
    assert exc.value.kind is ErrorKind.UNAVAILABLE


@pytest.mark.parametrize("model", ["../../admin", "a b", "", "x" * 101, "model?key=1"])
def test_model_name_is_validated(model: str) -> None:
    with pytest.raises(ValueError):
        ChatRequest(model=model, messages=[ChatMessage("user", "hi")])
