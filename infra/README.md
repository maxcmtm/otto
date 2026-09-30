# Otto on its own server — runbook

The design is `docs/HOSTING.md`. This is how to set it up and run it. `otto.example` stands for our domain everywhere.

| What | Where |
|---|---|
| Code (a git checkout, never written to by the engine) | `/opt/otto` |
| Data: data.json, brands/, assets/, public/ (served media), billing, leads, events, logs, heartbeats | `/var/lib/otto` |
| Settings / secrets / origin certificate | `/etc/otto/otto.env` · `/etc/otto/secrets/` (otto only) · `/etc/otto/tls/` |
| Web pages (published by each deploy) | `/srv/otto/{site,app,admin,static}` |
| Web server (Caddy; the config is `infra/Caddyfile`) | `otto.example` landing + public endpoints · `app.` client app · `admin.` owner console |
| Services | `otto-api`, `otto-telegram`, one timer per engine job (`otto-job-*`), `otto-backup`, `otto-cloudflare-ips` |

Jobs run on local clocks: a client's approval cards at 08:00 *its* time (`brands[].tz`), its visuals at 18:00, its paid report
at 07:35, and so on; the owner's morning report, recommendation cards and growth ledger at the owner's time (`OTTO_OWNER_TZ`
in otto.env). Summer/winter time needs nothing. The full table is in `platform/crons.md` (`otto jobs` on the server).

Everything reaches the server through Cloudflare; the firewall only lets Cloudflare in on 80/443. Logins are Cloudflare
Access (e-mail one-time code) — nobody shares a password, keys go straight into the accounts or onto the server.

## 1. First setup (about 15 minutes, in this order)

**On your computer**

1. Deploy key for GitHub Actions: `ssh-keygen -t ed25519 -N '' -C github-actions -f otto-deploy`
2. Backup key: `age-keygen -o otto-backup-key.txt` (install `age` first: `brew install age`). It prints the public key
   (`age1…`). Put `otto-backup-key.txt` in the password manager — it is the only way to open a backup; the server only
   ever gets the public key.

**Cloudflare**

3. Buy the domain in Cloudflare Registrar (or add the site and move its nameservers to Cloudflare).
4. SSL/TLS → Overview: **Full (strict)**. SSL/TLS → Edge Certificates: Always Use HTTPS **on**, minimum TLS 1.2.
5. SSL/TLS → Origin Server → **Create certificate**: hostnames `otto.example` and `*.otto.example`, 15 years. Keep the page
   open: the certificate and the private key are needed in step 11 (the key is shown only once).
6. Zero Trust → Access → Applications → **Add a self-hosted application**, twice:
   - `admin.otto.example` — policy "Allow", selector Emails = the Otto team.
   - `app.otto.example` — policy "Allow", Emails = the team, plus each client's e-mail as they sign up. The API only shows a
     signed-in e-mail the brands it is a member of (`brands[].members`; signing in and onboarding adds it). Owner-console
     users are `OTTO_ADMIN_USERS` in otto.env.
   Login method: One-time PIN. The bare `otto.example` must **not** be behind Access (landing, onboarding, webhooks).
7. Security → WAF → Rate limiting rules → one rule: when the host is `otto.example` and the path is one of `/otto-peek`,
   `/otto-track`, `/otto-onboard`, `/otto-api/onboard`, `/hooks/whop`, `/otto-email/act` → 20 requests per 10 seconds per IP
   → Block.
   (The API has its own limits too; this stops floods before they reach the server.)

**Hetzner**

8. Cloud Console → new project "Otto" → Security → SSH keys → add *your* public key.
9. Add server: Nuremberg or Falkenstein · Ubuntu 24.04 · **CPX31** · IPv4 + IPv6 · your SSH key · **Backups on** · name `otto-1`.
   Note its IPv4 and IPv6.
10. Cloudflare → DNS: `A` records `@`, `app`, `admin` → the IPv4, `AAAA` records → the IPv6, all **Proxied** (orange cloud).

**The server**

11. Copy the script over and run it (paste the contents of `otto-deploy.pub` into the quotes):
    ```sh
    scp infra/bootstrap.sh root@IPV4:
    ssh root@IPV4
    OTTO_DOMAIN=otto.example OTTO_REPO=git@github.com:maxcmtm/otto.git \
    OTTO_ADMIN_EMAILS=you@yourmail.com OTTO_DEPLOY_PUBKEY="ssh-ed25519 AAAA… github-actions" \
    bash bootstrap.sh
    ```
    It stops once and prints a key: GitHub → repo → Settings → **Deploy keys** → Add (read-only, "Allow write access" off).
    Run the same command again. Then paste the origin certificate from step 5 and run bootstrap a third time:
    ```sh
    nano /etc/otto/tls/origin.pem     # the "Origin Certificate" block
    nano /etc/otto/tls/origin.key     # the "Private Key" block
    bash /opt/otto/infra/bootstrap.sh
    ```
    At the end it prints what is still missing, plus the two values GitHub needs (`OTTO_HOST`, `OTTO_KNOWN_HOSTS`).
12. Secrets (all JSON, owner otto, mode 600 — create each with `sudo -u otto nano /etc/otto/secrets/<file>`):
    `telegram.json` `{"bot_token": "…", "owner_chat_id": "…"}` · `leonardo.json` `{"api_key": "…"}` · `elevenlabs.json` ·
    `whop.json` (docs/ADMIN.md) · `meta-<brand>.json` / `google-<brand>.json` per client (platform/crons.md) ·
    `email.json` (approval e-mails, docs/ADMIN.md: `link_secret`, `from`, SMTP host/port/user/pass with STARTTLS, or
    `"provider": "postmark" | "resend"` + `api_key`; until it exists every approval e-mail is written to
    `/var/lib/otto/outbox/` and the console says so). Then
    `systemctl start otto-telegram` and `otto alert-test` (a test alert must arrive in Telegram).
13. Backups — see section 5 (Storage Box + rclone, 5 minutes).

**GitHub**

14. Repo → Settings → Secrets and variables → Actions → New repository secret: `OTTO_HOST` (the IPv4), `OTTO_SSH_KEY` (the
    whole *private* file `otto-deploy`), `OTTO_KNOWN_HOSTS` (the line bootstrap printed), and for deploy messages
    `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`. Delete `otto-deploy` and `otto-deploy.pub` from your computer.
15. Actions → deploy → Run workflow (or push to `main`). A green run and a Telegram message mean deploys work.

**Whop**

16. Webhook URL: `https://otto.example/hooks/whop` (events and secret: docs/ADMIN.md). Checkout redirect after purchase:
    `https://otto.example/onboarding.html?site={custom field if any}` — the buyer lands on onboarding before having a login.

A new server starts with **publishing paused** (kill switch on). When all is ready: owner console → Kill switch → Resume,
or `otto resume`.

## 2. Moving from the old AWS box

1. Set up the new server as above. Publishing stays paused.
2. Before the move, write the old per-brand cron arguments into data.json (the new scheduler reads them from the brand):
   CMTM → `"countries": ["IL"]` and `"cron": {"ads_budget": 30}` (`python3 ap.py …` or the owner console).
3. Old box, in the repo checkout (after `git pull`): `bash infra/export-legacy.sh` → `~/otto-legacy-<time>.tar.gz`
   (data, brands, assets, secrets — unencrypted, so move it only over SSH and delete it afterwards).
4. `scp` it to the new server, then there: `otto restore /root/otto-legacy-<time>.tar.gz --migrate` — publishing paused,
   job timers and the Telegram poller off (so the two boxes never both send).
5. Check on the new domain for a day: `admin.` shows the clients, `app.` shows posts, `otto run publish --dry` and
   `otto run cards --dry` list the right brands.
6. Cut-over, in one sitting:
   - old box: `crontab -e` → comment out every Otto line; `systemctl --user disable --now otto-telegram` (only one poller
     may run per bot);
   - export again (step 3) and restore again with `--migrate` (brings over the last hours);
   - new box: `otto cutover` (timers + poller on), then resume publishing (owner console, or `otto resume`);
   - Whop: change the webhook URL to `https://otto.example/hooks/whop`. Telegram needs nothing (Otto polls, no webhook).
7. Leave the old box read-only for a week, then remove its Otto crons, nginx locations and `/srv/pulse/otto`.

## 3. Daily control

| Want to… | Do |
|---|---|
| Deploy | merge to `main` (tests → deploy → health check → Telegram). By hand: `otto deploy <sha>` |
| Roll back | Actions → deploy → Run workflow → tick **rollback**; or on the server `otto rollback` (toggles between the last two releases; further back: `otto deploy <sha>`) |
| See everything | `otto status` (services, timers, every job's last run, kill switch, release) · owner console → System |
| Logs | `otto logs api` · `otto logs telegram` · `otto logs <job>` (e.g. `otto logs publish -f`) · `otto logs backup` · raw: `journalctl -u otto-job@publish` · job output: `/var/lib/otto/<job>.log` |
| Run a job now | `otto run <job>` (every active client, now) · `otto run <job> --brand <id>` · what it would do: `otto run <job> --dry` · list: `otto jobs` |
| Stop everything | `otto pause "reason"` (kill switch: no publishing, no ad launches; ad guard keeps running) · `otto resume` |
| Stop one client | `otto pause-brand <id>` / `otto resume-brand <id>` (also pauses its live campaigns) |
| Backup now / restore | `otto backup` · `otto restore list` · `otto restore latest < otto-backup-key.txt` |
| Add a client | nothing on the server: once the brand is `active` in data.json every job picks it up |
| Client data after a plan ends | the `retention` job deletes a brand 90 days after its plan ended (owner notices 14 and 3 days before, a zip export in `/var/lib/otto/exports` kept 30 days, never in the backups). What it would do: `otto retention plan` · keep one (legal dispute): `otto retention hold <id>` · a client export on request: `otto retention export <id>` · bring one back: `otto retention restore <zip> --apply` |
| Media published before random names | once, after the move: `otto media-names` (dry: lists them), then `otto media-names --apply` |
| Change the server setup | edit `infra/`, merge, then `sudo bash /opt/otto/infra/bootstrap.sh` (deploy tells you when this is needed) |

## 4. When an alert fires

The Telegram alert names the unit and, for a job, which client failed and its last output line. The same unit alerts at most
once every 3 hours.

- **`otto-job@<job>` failed** — `otto logs <job>`. Usual causes: an expired Meta/Google token (update
  `/etc/otto/secrets/meta-<brand>.json`), Leonardo/ElevenLabs out of credit, a client's site down (competitors). Fix, then
  `otto run <job> --brand <id>` (a failed client is not retried by itself the same day, so nothing is sent twice).
  If it keeps failing for one client: `otto pause-brand <id>` and deal with it calmly.
- **`otto-api` failed** (it crashed 10 times in 5 minutes) — `otto logs api`. Right after a deploy? `otto rollback`.
- **`otto-telegram` failed** — `otto logs telegram`; a `409 Conflict` means another poller uses the same bot (the old box?).
- **`otto-backup` failed** — `otto logs backup`; can the server reach the Storage Box? `sudo -u otto rclone lsd storagebox:`
- **Deploy failed** (GitHub + Telegram): "tests failed" → nothing changed. "rolled back" → the old release is live and
  healthy; read the Actions log. "ROLLBACK FAILED" → SSH in now: `otto status`, `otto logs api`, then
  `otto deploy <last good sha>` (`otto release` shows it).
- **Something is being published that should not be** → `otto pause` first, investigate second.
- **Disk** → `df -h /`, `du -sh /var/lib/otto/*`. Job logs rotate weekly; `events.jsonl` has its own cap.

## 5. Backups and restore

Nightly at 01:30 UTC `infra/backup.sh` copies `/var/lib/otto` (data.json, billing and leads under their locks) plus
`/etc/otto` (including the secrets — `OTTO_BACKUP_SECRETS=0` in otto.env leaves them out), compresses it, encrypts it to
`/etc/otto/backup.pub` and uploads it. It keeps 14 daily and 8 weekly archives. Hetzner's own backups (7 daily snapshots of
the whole server) come on top.

Setup, once:
1. Hetzner → Storage Boxes → BX11 → Settings: SSH support **on**; note host `uNNNNN.your-storagebox.de` and user.
2. On the server: `echo 'age1…' > /etc/otto/backup.pub` (the public key from step 2 of the setup).
3. `sudo -u otto rclone config --config /etc/otto/secrets/rclone.conf` → new remote `storagebox`, type `sftp`, host
   as above, port `23`, user as above, the Storage Box password.
4. In `/etc/otto/otto.env` set `OTTO_BACKUP_REMOTE=storagebox:otto`, then `otto backup` and `otto logs backup` (look for "OK").

Restore: `otto restore list`, then `otto restore latest < otto-backup-key.txt` (or a name from the list). Services stop while
it runs; the current data is moved aside to `/var/lib/otto.before-restore-<time>`; publishing is paused afterwards until you
resume it. Lost the whole server: Hetzner → server → Backups → restore a snapshot; or a new server + bootstrap (section 1)
+ `otto restore latest`.

## 6. Reference

- **Caddy / TLS.** The origin certificate lives in `/etc/otto/tls/`. Fallback without it (Let's Encrypt): in Cloudflare turn
  *Always Use HTTPS* **off** (Caddy redirects to HTTPS itself and answers the certificate challenge on port 80, which
  Cloudflare passes through), keep the records proxied and Full (strict), then
  `OTTO_TLS=letsencrypt OTTO_ACME_EMAIL=you@yourmail.com bash /opt/otto/infra/bootstrap.sh`.
- **Trust.** Caddy drops any `X-Otto-User` / `X-Real-IP` / `X-Otto-Proxy-Key` a browser sends and sets all three itself:
  `X-Real-IP` = `CF-Connecting-IP` when the connection comes from Cloudflare's ranges (refreshed weekly with the firewall),
  else the peer address; `X-Otto-User` = Cloudflare Access's e-mail header, from Cloudflare only and only on `app.` /
  `admin.` (the apex never names a user); `X-Otto-Proxy-Key` = `OTTO_PROXY_KEY`, a random value bootstrap puts in both
  `/etc/otto/otto.env` and `/etc/otto/caddy.env` (the API believes a user name only next to it). `/otto-api/admin*` exists
  only on `admin.`, the Whop webhook only on the apex (`/hooks/whop`). Never set `OTTO_SINGLE_TENANT`, `OTTO_FALLBACK=full`
  or `OTTO_ADMIN_USERS=*` here — those are for the old single-login box (section 7); bootstrap warns if it finds them.
- **Owner console users**: `OTTO_ADMIN_USERS` in `/etc/otto/otto.env` (lower-case Access e-mails; then `systemctl restart otto-api`).
- **Pages**: the app page is published with its embedded data block emptied — the live data only ever comes from the API,
  per signed-in user.
- **Jobs and schedule**: `platform/crons.md` and `platform/otto_cron.py` (`otto jobs`). Heartbeats: `/var/lib/otto/heartbeats.json`.
- **Sudo rules** (`/etc/sudoers.d/otto`): the `deploy` user (GitHub's key, locked to `otto-deploy-gate`) may only run
  `deploy.sh` as otto; otto may only restart otto-api / otto-telegram and reload Caddy.
- **Scripts**: `bootstrap.sh` (server setup, idempotent) · `deploy.sh` · `backup.sh` · `restore.sh` · `export-legacy.sh`
  (old box) · `cloudflare-ips.sh` · `deploy-gate.sh` · `otto` (the CLI) · `otto_alert.py` · `systemd/` · `Caddyfile`.

## 7. Updating the current AWS box (until the cut-over)

The new API is fail-closed: behind a proxy it answers only a named, known user. The old box has one login (Max's mm-check
gate in nginx), so it must say so **before** its otto-api restarts on the new code — otherwise the dashboard gets 401 and
the owner console 403. For Maximus, on the old box:

```sh
cd /home/ubuntu/.openclaw/workspace-maximus/autopilot && git pull
mkdir -p ~/.config/systemd/user/otto-api.service.d
cat > ~/.config/systemd/user/otto-api.service.d/single-login.conf <<'EOF'
[Service]
# old box only: one login (mm-check) in front, so everyone signed in may see every brand and use the owner console
Environment=OTTO_SINGLE_TENANT=1
Environment=OTTO_ADMIN_USERS=*
EOF
systemctl --user daemon-reload
systemctl --user restart otto-api
systemctl --user show otto-api -p Environment        # must list both variables
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Real-IP: 127.0.0.1' http://127.0.0.1:8161/otto-api/data   # 200 (401 = not applied)
bash platform/deploy.sh                               # static pages, as before
```

Nothing else changes there: the crontab lines keep calling the scripts directly and the Telegram poller is untouched. The
nginx locations for `/otto-track` and `/otto-api/whop` are in `docs/ADMIN.md`. These two settings never go on the new server.
