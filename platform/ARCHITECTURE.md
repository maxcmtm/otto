# Autopilot Platform — Architecture
Date: 2026-09-24 | Owner: Maximus | Approved direction: Max ("מערכת פלטפורמה שלמה... עם טוויסט שלנו... fintech ברמה הכי גבוהה")

## What this is
מערכת הניהול של האוטופיילוט — המקבילה שלנו לדשבורד של Native, עם שני הבדלים מהותיים:
1. **הפעולה בטלגרם, התמונה בדשבורד.** אצל Native מאשרים פוסטים בדשבורד. אצלנו האישור נשאר בטלגרם (כפתורים, איפה שהלקוח ממילא חי) — הדשבורד הוא ה-Mission Control: מצב כל המותגים, הצנרת, האנליטיקס והסוכנים במבט אחד.
2. **המנוע הוא סוכני OpenClaw**, לא backend קנייני. הדשבורד קורא state, לא מריץ לוגיקה.

## Components
```
autopilot/
├── brands/<brand>/           # Phase 1-2 outputs (profile, plans)
├── platform/
│   ├── index.html            # Mission Control dashboard (fintech-grade, RTL)
│   ├── data.json             # single source of truth (state)
│   ├── ap.py                 # CLI: state updates (add post, set status, log publish)
│   └── ARCHITECTURE.md       # this file
└── MVP-PLAN.md
```

## data.json schema (v1)
- `brands[]`: id, name, url, lang, status(active/onboarding/paused), pillars[], compliance_notes
- `posts[]`: id, brand, pillar, platform(fb/ig/li), copy_hook, status(draft→pending_approval→approved→scheduled→published→skipped), slot(ISO), approved_via(telegram msg id)
- `agents[]`: id, role, scope, status
- `metrics`: per-brand weekly rollup (reach, saves, clicks, leads) — Phase 5 fills this

State writes go through `ap.py` (same pattern as dashboard/dash.py) — the agent edits state via CLI, the dashboard renders it. No hand-editing of data.json.

## Agent separation plan (Max, 24.09: "סוכנים נפרדים שלא יתערבב")
**Now (build phase):** everything runs under `maximus` — fast iteration, one context.
**After the loop is proven end-to-end (post Phase 4):**
1. `autopilot-core` — orchestrator: onboarding, plan generation, approval loop, scheduling. Own workspace `workspace-autopilot`, own Telegram binding. No access to Otto/trading/Meta-brands workspaces.
2. `autopilot-<client>` — per-client agents via the Otto provisioner (exists), each with isolated workspace + own client Telegram chat. Core agent talks to them via sessions, never shares credentials.
3. `maximus` (me) — stays owner/developer: deploys, reviews, incidents. Not in the serving path.
Provisioning follows the known wiring: workspace + agents.list + telegram account + binding + operator-authorized openclaw.json edit + restart (see memory: new-bot-wiring).

**Isolation rules:**
- Client tokens (Meta/LinkedIn) live in per-client secrets dirs, never in the shared workspace
- Cross-brand data never mixes in one context; the dashboard aggregates from data.json only
- Cron jobs namespaced `autopilot:*` so they're separable from Meta-brand crons

## Design language v2 (Max, 24.09: "בהיר, באנגלית, 3D, fintech הכי גבוה")
Reference class: Mercury / Stripe / Linear — **light theme**. Porcelain canvas (#F5F7FB), white surfaces,
one cobalt accent (#2447F0), Inter UI + Fraunces italic (reserved for the "agency voice" headline) +
JetBrains Mono for data. 3D elements: CSS orb ("the core") with orbit rings, pointer-tilt decision cards,
layered depth shadows. **UI chrome is English-only**; client content (post hooks) renders in its own
language via dir=auto. prefers-reduced-motion respected. Dark v1 kept at index.html.bak.dark-v1.

## Product paradigm (Max, 24.09: "סוכנות שאומרת לך מה לעשות")
This is a **proactive agency, not a task executor**. The system composes the plan and the
recommendations; the owner only decides. UI order encodes it: briefing (agency speaks, first person) →
decision deck ("Your agency recommends", Approve / Not now) → pipeline → agents/metrics.
`recommendations[]` in data.json is the first-class object; agents add via `ap.py rec-add`,
resolve via `ap.py rec <id> <status>`.

## Verification checklist (this build)
- [x] Phase 1+2 re-run on a second brand (cmtm.co.il) — proves onboarding is generic, not HG-specific
- [x] Dashboard renders correctly (playwright screenshot, 0 JS errors — preview.png)
- [x] ap.py add/status/list round-trip works against data.json (24.09)
- [ ] Telegram approval demo message maps to a post id in data.json
