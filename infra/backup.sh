#!/usr/bin/env bash
# Nightly Otto backup. otto-backup.timer (01:30 UTC) → otto-backup.service → this, as otto. By hand: sudo systemctl start otto-backup
#
#   1. a consistent copy of /var/lib/otto: data.json, billing.json and leads.json are copied while holding their own flock
#      (<file>.lock — the lock ap.transaction() / otto_whop / otto_admin take), so no half-written state is ever saved;
#      assets are hard-linked (written once, atomically), everything else copied. public/ is left out — it is a copy of
#      assets/ (restore.sh republishes it). Plus /etc/otto/otto.env and, unless OTTO_BACKUP_SECRETS=0, /etc/otto/secrets.
#   2. tar | zstd | age to the public key in /etc/otto/backup.pub (the private key is NOT on the server)
#   3. rclone copy to $OTTO_BACKUP_REMOTE/daily/ (and weekly/ on Sundays or when the newest weekly is over 6 days old),
#      size-checked; keeps the newest $OTTO_BACKUP_KEEP_DAILY (14) daily and $OTTO_BACKUP_KEEP_WEEKLY (8) weekly archives
#   4. heartbeat "backup" in heartbeats.json (owner console) — ok, skipped (not configured yet) or failed
# Not configured (no remote / no public key / no rclone config) → heartbeat "skipped", exit 0. Anything else failing → exit 1
# (systemd OnFailure → Telegram alert). Archive names: otto-YYYYmmddTHHMMSSZ.tar.zst.age (lexical order = time order).
set -euo pipefail

ENV_FILE=${OTTO_ENV_FILE:-/etc/otto/otto.env}
if [[ -z ${OTTO_DATA:-} && -r $ENV_FILE ]]; then
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
fi
DATA=${OTTO_DATA:-/var/lib/otto/data.json}
DIR=$(dirname "$DATA")
PUB=${OTTO_BACKUP_PUBKEY_FILE:-/etc/otto/backup.pub}
REMOTE=${OTTO_BACKUP_REMOTE:-}
KEEP_D=${OTTO_BACKUP_KEEP_DAILY:-14}
KEEP_W=${OTTO_BACKUP_KEEP_WEEKLY:-8}
CRON=/opt/otto/platform/otto_cron.py
PATTERN='^otto-[0-9]{8}T[0-9]{6}Z\.tar\.zst\.age$'
STARTED=$(date -u +%FT%TZ)
stage=start

beat() { python3 "$CRON" beat backup "$@" --every 1440 --label "Backup" --log "journalctl -u otto-backup" --started "$STARTED" >/dev/null 2>&1 || true; }
say() { printf '[backup] %s\n' "$*"; }
noted=0
fail() { say "FAILED at $stage: $*"; beat failed --note "failed at $stage: $*"; noted=1; exit 1; }
trap 'rc=$?; if (( rc && ! noted )) && [[ $stage != done ]]; then beat failed --note "failed at $stage (exit $rc)"; fi; rm -rf "${STAGE:-/nonexistent-otto}"' EXIT

missing=()
[[ -n $REMOTE ]] || missing+=("OTTO_BACKUP_REMOTE in otto.env")
[[ -s $PUB ]] || missing+=("the age public key in $PUB")
[[ -n ${RCLONE_CONFIG:-} && ! -r ${RCLONE_CONFIG:-/nonexistent} ]] && missing+=("the rclone config $RCLONE_CONFIG")
if (( ${#missing[@]} )); then
	stage=done
	say "not configured: missing ${missing[*]} — nothing backed up (infra/README.md → Backups)"
	beat skipped --note "not configured: missing ${missing[*]}"
	exit 0
fi
for t in tar zstd age rclone flock; do command -v "$t" >/dev/null || fail "$t is not installed"; done
beat running

stage=snapshot
mkdir -p "$DIR/tmp"
STAGE=$(mktemp -d "$DIR/tmp/backup.XXXXXX")
root=$STAGE/root
mkdir -p "$root/data" "$root/etc"
locked=(data.json billing.json leads.json)
for f in "${locked[@]}"; do
	if [[ -f $DIR/$f ]]; then
		flock -w 120 "$DIR/$f.lock" cp -p "$DIR/$f" "$root/data/$f" || fail "could not copy $f under its lock"
	fi
done
shopt -s dotglob nullglob
for p in "$DIR"/*; do
	name=${p##*/}
	case $name in
		# exports: brand zips made before a retention deletion live 30 days on the server only, so deleted client data
		# leaves the backups within their 8 weeks (Terms 17.3, DPA 9.2)
		data.json | billing.json | leads.json | *.lock | locks | tmp | public | exports | lost+found) continue ;;
		assets) cp -al "$p" "$root/data/" 2>/dev/null || cp -a "$p" "$root/data/" ;;
		*) cp -a "$p" "$root/data/" ;;
	esac
done
shopt -u dotglob nullglob
cp -p /etc/otto/otto.env "$root/etc/" 2>/dev/null || true
cp -p "$PUB" "$root/etc/backup.pub"
if [[ ${OTTO_BACKUP_SECRETS:-1} != 0 && -d ${OTTO_SECRETS:-/etc/otto/secrets} ]]; then
	cp -a "${OTTO_SECRETS:-/etc/otto/secrets}" "$root/etc/secrets"
fi
python3 - "$root" <<'PY'
import json, os, socket, subprocess, sys
from datetime import datetime, timezone
root = sys.argv[1]
files = sizes = 0
for base, _, names in os.walk(root):
    for n in names:
        files += 1
        sizes += os.lstat(os.path.join(base, n)).st_size
try:
    rel = subprocess.run(["git", "-C", "/opt/otto", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
except Exception:
    rel = ""
json.dump({"format": 1, "source": "backup.sh", "host": socket.gethostname(), "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "domain": os.environ.get("OTTO_DOMAIN"), "release": rel, "files": files, "bytes": sizes,
           "secrets": os.path.isdir(os.path.join(root, "etc", "secrets"))}, open(os.path.join(root, "manifest.json"), "w"), indent=1)
PY

stage=archive
name="otto-$(date -u +%Y%m%dT%H%M%SZ).tar.zst.age"
out=$STAGE/$name
tar -C "$root" -cf - . | zstd -q -T0 -6 | age -R "$PUB" -o "$out"
size=$(stat -c %s "$out")
human=$(numfmt --to=iec --suffix=B "$size" 2>/dev/null || echo "${size}B")
say "archive $name ($human)"

stage=upload
remote_size() { rclone lsf "$1" --files-only --format "ps" --separator ";" 2>/dev/null | awk -F';' -v n="$2" '$1 == n {print $2}'; }
upload() {   # $1 = folder
	rclone copyto "$out" "$REMOTE/$1/$name" --retries 3 --low-level-retries 10 || fail "rclone copy to $REMOTE/$1 failed"
	[[ $(remote_size "$REMOTE/$1/" "$name") == "$size" ]] || fail "$REMOTE/$1/$name has the wrong size after upload"
}
upload daily
weekly=no
newest_w=$(rclone lsf "$REMOTE/weekly/" --files-only 2>/dev/null | grep -E "$PATTERN" | sort | tail -n 1 || true)
cutoff=$(date -u -d '6 days ago' +%Y%m%d)
if [[ $(date -u +%u) == 7 || -z $newest_w || ${newest_w:5:8} < $cutoff ]]; then
	upload weekly
	weekly=yes
fi

stage=prune
prune() {   # $1 = folder, $2 = how many to keep — only ever deletes files named like our archives
	local old
	rclone lsf "$REMOTE/$1/" --files-only | { grep -E "$PATTERN" || true; } | sort | head -n "-$2" | while read -r old; do
		rclone deletefile "$REMOTE/$1/$old" && say "pruned $1/$old"
	done
}
prune daily "$KEEP_D"
prune weekly "$KEEP_W"
nd=$(rclone lsf "$REMOTE/daily/" --files-only | grep -cE "$PATTERN" || true)
nw=$(rclone lsf "$REMOTE/weekly/" --files-only | grep -cE "$PATTERN" || true)

stage=done
note="$name $human → $REMOTE ($nd daily, $nw weekly kept$([[ $weekly == yes ]] && echo ', weekly copy made'))"
beat ok --note "$note"
say "OK: $note"
