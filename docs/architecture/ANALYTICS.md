# Analytics and the Data Analyst (Tasks 18a, 18b)

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

## Uploaded tables (Task 18b)

CSV and Excel files uploaded on the Knowledge page (`KNOWLEDGE_FILES.md`) are kept as they were
uploaded and **profiled** in the background: column names (reduced to letters, digits and `_`),
inferred types (integer, real, text) and the row count; cell values never leave the file. The
first sheet is used and its first row holds the column names. Limits: 200,000 rows, 100 columns.
The Knowledge page shows "Ready for the Data Analyst · N rows, M columns" (or why it failed:
`no_rows`, `too_many_rows`, `too_many_columns`, `damaged_file`, `too_complex`).

The Data Analyst's computed block lists the business's tables (`d1`, `d2`, … newest first, at
most 20) with their columns and row counts. To calculate something it replies with only a marker,
`<<SQL d1: SELECT ...>>`; the backend runs the query and calls the model once more with the
result added to the computed block. **One query per turn**; markers never reach the reply, and an
agent that asks again gets no second query (its reply becomes the computed numbers). Every number
in the final answer must appear in the Agentree numbers, a row count or the query result (not in
file or column names, the SQL or the question's file name), else the reply is replaced as above.

**The sandbox** (`agentree/knowledge/tables.py`, run as a child process by `core.sandbox`):
- 384 MB memory, 20 s CPU, no file writes, a 30 s timeout, one child at a time; no secrets in its
  environment.
- The file is loaded into an **in-memory SQLite** table `data`; values are bound parameters.
- Only one statement, starting with `SELECT` or `WITH`, at most 4,000 characters.
- SQLite's **authorizer** allows reading only the `data` table and calling only allow-listed
  functions (aggregates, rounding, text and date helpers). Everything else is refused by the
  engine: writes, `ATTACH`, `PRAGMA`, schema tables, recursive CTEs, `load_extension`, file
  functions. Attached databases are limited to 0; extension loading is off in Python's sqlite3.
- A progress handler stops queries after 20 million VM steps (`query_too_long`); results are
  capped at 200 rows (50 shown to the model).
- Errors come back as stable codes only (`invalid_sql`, `query_failed`, …), never file content.

**Why SQLite rather than DuckDB** (the roadmap's first idea, TD-15): it ships with Python, uses
far less memory on the shared host, and the refusals above are enforced by the engine itself.
There is no Parquet snapshot: the original upload is parsed per query (files are at most 10 MB).

Members can upload and use the test chat, so members can query their business's tables; visitors
never reach the Data Analyst. A table is a knowledge file: deleting the file removes it.

## Tests

`tests/test_analytics.py`: counts from real activity per business; uncomputed days are missing,
not zero; invalid/future months; 13-month retention and the function's day guard; the export's
sheets by role and formula injection; the cited-number check; the Data Analyst's prompt and the
replacement of an invented number; guests never reach it. Isolation matrix covers the analytics
routes. E2E: the last part of `e2e/agents.spec.ts` (incl. an uploaded table queried in the
test chat).

`tests/test_datasets.py` (18b): profiling on upload and failures; normalised names and cells;
read-only queries and the result cap; sandbox escapes refused (schema tables, multiple
statements, writes, PRAGMA, ATTACH, extensions, file functions, recursion, huge blobs, overlong
SQL); long queries stopped; queries run in the limited child; the analyst answering from a
result, invented numbers and file-name digits refused; failed, unknown and repeated queries;
only the analyst sees tables, and only its own business's.
