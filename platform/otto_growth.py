#!/usr/bin/env python3
"""Otto growth ledger — every marketing number in one place, month over month.

  otto_growth.py rollup [--send]        # recompute growth[brand] in data.json (cron daily 05:10); --send = last month's review to Telegram
                                        # (once per month: markers.growth_review_sent guards re-runs)
  otto_growth.py show [brand]           # print the table

Sources (all already in the loop):
  organic  posts[].metrics (reach, saves, likes, comments, clicks) per published post → attributed to its month
  paid     ads[brand].daily[date].meta/google.yesterday (spend, results, clicks) → attributed to the day before the report.
           Meta results (leads/purchases by objective) and Google conversions are kept apart (results_meta /
           results_google); "results" is their labelled sum, never an unlabelled mix in the review text.
  audience metrics_history.jsonl daily snapshots (followers, 7-day reach) — end-of-month level + daily series
  effort   posts published, owner decisions (taste_log) per month
Writes growth[brand] = {"started", "months": {YYYY-MM: {...}}, "mom": {...pct}, "best_pillar", "daily": [...90 days], "review": "<text>",
                         "currency"}  — money in the brand currency (brands[].currency → scan → EUR). Owner decisions are kept in
the data (months[].decisions) but are not a growth KPI and are not in the review headline.
Mission Control renders it as the Growth section; the 1st-of-month review goes to the owner as one message.
"""
import json, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap

HERE = Path(__file__).parent
MARKER = "growth_review_sent"
SENDING = "growth_review_sending"                   # claim while the message is on its way (a parallel run stops)
HIST = ap.DATA.parent / "metrics_history.jsonl"      # written by otto_watch next to data.json


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
    M = {k: {"reach": 0, "engagement": 0, "clicks": 0, "posts": 0, "followers": None, "spend": 0.0, "results": 0.0,
             "results_meta": 0.0, "results_google": 0.0, "results_label": "Meta leads/purchases + Google conversions",
             "cpl": None, "decisions": 0, "by_pillar": {}} for k in keys}
    n = lambda v: ap.num(v) or 0
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
        M[k]["reach"] += n(m.get("reach"))
        M[k]["engagement"] += n(m.get("saves")) + n(m.get("likes")) + n(m.get("comments")) + n(m.get("shares"))
        M[k]["clicks"] += n(m.get("clicks"))
        bp = M[k]["by_pillar"].setdefault(p.get("pillar", "?"), {"reach": 0, "posts": 0})
        bp["reach"] += n(m.get("reach")); bp["posts"] += 1
    for t in d.get("taste_log", []):
        if t.get("brand") == bid and ym_of(t.get("ts")) in M:
            M[ym_of(t["ts"])]["decisions"] += 1
    daily = {}
    for dt, entry in sorted((d.get("ads", {}).get(bid, {}).get("daily") or {}).items()):
        day = (date.fromisoformat(dt) - timedelta(days=1)).isoformat()      # the report is about "yesterday"
        spend = clicks = 0.0
        res = {"meta": 0.0, "google": 0.0}
        for net in ("meta", "google"):
            y = ((entry or {}).get(net) or {}).get("yesterday") or {}
            spend += n(y.get("spend")); res[net] += n(y.get("results")); clicks += n(y.get("clicks"))
        daily[day] = {"spend": round(spend, 2), "results": res["meta"] + res["google"], "results_meta": res["meta"],
                      "results_google": res["google"], "clicks": clicks}
        k = day[:7]
        if k in M:
            M[k]["spend"] += spend; M[k]["results"] += res["meta"] + res["google"]
            M[k]["results_meta"] += res["meta"]; M[k]["results_google"] += res["google"]
    for r in hist:
        mb = (r.get("metrics") or {}).get(bid) or {}
        k = ym_of(r.get("date"))
        if k in M and ap.num(mb.get("followers")) is not None:
            M[k]["followers"] = ap.num(mb["followers"])            # last snapshot of the month wins
        if r.get("date"):
            daily.setdefault(r["date"], {})["reach7"] = ap.num(mb.get("reach"))
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
         "best_pillar": cur["best_pillar"] or prev["best_pillar"], "daily": series, "updated_at": ap.now_iso(),
         "currency": ap.brand_currency(d, bid)}
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


def review_text(b, g, month_key=None):
    """month_key None → the current month "so far"; the previous month key → "<Month> in review" (compared with the one before)."""
    mk = month_key or g["current"]
    keys = sorted(g["months"])
    c = g["months"][mk]
    prev_key = keys[keys.index(mk) - 1] if keys.index(mk) > 0 else None
    p = g["months"].get(prev_key) or {}
    mom = g["mom"] if mk == g["current"] else _mom(c, p)
    cur = g.get("currency") or "EUR"
    month = datetime.strptime(mk, "%Y-%m").strftime("%B")
    lines = [f"📈 {month} {'so far' if mk == g['current'] else 'in review'} · {b['name']}"]
    lines.append(f"Posts published {c['posts']} ({arrow(mom['posts'], '')}) · reach {c['reach']:,} ({arrow(mom['reach'])}) · engagement {c['engagement']:,} ({arrow(mom['engagement'])})")
    if c["followers"] is not None:
        lines.append(f"Followers {c['followers']:,}" + (f" ({arrow(mom['followers'], '')})" if mom["followers"] is not None else ""))
    if c["spend"]:
        parts = []
        if c.get("results_meta"):
            parts.append(f"{c['results_meta']:.0f} Meta leads/purchases")
        if c.get("results_google"):
            parts.append(f"{c['results_google']:.0f} Google conversions")
        if c["cpl"]:
            lines.append(f"Paid {ap.money(c['spend'], cur)} → {' + '.join(parts) or 'no results yet'} · cost per result {ap.money(c['cpl'], cur, 1)}"
                         + (f" ({arrow(mom['cpl'], cpl=True)})" if mom.get("cpl") is not None else ""))
        else:
            lines.append(f"Paid {ap.money(c['spend'], cur)} → no results yet")
    best = c.get("best_pillar") if mk != g["current"] else g["best_pillar"]
    if best:
        lines.append(f"Best pillar: {best}")
    return "\n".join(lines)


def _mom(cur, prev):
    return {"reach": pct(cur.get("reach"), prev.get("reach")), "engagement": pct(cur.get("engagement"), prev.get("engagement")),
            "clicks": pct(cur.get("clicks"), prev.get("clicks")), "posts": (cur.get("posts") or 0) - (prev.get("posts") or 0),
            "followers": (cur["followers"] - prev["followers"]) if cur.get("followers") is not None and prev.get("followers") is not None else None,
            "spend": pct(cur.get("spend"), prev.get("spend")), "results": pct(cur.get("results"), prev.get("results")),
            "cpl": pct(cur.get("cpl"), prev.get("cpl"), invert=True) if cur.get("cpl") and prev.get("cpl") else None}


def rollup(send=False):
    hist = history()
    with ap.transaction() as d:                     # pure computation — short enough to hold the lock
        d["growth"] = {b["id"]: rollup_brand(d, b["id"], hist) for b in d.get("brands", [])}
        growth = d["growth"]
        names = {b["id"]: b for b in d.get("brands", [])}
        sent_for = (d.get("markers") or {}).get(MARKER)
    for bid, g in growth.items():
        print(g["review"]); print()
    if not send:
        return
    month = next(iter(growth.values()))["previous"] if growth else None
    if not month:
        return
    if sent_for == month:
        print(f"month-in-review for {month} already sent — not sending again"); return
    with ap.transaction() as d:                     # claim: two rollup --send at once must not both send
        mk = d.setdefault("markers", {})
        since = ap.parse_iso(mk.get(SENDING))
        busy = mk.get(MARKER) == month or bool(since and since.tzinfo and datetime.now(timezone.utc) - since < timedelta(minutes=10))
        if not busy:
            mk[SENDING] = ap.now_iso()
    if busy:
        print(f"month-in-review for {month} already sent or being sent by another run — not sending"); return
    text = "\n\n".join(review_text(names.get(bid) or {"name": bid}, g, month) for bid, g in growth.items())
    try:
        import otto_ads
        ok = otto_ads.notify(text)
    except Exception as e:
        ok = False
        print("send failed:", e)
    with ap.transaction() as d:
        mk = d.setdefault("markers", {})
        mk.pop(SENDING, None)
        if ok:
            mk[MARKER] = month
    if ok:
        print(f"month-in-review for {month} sent")


def show(bid=None):
    d = ap.load()
    for b, g in (d.get("growth") or {}).items():
        if bid and b != bid:
            continue
        print(f"== {b} · since {g.get('started') or '—'} · best pillar {g.get('best_pillar') or '—'}")
        print(f"{'month':8} {'posts':>5} {'reach':>8} {'engag':>6} {'clicks':>6} {'follow':>7} {'spend':>8} {'results':>7} {'cpl':>6} {'decis':>5}")
        for k, m in g["months"].items():
            print(f"{k:8} {int(m['posts']):5d} {int(m['reach']):8,d} {int(m['engagement']):6,d} {int(m['clicks']):6,d} {str(m['followers'] or '—'):>7} {m['spend']:8,.0f} {m['results']:7.0f} {str(m['cpl'] or '—'):>6} {m['decisions']:5d}")
        print("MoM:", json.dumps(g["mom"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "rollup":
        rollup(send="--send" in a)
    elif a and a[0] == "show":
        show(a[1] if len(a) > 1 else None)
    else:
        print(__doc__)
