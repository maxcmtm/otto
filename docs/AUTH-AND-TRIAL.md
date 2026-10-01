# Sign in with Google, the free 7-day trial, and "add a card"

Max, 30.09.2026: "I want a free 7-day trial for new sign-ups; the option to log in with Gmail (Google auth) and open a user;
after 7 days they should place a credit card."

This is how it works, what is stored, and what Max has to set up (Google Cloud and Whop, about 20 minutes).

## The client's path

1. **Landing → "Start free 7-day trial".** The button goes to `https://app.<domain>/auth/google/start?next=/onboarding.html?site=<the
   scanned domain>`, so the scan the visitor just ran carries over.
2. **Google.** The visitor picks a Google account. Otto asks for `openid email profile` only: the e-mail address (verified by
   Google), the name and the Google account id. No access to Gmail, Drive or anything else, and no profile picture is stored.
3. **Account + trial.** The first sign-in creates the account (data.json `users[]`) and starts the trial clock: 7 days from that
   moment, no card. A returning sign-in finds the same account (by Google account id, else by e-mail).
4. **Onboarding.** The first brand the account sets up runs on the **trial plan** until the trial ends: Starter's organic posts,
   stories, reels, the monthly competitor sweep and reports all run for real (status "active"). Paid ads are planned and the ad
   matrix is rendered so the client sees them, but no campaign launches (`ads_launch: false`), and video ads are capped at 3
   previews.
5. **During the trial** the app shows one calm line: "N days left in your trial · Add a card". E-mails (to the Google address):
   - 2 days before the end: "2 days left in your Otto trial"
   - in the last 24 hours: "Your Otto trial ends today" (or "tomorrow", by the local clock)
   - after the end: "Your Otto trial has ended — <brand> is paused … your work is kept for 90 days"
   Each goes out once. Nothing is ever charged automatically: there is no card on file.
6. **The end.** On the hour (the `trials` job runs hourly), a trial brand without a paid plan moves to the ended plan
   (`none`): publishing and ads pause, the owner gets a card, the data is kept. The app shows the "add a card" screen instead
   of the data (the API answers 402). After 90 days without a plan, `otto_retention` deletes the brand (owner notices 14 and 3
   days before, a zip export first) — the 90 days count from the trial's end.
7. **Add a card.** The screen offers Starter and Growth (plans.json `trial.checkout_plans`) as Whop checkout links with the
   Google e-mail prefilled and locked. When Whop's webhook reports the membership, Otto links it by that verified e-mail to the
   client's brand: the plan starts, publishing resumes, nothing needs the owner. Paid first and onboarded later? The link
   happens at onboarding.

One trial per Google account e-mail and per website domain: a second sign-up with the same e-mail, a second brand, or a
domain that already had a trial gets no trial — the brand is created, and the app asks for a card straight away.

## Endpoints (platform/otto_api.py → otto_auth.py, otto_trial.py)

| Route | What it does |
|---|---|
| `GET /auth/google/start?next=/path` | 302 to Google with state, nonce and PKCE (S256); a 10-minute HttpOnly login cookie binds the state to this browser. `next` must be a same-origin path. |
| `GET /auth/google/callback` | Checks the state (cookie + pending login, single use), exchanges the code at Google's token endpoint over TLS with the client secret and the PKCE verifier, verifies the ID token, creates or updates the user, opens a session, 303 to `next` (a new account with no brand goes to `/onboarding.html`). |
| `POST /auth/logout` | Ends the session and clears the cookie (Origin must be ours). |
| `GET /auth/me` | `{signed_in, google, email, name, status, trial {state, ends_at, days_left}, brands, checkout [...]}` — the app's account menu, trial line and "add a card" screen. |
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
  and the trial job, onboarding and the Whop link change both in one transaction. Clients never receive `users[]` (the client
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

### 2. Whop (5 minutes, once the prices are final)

1. Create the two subscription plans on Whop — **Starter** and **Growth**, monthly, in EUR (prices in `plans.json` are drafts;
   Whop's price is what is charged). Leave Whop's own free-trial days **off**: the trial already happened in Otto.
2. Put each Whop plan id into `plans.json` → `plans.starter.whop_plan_ids` / `plans.growth.whop_plan_ids`. Until then the
   "add a card" screen shows the plans without a checkout button ("not on sale yet").
3. The checkout link Otto builds is `https://whop.com/checkout/<plan id>?email=<the Google e-mail>&email.disabled=1` — Whop
   prefills and locks the e-mail field, which is what lets Otto match the payment to the account (Whop docs: checkout URL
   parameters). A custom checkout host: `"checkout_base": "https://…/checkout/"` in `whop.json`.
4. The webhook (`https://<domain>/hooks/whop`, events `membership.*`, `payment.*`) must carry the member's e-mail: give the
   Whop app/API key the member e-mail permission. A membership whose e-mail matches no Google sign-in, or a Whop plan that
   `plans.json` does not map, is never linked automatically — the owner links it in the console as before.

### 3. Local development (optional)

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

Terms §"Free trial" (7 days, no card, one per business, what happens at the end, no automatic charge), the Privacy Policy
(Google sign-in data: what, why, how long) and the sub-processor list (Google, authentication) are updated in `docs/legal/`
(rendered with `python3 platform/tools/legal.py`). They are drafts for the lawyer like the rest.

## Tests

`platform/tests/test_auth.py` (the OIDC flow against a fake Google, every refusal, the RS256 verifier, sessions, cookies, rate
limit, admin and tenant scoping) and `platform/tests/test_trial.py` (sign-up → trial, one per e-mail / domain / user, no launch
during the trial, the three e-mails once each, the end on the hour with the retention clock, the 402, the Whop auto-link and
the manual link, the console). `platform/tests/test_app_fixes.py` holds the QA round-2 regressions.
