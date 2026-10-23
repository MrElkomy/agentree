# Task 22 — Results

## B1 — Automated baseline and stability (2026-10-22/23)
| Check | Result |
|---|---|
| Backend suite on `main`, 8 consecutive runs | 8/8 green (855 passed each) |
| Backend suite, random order (pytest-randomly seeds 101, 202, 303, 404) | 3 green; seed 404: 1 failure (below) |
| gitleaks, full history | no leaks |
| pip-audit (runtime deps) | no known vulnerabilities |
| npm audit (production deps) | 0 vulnerabilities |
| E2E (Playwright, local stack) on 22b + 22c combined | 12/12 passed |
| Backend suite on 22a (flaky fix) | 855 passed |
| Backend suite on 22b / 22c | 876 / 866 passed |

### The intermittent backend failure — found and fixed
- **Test:** `test_audit.py::test_provider_key_changes_are_audited_without_the_key`.
- **Reproduction:** happens in any order, at random: about 1 run in 100 (measured 0.9 % for a
  4-hex string inside 30 random UUIDs).
- **Root cause:** the test checks that the key hint (the key's last 4 characters, `3c4d`, all
  hex) does not appear in the audit response; the response contains random UUIDs, which can
  contain the same 4 hex characters. The product was correct; the assertion was not.
- **Fix:** fake keys whose last 4 characters are not hex (`tests/test_audit.py`, and the same
  pattern in `tests/test_push.py`), so the check stays strict and cannot collide.

### Test-infrastructure notes (not product defects)
- E2E sign-ups share the 10-per-hour per-IP sign-up limit; the suite has exactly 10. New E2E
  tests reuse an existing account. Re-running locally needs `DELETE FROM rate_limit_buckets`.
- The demo provider interrupts a "simulate an interruption" reply once per API process, so a
  local re-run of `reliability.spec.ts` needs a fresh API process.

## B2 — Security review
See `SECURITY_REVIEW.md`: 6 findings fixed (Task 22c), none Critical or High.

## B3 — Bot challenge
Task 22b. Automated tests use a fake verifier; Cloudflare itself is unreachable from the build
container, so the real Turnstile check is a staging step for the PO (B6, needs Turnstile keys).

## B7 — Shared-host review
See `SHARED_HOST_REVIEW.md`.

## B4/B5 — Batch 2: end-to-end journeys and reliability (2026-10-23)
Most journeys were already covered by the existing E2E specs (agents, approvals, hours and pause,
Data Analyst upload, Executive Assistant, email reports, inbox and legal hold, leads, public page
and widget, reliability). Added:

| Test | Result |
|---|---|
| Two businesses in the UI: an owner gets "Business not available" for every page of a business they are not a member of | Pass |
| Phone (390×844): dashboard, inbox, leads, knowledge, AI team, approvals, analytics, members fit without sideways scrolling | Pass |
| Accessibility (axe, WCAG 2 A/AA, serious and critical): sign-in (phone and desktop), the dashboard pages above, public page, widget | **2 defects found and fixed** (below) |
| Arabic message on the public page is shown right to left | Pass |
| Worker: one pass of every job against the E2E database | Pass (exit 0, no errors) |
| Large spreadsheets in the analysis sandbox (50k, 150k, 200k rows, up to 7 MB XLSX) | **1 defect found and fixed** (below); peak child memory 154 MB at 200k rows |

### Defects found in batch 2
| ID | Defect | Severity | Fix | Regression test |
|---|---|---|---|---|
| T22-01 | Data Analyst queries with GROUP BY / ORDER BY failed (`query_failed`) on tables above ~100k rows: SQLite spilled the sort to a temporary file, which the sandbox forbids | Medium | `PRAGMA temp_store = MEMORY` (no file writes, still under the child's memory limit) | `test_large_tables_sort_inside_the_sandbox` (fails without the fix) |
| T22-02 | Sideways-scrolling tables (Analytics day by day, agent outcomes, members) could not be reached by keyboard | Medium (accessibility) | Scroll areas are focusable labelled regions | E2E accessibility scan |
| T22-03 | Low-contrast hint text on the public page chat button (white at 80 % on brand blue) | Low (accessibility) | Full white | E2E accessibility scan |

### Memory and time at the limits (local, one CPU core)
Peak memory of the sandbox child: 58 MB (50k rows), 122 MB (150k), 154 MB (200k). The API process
itself used about 70 MB in this test, so the 384 MB api container has room. A query at 200k rows
takes about 14 s of CPU (the file is parsed again for every query); the child's CPU limit is
20 s, so on a slower server the largest files may answer "too complex". To watch on staging with a
real large file (B6).

## B8 — Batch 3: release readiness (2026-10-23)
- `/privacy` and `/terms` pages (draft text for PO approval), linked from sign-up, the public
  page footer and the chat (public page and widget), with the AI disclosure and retention.
- `docs/operations/CUSTOMER_KEY_GUIDE.md`, `ONBOARDING_RUNBOOK.md`, `MONITORING.md` (gaps and
  proposals), `PILOT_CHECKLIST.md` (the four final gates with status and evidence).

## Next
- Last batch (B6, PO): manual staging checklist, real failover with low-budget keys, restore drill.
- PO decisions: legal text approval, support address, monitoring proposals, proposed deferrals,
  Turnstile keys, production stack on the upgraded server.
