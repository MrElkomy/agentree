# Task 22 — Shared-host security review (B7)

Staging runs on the same VPS as TRACK, IELTS and the Telegram Bridge. This review is based on
`infra/staging/` in the repository; items marked **check** need read-only commands on the
server, run by the Product Owner one at a time. **No server change is made without PO approval.**

## What is already in place
- Only the web container publishes a port, bound to `127.0.0.1:3103`; Postgres and the API are
  reachable only on the project's own Docker network.
- Caddy terminates TLS, sets `X-Forwarded-For` itself, adds HSTS and a basic-auth gate.
- Every container has memory and CPU limits and rotated logs (10 MB × 3); the API runs as a
  non-root user (uid 10001).
- The app connects as `agentree_app` (no superuser, no BYPASSRLS, refuses to start otherwise).
- Backups are encrypted with `age` before they touch disk; only the offline key decrypts them.

## Risks and proposed mitigations

| ID | Risk | Severity | Proposed mitigation | Needs |
|---|---|---|---|---|
| SH-01 | A compromise of any app on the host that reaches root or the Docker socket reads Agentree's database volume, secrets file and master key | High for production, accepted for staging (synthetic data) | **Production on its own server** (roadmap gate 3, U-11); keep staging synthetic-only | PO decision (U-11) |
| SH-02 | Containers keep default Linux capabilities and a writable root filesystem | Medium | `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]` on api, worker, web; `read_only: true` with a `tmpfs` for `/tmp` where the app allows it | Compose PR + PO-approved deploy |
| SH-03 | No proxy-level request size limit | Low | `request_body { max_size 12MB }` in the Caddy site block (the app now limits bodies too, Task 22c) | PO-approved Caddy reload |
| SH-04 | Who can use Docker on the host (`docker` group = root) | **check** | Only the deploy user and admins in the `docker` group | `getent group docker` |
| SH-05 | Secrets file permissions | **check** | `~/agentree-secrets/staging.env` owned by the deploy user, mode 600 | `stat -c '%U %a' ~/agentree-secrets/staging.env` |
| SH-06 | Backups only on the same server | **check** | `AGENTREE_RCLONE_REMOTE` set to an off-server bucket, plus a timed restore drill | `ls -la ~/agentree-backups` and the secrets file (`grep -c RCLONE`, no values) |
| SH-07 | SSH and OS patching | **check** | key-only SSH, no root login, unattended security upgrades | `sudo sshd -T \| grep -E 'passwordauth\|permitrootlogin'`, `systemctl is-enabled unattended-upgrades` |
| SH-08 | Exposed ports on the host | **check** | Only 22, 80, 443 public | `sudo ss -tlnp` |
| SH-09 | Disk filling up affects every app on the host (build cache, logs, backups) | Medium | Docker build cache pruned after deploys; disk alert at 80 % | PO approval for `docker builder prune -f` and a cron/alert |

## Before the first real customer
SH-01 is the deciding item: real customer API keys and conversations must not sit on a host
shared with other applications. Proposal: a separate small production server (or managed
container host) with only Agentree, decided under U-11 before onboarding.
