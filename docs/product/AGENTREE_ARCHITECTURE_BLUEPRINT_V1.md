# AGENTREE — ARCHITECTURE BLUEPRINT V1
Date: 2026-10-19
Status: PROPOSED FOR TECHNICAL REVIEW — NOT PRODUCTION APPROVED

## 0. Authority and constraints
Source of truth: Agentree Master Project Context plus the Product Owner's approved decisions AGT-001 to AGT-021. MVP Scope V1 is approved as planning scope. Sector choice is deferred. This is a proposed design, not evidence that code exists or has been tested. Do not start production coding until Product Owner approves architecture and execution plan.

### Approved decisions carried forward
- 5 fixed core agents: Sales, Customer Service, Technical Support, Data Analyst, Executive. Three public, two internal; agents cooperate and hand off without losing authorized context.
- Controlled multi-segment pilot; sector selection deferred. Exclude wedding photography and wedding-event businesses from future recommendations per owner preference.
- Productized Managed SaaS, assisted setup initially; Controlled Real Actions.
- Hybrid integrations (reusable connectors + custom services); risk-based action approval; multi-user basic roles; multi-business memberships.
- Hybrid guest/verified customer identity; structured customer memory, separately from conversation history; raw message retention 30 days; active memory only while justified, subject to deletion/review.
- Hybrid intelligent agent routing and hybrid human handoff.
- Customer-owned BYOK only: primary and backup keys belong to each customer. Set up both without extra backup-key fee during initial setup. No Agentree-owned usage keys for customers. Capability-aware fallback and automatic recovery with notification; provider free tiers are NOT assumed permanent or guaranteed.
- Hybrid knowledge management, manual and connected sources. Risk-based knowledge publishing discussed but not explicitly approved: record as recommendation, not a confirmed product decision.
- Data Analyst: Agentree operational data + files + selected connected sources. Proactive Executive: internal monitoring, reports, approved actions; Dashboard, in-app notifications, Telegram; Text First, Voice Ready.

## 1. Architecture decision proposal
Use a *modular monolith* deployed with separate frontend, backend API, and worker processes from a single coordinated product codebase. Avoid distributed microservices until operational evidence requires them.

Proposed stack (requires verification and approval):
- Web: Next.js + TypeScript; public bio pages, embeddable widget bundle, admin dashboard.
- API and agent runtime: Python + FastAPI; Pydantic schemas and explicit service boundaries.
- Data: PostgreSQL, SQLAlchemy/Alembic; evaluate pgvector for RAG at expected initial corpus size.
- Provider abstraction: interface owned by Agentree, optionally implemented with pinned/tested LiteLLM SDK; do not delegate tenant authorization, action approval, or secret custody to LiteLLM.
- Files: S3-compatible object storage; per-tenant access mediation, no direct public bucket reads for private files.
- Worker & scheduling: Redis-backed durable queue + worker; choose a specific library only after review. Jobs include ingestion, reports, memory extraction, retention deletion, notification delivery, sync and health checks.
- Containers: Docker Compose for development and modest initial deployment; deploy behind HTTPS proxy, with distinct environments.
- Observability: structured logs with tenant-safe identifiers, metrics, tracing without secrets/personal message contents, audit event store.

### Boundaries
Web -> API -> Authentication/tenant middleware -> Domain modules -> DB/queue/provider adapters.
Domain modules:
1. identity_organizations
2. memberships_permissions
3. agent_config_orchestration
4. conversations_routing
5. customer_identity_memory
6. knowledge_ingestion_retrieval
7. provider_credentials_routing
8. integrations_actions_approvals
9. inbox_handoff
10. analytics_data_analyst
11. executive_jobs_notifications
12. billing_entitlements (minimal boundaries only, since prices/packages not finalized)
13. audit_observability_retention

No module may directly import another module's persistence internals; use explicit interfaces/services. Integrations are executed server-side through a gateway, never from arbitrary model-generated URLs or client tokens.

## 2. Data design
Primary entities (tentative): users; businesses; business_memberships(role, state); sessions; business_settings; agents; agent_versions; conversations; conversation_messages; conversation_participants; customer_profiles; customer_identities(verification_state); customer_memories(source, confidence, review_at); handoff_events; inbox_assignments; knowledge_sources; knowledge_documents; document_versions; document_chunks; model_credentials(encrypted_ref); provider_model_profiles; routing_policies; integration_connections; action_definitions; action_executions(idempotency_key); action_approvals; leads; uploaded_datasets; analysis_runs; scheduled_reports; notifications; notification_deliveries; audit_events; deletion_jobs.

Every tenant-owned row should carry business_id with tenant-scoped unique constraints and foreign keys wherever practical. Membership resolves on EVERY request; derive tenant from authenticated server-validated context rather than trusting an arbitrary client header. Cross-business membership does not imply any cross-business data sharing.

Security requirements:
- Verify resource ownership and membership in read/update/delete and job handlers; test IDOR by passing another business's IDs.
- Assess Postgres Row Level Security as defense in depth: application connections, policy evaluation, background jobs, migration role bypass and testability must be explicitly designed. RLS alone is insufficient.
- Encrypt customer provider keys with envelope encryption/KMS-like key separation; avoid plaintext logging, echoes, front-end storage; support rotation and revocation.
- Public guest session tokens should be short-lived and scoped to one business and conversation. Verified identity required before accessing previously stored protected personal data or linking cross-device identities.
- Store 30-day raw-message retention metadata per message; deletion must cover DB text, embeddings derived directly from raw text if applicable, files/indexes, caches and documented backup expiry; legal exceptions decided separately. Memory, analytics and audit retention need their own policies.

## 3. Runtime and routing
Conversation message -> authoritative business + visitor context -> conversation state -> intent routing -> selected role -> policy-checked tools/knowledge/customer memory -> model router -> provider adapter -> response/event persistence. Avoid unnecessary model calls for basic route checks. Handoffs preserve only authorized conversation context; agent transfer does not increase tool rights.

Models are untrusted planners, not authority to execute. Model output is validated against allowlisted structured action schemas. Backend authorizes action by tenant, agent role, user/customer identity, integration connection, risk tier and approval state; queue async if needed. Low-risk examples: create lead. High-risk examples: deletion and sensitive config modifications. Human-inbox acquisition suppresses agent auto-replies until resolved/released.

Provider failover:
- Credential primary/backup defined per business, never platform keys; verify that alternative uses a distinct valid quota/provider when desired.
- Per-task capability profile: model support for structured outputs, tool calls, context windows and tested quality; deny or escalate unsupported tasks on backup.
- Error classes: auth invalid, quota exhausted, rate limit, transient network, provider service error, model unsupported. Bounded retries and circuit-breaker/cooldown; do not failover indiscriminately for malformed prompts/tenant policy errors.
- Recovery health probes should be low-impact and cost-aware; move NEW turns to healthy primary after checks, not mid-action.
- Exactly-once effect cannot be promised for external systems; use idempotency keys and reconciliation for uncertain responses. Record attempts, avoid blind replay of side effects.
- Dashboard banner and notification; do not expose key values.

## 4. Knowledge and data analyst
Knowledge ingestion: approved source -> fetch/upload -> sanitization/virus checks -> document extraction -> chunk/embed/index with metadata -> retrieval scoped by business and role. External content is untrusted data, never executable instructions. Source changes are versioned; risk-based publishing is PROPOSED, not approved.

Data analysis: use immutable import artifacts / selected read-only views and constrained computation tools, not unrestricted SQL/code execution against production DB. Scope requests by tenant and entitlement; log dataset/source provenance. Answers with numeric claims must cite the specific run/source and show data freshness. For CSV/XLSX, enforce upload size, malware scanning, parse limits, PII minimization and workload timeouts. Connected sources begin with one reusable read connector selected during pilot planning.

## 5. User-facing MVP
- Public bio page: stable business slug, basic branding, agent entry points and configurable links. Rate limits, anti-abuse measures and consent/privacy notice.
- Widget: one embeddable script with constrained allowed origins per business; never expose model credentials. Text only initially.
- Human inbox: assignment, reply, conversation status, handoff and AI resume. External handoff first through a simple configurable supported route, not full contact-center integration.
- Dashboard: agents and knowledge, leads, conversations, inbox, basic analytics, key status, notices, executive reports; user roles Owner/Admin/Member are tentative permission mappings and require review.
- Executive: text conversation, read approved data, generate scheduled reports/alerts, internal actions under policy; Telegram outbound notifications linked to verified business members; no sensitive raw payload without policy review.
- Voice-ready means channel abstraction only, NOT premature realtime-audio infrastructure.

## 6. Deployment and operations
Local environment: Docker services with isolated dev secrets. Dev/staging/production separated. Migrations tested against staging and reversible or repairable; automated backups tested via restore drill; access controls for operator. CI: static checks, dependency scanning, unit+integration tests, migrations, end-to-end core flows, secrets scan. Feature flags for risky capabilities. Metrics: AI availability, fallback rate, latency, conversation success, action rejection/approval, token usage cost attribution (customer provider spending estimates), job failures, 30-day deletion backlog, tenant isolation tests.

No direct production deployment, billing integration, live customer credentials, or DNS changes without explicit approval.

## 7. Threat and risk register
R1 cross-tenant leak: scoped queries + authorization + RLS review + adversarial tests.
R2 prompt injection via files/pages: untrusted-data treatment + typed tools + deny arbitrary actions.
R3 customer secret leakage: envelope encryption, RBAC, redaction, rotate workflow.
R4 duplicate external write: idempotency, dedup/reconciliation, audit trail.
R5 uncontrolled cost / free tier exhaustion: customer-owned credential and quotas, usage alerts, fail-closed when no compatible model.
R6 failed deletion and retention: deletion jobs, indexed storage inventory, backup expiration.
R7 false analytics claims: source-linked calculations and tests.
R8 guest identity spoofing: verification before protected history/action.
R9 background queue failures: durable jobs, retry limits, dead-letter handling.
R10 scope creep: fixed phase gates and explicit exclusions.

## 8. Architecture decisions to review before code
ADR-001 language split (Next.js/TS + FastAPI/Python) vs TypeScript-only backend, with measurable tradeoffs.
ADR-002 ORM/schema strategy, tenant enforcement and RLS threat model.
ADR-003 queue choice with reliability/idempotency demonstration.
ADR-004 LiteLLM SDK as adapter vs direct vendor SDKs; licensing, feature parity, compatibility, credentials.
ADR-005 knowledge extraction/chunking/pgvector for MVP scale.
ADR-006 OAuth/auth mechanism, invites and workspace switching.
ADR-007 private object store and document processor isolation.
ADR-008 approval/audit and reversible configuration handling.
ADR-009 notification delivery and Telegram identity proof.
ADR-010 bounded Pilot readiness and provider/key test matrix.

## 9. Approval gates
Gate A: Claude inspects actual repo and produces evidence-backed inventory (what exists vs planned).
Gate B: architecture ADRs with tradeoffs/security review and owner approval.
Gate C: agreed milestone acceptance criteria and release plan.
Gate D: production coding on feature branch, tests passing, reviewer approval, owner approval before merge.

## References
Primary: user-provided Agentree Master Project Context; approved decisions in conversation.
External verification: https://docs.litellm.ai/docs/ ; https://docs.litellm.ai/docs/routing ; https://docs.litellm.ai/docs/proxy/reliability/ ; https://fastapi.tiangolo.com/tutorial/background-tasks/ .
