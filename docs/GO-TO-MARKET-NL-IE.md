# Otto go-to-market: the Netherlands and Ireland (launch: November 2026)

Date: 2026-09-30 · Author: Claude Code (head of growth pass) · Decision owner: Max · Status: plan, ready for decision
Builds on: `research/EU-LAUNCH-AND-PRICING-2026-09.md` (§1, §5.3, §6.5, §7, §8), `research/COMPETITORS-2026-09.md` (§3–§6),
`docs/HOSTING.md`, `docs/COMPLIANCE-BASELINES.md`. Nothing in this plan has been sent, published, launched or paid for.

Conventions: prices excl. VAT. "(est.)" = my estimate. "(unv.)" = not confirmed from a primary source; check before relying
on it. Sources are listed in §13.

---

## 0. The plan on one page

| Question | Answer |
|---|---|
| What we sell in November | What the landing sells today (changed on 30.09): a **free 7-day trial** (Google sign-in, no card, nothing charged automatically; first posts within 24 hours), with the **founding pilot, €197 once** as the pay-once alternative. After the trial: a monthly plan (Starter €99 / Growth €249, still drafts awaiting Max's approval). |
| Where | **Netherlands** (Dutch ads, written natively) and **Ireland** (Irish English), launched together on Monday 2 November 2026. Flanders joins as a Dutch spillover once NL is on target (§3.6). |
| Test budget | **€50 a day per country for 30 days = €3,000 media**, plus €900 for six creator-owners and about €300 for a Dutch native reviewer. **Total ≈ €4,200.** |
| Campaign structure | Per market: **one campaign with Advantage+ campaign budget** (formerly CBO), **one ad set per concept (6)**, optimising for the **Lead** event (the scan result, via the Conversions API). Broad + Advantage+ audience with a vertical interest stack as suggestions. |
| Creative | Per market **37 ads: 6 concepts × 6–7 styles, 19 video (51 %)**: 18 image cells (all rendered and reviewed), 13 faceless videos (4 rendered per market, 9 scripted), 6 founder-led creator videos (briefs ready, real owners). |
| Funnel targets (§5.3) | CTR ≥ 0.8 % · CPC ≤ €1.30 · 20 % of visitors scan · **≤ €8 per scan result** · ≤ €30 per trial start · 18–25 % of trials pay · **plan €150–300 per paying customer**. |
| What €3,000 should buy | **~100 trial starts and 10–20 paying customers** (plan, EU §5.3); the funnel midpoint allows ~25. Payback 1.8–3.5 months on a monthly plan. |
| Measurement | Privacy-first: a consent banner (reject = accept), first-party cookieless analytics for everything, and Meta only through the server-side Conversions API for visitors who pressed Accept. Shipped in this pass (§5.4). |
| Organic | A 30-day founder LinkedIn plan (English: 22 weekday posts, 4 light Saturday posts, 4 engagement Sundays), tied to real NL/IE events (§6). |
| Partners | 20 web/Shopify agencies per country, from public directories, for the Agency plan. **Nobody has been contacted** (§7). |
| Dutch landing | Recommended before NL spend passes €50/day; the Dutch copy is written for review: `platform/landing-nl-copy.md` (§8). |
| Max's decisions | Approve the €4,200 and the monthly prices (trials need a plan to convert); set up Meta (ad account, dataset, CAPI token); Starter/Growth on Whop; buy the domain and move to Hetzner; LinkedIn; recruit creators; hire the Dutch reviewer; approve partner outreach (§11). |

---

## 1. What we sell and what we say

### 1.1 Offer and message

- **Offer (live on the landing today):** a free 7-day trial — sign in with Google, no card, one trial per business; the first week of posts, stories and reels, approvals by e-mail, in Telegram or in the app, the 07:35 report, paid ads planned for preview (they launch once a plan is chosen); an e-mail two days before the end and nothing charged automatically. The founding pilot (€197 once, excl. VAT) stays as the pay-once alternative. Monthly prices are **not** stated in ads until Max approves them and they exist on Whop; the ads say "no card, nothing charged automatically", which is the full truth about the trial's cost.
- **Three concepts carry the launch** (COMPETITORS §6): **the 7:35 message** (accountability), **your website, as a reel** (the video gap), **local, not translated** (Native reaches 2 of 86 ads into NL; Holo translates). Three more complete the six families the engine requires: owners-not-marketers (identity), the free week (offer), December planned in November (moment).
- **Never:** "autopilot", "paste your website", "walk away", price-versus-agency framing, invented results or reviews, fake scarcity, competitor names. These are enforced in `brands/otto/compliance.json` and `competitors.json`, so the engine blocks them before anything renders.
- **Proof we can use now:** product facts from the landing (07:35 report, first posts within 24 h, ~30 min a week, at most four questions, nothing goes out without approval, 7 days free with no card) and the offer. **No customer reviews or results exist yet**; every figure in a report screen is labelled "Sample"/"Voorbeeld".

### 1.2 Must be true before the first euro is spent

| # | Item | Why | Owner |
|---|---|---|---|
| 1 | Consent banner live, `/otto-track` CAPI path deployed, `meta-capi.json` on the server, a test event seen in Events Manager | Dutch DPA cookie enforcement (EU §8); the campaign optimises on Lead | Done in code (§5.4); Max for Meta setup |
| 2 | Domain bought, production on the Hetzner box, `OTTO_ALLOWED_ORIGINS` set | HOSTING.md: not on a shared box with paying customers | Max |
| 3 | ~~Landing FAQ lists **Dutch** as a content language~~ **Done 30.09** | The NL ads promise Dutch | Done |
| 4 | ~~E-mail approvals working for NL/IE trials~~ **Done 1.10** (otto_email; needs a mail service on the server: Postmark, Resend or SMTP in `email.json`) | 98 % of Dutch people use messaging, Telegram is a minority (EU §6.2) | Done in code; Max for the mail service |
| 5 | ~~The 07:35 report and approval cards in Dutch for Dutch brands~~ **Done 1.10:** the 07:35 report goes out by e-mail and Telegram; English by default, Dutch or German when the client chooses it (`brands[].comms_lang`). The NL ads should say the language is a choice | Our NL "7:35" ads show the message in Dutch | Done |
| 6 | **Stripe prices (Starter, Growth) in EUR** with cards, SEPA, iDEAL and Bancontact on and Stripe Tax set up (docs/BILLING.md; Whop is no longer used for new customers) — the trial's "add a card" screen needs them (`plans.json` stripe_price_ids), otherwise no trial can convert | EU §8; without it the funnel ends at the trial | Max |
| 6b | ~~The trial start reaches Meta~~ **Done 1.10:** the Google sign-up sends CompleteRegistration and the first trial brand sends StartTrial (otto_api → otto_track.capi_track) | §5.4 | Done |
| 7 | Dutch native review of the NL matrix and the NL landing copy | EU §8: the team cannot judge Dutch copy | Dutch reviewer |
| 8 | Lawyer review of the updated cookie and privacy notices (Meta joint controllership) | Drafts, clearly marked | Max |

### 1.3 The offer changed to a free trial (30.09) — what that means for the ads

The landing's CTAs became "Start free 7-day trial" with Google sign-in while this plan was written. Done in this pass:
- Concept **a5** in both matrices is now the free trial ("Probeer Otto 7 dagen gratis" / "Try Otto free for 7 days"), with the founding pilot named only as the pay-once alternative; every end card's fine print is the trial line ("7 dagen gratis proberen, geen creditcard nodig" / "Try it free for 7 days, no card needed"); `"Google"` is in `rules.allowed_names`. When Max approves a monthly price, these checked lines can add it (NL / IE baselines and Otto's own rules, 0 violations):
  - NL: "Probeer Otto 7 dagen gratis. Daarna €99 per maand, excl. btw, maandelijks opzegbaar." · "7 dagen gratis, daarna €99 per maand excl. btw" · "Log in met Google en je eerste posts staan binnen 24 uur klaar om goed te keuren."
  - IE: "Try Otto free for 7 days. Then €99 a month, excl. VAT, cancel any month." · "7 days free, then €99 a month excl. VAT" · "Sign in with Google and your first posts are ready for your approval within 24 hours."
- Measurement needs no rework: every "get started / start trial / sign up" CTA click already maps to **InitiateCheckout**, and the server that completes a sign-up calls `otto_track.capi_track("signup" | "trial_start", …)` → **CompleteRegistration / StartTrial** (§5.4). Switch the campaign's optimisation event from Lead to CompleteRegistration once it fires ≥ 25 times a week per market.

---

## 2. Budget

### 2.1 The 30-day test (2 Nov – 1 Dec 2026)

| Line | NL | IE | Total |
|---|---|---|---|
| Meta media, €50 a day × 30 days | €1,500 | €1,500 | **€3,000** |
| Creator-owners: 3 per market × €150 for two takes (plus a free month of Otto after the pilot) | €450 | €450 | €900 |
| Dutch native reviewer, ~6 h (matrix, landing copy, week-2 refresh) | €300 | – | €300 |
| **Total cash** | €2,250 | €1,950 | **≈ €4,200** |

Rendering costs are compute only: the cards and faceless videos are rendered by Otto's own engine, with synthesized music and UI sounds and no paid voice.

### 2.2 Pacing inside the test

- **Days 1–7:** €50/day per market, Advantage+ campaign budget with a **€4/day minimum per ad set** so each of the six concepts gets a fair read. No edits for 72 hours after launch except disapprovals.
- **Days 8–14:** remove the ad-set minimums; let the campaign budget move to the winners.
- **Days 15–30:** the scaling rules below apply.

### 2.3 Scaling rules (per market, judged on the last 7 days)

| Signal | Action |
|---|---|
| An ad: ≥ €10 spent and link CTR < 0.5 %, or ≥ €15 spent and 0 scans | Pause it; replace in the Monday refresh |
| An ad set (concept): ≥ €50 spent and cost per scan result > €16 (2× target) | Pause it; its budget flows to the others; bring a new concept from the bank next Monday |
| Market: cost per paying customer ≤ €150 with ≥ 3 purchases (or ≤ €30 per trial start before purchases exist) | +20 % budget every 72 h, up to €150/day by day 30 |
| Market: cost per paying customer €150–300 | Hold budget; refresh creative; test the Dutch landing (NL) |
| Market: > €300 per paying customer for 7 days, or €600 spent with 0 purchases | −30 % budget; review landing, offer and scan flow before spending more |
| One market's cost per paying customer (or per trial start) < 70 % of the other's | Move €10/day to it (floor €30/day per market so the other keeps learning) |
| Founding seats reach 50 | Remove the pay-once line from a5 and the landing; the trial carries on |

### 2.4 After the test

- **Month 2 (December):** €100/day per market if cost per paying customer ≤ €225 and ≥ 20 % of November trials paid. Otherwise stay at €50 and fix the weakest funnel step first.
- **Month 3 (January):** up to €150–200/day per market while payback stays ≤ 3.5 months (EU §5.3: €171.50 average revenue, ~€85 contribution per account per month).

---

## 3. Campaign structure

### 3.1 One campaign per market

| Setting | NL | IE |
|---|---|---|
| Name | `OTTO · NL · Launch · 2026-11` | `OTTO · IE · Launch · 2026-11` |
| Objective | Leads, conversion location Website | same |
| Budget | Advantage+ campaign budget, €50/day, highest volume | same |
| Optimisation event | **Lead** (scan result, CAPI) in week 1–2; switch to **StartTrial** once `capi_track("trial_start")` fires ≥ 25 times a week in the market. If CAPI is not live at launch: link clicks, judged on first-party scans (§5) | same |
| Attribution | 7-day click, 1-day view (default) | same |
| Destination | The landing (English today; the Dutch variant when built, §8) with UTMs | The English landing |
| UTMs | `utm_source=meta&utm_medium=paid_social&utm_campaign=launch_2026-11_nl&utm_content={{ad.name}}` | `…_ie` |
| Ad names | The matrix cell id (`nl-a2-texts`), so first-party analytics, Meta and the matrix line up | same |

### 3.2 One ad set per concept (6 per market)

Ad set names come from the matrix (`ad_set`): `NL · a1 · Reels zonder te filmen` … `IE · a6 · December, sorted`. Each ad set runs
that concept's cells: at launch the 3 statics (4:5 feed + 9:16 story via asset customisation) and the faceless videos;
the creator video joins when the footage and the owner's signed release arrive (week 2–3).

### 3.3 Audiences

- **Hard controls (both markets):** location = the country; minimum age 25; no language restriction (many Dutch owners run their phone in English). Placements: Advantage+ placements (the renders cover 4:5 and 9:16).
- **Advantage+ audience on**, with the vertical stack of the concept's persona as the suggestion. Meta treats suggestions as a starting point, not a limit.
- **Interest stacks** (check each in Ads Manager before use: Meta removed or merged many detailed-targeting options between June 2025 and January 2026 (unv. for individual options)):

| Market | Vertical (EU §7) | Suggested interests / behaviours | Used on |
|---|---|---|---|
| NL | E-commerce / Shopify (no supplements) | Shopify, E-commerce, Online shopping (business), Small business owners, Facebook page admins | a2, a4, a5 |
| NL | Hospitality (café, lunchroom, restaurant, B&B) | Restaurants, Coffeehouses, Hospitality industry, Small business owners | a1, a6 |
| NL | Salons and local services (non-medical) | Hairdresser, Beauty salon, Nail salon, Small business owners | a3 |
| IE | Trades and local services | Plumbing, Construction, Electrician, Small business owners, Facebook page admins | a2, a4 |
| IE | Hospitality and tourism | Restaurants, Bed and breakfast, Hotels, Tourism | a1, a6 |
| IE | Dental and physio clinics | Physical therapy, Dentistry, Small business owners | a3, a5 |

### 3.4 Exclusions

- **Detailed-targeting exclusions no longer exist** (removed from ad sets in 2025). What remains: custom-audience exclusions, age, location, language, and account-level controls.
- Exclude: **buyers** (a Meta event audience of InitiateCheckout in the last 30 days until a purchase signal exists; plus a Whop buyer list only if the lawyer confirms the basis for uploading hashed e-mails), **Otto's team** (account-level employer exclusion), **existing pilot brands** (their page admins).
- Flanders is **not** targeted in November; Belgium bans all aesthetics advertising, which Otto's ads don't touch, but a separate BE location keeps the NL read clean (§3.6).

### 3.5 Advantage+ notes

- With six ad sets at €50/day, no ad set will leave the learning phase (Meta wants ~50 optimisation events per ad set per week). That is expected: judge concepts on cost per scan result and CTR, and let the campaign budget do the allocation.
- Only a share of visitors accept measurement, so Meta sees a share of the scans. **The source of truth is Otto's first-party funnel** (every visitor, cookieless) plus Whop; Meta's numbers steer delivery.
- Creator videos run as **partnership ads** (Paid partnership label) from the owner's account with their permission.

### 3.6 Flanders spillover

From day 15, if NL cost per scan result ≤ €8: duplicate the two best NL ad sets into a `OTTO · BE-VL` campaign (€15/day, location Flemish Region). Same creative; Dutch works in Flanders.

---

## 4. Creative: Otto marketing itself with its own engine

### 4.1 Where it lives

| What | Where |
|---|---|
| Brand | `brands/otto/`: `brand-profile.md` (personas per NL/IE vertical, visual identity), `strategy.json` (6 personas, pains, objections, proof bank, offer, targets), `compliance.json`, `competitors.json`, `angles.json` (ad copy per market), `render.json` (Mona Sans + the landing's tokens), `logo.svg` / `logo-white.svg`, `assets/` (phone cutouts of the real app: review NL/IE, 07:35 report, month) |
| Matrices | `brands/otto/ads-2026-11-nl.json`, `brands/otto/ads-2026-11-ie.json` (the `ads-YYYY-MM.json` schema, preset `launch`) |
| Video kit data | `brands/otto/video/brand.json`, `presentation-2026-11-{nl,ie}.json`, `video/2026-11-{nl,ie}/*.json` (13 per market, written by `motion/ad-kit/from_matrix.py`, copy verbatim) |
| Creator briefs | `brands/otto/creator-briefs-2026-11.md` (generated from the creator cells) |

### 4.2 The matrices (per market: 6 concepts × 6–7 styles = 37 ads, 19 video, 6 creator)

**NL** (Dutch, 14 styles; `--check`: 31 ready, 6 creator cells waiting for footage, 0 gaps, 0 copy gaps, 0 violations on 637 checked lines)

| Concept | Family · stage | Headlines | Styles |
|---|---|---|---|
| a1 Reels zonder te filmen | pain · cold | Reels zonder te filmen / Je website als reel | creator · notes video · versus video · product hero · search · big number |
| a2 Het bericht van 07:35 | experience · warm | Om 07:35 weet je hoe je ervoor staat / Eén bericht. Elke ochtend. | creator · texts video · big video · comparison · macro hero · notes |
| a3 Lokaal, niet vertaald | enemy (competitor research) · cold | Nederlands. Niet vertaald. / Klinkt als jouw zaak | creator · notes video · versus video · product hero · social post · carousel |
| a4 Jij onderneemt, Otto post | identity · cold | Jij onderneemt. Otto post. / Voor ondernemers zonder marketingteam | creator · big video · versus video · product hero · search · checklist |
| a5 7 dagen gratis | offer · hot (SIGN_UP) | Probeer Otto 7 dagen gratis / Geen creditcard nodig | creator · big video · texts video · versus video · offer · product hero · notes |
| a6 December al gepland | moment · warm | In november al klaar voor december / Jouw december, al gepland | creator · texts video · big video · before/after · product hero · search |

**IE** (Irish English, 15 styles; same check result: 31 ready, 6 planned, 0 gaps, 0 violations on 637 lines)

| Concept | Family · stage | Headlines | Styles |
|---|---|---|---|
| a1 Reels without the filming | pain · cold | Reels, without the filming / Your website, as a reel | creator · notes video · versus video · product hero · search · big number |
| a2 The 7:35 message | experience · warm | One message at 7:35 / Know by 7:35 every morning | creator (the plumber's own 7:35 message) · texts video · big video · comparison · macro hero · notes |
| a3 Local, not generic | enemy (competitor research) · cold | Written for Cork. Not California. / Sounds like your business | creator · notes video · versus video · product hero · social post · myth/fact |
| a4 You run it, Otto posts | identity · cold | You run the business. Otto posts. / For owners with no marketing team | creator · big video · versus video · product hero · search · checklist |
| a5 7 days free | offer · hot (SIGN_UP) | Try Otto free for 7 days / No card needed | creator · big video · texts video · versus video · offer · product hero · notes |
| a6 December, sorted | moment · warm | December, sorted before the rush / Christmas, planned in November | creator · texts video · big video · before/after · product hero · carousel |

Every angle has 2–3 primary texts. A native Dutch review pass (fresh eyes) was applied: calques and grammar fixed ("doe je met één tik", "loopt terug", "binnen een uur", "websiteadres"), claims tightened ("eerste posts binnen 24 uur" instead of "live", "veel bureaus" instead of all agencies, no 50-seat line). The Dutch copy was written in Dutch (je/jij, "excl. btw", Sinterklaas, "de eerste terrasdag"), the Irish copy for Irish owners (Cork, Galway, "Go on", "your say-so", colour with a u). Neither is a translation of the other.

### 4.3 What was rendered and reviewed

- **All 18 image cells per market**, feed and story (36 files each), rendered with `otto_creative.py matrix otto 2026-11 --render` in an isolated workspace, and reviewed card by card on contact sheets. Fixes made during review: phone cutouts re-cut so the renderer treats them as packshots (the offer card had cropped the phone full-bleed), "Sample" moved onto the visible side of the report screen, checklist ticks, an internal proof id removed from a source line, a stray tiny phone removed, a wrapping callout shortened, a white logo for dark video end cards.
- **8 faceless videos** (4 per market) with `motion/ad-kit` (`build.mjs` → `ship.mjs`: check, render, −14 LUFS, poster, web copy, key-frame sheet): NL a2 texts (the 07:35 message), a1 notes, a3 versus, a5 big; IE a2 texts, a1 notes, a3 versus, a4 big. 10–16 s, 9:16, synthesized music and UI sounds, no voice. The other 9 per market are scripted (kit JSON written) and render with the same two commands.
- Files: see "Report" in the handover; contact sheets and videos are in the session scratchpad, not in the repo.

### 4.4 Weekly creative refresh (every Monday, per market)

1. Pull the last 7 days: per ad, spend, CTR, cost per scan result; per concept, cost per trial start and per paying customer (first-party + Whop).
2. Pause per §2.3. Keep the winners untouched.
3. Add **one new creative per live concept** (6 a week per market), dated `"added"` in the matrix (set `"launched": "2026-11-02"` at the top of each matrix on launch day so `--check` prints the refresh lines): first a re-cut of the concept's winner in a style it hasn't run (e.g. the winning static as its motion version), then new styles. Otto's engine flags a concept with no new creative (`matrix --check` refresh lines).
4. Every second week, retire the weakest concept and bring one from the bank (e.g. "What your competitors changed this week", "Approve like you answer a text").
5. Creator videos: add each as it arrives (week 2–3); they usually become the winners in this category (COMPETITORS §3, pattern 5).
6. Dutch reviewer checks every new NL line before it goes live.

### 4.5 Rendering Otto's own ads (for whoever runs the Monday refresh)

The engine reads one matrix per brand and month (`brands/<id>/ads-YYYY-MM.json`) and one language per brand, so render each
market in a throwaway workspace: nothing is written to the repo or to `platform/data.json`.

```bash
MK=nl                                   # or ie
W=$(mktemp -d); mkdir -p $W/brands $W/assets $W/fonts $W/secrets
cp -R ~/otto/brands/otto $W/brands/otto
cp $W/brands/otto/ads-2026-11-$MK.json $W/brands/otto/ads-2026-11.json
# the market's language and baselines
python3 - "$W" "$MK" <<'EOF'
import json, sys, hashlib, base64
from pathlib import Path
W, mk = Path(sys.argv[1]), sys.argv[2]; b = W / "brands/otto"
r = json.loads((b / "render.json").read_text()); r["lang"] = "nl" if mk == "nl" else "en"; (b / "render.json").write_text(json.dumps(r))
c = json.loads((b / "compliance.json").read_text()); c["countries"] = [mk.upper()]; (b / "compliance.json").write_text(json.dumps(c))
(W / "data.json").write_text('{"brands": [], "posts": [], "campaigns": [], "recommendations": []}')
# otto_render has no FONT_SPECS entry for Mona Sans (a Google fetch would load weight 400 only): seed its cache with the landing's woff2
key = hashlib.sha1((json.dumps(["Mona Sans"]) + json.dumps(["latin", "latin-ext"])).encode()).hexdigest()[:16]
woff = base64.b64encode((Path.home() / "otto/platform/assets/landing/mona-sans-latin.woff2").read_bytes()).decode()
(W / "fonts" / f"{key}.css").write_text("@font-face{font-family:'Mona Sans';font-style:normal;font-weight:400 800;"
                                        f"font-display:block;src:url(data:font/woff2;base64,{woff}) format('woff2');}}")
EOF
cd ~/otto/platform
E="OTTO_DATA=$W/data.json OTTO_HTML=$W/index.html OTTO_BRANDS=$W/brands OTTO_ASSETS=$W/assets OTTO_PUBLIC_ASSETS= OTTO_SECRETS=$W/secrets OTTO_EVENTS=$W/events.jsonl OTTO_FONT_CACHE=$W/fonts OTTO_RENDER_TMP=$W/tmp"
env $E python3 otto_creative.py matrix otto 2026-11 --check
env $E python3 otto_creative.py matrix otto 2026-11 --render $W/out && python3 otto_render.py sheet $W/sheet.jpg $W/out
# faceless videos: kit JSON from the matrix, then build + ship one cell
cd ~/otto/motion/ad-kit
python3 from_matrix.py --matrix ~/otto/brands/otto/ads-2026-11-$MK.json --brand ~/otto/brands/otto/video/brand.json \
                       --presentation ~/otto/brands/otto/video/presentation-2026-11-$MK.json
node build.mjs --brand ~/otto/brands/otto/video/brand.json --ad ~/otto/brands/otto/video/2026-11-$MK/$MK-a2-texts.json --out $W/v --format 9x16
node ship.mjs $W/v --name $MK-a2-texts-9x16 --final $W/final --web $W/web
```

Renderer follow-up (for the renderer's owner, not done here): add `"Mona Sans": "Mona+Sans:wght@400..800"` to
`otto_render.FONT_SPECS` so server renders get the right weights without the cache seed.

---

## 5. Funnel, events and target rates

### 5.1 The funnel

| Step | What happens | First-party event (`/otto-track`, every visitor, cookieless) | Meta event (CAPI, consented visitors only) | Target (EU §5.3) |
|---|---|---|---|---|
| Ad | Impression → link click | – | – | CPM NL €9–14, IE €9–13 · CTR 0.8–1.0 % · CPC €0.9–1.7 (plan ≤ €1.30) |
| Landing | Page view (UTMs recorded) | `view` (+ scroll, sections) | – (no PageView: there is no browser pixel) | ~85 % of clicks load the page (est.) |
| Scan | The visitor types their site | `scan_start` | **ViewContent** | 15–25 % of visitors (plan 20 %) |
| Preview | Otto shows what it read | `scan_result` (ok) | **Lead** (the optimisation event) | ~90 % of scans succeed (est.) · **≤ €8 per scan result** |
| Trial CTA | "Start free 7-day trial" (or the pay-once link) | `cta` `start_trial@…` / `get_started@…` | **InitiateCheckout** | 30–40 % of scans (est.) |
| Trial start | Google sign-in completes, trial created | server (`otto_trial`) | **StartTrial** (and CompleteRegistration) via `otto_track.capi_track` (§1.2 item 6b) | 60–70 % of trial clicks (est.) → ~25 % of scans · ≤ €30 per trial |
| Paid | Card added before day 7 (Whop), or the pay-once founding pilot | Whop webhook (`otto_whop`) | – (server-to-server, no consent context) | **18–25 % of trials** (18.2 % of no-card trials convert, EU §5.3 [A8]) → ~5 % of scans |
| Onboarding | Brand set up, first posts ready | `otto_onboard` | – | ≥ 80 % approve a first post within 24 h |
| Habit | A decision taken from the 07:35 report | one-tap links / app (no open tracking, by design) | – | a decision (approve, skip or change) within 2 hours of 07:35 on ≥ 5 of 7 mornings in week 1 |
| Retention | Month 2 on the plan | Whop | – | ≥ 85 % of paying customers (est.) |

### 5.2 What €1,500 per market should produce (30 days)

| | Pessimistic | **Plan** | Optimistic |
|---|---|---|---|
| CPC | €1.70 | **€1.30** | €0.90 |
| Visitors | ~750 | **~1,000** | ~1,400 |
| Scans (15 / 20 / 25 %) | ~110 | **~200** | ~350 |
| Cost per scan result | ~€15 | **~€8** | ~€4.80 |
| Trial starts (20 / 25 / 30 % of scans) | ~22 | **~50** | ~105 |
| Cost per trial start | ~€68 | **~€30** | ~€14 |
| Paying customers (15 / 20 / 25 % of trials) | ~3 | **~10** | ~26 |
| Cost per paying customer | ~€500 | **~€150** | ~€58 |

EU §5.3 tells us to **plan with €150–300 per paying customer** (the B2B owner multiplier on CPM is an estimate), i.e. 5–10 per
market and **10–20 across both**. A no-card trial adds a step, so the pessimistic column is worse than with a direct sale; the
day-15 rules in §2.3 exist for exactly that case.

### 5.3 KPI traffic lights (weekly, per market)

| KPI | Green | Amber | Red |
|---|---|---|---|
| Link CTR | ≥ 0.8 % | 0.5–0.8 % | < 0.5 % |
| CPC | ≤ €1.30 | €1.30–1.70 | > €1.70 |
| Visitors who scan | ≥ 20 % | 15–20 % | < 15 % |
| Cost per scan result (Lead) | ≤ €8 | €8–12 | > €12 |
| Scans that start a trial | ≥ 25 % | 15–25 % | < 15 % |
| Cost per trial start | ≤ €30 | €30–50 | > €50 |
| Trials that pay | ≥ 25 % | 15–25 % | < 15 % |
| Cost per paying customer | ≤ €150 | €150–300 | > €300 |
| Trials approving a first post within 24 h | ≥ 80 % | 60–80 % | < 60 % |
| Consent acceptance (information) | – | – | – |

### 5.4 Consent and measurement (shipped in this pass)

- `platform/assets/consent.js` + `consent.css`, one include line in `landing.html` and **Privacy choices** in the footer. One question ("Can Otto measure its ads?" / "Mag Otto zijn advertenties meten?"), Reject and Accept equal and side by side, no cookie wall, remembered 180 days in the first-party `otto_consent` cookie, reopened from the footer, English or Dutch by browser language, DNT/GPC treated as reject. On phones the banner is compact and the sticky "Get started" dock rides above it until the visitor chooses.
- **No browser pixel.** The CSP stays same-origin. `otto_track.py` forwards consented events to the Meta Conversions API from the server, only when `$OTTO_SECRETS/meta-capi.json` has a pixel id and token **and** the request carries `otto_consent=v1.granted` **and** there is no DNT/GPC. Sent: event name, time, event id, page URL, IP and user agent (required by Meta, never stored by us), the click id from `otto_fbc` (set only after Accept, from `?fbclid=`), SHA-256 of the day's visitor code and of the country. Never sent: the scanned domain, referrer, UTMs, anything typed.
- CTA kinds `get_started`, `start_trial`, `trial`, `signup`, `sign_up` → InitiateCheckout. `capi_track("signup" | "trial_start", ip, headers)` → CompleteRegistration / StartTrial, for the server that completes a sign-up; not accepted from the public beacon, so conversions cannot be spoofed.
- Tests: `platform/tests/test_capi.py` (15, fake Graph endpoint). Legal: `docs/legal/cookies.md` and `privacy.md` describe it (drafts for the lawyer).
- Setup check: `python3 otto_track.py capi-status` (no network), `python3 otto_track.py capi-test` (one test event; needs `test_event_code`, which must be removed before launch: test events are not dropped by Meta).

---

## 6. Founder LinkedIn (Max, English)

Why: in the Netherlands LinkedIn has 14.0 M members and Ireland 3.7 M (EU §6.2); founder posts get 10–30× the reach of product
posts in this category (COMPETITORS §1.3, §3). Rules: real numbers only, no "Introducing: feature X", no emoji hooks, no
"autopilot", no competitor names, every visual made with Otto and labelled so. Cadence: weekday posts, weekends for comments and
light reshares. Each post ends with one soft CTA at most ("scan your site", link in the first comment).

### 6.1 Thirty days (Mon 2 Nov – Tue 1 Dec 2026)

| Day | Date | Hook / post | Format |
|---|---|---|---|
| 1 | Mon 2 Nov | "Today Otto opens in the Netherlands and Ireland. Why those two first, not the UK." (the data behind the choice) | Text + one chart |
| 2 | Tue 3 Nov | "One message at 7:35: the anatomy of Otto's daily report" (sample figures labelled) | 6-slide PDF carousel |
| 3 | Wed 4 Nov | "Why Otto asks before it posts" | Text |
| 4 | Thu 5 Nov | Emerce EDAY / NXT:Commerce, Amsterdam: "What I'm listening for at EDAY today" (if attending) — otherwise "A reel from a website that has no video on it" | Photo or 30 s reel |
| 5 | Fri 6 Nov | "Written for Cork, not California: three sentences that give away a generic post" | Carousel |
| 6 | Sat 7 Nov | Reshare one launch ad with the story of how Otto made it | Light |
| 7 | Sun 8 Nov | Comment on 10 posts by Dutch and Irish owners | Engagement |
| 8 | Mon 9 Nov | "Week 1 of marketing an AI marketing company: the real numbers" (spend, scans, trials) | Text + screenshot |
| 9 | Tue 10 Nov | "Same café, two countries": one café's post in Dutch and in Irish English | Carousel |
| 10 | Wed 11 Nov | "The skip button is the product": how skips and edits teach Otto | Text + image |
| 11 | Thu 12 Nov | "What one free week with Otto produces, line by line" (a real trial, with permission; no agency price table) | Carousel |
| 12 | Fri 13 Nov | KVK Ondernemersdagen (Utrecht, 13–14 Nov) / Limerick Chamber awards (13 Nov): where to find me | Short text |
| 13 | Sat 14 Nov | "Three posts every Dutch shop can make before 5 December" (Sinterklaas; for saves) | Carousel |
| 14 | Sun 15 Nov | Engagement | – |
| 15 | Mon 16 Nov | "Two weeks, six concepts, 37 ads per market: what's winning in Otto's own ads" | Text + contact sheet |
| 16 | Tue 17 Nov | "Why every Otto ad says it was made with Otto" (EU AI Act Art. 50, labelling) | Text |
| 17 | Wed 18 Nov | Founder story: why a marketing department for owners who have no time | Text + photo |
| 18 | Thu 19 Nov | "Website in, reel out": 45 s screen recording, site → storyboard → reel | Video |
| 19 | Fri 20 Nov | Dag van de Ondernemer (NL): "To every owner who posted at 11pm this year" | Text |
| 20 | Sat 21 Nov | Poll: "When do you do your marketing? Morning · Lunch · Evening · Never" | Poll |
| 21 | Sun 22 Nov | Engagement | – |
| 22 | Mon 23 Nov | "Our first creator: a café owner filmed his own reel review" (with consent) | Video |
| 23 | Tue 24 Nov | "The 7:35 report, three weeks in: what owners actually open" (real data only) | Text + chart |
| 24 | Wed 25 Nov | "Compliance you don't see: how Otto holds a clinic post that could break the ad rules" | Carousel |
| 25 | Thu 26 Nov | Frankwatching AI Marketing Event (Utrecht): "Five rules for AI marketing that doesn't look like AI" | Carousel |
| 26 | Fri 27 Nov | "We're not doing Black Friday. Here's what we do instead" (no fake urgency) | Text |
| 27 | Sat 28 Nov | Reshare a client post made by Otto (with permission) | Light |
| 28 | Sun 29 Nov | Engagement | – |
| 29 | Mon 30 Nov | "Month one: what we got wrong" | Text |
| 30 | Tue 1 Dec | "December is planned: how Otto built a month for a café" | Carousel |

### 6.2 Communities and events (window Nov 2026 – Feb 2027; dates from the organisers unless marked)

**Netherlands**
- Emerce EDAY, Thu 5 Nov 2026, Kromhouthal Amsterdam (e-business, 2,000+) — emerceeday.nl
- NXT:Commerce Summit, 5 Nov 2026, Felix Meritis Amsterdam (D2C brands; organised by Ask Phill, a Shopify partner) — nxtcommercesummit.com
- KNGF FysioCongres, 6 Nov 2026, Barneveld (physio practice owners; content hook only)
- Beauty Live, 7–8 Nov 2026, Messe Kalkar (DE border; Dutch-language beauty trade fair)
- **KVK Ondernemersdagen, 13–14 Nov 2026, Jaarbeurs Utrecht** — the largest free MKB gathering in the window (kvk.nl)
- **Dag van de Ondernemer, Fri 20 Nov 2026** (MKB-Nederland; local ondernemersontbijten)
- Frankwatching AI Marketing Event, 26 Nov 2026, Jaarbeurs Utrecht; SocialToday, 11 Feb 2027
- KNMT year-end meeting (dentists), 30 Nov 2026, Woerden (members only; content hook)
- **Horecava, 11–14 Jan 2027, RAI Amsterdam** — the main hospitality event in the window
- InfraTech 12–15 Jan 2027 (Rotterdam Ahoy); BouwBeurs 1–5 Feb 2027 (Jaarbeurs) — trades
- Online: EcomCommunity (Discord, 3,000+ Dutch webshop owners, self-reported); Frankwatching; MKB-Nederland company page. No active Dutch LinkedIn groups or Shopify meetups found for the window (unv.).
- Outside the window: Webwinkel Vakdagen 7–8 Apr 2027; Beauty Trade Special 3–5 Apr 2027.

**Ireland**
- SME & Clusters Assembly (EU SME Week), 3–4 Nov 2026, Dublin (policy-heavy)
- **SFA Annual Lunch, Fri 6 Nov 2026, Mansion House Dublin** (400+ small-business leaders)
- Irish Dental Association: dental nurses day 6 Nov; Colgate Caring Dentist 21 Nov (Dublin)
- Limerick Chamber Regional Business Awards, Fri 13 Nov 2026, Limerick (400+)
- Good Food Ireland 20th anniversary awards, Mon 16 Nov 2026, InterContinental Dublin (hospitality)
- Dublin Chamber: tourism & hospitality evening 17 Nov; "How to Win High-Value Clients on LinkedIn" 24 Nov
- **Local Enterprise Showcase, 17–19 Jan 2027, RDS Dublin** (LEO small businesses)
- **CATEX, 16–18 Feb 2027, RDS** (foodservice and hospitality, free entry)
- Shopify Meetup Ireland (Milk Bottle Labs; Dublin and Cork, dates ad hoc); Irish Small Business (Meetup, ~421 members, unv.)
- Not in the window or unannounced: Local Enterprise Week (usually March), Irish Hotels Federation conference 2027 (unv.), ISME lunch 2026 (unv.).
- **Grants:** the Trading Online Voucher closed on 13 Dec 2024. Its successor, the **Grow Digital Voucher** (50 %, €500–5,000, after an LEO "Digital for Business" project), covers up to a year of off-the-shelf software subscriptions, including AI software; whether Otto qualifies is decided per LEO (unv.). Worth one line on the IE landing FAQ once confirmed with an LEO.

---

## 7. Partner channel: web and Shopify agencies on the Agency plan

### 7.1 The offer (when it exists)

EU §4.1: **Agency from €499 a month for 5 client workspaces at Starter level, +€79 per extra workspace**, client approval links,
white-label reports, partner support. It is **not on Whop yet**. Until it is, the only honest partner offer is a referral of
clients to the free trial; no commission system exists, so promise none.

Why these agencies: they build sites and shops for small businesses and stop there. Their clients then ask "who does our
Instagram and ads?"; a full retainer is too small for most agencies to staff. Otto is the layer they can resell.

**Status: nobody has been contacted.** Outreach starts only when Max approves it and the Agency plan is live; a sequence is in §7.4.

### 7.2 Netherlands (20, from the Shopify Partner Directory and Sortlist; all sites checked live on 30.09.2026)

| # | Agency | City | Website | Found via | Why it fits |
|---|---|---|---|---|---|
| 1 | Kroononline | Woerden | kroononlinedesign.nl | Shopify Partner Directory | Shops (€1.5–2.75k) for starters and small owners; SEO/e-mail/Google Ads add-on, no social |
| 2 | Studio Dot | Rotterdam | studio-dot.nl | Shopify Partner Directory | Two founders; Shopify builds for small webshops; no marketing services |
| 3 | Briefvibe | Zoetermeer | briefvibe.nl | Shopify Partner Directory | 400+ webshops built for starters and SMEs; builds only |
| 4 | Online Origins | 's-Hertogenbosch | onlineorigins.nl | Shopify Partner Directory | Shopify builds, migrations, apps; no social or ads |
| 5 | Sell your stuff online | Den Haag | sellyourstuffonline.nl | Shopify Partner Directory | Branding + Shopify packages for small entrepreneurs; content/e-mail add-on, no social ads |
| 6 | Opklopper | Amsterdam | opklopper.nl | Shopify directory (NL) / Sortlist | 250+ projects (fashion, food, retail); SEO/CRO, no social or ads |
| 7 | Groove Digital | Amsterdam | groovedigital.agency | Shopify Partner Directory | Shopify + Webflow for SMEs incl. hospitality; no social or ads |
| 8 | Codemaker-S | Eindhoven | codemaker-s.com | Shopify Partner Directory | Shopify builds for SMEs in NL and BE; no marketing |
| 9 | Bakker Media | Groningen | bakkermedia.com | Shopify Partner Directory | One-person Shopify/WordPress builder for owners |
| 10 | Studio RAO | Dordrecht | studiorao.nl | Shopify Partner Directory | Development-only Shopify agency (161 reviews); no social or ads |
| 11 | XY Web Solutions | Utrecht | xyws.nl | Sortlist | WordPress sites/shops + hosting for MKB; no marketing retainer |
| 12 | WP Web Creaties | Dordrecht | wpwebcreaties.nl | Sortlist | Solo WordPress builder for freelancers, clubs, small businesses |
| 13 | Digital Compass | Leiden | digitalcompassdesign.com | Sortlist | WordPress/WooCommerce for small local firms (physios, shops) |
| 14 | Horeca Webservice | Ede | horecawebservice.nl | Web search | Builds and maintains restaurant and hotel sites; newsletters, no social or ads |
| 15 | Gaia Digital | Amsterdam | gaiadigital.nl | Sortlist | Web, shops, branding for 100+ startups and SMEs; no social or ads |
| 16 | Euforie Online | Uden | euforie.online | Sortlist | Branding + WordPress for local businesses (incl. food) |
| 17 | B2Design | Groningen | b2design.nl | Sortlist (search result) | WordPress sites/shops since 2004; SEO add-on only |
| 18 | WOW media | Amsterdam | wowmedia.nl | Sortlist | Web design + hosting for 500 starter/MKB sites; mentions some social (light) |
| 19 | Crads | Eindhoven | crads.nl | Sortlist | WordPress/Shopify for local MKB (care, construction); SEO/Google Ads, no Meta |
| 20 | Web Rabbitz | Waddinxveen | webrabbitz.nl | Web search | Sites, shops, hosting and IT support for small MKB around Gouda |

Alternates: PlazaXL (Leeuwarden; salon sites on subscription, but sells social too), Nedfinity (Zwolle), Shopmonkey (Haarlem).
Left out: agencies that sell Meta/social retainers (competitors, not partners), mid-market-only shops, one site that redirected to an unrelated domain.

### 7.3 Ireland (20, from the Shopify Partner Directory, GoodFirms and search; all sites checked live on 30.09.2026)

| # | Agency | Town | Website | Found via | Why it fits |
|---|---|---|---|---|---|
| 1 | Sharp Media Agency | Dublin | sharpmediaagency.com | Shopify Partner Directory | Shopify for SMEs with payment plans; ads a side service Otto could take over |
| 2 | radical ecom | Dublin | radicalecommerce.com | Shopify Partner Directory | Shopify builds + monthly management for SME food/retail; no social or ads |
| 3 | Q Division | Dublin | qdivision.ie | Shopify Partner Directory | Technical Shopify/POS since 2014; marketing minor |
| 4 | Lightyear Creative | Dublin 12 | lightyear.ie | Shopify Partner Directory | Early Irish Shopify Experts; SME builds and branding, no ads |
| 5 | FelleMedia | Dublin | fellemedia.com | Shopify Partner Directory | Small award-winning Shopify/CRO shop; no social/ads (clients skew larger) |
| 6 | Castle Commerce | Claregalway | castlecommerce.ie | Shopify Partner Directory | Shopify for hardware/agri/owner-run businesses; supports owners over WhatsApp |
| 7 | Little & Large | Galway | littleandlarge.ie | Shopify Partner Directory | Branding + Shopify for Irish SME retail; no paid-social retainer |
| 8 | Perfidious Albert | Dundalk | perfidiousalbert.com | Shopify Partner Directory | Shopify + Klaviyo for independent retailers; e-mail, not social |
| 9 | Netboost | Galway | netboost.ie | GoodFirms | Sites from €500 for local trades and SMEs; light ads add-on |
| 10 | Martec | Galway | martec.ie | GoodFirms | Low-cost web since 1996 for hospitality, restaurants, retail |
| 11 | Studio Nowinter | Cork | studionowinter.com | GoodFirms | Small WordPress/Shopify studio; hosting, no marketing retainer |
| 12 | Webie | Waterford | webie.ie | GoodFirms | WordPress/WooCommerce packages for small businesses; no social |
| 13 | Istech Web Design | Kilkenny | istech.ie | Web search | Sites for trades, clinics and local businesses with care plans |
| 14 | Little Blue Studio | Limerick | littlebluestudio.ie | bestinireland.com | Bespoke sites with a tourism/hospitality client list |
| 15 | Egg Design | Killarney | eggdesign.ie | GoodFirms | WordPress/WooCommerce for Kerry hospitality |
| 16 | Design Web Studio | Ennis | designwebstudio.ie | GoodFirms | Small studio building WordPress/Shopify for local businesses |
| 17 | Firesky Studios | Ennis | fireskystudios.com | GoodFirms | Budget designs, Shopify theme work, hosting; mentions Grow Digital |
| 18 | Logicode Digital | Cavan | logicode.ie | GoodFirms | Bespoke sites for local hospitality and SMEs; no social or ads |
| 19 | Eflow Solutions | Dún Laoghaire | eflowsolutions.ie | GoodFirms | Sites for trades/services in 4–7 days; Google Ads but no social |
| 20 | Stewart Design | Dublin | stewartdesign.ie | GoodFirms | One-off business-site packages with no recurring marketing |

Backups: McBride Digital (Letterkenny), Moji (Spiddal). Left out: Cork agencies whose core is ads/social (competitors).

### 7.4 Outreach sequence (draft, not sent; only after Max's go and the Agency plan on Whop)

1. Week 1 of approval: a personal LinkedIn note from Max to the founder (no automation): "You build the shop; your clients then ask who runs their Instagram. We built Otto for that gap…", link to a 60-second Otto film.
2. Offer: a free partner workspace for their own agency plus 30 days for two of their clients, then the Agency plan at list price.
3. Success signal: 5 NL + 5 IE partners in a pilot by day 60; at least 10 client workspaces live by day 90.
4. Never: bulk e-mail to these addresses (e-mail marketing rules for businesses in NL/IE apply; check with the lawyer first).

---

## 8. Dutch landing variant

**Recommendation: build `/nl` (a copy of `landing.html` with `lang="nl"`) before NL spend passes €50/day, and at the latest
in week 3.** Dutch ads that land on an English page lose some of the "local, not translated" promise, even if Dutch owners read
English well (EF EPI #1). The copy is ready for review in **`platform/landing-nl-copy.md`**: every section of the current
landing rewritten in Dutch (not translated), plus notes for the builder where the English page says something untrue for the
Netherlands today (Telegram approvals, content languages, where data is hosted) and strings for the free-trial variant.

Test plan: from day 15, send 50 % of NL traffic (all ad sets, via the URL) to `/nl` and 50 % to the English landing for 14
days. Decide on scan rate and cost per scan result; expect Dutch to win and keep English only for Flanders tests if not.

The consent banner is already bilingual: on `/nl` it shows Dutch because of `lang="nl"`.

---

## 9. KPIs

| Level | KPI | Target for the 30-day test |
|---|---|---|
| North star | Paying customers (trial → plan, or the pay-once pilot) | 10–20 across both markets (plan); ~25 is the stretch |
| Efficiency | Cost per trial start · cost per paying customer | ≤ €30 · ≤ €225 blended (EU §5.3 planning range €150–300) |
| Funnel | Cost per scan result (Lead) | ≤ €8 per market |
| Funnel | Visitor → scan · scan → checkout · checkout → paid | 20 % · 15 % · 35–50 % |
| Creative | Link CTR · share of spend on video | ≥ 0.8 % · ≥ 50 % |
| Activation | First post approved ≤ 24 h after sign-up | ≥ 80 % of trials |
| Habit | Decision from the 07:35 report within 2 hours | ≥ 5 of 7 mornings in week 1 |
| Conversion and retention | Trials that pay · paying customers still on a plan in month 2 | ≥ 20 % · ≥ 85 % (est.) |
| Organic | LinkedIn: founder posts · average reactions · profile visits → scans | 22 weekday posts · ≥ 50 · tracked by `utm_source=linkedin` |
| Partners | Agencies in a pilot (after approval) | 10 by day 60 |
| Quality | Ads rejected by Meta · compliance holds · NL copy edits by the reviewer | 0 · 0 at launch · all resolved before a line runs |

Where each number comes from: first-party analytics in the owner console (`/otto-track`), Whop (purchases), Meta Ads Manager
(delivery), Otto's own app data (activation, decisions taken from the morning report; e-mail opens are not tracked).

---

## 10. 30 / 60 / 90 days

**Days 1–30 (2 Nov – 1 Dec): launch and learn**
- Both markets live on 2 Nov at €50/day with the 31 ready ads per market; the Monday refresh from 9 Nov.
- Creator-owners recruited from the first trial users and paying customers, filmed by day 14, live by day 21.
- Dutch landing built by day 15, A/B from day 15.
- LinkedIn plan §6.1; KVK Ondernemersdagen (13–14 Nov) in person if possible.
- Partner lists ready; no contact until approval.
- Exit: ~100 trial starts and 10–20 paying customers, cost per trial and per customer known per market, a winning concept per market.

**Days 31–60 (2 Dec – 31 Dec): scale what works**
- Budgets per §2.4 (€100/day per market if cost per paying customer ≤ €225).
- Close the pay-once founding offer at 50 seats or on a dated notice (EU §4.4); add the approved monthly price to the a5 lines (§1.3).
- StartTrial becomes the optimisation event once it has volume (≥ 25 a week per market).
- Retargeting campaign (scanned, not bought; 14 days) at 15 % of budget.
- Flanders spillover if NL is on target; partner pilot with 3–5 agencies per country after Max's approval.
- First case study from a paying customer (written consent, real numbers).

**Days 61–90 (1 Jan – 31 Jan): make it repeatable**
- €150–200/day per market while payback ≤ 3.5 months.
- Horecava (11–14 Jan, Amsterdam) and the Local Enterprise Showcase (17–19 Jan, Dublin) for founder presence and creator recruiting.
- Churn and plan mix review: monthly churn < 8 % (est.); Growth share of plans ≥ 30 %.
- Prepare Germany/Austria and the UK per EU §7 (German UI, GBP plans); reuse the Irish matrix for the UK with British spelling.

---

## 11. What Max must set up (checklist)

| # | Task | Detail | Before |
|---|---|---|---|
| 1 | **Meta business portfolio + ad account** | Company-owned portfolio; ad account in EUR, payment method, spending limit €3,500; Otto Facebook Page + Instagram professional account as the ad identity; verify the new domain | 26 Oct |
| 2 | **Dataset (pixel) + Conversions API token** | Create a dataset in Events Manager (its id is the `pixel_id`); a system user with access to it and a generated token; write `$OTTO_SECRETS/meta-capi.json` = `{"pixel_id": "…", "access_token": "…", "test_event_code": "TEST…", "site_url": "https://<domain>"}` (chmod 600); run `python3 otto_track.py capi-status`, then `capi-test`; see the event under Test events; **remove `test_event_code`** | 28 Oct |
| 3 | **Budget and price approval** | €3,000 media + €900 creators + €300 Dutch reviewer ≈ €4,200 for November; month 2 only on the §2.4 rule. Approve the draft monthly prices (Starter €99, Growth €249) so trials can convert | 23 Oct |
| 4 | Domain + Hetzner move | docs/HOSTING.md; set `OTTO_ALLOWED_ORIGINS`; the CAPI `event_source_url` uses the Origin | 28 Oct |
| 5 | Stripe | Selling entity (Israel is not supported), account, Stripe Tax, **Starter and Growth prices in EUR** (after the price approval), webhook, keys — docs/BILLING.md "What Max sets up in Stripe" | 28 Oct |
| 6 | **LinkedIn** | Max's profile (headline "Building Otto: the marketing department for small businesses in NL and IE"), banner made with Otto; the Otto company page; schedule §6.1 | 30 Oct |
| 7 | Creators | Ask the first trial users and customers; €150 each for two takes + a free month; signed release (template from the lawyer); partnership-ad permission in Meta | day 7–14 |
| 8 | Dutch reviewer | ~6 h: the NL matrix, `landing-nl-copy.md`, then each weekly refresh | 23 Oct |
| 9 | ~~Product fixes (§1.2)~~ | **Done 1.10:** FAQ lists Dutch, e-mail approvals, the 07:35 report in English / Dutch / German, StartTrial to Meta | — |
| 10 | Legal | Lawyer review of cookies/privacy (Meta joint controllership, consent), creator release, the creator row in privacy.md | 30 Oct |
| 11 | Partners | Approve (or not) the outreach in §7.4; nothing happens without it | day 30 |

---

## 12. Risks

1. **Signal loss from consent.** Only consenting visitors reach Meta; optimisation on Lead may be slow. Mitigation: judge on first-party data; keep six ad sets but let the campaign budget concentrate; consider consolidating to three ad sets per market if nothing exits learning by day 14.
2. **B2B CPMs above the estimate** (EU §5.3 assumes 1.2–1.8× consumer CPM). Mitigation: the §2.3 rules cap the loss at about €600 per market before a rethink.
3. **"Dutch" promise vs English app and report.** Mitigation: §1.2 items 3–5; honest FAQ line in the Dutch landing.
4. **Monthly plans must exist on Whop before the first trial ends (9 Nov).** Otherwise trials cannot convert and the test measures nothing past sign-up.
5. **Creator supply.** No customers yet means no creators until the first trials run; faceless videos carry weeks 1–2 by design.
8. **A no-card trial adds a step.** Trials convert at ~18 % industry-wide (EU §5.3 [A8]); if November trials convert below 15 %, fix onboarding and the day-5 e-mail before buying more trials.
6. **Unverified targeting options** (§3.3) and **Grow Digital eligibility** (§6.2): check before relying on them.
7. **Native could start advertising in NL/IE in Dutch** (it writes in 183 languages). Otto's edges stay reels, the 07:35 report, local copy and a human; keep them as the headline.

---

## 13. Sources

Internal: `research/EU-LAUNCH-AND-PRICING-2026-09.md` (§1 answer, §3.4 NL/IE price ranges, §4.1 plans, §4.4 founding bridge,
§5.3 CPM, CTR, CPC, scan and conversion rates, payback, §6.2 LinkedIn members and messaging, §6.5, §7 verticals, §8 product
changes) · `research/COMPETITORS-2026-09.md` (§1.4 Native's ad countries and phrases, §3 patterns, §5 hooks and objections, §6
concepts) · `docs/HOSTING.md` · `docs/COMPLIANCE-BASELINES.md` · `platform/landing.html` (offer and product facts, 30.09.2026).

Web (accessed 30.09.2026 by research sub-agents; read-only, nobody contacted):
- Meta: Advantage+ campaign budget — facebook.com/business/ads/meta-advantage-plus/budget; Advantage+ audience — facebook.com/business/ads/meta-advantage-plus/audience; detailed-targeting exclusions removed (Graph API v22.0 changelog) — developers.facebook.com/docs/graph-api/changelog/version22.0/; v26.0 changelog (29.07.2026); Conversions API parameters — developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event and …/customer-information-parameters; using the API (test_event_code) — developers.facebook.com/docs/marketing-api/conversions-api/using-the-api; interest consolidation 2025–26 (3p) — socialmediatoday.com/news/meta-removes-more-detailed-ad-targeting-options-facebook-instagram/757856/
- Events NL: emerceeday.nl/info · nxtcommercesummit.com · kngf.nl/evenementen/fysiocongres · beautylive.eu/nl · kvk.nl/evenementen/kvk-ondernemersdagen-2026 · helmond.nl (Dag van de Ondernemer 20.11.2026) · frankwatching.com/events · knmt.nl/evenementen/eindejaarsbijeenkomst · horecava.nl/en · ahoy.nl (InfraTech 2027) · jaarbeurs.nl (BouwBeurs 2027) · ecomcommunity.nl · webwinkelvakdagen.nl
- Events IE: irish-presidency.consilium.europa.eu (SME & Clusters Assembly) · ibec.ie/sfa (SFA Annual Lunch 2026) · dentist.ie/events · ilovelimerick.ie (Limerick Chamber awards) · goodfoodireland.ie · dublinchamber.ie/events · mayo.ie (Local Enterprise Showcase 2027) · catexexhibition.com · milkbottlelabs.com/pages/shopify-meetup-ireland · meetup.com/irishsmallbusiness
- Grants IE: localenterprise.ie Trading Online Voucher (closed 13.12.2024) and Grow Digital Voucher pages
- Agencies: shopify.com/partners/directory (NL and IE filters), sortlist.nl / sortlist.com category pages, goodfirms.co Ireland pages, bestinireland.com, and each agency's own site (checked live)
