# Launch now — the short path (2 Oct 2026)

Max: "launch today or tomorrow with a campaign, no waiting." This is the minimum to put the landing, sign-up, trial and app on
a real domain and start the Meta campaign. Everything not here (GitHub Actions deploys, off-site backups, Telegram alerts,
Google Ads, creators, the Dutch review) follows in week 1 and does not block the launch.

Keys for the server were generated on Max's Mac in `~/otto-launch-keys/` (outside the repo):
`otto-root.pub` (Hetzner: lets the launch session reach the server as root) and `otto-server-github.pub` (GitHub: the
server's read-only access to the repo). Secrets Max creates are saved as files in the same folder and copied straight onto
the server — never pasted into a chat.

## Max (about 90 minutes, in this order)

| # | Where | What | Save as (in `~/otto-launch-keys/`) |
|---|---|---|---|
| 1 | Cloudflare | Buy the domain (Registrar). SSL/TLS → **Full (strict)**, Always Use HTTPS on. SSL/TLS → Origin Server → Create certificate (`<domain>`, `*.<domain>`, 15 years) | `origin.pem`, `origin.key` |
| 2 | Cloudflare | Zero Trust → Access → self-hosted app for `admin.<domain>` only, your e-mail, One-time PIN | — |
| 3 | Hetzner | Project "Otto" → SSH key = the line in `otto-root.pub` → server CPX31, Ubuntu 24.04, Nuremberg, backups on, name `otto-1`. Cloudflare DNS: `@`, `app`, `admin` → its IPv4 (A) and IPv6 (AAAA), proxied | send the IPv4 in the chat |
| 4 | GitHub | maxcmtm/otto → Settings → Deploy keys → Add: the line in `otto-server-github.pub`, write access **off** | — |
| 5 | Google Cloud | Project "Otto" → OAuth consent screen (External, app name Otto, scopes `openid email profile`, publish) → Credentials → OAuth client (Web), redirect `https://app.<domain>/auth/google/callback` → Download JSON | `google-oauth.json` |
| 6 | Resend (or Postmark) | Add the domain, put its DNS records in Cloudflare, create an API key; sender `otto@<domain>` | `email-api-key.txt` |
| 6b | Cloudflare | Email → Email Routing: `hello@<domain>` and `privacy@<domain>` → your inbox (the legal pages and e-mails name them) | — |
| 6c | — | The company facts for the legal pages: legal name, form, address, register number, VAT ID, director, phone, country — the entity that runs Otto **today** (they go into `docs/legal/facts.json`; with `"publish": true` the pages drop the draft notes and refuse to render while anything is missing) | send in the chat |
| 7 | Anthropic Console | API key for the automatic copywriter (`platform/otto_copy.py`): every new trial gets its first week written and designed within minutes | `anthropic-key.txt` |
| 8 | Meta Business (your own business, not a client's) | New ad account in **EUR** with a payment method; Facebook Page + Instagram professional account "Otto"; Events Manager → new dataset (pixel) → Conversions API token; Business settings → Brand safety → Domains → verify `<domain>` (DNS TXT in Cloudflare) | `meta-capi.txt` (pixel id + token) |
| 9 | Stripe | Start the selling company today (Stripe Atlas is the fastest path; or an EU entity with the accountant). Trials run 7 days without a card, so payments must be live within a week of the first sign-up — docs/BILLING.md | later: keys into `stripe.json` |
| 10 | — | Approve the campaign budget: **€100 a day** (€50 Netherlands, €50 Ireland), ramp and stop rules in `launch/2026-10/README.md` | say "go" in the chat |

## The launch session (after each of Max's steps)

- After 1–4: bootstrap the server (`infra/bootstrap.sh` over SSH with `otto-root`; the server's deploy key replaced by
  `otto-server-github` so the clone works on the first run), install the origin certificate, first deploy, health check.
- After 5–8: write `google-oauth.json`, `email.json` (link secret generated on the server, provider + key), `anthropic.json`,
  `meta-capi.json` into `/etc/otto/secrets/` (otto only, 600), restart, then run the whole client journey on the real domain
  (landing → scan → Google → onboarding → first week written and designed → approval e-mail) and the CAPI test event.
- Campaign: the kit in `launch/2026-10/` is regenerated for the domain (`python3 build.py --domain <domain>`), uploaded
  **paused**, and switched on only after Max's "go".
- If Stripe is not live by day 5 of the first trials, their trials are extended (data only, nothing charged) so nobody hits
  "Payments aren't set up yet".
