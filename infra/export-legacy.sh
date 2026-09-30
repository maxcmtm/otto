#!/usr/bin/env bash
# One-off: export Otto's state from the OLD box (OpenClaw workspace layout) into the archive layout restore.sh reads.
# Run on the old box, from the repo checkout there (after `git pull`), as the user that owns the workspace:
#
#   bash infra/export-legacy.sh            # → ~/otto-legacy-<time>.tar.gz (0600)
#
# Old layout (what the engine defaulted to before OTTO_* paths): <repo>/platform/{data.json, *.log, *.jsonl, billing.json,
# leads.json, .watch-state.json, .telegram-state.json, assets/}, <repo>/brands/, secrets in <repo>/../otto-secrets/*.json,
# the Leonardo key in <repo>/platform/.leonardo_key (becomes secrets/leonardo.json). data.json, billing.json and leads.json are
# copied under their own flock, like backup.sh does. The archive is NOT encrypted (it holds the secrets): copy it straight to the
# new server over SSH, restore it, then delete it on both sides:
#   scp ~/otto-legacy-*.tar.gz root@NEW:/root/ && ssh root@NEW '/opt/otto/infra/restore.sh /root/otto-legacy-*.tar.gz --migrate'
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
P=$REPO/platform
SECRETS=${OTTO_SECRETS:-$(cd "$REPO/.." && pwd)/otto-secrets}
[[ -f $P/data.json ]] || { echo "no $P/data.json — run this from the old box's checkout" >&2; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=${1:-$HOME}/otto-legacy-$STAMP.tar.gz
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
chmod 700 "$W"
mkdir -p "$W/data" "$W/etc/secrets"

for f in data.json billing.json leads.json; do
	[[ -f $P/$f ]] && flock -w 120 "$P/$f.lock" cp -p "$P/$f" "$W/data/$f"
done
shopt -s dotglob nullglob
for f in "$P"/*.log "$P"/*.jsonl "$P"/.watch-state.json "$P"/.telegram-state.json; do
	cp -p "$f" "$W/data/"
done
shopt -u dotglob nullglob
cp -a "$P/assets" "$W/data/assets"
[[ -d $REPO/brands ]] && cp -a "$REPO/brands" "$W/data/brands"
if [[ -d $SECRETS ]]; then
	cp -p "$SECRETS"/*.json "$W/etc/secrets/" 2>/dev/null || true
fi
if [[ -s $P/.leonardo_key && ! -f $W/etc/secrets/leonardo.json ]]; then
	python3 -c 'import json,sys; print(json.dumps({"api_key": open(sys.argv[1]).read().strip()}))' "$P/.leonardo_key" >"$W/etc/secrets/leonardo.json"
fi
python3 - "$W" "$REPO" <<'PY'
import json, os, socket, subprocess, sys
from datetime import datetime, timezone
root, repo = sys.argv[1], sys.argv[2]
rel = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
n = sum(len(f) for _, _, f in os.walk(root))
json.dump({"format": 1, "source": "export-legacy.sh", "host": socket.gethostname(), "release": rel, "files": n,
           "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "secrets": sorted(os.listdir(os.path.join(root, "etc", "secrets")))}, open(os.path.join(root, "manifest.json"), "w"), indent=1)
PY
umask 077
tar -C "$W" -czf "$OUT" .
echo "exported $(du -h "$OUT" | cut -f1) → $OUT"
echo "secrets included: $(ls "$W/etc/secrets" | tr '\n' ' ')"
echo "next: scp it to the new server, run restore.sh on it with --migrate, then delete it here (rm $OUT)"
