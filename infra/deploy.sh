#!/usr/bin/env bash
# Deploy an Otto release on the server. Runs as otto (GitHub Actions: ssh deploy@host → otto-deploy-gate → this).
#
#   sudo -u otto /opt/otto/infra/deploy.sh <sha|branch>   fetch → run the tests on a clean copy of that commit → switch
#                                                         /opt/otto to it → publish the pages → restart → health check;
#                                                         anything failing after the switch rolls back automatically
#   sudo -u otto /opt/otto/infra/deploy.sh --rollback     back to the release that was live before the current one (no tests)
#   sudo -u otto /opt/otto/infra/deploy.sh --status       current / previous release and the last deploys
#   --skip-tests                                          emergency only (the GitHub workflow has already run them)
#
# Releases: /var/lib/otto/deploy/{current,previous,history.log}. /opt/otto is a git checkout at a detached commit; the engine
# never writes into it (every OTTO_* path points into /var/lib/otto). Web roots (Caddy): /srv/otto/{site,app,admin,static}.
# Health check: the API directly (GET 127.0.0.1:8161/otto-api/data from this host — a direct local call, no proxy headers),
# then through Caddy on this host with the real Host header (GET / on the apex, app. and admin., and /otto-peek → the API's
# 400 "url required", which proves Caddy reaches the API). Units, sudoers and other root-owned files are not touched here:
# when infra/systemd or bootstrap files change, it says so — run `sudo bash /opt/otto/infra/bootstrap.sh`.
set -euo pipefail

# the checkout changes under us: run from a private copy
if [[ ${OTTO_DEPLOY_COPY:-} != 1 ]]; then
	self=$(mktemp "${TMPDIR:-/tmp}/otto-deploy.XXXXXX")
	cp "$0" "$self"
	OTTO_DEPLOY_COPY=1 OTTO_DEPLOY_SELF=$self exec bash "$self" "$@"
fi
trap 'rm -f "${OTTO_DEPLOY_SELF:-}"' EXIT

REPO=/opt/otto
WEB=/srv/otto
ENV_FILE=${OTTO_ENV_FILE:-/etc/otto/otto.env}
say() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] FAILED: %s\n' "$*" >&2; exit 1; }

[[ $(id -un) == otto ]] || die "run as otto: sudo -u otto $REPO/infra/deploy.sh $*"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
DATA_DIR=$(dirname "${OTTO_DATA:-/var/lib/otto/data.json}")
STATE=$DATA_DIR/deploy
mkdir -p "$STATE" "$DATA_DIR/locks" "$DATA_DIR/tmp"

git_() { git -C "$REPO" "$@"; }
short() { git_ rev-parse --short=8 "$1" 2>/dev/null || printf '%s' "${1:0:8}"; }
subject() { git_ log -1 --format=%s "$1" 2>/dev/null | cut -c1-80; }
beat() { python3 "$REPO/platform/otto_cron.py" beat deploy "$@" >/dev/null 2>&1 || true; }

status() {
	local cur prev
	cur=$(cat "$STATE/current" 2>/dev/null || true)
	prev=$(cat "$STATE/previous" 2>/dev/null || true)
	say "current:  ${cur:+$(short "$cur") $(subject "$cur")}${cur:-none}"
	say "previous: ${prev:+$(short "$prev") $(subject "$prev")}${prev:-none}"
	say "checkout: $(git_ rev-parse --short=8 HEAD 2>/dev/null || echo '?')"
	[[ -f $STATE/history.log ]] && tail -n 8 "$STATE/history.log" | sed 's/^/[deploy]   /'
	return 0
}

# ---------- steps ----------

run_tests() {   # $1 = sha — on a clean export of the commit, with no OTTO_* in the environment (tests make their own)
	local t rc=0
	t=$(mktemp -d "$DATA_DIR/tmp/deploy-test.XXXXXX")
	git_ archive --format=tar "$1" | tar -x -C "$t"
	say "tests: $(short "$1") …"
	(cd "$t/platform" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 TMPDIR="$t" \
		timeout 1200 python3 -m unittest discover -s tests >"$t/tests.out" 2>&1) || rc=$?
	grep -E '^(Ran [0-9]+ tests|OK|FAILED)' "$t/tests.out" | sed 's/^/[deploy]   /' || true
	if (( rc )); then
		grep -E '^(ERROR|FAIL):' "$t/tests.out" | head -n 15 | sed 's/^/[deploy]   /' || true
		tail -n 25 "$t/tests.out" | sed 's/^/[deploy]   | /'
	fi
	rm -rf "$t"
	return "$rc"
}

# The step functions below run inside `a && b && c` chains, where bash ignores `set -e`: every command that matters
# carries its own `|| return 1`.

switch_to() {   # $1 = sha
	git_ checkout --quiet --force --detach "$1" || return 1
	git_ clean -fdq || return 1
}

put() {   # atomic copy: $1 src → $2 dst (0644)
	local tmp
	tmp=$(mktemp "$2.XXXXXX") || return 1
	cp "$1" "$tmp" && chmod 0644 "$tmp" && mv -f "$tmp" "$2" || { rm -f "$tmp"; return 1; }
}

publish_pages() {
	local p=$REPO/platform f tmp
	mkdir -p "$WEB/site" "$WEB/app" "$WEB/admin" "$WEB/static/assets" || return 1
	# apex: landing + onboarding (the public onboarding, before having a login)
	put "$p/landing.html" "$WEB/site/index.html" || return 1
	put "$p/onboarding.html" "$WEB/site/onboarding.html" || return 1
	# legal pages (tools/legal.py renders them from docs/legal/*.md): /legal/*.html on the apex, and on app. because
	# onboarding links to them from both hosts. Guarded: a rollback to a release from before them must not fail here.
	if [[ -d $p/legal ]]; then
		for host in site app; do
			rsync -a --delete --chmod=D0755,F0644 --include='*.html' --exclude='*' "$p/legal/" "$WEB/$host/legal/" || return 1
		done
	fi
	# app.: the client app with the NEUTRAL embedded fallback (ap.sync_fallback without OTTO_FALLBACK=full) — the page is
	# served to every client and must never carry data.json (OTTO_HTML points at an unserved file, so the engine never
	# writes one either)
	tmp=$(mktemp "$WEB/app/index.html.XXXXXX") || return 1
	cp "$p/index.html" "$tmp" &&
		(cd "$p" && OTTO_HTML="$tmp" OTTO_FALLBACK=neutral python3 ap.py sync-fallback >/dev/null) &&
		chmod 0644 "$tmp" && mv -f "$tmp" "$WEB/app/index.html" || { rm -f "$tmp"; return 1; }
	for f in onboarding.html billing.html approve.html ads.html analytics.html; do
		if [[ -f $p/$f ]]; then put "$p/$f" "$WEB/app/$f" || return 1; fi
	done
	# admin.: the owner console (its bundled sample is invented businesses on .example domains)
	put "$p/admin.html" "$WEB/admin/index.html" || return 1
	# static assets shipped in git (landing images, films, platform.css); generated media live in /var/lib/otto/public
	rsync -a --delete --chmod=D0755,F0644 "$p/assets/" "$WEB/static/assets/" || return 1
}

apply() {   # $1 = from sha (may be empty), $2 = to sha: restart what runs the code, reload Caddy if its config changed
	sudo -n /usr/bin/systemctl restart otto-api.service || return 1
	sudo -n /usr/bin/systemctl try-restart otto-telegram.service || return 1   # a poller kept off (migration) stays off
	if [[ -z $1 ]] || ! git_ diff --quiet "$1" "$2" -- infra/Caddyfile; then
		if systemctl is-active --quiet caddy; then
			sudo -n /usr/bin/systemctl reload caddy.service || { say "Caddy refused the new Caddyfile (the old config keeps running)"; return 1; }
		fi
	fi
	if [[ -n $1 ]] && [[ -n $(git_ diff --name-only "$1" "$2" -- infra/systemd infra/bootstrap.sh infra/otto_alert.py \
		infra/cloudflare-ips.sh infra/deploy-gate.sh infra/otto) ]]; then
		say "NOTE: server config changed in this release (units / bootstrap) — run: sudo bash $REPO/infra/bootstrap.sh"
	fi
}

health() {
	local i ok=0 out code host
	out=$(mktemp "$DATA_DIR/tmp/health.XXXXXX")
	for i in $(seq 1 30); do
		if curl -fsS -m 5 -o "$out" http://127.0.0.1:8161/otto-api/data &&
			python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) else 1)' "$out"; then
			ok=1
			break
		fi
		sleep 1
	done
	rm -f "$out"
	(( ok )) || { say "health: the API does not answer /otto-api/data"; return 1; }
	say "health: API ok"
	if ! systemctl is-active --quiet caddy; then
		say "health: Caddy is not running — web checks skipped (bootstrap prints what it still needs)"
		return 0
	fi
	for host in "$OTTO_DOMAIN" "app.$OTTO_DOMAIN" "admin.$OTTO_DOMAIN"; do
		code=$(curl -ks -m 10 -o /dev/null -w '%{http_code}' --resolve "$host:443:127.0.0.1" "https://$host/" || true)
		[[ $code == 200 ]] || { say "health: https://$host/ answered ${code:-nothing}"; return 1; }
	done
	if [[ -f $REPO/platform/legal/terms.html ]]; then
		code=$(curl -ks -m 10 -o /dev/null -w '%{http_code}' --resolve "$OTTO_DOMAIN:443:127.0.0.1" "https://$OTTO_DOMAIN/legal/terms.html" || true)
		[[ $code == 200 ]] || { say "health: https://$OTTO_DOMAIN/legal/terms.html answered ${code:-nothing}"; return 1; }
	fi
	code=$(curl -ks -m 10 -o /dev/null -w '%{http_code}' --resolve "$OTTO_DOMAIN:443:127.0.0.1" "https://$OTTO_DOMAIN/otto-peek" || true)
	[[ $code == 400 ]] || { say "health: /otto-peek through Caddy answered ${code:-nothing} (expected the API's 400)"; return 1; }
	say "health: Caddy ok (apex, app., admin., legal pages, API through Caddy)"
}

record() {   # $1 = new current, $2 = the one it replaced, $3 = note
	[[ -n $2 && $2 != "$1" ]] && printf '%s\n' "$2" >"$STATE/previous"
	printf '%s\n' "$1" >"$STATE/current"
	printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$(short "$1")" "$3" >>"$STATE/history.log"
}

# ---------- main ----------

target=${1:-}
skip_tests=0
[[ ${2:-} == --skip-tests || ${1:-} == --skip-tests ]] && skip_tests=1
[[ $target == --skip-tests ]] && target=${2:-}
case $target in
	--status) status; exit 0 ;;
	--rollback) mode=rollback ;;
	"") die "usage: deploy.sh <sha|branch> | --rollback | --status" ;;
	-*) die "unknown option $target" ;;
	*) mode=deploy
	   [[ $target =~ ^[A-Za-z0-9._/-]{1,100}$ ]] || die "bad target $target" ;;
esac

exec 9>"$DATA_DIR/locks/deploy.lock"
flock -n 9 || die "another deploy is running"
t0=$(date +%s)
cur=$(cat "$STATE/current" 2>/dev/null || true)
[[ -n $cur ]] || cur=$(git_ rev-parse HEAD 2>/dev/null || true)
[[ -f $STATE/current ]] || first=1

if [[ $mode == rollback ]]; then
	sha=$(cat "$STATE/previous" 2>/dev/null || true)
	[[ -n $sha ]] || die "no previous release recorded — deploy a specific commit instead: deploy.sh <sha>"
	git_ cat-file -e "$sha^{commit}" 2>/dev/null || git_ fetch --quiet --prune origin
	say "rollback: $(short "$cur") → $(short "$sha") $(subject "$sha")"
	skip_tests=1
else
	say "fetching $target"
	git_ fetch --quiet --prune origin '+refs/heads/*:refs/remotes/origin/*'
	if [[ $target =~ ^[0-9a-f]{7,40}$ ]] && git_ cat-file -e "$target^{commit}" 2>/dev/null; then
		sha=$(git_ rev-parse "$target^{commit}")
	else
		sha=$(git_ rev-parse --verify --quiet "origin/$target^{commit}") || die "unknown commit or branch: $target"
	fi
	say "deploy: $(short "$sha") $(subject "$sha") (live: ${cur:+$(short "$cur")}${cur:-none})"
fi
beat running --label Deploy

if (( ! skip_tests )); then
	run_tests "$sha" || { beat failed --note "tests failed for $(short "$sha") — nothing changed"; die "tests failed for $(short "$sha") — nothing changed on the server"; }
fi

stage=switch
if switch_to "$sha" && stage=pages && publish_pages && stage=restart && apply "$cur" "$sha" && stage=health && health; then
	record "$sha" "$cur" "$mode ok${first:+ (first release)}"
	secs=$(( $(date +%s) - t0 ))
	beat ok --label Deploy --note "$(short "$sha") $(subject "$sha") (${secs}s)"
	say "OK: $(short "$sha") is live (${secs}s) · previous $(short "${cur:-$sha}") · rollback: deploy.sh --rollback"
	exit 0
fi

say "FAILED at $stage for $(short "$sha")"
if [[ -z $cur || $cur == "$sha" ]]; then
	beat failed --label Deploy --note "$(short "$sha") failed at $stage, nothing to roll back to"
	die "$(short "$sha") failed at $stage and there is no earlier release to go back to"
fi
say "rolling back to $(short "$cur")"
if switch_to "$cur" && publish_pages && apply "$sha" "$cur" && health; then
	printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$(short "$sha")" "$mode FAILED at $stage → rolled back to $(short "$cur")" >>"$STATE/history.log"
	beat failed --label Deploy --note "$(short "$sha") failed at $stage — rolled back to $(short "$cur")"
	die "$(short "$sha") failed at $stage — rolled back to $(short "$cur"), which is healthy"
fi
beat failed --label Deploy --note "$(short "$sha") failed at $stage and the rollback to $(short "$cur") failed too"
printf '[deploy] ROLLBACK FAILED: %s is checked out but not healthy — look now: journalctl -u otto-api -n 50\n' "$(short "$cur")" >&2
exit 2
