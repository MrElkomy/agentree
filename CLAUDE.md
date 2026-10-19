# Agentree — Engineering Instructions

Read before changing code. Product source of truth: `docs/product/AGENTREE_MASTER_PROJECT_CONTEXT_V2.md`. Approved architecture and open decisions: `docs/architecture/ARCHITECTURE_DECISIONS.md`. Never silently change an approved product decision; record proposals as proposals.

## Working rules
- Product Owner communicates in Egyptian Arabic. Code, docs, commits and comments are English.
- One roadmap slice per feature branch (`docs/architecture/MVP_IMPLEMENTATION_ROADMAP.md`). Never merge to `main` without Product Owner approval.
- Never claim tests, CI or deployment results that did not actually run. Report failures as they are.
- Never weaken, skip or delete a check to make CI green.

## Layout
```
apps/api/      Python package `agentree` (FastAPI api + worker entrypoints, Alembic migrations)
apps/web/      Next.js dashboard (App Router, TS strict, Tailwind); /api/* proxied to FastAPI (same-origin
               cookie), Playwright E2E in apps/web/e2e; see apps/web/README.md (npm run lint/typecheck/build/e2e)
infra/         Dockerfile(s), docker-compose for dev
docs/          product + architecture docs
```

## Architecture rules (approved)
- Modular monolith. Modules live in `agentree/<module>/` with `api.py`, `service.py`, `models.py`, `schemas.py`. Other modules call `service.py` only, never another module's models or tables. `agentree/core` must not import feature modules. Enforced by import-linter (`[tool.importlinter]` in `apps/api/pyproject.toml`); add a contract when adding a module.
- **Tenant context is derived, never accepted.** Business access comes from authenticated membership (dashboard) or validated public page / widget configuration (public). A client-supplied `business_id` only selects; it never authorizes.
- Every tenant-owned row has `business_id`; RLS enabled in the table's first migration via `enable_tenant_rls()`; tenant tables are only touched inside `tenant_session(factory, ctx)`. The app connects as `agentree_app` (unprivileged; startup guard enforces it); migrations run as `agentree_migrator`. Full rules: `docs/architecture/TENANCY.md`.
- Authorization and approvals are enforced in the backend, never by the LLM and never by Next.js middleware.
- Model output, uploaded files, retrieved documents and external responses are untrusted input.
- Background work uses the Postgres-backed queue (to be introduced); no Redis in the MVP.
- AI calls go through `agentree/llm` (`LLMProvider` interface) with the customer's key resolved per call from `agentree/providers` (BYOK vault, ADR-002). Never call vendor APIs or SDKs elsewhere; tests use `FakeProvider` via the `harness` fixture.
- Authentication: first-party (ADR-001, accepted). No managed auth providers; no custom crypto — use `argon2-cffi`, `secrets`, `hashlib`.

## Security rules
- No secrets in the repo, prompts, logs, errors or frontend. Config comes from `AGENTREE_*` env vars (`.env.example` lists names only).
- Never log customer message content or credentials. Use `logging.getLogger(__name__)` with structured `extra={...}`; the JSON formatter redacts sensitive keys as a safety net, not a licence.
- Outbound HTTP to customer-provided URLs must go through the SSRF guard (to be introduced) — never raw `httpx`/`requests` calls.
- Prefer allowlisted, typed operations. No arbitrary SQL or code execution paths for agents.

## Commands (run from `apps/api`)
```bash
uv sync                                   # install
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict
uv run lint-imports                       # module boundaries
uv run python -m agentree.core.db_roles   # once per DB: AGENTREE_ADMIN_DATABASE_URL, AGENTREE_APP_DB_PASSWORD, AGENTREE_MIGRATOR_DB_PASSWORD
uv run alembic upgrade head               # needs AGENTREE_MIGRATION_DATABASE_URL (agentree_migrator)
uv run pytest                             # needs AGENTREE_TEST_DATABASE_URL (superuser on a test server)
uv run uvicorn agentree.main:create_app --factory --reload
```
In the Claude Code cloud container: `service postgresql start`, then use
`postgresql+asyncpg://postgres:postgres@localhost:5432/postgres` as the test URL (set the password once with `ALTER USER`).
Dev stack: `docker compose -f infra/docker-compose.yml up --build`.
Note: DB roles are cluster-wide. The test harness re-bootstraps `agentree_app`/`agentree_migrator` with test passwords, so a local dev database on the same cluster must use those passwords (or a separate cluster).

## Tests
- DB tests run against real PostgreSQL (no DB mocking). Use the `db_session` fixture (rolled back per test).
- Business-scoped endpoints (`/api/businesses/{business_id}/...`) are auto-covered by `tests/test_isolation_matrix.py`; new path params need a real B-owned value there. Other tenant-scoped endpoints need explicit isolation tests.
- Use `tests/helpers.py` (`signup`, `create_business`, `invite_and_join`) and the `harness` fixture (fake mailer, one client per user).
- LLM behaviour is tested with the scripted fake provider (to be introduced), never live keys in automated tests.

## Migrations
- Alembic, one revision per change, readable names, both `upgrade` and `downgrade` (or a documented repair path).
- Backward-compatible (expand → migrate → contract). CI runs upgrade → downgrade → upgrade.

## Definition of Done
Feature branch · lint/format/types/boundaries/tests passing in CI with results quoted · isolation coverage for tenant endpoints · migrations round-trip · no secrets or message content in logs · docs updated · honest completion report · Product Owner approval before merge.
