#!/usr/bin/env bash
# Otto server bootstrap: a fresh Ubuntu 24.04 (Hetzner Cloud) → a running Otto behind Cloudflare. Run as root.
# Idempotent: run it again whenever it says so (after adding the GitHub deploy key, after putting the Cloudflare origin
# certificate in place, after a release changed infra/systemd) — it only changes what differs and never touches data or
# secrets you created.
#
#   OTTO_DOMAIN=otto.example OTTO_REPO=git@github.com:maxcmtm/otto.git bash bootstrap.sh     # first run (script copied over)
#   bash /opt/otto/infra/bootstrap.sh                                                        # later runs (values remembered)
#
# Optional env (remembered in /etc/otto/bootstrap.env):
#   OTTO_ADMIN_EMAILS   owner-console users: comma list of Cloudflare Access e-mails → OTTO_ADMIN_USERS in otto.env
#   OTTO_BRANCH         branch for the first checkout (main)
#   OTTO_TLS            origin (default: Cloudflare origin certificate at /etc/otto/tls/origin.pem + origin.key)
#                       | letsencrypt (fallback, needs OTTO_ACME_EMAIL; keep the DNS records proxied)
#   OTTO_SSH_FROM       comma list of CIDRs allowed to SSH (default: anyone, rate-limited + fail2ban — GitHub Actions needs it)
# Not remembered:
#   OTTO_TIMERS         off → install the job timers but leave them (and the Telegram poller) off — migration; `otto timers on` later
#   OTTO_DEPLOY_PUBKEY  public half of the GitHub Actions deploy key ("ssh-ed25519 AAAA… github-actions") → ~deploy/.ssh
#
# Only official package sources are added (NodeSource, Google, Caddy's Cloudsmith repo), each with its own signing key.
# Nothing secret goes on this command line: tokens and keys go into /etc/otto/secrets/ by hand (infra/README.md).
set -euo pipefail

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '   WARNING: %s\n' "$*" >&2; }
die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
TODO=()
todo() { TODO+=("$*"); }
as_otto() { runuser -u otto -- env HOME=/home/otto GIT_SSH_COMMAND="ssh -o BatchMode=yes" "$@"; }

[[ $EUID -eq 0 ]] || die "run as root (sudo bash $0)"

# ------------------------------------------------------------------ settings (env wins, else remembered)
CONF=/etc/otto/bootstrap.env
KEEP=(OTTO_DOMAIN OTTO_REPO OTTO_BRANCH OTTO_TLS OTTO_ACME_EMAIL OTTO_SSH_FROM OTTO_ADMIN_EMAILS)
if [[ -r $CONF ]]; then
	while IFS='=' read -r k v; do
		[[ $k =~ ^OTTO_[A-Z_]+$ ]] || continue
		[[ -n ${!k:-} ]] || printf -v "$k" '%s' "$v"
	done <"$CONF"
fi
OTTO_BRANCH=${OTTO_BRANCH:-main}
OTTO_TLS=${OTTO_TLS:-origin}
OTTO_DOMAIN=$(printf '%s' "${OTTO_DOMAIN:-}" | tr 'A-Z' 'a-z')
[[ $OTTO_DOMAIN =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] ||
	die "set OTTO_DOMAIN to the bare domain, e.g. OTTO_DOMAIN=otto.example"
[[ ${OTTO_REPO:-} =~ ^(git@github\.com:|https://github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
	die "set OTTO_REPO, e.g. OTTO_REPO=git@github.com:maxcmtm/otto.git"
[[ $OTTO_TLS == origin || $OTTO_TLS == letsencrypt ]] || die "OTTO_TLS must be origin or letsencrypt"
[[ $OTTO_TLS == origin || ${OTTO_ACME_EMAIL:-} =~ ^[^@[:space:]]+@[^@[:space:]]+$ ]] || die "OTTO_TLS=letsencrypt needs OTTO_ACME_EMAIL"
[[ -z ${OTTO_BRANCH//[A-Za-z0-9._\/-]/} ]] || die "bad OTTO_BRANCH"

. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || warn "made for Ubuntu 24.04, this is ${PRETTY_NAME:-unknown} — continuing"
ARCH=$(dpkg --print-architecture)

install -d -m 0755 -o root -g root /etc/otto
umask 022
tmpconf=$(mktemp)
for k in "${KEEP[@]}"; do [[ -n ${!k:-} ]] && printf '%s=%s\n' "$k" "${!k}"; done >"$tmpconf"
install -m 0600 "$tmpconf" "$CONF"
rm -f "$tmpconf"

# ------------------------------------------------------------------ packages
say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends ca-certificates curl gnupg
install -d -m 0755 /etc/apt/keyrings
add_repo() {   # name, signing-key URL, sources line — official vendor repos only
	local kr=/etc/apt/keyrings/$1.gpg
	if [[ ! -s $kr ]]; then
		curl -fsSL --proto '=https' --tlsv1.2 "$2" | gpg --dearmor --yes -o "$kr"
		chmod 0644 "$kr"
	fi
	printf '%s\n' "$3" >"/etc/apt/sources.list.d/$1.list"
}
add_repo nodesource https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
	"deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main"
add_repo caddy https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
	"deb [signed-by=/etc/apt/keyrings/caddy.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main"
chrome=()
if [[ $ARCH == amd64 ]]; then
	# keep Google's package from rewriting this repo entry (it would duplicate it without signed-by)
	printf 'repo_add_once="false"\nrepo_reenable_on_distupgrade="false"\n' >/etc/default/google-chrome
	add_repo google-chrome https://dl.google.com/linux/linux_signing_key.pub \
		"deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main"
	chrome=(google-chrome-stable)
else
	warn "no Google Chrome for $ARCH — ad statics fall back to the ffmpeg renderer"
fi
apt-get update -q
apt-get install -y -q --no-install-recommends \
	git python3 python3-systemd ffmpeg rsync zstd age rclone ufw fail2ban unattended-upgrades logrotate sudo \
	fontconfig fonts-dejavu-core fonts-dejavu-extra fonts-noto-core fonts-noto-ui-core fonts-noto-mono fonts-noto-color-emoji \
	nodejs caddy "${chrome[@]}"
note "python $(python3 -c 'import sys; print(sys.version.split()[0])') · node $(node --version) · caddy $(caddy version | cut -d' ' -f1) · ffmpeg $(ffmpeg -version | head -n1 | cut -d' ' -f3)${chrome:+ · $(google-chrome-stable --version 2>/dev/null)}"
timedatectl set-timezone UTC 2>/dev/null || true
if [[ -z $(swapon --show --noheadings) && ! -e /swapfile ]]; then   # headless Chrome + ffmpeg peaks; 2 GB of swap as a cushion
	if fallocate -l 2G /swapfile && chmod 0600 /swapfile && mkswap -q /swapfile && swapon /swapfile; then
		grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
	else
		rm -f /swapfile
		warn "could not create a swap file"
	fi
fi

# ------------------------------------------------------------------ users + layout
say "users and directories"
id otto >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/otto --shell /bin/bash --user-group otto
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --user-group deploy
install -d -m 0700 -o otto -g otto /etc/otto/secrets
install -d -m 0750 -o root -g caddy /etc/otto/tls
install -d -m 0710 -o otto -g caddy /var/lib/otto              # caddy may only traverse (to public/), never list or read data
for d in brands assets locks tmp deploy; do install -d -m 0750 -o otto -g otto "/var/lib/otto/$d"; done
install -d -m 0755 -o otto -g otto /var/lib/otto/public /var/lib/otto/public/assets
install -d -m 0755 -o otto -g otto /srv/otto /srv/otto/site /srv/otto/app /srv/otto/admin /srv/otto/static
install -d -m 0750 -o otto -g otto /var/cache/otto
install -d -m 0755 -o otto -g otto /opt/otto
install -d -m 0755 /etc/caddy/otto.d /usr/local/lib/otto

ENVF=/etc/otto/otto.env
if [[ ! -f $ENVF ]]; then
	cat >"$ENVF" <<'EOF'
# /etc/otto/otto.env — the engine's environment (systemd EnvironmentFile for every Otto unit; deploy.sh and the `otto` CLI
# source it too). Written by infra/bootstrap.sh; re-running it only ADDS missing keys, it never changes a value you edited.
# Format: KEY=value, one per line, no quotes, no inline comments. This is production: never set single-tenant or development
# switches here (for example OTTO_ADMIN_USERS=* would open the owner console to anyone Cloudflare Access lets into admin.).
EOF
fi
chown root:otto "$ENVF"
chmod 0640 "$ENVF"
env_default() {   # KEY VALUE [comment] — appended only when KEY is not in the file yet
	grep -q "^$1=" "$ENVF" && return 0
	[[ -n ${3:-} ]] && printf '# %s\n' "$3" >>"$ENVF"
	printf '%s=%s\n' "$1" "$2" >>"$ENVF"
}
admins=$(printf '%s' "${OTTO_ADMIN_EMAILS:-}" | tr 'A-Z' 'a-z' | tr -d ' ')
env_default OTTO_DOMAIN "$OTTO_DOMAIN" "apex = landing + public endpoints; app. = client app; admin. = owner console"
env_default OTTO_DATA /var/lib/otto/data.json "engine state — everything below lives outside the checkout (/opt/otto)"
env_default OTTO_HTML /var/lib/otto/app-fallback.html \
	"on purpose a file that does not exist and is never served: the client app is multi-tenant, so ap.sync_fallback embeds nothing"
env_default OTTO_BRANDS /var/lib/otto/brands
env_default OTTO_ASSETS /var/lib/otto/assets
env_default OTTO_PUBLIC_ASSETS /var/lib/otto/public/assets "every generated image / reel is copied here; Caddy serves it as https://DOMAIN/assets/…"
env_default OTTO_PUBLIC_BASE "https://$OTTO_DOMAIN/"
env_default OTTO_SECRETS /etc/otto/secrets
env_default OTTO_EVENTS /var/lib/otto/events.jsonl
env_default OTTO_BILLING /var/lib/otto/billing.json
env_default OTTO_LEADS /var/lib/otto/leads.json
env_default OTTO_LEAD_RETENTION_DAYS 730 "scanned-domain leads are deleted after this many days without activity (Privacy Policy)"
env_default OTTO_EXPORTS /var/lib/otto/exports "brand exports (before a retention deletion, or on request): kept 30 days, not in the backups"
env_default OTTO_HEARTBEATS /var/lib/otto/heartbeats.json
env_default OTTO_LOCKS /var/lib/otto/locks
env_default OTTO_ALLOWED_ORIGINS "https://$OTTO_DOMAIN,https://app.$OTTO_DOMAIN,https://admin.$OTTO_DOMAIN"
env_default OTTO_ADMIN_USERS "${admins:-owner@example.invalid}" \
	"owner console users = the Cloudflare Access e-mails of the Otto team (comma list, lower case). Replace the placeholder."
env_default OTTO_PROXY_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
	"shared with Caddy (/etc/otto/caddy.env): the API believes X-Otto-User only on requests carrying this key. Random, per server."
env_default OTTO_OWNER_TZ Asia/Jerusalem "the owner's clock: owner jobs (metrics snapshot, recommendation cards, growth) run on it; brand jobs (the 07:35 morning report too) use brands[].tz"
[[ ${#chrome[@]} -gt 0 ]] && env_default OTTO_CHROME /usr/bin/google-chrome-stable
env_default OTTO_FONT /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
env_default OTTO_FONT_CACHE /var/cache/otto/fonts
env_default OTTO_RENDER_TMP /var/lib/otto/tmp/render
env_default OTTO_BACKUP_REMOTE "" "rclone remote:path for the nightly backup, e.g. storagebox:otto (remote defined in RCLONE_CONFIG)"
env_default OTTO_BACKUP_KEEP_DAILY 14
env_default OTTO_BACKUP_KEEP_WEEKLY 8
env_default OTTO_BACKUP_SECRETS 1 "1 = the encrypted backup also carries /etc/otto/secrets (needed to rebuild a server without re-connecting every client)"
env_default RCLONE_CONFIG /etc/otto/secrets/rclone.conf
env_default PYTHONUNBUFFERED 1
env_default LANG C.UTF-8
want_domain=$OTTO_DOMAIN
set -a
. "$ENVF"
set +a
file_domain=$(sed -n 's/^OTTO_DOMAIN=//p' "$ENVF" | tail -n1)
[[ $file_domain == "$want_domain" ]] || warn "otto.env has OTTO_DOMAIN=$file_domain; this run asked for $want_domain — edit OTTO_DOMAIN, OTTO_PUBLIC_BASE and OTTO_ALLOWED_ORIGINS in $ENVF by hand"
grep -q '^OTTO_ADMIN_USERS=owner@example.invalid' "$ENVF" &&
	todo "Owner console users: set OTTO_ADMIN_USERS in $ENVF to your Cloudflare Access e-mail(s), then: systemctl restart otto-api"
if grep -Eq '^OTTO_SINGLE_TENANT=(1|true|yes|on)|^OTTO_FALLBACK=(full|1|true|yes)|^OTTO_ADMIN_USERS=.*\*' "$ENVF"; then
	warn "otto.env sets a single-tenant / development switch (OTTO_SINGLE_TENANT, OTTO_FALLBACK=full or OTTO_ADMIN_USERS=*)"
	todo "Production: remove OTTO_SINGLE_TENANT / OTTO_FALLBACK=full / OTTO_ADMIN_USERS=* from $ENVF, then: systemctl restart otto-api"
fi
proxy_key=$(sed -n 's/^OTTO_PROXY_KEY=//p' "$ENVF" | tail -n1)
[[ ${#proxy_key} -ge 32 ]] || die "OTTO_PROXY_KEY in $ENVF is missing or too short"
# Caddy's environment (systemd reads it as root; the key never goes into a world-readable file)
(umask 077 && printf 'OTTO_DOMAIN=%s\nOTTO_PROXY_KEY=%s\n' "$file_domain" "$proxy_key" >/etc/otto/caddy.env.new)
chown root:root /etc/otto/caddy.env.new
chmod 0600 /etc/otto/caddy.env.new
mv -f /etc/otto/caddy.env.new /etc/otto/caddy.env

if [[ ! -f /var/lib/otto/data.json ]]; then
	# a new server starts with publishing paused: nothing goes out until someone resumes it in the owner console
	python3 - <<'PY'
import json
from datetime import datetime, timezone
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
d = {"generated": now, "brands": [], "posts": [], "recommendations": [], "campaigns": [], "connections": [],
     "controls": {"publishing_paused": {"at": now, "by": "bootstrap", "note": "new server — resume in the owner console when it is ready"}}}
open("/var/lib/otto/data.json", "w").write(json.dumps(d, indent=2) + "\n")
PY
	chown otto:otto /var/lib/otto/data.json
	chmod 0640 /var/lib/otto/data.json
	note "new data.json (empty, kill switch ON)"
fi

# ------------------------------------------------------------------ SSH, firewall, fail2ban, upgrades
say "hardening"
keys=0
for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do [[ -s $f ]] && grep -q '^[^#]' "$f" && keys=1; done
if (( keys )); then
	cat >/etc/ssh/sshd_config.d/10-otto.conf <<'EOF'
# Managed by infra/bootstrap.sh — keys only (sshd uses the first value it reads; 10- sorts before cloud-init's 50-).
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 4
X11Forwarding no
EOF
	if sshd -t; then systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true; else warn "sshd -t failed — SSH config not reloaded"; fi
else
	warn "no authorized SSH key found — password login left as it is (add a key, then re-run)"
fi

ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
if [[ -n ${OTTO_SSH_FROM:-} ]]; then
	IFS=',' read -r -a froms <<<"$OTTO_SSH_FROM"
	for c in "${froms[@]}"; do ufw allow proto tcp from "$c" to any port 22 comment otto-ssh >/dev/null; done
	ufw delete limit 22/tcp >/dev/null 2>&1 || true
	ufw delete allow 22/tcp >/dev/null 2>&1 || true
	ufw delete allow OpenSSH >/dev/null 2>&1 || true
else
	ufw limit 22/tcp comment otto-ssh >/dev/null
fi
for p in 80/tcp 443/tcp 'Nginx Full' 'WWW Full'; do ufw delete allow "$p" >/dev/null 2>&1 || true; done   # web: Cloudflare only
ufw --force enable >/dev/null
note "ufw on: SSH ${OTTO_SSH_FROM:-from anywhere (rate-limited)}; 80/443 from Cloudflare only (below)"

cat >/etc/fail2ban/jail.d/otto.local <<'EOF'
# Managed by infra/bootstrap.sh
[DEFAULT]
backend = systemd
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 || true
systemctl reload fail2ban >/dev/null 2>&1 || systemctl restart fail2ban || warn "fail2ban did not start"

cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat >/etc/apt/apt.conf.d/52otto-unattended-upgrades <<'EOF'
// Managed by infra/bootstrap.sh — security updates daily (Ubuntu's defaults) + Chrome, which renders pages; reboot at a quiet
// hour when an update needs it (timers with Persistent=true catch up after the reboot).
Unattended-Upgrade::Origins-Pattern { "o=Google LLC,a=stable"; };
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "00:40";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true

# ------------------------------------------------------------------ GitHub access for the server (read-only deploy key)
say "repository"
install -d -m 0700 -o otto -g otto /home/otto/.ssh
[[ -f /home/otto/.ssh/id_ed25519 ]] ||
	as_otto ssh-keygen -q -t ed25519 -N '' -C "otto@$(hostname) (read-only deploy key)" -f /home/otto/.ssh/id_ed25519
if [[ $OTTO_REPO == git@github.com:* ]] && ! grep -q '^github.com ' /home/otto/.ssh/known_hosts 2>/dev/null; then
	# GitHub's SSH host keys from its API over HTTPS (no trust-on-first-use)
	curl -fsSL --proto '=https' https://api.github.com/meta |
		python3 -c 'import json,sys; [print("github.com " + k) for k in json.load(sys.stdin)["ssh_keys"]]' >>/home/otto/.ssh/known_hosts
	chown otto:otto /home/otto/.ssh/known_hosts
	chmod 0644 /home/otto/.ssh/known_hosts
fi
if [[ ! -d /opt/otto/.git ]]; then
	if ! as_otto git ls-remote --heads "$OTTO_REPO" >/dev/null 2>&1; then
		cat <<EOF

== ONE STEP BEFORE THE REST: give this server read access to the repository
   GitHub → $OTTO_REPO → Settings → Deploy keys → Add deploy key
     Title:  otto server $(hostname)
     Key:    $(cat /home/otto/.ssh/id_ed25519.pub)
     "Allow write access": leave it OFF
   Then run this again:  bash $0
EOF
		exit 0
	fi
	as_otto git clone --quiet --branch "$OTTO_BRANCH" "$OTTO_REPO" /opt/otto
	note "cloned $OTTO_REPO ($OTTO_BRANCH) into /opt/otto"
fi
SRC=/opt/otto/infra
[[ -f $SRC/Caddyfile && -d $SRC/systemd ]] || die "$SRC is incomplete — is $OTTO_BRANCH the branch with infra/?"

# ------------------------------------------------------------------ root-owned tools (never run root code from the otto-writable checkout)
install -m 0755 -o root -g root "$SRC/cloudflare-ips.sh" /usr/local/sbin/otto-cloudflare-ips
install -m 0755 -o root -g root "$SRC/deploy-gate.sh" /usr/local/sbin/otto-deploy-gate
install -m 0755 -o root -g root "$SRC/otto" /usr/local/bin/otto
install -m 0644 -o root -g root "$SRC/otto_alert.py" /usr/local/lib/otto/otto_alert.py

# ------------------------------------------------------------------ Caddy
say "web (Caddy)"
/usr/local/sbin/otto-cloudflare-ips | sed 's/^/   /'
tls_snip=/etc/caddy/otto.d/tls.caddy
if [[ $OTTO_TLS == origin ]]; then
	printf '# Written by infra/bootstrap.sh (OTTO_TLS=origin)\n(otto_tls) {\n\ttls /etc/otto/tls/origin.pem /etc/otto/tls/origin.key\n}\n' >"$tls_snip"
	tls_ok=0
	if [[ -s /etc/otto/tls/origin.pem && -s /etc/otto/tls/origin.key ]]; then
		chown root:caddy /etc/otto/tls/origin.pem /etc/otto/tls/origin.key
		chmod 0644 /etc/otto/tls/origin.pem
		chmod 0640 /etc/otto/tls/origin.key
		tls_ok=1
	else
		todo "TLS: Cloudflare → SSL/TLS → Origin Server → Create certificate (hosts: $OTTO_DOMAIN, *.$OTTO_DOMAIN; 15 years); save the two blocks as /etc/otto/tls/origin.pem and /etc/otto/tls/origin.key on this server, set SSL/TLS mode to Full (strict), then re-run: bash $SRC/bootstrap.sh"
	fi
else
	printf '# Written by infra/bootstrap.sh (OTTO_TLS=letsencrypt)\n(otto_tls) {\n\ttls %s\n}\n' "$OTTO_ACME_EMAIL" >"$tls_snip"
	tls_ok=1
fi
chmod 0644 "$tls_snip"
cat >/etc/caddy/Caddyfile <<'EOF'
# Managed by infra/bootstrap.sh — the real config is versioned in the repo (deploy.sh reloads Caddy when it changes).
import /opt/otto/infra/Caddyfile
EOF
install -d -m 0755 /etc/systemd/system/caddy.service.d
printf '# Managed by infra/bootstrap.sh\n[Service]\nEnvironmentFile=/etc/otto/caddy.env\n' >/etc/systemd/system/caddy.service.d/otto.conf
systemctl daemon-reload
caddy_ok=0
if (( tls_ok )); then
	vlog=$(mktemp)
	if env OTTO_DOMAIN="$file_domain" OTTO_PROXY_KEY="$proxy_key" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >"$vlog" 2>&1; then
		systemctl enable caddy >/dev/null 2>&1
		systemctl reload-or-restart caddy
		caddy_ok=1
		note "Caddy serves $file_domain, app.$file_domain, admin.$file_domain"
	else
		warn "caddy validate failed:"
		tail -n 15 "$vlog" | sed "s/$proxy_key/<OTTO_PROXY_KEY>/g" >&2
		todo "Fix the Caddy config (caddy validate --config /etc/caddy/Caddyfile), then re-run bootstrap"
	fi
	rm -f "$vlog"
else
	systemctl stop caddy 2>/dev/null || true
	note "Caddy waits for the origin certificate"
fi

# ------------------------------------------------------------------ systemd units, sudo rules, deploy key, logrotate
say "services"
units_hash() { { cat /etc/systemd/system/otto-*.service /etc/systemd/system/otto-*.timer /etc/systemd/system/otto-*.service.d/*.conf 2>/dev/null || true; } | sha256sum; }
units_before=$(units_hash)
for f in "$SRC"/systemd/*.service "$SRC"/systemd/*.timer; do install -m 0644 -o root -g root "$f" /etc/systemd/system/; done
# drop-ins (one job's extra rights, e.g. otto-job@retention.service.d/secrets.conf)
for dir in "$SRC"/systemd/*.service.d; do
	[[ -d $dir ]] || continue
	install -d -m 0755 -o root -g root "/etc/systemd/system/$(basename "$dir")"
	for f in "$dir"/*.conf; do install -m 0644 -o root -g root "$f" "/etc/systemd/system/$(basename "$dir")/"; done
done
for f in /etc/systemd/system/otto-job-*.timer; do
	[[ -e $f && ! -e $SRC/systemd/$(basename "$f") ]] || continue
	systemctl disable --now "$(basename "$f")" >/dev/null 2>&1 || true
	rm -f "$f"
	note "removed old timer $(basename "$f")"
done
systemctl daemon-reload
units_after=$(units_hash)

sud=$(mktemp)
cat >"$sud" <<'EOF'
# Managed by /opt/otto/infra/bootstrap.sh — re-run it instead of editing.
# GitHub Actions: the deploy user (its key is locked to /usr/local/sbin/otto-deploy-gate) may run the deploy script as otto.
deploy ALL=(otto) NOPASSWD: /opt/otto/infra/deploy.sh
# deploy.sh (as otto) may restart Otto's own services and reload Caddy — these exact commands, nothing else.
otto ALL=(root) NOPASSWD: /usr/bin/systemctl restart otto-api.service, /usr/bin/systemctl try-restart otto-telegram.service, /usr/bin/systemctl reload caddy.service
EOF
visudo -cqf "$sud" || die "generated sudoers rules do not validate"
install -m 0440 -o root -g root "$sud" /etc/sudoers.d/otto
rm -f "$sud"

install -d -m 0755 -o root -g root /home/deploy/.ssh
if [[ -n ${OTTO_DEPLOY_PUBKEY:-} ]]; then
	re='^(ssh-ed25519|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+( [A-Za-z0-9@._:+-]+)*$'
	[[ $OTTO_DEPLOY_PUBKEY =~ $re ]] || die "OTTO_DEPLOY_PUBKEY must be one public key line (ssh-ed25519 AAAA… comment)"
	printf 'restrict,command="/usr/local/sbin/otto-deploy-gate" %s\n' "$OTTO_DEPLOY_PUBKEY" >/home/deploy/.ssh/authorized_keys
	chmod 0644 /home/deploy/.ssh/authorized_keys
	note "GitHub Actions deploy key installed for user deploy (forced command otto-deploy-gate)"
fi
[[ -s /home/deploy/.ssh/authorized_keys ]] ||
	todo "GitHub Actions deploy key: on your computer run  ssh-keygen -t ed25519 -N '' -C github-actions -f otto-deploy  then re-run bootstrap with  OTTO_DEPLOY_PUBKEY=\"\$(cat otto-deploy.pub)\"  and paste the PRIVATE file into the GitHub secret OTTO_SSH_KEY (then delete both files)"

cat >/etc/logrotate.d/otto <<'EOF'
# Managed by infra/bootstrap.sh — the engine's logs next to data.json (the owner console tails them)
/var/lib/otto/*.log {
	su otto otto
	weekly
	rotate 8
	maxsize 50M
	compress
	delaycompress
	missingok
	notifempty
	copytruncate
}
EOF

# ------------------------------------------------------------------ first release, then start everything
HOLD=/etc/otto/timers-off
[[ ${OTTO_TIMERS:-on} == off ]] && touch "$HOLD"
systemctl enable otto-api.service >/dev/null 2>&1
if [[ ! -s /var/lib/otto/deploy/current ]]; then
	sha=$(as_otto git -C /opt/otto rev-parse HEAD)
	say "first release $(printf '%s' "$sha" | cut -c1-8) (tests, pages, health check)"
	systemctl start otto-api.service
	if ! sudo -u otto -H /opt/otto/infra/deploy.sh "$sha"; then
		warn "the first deploy failed — see above"
		todo "First release failed: fix, then run  sudo -u otto /opt/otto/infra/deploy.sh main"
	fi
elif [[ $units_before != "$units_after" ]]; then
	systemctl restart otto-api.service
	systemctl try-restart otto-telegram.service
	note "units changed — otto-api restarted"
else
	systemctl start otto-api.service
fi
if [[ -e $HOLD ]]; then
	note "job timers and the Telegram poller stay OFF ($HOLD exists — otto timers on / otto cutover)"
else
	for f in /etc/systemd/system/otto-job-*.timer; do systemctl enable --now "$(basename "$f")" >/dev/null 2>&1; done
	systemctl enable otto-telegram.service >/dev/null 2>&1
	systemctl start otto-telegram.service >/dev/null 2>&1 || true        # starts only once telegram.json exists
	note "job timers on ($(ls /etc/systemd/system/otto-job-*.timer | wc -l))"
fi
systemctl enable --now otto-backup.timer otto-cloudflare-ips.timer >/dev/null 2>&1

# ------------------------------------------------------------------ what is left for a human
[[ -s /etc/otto/secrets/telegram.json ]] ||
	todo "Telegram (approvals + alerts): create /etc/otto/secrets/telegram.json = {\"bot_token\": \"…\", \"owner_chat_id\": \"…\"} (owner otto, mode 600), then: systemctl start otto-telegram && otto alert-test"
[[ -s /etc/otto/secrets/google-oauth.json ]] ||
	todo "Google sign-in for clients (app.$OTTO_DOMAIN): create a Google OAuth client (Web application, redirect URI https://app.$OTTO_DOMAIN/auth/google/callback; docs/AUTH-AND-TRIAL.md), save {\"client_id\": \"…\", \"client_secret\": \"…\"} as /etc/otto/secrets/google-oauth.json (owner otto, mode 600), then: systemctl restart otto-api"
[[ -s /etc/otto/backup.pub && -n ${OTTO_BACKUP_REMOTE:-} && -s ${RCLONE_CONFIG:-/nonexistent} ]] ||
	todo "Backups: age public key → /etc/otto/backup.pub; rclone remote → /etc/otto/secrets/rclone.conf; OTTO_BACKUP_REMOTE in $ENVF; then: otto backup (infra/README.md → Backups)"

ip4=$(curl -fsS -m 3 http://169.254.169.254/hetzner/v1/metadata/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
cat <<EOF

== Otto is installed on $(hostname) ($ip4)
   Domain         $file_domain  (app.$file_domain, admin.$file_domain)
   Web            $([[ $caddy_ok == 1 ]] && echo "Caddy running" || echo "Caddy NOT serving yet")
   Release        $(cat /var/lib/otto/deploy/current 2>/dev/null | cut -c1-8 || echo none)
   Control        otto status · otto logs <job|api> · otto pause|resume · otto help

   For GitHub (repository secrets):
     OTTO_HOST          $ip4
     OTTO_KNOWN_HOSTS   $ip4 $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
EOF
if (( ${#TODO[@]} )); then
	echo
	echo "== Still to do (in this order):"
	i=1
	for t in "${TODO[@]}"; do printf '   %d. %s\n' "$i" "$t"; i=$((i + 1)); done
else
	echo
	echo "== Nothing left to do here. Publishing is paused until you resume it in the owner console (or: otto resume)."
fi
