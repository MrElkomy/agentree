# Audit log (Task 10a)

Append-only record of important changes in a business: who did what to which object, when.

## Storage
- Table `audit_events` (migration 0009): `id` (uuid7, time-ordered), `business_id`, `actor_user_id`
  (no foreign key, so the trail outlives the account), `action`, `target_type`, `target_id`,
  `details` (JSONB object, ≤ 4 KB), `created_at`.
- Tenant RLS enabled in the first migration. The app role (`agentree_app`) has **INSERT and SELECT
  only**: UPDATE, DELETE and TRUNCATE are revoked, so the application cannot rewrite or erase
  history. Rows are removed only with their business (`ON DELETE CASCADE`).
- `agentree.audit.service.record()` writes inside the caller's `tenant_session`, so an event
  commits or rolls back together with the change it describes.
- `details` keeps only allowlisted keys (`email, role, from_role, to_role, slot, provider, model,
  replaced, verified`) as scalars ≤ 200 chars. Passwords, API keys, key hints, tokens and message
  content are never recorded; unknown keys are dropped.

## Recorded actions
| Action | When | Details |
|---|---|---|
| `business.created` | business provisioned | — |
| `invitation.created` | invite sent | `email`, `role` |
| `invitation.revoked` | invite canceled | — |
| `member.joined` | invitation accepted (audited in the claim transaction) | `role` |
| `member.role_changed` | role actually changed | `from_role`, `to_role` |
| `member.removed` / `member.left` | removed by someone else / left | `role` |
| `provider_key.saved` | primary/backup key added or replaced | `slot`, `provider`, `model`, `replaced`, `verified` |
| `provider_key.removed` | key deleted | `slot` |

Later tasks add their own actions (leads, handoffs, approvals, executive actions, legal hold).
New detail keys must be added to `ALLOWED_DETAILS` deliberately.

## API and UI
- `GET /api/businesses/{business_id}/audit-events?before=<id>&limit=1..100` (default 50), newest
  first, keyset pagination via `next_before`. Owner and Admin only (members 403, non-members 404).
  Actor and user-target emails are resolved at read time; deleted accounts show as "former user".
- Dashboard page "Activity log" (`/b/{id}/activity`), shown in the nav to Owners and Admins.

## Known limits
- Events in the same millisecond are ordered by the random part of the uuid7.
- No export or SIEM forwarding yet (out of scope for Task 10).
