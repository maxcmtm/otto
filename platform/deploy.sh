#!/bin/bash
# Deploy Otto Mission Control static files to the live dashboard (dash.monyflow.work/otto/)
# and the public landing page (dash.monyflow.work/pilot-landing.html).
# The action API (otto-api.service) reads/writes the workspace data.json directly — no data copy needed.
set -e
cd "$(dirname "$0")"
python3 ap.py sync-fallback
cp index.html /srv/pulse/otto/index.html
cp admin.html /srv/pulse/otto/admin.html          # owner console — must sit behind the same auth as the app (docs/ADMIN.md)
cp onboarding.html /srv/pulse/otto/onboarding.html
# legal pages (rendered from docs/legal/*.md by tools/legal.py). The landing and onboarding link to legal/*.html, which
# resolves to /otto/legal/ here: nginx must serve /otto/legal/ WITHOUT the app's auth, like /otto/assets/.
mkdir -p /srv/pulse/otto/legal
cp legal/*.html /srv/pulse/otto/legal/
cp -r assets /srv/pulse/otto/
# Landing lives in the repo now (platform/landing.html). It references /otto/assets/... absolutely,
# so it must be served from the same host as /otto/. cp keeps the existing hardlink inode intact.
cp landing.html /srv/pulse/pilot-landing.html
echo "deployed to /srv/pulse/otto/ (+ admin.html) + /srv/pulse/pilot-landing.html — restart otto-api after API changes"
