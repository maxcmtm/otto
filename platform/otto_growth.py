#!/usr/bin/env python3
"""Otto growth ledger — every marketing number in one place, month over month.

  otto_growth.py rollup [--send]        # recompute growth[brand] in data.json (cron daily 05:10); --send = month-in-review to Telegram (1st of month)
  otto_growth.py show [brand]           # print the table

Sources (all already in the loop):
  organic  posts[].metrics (reach, saves, likes, comments, clicks) per published post → attributed to its month
  paid     ads[brand].daily[date].meta/google.yesterday (spend, results, clicks) → attributed to the day before the report
  audience metrics_history.jsonl daily snapshots (followers, 7-day reach) — end-of-month level + daily series
  effort   posts published, owner decisions (taste_log) per month
Writes growth[brand] = {"started", "months": {YYYY-MM: {...}}, "mom": {...pct}, "best_pillar", "daily": [...90 days], "review": "<text>"}
Mission Control renders it as the Growth section; the 1st-of-month review goes to the owner as one message.
"""
import json, sys
from datetime import date, datetime, timedelta
from pathlib import Path

import ap

HERE = Path(__file__).parent
HIST = HERE / "metrics_history.jsonl"
KEYS = ["reach", "engagement", "clicks", "posts", "followers", "spend", "results", "cpl", "decisions"]


def ym_of(iso):
    return (iso or "")[:7]


def month_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def history():
    rows = []
    if HIST.exists():
        for line in HIST.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def pct(cur, prev, invert=False):
    if prev in (None, 0) or cur is None:
        return None
    p = (cur - prev) / prev * 100
    return round(-p if invert else p, 1)


def rollup_brand(d, bid, hist, months=6):
    this = date.today().isoformat()[:7]
    keys = [month_add(this, -i) for i in range(months - 1, -1, -1)]
    M = {k: {"reach": 0, "engagement": 0, "clicks": 0, "posts": 0, "followers": None, "spend": 0.0, "results": 0.0, "cpl": None,
             "decisions": 0, "by_pillar": {}} for k in keys}
    started = None
    for p in d.get("posts", []):
        if p.get("brand") != bid or p.get("status") != "published":
            continue
        when = p.get("published_at") or p.get("slot")
        started = min(started, when) if started else when
        k = ym_of(when)
        if k not in M:
            continue
        m = p.get("metrics") or {}
        M[k]["posts"] += 1
        M[k]["reach"] += m.get("reach", 0) or 0
        M[k]["engagement"] += (m.get("saves", 0) or 0) + (m.get("likes", 0) or 0) + (m.get("comments", 0) or 0) + (m.get("shares", 0) or 0)
        M[k]["clicks"] += m.get("clicks", 0) or 0
        bp = M[k]["by_pillar"].setdefault(p.get("pillar", "?"), {"reach": 0, "posts": 0})
        bp["reach"] += m.get("reach", 0) or 0; bp["posts"] += 1
    for t in d.get("taste_log", []):
        if t.get("brand") == bid and ym_of(t.get("ts")) in M:
            M[ym_of(t["ts"])]["decisions"] += 1
    daily = {}
    for dt, entry in sorted((d.get("ads", {}).get(bid, {}).get("daily") or {}).items()):
        day = (date.fromisoformat(dt) - timedelta(days=1)).isoformat()      # the report is about "yesterday"
        spend = res = clicks = 0.0
        for net in ("meta", "google"):
            y = ((entry or {}).get(net) or {}).get("yesterday") or {}
            spend += y.get("spend", 0) or 0; res += y.get("results", 0) or 0; clicks += y.get("clicks", 0) or 0
        daily[day] = {"spend": round(spend, 2), "results": res, "clicks": clicks}
        k = day[:7]
        if k in M:
            M[k]["spend"] += spend; M[k]["results"] += res
    for r in hist:
        mb = (r.get("metrics") or {}).get(bid) or {}
        k = ym_of(r.get("date"))
        if k in M and mb.get("followers") is not None:
            M[k]["followers"] = mb["followers"]                   # last snapshot of the month wins
        daily.setdefault(r.get("date"), {})["reach7"] = mb.get("reach")
    for k, m in M.items():
        m["spend"] = round(m["spend"], 2)
        m["cpl"] = round(m["spend"] / m["results"], 2) if m["results"] else None
        m["best_pillar"] = max(m["by_pillar"], key=lambda x: m["by_pillar"][x]["reach"]) if m["by_pillar"] else None
    cur, prev = M[keys[-1]], M[keys[-2]]
    mom = {"reach": pct(cur["reach"], prev["reach"]), "engagement": pct(cur["engagement"], prev["engagement"]),
           "clicks": pct(cur["clicks"], prev["clicks"]), "posts": cur["posts"] - prev["posts"],
           "followers": (cur["followers"] - prev["followers"]) if cur["followers"] is not None and prev["followers"] is not None else None,
           "spend": pct(cur["spend"], prev["spend"]), "results": pct(cur["results"], prev["results"]),
           "cpl": pct(cur["cpl"], prev["cpl"], invert=True) if cur["cpl"] and prev["cpl"] else None,
           "decisions": cur["decisions"] - prev["decisions"]}
    series = [dict(dt=k, **v) for k, v in sorted(daily.items())][-90:]
    g = {"started": started, "months": M, "current": keys[-1], "previous": keys[-2], "mom": mom,
         "best_pillar": cur["best_pillar"] or prev["best_pillar"], "daily": series, "updated_at": ap.now_iso()}
    g["review"] = review_text(ap.brand(d, bid) or {"name": bid}, g)
    return g


def arrow(v, suffix="%", cpl=False):
    """▲ +38% · ▼ -12% · '· same' for 0 · CPL: '▲ 14% better' / '▼ 9% worse' (otto_growth stores CPL change as improvement %)."""
    if v is None:
        return "—"
    if v == 0:
        return "· same"
    good = v > 0
    if cpl:
        return f"{'▲' if good else '▼'} {abs(v):.0f}% {'better' if good else 'worse'}"
    return f"{'▲' if good else '▼'} {v:+.0f}{suffix}" if suffix == "%" else f"{'▲' if good else '▼'} {v:+d}"


def review_text(b, g):
    c, p, mom = g["months"][g["current"]], g["months"][g["previous"]], g["mom"]
    cur = "€"
    month = datetime.strptime(g["current"], "%Y-%m").strftime("%B")
    lines = [f"📈 {month} so far · {b['name']}"]
    lines.append(f"Posts published {c['posts']} ({arrow(mom['posts'], '')}) · reach {c['reach']:,} ({arrow(mom['reach'])}) · engagement {c['engagement']:,} ({arrow(mom['engagement'])})")
    if c["followers"] is not None:
        lines.append(f"Followers {c['followers']:,}" + (f" ({arrow(mom['followers'], '')})" if mom["followers"] is not None else ""))
    if c["spend"]:
        lines.append(f"Paid {cur}{c['spend']:,.0f} → {c['results']:.0f} results · CPL {cur}{c['cpl']:.1f}" + (f" ({arrow(mom['cpl'], cpl=True)})" if mom["cpl"] is not None else "") if c["cpl"] else f"Paid {cur}{c['spend']:,.0f} → no results yet")
    if g["best_pillar"]:
        lines.append(f"Best pillar: {g['best_pillar']}")
    lines.append(f"You made {c['decisions']} decisions this month.")
    return "\n".join(lines)


def rollup(send=False):
    d = ap.load()
    hist = history()
    d["growth"] = {b["id"]: rollup_brand(d, b["id"], hist) for b in d.get("brands", [])}
    ap.save(d)
    for bid, g in d["growth"].items():
        print(g["review"]); print()
    if send:
        try:
            import otto_ads
            otto_ads.notify("\n\n".join(g["review"] for g in d["growth"].values()))
        except Exception as e:
            print("send failed:", e)


def show(bid=None):
    d = ap.load()
    for b, g in (d.get("growth") or {}).items():
        if bid and b != bid:
            continue
        print(f"== {b} · since {g.get('started') or '—'} · best pillar {g.get('best_pillar') or '—'}")
        print(f"{'month':8} {'posts':>5} {'reach':>8} {'engag':>6} {'clicks':>6} {'follow':>7} {'spend':>8} {'results':>7} {'cpl':>6} {'decis':>5}")
        for k, m in g["months"].items():
            print(f"{k:8} {m['posts']:5d} {m['reach']:8,d} {m['engagement']:6,d} {m['clicks']:6,d} {str(m['followers'] or '—'):>7} {m['spend']:8,.0f} {m['results']:7.0f} {str(m['cpl'] or '—'):>6} {m['decisions']:5d}")
        print("MoM:", json.dumps(g["mom"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "rollup":
        rollup(send="--send" in a)
    elif a and a[0] == "show":
        show(a[1] if len(a) > 1 else None)
    else:
        print(__doc__)
