#!/usr/bin/env bash
# Read-only resource snapshot of the shared host. Changes nothing.
# Usage: measure.sh [label]    (e.g. before / after / demo)
# shellcheck source=infra/staging/lib.sh
source "$(dirname "$0")/lib.sh"

label="${1:-snapshot}"
mkdir -p "$MEASURE_DIR"
out="$MEASURE_DIR/$(date +%Y%m%d-%H%M%S)-$label.txt"

{
  echo "## $label — $(date -Is)"
  echo "### uptime / load";        uptime
  echo "### cpu";                  nproc
  echo "### memory (MiB)";         free -m
  echo "### swap";                 swapon --show
  echo "### vmstat 1s x5";         vmstat 1 5
  echo "### disk /";               df -h /
  echo "### top processes by RSS"; ps -eo pid,comm,rss,%cpu --sort=-rss | head -12
  echo "### containers";           docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
  echo "### docker disk";          docker system df
  echo "### agentree volume";      docker volume inspect agentree-staging-pgdata --format '{{.Mountpoint}}' 2>/dev/null || echo "(not created)"
  echo "### services"
  for s in caddy docker; do printf '%s: %s\n' "$s" "$(systemctl is-active "$s" || true)"; done
  printf 'telegram-bridge (user): %s\n' "$(systemctl --user is-active telegram-bridge 2>/dev/null || true)"
  echo "### sites (HTTP status on loopback)"
  for p in 3101 3102 "$WEB_PORT"; do
    printf '127.0.0.1:%s -> %s\n' "$p" "$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$p/" || echo down)"
  done
} 2>&1 | tee "$out"

echo "saved: $out"
