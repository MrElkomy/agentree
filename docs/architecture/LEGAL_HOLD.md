# Legal hold and retention records (Task 21)

## Legal hold
- Raw conversations are deleted 30 days after their last message (AGT-010, the retention job).
  A conversation on **legal hold** is skipped. The purge function has honoured
  `conversations.legal_hold` since 0006.
- **Owner only:** `PUT /api/businesses/{id}/inbox/{conversation_id}/legal-hold {held}`. Admins
  and members get 403. Each change is audited (`conversation.legal_hold`, `held: true|false`) and
  appears in the activity log; repeating the same state is not audited again.
- In the web: a "Legal hold" panel on each Inbox conversation (button for owners, status for
  everyone). Inbox lists and details carry `legal_hold`.
- **Releasing** a hold makes the conversation eligible again: if it is already older than the
  window, the next retention pass deletes it.

## Retention run records
- Every retention pass that runs leaves a record in `retention_runs`. The table is global: times
  (started, finished, cutoff) and counts (rows deleted, batches) only, with no tenant data.
- Records are written only through `agentree_record_retention_run` (SECURITY DEFINER). It
  validates the times and counts and keeps 400 days of records. The app role can read the table
  but has no INSERT/UPDATE/DELETE on it, so a record cannot be changed.
- If writing the record fails, the deletions stand and the failure is logged as an error.
- Owners see only when the job last ran (Analytics → Data retention,
  `GET /api/businesses/{id}/analytics/retention`), never the counts, which span all businesses.

## Per-agent outcomes (Analytics)
The daily metrics function also stores `agent:<role>:<outcome>` per business and UTC day, from
public and widget conversations:

| Outcome | Counted from |
|---|---|
| `conversations` | conversations the agent answered at least once with AI |
| `replies` | its AI replies (fixed away messages are not counted) |
| `resolved` | `conversation.resolved` while it led the conversation |
| `to_team` | `conversation.handoff_requested` while it led (the audit records the agent since Task 21) |
| `handoffs_out` | `agent.handoff` from it |

Shown as "Agent outcomes" on the Analytics page, next to the current **AI key health** (from the
AI Providers status: working / some errors / recovering / down).

## Tests
`tests/test_legal_hold.py` covers:
- legal hold: owners only, audited once per change, shown in the inbox;
- retention keeping exactly the held conversations, and deleting one after its release;
- a record for every run, matching its result;
- the app unable to insert, update or delete records, and bad records refused;
- agent outcomes coming from stored activity, separately for each business.

E2E: `inbox.spec.ts` places and releases a hold; `agents.spec.ts` checks the key health and
retention panels.
