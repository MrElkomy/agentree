# Agentree — Fast-Track Launch Plan (30 days)

Date: 2026-10-19 (Day 1). Status: plan for Product Owner review. MVP Scope V1 is unchanged; anything marked **[PO approval]** is a *proposal* to sequence after launch, not a decision.

## Definition of "sellable first release"
A paying business can: sign up → create a workspace → add its own AI key(s) → load its knowledge → publish its Public AI/Bio page and widget → visitors chat with Sales / Customer Service / Technical Support (with routing and handoff) → leads are captured → humans take over from an inbox → owners see conversations, leads and basic analytics. All of it under the launch gates below.

## Critical path (sequential dependencies)
```
Tenancy+RLS ✅ → Auth + memberships + business switcher → BYOK vault + LLM adapter
→ Knowledge v1 → Sales agent conversation → Public page + widget + guest sessions
→ Leads (minimal Action Gateway) + Inbox → 5 roles + routing/handoff → Fallback/recovery
→ Retention job + audit → Staging/production deploy, backups, security review → Launch
```

## Weekly milestones (each ends with a working, demoable product)

| Week | Days | Working product at end of week |
|---|---|---|
| 1 | 1–7 | First-party login (ADR-001), create/switch businesses, invite members with roles, isolation matrix on all endpoints. Next.js shell with dashboard layout. **Staging environment deployed from CI.** |
| 2 | 8–14 | Owner adds primary + backup key (encrypted), uploads/edits knowledge, chats with the Sales Agent in a dashboard test console with streaming replies grounded in its own knowledge. |
| 3 | 15–21 | Public AI/Bio page + embeddable widget live on staging; visitors chat with all three public agents, transfers between them keep context; leads auto-created; human takeover from inbox; abuse limits protect customer keys; automatic failover to backup key and recovery. |
| 4 | 22–30 | Retention (30-day deletion), audit log, operational analytics + Data Analyst on Agentree data and CSV/XLSX, Executive daily report in-app; security review, backup/restore drill, production deploy (with approval), onboarding runbook, first pilot customer onboarded. |

## Launch-blocking vs post-launch

| Capability (MVP V1) | Launch | Note |
|---|---|---|
| SaaS foundation, roles, isolation | Blocking | |
| 5 agents, routing, handoff, shared context | Blocking | Data Analyst + Executive minimal versions in week 4 |
| BYOK, fallback, recovery, usage tracking | Blocking | |
| Knowledge (manual + upload), guest identity, 30-day retention | Blocking | |
| Structured customer memory | Blocking (basic) | Extraction + review/delete UI; email-OTP verification can follow **[PO approval]** if week 3 slips |
| Public page, widget, links | Blocking | |
| Dashboard: leads, conversations, inbox, basic analytics, config | Blocking | |
| At least one real action + audit | Blocking | Internal `create_lead`/`create_follow_up_task` via Action Gateway |
| Approval workflow UI (medium/high-risk actions) | **[PO approval]** post-launch | No medium/high-risk actions exist at launch, so nothing needs approval yet |
| First external connector (signed webhook) | **[PO approval]** post-launch (week 5) | |
| Data Analyst: Google Sheets source | **[PO approval]** post-launch | CSV/XLSX at launch; Google OAuth verification takes weeks anyway |
| Executive scheduled reports | Blocking (daily, in-app) | Weekly report + Telegram delivery **[PO approval]** week 5 if week 4 slips |
| External handoff | Blocking (email notification) | Webhook route with the connector |

## Parallel tracks (safe to run concurrently)
- **Backend core** (critical path above) — primary.
- **Frontend** (Next.js dashboard, public page, widget) against the generated API client — can run in a separate session/branch once each API slice lands.
- **Infra** (staging/prod, Caddy TLS, backups, monitoring) — week 1 onward, independent of features.
- **Docs/onboarding** (key-setup guide, privacy notice, runbooks) — week 3 onward.
Each track uses its own branch and PR; tenancy/security code changes only on the backend track.

## Non-negotiable launch gates
1. Cross-tenant isolation matrix passes on every tenant endpoint; RLS on every tenant table; app DB role verified unprivileged in production.
2. Provider keys encrypted at rest; never in logs, responses or frontend (automated test + log scan).
3. Authorization enforced server-side for every action; no agent tool outside the Action Gateway.
4. Public endpoints rate-limited with per-business daily caps and bot protection.
5. 30-day raw-conversation deletion job running and tested with aged data.
6. Encrypted backups with a completed restore drill; rollback procedure tested once.
7. TLS, security headers, secrets only in the environment/secret store; gitleaks + dependency audit clean.
8. Failover to backup key and recovery demonstrated on staging with real test keys.
9. Error monitoring + alerting on API errors, job failures and provider health.
10. Privacy notice + AI disclosure on public page and widget.

## Risks to the date
- 30 days is aggressive for the full MVP V1; the post-launch proposals above are the pressure valves.
- External accounts needed early: hosting + domain (week 1), transactional email/SMTP (before staging invites, week 1–2), object storage (week 2). **Product Owner action.**
- Real AI test keys (two providers) needed by week 2 for staging verification.
