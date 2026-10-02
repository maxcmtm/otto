# Otto engine jobs (the old crontab below is in UTC; IL = UTC+2/+3)

**New server (Hetzner, infra/):** one systemd timer per job runs `platform/otto_cron.py <job>`, which runs the job for every
brand that needs it — a new client needs no server change. The schedule is the table in `otto_cron.JOBS` (the timer files in
`infra/systemd/otto-job-*.timer` are generated from it: `python3 platform/otto_cron.py timers infra/systemd`; a test fails
when they drift). Each run writes a heartbeat to `heartbeats.json` next to data.json (the owner console's System section) and
a failed run sends a Telegram alert (`otto-alert@.service`). Runbook: `infra/README.md`.

Wall-clock jobs run on **local** time — a client's at its own clock (`brands[].tz`), the owner's at `OTTO_OWNER_TZ` — so
summer/winter time and clients abroad need nothing. Their timers tick hourly; each tick runs whoever's local time has reached
the job's time today and has not had its run yet that day (a tick up to 3 h late still counts; each brand runs once per local
day, success or not — a failure alerts and `otto run <job> --brand B` repeats it by hand).

| job | when | runs | for |
|---|---|---|---|
| `publish` | every 15 min | `otto_publish.py --brand B` (slots are brand-local already) | each active brand · kill switch |
| `watch` | hourly :15 | `otto_watch.py watch` | once |
| `watch-report` | 07:30 owner | `otto_watch.py snapshot` (the daily metrics snapshot the drop alerts and the growth ledger read) | once |
| `morning-report` | 07:35 brand | `otto_report.py send --brand B` — **the 7:35 message**: yesterday's posts and their numbers, paid spend vs budget with results (plans with paid ads), today's posts, and every decision waiting, in the brand's language. By e-mail it is one e-mail with the approvals inside (the same one-tap links as the digest); in Telegram the report is followed by the cards. Once per brand per local day (`.report-state.json`) | each active brand whose approvals include e-mail or Telegram, on a plan with reports |
| `cards` | 08:00 brand | `otto_telegram.py send-cards --brand B` (catch-up: the 07:35 report already sent the cards it could) | each active brand |
| `recs` | 18:30 owner | `otto_telegram.py send-recs` (recommendation cards go to the owner) | once |
| `email-cards` | 08:00 brand | `otto_email.py send-cards --brand B` (catch-up digest: only posts the 07:35 report e-mail did not carry — normally nothing) | each active brand whose approvals include e-mail |
| `email-recs` | 18:30 brand | `otto_email.py send-recs --brand B` (the monthly paid-plan card + P0/P1 recommendations) | each active brand whose approvals include e-mail |
| `genvisuals` | 18:00 brand | `genvisuals.py --brand B --limit 12` | each active brand |
| `reels` | 18:30 brand | `otto_video.py missing --brand B` → `render <id>` per id | each active brand |
| `ads-launch` | 06:00 brand | `otto_ads.py launch --brand B` | each active brand · kill switch |
| `ads-guard` | 06:05 owner | `otto_ads.py guard` | once (runs under the kill switch too) |
| `ads-report` | 07:15 brand | `otto_ads.py report --brand B [--no-send]` (yesterday's paid numbers for the 07:35 report; `--no-send` when the brand's Telegram report carries them) | each active brand |
| `growth` | 05:10 owner | `otto_growth.py rollup` (+ `--send` on the owner's days 1–3; the month marker sends it once) | once |
| `competitors` | Mon 06:00 brand | `otto_competitors.py sweep B [--country C]` | each active brand with a competitor list |
| `insights` | Fri 06:00 brand | `otto_insights.py --brand B` | each active brand |
| `plan-month` | 25th 06:00 brand | `otto_plan.py build B <the brand's next month>` | each active brand not planned yet |
| `ads-plan` | 25th 06:15 brand | `otto_ads.py plan B <next month> [--budget N]` | each active brand not planned yet, with an ad budget |
| `whop-sync` | 02:20 UTC | `otto_whop.py backfill` | once, when api_key + company_id exist (LEGACY: the founding seats sold on Whop; Stripe needs no sync — its webhook is the source of truth) |
| `track-prune` | 1st 04:00 UTC | `otto_track.py prune --days 400` | once |
| `retention` | 04:40 owner | `otto_retention.py run` (client data 90 days after the plan ended, owner notices 14 and 3 days before, export first; exports after 30 days; leads after `OTTO_LEAD_RETENTION_DAYS`) | once (the kill switch does not stop it) |
| `trials` | hourly :05 UTC | `otto_trial.py run` (free trials: a trial that ended without a card → plan `none`; the day-5 / day-7 / day-8 e-mails, once each; idle accounts without a brand after 90 days; a new trial's first week still unwritten 15 min after its kickoff is written inline, and cards the kickoff's background run left pending are rendered) | once (the kill switch does not stop it) |
| `copy` | 05:30 brand | `otto_copy.py daily --brand B` — the AI copywriter (Claude API, `anthropic.json`): every draft slot in the next 7 days gets copy + its rendered card and goes to `pending_approval` before the 07:35 report; a post failing compliance / the no-invention guard twice stays a draft with an owner card. Without a key it does nothing (the console's Setup says so) | each active brand with organic content (`brands[].cron.off: ["copy"]` keeps a brand hand-written) |

"Active" = `brands[].status == "active"` (or no status); onboarding and paused brands (`brands[].paused` / status `paused`) are
skipped and the heartbeat says why. A sign-up leaves "onboarding" when a running subscription is linked to it (a Stripe checkout
links itself by its signed reference, `otto_billing.link` / the console's link: the brand gets its plan and status "active"). A Google sign-up's first brand starts "active" on the free trial
(`otto_trial`): its jobs run for 7 days, `ads-launch` sits out ("plan trial plans and previews paid ads but launches none"). Plans (`plans.json`, `otto_cron.PLAN_GATES`): a brand whose plan lacks a job's feature sits it
out with the reason — `ads-plan` / `ads-launch` / `ads-report` say "plan content has no paid ads", likewise reels, Telegram cards,
insights, visuals and the monthly plan; a monthly competitor sweep runs on the first Monday of the month only; a brand on plan
`none` (membership ended) sits every job out. Approvals channel (`brands[].approvals`, `otto_cron.CHANNEL_GATES`): `cards` runs
for brands whose approvals include Telegram (no field = Telegram, as before), `email-cards` / `email-recs` for brands whose approvals
include e-mail, `morning-report` for either; "app" sends nothing — the heartbeat says "approvals by email" / "approvals in the app only". `ads-guard` runs for everyone and pauses live campaigns a plan no longer covers. Per-brand overrides in `brands[].cron`: `{"off": [jobs], "ads_budget": 30, "country": "IL",
"visuals_limit": 12, "per_week": 12}` — e.g. the old `cmtm` lines become `"countries": ["IL"]` (or `cron.country`) and
`"cron": {"ads_budget": 30}`. By hand: `otto run <job>` (every active brand, now) or `otto run <job> --brand B`;
`python3 otto_cron.py <job> --dry` prints what a tick would run now; `otto_cron.py status` shows the heartbeats. Every job still
only writes through `ap.transaction()`; one run per job at a time (flock on `locks/<job>.lock`, a second run exits 75). Child
output goes to the same log files as before (publish.log, ads.log, …); logrotate rotates `/var/lib/otto/*.log` weekly.

## Old box (AWS, until the cut-over): the crontab

Run from `autopilot/platform/` with the workspace Python. All scripts write state only through `ap.transaction()`
(exclusive `flock` on `data.json.lock`, fresh load, atomic temp-file + `os.replace` write), and every job line is wrapped
in `flock -n /tmp/otto-<job>.lock` so a slow run is never overlapped by the next one (the overlapping run just exits).

What "safe to re-run" really means per job:
- **Idempotent** (re-running changes nothing new): `otto_publish.py` (a post is `publishing` before the Meta call and a
  post stuck in `publishing` is never retried — it raises a P0 instead), `otto_telegram.py send-cards` / `send-recs`
  (only items without a card; send-cards also claims each post in data.json before sending, so even two runs at once
  send one card), `otto_ads.py launch` (resumes from `campaign.remote`, never recreates objects; a flight is claimed —
  `launching_at` — before any Meta call, so a second run at the same time skips it),
  `otto_ads.py plan` and `otto_plan.py build` (refuse a month that exists), `otto_insights.py` and `otto_competitors.py`
  (no duplicate *proposed* recommendation with the same title/brand), `otto_growth.py rollup --send` (once per month:
  `markers.growth_review_sent`, claimed with `markers.growth_review_sending` while it is on its way), `otto_ads.py guard`
  (marks `ended` only after the pause succeeded). The `flock -n` wrappers stay: they are the first line of defence.
- **Once per local day**: `otto_report.py send` (the 07:35 report; `otto_watch.py report` sends the same Telegram report by hand)
  claims each channel in `.report-state.json` first — a second run that day sends nothing (`--force` resends).
- **Not idempotent**: `otto_ads.py report` without `--no-send` sends a Telegram message on every run;
  `genvisuals.py` / `otto_video.py render` spend money (they only work on posts that still lack an image / video, but a
  second run while the first is still generating would pay twice — that is what the flock prevents).

```cron
# OLD BOX ONLY (crontab, one line per brand) — replaced on the new server by otto_cron.py + systemd timers
# morning briefing 07:30 IL + daily metrics snapshot
30 4 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-watch-report.lock python3 otto_watch.py report >> watch.log 2>&1
# hourly guard: drops, missed slots, approvals about to miss their slot, posts stuck in "publishing"
15 * * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-watch.lock python3 otto_watch.py watch  >> watch.log 2>&1
# approval cards to the owner's Telegram 08:00 IL (posts due within 72 h; compliance-checked first) + new recommendation cards 18:30 IL
0 5 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-cards.lock python3 otto_telegram.py send-cards >> telegram.log 2>&1
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-recs.lock python3 otto_telegram.py send-recs >> telegram.log 2>&1
# approval e-mails (brands whose brands[].approvals include "email"): digest 08:00 IL, paid-plan card + recommendations 18:30 IL
0 5 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-email-cards.lock python3 otto_email.py send-cards >> email.log 2>&1
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-email-recs.lock python3 otto_email.py send-recs >> email.log 2>&1
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

Copy for planned posts is written by the engine itself now (`otto_copy.py`, the `copy` job and the trial kickoff); an agent
only reviews it and fixes what the copywriter held. Agent-side steps that are still not cron (they need the LLM): rewriting
`edit_requests[]`, the ad matrix copy, completing the ad-library half of the competitor sweep, the Sunday weekly card.
`otto-autopilot/SKILL.md` is the schedule for those.

Telegram button handling is a long-running poller, not a cron. New server: `infra/systemd/otto-telegram.service` (system
unit, starts once `/etc/otto/secrets/telegram.json` exists). Old box — systemd user service:
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

Brand settings Otto reads from `data.json brands[]`: `tz` (default `Asia/Jerusalem`; post slots are brand-local —
`ap.py brand-add` fills `tz` and `countries` from the url's country TLD, then the language; `--tz/--countries/--currency` override),
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
from that user. That owner chat also receives the `otto_watch` morning report and alerts (the OpenClaw CLI is only the
fallback when there is no bot config). `systemctl --user enable --now otto-telegram`.

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

Owner console (`admin.html`, `otto_admin.py`): the public `/otto-track` (landing analytics) and `/otto-api/whop` (legacy Whop
webhook) nginx locations, the optional Whop backfill + analytics prune crons, and the secrets shape are in `docs/ADMIN.md`;
Stripe billing (`/hooks/stripe`, `/billing/*`, `stripe.json`) is in `docs/BILLING.md`.
