# Otto — Launch readiness (pre-launch simulation)

Date: 2026-09-29 · Scope: the Python engine in `platform/` (not `index.html` / `landing.html`) · No git commit made.

## 1. What was run

`platform/tests/simulate.py` onboards **five synthetic businesses** and drives each through the whole lifecycle inside a
throwaway workspace (every `OTTO_*` path points into a temp dir; the real `data.json`, `brands/` and `index.html` are
fingerprinted before/after and must not change). Fixture websites are local HTML served by `http.server`. There is no
real network at all: every process, subprocesses included, gets a `sitecustomize` guard that refuses DNS and non-loopback
connections. Meta Graph, Telegram, Google OAuth/Ads and the OpenClaw sender are call-recording fakes. A simulated clock
moves time: cards Sep 30 → publishing Oct 1–2 (with a deliberate 4-hour publisher gap) → paid launch Oct 1 and boosts Oct 8
→ reports Oct 2–4 → hourly guard Oct 5 → month review Nov 1 (crossing the Oct 25 DST change).

| Business (fixture) | Lang | Currency | TZ | Restricted | Meta / Google setup |
|---|---|---|---|---|---|
| Berlin dental clinic `spreebogen` | de | EUR | Europe/Berlin | health | pixel + lead form · Google token **revoked** |
| Lisbon surf school `ondaviva` | pt/en | EUR | Europe/Lisbon | no | no pixel, no form (→ traffic) · Google OK · per-stage landing pages |
| Amsterdam coffee e-shop `grachtenkoffie` | nl/en | EUR (ad account **USD**) | Europe/Amsterdam | no | pixel · no Google |
| Tel Aviv therapy-training college `ofek` | he (RTL) | ILS | Asia/Jerusalem | therapy | lead form · Google OK |
| Milan interior designer `studiolume` | it | none on site | Europe/Rome | no | page only, **no ad account**, no Google |

Lifecycle per business (dry first, then real against the fakes): brand-add → scan → strategy → competitors (3 sweeps, one
site change) → plan → copy fill in the brand's language → images, real ffmpeg carousels and reel → compliance → send-cards →
approvals (CLI, Telegram ✅/❌/✏️/↷, dashboard) → publish (7 cron runs) → ads plan/approve/launch/re-launch → insights →
ads report ×3 + send-recs → watch → growth → 90-day demo → motion prepare (external tools stubbed).

Run: `cd platform && python3 tests/simulate.py [--keep] [--json out.json]` (exit 1 on any FAIL; ~70–135 s).
Unit tests: `python3 tests/test_engine.py` — **56 tests, all green** (30 existing + 26 new).

## 2. Results matrix (business × step)

`ok` / `WARN` (suspicious output) / `FAIL` (exception or broken invariant) / `skip` (not runnable offline).
Each cell reads *first run → final run*; a single value means it did not change.

| step | dental DE | surf PT | coffee NL | therapy IL | interior IT |
|---|---|---|---|---|---|
| scan | WARN→ok | WARN→ok | WARN→ok | WARN→ok | WARN→ok |
| onboard (brand-add) | WARN→ok | WARN→ok | WARN→ok | ok | WARN→ok |
| strategy | ok | WARN→ok | WARN→ok | ok | WARN→ok |
| competitors | ok | WARN→ok | WARN→ok | ok | WARN→ok |
| plan | WARN→ok | WARN→ok | WARN→ok | ok | WARN→ok |
| visuals / creatives | WARN→ok | WARN→ok | WARN→ok | WARN→ok | WARN→ok |
| compliance | **FAIL**→ok | ok | ok | **FAIL**→ok | ok |
| send-cards | **FAIL**→ok | ok | ok | **FAIL**→ok | ok |
| publish | ok | ok | ok | **FAIL**→ok | ok |
| ads plan | WARN→ok | WARN→ok | WARN→ok | ok | WARN→ok |
| ads launch | WARN→ok | ok | ok | ok | WARN→ok |
| ads report + recs | WARN¹→ok | WARN¹→ok | WARN¹→ok | WARN¹→ok | ok |
| watch | WARN→ok | ok | ok | ok | ok |
| demo journey | **FAIL**→ok | **FAIL**→ok | **FAIL**→ok | **FAIL**→ok | **FAIL**→ok |
| reels (motion) | skip | WARN→skip | WARN→skip | skip | WARN→skip |

Always ok for all five: plan --dry, copy fill, send-cards --dry, approvals, publish --dry, insights, growth.
¹ a harness bug (fake insights keyed wrong), not an engine bug.

Engine checks and failure injections (first → final):

| injection | expected behaviour | result |
|---|---|---|
| isolation: modules honour `OTTO_*` | nothing written outside the workspace | **FAIL**→PASS |
| malformed site (bogus charset, binary, `javascript:` theme-color) | scan completes, nothing unsafe stored | **FAIL**→PASS |
| redirect → 169.254.169.254 / 10.0.0.5 / loop / HTTP 500; `/otto-peek` | clean refusal | PASS² |
| Meta error on publish (once) | back to `approved`, published next run | PASS |
| unconfirmed publish (timeout) | stays `publishing`, never retried, P0 + alert | PASS |
| IG post without image | refused + P0, run continues | PASS |
| Google `invalid_grant` (launch + 3 reports) | launch `failed` + P0; one "Reconnect" card | PASS |
| ad account bills USD, plan in EUR | refused before any object is created | PASS |
| violating posts (German heal claim, Hebrew "do you suffer…") | never carded, never published | **FAIL**→PASS |
| corrupt `compliance.json` | fail closed | **FAIL**→PASS |
| mid-month onboarding | no past slots | WARN→PASS |
| 2 × publish in parallel | no double post | PASS² |
| 2 × send-cards | one card per post | WARN (59 duplicates)→PASS |
| 2 × plan build (same month) | second refused | PASS |
| 2 × `growth --send` | one review | WARN (2 sent)→PASS |
| 2 × `ads launch` | one Meta campaign per flight | WARN (double spend)→PASS |

² any run-1 FAIL here was a harness assertion bug.

## 3. Bugs found and fixed

Tests are in `platform/tests/test_engine.py` (class · test prefix); all 26 new tests fail on the pre-fix code.

| # | where | bug (cause) | fix | test |
|---|---|---|---|---|
| 1 | `otto_strategy.py:30`, `otto_telegram.py:41`, `otto_watch.py:22-23`, `otto_growth.py:29`, `otto_motion.py:27,32` | paths ignored `OTTO_*`: strategy wrote the real `brands/`; state files pinned to the code dir | env-aware paths; state next to `data.json` (same path on the server) | IsolationTest · every_module… |
| 2 | `otto_demo.py:25,36,53,107` | read the real `data.json`/`index.html`/`brands/`; unknown brands got Happy Garden's € and "CBD is restricted…"; "50 feed posts" hard-coded but marked real | `ap` paths; neutral defaults in the brand currency; counts from the brand's plan | IsolationTest · demo_reads… |
| 3 | `otto_motion.py:353` | `ap.publish_asset` does not exist → rendered reel never made public | `otto_paths.publish` | LanguageTest · finished_reel… |
| 4 | `ap.py:496` | brand-add set `tz = Asia/Jerusalem` for everyone → Berlin posts at 08:00, Lisbon at 07:00 | tz + countries from url TLD, then language; `--tz/--countries/--currency` | OnboardingDefaultsTest · brand_add… |
| 5 | `ap.py:378` | Israeli brand without prices → EUR | country currency fallback | same |
| 6 | `otto_strategy.py:72` | tz = Jerusalem if Hebrew else Berlin | brand tz / currency | strategy_takes… |
| 7 | `otto_ads.py:375`, `ap.py:406`, `otto_competitors.py:195` | ads audience and Ad Library country = DE for pt/nl/it brands | `ap.brand_countries` (brand → TLD → language) | markets_follow… |
| 8 | `otto_scan.py:53` | `2.900 €`→`900 €`, `₪18,500`→`₪18,50` (wrong offers) | thousands-aware amounts | ScanParseTest · prices… |
| 9 | `otto_scan.py:33,59` | English-only subpage keys and industry words → de/it homepage only, "Unknown (?)" industry | localized keys/keywords | localized_subpages… |
| 10 | `otto_scan.py:598` | `javascript:` theme-color stored in scan.json + profile | CSS colours only | theme_color… |
| 11 | `otto_compliance.py:26,41` | new restricted brand has no rules → Hebrew "האם אתה סובל מחרדה?" and German "Wir heilen…" carded and published | health baseline (claims + personal attributes, 7 languages) when no `compliance.json` | ComplianceBaselineTest · health_brand… |
| 12 | `otto_compliance.py:80` | unreadable rules → everything passed | fail closed | unreadable_rules… |
| 13 | `otto_publish.py:271` | dashboard-approved violating post went to Meta | re-check before any Graph call → `draft` + hold card | publisher_holds… |
| 14 | `otto_creative.py:32`, `otto_video.py:48`, `otto_ads.py:69-85` | English CTA card (pt/nl), "Link in bio." (all), RSA fallbacks (pt/nl/it); no Google `pt` language | localized; `pt` 1014 (+ar, hu, pl, ru, ro) | LanguageTest · non_english… |
| 15 | `otto_ads.py:441,474` | RSA used the English industry label ("Unknown (?)") and compliance-blocked hooks (put Search on hold) | both removed | plan_headlines… |
| 16 | `otto_ads.py:820` | headlines cut mid-phrase ("Surf camp: uma semana que") | `_fit`: sentences → clause → drop | search_ads… |
| 17 | `otto_motion.py:100,228` | reel brief `language: en` unless he/de; Whisper `small.en` for Hebrew | brand language; multilingual model | reel_brief… |
| 18 | `otto_plan.py:134` | current-month build: 61 of 65 slots in the past | past slots skipped | SchedulingTest · plan_skips… |
| 19 | `otto_telegram.py:168,187` | cards for passed slots; 2 runs = every card twice | skip; per-post `tg_claim` | no_card_for_a_past_slot… |
| 20 | `otto_telegram.py:110` | cards showed "angle TBD by Quill…" to clients | hidden | card_hides… |
| 21 | `otto_ads.py:965,1026` | 2 launch runs = 2 Meta campaigns (double spend) | `launching_at` claim, stale takeover | PaidLaunchTest · a_claimed_flight… |
| 22 | `otto_ads.py:955` | boosts picked before anything is live → always skipped | best live FB post at launch | boost_uses… |
| 23 | `otto_ads.py:1017` | approved flights without credentials: silent daily NO-CREDS | one "Connect …" card | approved_flight_without… |
| 24 | `otto_ads.py:518` | plan card "on it" while every flight stays on hold | card names the held flights | plan_card_says… |
| 25 | `otto_watch.py:194` | missed-publish alert needed a `connections[]` entry new brands never get | also brands with Meta creds | WatchAndGrowthTest · missed_publish… |
| 26 | `otto_watch.py:38` | alerts to a hard-coded chat (Max) via OpenClaw; missing CLI crashed `report`/`watch` | owner bot from `telegram.json` first | reports_go_to… |
| 27 | `otto_growth.py:196` | 2 runs = review sent twice | sending claim | review_not_sent… |

Also: `otto_strategy init` now creates the brand folder if the scan has not run yet; `crons.md` documents the claims,
brand-add defaults and where watch sends.

## 4. Still failing or unverified

- **Reels (otto_motion finish / HyperFrames render, ElevenLabs voice, faster-whisper word timings)** — needs npx, network and
  models; only `prepare` was run (external calls stubbed). The Whisper model/language change is untested live.
- **Real APIs**: fakes accept any payload. Unverified against Meta v25 / Google Ads v21: `photo_stories`,
  `special_ad_category_country`, lead-form CTA, Google `startDate/endDate` (flagged in code), the new language IDs, HUF
  minor units. Leonardo and ElevenLabs only dry-run.
- **Scanner on real sites**: JavaScript-rendered sites (Wix/Next.js client-side) will scan nearly empty; Hebrew
  percent-encoded slugs are not matched by the subpage keys.
- **Design gaps left as is** (not bugs in the simulated flow, owner decisions):
  - `brand-add` with a generic TLD (.com/.io) and English `LANG` still defaults to Asia/Jerusalem — it prints the tz; pass `--tz`.
  - Pending posts whose slot passed stay pending (no card now), still listed in the morning report; no auto-reslot.
  - Dashboard "so far" month-over-month on the 1st compares an empty month (shows −100 %).
  - A boost with no live Facebook post on its start day is `skipped` for good (not retried later in its window).
  - Owner-facing card headers and the morning report are English; the compliance baseline is a floor, not legal review.
  - Every write rewrites all of `data.json` and its copy in `index.html` (a shared dashboard would expose every client).
  - `otto_watch report` / `otto_ads report` still send on every run — keep `flock -n` on all cron lines.
  - A competitor without a URL triggers a DuckDuckGo lookup on every weekly sweep.

## 5. Performance

- Month build (66 posts incl. 13 stories, 11 reels): **0.06–0.27 s** per brand as a CLI process.
- Large tenant file: 40 brands / 3,053 posts / 2.8 MB `data.json` → month build **0.2–1.2 s**, one decision write
  **0.07–0.37 s** (lock + full rewrite + fallback sync). Fine up to low thousands of posts per instance; beyond that the
  fallback embed is the first thing to drop.
- Whole simulation 70–135 s wall on this Mac (varies with load); ~56 s of it is ffmpeg (5 real reels + carousel slides and
  ad statics). One 5-scene reel ≈ 10 s of ffmpeg.
- Production cost/time not measured here: Leonardo ≈ $0.20 and 15–60 s per image (≈ $13/brand/month at 66 images).

## 6. Go / no-go

**Engine verdict: GO for a controlled launch** (organic first, paid only behind approvals), once the owner items below are
done. Treat reels as assisted/manual until one full render is verified on the server.

Owner actions — credentials
- [ ] Meta app: App Review for `pages_manage_posts`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`,
      `ads_management`; Business Verification. Per brand `otto-secrets/meta-<slug>.json` with a long-lived Page token,
      `page_id`, `ig_user_id`, and for paid `ad_account_id` (+ `pixel_id` / `lead_form_id`).
- [ ] Check each ad account's billing currency equals the brand currency (else launches are refused — as designed).
- [ ] Google Ads developer token (Basic access), OAuth client and a refresh token per brand; re-auth runbook for
      `invalid_grant`; verify v21 date fields and language IDs on the first campaign.
- [ ] One Telegram bot per client instance: `telegram.json` with the client's `owner_chat_id` (now also receives the morning
      report and alerts); the client must `/start` it.
- [ ] `LEONARDO_API_KEY` (or `.leonardo_key`, chmod 600), ElevenLabs key; rotate the Whop webhook secret (open item).

Owner actions — server
- [ ] Cron lines exactly as `crons.md`, each with `flock -n`; server clock in UTC; `python3 ≥ 3.9` with `tzdata`.
- [ ] `ffmpeg`, `ffprobe`, `fonts-dejavu-core`; check `ffmpeg -h filter=drawtext` for `text_shaping` (Hebrew).
- [ ] `OTTO_PUBLIC_ASSETS` writable by the cron user; nginx `/otto-peek` rate limit + `X-Real-IP`; `/otto-api` behind auth;
      `OTTO_ALLOWED_ORIGINS` set; `otto-telegram` systemd poller enabled.
- [ ] Give the two pilot brands an explicit `tz` / `countries` in `data.json` (they have none; Happy Garden currently runs on
      Jerusalem time).
- [ ] Before every deploy: `python3 platform/tests/test_engine.py` and `python3 platform/tests/simulate.py` (both green).

Owner actions — compliance
- [ ] Write `brands/<slug>/compliance.json` for every restricted client before its first card (dental → German
      Heilmittelwerbegesetz, therapy/mental health → Meta personal-attributes, CBD → EU novel food). The baseline only
      catches the obvious.
- [ ] Review each restricted client's paid flights and `otto_ads.py release <id>` only after a compliant landing page exists.
- [ ] Lead forms / pixel: GDPR consent text and privacy-policy URL per client.

**No-go if any of these is open:** Meta App Review / Page token missing for the launch brands · client Telegram bot not
paired · a restricted client without `compliance.json` · cron without `flock` · paid flights approved for a client whose ad
account currency does not match.
