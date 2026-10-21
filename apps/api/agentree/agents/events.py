"""Server-sent events for a streaming agent turn (shared by the console and public chat).

`agent` starts a reply from that agent; `delta` adds text to it; `restart` drops its partial
text (the backup provider answers instead); `handoff` says the previous agent handed the
conversation to a teammate, whose `agent` event follows. The endpoint adds `done` / `error`.
"""

from agentree.agents.service import AgentStart, Delta, Handoff, Restart
from agentree.core import sse


def encode(item: AgentStart | Delta | Restart | Handoff) -> bytes:
    if isinstance(item, Delta):
        return sse.event("delta", {"text": item.text})
    if isinstance(item, Restart):
        return sse.event("restart", {})
    if isinstance(item, AgentStart):
        return sse.event("agent", {"agent": item.agent, "name": item.name})
    return sse.event("handoff", {"from_agent": item.from_agent, "to_agent": item.to_agent,
                                 "name": item.to_name})  # fmt: skip
