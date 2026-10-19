# AGENTREE — Architecture Decisions

Date: 2026-10-19
Legend: **AP** = approved product constraint (Product Owner). **TD** = recommended technical decision (Claude, awaiting approval). **U** = unresolved. **R** = risk. **A** = assumption.
Details and reasoning for each TD are in `ARCHITECTURE_REVIEW.md` (section in brackets).

## 1. Approved product constraints (do not change without Product Owner approval)

### 1a. Approved decision register (from `docs/product/AGENTREE_MASTER_PROJECT_CONTEXT_V2.md` §2)

| ID | Decision | Architectural consequence |
|---|---|---|
| AGT-001 | Controlled Multi-Segment Pilot (sectors deferred) | Industry-agnostic core; no sector-specific logic. |
| AGT-002 | Productized Managed SaaS | Assisted setup tooling; entitlements boundary; no pricing logic yet. |
| AGT-003 | Controlled Real Actions | Action Gateway with audit (TD-13). |
| AGT-004 | Hybrid Integration Model | Common connector interface; custom integrations plug in behind it. |
| AGT-005 | Risk-Based Approval | Backend-enforced risk tiers; approval bound to exact parameters. |
| AGT-006 | Multi-User with Basic Roles | Owner/Admin/Member labels provisional; matrix in §2 is a proposal. |
| AGT-007 | Multi-Business Membership | Membership-derived tenant context; business switcher. |
| AGT-008 | Hybrid Customer Identity | Guest → provisional profile → verification gate (TD-08). |
| AGT-009 | Structured Customer Memory | Separate memory store per customer within business. |
| AGT-010 | 30-Day Raw Conversation Retention | Daily deletion job, backup window, legal hold (TD-18). |
| AGT-011 | Active Customer Memory | `review_at`/`expires_at`, review/correct/delete UI. |
| AGT-012 | Hybrid Intelligent Routing | Entry choice + validated `transfer_to` (TD-07). |
| AGT-013 | Hybrid Human Handoff | Inbox with AI suppression while human owns conversation + external route. |
| AGT-014 | Customer-Owned BYOK + Backup | Encrypted per-business credentials; no platform keys (TD-10/11). Distinguish account-balance failure from single-key failure. |
| AGT-015 | Capability-Aware Fallback | Capability profiles; fail safe when backup is unsuitable. |
| AGT-016 | Automatic Recovery | Circuit breaker, cooldown, switch between turns only. |
| AGT-017 | Hybrid Knowledge Management | Draft → publish, versioning, provenance (TD-09). |
| AGT-018 | Data Analyst: Agentree Data + Files + Connected Sources | Deterministic analysis engine (TD-15). |
| AGT-019 | Proactive Executive | Scheduled jobs + events; Observe → Analyze → Recommend → Approve/Execute → Report. |
| AGT-020 | Dashboard + In-App Notifications + Telegram | Notification abstraction, verified Telegram linking (TD-16). |
| AGT-021 | Text First, Voice Ready | Channel-agnostic Executive service; no audio infrastructure. |

Not approved (V2 explicit): risk-based knowledge publishing — remains a recommendation (U-10).

### 1b. Core product principles (V2 §1, §3, §7 and master prompt)

| ID | Principle |
|---|---|
| PC-01 | One integrated AI workforce with five fixed roles: Sales, Customer Service, Technical Support (public); Data Analyst, Executive (internal). |
| PC-02 | Public AI/Bio page (`agentree.com/{name}`) with agent entry points and business links; one text-first website widget. Custom domains excluded from MVP. |
| PC-03 | Model routing picks the best supported model by cost, capability, latency, quality, availability, customer settings; no provider lock-in; routing never overrides permissions or approval. |
| PC-04 | MVP Scope V1 (approved 19 Oct 2026, 8 capability areas) and its deferred list. |
| PC-05 | No wedding photography / wedding-event sectors in recommendations. |
| PC-06 | Founder publicly based in Egypt; never imply US origin. |

## 2. Recommended technical decisions

| ID | Decision | Ref |
|---|---|---|
| TD-01 | Modular monolith: one Python package (`api` + `worker` entrypoints) + one Next.js app; module boundaries enforced by import-linter. | §2 |
| TD-02 | Next.js (App Router, TypeScript strict, Tailwind, shadcn/ui) + FastAPI (Python 3.12+, Pydantic v2). TS client generated from OpenAPI. | §3 |
| TD-03 | PostgreSQL 16+, SQLAlchemy 2 (async, asyncpg), Alembic. UUIDv7 ids. | §5 |
| TD-04 | In-house auth: Argon2id, server-side sessions in opaque HttpOnly cookie, same-origin API behind Caddy. | §4 |
| TD-05 | Tenant context derived from membership; `business_id` on every tenant row; composite FKs; repository layer requires `TenantContext`; **RLS enabled from day one**; auto-generated isolation test matrix. | §5 |
| TD-06 | **Deviation from V2 candidate stack (Redis):** Postgres-backed job queue (Procrastinate or custom `SKIP LOCKED` table — final pick in Task 03). No Redis in MVP. | §6 |
| TD-07 | Own thin agent runtime; no agent frameworks. Agents = versioned configuration. Routing via validated `transfer_to` tool. | §7 |
| TD-08 | Email OTP as first customer verification method. | §8 |
| TD-09 | Knowledge retrieval: Postgres full-text first; pgvector + platform-run CPU embedding model only if evaluation justifies. Manual publish by default. | §9 |
| TD-10 | Agentree `LLMClient` interface; LiteLLM SDK (exact-pinned, hash-locked) as first implementation; own fallback, circuit breaker and capability profiles. | §10 |
| TD-11 | Envelope encryption for provider keys (per-business AES-256-GCM data key; master key outside DB). Write-only keys in UI. | §10 |
| TD-12 | Public abuse controls protecting customer keys: rate limits, daily per-business caps, bot challenge. | §10 |
| TD-13 | Action registry + Gateway state machine; approval bound to parameter hash; `unknown` outcomes never blindly retried. | §11 |
| TD-14 | First actions: internal lead/task actions; first external connector proposal: signed outbound webhook. | §11 |
| TD-15 | Data Analyst: metric library for operational data; DuckDB in sandboxed subprocess over immutable Parquet snapshots; `sqlglot` SELECT-only validation; cited-number post-check. | §13 |
| TD-16 | Notification abstraction with sensitivity classes; Telegram linking via one-time deep-link token + verified webhook. | §14 |
| TD-17 | Widget = script injecting an iframe from agentree.com; `frame-ancestors` allowlist per business. | §15 |
| TD-18 | Retention: daily batched hard delete; 30-day rolling encrypted backups; legal-hold flag; no message content in logs. | §16 |
| TD-19 | Docker Compose + Caddy; GitHub Actions CI; manual-approval deploy; image-tag rollback; expand/contract migrations. | §19 |
| TD-20 | Project standards start as `CLAUDE.md` + `docs/`; dedicated Coder/Designer/DevOps skills only once conventions stabilize (after Phase 1). | — |
| TD-21 | Monorepo layout in `MrElkomy/agentree`: `apps/api`, `apps/web`, `infra`, `docs`. | Audit §5 |

### Proposed role-permission matrix (TD, needs review)

| Permission | Owner | Admin | Member |
|---|:-:|:-:|:-:|
| View conversations, leads, analytics | ✓ | ✓ | ✓ |
| Reply in inbox / take over conversation | ✓ | ✓ | ✓ |
| Edit knowledge (draft) | ✓ | ✓ | ✓ |
| Publish knowledge, edit agent configuration, public page, links | ✓ | ✓ | — |
| Approve medium-risk actions | ✓ | ✓ | — |
| Approve high-risk actions | ✓ | — | — |
| Manage provider keys and integrations | ✓ | ✓ | — |
| Invite/remove members | ✓ | ✓ (not Owners) | — |
| Billing, delete business, transfer ownership, legal hold | ✓ | — | — |

Rules: at least one Owner always exists; nobody can grant a role higher than their own.

## 3. Unresolved decisions

| ID | Decision | Default until decided | Needed by |
|---|---|---|---|
| U-01 | Repository for Agentree | **Resolved:** private repo `MrElkomy/agentree` created by Product Owner | — |
| U-02 | Target sectors / first pilot profiles | Industry-agnostic | Phase 7 |
| U-03 | Prices and package boundaries | Entitlements module with placeholder limits | Phase 7 |
| U-04 | Executive Agent final name | "Executive" internally | Before marketing |
| U-05 | Transactional email provider | Mailpit in dev | Phase 1 (slice 1.3) |
| U-06 | First external connector | Signed outbound webhook (TD-14) | Phase 5 |
| U-07 | Connected data source | Google Sheets candidate | Phase 5 |
| U-08 | Provider failure thresholds / cooldowns | Configurable defaults (e.g., open after 3 failures/60s, 2-min cooldown) | Phase 2 |
| U-09 | Initial supported providers list | OpenAI-compatible + Anthropic + Google Gemini, verified at Phase 2 | Phase 2 |
| U-10 | Risk-based auto-publish of knowledge | Manual publish | Phase 3 |
| U-11 | Hosting provider/region, managed vs self-run Postgres | Hetzner US + self-run with WAL-G | Phase 7 |
| U-12 | Conversation summaries/aggregates kept after 30 days | Keep non-verbatim summary + daily aggregates (needs owner confirmation that this is consistent with AGT-010) | Phase 3 |
| U-13 | Memory review schedule | `review_at` = 180 days default | Phase 3 |
| U-14 | Telegram two-way Executive chat in MVP | Outbound notifications + deep links only | Phase 6 |
| U-15 | Billing/payment implementation | Out of MVP code until prices exist | Post-MVP |
| U-16 | Bot challenge provider | Cloudflare Turnstile candidate | Phase 4 |

## 4. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R-01 | Cross-tenant leakage | TD-05 + isolation matrix in CI |
| R-02 | Prompt injection via knowledge, files, web content | Data delimiting, backend-enforced tools, approvals |
| R-03 | Provider key leakage | TD-11, log redaction tests, write-only UI |
| R-04 | Duplicate external writes | TD-13, transactional enqueue (TD-06) |
| R-05 | Abuse drains customer AI quota | TD-12 |
| R-06 | Incomplete deletion (backups, files, logs) | TD-18, deletion job audit, restore procedure |
| R-07 | Fabricated analytics | TD-15 |
| R-08 | Guest identity spoofing | TD-08, verification gates |
| R-09 | Job failures unnoticed | Retry limits, dead-letter state, job-failure metric + alert |
| R-10 | Scope creep | Roadmap phase gates |
| R-11 | Google OAuth verification delays | Early application; CSV/XLSX fallback |
| R-12 | Dependency churn / supply chain | Exact pins, lockfiles, pip-audit/npm audit, scheduled upgrades |
| R-13 | Single-person operations burden | Simple topology, runbooks, restore drills, managed options |
| R-14 | Backup provider model lacks needed capability → degraded service | Capability profiles; honest fail-safe + alert |

## 5. Assumptions

| ID | Assumption |
|---|---|
| A-01 | English is the primary customer-facing language for the US market; UI built with i18n-ready strings. |
| A-02 | Pilot scale: < 20 businesses, < 10k conversations/month total. Architecture choices are sized for this with clear upgrade paths. |
| A-03 | Each business's knowledge base is small (≤ a few hundred documents). |
| A-04 | Agentree may run one platform-owned Telegram bot and a platform embedding model; these are platform costs, not customer AI token usage, so they do not conflict with AGT-014. |
| A-05 | Product Owner will create/approve external accounts (GitHub repo, hosting, email, domain) when needed; no accounts are assumed to exist. |
| A-06 | Master Context V2 is authoritative; V1 documents are supporting history. |
