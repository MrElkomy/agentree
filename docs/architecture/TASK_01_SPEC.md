# TASK 01 — Repository Skeleton, Backend Foundation, CI

Date: 2026-10-19
Status: **Approved 2026-10-19** by Product Owner. Implemented on branch `feat/task-01-foundation`.

## 1. Goal

Create the empty-but-real engineering foundation for Agentree: a backend that boots, connects to PostgreSQL, runs migrations, is covered by tests against a real database, and is checked by CI on every push. No product features. This is the base every later slice builds on, and it proves the cloud development workflow (Claude Code Web → GitHub → CI) works end to end.

## 2. Precondition

Repository `MrElkomy/agentree` exists (created by Product Owner) and is attached to the session. Architecture and this spec approved 2026-10-19. The worker stays a placeholder; no job queue in this task.

## 3. Scope

### In scope
1. Monorepo layout:
   ```
   apps/api/                 Python package `agentree` (uv, pyproject.toml, uv.lock)
     agentree/main.py        FastAPI app factory
     agentree/worker.py      worker entrypoint stub (prints readiness, exits cleanly) — real queue in Task 03
     agentree/core/config.py Pydantic Settings (env-based, no secrets committed)
     agentree/core/db.py     async SQLAlchemy engine/session
     agentree/core/logging.py structured JSON logging with redaction filter
     agentree/health/api.py  /healthz, /readyz
     migrations/             Alembic (baseline revision: empty + `uuid` helper if needed)
     tests/
   apps/web/                 (empty placeholder README; built in slice 0.2)
   infra/docker-compose.yml  postgres + api (dev)
   infra/Dockerfile.api
   docs/                     already present (product + architecture docs)
   CLAUDE.md                 coding rules, module boundaries, test commands, security rules
   .github/workflows/ci.yml
   .env.example              names only, no values
   ```
2. Endpoints: `GET /healthz` (process alive), `GET /readyz` (DB `SELECT 1`, returns 503 if DB down).
3. Tooling: ruff (lint + format), mypy (strict on `agentree/`), pytest + pytest-asyncio, import-linter config (empty contracts ready for modules).
4. Test harness: session-scoped real Postgres database, created and migrated per test run; per-test transaction rollback.
5. Redaction filter: log records containing configured sensitive keys (`api_key`, `password`, `token`, `authorization`, `content`) are masked.
6. CI (GitHub Actions): Postgres service container → `uv sync --frozen` → ruff → mypy → alembic upgrade head + downgrade base + upgrade head → pytest → gitleaks → pip-audit.

### Out of scope
Users, auth, businesses, RLS policies (Task 02 = slice 1.1), web app (slice 0.2), job queue (Task 03), any LLM code, any deployment, any cloud resource, any real secret.

## 4. Acceptance criteria

1. `docker compose -f infra/docker-compose.yml up` starts Postgres and API; `/healthz` → 200, `/readyz` → 200.
2. With the DB stopped, `/readyz` → 503 and `/healthz` → 200.
3. `uv run pytest` passes locally in the Claude Code container against real Postgres.
4. Alembic upgrade → downgrade → upgrade succeeds on an empty database.
5. CI workflow runs on push to the feature branch and is green; link and job output included in the completion report.
6. A test proves the redaction filter masks a fake API key in a log line.
7. `.env.example` contains variable names only; gitleaks finds nothing.
8. `CLAUDE.md` documents: module boundary rule, "tenant context is derived, never accepted", no secrets/message content in logs, test commands, Definition of Done.

## 5. Test plan

| Test | Type |
|---|---|
| `test_healthz_ok` | API |
| `test_readyz_ok_with_db` | Integration (real Postgres) |
| `test_readyz_503_without_db` | Integration (engine pointed at closed port) |
| `test_settings_require_database_url` | Unit |
| `test_log_redaction_masks_secrets` | Unit |
| Migration round-trip | CI step |

## 6. Anticipated files

~20 new files, all under the new repository, as listed in §3. No existing file in any repository is modified.

## 7. Security checks

- No secrets committed; settings fail fast if required env is missing.
- Docker image runs as non-root user.
- Dependencies pinned via `uv.lock`; pip-audit clean (or findings reported).
- CI uses least-privilege `permissions: contents: read`.

## 8. Rollback

Everything lives on feature branch `feat/task-01-foundation` in the new repository. Rollback = do not merge / delete the branch. No data, infrastructure or external accounts are touched.

## 9. Completion report will include

Commands actually run with their output summaries, CI run link, test counts, known limitations, and the next proposed task (Task 02 = slice 1.1 Tenancy primitives + RLS).
