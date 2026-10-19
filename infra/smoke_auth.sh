#!/usr/bin/env bash
# End-to-end auth smoke test against the dev compose stack (API :8000, Mailpit :8025).
set -euo pipefail
API=http://127.0.0.1:8000
MAILPIT=http://127.0.0.1:8025
ORIGIN=http://localhost:3000
EMAIL="smoke-$(date +%s)@example.com"
PASSWORD="smoke test long passphrase"
JAR=$(mktemp)
post() { curl -fsS -b "$JAR" -c "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' -X POST "$API$1" -d "$2"; }

post /api/auth/register "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" >/dev/null
for _ in $(seq 1 20); do
  ID=$(curl -fsS "$MAILPIT/api/v1/search?query=to:$EMAIL" | jq -r '.messages[0].ID // empty')
  [ -n "$ID" ] && break; sleep 1
done
[ -n "${ID:-}" ] || { echo "verification email not delivered"; exit 1; }
TOKEN=$(curl -fsS "$MAILPIT/api/v1/message/$ID" | jq -r '.Text' | grep -o 'token=[A-Za-z0-9_-]*' | head -1 | cut -d= -f2)
post /api/auth/verify-email "{\"token\":\"$TOKEN\"}" >/dev/null
post /api/auth/login "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" >/dev/null
grep -q agentree_session "$JAR" || { echo "no session cookie"; exit 1; }
SLUG="smoke-$(date +%s)"
post /api/businesses "{\"name\":\"Smoke Co\",\"slug\":\"$SLUG\"}" | jq -e '.role == "owner"' >/dev/null
curl -fsS -b "$JAR" "$API/api/businesses" | jq -e "map(.slug) | index(\"$SLUG\") != null" >/dev/null
# CSRF: missing Origin is refused
code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/api/auth/logout")
[ "$code" = "403" ] || { echo "CSRF check failed: $code"; exit 1; }
post /api/auth/logout '{}' >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$API/api/auth/me")
[ "$code" = "401" ] || { echo "session not revoked: $code"; exit 1; }
echo "auth smoke test passed"
