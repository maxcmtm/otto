# OTTO — דוח מערכת מלא (Handoff ל-Claude Code)
Date: 2026-09-28 (עודכן אחרי דיפלוי ל-git) · Author: Maximus · Source server: openclaw @ AWS (`/home/ubuntu/.openclaw/workspace-maximus/`)

> מסמך self-contained: כל הארכיטקטורה, הפרומפטים המלאים, מצב חי, ומה שחסר.
> **הריפו הרשמי: https://github.com/maxcmtm/otto (פרטי, branch `main`)** — הקוד + המסמך הזה ב-`docs/`.
> Claude Code מקומי: `git clone https://github.com/maxcmtm/otto.git` ומתחילים מ-`docs/OTTO-SYSTEM-REPORT.md`.

---

## 1. מה זה Otto — משפט אחד
**Otto = סוכן שיווק אוטונומי על תשתית OpenClaw**: הלקוח נותן URL → המערכת סורקת את המותג, בונה פרופיל אסטרטגי, מייצרת תוכנית תוכן חודשית (אורגני+ממומן), מייצרת קופי+ויז'ואלים on-brand, שולחת כל פוסט לאישור one-tap בטלגרם → ומפרסמת בפועל. הלקוח רק מאשר וסופר כסף. (המתחרה שאנחנו הורגים: Native.no — web SaaS; אנחנו Telegram-first + agent-per-client.)

**החלטת איחוד (27.09.2026):** Otto ו-Autopilot = פרויקט אחד בשם Otto. הקוד יושב ב-`autopilot/`, המיתוג Otto.

## 2. השכבה המסחרית (קיימת וחיה)
- מוצר נמכר ב-Whop: **€197 חד-פעמי** (מוצר ביניים; היעד: מנוי €79/199/449 כמו Native, אחרי שהלופ מוכח).
- Landing: https://dash.monyflow.work/pilot-landing.html · Checkout: https://whop.com/checkout/plan_joHl1qsZoiJc9
- Whop: company `biz_hSUmJXkmP4CrRh`, product `prod_FGbaAX2so8ahW`, plan `plan_joHl1qsZoiJc9`
- **זרימת רכישה:** תשלום → Whop webhook → `provisioner.py` (:8110, systemd `pilot-provisioner`) → מקים ללקוח instance OpenClaw משלו עם סקילים טעונים → מוסר לו בוט טלגרם.
- קוד הצנרת: `openclaw-installer/` — provisioner.py, provision.sh (חסום בלי `PILOT_SEND=1`), server-setup.sh, client_claim_owner.py, client_inject_connections.py, bot_factory.py, finish_whop_setup.py, skills-bundle/ + build_bundle.sh, railway-template/.

## 2.5 הדומיין וה-URLs החיים (dash.monyflow.work)
כל ה-web של Otto רץ תחת הדומיין **dash.monyflow.work** (nginx על השרת, מגיש מ-`/srv/pulse/`):
- **https://dash.monyflow.work/otto/** — Otto Mission Control (הדשבורד). מאחורי magic-link auth. הדף מזהה לבד: אם ה-action API חי → badge LIVE + כפתורי אישור אמיתיים; אחרת read-only SNAPSHOT.
- **https://dash.monyflow.work/pilot-landing.html** — דף המכירה הציבורי של Otto. **v4 (28.09, Claude Code מקומי) חי בריפו: `platform/landing.html`** — נבנה על מבנה ה-conversion של Native (דוגמאות אמיתיות + ווידג'טים שרצים חי) אבל בשפה העיצובית של Otto בלבד: fintech בהיר (porcelain/cobalt, Inter + Fraunces italic + JetBrains Mono), הירו תלת-ממדי עם ה-core orb + טבעות מסלול + כרטיסי מוצר צפים (pointer-tilt), מרקיז של פוסטים אמיתיים מ-`assets/posts/`, 4 פרקי "How it works" עם ווידג'טים חיים (סריקת URL→פרופיל, לוח חודשי שמתמלא, לופ אישור בטלגרם+deck, מנוע פרואקטיבי), flip, טבלת השוואה, צוות 6 הסוכנים, מחיר founding €197, FAQ. **חוק:** לא להיראות כמו Native — אם זה נראה כמוהם אי אפשר להתחרות בהם. הדף מפנה ל-`/otto/assets/...` בנתיב מוחלט, ולכן `deploy.sh` מעתיק אותו ל-`/srv/pulse/pilot-landing.html` (אותו host כמו `/otto/`). הגרסה הישנה (v3, dark Space Grotesk) נשארת רק ב-`dashboard/pilot-landing.html` בשרת עד הדיפלוי הבא.
- **`/otto-api/`** — proxy של nginx ל-otto_api.py (localhost:8161) — הכפתורים בדשבורד כותבים דרכו ל-data.json.
- דיפלוי: `deploy.sh` מעתיק את הסטטיקה ל-`/srv/pulse/otto/` וגם את `landing.html` ל-`/srv/pulse/pilot-landing.html` (copy, לא symlink — nginx לא יכול לעבור דרך `~/.openclaw` שהוא 700). מ-28.09 הלנדינג נערך **רק בריפו** (`platform/landing.html`), לא ב-`dashboard/`.
- תצוגה מקומית (Claude Code): שרת סטטי שמגיש תיקייה עם `otto -> platform` symlink + `pilot-landing.html -> platform/landing.html`, כך שהנתיבים `/otto/assets/...` זהים לפרוד.
- הערה: הדומיין משרת גם דשבורדים אחרים של מקס (Pulse וכו') — Otto חי תחת `/otto/` + הלנדינג.

## 3. ארכיטקטורה — Mission Control
**עיקרון:** הפעולה בטלגרם, התמונה בדשבורד. המנוע = סוכני OpenClaw; הדשבורד קורא state, לא מריץ לוגיקה.

```
autopilot/
├── brands/<slug>/            # brand-profile.md, content-plan, winning-ads-analysis, assets
│   └── BRAND-PROFILE-TEMPLATE.md
├── platform/
│   ├── index.html            # Mission Control (fintech light theme: porcelain #F5F7FB, cobalt #2447F0,
│   │                         #   Inter + Fraunces italic + JetBrains Mono; מובייל: Tinder-style swipe approve)
│   ├── data.json             # single source of truth (state)
│   ├── ap.py                 # CLI — כל כתיבה ל-data.json עוברת פה (add/status/recs/sync-fallback)
│   ├── otto_api.py           # action API, localhost:8161, nginx מפרוקסה /otto-api/ (systemd: otto-api.service)
│   ├── otto_watch.py         # מנוע פרואקטיבי: דוח בוקר יומי + שומר שעתי (התראות ירידה/סלוטים)
│   ├── genvisuals.py         # ויז'ואלים דרך Leonardo GPT Image 2 → assets/posts/<post-id>.png
│   ├── deploy.sh             # sync-fallback + copy ל-/srv/pulse/otto/ (חי ב-dash.monyflow.work/otto/)
│   ├── onboarding.html, ads.html, analytics.html, approve.html
│   └── ARCHITECTURE.md, STRUCTURE.md
├── mcp/otto-social-mcp/      # MCP server שלנו לפרסום אורגני Meta (7 כלים)
├── skills/otto-creative-engine/SKILL.md
├── skills/otto-competitor-research/SKILL.md   # חדש 28.09
└── research/  (mcp-connections-m2.md, creative-and-competitor-stack.md)
```

**data.json schema:** `brands[]` (id,name,url,lang,status,pillars,compliance) · `posts[]` (id,brand,pillar,platform,copy_hook,status: draft→pending_approval→approved→scheduled→published→skipped, slot ISO, approved_via) · `recommendations[]` (first-class! "הסוכנות ממליצה" — rec-add/rec via ap.py) · `agents[]` · `metrics` · `connections` · `fleet`.

**אינפרה חיה כרגע:**
- systemd: `otto-api.service` (running) · `pilot-provisioner.service` (running)
- cron: `otto_watch.py report` יומי 04:30 UTC (07:30 IL) · `otto_watch.py watch` שעתי (xx:15)
- דשבורד חי: https://dash.monyflow.work/otto/ (מאחורי auth)
- מצב pipeline (28.09): 2 מותגים active · 4 posts pending_approval · 4 draft · 1 approved · 1 scheduled · 1 published (demo) · 8 recommendations

**הפרדת סוכנים (אחרי שהלופ מוכח):** `autopilot-core` (אורקסטרטור, workspace משלו) · `autopilot-<client>` per-client דרך ה-provisioner · `maximus` נשאר owner/developer. בידוד: טוקנים per-client secrets dirs, אין ערבוב cross-brand, crons בnamespace `autopilot:*`.

## 4. שבעת המודולים + סטטוס
| # | מודול | סטטוס |
|---|---|---|
| M1 | Onboarding: URL→מותג חי→תוכנית תוכן→לופ אישורים | ✅ עובד (happygarden, cmtm) |
| M2 | חיבורי פרסום: Meta+Google דרך MCP, לקוח מתחבר OAuth | 🔨 **החסם הקריטי** — הוחלט: Meta ads = MCP רשמי `mcp.facebook.com/ads`; Google Ads = MCP רשמי (Apache-2.0, בלי dev token); אורגני = otto-social-mcp שלנו (בנוי, ממתין ל-Meta app + page token) |
| M3 | קריאייטיב תמונות+וידאו | 🔨 הוחלט: fal.ai hosted MCP (`mcp.fal.ai/mcp`, מפתח אחד — FLUX/GPT-Image תמונות, Kling 3.0 רילסים ~$0.10/sec, Veo 3.1 הירו עם אודיו). בינתיים Leonardo GPT Image 2 עובד בפרוד (genvisuals.py). חסר: FAL_KEY |
| M4 | מנוע קופי (Hormozi/Suby/Brunson) | ✅ v1 — `otto-copy-engine` skill, בחבילת כל לקוח |
| M5 | בילדר דפי נחיתה (profile+offer→דף ממיר, deploy אוטומטי, פיקסלים) | 🔨 היכולת קיימת (pilot-landing, דף מימדים), לא ממוסגר כמודול |
| M6 | אורגני אוטונומי + חקר מתחרים שוטף + לופ אנליטיקס | 🔨 סקיל competitor-research נבנה 28.09; לופ מלא אחרי M2 |
| M7 | מסחור: מנוי + provisioning מלא, Mission Control = דשבורד הלקוח | ⏳ אחרי שהלופ מוכח |

**Critical path:** M2 Meta MCP+OAuth → M6 מינימלי (פוסט אורגני חי end-to-end על Happy Garden) → M3+M4 בלופ → M2 Google+ממומן, M5 → M7.

## 5. מותגי הפיילוט
- **Happy Garden CBD** (happygardeneu.com, של מקס) — פרופיל מלא: פלטה נסרקה חי (צהוב `#FFBC00` דומיננטי + שחור/לבן, אקסנטים ורוד/קורל), 4 אווטארים (שינה, כאב, חרדה-בלי-THC, בעלי חיות) + התנגדויות וזוויות (טיוטה — אין היסטוריית מודעות). CBD = קטגוריה מוגבלת במטא → organic-first זה בדיוק הפיט.
- **CMTM / תרפיית מימדים** (cmtm.co.il) — זהב אמיתי: brand guide מלא (הקסים, מבנה מודעה, מיקום לוגו) + ניתוח כל המודעות המנצחות אי-פעם לפי CPL (הזוכה: "תוך שנה הפכתי למטפלת" — 647 לידים ב-₪44). קבצים: `brands/cmtm/terapia-brand-guide.md`, `terapia-winning-ads-analysis.md`.

## 6. הפרומפטים המלאים (הליבה)

### 6.1 otto-creative-engine (מיזוג CreativeGod + Facebook Ads Master)
**חוק העל:** הלקוח לא ממלא שאלון לעולם. נותן URL → אוטו סורק וממלא את הפרופיל בשבילו → מקסימום 3-4 שאלות פער. העיצוב תמיד נשאב מהמותג שלו, אף פעם לא לוק גנרי.

**Pipeline:**
1. **Scan (אוטומטי):** fetch homepage+about+products+testimonials+pricing. חילוץ ויזואלי: צבעים (`curl -sL <url> | grep -oE '#[0-9a-fA-F]{6}' | sort | uniq -c | sort -rn | head -12` + theme-color meta), לוגו (og:image / img עם "logo") → `brands/<slug>/logo.png`, פונטים+וייב. חילוץ קול+שוק: שפות, טון, ציטוטי ביקורות verbatim (= זהב לקופי), עוגני אמון, מחירים. אם יש FB/IG — פוסטים אחרונים + מודעות עבר לניתוח זוויות מנצחות.
2. **מילוי הפרופיל (טיוטה אוטומטית):** BRAND-PROFILE-TEMPLATE → `brands/<slug>/brand-profile.md`. כל סעיף מנוסח מהסריקה; השערות לא מאומתות מסומנות `(?)`.
3. **אישור פערים בלבד (≤4 שאלות):** בד"כ — מחיר אם מוסתר, זווית מנצחת מהעבר, ההתנגדות הכי נפוצה בשיחות, הוכחות אופליין. אושר → ננעל כמקור אמת קריאייטיבי.
4. **ייצור (on-brand תמיד):** כל ייצור חייב לקרוא את brand-profile.md קודם — פלטת המותג בלבד, לוגו לפי ה-guide, קול המותג + ציטוטים אמיתיים, זווית אחת לקריאייטיב, hook קודם, ציות ל-compliance.

**מתכון פרומפט לויז'ואל מודעה:**
```
[FORMAT] ad creative for [BRAND], [industry].
Brand palette: [hex list — mandatory, dominant].
Visual style: [from profile: premium/warm/clinical/... + motifs].
Scene: [angle-specific — the avatar's moment: pain, dream outcome, or proof].
Text on image: "[hook ≤6 words, brand language]" in [font vibe], high contrast.
[Logo band/space instruction per brand guide]. No generic stock look, no watermarks.
```

**Leonardo GPT Image 2 (רץ בפרוד):** `POST https://cloud.leonardo.ai/api/rest/v2/generations`, Bearer key (otto-secrets). Body: `{"model":"gpt-image-2","parameters":{"width":W,"height":H,"prompt":"...","quality":"HIGH","quantity":1,"prompt_enhance":"OFF"},"public":false}`. יחסים: feed 4:5 = 848×1264, ריבוע 1024², סטורי 9:16 = 768×1376. בלי style_ids/seed — הסטייל כולו בפרומפט (חובה hex של המותג + "leave clear space bottom-right for logo"). לוגו כרפרנס: `POST /v1/init-image` → S3 → `guidances.image_reference`. Poll כל 15-20 שניות. ~$0.20/תמונה. הורדה חייבת browser User-Agent (אחרת 403). **עברית לא מרונדרת בתוך תמונה** (המודלים הורסים אותה) — הקופי בכיתוב, הויז'ואל text-free.

**מ-Facebook Ads Master:** כל claim בקריאייטיב חייב להתקיים באתר הלקוח או בנכסי הוכחה — לא ממציאים מספרים/תעודות/ערבויות. נכסי לקוח (לוגו/תמונות/ZIP) נפתחים ומאומתים לפני שימוש → `brands/<slug>/assets/`. קטגוריות מוגבלות (CBD, בריאות נפשית, תעסוקה, פיננסים) → organic-first כשמטא מגבילה.

**זיכרון מודעות מנצחות:** אחרי דאטה אמיתי (M2+) — `brands/<slug>/winning-ads-analysis.md` מדורג CPL/CTR; קריאייטיבים חדשים איטרציה על מנצחים, לא מאפס.

### 6.2 otto-copy-engine (Hormozi / Suby / Brunson)
כל קופי של Otto עובר פה. קופי גנרי = באג.
- **Step 0:** לקרוא brand-profile.md. אין פרופיל → אין קופי.
- **Step 1 — ההצעה (Hormozi Value Equation):** `Value = (Dream Outcome × Likelihood) / (Time Delay × Effort)`. תוצאת חלום במילים של הלקוח, הוכחות, התקפה על delay+effort, offer stack: ליבה + בונוסים (כל אחד פותר התנגדות) + risk reversal + scarcity אמיתי בלבד. בדיקה: אפשר לנסח את ההצעה במשפט שקשה לסרב לו.
- **Step 2 — Hook והדליין (Suby):** להוביל עם bleeding-neck problem או pattern interrupt. בנק נוסחאות: call-out+promise+timeframe+objection ("How [avatar] get [outcome] in [time] without [pain]"), פער סקרנות עם מספר, framing אויב/סוד. 10 מועמדים → 1 נבחר + 2 ל-A/B.
- **Step 3 — מבנה גוף:** דפי נחיתה = HVCO + Star-Story-Solution: agitation→מנגנון למה ניסיונות קודמים נכשלו→סיפור מקור (epiphany bridge)→המנגנון הייחודי בשם→הוכחות→offer stack→risk reversal+P.S. מודעות = hook→כאב/סקרנות אחד→הוכחה אחת→CTA עם message match לדף. אורגני = value-first, CTA רק בפוסטי המרה ייעודיים. אימיילים = Soap Opera Sequence ואז Seinfeld dailies.
- **Step 4 — אמת+ציות:** claim לא מאומת → נחתך או `[needs client approval]`.
- **Step 5 — אנטי-סלופ:** מחיקת "unlock/elevate/seamless/game-changer", שרשראות מקפים, שלשות סימטריות. משפט שיכול להופיע אצל מתחרה → נמחק. ספציפיות > ליטוש.
- **פלט:** הקופי + 3 שורות רציונל (אווטאר, זווית, האמונה שצריך לשנות).

### 6.3 otto-competitor-research (נבנה 28.09)
מודיעין מתחרים per-brand → `brands/<slug>/competitor-research.md`, רענון שבועי (M6).
1. **רשימה:** 5-8 מתחרים (2-3 ישירים, 2-3 שאיפתיים, 1-2 צמודי-קהל) מהפרופיל + web search.
2. **סריקת ממומן:** Meta Ad Library (חינם, דרך browser tool; **longevity = הסיגנל #1** — מודעה 30+ יום = מנצחת מוכחת; הרבה וריאנטים = scaling; EU/DSA מציג גם reach). TikTok Creative Center Top Ads (פורמטים+הוקים לפי תעשייה). Google Ads Transparency Center (שפת intent בחיפוש). בסקייל: Apify actors (~$1.5/1k, גם MCP) + ScrapeCreators ($47/25k) + Meta Ad Library API רשמי (חינם, EU).
3. **סריקת אורגני:** IG/TikTok/FB — רק outliers (engagement חריג = הקהל הצביע) ותבניות.
4. **סינתזה:** מנצחי longevity → רשימת steal-and-improve (זווית+פסיכולוגיה, אף פעם לא העתקה — ייצור מחדש 100% on-brand), פערים (זוויות שאף אחד לא מריץ), 3-5 בריפים קונקרטיים ל-creative-engine.
- בנישות מוגבלות: הניסוח התואם-מטא של מתחרים = זהב, לתעד מילה במילה.

### 6.4 BRAND-PROFILE-TEMPLATE (מה שממולא אוטומטית לכל לקוח)
סעיפים (AUTO=מהסריקה, ASK=רק אם אין תשובה, מקס 3-4): Business snapshot (מה מוכרים כ-outcome, מחיר, USP, שוק+שפות, עוגני אמון) · Core audience (דמוגרפיה, פסיכוגרפיה, awareness level) · Avatars 2-4 ("[שם], [גיל], [תפקיד]" — מה הוא אומר לעצמו, כאב, טריגר לקנות עכשיו, מה משכנע) · כאבים מדורגים בשפת הלקוח · טריגרים · התנגדויות+קאונטרים · אלטרנטיבות שנכשלו · ציטוטי ביקורות verbatim · נכסי הוכחה · הבטחת ליבה+פוזישנינג (Not/Yes) · זוויות מנצחות מדורגות · **VISUAL IDENTITY** (פלטת hex, לוגו+חוק מיקום, טיפוגרפיה, סגנון צילום, motifs) · Compliance · עמודי תוכן 4-6.

### 6.5 otto-social-mcp (הקוד שלנו, בנוי 27.09)
MCP server (stdio, Python) לפרסום אורגני Meta. Multi-tenant: תהליך per-client, tenant=env vars. 7 כלים: `fb_page_post` (טקסט/לינק/תמונה+תזמון) · `ig_publish_image` · `ig_publish_carousel` · `ig_publish_reel` (async polling) · `ig_publish_story` · `ig_publishing_limit` · `page_insights`. דרישות טוקן: long-lived Page token עם `pages_manage_posts, pages_read_engagement, instagram_basic, instagram_content_publish`. במצב dev עובד לאדמינים/טסטרים מיד; לקוחות ציבוריים = App Review + Business Verification (~20 יום). **ממתין ל:** Meta app + page token של Happy Garden.

## 7. מנוע פרואקטיבי (otto_watch)
- דוח בוקר יומי 07:30 IL לטלגרם של מקס + snapshot ל-metrics_history.jsonl.
- שומר שעתי: ירידת מדד ≥30% מול ממוצע 7 ימים (בסיס מינימלי 50), פרסומים שפוספסו, אישורים שעומדים לפספס סלוט. שולח רק כשמשהו לא בסדר, dedup 1/יום per key.

## 8. סודות (מיקומים בלבד — הערכים בשרת)
- `otto-secrets/` — אינוונטר מלא ב-README.md; whop.json (מפתחות Whop חיים).
- Leonardo API key — **הוצא מהקוד (28.09)**: `genvisuals.py` קורא env `LEONARDO_API_KEY` או `platform/.leonardo_key` (chmod 600, ב-.gitignore). עדיין hardcoded ב-funnels/*/fire_ads.py (מחוץ לריפו).
- ⚠️ פתוח: rotate ל-Whop webhook secret (דלף ללוג, קוצץ ונשמר chmod 600).

## 9. מה חסר — הרשימה המדויקת
**חוסם את הלופ (M2, אצל מקס):**
1. Meta App (app_id+app_secret+redirect URI) + חיבור עמוד FB/IG של Happy Garden → page token. במצב dev עובד מיד.
2. Business Verification להתניע ברקע (~20 יום; נדרש רק ללקוחות משלמים).
3. FAL_KEY ל-fal.ai (https://fal.ai/dashboard/keys) — ויז'ואלים+וידאו בפרודקשן.

**חוסם מכירה end-to-end אוטומטית (provisioner):** Hetzner creds (HCLOUD_TOKEN+SSH key) · Telegram api_id/api_hash+userbot session ל-bot factory · פורמט הזרקת Claude auth ללקוח (sub-account/BYOK/pool) · `PILOT_SEND=1` בפרוד.

**החלטות פתוחות למקס:** שפת פוסטים HG (EN/DE/שניהם) · תזמון מעבר למנוי · איחוד שם סופי Otto vs Pilot בקוד/Whop.

**טכני הבא בתור:** callback טלגרם→state machine מלא לאישורים · queue.json→scheduler cron לפרסום בסלוט · לופ אנליטיקס שבועי (Insights→כיוונון באץ' הבא) · הפרדת autopilot-core לסוכן משלו.

## 10. Git + עבודה מול Claude Code מקומי (חי מ-28.09.2026)
**הריפו:** https://github.com/maxcmtm/otto — פרטי, branch `main`. Root הריפו = `autopilot/` בשרת. הדחיפה מהשרת דרך deploy key בשם `otto-server` (המפתח: `~/.ssh/id_ed25519` בשרת, עם write access).

**מה בריפו (50 קבצים):** `platform/` (Mission Control: ap.py, otto_api.py, otto_watch.py, genvisuals.py, deploy.sh, כל ה-HTML, assets) · `brands/` (טמפלייט + cmtm + happygarden) · `skills/` (otto-creative-engine, otto-competitor-research) · `mcp/otto-social-mcp/` · `docs/` (MASTER-PLAN, SYSTEM-REPORT, OWNER-CHARTER).

**מה בכוונה לא בריפו (.gitignore):** `platform/.leonardo_key` וכל סוד · `platform/data.json` + לוגים + metrics (סטייט חי של השרת — לא דורסים אותו מ-git) · `.venv` · קבצי `.bak`.

**זרימת העבודה:**
1. Claude Code מקומי: clone → עובד → commit+push ל-`main`.
2. אומרים למקסימוס (הסוכן בשרת) "תמשוך ותפרוס" → הוא עושה `git pull` ב-`autopilot/`, מריץ `platform/deploy.sh` (מעתיק ל-`/srv/pulse/otto/`), ומוודא שהשירותים חיים.
3. שינויים שהשרת עושה (סקילים/מסמכים/פרופילי מותג) — מקסימוס דוחף חזרה לריפו. לפני pull מקומי: `git pull` תמיד.
- `data.json` נערך **רק בשרת** (ap.py). Claude Code שמשנה סכימה — מתאם עם מקסימוס לפני.

**חוקי פרוד (בתוקף גם דרך git):** לפני נגיעה ב-provisioner — `systemctl --user status pilot-provisioner` + בדיקת provisioner.db; תמיד `.bak.<date>`; dry-run; רק אז restart. הקוד המסחרי (`openclaw-installer/`, provisioner, לנדינג) עדיין מחוץ לריפו הזה — חי בשרת בלבד.

## קבצי אמת בשרת (למי שמתחבר)
`OTTO-MASTER-PLAN.md` (רודמאפ) · `OTTO-OWNER-CHARTER.md` (צנרת מסחרית) · `autopilot/platform/ARCHITECTURE.md` · `autopilot/MVP-PLAN.md` · `autopilot/research/*.md` (החלטות MCP/סטאק) · `brands/*/brand-profile.md` · הסקילים: `autopilot/skills/otto-creative-engine/`, `autopilot/skills/otto-competitor-research/`, `openclaw-installer/skills-bundle/otto-copy-engine/`.
