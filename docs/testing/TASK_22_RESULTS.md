# Task 22 — Results (in progress)

## B1 status (2026-10-22)
- Backend suite on `main`: 8 consecutive runs 855/855; 4 random-order runs (pytest-randomly
  seeds 101/202/303/404): 3 green, seed 404 failed `test_audit.py::test_provider_key_changes_are_audited_without_the_key`.
- **Flaky test root cause:** the test asserts the key hint (last 4 chars, hex `3c4d`) is not in
  the audit response; random UUIDs in the response contain that hex substring by chance.
  **Fix (not yet applied):** use fake keys whose last 4 chars are non-hex in `tests/test_audit.py`
  (`SECRET`) and `tests/test_push.py` (`KEY`, same `[-4:]` check).
- gitleaks (full history): no leaks · pip-audit: none · npm audit (prod): 0.
- Branches pushed: 22a (this plan + reviews), 22b bot challenge (876 passed), 22c security fixes
  (866 passed).

## Next steps
1. Apply the flaky-test fix on 22a; run the full suite.
2. E2E (Playwright, local stack) for 22b and 22c (22c adds the open-redirect E2E).
3. Open PRs 22a/22b/22c with evidence; report to the PO.
4. PO decisions: verified recipients for auto follow-ups (SR-01), Turnstile keys, separate
   production server (SH-01), shared-host checks SH-04..SH-08.
