#!/usr/bin/env python3
"""Otto owner console — the whole business in one JSON snapshot, and the owner's controls.

  otto_admin.py snapshot [--json] [--days 30]      # what GET /otto-api/admin/snapshot serves (window: 7 / 30 / 90 days)
  otto_admin.py sample [--embed]                   # synthetic sample snapshot; --embed writes it into admin.html
  otto_admin.py kill on|off [--note "…"]           # global kill switch: no post publishes, no ad launches, live campaigns
                                                   # are paused (off resumes only the ones the switch paused)
  otto_admin.py pause|resume <brand> [--note "…"]  # one brand (publishing + ad launches; pause also pauses its live campaigns)
  otto_admin.py activate <brand> [--note "…"]      # a client outside paid billing (brand-add, comped): onboarding → active
  otto_admin.py campaign <cp-id> approve|reject [--note "…"]
  otto_admin.py rescan <brand>                     # re-read the brand's website in the background (scan.json only)
  otto_admin.py lead <lead-id> new|contacted|won|lost [--note "…"]
  otto_admin.py members <brand> [--add a@x.com,@team.com] [--remove b@x.com]   # who may sign in to the app for this brand
  otto_admin.py plan <brand> <plan-id> [--until YYYY-MM-DD] [--note "…"]      # put a brand on a plans.json plan (--until ""
                                                   # clears the end date; a new plan without --until has none). A plan without
                                                   # paid ads pauses the brand's live campaigns now; "none" pauses publishing
  otto_admin.py plans                              # the plans in plans.json and every brand's plan + usage this month

Sources (all read-only here, except the controls): data.json (ap.load) · landing events ($OTTO_EVENTS, otto_track) ·
billing ($OTTO_BILLING, otto_billing: Stripe + the legacy Whop founders) · lead notes ($OTTO_LEADS, default leads.json next to data.json) · cron logs, publish.log,
api-errors.log and actions.log next to data.json · which otto-secrets files exist (never their contents).

Definitions (the console's footnotes say the same):
  visitors     distinct visitors per day on the landing (the visitor id changes every UTC day), plus anonymous (Do Not Track) views
  scanned      visitors who ran a scan · get started = visitors who clicked a checkout or "Start free 7-day trial" button
  checkouts    customer records created (Stripe Checkout Sessions completed or still unpaid, legacy Whop memberships incl.
               "drafted") · paying = customers who started in the window
  onboarded    paying customers tied to a brand in data.json (linked by hand, or matched by domain)
  lead         a scanned domain (d:<domain>), or a visitor who clicked Get started / reached onboarding without scanning
               (v:<day>:<id>); "paid" when a customer's e-mail domain, website or brand matches the lead's domain
  MRR          EUR (otto_billing.metrics), active + past_due subscriptions: monthly = the amount, yearly = amount / 12; one-time
               founding seats add 0 · churn = cancellations · legacy Whop founders are listed read-only (no Whop sync)
  comms_lang   brands[].comms_lang (otto_i18n): the language of what Otto sends the client (e-mails, the 07:35 report, one-tap
               pages, Telegram cards) — English unless the client or the owner chose Nederlands / Deutsch; shown next to the
               content language (what the posts are written in), which it never changes. The owner sets it with
               {"action": "comms_lang", "brand": …, "lang": "en|nl|de"}.
  approvals    brands[].approvals (otto_email): the channel (Email / Telegram / App only), who approval e-mails go to (masked),
               the last digest / recommendation e-mail, the last send error, bounces the provider reported, and the outbox
               (e-mails written to disk while no mail transport is configured)
  trials       Google sign-ups (users[], otto_auth) and their free trials (otto_trial): trials running with days left, converted
               (a paid plan replaced the trial), expired (ended without a card), no trial (e-mail / domain already trialled);
               conversion = converted ÷ (converted + expired) among trials that finished in the window; trial funnel =
               visitors → scans → sign-ups → trials started → paid, all in the window
  plan         brands[].plan resolved through plans.json (ap.plan_view): label, what is included, and this month's usage
               against the limits — posts + reels planned (not skipped, every format counts), paid budget Otto manages
               (approved / live / paused / ended flights in the month, EUR) against ad_spend_managed_eur_month
Pure functions (build, index_events, …) take the loaded inputs, so the tests and the sample run the exact production code.
Every control writes through ap.transaction() / its own lock and appends "admin <who> <action> …" to actions.log.
"""
import fcntl, json, os, random, re, subprocess, sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_billing
import otto_email
import otto_metrics
import otto_i18n
import otto_paths
import otto_stripe
import otto_track as track
import otto_whop as whop

HERE = Path(__file__).parent
ADMIN_HTML = HERE / "admin.html"
LEAD_ROWS, LEAD_STATUSES = 300, ("new", "contacted", "won", "lost")
WINDOWS = (7, 30, 90)
PUBLIC_BASE = "/".join(otto_paths.BASE.split("/")[:3])           # scheme://host of OTTO_PUBLIC_BASE (otto_paths.BASE)
LANDING_SECTIONS = ["top", "story", "reads", "plans", "asks", "posts", "ads", "campaign", "reports", "agency", "launch", "next-level",
                    "pricing", "faq", "final"]        # landing.html's <section id> / .chapter id, top to bottom (Oct 2026)
SECTION_LABELS = {"top": "Hero and scan", "story": "Automate your marketing", "reads": "Reads", "plans": "Plans",
                  "asks": "You approve (review)", "ads": "Ads Otto makes", "campaign": "A campaign Otto runs",
                  "reports": "Daily 07:35 ads report", "posts": "Posts Otto makes", "agency": "Otto or an agency",
                  "launch": "Launching a business", "next-level": "Next level (before and after)", "pricing": "Offer and price",
                  "faq": "FAQ", "final": "Final call to action",
                  # sections of the September page, still in older events
                  "work": "Pilot work (old page)", "publishes": "Publishes (old page)", "replaces": "What Otto replaces (old page)",
                  "watch": "Films (old page)"}
# job, label, log file (next to data.json; the cron line appends stdout there), expected cadence in minutes
CRON_JOBS = [("publish", "Publisher", "publish.log", 15), ("watch", "Guard and morning report", "watch.log", 60),
             ("telegram", "Approval cards", "telegram.log", 1440), ("visuals", "Visuals", "genvisuals.log", 1440),
             ("reels", "Reels", "reels.log", 1440), ("ads", "Paid launch, guard, report", "ads.log", 1440),
             ("growth", "Growth ledger", "growth.log", 1440), ("competitors", "Competitor sweep", "competitors.log", 10080),
             ("insights", "Insights", "insights.log", 10080), ("plan", "Monthly plan", "plan.log", 44640)]
FREEMAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.de", "yahoo.fr", "yahoo.co.uk", "outlook.com", "outlook.de", "hotmail.com",
            "hotmail.de", "hotmail.fr", "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
            "web.de", "t-online.de", "freenet.de", "proton.me", "protonmail.com", "pm.me", "aol.com", "mail.com", "zoho.com", "yandex.ru",
            "mail.ru", "walla.co.il", "libero.it", "virgilio.it", "orange.fr", "free.fr", "laposte.net", "wanadoo.fr", "sfr.fr",
            "bluewin.ch", "seznam.cz", "wp.pl", "o2.pl", "onet.pl", "interia.pl", "hey.com", "fastmail.com", "tutanota.com", "sapo.pt"}
TWO_LEVEL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "co.il", "org.il", "ac.il", "com.au", "net.au", "co.nz", "com.br", "co.za", "co.jp",
             "com.tr", "com.pl", "com.pt", "co.at", "or.at", "com.es", "com.mx", "com.ar", "co.in", "com.cy", "com.gr", "com.ro"}
REF_NAMES = [(r"(^|\.)google\.", "Google"), (r"(^|\.)bing\.com$", "Bing"), (r"duckduckgo\.com$", "DuckDuckGo"),
             (r"(^|\.)facebook\.com$|^fb\.me$", "Facebook"), (r"instagram\.com$", "Instagram"), (r"^t\.co$|twitter\.com$|(^|\.)x\.com$", "X"),
             (r"linkedin\.com$|^lnkd\.in$", "LinkedIn"), (r"youtube\.com$|^youtu\.be$", "YouTube"), (r"whop\.com$", "Whop"),
             (r"reddit\.com$", "Reddit"), (r"chatgpt\.com$|openai\.com$", "ChatGPT"), (r"perplexity\.ai$", "Perplexity"),
             (r"^t\.me$|telegram\.", "Telegram"), (r"^wa\.me$|whatsapp\.", "WhatsApp")]
SPAWN = lambda args, log: subprocess.Popen(args, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           start_new_session=True)


# ============================================================================================
# small helpers
# ============================================================================================

def utcnow():
    return datetime.now(timezone.utc)


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def day_list(end, n):
    """n ISO days ending with `end` (a date), oldest first."""
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def delta(cur, prev):
    return round((cur - prev) / prev * 100, 1) if prev else None


def host_of(u):
    u = str(u or "").strip().lower()
    return track.clean_domain(u) if u else None


def base_domain(host):
    """shop.example.co.uk → example.co.uk; www.a.de → a.de."""
    if not host:
        return None
    parts = host.split(".")
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_LEVEL else 2
    return ".".join(parts[-n:])


def source_label(ref, utm):
    if utm and utm.get("source"):
        return (utm["source"].strip().lower() + (" · " + utm["medium"].strip().lower() if utm.get("medium") else ""))[:48]
    if ref:
        for pat, name in REF_NAMES:
            if re.search(pat, ref):
                return name
        return ref
    return "Direct"


def clean_who(v):
    v = str(v or "").strip()
    return v if re.fullmatch(r"[A-Za-z0-9@._+:-]{1,64}", v) else "admin"


def leads_path():
    return Path(os.environ.get("OTTO_LEADS") or ap.DATA.parent / "leads.json")


def actions_log():
    return ap.DATA.parent / "actions.log"


def log_action(who, text):
    with actions_log().open("a") as f:
        f.write(f"{fmt(utcnow())} admin {clean_who(who)} {text}\n")


def tail_lines(path, n=20, max_bytes=65536):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        f.seek(max(0, size - max_bytes))
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]                                     # first one is cut
    return [l for l in lines if l.strip()][-n:]


def load_leads():
    try:
        x = json.loads(leads_path().read_text()) if leads_path().exists() else {}
    except Exception:
        x = {}
    return x.get("leads", {}) if isinstance(x, dict) else {}


# ============================================================================================
# landing events → per-visitor facts (one pass)
# ============================================================================================

def index_events(events, win_start):
    """vis[(day, v)] = what one visitor did that day; window counters for the traffic section (days >= win_start)."""
    vis, domains = {}, {}
    anon, scans_by_day = Counter(), Counter()
    T = {"sections": defaultdict(set), "scroll": defaultdict(set), "loads": set(), "ctas": Counter(), "faq": Counter(),
         "videos": Counter(), "pages": Counter(), "anon": 0}
    for e in events:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts") if isinstance(e.get("ts"), str) else ""
        day, typ = ts[:10], e.get("e")
        inwin = day >= win_start
        if e.get("anon"):
            if typ == "view":
                anon[day] += 1
                if inwin:
                    T["anon"] += 1
                    T["pages"][e.get("p") or "/"] += 1
            continue
        v = e.get("v")
        if not v or len(day) != 10:
            continue
        key = (day, v)
        info = vis.get(key)
        if info is None:
            info = vis[key] = {"day": day, "v": v, "first": ts, "src": None, "landing": False, "onb": False, "gs": 0, "scan": []}
        if typ == "view":
            if inwin:
                T["pages"][e.get("p") or "/"] += 1
            if "onboarding" in (e.get("p") or ""):
                info["onb"] = True
            else:
                info["landing"] = True
                if inwin and e.get("s"):
                    T["loads"].add(e["s"])
            if info["src"] is None:
                info.update(src=source_label(e.get("r"), e.get("u")), ref=e.get("r"), utm=e.get("u"), dv=e.get("dv"), cc=e.get("cc"))
        elif typ == "scroll":
            if inwin and e.get("s"):
                T["scroll"][e.get("d")].add(e["s"])
        elif typ == "section":
            if inwin:
                T["sections"][e.get("id")].add(key)
        elif typ == "cta":
            cid = e.get("id") or ""
            if inwin:
                T["ctas"][cid] += 1
            if cid.startswith(("get_started", "start_trial")):     # a checkout button, or "Start free 7-day trial"
                info["gs"] += 1
        elif typ in ("scan_start", "scan_result"):
            dom = e.get("domain")
            if not dom:
                continue
            x = domains.get(dom)
            if x is None:
                x = domains[dom] = {"first": ts, "last": ts, "scans": 0, "ok": None, "keys": []}
            x["last"] = max(x["last"], ts)
            if key not in x["keys"]:
                x["keys"].append(key)
            if typ == "scan_start":
                x["scans"] += 1
                scans_by_day[day] += 1
                if dom not in info["scan"]:
                    info["scan"].append(dom)
            else:
                x["ok"] = bool(x["ok"]) or bool(e.get("ok"))
        elif typ == "faq_open":
            if inwin:
                T["faq"][e.get("q")] += 1
        elif typ == "video_play":
            if inwin:
                T["videos"][e.get("id")] += 1
    return vis, domains, anon, scans_by_day, T


# ============================================================================================
# customers ↔ brands ↔ leads
# ============================================================================================

def brand_domains(d):
    return {base_domain(host_of(b.get("url"))): b["id"] for b in d.get("brands", []) if host_of(b.get("url"))}


def customer_domains(c, brands_by_id):
    out = set()
    dom = otto_billing.email_domain(c.get("email"))
    if dom and dom not in FREEMAIL:
        out.add(base_domain(dom))
    if c.get("website"):
        out.add(base_domain(host_of(c["website"])))
    b = brands_by_id.get(c.get("brand_id"))
    if b and host_of(b.get("url")):
        out.add(base_domain(host_of(b["url"])))
    return {x for x in out if x}


def enrich_customers(rows, d):
    """brand_id: linked by hand, else matched by domain (brand_auto=True)."""
    brands_by_id = {b["id"]: b for b in d.get("brands", [])}
    by_dom = brand_domains(d)
    for c in rows:
        if c.get("brand_id") not in brands_by_id:
            if c.get("brand_id"):
                c["brand_missing"] = c["brand_id"]
            c["brand_id"] = next((by_dom[x] for x in customer_domains(c, {}) if x in by_dom), None)
            c["brand_auto"] = bool(c["brand_id"])
        c["domains"] = sorted(customer_domains(c, brands_by_id))
    return rows


def build_leads(vis, domains, customers, overlay, now):
    cust_by_dom = {}
    for c in customers:
        for dom in c.get("domains", []):
            cust_by_dom.setdefault(dom, c)
    rows = []
    for dom, x in domains.items():
        infos = [vis[k] for k in x["keys"] if k in vis]
        first = next((i for i in infos if i.get("src")), infos[0] if infos else {})
        c = cust_by_dom.get(base_domain(dom))
        clicked, onb = any(i["gs"] for i in infos), any(i["onb"] for i in infos)
        rows.append({"id": "d:" + dom, "domain": dom, "first_seen": x["first"], "last_seen": x["last"], "scans": x["scans"],
                     "scan_ok": x["ok"], "clicked": clicked, "source": first.get("src") or "Direct", "device": first.get("dv"),
                     "country": first.get("cc"), "stage": "paid" if c else "onboarding" if onb else "clicked" if clicked else "scanned",
                     "customer_id": c and c["id"], "paid": bool(c)})
    for (day, v), i in vis.items():
        if i["scan"] or not (i["gs"] or i["onb"]):
            continue
        rows.append({"id": f"v:{day}:{v[:8]}", "domain": None, "first_seen": i["first"], "last_seen": i["first"], "scans": 0,
                     "scan_ok": None, "clicked": bool(i["gs"]), "source": i.get("src") or "Direct", "device": i.get("dv"),
                     "country": i.get("cc"), "stage": "onboarding" if i["onb"] else "clicked", "customer_id": None, "paid": False})
    for r in rows:
        ov = overlay.get(r["id"]) or {}
        r["status"] = ov.get("status") or ("won" if r["paid"] else "new")
        r["note"] = ov.get("note") or ""
        r["updated"] = ov.get("updated")
    rows.sort(key=lambda r: r["last_seen"], reverse=True)
    return rows


# ============================================================================================
# brands (clients) health
# ============================================================================================

def _paid_numbers(d, bid, ym):
    """Yesterday and the month so far in the 07:35 report's own numbers (otto_metrics.paid_day: spend, leads = Meta `lead`,
    cost per lead = the lead campaigns' spend / their leads, sales, conversations started). Never raises."""
    try:
        return otto_metrics.console_view(((d.get("ads") or {}).get(bid) or {}).get("daily"), ym)
    except Exception as e:                                   # noqa: BLE001 — one odd entry never takes the console down
        return {"yesterday": None, "month": None, "error": f"{type(e).__name__}: {e}"[:160]}


def _insights_state(d, bid):
    """Is Otto getting the brand's organic numbers? Last account pull, its errors, the baseline window (otto_insights)."""
    m = (d.get("metrics") or {}).get(bid)
    m = m if isinstance(m, dict) else {}
    acct = m.get("account") if isinstance(m.get("account"), dict) else {}
    base = m.get("baseline") if isinstance(m.get("baseline"), dict) else None
    daily = m.get("daily") if isinstance(m.get("daily"), dict) else {}
    return {"pulled_at": acct.get("pulled_at"), "errors": (acct.get("errors") or [])[:4], "last_day": max(daily) if daily else None,
            "followers": {k: (acct.get(k) or {}).get("followers") for k in ("ig", "fb") if acct.get(k)},
            "baseline": {k: base.get(k) for k in ("since", "until", "final", "errors")} if base else None}


def _month_overlap_days(start, end, ym):
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        return 0
    y, m = int(ym[:4]), int(ym[5:7])
    ms = date(y, m, 1)
    me = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    lo, hi = max(s, ms), min(e, me)
    return (hi - lo).days + 1 if hi >= lo else 0


def _compliance(d, bid):
    """Which country / industry baselines check this brand, what they hold, clearances, AI-marked media
    (otto_compliance.summary). A broken rules file shows as an error, never takes the console down."""
    try:
        import otto_compliance
        return otto_compliance.summary(bid, d=d)
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:160]}


def _content_lang(b):
    try:
        return ap.brand_lang(b)
    except Exception:                                        # noqa: BLE001 — a hand-edited lang never takes the console down
        return None


def brand_health(d, sysinfo, customers, now):
    ym = now.strftime("%Y-%m")
    ks = (d.get("controls") or {}).get("publishing_paused")
    secrets_ = sysinfo.get("secrets", {})
    conns = d.get("connections") or []
    out = []
    for b in d.get("brands", []):
        bid = b["id"]
        posts = [p for p in d.get("posts", []) if p.get("brand") == bid]
        month = [p for p in posts if str(p.get("slot") or "").startswith(ym)]
        st = Counter(p.get("status") for p in month)
        pending = [p for p in posts if p.get("status") == "pending_approval"]
        ages = []
        for p in pending:
            t = ap.parse_iso(p.get("tg_sent_at") or p.get("created_at") or p.get("decided_at"))
            if t:
                ages.append((now - (t if t.tzinfo else t.replace(tzinfo=timezone.utc))).total_seconds() / 3600)
        failed = [p for p in posts if p.get("status") == "failed"]
        stuck = [p for p in posts if p.get("status") == "publishing"]
        held_posts = [p for p in posts if p.get("compliance_block") and p.get("status") == "draft"]
        camps = [c for c in d.get("campaigns", []) if c.get("brand") == bid]
        held_camps = [c for c in camps if c.get("compliance_hold")]
        cst = Counter(c.get("status") for c in camps)
        budget = sum((ap.num(c.get("daily_budget")) or 0) * _month_overlap_days(c.get("start"), c.get("end"), ym)
                     for c in camps if c.get("status") in ("approved", "live", "paused", "ended"))
        spend = 0.0
        for dt, entry in ((d.get("ads") or {}).get(bid, {}).get("daily") or {}).items():
            try:
                day = (date.fromisoformat(dt) - timedelta(days=1)).isoformat()
            except ValueError:
                continue
            if day.startswith(ym):
                for net in ("meta", "google"):
                    spend += float(ap.num((((entry or {}).get(net) or {}).get("yesterday") or {}).get("spend")) or 0)
        stamps = []
        for p in posts:
            stamps += [p.get(k) for k in ("decided_at", "published_at", "created_at", "publishing_at")]
        stamps += [t.get("ts") for t in d.get("taste_log", []) if t.get("brand") == bid]
        stamps += [c.get(k) for c in camps for k in ("launched_at", "decided_at", "paused_at")]
        stamps += [r.get("created_at") for r in d.get("recommendations", []) if r.get("brand") == bid]
        stamps = [s for s in stamps if isinstance(s, str) and s[:4].isdigit()]
        name_l = (b.get("name") or "").lower()
        brand_cur = ap.brand_currency(d, bid)
        conn_meta = "connected" if secrets_.get(f"meta-{bid}.json") else next(
            ("connected" for c in conns if c.get("status") == "connected" and (c.get("brand") or "").lower() == name_l
             and "google" not in (c.get("service") or "").lower() and "linkedin" not in (c.get("service") or "").lower()), "missing")
        conn = {"meta": conn_meta, "google": "connected" if secrets_.get(f"google-{bid}.json") else "missing",
                "telegram": "connected" if secrets_.get(f"telegram-{bid}.json") else "owner bot" if secrets_.get("telegram.json") else "missing"}
        issues = []
        if ks:
            issues.append("Kill switch is on: nothing publishes")
        if b.get("paused") or b.get("status") == "paused":
            issues.append("Paused from the console")
        if stuck:
            issues.append(f"{len(stuck)} post{'s' * (len(stuck) != 1)} stuck in publishing (check the page)")
        if failed:
            issues.append(f"{len(failed)} failed post{'s' * (len(failed) != 1)}")
        if held_posts or held_camps:
            issues.append(f"{len(held_posts) + len(held_camps)} compliance hold{'s' * (len(held_posts) + len(held_camps) != 1)}")
        if ages and max(ages) > 48:
            issues.append(f"Approval waiting {int(max(ages) // 24)} days")
        if conn["meta"] != "connected" and (st["approved"] + st["scheduled"]):
            issues.append("Approved posts but no Meta connection")
        if cst.get("failed"):
            issues.append(f"{cst['failed']} campaign launch{'es' * (cst['failed'] != 1)} failed")
        try:
            pv = ap.plan_view(d, bid, today=now.astimezone(ap.brand_tz(b)).date())
        except Exception as e:                               # one hand-edited brand record never takes the console down
            pv = {"id": "?", "label": "Unreadable", "requested": str(b.get("plan")), "source": "error", "until": None,
                  "expired": False, "paid_ads": False, "ended": False, "included": [], "limits": {}, "features": {},
                  "usage": {"posts": {"used": 0, "limit": None}, "reels": {"used": 0, "limit": None}}, "band": None,
                  "overage": None, "not_billed": False, "error": f"{type(e).__name__}: {e}"[:160]}
            issues.append(f"Plan cannot be read: {pv['error']}")
        hist = [h for h in (b.get("plan_history") if isinstance(b.get("plan_history"), list) else []) if isinstance(h, dict)]
        pv.update(changed=hist[-1] if hist else None, history=hist[-5:][::-1])
        uncovered = [c["id"] for c in camps if c.get("status") == "live" and ap.no_ads_why(d, bid, c.get("network"))]
        tr = b.get("trial") if isinstance(b.get("trial"), dict) else {}
        if pv["ended"] and tr and not tr.get("converted_at"):
            issues.append("Free trial ended without a card: publishing and ads are paused" if not tr.get("denied") else
                          f"No free trial ({tr.get('denied')}): waiting for a card")
        elif pv["ended"]:
            issues.append("No active plan: publishing and ad launches are paused (membership ended)")
        elif pv["expired"]:
            issues.append(f"The {pv['requested']} plan ended {pv['until']}: on {pv['label']} now")
        if uncovered:
            issues.append(f"{len(uncovered)} live campaign{'s' * (len(uncovered) != 1)} not covered by the plan "
                          "(the daily guard pauses them)")
        for k, what in (("posts", "posts"), ("reels", "reels")):
            u = pv["usage"][k]
            if u["limit"] is not None and u["used"] > u["limit"]:
                issues.append(f"{u['used']} {what} planned this month, the plan allows {u['limit']:g}")
        ab, band = pv["usage"].get("ad_budget_eur"), pv.get("band") or {}
        if band.get("mode") == "grace":
            issues.append(f"Paid budget above the {pv['label']} band (€{band.get('cap_eur') or 0:,.0f}): first month, planned in full")
        elif band.get("mode") == "capped":
            issues.append(f"Second month above the {pv['label']} band: planned at €{band.get('cap_eur') or 0:,.0f}"
                          + (f", offer {pv['upgrade_label']}" if pv.get("upgrade_label") else ""))
        elif ab and ab["limit"] is not None and ab["used"] > ab["limit"] and not pv.get("overage"):
            issues.append(f"Paid budget this month €{ab['used']:,.0f} is above the plan's €{ab['limit']:,.0f} band")
        if pv.get("overage"):                                # on the approved / live budget of the month
            o = pv["overage"]
            issues.append(f"Overage: {o['pct']:g}% of €{o['excess_eur']:,.0f} above €{o['above_eur']:,.0f} ≈ €{o['fee_eur']:,.0f} "
                          "this month (invoice by hand)")
        elif band.get("mode") == "overage":                   # on the month's plan, before it is approved
            issues.append(f"Overage: {band.get('overage_pct') or 0:g}% of the planned spend above "
                          f"€{band.get('overage_above_eur') or band.get('cap_eur') or 0:,.0f} ≈ €{band.get('overage_eur') or 0:,.0f} "
                          "this month (invoice by hand)")
        if pv.get("not_billed") and not pv["ended"]:
            issues.append(f"Not billed yet: on {pv['label']} without a subscription")
        pv["uncovered_live"] = uncovered
        eh = sysinfo.get("email") if isinstance(sysinfo.get("email"), dict) else {}
        try:
            appr = otto_email.brand_health(b, eh)
        except Exception as e:                               # a hand-edited approvals / members field never takes the console down
            appr = {"channels": [], "label": "Unreadable", "set": True, "recipients": 0, "to": [], "bounces": [],
                    "error": {"why": f"{type(e).__name__}: {e}"[:160]}}
        if "email" in appr["channels"]:
            if not appr["recipients"]:
                issues.append("Approvals by e-mail, but nobody to send to (no member e-mail; @domain entries cannot be mailed)")
            if eh.get("transport") == "outbox":
                issues.append("Approval e-mails wait in the outbox: no mail transport yet (otto-secrets/email.json)")
            elif eh.get("transport") == "error":
                issues.append(f"E-mail settings cannot be used: {str(eh.get('config_error') or '')[:120]}")
            if (appr.get("error") or {}).get("why"):
                issues.append(f"Last approval e-mail failed: {appr['error']['why'][:140]}")
            if appr.get("bounces"):
                n_b = len(appr["bounces"])
                issues.append(f"{n_b} approval address{'es' * (n_b != 1)} bounced ({', '.join(x['to'] for x in appr['bounces'][:2])})")
        paused = b.get("paused") if isinstance(b.get("paused"), dict) else ({"at": None} if b.get("status") == "paused" else None)
        health = "blocked" if (ks or paused or stuck or pv["ended"]) else "attention" if issues else "ok"
        cust = [c for c in customers if c.get("brand_id") == bid]
        upcoming = sorted([p for p in posts if p.get("status") in ("pending_approval", "approved", "scheduled", "draft", "failed", "publishing")],
                          key=lambda p: str(p.get("slot") or ""))[:8]
        out.append({
            "id": bid, "name": b.get("name") or bid, "url": b.get("url"), "status": b.get("status"), "paused": paused,
            "members": [str(m) for m in b.get("members") or []],
            "health": health, "issues": issues, "currency": brand_cur,
            "posts": {"planned": sum(v for k, v in st.items() if k != "skipped"), "draft": st["draft"], "pending": st["pending_approval"],
                      "approved": st["approved"] + st["scheduled"], "published": st["published"], "failed": st["failed"] + st["publishing"],
                      "skipped": st["skipped"]},
            "pending_total": len(pending), "pending_oldest_h": round(max(ages), 1) if ages else None,
            "compliance_holds": len(held_posts) + len(held_camps),
            "campaigns": {"total": len(camps), "live": cst["live"], "approved": cst["approved"], "draft": cst["draft"],
                          "failed": cst["failed"], "budget_month": round(budget, 2), "spend_month": round(spend, 2)},
            "paid": _paid_numbers(d, bid, ym), "insights": _insights_state(d, bid),
            "campaign_list": [dict({k: c.get(k) for k in ("id", "name", "network", "status", "start", "end", "daily_budget",
                                                           "objective", "compliance_hold", "error")},
                                   currency=ap.currency_code(c.get("currency_code") or c.get("currency")) or brand_cur)
                              for c in camps][-12:],
            "upcoming": [{"id": p["id"], "hook": (p.get("hook_en") or p.get("hook") or "")[:120], "status": p.get("status"),
                          "slot": p.get("slot"), "platform": p.get("platform"), "format": p.get("format") or "post",
                          "error": (p.get("error") or "")[:160] or None} for p in upcoming],
            "last_activity": max(stamps) if stamps else None, "connections": conn,
            "customers": [c["id"] for c in cust], "last_scan": (sysinfo.get("scans") or {}).get(bid),
            "rescan": b.get("rescan"), "plan": pv, "approvals": appr, "compliance": _compliance(d, bid),
            "comms_lang": {"value": otto_i18n.lang_of(b), "label": otto_i18n.COMMS_LANGS[otto_i18n.lang_of(b)],
                           "set": isinstance(b.get("comms_lang"), str) and bool(b.get("comms_lang")),
                           "changed": b.get("comms_lang_set"), "content_lang": _content_lang(b)},
        })
    order = {"blocked": 0, "attention": 1, "ok": 2}
    return sorted(out, key=lambda x: (order[x["health"]], x["name"].lower()))


# ============================================================================================
# system health
# ============================================================================================

def heartbeat_rows(now):
    """Engine heartbeats (systemd timers → otto_cron.py → heartbeats.json next to data.json), one row per job in
    cron_rows' shape (+ schedule, failed_brands, fails_in_row). [] until the file exists — the old box keeps log mtimes."""
    try:
        import otto_cron
        return otto_cron.heartbeat_rows(now)
    except Exception:
        return []


def cron_rows(sysinfo, now):
    hb = heartbeat_rows(now)
    if hb:
        return hb
    out = []
    for key, label, log, every in CRON_JOBS:
        info = (sysinfo.get("logs") or {}).get(log) or {}
        last = ap.parse_iso(info.get("mtime"))
        age = round((now - last).total_seconds() / 60) if last else None
        if age is None:
            st = "never"
        elif age <= every * 1.5 + 10:
            st = "ok"
        elif age <= every * 3 + 30:
            st = "late"
        else:
            st = "stale"
        out.append({"job": key, "label": label, "log": log, "every_min": every, "last_run": info.get("mtime"), "age_min": age,
                    "status": st, "last_line": (info.get("last") or "")[:200] or None})
    return out


def system_health(d, sysinfo, now):
    posts = d.get("posts", [])
    failed = [{"id": p["id"], "brand": p.get("brand"), "hook": (p.get("hook") or "")[:90], "error": (p.get("error") or "")[:200],
               "slot": p.get("slot")} for p in posts if p.get("status") == "failed"]
    stuck = [{"id": p["id"], "brand": p.get("brand"), "hook": (p.get("hook") or "")[:90], "since": p.get("publishing_at")}
             for p in posts if p.get("status") == "publishing"]
    pub_err = [l for l in sysinfo.get("publish_tail", []) if re.search(r"\b(FAIL|UNCONFIRMED|MISSED|ERROR|HELD)\b", l)][-12:]
    ks = (d.get("controls") or {}).get("publishing_paused")
    gen = ap.parse_iso(d.get("generated"))
    return {"kill_switch": ks or None, "last_resume": (d.get("controls") or {}).get("last_resumed"),
            "crons": cron_rows(sysinfo, now), "publisher": {"failed": failed[-20:], "stuck": stuck, "recent": pub_err},
            "api_errors": sysinfo.get("api_errors", [])[-15:], "actions": sysinfo.get("actions", [])[-40:],
            "data_age_min": round((now - gen).total_seconds() / 60) if gen and gen.tzinfo else None,
            "events_file": sysinfo.get("events_file")}


def recs_queue(d, now):
    pr = {"P0": 0, "P1": 1, "P2": 2}
    rows = []
    for r in d.get("recommendations", []):
        if r.get("status") != "proposed":
            continue
        t = ap.parse_iso(r.get("created_at"))
        rows.append({"id": r["id"], "priority": r.get("priority"), "title": r.get("title"), "brand": r.get("brand"),
                     "source": r.get("source"), "created_at": r.get("created_at"),
                     "age_h": round((now - t).total_seconds() / 3600, 1) if t and t.tzinfo else None})
    rows.sort(key=lambda r: (pr.get(r["priority"], 3), r.get("created_at") or ""))
    return {"counts": dict(Counter(r["priority"] for r in rows)), "items": rows[:40], "total": len(rows)}


def _email_setup(eh, brands):
    tr = eh.get("transport")
    n = sum(1 for b in brands if "email" in otto_email.approval_channels(b))
    ob = eh.get("outbox") or {}
    return {"key": "email", "label": "Approval e-mails",
            "status": "connected" if tr in ("smtp", "postmark", "resend") else "missing" if tr == "error" or (tr == "outbox" and n)
            else "waiting" if tr == "outbox" else "optional",
            "detail": ((f"Sending by {tr}" if tr in ("smtp", "postmark", "resend") else
                        f"Cannot be used: {str(eh.get('config_error') or '')[:160]}" if tr == "error" else
                        f"No mail transport: e-mails are written to the outbox ({ob.get('files') or 0} waiting)" if tr == "outbox" else
                        "Not checked") + f" · {n} brand{'s' * (n != 1)} approve by e-mail"
                       + (" · link secret generated on the server (set link_secret in email.json)" if eh.get("link_secret") == "generated" else "")),
            "at": ob.get("latest"),
            "how": "otto-secrets/email.json: {\"link_secret\": <64 hex>, \"from\": \"Otto <approvals@your-domain>\", and either SMTP "
                   "(\"host\", \"port\": 587, \"user\", \"pass\"; STARTTLS required) or \"provider\": \"postmark\" | \"resend\" with "
                   "\"api_key\"}. Turn open and click tracking off at the provider. Test: otto_email.py send-cards --brand <id> --dry."}


def whop_webhook_url():
    """Where Whop must send its webhook: https://<apex>/hooks/whop — Caddy's only Whop route (infra/Caddyfile; /otto-api/* is
    404 on the apex). The apex is OTTO_DOMAIN, else the host of OTTO_PUBLIC_BASE."""
    dom = (os.environ.get("OTTO_DOMAIN") or "").strip().strip("/")
    return f"https://{dom}/hooks/whop" if dom else f"{PUBLIC_BASE}/hooks/whop"


def stripe_webhook_url():
    """Where Stripe must send its events: https://<apex>/hooks/stripe (infra/Caddyfile; public, POST only)."""
    dom = (os.environ.get("OTTO_DOMAIN") or "").strip().strip("/")
    return f"https://{dom}/hooks/stripe" if dom else f"{PUBLIC_BASE}/hooks/stripe"


def _billing_setup(billing_meta, plans_cfg, legacy_n):
    """The Stripe rows of Setup (keys, webhook, prices, Stripe Tax, branding, the optional portal) and the legacy Whop row.
    billing_meta = {"stripe": otto_stripe.status(), "whop": otto_whop.status()} (a flat dict = the old Whop-only shape)."""
    sm = billing_meta.get("stripe") if isinstance(billing_meta.get("stripe"), dict) else {}
    wm = billing_meta.get("whop") if isinstance(billing_meta.get("whop"), dict) else \
        ({} if "stripe" in billing_meta else billing_meta)
    chk = sm.get("check") if isinstance(sm.get("check"), dict) else {}
    sellable = [pid for pid in (plans_cfg.get("order") or []) if pid in plans_cfg["plans"] and plans_cfg["plans"][pid].get("public")
                and plans_cfg["plans"][pid].get("monthly_eur") is not None]
    priced = {pid: [k for k in ("monthly", "yearly") if (plans_cfg["plans"][pid].get("stripe_price_ids") or {}).get(k)] for pid in sellable}
    wanted = {pid: ["monthly"] + (["yearly"] if plans_cfg["plans"][pid].get("yearly_eur") is not None else []) for pid in sellable}
    full = [pid for pid, ks in priced.items() if all(k in ks for k in wanted[pid])]       # Starter: monthly only (no yearly_eur)
    none = [pid for pid, ks in priced.items() if not ks]
    bad_prices = {k: v for k, v in (chk.get("prices") or {}).items() if v != "ok"}
    found = (plans_cfg["plans"].get("founding") or {}).get("stripe_price_ids") or {}
    checked = f" · checked {chk['at'][:16].replace('T', ' ')}" if chk.get("at") else " · not checked yet (Controls → Check Stripe setup)"
    events = ", ".join(otto_stripe.EVENTS)
    return [
        {"key": "stripe_keys", "label": "Stripe keys", "status": "connected" if sm.get("ready") else "missing",
         "detail": ((f"{'Live' if sm.get('mode') == 'live' else 'Test'} mode · {sm.get('checkout_ui') or 'embedded'} checkout on the "
                     "Billing page") if sm.get("ready") else
                    "Not set up: every billing screen says “Payments aren't set up yet”" + (" (publishable key missing)" if sm.get("secret_key") else "")),
         "how": "Stripe dashboard (account in EUR) → Developers → API keys: a restricted key (or the secret key) and the publishable "
                "key into otto-secrets/stripe.json {\"secret_key\", \"publishable_key\"} (chmod 600), then systemctl restart otto-api. "
                "Test-mode keys (sk_test_ / pk_test_) first. docs/BILLING.md has every step."},
        {"key": "stripe_webhook", "label": "Stripe webhook", "status": "connected" if sm.get("last_webhook_at") else
            "waiting" if sm.get("webhook_secret") else "missing",
         "detail": ("Receiving events" if sm.get("last_webhook_at") else "Secret is configured; no event received yet"
                    if sm.get("webhook_secret") else "Not connected yet: subscriptions would never switch a plan on"),
         "at": sm.get("last_webhook_at"),
         "how": f"Stripe dashboard → Developers → Webhooks → Add endpoint. URL: {stripe_webhook_url()} · events: {events} · copy "
                "its signing secret (whsec_…) into otto-secrets/stripe.json \"webhook_secrets\": [\"whsec_…\"] (keep the old one in the "
                "list while you roll a secret)."},
        {"key": "stripe_prices", "label": "Stripe prices (plans.json)",
         "status": "missing" if not full and sellable else "partial" if none or len(full) < len(sellable) or bad_prices else "connected",
         "detail": (f"On sale: {', '.join(full) or 'none'}" + (f" · not on sale yet: {', '.join(none)}" if none else "")
                    + (f" · founding seat: {'on' if found.get('one_time') else 'off'}")
                    + (f" · problems: {'; '.join(f'{k} {v}' for k, v in list(bad_prices.items())[:3])}" if bad_prices else "") + checked),
         "how": "Stripe → Product catalog: one product per plan (Starter, Growth, Scale, Agency), each with a monthly EUR price (and a "
                "yearly one where plans.json has yearly_eur; Starter is a monthly subscription only), tax behaviour exclusive. Put "
                "the price ids (price_…) into plans.json stripe_price_ids {monthly, yearly}; "
                "founding.stripe_price_ids.one_time switches the €197 seat on (off while null)."},
        {"key": "stripe_tax", "label": "Stripe Tax (EU VAT, reverse charge)",
         "status": "connected" if chk.get("tax") == "active" else "missing" if chk.get("at") else "waiting",
         "detail": ("Active" if chk.get("tax") == "active" else f"Status: {chk.get('tax') or 'unknown'}" if chk.get("at")
                    else "Not checked yet") + checked,
         "how": "Stripe → Settings → Tax: head office address, preset product tax code “Software as a service (SaaS) – business use”, "
                "prices exclusive of tax, a registration for the Netherlands (and OSS if ever needed). Checkout collects the VAT ID; "
                "a valid EU VAT ID outside the Netherlands gets the reverse charge automatically."},
        {"key": "stripe_branding", "label": "Invoices and receipts look like Otto",
         "status": "connected" if chk.get("branding") else "waiting",
         "detail": ("Branding set" if chk.get("branding") else "Icon / logo or colours not set in Stripe") + checked,
         "how": "Stripe → Settings → Business → Branding: Otto icon and logo, brand colour #2447F0, accent #10182B; public business name "
                "“Otto”; Settings → Customer emails: successful payments + refunds on; optional custom domain for invoice links "
                "(Settings → Custom domains, e.g. pay.<domain>)."},
        {"key": "stripe_portal", "label": "Stripe Customer Portal (fallback)", "status": "connected" if sm.get("portal_fallback") else "optional",
         "detail": "On: the Billing page also offers Stripe's portal" if sm.get("portal_fallback") else
                   "Off: clients manage plan, card, VAT ID and invoices on Otto's own Billing page",
         "how": "Only if wanted: Stripe → Settings → Billing → Customer portal (cancel at period end, switch plans, invoices), then "
                "\"portal_fallback\": true in stripe.json."},
        {"key": "whop_legacy", "label": "Legacy Whop founders", "status": "optional",
         "detail": f"{legacy_n} founding seat{'s' * (legacy_n != 1)} bought on Whop · " + (
             "webhook receiving events" if wm.get("last_webhook_at") else "webhook secret set" if wm.get("webhook_secret") else "no webhook")
             + " · no new Whop checkout is offered anywhere",
         "at": wm.get("last_webhook_at"),
         "how": f"Read-only. Whop keeps reporting refunds / disputes of those seats to {whop_webhook_url()} "
                "(otto-secrets/whop.json \"otto_webhook_secret\"); python3 otto_whop.py backfill re-reads them with the API key."},
    ]


def _google_setup():
    try:
        import otto_auth
        ok = otto_auth.configured()
    except Exception:                                        # noqa: BLE001 — setup info only
        ok = False
    dom = (os.environ.get("OTTO_DOMAIN") or "").strip() or "<your domain>"
    return {"key": "google_signin", "label": "Google sign-in (client app)", "status": "connected" if ok else "missing",
            "detail": "Clients sign in with Google on app. and start a free trial" if ok else
                      "Not set up: the app's sign-in answers “Google sign-in isn't set up yet” and hides the button",
            "how": "Google Cloud console → APIs & Services → OAuth consent screen (External, scopes openid email profile) → "
                   f"Credentials → OAuth client ID (Web application), redirect URI https://app.{dom}/auth/google/callback. Put "
                   "{\"client_id\", \"client_secret\"} into /etc/otto/secrets/google-oauth.json (chmod 600), then "
                   "systemctl restart otto-api. docs/AUTH-AND-TRIAL.md has every step."}


def _copy_setup():
    """The AI copywriter (otto_copy): key, model, today's calls / tokens / estimated spend against its caps."""
    try:
        import otto_copy
        return otto_copy.console_row()
    except Exception as e:                                   # noqa: BLE001 — setup info only
        return {"key": "copywriter", "label": "AI copywriter (Claude API)", "status": "missing",
                "detail": f"Cannot be checked: {type(e).__name__}", "how": "platform/otto_copy.py docstring."}


def setup_items(d, sysinfo, billing_meta, events_meta):
    s = sysinfo.get("secrets", {})
    plans_cfg = ap.plans_config()
    public = [pid for pid in plans_cfg["order"] if plans_cfg["plans"][pid].get("public")]
    drafts = [pid for pid in public if plans_cfg["plans"][pid].get("status") == "draft"]
    unsold = [pid for pid in public if not any((plans_cfg["plans"][pid].get("stripe_price_ids") or {}).values())
              and not plans_cfg["plans"][pid]["whop_plan_ids"]]
    legacy_n = int(sysinfo.get("legacy_whop") or 0)
    brands = d.get("brands", [])
    unowned = [b["id"] for b in brands if not b.get("members")]
    cap_mb = float(os.environ.get("OTTO_EVENTS_MAX_MB") or 512)
    full = (events_meta.get("size_mb") or 0) >= cap_mb * 0.9            # otto_track stops writing at the cap
    meta_n = sum(1 for b in brands if s.get(f"meta-{b['id']}.json"))
    google_n = sum(1 for b in brands if s.get(f"google-{b['id']}.json"))
    items = [
        *_billing_setup(billing_meta, plans_cfg, legacy_n),
        {"key": "analytics", "label": "Landing analytics",
         "status": "missing" if full else "connected" if events_meta.get("last") else "waiting",
         "detail": (f"Events file is {events_meta.get('size_mb')} MB of {cap_mb:.0f} MB: new events are refused past it. "
                    "Run python3 otto_track.py prune --days 400" if full else
                    "Receiving events" if events_meta.get("last") else "No events received yet"), "at": events_meta.get("last"),
         "how": "Caddy sends /otto-track (apex and app.) to the API (infra/Caddyfile); the rate limit is a Cloudflare WAF rule "
                "(infra/README.md) plus the API's own. The beacon is already in the landing."},
        {"key": "country", "label": "Visitor country (optional)", "status": "connected" if events_meta.get("country") else "optional",
         "detail": "Countries are recorded" if events_meta.get("country") else "Cloudflare does not send a country header yet",
         "how": "Cloudflare dashboard → the zone → Network → IP Geolocation: on. Cloudflare then adds CF-IPCountry, which Caddy "
                "passes to the API unchanged; otto_track keeps only the two-letter code."},
        {"key": "meta", "label": "Meta (Facebook + Instagram)", "status": "connected" if brands and meta_n == len(brands) else
            "partial" if meta_n else "missing", "detail": f"{meta_n} of {len(brands)} brands connected",
         "how": "otto-secrets/meta-<brand>.json per brand (page token, page_id, ig_user_id, ad_account_id). See crons.md."},
        {"key": "google", "label": "Google Ads", "status": "connected" if brands and google_n == len(brands) else
            "partial" if google_n else "missing", "detail": f"{google_n} of {len(brands)} brands connected",
         "how": "otto-secrets/google-<brand>.json per brand (client_id, client_secret, refresh_token, developer_token, customer_id)."},
        {"key": "telegram", "label": "Telegram bot", "status": "connected" if s.get("telegram.json") else "missing",
         "detail": "Owner bot configured" if s.get("telegram.json") else "No bot token yet",
         "how": "/etc/otto/secrets/telegram.json {bot_token, owner_chat_id}; systemctl enable --now otto-telegram."},
        _email_setup(sysinfo.get("email") if isinstance(sysinfo.get("email"), dict) else {}, brands),
        _google_setup(),
        _copy_setup(),
        {"key": "admin_auth", "label": "Console access", "status": "connected" if sysinfo.get("admin_users") else "missing",
         "detail": "Limited to named users" if sysinfo.get("admin_users") else "OTTO_ADMIN_USERS is not set: the console refuses "
                                                                                "every request that comes through Caddy",
         "how": "admin.<domain> sits behind Cloudflare Access (the Otto team's e-mails, one-time PIN). Put the same lower-case "
                "e-mails in OTTO_ADMIN_USERS in /etc/otto/otto.env and systemctl restart otto-api. Caddy passes Access's verified "
                "e-mail as X-Otto-User (admin. only, with OTTO_PROXY_KEY); a Google sign-in on app. never opens the console."},
        {"key": "tenants", "label": "Client logins",
         "status": "optional" if sysinfo.get("single_tenant") else "missing" if unowned else "connected",
         "detail": ("Single login (OTTO_SINGLE_TENANT=1): everyone signed in sees every brand" if sysinfo.get("single_tenant") else
                    f"{len(unowned)} brand{'s' * (len(unowned) != 1)} with no client login yet: " + ", ".join(unowned[:6]) if unowned
                    else "Every brand has at least one client login"),
         "how": "A client signs in with Google on app. and sees only brands whose members list has that e-mail (a new sign-up "
                "becomes the member of the brand it creates; \"@company.com\" counts only for that company's Google Workspace "
                "accounts). A paid checkout adds the payer to the brand it was bought for; Clients → open the brand → Who can sign in (or "
                "otto_admin.py members <brand> --add a@x.com,@company.com) adds anyone else."},
        {"key": "plans", "label": "Plans (plans.json)", "status": "missing" if plans_cfg.get("error") else
            "waiting" if unsold or drafts else "connected",
         "detail": (f"Cannot be used: {plans_cfg['error'][:200]}" if plans_cfg.get("error") else
                    f"{len(plans_cfg['plans'])} plans" + (f" · draft prices: {', '.join(drafts)}" if drafts else "")
                    + (f" · not on sale yet: {', '.join(unsold)}" if unsold else "")),
         "how": "platform/plans.json: features, limits, prices and stripe_price_ids per plan (no code change, re-read on save). "
                "Add each Stripe price id to its plan's stripe_price_ids once the prices exist in Stripe (docs/BILLING.md)."},
        {"key": "secrets_mode", "label": "Secret files locked", "status": "missing" if sysinfo.get("secrets_open") else "connected",
         "detail": ("Readable by other users: " + ", ".join(sysinfo.get("secrets_open")[:6])) if sysinfo.get("secrets_open")
                   else "Only the service user can read otto-secrets",
         "how": "chmod 600 otto-secrets/*.json (and chmod 700 the directory), owned by the user otto-api runs as."},
    ]
    return items


# ============================================================================================
# the snapshot
# ============================================================================================

def _records(xs, need=("id",)):
    """Only well-formed records: dicts whose `need` fields are non-empty strings (one hand-edited or half-written entry
    in data.json must not take the whole console down with a KeyError)."""
    return [x for x in (xs if isinstance(xs, list) else []) if isinstance(x, dict)
            and all(isinstance(x.get(k), str) and x.get(k) for k in need)]


def clean_state(d):
    """A shallow copy of data.json with the lists the console reads filtered to well-formed records."""
    d = dict(d if isinstance(d, dict) else {})
    d["brands"] = _records(d.get("brands"))
    d["posts"] = _records(d.get("posts"))
    d["recommendations"] = _records(d.get("recommendations"))
    d["campaigns"] = _records(d.get("campaigns"))
    d["connections"] = _records(d.get("connections"), ())
    d["taste_log"] = _records(d.get("taste_log"), ())
    d["users"] = _records(d.get("users"))
    for k in ("controls", "ads"):
        if not isinstance(d.get(k), dict):
            d.pop(k, None)
    return d


def build(d, events, billing, overlay, sysinfo, now=None, window=30, sample=False):
    """Pure: everything the console shows, from already-loaded inputs."""
    d = clean_state(d)
    billing = dict(otto_billing.empty(), **(billing if isinstance(billing, dict) else {}))
    for k in ("customers", "payments", "plans"):
        billing[k] = {i: v for i, v in (billing[k] if isinstance(billing[k], dict) else {}).items()
                      if isinstance(v, dict) and (k == "plans" or isinstance(v.get("id"), str))}
    overlay = overlay if isinstance(overlay, dict) else {}
    now = now or utcnow()
    window = window if window in WINDOWS else 30
    today = now.date()
    span = max(90, 2 * window)
    days = day_list(today, span)
    win_days, prev_days = days[-window:], days[-2 * window:-window]
    win_start = win_days[0]
    vis, domains, anon, scans_by_day, T = index_events(events, win_start)

    cfg_plans = sysinfo.get("plans")
    customers = enrich_customers(otto_billing.customer_rows(billing, cfg_plans or dict(whop.PLANS)), d)
    brand_ids = {b["id"] for b in d.get("brands", [])}
    leads = build_leads(vis, domains, customers, overlay, now)

    # ---- per-day series ----
    per = {k: Counter() for k in ("visitors", "scanned", "get_started", "checkouts", "paying", "onboarded", "leads", "churn")}
    for (day, v), i in vis.items():
        if i["landing"]:
            per["visitors"][day] += 1
        if i["scan"]:
            per["scanned"][day] += 1
        if i["gs"]:
            per["get_started"][day] += 1
    for day, n in anon.items():
        per["visitors"][day] += n
    for c in billing.get("customers", {}).values():
        s = (c.get("started") or c.get("first_seen") or "")[:10]
        if s:
            per["checkouts"][s] += 1
    for c in customers:
        s = (c.get("started") or "")[:10]
        if s:
            per["paying"][s] += 1
            if c.get("brand_id") in brand_ids:
                per["onboarded"][s] += 1
        if c.get("canceled_at"):
            per["churn"][c["canceled_at"][:10]] += 1
    for r in leads:
        per["leads"][r["first_seen"][:10]] += 1

    def total(key, dl):
        return sum(per[key][x] for x in dl)

    def level(day):                                          # customers + MRR standing at the end of `day`
        n = mrr = 0
        for c in customers:
            s, e = (c.get("started") or "")[:10], (c.get("canceled_at") or "")[:10]
            if s and s <= day and not (e and e <= day) and c.get("status") != "trialing":
                n += 1
                mrr += c.get("mrr_eur") or 0
        return n, round(mrr, 2)

    levels = {x: level(x) for x in win_days}
    before = level(prev_days[-1]) if prev_days else (0, 0)
    kpis = {}
    for key, label in (("visitors", "Visitors"), ("scans", "Scans"), ("leads", "Leads"), ("churn", "Churned")):
        src = scans_by_day if key == "scans" else per[key]
        cur, prev = sum(src[x] for x in win_days), sum(src[x] for x in prev_days)
        kpis[key] = {"label": label, "value": cur, "prev": prev, "delta_pct": delta(cur, prev), "series": [src[x] for x in win_days],
                     "better": "down" if key == "churn" else "up"}
    kpis["customers"] = {"label": "Paying customers", "value": levels[win_days[-1]][0], "prev": before[0],
                         "delta_pct": delta(levels[win_days[-1]][0], before[0]), "series": [levels[x][0] for x in win_days], "better": "up"}
    mrr_now = round(sum(c["mrr_eur"] for c in customers if c.get("status") in ("active", "past_due")), 2)
    kpis["mrr"] = {"label": "MRR", "value": mrr_now, "prev": before[1], "delta_pct": delta(mrr_now, before[1]),
                   "series": [levels[x][1] for x in win_days], "better": "up", "unit": "EUR"}

    # ---- funnel ----
    steps = [("visitors", "Visitors"), ("scanned", "Scanned a site"), ("get_started", "Clicked Get started / Start trial"),
             ("checkouts", "Checkouts"), ("paying", "Paying"), ("onboarded", "Onboarded brands")]
    fsteps, prev_n, top = [], None, None
    for key, label in steps:
        n = total(key, win_days)
        top = n if top is None else top
        fsteps.append({"key": key, "label": label, "n": n, "prev_n": total(key, prev_days),
                       "step_rate": pct(n, prev_n) if prev_n is not None else None, "overall_rate": pct(n, top)})
        prev_n = n
    by_day = [dict({"date": x}, **{k: per[k][x] for k, _ in steps}) for x in days[-90:]]
    weeks = defaultdict(lambda: Counter())
    for row in by_day:
        y, w, _ = date.fromisoformat(row["date"]).isocalendar()
        wk = weeks[f"{y}-W{w:02d}"]
        for k, _ in steps:
            wk[k] += row[k]
    by_week = []
    for wk, c in sorted(weeks.items())[-13:]:
        start = date.fromisocalendar(int(wk[:4]), int(wk[6:]), 1).isoformat()
        by_week.append(dict({"week": wk, "start": start}, **{k: c[k] for k, _ in steps}))

    # ---- traffic (window) ----
    win_vis = [i for (day, v), i in vis.items() if day >= win_start and i["landing"]]
    nv = len(win_vis) + T["anon"]
    src = defaultdict(lambda: {"visitors": 0, "scanned": 0, "get_started": 0})
    camp, devices, countries = Counter(), Counter(), Counter()
    for i in win_vis:
        s = src[i.get("src") or "Direct"]
        s["visitors"] += 1
        s["scanned"] += bool(i["scan"])
        s["get_started"] += bool(i["gs"])
        u = i.get("utm") or {}
        if u:
            camp[(u.get("campaign") or "—", u.get("source") or "—", u.get("medium") or "—")] += 1
        devices[i.get("dv") or "unknown"] += 1
        countries[i.get("cc") or "unknown"] += 1
    if T["anon"]:
        src["Anonymous (Do Not Track)"]["visitors"] += T["anon"]
    sources = sorted(({"source": k, **v, "share": pct(v["visitors"], nv)} for k, v in src.items()), key=lambda r: -r["visitors"])[:15]
    sec_ids = [s for s in LANDING_SECTIONS if s in T["sections"]] + sorted(s for s in T["sections"] if s not in LANDING_SECTIONS)
    landing_vis = max(1, len(win_vis))
    loads = max(1, len(T["loads"]))
    traffic = {
        "visitors": nv, "anonymous": T["anon"], "page_loads": len(T["loads"]),
        "sources": sources,
        "campaigns": [{"campaign": c, "source": s, "medium": m, "visitors": n} for (c, s, m), n in camp.most_common(12)],
        "devices": [{"device": k, "visitors": n, "share": pct(n, len(win_vis))} for k, n in devices.most_common()],
        "countries": [{"country": k, "visitors": n, "share": pct(n, len(win_vis))} for k, n in countries.most_common(12)],
        "sections": [{"id": s, "label": SECTION_LABELS.get(s, s), "visitors": len(T["sections"][s]),
                      "share": pct(len(T["sections"][s]), landing_vis)} for s in sec_ids],
        "scroll": [{"depth": m, "loads": len(T["scroll"].get(m, ())), "share": pct(len(T["scroll"].get(m, ())), loads)} for m in (25, 50, 75, 100)],
        "ctas": [{"id": k, "clicks": n} for k, n in T["ctas"].most_common(15)],
        "faq": [{"q": k, "opens": n} for k, n in T["faq"].most_common(12)],
        "videos": [{"id": k, "plays": n} for k, n in T["videos"].most_common(6)],
        "pages": [{"path": k, "views": n} for k, n in T["pages"].most_common(8)],
        "pricing_views": len(T["sections"].get("pricing", ())),
    }

    # ---- leads ----
    lead_rows = leads[:LEAD_ROWS]
    in_win = [r for r in leads if r["first_seen"][:10] >= win_start]
    leads_out = {"rows": lead_rows, "total": len(leads), "shown": len(lead_rows), "new_in_window": len(in_win),
                 "by_stage": dict(Counter(r["stage"] for r in in_win)), "by_status": dict(Counter(r["status"] for r in leads))}

    # ---- customers + revenue (otto_billing: every provider; Whop founders are legacy and read-only) ----
    pays = sorted(billing.get("payments", {}).values(), key=lambda p: p.get("at") or "", reverse=True)
    cut30 = fmt(now - timedelta(days=30))
    m = otto_billing.metrics(customers, pays, now)
    cust_rows = []
    for c in customers:
        pend = c.get("pending") if isinstance(c.get("pending"), dict) else None
        cust_rows.append({"id": c["id"], "provider": c.get("provider"), "email": otto_billing.mask_email(c.get("email")),
                          "plan": c.get("plan"), "plan_type": c.get("plan_type"), "interval": c.get("interval"),
                          "status": c.get("status"), "cancel_at_period_end": bool(c.get("cancel_at_period_end")),
                          "started": c.get("started"), "renews": c.get("renews"), "canceled_at": c.get("canceled_at"),
                          "trial_end": c.get("trial_end"), "pending": {"plan": pend.get("plan"), "at": pend.get("at")} if pend else None,
                          "mrr_eur": c.get("mrr_eur"), "mrr_estimated": c.get("mrr_estimated"), "ltv_eur": c.get("ltv_eur"),
                          "failed_payments": c.get("failed_payments"), "brand_id": c.get("brand_id"), "brand_auto": c.get("brand_auto"),
                          "linked_by": (c.get("brand_link") or {}).get("by"), "linkable": c.get("provider") == "stripe",
                          "domain": (c.get("domains") or [None])[0]})

    def pay_row(p):
        return {"id": p["id"], "provider": otto_billing.provider_of(p), "status": p.get("status"), "amount": p.get("amount"),
                "currency": p.get("currency"), "amount_eur": p.get("amount_eur"), "at": p.get("at"),
                "email": otto_billing.mask_email(p.get("email")), "membership": p.get("membership"), "reason": p.get("reason"),
                "number": p.get("number")}

    bm = sysinfo.get("billing_meta") or {}
    sm = bm.get("stripe") if isinstance(bm.get("stripe"), dict) else {}
    lw = billing.get("last_webhook") if isinstance(billing.get("last_webhook"), dict) else {}
    revenue = dict({k: v for k, v in m.items() if k != "by_provider"},
                   connected=bool(sm.get("ready") or sm.get("webhook_secret") or billing.get("customers")),
                   provider="stripe", stripe_ready=bool(sm.get("ready")), stripe_mode=sm.get("mode"),
                   last_webhook_at=lw.get("stripe"), last_backfill_at=billing.get("last_backfill_at"),
                   paying_by_provider=m["by_provider"],
                   open_checkouts=sum(1 for c in billing.get("customers", {}).values() if c.get("status") in ("drafted", "incomplete")),
                   failed_payments_30d=[pay_row(p) for p in pays if p.get("status") == "failed" and (p.get("at") or "") >= cut30][:20],
                   payments=[pay_row(p) for p in pays[:25]], customers=cust_rows,
                   legacy_whop=[r for r in cust_rows if r["provider"] == "whop"],
                   fx_note=any((p.get("currency") or "EUR") != "EUR" for p in pays))

    brands = brand_health(d, sysinfo, customers, now)
    ks = (d.get("controls") or {}).get("publishing_paused")
    events_meta = sysinfo.get("events_file") or {}
    return {
        "plans": plans_catalogue(),
        "generated": fmt(now), "sample": bool(sample), "window": window,
        "range": {"from": win_start, "to": win_days[-1], "prev_from": prev_days[0] if prev_days else None},
        "kill_switch": ks or None,
        "kpis": kpis,
        "funnel": {"steps": fsteps, "by_day": by_day, "by_week": by_week},
        "trials": trials_block(d, now, win_start, total("visitors", win_days), total("scanned", win_days)),   # people, as in the funnel
        "traffic": traffic,
        "leads": leads_out,
        "revenue": revenue,
        "brands": brands,
        "recommendations": recs_queue(d, now),
        "system": system_health(d, sysinfo, now),
        "setup": setup_items(d, sysinfo, bm, events_meta),
        "attention": {"brands_blocked": sum(1 for b in brands if b["health"] == "blocked"),
                      "brands_attention": sum(1 for b in brands if b["health"] == "attention"),
                      "p0": recs_queue(d, now)["counts"].get("P0", 0),
                      "failed_payments": len(revenue["failed_payments_30d"]),
                      "past_due": revenue["past_due"],
                      "stale_crons": sum(1 for c in cron_rows(sysinfo, now) if c["status"] in ("late", "stale"))},
    }


def trials_block(d, now, win_start, visitors=0, scans=0):
    """The console's Trials section (otto_trial): trials running (days left, reminders sent), converted / expired / no trial,
    the trial → paid conversion rate, and the trial funnel for the window: visitors → scans → sign-ups → trials → paid."""
    import math
    tp = ap.trial_plan_id()
    users = {u["id"]: u for u in d.get("users") or [] if isinstance(u, dict) and u.get("id")}
    in_win = lambda v: bool(v) and str(v)[:10] >= win_start
    rows, conv, exp, denied, conv_w, exp_w, soon = [], 0, 0, 0, 0, 0, 0
    for b in d.get("brands") or []:
        tr = b.get("trial") if isinstance(b, dict) else None
        if not isinstance(tr, dict):
            continue
        if tr.get("denied"):
            denied += 1
            continue
        if tr.get("converted_at"):
            conv += 1
            conv_w += in_win(tr["converted_at"])
            continue
        end = ap.parse_iso(tr.get("ends_at"))
        end = end if end is None or end.tzinfo else end.replace(tzinfo=timezone.utc)
        if b.get("plan") == tp and end and now < end:
            u = users.get(tr.get("user")) or {}
            left = (end - now).total_seconds()
            soon += left <= 2 * 86400
            rows.append({"brand": b["id"], "name": b.get("name") or b["id"], "email": otto_billing.mask_email(u.get("email")),
                         "started_at": tr.get("started_at"), "ends_at": tr.get("ends_at"), "days_left": max(1, math.ceil(left / 86400)),
                         "reminders": sorted(k for k, v in (u.get("trial_reminders") or {}).items() if isinstance(v, dict) and v.get("sent"))})
        else:
            exp += 1
            exp_w += in_win(tr.get("ended_at") or tr.get("ends_at"))
    us = list(users.values())
    signups = sum(1 for u in us if in_win(u.get("created_at")))
    started = sum(1 for u in us if in_win(u.get("trial_started_at")))
    paid = sum(1 for u in us if u.get("trial_started_at") and in_win(u.get("paid_at")))
    sent = Counter(k for u in us for k, v in (u.get("trial_reminders") or {}).items() if isinstance(v, dict) and v.get("sent"))
    steps, prev, top = [], None, None
    for key, label, n in (("visitors", "Visitors", visitors), ("scanned", "Scanned a site", scans), ("signups", "Signed up with Google", signups),
                          ("trials", "Started a trial", started), ("paid", "Paid after the trial", paid)):
        top = n if top is None else top
        steps.append({"key": key, "label": label, "n": n, "step_rate": pct(n, prev) if prev is not None else None,
                      "overall_rate": pct(n, top)})
        prev = n
    return {"enabled": tp is not None, "active": sorted(rows, key=lambda r: r["ends_at"] or ""),
            "counts": {"active": len(rows), "ending_48h": soon, "converted": conv, "expired": exp, "no_trial": denied,
                       "signups": signups, "converted_window": conv_w, "expired_window": exp_w, "accounts": len(us)},
            "conversion_rate": pct(conv_w, conv_w + exp_w), "conversion_rate_all": pct(conv, conv + exp),
            "reminders": {k: sent.get(k, 0) for k in ("day5", "day7", "day8")}, "funnel": steps}


def plans_catalogue():
    """plans.json for the console's plan selector: id, label, paid ads or not, the key limits, prices (null until set)."""
    cfg = ap.plans_config()
    items = []
    for pid in cfg["order"]:
        p = cfg["plans"][pid]
        f, L = p["features"], p["limits"]
        items.append({"id": pid, "label": p["label"], "paid_ads": bool(f.get("ads_meta") or f.get("ads_google")),
                      "ended": pid == cfg["defaults"]["ended"], "limits": dict(L), "features": dict(f),
                      "public": p.get("public", True), "status": p.get("status"), "upgrade_to": p.get("upgrade_to"),
                      "overage": p.get("overage"), "founding_bridge": p.get("founding_bridge"),
                      "monthly_eur": p.get("monthly_eur"), "yearly_eur": p.get("yearly_eur"), "one_time_eur": p.get("one_time_eur"),
                      "extra_brand_eur": p.get("extra_brand_eur"), "whop_plan_ids": list(p["whop_plan_ids"])})
    return {"items": items, "defaults": cfg["defaults"], "error": cfg.get("error")}


def gather_sysinfo(d):
    """What the snapshot needs from disk besides data.json: log freshness, error tails, which secrets exist."""
    base = ap.DATA.parent
    logs = {}
    for _, _, name, _ in CRON_JOBS:
        f = base / name
        if f.exists():
            last = tail_lines(f, 1, 4096)
            logs[name] = {"mtime": fmt(datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)), "last": last[-1] if last else ""}
    sd = whop.secrets_dir()
    names, open_ = {}, []
    if sd.is_dir():
        for f in sd.glob("*.json"):
            names[f.name] = True                              # existence only — never the contents
            try:
                if f.stat().st_mode & 0o077:
                    open_.append(f.name)                      # readable by the group / other users on the box
            except OSError:
                pass
    scans = {}
    for b in d.get("brands", []):
        f = ap.BRANDS / b["id"] / "scan.json"
        if f.exists():
            scans[b["id"]] = fmt(datetime.fromtimestamp(f.stat().st_mtime, timezone.utc))
    ev = track.events_path()
    ev_meta = {}
    if ev.exists():
        last = tail_lines(ev, 1, 4096)
        try:
            ev_meta["last"] = json.loads(last[-1]).get("ts") if last else None
        except Exception:
            ev_meta["last"] = None
        ev_meta["size_mb"] = round(ev.stat().st_size / 1048576, 2)
    ws = whop.status()
    cfg = whop.config()
    try:
        ss = otto_stripe.status()
    except Exception as e:                                   # setup info only: never fail the snapshot over it
        ss = {"error": type(e).__name__}
    try:
        email_h = otto_email.health()
    except Exception as e:                                   # health info only: never fail the snapshot over it
        email_h = {"transport": "error", "config_error": f"{type(e).__name__}"}
    return {"email": email_h, "logs": logs, "secrets": names, "secrets_open": sorted(open_), "scans": scans, "events_file": ev_meta,
            "publish_tail": tail_lines(base / "publish.log", 60),
            "api_errors": tail_lines(base / "api-errors.log", 15), "actions": tail_lines(actions_log(), 40),
            "billing_meta": {"stripe": ss, "whop": ws}, "legacy_whop": ws.get("customers") or 0,
            "plans": cfg["plans"], "admin_users": bool(os.environ.get("OTTO_ADMIN_USERS")),
            "single_tenant": (os.environ.get("OTTO_SINGLE_TENANT") or "").strip().lower() in ("1", "true", "yes", "on")}


def snapshot(window=30, now=None):
    now = now or utcnow()
    window = window if window in WINDOWS else 30
    since = (now.date() - timedelta(days=max(90, 2 * window) - 1)).isoformat()
    d = clean_state(ap.load())
    sysinfo = gather_sysinfo(d)
    events = track.read_events(since)                         # bounded: only the newest READ_MAX_MB are parsed
    sysinfo["events_file"]["country"] = any(e.get("cc") for e in events[-5000:])
    sysinfo["events_file"]["truncated"] = bool(getattr(track.read_events, "truncated", False))
    return build(d, events, whop.load(), load_leads(), sysinfo, now=now, window=window)


# ============================================================================================
# controls
# ============================================================================================

ACTIONS = ("kill_switch", "pause_brand", "resume_brand", "campaign", "rescan", "lead", "link_customer", "stripe_check", "members",
           "plan", "activate", "comms_lang")
RESCAN_GAP_MIN = 10


def _note(req):
    n = req.get("note")
    return re.sub(r"[\s\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]+", " ", str(n)).strip()[:300] if n else ""   # one line, no bidi override


def _q(s):
    return json.dumps(s, ensure_ascii=False)


def _pause_campaigns(d_campaigns, by, why):
    """Pause live campaigns on Meta / Google (remote first, then state, paused_by=by). A campaign that cannot be paused
    stays live and becomes a P0 "pause it by hand" card. → (paused ids, failed ids)"""
    import otto_ads                                          # remote pause (Meta / Google) of what is already spending
    done, failed = [], []
    for cid, bid in d_campaigns:
        try:
            otto_ads.pause(cid, by=by)
            done.append(cid)
        except BaseException as e:                           # otto_ads asserts / exits on bad state — never kill the API
            failed.append(cid)
            with ap.transaction() as d:
                ap.add_rec_once(d, "P0", f"Pause campaign {cid} by hand", f"{why}, but pausing the live campaign failed: "
                                f"{str(e)[:200]}", "It may still be spending", "Pause in Ads Manager",
                                brand=bid, source="otto_admin", campaign_id=cid)
    return done, failed


def _resume_switch_paused():
    """After the kill switch: resume exactly the campaigns the switch paused (paused_by "kill_switch"). A campaign paused
    before the switch, by hand or with its brand, stays paused; one whose brand is paused now is handed to the brand pause;
    one whose flight ended meanwhile is marked ended. → (resumed, ended, kept, failed) id lists"""
    import otto_ads
    resumed, ended, kept, failed = [], [], [], []
    d = ap.load()
    for c in [c for c in d.get("campaigns", []) if c.get("status") == "paused" and c.get("paused_by") == "kill_switch"]:
        cid, bid = c["id"], c.get("brand")
        if ap.paused(d, bid) or ap.no_ads_why(d, bid, c.get("network")):
            kept.append(cid)
            with ap.transaction() as d2:
                c2 = ap.campaign(d2, cid)
                if c2 is not None and c2.get("paused_by") == "kill_switch":   # the brand pause / the plan holds it now
                    c2["paused_by"] = "brand" if ap.paused(d2, bid) else "plan"
            continue
        try:
            (ended if otto_ads.resume(cid) == "ended" else resumed).append(cid)
        except BaseException as e:
            failed.append(cid)
            with ap.transaction() as d2:
                ap.add_rec_once(d2, "P1", f"Resume campaign {cid} by hand", f"Publishing was resumed from the console, but "
                                f"restarting the campaign the kill switch had paused failed: {str(e)[:200]}", "It is not spending",
                                "Resume in Ads Manager", brand=bid, source="otto_admin", campaign_id=cid)
    return resumed, ended, kept, failed


def act(req, who="admin", pause_live=True):
    """One owner action → {"ok": True, "message": …}. Raises ValueError (bad request / transition), KeyError (unknown id)."""
    if not isinstance(req, dict):
        raise ValueError("JSON object expected")
    a = req.get("action")
    if a not in ACTIONS:
        raise ValueError(f"unknown action {a!r}")
    who = clean_who(who)
    note = _note(req)
    now = ap.now_iso()

    if a == "kill_switch":
        state = req.get("state")
        if state not in ("on", "off"):
            raise ValueError("state must be on or off")
        with ap.transaction() as d:
            ctl = d.setdefault("controls", {})
            was = bool(ctl.get("publishing_paused"))
            if state == "on":
                if not was:
                    ctl["publishing_paused"] = {"at": now, "by": who, "note": note}
            else:
                if was:
                    ctl["last_resumed"] = {"at": now, "by": who, "paused_at": ctl["publishing_paused"].get("at")}
                ctl.pop("publishing_paused", None)
            live = [(c["id"], c.get("brand")) for c in d.get("campaigns", []) if c.get("status") == "live"]
        extra, out = "", {"ok": True}
        if state == "on":
            msg = "All publishing and ad launches are paused."
            if live and pause_live:                          # every campaign already spending, on every brand (again on a
                done, failed = _pause_campaigns(live, "kill_switch", "Everything was paused with the kill switch")   # repeat "on")
                msg += f" Live campaigns paused: {len(done)} of {len(live)}." + (" Pause the rest by hand (recommendation filed)."
                                                                                if failed else "")
                extra = f" live={len(live)} failed={len(failed)}"
                out.update(paused_campaigns=done, failed_campaigns=failed)
            else:
                msg += " No campaign was live."
        else:
            msg = "Publishing resumed."
            if pause_live:
                resumed, ended, kept, failed = _resume_switch_paused()
                n = len(resumed) + len(ended) + len(kept) + len(failed)
                if n:
                    msg += f" Campaigns the switch paused are live again: {len(resumed)} of {n}." + \
                           (f" {len(ended)} ended meanwhile." if ended else "") + \
                           (f" {len(kept)} stay paused with their brand." if kept else "") + \
                           (" Resume the rest by hand (recommendation filed)." if failed else "")
                    extra = f" resumed={len(resumed)} ended={len(ended)} kept={len(kept)} failed={len(failed)}"
                out.update(resumed_campaigns=resumed, failed_campaigns=failed)
            msg += " Campaigns paused before the switch stay paused."
        log_action(who, f"kill-switch {state}" + (" (no change)" if was == (state == "on") else "") + extra
                   + (f" note={_q(note)}" if note else ""))
        return dict(out, message=msg)

    if a in ("pause_brand", "resume_brand"):
        bid = str(req.get("brand") or "")
        live = []
        with ap.transaction() as d:
            b = ap.brand(d, bid)
            if b is None:
                raise KeyError(bid)
            if a == "pause_brand":
                if b.get("paused"):
                    raise ValueError(f"{b.get('name') or bid} is already paused")
                b["paused"] = {"at": now, "by": who, "note": note, "prev_status": b.get("status")}
                b["status"] = "paused"
                live = [c["id"] for c in d.get("campaigns", []) if c.get("brand") == bid and c.get("status") == "live"]
            else:
                if not (b.get("paused") or b.get("status") == "paused"):
                    raise ValueError(f"{b.get('name') or bid} is not paused")
                prev = (b.get("paused") or {}).get("prev_status") if isinstance(b.get("paused"), dict) else None
                b["status"] = prev if prev and prev != "paused" else "active"
                b.pop("paused", None)
        msg = f"{bid} paused: no posts publish and no ads launch." if a == "pause_brand" else f"{bid} resumed."
        failed = []
        if live and pause_live:
            _, failed = _pause_campaigns([(cid, bid) for cid in live], "brand", "The brand was paused from the console")
            msg += f" Live campaigns paused: {len(live) - len(failed)} of {len(live)}." + (" Pause the rest by hand (recommendation filed)."
                                                                                         if failed else "")
        elif a == "resume_brand":
            msg += " Campaigns paused earlier stay paused."
        log_action(who, f"{a.replace('_', '-')} {bid}" + (f" live={len(live)} failed={len(failed)}" if live else "") + (f" note={_q(note)}" if note else ""))
        return {"ok": True, "message": msg, "failed_campaigns": failed}

    if a == "campaign":
        cid, decision = str(req.get("id") or ""), req.get("decision")
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        with ap.transaction() as d:
            c = ap.campaign(d, cid)
            if c is None:
                raise KeyError(cid)
            st = c.get("status")
            if decision == "approve":
                if st != "draft":
                    raise ValueError(f"campaign is {st} — only a draft can be approved")
                if c.get("compliance_hold"):
                    raise ValueError("campaign is on compliance hold — fix the copy and release it first (otto_ads.py release)")
                c["status"] = "approved"; c["approved_via"] = "admin"; c["decided_at"] = now
            else:
                if st not in ("draft", "approved"):
                    raise ValueError(f"campaign is {st} — a live campaign is paused, not rejected")
                held = ap.parse_iso(c.get("launching_at"))
                if held and held.tzinfo and datetime.now(timezone.utc) - held < timedelta(minutes=60):
                    raise ValueError("campaign is being launched right now — pause it after the launch")
                c["status"] = "skipped"; c["rejected"] = {"at": now, "by": who, "note": note}; c["decided_at"] = now
        log_action(who, f"campaign {cid} {decision}" + (f" note={_q(note)}" if note else ""))
        return {"ok": True, "message": f"{cid} {'approved' if decision == 'approve' else 'rejected'}."}

    if a == "rescan":
        bid = str(req.get("brand") or "")
        with ap.transaction() as d:
            b = ap.brand(d, bid)
            if b is None:
                raise KeyError(bid)
            if not b.get("url"):
                raise ValueError(f"{bid} has no website url")
            last = ap.parse_iso((b.get("rescan") or {}).get("requested_at"))
            if last and last.tzinfo and datetime.now(timezone.utc) - last < timedelta(minutes=RESCAN_GAP_MIN):
                raise ValueError(f"a scan of {bid} started less than {RESCAN_GAP_MIN} minutes ago")
            b["rescan"] = {"requested_at": now, "by": who}
            url = b["url"]
        with open(ap.DATA.parent / "scan.log", "a") as lf:
            lf.write(f"{now} rescan {bid} {url} (admin {who})\n")
            lf.flush()
            SPAWN([sys.executable, str(HERE / "otto_scan.py"), url, "--slug", bid, "--no-profile"], lf)
        log_action(who, f"rescan {bid}")
        return {"ok": True, "message": f"Re-reading {url}. The profile updates in about a minute (scan.json only; the brand profile is kept)."}

    if a == "lead":
        lid, st = str(req.get("id") or ""), req.get("status")
        if not re.fullmatch(r"d:[a-z0-9.-]{3,100}|v:\d{4}-\d{2}-\d{2}:[0-9a-f]{8}", lid):
            raise ValueError("bad lead id")
        if st not in LEAD_STATUSES:
            raise ValueError(f"status must be one of {', '.join(LEAD_STATUSES)}")
        f = leads_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f.with_name(f.name + ".lock"), "a+") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                cur = json.loads(f.read_text()) if f.exists() else {}
            except Exception:
                cur = {}
            leads = cur.setdefault("leads", {})
            row = leads.setdefault(lid, {"history": []})
            row["history"] = (row.get("history") or [])[-19:] + [{"at": now, "by": who, "status": st, "note": note}]
            row.update(status=st, note=note if "note" in req else row.get("note", ""), updated=now, by=who)   # "" clears it
            ap._atomic_write(f, json.dumps(cur, ensure_ascii=False, indent=1) + "\n")
            os.chmod(f, 0o600)
        log_action(who, f"lead {lid} {st}" + (f" note={_q(note)}" if note else ""))
        return {"ok": True, "message": f"Lead marked {st}."}

    if a == "link_customer":
        cid, bid = str(req.get("customer") or ""), str(req.get("brand") or "")
        if bid and ap.brand(ap.load(), bid) is None:
            raise KeyError(bid)
        c = otto_billing.link(cid, bid, by=who)              # also makes the payer a member (like the CLI)
        email = ap.norm_member(c.get("email")) if bid else None
        ps = c.get("plan_sync") or {}
        log_action(who, f"link-customer {cid} -> {bid or 'none'}" + (" (+member)" if email else "")
                   + (f" plan {ps['from']} -> {ps['to']}" if ps.get("changed") else "") + (" activated" if ps.get("activated") else ""))
        plan_msg = (f" Plan: {ps['from']} → {ps['to']}." + (" Its live campaigns the new plan does not cover are being paused."
                                                          if ps.get("live") else "") if ps.get("changed")
                    else f" Plan unchanged: {ps['why']}." if ps else "") + (" Onboarding done: its jobs start." if ps.get("activated") else "")
        return {"ok": True, "message": (f"{cid} linked to {bid}." + (" They can sign in to see it." if email else "") + plan_msg) if bid
                else f"{cid} unlinked (the brand keeps its plan)."}

    if a == "comms_lang":                                     # the language of what Otto sends this client (otto_i18n)
        bid = str(req.get("brand") or "")
        before, lang = otto_i18n.set_comms_lang(bid, req.get("lang"), via="admin")     # KeyError / ValueError → 404 / 400
        log_action(who, f"comms_lang {bid} {before} -> {lang}")
        return {"ok": True, "message": f"{bid}: e-mails and reports in {otto_i18n.COMMS_LANGS[lang]}.", "comms_lang": lang}

    if a == "members":
        bid = str(req.get("brand") or "")
        adds, removes = req.get("add") or [], req.get("remove") or []
        if not isinstance(adds, list) or not isinstance(removes, list) or len(adds) + len(removes) > 50:
            raise ValueError("add / remove must be lists of e-mails")
        add = [ap.norm_member(x) for x in adds]
        rem = {str(x).strip().lower() for x in removes}
        if not all(add):
            raise ValueError("members are e-mail addresses (or @domain for a whole company)")
        with ap.transaction() as d:
            b = ap.brand(d, bid)
            if b is None:
                raise KeyError(bid)
            cur = [m for m in b.get("members") or [] if str(m).lower() not in rem]
            b["members"] = cur + [m for m in add if m not in cur]
            members = list(b["members"])
        log_action(who, f"members {bid} +{len(add)} -{len(rem)} now={len(members)}")
        return {"ok": True, "message": f"{bid}: {len(members)} member{'s' * (len(members) != 1)}.", "members": members}

    if a == "plan":
        bid, pid = str(req.get("brand") or ""), str(req.get("plan") or "")
        if "until" in req and req["until"] is not None and not isinstance(req["until"], str):
            raise ValueError("until must be a date (YYYY-MM-DD) or empty")
        cfg = ap.plans_config()
        if cfg.get("error"):
            raise ValueError(f"plans.json cannot be used: {cfg['error'][:200]}")
        if pid not in cfg["plans"]:
            raise ValueError(f"unknown plan {pid!r}: one of {', '.join(cfg['order'])}")
        with ap.transaction() as d:
            if ap.brand(d, bid) is None:
                raise KeyError(bid)
            cur = ap.plan_of(d, bid)
            # a new plan starts without the old plan's end date unless one is given; the same plan keeps it
            until = (str(req.get("until") or "").strip() or None) if "until" in req else (ap.KEEP if cur["requested"] == pid else None)
            before, after = ap.set_plan(d, bid, pid, until=until, by=who, via="admin", note=note)
            bb = ap.brand(d, bid)
            activated = bb.get("status") == "onboarding" and pid != "none"      # a plan set by hand = a comped/approved client
            if activated:
                bb["status"] = "active"; bb["activated_at"] = now; bb["activated_by"] = who
            live = [(c["id"], bid) for c in d.get("campaigns", []) if c.get("brand") == bid and c.get("status") == "live"
                    and ap.no_ads_why(d, bid, c.get("network"))]
            name = (ap.brand(d, bid) or {}).get("name") or bid
        msg = f"{name}: {before['label']} → {after['label']}" + (f" until {after['until']}" if after["until"] and not after["expired"] else "") + "."
        if activated:
            msg += " The brand was still in onboarding, so it is active now: its jobs start on their next run."
        if after["expired"]:
            msg += f" The end date {after['until']} has passed, so it runs as {after['label']} now."
        if ap.plan_ended(ap.load(), bid):
            msg += (" No active plan: publishing and ad launches are paused for this brand. Nothing was deleted; the data is "
                    "deleted 90 days from now unless a plan starts again (otto_retention).")
        paid_before = before["features"].get("ads_meta") or before["features"].get("ads_google")
        paid_after = after["features"].get("ads_meta") or after["features"].get("ads_google")
        done, failed = [], []
        if live and pause_live:
            done, failed = _pause_campaigns(live, "plan", f"{name} moved to the {after['label']} plan, which does not cover it")
            msg += f" Live campaigns paused: {len(done)} of {len(live)}." + (" Pause the rest by hand (recommendation filed)."
                                                                            if failed else "")
        elif paid_before and not paid_after:
            msg += " Paid ads are off for this brand; no campaign was live."
        log_action(who, f"plan {bid} {before['id']} -> {pid}" + (f" until={after['until']}" if after["until"] else "")
                   + (f" live={len(live)} failed={len(failed)}" if live else "") + (f" note={_q(note)}" if note else ""))
        return {"ok": True, "message": msg, "plan": ap.plan_view(ap.load(), bid), "paused_campaigns": done, "failed_campaigns": failed}

    if a == "activate":
        # a client that did not come through a paid checkout (brand-add, a comped seat): onboarding → active, nothing else changes
        bid = str(req.get("brand") or "")
        with ap.transaction() as d:
            bb = ap.brand(d, bid)
            if bb is None:
                raise KeyError(bid)
            if bb.get("status") == "active":
                return {"ok": True, "message": f"{bb.get('name') or bid} is already active."}
            if bb.get("status") != "onboarding":
                raise ValueError(f"{bid} is {bb.get('status')}: resume it instead (resume_brand)")
            bb["status"] = "active"; bb["activated_at"] = now; bb["activated_by"] = who
            name = bb.get("name") or bid
        log_action(who, f"activate {bid}" + (f" note={_q(note)}" if note else ""))
        return {"ok": True, "message": f"{name} is active: its jobs start on their next run."}

    if a == "stripe_check":
        # read-only: account, Stripe Tax, every price in plans.json, the webhook endpoint, branding → Setup
        if not otto_stripe.config()["secret_key"]:
            raise ValueError("Stripe is not set up yet — add secret_key to otto-secrets/stripe.json (docs/BILLING.md)")
        with open(ap.DATA.parent / "stripe.log", "a") as lf:
            lf.write(f"{now} check (admin {who})\n")
            lf.flush()
            SPAWN([sys.executable, str(HERE / "otto_stripe.py"), "check"], lf)
        log_action(who, "stripe-check")
        return {"ok": True, "message": "Checking the Stripe setup. Refresh in a few seconds."}


# ============================================================================================
# sample (synthetic, clearly labelled) — the console opened as a file shows this
# ============================================================================================

def sample_inputs(now):
    """Invented businesses on reserved .example domains; numbers are made up. Runs through build() like live data."""
    R = random.Random(29)
    today = now.date()
    iso = lambda dt: fmt(dt)
    brands = [
        {"id": "spreebogen", "name": "Spreebogen Dental", "url": "spreebogen-dental.example", "status": "active", "tz": "Europe/Berlin", "currency": "EUR",
         "plan": "scale", "approvals": "email", "members": ["praxis@spreebogen-dental.example", "lena@spreebogen-dental.example"]},
        {"id": "casalume", "name": "Casa Lume", "url": "casalume.example", "status": "active", "tz": "Europe/Lisbon", "currency": "EUR",
         "plan": "founding", "plan_until": (today + timedelta(days=45)).isoformat(),
         "plan_history": [{"at": iso(now - timedelta(days=20)), "by": "whop", "via": "whop", "from": "content", "to": "founding",
                           "until": None, "note": "Whop plan plan_joHl1qsZoiJc9"}]},
        {"id": "nordlicht", "name": "Nordlicht Coffee", "url": "nordlicht-coffee.example", "status": "active", "tz": "Europe/Berlin", "currency": "EUR",
         "plan": "growth", "approvals": ["email", "telegram"], "members": ["jonas@nordlicht-coffee.example"]},
        {"id": "brume", "name": "Atelier Brume", "url": "atelier-brume.example", "status": "active", "tz": "Europe/Paris", "currency": "EUR",
         "plan": "starter", "approvals": "email", "members": ["claire@atelier-brume.example", "hello@atelier-brume.example"], "ad_band": {now.strftime("%Y-%m"): {"plan": "starter", "over": True, "mode": "grace", "asked_eur": 1240.0,
                                                               "plan_eur": 1240.0, "cap_eur": 1000, "overage_eur": 0.0}}},
        {"id": "fjordyoga", "name": "Fjord Yoga", "url": "fjordyoga.example", "status": "onboarding", "tz": "Europe/Copenhagen", "currency": "EUR",
         "plan": "starter", "plan_billing": "not_billed", "approvals": "app"},
    ]
    ym = now.strftime("%Y-%m")
    hooks = ["Three questions to ask before your first implant", "Behind the pass: Friday's catch", "Why we roast light in summer",
             "Peonies are back for two weeks", "Five minutes of breath work before work", "What our patients say after the first visit",
             "Tasting menu, explained in one minute", "From farm to cup: the Ethiopian lot", "A bouquet for someone who has everything",
             "Your first class: what to bring"]
    posts, n = [], 0
    for bi, b in enumerate(brands):
        for k in range(14 if b["status"] == "active" else 4):
            n += 1
            when = now + timedelta(days=k * 2 - 17 + bi % 2, hours=(k % 3) * 4 - now.hour + 9)
            slot = when.strftime("%Y-%m-%dT%H:00")
            if when < now:
                st = R.choice(["published", "published", "published", "skipped"])
            else:
                st = R.choice(["approved", "pending_approval", "scheduled", "pending_approval", "draft"])
            if b["id"] == "casalume" and k == 7:
                st = "failed"
            if b["id"] == "nordlicht" and k == 9:
                st = "pending_approval"
            p = {"id": f"{b['id'][:2]}-{n:03d}", "brand": b["id"], "pillar": "Education", "platform": R.choice(["ig", "fb"]),
                 "format": R.choice(["post", "post", "carousel", "reel", "story"]),
                 "hook": hooks[(bi * 3 + k) % len(hooks)], "status": st, "slot": slot,
                 "created_at": iso(now - timedelta(days=R.randint(3, 20)))}
            if st == "failed":
                p["error"] = "Graph 190: the Page access token has expired"
            if st == "pending_approval":
                p["tg_sent_at"] = iso(now - timedelta(hours=80 if b["id"] == "nordlicht" else R.choice([3, 9, 20])))
            if st in ("published", "skipped", "approved"):
                p["decided_at"] = iso(now - timedelta(days=R.randint(1, 6), hours=R.randint(0, 20)))
            posts.append(p)
    posts.append({"id": "br-900", "brand": "brume", "pillar": "Offers", "platform": "ig", "hook": "Guaranteed to last three weeks",
                  "status": "draft", "slot": (now + timedelta(days=3)).strftime("%Y-%m-%dT10:00"), "compliance_block": {"rules": ["guarantee claim"], "at": iso(now - timedelta(days=1))}})
    fl = lambda k: (today + timedelta(days=k)).isoformat()
    camps = [
        {"id": "cp-001", "brand": "spreebogen", "network": "meta", "name": "Implant consult, cold", "status": "live", "start": fl(-24),
         "end": fl(6), "daily_budget": 25, "objective": "OUTCOME_LEADS", "launched_at": iso(now - timedelta(days=24))},
        {"id": "cp-002", "brand": "spreebogen", "network": "google", "name": "Search: dentist Mitte", "status": "live", "start": fl(-18),
         "end": fl(12), "daily_budget": 15, "objective": "search", "launched_at": iso(now - timedelta(days=18))},
        {"id": "cp-003", "brand": "casalume", "network": "meta", "name": "Tasting menu, warm audience", "status": "draft", "start": fl(2),
         "end": fl(16), "daily_budget": 12, "objective": "OUTCOME_TRAFFIC"},
        {"id": "cp-004", "brand": "nordlicht", "network": "meta", "name": "Boost: the Ethiopian lot", "status": "approved", "start": fl(1),
         "end": fl(10), "daily_budget": 8, "objective": "engagement"},
        {"id": "cp-005", "brand": "brume", "network": "meta", "name": "Peony weeks", "status": "draft", "start": fl(3),
         "end": fl(17), "daily_budget": 10, "objective": "OUTCOME_SALES", "compliance_hold": True},
        {"id": "cp-006", "brand": "nordlicht", "network": "meta", "name": "Subscription launch", "status": "ended", "start": fl(-40),
         "end": fl(-12), "daily_budget": 10, "objective": "OUTCOME_SALES", "launched_at": iso(now - timedelta(days=40))},
    ]
    ads = {"spreebogen": {"daily": {(today - timedelta(days=i)).isoformat(): {"meta": {"yesterday": {"spend": round(R.uniform(19, 26), 2)}},
                                                                          "google": {"yesterday": {"spend": round(R.uniform(9, 15), 2)}}}
                                    for i in range(0, 25)}}}
    recs = [
        {"id": "rec-101", "priority": "P0", "title": "Reconnect Casa Lume's Facebook page", "brand": "casalume", "source": "otto_publish",
         "status": "proposed", "created_at": iso(now - timedelta(hours=7))},
        {"id": "rec-102", "priority": "P1", "title": "Approve the paid plan for Casa Lume", "brand": "casalume", "source": "otto_ads",
         "status": "proposed", "created_at": iso(now - timedelta(days=2))},
        {"id": "rec-103", "priority": "P1", "title": "Compliance hold: Atelier Brume, guarantee claim", "brand": "brume", "source": "otto_compliance",
         "status": "proposed", "created_at": iso(now - timedelta(days=1))},
        {"id": "rec-104", "priority": "P2", "title": "Double down on 'Behind the pass' reels", "brand": "casalume", "source": "otto_insights",
         "status": "proposed", "created_at": iso(now - timedelta(days=3))},
        {"id": "rec-105", "priority": "P2", "title": "Competitor launched a summer menu", "brand": "casalume", "source": "otto_competitors",
         "status": "proposed", "created_at": iso(now - timedelta(days=4))},
    ]
    d = {"generated": iso(now - timedelta(minutes=4)), "brands": brands, "posts": posts, "campaigns": camps, "ads": ads,
         "recommendations": recs, "connections": [], "controls": {}}

    # ---- billing ----
    first = ["anna", "lukas", "sofia", "mateo", "lea", "jonas", "chiara", "tomas", "ines", "noah", "eva", "marta", "felix", "clara",
             "joao", "elena", "paul", "sara", "david", "nina", "leo", "maria"]
    LINKED = [3, 9, 14, 17, 19]
    doms = ["salt-and-sage.example", "gmail.com", "hafen-physio.example", "", "atelier-kobalt.example", "gmail.com",
            "praxis-lindner.example", "velo-werk.example", "gmx.de", "", "haus-am-see.example", "kanal-bakery.example", "outlook.com",
            "studio-mira.example", "", "ferro-gym.example", "web.de", "", "bloom-and-root.example", "", "cantina-norte.example",
            "linden-apotheke.example"]                        # "" = linked to a sample brand below
    plans = dict(whop.PLANS)                                 # the legacy Whop founding seat (read-only list)
    _pp = ap.plans_config()["plans"]                           # the sample bills what plans.json charges (Starter EUR 79 a month)
    price_of = {pid: (_pp.get(pid, {}).get("monthly_eur") or m, _pp.get(pid, {}).get("yearly_eur"))
                for pid, m in (("starter", 79), ("growth", 249))}
    customers, payments = {}, {}
    for i, name in enumerate(first):
        started = now - timedelta(days=int(85 * (1 - i / len(first)) ** 1.3) + 1, hours=R.randint(0, 20))
        founder = i < 6                                       # the first seats were sold on Whop before Stripe
        st = "completed" if founder else "active"
        if i in (6, 15):
            st = "canceled"
        if i == 18:
            st = "past_due"
        if i == 20:
            st = "trialing"
        email = f"{name}@{doms[i]}"
        if i in LINKED:
            email = f"{name}@{brands[LINKED.index(i)]['url']}"
        if founder:
            cid = f"mem_sample{i:03d}"
            c = {"id": cid, "provider": "whop", "email": email, "status": whop.STATUS[st], "whop_status": st,
                 "plan_id": "plan_joHl1qsZoiJc9", "started": iso(started), "currency": "EUR", "updated_at": iso(started),
                 "source": "sample", "first_seen": iso(started)}
            amount, n_pay, reason = 197, 1, "one_time"
        else:
            plan = "growth" if i % 3 == 2 else "starter"
            year = i % 5 == 4 and price_of[plan][1] is not None             # Starter is monthly only
            cid = f"sub_sample{i:03d}"
            amount = price_of[plan][1 if year else 0]
            status = {"completed": "active", "canceled": "canceled"}.get(st, st)
            c = {"id": cid, "provider": "stripe", "kind": "subscription", "subscription": cid, "customer": f"cus_sample{i:03d}",
                 "email": email, "status": status, "provider_status": status, "plan": plan, "plan_id": f"price_sample_{plan}_{'y' if year else 'm'}",
                 "interval": "year" if year else "month", "amount": float(amount), "currency": "EUR", "started": iso(started),
                 "updated_at": iso(started), "source": "sample", "first_seen": iso(started)}
            if status == "trialing":
                c["trial_end"] = iso(now + timedelta(days=3))
            if i == 11:
                c["pending"] = {"plan": "starter", "interval": "month", "at": iso(now + timedelta(days=12))}
            if i == 13:
                c["cancel_at_period_end"] = True
            n_pay = 0 if status == "trialing" else (1 if year else max(1, int((now - started).days // 30) + 1))
            reason = "subscription"
        if st in ("active", "past_due", "trialing"):
            c["renews"] = iso(now + timedelta(days=R.randint(2, 28)))
        if st == "canceled":
            c["canceled_at"] = iso(now - timedelta(days=R.randint(1, max(2, today.day - 1))))
        if i in LINKED:
            c["brand_id"] = brands[LINKED.index(i)]["id"]
            c["brand_link"] = {"by": "auto: signed checkout reference" if not founder else "max", "at": iso(started)}
        customers[cid] = c
        for k in range(n_pay):
            at = started + timedelta(days=30 * k)
            pid = (f"pay_sample{i:03d}{k}" if founder else f"in_sample{i:03d}{k}")
            payments[pid] = {"id": pid, "provider": c["provider"], "membership": cid, "status": "paid", "amount": float(amount),
                             "currency": "EUR", "amount_eur": float(amount), "at": iso(at), "email": email, "plan_id": c["plan_id"],
                             "reason": reason if founder else ("subscription_create" if k == 0 else "subscription_cycle")}
            if not founder:
                payments[pid]["number"] = f"OTTO-{1000 + i * 10 + k}"
        if i == 18:
            payments["in_sample_fail"] = {"id": "in_sample_fail", "provider": "stripe", "membership": cid, "status": "failed",
                                          "amount": float(amount), "currency": "EUR", "amount_eur": float(amount),
                                          "at": iso(now - timedelta(days=2)), "email": email, "plan_id": c["plan_id"],
                                          "reason": "subscription_cycle", "number": "OTTO-1999"}
    for k in range(3):                                        # checkouts not paid yet (SEPA processing, abandoned 3-D Secure)
        cid = f"sub_open{k}"
        customers[cid] = {"id": cid, "provider": "stripe", "kind": "subscription", "status": "incomplete", "plan": "starter",
                          "plan_id": "price_sample_starter_m", "started": iso(now - timedelta(days=R.randint(0, 25))), "first_seen": iso(now)}
    billing = {"customers": customers, "payments": payments, "plans": {}, "events": [], "seen": [],
               "last_webhook_at": iso(now - timedelta(hours=3)), "last_webhook": {"stripe": iso(now - timedelta(hours=3))},
               "last_backfill_at": iso(now - timedelta(days=1))}

    # ---- landing events ----
    srcs = [("google.com", None, 34), (None, None, 22), ("instagram.com", None, 12), ("facebook.com", None, 7), ("linkedin.com", None, 6),
            (None, {"source": "newsletter", "medium": "email", "campaign": "founding-seats"}, 6),
            ("l.facebook.com", {"source": "facebook", "medium": "paid", "campaign": "otto-launch-de"}, 9), ("chatgpt.com", None, 4)]
    weights = [w for *_, w in srcs]
    ccs = ["DE", "DE", "DE", "AT", "CH", "PT", "NL", "FR", "IT", "ES", "IL", "GB", "PL"]
    pre = ["praxis", "cafe", "studio", "atelier", "haus", "casa", "zahn", "physio", "yoga", "wein", "blumen", "baeckerei", "salon",
           "kanzlei", "optik", "surf", "velo", "pasta", "tattoo", "kita"]
    suf = ["lindner", "am-see", "mira", "nord", "sonne", "lumen", "fresca", "berg", "kante", "porto", "mitte", "linden", "rosa",
           "hafen", "alma", "vita"]
    scan_domains = sorted({f"{R.choice(pre)}-{R.choice(suf)}.example" for _ in range(400)})
    events = []
    sec = LANDING_SECTIONS
    for back in range(89, -1, -1):
        dd = today - timedelta(days=back)
        base_n = int(28 + (89 - back) * 0.55 + (8 if dd.weekday() < 5 else -6))
        for j in range(max(4, base_n + R.randint(-6, 6))):
            t = datetime(dd.year, dd.month, dd.day, R.randint(6, 22), R.randint(0, 59), R.randint(0, 59), tzinfo=timezone.utc)
            if t > now:
                t = now - timedelta(minutes=R.randint(1, 50))
            ts = iso(t)
            if R.random() < 0.04:
                events.append({"ts": ts, "e": "view", "p": "/pilot-landing.html", "anon": 1})
                continue
            v = f"{R.getrandbits(64):016x}"
            s = f"{R.getrandbits(40):010x}"
            ref, utm, _ = R.choices(srcs, weights)[0]
            dv = R.choices(["mobile", "desktop", "tablet"], [58, 37, 5])[0]
            view = {"ts": ts, "e": "view", "v": v, "s": s, "p": "/pilot-landing.html", "dv": dv, "cc": R.choice(ccs)}
            if ref:
                view["r"] = ref
            if utm:
                view["u"] = utm
            events.append(view)
            depth = R.random()
            for mm, thr in ((25, 0.15), (50, 0.4), (75, 0.62), (100, 0.8)):
                if depth > thr:
                    events.append({"ts": ts, "e": "scroll", "v": v, "s": s, "p": "/pilot-landing.html", "d": mm})
            for si, sid in enumerate(sec):
                if depth > si / len(sec) * 0.95:
                    events.append({"ts": ts, "e": "section", "v": v, "s": s, "p": "/pilot-landing.html", "id": sid})
            if R.random() < 0.075:
                dom = R.choice(scan_domains)
                events.append({"ts": ts, "e": "scan_start", "v": v, "s": s, "p": "/pilot-landing.html", "domain": dom})
                events.append({"ts": ts, "e": "scan_result", "v": v, "s": s, "p": "/pilot-landing.html", "domain": dom, "ok": R.random() < 0.85})
            if depth > 0.55 and R.random() < 0.12:
                where = R.choices(["top", "pricing", "nav", "dock", "final", "launch", "menu"], [30, 26, 16, 12, 8, 4, 4])[0]
                events.append({"ts": ts, "e": "cta", "v": v, "s": s, "p": "/pilot-landing.html", "id": f"start_trial@{where}"})
            if depth > 0.3 and R.random() < 0.05:
                events.append({"ts": ts, "e": "cta", "v": v, "s": s, "p": "/pilot-landing.html", "id": "scan_first@final"})
            if depth > 0.8 and R.random() < 0.3:
                events.append({"ts": ts, "e": "faq_open", "v": v, "s": s, "p": "/pilot-landing.html",
                               "q": R.choice(["how-much-does-otto-cost", "whats-included-in-the-79", "what-happens-after-the-7-days",
                                              "can-i-cancel-anytime", "does-anything-go-out-without-my-approval",
                                              "will-the-ads-and-posts-sound-like-my-brand", "which-languages",
                                              "how-is-this-different-from-a-scheduler-plus-chatgpt", "what-do-i-need-to-bring"])})
    events.sort(key=lambda e: e["ts"])
    # the paying sample customers who scanned first
    for i, dom in enumerate(["salt-and-sage.example", "hafen-physio.example", "atelier-kobalt.example"]):
        t = iso(now - timedelta(days=40 - i * 9))
        events.append({"ts": t, "e": "scan_start", "v": f"{i:016x}", "s": f"{i:010x}", "p": "/pilot-landing.html", "domain": dom})
    events.sort(key=lambda e: e["ts"])
    recent = [e["domain"] for e in events if e["e"] == "scan_start"][-40:]
    overlay = {"d:salt-and-sage.example": {"status": "won", "note": "Founding seat, onboarding call done", "updated": iso(now - timedelta(days=30))},
               f"d:{recent[-3]}": {"status": "contacted", "note": "Asked about WhatsApp approvals", "updated": iso(now - timedelta(days=1))},
               f"d:{recent[-12]}": {"status": "contacted", "note": "Sent the sample month", "updated": iso(now - timedelta(days=3))},
               f"d:{recent[-25]}": {"status": "lost", "note": "Went with an agency", "updated": iso(now - timedelta(days=9))}}

    mins = lambda n: iso(now - timedelta(minutes=n))
    logs = {"publish.log": {"mtime": mins(6), "last": "nothing due"}, "watch.log": {"mtime": mins(41), "last": "watch: all quiet"},
            "telegram.log": {"mtime": mins(60 * 7), "last": "sent 6 cards"}, "genvisuals.log": {"mtime": mins(60 * 16), "last": "12 images"},
            "reels.log": {"mtime": mins(60 * 15), "last": "rendered 1 reel"}, "ads.log": {"mtime": mins(60 * 5), "last": "report sent"},
            "growth.log": {"mtime": mins(60 * 9), "last": "growth rolled up for 5 brands"},
            "competitors.log": {"mtime": mins(60 * 24 * 1 + 30), "last": "sweep done: 3 changes"},
            "insights.log": {"mtime": mins(60 * 24 * 11), "last": "winners: 4"},
            "plan.log": {"mtime": mins(60 * 24 * 4 + 200), "last": "planned 14 posts for 5 brands"}}
    sysinfo = {"logs": logs,
               "secrets": {"stripe.json": True, "whop.json": True, "telegram.json": True, "meta-spreebogen.json": True, "meta-nordlicht.json": True,
                           "meta-brume.json": True, "google-spreebogen.json": True},
               "scans": {b["id"]: iso(now - timedelta(days=R.randint(2, 30))) for b in brands},
               "events_file": {"last": iso(now - timedelta(minutes=2)), "size_mb": 3.4, "country": True},
               "publish_tail": [f"{mins(60 * 26)} FAIL ca-020 casalume/fb slot {today.strftime('%d/%m')} 12:00: Graph 190: the Page access token has expired"],
               "api_errors": [], "legacy_whop": 6,
               "billing_meta": {"stripe": {"file": True, "secret_key": True, "publishable_key": True, "ready": True, "mode": "test",
                                           "webhook_secret": True, "checkout_ui": "embedded", "portal_fallback": False,
                                           "last_webhook_at": billing["last_webhook_at"],
                                           "check": {"at": iso(now - timedelta(hours=20)), "tax": "active", "branding": True,
                                                     "prices": {"starter.monthly": "ok", "starter.yearly": "ok", "growth.monthly": "ok",
                                                                "growth.yearly": "ok"}, "problems": []}},
                                "whop": {"file": True, "api_key": True, "company_id": True, "webhook_secret": True, "customers": 6,
                                         "last_webhook_at": iso(now - timedelta(days=9)), "last_backfill_at": billing["last_backfill_at"]}},
               "actions": [f"{mins(60 * 30)} dashboard post sp-004 -> approved", f"{mins(60 * 26)} telegram decide no-021 -> approve",
                           f"{mins(60 * 20)} admin max lead d:{recent[-3]} contacted note=\"Asked about WhatsApp approvals\"",
                           f"{mins(60 * 3)} admin max campaign cp-004 approve"],
               "plans": plans, "admin_users": False,
               "email": {"transport": "postmark", "config_error": None, "link_secret": "email.json", "outbox": None,
                         "brands": {"spreebogen": {"digest": {"at": mins(60 * 3), "posts": 3, "emails": 2, "to": 2, "transport": "postmark"},
                                                   "recs": {"at": mins(60 * 16), "recs": 1, "emails": 2, "transport": "postmark"}, "sent": 41},
                                    "nordlicht": {"digest": {"at": mins(60 * 4), "posts": 2, "emails": 1, "to": 1, "transport": "postmark"},
                                                  "plan": {"at": mins(60 * 24 * 4), "recs": 1, "emails": 1, "plan": ym}, "sent": 17},
                                    "brume": {"digest": {"at": mins(60 * 2), "posts": 4, "emails": 1, "to": 1, "transport": "postmark"}, "sent": 12}},
                         "bounces": [{"to": "h•••@atelier-brume.example", "type": "hard", "at": mins(60 * 26), "brands": ["brume"],
                                      "why": "The server was unable to deliver your message (mailbox unavailable)", "source": "postmark"}],
                         "bounce_sync": {"at": mins(40), "found": 0, "transport": "postmark"}}}
    # free trials (otto_trial): Google sign-ups on invented .example businesses — two running, one converted, one ended
    trials = [("lindenhof", "Lindenhof Bakery", 5, None, "trial"), ("saltpier", "Salt Pier Surf", 2, None, "trial"),
              ("kaffeklubb", "Kaffe Klubb", 19, "starter", "starter"), ("ateliernord", "Atelier Nord", 13, None, "none")]
    for i, (bid, name, ago, conv, plan) in enumerate(trials):
        start = now - timedelta(days=ago, hours=3)
        end = start + timedelta(days=7)
        uid = f"u-sample{i}"
        tr = {"user": uid, "started_at": iso(start), "ends_at": iso(end)}
        if conv:
            tr.update(converted_at=iso(start + timedelta(days=6)), converted_to=conv)
        elif plan == "none":
            tr["ended_at"] = iso(end)
        d["brands"].append({"id": bid, "name": name, "url": f"{bid}.example", "status": "active", "tz": "Europe/Berlin", "currency": "EUR",
                            "plan": plan, "approvals": "email", "members": [f"owner@{bid}.example"], "trial": tr,
                            **({"plan_until": end.date().isoformat()} if plan == "trial" else {})})
        sent = {k: {"sent": iso(t)} for k, t in (("day5", end - timedelta(days=2)), ("day7", end - timedelta(days=1)), ("day8", end))
                if t <= now and not (conv and k == "day8")}
        d.setdefault("users", []).append({"id": uid, "email": f"owner@{bid}.example", "name": name, "google_sub": f"10{i}",
                                          "created_at": iso(start), "last_login_at": iso(now - timedelta(hours=i + 1)),
                                          "trial_started_at": iso(start), "trial_ends_at": iso(end), "brands": [bid],
                                          "status": "active" if conv else "trial" if now < end else "expired", "trial_reminders": sent,
                                          **({"paid_at": tr["converted_at"]} if conv else {})})
    return d, events, billing, overlay, sysinfo


def sample_snapshot(now=None, window=30):
    now = now or utcnow()
    return build(*sample_inputs(now), now=now, window=window, sample=True)


def embed_sample(path=ADMIN_HTML, lead_rows=60):
    snaps = {str(w): sample_snapshot(window=w) for w in WINDOWS}
    for s in snaps.values():                                  # keep the page light: the sample needs a screenful of leads
        s["leads"]["rows"] = s["leads"]["rows"][:lead_rows]
        s["leads"]["shown"] = len(s["leads"]["rows"])
    blob = ap.embed_json(snaps)
    html = Path(path).read_text()
    new, n = re.subn(r'(<script id="sample-snapshot" type="application/json">).*?(</script>)',
                     lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    if not n:
        raise SystemExit("admin.html has no <script id=\"sample-snapshot\"> block")
    ap._atomic_write(path, new)
    return len(blob)


# ============================================================================================
# CLI
# ============================================================================================

def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def main(a):
    cmd = a[0] if a else ""
    who = "cli:" + (os.environ.get("USER") or "owner")
    if cmd == "snapshot":
        s = snapshot(window=int(_opt(a, "--days", 30)))
        if "--json" in a:
            print(json.dumps(s, ensure_ascii=False, indent=1))
            return
        k = s["kpis"]
        print(f"Otto · last {s['window']} days · {s['range']['from']} → {s['range']['to']}")
        for key in ("visitors", "scans", "leads", "customers", "mrr", "churn"):
            x = k[key]
            dp = f"{x['delta_pct']:+.0f}%" if x["delta_pct"] is not None else "—"
            print(f"  {x['label']:18} {x['value']:>10,.2f}  ({dp} vs previous)" if key == "mrr" else f"  {x['label']:18} {x['value']:>10,}  ({dp})")
        print("  funnel: " + " → ".join(f"{st['label']} {st['n']}" for st in s["funnel"]["steps"]))
        for b in s["brands"]:
            print(f"  [{b['health']:9}] {b['name']:24} " + ("; ".join(b["issues"]) or "fine"))
        if s["kill_switch"]:
            print(f"  KILL SWITCH ON since {s['kill_switch'].get('at')} by {s['kill_switch'].get('by')}")
    elif cmd == "sample":
        if "--embed" in a:
            print(f"sample embedded into {ADMIN_HTML.name} ({embed_sample() // 1024} KB)")
        else:
            print(json.dumps(sample_snapshot(window=int(_opt(a, "--days", 30))), ensure_ascii=False, indent=1))
    elif cmd == "kill":
        print(act({"action": "kill_switch", "state": a[1], "note": _opt(a, "--note")}, who)["message"])
    elif cmd in ("pause", "resume"):
        print(act({"action": f"{cmd}_brand", "brand": a[1], "note": _opt(a, "--note")}, who)["message"])
    elif cmd == "activate":
        print(act({"action": "activate", "brand": a[1], "note": _opt(a, "--note")}, who)["message"])
    elif cmd == "campaign":
        print(act({"action": "campaign", "id": a[1], "decision": a[2], "note": _opt(a, "--note")}, who)["message"])
    elif cmd == "rescan":
        print(act({"action": "rescan", "brand": a[1]}, who)["message"])
    elif cmd == "lead":
        req = {"action": "lead", "id": a[1], "status": a[2]}
        if "--note" in a:
            req["note"] = _opt(a, "--note")                   # --note "" clears it; no --note keeps it
        print(act(req, who)["message"])
    elif cmd == "members":
        split = lambda k: [x for x in (_opt(a, k) or "").split(",") if x.strip()]
        print(act({"action": "members", "brand": a[1], "add": split("--add"), "remove": split("--remove")}, who)["message"])
    elif cmd == "plan" and len(a) > 2:
        req = {"action": "plan", "brand": a[1], "plan": a[2], "note": _opt(a, "--note")}
        if "--until" in a:
            req["until"] = _opt(a, "--until") or ""
        print(act(req, who)["message"])
    elif cmd == "plans":
        cat = plans_catalogue()
        if cat["error"]:
            print(f"plans.json cannot be used: {cat['error']}")
        for p in cat["items"]:
            L = p["limits"]
            print(f"{p['id']:9} {p['label']:16} {'paid ads' if p['paid_ads'] else 'organic ':8}  posts {L['posts_per_month']} · reels "
                  f"{L['reels_per_month']} · matrix {L['ad_matrix_preset']} · ad cap €{L['ad_spend_managed_eur_month']} · brands {L['brands']}")
        try:
            d = clean_state(ap.load())
        except (OSError, ValueError) as e:
            print(f"(no brands: {ap.DATA.name} cannot be read — {type(e).__name__})")
            d = clean_state({})
        for b in d["brands"]:
            v = ap.plan_view(d, b["id"])
            u = v["usage"]
            print(f"  {b['id']:16} {v['label']:16} ({v['source']}{', until ' + v['until'] if v['until'] else ''})  posts "
                  f"{u['posts']['used']}/{u['posts']['limit']} · reels {u['reels']['used']}/{u['reels']['limit']}"
                  + (f" · ads €{u['ad_budget_eur']['used']:,.0f}/{u['ad_budget_eur']['limit']}" if "ad_budget_eur" in u else ""))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
