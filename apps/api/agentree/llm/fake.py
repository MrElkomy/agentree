"""Scripted provider for tests and local demos. Never calls the network."""

import json
import re
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


DEMO_REPLY = (
    "This is a demo reply from Agentree's local demo mode. No AI provider was called. "
    "Connect a real provider key to get real answers."
)


@dataclass
class DemoProvider:
    """Canned replies for local demos and browser E2E tests (llm_demo_mode, dev only)."""

    name: ProviderName = ProviderName.OPENAI

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult:
        text = DEMO_REPLY
        # Mimic the Sales Agent's lead marker when the visitor writes an email (see prompts.py).
        last = request.messages[-1].content if request.messages else ""
        email = re.search(r"[^@\s]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", last)
        if email and "<<LEAD" in request.messages[0].content:
            lead = {"name": "", "email": email.group(0), "phone": "", "need": "Demo request"}
            text = f"{DEMO_REPLY}\n<<LEAD {json.dumps(lead)}>>"
        # Mimic the handoff marker when the visitor asks for a person.
        elif (
            re.search(r"\b(human|person)\b", last, re.I)
            and "<<HANDOFF" in request.messages[0].content
        ):
            text = "Let me connect you with the team.\n<<HANDOFF>>"
        return ChatResult(text=text, provider=self.name, model=request.model)
