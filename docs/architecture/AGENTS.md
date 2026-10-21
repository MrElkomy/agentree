# Agent framework, routing and shared context (Task 14)

Agentree's AI team is five fixed roles. A business decides which of them work for it, what they
are called and which tools they hold; agents hand a conversation to a better-suited teammate,
and the customer does not repeat themselves. Everything that decides access is server-side.

## Roles (`agentree/agents/registry.py`)

| Role | Audience | Built | Default |
|---|---|---|---|
| `sales` | public | Task 06 (full) | on |
| `customer_service` | public | baseline prompt (Task 15 completes it) | off |
| `technical_support` | public | baseline prompt (Task 15 completes it) | off |
| `data_analyst` | internal | Task 18 — cannot be enabled yet | off |
| `executive` | internal | Task 20 — cannot be enabled yet | off |

Each definition is versioned (`version`, bump when a role's prompt or behaviour changes) and
carries its title, audience, what it handles, and its Action Gateway allowlist
(`actions.service.PERMISSIONS`; today only Sales holds `create_lead`, `update_lead`,
`create_follow_up_task`).

## Per-business configuration (`agent_configs`, migration 0015, RLS)

`enabled`, `display_name`, `public` (visitors may reach it; public roles only), `tools` (a
subset of the role's allowlist) and `version` (+1 on every save). No row means the role's
defaults. API: `GET /api/businesses/{id}/agents` (members), `PUT …/agents/{role}` (Admins+),
audited as `agent.config_updated` (agent, enabled, public, version).

- **Display name** is cosmetic: 1–40 letters/digits (any script), spaces and `.,'&()-`; no
  control characters or markup. It never decides identity, permissions or routing.
- **Tools** narrow the Action Gateway: `claim(..., granted=...)` refuses an action the business
  turned off even if the role allows it. Lead capture follows the Sales Agent's tools: without
  `create_lead` the public page hides "Leave your details" and `POST /leads` answers
  409 `lead_capture_off`; without `create_follow_up_task` a new lead gets no first-contact
  reminder.

## Who may answer (`agents/configs.py`, `Roster`)

- **Guests** (public page, widget): enabled ∧ built ∧ public-audience role ∧ `public = true`.
  Internal roles are unreachable whatever the configuration.
- **Members** (test chat): any enabled, built role, including ones closed to visitors.
- **Entry agent:** the visitor's choice (public page buttons, `agent` on the first message) if
  allowed, else the first allowed role (Sales first). A refused choice is
  422 `invalid_agent` (public) / `agent_unavailable` (console). If the conversation's active
  agent is later disabled, the next message goes to the entry agent.

## Routing and handoffs (`agents/service.py`)

1. The active agent answers. Its prompt lists only the teammates the roster allows for this
   caller (role and what it handles).
2. To hand over, the agent writes one sentence and a last line
   `<<ROUTE role: one-sentence note>>`. The marker is never streamed or stored; the backend
   accepts the role only if it is in that allowed list (unknown, internal, disabled or same
   roles are ignored).
3. The teammate answers the **same message** in the same turn, with the conversation history
   and the team context. At most one handoff per message (the second agent gets no teammates),
   so agents cannot ping-pong.
4. At the end of the turn, in one transaction: the visitor's message, each agent's reply
   (`conversation_messages.agent`), an `agent_handoffs` row (from, to, note), an
   `agent.handoff` audit row (roles and channel only — never the note) and the new
   `conversations.active_agent`. A turn that fails stores nothing.

Streaming adds two events (`agents/events.py`): `agent` (a reply from this agent starts) and
`handoff` (the conversation moved to this teammate). `done` carries every reply of the turn
(`replies`), the answering agent and its display name.

## Shared authorized context

The answering agent's prompt gets a delimited `TEAM_CONTEXT` block (data, not instructions):

- the latest handoff notes of this conversation (up to 3, ≤300 characters each, sanitized:
  one line, no delimiters or markers);
- facts the visitor confirmed in **this** conversation through the lead form: name, need and
  whether contact details were given — never the email address or phone number.

Notes live in `agent_handoffs`, which is tenant-scoped (RLS) and deleted with its conversation
by the 30-day retention job (composite FK `ON DELETE CASCADE`). There is no cross-conversation
customer memory here; that is Task 16.

## Tests

`tests/test_agents.py`: configuration rules and audit; Sales → Technical Support → Sales with
history and notes; disabled and visitor-closed agents never routed to guests; forged route
targets (internal, unknown, same agent); guests cannot pick internal or disabled agents; one
route per message; disabled active agent; no public agent; lead suggestions only from an agent
holding `create_lead`; business tool choices bind the gateway; console reaches agents closed
to visitors; SSE `agent`/`handoff` events; RLS on handoffs and deletion by retention; shared
context without contact details; marker validation. The isolation matrix covers
`/agents/{role}`. E2E: `e2e/agents.spec.ts`.
