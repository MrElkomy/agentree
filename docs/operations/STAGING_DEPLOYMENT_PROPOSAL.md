# Staging deployment proposal

Status: **Proposal — nothing purchased or deployed.** Prices are indicative (October 2026) and
must be re-checked on the provider's site before ordering.

## Goal
A private, browser-accessible staging environment where the Product Owner can run the real
Sales Agent demo with a customer-owned AI key (`docs/operations/DEMO_RUNBOOK.md`), deployed with
the same Docker Compose topology we already test in CI.

## Recommendation (lowest practical cost, no managed services)

| Item | Choice | Indicative cost / month |
|---|---|---|
| Server | **Hetzner Cloud CX22** — 2 vCPU, 4 GB RAM, 40 GB NVMe, 20 TB traffic, EU region (Nuremberg/Falkenstein) | ≈ €4–5 |
| Server backups | Hetzner automatic backups (7 daily images) | +20% of server ≈ €1 |
| Off-server DB backups | Nightly encrypted `pg_dump` to a **Hetzner Storage Box BX11** (1 TB) | ≈ €3–4 (optional for staging, required for production) |
| Domain | `staging.<your-domain>` (A record); domain itself if not owned | ≈ €1 (≈ €10–15/year) |
| TLS | Caddy + Let's Encrypt (automatic) | free |
| Email | SMTP free tier (e.g. Brevo / Resend free plan) for verification & invites | free at staging volume |
| Firewall | Hetzner Cloud Firewall | free |
| **Total** |  | **≈ €6–11 / month** |

Why: one small VM runs Postgres + API + Web + Caddy comfortably at staging load; Hetzner is the
cheapest reputable option with backups and a free firewall. EU region is fine for staging
(no real customer data). **Production** should move to a US location (Ashburn, VA / Hillsboro,
OR: CPX-series, roughly double) and is a separate decision (Phase 7).

If 4 GB proves tight during image builds, upgrade in place to CX32 (8 GB, ≈ €7–8) — a reboot,
no migration.

## Topology (Docker Compose on one VM)
```
Internet ─► Caddy :443 (TLS, HSTS, basic-auth gate for staging)
              ├─ /api/*  ─► api (FastAPI, agentree_app role)       ┐
              └─ /*      ─► web (Next.js, proxies /api same-origin) │ private Docker network
                              postgres (volume, not exposed)       ─┘
              migrate (one-shot: role bootstrap + alembic as agentree_migrator)
```
- Only ports 22 (SSH, key-only), 80 and 443 open (Hetzner firewall + ufw). Postgres and the API
  are not published to the host.
- Staging is **private**: Caddy basic-auth on the whole site + `X-Robots-Tag: noindex`, on top of
  Agentree's own login.
- Images are built on the server from a git tag (no paid registry). Each build is tagged with the
  commit SHA so the previous version stays available for rollback.
- New files needed (added in the deployment PR after approval, not now):
  `infra/Dockerfile.web`, `infra/staging/docker-compose.yml`, `infra/staging/Caddyfile`,
  `infra/staging/deploy.sh`, `infra/staging/backup.sh`.

## Configuration and secrets
- One file on the server: `/opt/agentree/.env.staging`, owner `root`, mode `600`. Never in git,
  never in GitHub Actions logs.
- `AGENTREE_ENVIRONMENT=staging` → the API **refuses to start** with insecure settings (non-Secure
  cookies, non-https origins, local/unauthenticated SMTP, missing master key, demo mode).
- **Master key:** generated on the server (`generate_master_key()`), never transmitted through
  chat/GitHub; two offline copies per `docs/operations/MASTER_KEY.md`; staging has its **own** key
  (never the dev key, never production's).
- Separate DB passwords for `postgres` (admin), `agentree_migrator`, `agentree_app`; the API only
  ever gets the `agentree_app` URL (startup guard enforces it).
- SSH: key-only, root login disabled, a `deploy` user in the `docker` group; automatic security
  updates (`unattended-upgrades`).

## PostgreSQL persistence and backups
- Data on a named Docker volume on the VM disk.
- **Nightly** `pg_dump -Fc`, encrypted with `age` (public key on server, private key offline with
  the PO), copied to the Storage Box; **7 daily + 4 weekly** retained (≤ 30 days, consistent with
  the 30-day raw-conversation policy).
- Hetzner server backups (daily disk images) as a second layer.
- **Restore drill** before calling staging "ready": restore last night's dump into a scratch DB and
  confirm a stored provider key decrypts with the master key.

## Deploy procedure (`deploy.sh <git-tag>`, run by the `deploy` user)
1. `git fetch --tags && git checkout <tag>` (only tags of commits merged to `main` with green CI).
2. Pre-deploy backup: `pg_dump` → local + Storage Box.
3. `docker compose build` (images tagged `<sha>`).
4. Run `migrate` (role bootstrap is idempotent; Alembic upgrade as migrator).
5. `docker compose up -d api web` → wait for `/readyz` = 200 and `/login` = 200 through Caddy.
6. On failure: automatic rollback (below) and exit non-zero.
Later (optional): a manual-approval GitHub Actions job that SSHes in and runs the same script;
it holds only an SSH deploy key, never application secrets.

## Rollback
- **Application:** `deploy.sh <previous-tag>` — previous images are still on disk, so this is a
  restart (≈ 1 minute).
- **Database:** migrations are expand/contract (backward-compatible), so the previous app version
  runs on the newer schema. For a destructive bug, restore the pre-deploy dump taken in step 2.

## What the PO needs to do (when approved)
1. Create a Hetzner Cloud account and the CX22 server (or give a scoped API token) — Claude never
   holds billing access.
2. Choose the domain/subdomain and point an A record to the server IP.
3. Create a free SMTP account and enter its credentials directly on the server (or share via a
   one-time secure channel — not chat/GitHub).
4. Generate and store the master key copies (Claude can guide, but the PO keeps the offline copies).

## Not covered yet (tracked separately)
Monitoring/alerting (Phase 6–7), production topology, trusted-proxy client IP for rate limits
(must be configured with Caddy in the deployment PR), and the open product requirements
(streaming, circuit breaker/recovery, 30-day retention job) — **retention must be implemented
before real customer conversations reach staging or production**.
