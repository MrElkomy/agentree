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
- The backend is the only authority. Pages ask the API (`/api/auth/me`,
  `/api/businesses/{id}`) and redirect to `/login` on 401. Role checks in the UI only hide
  controls. The only Next.js proxy (`src/proxy.ts`, matcher `/w/:path*`) sets the widget
  iframe's framing header; it is not an authorization layer.
- Public pages (`/{slug}`, `/w/{slug}`) are server-rendered from the public API, read straight
  from `AGENTREE_API_URL` on the server (`src/lib/public-api.ts`), so that variable is also
  needed at runtime.

## Public page & widget
- Owners turn it on under **Public page & widget** in the business sidebar (Admin+ can edit;
  Members see it read-only). The page is off (visitors get "not found") until enabled.
- Public page: `{origin}/{slug}` — name, bio, links and a "Chat with our Sales Agent" panel.
- Website chat: paste `<script src="{origin}/widget.js" data-agentree="{slug}" async></script>`
  on a website listed under "Websites allowed to show the chat". The script adds a button that
  opens an iframe of `/w/{slug}`.
- Framing: every route sends `X-Frame-Options: DENY` except `/w/*`, which gets
  `Content-Security-Policy: frame-ancestors 'self' <allowed websites>` from
  `GET /api/public/{slug}/widget-config` (`'none'` on any failure).
- Visitors get a guest token per business in `localStorage` (`agentree:guest:{slug}`, in-memory
  fallback); it is sent as a bearer header, never a cookie or URL. Visitors never see provider or
  model details; replies say "You're chatting with an AI assistant."
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

Note: the backend rate-limits registration to 10 per IP per hour. Each full E2E run registers four
accounts, so repeated local runs against the same database may hit `rate_limited`; use a fresh
database (or clear `rate_limit_buckets` in your local test database).
