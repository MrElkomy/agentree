#!/usr/bin/env bash
# Restore drill: restores an encrypted backup into a SCRATCH database
# (agentree_restore_check), prints table row counts, then drops the scratch database.
# The live `agentree` database is never touched.
# Usage: restore-check.sh <backup.dump.age> <age-identity-file>
# shellcheck source=infra/staging/lib.sh
source "$(dirname "$0")/lib.sh"

backup="${1:?usage: restore-check.sh <backup.dump.age> <age-identity-file>}"
identity="${2:?usage: restore-check.sh <backup.dump.age> <age-identity-file>}"
require_env_file
scratch=agentree_restore_check

psql_admin() { compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 "$@"; }

psql_admin -c "DROP DATABASE IF EXISTS $scratch" -c "CREATE DATABASE $scratch"
trap 'psql_admin -c "DROP DATABASE IF EXISTS $scratch" >/dev/null' EXIT
age -d -i "$identity" "$backup" | compose exec -T postgres pg_restore -U postgres --no-owner -d "$scratch"
psql_admin -d "$scratch" -c "ANALYZE" >/dev/null
psql_admin -d "$scratch" -c "SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables ORDER BY relname"
psql_admin -d "$scratch" -c "SELECT version_num AS alembic_version FROM alembic_version"
echo "restore drill OK: $backup"
