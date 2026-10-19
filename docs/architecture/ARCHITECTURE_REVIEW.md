# AGENTREE — Architecture Review

Date: 2026-10-19
Status: Recommendation for Product Owner approval. Nothing here is implemented.
Inputs: `docs/product/AGENTREE_MASTER_PROJECT_CONTEXT_V2.md` (authoritative), `docs/product/AGENTREE_ARCHITECTURE_BLUEPRINT_V1.md`, `docs/product/AGENTREE_CLAUDE_CODE_EXECUTION_PLAN_V1.md`.

Overall verdict: **the proposed architecture is sound.** A modular monolith on Next.js + FastAPI + PostgreSQL is the right shape for this product. The changes below remove moving parts (Redis, separate worker app, agent frameworks) and close a few gaps that would have caused real problems (BYOK embeddings, public abuse draining customer keys, the 30-day retention vs analytics interaction).

---

## 1. System shape

```
                  ┌───────────────────────── agentree.com (one origin, Caddy TLS) ─────────────────────────┐
 Browser ────────►│  /            Next.js  (marketing, dashboard, /{slug} public bio page, widget iframe) │
 Widget on        │  /api/*       FastAPI  (session-cookie API for dashboard)                             │
 customer site ──►│  /public/*    FastAPI  (public API: guest token in header, rate-limited)              │
 Telegram ───────►│  /hooks/*     FastAPI  (Telegram webhook, signed callbacks)                           │
                  └──────────────────────────────────────────────┬──────────────────────────────────────────┘
                                                                 │
                      ┌──────────────────────────────────────────▼───────────────────────────┐
                      │ Python package `agentree`  (one codebase, two entrypoints)           │
                      │   api process   : FastAPI                                            │
                      │   worker process: job runner + scheduler (same domain code)          │
                      │ Modules: identity · tenancy · agents · conversations · customers ·   │
                      │ knowledge · providers · actions · inbox · analytics · executive ·    │
                      │ notifications · audit · retention · entitlements                     │
                      └───────┬─────────────────────┬───────────────────────┬────────────────┘
                              │                     │                       │
                     PostgreSQL 16+           S3-compatible            Customer-owned
                     (data, RLS, jobs,        object storage           AI providers (BYOK)
                      FTS, pgvector)          (private files)          + external systems
```

Deployables: `web` (Next.js), `api`, `worker`, `postgres`, `caddy`. Object storage is an external service. **No Redis in the MVP** (see §6).

## 2. Modular monolith — keep

Correct choice. Rules that make it real rather than nominal:
- One Python package with `agentree/<module>/{api.py, service.py, models.py, schemas.py}`. Other modules call `service.py` only, never another module's models or tables.
- An import-linter rule in CI enforces the boundaries (cheap, catches drift early).
- The worker is the **same package** with a different entrypoint, not a separate app. The execution plan's `/apps/worker` would duplicate domain code; drop it.

## 3. Frontend / backend split — keep, with one guard

**Recommendation: Next.js (TypeScript) + FastAPI (Python).**

| Option | For | Against |
|---|---|---|
| Next.js + FastAPI (proposed) | Python owns what is hardest here: data analysis (DuckDB, Polars, openpyxl), document parsing, LLM tooling (LiteLLM is Python-native). | Two languages; API contract drift. |
| TypeScript only (Next.js + Node API) | One language, shared types. | Data Analyst and file ingestion are materially weaker/riskier in Node; we would end up adding Python anyway. |
| Python only (FastAPI + HTMX/Jinja) | Fewest moving parts. | Embeddable widget, polished dashboard and public pages are slower to build well; weaker UI component ecosystem. |

Guard against drift: FastAPI's OpenAPI schema generates the TypeScript client (`openapi-typescript`) in CI; a schema change that breaks the frontend fails the build. Drop `/packages/contracts` as a hand-maintained package.

Frontend specifics: Next.js App Router, Tailwind + shadcn/ui (Radix primitives → accessible by default). The public bio page is server-rendered for SEO; the dashboard is mostly client components calling `/api`. **Next.js middleware is never used for authorization** — all authorization is in FastAPI (Next.js has had middleware-bypass vulnerabilities; the backend must not depend on it).

## 4. Authentication and sessions

> **Status (2026-10-19): decided** — first-party authentication, no managed provider (ADR-001).

**Approach: in-house authentication in FastAPI with server-side sessions.**
- Email + password (Argon2id), email verification, password reset, invite links. Google sign-in can be added later.
- Opaque session token in an `HttpOnly; Secure; SameSite=Lax` cookie, stored hashed in Postgres → instant revocation, no JWT revocation problem.
- Same origin for web and API (Caddy routes `/api`) → first-party cookies, simple CSRF defense (SameSite + Origin check on state-changing requests).
- Login/reset rate limits and generic error messages.

Alternative: managed auth (Clerk, WorkOS, Auth0). Faster to get MFA/SSO, but adds per-user cost, a vendor in the critical path, and we still must build memberships/roles ourselves — the hard part is tenancy, not login. Reconsider if enterprise SSO becomes a sales requirement.

Requires: a transactional email provider (Postmark/Resend/SES — open decision). Dev uses Mailpit.

## 5. Tenancy, isolation and authorization

The single most important part of the system.

1. **Tenant context is derived, never accepted.** Dashboard requests: `session → user → membership(business_id from URL path) → role`. A business id in the URL only *selects*; membership *authorizes*. Public requests: `slug or widget key → business → public context` with no internal privileges.
2. **Every tenant row carries `business_id`**, with composite foreign keys `(business_id, id)` so a row in business A can never reference a row in business B, even by bug.
3. **Repository layer requires a `TenantContext`** object; there is no query helper that omits it.
4. **PostgreSQL Row-Level Security from day one** as defense in depth: the app connects with a role that is not the table owner and has no `BYPASSRLS`; each transaction runs `SET LOCAL app.business_id = …`; policies compare `business_id` to that setting. Workers set the same context per job. Migrations run as a separate owner role. Retrofitting RLS later is far more expensive than starting with it.
5. **Automated isolation test matrix:** every tenant-scoped endpoint is called with business B's ids while authenticated into business A and must return 404. New endpoints are auto-discovered from the router so nothing escapes the matrix.
6. Roles: Owner / Admin / Member as a code-defined permission map (`permission → roles`), not a role builder. Proposed matrix in `ARCHITECTURE_DECISIONS.md` §2.

IDs: UUIDv7 (non-guessable, index-friendly).

## 6. Background jobs — PostgreSQL queue, no Redis (change)

The proposal says Redis + a queue library. **Recommendation: a Postgres-backed queue (Procrastinate, or a ~200-line `jobs` table using `FOR UPDATE SKIP LOCKED`).**

Why it is better here, not just simpler:
- **Transactional enqueue.** An action execution row and its job are committed in the same transaction. With Redis, a crash between "save" and "enqueue" loses or duplicates the job — exactly the duplicate-side-effect risk the product forbids. This gives us the outbox pattern for free.
- One less service to run, secure, back up and monitor.
- Periodic jobs (reports, retention, health probes) supported in the same system.
- Pilot volume (thousands of jobs/day) is trivial for Postgres.

Redis is added later only for a measured need (high-rate limiting, pub/sub fan-out, caching). Public rate limits start in Postgres (or in-process with a single API instance); the limiter sits behind an interface so swapping to Redis is local.

Final library choice (Procrastinate vs custom table) is ADR-003, decided in Task 03 with a crash/retry demonstration.

## 7. Agent runtime and orchestration — own thin runtime (change)

**Do not adopt LangChain, LangGraph, CrewAI or similar.** They add abstraction where we need control (authorization, approval, idempotency, provider fallback), and they churn quickly.

Runtime:
- **Agent definition = configuration, not code:** role, system instructions, allowed tools, knowledge scopes, memory categories, model capability requirements. Five built-in definitions; per-business overrides are versioned (`agent_versions`).
- **Turn loop:** load authorized context → build prompt (system policy, business instructions, retrieved knowledge clearly delimited as untrusted data, relevant memory, recent messages) → model call with typed tools → validate tool calls with Pydantic → execute through the Action Gateway → persist → stream reply (SSE).
- **Routing without an extra model call per turn:** the customer's entry choice selects the first agent. Each public agent has a `transfer_to(role, reason)` tool. The backend validates the transfer (public agents can only transfer to public agents or to a human) and records a `handoff_event`. Ambiguous requests stay with the current agent, which asks a clarifying question. A cheap classifier is added only if evaluation shows mis-routing.
- **Shared context:** one conversation, one transcript; on transfer the new agent receives the transcript plus a short structured handoff note. Tool rights come from the *receiving agent's* definition — transfer never escalates privileges.
- **Internal agents never answer public channels**; public agents cannot read internal analytics, notes or other customers.

## 8. Customer identity and memory

- `customer_profiles` (provisional or verified), `customer_identities` (email/phone/channel handles with `verification_state`).
- Guest: short-lived signed token scoped to one business + one conversation, stored in the widget iframe's own storage.
- **Verification: email OTP first** (cheapest, no SMS provider). Required before reading protected history, merging profiles, or verified-identity actions. Typing an email only creates an *unverified* identity.
- **Structured memory:** `customer_memory_items(business_id, customer_id, category, key, value, source_message_id, confidence, verified, review_at, expires_at)`. Categories are allowlisted (e.g., contact preference, product interest, open issue, stated constraints). No free-form "remember everything".
- Extraction runs as a background job after a conversation goes idle, with the model proposing items and code validating category/shape. Memory from an unverified session stays on the provisional profile.
- Owner/Admin can review, correct and delete memory items; customer deletion requests cascade.

## 9. Knowledge and retrieval — BYOK-aware (important change)

Gap in the proposal: **embeddings need a model, and BYOK means the customer's provider.** Some providers have no embeddings API, embeddings differ per provider, and a failover to a different provider would make the vector index unusable.

Recommendation:
1. **Baseline retrieval: PostgreSQL full-text search** (`tsvector`, ranked) + trigram for fuzzy matching. Works for every tenant with zero model dependency. A small business's knowledge base (tens to hundreds of documents) retrieves well this way.
2. **Phase 2b, if evaluation shows need:** pgvector with a **platform-run small open-source embedding model on CPU** in the worker (e.g., via `fastembed`). This is platform compute, not customer token usage, so it does not violate BYOK; embeddings stay stable across provider failover. Hybrid ranking = FTS + vector.
3. Ingestion pipeline (worker): upload/fetch → type + size validation → parse in a resource-limited subprocess → normalize → chunk with metadata → index → **draft** version → publish. Published versions only are retrievable.
4. Publishing: default = owner/admin publishes manually (safe, simple). Risk-based auto-publish stays a *proposal* until approved.
5. Prompt-injection defenses: retrieved text is wrapped as quoted data with provenance; system policy states it cannot change instructions; tool authorization never depends on model text; dangerous tools need approval regardless of what the model says.

## 10. BYOK, model routing, fallback and recovery

- **Agentree-owned interface** `LLMClient.generate(request, capability_requirements) → response`. First implementation uses the **LiteLLM Python SDK** (not the LiteLLM Proxy server), pinned to an exact version with hash-locked dependencies. LiteLLM is a large, fast-moving dependency with past security advisories; isolation behind our interface keeps a switch to direct vendor SDKs local. LiteLLM never sees authorization or approval logic.
- **We implement fallback ourselves** instead of LiteLLM Router, because ours must be per-tenant, persisted, capability-aware and side-effect-aware.
- **Credentials:** envelope encryption — per-business data key (AES-256-GCM) encrypted by a master key held outside the DB (env/secret file in MVP, KMS later). Keys are write-only from the UI (show provider + last 4 chars); never in logs, prompts, frontend or error messages. Decryption only inside the provider adapter, in memory, per call.
- **Capability profiles:** `provider_model_profiles` (tool calling, structured output, context window, vision, tested quality tier). Each task declares requirements; the router picks the best eligible model on the healthy credential; if none qualifies, the task fails safe or escalates to a human.
- **Error classification:** auth invalid / quota exhausted / rate limited / transient / provider down / unsupported. Only availability-class errors trigger failover; auth-invalid raises an owner alert.
- **Circuit breaker per credential:** closed → open after N availability failures in a window → half-open probe after cooldown → closed after M successes. Probes are cheap (minimal tokens) and rate-limited. Thresholds are configuration (open decision).
- **Switch only between turns, never mid-action.** A turn that already proposed an action keeps that action's execution record; the retry path goes through the idempotency key, not a fresh model call that could propose a second action.
- **Usage monitoring:** token counts per call → `usage_events`; dashboard shows estimated spend per provider and an active-provider banner on failover.

**Abuse protection for customers' keys (gap in proposal):** public visitors spend the *customer's* tokens. Required: per-IP and per-conversation limits, message size limits, a per-business daily token/turn cap with alerting, and a bot challenge (e.g., Cloudflare Turnstile) on conversation start.

## 11. Actions, integrations and approvals

- **Action registry in code:** each action has a name, parameter schema, risk tier, required permission, idempotency rule and adapter.
- **Action Gateway flow:** validate params → authorize (tenant, agent role, actor identity/verification, connection) → risk policy → create `action_execution` row with idempotency key (state `proposed`) → `pending_approval` if required → `approved` → `executing` → `succeeded | failed | unknown`.
- **Approvals bind to a hash of the exact parameters**; any change invalidates the approval. Approvals expire.
- **`unknown` outcomes** (timeout after sending) are never blindly retried: reconciliation (read-back) if the adapter supports it, otherwise a human resolves it.
- **First actions (recommendation):** (1) internal `create_lead` / `update_lead` / `create_follow_up_task` — real, useful, no external dependency; (2) first external connector: **signed outbound webhook** to a customer-configured URL. One connector reaches Zapier, Make, n8n and custom CRMs, so it delivers the most real-world reach for the least connector code. SSRF protection: HTTPS only, DNS resolved and private/link-local ranges blocked, no redirects, timeouts, size limits. A native connector (e.g., HubSpot or Google Sheets append) can follow based on pilot demand.

## 12. Human inbox and handoff

- `conversation.owner_mode = ai | human | waiting_human`. When a human owns it, the AI does not auto-reply. Release returns it to the AI (if allowed by the business setting).
- MVP real-time: SSE for streaming AI replies to the visitor; dashboard inbox polls every few seconds. WebSockets deferred.
- No human available: the agent says so honestly, collects contact details, creates a follow-up task, and notifies the team.
- External handoff MVP: email notification and/or the outbound webhook with a context summary. WhatsApp is **not** assumed.

## 13. Data Analyst — deterministic by construction

- **Operational data:** a library of metric functions written by us (conversations, leads, conversion, handoffs, response times, topics). The model chooses metric + parameters; code computes. Fully deterministic.
- **Uploaded CSV/XLSX and Google Sheets:** imported once into an immutable Parquet snapshot in object storage (with size/row/column limits). Analysis runs in **DuckDB inside an isolated worker subprocess**: in-memory DB, only the dataset registered as a table, external access disabled and configuration locked, memory and time limits.
- The model writes SQL; **`sqlglot` parses it and only allows a single read-only `SELECT`** over registered tables. Result tables, the executed query and the dataset version are stored as an `analysis_run`.
- **No fabricated numbers:** the final answer may only cite numbers present in analysis results; a post-check compares cited numbers against the run output and flags mismatches. The UI shows the query and source for verification.
- No arbitrary Python execution in the MVP. Charts are rendered by the frontend from result tables.
- **Retention interaction (decided 2026-10-19):** raw messages are deleted at 30 days. Analysis beyond 30 days uses **privacy-conscious daily aggregated operational metrics** (approved, own retention policy). Individual conversation summaries are **not** kept beyond 30 days until a policy is approved (`ARCHITECTURE_DECISIONS.md` U-12).
- Google Sheets: Google's OAuth verification for sensitive scopes can take weeks. Use the `drive.file` scope with the Google Picker (non-sensitive) where possible, and start verification early. CSV/XLSX covers the gap.

## 14. Executive, scheduling and notifications

- Proactive = scheduled jobs + domain events, not autonomous loops. Reports: deterministic metrics → model writes the narrative → stored → delivered.
- Executive tools: read-only analytics, recommendations, and a small set of internal settings actions through the Action Gateway (medium/high risk → approval).
- **Notification abstraction:** `notify(recipient_membership, type, severity, payload)` → channel adapters (`in_app`, `telegram`, later `email`/`voice`). Each type has a sensitivity class; Telegram receives a minimal message + dashboard link for sensitive types.
- **Telegram linking:** one Agentree platform bot. A logged-in member clicks "Connect Telegram" → one-time token deep link `t.me/<bot>?start=<token>` (expires in 10 min) → webhook (verified with Telegram's secret-token header) binds `chat_id` to that membership. Unlink from dashboard; membership removal unlinks automatically.
- Voice-ready = the Executive's logic is channel-agnostic (text in/text out service). No audio infrastructure.

## 15. Public AI/Bio page and widget

- `agentree.com/{slug}` server-rendered; slug unique, with a reserved list (`api`, `app`, `login`, `admin`, `pricing`, …).
- Widget: a small script that injects an **iframe served from agentree.com**. The iframe isolates the chat from the host page's CSS/JS and keeps tokens off the customer's site. Allowed embed origins enforced via per-business `Content-Security-Policy: frame-ancestors`.
- Links: title, description, URL (validated `https://` / `mailto:` / `tel:`), ordering, per-plan limits later.
- Privacy notice + AI disclosure on page and widget.

## 16. Retention and deletion (30-day raw conversations)

- Every message row has `created_at`; attachments reference objects with the same lifecycle.
- Daily job hard-deletes messages and attachments older than 30 days (batched), records a `deletion_job` with counts. Search index rows live in the same tables, so they go with them; caches are not used for message content.
- Logs and traces never contain message content (enforced by a structured-logging redaction filter + test).
- **Backups:** encrypted database backups retained 30 days (rolling). Policy statement: deleted data disappears from backups within the backup window. Restores replay the retention job before going live.
- Legal holds: a `legal_hold` flag on conversation exempts it; only Owner can set; audited.
- Provider-side retention is governed by the customer's own provider account terms — stated in onboarding docs.

## 17. Security baseline (MVP)

Tenant isolation (§5) · server-side authorization · envelope-encrypted secrets · redacted structured logs · secure cookies + CSRF · rate limits and bot challenge on public endpoints · SSRF guard module used by every outbound HTTP call · file uploads: type sniffing, size limits, parsing in a sandboxed subprocess, private bucket, downloads via short-lived signed URLs after authorization · Telegram/webhook signature verification · audit events for auth, membership, settings, credentials, actions, approvals, exports, deletions · dependency scanning (pip-audit, npm audit), secrets scanning (gitleaks) in CI · security headers (CSP, HSTS).

## 18. Testing strategy

- **Backend:** pytest against a real PostgreSQL (available in the dev container and CI service container), with RLS active. Transaction-per-test isolation.
- **Fake LLM provider** that replays scripted responses, tool calls and failures → deterministic tests for routing, fallback, approvals and idempotency.
- **Isolation matrix** auto-generated from routes (§5).
- **Frontend:** TypeScript strict, ESLint, component tests where valuable; **Playwright** E2E for core journeys (signup → business → public chat → lead → inbox).
- Optional, manual-trigger real-provider smoke tests using test keys stored as CI secrets.

## 19. Deployment, hosting and cost

- Docker images for `web`, `api`/`worker` (one image, two commands); Docker Compose for dev and pilot; Caddy for automatic TLS.
- Environments: dev (container), staging, production — separate databases, secrets and buckets.
- CI/CD: GitHub Actions → build, test, push images → manual approval → deploy via SSH + `docker compose pull && up -d` with health check; rollback = previous image tag. Migrations are backward-compatible (expand → migrate → contract).
- **Hosting recommendation:** Hetzner Cloud VPS in a **US location** (target market is US; data location matters to US buyers) + S3-compatible object storage + off-site encrypted backups (WAL-G/pgBackRest to object storage) + quarterly restore drill. Expected pilot infra cost is low (tens of USD/EUR per month) — exact prices and US availability of each Hetzner service must be verified at Phase 7.
- Alternative worth considering at Phase 7: managed PostgreSQL (point-in-time recovery handled for us) at higher cost — trades money for less operational risk.
- Customer AI token costs are zero for Agentree by design (BYOK). Platform costs: hosting, email provider, object storage, optional bot-challenge service, domain.

## 20. What was intentionally removed or deferred

| Removed / deferred | Reason |
|---|---|
| Redis | Postgres queue gives transactional enqueue; one less service. Add on measured need. |
| Separate worker app / contracts package | Same package, generated TS client. |
| Agent frameworks (LangChain etc.) | Control over auth/approval/idempotency matters more than convenience. |
| LiteLLM Proxy server / Router | SDK behind our interface; our own fallback logic. |
| pgvector on day one | FTS baseline first; vectors with a platform embedding model when evaluation justifies. |
| WebSockets | SSE + polling suffice for MVP. |
| Microservices, Kubernetes | Not justified at pilot scale. |

## 21. Top risks

1. Cross-tenant leakage → §5 controls + automated matrix.
2. Public abuse draining customers' AI quotas → §10 limits, caps, bot challenge.
3. Duplicate external writes during failover/retries → §11 state machine + idempotency.
4. Prompt injection via knowledge/files → §9 data delimiting + backend-enforced tools.
5. Fabricated analytics → §13 deterministic engine + number post-check.
6. Small-team operations (backups, on-call) → managed services where cheap, restore drills, runbooks.
7. Scope creep → phase gates in `MVP_IMPLEMENTATION_ROADMAP.md`.
8. Google OAuth verification delay → start early; CSV fallback.
9. Fast-moving dependencies (Next.js, LiteLLM) → exact pins, lockfiles, scheduled upgrade reviews.
