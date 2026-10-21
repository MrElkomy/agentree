# Leads and the Action Gateway (Task 11)

## Flow
1. **Agent asks.** In public conversations (public page, website widget) the Sales Agent prompt
   asks interested visitors for a name and an email or phone number.
2. **Marker, not action.** After the visitor writes contact details, the model appends a hidden
   line `<<LEAD {"name","email","phone","need"}>>`. The backend strips every marker before the
   reply is stored or shown (`agents.prompts.split_lead_marker`). The marker is untrusted: an email
   or phone number is kept only if the visitor wrote it in this conversation, so the model cannot
   invent contact details. The result is returned as `lead_suggestion` in the chat response.
3. **Visitor confirms.** The chat shows a form prefilled from the suggestion (or empty, via "Leave
   your details"). Nothing is saved until the visitor ticks *"I agree that {business} may contact
   me about my request"* and presses *Send my details*. Consent is therefore explicit and recorded
   (`consent_at`), never inferred by the model.
4. **Gateway.** `POST /api/public/{slug}/leads` (guest token; own conversation only) runs
   `create_lead` (or `update_lead` when the conversation already has a lead) through
   `agentree.actions` as the `sales` agent.
5. **Follow-up.** Owners and Admins get a branded email per **new** lead (not on updates). Members
   see Leads in the dashboard, change status (new → contacted → qualified → won / lost) and keep
   notes; Admins and Owners can delete a lead (e.g. a data-deletion request).

## Action Gateway (`agentree/actions`)
- **Authorization:** fixed allowlist per agent role (`PERMISSIONS`); today only `sales` may run
  `create_lead` / `update_lead`. Model output never chooses the action or the agent.
- **Idempotency:** `action_executions` (RLS) records `(business_id, idempotency_key)` in the same
  transaction as the action. A retry with the same key and parameters returns the original
  result; the same key with different parameters → 409 `idempotency_conflict`. Concurrent claims
  of one key wait on the unique index. The visitor's form uses one key per submission attempt.

## Data
- `leads` (migration 0010, RLS): one per conversation; `conversation_id` is cleared, not the lead,
  when the 30-day retention job deletes the conversation (`ON DELETE SET NULL (conversation_id)`).
- Contact details never go to logs or the audit trail. Audit actions: `lead.created`,
  `lead.updated` (visitor re-submitted), `lead.status_changed`, `lead.notes_updated`,
  `lead.deleted` (details: channel, agent, from/to status only).
- Limits: 10 submissions per guest session per hour (plus the per-IP limit).

## API
| Method | Path | Who |
|---|---|---|
| POST | `/api/public/{slug}/leads` | guest token, own conversation |
| GET | `/api/businesses/{id}/leads?status=&before=&limit=` | member |
| GET | `/api/businesses/{id}/leads/{lead_id}` (+ transcript while retained) | member |
| PATCH | `/api/businesses/{id}/leads/{lead_id}` `{status?, notes?}` | member |
| DELETE | `/api/businesses/{id}/leads/{lead_id}` | admin+ |

## Follow-up reminders (Task 11b)
People contact customers; the agent only schedules reminders for them (PO decision 2026-10-21:
option A now; agent-sent follow-up messages come later with Approvals, Task 19).
- **Rules** (fixed by Agentree for now; per-business sales playbooks come with agent configuration):
  every new lead gets one *first contact* task from the Sales Agent, due 24 hours later, created
  through the gateway (`create_follow_up_task`, idempotent per lead); moving the lead past *new*
  closes it; the agent may hold at most 3 open tasks per lead, members 20; due dates within a year
  (agent: 15 minutes to 30 days).
- **Members** add reminders (title, due date, optionally a member to remind), mark them done or
  reopen them. Every change is audited (`follow_up.created` / `follow_up.updated`).
- **Reminders:** the worker (`python -m agentree.worker`, every `AGENTREE_FOLLOW_UP_INTERVAL_SECONDS`,
  default 300) claims overdue open tasks through the SECURITY DEFINER function
  `agentree_claim_due_follow_ups` (ids only, marked reminded atomically, `SKIP LOCKED`), then
  emails one branded reminder per task — to the assignee, or to Owners and Admins when nobody is
  assigned. A failed send clears the mark so the next pass retries. Changing the due date
  re-arms the reminder.

| Method | Path | Who |
|---|---|---|
| GET / POST | `/api/businesses/{id}/leads/{lead_id}/follow-ups` | member |
| PATCH | `/api/businesses/{id}/follow-ups/{task_id}` `{status?, due_at?, assignee_user_id?}` | member |

## Decisions (Product Owner, 2026-10-21)
- **Lead retention:** leads are kept until the business deletes them, and will also be written to
  the business's Google Sheet (see the roadmap's tracking table).
