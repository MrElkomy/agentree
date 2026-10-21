"""Provider adapters against a mocked HTTP transport (no network)."""

import json
from collections.abc import Callable

import httpx
import pytest

from agentree.llm.base import (
    ChatMessage,
    ChatRequest,
    ChatResult,
    ErrorKind,
    ProviderError,
    TextDelta,
)
from agentree.llm.http_providers import (
    AnthropicProvider,
    GeminiProvider,
    GroqProvider,
    OpenAIProvider,
)

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


async def test_groq_uses_its_fixed_openai_compatible_endpoint() -> None:
    seen, transport = _capture(
        {"choices": [{"message": {"content": "Ten."}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 7, "completion_tokens": 1}}
    )  # fmt: skip
    result = await GroqProvider(transport).chat(KEY, ChatRequest(
        model="openai/gpt-oss-120b", messages=[ChatMessage("user", "Price?")]
    ))  # fmt: skip
    assert result.text == "Ten." and result.provider == "groq"
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(req.url)
    assert json.loads(req.content)["model"] == "openai/gpt-oss-120b"


async def test_gemini_invalid_key_400_is_auth_not_bad_request() -> None:
    # Gemini rejects a bad key with HTTP 400 / API_KEY_INVALID; it must not read as a model error.
    body: dict[str, object] = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                      "details": [{"reason": "API_KEY_INVALID"}]}}  # fmt: skip
    _, transport = _capture(body, 400)
    with pytest.raises(ProviderError) as exc:
        await GeminiProvider(transport).chat(KEY, REQ)
    assert exc.value.kind is ErrorKind.AUTH


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


# --- streaming --------------------------------------------------------------------------------


def _sse(*events: object, done: bool = False) -> bytes:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def _stream_transport(
    body: bytes, status: int = 200
) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body,
                              headers={"content-type": "text/event-stream"})  # fmt: skip

    return seen, httpx.MockTransport(handler)


async def _collect(provider: object) -> tuple[list[str], object]:
    deltas: list[str] = []
    final: object = None
    async for item in provider.stream(KEY, REQ):  # type: ignore[attr-defined]
        if isinstance(item, TextDelta):
            deltas.append(item.text)
        else:
            assert isinstance(item, ChatResult)
            final = item
    return deltas, final


async def test_openai_stream() -> None:
    seen, transport = _stream_transport(_sse(
        {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
        done=True,
    ))  # fmt: skip
    deltas, final = await _collect(OpenAIProvider(transport))
    assert deltas == ["Hel", "lo"]
    assert final.text == "Hello" and final.input_tokens == 7 and final.output_tokens == 2  # type: ignore[attr-defined]
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


async def test_groq_stream_reads_usage_from_x_groq() -> None:
    seen, transport = _stream_transport(_sse(
        {"choices": [{"delta": {"content": "Hi"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}],
         "x_groq": {"usage": {"prompt_tokens": 3, "completion_tokens": 1}}},
        done=True,
    ))  # fmt: skip
    deltas, final = await _collect(GroqProvider(transport))
    assert deltas == ["Hi"] and final.output_tokens == 1  # type: ignore[attr-defined]
    assert "stream_options" not in json.loads(seen[0].content)


async def test_anthropic_stream() -> None:
    _, transport = _stream_transport(_sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 9}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "there"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
        {"type": "message_stop"},
    ))  # fmt: skip
    deltas, final = await _collect(AnthropicProvider(transport))
    assert deltas == ["Hi ", "there"]
    assert final.text == "Hi there" and final.input_tokens == 9 and final.output_tokens == 2  # type: ignore[attr-defined]


async def test_anthropic_stream_error_event_is_an_outage() -> None:
    _, transport = _stream_transport(_sse(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ))  # fmt: skip
    with pytest.raises(ProviderError) as exc:
        await _collect(AnthropicProvider(transport))
    assert exc.value.kind == ErrorKind.UNAVAILABLE


async def test_gemini_stream() -> None:
    seen, transport = _stream_transport(_sse(
        {"candidates": [{"content": {"parts": [{"text": "Bon"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "jour"}]}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2}},
    ))  # fmt: skip
    deltas, final = await _collect(GeminiProvider(transport))
    assert deltas == ["Bon", "jour"] and final.output_tokens == 2  # type: ignore[attr-defined]
    assert seen[0].url.path.endswith("/model-x:streamGenerateContent")
    assert seen[0].url.params["alt"] == "sse"
    assert KEY not in str(seen[0].url)


@pytest.mark.parametrize(("status", "kind"), [(401, ErrorKind.AUTH), (429, ErrorKind.RATE_LIMIT),
                                              (503, ErrorKind.UNAVAILABLE)])  # fmt: skip
async def test_stream_http_errors_are_classified(status: int, kind: ErrorKind) -> None:
    _, transport = _stream_transport(b'{"error": "nope"}', status)
    with pytest.raises(ProviderError) as exc:
        await _collect(OpenAIProvider(transport))
    assert exc.value.kind == kind and KEY not in str(exc.value)


async def test_stream_garbage_is_an_outage_and_network_errors_are_transient() -> None:
    _, transport = _stream_transport(b"data: {not json\n\n")
    with pytest.raises(ProviderError) as exc:
        await _collect(OpenAIProvider(transport))
    assert exc.value.kind == ErrorKind.UNAVAILABLE

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProviderError) as exc:
        await _collect(OpenAIProvider(httpx.MockTransport(boom)))
    assert exc.value.kind == ErrorKind.TRANSIENT
