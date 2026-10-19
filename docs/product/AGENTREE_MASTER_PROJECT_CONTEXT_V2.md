# AGENTREE — MASTER PROJECT CONTEXT V2

**Updated:** 19 October 2026  
**Status:** Consolidated product context and approved decision register. This is not an approved final technical architecture, implemented code, or evidence of testing.  
**Intended readers:** Product Owner, ChatGPT reviewer, Claude Code Web (primary developer), and occasional independent reviewers.

## 0. Read this first — source of truth and working rules

This V2 document consolidates the original Agentree Master Project Context with the decisions approved in the October 2026 discovery conversation. Where the earlier V1 text disagrees with this document, **V2 approved decisions prevail**. Do not reinterpret proposals as approvals. Do not write production code until the Product Owner approves the technical architecture and first implementation task.

- Communicate with the Product Owner in **Egyptian Arabic** and use English for technical terms and code/docs where appropriate.
- Be direct and concise. Avoid repetitive discovery questions; ask only one critical question at a time, and prefer well-reasoned engineering proposals for routine choices.
- Product Owner is the ultimate decision-maker. Claude Code is the primary developer; ChatGPT reviews product/architecture/code/test plans. Cursor is optional for targeted inspection.
- **Development is through Claude Code on the WEB**, backed by a **private GitHub repository named `agentree`**. Do not assume local CLI use, a populated repository, or connected credentials. The Product Owner reported creating the private repo with an initial README; the codebase has **not been independently inspected**.
- Inspect the repository and existing files before proposing changes. Clearly report what is documented, actually built, tested, missing, or unverified.
- Use Git branches, small verifiable vertical slices, acceptance criteria, automated tests, review and approval before merge. Do not claim work or validation that has not occurred.
- **Target sectors are NOT chosen.** The Product Owner deferred sector selection. Do not present earlier speculative sector rankings as approved. Do not recommend wedding photography or wedding-event organization as target sectors, per the Product Owner's expressed business/religious preference.

## 1. Product identity and positioning

**Agentree** is a B2B SaaS delivering an **integrated 24/7 AI Workforce**, primarily for the US market. North Star: *Give every business an AI workforce that can understand, communicate, analyze, act, and improve — 24/7.* It is not merely a chatbot builder, five isolated assistants, a superficial dashboard, or a generic automation marketplace.

The five **fixed core roles** apply to all industries, while instructions, business knowledge, tools, integrations, configurations and allowed actions vary by tenant:

1. **Sales Agent (public):** inquiries, products, lead qualification, capture, approved sales actions, and handoff.
2. **Customer Service Agent (public):** questions, complaints, requests, authorized updates and human escalation.
3. **Technical Support Agent (public):** troubleshooting from approved knowledge, supported tools and human escalation.
4. **Data Analyst Agent (internal):** genuine analysis of operational data and available company data, with grounded calculations, insight, trends, and limitations.
5. **Executive / Assistant Agent (internal):** business intelligence, AI workforce management, proactive reports and recommendations, and authorized execution. **Final product-facing name remains open.**

The agents cooperate and hand off context safely, rather than acting as unrelated bots.

## 2. Approved decisions — authoritative register

*The following AGT numbers reflect the numbering established in the conversation. Do not assume that the original unnumbered product principles started on these dates; these entries register the decisions as expressly approved during the October 2026 discovery.*

| ID | Approved decision | Operational meaning |
|---|---|---|
| AGT-001 | **Controlled Multi-Segment Pilot** | Pilot with a small set of companies across 2–3 candidate segments; **which sectors remains deferred/unselected**. |
| AGT-002 | **Productized Managed SaaS** | Clear SaaS packages and digital demos, assisted structured setup, a path to lower-touch self-service. Pricing is unapproved. |
| AGT-003 | **Controlled Real Actions** | Real limited authorized integrations/actions rather than just conversation; audit and approvals. |
| AGT-004 | **Hybrid Integration Model** | Reusable connectors + scoped paid custom integration work behind common Action/Integration Layer. |
| AGT-005 | **Risk-Based Approval** | Pre-authorized low-risk actions may execute; sensitive actions require a verified human approval. Backend enforces policy. |
| AGT-006 | **Multi-User with Basic Roles** | Several users per business; Owner/Admin/Member are provisional role labels; detailed matrix remains open. |
| AGT-007 | **Multi-Business Membership** | Same account can join different businesses with independently enforced membership/permissions and business switcher. |
| AGT-008 | **Hybrid Customer Identity** | Guest conversation first; provisional profile; verify identity before private records or cross-device identity linking. |
| AGT-009 | **Structured Customer Memory** | Per-customer-within-business structured memory distinct from raw conversations, knowledge, operational data and analytics. |
| AGT-010 | **30-Day Raw Conversation Retention** | Delete raw conversation content on a 30-day policy; deletion mechanics/backups/legal exceptions require design. |
| AGT-011 | **Active Customer Memory** | Retain only while a legitimate operational purpose exists, with review, correction and deletion; not indefinite. |
| AGT-012 | **Hybrid Intelligent Routing** | Customer may pick a public agent; system may route to more suitable agent preserving authorized context. |
| AGT-013 | **Hybrid Human Handoff** | Basic internal human inbox and configurable external escalation. |
| AGT-014 | **Customer-Owned BYOK + Backup** | Customer supplies primary and separate backup API credentials; initial setup configures both, backup installation included. No platform-funded AI tokens. Alert on fallback; self-service replacement or modest-fee assisted replacement. |
| AGT-015 | **Capability-Aware Fallback** | Use backup only for compatible supported tasks; suspend/escalate unsupported or unsafe operations. |
| AGT-016 | **Automatic Recovery** | On stability of primary provider, automatically fail back, with health checks/cooldown and safeguards against duplicate side effects. |
| AGT-017 | **Hybrid Knowledge Management** | Manual edits/uploads and selected synced sources, with controlled validation/review of significant changes. |
| AGT-018 | **Data Analyst: Agentree Data + Files + Connected Sources** | Operational analytics, Excel/CSV, and a limited set of authorized connected data sources; credible calculations and cross-source analysis where appropriate. |
| AGT-019 | **Proactive Executive** | On-demand assistance plus scheduled reports, alerts, monitoring, recommendations, and controlled execution. |
| AGT-020 | **Dashboard + In-App Notifications + Telegram** | MVP's initial executive delivery channels; ensure recipient authorization/privacy. |
| AGT-021 | **Text First, Voice Ready** | Deliver text-based Executive first, maintain clear channel separation to add voice later. |

**Not an approved independent decision:** Risk-Based Knowledge Publishing (automatically publish low-risk verified changes, human approval for sensitive changes) is a **technical recommendation pending review**, not AGT-018. The Product Owner explicitly chose to streamline technical detail rather than answer that question.

## 3. Public experiences, human handoff and identity

### Public AI / Bio Page (strategic core feature)

Each tenant gets a business URL such as `agentree.com/BusinessName`, combining an AI front door and link-in-bio. It can show Sales / Customer Service / Technical Support entry points and user-configured links to website, WhatsApp, booking, social profiles, contact and other URLs with title, description and URL. Future subscription limits and custom domains are not finalized; custom domains are outside MVP.

### Website widget

One embedded text-first widget on the client's website exposes customer-facing agents, routing, and context continuity. No public voice in MVP. Secure public APIs, anti-abuse measures and tenant scoping are necessary.

### Human handoff

Basic internal inbox: receive, assign, reply to, track status and return escalations to AI where permitted. Also allow external escalation destinations/workflows; exact channels/connectors are open. Handoff should preserve authorized context. Do not let AI continue replying while a human owns the conversation unless explicit rules allow it.

### Identity and memory

Guests can start chatting immediately. Unverified names, emails or phones are NOT identity proofs. Only verified linking grants access to previous protected personal data or authorizes sensitive actions. Shared structured memory belongs to a customer within a business; do not conflate it with 30-day raw chat history, business knowledge, operational data, analytics or audit logs. Memory extraction/review/deletion requires privacy design. No cross-tenant identity leakage.

## 4. Knowledge, integrations, actions, routing and BYOK

### Knowledge

Each business owns isolated company/product/service/price/policy/FAQ/technical docs, files, onboarding input and supported connected knowledge. Support manual edits + selective sync; maintain provenance, checks and versioning as appropriate. External documents are **untrusted content**, never executable instructions.

### Integrations/actions

Avoid custom direct integrations per agent. Use shared typed Action Gateway → tenant authorization → risk policy → approval where necessary → connector → external system; record outcomes. Start with a **small validated real action** such as creating a lead or follow-up; first connector has NOT been approved. Support reusable integrations plus separately scoped customer-specific implementation, not a large marketplace. Recheck permissions on backend. Prevent duplicate non-idempotent writes during retries or failover.

### BYOK, backups and routing

The customer owns and pays for AI provider use, **not Agentree**. Agentree helps install primary and backup keys during first setup at no additional backup-installation charge. The platform may offer guided self-service key update or a small paid managed replacement service. A primary outage triggers capability-aware fallback to a customer-owned compatible provider; dashboard warning/status; automatically return after verified recovery. Important: no guarantee an API called “free” remains free; DeepSeek API is not generally free, and backup access may have limits/fees. Verify real free tiers/rates later. Distinguish failing account balance from a single key failure. Store secrets encrypted, never expose in code/prompts/logs.

The model router chooses a supported model for the task according to cost, capabilities, latency, quality, availability and customer settings. Provider wrappers/adapters should prevent provider lock-in. Routing must not override permissions or human approval.

## 5. Data Analyst & Executive

**Data Analyst** must analyze internal Agentree metrics and authorized business data (Excel/CSV plus at least one candidate connected source). Use verifiable calculations and clearly disclose missing data; no invented figures. Uploaded data must not enable arbitrary code execution. Permissions and tenant boundaries apply to datasets, query results, caching and outputs.

**Executive** observes authorized business metrics and agent performance; offers dashboards, scheduled reports, alerts, actionable recommendations and tightly controlled internal changes. The loop is Observe → Analyze → Recommend → Approve/Execute → Report. Start text-only, later add voice through channel abstraction. Deliver through Dashboard, in-app alerts and Telegram, with identity-verified secure Telegram linkage, appropriate data minimization, retries and event scheduling. Autonomous broad self-modification is excluded.

## 6. Commercial operating model and onboarding

Primary audience is US business customers, but precise launch segments are deferred. Product Owner will market publicly as a founder based in Egypt, predominantly through videos, interactive demos, website and low-call sales. Never imply a US origin or guaranteed bias-free prospects. Productized managed SaaS includes subscriptions (final prices/open), assisted setup (potential one-time implementation fee), optional custom integrations, and distinct **Custom Your Agent** development/recurring work. Custom Your Agent stays separate from the five-role core and does not require building a full self-service agent builder in MVP.

Onboarding gathers business identity, products/services, policies, knowledge, customer needs, agent configuration, handoffs, tools/connectors and customer-owned keys. Initial implementation may be assisted: Customer Input → Configuration → Review → Tests → Adjustments → Delivery. Aim to reduce manual effort over time.

## 7. Approved MVP Scope V1 — planning baseline

The Product Owner **explicitly approved MVP Scope V1 on 19 October 2026**. Its eight capability areas:

1. **SaaS Foundation:** auth, multiple tenant workspaces, multi-user basic roles, multi-business membership, secure isolation.
2. **Core AI Workforce:** five real agents, conversation orchestration, intelligent routing/handoffs and shared authorized context.
3. **Memory & Knowledge:** guest identity, structured memory, isolated knowledge, uploads, 30-day raw history/deletion.
4. **BYOK & Model Runtime:** customer keys, provider abstraction, routing, compatible fallback, recovery, usage tracking.
5. **Integrations & Actions:** shared integration boundary, at least one approved real action, approvals and audit events.
6. **Public Interfaces:** Public AI / Bio Page, text widget, links.
7. **Business Dashboard:** leads, conversations, settings, human inbox, basic analytics.
8. **Intelligence Layer:** Data Analyst on platform metrics, CSV/Excel and a selected source; text-first proactive Executive; scheduled reports/notifications/Telegram.

**Explicitly deferred:** public voice, Executive voice, many native connectors, marketplace, complex autonomous workflows, advanced roles builder, advanced custom-agent self-service, custom domains, full multichannel helpdesk, unrestricted self-learning and enterprise extras. The broader product vision remains valid; use narrow functioning MVP versions of each selected capacity.

**Pilot acceptance remains contingent on real tests:** cross-tenant isolation, unauthorized actions blocked, secure handoff and identity, no fabricated analytics, compatible provider failover/recovery without double-writes, reports/Telegram notifications, and correct retention/deletion behavior.

## 8. Architecture Blueprint V1 — RECOMMENDATIONS, NOT APPROVALS

An architecture proposal was prepared but has **not been technically validated or approved**. Preferred conceptual style: **modular monolith** rather than premature microservices, with clear frontend, API, authentication/tenant layer, orchestrator, memory/knowledge, provider routing, integrations/action gateway, worker and storage boundaries.

**Candidate, not locked technology stack:** Next.js/TypeScript frontend; Python/FastAPI backend; PostgreSQL/SQLAlchemy/Alembic; pgvector if justified; S3-compatible object storage; Redis + background worker; LiteLLM SDK behind our own provider adapter; Docker Compose for early deployment; private GitHub repo, automated tests and CI/CD. Review against real repository, docs, operational cost and implementation speed before committing. Consider simpler stack if justified. Hetzner is only one hosting candidate.

Non-negotiable technical properties: strict tenant isolation, backend authorization, API key encryption, rate limits for public interfaces, untrusted data isolation, prompt injection and SSRF defenses, secure ingestion, audit events, idempotency, controlled retries, logging without private secrets, backups/recovery, versioned migrations and rollout/rollback.

## 9. Proposed development plan — 7 vertical slices

1. **Foundation:** auth, tenants, memberships, roles, isolation tests.
2. **First Working Agent:** customer-owned BYOK, adapter/router, knowledge, a real Sales conversation.
3. **Workforce Integration:** all five roles, routing/handoff, shared context, identity and memory.
4. **Public Experience:** AI page, widget, leads, internal inbox, human escalation.
5. **Actions & Intelligence:** gateway/approvals, first connector, CSV/Excel and connected-source analytics.
6. **Executive & Operations:** executive insights, scheduled notifications/Telegram, retention and health monitoring.
7. **Pilot Readiness:** E2E/security/regression tests, deployment, backup/recovery and assisted onboarding.

This is sequencing for review, not an instruction to implement all slices immediately. Each slice needs requirements, acceptance criteria, expected files, test evidence, failure handling and explicit approval before merge.

## 10. Exact current project state and Claude Code Web first task

- Private `agentree` GitHub repository reportedly created with README; **contents not yet inspected here**.
- No evidence of a running application, configured deployment, implemented code, or test results yet.
- Core project docs have been drafted. This **V2** is the current consolidated context. Older V1 files are supporting historical material.
- Product Owner approved planning scope, **not final technical architecture** or production implementation.

**Claude Code Web's first task:** confirm actual GitHub/repository availability; inspect real files/branch/dependencies; read this master V2 plus any blueprint/execution plan; produce a brief repository audit, architecture review, decision recommendations and `TASK_01_SPEC.md`; identify high-impact risks and anything needing Product Owner approval. **Do not build, migrate, deploy, commit speculative production code, or claim testing on this first task.**

Once reviewed, proposed architecture and first task return to Product Owner and ChatGPT for approval. Only then start implementation in small feature branches.

## 11. Open decisions (not blockers to the repository audit)

- Pilot sectors and initial customer profile (explicitly deferred).
- Final commercial packages/prices and charge details.
- Executive product-facing name.
- Tech stack and hosting topology, after actual audit.
- Detailed roles/permission matrix and identity verification mechanisms.
- Backup provider/key configuration, capability tests, failure and recovery thresholds.
- Selected first real connector/action and connected analytics data source.
- Knowledge publishing policy and sync mechanisms.
- Retention enforcement including memory review criteria, raw history deletion/backups, privacy/legal exceptions, data export, cancellation data handling.
- Final billing/payment workflow, operational costs and deployment/CI/CD.

Avoid reopening approved decisions without identifying a concrete contradiction or risk. Document routine technical choices as recommendations/ADRs instead of asking the Product Owner many questions.
