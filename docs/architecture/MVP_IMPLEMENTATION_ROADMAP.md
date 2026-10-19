# AGENTREE — MVP Implementation Roadmap

Date: 2026-10-19
Status: Proposed. Follows the approved phase direction (Master Context V2 §9) with three justified sequencing changes, marked **[changed]**.

## Standard Definition of Done (applies to every slice)

1. Code on a feature branch, one slice per PR.
2. Lint, type-check, unit and integration tests **actually run** and passing in CI; results quoted in the completion report.
3. Every new tenant-scoped endpoint covered by the isolation matrix.
4. Migrations apply cleanly on an empty DB and on the previous schema; downgrade or repair path documented.
5. No secrets or message content in logs (redaction test passes).
6. Docs updated (API notes, decisions, runbook if operational).
7. Self-review for security; completion report lists limitations honestly.
8. Product Owner approval before merge.

Each slice below lists only what is specific to it.

## Sequencing changes vs the original plan

- **[changed] Minimal Action Gateway moves into Phase 3** (with the workforce), so the Sales Agent's `create_lead` goes through the gateway from the start. Approvals UI and external connector stay in Phase 5. Reason: no agent tool should ever exist outside the gateway.
- **[changed] Primary/backup fallback moves into Phase 2** (right after the first agent). Reason: it defines the runtime contract; retrofitting is costly.
- **[changed] Retention job runs in Phase 4**, before any real public visitor. Reason: AGT-010 must hold from the first real conversation.

---

## Phase 0 — Engineering foundation

### 0.1 Repository skeleton, CI, test harness → `TASK_01_SPEC.md`
- **Objective:** a runnable, tested, CI-checked empty platform.
- **Dependencies:** architecture approval (repository now exists).
- **Acceptance:** `/healthz` and `/readyz` (DB check) pass; pytest runs against real Postgres; CI green.

### 0.2 Web skeleton
- **Objective:** Next.js app with design tokens, layout shell, generated API client, Playwright smoke test.
- **Dependencies:** 0.1.
- **Expected changes:** `apps/web/*`, CI job for web.
- **Acceptance:** web page calls `/api/healthz` via generated client; Playwright smoke passes in CI.
- **Security checks:** security headers baseline (CSP, HSTS in prod config).

## Phase 1 — SaaS foundation

### 1.1 Tenancy primitives + RLS
- **Objective:** `TenantContext`, tenant-aware repository base, RLS policies, app/migration DB roles.
- **Dependencies:** 0.1.
- **Expected changes:** `agentree/tenancy/*`, migration creating roles/policies, test fixtures for two businesses.
- **Acceptance:** querying a tenant table without context returns zero rows; with context A never returns B's rows, even with a deliberately unscoped query.
- **Tests:** RLS tests that bypass the repository layer on purpose.
- **Security checks:** app role has no `BYPASSRLS` and does not own tables.

### 1.2 Users, sessions, login
- **Precondition:** auth ADR (U-17) approved — managed solution vs in-house. Steps below assume in-house and change if a managed solution is chosen; membership authorization stays server-side either way.
- **Objective:** register, login, logout, session management.
- **Acceptance:** Argon2id hashes; session revocation immediate; rate-limited login; generic errors.
- **Tests:** auth flows, session expiry, CSRF/Origin check, brute-force limit.
- **Security checks:** cookie flags; no password/token in logs.

### 1.3 Email verification, password reset
- **Dependencies:** 1.2, U-05 (Mailpit in dev).
- **Acceptance:** single-use, expiring tokens stored hashed.

### 1.4 Businesses and memberships
- **Objective:** create business, invite by email, accept invite, Owner/Admin/Member, role changes, remove member.
- **Acceptance:** permission matrix enforced server-side; last Owner cannot be removed; nobody grants above own role.
- **Tests:** full matrix role × permission; isolation matrix.

### 1.5 Business switcher + dashboard shell
- **Objective:** user sees only their businesses; URL-scoped business routes.
- **Acceptance (phase gate):** one user is Owner of A and Member of B with correct, separate rights; all cross-tenant read/write/IDOR attempts return 404. Playwright journey: signup → create business → invite → switch.

### 1.6 Audit events
- **Objective:** append-only `audit_events` for auth, membership, settings.
- **Acceptance:** Owners/Admins can view their business audit log; no cross-tenant visibility.

## Phase 2 — First working agent (BYOK)

### 2.1 Provider credentials (BYOK vault)
- **Objective:** add/replace/remove primary and backup keys, encrypted; validation call on save.
- **Acceptance:** UI never shows key after save (last 4 only); DB holds ciphertext only.
- **Tests:** encryption round-trip, key rotation, redaction (key never appears in logs/errors/API responses).
- **Security checks:** master key loaded from secret file/env, not the repo.

### 2.2 LLM client + fake provider
- **Objective:** `LLMClient` interface, LiteLLM implementation, scripted fake for tests, usage events.
- **Acceptance:** a real call with a test key works (manual run, reported); all automated tests use the fake.

### 2.3 Knowledge base v1
- **Objective:** manual entries + file upload (PDF/DOCX/TXT/MD), parse in sandboxed subprocess, chunk, Postgres FTS, draft → publish.
- **Acceptance:** only published versions are retrievable; business A never retrieves B's chunks.
- **Security checks:** size/type limits; private object storage; parsing timeouts.

### 2.4 Sales Agent text conversation (dashboard test console)
- **Objective:** agent definition, turn loop, retrieval, streaming reply (SSE), messages persisted with retention fields.
- **Acceptance (phase gate):** the Sales Agent answers using the customer's key and the correct business's knowledge; injected instructions inside a knowledge document do not change behavior (test case).

### 2.5 Fallback, circuit breaker, recovery **[changed]**
- **Objective:** capability profiles, error classification, primary→backup failover between turns, half-open probes, automatic return, dashboard banner + in-app notice.
- **Acceptance:** with the fake provider: primary outage → backup serves; unsupported task on backup fails safe; primary recovers → returns after cooldown; no flapping under intermittent failure.

## Phase 3 — Integrated workforce

### 3.1 Five agent definitions + per-business configuration (versioned)
### 3.2 Routing and handoff
- **Acceptance:** Sales → Technical Support → Sales without the customer repeating info; handoff events recorded; public agents cannot transfer to internal agents; tool rights follow the receiving agent.
### 3.3 Minimal Action Gateway + `create_lead`, `update_lead`, `create_follow_up_task` **[changed]**
- **Acceptance:** retried tool call with same idempotency key creates exactly one lead; agent lacking permission is refused by the backend even if the model asks.
### 3.4 Customer identity (guest, provisional profile, email OTP verification)
- **Acceptance:** entering an email does not unlock history; OTP verification links profiles; OTP attempts rate-limited.
### 3.5 Structured customer memory (extraction job, review/edit/delete UI)
- **Acceptance (phase gate):** agents use memory of the right customer only; unverified sessions cannot read verified memory; no cross-tenant leaks.
- Requires decisions U-10, U-12, U-13. Daily aggregated metrics job (approved) lands with 5.4.

## Phase 4 — Customer experience

### 4.1 Public AI/Bio page (slug, branding, entry points, links)
### 4.2 Website widget (iframe, origin allowlist, guest token)
### 4.3 Public abuse controls (rate limits, per-business daily cap, bot challenge)
### 4.4 Human inbox (take over, reply, assign, status, release to AI)
### 4.5 External handoff (email + webhook with context summary); no-human-available path
### 4.6 Retention job (30-day hard delete, deletion audit, legal hold) **[changed]**
- **Acceptance (phase gate):** a real browser visitor chats on the public page and widget → lead created → escalated to inbox → human replies; synthetic 31-day-old data is deleted; no credentials in any public response (scanned in E2E).

## Phase 5 — Integrations and intelligence

### 5.1 Approvals (pending queue, approve/reject, parameter-hash binding, expiry, notifications)
### 5.2 Integration connections + SSRF-guarded HTTP client
### 5.3 First external connector (proposed: signed outbound webhook), `unknown`-outcome handling
### 5.4 Operational metrics library + Data Analyst on Agentree data
### 5.5 CSV/XLSX import → Parquet snapshot → DuckDB sandbox → SELECT-only validation → cited-number check
### 5.6 Connected data source (candidate: Google Sheets)
- **Acceptance (phase gate):** an authorized action executes once under retries; an unauthorized one is denied; analyst answers match independently computed results on test datasets; a malicious dataset/SQL cannot read files, network or other tenants.

## Phase 6 — Executive and operations

### 6.1 Executive agent (internal chat, read analytics, recommendations, settings actions via gateway)
### 6.2 Scheduled reports (daily/weekly) + event alerts
### 6.3 Notifications: in-app center + Telegram linking and delivery
### 6.4 Basic monitoring (job failures, provider health, deletion backlog, error rates)
- **Acceptance (phase gate):** reports match underlying data; Telegram only reaches linked, current members; sensitive types send minimal content.

## Phase 7 — Pilot readiness

### 7.1 Staging + production deployment (hosting decision U-11), TLS, secrets
### 7.2 Backups + restore drill (documented, timed)
### 7.3 Security review: isolation, auth, uploads, SSRF, injection; dependency and secret scans
### 7.4 Full E2E suite + provider failover test matrix with real test keys
### 7.5 Onboarding runbook (assisted setup, key setup guide), privacy notice, operator runbooks
- **Acceptance:** pilot checklist evidence complete; Product Owner go/no-go.

## Indicative size

~35 slices. Each is intended to be reviewable in one sitting. Estimates are deliberately not given in calendar time until Phase 0–1 velocity is measured.
