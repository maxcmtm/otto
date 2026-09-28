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
--dry: no API calls; ranks whatever metrics already exist in data.json.
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_publish as pub

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"


def score(m):
    return (m.get("reach") or 0) + 10 * (m.get("saves") or 0) + 5 * (m.get("clicks") or 0) + 2 * (m.get("comments") or 0)


def pull_post(p, c):
    rid = p.get("remote_id")
    if not rid:
        return None
    if p["platform"] == "fb":
        r = pub.graph("GET", rid, c["access_token"],
                      fields="insights.metric(post_impressions_unique,post_clicks,post_engaged_users)")
        vals = {i["name"]: (i["values"][0]["value"] if i.get("values") else 0) for i in r.get("insights", {}).get("data", [])}
        return {"reach": vals.get("post_impressions_unique", 0), "clicks": vals.get("post_clicks", 0),
                "engaged": vals.get("post_engaged_users", 0)}
    r = pub.graph("GET", f"{rid}/insights", c["access_token"], metric="reach,saved,likes,comments,shares")
    vals = {i["name"]: (i["values"][0]["value"] if i.get("values") else 0) for i in r.get("data", [])}
    return {"reach": vals.get("reach", 0), "saves": vals.get("saved", 0), "likes": vals.get("likes", 0),
            "comments": vals.get("comments", 0), "shares": vals.get("shares", 0)}


def pull_page(c):
    out = {}
    try:
        r = pub.graph("GET", f"{c['page_id']}/insights", c["access_token"],
                      metric="page_impressions_unique,page_post_engagements,page_fans", period="week")
        for i in r.get("data", []):
            out[i["name"]] = i["values"][-1]["value"] if i.get("values") else 0
    except pub.GraphError as e:
        out["error"] = str(e)
    return out


def run(dry=False, bid=None, days=7):
    d = ap.load()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    for b in d["brands"]:
        if bid and b["id"] != bid:
            continue
        c = None if dry else pub.creds(b["id"])
        posts = [p for p in d["posts"] if p["brand"] == b["id"] and p["status"] == "published"]
        recent = [p for p in posts if p.get("published_at") and datetime.fromisoformat(p["published_at"].replace("Z", "+00:00")) >= since]
        if c:
            page = pull_page(c)
            for p in recent:
                try:
                    m = pull_post(p, c)
                    if m:
                        m["pulled_at"] = ap.now_iso(); p["metrics"] = m
                except pub.GraphError as e:
                    p.setdefault("metrics", {})["error"] = str(e)
            tot = {"reach": sum((p.get("metrics") or {}).get("reach", 0) for p in recent),
                   "saves": sum((p.get("metrics") or {}).get("saves", 0) for p in recent),
                   "clicks": sum((p.get("metrics") or {}).get("clicks", 0) for p in recent),
                   "leads": d.get("metrics", {}).get(b["id"], {}).get("leads", 0),
                   "followers": page.get("page_fans"), "page_reach_week": page.get("page_impressions_unique")}
            d.setdefault("metrics", {})[b["id"]] = tot
            print(f"{b['id']}: {len(recent)} posts pulled · reach {tot['reach']} · saves {tot['saves']} · clicks {tot['clicks']}")
        elif not dry:
            print(f"{b['id']}: no credentials (meta-{b['id']}.json) — skipped")
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
                ap.add_rec(d, "P1", f"Double down on “{best}” next week",
                           f"Top post: “{top.get('hook','')[:70]}” — reach {top['metrics'].get('reach',0):,}, "
                           f"saves {top['metrics'].get('saves',0)}. {best} carries {len([p for p in scored[:5] if p['pillar']==best])} of the top 5.",
                           "Next batch iterates on proven angles", "Approve plan tweak", brand=b["id"], source="otto_insights")
            print(f"{b['id']}: winner pillar → {best}")
        else:
            print(f"{b['id']}: {len(scored)} posts with metrics — winners need 3+")
    if not dry:
        ap.save(d)


def write_winners(b, top):
    path = BRANDS / b["id"] / "winning-posts.md"
    lines = [f"# Winning posts — {b['name']} · updated {ap.now_iso()[:10]}", "",
             "| rank | post | pillar | platform | reach | saves | clicks | why it likely won |", "|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(top, 1):
        m = p["metrics"]
        lines.append(f"| {i} | {p['id']} “{p.get('hook','')[:50]}” | {p['pillar']} | {p['platform']} | {m.get('reach',0):,} | {m.get('saves',0)} | {m.get('clicks',0)} | _(agent fills)_ |")
    lines.append("\nNext batch: iterate on the top angles (otto-creative-engine reads this file first).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    run(dry="--dry" in a, bid=a[a.index("--brand") + 1] if "--brand" in a else None,
        days=int(a[a.index("--days") + 1]) if "--days" in a else 7)
