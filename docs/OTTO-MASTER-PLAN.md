# OTTO — Master Plan (המערכת המאוחדת)
Date: 2026-09-27 | Owner: Maximus | Directive: Max — "צריך לאחד אותם, זה אותו פרויקט, תקרא לו Otto"

## ההחלטה (27.09)
**Otto ו-Autopilot הם פרויקט אחד: Otto.**
- אין יותר שני מסלולים. ה-Autopilot platform הוא הליבה; Otto הוא השם, המותג והמעטפת המסחרית.
- החזון: מערכת אחת על התשתית שלנו (כמו Native) שעושה את **כל השיווק** של הלקוח —
  ממומן + אורגני + קריאייטיב + דפי נחיתה — והלקוח רק מנהל את העסק וסופר כסף.
- `autopilot/` נשאר מיקום הקוד בינתיים; המיתוג, המסמכים והשמות החדשים = Otto.

## המערכת — 7 מודולים

### M1 — Onboarding: URL → מותג חי  ✅ קיים (Phase 1-2)
URL → brand profile → תוכנית תוכן חודשית → לופ אישורים בטלגרם.
קיים ועובד (happygarden, cmtm). Mission Control dashboard בנוי.

### M2 — חיבורי פרסום: Meta + Google דרך MCP  🔨 בעבודה (החלטות נסגרו 27.09)
**הוחלט (ראה `autopilot/research/mcp-connections-m2.md`):** Meta Ads = MCP רשמי של Meta (`mcp.facebook.com/ads`, OAuth לקוח, בלי review); Google Ads = MCP רשמי של גוגל (Apache-2.0, בלי developer token מאז 09.26); אורגני = `otto-social-mcp` שלנו — **נבנה 27.09**, 7 כלים (FB post, IG image/carousel/reel/story, quota, insights), נטען ונבדק. חסר לפיילוט: Meta app + page token של Happy Garden.
הנחיית מקס: **MCP הוא שכבת החיבור, הלקוח מתחבר ב-OAuth.**
- Meta: MCP server מול Marketing API + Graph API (פוסטים, קמפיינים, אינסייטס).
  לבדוק קודם MCP קיים (meta-ads-mcp וכד') לפני שבונים מאפס.
- Google: MCP מול Google Ads API באותו דפוס OAuth.
- זרימת לקוח: כפתור "Connect Meta/Google" → OAuth → הטוקן נשמר בסודות פר-לקוח
  (per-client secrets dir, לפי כללי הבידוד ב-ARCHITECTURE.md).
- זה מחליף את Phase 4 הישן (פרסום ידני מול Graph API) — אותו יעד, דרך MCP.

### M3 — קריאייטיב: תמונות + וידאו דרך MCP  🔨 (סטאק הוחלט 27.09)
**הוחלט (ראה `autopilot/research/creative-and-competitor-stack.md`):** fal.ai hosted MCP (מפתח אחד: FLUX/GPT-Image לתמונות, Kling 3.0 לרילסים, Veo 3.1 להירו-ספוטים עם אודיו) + Leonardo כגיבוי מוכח. חסר: FAL_KEY.
- MCP למודל תמונות (יש כבר pipeline עובד: Leonardo/GPT Image 2 ב-fire_ads.py — לעטוף כ-MCP או להשתמש ב-image_generate הקיים).
- MCP/כלי לוידאו קצר (רילסים, קריאייטיבים לקמפיינים) — video_generate קיים ב-OpenClaw; לבחון ספקים.
- כל visual brief מתוכנית התוכן נשלח לכאן אוטומטית.

### M4 — מנוע קופי  ✅ v1 נבנה 27.09
Skill חי ב-`openclaw-installer/skills-bundle/otto-copy-engine/SKILL.md` — Value Equation (Hormozi), הוקים+HVCO (Suby), Story/Offer-stack (Brunson), compliance pass, anti-slop pass. נכנס לחבילת כל לקוח.
רמת Alex Hormozi / Sabri Suby / Russell Brunson — כבר הוכח על דף מימדים (27.09).
- לקודד את זה כ-skill קבוע: value equation (Hormozi), HVCO+funnel logic (Suby), story/hook/offer stack (Brunson).
- משמש: מודעות, דפי נחיתה, פוסטים, אימיילים. יש skills קיימים (copywriting, offers, ad-creative) — לחבר אותם לפרופיל המותג.

### M5 — בילדר דפי נחיתה  🔨
- brand profile + offer → דף נחיתה ממיר ויפה (יש לנו את היכולת — pilot-landing, דף מימדים).
- תבניות: VSL / lead-gen / checkout. עיצוב ברף fintech (taste-skill, frontend-design).
- דיפלוי אוטומטי לתשתית שלנו (srv/pulse pattern) + פיקסלים מחווטים מהיום הראשון.

### M6 — אורגני אוטונומי  🔨
- מחקר מתחרים שוטף: מה הם מפרסמים, מה עובד ומה לא (competitor-tracker, trend-spotter).
- מייצר ומפרסם לבד: פוסטים, רילסים, סטוריז — לכל הרשתות שהלקוח חיבר (דרך M2/M3).
- לופ אנליטיקס (Phase 5 הישן): Insights שבועי → מכוונן את הבאץ' הבא.

### M7 — מסחור  (אחרי שהלופ מוכח)
- Otto = מנוי: ~€79/199/449 (כמו Native). ה-€197 החד-פעמי הנוכחי = מוצר ביניים עד המעבר.
- Provisioner קיים → כל לקוח מקבל agent משלו עם המערכת המלאה.
- Mission Control = הדשבורד של הלקוח; טלגרם = ממשק הפעולה.

## סדר בנייה (critical path)
1. **M2 Meta MCP + OAuth** — בלי זה אין פרסום אמיתי. פיילוט: Happy Garden.
2. **M6 מינימלי** — פוסט אורגני חי מקצה לקצה (URL→תוכן→אישור טלגרם→פורסם ב-FB/IG).
3. **M3+M4** מחוברים ללופ (ויז'ואלים+קופי אוטומטיים לכל פוסט).
4. **M2 Google + קמפיינים ממומנים**, M5 דפי נחיתה.
5. **M7** מעבר למנוי + provisioning מלא.

## החלטות פתוחות למקס (יורש מ-24.09)
1. עמוד FB / חשבון IG לפיילוט Happy Garden (asset IDs) — ה-OAuth החדש יכול לפתור את הטוקן.
2. שפת פוסטים ל-HG: EN / DE / שניהם.
3. תזמון מעבר Otto למנוי (הנטייה: אחרי שהלופ מוכח על HG).

## קבצי אמת
- מסמך זה — התמונה המאוחדת.
- `autopilot/MVP-PLAN.md` + `autopilot/platform/ARCHITECTURE.md` — פירוט טכני (Phases 1-6 הישנים ממופים למודולים כאן).
- `OTTO-OWNER-CHARTER.md` — הצנרת המסחרית הקיימת (Whop, provisioner, landing).

## 2026-09-28 — Creative engine merged from CreativeGod + Facebook Ads Master
- New skill: `autopilot/skills/otto-creative-engine/SKILL.md` — URL→Strategic Profile auto-fill (customer answers ≤4 gap questions, never a questionnaire), visual identity extracted from THEIR site (colors/logo/style), Leonardo GPT Image 2 recipe, FB-Ads-Master practices (claim verification, restricted categories, asset intake), winning-ads memory loop.
- Template: `autopilot/brands/BRAND-PROFILE-TEMPLATE.md` (AUTO/ASK markers).
- Both pilot brands upgraded: cmtm got the real Terapia brand guide + all-time winning-ads analysis (copied from workspace-creative); happygarden got live-scanned palette (#FFBC00 yellow) + avatars/angles draft.
- Rule now enforced: every creative generation reads brand-profile.md first — brand's palette/voice, never a generic Otto look.

## 2026-09-28 — Competitor research skill + system handoff report
- New skill: `autopilot/skills/otto-competitor-research/SKILL.md` — Meta Ad Library / TikTok Creative Center / Google Ads Transparency sweeps per brand (longevity = #1 signal), scaled path via Apify/ScrapeCreators/official Meta API. Output `brands/<slug>/competitor-research.md` → feeds creative engine + M6 loop.
- `OTTO-SYSTEM-REPORT.md` — full self-contained system handoff (architecture, all core prompts, live state, blockers) for Max's local Claude Code.

## 2026-09-28 — Autopilot engine v1 (Claude Code, local → git)
Directive from Max: "מערכת שיווק אוטומטית לחלוטין, כולל חקר מתחרים אוטומטי". The loop is now code, not ad-hoc agent work:
- `platform/otto_scan.py` — URL → `scan.json` + brand-profile draft (identity, palette/logo/fonts, socials, prices, trust, quotes, industry). Also powers the public `/otto-peek` endpoint the landing uses for a REAL scan of a visitor's site.
- `platform/otto_plan.py` — brand pillars + slots → full month of draft posts in data.json + `content-plan-YYYY-MM.md`; `fill` imports Quill's copy (`--pending` → straight to the deck).
- `platform/otto_competitors.py` — weekly sweep: competitor list (seeded from the profile, sites resolved), site fingerprints + diffs, live promos, ad-library checklist links, dated section in `competitor-research.md`, recommendation filed when something moved.
- `platform/otto_publish.py` — cron publisher (FB photo/feed, IG image) with grace window, retries, failed→P0; needs `otto-secrets/meta-<brand>.json`.
- `platform/otto_insights.py` — weekly metrics pull, winners ranking, `winning-posts.md`, "double down" recommendation.
- `platform/ap.py` — `decide` (approve/skip/later + taste log), `set`, `brand-add`, `taste`; env-overridable paths for tests.
- `platform/otto_api.py` — `/otto-api/decide`, `/otto-api/peek`, public `/otto-peek` (SSRF-guarded, rate-limited, cached).
- `skills/otto-autopilot/SKILL.md` — the orchestration playbook (onboarding, daily, weekly, monthly, what Otto decides alone, Telegram card protocol). `platform/crons.md` — server crons.
- `docs/NATIVE-PARITY.md` — feature-by-feature parity + edge checklist vs native.no, with the build order.
Module status update: M1 ✅ code · M2 🟡 publisher written, tokens pending · M3 unchanged · M4 ✅ · M5 unchanged · **M6 ✅ code (competitors + insights loop), live after M2** · M7 unchanged.

## 2026-09-28 (later) — engine v1.1: Telegram loop in code, visuals from state, pricing proposal
- `platform/otto_telegram.py` — cards with inline buttons (send-cards / send-recs), long-poll handler (poll): approve/skip/later → `ap.decide` + card edited in place; ✏️ edit → owner's reply → `edit_requests[]` for Quill. Needs a bot token (`otto-secrets/telegram.json`) + systemd service (crons.md).
- `platform/genvisuals.py` — no more hardcoded list: every post without an image, prompt from the profile's palette/style + the post's brief, writes `image` back.
- `otto_competitors.py` writes `competitors[brand]` summary → Mission Control "Competitor watch" card; dashboard also shows "What you've taught Otto" (taste log), source badges on recommendations, format chips, failed posts + rewrite requests in reminders.
- Landing v5: pricing tiers (Starter €69 / Growth €149 / Agency €399, yearly −20 %, toggle; founding €197 band), "Otto for your industry" (8 industries), sticky mobile CTA, JSON-LD.
- `docs/PRICING-EU.md` — EU market research (Native, AI tools, agencies) + recommended ladder for Max's decision.

## 2026-09-28 (evening) — engine v1.2: paid layer + growth ledger + stories
Max: "דוחות יומיים של קמפיינים פייסבוק גוגל + גאנט חודשי שיעלה לכל הרשתות + פוסטים אורגניים וסטוריז" and "כל נתוני השיווק מול העיניים, מה השתנה מחודש לחודש, צמיחה".
- `platform/otto_ads.py` — report (Meta Marketing API + Google Ads GAQL: spend/results/CPL/CTR yesterday + 7d, best/worst, suggested action → rec card), plan (monthly paid Gantt: evergreen, 2 boosts of organic winners, Google Search; restricted categories → compliance hold, no Google), approve, launch (Meta campaign→adset→creative→ad; Google Search via one mutate with temp ids), guard (ended flights, CPL rule), pause.
- `platform/otto_growth.py` — growth[brand]: months table (reach, engagement, posts, followers, spend, results, CPL, decisions, best pillar), MoM %, 90-day series, review text; `--send` on the 1st.
- `platform/otto_publish.py` — IG stories/carousels/reels, FB photo stories/multi-photo/video. `otto_plan.py` — story slots Mon/Wed/Fri 12:00 (brands[].story_days/story_time).
- Mission Control — Growth section (KPI deltas + sparkline + autopilot-start marker), "Paid · Facebook + Google" rail card, campaign flight bands in the month plan, day detail lists campaigns, KPI "Reach this month".
- Landing — chapter 05 "Paid, and the numbers" (daily report + month-in-review widget), Growth tier copy.
Module status: **M2 paid = code written (Meta + Google), waiting on ad-account credentials** · M6 analytics loop now includes the growth ledger.

## 2026-09-28 (night) — v1.3: Apple-grade UI, English only, reels, ad creatives, format mix
Max: "עיצוב יותר של Apple, שלא יורגש שזה עוצב ב-AI", "הכל באנגלית", "האווטארים מצועצעים, בלגן בעיניים", "רילסים של הסברה 30–60 שניות בחבילה הבסיסית", "קרוסלות לפי מה שהמתחרים עושים", "מודעות בכל הסגנונות עם טקסטים, זוויות מהמתחרים", "רמת סוכנות הכי גבוהה".
- Mission Control + landing restyled: system font, sentence case, no mono/emoji/avatars, grouped hairline lists, real month calendar, Apple Reminders-style list, four KPIs, rail = Connections · Paid · Signals, team = quiet list. Demo data, watch messages, mockups: English only (`hook_en`/`caption_en` supported for non-English clients).
- `platform/otto_video.py` — explainer reels (scenes → images → captions → VO → music) via ffmpeg. `platform/otto_creative.py` — text on image (brand band), ad variants (angles × static/carousel/video, titles/bodies), angle bank from `angles.json` (competitor sweep) → profile → hooks. `otto_ads.py launch` = Meta dynamic creative (asset_feed_spec). `otto_plan.py` — format mix by industry + competitors, ≥4 reels/month. `genvisuals.py` — carousel slides with copy. `otto_competitors.py angles/formats`.
