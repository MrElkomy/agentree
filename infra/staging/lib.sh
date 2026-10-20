# shellcheck shell=bash disable=SC2034
# Shared settings for the staging scripts. Sourced, not executed.
# Override any of these in the environment before running a script.
set -euo pipefail

STAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$STAGING_DIR/../.." && pwd)"
SECRETS_DIR="${AGENTREE_SECRETS_DIR:-$HOME/agentree-secrets}"
ENV_FILE="${AGENTREE_ENV_FILE:-$SECRETS_DIR/staging.env}"
BACKUP_DIR="${AGENTREE_BACKUP_DIR:-$HOME/agentree-backups}"
MEASURE_DIR="${AGENTREE_MEASURE_DIR:-$HOME/agentree-measurements}"
# age public key(s) only; the private key stays offline with the Product Owner.
AGE_RECIPIENTS="${AGENTREE_AGE_RECIPIENTS:-$SECRETS_DIR/backup-recipients.txt}"
# Optional rclone remote for off-server copies, e.g. "gdrive:Agentree/staging-backups".
RCLONE_REMOTE="${AGENTREE_RCLONE_REMOTE:-}"
WEB_PORT="${AGENTREE_WEB_PORT:-3103}"

compose() {
  docker compose -p agentree-staging -f "$STAGING_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

die() { echo "error: $*" >&2; exit 1; }

require_env_file() {
  [ -f "$ENV_FILE" ] || die "secrets file not found: $ENV_FILE"
  local mode
  mode="$(stat -c '%a' "$ENV_FILE")"
  [ "$mode" = "600" ] || die "$ENV_FILE must be mode 600 (is $mode)"
}
