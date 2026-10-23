# First-customer pilot checklist (Task 22 final gates)

Status as of 2026-10-23. ✅ done with evidence · 🟡 partly / waiting on the PO · ❌ open.

## Gate 1 — Onboarding
| Item | Status | Evidence / next step |
|---|---|---|
| In-product flow: sign-up → business → keys → knowledge → agents → public page/widget | ✅ | E2E specs (`apps/web/e2e`), `TASK_22_RESULTS.md` |
| Assisted-setup runbook | ✅ | `ONBOARDING_RUNBOOK.md` |
| Customer key-setup guide | ✅ | `CUSTOMER_KEY_GUIDE.md` |

## Gate 2 — Privacy notice and terms
| Item | Status | Evidence / next step |
|---|---|---|
| Pages published at `/privacy` and `/terms` | 🟡 | Task 22f; **text needs PO approval** (recommended: a lawyer's review for the US market) |
| Linked from sign-up, public page and chat/widget (AI disclosure, retention, BYOK costs) | 🟡 | Task 22f, E2E checks |
| Support contact address | 🟡 | `support@tryagentree.com` proposed — PO to confirm it exists |

## Gate 3 — Production readiness
| Item | Status | Evidence / next step |
|---|---|---|
| Hosting decision (U-11) | 🟡 | PO 2026-10-23: upgrade the current server instead of a separate one; shared-host risk SH-01 stays open with mitigations SH-02..SH-09 (`docs/testing/SHARED_HOST_REVIEW.md`) |
| Production data separate from staging | ❌ | Needs a production stack/database (same server) and a production domain |
| TLS, secrets outside the repo | ✅ | Caddy TLS; secrets file on the server; gitleaks clean |
| Bot challenge | 🟡 | Built (Task 22b); needs Turnstile keys (reminder set) |
| Monitoring and alerting | 🟡 | `MONITORING.md` — uptime, worker heartbeat, backup heartbeat and disk alerts proposed |
| Encrypted off-server backups + timed restore drill | 🟡 | Scripts exist (`backup.sh`, `restore-check.sh`); drill to be run by the PO (last batch) |

## Gate 4 — Pilot checks
| Item | Status | Evidence / next step |
|---|---|---|
| Tenant isolation | ✅ | Isolation matrix tests, RLS review (`SECURITY_REVIEW.md`), two-tenant E2E |
| Retention and legal hold | ✅ | `test_legal_hold.py`, `test_retention.py`, E2E |
| Failover | 🟡 | Automated with fake providers ✅; real low-budget keys on staging (PO, last batch) |
| Handoff and lead flow | ✅ | `inbox.spec.ts`, `leads.spec.ts` |
| Analyst / Executive accuracy | ✅ | Computed-number checks in tests; large tables fixed (T22-01) |
| Security review: no open Critical/High | ✅ | `SECURITY_REVIEW.md` |
| Every approved requirement delivered or deferred with PO approval | 🟡 | Roadmap table "Approved requirements outside Tasks 10–22": webhook handoff, integrations/SSRF guard, first connector, Telegram, in-app notification center are **proposed deferrals awaiting PO approval**; Google Sheets needs the PO's Google Cloud project |
| Operator runbooks | ✅ | `STAGING_RUNBOOK.md`, `ONBOARDING_RUNBOOK.md`, `MASTER_KEY.md`, `MONITORING.md` |
| Manual staging checklist | ❌ | Last batch (PO) |
| PO go/no-go | ❌ | After everything above |
