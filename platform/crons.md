# Otto engine crons (server, UTC; IL = UTC+2/+3)

Run from `autopilot/platform/` with the workspace Python. All scripts write state only through `ap.py`
and are safe to re-run (idempotent per slot / per week).

```cron
# morning briefing 07:30 IL + daily metrics snapshot
30 4 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_watch.py report >> watch.log 2>&1
# hourly guard: drops, missed slots, approvals about to miss their slot
15 * * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_watch.py watch  >> watch.log 2>&1
# approval cards to the owner's Telegram 08:00 IL (posts due within 72 h) + new recommendation cards 18:30 IL
0 5 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_telegram.py send-cards >> telegram.log 2>&1
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_telegram.py send-recs >> telegram.log 2>&1
# visuals for every post without an image (18:00 IL) — one line per brand, ~$0.20/image
0 15 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 genvisuals.py --brand happygarden --limit 12 >> genvisuals.log 2>&1
0 15 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 genvisuals.py --brand cmtm --limit 12 >> genvisuals.log 2>&1
# reels: render every reel-format post without a video (needs ffmpeg + a TTF font; voice needs otto-secrets/elevenlabs.json)
30 15 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && for id in $(python3 -c "import ap;d=ap.load();print(' '.join(p['id'] for p in d['posts'] if p.get('format')=='reel' and not p.get('video') and p['status'] in ('draft','pending_approval')))"); do python3 otto_video.py render $id >> reels.log 2>&1; done
# publisher: approved posts go out on their slot (needs otto-secrets/meta-<brand>.json per brand)
*/15 * * * * cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_publish.py >> publish.log 2>&1
# paid layer: launch approved flights 06:00 IL, guard 06:05, daily Facebook + Google report 07:35 IL
0 3 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_ads.py launch >> ads.log 2>&1
5 3 * * *    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_ads.py guard  >> ads.log 2>&1
35 4 * * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_ads.py report >> ads.log 2>&1
# growth ledger 05:10 IL (month over month); 1st of the month also sends the month-in-review
10 2 2-31 * * cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_growth.py rollup >> growth.log 2>&1
10 2 1 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_growth.py rollup --send >> growth.log 2>&1
# weekly competitor sweep (Mon 06:00 IL) — one line per brand
0 3 * * 1    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_competitors.py sweep happygarden >> competitors.log 2>&1
0 3 * * 1    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_competitors.py sweep cmtm --country IL >> competitors.log 2>&1
# weekly insights + winners (Fri 06:00 IL)
0 3 * * 5    cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_insights.py >> insights.log 2>&1
# monthly plan for next month (25th, 06:00 IL) — one line per brand; $(date -d '+1 month' +%Y-%m)
0 3 25 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_plan.py build happygarden $(date -d '+1 month' +\%Y-\%m) >> plan.log 2>&1
0 3 25 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_plan.py build cmtm $(date -d '+1 month' +\%Y-\%m) >> plan.log 2>&1
# monthly paid plan (25th) — drafts + one "approve the paid plan" card; nothing spends before approval
15 3 25 * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_ads.py plan happygarden $(date -d '+1 month' +\%Y-\%m) >> ads.log 2>&1
15 3 25 * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && python3 otto_ads.py plan cmtm $(date -d '+1 month' +\%Y-\%m) --budget 30 >> ads.log 2>&1
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

Paid credentials: `otto-secrets/meta-<brand>.json` + `ad_account_id`/`pixel_id`/`lead_form_id`; `otto-secrets/google-<brand>.json`
{client_id, client_secret, refresh_token, developer_token, customer_id, login_customer_id}.

Needs `otto-secrets/telegram.json` = {"bot_token": "...", "owner_chat_id": "590113904"} (a bot from @BotFather; the owner
must /start it once). `systemctl --user enable --now otto-telegram`.

nginx (public peek for the landing): `location /otto-peek { proxy_pass http://127.0.0.1:8161; }` —
no auth on this path; the handler is SSRF-guarded, rate-limited and cached.
