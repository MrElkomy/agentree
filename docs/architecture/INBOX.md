# Human inbox and handoff (Task 12)

Visitors on the public page and website chat can reach a person. When they ask, or when the AI
cannot help, the conversation waits in the business's **Inbox** and Owners and Admins get an
email. A member takes over and replies in the same chat; the AI stays quiet until the member hands
the conversation back.

## Conversation status

`conversations.status` (public and widget conversations; console conversations stay `open` and
never appear in the inbox):

| Status | Meaning | Who answers the visitor |
|---|---|---|
| `open` | Normal chat | The AI |
| `needs_human` | Handoff requested, nobody has taken over | Nobody: visitor messages are stored, the AI is paused |
| `human_active` | A member took over (`assignee_user_id`) | The team (members reply) |
| `resolved` | Closed by a member, or (Customer Service and Technical Support conversations) by the visitor or the agent | The AI again if the visitor writes (back to `open`) |

Transitions (all in `agentree/agents/inbox.py`, row-locked, audited):

- `open`/`resolved` → `needs_human`: the visitor presses **Talk to a person**
  (`POST /api/public/{slug}/conversations/{id}/handoff`), or the AI ends its reply with the
  `<<HANDOFF>>` marker. The marker is stripped by the backend and never shown or stored.
  `handoff_reason` is `visitor` or `agent`. Only this transition sends the email alert, so repeats
  do not spam the team.
- `needs_human` → `open`: the visitor chooses **Continue with the assistant** (`DELETE …/handoff`).
  Once a person is active the visitor cannot cancel.
- any → `human_active`: a member presses **Take over** (assignee = that member; also takes over
  from a teammate).
- `needs_human`/`human_active` → `open`: **Hand back to AI** (clears the assignee).
- any → `resolved`: **Resolve** by a member (every conversation, Sales included).
- Task 15 (Technical Support added 2026-10-22), only while the conversation's active agent is
  Customer Service or Technical Support (roles with shared resolution in `agents/registry.py`;
  Sales conversations stay team-only):
  - `open`/`needs_human` → `resolved`: the visitor presses **My issue is resolved**
    (`POST /api/public/{slug}/conversations/{id}/resolve`; 403 `resolve_not_allowed` for other
    agents' conversations, 409 `conversation_state` while a member is handling it).
  - `open` → `resolved`: the agent ends its reply with `<<RESOLVED>>` after the customer confirmed
    the issue is solved. Accepted only from an agent with shared resolution whose business left
    its `resolve_conversation` tool on (Action Gateway), never together with a route or handoff.
- Assign: any member of the business, or nobody; other user ids are refused (`invalid_assignee`).

The AI never decides who may take over or reply; the backend enforces state and membership.

## Messages

`conversation_messages.role` now also allows `human` (a team member's reply) with
`author_user_id` set; a check constraint ties the two together. Members see who wrote each reply;
visitors see only "{business} team" (the guest API returns role and content, never member ids).
When the AI answers again it sees team replies in its history as assistant turns prefixed with
"[Team member]", so context carries across take-over and hand-back.

Replies are 1–4,000 characters, stored like other messages (same 30-day retention), and never
logged.

## API

Dashboard (any member of the business; others get 404):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/businesses/{id}/inbox?status=&before=&limit=` | Newest activity first, counts per status, `next_before` cursor |
| GET | `/api/businesses/{id}/inbox/{conversation_id}` | Conversation + transcript |
| POST | `…/{conversation_id}/take-over` · `release` · `resolve` | 204; 409 `conversation_state` when the action does not apply |
| POST | `…/{conversation_id}/assign` | `{"assignee_user_id": uuid \| null}` |
| POST | `…/{conversation_id}/reply` | `{"content": "…"}`; 201 with the stored message; only while `human_active` |

Public (guest token required, the conversation must belong to that guest session):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/public/{slug}/conversations/{id}` | Status + messages (polled every 5 s while paused) |
| POST | `/api/public/{slug}/conversations/{id}/handoff` | Visitor asks for a person; 10/hour per guest session |
| DELETE | `/api/public/{slug}/conversations/{id}/handoff` | Continue with the assistant |

`POST /chat` now returns `status`; while paused, `reply` is empty and no provider is called.

## Alerts

`notify_handoff` emails Owners and Admins (branded layout, sent in the background after the
response) with a link to `/b/{business}/inbox/{conversation}`. The email names the business and
whether the visitor or the AI asked; it never includes message content.

Web Push for handoff alerts was proposed by the PO (2026-10-21); its placement awaits PO approval
and it is not part of this task.

## Audit

`conversation.handoff_requested` (reason), `conversation.handoff_canceled`,
`conversation.taken_over`, `conversation.assigned` (assigned: true/false),
`conversation.released`, `conversation.resolved` (`resolved_by`: member, visitor or agent; the
agent's role for the last two). Details hold the channel and these flags only,
never message content.

## Limits and follow-ups

- Updates reach the dashboard and the visitor by polling every 5 seconds (no push channel yet;
  Task 13 adds streaming for AI replies).
- A member taking over while the AI is mid-reply can still see that one AI reply land.
- Not in this task: SLA timers, canned replies, a lead link on the conversation page, webhook
  handoff (proposed deferral in the roadmap tracking table).
