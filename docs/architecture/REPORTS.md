# Email reports and alerts (Task 20c)

## Email reports (`agentree/reports`)
- **Settings** (Analytics page, Owners/Admins): off (default), every day, or every week on a
  chosen weekday. There is also an optional "notes from the Executive Assistant" setting
  (`report_settings`, RLS).
- **When:** the worker (every `AGENTREE_REPORTS_INTERVAL_SECONDS`, default 300) claims due
  businesses through `agentree_claim_due_reports` (SECURITY DEFINER, ids only). A report is due
  from 08:00 in the business's time zone (its business hours' zone, else UTC), at most once per
  local day. Weekly reports go on the chosen weekday only.
- **Who:** Owners and Admins. "Send me a report now" emails only the requester (5 per hour).
- **What:** only computed numbers (`agentree.analytics`, UTC days), each next to the period
  before:
  - daily = yesterday vs the day before; weekly = the last 7 complete days vs the 7 before;
  - conversations, visitor messages, AI replies, away messages, handoffs to the team,
    resolutions, leads and confirmed customers;
  - the rates.

  It also shows what waits now: visitors waiting for a person, leads still new, and requests
  waiting for approval. There are no customer messages and no names.
- **Executive notes** (only when turned on in the report settings and the Executive Assistant
  is on): the business's own AI key writes at most 3 observations and 2 suggestions. Every
  number must appear in the report (`cited_numbers_ok`), otherwise the notes are left out and the
  report goes without them. A provider error does the same. The call counts toward the daily AI
  budget.

## Alerts (email to Owners and Admins, push to their devices)
| Alert | When | How often |
|---|---|---|
| Daily reply budget used up | a visitor's message hits the business's daily AI budget (the visitor sees "busy") | once per business per UTC day |
| A visitor is still waiting | a conversation has waited for a person (`needs_human`) for 30 minutes | once per handoff (`conversations.waiting_alerted_at`, via `agentree_claim_waiting_alerts`) |

Neither alert includes the visitor's messages. Alerts that already existed are unchanged: new
lead, handoff requested, AI key outage, approval needed, follow-up due.

## API
| Method | Path | Who |
|---|---|---|
| GET | `/api/businesses/{id}/report-settings` | member |
| PUT | `/api/businesses/{id}/report-settings` `{frequency, weekday, include_notes}` | admin+ |
| POST | `/api/businesses/{id}/report-settings/test` | admin+ (429 `busy`) |

Audit: `report_settings.updated`.

## Tests
`tests/test_reports.py` covers:
- settings and permissions;
- the report's numbers coming from computed metrics, and a test send going only to the
  requester;
- notes: only with the Executive on, and an invented number drops them;
- scheduled reports going once per period, to Owners and Admins only, and only on the chosen
  weekday;
- the budget alert going once a day;
- the waiting alert going after 30 minutes, once;
- the claim functions refusing bad arguments.

E2E: end of `agents.spec.ts` (weekly settings, "Send me a report now", and the email checked in
Mailpit).
