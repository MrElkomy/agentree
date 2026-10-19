# apps/web

Next.js (App Router, TypeScript strict, Tailwind CSS) dashboard for Agentree: sign up, email
verification, sign in, password reset, businesses, business switcher, members and invitations.

## How it talks to the API
- The browser only talks to the Next.js origin. `next.config.ts` rewrites `/api/*` to FastAPI at
  `AGENTREE_API_URL` (default `http://127.0.0.1:8000`), so the HttpOnly session cookie is
  first-party and never visible to JavaScript.
- All fetches use `credentials: "same-origin"`; the browser adds the `Origin` header the backend's
  CSRF check needs. The web origin must be listed in the backend's `AGENTREE_ALLOWED_ORIGINS`
  (dev: `http://localhost:3000`).
- The backend is the only authority. There is no Next.js middleware; pages ask the API
  (`/api/auth/me`, `/api/businesses/{id}`) and redirect to `/login` on 401. Role checks in the UI
  only hide controls.
- API types in `src/lib/api-types.ts` are generated: `npm run gen:api` renders the OpenAPI schema
  from `apps/api` offline (needs `uv`), or set `AGENTREE_OPENAPI_SOURCE` to a URL/file.

## Develop
```bash
npm ci
npm run dev            # http://localhost:3000, API expected on :8000
npm run lint && npm run typecheck && npm run build
```
Backend for local development: `docker compose -f infra/docker-compose.yml up --build` from the
repo root (postgres, migrations, api on :8000, Mailpit UI on http://localhost:8025).

## End-to-end tests (Playwright)
The suite (`e2e/`) drives the real stack: it signs up, reads verification and invitation links
from Mailpit's HTTP API (`MAILPIT_URL`, default `http://127.0.0.1:8025`), creates a business,
invites a second user who signs up and joins, and checks what a member can see.

```bash
docker compose -f infra/docker-compose.yml up -d --build   # from the repo root
npm run build
npx playwright install chromium   # once
npm run e2e                       # starts `npm run start` on :3000 unless already running
```
Environment knobs: `E2E_BASE_URL` (default `http://localhost:3000`; must match an allowed
origin), `PLAYWRIGHT_CHROMIUM_EXECUTABLE` (local override when a preinstalled Chromium doesn't
match the pinned Playwright version).

Without Docker: run PostgreSQL, bootstrap roles and migrate as described in the root `CLAUDE.md`,
run a Mailpit binary (`mailpit --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025`), and start the API
from `apps/api` with `AGENTREE_SESSION_COOKIE_SECURE=false`,
`AGENTREE_ALLOWED_ORIGINS='["http://localhost:3000"]'`, `AGENTREE_PUBLIC_BASE_URL=http://localhost:3000`,
`AGENTREE_SMTP_HOST=127.0.0.1`, `AGENTREE_SMTP_PORT=1025`.

Note: the backend rate-limits registration to 10 per IP per hour. Each full E2E run registers two
accounts, so repeated local runs against the same database may hit `rate_limited`; use a fresh
database (or clear `rate_limit_buckets` in your local test database).
