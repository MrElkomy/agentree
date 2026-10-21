# Customer identity and memory (Task 16)

Returning customers shouldn't have to repeat themselves, and the business shouldn't keep more
than it needs. Code: `agentree/customers/` (models, service, extraction job, owner API),
migration 0017. PO decisions U-12 / U-13 (2026-10-21): nothing derived from a conversation is
kept beyond the 30-day raw window, there is no long-term review schedule, and the customer is
told in the chat.

## Identity

| State | How | What it unlocks |
|---|---|---|
| Anonymous guest | Guest session (public page / widget token) | Its own conversations only |
| Provisional profile | Created the first time memory is saved for a guest session | Nothing: agents never read provisional memory |
| Verified customer | The visitor enters a 6-digit code emailed to them, in the same guest session | Agents read this customer's memory, by role |

- **Typing an email unlocks nothing.** Neither the lead form nor `POST /identity/start` links
  anything; only `POST /identity/confirm` with the right code does.
- Codes: `secrets`, 6 digits, only the SHA-256 is stored, 10-minute expiry, 5 attempts, one
  use, a new code replaces the old one, bound to the guest session that asked. Wrong, expired,
  used and exhausted codes are one answer (422 `invalid_code`).
- Rate limits: 3 code emails per session per hour, 10 per IP per hour, 5 per email per business
  per day, 10 checks per session per 10 minutes (429 `busy`). `start` always answers
  `{"sent": true}`: it never reveals whether an email is known.
- One verified profile per (business, email); the same person at another business is a
  different customer. On verification, the session's provisional memory moves to the verified
  profile (the visitor proved it is theirs). "Not you?" (`DELETE /identity`) unlinks the
  browser; the memory stays with the customer.

Public endpoints (`/api/public/{slug}`, guest token): `GET /identity`, `POST /identity/start`
`{email}` → 202, `POST /identity/confirm` `{code}`, `DELETE /identity`. The public page reports
`retention_days`.

## Memory

`customer_memory_items`: `category`, `value` (≤120 characters checked in code, 200 in the DB),
`source_conversation_id` (set null when the conversation is purged), `created_at`,
`updated_at`, `expires_at`.

- **Categories** (allowlist, also a DB check): `interest`, `owned`, `issue`, `preference`,
  `constraint`. No free-form "remember everything".
- **Extraction** (worker, every `AGENTREE_MEMORY_INTERVAL_SECONDS`, default 300): public
  conversations idle for 10 minutes with new messages and at least 2 visitor messages are
  claimed once (SECURITY DEFINER `agentree_claim_memory_extractions`, ids only). The business's
  own key (BYOK, primary then backup, circuit breaker) proposes up to 5 items; the transcript is
  delimited untrusted data.
- **Validation in code** (`service.validate_fact`); anything else is dropped:
  - category in the allowlist; 3–120 characters, one line;
  - no email, URL or long digit run (phones, cards), no markers (`<<`, `>>`);
  - **never message text**: rejected if it shares 6 consecutive words with any message of
    the conversation, or (short items) is a whole phrase of one.
- **Expiry (U-12):** `expires_at` = the conversation's last message + retention window (never
  more than 30 days; DB check `expires_at <= created_at + 30 days`). A fact seen again is
  stored as a new row, so it follows the newest conversation. An owner's correction does not
  extend it. Max 30 items per customer (oldest dropped).
- **Retention purge** (`agentree_purge_customer_data`, with the conversation purge): expired
  items, profiles with no activity for the window (their memory and session links cascade),
  codes older than a day past expiry.

## What agents read

Only the verified customer behind the current guest session, only unexpired items, and only
the categories the answering agent's role allows (`agents/registry.py`, checked per agent and
per handoff hop):

| Role | Categories |
|---|---|
| Sales | interest, owned, preference, constraint |
| Customer Service | owned, issue, preference |
| Technical Support | owned, issue |
| Internal roles, dashboard test chat | none |

The items go into the delimited `TEAM_CONTEXT` block as "may be out of date, confirm before
relying on it". Memory never reaches a provisional session, a session that only typed an email,
another business, or the dashboard test chat.

## Owner review

`/api/businesses/{id}/customers`: list (members), detail with memory (members), `PATCH` and
`DELETE …/memory/{item_id}` and `DELETE /{customer_id}` (Owner/Admin). Edits pass the same
validation (no contact data). Audit: `customer.verified`, `customer.memory_updated`,
`customer.memory_deleted`, `customer.deleted`. Details are category or verified flag only:
never emails, codes or memory values. The dashboard page is **Customers**.

## The customer is told

The chat (public page and widget) always shows "Chats, and what {business}'s assistants remember
about you, are deleted after {retention_days} days", plus "Remember me next time" (email →
code) or "Remembered as m***@example.com · Not you?".

## Tests

`tests/test_customers.py`: code flow, typing an email unlocks nothing, code expiry, attempts,
replacement, session binding, rate limits, other businesses' tokens; extraction validation
(quotes, contact data, unknown categories, markers), provisional profile, claim once, short or
failed runs store nothing; agents read only verified memory and only their role's categories;
another device after verification; "Not you?"; no cross-business memory; owner edit/delete,
member read-only, audit without values; retention purge of expired items and idle customers;
the 30-day DB check; the worker process resolves every foreign key. Isolation matrix covers
`/customers/{customer_id}` and `/memory/{item_id}`. E2E: the last part of `e2e/support-agents.spec.ts` (email code, "Remember
me", Customers page; one test so the suite stays under the sign-up rate limit).

## Limits

- Email OTP only (no SMS); no customer self-service portal (out of scope).
- Extraction costs one small call per finished conversation on the business's own key.
- Extraction is not retried if the business's key fails at that moment.
