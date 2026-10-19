# AGENTREE — CLAUDE CODE EXECUTION PLAN V1
Date: 2026-10-19
Status: REVIEW / PLANNING ONLY. NO PRODUCTION CODE UNTIL OWNER APPROVES ARCHITECTURE + FIRST TASK.

## Roles
Product Owner: final decisions; ChatGPT: cross-product architecture/security/test review; Claude Code: primary developer, code owner; Cursor: supplementary read-only review or tightly scoped changes by permission. Git is source of truth; one feature branch per slice; no competing edits.

## Preflight — task 0 (first Claude run, no application coding)
1. Inspect repository and existing project docs/readme/package manifests, lockfiles, configs, migrations, tests and Git status; do not claim repo is empty without proof.
2. Locate existing features, their status and tests; compare against AGENTREE_ARCHITECTURE_BLUEPRINT_V1.md and Agentree_Master_Project_Context.md.
3. Inventory dependencies, candidate stack, deployment environment, and missing secrets WITHOUT reading/printing sensitive secret contents.
4. Produce ARCHITECTURE_REVIEW.md with diagrams, directory proposal, dependencies, ADRs with alternatives, security risks, cost/complexity, and clear MVP exclusions.
5. Produce REPOSITORY_AUDIT.md showing path, state, key evidence, what can be reused and what must be rewritten.
6. Produce TASK_01_SPEC.md with bounded first slice, acceptance criteria, test plan, files anticipated, explicit out-of-scope and rollback plan.
7. STOP and request Product Owner approval. No `npm install`/`pip install`, migrations, unapproved file rewrites, cloud resources, deployment, or production implementation in Task 0.

## Proposed phase gates (implement only after approvals)
P1 Foundation: registration/auth, business creation and switching, invites, Owner/Admin/Member permission checks, tenant isolation, tests. Acceptance: user has separate roles across two businesses; cross-tenant read/write and IDOR tests fail closed.
P2 First Agent vertical slice: one business, one BYOK provider, secret vault, text conversation, versioned basic knowledge, Sales Agent, lead capture and audit. Acceptance: lead action approved under policy and persisted exactly once under retry test; no secrets on frontend/logs.
P3 Workforce: five agent roles, routing, handoff, customer identity, structured memory, initial memory extraction. Acceptance: context preserved with limits, unauthorized memory not exposed, no cross-tenant leaks.
P4 Public Experience: Bio Page, text Widget, guest security, human inbox, external handoff, minimal dashboard. Acceptance: public browser E2E chat → lead → inbox transfer; no API keys leaked.
P5 Integrations and Analyst: controlled Action Gateway, approvals, one reusable external connector, CSV/XLSX import, operational reporting and external dataset analysis. Acceptance: provenance correct; unsupported operations denied; duplicate writes mitigated.
P6 Executive and Ops: scheduled reports, in-app and Telegram, failover/recovery capability checks, knowledge sync, retention worker. Acceptance: controlled failover/recover; no double actions; accurate scheduled reporting; 30-day cleanup tested with synthetic aged data.
P7 Pilot hardening: onboarding wizard-assisted workflow, privacy compliance review, back-up restore exercise, rate limits, abuse prevention, staging tests, observability, deployment runbook, load tests. Acceptance: pilot checklist evidence and owner go/no-go.

## Every-feature contract
- 1-paragraph goal / problem / target actor.
- Functional behavior, failure behavior and security/privacy cases.
- Explicit affected modules / files with diff scope.
- Data migration and rollback considerations.
- Tests: unit + integration + isolated tenant + auth + provider failure + E2E as applicable.
- Observable proof: commands run, logs sanitized, screenshots/video only if available, failing/passing cases.
- Reviewer report and outstanding limitations.
- Owner's final approval before merge.

## Claimed completion definition
No feature is 'done' without implemented behavior + tests actually run + acceptance criteria met + no security blockers + reviewer approval + owner approval. Never describe unexecuted tests as passed. Keep milestone sizes small enough to review independently.

## Recommended repo layout (subject to audit)
/apps/web (Next.js)
/apps/api (FastAPI API + domain services)
/apps/worker (jobs)
/packages/contracts (versioned API schema/types generated or shared)
/infra (compose, scripts, deployment templates)
/docs/architecture (ADRs, blueprint)
/docs/product (scope, decisions)
/tests (E2E and security matrices)

Avoid copying this folder tree into an existing project without inspecting real code and agreements.

## First Claude Code prompt — copy as one message
You are the primary technical architect and developer for AGENTREE. This task is DISCOVERY/ARCHITECTURE REVIEW ONLY. Read Agentree_Master_Project_Context.md, AGENTREE_ARCHITECTURE_BLUEPRINT_V1.md, AGENTREE_CLAUDE_CODE_EXECUTION_PLAN_V1.md, and inspect the actual repository and Git status. Preserve all approved AGT-001..AGT-021 decisions (the sector is not selected; the owner excludes wedding-related verticals). Do NOT write production code, install dependencies, create migrations, touch deployment, or modify existing application source. Do not access or disclose secret values.

Deliver: (1) REPOSITORY_AUDIT.md with evidence-linked file tree and implemented vs planned matrix; (2) ARCHITECTURE_REVIEW.md evaluating proposed modular monolith and Next.js+FastAPI+Postgres+pgvector+durable worker vs practical alternatives with specific security architecture, multi-tenant/roles, customer BYOK and compatibility-aware failover, knowledge, memory, action governance, Data Analyst and Executive; (3) ADR list with recommended choices, risks and open decisions; (4) TASK_01_SPEC.md giving a small first implementation slice and acceptance tests, rollback plan, anticipated files; (5) concise executive summary of recommendations and unresolved blockers. Clearly separate confirmed owner decisions, your recommendations, existing code evidence, and unknowns. STOP for Product Owner approval before implementing anything.

## Important unapproved topics
The precise first connector, initial target sectors, prices, Auth provider, cloud service, retention backup mechanism, connected knowledge source and risk-based knowledge publishing policy are OPEN. Do not mislabel these as approved.
