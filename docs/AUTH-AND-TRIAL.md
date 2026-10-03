# Sign in with Google, the free 7-day trial, and "add a card"

Max, 30.09.2026: "I want a free 7-day trial for new sign-ups; the option to log in with Gmail (Google auth) and open a user;
after 7 days they should place a credit card."

This is how it works, what is stored, and what Max has to set up (Google Cloud here, Stripe in `docs/BILLING.md`). Since
1 Oct 2026 clients pay with Stripe on Otto's own Billing page; Whop is legacy (the founding seats already sold on it).

## The client's path

1. **Landing → "Start free 7-day trial".** The button goes to `https://app.<domain>/auth/google/start?next=/onboarding.html?site=<the
   scanned domain>`, so the scan the visitor just ran carries over.
2. **Google.** The visitor picks a Google account. Otto asks for `openid email profile` only: the e-mail address (verified by
   Google), the name and the Google account id. No access to Gmail, Drive or anything else, and no profile picture is stored.
3. **Account + trial.** The first sign-in creates the account (data.json `users[]`) and starts the trial clock: 7 days from that
   moment, no card. A returning sign-in finds the same account (by Google account id, else by e-mail).
4. **Onboarding.** The first brand the account sets up runs on the **trial plan** until the trial ends: Starter's organic posts,
   stories, reels, the monthly competitor sweep and reports all run for real (status "active"). Paid ads are previewed: the
   month's ad matrix is planned and written (below) so the client sees them, but no campaign launches (`ads_launch: false`),
   and video ads are capped at 3 previews.

   **The first week, written for them.** Onboarding plans the trial's weeks on the spot (`otto_trial.kickoff`) and starts
   the AI copywriter in the background (`otto_copy.py week`, the request does not wait). Within minutes every post of the next
   7 days has real copy from the Claude API (the site's own products, prices, reviews and voice, in the language of the
   market), checked by Otto's compliance rules and its no-invention guard, rewritten once when a check fails; its card is
   rendered in the brand's look on the site's photos (by the next hourly `trials` job when the API process cannot start
   headless Chrome). The posts wait in the app's Review, and **the next morning at 07:35 the first ones arrive by e-mail** with
   one-tap Approve · Skip · Change. A post that still fails a check stays a draft for the Otto team (owner card "Copy held for
   review"), never in front of the client. Without an Anthropic key nothing is generated and the owner card "New trial: write
   the first week for X" is the manual fallback.
   The client watches it honestly (`otto_progress` → `/otto-api/data` `brands[].work` + `posts[].work`): onboarding's last
   step and the app say "Otto is writing your first week" with an n-of-N bar and an ETA only while a run really writes (the
   app polls every ~10 s, backing off to 60 s), "Ready by 15:05" when the next automatic run will do it, and "The Otto team
   is preparing your first week" — no spinner — when nothing automatic will (no key); then, once, "Your first week is ready
   to review".

   **Its ads, written too.** Right after the first week of posts (in the same background run: `otto_copy.finish_trial` →
   `trial_ads`) the copywriter writes the ads the trial previews: the brand's ad concepts (`angles.json`, one per angle family
   of Starter's micro matrix — pain, identity, enemy, offer — from the site, the strategy and the competitor list, each with
   its headline, primary text and description), the trial month's ad matrix (planned on the spot when the month has none: 4
   concepts × 5 styles) and every concept's and visual's copy — headlines, primary texts, the words on each image, the
   faceless videos' beats — through the same compliance and no-invention checks as the posts (a part that still fails is
   held for the Otto team: owner card "Ad copy held for review"). Nothing launches during the trial; once a card is on file,
   the next paid plan (the 25th) plans the campaigns and the copywriter writes that month's copy the moment it is planned.
5. **During the trial** the app shows one calm line: "N days left in your trial · Add a card". E-mails (to the Google address):
   - 2 days before the end: "2 days left in your Otto trial"
   - in the last 24 hours: "Your Otto trial ends today" (or "tomorrow", by the local clock)
   - after the end: "Your Otto trial has ended — <brand> is paused … your work is kept for 90 days"
   Each goes out once. Nothing is ever charged automatically: there is no card on file.
6. **The end.** On the hour (the `trials` job runs hourly), a trial brand without a paid plan moves to the ended plan
   (`none`): publishing and ads pause, the owner gets a card, the data is kept. The app shows the "add a card" screen instead
   of the data (the API answers 402). After 90 days without a plan, `otto_retention` deletes the brand (owner notices 14 and 3
   days before, a zip export first) — the 90 days count from the trial's end.
7. **Add a card.** The screen (and the reminder e-mails' button) opens Otto's own Billing page,
   `app.<domain>/billing.html?plan=starter|growth` (plans.json `trial.checkout_plans`; a plan without `stripe_price_ids` is
   "not on sale yet"; without Stripe keys everything says "Payments aren't set up yet"). The payment form is Stripe's
   Embedded Checkout inside that page, with the Google e-mail locked and our signed reference (brand + user). Paid while the
   trial still runs? The subscription starts when the trial ends, so the first charge is never early. Stripe's webhook links
   the subscription to exactly that brand by the reference: the plan starts, publishing resumes, nothing needs the owner.
   Paid first and onboarded later (the founding seat from the landing)? The link happens at onboarding, by the user id in
   the reference. Details: `docs/BILLING.md`.

One trial per Google account e-mail and per website domain: a second sign-up with the same e-mail, a second brand, or a
domain that already had a trial gets no trial — the brand is created, and the app asks for a card straight away.

## Endpoints (platform/otto_api.py → otto_auth.py, otto_trial.py)

| Route | What it does |
|---|---|
| `GET /auth/google/start?next=/path` | 302 to Google with state, nonce and PKCE (S256); a 10-minute HttpOnly login cookie binds the state to this browser. `next` must be a same-origin path. |
| `GET /auth/google/callback` | Checks the state (cookie + pending login, single use), exchanges the code at Google's token endpoint over TLS with the client secret and the PKCE verifier, verifies the ID token, creates or updates the user, opens a session, 303 to `next` (a new account with no brand goes to `/onboarding.html`). |
| `POST /auth/logout` | Ends the session and clears the cookie (Origin must be ours). |
| `GET /auth/me` | `{signed_in, google, email, name, status, trial {state, ends_at, days_left}, brands, checkout [...], billing [...], payments, billing_url}` — the app's account menu (plan, next charge, "Manage billing"), trial line, past-due banner and "add a card" screen. |
| `/billing/*` | The Billing page's API (checkout, account, plan change, cancel / resume, payment method, VAT ID): `docs/BILLING.md`. |
| `POST /otto-api/onboard` | Signed in: creates the brand on the trial (answer: `trial: {granted, ends_at | why, message}`). |
| `GET /otto-api/data` | A client whose every brand came from a trial that ended without a card: **402** `{code: "trial_ended" | "no_trial", message, kept_until, checkout}`. |

Without `google-oauth.json` the sign-in routes answer 503 "Google sign-in isn't set up yet", `/auth/me` says `google: false`,
and the UI hides the Google button.

## Security decisions

- **OpenID Connect, authorization-code flow + PKCE + state + nonce**, stdlib only, no Google script on any page (a plain
  redirect), so every page's CSP stays as strict as before.
- **ID token**: received straight from Google's token endpoint over TLS (OIDC Core §3.1.3.7 allows trusting it), and still fully
  checked: RS256 signature against Google's published keys (JWKS, cached by Cache-Control, a new key id refetches at most once a
  minute; keys under 2048 bits refused; the verifier is pure Python PKCS#1 v1.5 and is tested against an OpenSSL signature),
  `iss`, `aud` = our client id (and `azp` when `aud` is a list), `exp` / `iat` (60 s skew), `nonce`, `email_verified` true.
- **Session**: 256 random bits in `__Host-otto_sid` — HttpOnly, Secure, SameSite=Lax, Path=/, no Domain, so only `app.<domain>`
  ever receives it (never `admin.` or the apex). 30 days, sliding (extended on use, written at most hourly). Logout deletes it.
- **Where sessions live**: `sessions.json` next to data.json (own lock, mode 600), holding only the SHA-256 of each session id.
  Not data.json, because every engine job writes data.json (a sign-in would queue behind them), the owner sees data.json whole
  and exports copy it, and a session id is a credential.
- **Where users live**: data.json `users[]` (`id, email, name, google_sub, hd, created_at, last_login_at, trial_started_at,
  trial_ends_at, status trial|active|expired|none, brands, trial_reminders, paid_at`) — they belong with the brands they own,
  and the trial job, onboarding and a subscription link change both in one transaction. Clients never receive `users[]` (the client
  view is an allowlist).
- **Who is signed in, per request, one source only**: the Google session on `app.`; Cloudflare Access's header on `admin.`.
  A request with a session and a different proxy user is refused (401). A session is always scoped to its own brands — even on a
  single-tenant box — and sees everything only when its exact address is in `OTTO_ADMIN_USERS` (`*` never counts for a
  session). The console API (`/otto-api/admin*`) never accepts a session.
- **"@company.com" members** (a whole company may sign in) count for a Google sign-in only when it is that company's Google
  Workspace account (`hd` claim). A private Google account that merely uses a company address does not get in.
- **Rate limit**: 20 sign-in starts and 20 callbacks per client per 10 minutes (an IPv6 /64 is one client).
- **Brand id `oauth` is reserved**: Otto's own `google-oauth.json` sits next to the per-brand `google-<brand>.json` files, and
  the retention job never deletes it.

## The trial, in data

- `plans.json` → `defaults.trial = "trial"`; plan `trial` inherits Starter with `features.ads_launch: false`,
  `limits.video_ads_per_month: 3`, `trial_days: 7`, `after_expiry: "none"` (so a trial whose `plan_until` passed never falls back
  to the free Content plan) and `checkout_plans: ["starter", "growth"]`. Remove `defaults.trial` to switch trials off.
- `brands[].trial = {user, started_at, ends_at, ended_at?, converted_at?, converted_to?}` — or `{user, denied: email|domain|ended|
  one_brand|off}` for a brand that got no trial.
- `trial_ledger[]` — `"e:"` / `"d:"` + SHA-256 of the e-mail / site host: survives deleted accounts and brands, so the same
  e-mail or domain never gets a second trial. Hashes only.
- The `trials` job (`otto_trial.py run`, hourly at :05 UTC, systemd `otto-job-trials.timer`): ends trials on the hour
  (`plan_history` entry with `effective` = the trial's end → the retention clock), sends the reminders (claimed in data.json
  first, retried next hour on a failed send, never sent late), removes accounts with no brand and no sign-in for 90 days.
- Owner console → **Trials**: trials running with days left, ending within 48 h, converted, expired, no trial, reminders sent,
  the trial → paid conversion rate, and the funnel visitors → scans → sign-ups → trials → paid.
- The first week's copy: `brands[].kickoff = {done, at, months, planned, copy_needed, copy_try_at}`. `otto_copy` writes the posts
  (post.copy = `{by, model, at, attempts, state written | held | failed, render?}`), then `otto_trial.copy_done` clears
  `copy_needed` and the owner card is marked done, and the trial month's ads are written (`otto_copy.trial_ads`:
  `angles.json`, `ads-<month>.json` planned when missing, every concept and cell with `copy = {by: "otto_copy", …}`). The `trials` job catches up a week still unwritten 15 minutes after its
  kickoff (at most three brands an hour, inline: a systemd oneshot would kill a spawned child). Caps, the usage ledger
  (`copy-usage.json`) and every check are in the `platform/otto_copy.py` docstring; `otto_copy.py status` shows them.

## What Max sets up

### 1. Google Cloud (15 minutes, once)

1. <https://console.cloud.google.com> → create a project "Otto".
2. **APIs & Services → OAuth consent screen** (Google Auth Platform → Branding / Audience / Data access):
   - User type **External**; app name "Otto"; support e-mail; the app's home page `https://<domain>`, privacy policy
     `https://<domain>/legal/privacy.html`, terms `https://<domain>/legal/terms.html`; authorized domain `<domain>`.
   - Data access / scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (all non-sensitive: no Google
     verification review is needed for them).
   - Audience: **Publish app** ("In production"). While it stays in "Testing", only listed test users can sign in.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type **Web application**, name
   "Otto app". **Authorized redirect URIs**:
   - `https://app.<domain>/auth/google/callback`
   - `http://localhost:8790/auth/google/callback` (local development, optional)
   No JavaScript origins are needed (there is no Google script in the pages).
4. Copy the client id and secret (or download the JSON) onto the server as `/etc/otto/secrets/google-oauth.json`:
   `{"client_id": "…apps.googleusercontent.com", "client_secret": "GOCSPX-…"}` — owner `otto`, mode 600 (Google's downloaded
   `{"web": {...}}` file works as is). Then `systemctl restart otto-api`. `otto_auth.py status` says `configured: true`, and
   the owner console's Setup shows "Google sign-in" connected.
5. Cloudflare: `app.<domain>` must **not** be behind Cloudflare Access any more (delete that Access application if it exists;
   keep the one on `admin.`). The Caddyfile in this repo already stopped passing Access's header on `app.`.

The redirect URI is derived from `OTTO_DOMAIN` (`https://app.<OTTO_DOMAIN>/auth/google/callback`); `OTTO_GOOGLE_REDIRECT_URI`
overrides it (local development), as does `"redirect_uri"` in the file.

### 2. Stripe (see `docs/BILLING.md`)

Stripe account in EUR, products and prices from `plans.json` → `stripe_price_ids`, Stripe Tax, the webhook
`https://<domain>/hooks/stripe`, and `/etc/otto/secrets/stripe.json` — every step and a test-mode run-through are in
`docs/BILLING.md`. Do not turn on a Stripe free trial on the prices: the trial already happened in Otto, and Otto itself
starts a subscription bought during the trial at the trial's end. The legacy Whop webhook (`/hooks/whop`) stays only for
the founding seats sold on Whop; there is no Whop checkout any more.

### 3. Anthropic API key (the AI copywriter, 5 minutes)

1. <https://console.anthropic.com> → the organisation Otto runs under → **Billing**: add credit and set a monthly spend limit
   (a week of copy for one trial costs well under a dollar with `claude-opus-5-5`; the daily caps below bound the rest).
2. **API keys → Create key** ("otto-copywriter").
3. On the server: `sudo -u otto nano /etc/otto/secrets/anthropic.json` (owner `otto`, mode 600):
   ```json
   {"api_key": "sk-ant-…", "model": "claude-opus-5-5"}
   ```
   Optional keys: `"effort"` (`low` · `medium` default · `high`), `"max_calls_day"` (300), `"max_usd_day"` (40),
   `"max_calls_per_brand_day"` (16), `"batch"` (4 posts per request), `"parallel"` (2), `"fallbacks"` (true: a request the
   model's safety classifier declines is retried on Anthropic's recommended fallback model), `"enabled"` (false switches it
   off without removing the key). Nothing to restart: every run reads the file.
4. Check: `python3 /opt/otto/platform/otto_copy.py status` (key set, model, today's usage), then
   `otto_copy.py week --brand <an existing brand> --dry` and `otto_copy.py ads --brand <a brand with paid ads> --dry` (what it
   would write; nothing is sent). The owner console's Setup shows
   "AI copywriter (Claude API)" connected, with today's calls, tokens and estimated spend against the caps.

### 4. Local development (optional)

The API listens on 127.0.0.1:8161 and serves no pages, so a browser needs one origin for both. For example
`caddy run --config Caddyfile.local` with:

```
http://localhost:8790 {
	handle /auth/* {
		reverse_proxy 127.0.0.1:8161
	}
	handle /otto-api/* {
		reverse_proxy 127.0.0.1:8161
	}
	handle /billing/* {
		reverse_proxy 127.0.0.1:8161
	}
	handle {
		root * platform
		try_files {path} {path}.html
		file_server
	}
}
```

and `OTTO_GOOGLE_REDIRECT_URI=http://localhost:8790/auth/google/callback` in the API's environment (cookies are then
`otto_sid` without `Secure`, since it is plain http on localhost).

## Legal

Terms §"Free trial" (7 days, no card, one per business, what happens at the end, no charge without a plan, a plan chosen
during the trial is first charged when it ends), the Privacy Policy
(Google sign-in data: what, why, how long) and the sub-processor list (Google, authentication) are updated in `docs/legal/`
(rendered with `python3 platform/tools/legal.py`). They are drafts for the lawyer like the rest.

## Tests

`platform/tests/test_copy.py` (the AI copywriter against a fake Claude API: the request shape, the posts and cards it writes,
compliance rejection → rewrite → held, the no-invention guard, the trial's copy_done, spawn on kickoff, the hourly catch-up,
no key → no-op, caps, retries), `platform/tests/test_auth.py` (the OIDC flow against a fake Google, every refusal, the RS256 verifier, sessions, cookies, rate
limit, admin and tenant scoping) and `platform/tests/test_trial.py` (sign-up → trial, one per e-mail / domain / user, no launch
during the trial, the three e-mails once each, the end on the hour with the retention clock, the 402, the offers on the
Billing page, the legacy Whop auto-link and the manual link, the console) and `platform/tests/test_stripe.py` (paying with
Stripe against a fake Stripe: the checkout request, the webhook, every event, the trial's end as the first charge). `platform/tests/test_app_fixes.py` holds the QA round-2 regressions.
