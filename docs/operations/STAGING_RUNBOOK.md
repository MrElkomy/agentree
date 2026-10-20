# Staging runbook: tryagentree.com on the shared Hetzner CX23

Status: **prepared, not deployed.** Every step that changes the live server is run by the
Product Owner (PO) after approval. Supersedes the topology in `STAGING_DEPLOYMENT_PROPOSAL.md`
(PR #9): we reuse the existing server and its host-level Caddy instead of a new VM.

## Decisions (PO, 2026-10-20)
- Staging runs on the existing CX23 (2 vCPU, 4 GB RAM, 38 GB NVMe) next to TRACK, IELTS,
  the Telegram bridge and video rendering. If measurements show it is tight, the same server
  is upgraded in place (more CPU/RAM). An upgrade adds capacity, **not isolation**.
- Synthetic test data only, and a dedicated low-budget demo AI key.
- The demo is served on the main domain `tryagentree.com` (`www` redirects to it), not a
  subdomain. When production launches, it takes the main domain and staging moves to a
  subdomain: only `AGENTREE_PUBLIC_HOST` and the Caddy site address change.
- No existing service is modified. The only shared touch point is one new Caddy site block.

## As deployed (2026-10-20): what is actually live
The steps below were run by the PO, one at a time. Where this section and the step list
differ, this section is current.

- **Live:** `https://tryagentree.com` (`www` redirects to it), behind a Caddy basic-auth
  gate (user `demo`), with Let's Encrypt certificates. The Caddyfile backup is
  `/etc/caddy/Caddyfile.bak-20261020`.
- **AI:** a Groq free-tier key (`openai/gpt-oss-120b`) as the primary. Google AI Studio
  `AQ.` keys are rejected by Google's REST API, which is why Groq was added (ADR-002
  addendum).
- **Email:** Brevo SMTP. The domain `tryagentree.com` is authenticated (brevo-code, 2 DKIM
  CNAMEs). The existing `_dmarc` record was edited to add `rua`, not duplicated.
- **Measured on the server:** the Agentree stack uses about 190 MB at idle, and about
  2.5 GB RAM stays available. TRACK and IELTS were unaffected, including across a reboot
  (kernel 7.0.0-38).
- **Backups:**
  - Encrypted with `age`.
  - The cron line runs every hour and acts only at **03:00 America/New_York**, so DST is
    handled.
  - Each backup is copied to Google Drive (`agentree-gdrive:Agentree Server Backups`). The
    rclone remote uses the PO's own account with **`drive.file` scope**, so it can only see
    the files it created.
  - Local copies: newest 7. Drive copies: deleted after 30 days.
  - The restore drill passed on 2026-10-20.
  - The TRACK service account cannot upload: "Service Accounts do not have storage quota".
- **Backup identity:** kept on the server at `~/agentree-secrets/backup-identity.txt`
  (mode 600) by PO decision, plus offline copies with the PO. See the security review below.
- **Cron line** (user `me`):
  ```
  0 * * * * [ "$(TZ=America/New_York date +\%H)" = "03" ] && AGENTREE_RCLONE_REMOTE="agentree-gdrive:Agentree Server Backups" $HOME/agentree/infra/staging/backup.sh nightly >> $HOME/agentree-backups/backup.log 2>&1
  ```
- **Update the demo:** `~/agentree/infra/staging/deploy.sh origin/main` (not between 14:45
  and 15:20 Cairo). Free build cache from time to time with `docker builder prune -f`.

## What gets added (nothing else changes)
| Item | Where | Notes |
|---|---|---|
| Repo checkout | `~/agentree` | `gh repo clone MrElkomy/agentree` (gh is already logged in) |
| Secrets | `~/agentree-secrets/` (mode 700) | `staging.env` (600), `backup-recipients.txt` (age public key), `deployed-tags` |
| Backups | `~/agentree-backups/` (700) | encrypted only, newest 7 kept |
| Measurements | `~/agentree-measurements/` | text snapshots from `measure.sh` |
| Docker project | `agentree-staging` | 5 containers (postgres, one-shot migrate, api, web, retention worker), volume `agentree-staging-pgdata` |
| Port | `127.0.0.1:3103` | loopback only (TRACK 3102, IELTS 3101) |
| Caddy | `tryagentree.com` block + `www` redirect | `infra/staging/Caddyfile.snippet` |
| Packages | `age` (+ `rclone` for off-server copies) | apt |
| Cron (user `me`) | nightly backup at 03:00 New York time | see "As deployed" |

Postgres and the API publish **no** host ports. Docker-published ports bypass UFW, so only the
web container is published, and only on 127.0.0.1; Caddy is the single public entry point.

## Resource estimates (to be replaced by measured numbers)
| | Idle (expected) | Hard cap (no swap) | CPU cap |
|---|---|---|---|
| postgres (64 MB shared_buffers, 40 conns) | 40–80 MB | 384 MB | 1.0 |
| api (uvicorn, 1 worker) | 110–170 MB | 384 MB | 1.0 |
| web (Next.js standalone, heap 192 MB) | 70–130 MB | 256 MB | 0.75 |
| worker (30-day retention, hourly pass) | 50–80 MB | 192 MB | 0.5 |
| migrate (runs at deploy, then exits) | — | 256 MB | 1.0 |
| **Total steady state** | **≈ 300–480 MB** | **1.2 GB** | |

- **Today:** ~2.7 GB available at idle and 761 MB of swap already in use. After deploy, expect
  ~2.3 GB available.
- **Image builds** (run on the server at `nice 10`): Next.js build peaks around 1–1.5 GB RAM
  and both cores for 2–4 minutes. Don't build during a render or between 14:45 and 15:20.
- **Disk:** images ~0.8–1.2 GB, build cache 1–2 GB, database < 100 MB. Today 25 GB is free.
- **Contention:** video renders peak at ~2 GB. Render + Agentree leaves only ~0.3 GB headroom,
  so **no rendering while the demo is being shown**. If that rule is too restrictive, upgrade
  the server (the CX33 tier has 8 GB).
- CI's "Staging stack smoke test" job prints real idle memory per container and image sizes
  for this exact compose file (first run, before the worker existed: web 35 MiB, api 69 MiB,
  postgres 28 MiB; images 0.9 GB). The server measurements are the numbers that count.

## Changes that need PO approval (applied by the PO, in this order)
1. **DNS (done 2026-10-20 at Spaceship):** `A @` and `A www` → the server IPv4 (no `AAAA`,
   matching the TRACK record). Caddy gets the TLS certificates automatically on first request
   (ports 80/443 are already open). Check the existing Caddyfile for a `tryagentree.com`/`www`
   block first: if there is one, replace it rather than adding a duplicate.
2. **SMTP (Brevo free tier, 300 emails/day):** create the account, add the sender domain
   `tryagentree.com`, and add the TXT/CNAME records Brevo shows (domain code, two DKIM
   CNAMEs). An existing `_dmarc` record is **edited** to add the `rua` tag, never duplicated
   (done 2026-10-20). If an SPF TXT record exists, merge into it; never add a second one. Create an SMTP key and type it only into
   `staging.env`.
3. **Packages:** `sudo apt install age rclone`.
4. **Caddy:** append the snippet, validate, reload (graceful: TRACK/IELTS keep serving).
5. **Cron:** one line in `me`'s crontab for the nightly backup.

## Exact steps
Run as `me` in Tabby. Lines marked (**approval**) change the server.

**0. Baseline measurement (read-only)**
```bash
gh repo clone MrElkomy/agentree ~/agentree        # (approval) new folder only
~/agentree/infra/staging/measure.sh baseline
ss -ltn | grep -E ':3103\b' || echo "3103 free"
caddy version
```
Send the output for review before continuing.

**1. Secrets (approval)**
```bash
mkdir -m 700 -p ~/agentree-secrets ~/agentree-backups
cp ~/agentree/infra/staging/staging.env.example ~/agentree-secrets/staging.env
chmod 600 ~/agentree-secrets/staging.env
for v in POSTGRES_ADMIN_PASSWORD AGENTREE_MIGRATOR_DB_PASSWORD AGENTREE_APP_DB_PASSWORD; do
  sed -i "s|^$v=.*|$v=$(openssl rand -hex 24)|" ~/agentree-secrets/staging.env
done
sed -i "s|^AGENTREE_MASTER_KEY=.*|AGENTREE_MASTER_KEY=$(openssl rand -base64 32)|" ~/agentree-secrets/staging.env
nano ~/agentree-secrets/staging.env               # fill SMTP username + key only
```
Master key custody: copy the `AGENTREE_MASTER_KEY` line into two offline places
(`MASTER_KEY.md`). Never paste it in chat, Telegram or GitHub. It is staging-only.

**2. Backup key (approval)**: generate on the server, move the private half off it:
```bash
age-keygen -o ~/agentree-backup-identity.txt      # prints the public key
age-keygen -y ~/agentree-backup-identity.txt > ~/agentree-secrets/backup-recipients.txt
```
Copy `~/agentree-backup-identity.txt` to your PC and a second offline place, then delete it
from the server yourself. Without it, backups cannot be decrypted.

**3. Off-server target (approval; choose one)**
| Option | Cost | Note |
|---|---|---|
| Google Drive via rclone (**recommended to start**) | free | you already use Drive; files are age-encrypted before upload |
| Backblaze B2 | free up to 10 GB | S3-style, more setup |
| Hetzner Storage Box BX11 | ≈ €3–4/month | same provider, simplest for later production |

For Drive: `rclone config` (remote name `gdrive`), then add
`AGENTREE_RCLONE_REMOTE=gdrive:Agentree/staging-backups` to the cron line below.

**4. First deploy (approval)**
```bash
~/agentree/infra/staging/deploy.sh origin/main
```
What it does: checks the commit is on `main` → measures → builds images at low priority →
migrates as `agentree_migrator` → starts api + web + the retention worker → health checks → measures again. Nothing
is public yet; it only answers on 127.0.0.1:3103.

**5. Caddy (approval)**
```bash
caddy hash-password                               # choose the demo gate password
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d)
sudo nano /etc/caddy/Caddyfile                    # append infra/staging/Caddyfile.snippet, fill user + hash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -sI https://track.tryagentree.com | head -1  # TRACK still 200
```

**6. Backups (approval)**
```bash
~/agentree/infra/staging/backup.sh first
crontab -e    # add:
# 30 3 * * * AGENTREE_RCLONE_REMOTE=gdrive:Agentree/staging-backups $HOME/agentree/infra/staging/backup.sh nightly >> $HOME/agentree-backups/backup.log 2>&1
```

**7. Restore drill (before calling staging ready)**: bring the identity file back temporarily:
```bash
~/agentree/infra/staging/restore-check.sh ~/agentree-backups/<latest>.dump.age <identity-file>
```
It restores into a scratch database, prints row counts, and drops the scratch database.
The live database is not touched. Delete the identity file from the server again afterwards.

**8. Demo setup (in the browser)**
1. Sign up with a test address.
2. Create a fictional business.
3. Add the **dedicated demo key** on AI Providers. Set a hard monthly budget on the provider's
   dashboard first (OpenAI project budget / Anthropic workspace spend limit).
4. Publish synthetic knowledge and chat. Demo mode is refused in staging, so replies are real.

**9. After measurement**: run `measure.sh demo` during a demo session and send the three
snapshots (baseline / after deploy / during demo) for the upgrade decision.

## Update and rollback
- Update: `deploy.sh origin/main`. A pre-deploy encrypted backup is taken automatically.
- Automatic rollback: if the new version fails health checks, the previous images are started
  again.
- Manual rollback: `deploy.sh <previous tag from ~/agentree-secrets/deployed-tags>` (images are
  still on disk, about 1 minute). Migrations are backward-compatible, so the database stays.

## Recovery
- **Bad data or broken migration:** restore the pre-deploy backup into the live database.
  This is destructive and done only with PO approval:
  ```bash
  cd ~/agentree && C="docker compose -p agentree-staging -f infra/staging/docker-compose.yml --env-file ~/agentree-secrets/staging.env"
  $C stop api web
  age -d -i <identity> <backup>.dump.age | $C exec -T postgres pg_restore -U postgres --clean --if-exists -d agentree
  $C up -d api web
  ```
- **Server lost:** new server → steps 0–6 with the **same** `AGENTREE_MASTER_KEY` (from the
  offline copy) → restore the latest off-server backup. Stored provider keys decrypt only
  with that master key.
- **Master key lost:** stored provider keys cannot be recovered. Re-enter them in the UI.
  Everything else in the database is unaffected.
- **Remove staging entirely (destructive, PO only):** remove the Caddy block and reload, then
  `$C down -v` (deletes the database volume), `docker image rm` the `agentree-*` images, and
  delete the three `~/agentree*` folders.

## Shared-host security review (required before real customers or production keys)
Acceptable for a demo with synthetic data and a capped demo key. Not acceptable for customer
data until reviewed and mitigated:
| Risk | Why it matters | Candidate mitigation |
|---|---|---|
| `me` is in the `docker` group (root-equivalent) and reads `staging.env` | anything running as `me` can read secrets or the DB | dedicated server, or a separate `agentree` user and rootless Docker |
| Claude Code and the Telegram bridge can run shell commands as `me` | a prompt-injection or bridge compromise reaches Agentree secrets | dedicated host; bridge on a separate user without docker access |
| Other client sites share the kernel and Docker daemon | a container escape in another site exposes Agentree | dedicated host |
| Secrets passed as container env vars | visible via `docker inspect` to docker-group users | Docker secrets / files read at startup |
| Master key on the same disk as the encrypted provider keys | disk or backup theft plus `staging.env` theft = key exposure | KMS or a separate secret host for production |
| Builds and renders compete for RAM | OOM or slow demo | memory caps (done), upgrade, or a separate host |
| Basic-auth demo gate shared with viewers | credential spreads | rotate after each demo round |
| Backup decryption key kept on the server (PO decision, 2026-10-20) | server compromise also exposes off-server backups | keep it only offline before real customers |
| Drive OAuth token (`drive.file`) in `~/.config/rclone/rclone.conf` | it can read/delete the backup files only | revoke under Google Account → Security → Third-party access if leaked |

## Not included yet
- Monitoring/alerting, and an uptime check on `/readyz` through Caddy.
