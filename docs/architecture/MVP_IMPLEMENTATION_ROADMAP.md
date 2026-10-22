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

## MVP Completion Sprint — task plan (Product Owner approved 2026-10-21)

Supersedes the slice order of Phases 3–7 below for the remaining MVP work; the phase sections stay
as the requirement reference. Tasks 01–09 are done (09 = public page + widget). One PR per task (a
task may ship as a/b PRs when backend and web are independently testable); the standard Definition
of Done applies to each. Target: start General Testing around 2026-10-23 — aggressive, not a
reason to skip security or tests. **Implementation starts only after PO approval of Task 10.**

| Task | Scope | Depends on |
|---|---|---|
| 10 | Audit log (1.6) + branded HTML emails | — |
| 11 | Lead management + minimal Action Gateway (3.3) | 10 |
| 12 | Human inbox + handoff + email alert (4.4, 4.5) | 10, 11 |
| 13 | AI reliability: streaming, circuit breaker, recovery, provider monitoring (2.4, 2.5, 6.4 part) | — (parallel with 11–12) |
| 14 | Agent framework, routing, shared authorized context (3.1, 3.2) | 11, 13 |
| 15 | Customer Service + Technical Support agents | 14 |
| 16 | Customer identity + structured customer memory (3.4, 3.5) | 11, 14 |
| 17 | Knowledge file uploads + shared upload pipeline (2.3) | 10 |
| 18 | Data Analyst: metrics library + CSV/XLSX sandbox (5.4, 5.5) | 11, 12, 17 |
| 19 | Approvals queue (5.1) | 10, 11 |
| 20 | Executive Agent: reports, alerts, recommendations, controlled actions (6.1, 6.2) | 18, 19 |
| 21 | Analytics dashboard + legal-hold API + deletion audit record (4.6 rest) | 10, 18 |
| 22 | General Testing + shared-host security review + bot challenge (7.3, 7.4, 4.3 rest) | all |

Parallel lanes once Task 10 lands: {11 → 12}, {13}, {17}. Then 14 → {15, 16}; 18 → 19 → 20; 21.

### Staging deployment batches (PO decision 2026-10-21)
Not every merged PR is deployed to the shared staging server. Merge as tasks pass review, deploy in
batches: **1** Tasks 11 + 11b + 12 + 13 (sales journey) · **2** Tasks 14–16 (three public agents) ·
**3** Tasks 17–21 (intelligence) · **4** Task 22 (general testing). A security fix may ship alone.

### Approved requirements outside Tasks 10–22 (nothing removed)

Every previously approved requirement stays in scope. Items below are not covered by a Task 10–22
scope yet. **"Proposed deferral" means a proposal only: it requires explicit Product Owner approval;
until then the item remains an open MVP requirement and blocks the final pilot gate (Task 22).**

| Requirement (phase ref) | Proposed handling | Status |
|---|---|---|
| Follow-up actions: `create_follow_up_task` via the gateway (3.3) | **Approved 2026-10-21:** (A) team reminders now as Task 11b; (B) agent-sent follow-up messages later, as drafts approved by the owner (with Task 19), within limits and the business's sales playbook. **PO 2026-10-22:** each approval offers "approve once" or "always allow" | A: Task 11b · B: Task 19 (`APPROVALS.md`) |
| External handoff by signed webhook with context summary (4.5) | Proposed deferral to after Task 22 (email handoff ships in Task 12); needs the SSRF guard (5.2) | Needs PO approval |
| Integration connections + SSRF-guarded HTTP client (5.2) | Proposed deferral to after Task 22 | Needs PO approval |
| First external connector, `unknown`-outcome handling (5.3) | Proposed deferral to after Task 22 | Needs PO approval |
| Connected data source: **Google Sheets** (5.6) | **PO 2026-10-21: required, three uses** — write every lead to the business's sheet; publish reports to sheets; use sheets as a knowledge source for agents instead of uploading files to our server (affects Task 17). Needs the integration connections + OAuth (5.2). Placement to be proposed with Task 17 | Needs PO approval of placement |
| Telegram linking and delivery (6.3) | Proposed deferral to after Task 22 (email alerts ship in Tasks 11, 12, 20) | Needs PO approval |
| In-app notification center (6.3) | Proposed deferral to after Task 22 | Needs PO approval |
| Custom agent display name (2.4, PO request 2026-10-20) | **Approved 2026-10-21** (Task 14 authorization): display name per agent, cosmetic only | Task 14 |
| Alert when a business hits its daily reply budget (4.3) | Proposed: add to Task 13 (monitoring) | Needs PO approval of placement |
| Daily aggregated operational metrics job (approved with 5.4) | **Placed in Task 18a (PO 2026-10-22)**; 13-month retention | Done in 18a |
| **New (PO request 2026-10-21):** free Web Push notifications to Owners/Admins (new lead, handoff request, provider outage) via the standard Push API + VAPID, opt-in per device, email stays the fallback; iOS needs 16.4+ and Add to Home Screen | **Approved 2026-10-21:** Task 13b (lead, handoff and provider-down alerts) | Task 13b |
| **New (PO request 2026-10-21):** platform admin dashboard for the Agentree team, separate from business dashboards: manage customer businesses (e.g. suspend/reactivate), send announcements/notifications to customers, with room for many more capabilities | PO: "at the end" — after Task 22; scope and security (separate admin identity, audit) to be specified then | Later (after Task 22) |
| **New (PO request 2026-10-21):** "Resolve" in conversations not limited to team members, and available in Customer Service chats (not the Sales chat) | **Confirmed by the PO 2026-10-21:** Task 15 — the Customer Service agent and the visitor can mark a support conversation resolved, as well as the team; Sales conversations keep team-only resolve | Task 15 |
| Onboarding, privacy notice, production readiness, pilot checks (7.1, 7.2, 7.5) | Final acceptance gates of Task 22 (below) | In plan |

### Task 10 — Audit log + branded emails
- **Scope:** append-only `audit_events` (tenant-scoped, RLS; actor, action, target, time, minimal
  metadata, never message content or secrets); Owner/Admin read API + simple list page. HTML +
  plain-text email layout with the Agentree logo for verification, password reset, invitations, and
  the template later used by lead/handoff alerts.
- **Acceptance:** membership/role changes and provider-key changes write audit rows; rows cannot be
  updated or deleted by the app role; cross-tenant read denied (isolation matrix); emails render in
  HTML and plain text, links unchanged, no user content injected unescaped.
- **Out of scope:** audit export, SIEM forwarding, marketing emails.

### Task 11 — Lead management + Action Gateway — 🟡 implemented (pending PO approval), see `LEADS.md`
- **Scope:** `leads` linked to conversation and channel; fields: name, email and/or phone (at least
  one required), need, contact consent, status (new → contacted → qualified → won/lost), owner notes.
  Sales Agent asks conversationally; optional in-chat form. All agent writes go through the gateway
  (`create_lead`, `update_lead`) with per-agent permissions and idempotency keys. Leads list + detail
  page; email alert to Owner/Admins on a new lead (PO decision).
- **Acceptance:** a guest chat creates exactly one lead under retries; an agent without the
  permission is refused by the backend; guests never read leads; cross-tenant isolation; audit row
  per lead change; E2E: visitor leaves details → lead visible in the dashboard.
- **Out of scope:** CRM sync, lead scoring models. Follow-up actions: see "Approved requirements
  outside Tasks 10–22" (proposed for this task, pending PO approval).

### Task 12 — Human inbox + handoff — 🟡 implemented (pending PO approval), see `INBOX.md`
- **Scope:** inbox of conversations (dashboard + public + widget) with status open / needs human /
  human active / resolved; handoff when the visitor asks for a person or the agent cannot answer;
  member takes over, replies (guest sees it in the same chat), assigns, releases back to the AI. Email
  alert on handoff request (PO decision); "no one available" message to the visitor.
- **Acceptance:** while a human is active the AI does not reply; context preserved across take-over
  and release; only members of that business see its inbox; guest sees human replies without
  reload (polling acceptable); audit rows for take-over/assign/release; E2E covers the full path.
- **Out of scope:** SLA timers, canned replies, mobile push. Webhook handoff (approved, 4.5): see
  "Approved requirements outside Tasks 10–22" (proposed deferral, pending PO approval).

### Task 13 — AI reliability — 🟡 13a and 13b implemented (pending PO approval), see `RELIABILITY.md`
- **Scope:** streamed replies (SSE) for console, public page and widget; per-business circuit
  breaker (closed / open with cooldown / half-open probe) over primary → backup; automatic return to
  primary; provider-health status visible to Owners; structured health logs + counters for
  monitoring (error rate, open breakers).
- **Acceptance:** fake-provider tests for open → half-open → closed transitions and recovery to
  primary; streaming works through the Next.js proxy and the staging Caddy gate; partial stream
  failure ends cleanly with a retry option; no keys or message content in logs.
- **Out of scope:** external alerting service (paid), token-level cost dashboards.
- **Split (2026-10-21):** 13a = streaming, circuit breaker, recovery, health, metrics. 13b = Web
  Push (PO approved adding it to Task 13 on 2026-10-21): opt-in per device for Owners/Admins,
  alerts for new lead, handoff request and a provider key going down; email stays the fallback.

### Task 14 — Agent framework, routing, shared context — ✅ merged (#36), see `AGENTS.md`
- **Scope:** versioned per-business agent definitions (role, enabled, tools/permissions, public vs
  internal); router selecting the agent per turn; handoff events between agents; shared authorized
  context (conversation summary + lead/customer facts the receiving agent may see).
- **Acceptance:** Sales → Technical Support → Sales without the customer repeating information;
  handoff events recorded; public agents cannot transfer to internal agents (Data Analyst,
  Executive); tool rights follow the receiving agent; isolation tests.
- **Out of scope:** owner-built custom agents. Custom display name: proposed for this task, pending
  PO approval (see the tracking table).

### Task 15 — Customer Service + Technical Support agents — ✅ merged (#37), see `AGENTS.md`
- **Scope:** two public agents on the Task 14 framework, with role prompts, knowledge scoping and
  escalation rules; entry points on the public page and widget. Resolution by the Customer
  Service agent and the visitor as well as the team (PO decision 2026-10-21); Sales stays
  team-only.
- **Acceptance:** each answers only from published knowledge in scope; escalates to the inbox per
  Task 12; routing E2E across all three public agents.
- **Out of scope:** ticketing integrations.

### Task 16 — Customer identity + customer memory — ✅ merged (#39, #40), see `CUSTOMERS.md`
- **Scope:** guest → provisional profile; email OTP verification (rate-limited) links a guest to a
  verified customer profile; structured memory items (fact, source conversation, created/updated,
  review date) separate from raw messages; owner review/edit/delete UI;
  agents read memory only for the verified customer and only fields their role permits.
- **Acceptance:** entering an email alone unlocks nothing; unverified sessions cannot read verified
  memory or history; memory items never contain verbatim message text; no memory item outlives the
  retention the PO approves; deleting a customer deletes their memory; cross-tenant isolation.
- **PO decisions (2026-10-21):** U-12 — nothing derived from a conversation is kept beyond the
  30-day raw window: memory items are deleted within the same 30 days as raw messages. U-13 — no
  long-term review schedule (follows U-12). Customers are told in the chat how long their
  conversation and what the agents remember about them are kept.
- **Out of scope:** SMS/phone verification, customer self-service portal.

### Task 17 — Knowledge file uploads — ✅ merged (#42), see `KNOWLEDGE_FILES.md`
- **Scope:** upload PDF/DOCX/TXT/MD (and CSV/XLSX storage for Task 18) with size/type limits,
  content sniffing, text extraction into draft knowledge entries, processing status; files stored
  tenant-scoped, never executed or served back as HTML.
- **Acceptance:** malicious/oversized/mismatched files rejected; extracted text is untrusted
  (prompt-injection tests); drafts require manual publish (U-10 unchanged); isolation tests.
- **Out of scope:** OCR of scanned PDFs, URL crawling (needs the SSRF guard).

### Task 18 — Data Analyst — 🟡 18a implemented (pending PO approval), see `ANALYTICS.md`; 18b (CSV/XLSX analysis) next
- **PO 2026-10-22:** monthly summary + Excel export (the business uploads it to Google Drive);
  analysis of uploaded sheets (18b); the business's Google Sheets after the Sheets connection.
  The daily aggregated metrics job is part of this task (13-month retention).
- **Scope:** internal agent; deterministic metrics library over Agentree data (leads, conversations,
  handoffs, response outcomes); CSV/XLSX import → snapshot → sandboxed SELECT-only queries; every
  number in an answer comes from a computed result and is cited.
- **Acceptance:** answers match independently computed results on test datasets; a malicious
  dataset or query cannot read files, network or other tenants; members only.
- **Out of scope:** connected live data sources (5.6), forecasting.

### Task 19 — Approvals
- **Scope:** pending-approval queue for sensitive gateway actions: approve/reject, parameter-hash
  binding, expiry, email notification, audit.
- **Acceptance:** an approved action executes exactly once under retries; changed parameters void
  the approval; expired approvals cannot execute; only authorized roles approve.
- **Out of scope:** multi-step approval chains.

### Task 20 — Executive Agent
- **Scope:** internal agent as the owner's operational manager: summaries, reports (on demand +
  scheduled daily/weekly), alerts, recommendations from Task 18 data; controlled actions through the
  gateway + Task 19 approvals: pause/resume an agent, change agent schedules/availability, edit the
  public profile, reassign or update leads. Every action is permission-checked, approved where
  sensitive, and audited.
- **Acceptance:** reports match underlying data; an action without approval does not execute; the
  agent cannot act outside its permissions or on external systems; audit trail complete.
- **Split (as built):** 20a = the agent, its context and approval-backed actions (pause/resume an
  agent, public page, lead status, lead assignment; `EXECUTIVE.md`); 20b = agent hours; 20c = scheduled reports and
  alerts. **PO 2026-10-22:** agents get working hours. That is 20b (always / during business hours /
  outside business hours, plus pauses such as holidays with a fixed message), so scheduled reports
  and alerts become 20c. The Executive is an initial version, to be developed much further.
- **Out of scope (post-launch growth, PO 2026-10-21):** full "manage everything" coverage,
  external-system actions. Telegram delivery (6.3, approved): see the tracking table (proposed
  deferral, pending PO approval).

### Task 21 — Analytics + legal hold
- **Scope:** owner dashboard of measured metrics only (conversations, leads, handoffs, agent
  outcomes, provider health); Owner-only audited legal-hold API; persisted deletion audit record for
  the retention job.
- **Acceptance:** every metric traceable to stored data; empty states when no data; legal hold
  exempts exactly the held conversations; deletion runs leave an audit record.
- **Out of scope:** exports, custom report builder.

### Task 22 — General Testing + hardening
- **Scope:** scripted end-to-end scenarios (new business setup → keys → knowledge; visitor across
  agents; lead → human; provider outage → backup → recovery; analyst numbers checked; executive
  report checked; two-tenant isolation; retention); desktop + mobile; shared-host security review
  with mitigations; bot challenge (U-16); failover matrix with real low-budget test keys.
- **Acceptance:** results documented with evidence; open defects triaged.
- **Final acceptance gates (all required before the first real customer):**
  1. **Onboarding:** a new business completes signup → business setup → AI provider key → knowledge
     → agents → public page/widget using the in-product flow, plus the assisted-setup runbook and the
     customer key-setup guide (7.5).
  2. **Privacy notice and terms** published and linked from signup, public page and widget (AI
     disclosure, retention, BYOK cost responsibility), PO-approved text.
  3. **Production readiness (7.1, 7.2):** hosting decision U-11 made; production deployment
     separate from staging data; TLS, secrets outside the repo, monitoring and alerting on; encrypted
     off-server backups with a timed restore drill on production; shared-host risks closed or
     mitigated per the security review.
  4. **First-customer pilot checks:** pilot checklist with evidence (isolation, retention, failover,
     handoff, lead flow, analyst/executive accuracy), every approved requirement either delivered or
     deferred with explicit PO approval (tracking table), operator runbooks, and the PO go/no-go.

---

## Open requirements (NOT done — tracked explicitly)

Partially delivered slices stay open until every item below is implemented and tested.

| Requirement | Slice | Status |
|---|---|---|
| Streaming agent replies (SSE) | 2.4 | 🟡 Task 13a (pending PO approval): console, public page and widget stream over SSE; retry after an interrupted reply. |
| Circuit breaker with cooldown / half-open probes | 2.5 | 🟡 Task 13a (pending PO approval): per-key breaker shared by all API processes, one probe at a time. |
| Automatic recovery to primary after an outage (health probes) | 2.5 | 🟡 Task 13a (pending PO approval): the first request after the cooldown probes the primary; success returns traffic to it. |
| 30-day raw conversation retention (deletion job, legal hold) | 4.6 | 🟡 Deletion job implemented (Task 08, pending Product Owner approval): worker loop (`python -m agentree.worker`, every `AGENTREE_RETENTION_INTERVAL_SECONDS`, default 3600) hard-deletes conversations idle longer than `AGENTREE_RETENTION_DAYS` (default 30, max 30) via `agentree_purge_expired_conversations`, batched, one worker at a time. `conversations.legal_hold` exempts a conversation. ❌ Still open: Owner-only audited legal-hold API, persisted deletion audit record (`deletion_job`; counts are only logged today), worker deployment in the dev stack (staging: `worker` service in `infra/staging`), backup-window policy. |
| Knowledge file uploads (PDF/DOCX/TXT/MD) | 2.3 | ❌ Not started. Manual entries only. |
| Custom agent display name (e.g. "Sara from Track") set by the owner in settings | 2.4 | ❌ Not started (PO request 2026-10-20). Chat shows "Sales Agent · <business>" until then. |
| Remaining four agent roles, routing and handoff | 3.x | ❌ Not started. |
| Public AI/Bio page | 4.1 | 🟡 Backend API (Task 09a, merged) + web UI (Task 09b, pending Product Owner approval): owner settings page "Public page & widget" (enable, display name, bio, ordered links, allowed websites, daily reply limit; Admin+ edits), server-rendered public page at `/{slug}` (links + "Chat with our Sales Agent" panel, guest token per browser, conversation restored on reload, AI disclosure). ❌ Still open: agent entry points beyond Sales, branding (logo/colours/avatar image), search indexing (pages are `noindex` on staging). |
| Website widget | 4.2 | 🟡 Backend API (Task 09a, merged) + web (Task 09b, pending Product Owner approval): `/widget.js` loader (one script tag, floating button, RTL-aware, Escape/close), iframe page `/w/{slug}` with `Content-Security-Policy: frame-ancestors` from the allowlist (`src/proxy.ts`; `none` on any failure), every other route keeps `X-Frame-Options: DENY`. ❌ Still open: widget branding/colours, launcher customization; on staging the basic-auth gate also covers the widget, so it can only be tried on tryagentree.com pages. |
| Public abuse controls | 4.3 | 🟡 Rate limits done (Task 09a): sessions 20/h per IP and 500/day per business; chat 20/10 min and 100/day per session, 60/h per IP, per-business daily reply budget (owner-set, default 200, max 5000). ❌ Still open: bot challenge (U-16, Turnstile candidate), per-business alerting when the budget is hit. |

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

### 1.1 Tenancy primitives + RLS — ✅ implemented (Task 02, see `TENANCY.md`)
- **Objective:** `TenantContext`, tenant-aware repository base, RLS policies, app/migration DB roles.
- **Dependencies:** 0.1.
- **Expected changes:** `agentree/tenancy/*`, migration creating roles/policies, test fixtures for two businesses.
- **Acceptance:** querying a tenant table without context returns zero rows; with context A never returns B's rows, even with a deliberately unscoped query.
- **Tests:** RLS tests that bypass the repository layer on purpose.
- **Security checks:** app role has no `BYPASSRLS` and does not own tables.

### 1.2 Users, sessions, login — ✅ implemented (Task 03)
- **Decision:** first-party auth (ADR-001, accepted). No managed provider.
- **Objective:** register, login, logout, session management.
- **Acceptance:** Argon2id hashes; session revocation immediate; rate-limited login; generic errors.
- **Tests:** auth flows, session expiry, CSRF/Origin check, brute-force limit.
- **Security checks:** cookie flags; no password/token in logs.

### 1.3 Email verification, password reset — ✅ implemented (Task 03)
- **Dependencies:** 1.2, U-05 (Mailpit in dev).
- **Acceptance:** single-use, expiring tokens stored hashed.

### 1.4 Businesses and memberships — ✅ implemented (Task 03)
- **Objective:** create business, invite by email, accept invite, Owner/Admin/Member, role changes, remove member.
- **Acceptance:** permission matrix enforced server-side; last Owner cannot be removed; nobody grants above own role.
- **Tests:** full matrix role × permission; isolation matrix.

### 1.5 Business switcher + dashboard shell
- **Objective:** user sees only their businesses; URL-scoped business routes.
- **Acceptance (phase gate):** one user is Owner of A and Member of B with correct, separate rights; all cross-tenant read/write/IDOR attempts return 404. Playwright journey: signup → create business → invite → switch.

### 1.6 Audit events — 🟡 Task 10a implemented (pending PO approval), see `AUDIT_LOG.md`
- **Objective:** append-only `audit_events` for auth, membership, settings.
- **Acceptance:** Owners/Admins can view their business audit log; no cross-tenant visibility.

## Phase 2 — First working agent (BYOK)

### 2.1 Provider credentials (BYOK vault) — ✅ implemented (Task 05)
- **Objective:** add/replace/remove primary and backup keys, encrypted; validation call on save.
- **Acceptance:** UI never shows key after save (last 4 only); DB holds ciphertext only.
- **Tests:** encryption round-trip, key rotation, redaction (key never appears in logs/errors/API responses).
- **Security checks:** master key loaded from secret file/env, not the repo.

### 2.2 LLM client + fake provider — ✅ implemented (Task 05; streaming lands with 2.4)
- **Objective:** `LLMClient` interface, LiteLLM implementation, scripted fake for tests, usage events.
- **Acceptance:** a real call with a test key works (manual run, reported); all automated tests use the fake.

### 2.3 Knowledge base v1 — ✅ partial (Task 06: manual entries, draft→publish, Postgres full-text retrieval; file upload pending)
- **Objective:** manual entries + file upload (PDF/DOCX/TXT/MD), parse in sandboxed subprocess, chunk, Postgres FTS, draft → publish.
- **Acceptance:** only published versions are retrievable; business A never retrieves B's chunks.
- **Security checks:** size/type limits; private object storage; parsing timeouts.

### 2.4 Sales Agent text conversation (dashboard test console) — ✅ implemented (Task 06; streaming in Task 13a)
- **Objective:** agent definition, turn loop, retrieval, streaming reply (SSE), messages persisted with retention fields.
- **Acceptance (phase gate):** the Sales Agent answers using the customer's key and the correct business's knowledge; injected instructions inside a knowledge document do not change behavior (test case).

### 2.5 Fallback, circuit breaker, recovery **[changed]** — 🟡 Task 06 failover + Task 13a circuit breaker and recovery (pending PO approval)
- **Objective:** capability profiles, error classification, primary→backup failover between turns, half-open probes, automatic return, dashboard banner + in-app notice.
- **Acceptance:** with the fake provider: primary outage → backup serves; unsupported task on backup fails safe; primary recovers → returns after cooldown; no flapping under intermittent failure.

## Phase 3 — Integrated workforce

### 3.1 Five agent definitions + per-business configuration (versioned) — 🟡 Task 14
### 3.2 Routing and handoff — 🟡 Task 14
- **Acceptance:** Sales → Technical Support → Sales without the customer repeating info; handoff events recorded; public agents cannot transfer to internal agents; tool rights follow the receiving agent.
### 3.3 Minimal Action Gateway + `create_lead`, `update_lead`, `create_follow_up_task` **[changed]**
- **Acceptance:** retried tool call with same idempotency key creates exactly one lead; agent lacking permission is refused by the backend even if the model asks.
### 3.4 Customer identity (guest, provisional profile, email OTP verification)
- **Acceptance:** entering an email does not unlock history; OTP verification links profiles; OTP attempts rate-limited.
### 3.5 Structured customer memory (extraction job, review/edit/delete UI)
- **Acceptance (phase gate):** agents use memory of the right customer only; unverified sessions cannot read verified memory; no cross-tenant leaks.
- Requires decisions U-10, U-12, U-13. Daily aggregated metrics job (approved) lands with 5.4.

## Phase 4 — Customer experience

### 4.1 Public AI/Bio page (slug, branding, entry points, links) — 🟡 API (Task 09a) and web UI (Task 09b) implemented; branding and more entry points open
### 4.2 Website widget (iframe, origin allowlist, guest token) — 🟡 API (Task 09a) and embed script + iframe page (Task 09b) implemented; branding open
### 4.3 Public abuse controls (rate limits, per-business daily cap, bot challenge) — 🟡 limits implemented (Task 09a), bot challenge open (U-16)
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
- As built (Task 18b): stored file → SQLite in a limited child process → single SELECT + engine authorizer → cited-number check (TD-15 note).
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
