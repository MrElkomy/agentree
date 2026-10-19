# AGENTREE — Repository Audit

Date: 2026-10-19 (updated after the `agentree` repository was created)
Phase: Architecture Validation & Repository Audit (Task 0). No production code written.

## 1. What was inspected

| Item | Method | Result |
|---|---|---|
| Session environment | Claude Code on the Web, cloud container | Verified |
| Repository | `MrElkomy/agentree` (private), cloned to the session | Verified accessible with push rights |
| Branches | `git branch -a` | `main` only (before this work) |
| History | `git log --all` | 2 commits: `48f1382 Initial commit`, `b0168d8 Add files via upload` |
| Files on `main` | `find` | `README.md` (2 lines), `AGENTREE_MASTER_PROJECT_CONTEXT_V2.md` |
| Master Context V2 | Read in full; byte-identical to the copy uploaded in chat | Verified |
| Blueprint V1, Execution Plan V1 | Uploaded zip, read in full | Not in repo before; added under `docs/product/` |
| Tests / CI / dependencies / config | Searched | **None exist** |
| Secrets | None present; none read | — |

Earlier in this session, `MrElkomy/track-sm-automation` was inspected and confirmed to be an unrelated product (TRACK social-media automation). It contains nothing reusable for Agentree.

## 2. What actually exists

| Agentree capability | Status |
|---|---|
| Any application code (frontend, backend, worker) | Not implemented |
| SaaS foundation, agents, memory, knowledge, BYOK, actions, public page, widget, dashboard, inbox, analyst, executive | Not implemented |
| Tests, CI, Docker, infrastructure, deployment | Not implemented |
| Product documentation | Master Context V2 (authoritative), Blueprint V1, Execution Plan V1 (supporting) |

**Conclusion: greenfield build.** Nothing to rewrite or reuse.

## 3. Environment capabilities (verified)

Python 3.13, `uv`, Node 22, npm 10, Docker 29, PostgreSQL 16, Redis 7, 4 vCPU / 15 GB RAM, PyPI and npm reachable, GitHub via MCP tools (no `gh` CLI).
- Real-Postgres integration tests can run inside the session.
- Containers are ephemeral: anything not pushed is lost.
- No deployment credentials, servers, domains, email provider or cloud accounts exist; none assumed.

## 4. Document reconciliation

Source-of-truth order: **Master Context V2** > master prompt of this session > Blueprint V1 / Execution Plan V1.

| # | Topic | Conflict | Resolution |
|---|---|---|---|
| C1 | AGT-001..021 | Referenced by V1 docs without a list | **Resolved by V2 §2.** `ARCHITECTURE_DECISIONS.md` now uses the AGT numbering. |
| C2 | Lead creation timing | Master: Action Gateway in slice 5. Execution Plan: lead action in P2 | Minimal Action Gateway (low-risk internal actions) ships with the workforce; approvals UI + external connector stay in slice 5. |
| C3 | "Exactly once" | Execution Plan says exactly once; Blueprint says it cannot be promised | Exactly-once holds for internal DB writes (idempotency key + unique constraint), not for external systems. |
| C4 | Fallback timing | V2 places BYOK adapter/router in slice 2; Execution Plan places failover in P6 | Primary/backup + circuit breaker right after the first agent. |
| C5 | Executive over Telegram | AGT-020 lists Telegram as a delivery channel; Blueprint says outbound notifications | MVP: outbound notifications + approval deep links. Two-way chat over Telegram later unless approved. |
| C6 | Retention job timing | V2 slice 6 | Retention fields from day one; deletion job running before any real public visitor (slice 4). |
| C7 | Background queue | V2 candidate stack lists Redis + worker (candidate, not locked) | Recommendation: Postgres-backed queue, no Redis in MVP (`ARCHITECTURE_REVIEW.md` §6). Flagged for approval. |
| C8 | Knowledge publishing | — | V2 confirms risk-based publishing is **not** approved. Default stays manual publish. Consistent. |

## 5. Repository changes made in Task 0 (branch `claude/nifty-darwin-x2veie`, not merged)

- `AGENTREE_MASTER_PROJECT_CONTEXT_V2.md` moved from root to `docs/product/` (content unchanged).
- `docs/product/` — Blueprint V1 and Execution Plan V1 (unchanged copies).
- `docs/architecture/` — this audit, review, decisions, roadmap, Task 01 spec.
- `README.md` — short index pointing to the docs.

No application code, dependencies, migrations, CI or infrastructure were added.
