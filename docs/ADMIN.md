# Otto owner console — deploy notes

Date: 2026-09-29 · Page: `platform/admin.html` → `https://dash.monyflow.work/otto/admin.html` · Data: `platform/otto_admin.py`

One page for our side of the business: landing traffic and the funnel, leads, customers and revenue (Stripe, plus the legacy Whop founders), every client brand's
health, system health, and the controls (global kill switch, pause a brand, approve / reject a campaign, re-run a scan, lead
status). Opened as a file, or when the API cannot be reached, it shows a bundled sample (invented businesses on `.example`
domains) and says "Sample data".

## What is new on the API (`otto_api.py`, 127.0.0.1:8161)

| Route | Access | What |
|---|---|---|
| `POST /otto-track` | **public** | landing analytics beacon (`otto_track.py`) → 204 |
| `POST /hooks/stripe` | **public** (Stripe → us; Caddy, apex only) | Stripe webhook (`otto_stripe.py`); the Stripe-Signature HMAC is the authentication — `docs/BILLING.md` |
| `/billing/*` | Google session (app.) | the client's Billing page API (`otto_stripe.py`) — `docs/BILLING.md` |
| `POST /otto-api/whop` | **public** (Whop → us; Caddy `/hooks/whop`) | LEGACY Whop webhook for the founding seats sold on Whop (`otto_whop.py`); the Standard Webhooks signature is the authentication |
| `GET /otto-api/admin/snapshot?days=7\|30\|90` | behind app auth | the console's JSON (cached 15 s) |
| `POST /otto-api/admin` | behind app auth, JSON + Origin rules of `/otto-api/action` | controls, logged to `actions.log` as `admin <who> <action> …` |
| `GET/POST /otto-email/act?t=…` | **public** (the signed link is the credential) | one-tap approval page from an approval e-mail (`otto_email.py`) — GET shows, only the page's POST acts |
| `POST /otto-api/action {"kind":"brand","id":…,"approvals":"email\|telegram\|app"}` | app auth, tenant-scoped | the client's "Approvals by" choice in Settings |

Restart the API after `git pull` + `deploy.sh`: `systemctl --user restart otto-api`.

## nginx

```nginx
# http {}
limit_req_zone $binary_remote_addr zone=ottotrack:10m rate=120r/m;
limit_req_zone $binary_remote_addr zone=ottowhop:1m  rate=60r/m;

# server {}  — exact-match locations win over the authenticated `location /otto-api/` prefix
location = /otto-track {
    limit_req zone=ottotrack burst=40 nodelay;
    limit_except POST { deny all; }
    client_max_body_size 4k;
    proxy_set_header X-Real-IP $remote_addr;            # the API trusts only this header; it is hashed, never stored
    # proxy_set_header X-Country $geoip2_data_country_code;   # only if the GeoIP2 module is installed (optional)
    proxy_pass http://127.0.0.1:8161;
}
location = /otto-api/whop {
    # public on purpose: Whop calls it server to server. No auth_request here; the handler verifies Whop's signature,
    # refuses anything older than 5 minutes and processes each event id once.
    limit_req zone=ottowhop burst=20 nodelay;
    limit_except POST { deny all; }
    client_max_body_size 256k;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_pass http://127.0.0.1:8161;
}
```

- `admin.html` is copied by `deploy.sh` to `/srv/pulse/otto/admin.html`, so it sits under `/otto/` behind the same mm-check
  magic-link auth as the app. `/otto/assets/` is public (Meta fetches media there); check the auth exception does not cover
  `/otto/admin.html`. If in doubt, add `location = /otto/admin.html { <the same auth lines as location /otto/>; }`.
- `/otto-api/admin*` is covered by the existing authenticated `location /otto-api/`. Also add to that location
  `proxy_set_header X-Otto-User <the user variable mm-check exposes>;` (or `proxy_set_header X-Otto-User "";` if it exposes
  none) so a browser can never choose the name that goes into the audit log.
- Owner-only access (once clients get app logins): set `OTTO_ADMIN_USERS=max,…` in the otto-api service environment; then the
  `X-Otto-User` nginx passes must be on that list for every `/otto-api/admin*` call.
- `/otto-track` and `/otto-api/whop` must not inherit a server-level `auth_request`.

## Billing: Stripe (and the legacy Whop founders)

New customers pay with Stripe on Otto's own Billing page; every step for Max (keys, prices, Stripe Tax, webhook, branding,
test-mode run-through) is in **`docs/BILLING.md`**. Without `otto-secrets/stripe.json` nothing breaks: every billing screen
says "Payments aren't set up yet", `/billing/*` answers 503 and the webhook 503.

Console:
- **Customers and billing**: MRR / ARR / ARPU / churn / LTV / revenue from `otto_billing` (Stripe subscriptions: monthly at
  their price, yearly at a twelfth; one-time seats add 0; trialing = paid during Otto's trial, first charge at its end). The
  Customers table lists the Stripe customers (plan, interval, pending change, next charge or first charge, cancels, failed
  payments, brand). A paid checkout links itself to the brand it was bought for (our signed reference); the row's drawer keeps
  a **manual link** for edge cases (a payment made outside the app): `{"action": "link_customer", "customer": "sub_…",
  "brand": …}` — adds the payer as a member and sets the plan. **Legacy Whop founders** are a read-only list (no Whop sync or
  link UI any more; `python3 otto_whop.py link|backfill` still works from the shell).
- **Setup**: Stripe keys (test / live), Stripe webhook (URL with a Copy button, last event), Stripe prices (which public plans
  are on sale, problems from the last check), Stripe Tax, branding of invoices / receipts, the optional Customer Portal
  fallback, legacy Whop founders.
- **Controls → Check Stripe setup** (`{"action": "stripe_check"}` → `otto_stripe.py check` in the background, read-only):
  account currency, Stripe Tax status, every price in plans.json (active, EUR, interval, tax behaviour, amount = plans.json),
  the webhook endpoint and its events, branding → `billing.json` `stripe_check`, shown in Setup.
- Past due: one owner card per failed invoice ("<brand>: payment failed"); the client sees a banner in the app and on the
  Billing page. After Stripe's last retry the subscription is canceled → the brand moves to no plan with the usual card.

The legacy Whop webhook (`https://<domain>/hooks/whop`, `otto-secrets/whop.json` `"otto_webhook_secret"`) stays so refunds and
status changes of the founding seats sold on Whop keep arriving; `otto_whop.PLANS` knows the founding plan
`plan_joHl1qsZoiJc9` (€197 one-time, adds 0 to MRR). No Whop checkout is offered anywhere.

## Files and env (all next to data.json on the server, git-ignored)

| File | Env | What |
|---|---|---|
| `events.jsonl` | `OTTO_EVENTS`, `OTTO_EVENTS_MAX_MB` (512) | one line per landing event; stops growing at the cap |
| `.track-salt` | — | today's random salt for visitor ids (600, replaced every UTC day) |
| `billing.json` | `OTTO_BILLING` | customers / subscriptions of every provider (`provider` stripe \| whop; records without it are Whop), payments, brand → Stripe customer accounts, processed event ids, the last Stripe setup check (600) |
| `.billing-ref-secret` | — | the key that signs our checkout references when `stripe.json` has no `ref_secret` (600, generated once) |
| `leads.json` | `OTTO_LEADS` | lead status + notes from the console (600) |
| `copy-usage.json` | `OTTO_COPY_LEDGER` | the AI copywriter's usage per UTC day and per brand (calls, tokens, cache, estimated USD) and each brand's last run — the daily caps are claimed here before every Claude API call; Setup → "AI copywriter" shows today's line (45 days kept) |
| `copy.log` | — | the copywriter's output: the daily `copy` job and the trial kickoff's background runs (`otto_copy.py week`) |
| `api-errors.log`, `scan.log`, `whop.log`, `stripe.log` | — | API 500s / refused webhooks / Stripe's own error messages (never a body), background re-scans, Whop syncs, Stripe setup checks |

Billing and lead notes are deliberately **not** in `data.json`: the client app reads `data.json` and embeds it in `index.html`.
The snapshot masks e-mails (`a•••@domain`) and reports which `otto-secrets/*.json` exist, never their contents.

## Privacy (landing analytics)

No cookies, no local storage, no third-party script. The beacon sends the path, referrer host, `utm_*`, device class, and events
(scroll 25/50/75/100, sections seen, button clicks, scan start/result with the domain typed, FAQ opens, film plays). The API
keeps `sha256(daily salt + IP + user agent)[:16]` as the visitor id; the IP is never written. Do Not Track or Global Privacy
Control → one anonymous page view and nothing else (enforced by the page and again by the server). Validation: allowlisted
events and fields, ≤ 4 KB, ≤ 20 events per request, e-mail-like utm values dropped, 60 events/min per client, 3,000/min overall.

"Reached onboarding" counts a page view whose path contains `onboarding`. `onboarding.html` is being rebuilt by the onboarding
work, so it has no beacon yet; one line in it is enough (same endpoint, same privacy rules):

```html
<script>(function(n,L){var o={p:L.pathname.replace(/[^A-Za-z0-9\/._~-]/g,'').slice(0,120),ev:[{e:'view'}]};if(n.doNotTrack==='1'||n.globalPrivacyControl===true)o.anon=1;try{n.sendBeacon('/otto-track',JSON.stringify(o))}catch(e){}})(navigator,location);</script>
```

## Crons (optional)

```cron
# LEGACY: safety net for missed Whop webhooks of the founding seats (only does anything once api_key + company_id are in whop.json)
20 2 * * *  cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-whop.lock python3 otto_whop.py backfill >> whop.log 2>&1
# keep about a year of landing events
0 4 1 * *   cd /home/ubuntu/.openclaw/workspace-maximus/autopilot/platform && flock -n /tmp/otto-track.lock python3 otto_track.py prune --days 400 >> track.log 2>&1
```

## Approval e-mails (`platform/otto_email.py`)

The launch markets (Netherlands, Ireland) mostly do not use Telegram, so approvals also go out by e-mail.
`brands[].approvals` is `"email"`, `"telegram"`, `"app"` (nothing pushed; everything waits in Review) or `["email","telegram"]`.
A brand without the field is a brand from before this feature: Telegram, unchanged. Onboarding writes `"email"` unless the
client picks otherwise; the client changes it in the app (Settings → Approvals), the owner with
`python3 otto_email.py channel <brand> email|telegram|app|email,telegram`.

- **07:35 brand time** (`morning-report` job, `otto_report.py`): the morning report — yesterday's posts and numbers, paid
  spend vs budget, today's posts — with every post due for approval inside it (same cards, same one-tap links, same claim
  as below), the paid-plan card and P0/P1 recommendations. One e-mail per approver, in the brand's language (`otto_i18n`).
- **08:00 brand time** (`email-cards` job, catch-up): one digest per brand with every post due within 72 h that has not been e-mailed (normally none — the 07:35 report carried them), the
  same selection as the Telegram cards (compliance-checked first; each post is claimed in data.json before anything is sent, so
  two runs never send it twice). Per post: its hosted image, platform, slot in the brand's time, hook, caption, and Approve · Skip
  (one-tap) · Change (opens the post in the app), plus "Review all in the app".
- **18:30 brand time** (`email-recs` job): the monthly paid-plan card ("Approve the November paid plan", with its campaigns) as its
  own e-mail, and the brand's other client-visible P0/P1 recommendations in one e-mail (Approve · Not now).
- **Who gets it:** `brands[].approvers` when present, else `brands[].members`; `@domain` entries cannot be mailed and are skipped.
  Each person gets their own copy (the buttons are signed for them).
- **The links:** HMAC-SHA256 over brand, item, action, a keyed hash of the recipient (never the address), 72-hour expiry and a
  nonce. Opening one only shows a confirmation page (mail scanners prefetch links); its button POSTs back, the nonce is burned
  (single use), the recipient must still be an approver of that brand, and the decision goes through `ap.decide(via="email")` —
  status transition + taste log, like the dashboard and Telegram (posts only while draft / pending approval; the paid plan runs
  `otto_ads.approve(via="email")`). Expired, used or foreign links get a calm page with a link to the app.

`otto-secrets/email.json` (mode 600; nothing in it is ever logged — addresses are masked as `a•••@domain`):

```json
{"link_secret": "<python3 -c 'import secrets; print(secrets.token_hex(32))'>",
 "from": "Otto <approvals@otto.example>", "reply_to": "hello@otto.example",
 "host": "smtp.example.com", "port": 587, "user": "…", "pass": "…"}
```

SMTP requires STARTTLS (or `"tls": "ssl"` on port 465) and refuses to log in without it. Instead of SMTP: `"provider": "postmark"`
(server token as `"api_key"`; open and link tracking are switched off per message) or `"provider": "resend"` (`"api_key"`; keep
open / click tracking off for the domain in Resend — link tracking would rewrite the one-tap links). Postmark / Resend bounces are
pulled at most hourly (`otto_email.py bounces` does it now); a hard bounce or a complaint stops mail to that address until
`otto_email.py unsuppress <address>`. Rotating `link_secret`: move the old one into `"previous_link_secrets": [...]` for 72 h.
Optional `"app_url"` / `"action_base"` override where links point (default `https://app.<OTTO_DOMAIN>/` and `https://<OTTO_DOMAIN>`;
on the old box `https://dash.monyflow.work/otto/` and `https://dash.monyflow.work`).

Nothing configured yet → every e-mail is written as an `.eml` file into `outbox/` next to data.json (`OTTO_OUTBOX`; directory 700,
files 600 because they hold working links) and the console shows how many are waiting. Without `link_secret` a random one is
generated once into `.email-link-secret` next to data.json. Preview without sending: `otto_email.py preview --brand <id>
[--kind digest|recs|plan] --out /tmp/x.html`; what a run would send: `otto_email.py send-cards --brand <id> --dry`.

Console: Clients → the "Email" dot next to Meta / Google / Telegram (green = a transport, recipients, no error, no bounce); the
drill-down's **Approvals** block: channel, recipients (masked), last digest / recommendations / paid-plan e-mail, the last error,
bounces, the outbox; the brand's issues say when e-mails cannot arrive. Setup → "Approval e-mails".

Old box (nginx): the route must not sit behind the mm-check auth.

```nginx
limit_req_zone $binary_remote_addr zone=ottoemail:1m rate=30r/m;      # http {}
location = /otto-email/act {                                          # server {}
    limit_req zone=ottoemail burst=20 nodelay;
    limit_except GET POST { deny all; }
    client_max_body_size 4k;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_pass http://127.0.0.1:8161;
}
```

New server: `infra/Caddyfile` serves it on the apex (no Access login) and the Cloudflare rate-limit rule lists the path.

## Kill switch

`data.json controls.publishing_paused` (global) and `brands[].paused` (one brand), set from the console or
`otto_admin.py kill on|off`, `otto_admin.py pause|resume <brand>`. Checked by `ap.paused()` in `otto_publish.run` (before
anything, per post, and again right before the call that makes a post public) and at the top of `otto_ads.launch`. Posts whose
slot passes while paused are not sent late: after resume the publisher marks them missed (grace 3 h) so they get rescheduled.
Both the global switch and pausing a brand also pause live campaigns on Meta / Google; a failed pause leaves the campaign
live and files a P0 recommendation "Pause campaign … by hand", and pressing the switch again retries. Campaigns the switch
paused are marked `paused_by: "kill_switch"`; turning it off resumes only those (never campaigns paused by hand or with their
brand), marks flights that ended meanwhile as ended, and files a P1 "Resume campaign … by hand" if a resume fails.
`otto_ads.launch` re-checks the switch right before each campaign, so nothing starts while it is being flipped.

## Plans (`platform/plans.json`)

What each client brand gets comes from `plans.json` — plans `starter`, `growth`, `scale`, `agency`, `founding`, the non-public
`content` fallback and `none` — with features (organic, stories, reels, Meta / Google ads, ad matrix, video ads, creator briefs,
competitor sweep monthly | weekly, reports, Telegram, multi-brand), per-brand limits (posts and reels a month, ad-matrix preset,
the ad-spend band, video ads a month, weekly refresh) and prices. Prices are drafts (`"status": "draft"`) until Max approves them
(research/EU-LAUNCH-AND-PRICING-2026-09.md §4); the landing is not wired to the file. Edit it on the server and it applies on the
next read — a file that does not validate is refused as a whole (Setup shows why): every brand then runs organic only, nothing
paid is planned or launched, live campaigns are left alone, and a P0 card asks to fix it.

- `brands[].plan` — none on the record (a brand from before plans) runs as `founding` (Growth during the pilot). Onboarding and
  `ap.py brand-add` write `starter`, flagged `plan_billing: "not_billed"` while no price sells Starter (`stripe_price_ids`);
  a linked running subscription sets the plan from `stripe_price_ids` (legacy Whop: `whop_plan_ids`) and clears the flag. A
  canceled / unpaid subscription (or an ended legacy membership) moves the brand to `none`:
  publishing and ad launches pause for it, live campaigns are paused, nothing is deleted, one owner card says so. A domain match
  shown in Customers never changes a plan — only an explicit link does.
- `brands[].plan_until` (YYYY-MM-DD, optional) — after it the brand runs as `content` and the daily guard files one owner card.
- Ad spend band (`ad_spend_managed_eur_month`) is a soft cap: the first month above it is planned in full and the plan card says
  so; the second month in a row is planned at the cap and the card offers the next plan. Scale is never capped: above €15,000
  the card and the console show 2 % of the excess (computed, never charged automatically). `brands[].ad_band` keeps the months.
- Console: Clients shows each brand's plan under its status; the drill-down has usage bars (posts, reels, paid budget against the
  plan), what is included, the soft-cap / overage / not-billed notes, and "Change plan" (plan + optional end date + note,
  confirmed in the page). `POST /otto-api/admin {"action":"plan","brand":…,"plan":…,"until":"YYYY-MM-DD"|"","note":…}` or
  `otto_admin.py plan <brand> <plan> [--until …] [--note …]`: validated against plans.json, logged as `admin <who> plan <brand>
  <from> -> <to> …` and in `brands[].plan_history`. A plan that no longer covers a brand's live campaigns pauses them now (Meta /
  Google, `paused_by: "plan"`); the kill switch's resume leaves those paused.
- Client app: Settings → Plan shows the plan, what is included and this month's use; a plan without paid ads gets one quiet
  "Add paid campaigns" link to the landing's #pricing. Owner-side fields (`plan_history`, `plan_billing`, `ad_band`) never reach
  the client.

## CLI

```
python3 otto_admin.py snapshot [--json] [--days 30]
python3 otto_admin.py sample --embed            # refresh the sample bundled in admin.html
python3 otto_stripe.py status | check | replay <event.json>
python3 otto_billing.py customers [--json] | link <customer id> <brand>   # every provider; link also sets the brand's plan
python3 otto_whop.py status | customers | backfill [--dry] | link <mem_id> <brand>   # LEGACY founders
python3 otto_admin.py plan <brand> <plan> [--until YYYY-MM-DD] [--note "…"] | plans
python3 ap.py plans                             # every plan and every brand's resolved plan
python3 otto_track.py tail 20 | prune --days 400
```

Tests: `platform/tests/test_email.py` (digest selection + claims, tokens, the one-tap page, recommendations, SMTP / Postmark /
Resend / outbox transports, rendering, cron gating, the Settings action, console fields), `platform/tests/test_admin.py` (tracking validation, rate limit, no raw IP, DNT; legacy Whop signature + events → customers +
backfill; snapshot on a fixture; Stripe setup items; kill switch in publish + ads launch; admin auth / origin / transitions),
`platform/tests/test_stripe.py` (Stripe billing end to end against a fake Stripe, incl. the console) and
`platform/tests/test_plans.py` (plan resolution, expiry, cron gates, paid refusals, soft band + overage, Whop mapping incl.
cancellation, the plan action and snapshot).
