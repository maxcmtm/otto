#!/usr/bin/env python3
"""Otto publisher — approved posts go out on their slot (M2 glue, cron every 15 min).

  otto_publish.py [--dry] [--brand <id>] [--grace 180] [--base https://dash.monyflow.work/otto/]

Picks posts with status approved|scheduled whose slot time has arrived (brand-local time: brands[].tz,
default Asia/Jerusalem — ap.slot_dt) and publishes them through the Meta Graph API:
  fb  → photo post · feed post · photo story (format story) · multi-photo (carousel, post.images) · video (post.video)
  ig  → image · story (STORIES) · carousel (children → CAROUSEL, post.images) · reel (REELS, post.video)
  li  → not supported yet: the post is marked failed with a clear note (it is never sent to Instagram).
Credentials per brand: $OTTO_SECRETS/meta-<brand>.json  {"access_token","page_id","ig_user_id"}
(default $OTTO_SECRETS = ../../otto-secrets, i.e. the workspace's otto-secrets/ dir).

Media: every post.image / post.images[] / post.video goes through otto_paths.media_url() — a public URL
for a file that really is on the public host (copied there if needed), never a relative path. Instagram
images are converted to real JPEG first (otto_paths.ensure_jpeg).

No double posts (state transitions, each saved in its own short ap.transaction):
  approved/scheduled → publishing (+publishing_at, saved BEFORE the call that makes the post public)
                     → published (+published_at, remote_id)
  a definite Graph error (Meta answered with an error) → back to approved, attempts+1; 3 attempts → failed + P0
  an ambiguous error after "publishing" (timeout, dropped connection) → stays publishing + P0 "check if it went out".
  A post found in "publishing" is NEVER retried automatically — a human checks the page first.
Compliance is checked again right before publishing (a post approved from the dashboard deck never passed the Telegram
card check, and copy can change after approval): a violating post goes back to draft with compliance_block + a
"Compliance hold" recommendation — never to Meta.
Posts older than --grace minutes past their slot are marked failed ("missed slot") so the
owner hears about it (otto_watch also alerts) instead of publishing at a random hour.
Every post is handled in its own try/except and saved on its own. Dry run prints what would go out and touches nothing.
After each tick (not --dry) Instagram stories 20–24 h old get their last numbers (otto_insights.stories): Meta keeps story
insights for 24 h only. Read-only and never raises.
Owner console (otto_admin): while controls.publishing_paused (the kill switch) is set nothing is published, and a paused brand
(brands[].paused) is skipped; both are checked again right before the call that makes a post public.
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_paths as paths

HERE = Path(__file__).parent
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
# One Graph API version for everything Otto asks Meta (publishing, insights, ads, CAPI): v26.0 (29.07.2026). Pinned on
# purpose — a new version is a reviewed change (otto_metrics has the metric map), never picked up by accident.
GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v26.0"
GRAPH = "https://graph.facebook.com/" + GRAPH_VERSION
BASE = paths.BASE
LOG = ap.DATA.parent / "publish.log"          # next to data.json (the workspace platform dir on the server)
STUCK_AFTER_MIN = 10


class GraphError(Exception):
    """Meta answered with an error. definite=False when the answer was unreadable (5xx without a body):
    the call may or may not have taken effect."""

    def __init__(self, msg, definite=True, code=None, subcode=None):
        super().__init__(msg)
        self.definite = definite
        self.code, self.subcode = code, subcode          # Meta's error.code / error_subcode (100 = invalid parameter / metric)


class Abort(Exception):
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
            raise GraphError(f"HTTP {e.code}", definite=e.code < 500)
    if "error" in out:
        err = out["error"]
        raise GraphError(f"Graph {err.get('code')}: {err.get('message')}", code=err.get("code"), subcode=err.get("error_subcode"))
    return out


def caption_of(p):
    cap = (p.get("caption") or p.get("hook") or "").strip()
    tags = p.get("hashtags")
    if isinstance(tags, list) and tags:
        cap += "\n\n" + " ".join(t if t.startswith("#") else "#" + t for t in tags)
    return cap


def image_url(p, base=BASE, verify=True):
    """post.image → public URL (None when the post has no image). Raises otto_paths.AssetError if not public."""
    return paths.media_url(p["image"], base, verify) if p.get("image") else None


def video_url(p, base=BASE, verify=True):
    return paths.media_url(p["video"], base, verify) if p.get("video") else None


def media_urls(p, base=BASE, verify=True):
    """Carousel slides: post.images (list) → public URLs."""
    return [paths.media_url(u, base, verify) for u in (p.get("images") or []) if u]


def _ig_ref(ref):
    return paths.ensure_jpeg(ref)


def publish_fb(p, c, base, commit=lambda: None):
    """commit() runs right before the call that makes the post public (status → publishing)."""
    tok, page, cap = c["access_token"], c["page_id"], caption_of(p)
    if p.get("format") == "story":
        img = image_url(p, base)
        if not img:
            raise GraphError("Facebook story needs an image")
        pid = graph("POST", f"{page}/photos", tok, url=img, published="false")["id"]
        commit()
        return graph("POST", f"{page}/photo_stories", tok, photo_id=pid).get("post_id") or pid
    if p.get("format") == "carousel" and len(p.get("images") or []) >= 2:
        urls = media_urls(p, base)[:10]
        ids = [graph("POST", f"{page}/photos", tok, url=u, published="false")["id"] for u in urls]
        commit()
        return graph("POST", f"{page}/feed", tok, message=cap,
                     attached_media=json.dumps([{"media_fbid": i} for i in ids]))["id"]
    if p.get("video"):
        v = video_url(p, base)
        commit()
        return graph("POST", f"{page}/videos", tok, file_url=v, description=cap)["id"]
    if p.get("image"):
        img = image_url(p, base)
        commit()
        r = graph("POST", f"{page}/photos", tok, url=img, message=cap)
        return r.get("post_id") or r.get("id")
    params = {"message": cap}
    if p.get("link"):
        params["link"] = p["link"]
    commit()
    return graph("POST", f"{page}/feed", tok, **params)["id"]


def _wait_container(cid, tok, tries=40):
    for _ in range(tries):
        st = graph("GET", cid, tok, fields="status_code")["status_code"]
        if st == "FINISHED":
            return
        if st == "ERROR":
            raise GraphError("IG container processing failed")
        time.sleep(3)
    raise GraphError("IG container still processing after timeout")


def publish_ig(p, c, base, commit=lambda: None):
    """post → image · story → STORIES · carousel → children + CAROUSEL · reel → REELS (post.video url)."""
    if not c.get("ig_user_id"):
        raise GraphError("no ig_user_id for this brand")
    ig, tok, fmt, cap = c["ig_user_id"], c["access_token"], p.get("format", "post"), caption_of(p)
    def img():
        return paths.media_url(_ig_ref(p["image"]), base) if p.get("image") else None
    if fmt == "story":
        if p.get("video"):
            cid = graph("POST", f"{ig}/media", tok, media_type="STORIES", video_url=video_url(p, base))["id"]
        elif p.get("image"):
            cid = graph("POST", f"{ig}/media", tok, media_type="STORIES", image_url=img())["id"]
        else:
            raise GraphError("story needs an image or a video")
    elif fmt == "carousel":
        slides = [paths.media_url(_ig_ref(u), base) for u in (p.get("images") or []) if u] or ([img()] if p.get("image") else [])
        if len(slides) < 2:
            raise GraphError("carousel needs at least 2 images (post.images)")
        kids = [graph("POST", f"{ig}/media", tok, image_url=u, is_carousel_item="true")["id"] for u in slides[:10]]
        for k in kids:
            _wait_container(k, tok)
        cid = graph("POST", f"{ig}/media", tok, media_type="CAROUSEL", children=",".join(kids), caption=cap)["id"]
    elif fmt in ("reel", "video"):
        if not p.get("video"):
            raise GraphError("reel needs post.video (a rendered mp4)")
        cid = graph("POST", f"{ig}/media", tok, media_type="REELS", video_url=video_url(p, base), caption=cap, share_to_feed="true")["id"]
    else:
        if not p.get("image"):
            raise GraphError("Instagram needs an image — post has none")
        cid = graph("POST", f"{ig}/media", tok, image_url=img(), caption=cap)["id"]
    _wait_container(cid, tok)
    commit()
    return graph("POST", f"{ig}/media_publish", tok, creation_id=cid)["id"]


def due_posts(d, bid, grace_min):
    now = datetime.now(timezone.utc)
    out = []
    for p in d.get("posts", []):
        if not isinstance(p, dict) or p.get("status") not in ("approved", "scheduled") or not p.get("id") or not p.get("brand") \
                or (bid and p["brand"] != bid):
            continue                                  # one malformed record must not stop every brand's publishing
        slot = ap.slot_dt(p, ap.brand(d, p["brand"]))
        if slot is None:
            continue
        if slot <= now:
            out.append((p, slot, (now - slot) > timedelta(minutes=grace_min)))
    return sorted(out, key=lambda x: x[1])


def log(line):
    with LOG.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {line}\n")


def stuck_alerts(d, dry=False):
    """Posts left in "publishing" by an earlier run: may be live already — alert once, never retry."""
    now = datetime.now(timezone.utc)
    for p in d.get("posts", []):
        if not isinstance(p, dict) or not p.get("id") or p.get("status") != "publishing" or p.get("stuck_alerted"):
            continue
        since = ap.parse_iso(p.get("publishing_at"))
        if since and since.tzinfo and now - since < timedelta(minutes=STUCK_AFTER_MIN):
            continue
        print(f"STUCK   {p['id']} {p['brand']}/{p['platform']} publishing since {p.get('publishing_at')} — alerting, not retrying")
        if dry:
            continue
        with ap.transaction() as d2:
            q = ap.post(d2, p["id"])
            if q and q.get("status") == "publishing" and not q.get("stuck_alerted"):
                _stuck_rec(d2, q)


def _stuck_rec(d, q):
    q["stuck_alerted"] = ap.now_iso()
    ap.add_rec_once(d, "P0", f"Check if it went out: {q.get('hook', '')[:60]}",
                    f"{q['id']} was sent to Meta at {q.get('publishing_at')} but Otto never got a confirmation"
                    f"{' (' + q['error'][:160] + ')' if q.get('error') else ''}. It will NOT be retried automatically. "
                    "Check the page: if it is live, mark it published; if not, send it back to review.",
                    "Prevents a double post", "Check page", brand=q["brand"], source="otto_publish", post=q["id"],
                    i18n={"key": "rec.check_live", "args": {"hook": q.get("hook", "")[:60]}})


def _when(d, q, slot):
    """The slot as the brand's client reads it (otto_i18n), for a card's i18n args."""
    try:
        import otto_i18n
        b = ap.brand(d, q.get("brand")) or {}
        return otto_i18n.Tr.for_brand(b).day_time(slot.astimezone(ap.brand_tz(b)))
    except Exception:                                          # noqa: BLE001
        return slot.strftime("%a %d %b %H:%M")


def _mark(pid, fn):
    with ap.transaction() as d:
        q = ap.post(d, pid)
        if q is not None:
            fn(d, q)


def publish_one(p, slot, missed, dry, grace, base):
    pid = p["id"]
    tag = f'{pid} {p["brand"]}/{p["platform"]} slot {slot.strftime("%d/%m %H:%M")}'
    if missed:
        print(f"MISSED  {tag} — {p.get('hook','')[:50]}")
        if not dry:
            def fn(d, q):
                if q["status"] in ("approved", "scheduled"):
                    q["status"] = "failed"; q["error"] = f"missed slot by more than {grace} min"
                    ap.add_rec_once(d, "P0", f"Missed publish: {q.get('hook','')[:60]}",
                                    f"{pid} was approved for {slot.strftime('%a %d %b %H:%M')} but never went out (publisher had no credentials or failed 3 times).",
                                    "Keeps the calendar honest", "Reschedule", brand=q["brand"], source="otto_publish", post=pid,
                                    i18n={"key": "rec.missed", "args": {"hook": q.get("hook", "")[:60], "when": _when(d, q, slot)}})
            _mark(pid, fn)
            log(f"MISSED {tag}")
        return
    if p["platform"] == "li":
        print(f"SKIP    {tag} — LinkedIn publishing is not supported yet")
        if not dry:
            def fn(d, q):
                if q["status"] in ("approved", "scheduled"):
                    q["status"] = "failed"; q["error"] = "LinkedIn publishing is not supported yet — post it by hand"
                    ap.add_rec_once(d, "P1", f"Post by hand on LinkedIn: {q.get('hook','')[:60]}",
                                    f"{pid} is approved for LinkedIn ({slot.strftime('%a %d %b %H:%M')}), which Otto cannot publish to yet.",
                                    "The post still goes out on time", "Open post", brand=q["brand"], source="otto_publish", post=pid,
                                    i18n={"key": "rec.linkedin", "args": {"hook": q.get("hook", "")[:60], "when": _when(d, q, slot)}})
            _mark(pid, fn)
            log(f"SKIP-LI {tag}")
        return
    if p["platform"] not in ("fb", "ig"):
        print(f"SKIP    {tag} — unknown platform {p['platform']}")
        return
    import otto_compliance as comp
    v = comp.check_post(p)
    if v:
        print(f"{'WOULD HOLD' if dry else 'HELD'}    {tag} — compliance: {comp.describe(v)}")
        if not dry:
            def fn(d, q):
                if q["status"] in ("approved", "scheduled"):
                    q["status"] = "draft"
                    q["compliance_block"] = {"rules": [x["rule"] for x in v][:6], "at": ap.now_iso()}
                    comp.file_block(d, q["brand"], f"{pid} “{q.get('hook', '')[:50]}”", v, "otto_publish", post=pid)
            _mark(pid, fn)
            log(f"HELD {tag}: {comp.describe(v)}")
        return
    c = creds(p["brand"])
    if not c:
        print(f"NO-CREDS {tag} — waiting for meta-{p['brand']}.json")
        return
    print(f"{'WOULD PUBLISH' if dry else 'PUBLISH'} {tag} — {p.get('hook','')[:50]}")
    if dry:
        try:
            refs = [x for x in [p.get("image"), p.get("video")] + list(p.get("images") or []) if x]
            for r in refs:
                print(f"    media {paths.media_url(r, base, verify=False)}")
        except paths.AssetError as e:
            print(f"    media problem: {e}")
        return
    state = {"committed": False}

    def commit():
        with ap.transaction() as d:
            q = ap.post(d, pid)
            if q is None or q["status"] not in ("approved", "scheduled"):
                raise Abort(f"status is now {q and q['status']} — not publishing")
            if ap.paused(d, q["brand"]):                  # kill switch flipped while this run was working
                raise Abort(ap.paused(d, q["brand"]))
            q["status"] = "publishing"; q["publishing_at"] = ap.now_iso()
        state["committed"] = True

    try:
        rid = publish_fb(p, c, base, commit) if p["platform"] == "fb" else publish_ig(p, c, base, commit)
    except Abort as e:
        print(f"  skipped: {e}")
        return
    except Exception as e:
        definite = isinstance(e, paths.AssetError) or (isinstance(e, GraphError) and e.definite) or not state["committed"]
        msg = f"{type(e).__name__}: {e}" if not isinstance(e, (GraphError, paths.AssetError)) else str(e)
        print(f"  failed: {msg}")
        if definite:
            def fn(d, q):
                q["attempts"] = q.get("attempts", 0) + 1; q["error"] = msg[:500]
                if q["status"] == "publishing":
                    q["status"] = "approved"; q.pop("publishing_at", None)   # Meta refused it: nothing went live
                if q["attempts"] >= 3 and q["status"] in ("approved", "scheduled"):
                    q["status"] = "failed"
                    ap.add_rec_once(d, "P0", f"Publishing failed 3×: {q.get('hook','')[:60]}", msg[:300],
                                    "Post stays unpublished until fixed", "Open post", brand=q["brand"], source="otto_publish", post=pid,
                                    i18n={"key": "rec.publish_failed", "args": {"hook": q.get("hook", "")[:60]}})
            _mark(pid, fn)
            log(f"FAIL {tag}: {msg}")
        else:
            def fn(d, q):
                q["error"] = f"unconfirmed: {msg}"[:500]
                if q["status"] == "publishing":
                    _stuck_rec(d, q)
            _mark(pid, fn)
            log(f"UNCONFIRMED {tag}: {msg} — left in publishing, not retried")
        return

    def done(d, q):
        q["status"] = "published"; q["published_at"] = ap.now_iso(); q["remote_id"] = rid
        q.pop("error", None); q.pop("publishing_at", None)
    _mark(pid, done)
    log(f"OK {tag} -> {rid}")


def run(dry=False, bid=None, grace=180, base=BASE):
    try:
        _run(dry, bid, grace, base)
    finally:
        if not dry:
            story_numbers(bid)


def story_numbers(bid=None):
    """Instagram stories 20–24 h old get their last numbers (otto_insights.stories): Meta keeps story insights for 24 h
    only, and this tick runs every 15 min. Read-only, after the publishing (kill switch or not); never raises."""
    try:
        import otto_insights
        otto_insights.stories(bid)
    except Exception as e:                     # noqa: BLE001 — numbers never get in the way of publishing
        print(f"story numbers: {type(e).__name__}: {str(e)[:120]}")


def _run(dry, bid, grace, base):
    d = ap.load()
    stuck_alerts(d, dry)
    if ap.paused(d):                                  # owner console kill switch: nothing goes out, nothing is marked missed
        print(f"PAUSED  {ap.paused(d)} — nothing is published"); return
    due = due_posts(d, bid, grace)
    if not due:
        print("nothing due"); return
    for p, slot, missed in due:
        if ap.paused(d, p["brand"]):
            print(f"PAUSED  {p['id']} — {ap.paused(d, p['brand'])}"); continue
        try:
            publish_one(p, slot, missed, dry, grace, base)
        except Exception as e:                 # one bad post never stops the others
            print(f"  error on {p['id']}: {type(e).__name__}: {e}")
            try:
                log(f"ERROR {p['id']}: {type(e).__name__}: {e}")
            except Exception:
                pass


if __name__ == "__main__":
    a = sys.argv[1:]
    run(dry="--dry" in a,
        bid=a[a.index("--brand") + 1] if "--brand" in a else None,
        grace=int(a[a.index("--grace") + 1]) if "--grace" in a else 180,
        base=a[a.index("--base") + 1] if "--base" in a else BASE)
