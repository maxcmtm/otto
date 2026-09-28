#!/usr/bin/env python3
"""Otto publisher — approved posts go out on their slot (M2 glue, cron every 15 min).

  otto_publish.py [--dry] [--brand <id>] [--grace 180] [--base https://dash.monyflow.work/otto/]

Picks posts with status approved|scheduled whose slot time has arrived (brand-local time,
OTTO_TZ, default Asia/Jerusalem) and publishes them through the Meta Graph API:
  fb  → Page photo (image + caption) or feed post (text + link)
  ig  → image container → publish   (carousel / reel / story: not yet — left in queue, logged)
Credentials per brand: $OTTO_SECRETS/meta-<brand>.json  {"access_token","page_id","ig_user_id"}
(default $OTTO_SECRETS = ../../otto-secrets, i.e. the workspace's otto-secrets/ dir).

State transitions (through ap.py): approved/scheduled → published (+published_at, remote_id)
                                    3 failed attempts → failed (+error) and a P0 recommendation.
Posts older than --grace minutes past their slot are marked failed ("missed slot") so the
owner hears about it (otto_watch also alerts) instead of publishing at a random hour.
Images: post.image is repo-relative (assets/posts/x.png) → served from --base for Meta to fetch.
Dry run prints exactly what would go out and touches nothing.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import ap

HERE = Path(__file__).parent
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
GRAPH = "https://graph.facebook.com/" + os.environ.get("GRAPH_API_VERSION", "v25.0")
TZ = ZoneInfo(os.environ.get("OTTO_TZ", "Asia/Jerusalem"))
BASE = "https://dash.monyflow.work/otto/"
LOG = HERE / "publish.log"


class GraphError(Exception):
    pass


def creds(bid):
    f = SECRETS / f"meta-{bid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def graph(method, path, token, **params):
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{GRAPH}/{path}" + ("" if method == "POST" else "?" + data.decode()),
                                 data=data if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            out = json.loads(e.read().decode())
        except Exception:
            raise GraphError(f"HTTP {e.code}")
    if "error" in out:
        err = out["error"]
        raise GraphError(f"Graph {err.get('code')}: {err.get('message')}")
    return out


def caption_of(p):
    cap = (p.get("caption") or p.get("hook") or "").strip()
    tags = p.get("hashtags")
    if isinstance(tags, list) and tags:
        cap += "\n\n" + " ".join(t if t.startswith("#") else "#" + t for t in tags)
    return cap


def image_url(p, base):
    img = p.get("image")
    if not img:
        return None
    return img if img.startswith("http") else base.rstrip("/") + "/" + img.lstrip("/")


def publish_fb(p, c, base):
    img, cap = image_url(p, base), caption_of(p)
    if img:
        r = graph("POST", f"{c['page_id']}/photos", c["access_token"], url=img, message=cap)
        return r.get("post_id") or r.get("id")
    params = {"message": cap}
    if p.get("link"):
        params["link"] = p["link"]
    return graph("POST", f"{c['page_id']}/feed", c["access_token"], **params)["id"]


def publish_ig(p, c, base):
    if not c.get("ig_user_id"):
        raise GraphError("no ig_user_id for this brand")
    fmt = p.get("format", "post")
    if fmt not in ("post", "image"):
        raise GraphError(f"format {fmt} not supported by the publisher yet (needs media pipeline)")
    img = image_url(p, base)
    if not img:
        raise GraphError("Instagram needs an image — post has none")
    cid = graph("POST", f"{c['ig_user_id']}/media", c["access_token"], image_url=img, caption=caption_of(p))["id"]
    for _ in range(20):
        st = graph("GET", cid, c["access_token"], fields="status_code")["status_code"]
        if st == "FINISHED":
            break
        if st == "ERROR":
            raise GraphError("IG container processing failed")
        time.sleep(3)
    return graph("POST", f"{c['ig_user_id']}/media_publish", c["access_token"], creation_id=cid)["id"]


def due_posts(d, bid, grace_min):
    now = datetime.now(TZ)
    out = []
    for p in d["posts"]:
        if p["status"] not in ("approved", "scheduled") or (bid and p["brand"] != bid):
            continue
        try:
            slot = datetime.fromisoformat(p["slot"]).replace(tzinfo=TZ)
        except Exception:
            continue
        if slot <= now:
            out.append((p, slot, (now - slot) > timedelta(minutes=grace_min)))
    return sorted(out, key=lambda x: x[1])


def log(line):
    with LOG.open("a") as f:
        f.write(f"{datetime.now(TZ).isoformat(timespec='seconds')} {line}\n")


def run(dry=False, bid=None, grace=180, base=BASE):
    d = ap.load()
    due = due_posts(d, bid, grace)
    if not due:
        print("nothing due"); return
    changed = False
    for p, slot, missed in due:
        tag = f'{p["id"]} {p["brand"]}/{p["platform"]} slot {slot.strftime("%d/%m %H:%M")}'
        if missed:
            print(f"MISSED  {tag} — {p.get('hook','')[:50]}")
            if not dry:
                p["status"] = "failed"; p["error"] = f"missed slot by more than {grace} min"; changed = True
                ap.add_rec(d, "P0", f"Missed publish: {p.get('hook','')[:60]}",
                           f"{p['id']} was approved for {slot.strftime('%a %d %b %H:%M')} but never went out (publisher had no credentials or failed 3 times).",
                           "Keeps the calendar honest", "Reschedule", brand=p["brand"], source="otto_publish")
                log(f"MISSED {tag}")
            continue
        c = creds(p["brand"])
        if not c:
            print(f"NO-CREDS {tag} — waiting for meta-{p['brand']}.json")
            continue
        print(f"{'WOULD PUBLISH' if dry else 'PUBLISH'} {tag} — {p.get('hook','')[:50]}")
        if dry:
            continue
        try:
            rid = publish_fb(p, c, base) if p["platform"] == "fb" else publish_ig(p, c, base)
            p["status"] = "published"; p["published_at"] = ap.now_iso(); p["remote_id"] = rid; p.pop("error", None)
            log(f"OK {tag} -> {rid}")
        except GraphError as e:
            p["attempts"] = p.get("attempts", 0) + 1; p["error"] = str(e)
            log(f"FAIL {tag} attempt {p['attempts']}: {e}")
            print(f"  failed: {e}")
            if p["attempts"] >= 3:
                p["status"] = "failed"
                ap.add_rec(d, "P0", f"Publishing failed 3×: {p.get('hook','')[:60]}", str(e)[:300],
                           "Post stays unpublished until fixed", "Open post", brand=p["brand"], source="otto_publish")
        changed = True
    if changed:
        ap.save(d)


if __name__ == "__main__":
    a = sys.argv[1:]
    run(dry="--dry" in a,
        bid=a[a.index("--brand") + 1] if "--brand" in a else None,
        grace=int(a[a.index("--grace") + 1]) if "--grace" in a else 180,
        base=a[a.index("--base") + 1] if "--base" in a else BASE)
