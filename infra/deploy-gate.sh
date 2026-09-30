#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key. bootstrap.sh installs a root-owned copy as /usr/local/sbin/otto-deploy-gate
# and puts the key in ~deploy/.ssh/authorized_keys as:
#     restrict,command="/usr/local/sbin/otto-deploy-gate" ssh-ed25519 AAAA… github-actions
# so that key can do exactly one thing — run the deploy script as otto — whatever command the client asks for:
#     sudo -u otto /opt/otto/infra/deploy.sh <commit sha> | --rollback | --status
set -euo pipefail

cmd=${SSH_ORIGINAL_COMMAND:-}
re='^sudo -u otto /opt/otto/infra/deploy\.sh ([0-9a-f]{7,40}|--rollback|--status)$'
if [[ $cmd =~ $re ]]; then
	exec sudo -n -u otto /opt/otto/infra/deploy.sh "${BASH_REMATCH[1]}"
fi
logger -t otto-deploy-gate "refused from ${SSH_CLIENT%% *}: ${cmd:0:200}" 2>/dev/null || true
echo "otto-deploy-gate: refused — this key may only run: sudo -u otto /opt/otto/infra/deploy.sh <sha>|--rollback|--status" >&2
exit 126
