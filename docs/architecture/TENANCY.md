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
3. `test_every_public_table_has_rls_enabled` fails if RLS is missing.
4. Add the new endpoints to the cross-tenant isolation matrix (when HTTP endpoints exist).

## Cross-tenant lookups
Only through narrow `SECURITY DEFINER` functions owned by the migrator, with pinned `search_path`, returning minimal data, `EXECUTE` revoked from PUBLIC and granted to `agentree_app`. Current: `agentree_resolve_business_slug(slug) → uuid` (public page routing). Membership listing for a user will follow the same pattern in slice 1.4.

## Known limits
- `businesses.slug` is globally unique, so a create attempt can reveal that a slug is taken (acceptable: slugs are public).
- Managed Postgres providers differ in role/ownership permissions; validate the bootstrap on the chosen host (Phase 7).
