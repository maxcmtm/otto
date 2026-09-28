# Native.no parity + edge checklist
Date: 2026-09-28 · Source: native.no public site (read live), STRUCTURE.md audit, research/native-*.md · Owner: Claude Code (local)

Legend: ✅ have · 🟡 partial · ❌ missing · ⭐ our edge (they don't have it)

## Product loop
| Native has | Otto status | Where / next |
|---|---|---|
| Drop URL → research (site, industry, competitors, audience) → content plan | ✅ code | `otto_scan.py` (real scan: identity, palette, logo, fonts, socials, prices, trust, quotes, industry) + creative-engine skill for inference |
| "We generate 50 posts" per month per brand | ✅ code | `otto_plan.py build` (slot grid, pillar rotation, formats, best hours) + Quill fills copy via `fill` |
| Swipe approve / skip, per-platform preview | ✅ | Mission Control deck + **⭐ Telegram cards** (`ap.py decide … --via telegram`, taste log) |
| Refine in plain words ("make it warmer") | 🟡 | Edit flow in Telegram (reply → Quill rewrite). Dashboard "Studio" chat not built |
| Auto-publish on schedule (FB, IG, LinkedIn, X + 10 more) | 🟡 code, ❌ live | `otto_publish.py` (FB photo/feed, IG image) — waiting on Meta app + page tokens (M2). Carousel/reel/story publish + LinkedIn: not yet |
| Native Autopilot (plans 2 weeks, publishes with an email before) | ✅ design | otto-autopilot skill + crons: full-auto per pillar is a flag the owner turns on |
| Analytics on what's working | 🟡 code | `otto_insights.py` (reach/saves/clicks per post, winners, "double down" recs) — needs tokens to run live |
| Meta Ads autopilot (organic winners → ads, own ad account) | ❌ | Atlas on standby; M2 Meta Ads MCP decided, not wired |
| Inbox (comments/DMs, WhatsApp) | ❌ | STRUCTURE.md §2.5 — phase E |
| Brand memory / taste layer (binding brand voice) | 🟡 | brand-profile.md (locked) + `taste_log` in data.json; no UI page yet |
| Native MCP (control from Claude/ChatGPT) | ❌ | rec-008 — OpenClaw-native, cheap to add later |
| Weekly competitor research | ⭐ code | `otto_competitors.py sweep` (site deltas, live promos, ad-library checklist) + otto-competitor-research skill. Native shows none. |
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
| 4 pricing tiers, monthly/yearly toggle | 🟡 single founding €197 (subscription ladder pending Max's decision: 69/149/399 or 79/199/449) |
| Testimonial | ❌ no real one yet — never fabricate |
| FAQ | ✅ (7) |
| Blog / changelog / roadmap pages | ❌ (STRUCTURE.md §2.11) |
| Solutions by industry pages (SEO) | ❌ — typewriter covers 12 industries; per-industry pages are the SEO play |
| Integrations page (13 channels) | ❌ — "works with" strip only |
| 9 locales | ❌ EN only (HE later for IL market) |
| YC / investor logos | n/a |
| Cookie banner | ❌ (add before ads traffic; privacy-preserving default) |

## Design
Native: dark painted Nordic hero, EB Garamond italic, gold accent, light body. **Otto: never that.** Porcelain/cobalt fintech,
Fraunces italic, Inter, JetBrains Mono, 3D orb + floating product cards. Rule from Max (28.09): "if I look the same I can't compete."

## Next in order
1. M2 tokens (Max): Meta app + page token per brand → `otto-secrets/meta-<brand>.json` → publisher + insights go live.
2. nginx `location /otto-peek` → the landing's real scan works in production.
3. Server crons from `platform/crons.md`; agent runs `otto-autopilot` skill.
4. Pricing decision → 3-tier pricing section + monthly/yearly toggle on the landing.
5. Solutions pages (restaurants, clinics, e-commerce, coaches…) reusing the landing's widgets with industry samples.
6. Studio (edit chat), Inbox, Brand memory page in Mission Control (STRUCTURE.md phases D/E).
