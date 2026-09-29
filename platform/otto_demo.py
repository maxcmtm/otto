#!/usr/bin/env python3
"""Otto client-journey demo data — what happens to a business in its first 90 days with Otto.

  otto_demo.py journey <brand> [--days 90] [--seed 7] [--out demo/<brand>-journey.json]

Builds ONE JSON the demo page renders: the onboarding facts are REAL (scan.json, strategy.json,
competitors.json, the brand's posts and reel in data.json); everything after launch day is a SIMULATION
from stated assumptions (the page must label it "simulated" and show the assumptions). No fabricated
reviews, no invented customer names, no claims about the brand that are not in its files.

Model (per day): organic reach = followers × base_rate × format multiplier (reel 3.2×, carousel 1.6×,
post 1×, story 0.35× of story viewers) × learning lift (winners loop: +0.6%/day compounding, capped +45%);
followers grow with reach × follow_rate; site clicks = reach × ctr_org + paid clicks; paid starts on
day `paid_start` at `budget`/day with CPC drifting down as the CPL guard prunes losers; orders = clicks ×
cvr; revenue = orders × aov. Assumptions are brand-tunable in the "assumptions" block.
"""
import json, math, random, sys
from datetime import date, timedelta
from pathlib import Path

import ap

HERE = Path(__file__).parent
REPO = HERE.parent
BRANDS = ap.BRANDS                                   # OTTO_BRANDS

DEFAULTS = {
    "happygarden": {"followers": 1200, "base_rate": 0.18, "follow_rate": 0.0035, "ctr_org": 0.006, "paid_start": 31,
                    "budget": 20.0, "cpc": 0.55, "cpc_floor": 0.38, "cvr": 0.021, "aov": 58.0, "currency": "€",
                    "paid_note": "CBD is a restricted category on Meta: month 1 is organic-only; month 2 adds a compliant traffic campaign to an educational landing page."},
    "cmtm": {"followers": 9800, "base_rate": 0.12, "follow_rate": 0.002, "ctr_org": 0.004, "paid_start": 8,
             "budget": 120.0, "cpc": 1.9, "cpc_floor": 1.3, "cvr": 0.09, "aov": 0.0, "currency": "₪",
             "paid_note": "Leads (webinar sign-ups) instead of orders; CPL target from the brand's winning-ads history (₪44)."},
}
# any other brand: neutral assumptions, the brand's own currency, no category-specific claims
GENERIC = {"followers": 800, "base_rate": 0.15, "follow_rate": 0.003, "ctr_org": 0.005, "paid_start": 15, "budget": 20.0,
           "cpc": 0.8, "cpc_floor": 0.5, "cvr": 0.03, "aov": 0.0, "currency": None,
           "paid_note": "Paid starts mid-month 1, once the first organic winners are known; every flight has a daily ceiling and a CPL guard."}


def load(p, d):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def journey(bid, days=90, seed=7, out=None):
    rnd = random.Random(seed)
    scan = load(BRANDS / bid / "scan.json", {})
    strat = load(BRANDS / bid / "strategy.json", {})
    comps = load(BRANDS / bid / "competitors.json", [])
    data = load(ap.DATA, None) or {}                 # OTTO_DATA; the dashboard's fallback block (OTTO_HTML) when absent
    if not data and ap.HTML.exists():
        import re
        m = re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', ap.HTML.read_text(), re.S)
        data = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
    A = dict(DEFAULTS.get(bid) or GENERIC)
    if not A["currency"]:
        A["currency"] = ap.currency_symbol(ap.brand_currency(data, bid)).strip()
    brand = next((b for b in data.get("brands", []) if b["id"] == bid), {"id": bid, "name": bid})
    posts = [p for p in data.get("posts", []) if p.get("brand") == bid]
    plans = sorted({p["plan"] for p in posts if p.get("plan")})
    month1 = [p for p in posts if plans and p.get("plan") == plans[0]]
    start = date(2026, 10, 1)
    # posting cadence: 12 feed posts/week (4:4:2 post/carousel/reel mix ≈ what otto_plan produces) + 3 stories
    week_pattern = ["post", "carousel", "post", "reel", "carousel", "post", "post", "carousel", "post", "reel", "post", "carousel"]
    followers = float(A["followers"])
    lift = 1.0
    cpc = A["cpc"]
    series, events = [], []
    k = 0
    for i in range(days):
        day = start + timedelta(days=i)
        n_posts = 2 if day.weekday() < 5 else 1
        fmts = [week_pattern[(k + j) % len(week_pattern)] for j in range(n_posts)]; k += n_posts
        mult = {"post": 1.0, "carousel": 1.6, "reel": 3.2}
        reach = sum(followers * A["base_rate"] * mult[f] * lift * rnd.uniform(0.75, 1.3) for f in fmts)
        if day.weekday() in (0, 2, 4):
            reach += followers * 0.22 * 0.35 * rnd.uniform(0.8, 1.2)          # story
        new_f = reach * A["follow_rate"] * rnd.uniform(0.8, 1.2)
        followers += new_f
        clicks_org = reach * A["ctr_org"] * rnd.uniform(0.85, 1.15)
        paid = i + 1 >= A["paid_start"]
        spend = A["budget"] * rnd.uniform(0.92, 1.0) if paid else 0.0
        if paid:
            cpc = max(A["cpc_floor"], cpc * 0.996)                              # guard prunes losers, winners scale
        clicks_paid = spend / cpc if paid else 0.0
        conv = (clicks_org + clicks_paid) * A["cvr"] * rnd.uniform(0.8, 1.2)
        revenue = conv * A["aov"]
        lift = min(1.45, lift * 1.006)
        series.append({"date": day.isoformat(), "reach": round(reach), "followers": round(followers), "clicks": round(clicks_org + clicks_paid),
                       "spend": round(spend, 2), "results": round(conv, 2), "revenue": round(revenue, 2), "posts": n_posts, "formats": fmts})
    def month(m):
        rows = [r for r in series if r["date"][5:7] == f"{m:02d}"]
        if not rows:
            return None
        return {"month": rows[0]["date"][:7], "reach": sum(r["reach"] for r in rows), "followers_end": rows[-1]["followers"],
                "clicks": sum(r["clicks"] for r in rows), "spend": round(sum(r["spend"] for r in rows), 2),
                "results": round(sum(r["results"] for r in rows)), "revenue": round(sum(r["revenue"] for r in rows)),
                "posts": sum(r["posts"] for r in rows), "reels": sum(r["formats"].count("reel") for r in rows)}
    months = [m for m in (month(10), month(11), month(12)) if m]
    events = [
        {"day": 0, "title": "Drops the URL", "what": f"Otto reads {scan.get('final_url', brand.get('url', ''))}: {len(scan.get('pages', []))} pages, palette {', '.join(c['hex'] for c in scan.get('visual', {}).get('palette', [])[:3])}, industry {scan.get('industry', '—')}.", "real": True},
        {"day": 0, "title": "Answers the open questions", "what": " · ".join(strat.get("ask", [])[:4]) or "At most four questions.", "real": True},
        {"day": 1, "title": "Competitors mapped", "what": ", ".join(c["name"] for c in comps[:6]) or "Competitor list from the profile.", "real": True},
        {"day": 1, "title": "The month is planned",
         "what": (f"{sum(1 for p in month1 if p.get('format') not in ('story', 'reel'))} feed posts, "
                  f"{sum(1 for p in month1 if p.get('format') == 'story')} stories, {sum(1 for p in month1 if p.get('format') == 'reel')} "
                  f"explainer reels across {len({p.get('pillar') for p in month1})} pillars, slotted to the audience's hours.")
         if month1 else "A month of feed posts, stories and explainer reels across the brand's pillars.", "real": bool(month1)},
        {"day": 2, "title": "First approval cards in Telegram", "what": f"{min(4, len(posts))} posts with visuals; one tap each.", "real": True},
        {"day": 3, "title": "First reel", "what": "A 57-second motion-design explainer, scripted from the brand profile and voiced.", "real": True},
        {"day": 7, "title": "First morning report", "what": "What went out, what performed, what is waiting.", "real": False},
        {"day": 14, "title": "First winner", "what": "Education carousels outperform product posts; next week's plan shifts toward them.", "real": False},
        {"day": A["paid_start"] - 1, "title": "Paid plan approved", "what": A["paid_note"], "real": False},
        {"day": 45, "title": "Competitor sweep flags a price move", "what": "Otto proposes a bundle post the same week (one tap).", "real": False},
        {"day": 60, "title": "Month in review", "what": "Reach, followers, clicks, orders — month over month, in one message.", "real": False},
        {"day": 89, "title": "Quarter closes", "what": "Plan for the next quarter built from what won.", "real": False},
    ]
    outp = Path(out) if out else REPO / "demo" / f"{bid}-journey.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    doc = {"brand": {"id": bid, "name": brand.get("name"), "url": brand.get("url")}, "simulated_from_day": 4,
           "assumptions": A, "disclaimer": "Days 0–3 are Otto's real outputs for this brand. Everything after is a simulation from the stated assumptions, not a promise of results.",
           "events": events, "months": months, "series": series,
           "real": {"scan": {k: scan.get(k) for k in ("final_url", "industry", "languages", "platform")},
                    "palette": [c["hex"] for c in scan.get("visual", {}).get("palette", [])[:5]],
                    "posts": [{k: p.get(k) for k in ("id", "hook", "caption", "platform", "pillar", "image", "format")} for p in posts[:8]],
                    "competitors": [c.get("name") for c in comps[:8]], "ask": strat.get("ask", [])}}
    outp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    m = months
    print(f"{bid}: {days} days → {outp}")
    for x in m:
        print(f"  {x['month']}: reach {x['reach']:,} · followers {x['followers_end']:,} · clicks {x['clicks']:,} · spend {A['currency']}{x['spend']:,.0f} · results {x['results']} · revenue {A['currency']}{x['revenue']:,}")
    return doc


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "journey":
        journey(a[1], int(a[a.index("--days") + 1]) if "--days" in a else 90, int(a[a.index("--seed") + 1]) if "--seed" in a else 7,
                a[a.index("--out") + 1] if "--out" in a else None)
    else:
        print(__doc__)
