#!/bin/bash
# Deploy Otto Mission Control static files to the live dashboard (dash.monyflow.work/otto/).
# The action API (otto-api.service) reads/writes the workspace data.json directly — no data copy needed.
set -e
cd "$(dirname "$0")"
python3 ap.py sync-fallback
cp index.html /srv/pulse/otto/index.html
cp -r assets /srv/pulse/otto/
echo "deployed to /srv/pulse/otto/"
