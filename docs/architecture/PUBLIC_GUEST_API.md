# Public page, widget and guest sessions — API notes (Task 09a)

Status: backend implemented (Task 09a, merged). Web UI (public page, `/widget.js`, `/w/{slug}` iframe with CSP `frame-ancestors`) in Task 09b.
Related: PC-02, TD-12, TD-17, AGT-008 (this is the *guest* stage only — no provisional profile or OTP yet), AGT-010.

## Endpoints

All error bodies are FastAPI's `{"detail": <string>}`.

### Owner (dashboard, session cookie)
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/businesses/{business_id}/public-profile` | Member+ | Defaults when never saved (`enabled: false`). |
| PUT | `/api/businesses/{business_id}/public-profile` | Admin+ | Full replacement; omitted fields reset to defaults. 403 `insufficient_role`; 422 (schema), `invalid_widget_origin`, `invalid_link`. |

Body: `{enabled, display_name?: ≤80 | null, bio?: ≤500, links?: [{label 1..60, url https:// ≤500, description? ≤160 (one line)}] ≤10, widget_origins?: [string] ≤10, daily_reply_budget?: 1..5000 (default 200)}` — unknown fields rejected.
Response: the same fields plus `slug` and `updated_at` (null until first save).
Origins: exact `https://host[:port]`, DNS names only, lowercased, `:443` dropped, duplicates removed; no path/query/fragment/credentials/wildcards/IP literals. `http://localhost:<port>` only when `AGENTREE_ENVIRONMENT` is `dev`/`test`. Values are safe to place in a CSP `frame-ancestors` header.

### Public (no login)
| Method | Path | Auth | Success | Errors |
|---|---|---|---|---|
| GET | `/api/public/{slug}` | — | 200 `{slug, display_name, bio, links, chat_enabled: true}` | 404 `not_found` |
| GET | `/api/public/{slug}/widget-config` | — | 200 `{widget_origins}` | 404 |
| POST | `/api/public/{slug}/sessions` | — (same-origin POST) | 201 `{token, expires_at}` | 404, 429 `busy`, 403 `origin_not_allowed` |
| POST | `/api/public/{slug}/chat` | `X-Agentree-Guest: <token>` | 200 `{conversation_id, reply}` | 404, 401 `guest_session_invalid`, 422, 429 `busy`, 503 `agent_unavailable`, 403 `origin_not_allowed` |
| GET | `/api/public/{slug}/conversations/{conversation_id}/messages` | `X-Agentree-Guest` | 200 `[{role, content, created_at}]` | 404, 401 |
| POST | `/api/public/{slug}/conversations/{conversation_id}/resolve` | `X-Agentree-Guest` | 200 `{status, messages, can_resolve}` — Customer Service conversations only (Task 15, `INBOX.md`) | 403 `resolve_not_allowed`, 409 `conversation_state`, 404, 401, 429 |

Chat body: `{message: 1..1000 chars (not blank), conversation_id?: uuid, channel?: "public" | "widget" (default "public")}`; unknown fields rejected. Omit `conversation_id` to start a conversation; the channel is fixed when the conversation is created.

Rules:
- Unknown slug, disabled page and never-configured page give the same 404 on every public route (checked first).
- 401 is the same for missing, malformed, unknown, expired and other-business tokens. A conversation that is not this session's (other guest, console, other business, unknown id) is 404.
- `display_name` falls back to the business name.
- Responses never contain provider, model, key slot, knowledge sources/ids or internal ids other than `conversation_id`.
- Every AI-side failure (no provider configured, provider outage/quota/auth/bad request, vault unavailable) is 503 `agent_unavailable`; owners see provider health in the dashboard.

## Limits (TD-12, Postgres fixed windows)
| Limit | Value | Key |
|---|---|---|
| Session creation per client IP | 20 / hour | IP from `core.client_ip` with `AGENTREE_TRUSTED_PROXY_COUNT` |
| Session creation per business | 500 / day | business |
| Chat per session | 20 / 10 min and 100 / day | guest session |
| Chat per client IP | 60 / hour | IP |
| Chat per business | `daily_reply_budget` per UTC day | business + date |

All return 429 `busy`. The business budget is consumed before the AI call (a failed AI call still counts).

## Guest sessions
- Token: `secrets.token_urlsafe(32)` (256 bits), returned once; only SHA-256 stored (`guest_sessions.token_hash`). Fixed 30-day lifetime; `last_seen_at` updated on each chat.
- Sent in the dedicated `X-Agentree-Guest` header (not a cookie, not `Authorization`): the widget iframe is third-party context where cookies are unreliable, a header keeps the token out of URLs and access logs, and `Authorization` must stay free for HTTP basic auth of a gate in front of the app (the staging gate broke Bearer tokens).
- Retention: stale sessions are deleted by the retention purge once none of their conversations remain (see `TENANCY.md`).

## CSRF / framing
- The existing Origin check applies to public POSTs: they must come from our own web origin (the public page, or the widget iframe served by us). A customer's site cannot call the API directly — it embeds our iframe (TD-17).
- The web app must set `Content-Security-Policy: frame-ancestors <widget_origins>` on the widget iframe page using `/widget-config` (web PR).

## Bot challenge (Task 22, U-16)
- `POST /sessions` takes `{"challenge": "<Cloudflare Turnstile token>"}`. When
  `AGENTREE_TURNSTILE_SITE_KEY` and `AGENTREE_TURNSTILE_SECRET_KEY` are set, the token is verified
  server-side (`agentree/core/botcheck.py`) and accepted only when Cloudflare says it is valid,
  was solved on our host (`public_base_url`) and for the `guest_session` action.
- Order: per-IP session limit, then the challenge, then the per-business daily limit, so unsolved
  requests cannot use up a business's sessions and every call to Cloudflare is rate limited.
- Missing or bad token: 403 `challenge_failed`. Cloudflare unreachable: 429 `busy` (fail
  closed; existing sessions keep working). Tokens and the secret are never logged.
- `GET /api/public/{slug}` returns `challenge_site_key` (public). The page and the widget load
  Turnstile only when it is set, with `appearance: interaction-only`, so most visitors see
  nothing. Only opening a session is challenged; chat turns stay under the session limits.
- Required in production (startup refuses without both keys); optional in staging and dev.

## Not in this slice
Provisional customer profile / email OTP (3.4), streaming, lead capture, human handoff, custom domains (excluded from MVP).

## Leads (Task 11)
`POST /chat` may return `lead_suggestion` (prefill only, from details the visitor wrote).
`POST /leads` records the visitor's confirmed details with explicit consent; see `LEADS.md`.
