"""Scripted provider for tests and local demos. Never calls the network."""

from collections import deque
from dataclasses import dataclass, field

from agentree.llm.base import ChatRequest, ChatResult, ErrorKind, ProviderError, ProviderName


@dataclass
class FakeProvider:
    name: ProviderName = ProviderName.OPENAI
    replies: deque[str | ErrorKind] = field(default_factory=deque)
    valid_keys: set[str] | None = None  # None: any key is accepted
    calls: list[tuple[str, ChatRequest]] = field(default_factory=list)

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult:
        self.calls.append((api_key, request))
        if self.valid_keys is not None and api_key not in self.valid_keys:
            raise ProviderError(self.name, ErrorKind.AUTH, 401)
        reply = self.replies.popleft() if self.replies else "ok"
        if isinstance(reply, ErrorKind):
            raise ProviderError(self.name, reply)
        return ChatResult(text=reply, provider=self.name, model=request.model,
                          input_tokens=10, output_tokens=len(reply.split()))  # fmt: skip
