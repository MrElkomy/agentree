# Agent framework, routing and shared context (Tasks 14–15)

Agentree's AI team is five fixed roles. A business decides which of them work for it, what they
are called and which tools they hold; agents hand a conversation to a better-suited teammate,
and the customer does not repeat themselves. Everything that decides access is server-side.

## Roles (`agentree/agents/registry.py`)

| Role | Audience | Built | Default |
|---|---|---|---|
| `sales` | public | Task 06 (full) | on |
| `customer_service` | public | Task 15 (full) | off |
| `technical_support` | public | Task 15 (full) | off |
| `data_analyst` | internal | Task 18 — cannot be enabled yet | off |
| `executive` | internal | Task 20 — cannot be enabled yet | off |

Each definition is versioned (`version`, bump when a role's prompt or behaviour changes) and
carries its title, audience, what it handles, and its Action Gateway allowlist
(`actions.service.PERMISSIONS`): Sales holds `create_lead`, `update_lead`,
`create_follow_up_task`; Customer Service holds `resolve_conversation`; Technical Support holds
none (it guides, people act).

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
by the 30-day retention job (composite FK `ON DELETE CASCADE`). Since Task 16 the block also
holds the verified customer's memory, filtered to the categories the answering role may read
(`CUSTOMERS.md`).

## Customer Service and Technical Support (Task 15)

Both are public agents on this framework (no separate architecture): role prompts in
`agents/prompts.py`, the same routing, handoff markers, team context and escalation to the
inbox (`<<HANDOFF>>`, `INBOX.md`).

- **Customer Service** answers general questions, policies and service information from
  published knowledge only. It cannot see orders, accounts or payments and never states an order
  status, refund decision or exception, or promises anything; such requests, complaints and
  sensitive matters go to the team. Technical problems route to Technical Support.
- **Technical Support** diagnoses first (one or two questions at a time), then suggests small
  numbered steps supported by the knowledge. It has no access to accounts, devices or systems,
  so every step is a suggestion: it never says it checked, reset or changed anything, never asks
  for passwords, codes or remote access, and escalates when a fix needs privileged access or the
  steps did not help. Non-technical questions route back to Sales or Customer Service.
- The prompts only describe; the backend enforces: no tools for Technical Support, no lead
  capture for either (a `<<LEAD …>>` from them is dropped), routes only to allowed public
  teammates, no internal agents.

### Knowledge scoping

`knowledge_entries.agent_roles` (migration 0016, expand-only): empty means every agent, else
only the listed roles may use the entry. `knowledge.retrieve(..., role=)` filters in SQL, per
agent and per hop (after a handoff the next agent retrieves again with its own role). Changing
the scope returns a published entry to draft, like any edit. Unknown roles are refused
(422 `invalid_agent_roles`). The knowledge page has "All agents / Only these agents".

### Who may resolve a conversation (approved PO decision)

| Conversation led by | Team member | Visitor | The agent |
|---|---|---|---|
| Customer Service | yes | yes (open or waiting for a person; not while a member handles it) | yes, with its `resolve_conversation` tool on, after the customer confirms |
| Sales, Technical Support | yes | no (403 `resolve_not_allowed`) | no (marker ignored) |

"Led by" is the conversation's `active_agent`, set by the backend. Roles with
`shared_resolution` are fixed in the registry; the visitor's button appears only when the backend
returns `can_resolve: true` (chat replies and the conversation view). The agent's `<<RESOLVED>>`
marker is accepted only through `_may_resolve` (role + Action Gateway `authorize` against the
business's tools) and never together with a route or handoff. Audit: `conversation.resolved`
with `resolved_by` (member, visitor, agent).

## Tests

`tests/test_support_agents.py` (Task 15): role prompts; complete definitions and tool limits;
knowledge grounding by business, publication and scope; no-match instruction; scope validation
and re-publishing; Sales → Customer Service → Technical Support → Customer Service with notes
and history; visitor-closed and disabled agents; forged internal routes; escalation and the AI
staying quiet; human takeover; resolution by the agent (and not without its tool, not by Sales
or Technical Support, not with a handoff), by the visitor (not for Sales, not for another guest
or business), by a member (Sales included); no lead capture by support agents; streamed replies
hide the marker. E2E: `e2e/support-agents.spec.ts`.

`tests/test_agents.py`: configuration rules and audit; Sales → Technical Support → Sales with
history and notes; disabled and visitor-closed agents never routed to guests; forged route
targets (internal, unknown, same agent); guests cannot pick internal or disabled agents; one
route per message; disabled active agent; no public agent; lead suggestions only from an agent
holding `create_lead`; business tool choices bind the gateway; console reaches agents closed
to visitors; SSE `agent`/`handoff` events; RLS on handoffs and deletion by retention; shared
context without contact details; marker validation. The isolation matrix covers
`/agents/{role}`. E2E: `e2e/agents.spec.ts`.
