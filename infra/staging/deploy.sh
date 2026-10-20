#!/usr/bin/env bash
# Deploy (or roll back to) a commit that is already on origin/main.
# Usage: deploy.sh <git-ref>        e.g. deploy.sh origin/main   |   deploy.sh 2651c3f
#
# Steps: refuse a dirty tree or a commit not on main → measure → pre-deploy backup (if a
# database exists) → build images tagged with the commit → migrate → start api + web + worker →
# health checks → measure. If the new version is unhealthy, the previous images are
# started again (no data is changed by a rollback; migrations are backward-compatible).
# shellcheck source=infra/staging/lib.sh
source "$(dirname "$0")/lib.sh"

ref="${1:?usage: deploy.sh <git-ref on origin/main>}"
require_env_file
history="$SECRETS_DIR/deployed-tags"

cd "$REPO_DIR"
[ -z "$(git status --porcelain)" ] || die "working tree has local changes; refusing to deploy"
git fetch --quiet origin main
commit="$(git rev-parse --verify "$ref^{commit}")"
git merge-base --is-ancestor "$commit" origin/main || die "$ref is not on origin/main"
git checkout --quiet --detach "$commit"
tag="$(git rev-parse --short=12 HEAD)"
previous="$(tail -n 1 "$history" 2>/dev/null || true)"
export AGENTREE_IMAGE_TAG="$tag"

echo "deploying $tag (previous: ${previous:-none})"
"$STAGING_DIR/measure.sh" "before-$tag"

if [ -n "$(compose ps -q postgres 2>/dev/null)" ]; then
  "$STAGING_DIR/backup.sh" "pre-deploy-$tag"
fi

# Low priority so the other sites stay responsive during the build.
nice -n 10 docker compose -p agentree-staging -f "$STAGING_DIR/docker-compose.yml" \
  --env-file "$ENV_FILE" build

compose up -d postgres
compose run --rm migrate

healthy() {
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null -m 5 "http://127.0.0.1:$WEB_PORT/login" &&
       compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz')" 2>/dev/null; then
      return 0
    fi
    sleep 4
  done
  return 1
}

compose up -d api web worker
if healthy; then
  echo "$tag" >> "$history"
  echo "deployed $tag"
  "$STAGING_DIR/measure.sh" "after-$tag"
  exit 0
fi

echo "new version is unhealthy; recent logs:" >&2
compose logs --tail 50 api web >&2 || true
if [ -n "$previous" ]; then
  echo "rolling back to $previous" >&2
  AGENTREE_IMAGE_TAG="$previous" compose up -d api web worker
  AGENTREE_IMAGE_TAG="$previous" healthy && echo "rolled back to $previous" >&2
fi
exit 1
