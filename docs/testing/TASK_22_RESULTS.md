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

## Next
B4 new E2E journeys, B5 reliability (incl. large XLSX memory), B6 staging checklist (PO), B8
release-readiness documents. PO decisions: verified recipients for automatic follow-ups (SR-01),
Turnstile keys, separate production server (SH-01), read-only server checks SH-04..SH-08.
