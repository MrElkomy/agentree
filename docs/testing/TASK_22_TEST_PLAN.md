# Task 22 — General Testing, Security Hardening & Pilot Readiness

Reference: the code on `main` at `fef3a76` (staging runs the same commit). Where a document and the
code disagree, the code is tested and the document is corrected.

Legend: **A** = automated (CI or scripted here) · **M** = needs the Product Owner (manual, staging,
real low-budget keys, real devices or a decision) · **S** = server change (PO approval first).

## Ground rules
- Staging stays behind its access gate, with synthetic data and low-budget demo keys only.
- No deploy, merge or server change without PO approval. One PR per defect group, each with a
  regression test and quoted evidence.
- Severity: **Critical** (cross-tenant data, key or secret exposure, unapproved action) ·
  **High** (auth/authz bypass, abuse that burns a customer's key, data loss) · **Medium**
  (defence-in-depth gap, reliability defect with workaround) · **Low** (polish, docs).
- Pilot readiness is not declared while any Critical or High finding is open.

## Batches

| # | Batch | Type | Depends on | Pass criteria |
|---|---|---|---|---|
| B1 | Automated baseline and test stability | A | — | All checks green; backend suite green on 8 consecutive local runs; the earlier intermittent failure found, explained and fixed (or shown not to reproduce, with evidence) |
| B2 | Security code review | A + review | — | Every area below checked; each finding has a reproduction, root cause, severity and a fix PR or an approved deferral |
| B3 | Bot challenge (U-16, Cloudflare Turnstile) | A | — | New guest sessions need a token verified server-side (our host + action); outage fails closed; unsolved requests cannot use up a business's daily sessions; required in production config |
| B4 | Scripted end-to-end journeys | A | B1 | Each journey below passes in Playwright against the local stack, desktop and mobile viewports |
| B5 | Reliability and workers | A + M | B1 | Worker loops, retries, provider outage, large-file memory inside the 384 MB api limit, all with evidence |
| B6 | Staging verification | M | B3, PO deploy | Checklist below done by the PO on staging, results recorded |
| B7 | Shared-host security review | review + S | B2 | Risks listed with mitigations; changes to the server proposed, applied only after PO approval |
| B8 | Release readiness | docs + M | B2–B7 | The four final gates in the roadmap (onboarding, privacy/terms, production readiness, pilot checks) have evidence |

### B1 — Automated baseline and stability (A)
- Backend: ruff, ruff format, mypy strict, import-linter (25 contracts), migration upgrade →
  downgrade → upgrade as `agentree_migrator`, `alembic check`, worker `--once`, full pytest on
  real PostgreSQL, repeated 8 times to catch order or timing dependent failures.
- Web: eslint, `tsc` strict, `next build`, the full Playwright suite (11 specs) on the local stack.
- Supply chain: gitleaks over full history, pip-audit, `npm audit --omit=dev`.

### B2 — Security review areas (A + review)
1. Cross-tenant isolation: RLS on every tenant table, `GLOBAL_TABLES` guard, SECURITY DEFINER
   functions (pinned `search_path`, argument checks, ids/counts only), every client-supplied id
   scoped by business, isolation matrix coverage of every business-scoped route.
2. Guest sessions: token ownership of conversations, identity OTP (attempts, expiry, reuse,
   enumeration), lead and handoff endpoints, `trusted_proxy_count` and forwarded-IP spoofing.
3. Authentication and authorization: cookie flags, CSRF on cookie-authenticated writes,
   verification and reset tokens (hashed, single use, expiry), login throttling and enumeration,
   role checks on every write, invitations.
4. Prompt injection and actions: model output cannot run an action without the gateway and its
   permissions; approvals cannot be bypassed or executed twice; the approver role is re-checked.
5. Uploads and the SQL sandbox: type sniffing, size and decompression limits (zip/XLSX bombs),
   isolated extraction, read-only SQLite with no `ATTACH`/extensions, time and row limits.
6. BYOK: envelope encryption, keys never returned, logged or echoed in provider errors.
7. Secrets and the public repository: full-history secret scan, staging hostnames and gate
   details in docs, logs free of message content.
8. Web: security headers and CSP, `frame-ancestors` for the widget, no unescaped model output,
   no open redirects.
9. Public abuse: per-IP, per-session and per-business limits, daily reply budget, bot challenge.
10. Backups, retention and deletion integrity: purge correctness, legal hold, backup window.

### B4 — End-to-end journeys (A)
Existing specs already cover auth and team, agents, inbox, leads, notifications, public page and
widget, reliability (failover banner), Sales and support agents. Added in Task 22:
1. **New business setup:** signup → verify email → business → AI key → knowledge entry → agents
   on → public page on → visitor chats.
2. **Visitor across agents:** Sales → Customer Service handoff with shared context → resolve.
3. **Lead → human:** visitor leaves details → lead in dashboard → handoff → member takes over,
   replies, assigns, resolves, hands back to the AI.
4. **Approvals:** follow-up email draft → approve once → sent exactly once; "always allow" → the
   next one runs at once; rule removed → approval needed again.
5. **Hours and pause:** outside hours the away message answers; pause with a fixed message.
6. **Data Analyst:** uploaded CSV/XLSX answers with computed numbers; another business cannot see
   the dataset.
7. **Executive Assistant:** proposal → approval → executed as the approver; report email numbers
   match the Analytics page.
8. **Two tenants:** a member of business A gets 404 for every business-B URL in the UI.
9. **Legal hold and retention:** held conversation survives the purge; released one is deleted.
10. **Mobile (390×844), RTL Arabic content, keyboard-only, axe accessibility scan** on the main
    dashboard pages, the public page and the widget.

### B5 — Reliability (A + M)
- Worker: every loop (retention, follow-ups, memory, metrics, approvals, reports, outage alerts)
  runs once without error and tolerates a DB restart.
- Notifications: SMTP failure does not fail the request; push "gone" subscriptions are removed.
- Provider outage: primary down → backup answers → breaker half-open → back to primary (fake
  providers, automated); the same with real low-budget keys on staging (**M**).
- Memory: a 5 MB/100k-row XLSX analysed inside a 384 MB container limit (A, local Docker).

### B6 — Staging checklist for the Product Owner (M, after deploy approval)
1. Signup with a real inbox, verification and reset emails arrive (not in spam).
2. Add a low-budget primary and backup key; revoke the primary at the provider → backup answers,
   the outage email/push arrives; restore → traffic returns to primary.
3. Public page and widget on tryagentree.com with the Turnstile staging keys.
4. Web Push on one Android phone and one iPhone (16.4+, added to Home Screen).
5. Arabic conversation end to end on a phone.
6. Scheduled report email arrives at 08:00 business time.

### B7 — Shared-host review (review + S)
Containers sharing the VPS with TRACK/IELTS/Telegram Bridge: Docker socket exposure, network
separation, published ports, resource limits, Postgres exposure, Caddy/TLS, backups location,
SSH and OS updates, log retention. Output: risks with mitigations; server changes only as
proposals until the PO approves.

### B8 — Release readiness (docs + M)
Hosting decision U-11, monitoring and actionable alerts, onboarding and BYOK setup guide, privacy
notice and terms (PO-approved text), encrypted off-server backups with a timed restore drill,
operator runbooks, pilot acceptance checklist, requirements tracking table, PO go/no-go.

## Results
Recorded per batch in `TASK_22_RESULTS.md`; security findings in `SECURITY_REVIEW.md`.
