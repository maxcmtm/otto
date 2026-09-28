# Native.no parity + edge checklist
Date: 2026-09-28 · Source: native.no public site (read live), STRUCTURE.md audit, research/native-*.md · Owner: Claude Code (local)

Legend: ✅ have · 🟡 partial · ❌ missing · ⭐ our edge (they don't have it)

## Product loop
| Native has | Otto status | Where / next |
|---|---|---|
| Drop URL → research (site, industry, competitors, audience) → content plan | ✅ code | `otto_scan.py` (real scan: identity, palette, logo, fonts, socials, prices, trust, quotes, industry) + creative-engine skill for inference |
| "We generate 50 posts" per month per brand | ✅ code | `otto_plan.py build` (slot grid, pillar rotation, formats, best hours) + Quill fills copy via `fill` + `genvisuals.py` images every post from the profile's palette |
| Swipe approve / skip, per-platform preview | ✅ code | Mission Control deck + **⭐ Telegram cards in code**: `otto_telegram.py send-cards` / `poll` (Bot API, buttons → `ap.decide`, card edited in place, taste log) |
| Refine in plain words ("make it warmer") | 🟡 code | ✏️ Edit button → owner replies → `edit_requests[]` (post back to draft) → Quill rewrites + `send-cards --resend`. Dashboard "Studio" chat not built |
| Auto-publish on schedule (FB, IG, LinkedIn, X + 10 more) | 🟡 code, ❌ live | `otto_publish.py` (FB photo/feed, IG image) — waiting on Meta app + page tokens (M2). Carousel/reel/story publish + LinkedIn: not yet |
| Native Autopilot (plans 2 weeks, publishes with an email before) | ✅ design | otto-autopilot skill + crons: full-auto per pillar is a flag the owner turns on |
| Analytics on what's working | 🟡 code | `otto_insights.py` (reach/saves/clicks per post, winners, "double down" recs) — needs tokens to run live |
| Meta Ads autopilot (organic winners → ads, own ad account) | ✅ code | `otto_ads.py`: monthly paid Gantt (evergreen + boosts of winners + Google Search), launch on Meta (campaign→ad set→creative→ad) and Google (one mutate), daily report, CPL guard. Needs ad-account credentials |
| Daily paid report (Facebook + Google) to the owner | ⭐ code | `otto_ads.py report` 07:35 → Telegram, best/worst campaign, suggested action as a card |
| Month-over-month growth (reach, engagement, followers, spend, results, CPL) | ⭐ code | `otto_growth.py` + Mission Control Growth section + 1st-of-month review |
| Stories / carousels / reels publishing | ✅ code | `otto_publish.py` (IG STORIES / CAROUSEL / REELS, FB photo stories, multi-photo, video); planner adds Mon/Wed/Fri stories |
| Inbox (comments/DMs, WhatsApp) | ❌ | STRUCTURE.md §2.5 — phase E |
| Brand memory / taste layer (binding brand voice) | 🟡 | brand-profile.md (locked) + `taste_log` → Mission Control card "What you've taught Otto"; no full brand page yet |
| Native MCP (control from Claude/ChatGPT) | ❌ | rec-008 — OpenClaw-native, cheap to add later |
| Weekly competitor research | ⭐ code | `otto_competitors.py sweep` (site deltas, live promos, ad-library checklist, summary card in Mission Control) + otto-competitor-research skill. Native shows none. |
| Proactive alerts (drop within the hour) + morning briefing | ⭐ live | `otto_watch.py` (cron) |
| Agency speaks first (recommendations as first-class objects) | ⭐ live | `recommendations[]`, Mission Control deck, engine scripts file recs automatically |
| AI video (reels) | ❌ both | fal.ai/Kling decided (M3) — needs FAL_KEY; Native has zero video generation |
| Hebrew / RTL | ⭐ | cmtm runs in Hebrew; UI English |

## Marketing site
| Native has | Otto status |
|---|---|
| Hero with URL input that generates | ✅ **real** peek (`/otto-peek`) → live brand DNA in the widget, sample fallback |
| Marquee of real client posts | ✅ (2 brands, real visuals) |
| 4 numbered steps with animated widgets | ✅ (4 live widgets: scan, month, Telegram approval + deck, proactive engine) |
| Before/after (VS) | ✅ |
| Cost comparison vs agency / employed | ✅ (+ tools+ChatGPT column) |
| 4 pricing tiers, monthly/yearly toggle | ✅ design · Starter €69 / Growth €149 / Agency €399 (+Enterprise), yearly −20 %, toggle, founding €197 band — numbers in `landing.html` → `PRICING`; rationale in `docs/PRICING-EU.md`. Live checkout still = founding only |
| Testimonial | ❌ no real one yet — never fabricate |
| FAQ | ✅ (7) |
| Blog / changelog / roadmap pages | ❌ (STRUCTURE.md §2.11) |
| Solutions by industry pages (SEO) | 🟡 — on-page "Otto for your industry" section (8 industries, pillars, hooks, sample card); separate SEO pages later |
| Integrations page (13 channels) | ❌ — "works with" strip only |
| 9 locales | ❌ EN only (HE later for IL market) |
| YC / investor logos | n/a |
| Cookie banner | ❌ (add before ads traffic; privacy-preserving default) |
| Structured data (FAQ / product) | ✅ JSON-LD FAQPage + SoftwareApplication offer |
| Sticky mobile CTA | ⭐ ✅ |

## Design
Native: dark painted Nordic hero, EB Garamond italic, gold accent, light body. **Otto: never that.** Porcelain/cobalt fintech,
Fraunces italic, Inter, JetBrains Mono, 3D orb + floating product cards. Rule from Max (28.09): "if I look the same I can't compete."

## Next in order
1. M2 tokens (Max): Meta app + page token per brand → `otto-secrets/meta-<brand>.json` → publisher + insights go live.
2. nginx `location /otto-peek` → the landing's real scan works in production.
3. Server crons from `platform/crons.md`; agent runs `otto-autopilot` skill.
4. Pricing decision (see PRICING-EU.md) → create the Whop subscription plans and point each tier CTA at its own checkout.
5. Solutions pages (restaurants, clinics, e-commerce, coaches…) reusing the landing's widgets with industry samples.
6. Studio (edit chat), Inbox, Brand memory page in Mission Control (STRUCTURE.md phases D/E).
