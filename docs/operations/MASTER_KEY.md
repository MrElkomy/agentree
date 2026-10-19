# BYOK master key: custody, backup and recovery

The master key (`AGENTREE_MASTER_KEY`) wraps every customer's AI provider key (ADR-002).
**Losing it makes every stored provider key unreadable** (customers must re-enter keys).
**Leaking it** lets anyone holding a database copy decrypt those keys.

## Rules
1. **Never commit a real master key** (production, staging, or any shared environment). The
   only key in the repository is the dev-only compose value, which is publicly known and
   must never be used elsewhere. CI runs gitleaks on full history; `.env*` files are
   git-ignored (`.env.example` holds names only).
2. One key per environment. Never reuse the dev key or copy production's key to staging.
3. Store the key only in the deployment secret store (environment / secret file readable by
   the API and worker processes), never in the database, logs, tickets, chat, or backups
   of the database.
4. Generate on a trusted machine:
   `uv run python -c "from agentree.core.vault import generate_master_key as g; print(g())"`

## Backup (before the first production deploy)
- Keep **two offline copies** of each environment's key, separate from database backups:
  e.g. an encrypted password-manager vault entry owned by the Product Owner and a sealed
  paper/USB copy in a different physical location.
- Record the key id (`AGENTREE_MASTER_KEY_ID`) and creation date next to each copy.
- Database backups and the master key must never be stored together: one without the other
  does not expose customer keys.

## Recovery
- **Server lost, key safe:** restore the database backup, set the same
  `AGENTREE_MASTER_KEY` / `AGENTREE_MASTER_KEY_ID` from the offline copy, start the API.
  Verify with `POST /api/businesses/{id}/ai-providers/{slot}/test` on a known business.
- **Key lost:** stored provider keys cannot be recovered (by design). Generate a new key,
  deploy it, and ask customers to re-enter their keys (the API answers
  `key_unreadable_reenter` for unreadable keys). Inform affected customers.

## Rotation (yearly, or immediately on suspected exposure)
1. Generate a new key; deploy it as `AGENTREE_MASTER_KEY` with a new `AGENTREE_MASTER_KEY_ID`.
2. Move the old key into `AGENTREE_PREVIOUS_MASTER_KEYS='{"<old id>": "<old key>"}'`.
3. Secrets re-wrap to the new key lazily on next use. After a re-wrap sweep (planned job) or
   once all keys show the new `master_key_id`, remove the old key and destroy its copies.
4. On suspected exposure, also ask customers to **rotate their provider keys** with the
   provider, because a leaked master key plus a database copy reveals them.

## Restore drill
Part of the Phase 7 launch gate: restore a backup into a scratch environment with the
offline key copy and confirm a stored key decrypts.
