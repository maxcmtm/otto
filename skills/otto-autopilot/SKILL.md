---
name: otto-autopilot
description: "Otto's orchestration playbook — the fully automatic marketing loop. Defines what runs when (onboarding, daily, weekly, monthly), which script or skill does each step, what the owner decides vs what Otto does alone, and the Telegram card + callback protocol. Use when running Otto for any brand, when a cron fires, or when asked 'what does Otto do next'."
---

# Otto Autopilot — the loop

**Thesis:** the owner gives a URL and answers ≤4 questions once. From then on Otto plans, writes,
designs, publishes, watches, researches competitors and proposes the next move. The owner only
taps ✅ / ❌ in Telegram. Nothing else is asked of them, ever.

**Engine (platform/):** `otto_scan.py` → `otto_plan.py` → *copy (Quill, skill)* → `genvisuals.py` → `otto_telegram.py send-cards` →
`otto_telegram.py poll` (buttons → `ap.decide`) → `otto_publish.py` → `otto_insights.py` → `otto_competitors.py` → back to the plan.
State lives in `data.json` (writes only through `ap.transaction()` — lock + atomic write; network work happens outside the
lock), files per brand in `brands/<slug>/`. Generated media is copied to the public assets dir (`/srv/pulse/otto/assets`)
as soon as it is written; nothing that is not public is ever handed to Meta.

## 0. Onboarding (once per brand, target < 1 hour, owner touches it twice)
1. `ap.py brand-add <slug> "<Name>" <url> <LANG> "<pillars, comma-separated>"` (pillars can be refined after step 3).
2. `otto_scan.py <url> --slug <slug>` → `scan.json` + `brand-profile.md` draft (AUTO sections filled: identity, palette, logo, fonts, socials, prices, trust, quotes).
3. Run **otto-creative-engine** Step 2 on the draft: fill the inference sections (avatars, pains, triggers, objections, angles, positioning, pillars). Mark unverified items `(?)`.
4. **Owner touch #1 — gap questions (≤4)** in one Telegram message: only what the scan could not answer (hidden price, best past angle, top objection, offline proof/reviews). Their answers overwrite `(?)`. Profile locked.
5. `otto_competitors.py add <slug> <name> <site>` ×5-8 (or let `sweep` seed from the profile) → `otto_competitors.py sweep <slug>` → agent completes the ad-library part (otto-competitor-research) → 3-5 briefs.
6. `otto_plan.py build <slug> <YYYY-MM>` → month of draft slots (pillar rotation, platform, format, best hours).
7. **Quill (otto-copy-engine):** write hook + caption per slot from the profile + competitor briefs → `copy.json` → `otto_plan.py fill <slug> <month> copy.json`.
8. Visuals for the first week: `genvisuals.py --brand <slug> --limit 12` (reads every post without an image, prompt from the profile's palette/style + the post's brief; writes `image` back itself).
9. `otto_plan.py fill … --pending` (or `ap.py set <id> '{"status":"pending_approval"}'`) for week 1 → `otto_telegram.py send-cards` (format below).
10. **Owner touch #2 — connect channels:** Meta OAuth (Page + IG) → `otto-secrets/meta-<slug>.json`; Telegram already paired. Until credentials exist the publisher waits and says so.

### 0b. Free-trial kickoff (self-serve sign-ups — highest priority work of the day)
A Google sign-up that onboards gets a 7-day trial (otto_trial) and its weeks are planned on the spot
(`otto_trial.kickoff`: every month the trial overlaps, future slots only). The brand then carries
`kickoff.copy_needed: true` and an owner card "New trial: write the first week for <Name>". Before anything else that day:
1. Steps 3 (profile inference) and 7 (Quill) for the posts in the **next 7 days** first, then the rest of the month.
2. Step 8 visuals for those 7 days (`genvisuals.py --brand <slug> --limit 12`), step 9 to put them in front of the client
   (their approvals channel: e-mail by default).
3. `otto_trial.py copy-done <slug>` → clears the flag; resolve the owner card.
The trial plan previews paid ads (matrix planned and rendered) but never launches them; don't promise a live campaign
before a card is on file. A trial that ends unpaid pauses itself (no action needed); its data is kept 90 days.

## 1. Daily (every day, no owner action unless a card arrives)
| when (IL) | what | how |
|---|---|---|
| 07:30 | Morning briefing (waiting / publishing today / reach / blockers) | `otto_watch.py report` (cron) |
| 08:00 | Send today's approval cards (posts due within 72 h, status pending_approval) | `otto_telegram.py send-cards` (cron) — photo + caption + buttons |
| always | Button taps → state + taste log; ✏️ Edit → owner's reply stored in `edit_requests[]` | `otto_telegram.py poll` (systemd service, long-polling) |
| hourly | Rewrite every `edit_requests[]` item in the owner's words, `ap.py set` the new copy (status back to `pending_approval`), `send-cards --ids <post>` | Quill (skill) |
| every 15 min | Publish approved posts whose slot arrived | `otto_publish.py` (cron) |
| hourly :15 | Guard: metric drops ≥30 %, missed slots, approvals about to miss their slot | `otto_watch.py watch` (cron) |
| on callback | Owner decision → state + taste log (handled by the poller; `ap.py decide … --via telegram` is the manual equivalent) | `otto_telegram.py poll` |
| on "edit" reply | Rewrite with the owner's instruction, resend the card | Quill (copy engine) → `ap.py set` |
| 18:00 | Keep the deck full: next 7 days must have captions + visuals; generate what's missing | Quill for copy · `genvisuals.py --brand <slug>` for images (cron) · `otto_telegram.py send-recs` for new recommendations |

Rules: never publish without `approved`. A `later` keeps the post pending and re-sends the card next morning.
If a slot is < 6 h away and still pending, `otto_watch` pings once; if it passes, `otto_publish` marks it
`failed` (missed) and files a P0 — Otto does not publish at random hours. Slots are brand-local (`brands[].tz`, default Asia/Jerusalem).
No double posts: the publisher sets `publishing` before the call that makes a post public. A clear Meta error puts it back
to `approved` (3 tries → `failed` + P0); an unconfirmed call leaves it in `publishing` — **never retried automatically**,
the owner gets a "check if it went out" P0. Dashboard/Telegram cannot move `published`/`publishing`/`failed` back to `approved`.
LinkedIn posts are not published yet (marked failed with a "post by hand" card, never sent to Instagram).
Compliance: every card is checked against `brands/<slug>/compliance.json` (banned phrases, required disclaimer) before
it is sent; a violating card is held and filed as a "Compliance hold" recommendation for Quill to rewrite.

## 2. Weekly
| day | what | how |
|---|---|---|
| Mon 06:00 | Competitor sweep: site deltas, live promos, ad-library checklist → recommendation if anything moved | `otto_competitors.py sweep <slug>` then agent completes longevity winners in `competitor-research.md` |
| Mon | Trend + angle briefs from the sweep (Nova) → 3-5 briefs into next week's slots | agent |
| Fri 06:00 | Insights: pull reach/saves/clicks per post, rank winners, file "double down on <pillar>" | `otto_insights.py` |
| Fri | Next week's copy + visuals generated iterating on the winners (`winning-posts.md` read first) | Quill + genvisuals |
| Sun 08:00 | Weekly card to the owner: what published, what won, what's proposed (one message, one tap) | agent, from `ap.py taste` + winners + recs |

## 3. Monthly (25th)
1. `otto_plan.py build <slug> <next-month>` (pillar weights nudged by taste log + winners: more of what got ✓, less of what got ✗).
2. Copy for week 1 of next month filled and visualised before the 1st.
3. Profile refresh: rerun `otto_scan.py` — new products/prices/promos on the owner's site update the profile appendix.

## 3b. Paid (Meta + Google) — same rails, `otto_ads.py`
| when | what | how |
|---|---|---|
| 07:35 daily | Paid report: spend, results, CPL, CTR yesterday + 7d per network, best/worst campaign, one suggested action (as a card) | `otto_ads.py report` (cron) → `ads[brand].daily` + Telegram |
| 06:00 daily | Launch approved flights whose start date is today (Meta: campaign → ad set → creative → ad, each id saved as it is created so a failed run resumes; Google: Search campaign via one mutate). Compliance check first — violations go on hold + a card | `otto_ads.py launch` (cron) |
| 06:05 daily | Guard: ended flights paused; CPL 3 days above target → "Pause X?" card (auto-pause only if `ads[brand].auto_pause`) | `otto_ads.py guard` (cron) |
| 25th monthly | Paid Gantt for next month: evergreen leads/traffic all month, two 5-day boosts of the best organic posts, Google Search on brand + category (skipped for restricted categories; Meta flights on compliance hold) | `otto_ads.py plan <brand> <month>` → drafts + the month's ad matrix skeleton (`ads-<month>.json`, Quill fills it) + ONE recommendation "Approve the paid plan ≈€X" (names the matrix size) |
| on approval | ✅ on the "Approve the <month> paid plan" card runs `otto_ads.approve(<brand>, <month>)` in the Telegram poller; ✅ on a "Pause …" card pauses exactly the campaign stored on it. Nothing spends before this | automatic (poller) · `otto_ads.py approve` by hand |
Credentials: `meta-<brand>.json` gains `ad_account_id`, `pixel_id`, `lead_form_id`; `google-<brand>.json` = OAuth client + refresh token + customer id.
How flights are built: leads + `lead_form_id` → instant-form ads (one ad per static, CTA carries the form); leads without a form →
website leads on the pixel (`LEAD`), or traffic when there is no pixel — never a lead objective without a form. Boosts only run
on a post that is already live on Facebook (`object_story_id`), else the boost is `skipped`. Budgets are in the ad account's
currency (a plan in another currency is refused). `brands[].special_ad_categories`, `.countries`, `.landing` (cold/warm/hot),
`.keywords` (`{"brand","generic"}` — Google never uses site nav/headings; brand and generic run as separate ad groups) and
`.currency` drive the plan. Restricted categories (CBD, therapy / mental health, employment, housing, credit, gambling, crypto,
pharma, supplements…) are planned on compliance hold; `otto_ads.py release <id>` after review, `otto_ads.py retry <id>` after a failure.
Reporting counts Meta results per objective (leads / purchases / engagements) and link clicks separately; Google conversions
are never added into the Meta number without a label.

## 3a. Formats, reels and ad creatives — agency-grade, competitor-informed
- **Format mix** (`otto_plan.py`): carousels / statics / reels per brand from `brands[].format_mix`, else the industry default blended
  with what competitors actually post (`otto_competitors.py formats <brand> <name> post=3,carousel=5,reel=8` after the IG grid browse).
  At least four explainer reels a month in every package. Stories Mon/Wed/Fri.
- **Carousels with copy** (`genvisuals.py`): 3–5 slides, hook on slide one, points on the rest, text rendered by ffmpeg in the brand band
  (Quill may pre-write `post.slides`).
- **Reels 30–60 s** (`otto_video.py`): `plan <post>` (or Quill writes `post.script`: 4–7 scenes) → `render <post>`: one vertical image per
  scene, Ken Burns, captions in the brand band, voice-over (ElevenLabs, `otto-secrets/elevenlabs.json`) and a music bed
  (`assets/music/*.mp3`). Publisher posts it as an IG reel / FB video.
- **Ad creatives: the angle × style matrix** (`otto_styles.py`, `otto_creative.py matrix`): every month's Meta evergreen runs
  6 angles (pain, identity, enemy, experience, offer, moment) × 6 styles (real-creator UGC video, faceless video, product,
  comparison, native screenshot, proof / humor; + a price card on the offer angle), ≥50 % video, 1-2 headlines per angle —
  the Grüns standard (`research/GRUNS-AD-LIBRARY-2026-09.md`); 4 × 5 under ~€36/day. From `brands/<slug>/ads-<YYYY-MM>.json`.
  `otto_ads.py plan` writes the skeleton; Quill fills it (otto-creative-engine, "Ad matrix"); `matrix --check` must pass. `otto_ads.py launch` builds one CBO campaign with **one ad set per angle**, each
  style its own ad. Until the matrix has ready cells the old path runs: angle bank (`angles.json` → profile winning angles
  → best hooks) × (static + 3-card carousel + reel) in ONE ad set with Meta dynamic creative. `otto_ads.py report` surfaces
  best/worst. Statics/cards are JPEG, text via ffmpeg drawtext (RTL right-aligned,
  shaped when ffmpeg supports it). Angles from the profile are only quoted hooks or clean angle labels — lines with CPL, ₪/€,
  lead counts, arrows or "(?)" never become copy — and the CTA card speaks the brand language.
- Visuals: the brand guide wins — the profile's VISUAL IDENTITY `Style:` line, else `brands/<slug>/*brand-guide*.md`; the generic
  industry style (and forced photorealism) only when neither exists.
- The Monday ad-library browse (otto-competitor-research) is what makes this agency-grade: record longevity winners, hooks and formats
  in `competitor-research.md` and `competitors.json`; the scripts turn them into next month's mix and next week's angles.

## 3c. Growth ledger — `otto_growth.py`
Daily 05:10 `otto_growth.py rollup` recomputes `growth[brand]` (this month vs last: reach, engagement, posts, followers, spend,
Meta results and Google conversions (kept apart, labelled), cost per result, best pillar, 90-day daily series; money in the brand
currency). Owner decisions are stored but are not a growth KPI. Mission Control shows it as the Growth section. On the 1st,
`rollup --send` sends "📈 <last month> in review" to the owner — once per month. The 25th plan reads it: more of the best pillar, boosts on the winners.

## 4. What Otto decides alone vs asks
**Alone:** slots and times, pillar rotation, formats, hashtags, visual generation, rescheduling around a missed slot, competitor monitoring, analytics, plan refills.
**Asks (one tap):** every post before it publishes (until the owner enables auto-publish per pillar), any recommendation (P0 blockers, channel additions, plan tweaks), the monthly paid plan and any pause/budget move (Atlas).
**Never:** invent claims, publish restricted-category content as paid, spend money silently, message the owner more than the briefing + cards + real alerts.

## 5. Telegram card protocol
Card = photo (the visual) + caption:
```
<Brand> · <Platform> · <Slot as "Sat 18:00">  ·  <Pillar>
<caption text, as it will appear>
—
Why this post: <one line from the plan/brief>
```
Inline buttons: `✅ Approve` `✏️ Edit` `❌ Skip` `↷ Later` with callback data `otto:<post-id>:approve|edit|skip|later`.
Handler: `otto_telegram.py poll` (Bot API long-polling; only the owner — `callback_query.from.id` = owner_user_id, default
owner_chat_id — may decide). Approve/skip/later → `ap.decide` + the card is edited in place (buttons removed, outcome appended);
`later` also clears the card id so tomorrow's run sends it again. `edit` → force-reply prompt; only a *reply to that prompt*
within 2 h counts, only for posts still in draft/pending_approval; it is stored in `edit_requests[]` and the post goes back to
draft; Quill rewrites and `send-cards --ids <post>`. Recommendation cards: `otto:rec:<rec-id>:approve|dismiss` — the reply says
"on it" only when approving actually ran something (paid plan approval, campaign pause). Config: `otto-secrets/telegram.json`
{bot_token, owner_chat_id, owner_user_id?}.
The same card is visible in Mission Control; whichever surface decides first wins (`approved_via`).

## 6. Crons (server, UTC — see platform/crons.md)
`otto_watch.py report` 04:30 · `otto_telegram.py send-cards` 05:00 · `otto_telegram.py poll` (service) · `otto_watch.py watch` hourly :15 ·
`otto_publish.py` */15 · `genvisuals.py --brand <b>` 15:00 · `otto_telegram.py send-recs` 15:30 · `otto_competitors.py sweep <brand>` Mon 03:00 ·
`otto_insights.py` Fri 03:00 · `otto_ads.py report` 04:35 · `otto_ads.py launch` 03:00 · `otto_ads.py guard` 03:05 · `otto_growth.py rollup` 02:10 (1st: `--send`) · monthly plans (organic + paid) 25th 03:00.

## 7. Files Otto maintains per brand
`brand-profile.md` (locked source of truth) · `scan.json` · `competitors.json` + `competitors/*.json` snapshots ·
`competitor-research.md` (dated sweeps) · `content-plan-YYYY-MM.md` · `winning-posts.md` · `assets/` (logo, posts).
