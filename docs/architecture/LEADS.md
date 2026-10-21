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

## Open decisions (Product Owner)
- **Lead retention:** leads are kept until deleted by the business; no automatic expiry yet.
- **Follow-up actions** (`create_follow_up_task`): proposed for this task in the roadmap's tracking
  table, still awaiting PO approval of placement — not implemented here.
