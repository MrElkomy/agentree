"""Scripted provider for tests and local demos. Never calls the network."""

import asyncio
import json
import re
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agentree.llm.base import (
    ChatRequest,
    ChatResult,
    ErrorKind,
    ProviderError,
    ProviderName,
    StreamItem,
    TextDelta,
)


def _chunks(text: str) -> list[str]:
    """Word-sized pieces that join back to `text` exactly."""
    return re.findall(r"\S+\s*|\s+", text)


@dataclass(frozen=True)
class Interrupted:
    """Scripted stream that sends `text`, then fails with `kind` (a mid-stream outage)."""

    text: str
    kind: ErrorKind = ErrorKind.TRANSIENT


@dataclass
class FakeProvider:
    name: ProviderName = ProviderName.OPENAI
    replies: deque[str | ErrorKind | Interrupted] = field(default_factory=deque)
    valid_keys: set[str] | None = None  # None: any key is accepted
    calls: list[tuple[str, ChatRequest]] = field(default_factory=list)

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult:
        self.calls.append((api_key, request))
        if self.valid_keys is not None and api_key not in self.valid_keys:
            raise ProviderError(self.name, ErrorKind.AUTH, 401)
        reply = self.replies.popleft() if self.replies else "ok"
        if isinstance(reply, ErrorKind):
            raise ProviderError(self.name, reply)
        if isinstance(reply, Interrupted):
            raise ProviderError(self.name, reply.kind)
        return ChatResult(text=reply, provider=self.name, model=request.model,
                          input_tokens=10, output_tokens=len(reply.split()))  # fmt: skip

    async def stream(self, api_key: str, request: ChatRequest) -> AsyncIterator[StreamItem]:
        self.calls.append((api_key, request))
        if self.valid_keys is not None and api_key not in self.valid_keys:
            raise ProviderError(self.name, ErrorKind.AUTH, 401)
        reply = self.replies.popleft() if self.replies else "ok"
        if isinstance(reply, ErrorKind):
            raise ProviderError(self.name, reply)
        for piece in _chunks(reply.text if isinstance(reply, Interrupted) else reply):
            yield TextDelta(piece)
        if isinstance(reply, Interrupted):
            raise ProviderError(self.name, reply.kind)
        yield ChatResult(text=reply, provider=self.name, model=request.model,
                         input_tokens=10, output_tokens=len(reply.split()))  # fmt: skip


_interrupted: set[str] = set()  # demo mode only: messages whose reply was already cut off

DEMO_REPLY = (
    "This is a demo reply from Agentree's local demo mode. No AI provider was called. "
    "Connect a real provider key to get real answers."
)


@dataclass
class DemoProvider:
    """Canned replies for local demos and browser E2E tests (llm_demo_mode, dev only)."""

    name: ProviderName = ProviderName.OPENAI

    async def stream(self, api_key: str, request: ChatRequest) -> AsyncIterator[StreamItem]:
        result = await self.chat(api_key, request)
        last = request.messages[-1].content if request.messages else ""
        # Browser tests: the first reply to a message asking to "simulate an interruption"
        # breaks off mid-way (a retry of the same message then succeeds).
        interrupt = "simulate an interruption" in last.lower() and last not in _interrupted
        pieces = _chunks(result.text)
        for i, piece in enumerate(pieces):
            if interrupt and i == len(pieces) // 2:
                _interrupted.add(last)
                raise ProviderError(self.name, ErrorKind.TRANSIENT)
            await asyncio.sleep(0.02)  # visible streaming in demos and browser tests
            yield TextDelta(piece)
        yield result

    async def chat(self, api_key: str, request: ChatRequest) -> ChatResult:
        text = DEMO_REPLY
        system = request.messages[0].content if request.messages else ""
        asked = request.messages[-1].content.lower() if request.messages else ""
        result = re.search(r"Query on d1: .*\nResult \(1 rows\):\nrows\n(\d+)", system)
        if result:  # Data Analyst, after its uploaded-table query ran (Task 18b)
            return ChatResult(text=f"Your table has {result.group(1)} rows.",
                              provider=self.name, model=request.model)  # fmt: skip
        if "<<SQL d1:" in system and "rows" in asked and "Uploaded tables" in system:
            return ChatResult(text="<<SQL d1: SELECT COUNT(*) AS rows FROM data>>",
                              provider=self.name, model=request.model)  # fmt: skip
        if "<<<COMPUTED_NUMBERS" in system:  # Data Analyst: quote a computed number
            block = system.split("Last 30 days", 1)[-1]
            found = re.search(r"- Visitor conversations: (\d+)", block)
            count = found.group(1) if found else "0"
            return ChatResult(text=f"In the last 30 days you had {count} visitor conversations.",
                              provider=self.name, model=request.model)  # fmt: skip
        if "You maintain short notes about a customer" in system:  # customer memory job
            item = {"category": "interest", "value": "Demo interest in the business's products"}
            return ChatResult(text=json.dumps({"items": [item]}), provider=self.name,
                              model=request.model)  # fmt: skip
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
        # Mimic the resolve marker when the visitor says their issue is solved.
        elif (
            re.search(r"\b(solved|resolved|that worked)\b", last, re.I)
            and "<<RESOLVED>>" in request.messages[0].content
        ):
            text = "Glad that's sorted! Have a great day.\n<<RESOLVED>>"
        else:
            text = _demo_route(request.messages[0].content, last) or text
        return ChatResult(text=text, provider=self.name, model=request.model)


def _demo_route(system: str, last: str) -> str | None:
    """Mimic agent routing (agents/prompts.py) for demos and browser tests: technical problems
    go to Technical Support, service questions to Customer Service, buying questions back to
    Sales, when that teammate is listed."""
    if re.search(r"\b(error|broken|not working|install|setup)\b", last, re.I) and (
        "  - technical_support:" in system
    ):
        note = f"the customer reports a problem: {last[:80]}"
        return (
            f"Let me bring in our Technical Support teammate.\n<<ROUTE technical_support: {note}>>"
        )
    if re.search(r"\b(refund|return|policy|complaint)\b", last, re.I) and (
        "  - customer_service:" in system
    ):
        note = f"the customer has a service question: {last[:80]}"
        return f"Let me bring in our Customer Service teammate.\n<<ROUTE customer_service: {note}>>"
    if re.search(r"\b(buy|price|quote|order)\b", last, re.I) and "  - sales:" in system:
        note = "the problem is solved; the customer now wants to buy"
        return f"I'll hand you back to our Sales teammate for that.\n<<ROUTE sales: {note}>>"
    if "the Technical Support of" in system:
        return "Technical Support here. " + DEMO_REPLY
    if "the Customer Service of" in system:
        return "Customer Service here. " + DEMO_REPLY
    return None
