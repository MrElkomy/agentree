# Task 22 — Security review (B2)

Code reviewed: `main` at `fef3a76`. Method: each area read end to end, from a real caller to the
database or the outside world; every finding was re-traced by hand before it was accepted.
Nothing here was tested against the live server.

## Summary

| ID | Finding | Severity | Status |
|---|---|---|---|
| SR-01 | Visitor-planted links/numbers count as "checked" in follow-up email drafts (spam/phishing from our mail domain, auto-sent under "always allow") | Medium | Fixed in Task 22c; unconfirmed recipients wait for a person (Task 22d) |
| SR-02 | A Member can make Admin-only changes through the Executive Assistant once an "always allow" rule exists | Medium | Fixed in Task 22c |
| SR-03 | Open redirect after sign-in: `/login?next=/%09/evil.example` (browsers drop the tab) | Low–Medium | Fixed in Task 22c |
| SR-04 | Per-IP limits count single IPv6 addresses, so one /64 rotates past them; business-wide counters can then be exhausted | Low (Medium before the bot challenge) | Fixed in Task 22c (/64 buckets) + bot challenge (Task 22b) |
| SR-05 | The test console accepted a visitor conversation id, so internal agents could reply into a thread the visitor reads | Low | Fixed in Task 22c |
| SR-06 | No request body size limit before multipart spooling (disk fill by a signed-up member) | Low | Fixed in Task 22c (app limit); proxy limit proposed (server change) |
| SR-07 | Prompt injection through visitor-typed lead fields can steer the Executive's proposals | Low (residual) | Mitigated by SR-02; see below |
| SR-08 | OTP email shows the business display name chosen by the account owner (low-volume branded phishing) | Info | Accepted: per-email/session/IP limits; revisit with the platform admin dashboard |
| SR-09 | No `script-src` Content-Security-Policy on the dashboard | Info | Proposed for later hardening (model output is rendered as text) |

No Critical or High findings.

## Findings

### SR-01 — Follow-up email drafts trusted visitor text (Medium)
- **Reproduce:** a visitor submits `POST /api/public/{slug}/leads` with any email address and a
  `need` containing `https://phish.example/login` and a phone number. 24 hours later the
  follow-up job drafts an email; `check_draft` accepted links and numbers found in `need` and
  `name`, so the draft was not flagged and, under "always allow", was sent automatically.
- **Root cause:** `leads/outreach.py` passed visitor-typed fields as verification sources.
- **Fix:** only the business's published knowledge and name back links and numbers. Anything
  else flags the draft, and flagged drafts always wait for a person.
- **Regression test:** `test_a_visitor_cannot_plant_links_or_numbers_in_an_auto_sent_email`.
- **PO decision 2026-10-23 (Task 22d):** automatic follow-up emails go only to addresses the
  visitor confirmed with the identity code; any other draft is flagged `unverified_recipient`
  and waits for a person. Test: `test_an_unconfirmed_address_always_waits_for_a_person`.

### SR-02 — Executive Assistant rules let a Member act as an Admin (Medium)
- **Reproduce:** an Admin chooses "Always allow" for `set_agent_enabled`. A Member opens the
  test chat with the Executive Assistant and asks it to turn agents off: it ran immediately,
  although `PUT /agents/{role}` requires Admin.
- **Root cause:** the console turn did not tell the Executive extension who was asking.
- **Fix:** `allow_rules` is true only for Owners and Admins; a Member's proposals always wait
  for approval (`approvals.request(use_rules=False)`).
- **Regression test:** `test_a_members_proposals_wait_even_under_a_rule`.

### SR-03 — Open redirect after sign-in (Low–Medium)
- **Reproduce:** `/login?next=/%09/evil.example/` passed `safeNext` (it only checked `//`
  and `/\`); the browser removes the tab and navigates to `//evil.example/` after sign-in.
- **Fix:** `safeNext` refuses control characters and backslashes and requires the parsed URL to
  stay on our origin.
- **Regression test:** E2E `sign-in never redirects to another site`.

### SR-04 — IPv6 rate-limit buckets (Low)
- **Root cause:** per-IP limits used the full IPv6 address.
- **Fix:** `rate_limit_bucket` counts IPv6 per /64 (IPv4-mapped addresses as IPv4), for all
  sign-in, sign-up, reset, guest session, chat, lead and identity limits.
- **Regression test:** `test_ipv6_rate_limits_count_the_64_network`.

### SR-05 — Console wrote into visitor conversations (Low)
- **Reproduce:** a member posts a public conversation id to `/agents/sales/console`; the agent's
  reply, including internal context, became visible to the visitor.
- **Fix:** the console only continues `console` conversations (404 otherwise).
- **Regression test:** `test_the_console_cannot_answer_into_a_visitor_conversation`.

### SR-06 — Request body size (Low)
- **Fix:** `BodyLimitMiddleware`: 1 MiB for every API body, 10 MB + overhead for knowledge file
  uploads, enforced from `Content-Length` and while chunked bodies stream in (413).
- **Server proposal (needs PO approval):** add `request_body { max_size 12MB }` to the Caddy
  site block as an outer limit.
- **Regression tests:** `tests/test_body_limit.py`.

### SR-07 — Prompt injection into the Executive (Low, residual)
Visitor-typed lead names and requests appear in the Executive's business state. An injected
instruction could make it propose an action. Proposals are typed, allowlisted, validated and
audited; after SR-02 only an Owner's or Admin's own chat can run them under a rule, and the worst
outcome is a reversible change (agent on/off, page on/off, lead status). Proposal for the PO:
keep, or require approval for every Executive proposal regardless of rules.

## Areas checked and found sound
- **Tenant isolation:** RLS on every tenant table; all 17 SECURITY DEFINER functions pin
  `search_path`, validate arguments and return ids/counts only; no TEMP/CREATE for the app role;
  every tenant query in `tenant_session` with an explicit `business_id` filter.
- **Guest API:** hashed guest tokens, ownership checked on messages, handoff, resolve and leads;
  OTP from `secrets`, constant-time compare, 5 attempts per code, per-email/session/IP limits.
- **Authentication:** `__Host-` HttpOnly Secure SameSite=Lax cookie; Origin/Referer CSRF check
  on every non-GET API call; hashed single-use expiring reset/verify tokens; reset revokes all
  sessions; login timing defence and limits; correct role checks on every mutating route.
- **Actions and approvals:** backend allowlist, approval-only actions refused by `claim()`,
  exactly-once execution by conditional update, parameter hash re-checked, approver role
  re-checked at execution.
- **SQL sandbox and uploads:** single SELECT, authorizer allowlist, no ATTACH, step and row
  limits, child process with memory/CPU limits; content-sniffed types, zip-bomb checks,
  defusedxml, downloads as attachments with a sandbox CSP.
- **BYOK:** envelope AES-GCM bound to the owner, keys never returned or logged, provider errors
  reduced to a classification.
- **Secrets and the public repository:** gitleaks over the full history: no leaks; no
  credentials in `infra/` or `docs/` (placeholders only); logs carry ids and error types only.
- **Web:** no `dangerouslySetInnerHTML`; model output rendered as text; `X-Frame-Options: DENY`
  except the widget, whose `frame-ancestors` comes from validated origins and fails closed.
