#!/usr/bin/env bash
# Restore Otto's data from a backup. Run as root; Otto's services and timers are stopped while it works.
#
#   sudo /opt/otto/infra/restore.sh list                                   # the backups on the remote
#   sudo /opt/otto/infra/restore.sh latest     < otto-backup-key.txt       # newest daily/weekly archive
#   sudo /opt/otto/infra/restore.sh otto-20261003T013012Z.tar.zst.age < otto-backup-key.txt
#   sudo /opt/otto/infra/restore.sh /root/otto-legacy-20261001.tar.gz      # export from the old box (infra/export-legacy.sh)
# Options:
#   --yes          no confirmation prompt
#   --migrate      new box next to a live old one: leave every job timer and the Telegram poller OFF afterwards
#                  (infra/README.md → Migration; `otto cutover` switches them on)
#   --no-secrets   keep this server's /etc/otto/secrets as they are
#   --no-pause     do not switch the kill switch on (default: publishing is paused after every restore until you resume it)
#
# The age private key (AGE-SECRET-KEY-1…) is read from stdin — redirect a file or paste it and press Ctrl-D. It is kept in a
# 0600 file under a 0700 work dir for the few seconds decryption takes, then deleted. The current /var/lib/otto is moved
# aside to /var/lib/otto.before-restore-<time> (delete it yourself once all is well). otto.env is never replaced; the backed-up
# one is left as /etc/otto/otto.env.from-backup to compare.
set -euo pipefail

say() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore] FAILED: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "run as root: sudo $0 $*"
ENV_FILE=/etc/otto/otto.env
[[ -r $ENV_FILE ]] || die "$ENV_FILE missing — run infra/bootstrap.sh first"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
DIR=$(dirname "${OTTO_DATA:-/var/lib/otto/data.json}")
SECRETS=${OTTO_SECRETS:-/etc/otto/secrets}
REMOTE=${OTTO_BACKUP_REMOTE:-}
PATTERN='^otto-[0-9]{8}T[0-9]{6}Z\.tar\.zst\.age$'

src="" yes=0 migrate=0 secrets=1 pause=1
for a in "$@"; do
	case $a in
		--yes) yes=1 ;;
		--migrate) migrate=1 ;;
		--no-secrets) secrets=0 ;;
		--no-pause) pause=0 ;;
		-*) die "unknown option $a" ;;
		*) [[ -z $src ]] || die "one backup at a time"; src=$a ;;
	esac
done
[[ -n $src ]] || die "which backup? latest | list | <name> | /path/to/file (see the header of this script)"

remote_list() {   # every archive on the remote, "folder/name", oldest first
	[[ -n $REMOTE ]] || die "OTTO_BACKUP_REMOTE is not set in $ENV_FILE"
	local f
	for f in daily weekly; do
		rclone lsf "$REMOTE/$f/" --files-only 2>/dev/null | { grep -E "$PATTERN" || true; } | sed "s|^|$f/|"
	done | sort -t/ -k2
}

if [[ $src == list ]]; then
	remote_list
	exit 0
fi

WORK=$(mktemp -d /var/tmp/otto-restore.XXXXXX)
chmod 700 "$WORK"
cleanup() { [[ -f $WORK/identity ]] && shred -u "$WORK/identity" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

# ---- 1. get the archive
if [[ -f $src ]]; then
	archive=$src
	label=$(basename "$src")
else
	if [[ $src == latest ]]; then
		pick=$(remote_list | tail -n 1)
		[[ -n $pick ]] || die "no backups found on $REMOTE"
	else
		[[ $src =~ $PATTERN ]] || die "$src is not a backup name (otto-YYYYmmddTHHMMSSZ.tar.zst.age) or a local file"
		pick=$(remote_list | grep -F "/$src" | tail -n 1 || true)
		[[ -n $pick ]] || die "$src is not on $REMOTE"
	fi
	label=${pick#*/}
	say "fetching $REMOTE/$pick"
	rclone copyto "$REMOTE/$pick" "$WORK/$label" --retries 3 || die "download failed"
	archive=$WORK/$label
fi

# ---- 2. decrypt + unpack into the work dir
mkdir "$WORK/x"
case $archive in
	*.age)
		umask 077
		[[ -t 0 ]] && say "paste the backup private key (AGE-SECRET-KEY-1…), then press Ctrl-D:"
		cat >"$WORK/identity"
		umask 022
		grep -q '^AGE-SECRET-KEY-1' "$WORK/identity" || die "stdin did not contain an age private key (AGE-SECRET-KEY-1…)"
		age -d -i "$WORK/identity" "$archive" | zstd -dq | tar -x --no-same-owner -C "$WORK/x" || die "could not decrypt/unpack (wrong key?)"
		shred -u "$WORK/identity" 2>/dev/null || rm -f "$WORK/identity"
		;;
	*.tar.zst) zstd -dqc "$archive" | tar -x --no-same-owner -C "$WORK/x" || die "could not unpack $archive" ;;
	*.tar.gz | *.tgz) tar -xzf "$archive" --no-same-owner -C "$WORK/x" || die "could not unpack $archive" ;;
	*) die "unknown archive type: $archive" ;;
esac
[[ -f $WORK/x/data/data.json ]] || die "the archive has no data/data.json — not an Otto backup"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d, dict) and isinstance(d.get("brands", []), list)' \
	"$WORK/x/data/data.json" || die "data/data.json in the archive is not valid Otto state"
summary=$(python3 - "$WORK/x" <<'PY'
import json, os, sys
root = sys.argv[1]
try:
    m = json.load(open(os.path.join(root, "manifest.json")))
except Exception:
    m = {}
d = json.load(open(os.path.join(root, "data", "data.json")))
print(f"made {m.get('created') or '?'} on {m.get('host') or '?'} ({m.get('source') or 'backup'}, release {(m.get('release') or '?')[:8]}) · "
      f"{len(d.get('brands', []))} brands, {len(d.get('posts', []))} posts, {len(d.get('campaigns', []))} campaigns · "
      f"secrets: {'yes' if os.path.isdir(os.path.join(root, 'etc', 'secrets')) else 'no'}")
PY
)
say "$label: $summary"

if (( ! yes )); then
	[[ -r /dev/tty ]] || die "no terminal to confirm on — re-run with --yes"
	printf '[restore] This replaces %s (the current data is moved aside). Type RESTORE to go on: ' "$DIR" >/dev/tty
	read -r answer </dev/tty
	[[ $answer == RESTORE ]] || die "cancelled"
fi

# ---- 3. stop everything that writes
mapfile -t timers < <(systemctl list-units --type=timer --state=active --plain --no-legend 'otto-*' | awk '{print $1}')
tg_was=$(systemctl is-active otto-telegram.service 2>/dev/null || true)
say "stopping Otto (api, telegram, ${#timers[@]} timers, running jobs)"
systemctl stop "${timers[@]}" 2>/dev/null || true
systemctl stop 'otto-job@*.service' otto-backup.service otto-telegram.service otto-api.service 2>/dev/null || true

# ---- 4. swap the data in
aside=${DIR}.before-restore-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$aside"
find "$DIR" -mindepth 1 -maxdepth 1 -exec mv -t "$aside" {} +
cp -a "$WORK/x/data/." "$DIR/"
# this server's own records win over the backup's: its release history and its job heartbeats
rm -rf "$DIR/deploy" "$DIR/heartbeats.json" "$DIR/.alert-state.json"
for keep in deploy heartbeats.json; do
	if [[ -e $aside/$keep ]]; then cp -a "$aside/$keep" "$DIR/$keep"; fi
done
mkdir -p "$DIR/locks" "$DIR/tmp" "$DIR/public/assets" "$DIR/assets" "$DIR/brands" "$DIR/deploy"
chown -R otto:otto "$DIR"
chown otto:caddy "$DIR" && chmod 0710 "$DIR"
chmod 0755 "$DIR/public" "$DIR/public/assets"
say "data restored into $DIR (previous data: $aside)"
# public media = a published copy of assets/ (the backup leaves it out)
runuser -u otto -- rsync -a --ignore-existing --chmod=D0755,F0644 "$DIR/assets/" "$DIR/public/assets/"

if (( secrets )) && [[ -d $WORK/x/etc/secrets ]]; then
	mkdir -p "$aside/etc-secrets"
	cp -a "$SECRETS/." "$aside/etc-secrets/" 2>/dev/null || true
	cp -a "$WORK/x/etc/secrets/." "$SECRETS/"
	chown -R otto:otto "$SECRETS"
	chmod 0700 "$SECRETS"
	find "$SECRETS" -type f -exec chmod 0600 {} +
	say "secrets restored into $SECRETS (this server's previous ones: $aside/etc-secrets)"
fi
if [[ -f $WORK/x/etc/otto.env ]]; then
	install -m 0640 -o root -g otto "$WORK/x/etc/otto.env" /etc/otto/otto.env.from-backup
fi

# ---- 5. paused by default, then start again
as_otto() { runuser -u otto -- bash -c 'set -a; . /etc/otto/otto.env; set +a; cd /opt/otto/platform && exec "$@"' otto "$@"; }
if (( pause )); then
	as_otto python3 otto_admin.py kill on --note "restored from $label — check, then resume in the owner console" ||
		die "data is restored but the kill switch could not be set — keep the timers off and check otto_admin.py"
fi
systemctl start otto-api.service
if (( migrate )); then
	touch /etc/otto/timers-off                                    # bootstrap.sh re-runs leave them off too, until `otto cutover`
	for t in /etc/systemd/system/otto-job-*.timer; do
		[[ -e $t ]] && { systemctl disable --now "$(basename "$t")" >/dev/null 2>&1 || true; }
	done
	systemctl disable --now otto-telegram.service >/dev/null 2>&1 || true
	for t in "${timers[@]}"; do
		[[ $t == otto-job-* ]] || systemctl start "$t"                  # backup + Cloudflare refresh keep running
	done
	say "migration mode: job timers and the Telegram poller stay OFF (cut-over: otto cutover)"
else
	if (( ${#timers[@]} )); then systemctl start "${timers[@]}"; fi
	if [[ $tg_was == active ]]; then systemctl start otto-telegram.service; fi
fi
for i in $(seq 1 20); do
	curl -fsS -m 5 -o /dev/null http://127.0.0.1:8161/otto-api/data && break
	sleep 1
done
curl -fsS -m 5 -o /dev/null http://127.0.0.1:8161/otto-api/data && say "API answers" || say "WARNING: the API does not answer — journalctl -u otto-api -n 50"
say "done: $label restored.$( (( pause )) && echo ' Publishing is PAUSED (kill switch on) — resume in the owner console or: otto resume')"
