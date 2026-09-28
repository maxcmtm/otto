# Otto engine crons (server, UTC; IL = UTC+2/+3)

Run from `autopilot/platform/` with the workspace Python. All scripts write state only through `ap.transaction()`
(exclusive `flock` on `data.json.lock`, fresh load, atomic temp-file + `os.replace` write), and every job line is wrapped
in `flock -n /tmp/otto-<job>.lock` so a slow run is never overlapped by the next one (the overlapping run just exits).

What "safe to re-run" really means per job:
- **Idempotent** (re-running changes nothing new): `otto_publish.py` (a post is `publishing` before the Meta call and a
  post stuck in `publishing` is never retried — it raises a P0 instead), `otto_telegram.py send-cards` / `send-recs`
  (only items without a card), `otto_ads.py launch` (resumes from `campaign.remote`, never recreates objects),
  `otto_ads.py plan` and `otto_plan.py build` (refuse a month that exists), `otto_insights.py` and `otto_competitors.py`
  (no duplicate *proposed* recommendation with the same title/brand), `otto_growth.py rollup --send` (once per month:
  `markers.growth_review_sent`), `otto_ads.py guard` (marks `ended` only after the pause succeeded).
- **Not idempotent**: `otto_watch.py report` and `otto_ads.py report` send a Telegram message on every run;
  `genvisuals.py` / `otto_video.py render` spend money (they only work on posts that still lack an image / video, but a
  second run while the first is still generating would pay twice — that is what the flock prevents).

```cron
# morning briefing 07:30 IL + daily metrics snapshot
30 4 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-watch-report.lock python3 otto_watch.py report >> watch.log 2>&1
# hourly guard: drops, missed slots, approvals about to miss their slot, posts stuck in "publishing"
15 * * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-watch.lock python3 otto_watch.py watch  >> watch.log 2>&1
# approval cards to the owner's Telegram 08:00 IL (posts due within 72 h; compliance-checked first) + new recommendation cards 18:30 IL
0 5 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-cards.lock python3 otto_telegram.py send-cards >> telegram.log 2>&1
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-recs.lock python3 otto_telegram.py send-recs >> telegram.log 2>&1
# visuals for every post without an image (18:00 IL) — one line per brand, ~$0.20/image; files are copied to /srv/pulse/otto/assets at once
0 15 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-genvisuals-happygarden.lock python3 genvisuals.py --brand happygarden --limit 12 >> genvisuals.log 2>&1
0 15 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-genvisuals-cmtm.lock python3 genvisuals.py --brand cmtm --limit 12 >> genvisuals.log 2>&1
# reels: render every reel-format post without a video (needs ffmpeg + a TTF font; voice needs otto-secrets/elevenlabs.json)
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-reels.lock sh -c 'for id in $(python3 otto_video.py missing); do python3 otto_video.py render "$id"; done' >> reels.log 2>&1
# publisher: approved posts go out on their slot (needs otto-secrets/meta-<brand>.json per brand)
*/15 * * * * cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-publish.lock python3 otto_publish.py >> publish.log 2>&1
# paid layer: launch approved flights 06:00 IL, guard 06:05, daily Facebook + Google report 07:35 IL
0 3 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-ads-launch.lock python3 otto_ads.py launch >> ads.log 2>&1
5 3 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-ads-guard.lock python3 otto_ads.py guard  >> ads.log 2>&1
35 4 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-ads-report.lock python3 otto_ads.py report >> ads.log 2>&1
# growth ledger 05:10 IL (month over month); 1st of the month also sends last month's review (once — marker in data.json)
10 2 2-31 * * cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-growth.lock python3 otto_growth.py rollup >> growth.log 2>&1
10 2 1 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-growth.lock python3 otto_growth.py rollup --send >> growth.log 2>&1
# weekly competitor sweep (Mon 06:00 IL) — one line per brand
0 3 * * 1    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-competitors-happygarden.lock python3 otto_competitors.py sweep happygarden >> competitors.log 2>&1
0 3 * * 1    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-competitors-cmtm.lock python3 otto_competitors.py sweep cmtm --country IL >> competitors.log 2>&1
# weekly insights + winners (Fri 06:00 IL)
0 3 * * 5    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-insights.lock python3 otto_insights.py >> insights.log 2>&1
# monthly plan for next month (25th, 06:00 IL) — one line per brand; $(date -d '+1 month' +%Y-%m)
0 3 25 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-plan-happygarden.lock python3 otto_plan.py build happygarden $(date -d '+1 month' +\%Y-\%m) >> plan.log 2>&1
0 3 25 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-plan-cmtm.lock python3 otto_plan.py build cmtm $(date -d '+1 month' +\%Y-\%m) >> plan.log 2>&1
# monthly paid plan (25th) — drafts + one "approve the paid plan" card; nothing spends before approval
15 3 25 * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-ads-plan-happygarden.lock python3 otto_ads.py plan happygarden $(date -d '+1 month' +\%Y-\%m) >> ads.log 2>&1
15 3 25 * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-ads-plan-cmtm.lock python3 otto_ads.py plan cmtm $(date -d '+1 month' +\%Y-\%m) --budget 30 >> ads.log 2>&1
```

Agent-side steps that are not cron (they need the LLM): writing copy (`otto_plan.py fill`), rewriting
`edit_requests[]`, completing the ad-library half of the competitor sweep, the Sunday weekly card.
`otto-autopilot/SKILL.md` is the schedule for those.

Telegram button handling is a long-running poller, not a cron — systemd user service:
```ini
# ~/.config/systemd/user/otto-telegram.service
[Unit]
Description=Otto Telegram approval loop
[Service]
WorkingDirectory=/home/ubuntu/.openclaw/workspace-maximus/autopilot/platform
ExecStart=/usr/bin/python3 otto_telegram.py poll
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
```
Reels + ad statics need `ffmpeg`/`ffprobe` and a bold TTF (`apt install ffmpeg fonts-dejavu-core`; or set OTTO_FONT).
Hebrew/Arabic text: if this ffmpeg's drawtext lists `text_shaping` (`ffmpeg -h filter=drawtext`, Ubuntu builds with
libfribidi do) Otto passes `text_shaping=1`; otherwise it pre-reorders RTL lines itself.

Public media: nginx serves `/srv/pulse/otto/` as `https://dash.monyflow.work/otto/` and cannot read the workspace. Every
generated image / ad static / reel is copied to `$OTTO_PUBLIC_ASSETS` (default `/srv/pulse/otto/assets` when it exists)
the moment it is written; the publisher and the ads code refuse media that is not there (clear error, no relative
paths ever reach Meta). The cron user needs write access to that dir. `deploy.sh` still copies the whole assets tree.

Brand settings Otto reads from `data.json brands[]`: `tz` (default `Asia/Jerusalem`; post slots are brand-local),
`currency` (ISO; default the site scan's currency, else EUR — Meta launches refuse a plan whose currency differs from the
ad account's), `countries`, `special_ad_categories` (Meta list), `landing` (url or `{"cold","warm","hot"}`),
`keywords` (`{"brand": [...], "generic": [...]}` — the only keywords Google Search ever uses).
Compliance rules per brand: `brands/<slug>/compliance.json` (`{"banned": [...], "required_disclaimer": ...}`) — checked
before every approval card and every paid launch; violations are held and filed as a recommendation.
Paid holds: `otto_ads.py release <campaign-id>` (after fixing the copy), `otto_ads.py retry <campaign-id>` (failed → approved, resumes).

Paid credentials: `otto-secrets/meta-<brand>.json` + `ad_account_id`/`pixel_id`/`lead_form_id`; `otto-secrets/google-<brand>.json`
{client_id, client_secret, refresh_token, developer_token, customer_id, login_customer_id}.

Needs `otto-secrets/telegram.json` = {"bot_token": "...", "owner_chat_id": "590113904"} (a bot from @BotFather; the owner
must /start it once; optional "owner_user_id" when the chat is not the owner's private chat). Button taps are accepted only
from that user. `systemctl --user enable --now otto-telegram`.

nginx (action API + public peek for the landing). The API trusts **only** `X-Real-IP` for rate limiting, so nginx must
set it (and must not pass the client's own `X-Forwarded-For` through as the identity); add an nginx rate limit in front of
the public path as the first line of defence:
```nginx
# http {}
limit_req_zone $binary_remote_addr zone=ottopeek:10m rate=15r/m;

# server {}
location /otto-peek {
    limit_req zone=ottopeek burst=5 nodelay;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 30s;
    proxy_pass http://127.0.0.1:8161;
}
location /otto-api/ {
    # behind the mm-check auth, as today
    proxy_set_header X-Real-IP $remote_addr;
    proxy_pass http://127.0.0.1:8161;
}
```
`/otto-peek` has no auth; the handler re-validates every redirect hop (http/https, ports 80/443, public IPs only — CGNAT,
link-local/metadata, private and loopback refused; the connection is pinned to the validated IP), runs at most 4 peeks at
once with a 20 s deadline, rate-limits 1 request / 4 s per `X-Real-IP` and caches 1 h. `/otto-api/*` sends no CORS
header; POSTs must be `application/json` from an allowed Origin (`OTTO_ALLOWED_ORIGINS`, default `https://dash.monyflow.work`).
