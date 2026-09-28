---
name: otto-autopilot
description: "Otto's orchestration playbook — the fully automatic marketing loop. Defines what runs when (onboarding, daily, weekly, monthly), which script or skill does each step, what the owner decides vs what Otto does alone, and the Telegram card + callback protocol. Use when running Otto for any brand, when a cron fires, or when asked 'what does Otto do next'."
---

# Otto Autopilot — the loop

**Thesis:** the owner gives a URL and answers ≤4 questions once. From then on Otto plans, writes,
designs, publishes, watches, researches competitors and proposes the next move. The owner only
taps ✅ / ❌ in Telegram. Nothing else is asked of them, ever.

**Engine (platform/):** `otto_scan.py` → `otto_plan.py` → *copy + visuals (skills)* → Telegram cards →
`ap.py decide` → `otto_publish.py` → `otto_insights.py` → `otto_competitors.py` → back to the plan.
State lives in `data.json` (writes only through `ap.py`), files per brand in `brands/<slug>/`.

## 0. Onboarding (once per brand, target < 1 hour, owner touches it twice)
1. `ap.py brand-add <slug> "<Name>" <url> <LANG> "<pillars, comma-separated>"` (pillars can be refined after step 3).
2. `otto_scan.py <url> --slug <slug>` → `scan.json` + `brand-profile.md` draft (AUTO sections filled: identity, palette, logo, fonts, socials, prices, trust, quotes).
3. Run **otto-creative-engine** Step 2 on the draft: fill the inference sections (avatars, pains, triggers, objections, angles, positioning, pillars). Mark unverified items `(?)`.
4. **Owner touch #1 — gap questions (≤4)** in one Telegram message: only what the scan could not answer (hidden price, best past angle, top objection, offline proof/reviews). Their answers overwrite `(?)`. Profile locked.
5. `otto_competitors.py add <slug> <name> <site>` ×5-8 (or let `sweep` seed from the profile) → `otto_competitors.py sweep <slug>` → agent completes the ad-library part (otto-competitor-research) → 3-5 briefs.
6. `otto_plan.py build <slug> <YYYY-MM>` → month of draft slots (pillar rotation, platform, format, best hours).
7. **Quill (otto-copy-engine):** write hook + caption per slot from the profile + competitor briefs → `copy.json` → `otto_plan.py fill <slug> <month> copy.json`.
8. Visuals for the first week: `genvisuals.py` (Leonardo GPT Image 2, brand palette + logo rule) → `ap.py set <id> '{"image":"assets/posts/<id>.png"}'`.
9. `ap.py set <id> '{"status":"pending_approval"}'` for week 1 → Telegram cards (format below).
10. **Owner touch #2 — connect channels:** Meta OAuth (Page + IG) → `otto-secrets/meta-<slug>.json`; Telegram already paired. Until credentials exist the publisher waits and says so.

## 1. Daily (every day, no owner action unless a card arrives)
| when (IL) | what | how |
|---|---|---|
| 07:30 | Morning briefing (waiting / publishing today / reach / blockers) | `otto_watch.py report` (cron) |
| 08:00 | Send today's approval cards (posts due within 72 h, status pending_approval) | agent: one Telegram card per post |
| every 15 min | Publish approved posts whose slot arrived | `otto_publish.py` (cron) |
| hourly :15 | Guard: metric drops ≥30 %, missed slots, approvals about to miss their slot | `otto_watch.py watch` (cron) |
| on callback | Owner decision → state + taste log | `ap.py decide <id> approve|skip|later --via telegram` |
| on "edit" reply | Rewrite with the owner's instruction, resend the card | Quill (copy engine) → `ap.py set` |
| 18:00 | Keep the deck full: next 7 days must have visuals + captions; generate what's missing | agent + `genvisuals.py` |

Rules: never publish without `approved`. A `later` keeps the post pending and re-sends the card next morning.
If a slot is < 6 h away and still pending, `otto_watch` pings once; if it passes, `otto_publish` marks it
`failed` (missed) and files a P0 — Otto does not publish at random hours.

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

## 4. What Otto decides alone vs asks
**Alone:** slots and times, pillar rotation, formats, hashtags, visual generation, rescheduling around a missed slot, competitor monitoring, analytics, plan refills.
**Asks (one tap):** every post before it publishes (until the owner enables auto-publish per pillar), any recommendation (P0 blockers, channel additions, plan tweaks), any ad budget (Atlas, when live).
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
Handler: `ap.py decide <post-id> <approve|skip|later> --via telegram`; `edit` = reply-to flow (owner types the change,
Quill rewrites, card is re-sent with the same id). Recommendation cards: `otto:rec:<rec-id>:approve|dismiss` → `ap.py rec`.
The same card is visible in Mission Control; whichever surface decides first wins (`approved_via`).

## 6. Crons (server, UTC — see platform/crons.md)
`otto_watch.py report` 04:30 · `otto_watch.py watch` hourly :15 · `otto_publish.py` */15 ·
`otto_competitors.py sweep <brand>` Mon 03:00 · `otto_insights.py` Fri 03:00 · monthly plan 25th 03:00.

## 7. Files Otto maintains per brand
`brand-profile.md` (locked source of truth) · `scan.json` · `competitors.json` + `competitors/*.json` snapshots ·
`competitor-research.md` (dated sweeps) · `content-plan-YYYY-MM.md` · `winning-posts.md` · `assets/` (logo, posts).
