#!/usr/bin/env python3
"""Otto insights loop — weekly analytics → winners → next-batch recommendations (M6 analytics loop).

  otto_insights.py [--dry] [--brand <id>] [--days 7]

For every brand with Meta credentials ($OTTO_SECRETS/meta-<brand>.json):
  1. Pulls page-level reach/engagement/followers and per-post metrics (reach, clicks, saves,
     likes, comments) for posts published in the last --days via the Graph API.
  2. Writes them into data.json (posts[].metrics, metrics[brand]) so Mission Control and
     otto_watch (drop alerts, morning report) see real numbers.
  3. Ranks the winners (reach + 10×saves + 5×clicks), writes brands/<slug>/winning-posts.md
     and files a P1 recommendation "Double down on <pillar>" — the loop that teaches the next batch.
     Re-running never stacks a second identical proposed card (ap.add_rec_once).
Metrics: only numeric values are kept. Deprecated / unavailable Graph metrics are requested one by one
with fallbacks (post_engaged_users dropped; followers from the page's followers_count field; stories
never ask for saved/likes), so one retired metric does not blank the whole pull.
All Graph calls happen outside the data lock; the results are patched in one short ap.transaction.
--dry: no API calls; ranks whatever metrics already exist in data.json.
"""
import sys
from datetime import datetime, timedelta, timezone

import ap
import otto_publish as pub

BRANDS = ap.BRANDS
IG_FEED_METRICS = ["reach", "saved", "likes", "comments", "shares"]
IG_STORY_METRICS = ["reach", "replies"]


def _n(v):
    return ap.num(v) or 0


def _utc(s):
    dt = ap.parse_iso(s)
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def score(m):
    return _n(m.get("reach")) + 10 * _n(m.get("saves")) + 5 * _n(m.get("clicks")) + 2 * _n(m.get("comments"))


def _values(rows):
    """Graph insights rows → {name: number}; non-numeric values (dicts, strings, None) are skipped."""
    out = {}
    for i in rows or []:
        vals = i.get("values") or []
        v = ap.num(vals[-1].get("value")) if vals else ap.num(i.get("total_value", {}).get("value"))
        if v is not None:
            out[i.get("name")] = v
    return out


def pull_post(p, c):
    rid = p.get("remote_id")
    if not rid:
        return None
    tok = c["access_token"]
    if p["platform"] == "fb":
        vals = {}
        # post_impressions_unique / post_clicks: still documented for v25 but on Meta's deprecation track —
        # asked separately so a retired one only loses itself; engagement falls back to the post's own counters.
        for metric in ("post_impressions_unique", "post_clicks"):
            try:
                r = pub.graph("GET", f"{rid}/insights", tok, metric=metric)
                vals.update(_values(r.get("data")))
            except pub.GraphError:
                pass
        out = {"reach": vals.get("post_impressions_unique"), "clicks": vals.get("post_clicks")}
        try:
            r = pub.graph("GET", rid, tok, fields="shares,comments.summary(true).limit(0),reactions.summary(true).limit(0)")
            out["shares"] = ap.num((r.get("shares") or {}).get("count"))
            out["comments"] = ap.num(((r.get("comments") or {}).get("summary") or {}).get("total_count"))
            out["likes"] = ap.num(((r.get("reactions") or {}).get("summary") or {}).get("total_count"))
        except pub.GraphError:
            pass
        return {k: v for k, v in out.items() if v is not None}
    metrics = IG_STORY_METRICS if p.get("format") == "story" else IG_FEED_METRICS
    try:
        r = pub.graph("GET", f"{rid}/insights", tok, metric=",".join(metrics))
        vals = _values(r.get("data"))
    except pub.GraphError:
        vals = {}
        for metric in metrics:                       # one bad metric must not blank the rest
            try:
                vals.update(_values(pub.graph("GET", f"{rid}/insights", tok, metric=metric).get("data")))
            except pub.GraphError:
                pass
    out = {"reach": vals.get("reach"), "saves": vals.get("saved"), "likes": vals.get("likes"),
           "comments": vals.get("comments"), "shares": vals.get("shares"), "replies": vals.get("replies")}
    return {k: v for k, v in out.items() if v is not None}


def pull_page(c):
    out = {}
    tok, page = c["access_token"], c["page_id"]
    for metric in ("page_impressions_unique", "page_post_engagements"):
        try:
            r = pub.graph("GET", f"{page}/insights", tok, metric=metric, period="week")
            out.update(_values(r.get("data")))
        except pub.GraphError as e:
            out.setdefault("errors", []).append(f"{metric}: {str(e)[:80]}")
    try:
        r = pub.graph("GET", page, tok, fields="followers_count,fan_count")
        f = ap.num(r.get("followers_count"))
        out["followers"] = f if f is not None else ap.num(r.get("fan_count"))
    except pub.GraphError as e:
        out.setdefault("errors", []).append(f"followers: {str(e)[:80]}")
    return out


def run(dry=False, bid=None, days=7):
    snap = ap.load()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pulled = {}                                     # brand -> {"page":…, "posts": {id: metrics}}
    for b in snap["brands"]:
        if bid and b["id"] != bid:
            continue
        c = None if dry else pub.creds(b["id"])
        posts = [p for p in snap["posts"] if p["brand"] == b["id"] and p["status"] == "published"]
        recent = [p for p in posts if (_utc(p.get("published_at")) or since - timedelta(days=1)) >= since]
        if c:
            got = {"page": pull_page(c), "posts": {}}
            for p in recent:
                try:
                    m = pull_post(p, c)
                    if m is not None:
                        m["pulled_at"] = ap.now_iso(); got["posts"][p["id"]] = m
                except pub.GraphError as e:
                    got["posts"][p["id"]] = {"error": str(e)}
                except Exception as e:
                    got["posts"][p["id"]] = {"error": f"{type(e).__name__}: {e}"[:200]}
            pulled[b["id"]] = got
        elif not dry:
            print(f"{b['id']}: no credentials (meta-{b['id']}.json) — skipped")

    def apply(d):
        for b in d["brands"]:
            if bid and b["id"] != bid:
                continue
            got = pulled.get(b["id"])
            posts = [p for p in d["posts"] if p["brand"] == b["id"] and p["status"] == "published"]
            if got:
                for pid, m in got["posts"].items():
                    q = ap.post(d, pid)
                    if q is None:
                        continue
                    if "error" in m:
                        q.setdefault("metrics", {})["error"] = m["error"]
                    else:
                        q["metrics"] = m
                recent = [p for p in posts if p["id"] in got["posts"]]
                page = got["page"]
                prev = d.get("metrics", {}).get(b["id"], {})
                tot = {"reach": sum(_n((p.get("metrics") or {}).get("reach")) for p in recent),
                       "saves": sum(_n((p.get("metrics") or {}).get("saves")) for p in recent),
                       "clicks": sum(_n((p.get("metrics") or {}).get("clicks")) for p in recent),
                       "leads": _n(prev.get("leads")),
                       "followers": page.get("followers"), "page_reach_week": page.get("page_impressions_unique")}
                d.setdefault("metrics", {})[b["id"]] = tot
                print(f"{b['id']}: {len(recent)} posts pulled · reach {tot['reach']} · saves {tot['saves']} · clicks {tot['clicks']}"
                      + (f" · page errors: {'; '.join(page['errors'])}" if page.get("errors") else ""))
            scored = sorted([p for p in posts if p.get("metrics") and "error" not in p["metrics"]],
                            key=lambda p: -score(p["metrics"]))
            if len(scored) >= 3:
                write_winners(b, scored[:5])
                top = scored[0]
                pillars = {}
                for p in scored[:5]:
                    pillars[p["pillar"]] = pillars.get(p["pillar"], 0) + score(p["metrics"])
                best = max(pillars, key=pillars.get)
                if not dry:
                    ap.add_rec_once(d, "P1", f"Double down on “{best}” next week",
                                    f"Top post: “{top.get('hook','')[:70]}” — reach {_n(top['metrics'].get('reach')):,}, "
                                    f"saves {_n(top['metrics'].get('saves'))}. {best} carries {len([p for p in scored[:5] if p['pillar']==best])} of the top 5.",
                                    "Next batch iterates on proven angles", "Approve plan tweak", brand=b["id"], source="otto_insights",
                                    i18n={"key": "rec.double_down", "args": {
                                        "pillar": best, "hook": top.get("hook", "")[:70], "reach": _n(top['metrics'].get('reach')),
                                        "saves": _n(top['metrics'].get('saves')),
                                        "k": len([p for p in scored[:5] if p['pillar'] == best])}})
                print(f"{b['id']}: winner pillar → {best}")
            else:
                print(f"{b['id']}: {len(scored)} posts with metrics — winners need 3+")

    if dry:
        apply(snap)
    else:
        with ap.transaction() as d:
            apply(d)


def write_winners(b, top):
    path = BRANDS / b["id"] / "winning-posts.md"
    lines = [f"# Winning posts — {b['name']} · updated {ap.now_iso()[:10]}", "",
             "| rank | post | pillar | platform | reach | saves | clicks | why it likely won |", "|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(top, 1):
        m = p["metrics"]
        lines.append(f"| {i} | {p['id']} “{p.get('hook','')[:50]}” | {p['pillar']} | {p['platform']} | {_n(m.get('reach')):,} | {_n(m.get('saves'))} | {_n(m.get('clicks'))} | _(agent fills)_ |")
    lines.append("\nNext batch: iterate on the top angles (otto-creative-engine reads this file first).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    run(dry="--dry" in a, bid=a[a.index("--brand") + 1] if "--brand" in a else None,
        days=int(a[a.index("--days") + 1]) if "--days" in a else 7)
