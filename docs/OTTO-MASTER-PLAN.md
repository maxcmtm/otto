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
