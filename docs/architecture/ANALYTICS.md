# Analytics and the Data Analyst (Task 18a)

The business's own numbers, computed by Agentree and never by a model. Code:
`agentree/analytics/` (metrics library, Excel export, API), migration 0020, the Data Analyst in
`agents/` (registry, prompts, `service._stream_turn`).

## Daily metrics (approved: privacy-conscious daily aggregates, own retention)

`daily_metrics(business_id, day, metric, value)` (RLS): counts per business per **UTC day**.
No message text, no customer data, no ids of people. Computed by the worker every
`AGENTREE_METRICS_INTERVAL_SECONDS` (default 3600) through the SECURITY DEFINER
`agentree_compute_daily_metrics(day)` (returns a count only): today and yesterday on every pass,
plus any of the last 30 days not computed yet (`metric_days`). Older days cannot be recomputed:
raw messages are deleted at 30 days, which is why the aggregates exist. **Kept 13 months (400
days)**, then deleted by the same function.

| Metric | Source |
|---|---|
| conversations | public/widget conversations started that day |
| visitor_messages, ai_replies, team_replies | messages in public/widget conversations |
| agent_handoffs | audit `agent.handoff` on public/widget channels |
| handoffs_to_team | audit `conversation.handoff_requested` |
| resolved | audit `conversation.resolved` |
| leads | audit `lead.created` |
| customers_verified | audit `customer.verified` |

Rates (lead, handoff-to-team, resolution) are computed in code from the totals. A day the job
has not computed is reported as **missing (unknown)**, never as zero.

## Monthly summary and Excel export

`GET /api/businesses/{id}/analytics/summary?month=YYYY-MM` (members) and
`GET …/analytics/export?month=YYYY-MM` (an `.xlsx` attachment): sheets **Summary**, **Daily** and,
for Owners and Admins only, **Leads** (created that month, with contact details). Visitor text
is always written as a text cell, never a formula (spreadsheet formula injection). The
dashboard page is **Analytics** (month picker, totals, rates, day by day, Download Excel). The
business can upload the file to Google Drive; reading the business's Google Sheets directly
comes with the Google Sheets connection (after Task 18).

## The Data Analyst (internal)

Available since Task 18a, off until a business turns it on; internal (members only, in the test
chat): guests can never reach it or be routed to it. Its prompt holds a delimited
`COMPUTED_NUMBERS` block (last 7 days, last 30 days, this month, last month). **Every number in
its reply must appear in that block or in the question** (`prompts.cited_numbers_ok`; thousands
separators and Arabic-Indic digits understood). Otherwise the reply is replaced by a notice and
the computed numbers themselves, so an invented, rounded or forecast number never reaches the
team.

## Tests

`tests/test_analytics.py`: counts from real activity per business; uncomputed days are missing,
not zero; invalid/future months; 13-month retention and the function's day guard; the export's
sheets by role and formula injection; the cited-number check; the Data Analyst's prompt and the
replacement of an invented number; guests never reach it. Isolation matrix covers the analytics
routes. E2E: the last part of `e2e/agents.spec.ts`.
