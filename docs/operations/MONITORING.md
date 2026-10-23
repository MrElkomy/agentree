# Monitoring and alerts

## In place today
| Signal | Who is told | How |
|---|---|---|
| A business's AI key goes down / recovers | That business's Owners and Admins | Email + Web Push (worker, every 60 s; at most once per key per 6 h) |
| New lead, handoff request, visitor waiting 30 min, daily reply budget reached, approval needed | That business's Owners and Admins | Email (+ push where available) |
| API liveness / readiness | Docker healthchecks (`/healthz`, `/readyz`) | Container restarts on failure |
| LLM calls, breaker transitions, key health | Operator | `GET /api/internal/metrics` (token-protected, Prometheus text) |
| Retention job runs | Owners (Analytics page) and operator | `retention_runs` table, "last ran" on Analytics |
| Logs | Operator | JSON logs, 10 MB × 3 per container, no message content or secrets |
| Server load and disk | Operator | `infra/staging/measure.sh` before/after each deploy |

## Gaps before the first real customer (proposals — need PO approval)
1. **Nobody is paged when the whole site is down.** Proposal: a free external uptime check
   (e.g. UptimeRobot or Better Stack free plan) on `https://<host>/login` every 5 minutes,
   alerting the operator by email/Telegram. External service, no customer data.
2. **A stopped worker is silent** (no alerts, reports, retention). Proposal: the worker pings a
   free heartbeat monitor (e.g. healthchecks.io) after each pass; alert if it misses 15 minutes.
   Needs a small code change (`AGENTREE_WORKER_HEARTBEAT_URL`, a fixed operator URL).
3. **Backups can fail silently.** Proposal: the nightly backup cron pings a second heartbeat on
   success.
4. **Disk filling up** affects every app on the shared host. Proposal: a daily cron that emails
   the operator when the disk is over 80 %, and `docker builder prune -f` after deploys.
