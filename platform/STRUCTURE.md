# Autopilot Platform — Product Structure (IA / Sitemap)

Date: 2026-09-24 · Owner: Maximus · Status: approved-for-mockups
Inputs: `ARCHITECTURE.md`, `index.html` (Mission Control v2), `data.json` (schema v1),
`research/native-system-audit-2026-09-24.md` (Native benchmark, 7-tab map, Trustpilot 2.8).

---

## 0. Product thesis (what the customer pays for)

Native's pitch: "marketing on autopilot" from a dashboard, $79–499/mo, dashboard-only approvals,
bot-first support (Trustpilot 2.8, 60% one-star — nearly all support complaints), no AI video.

**Our pitch: a proactive AI marketing agency that lives where you already live.**
The dashboard is Mission Control — the *picture*. The *action* happens in Telegram/WhatsApp.
Four durable edges, each a first-class surface below:

| Edge | Surface | Native status (updated 24/09 PM — `research/native-delta-2026-09-24-pm.md`) |
|---|---|---|
| **AI-generated video** (Reels/TikTok/Stories) | Studio → Video queue, proposed inside the weekly plan | Publishes video, generates none — still our cleanest edge |
| **Messenger-native approvals** ⚠️ URGENT | Approve deck mirrored 1:1 to Telegram inline buttons | **Window closing:** WhatsApp inbox LIVE; Telegram/Discord/Slack publishing "coming soon" on their public roadmap. Approvals-in-chat still unique — ship Phase A first |
| **Ad CREATIVE, not just ad plumbing** | Ads → generated variants + AI video ads (fire_ads pipeline) | **Ads Autopilot now LIVE** (FB+IG, daily budget, own ad account). They reuse organic posts as ads; they don't generate dedicated ad creative or video. Edge restated: creative + mid-tier price, not the autopilot itself |
| **Concierge support** (human, <2h SLA) | Persistent "Talk to a human" affordance + onboarding call | Bot-first, batch replies, 7 people, not hiring |
| **Hebrew market** | Full RTL content pipeline, HE fingerprints, local compliance (Meta restricted categories) | English/Nordic focus; no HE/RTL |

Anchor pricing against their $499 Agency tier: **we ship ads-on-autopilot + AI video in the mid tier**
(their ads copy hints it may trickle below Agency — assume the price umbrella shrinks; video + Hebrew + chat-approvals are the durable moats).
Ladder (rec-004): Starter €69 / Growth €149 / Agency €399 monthly, annual with a working discount flow.
The value line on the pricing page writes itself: *"Everything Native gates at $499 — plus AI video and a human on the phone — at €149."*

**Paradigm rule (from ARCHITECTURE.md, unchanged):** the agency speaks first person, composes the plan
and the recommendations; the owner only decides. Every screen leads with "what we recommend",
never with an empty toolbox.

---

## 1. Navigation model

### 1.1 Two-surface model (the twist)
Every decision object (post approval, ad budget, lead confirmation, reply draft) exists **twice**:
1. **Telegram** — inline-button card, one tap, where the owner lives. Primary action surface.
2. **Mission Control** — the same object in richer context (previews, history, analytics). Secondary.

State is one: `data.json` (v2 below). `approved_via` records which surface decided.
Rule: *nothing is decidable only in the dashboard.* If it can't be a Telegram card, it isn't a v1 feature.

### 1.2 App shell
Top app bar (exists in `index.html`): mark + wordmark, tab nav, ⌘K search, live badge, account avatar.

**Tabs (7 + settings), in order:**

| Tab | Route | One-liner |
|---|---|---|
| Overview | `/` (`index.html`, exists) | Mission Control: briefing, decision deck, fleet, pipeline |
| Approve | `/approve` | Swipe-deck of everything awaiting a decision |
| Planner | `/planner` | Calendar of the month — posts, videos, ads, campaigns |
| Studio | `/studio` | Chat-first create + AI video queue |
| Inbox | `/inbox` | Comments/DMs/reviews, AI-drafted replies |
| Ads | `/ads` | Ads-on-autopilot: ceiling, winners loop, campaign list |
| Analytics | `/analytics` | Revenue-first: new customers, est. revenue, lead confirm |
| — | `/brand/<id>` | Brand memory board (reached from Overview/brand chips, not a top tab) |
| — | `/settings` | Connections, billing, team, support SLA (avatar menu) |

Mobile (<960px): tabs collapse to a bottom bar of 5 (Overview · Approve · Inbox · Analytics · More).
⌘K search spans posts, recommendations, leads, brand assets.

**Global affordances on every screen:**
- "Talk to a human" pill (concierge edge — deliberately always visible; Native buries support)
- Brand switcher (multi-brand accounts; per-brand data never mixes — isolation rule from ARCHITECTURE.md)
- Live/snapshot badge (exists)

---

## 2. Sitemap — every page, purpose, components

### 2.1 Overview — `/` (exists, stays as built)
**Purpose:** the agency's daily briefing; the one screen that proves "your marketing is handled".
**Components (already live):** briefing hero + voice line, KPI row, flow strip, decision deck
(P0 blockers + collapsible strategic), agent fleet with ticker, content pipeline by brand,
connections rail, performance rail.
**Changes when other pages ship:** deck CTAs deep-link (`Review queue` → `/approve`,
`Connect assets` → `/settings#connections`, video/ads recs → `/studio`, `/ads`);
performance rail becomes a teaser of `/analytics` (revenue number, not reach).

### 2.2 Approve — `/approve` ⭐ (mockup: `approve.html`)
**Purpose:** Native's core UX (their tab #2), rebuilt with our wedge: one card at a time,
real platform preview, and the identical card simultaneously in Telegram.
**Layout:** centered card stack + right rail.
**Components:**
- **Deck card:** platform-true preview (IG/FB/LI frame, brand avatar, media, caption `dir=auto`,
  hashtags), pillar + slot chip, "why this post" line from the agency (which pillar/trend it serves),
  agent attribution (Quill drafted · Sage slotted).
- **Decision bar:** ❌ Skip · ✍️ Edit (opens Studio chat with the post loaded) · ✅ Approve.
  Keyboard: ←/→/E. Every decision appends to the brand fingerprint (`fingerprint.taste_log`).
- **Queue meter:** "4 of 9 · queue never runs dry" — the plan refills from pillars.
- **Telegram mirror strip:** "This same card is on your phone" + live status
  (`approved_via: telegram|dashboard`). If approved in Telegram while the deck is open, the card
  flies away with a "decided in Telegram" toast — the moment that demos the two-surface model.
- **Right rail:** Taste profile (top approved angles, declined angles — the learning made visible),
  recent decisions list, batch actions ("approve all P2 engagement posts").
**Scope note:** the deck holds *all* decision types — posts first; ad-budget bumps and lead
confirmations enter the same deck later (one inbox for decisions).

### 2.3 Planner — `/planner`
**Purpose:** "your month is handled" — the pipeline list doesn't say that; a calendar does.
**Components:** week/month toggle; one card per post across channels (platform chips on the card);
video posts get a ▶ badge; campaign/launch bands as calendar objects; drag-drop reschedule
(writes via `ap.py`); best-time auto-slot suggestions (Sage); status color = pill colors from
`index.html`; brand filter; empty-slot "+" opens Studio.
**States:** empty week → agency proposes a fill ("Let Sage slot week 2").

### 2.4 Studio — `/studio`
**Purpose:** chat-first creation (we're chat-native by construction — OpenClaw) + the AI-video edge.
**Components:**
- **Chat composer:** describe → caption + image + live per-platform preview; refine by chat;
  per-channel caption counter with auto-shorten; bring-your-own media.
- **Video queue (edge #1):** `video_generate` + Leonardo pipeline → branded vertical clips
  (Reels/TikTok/Stories). Each clip: storyboard strip, voiceover language (HE/EN/DE), status
  (rendering → preview → in approval deck). Marketing line on the page: *"Native can't make this."*
- **Asset drawer:** brand palette/fonts/logos pulled from the fingerprint; product catalog items.
**Not building (deliberate cut, from audit):** layered Designer canvas — heavy, low differentiation.

### 2.5 Inbox — `/inbox`
**Purpose:** retention surface — "handles the replies" (Native's Inbox is a major stickiness feature).
**v1 scope:** Meta comments + DMs only.
**Components:** thread list with mailbox tabs (Comments · DMs · Reviews *(soon)* · WhatsApp *(soon)*);
thread view with the source post inline; **AI-drafted reply in brand voice** with Approve / Edit / Skip
(same decision bar as `/approve`); sentiment + intent chips (lead! / complaint / spam); spam flag;
per-brand view. **Telegram mirror:** reply drafts route to the owner's Telegram for one-tap approve —
our differentiator vs Native's dashboard-only inbox.
**Lead handoff:** any thread marked "lead" creates a lead object → appears in `/analytics` confirm loop.

### 2.6 Ads — `/ads`
**Purpose:** match Native's Aug–Sep ads suite, undercut the $499 gate (we ship it in Growth tier).
**Components:**
- **Autopilot panel (hero):** master switch + **daily spend ceiling slider** (the one number the
  owner controls); status line: "Best organic posts become ads automatically, within €X/day."
- **Winners loop card:** last batch's winning angle → "teaching the next batch" (Native's Sep 3
  feature, ours via fire_ads + weekly pass).
- **Campaign list:** campaign → ad set → ad tree; pause/resume; per-audience vs campaign budget;
  Meta-block explainer banner with one-click fix (copy their Aug 13 pattern).
- **Creative rack:** generated variants (multiple headlines/primary texts — Meta picks).
- **Compliance guard:** restricted-category brands (CBD, mental-health) get organic-first badges
  and blocked-action explanations — Hebrew-market edge, encoded in `brands[].compliance`.
**Approvals:** budget changes above the ceiling and new campaigns go through the Approve deck/Telegram.

### 2.7 Analytics — `/analytics` ⭐ (mockup: `analytics.html`)
**Purpose:** reframe from posts to money — "real growth, not vanity metrics" (copy the framing,
beat it with the messenger confirm loop).
**Components:**
- **Money header:** new customers · estimated revenue · leads waiting confirmation (per brand + total).
- **Before/after chart:** reach & leads over time with a marked **"day Autopilot started"** vertical —
  Native's conversion weapon ("something you can see rather than something we claim"); ours from day 1.
- **Lead confirmation loop:** cards per lead — "Became a customer / Didn't" — one tap here *and* in
  Telegram; confirmed × avg deal size = estimated revenue (assumption editable per brand).
- **Performers shelf:** top posts/ads with why-it-worked line (feeds the winners loop).
- **Attention share vs competitors** (stolen from Velocity, nobody else in category has it):
  per interest topic, our share of engagement vs 2–3 named competitors, daily delta
  ("טיפול בחרדה 61% ▲3.1%"). Data source v1: competitor page scrape weekly; v2: APIs.
- **Per-post ticket:** every scheduled post gets a page: countdown → results (their pattern, cheap).
- **Agency reads it for you:** Echo's weekly conclusion sentence on top — the owner sees conclusions,
  not dashboards (paradigm rule).

### 2.8 Brand memory board — `/brand/<id>`
**Purpose:** the fingerprint made visible and correctable — "the system knows you" (churn killer).
**Components:** archetype card; tone-of-voice editable line-by-line; palette as swatches; moodboard
style refs with on/off toggles; pillars (many, editable); product catalog; compliance notes;
**taste log** (what approvals/declines taught it — pulls from `/approve` decisions);
**rules card** that validates a live sample post in front of the owner.
**Our advantage:** interview-based onboarding yields a richer fingerprint than Native's URL scrape —
this page is where that richness becomes *visible product value*.

### 2.9 Onboarding — `/start` ⭐ (mockup: `onboarding.html`, out-of-app wizard)
**Purpose:** the instant-wow path (theirs: "before your coffee gets cold") + our depth + concierge.
Five steps, progress bar, every step skippable-forward:
1. **URL** — site scrape → instant draft fingerprint (match their speed).
2. **Interview** — 5 conversational questions (chat UI, voice-note friendly) → fingerprint deepens
   live on the right (visibly better than a scrape — the differentiation moment).
3. **Fingerprint review** — archetype, tone, palette, pillars; owner corrects inline.
4. **Connect channels** — IG/FB (Meta OAuth), LinkedIn, **Telegram pairing** (QR/deep-link) —
   framed as "where you'll approve everything"; connection status cards; skip = snapshot mode.
5. **First plan** — 7 days of posts + 1 AI video slotted; CTA: "Review your first week" → `/approve`.
   Concierge card: "Prefer a human? Book your 15-min onboarding call" (edge #3, on the happy path).

### 2.10 Settings — `/settings`
Connections (moves in from Overview rail as the full manager: OAuth states, token health, reconnect);
Billing (plan ladder, monthly↔annual self-serve switch — copy Native's ladder, not their promo fumble:
discounts must apply to added brands and be honored by support); Team/roles; Notification routing
(which decision types ping Telegram vs digest); Support SLA page ("<2h human response" printed —
a *marketed* feature); Data & privacy.

### 2.11 Marketing site trust & distribution pages (not app)
Native's playbook is now fully visible (delta doc §3) — copy the shape, localize the content:
- **`/changelog`** — weekly dated cards, plain language, one improvement each. Source: we already
  log every deploy in memory files; an hour a week.
- **`/roadmap`** — public, like theirs ("Telegram approvals — live", "Google Ads — building").
  Honesty asset that doubles as a feature-announce surface.
- **`/compare` hub** — "fair on both sides" comparisons: vs Native (head-on, they won't dare),
  vs a social media manager, vs an agency, vs schedulers. Each ends in the instant-demo CTA.
- **Free tools for SEO/leadgen** — Hebrew-first: מחשבון עלות שיווק (cost calculator),
  לוח תוכן 30 יום, platform selector. They rank with these in EN; HE is empty space.
- **Pricing page notes:** annual = 20% off (match), "unlimited seats" line (steal from Velocity —
  costs us nothing, reads generous), Enterprise/custom row.

---

## 3. User flows (end-to-end)

### F1. Onboarding → first approved week (target: <20 min)
`/start` URL → interview → fingerprint review → connect (Meta OAuth + Telegram pairing) →
first plan generated → `/approve` deck (or straight from Telegram) → ≥1 post approved →
Overview shows "publishing Sat 08:00". Drop-off guards: skip-forward everywhere; no channels
connected = snapshot mode with sample plan; concierge call offered at step 5, not as failure mode.

### F2. Daily decision loop (the habit loop, 2 min/day)
06:00 agency compiles briefing → Telegram morning card ("3 decisions today") → owner taps through
approval cards in Telegram (or opens `/approve`) → decisions write `approved_via` → scheduler
publishes → evening one-line result ping. Dashboard visit optional *by design* — that's the retention
trick Native can't copy without abandoning their dashboard-first model.

### F3. Content approval (swipe deck detail)
Queue = `posts[status=pending_approval]` ordered by slot proximity → card shows platform-true
preview → Approve = status→approved + taste_log(+angle) · Skip = skipped + taste_log(−angle) →
Edit = Studio chat session, returns to deck → queue refills from pillars when < 3 remain.

### F4. Ads-on-autopilot
Owner sets ceiling once (`/ads` or Telegram) → weekly pass: Echo ranks organic winners → Atlas builds
ad + variants (fire_ads) → **ad card enters the same approval deck** (creative + audience + budget) →
approved ads run within ceiling → results feed winners loop → budget-raise suggestions arrive as
P1 recommendations, never silent spend. Compliance guard blocks restricted brands with an explanation.

### F5. Unified inbox reply
New comment/DM → intent classified → lead? → lead object → reply drafted in brand voice →
Telegram card (context + draft, Approve/Edit/Skip) → approved reply posts → thread archives;
confirmed leads flow to F6.

### F6. Revenue analytics loop
Published content + ads → clicks/leads land → lead confirmation cards (Telegram + `/analytics`):
"Became a customer / Didn't" → est. revenue accrues → before/after chart updates →
Echo's weekly conclusion → next recommendations (close the loop back to the Overview deck).

---

## 4. data.json schema v2 (additions; writes via `ap.py` only)

- `posts[]`: + `media[]`, `format` (post|carousel|reel|story|video), `preview_url`,
  `decided_at`, `angle` (feeds taste log)
- `videos[]` *(or posts.format=video)*: storyboard, render_status, voiceover_lang
- `fingerprint.<brand>`: archetype, tone_lines[], palette[], moodboard[], pillars[],
  products[], rules[], `taste_log[]` (decision, angle, ts, via)
- `ads`: `autopilot{enabled, daily_ceiling, currency}`, `campaigns[]` (→ad_sets[]→ads[]),
  `winners[]` (angle, evidence, taught_batch)
- `inbox[]`: thread{platform, kind(comment|dm|review), post_ref, messages[], intent, draft_reply, status}
- `leads[]`: source_ref, brand, status(waiting|customer|not), value_estimate, confirmed_via
- `metrics`: + `revenue_estimate`, `new_customers`, `autopilot_start_date` (chart marker)
- `connections[]`: + `token_health`, `last_sync`
- `billing`: plan, cycle, brands_included

New `ap.py` verbs: `lead-add/lead-confirm`, `inbox-add/reply-set`, `ads-ceiling`, `video-status`,
`taste-log` — same pattern as existing add/status/rec verbs.

---

## 5. Build order (maps to audit's top-10)

**Urgency note (24/09 PM):** Native's public roadmap lists Telegram publishing "coming soon" and
their WhatsApp inbox is live. Phase A's Telegram approval mirror is the one thing they can't ship
without abandoning dashboard-first — it must be demo-able before they get there.

| Phase | Ships | Audit ref |
|---|---|---|
| A (now) | `/approve` deck + Telegram mirror; `/start` onboarding incl. connect | #1, closes ARCHITECTURE checklist item 4 |
| B | `/analytics` revenue loop + lead confirm; concierge SLA on landing | #4, #7 |
| C | `/ads` autopilot v1 + winners loop; recurring pricing | #2, #10 |
| D | `/studio` video queue; `/planner` calendar | #3, #5 |
| E | `/inbox` comments v1; `/brand` memory board; `/changelog` | #9, #6, #8 |

Agent separation (ARCHITECTURE.md plan) unchanged: everything under `maximus` until the loop is
proven end-to-end, then `autopilot-core` + per-client agents via the provisioner.

---

## 6. Mockups in this directory

| File | Page | Preview |
|---|---|---|
| `approve.html` | §2.2 Approve deck | `preview-approve.png` |
| `analytics.html` | §2.7 Revenue analytics | `preview-analytics.png` |
| `onboarding.html` | §2.9 Onboarding (step 4: connect channels) | `preview-onboarding.png` |

Shared foundation extracted to `assets/platform.css` (tokens, app bar, cards, pills — lifted from
`index.html`, which itself is untouched). Agent avatars reused from `assets/agents/`.
