# agentree
Agentree — AI Workforce SaaS Platform

## Documentation

- Product (source of truth): [`docs/product/AGENTREE_MASTER_PROJECT_CONTEXT_V2.md`](docs/product/AGENTREE_MASTER_PROJECT_CONTEXT_V2.md)
- Supporting V1 docs: `docs/product/AGENTREE_ARCHITECTURE_BLUEPRINT_V1.md`, `docs/product/AGENTREE_CLAUDE_CODE_EXECUTION_PLAN_V1.md`
- Architecture review (Task 0, awaiting approval): `docs/architecture/`
  - `REPOSITORY_AUDIT.md`, `ARCHITECTURE_REVIEW.md`, `ARCHITECTURE_DECISIONS.md`, `MVP_IMPLEMENTATION_ROADMAP.md`, `TASK_01_SPEC.md`

## Status

Task 01 (engineering foundation) on branch `feat/task-01-foundation`: FastAPI skeleton, PostgreSQL + Alembic, health/readiness, redacted JSON logging, real-Postgres tests, Docker dev stack, CI. No product features yet.

## Quick start (backend)

```bash
cd apps/api
uv sync
export AGENTREE_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/agentree
uv run alembic upgrade head
uv run uvicorn agentree.main:create_app --factory --reload
```

Or the full dev stack: `docker compose -f infra/docker-compose.yml up --build`. See `CLAUDE.md` for engineering rules and test commands.
