"""Agentree-owned LLM provider interface. Business logic depends on this, never on a vendor SDK.

Provider adapters receive the customer's API key per call (BYOK); keys are never stored on
adapter instances, logged, or included in exception messages.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


class ProviderName(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    GROQ = "groq"


class ErrorKind(StrEnum):
    AUTH = "auth"  # key invalid or revoked
    QUOTA = "quota"  # account out of credit / quota
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"  # provider outage / overload
    TRANSIENT = "transient"  # network error or timeout
    BAD_REQUEST = "bad_request"  # our request is wrong (model name, parameters)

    @property
    def availability_problem(self) -> bool:
        """Errors that justify failing over to the backup provider."""
        return self in {ErrorKind.QUOTA, ErrorKind.RATE_LIMIT, ErrorKind.UNAVAILABLE,
                        ErrorKind.TRANSIENT, ErrorKind.AUTH}  # fmt: skip


class ProviderError(Exception):
    def __init__(self, provider: str, kind: ErrorKind, status: int | None = None) -> None:
        super().__init__(
            f"{provider} request failed: {kind}" + (f" (HTTP {status})" if status else "")
        )
        self.provider = provider
        self.kind = kind
        self.status = status


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: Sequence[ChatMessage]
    max_tokens: int = 1024
    temperature: float = 0.3

    def __post_init__(self) -> None:
        if not MODEL_RE.fullmatch(self.model):
            raise ValueError("invalid model name")


@dataclass(frozen=True)
class ChatResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw_finish_reason: str | None = field(default=None, compare=False)


class LLMProvider(Protocol):
    name: ProviderName

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult: ...
