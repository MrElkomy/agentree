# Tenancy & Row-Level Security

Status: implemented in Task 02 (roadmap slice 1.1). Rules here are binding for all modules.

## Model
- **Roles** (`agentree/core/db_roles.py`, bootstrapped once per database by an administrator):
  - `agentree_migrator` — owns schema and tables; runs migrations only. Table owner, so not subject to RLS (tables are not `FORCE`d). No SUPERUSER/BYPASSRLS.
  - `agentree_app` — used by API and worker. No SUPERUSER, no BYPASSRLS, owns nothing, cannot create objects or `SET ROLE`. Gets DML on migrator-created tables via default privileges.
- **Startup guard:** the API refuses to start, and `/readyz` returns 503 `unsafe_role`, if its DB role is superuser, has BYPASSRLS, or owns tables.
- **Context:** `TenantContext(business_id, source)` is built only by trusted server code (membership resolution, validated public slug, job payload, provisioning). Never from a raw client id.
- **Policy:** every tenant table has RLS enabled with
  `USING/WITH CHECK (business_id = agentree_current_business_id())`.
  No context → NULL → no rows visible or writable (fail closed). Malformed context → error.

## Usage
```python
async with tenant_session(session_factory, ctx) as session:
    ...  # one transaction; context set with set_config(..., is_local => true)
```
- Context is transaction-local: dropped at commit/rollback; safe with pooling and transaction-mode poolers.
- Pool `reset` hook also `RESET`s `agentree.business_id`, so even a buggy session-level `SET` cannot leak to the next checkout (tested).
- Add an explicit `business_id` filter in queries anyway (defense in depth).
- **Worker:** one `tenant_session` per job, from the job's stored `business_id`. Never reuse a session across jobs/tenants.

## Adding a tenant table (checklist)
1. Column `business_id uuid NOT NULL REFERENCES businesses(id)`; composite FK `(business_id, x_id)` when referencing another tenant table.
2. In the migration: `for s in enable_tenant_rls("table"): op.execute(s)`; downgrade with `disable_tenant_rls`.
3. `test_every_public_table_has_rls_unless_explicitly_global` fails if RLS is missing.
4. Routes under `/api/businesses/{business_id}/...` are picked up automatically by `tests/test_isolation_matrix.py` (discovered from OpenAPI); give new path parameters a real B-owned value there.

## Cross-tenant lookups
Only through narrow `SECURITY DEFINER` functions owned by the migrator, with pinned `search_path`, returning minimal data, `EXECUTE` revoked from PUBLIC and granted to `agentree_app`:
- `agentree_resolve_business_slug(slug) → uuid` — public page routing.
- `agentree_membership_role(user, business) → role` — authorizes a business-scoped request *before* a TenantContext exists.
- `agentree_user_businesses(user)` — business switcher (id, name, slug, role).
- `agentree_claim_invitation(token_hash, user)` — atomic, single-use; checks the user's stored verified email matches the invitation.
- `agentree_purge_expired_conversations(cutoff, max_rows) → integer` — retention worker only (AGT-010): deletes, across all tenants, at most `max_rows` conversations (with their messages) whose last activity is before `cutoff` and that are not on `legal_hold`; then (since 0008) at most `max_rows` guest sessions whose `last_seen_at` is before `cutoff` **and that no longer own any conversation** (so a legal-hold conversation keeps its session, and the session→conversation cascade never deletes anything). Returns the total number of rows deleted (conversations + guest sessions), never content. Refuses cutoffs newer than one day and `max_rows` outside 1..10000; skips rows locked by an in-flight turn. Migration 0008's downgrade restores the 0006 definition exactly.

## Public page and guest sessions (Task 09a)
- Public requests (`/api/public/{slug}/...`) get their `TenantContext(business_id, PUBLIC)` only from `agentree_resolve_business_slug` **and** only while that business's `public_profiles.enabled` is true (checked under RLS in the resolved tenant). Unknown and disabled slugs are the same 404.
- `public_profiles` (PK `business_id`) and `guest_sessions` are tenant tables with RLS, owned by `agentree/public`.
- Guest tokens are opaque (`secrets.token_urlsafe(32)`); only the SHA-256 is stored. The token is looked up **inside the slug's tenant session**, so a token of business A is simply unknown under business B's context (RLS + explicit `business_id` filter) — no cross-tenant lookup function is needed.
- `conversations.guest_session_id` has a composite FK `(business_id, guest_session_id) → guest_sessions(business_id, id)`; a CHECK ties it to the channel (`console` ⇔ no guest session; `public`/`widget` ⇔ guest session). `agentree/agents` enforces that a guest only reaches conversations whose `guest_session_id` is its own session (else 404).

## Global tables
`rls.GLOBAL_TABLES` lists the only tables without tenant RLS (`users`, `user_sessions`, `auth_tokens`, `rate_limit_buckets`, `alembic_version`). A test fails if any other table lacks RLS. Adding to this list is a security decision: the table must hold no tenant data.

## Known limits
- `businesses.slug` is globally unique, so a create attempt can reveal that a slug is taken (acceptable: slugs are public).
- Managed Postgres providers differ in role/ownership permissions; validate the bootstrap on the chosen host (Phase 7).
