#!/bin/bash
# Deploy Otto Mission Control static files to the live dashboard (dash.monyflow.work/otto/)
# and the public landing page (dash.monyflow.work/pilot-landing.html).
# The action API (otto-api.service) reads/writes the workspace data.json directly — no data copy needed.
set -e
cd "$(dirname "$0")"
python3 ap.py sync-fallback
cp index.html /srv/pulse/otto/index.html
cp -r assets /srv/pulse/otto/
# Landing lives in the repo now (platform/landing.html). It references /otto/assets/... absolutely,
# so it must be served from the same host as /otto/. cp keeps the existing hardlink inode intact.
cp landing.html /srv/pulse/pilot-landing.html
echo "deployed to /srv/pulse/otto/ + /srv/pulse/pilot-landing.html"
