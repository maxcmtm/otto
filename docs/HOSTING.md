# Otto hosting: where it runs, and how we control it

Decision draft, 2026-09-29. Max: "we need to decide where to host the whole system so we have access. I'll connect
a domain we buy, and everything should be convenient to control."

## Today

- Everything runs on the OpenClaw AWS box, inside Maximus' workspace
  (`/home/ubuntu/.openclaw/workspace-maximus/autopilot/platform`). Web files are copied into another project's web
  root (`/srv/pulse`) and served as `dash.monyflow.work/otto/` and `/pilot-landing.html`.
- Deploys happen by asking Maximus to `git pull && deploy.sh`. Crons are one line per client
  (`platform/crons.md`), so every new client means editing the crontab by hand.
- Auth for the app is Max's own gate (`mm-check`). There is no per-client login, no off-site backup, and no
  alert when a job fails.

That was right for building. It is wrong for paying customers: Otto shares a box and a domain with unrelated
projects, one person (or agent) holds every key, and a new client needs manual server work.

## Recommendation

**One dedicated Otto server in the EU, behind Cloudflare, deployed from GitHub.**

| Piece | Choice | Why | Cost (approx.) |
|---|---|---|---|
| Server | Hetzner Cloud CPX31 (4 vCPU, 8 GB, 160 GB), Nuremberg or Falkenstein | EU customers and GDPR (the price list is in euro for the EU); enough CPU/RAM for headless Chrome ad renders and HyperFrames video renders; Otto's engine is a single-box design (data.json + file locks) | ~€15/mo |
| Server backups | Hetzner automated backups (7 daily snapshots) | One-click restore of the whole box | +20% (~€3/mo) |
| Off-site backup | Hetzner Storage Box BX11 (or Backblaze B2), nightly encrypted archive of data.json, brands/, assets, logs | Survives losing the server or the Hetzner account | ~€4/mo |
| Domain, DNS, TLS, firewall | Cloudflare (buy the domain at Cloudflare Registrar, at cost) | DNS, certificates, WAF and rate limits for the public endpoints in one place, and Access for logins | Free plan + domain ~€10–15/yr |
| Logins | Cloudflare Access (free up to 50 users): `admin.` for the Otto team, `app.` for clients by email one-time code | Real logins without building auth now; the app learns who is signed in from the verified email header | Free |
| Code and deploys | GitHub (the existing private repo) + a GitHub Actions workflow: tests pass → deploy over SSH → health check → Telegram message; one command to roll back | No more "tell Maximus to pull and deploy"; every deploy is logged and reversible | Free |
| Agent runtime (copy, briefs) | OpenClaw installed on the Otto server as its own agent `autopilot-core` (the separation already planned in `platform/ARCHITECTURE.md`); Maximus stays on the old box as developer | Client work stops running inside a personal agent's workspace | Model usage only |

Total fixed cost: about **€25 a month** plus the domain.

Alternatives considered:
- **Stay on the current AWS box and point the new domain at it.** Fastest (an nginx server block and a certificate),
  but Otto keeps sharing a box and keys with unrelated projects, and nothing about control improves. Use it only as
  a stop-gap for launch week.
- **AWS Lightsail / EC2 for the dedicated server.** Same design, about 2–4 times the price for the same RAM. It only
  makes sense if we want everything on one AWS bill.
- **Render / Railway / Fly.** Poor fit today: Otto needs a persistent disk with file locks, cron jobs, headless Chrome
  and ffmpeg on the same machine.

## The domain layout

Placeholder `otto.example`, to be replaced with the domain we buy.

| Host | Serves | Access |
|---|---|---|
| `otto.example` | Landing page (`platform/landing.html`) and the public endpoints `/otto-peek`, `/otto-track`, `/otto-onboard`, `/hooks/whop` | Public, rate-limited at Cloudflare and in the API |
| `app.otto.example` | Client app (`index.html`), onboarding, approvals, `/otto-api/*` | Cloudflare Access, the client's email. Otto maps the email to the client's brand(s). |
| `admin.otto.example` | Owner console (`admin.html`) and admin API | Cloudflare Access, the Otto team only |
| `status.otto.example` (later) | Public uptime page | Public |

Mail: send-only for approvals and reports (Postmark or Resend) once we move approvals beyond Telegram. SPF, DKIM and
DMARC records sit in the same Cloudflare zone.

## On the server

- **Caddy** serves static files and reverse-proxies the API (Caddy renews certificates itself; with Cloudflare in
  front we use a Cloudflare origin certificate and "Full (strict)").
- **systemd** runs `otto-api` and the Telegram poller, and each engine job runs as a systemd timer. Timers replace
  cron lines, and `otto_cron.py <job>` runs a job for every active brand, so a new client needs no server change.
  Every run writes a heartbeat that the owner console shows, and a failed run sends a Telegram alert.
- The layout is `/opt/otto` (repo checkout), `/var/lib/otto` (data.json, brands/, assets, events, logs) and
  `/etc/otto/secrets` (0600, the `otto` user only). The OTTO_* env vars point the engine at these paths, so the code
  never writes into the checkout.
- Hardening: SSH keys only, a firewall allowing 22 (optionally from our IPs only), 80 and 443 (from Cloudflare only),
  unattended security upgrades, and fail2ban.

## Control, day to day

- **Deploy:** merge to `main`. The workflow tests, deploys, checks health and reports to Telegram.
  `infra/deploy.sh --rollback` goes back one release.
- **See everything:** the owner console at `admin.` shows traffic, leads, customers, MRR, clients, job heartbeats,
  failures and backups.
- **Stop everything:** the kill switch in the owner console pauses all publishing and ad launches at once.
- **Access:** add or remove people in Cloudflare Access; nobody shares a password.
- **Recover:** Hetzner snapshots for the box, the Storage Box for data, and `infra/restore.sh` to rebuild a fresh
  server from the latest backup.

## What Max does (about 15 minutes, all in his own accounts)

1. Buy the domain at Cloudflare Registrar, or move its nameservers to Cloudflare.
2. Create a Hetzner Cloud project, create a CPX31 (Ubuntu 24.04) with backups on, and add the SSH public key of whoever
   runs the bootstrap.
3. In Cloudflare Zero Trust, create two Access applications (`admin.` with the team's emails, `app.` with client
   emails as they sign up).
4. In GitHub, add the repository secrets for the deploy workflow (server host, deploy key, Telegram alert chat).

Everything after that is scripted in `infra/` (`bootstrap.sh`, `deploy.sh`, `backup.sh`, `restore.sh`, the Caddyfile,
the systemd units and the workflow). Nobody needs a password shared in chat: keys go into the accounts directly.

## Migration from the AWS box

1. Bootstrap the new server and restore the current `data.json`, `brands/` and assets from a backup of the old box.
2. Run it in parallel on the new domain for a day (publishing stays paused on the new box by the kill switch).
3. Cut over: pause the old box's timers, flip the kill switch off on the new one, and point the Telegram webhook and the
   Whop webhook at the new domain.
4. Keep the old box read-only for a week, then retire the Otto parts of it.
