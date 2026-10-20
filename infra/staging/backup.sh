#!/usr/bin/env bash
# Encrypted PostgreSQL backup. The plaintext dump never touches disk: pg_dump is piped
# straight into `age` with the PUBLIC key; only the offline private key can decrypt it.
# Keeps the 7 newest local files; if AGENTREE_RCLONE_REMOTE is set, copies off-server and
# removes remote copies older than 30 days (matches the 30-day retention policy).
# Usage: backup.sh [label]    (e.g. nightly / pre-deploy)
# shellcheck source=infra/staging/lib.sh
source "$(dirname "$0")/lib.sh"

label="${1:-manual}"
require_env_file
[ -s "$AGE_RECIPIENTS" ] || die "age recipients file missing: $AGE_RECIPIENTS"
command -v age >/dev/null || die "age is not installed (sudo apt install age)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
file="$BACKUP_DIR/agentree-staging-$(date -u +%Y%m%dT%H%M%SZ)-$label.dump.age"

compose exec -T postgres pg_dump -U postgres -Fc agentree | age -R "$AGE_RECIPIENTS" > "$file.partial"
[ -s "$file.partial" ] || die "backup is empty"
mv "$file.partial" "$file"
echo "backup written: $file ($(du -h "$file" | cut -f1))"

# Local rotation: only this script's own files, newest 7 kept.
find "$BACKUP_DIR" -maxdepth 1 -name 'agentree-staging-*.dump.age' -printf '%T@ %p\n' |
  sort -rn | tail -n +8 | cut -d' ' -f2- | xargs -r -d '\n' rm --

if [ -n "$RCLONE_REMOTE" ]; then
  rclone copy "$file" "$RCLONE_REMOTE"
  rclone delete --min-age 30d --include 'agentree-staging-*.dump.age' "$RCLONE_REMOTE"
  echo "copied off-server: $RCLONE_REMOTE"
else
  echo "warning: AGENTREE_RCLONE_REMOTE not set — backup is on this server only" >&2
fi
