# Autopilot MVP — "Native killer" on OpenClaw
Date: 2026-09-24 | Owner: Maximus | Approved by: Max ("יאללה תתחיל לעבוד")
Research base: `research/native-no-research.md`

## The product in one line
Paste a URL → the bot researches the brand, builds a monthly content plan (organic + paid),
generates the posts, and sends each one to Telegram for one-tap approval → publishes on schedule.
The user approves; the system does everything else.

## Architecture decision (differs from Native)
Native = web SaaS dashboard. We = **OpenClaw-native, Telegram-first**.
- The "AI engine" is the agent itself (no separate LLM backend to build/pay for)
- Approval surface = Telegram inline buttons (already supported by `message` tool)
- Scheduling = OpenClaw cron (exists)
- Per-client isolation = OpenClaw agent-per-client (provisioner exists from Otto)
This means MVP = mostly skills + light glue scripts, NOT a new SaaS build.

## Phases

### Phase 1 — URL → Brand Profile (auto-onboarding)  ✅ BUILT 24.09
Input: URL. Agent fetches site (+key subpages), extracts: industry, products, tone,
audience, competitors, languages, compliance constraints.
Output: `autopilot/brands/<brand>/brand-profile.md`
Status: **working — demoed on Happy Garden CBD** (see brands/happygarden/)

### Phase 2 — Content Plan Generator  ✅ v1 BUILT 24.09 (week-1 sample)
Input: brand profile. Output: monthly plan — 50 posts/brand, per-platform variants
(FB/IG/LinkedIn), mix of pillars (education/social-proof/product/engagement),
each post = copy + visual brief (feeds fire_ads.py / Leonardo pipeline).
Output: `autopilot/brands/<brand>/content-plan-YYYY-MM.md`
Next: full 30-day generation + visual generation hookup.

### Phase 3 — Telegram Approval Loop  ✅ demo sent 24.09
Each post → Telegram message with inline buttons: ✅ approve / ✏️ edit / ❌ skip.
Approved → queued to `queue.json` with publish slot. Callback handling via bot session.
Next: persistent queue + callback → state machine.

### Phase 4 — Publishing (the only real integration work)
- Meta Graph API: FB Page posts + IG Business publish (needs Page token; Max has Meta assets)
- LinkedIn API: company page posts
- Scheduler: cron reads queue.json, publishes at slot time
Estimate: 2-3 work sessions. This is the critical path.

### Phase 5 — Analytics feedback loop
Insights API pull weekly → what worked → adjust next batch prompts. After Phase 4.

### Phase 6 — Productize
- Fold into Otto provisioning (each customer gets an autopilot agent)
- Pricing: move to subscription — mirror Native: ~€79/mo (1 brand) / €199 (3 brands) / €449 agency
- Hebrew/IL + deep-EU-niche positioning; Telegram-first as the differentiator

## Pilot brand
**Happy Garden CBD** (happygardeneu.com) — Max's own business. Real stakes, zero client risk.
Note: CBD = restricted ads category on Meta → organic-first pilot is actually the right fit.

## Open decisions for Max
1. Publish targets for pilot: which FB page / IG account? (need asset IDs + token)
2. Post language for Happy Garden: EN, DE, or both? (site is EN, reviews are DE)
3. Subscription move for Otto: now or after pilot proves the loop?
