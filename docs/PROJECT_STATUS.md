# Agentree — project status and working agreement

Read this first in every new session (with `CLAUDE.md`). Keep it current: update it in the PR
that changes what it describes. Last updated: 2026-10-21.

## Working agreement with the Product Owner (PO)
- The PO writes in **Egyptian Arabic**; reply in Egyptian Arabic, short and direct. Code, docs,
  commits and PRs are in English.
- **One step at a time.** When the PO has to do something (server, DNS, settings), give one
  command or action, wait for the output, then the next. No chains of dependent steps with
  branches in the middle. Explain any server, DNS or SMTP change before it is made.
- The PO runs every server command themselves (Tabby, Hetzner). Never run destructive commands or
  change the live server without explicit approval.
- **No merge and no deploy without PO approval.** One focused PR per roadmap task (a/b split when
  backend and web are separately testable). Never claim tests/CI that did not run.
- Start a roadmap task only when the PO approves it ("ابدأ"). Do not start the next task on your
  own. Decisions that change scope go to the PO as proposals, then into the roadmap.
- Budget-sensitive: prefer free options, ask before anything paid.
- The PO sometimes relays reviews from ChatGPT; treat them as PO input. "Report for ChatGPT" means
  a concise English status report.

## Where we are
- **Roadmap:** `docs/architecture/MVP_IMPLEMENTATION_ROADMAP.md` → *MVP Completion Sprint*
  (Tasks 10–22) and the tracking table of approved requirements outside those tasks.
- **Done and merged:** Tasks 01–09 (foundation, auth, tenancy, BYOK, knowledge, Sales Agent,
  retention, staging, public page + widget + guest sessions), brand identity, Task 10 (audit log
  #27, branded emails #28), Task 11 (leads + Action Gateway #29), Task 11b (follow-up reminders
  #30).
- **Merged:** Task 12 — Human inbox + handoff + email alert (#32, `docs/architecture/INBOX.md`).
- **Task 13** merged (#33 13a reliability, #34 13b Web Push) and deployed with batch 1;
  #35 chat scroll fix merged and deployed.
- **Merged:** Task 14 — agent framework, routing, shared context (#36,
  `docs/architecture/AGENTS.md`).
- **In review:** Task 15 — complete Customer Service + Technical Support agents, knowledge
  scoping per agent, resolution by the AI, the visitor or the team (`AGENTS.md`). Batch 2 =
  Tasks 14–16.
- Shared Hetzner host with TRACK, IELTS and the Telegram bridge — never disrupt them.
- Deploy: the PO runs `~/agentree/infra/staging/deploy.sh origin/main` (pre-deploy encrypted
  backup, migrations, automatic rollback). Details: `docs/operations/STAGING_RUNBOOK.md`.
- **Deployed:** main through #35 (Tasks 10–13, migrations through 0014). **Merged:** #36 (Task 14,
  migration 0015); the PO started its deploy on 2026-10-21 — result not yet confirmed here.
- **Deployment batches (PO decision):** don't deploy every PR. Batch 1 = Tasks 11 + 11b + 12 + 13
  → batch 2 = 14–16 → batch 3 = 17–21 → batch 4 = 22. Tell the PO when a batch is ready.
- **Task 16 in review:** customer identity (email code) and customer memory
  (`docs/architecture/CUSTOMERS.md`, migration 0017); last task of batch 2.
- AI on staging: Groq (free tier) as the demo provider key. Nightly encrypted backups to Google
  Drive at 03:00 America/New_York.

## Open PO decisions (do not assume answers)
- **U-12 / U-13** (customer memory retention and review timing) — must be decided before Task 16.
- **Google Sheets** (required; three uses: lead sync, reports, knowledge for agents instead of
  server uploads) — placement to propose with Task 17.
- Other deferrals and placements: see the roadmap's tracking table; each needs PO approval.
- Possible later improvements noted, not approved: restrict characters in business names
  (invite-email spam risk); "sign out and use another account" on the invitation page.

## Local development notes (cloud container)
- `service postgresql start`; tests use `AGENTREE_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`.
- Full local stack for E2E: a scratch database, `alembic upgrade head`, uvicorn on :8000 with
  `AGENTREE_LLM_DEMO_MODE=true`, `npm run start` on :3000, and Mailpit (single binary from its
  GitHub release) on :8025/:1025. Repeated runs hit the signup rate limit (10/hour/IP): clear
  `rate_limit_buckets` in the scratch database.
- CI runs `alembic check`: every index/constraint in a migration must also be declared on the model.
