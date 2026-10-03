#!/usr/bin/env python3
"""Otto insights — organic numbers from Meta: per post, per Instagram account and per Facebook Page, the 30-day baseline
before Otto, and the weekly winners loop (M6 analytics loop). Metric names: otto_metrics (Graph API v26.0 map).

  otto_insights.py [--dry] [--brand <id>] [--days 7]   # weekly (Fri 06:00, otto_cron insights): per-post numbers of the last
                                                       # --days, Page reach of the week, winners → "Double down" card
  otto_insights.py daily [--brand <id>] [--days 3]     # daily (07:05 brand time, otto_cron insights-daily): Instagram account
                                                       # + Facebook Page numbers of the last complete days (re-pulled: Meta
                                                       # lags up to 48 h), followers, today's stories, and the baseline
                                                       # when the brand has none yet
  otto_insights.py baseline --brand <id> [--force]     # the 30 days before the brand joined Otto, now (also done by daily)
  otto_insights.py stories [--brand <id>]              # stories 20–24 h old: their numbers before Meta drops them (24 h);
                                                       # otto_publish runs this after every publish tick

For every brand with Meta credentials ($OTTO_SECRETS/meta-<brand>.json {"access_token","page_id","ig_user_id"}).
Weekly: pulls per-post numbers (reach, views, saves, likes, comments, shares, interactions; clicks for Facebook posts) for
posts published in the last --days, writes them into posts[].metrics, ranks the winners (reach + 10×saves + 5×clicks), writes
brands/<slug>/winning-posts.md and files a P1 "Double down on <pillar>" card (ap.add_rec_once: re-runs never stack it).

data.json metrics[brand] (one dict per brand; readers that only know the flat keys keep working):
  reach, saves, clicks   sums over the posts the weekly run pulled (as before)
  leads                  carried forward, never set here (paid leads: ads[brand].daily, otto_ads)
  followers              Facebook Page followers_count (fan_count fallback); Instagram followers when there is no Page
  page_reach_week        Page unique viewers of the last 7 days: page_total_media_view_unique, period=week
                         (was page_impressions_unique, retired 15.11.2025)
  account                {"pulled_at", "ig": {"followers", "media"}, "fb": {"followers"}, "errors": [...]}   (daily)
  daily                  {"YYYY-MM-DD": {"ig": {reach, views, engaged, interactions, likes, comments, shares, saves, replies,
                         link_taps, follows, unfollows}, "fb": {views, viewers, engagements, actions, page_views, followers,
                         follows, unfollows}}} — Instagram by brand-local day, Facebook by Meta's Page day; the last 62
                         days; a network that answered nothing keeps the day's earlier numbers
  baseline               the 30 days before the brand joined Otto: {"joined", "since", "until" (exclusive), "days",
                         "pulled_at", "final" (pulled 48 h after the window: Meta's lag is over), "ig": {window totals —
                         Instagram's own 30-day total_value, so reach is unique accounts, not a sum of days}, "fb":
                         {window sums; followers = the last day}, "daily": {date: {"ig": {"reach"}, "fb": {...}}}, "errors"}
                         joined = brands[].otto_since if set, else the earliest of onboarding.started_at, trial.started_at,
                         plan_history[].at and the brand's first post; window = [joined − 30 days, joined), clipped to Meta's
                         2 years of history. Pulled at connect time (the first daily run that finds credentials), pulled again
                         once when it was taken inside Meta's 48 h lag, retried a day later when Meta answered nothing.
metrics_history.jsonl (otto_watch snapshot, daily) keeps the flat keys and `account`, never daily / baseline.
Stories are pulled while they live (Meta keeps story numbers 24 h): daily takes every story under 24 h, the publisher's
tick takes each one once more at 20–24 h (posts[].metrics.final).
Metrics Meta refuses are dropped and logged once (otto_metrics.insights), never failing a pull; any other Graph error is
recorded (posts[].metrics.error, metrics[brand].account.errors, baseline.errors) and the next brand goes on.
All Graph calls happen outside the data lock; the results are patched in one short ap.transaction per brand.
--dry: no API calls; ranks whatever metrics already exist in data.json.
"""
import sys
from datetime import date, datetime, timedelta, timezone

import ap
import otto_metrics as om
import otto_publish as pub

BRANDS = ap.BRANDS
BASELINE_DAYS = 30
HISTORY_DAYS = 730                 # Meta keeps two years of insights
LAG = timedelta(hours=48)          # Meta: "data can be delayed up to 48 hours"
KEEP_DAYS = 62
STORY_LIFE = timedelta(hours=24)
STORY_FINAL_AFTER = timedelta(hours=20)
# legacy names, kept for anyone importing them
IG_FEED_METRICS = om.IG_MEDIA["feed"]
IG_STORY_METRICS = om.IG_MEDIA["story"]


def _n(v):
    return ap.num(v) or 0


def _utc(s):
    dt = ap.parse_iso(s)
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def utcnow():
    return datetime.now(timezone.utc)


def score(m):
    return _n(m.get("reach")) + 10 * _n(m.get("saves")) + 5 * _n(m.get("clicks")) + 2 * _n(m.get("comments"))


_values = om.values                # Graph insights rows → {name: number}


def _short(e):
    return f"{type(e).__name__}: {e}"[:160] if not isinstance(e, pub.GraphError) else str(e)[:160]


# ============================================================================================
# per post
# ============================================================================================

def ig_kind(p):
    fmt = p.get("format") or "post"
    return "story" if fmt == "story" else "reel" if fmt in ("reel", "video") else "carousel" if fmt == "carousel" else "feed"


def pull_post(p, c):
    """One published post's numbers → {reach, views, saves, likes, comments, shares, …} (only numbers Meta gave), None
    without remote_id. Raises GraphError when Meta refuses the whole request (token, permissions, deleted post)."""
    rid = p.get("remote_id")
    if not rid:
        return None
    tok = c["access_token"]
    if p["platform"] == "fb":
        out = om.rename(om.values(om.insights(rid, tok, list(om.FB_POST), "fb_post")), om.FB_POST)
        try:
            r = pub.graph("GET", rid, tok, fields="shares,comments.summary(true).limit(0),reactions.summary(true).limit(0)")
            out["shares"] = ap.num((r.get("shares") or {}).get("count"))
            out["comments"] = ap.num(((r.get("comments") or {}).get("summary") or {}).get("total_count"))
            out["likes"] = ap.num(((r.get("reactions") or {}).get("summary") or {}).get("total_count"))
        except pub.GraphError:
            pass
        return {k: v for k, v in out.items() if v is not None}
    kind = ig_kind(p)
    vals = om.values(om.insights(rid, tok, om.IG_MEDIA[kind], f"ig_media:{kind}"))
    return {om.IG_MEDIA_NAMES.get(k, k): v for k, v in vals.items() if v is not None}


# ============================================================================================
# per account: Instagram user + Facebook Page
# ============================================================================================

def ig_window(c, since_ts, until_ts):
    """Instagram account totals for [since, until) (unix): one total_value request + the follows breakdown."""
    ig, tok = c["ig_user_id"], c["access_token"]
    q = dict(period="day", metric_type="total_value", since=since_ts, until=until_ts)
    out = om.rename(om.values(om.insights(ig, tok, list(om.IG_ACCOUNT), "ig_user", **q)), om.IG_ACCOUNT)
    try:
        bd = om.breakdown(om.insights(ig, tok, [om.IG_FOLLOWS], "ig_user:follow_type", breakdown="follow_type", **q), om.IG_FOLLOWS)
    except pub.GraphError as e:                    # under 100 followers / no data for the breakdown: the totals still count
        if om.code_of(e) not in (10, 100):
            raise
        bd = {}
    for k, name in om.IG_FOLLOW_KEYS.items():
        if bd.get(k) is not None:
            out[name] = bd[k]
    return out


def ig_reach_series(c, since_ts, until_ts):
    """{date: reach} for [since, until): reach is the one account metric with a daily time series."""
    rows = om.insights(c["ig_user_id"], c["access_token"], ["reach"], "ig_user:time_series", period="day",
                       metric_type="time_series", since=since_ts, until=until_ts)
    return om.by_day(rows).get("reach", {})


def ig_profile(c):
    r = pub.graph("GET", c["ig_user_id"], c["access_token"], fields="followers_count,media_count")
    return {k: v for k, v in (("followers", ap.num(r.get("followers_count"))), ("media", ap.num(r.get("media_count"))))
            if v is not None}


def fb_days(c, since, until):
    """Facebook Page numbers per day for [since, until) (dates) → {"YYYY-MM-DD": {views, viewers, …}}. One request
    (Meta: ≤ 90 days a query); asked a day wider on both sides and cut to the window (Meta's day ends at 07:00 UTC)."""
    rows = om.insights(c["page_id"], c["access_token"], list(om.FB_PAGE_DAY), "fb_page:day", period="day",
                       since=(since - timedelta(days=1)).isoformat(), until=(until + timedelta(days=1)).isoformat())
    out = {}
    for metric, days in om.by_day(rows).items():
        name = om.FB_PAGE_DAY.get(metric)
        for day, v in days.items():
            if name and since <= day < until:
                out.setdefault(day.isoformat(), {})[name] = v
    return out


def fb_followers(c):
    r = pub.graph("GET", c["page_id"], c["access_token"], fields="followers_count,fan_count")
    f = ap.num(r.get("followers_count"))
    return f if f is not None else ap.num(r.get("fan_count"))


def pull_page(c):
    """The weekly Page numbers: unique viewers + engagements of the last 7 days, followers."""
    out = {}
    tok, page = c["access_token"], c["page_id"]
    try:
        out.update(om.rename(om.values(om.insights(page, tok, list(om.FB_PAGE_WEEK), "fb_page:week", period="week")),
                             om.FB_PAGE_WEEK))
    except pub.GraphError as e:
        out.setdefault("errors", []).append(f"page insights: {str(e)[:80]}")
    try:
        out["followers"] = fb_followers(c)
    except pub.GraphError as e:
        out.setdefault("errors", []).append(f"followers: {str(e)[:80]}")
    return out


def account_days(b, c, days=3, now=None):
    """The last `days` complete brand-local days of Instagram account + Facebook Page numbers, and today's followers.
    → {"daily": {day: {"ig": {…}, "fb": {…}}}, "account": {"ig": {…}, "fb": {…}}, "errors": [...]}. Never raises."""
    now = now or utcnow()
    tz = ap.brand_tz(b)
    today = now.astimezone(tz).date()
    span = [today - timedelta(days=i) for i in range(days, 0, -1)]
    daily, acct, errors = {}, {}, []
    if c.get("ig_user_id"):
        for day in span:
            try:
                v = ig_window(c, *om.local_bounds(day, tz))
                if v:
                    daily.setdefault(day.isoformat(), {})["ig"] = v
            except Exception as e:                             # noqa: BLE001 — one day / one account never stops the rest
                errors.append(f"instagram {day}: {_short(e)}")
                break
        try:
            acct["ig"] = ig_profile(c)
        except Exception as e:                                 # noqa: BLE001
            errors.append(f"instagram followers: {_short(e)}")
    if c.get("page_id"):
        try:
            for day, v in fb_days(c, span[0], today).items():
                daily.setdefault(day, {})["fb"] = v
        except Exception as e:                                 # noqa: BLE001
            errors.append(f"facebook page: {_short(e)}")
        try:
            f = fb_followers(c)
            if f is not None:
                acct["fb"] = {"followers": f}
        except Exception as e:                                 # noqa: BLE001
            errors.append(f"facebook followers: {_short(e)}")
    return {"daily": daily, "account": acct, "errors": errors}


# ============================================================================================
# the baseline: the 30 days before Otto
# ============================================================================================

def joined_date(d, b, today=None):
    """The brand-local day the brand joined Otto: brands[].otto_since, else the earliest of onboarding.started_at,
    trial.started_at, plan_history[].at and its first post (created / published); else today."""
    tz = ap.brand_tz(b)
    today = today or utcnow().astimezone(tz).date()
    if b.get("otto_since"):
        try:
            return date.fromisoformat(str(b["otto_since"])[:10])
        except ValueError:
            pass
    stamps = [(b.get("onboarding") or {}).get("started_at") if isinstance(b.get("onboarding"), dict) else None,
              (b.get("trial") or {}).get("started_at") if isinstance(b.get("trial"), dict) else None]
    stamps += [h.get("at") for h in (b.get("plan_history") or []) if isinstance(h, dict)]
    for p in d.get("posts") or []:
        if isinstance(p, dict) and p.get("brand") == b.get("id"):
            stamps += [p.get("created_at"), p.get("published_at")]
    days = []
    for s in stamps:
        dt = _utc(s) if isinstance(s, str) else None
        if dt is not None:
            days.append(dt.astimezone(tz).date())
    return min(days + [today])


def baseline_window(joined, today, days=BASELINE_DAYS, history=HISTORY_DAYS):
    """(since, until) brand-local dates, until exclusive: the `days` days before `joined`, inside Meta's history
    (`history` days back from today). A join date after today counts as today. None when nothing is left."""
    until = min(joined, today)
    since = max(until - timedelta(days=days), today - timedelta(days=history - 1))
    return (since, until) if since < until else None


def needs_baseline(base, now=None):
    """None / a provisional baseline whose window has cleared Meta's lag / an empty one tried a day ago → pull (again)."""
    now = now or utcnow()
    if not isinstance(base, dict):
        return True
    if not (base.get("ig") or base.get("fb")):
        tried = _utc(base.get("pulled_at"))
        return tried is None or now - tried > timedelta(hours=20)
    if base.get("final"):
        return False
    try:
        end = datetime.fromisoformat(str(base.get("until"))[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return now >= end + LAG + timedelta(hours=12)


def pull_baseline(d, b, c, now=None):
    """The baseline record (see the module docstring), or None when Meta's history does not reach the window."""
    now = now or utcnow()
    tz = ap.brand_tz(b)
    today = now.astimezone(tz).date()
    joined = joined_date(d, b, today)
    w = baseline_window(joined, today)
    if not w:
        return None
    since, until = w
    since_ts, until_ts = om.local_bounds(since, tz)[0], om.local_bounds(until, tz)[0]
    base = {"joined": joined.isoformat(), "since": since.isoformat(), "until": until.isoformat(), "days": (until - since).days,
            "pulled_at": ap.now_iso(), "final": now >= datetime(until.year, until.month, until.day, tzinfo=tz) + LAG,
            "ig": {}, "fb": {}, "daily": {}, "errors": []}
    if c.get("ig_user_id"):
        try:
            base["ig"] = ig_window(c, since_ts, until_ts)
        except Exception as e:                                 # noqa: BLE001
            base["errors"].append(f"instagram: {_short(e)}")
        try:
            for day, v in ig_reach_series(c, since_ts, until_ts).items():
                if since <= day < until:
                    base["daily"].setdefault(day.isoformat(), {}).setdefault("ig", {})["reach"] = v
        except Exception as e:                                 # noqa: BLE001
            base["errors"].append(f"instagram reach per day: {_short(e)}")
    if c.get("page_id"):
        try:
            fb = fb_days(c, since, until)
            for day, v in fb.items():
                base["daily"].setdefault(day, {})["fb"] = v
            base["fb"] = om.window_sums(fb)
        except Exception as e:                                 # noqa: BLE001
            base["errors"].append(f"facebook page: {_short(e)}")
    base["daily"] = {k: base["daily"][k] for k in sorted(base["daily"])}
    return base


# ============================================================================================
# stories: numbers before Meta drops them (24 h)
# ============================================================================================

def live_stories(d, bid, now, min_age=timedelta(0)):
    """Published Instagram stories of `bid` aged [min_age, 24 h) that are not final yet."""
    out = []
    for p in d.get("posts") or []:
        if not (isinstance(p, dict) and p.get("brand") == bid and p.get("status") == "published" and p.get("remote_id")
                and p.get("platform") == "ig" and p.get("format") == "story"):
            continue
        at = _utc(p.get("published_at"))
        if at is None or (p.get("metrics") or {}).get("final"):
            continue
        if min_age <= now - at < STORY_LIFE:
            out.append(p)
    return out


def pull_stories(d, bid, c, now=None, min_age=timedelta(0)):
    """{post id: metrics} for the brand's live stories (final once 20 h old: numbers this close to the end are kept)."""
    now = now or utcnow()
    got = {}
    for p in live_stories(d, bid, now, min_age):
        try:
            m = pull_post(p, c)
        except Exception as e:                                 # noqa: BLE001
            print(f"  {p['id']}: story numbers not pulled ({_short(e)})")
            continue
        if m:
            m["pulled_at"] = ap.now_iso()
            if now - _utc(p["published_at"]) >= STORY_FINAL_AFTER:
                m["final"] = True
            got[p["id"]] = m
    return got


def _merge_posts(d, got):
    for pid, m in got.items():
        q = ap.post(d, pid)
        if q is not None:
            merged = {k: v for k, v in (q.get("metrics") or {}).items() if k != "error"}
            merged.update(m)
            q["metrics"] = merged


def stories(bid=None, now=None):
    """The publisher's tick: stories 20–24 h old get their last numbers. Never raises (publishing must not care)."""
    try:
        now = now or utcnow()
        d = ap.load()
        for b in d.get("brands") or []:
            if not isinstance(b, dict) or not b.get("id") or (bid and b["id"] != bid):
                continue
            if not live_stories(d, b["id"], now, STORY_FINAL_AFTER):
                continue
            c = pub.creds(b["id"])
            if not c:
                continue
            got = pull_stories(d, b["id"], c, now, STORY_FINAL_AFTER)
            if got:
                with ap.transaction() as d2:
                    _merge_posts(d2, got)
                print(f"{b['id']}: {len(got)} stor{'y' if len(got) == 1 else 'ies'}: numbers pulled before they expire")
    except Exception as e:                                     # noqa: BLE001
        print(f"stories: {type(e).__name__}: {str(e)[:160]}")


# ============================================================================================
# storing
# ============================================================================================

def store(d, bid, got=None, base=None, posts=None, keep_days=KEEP_DAYS):
    """Patch metrics[bid] (daily, account, followers, baseline) and posts[].metrics in an open transaction."""
    allm = d.setdefault("metrics", {})
    m = allm.get(bid) if isinstance(allm.get(bid), dict) else {}
    allm[bid] = m
    if got:
        daily = m.get("daily") if isinstance(m.get("daily"), dict) else {}
        for day, v in got.get("daily", {}).items():
            cur = dict(daily.get(day)) if isinstance(daily.get(day), dict) else {}
            cur.update({net: vals for net, vals in v.items() if vals})
            if cur:
                daily[day] = cur
        m["daily"] = {k: daily[k] for k in sorted(daily)[-keep_days:]}
        prev = m.get("account") if isinstance(m.get("account"), dict) else {}
        acct = {net: (got.get("account") or {}).get(net) or prev.get(net) for net in ("ig", "fb")}
        m["account"] = dict({k: v for k, v in acct.items() if v}, pulled_at=ap.now_iso(), errors=got.get("errors") or [])
        fb_f = ((got.get("account") or {}).get("fb") or {}).get("followers")
        ig_f = ((got.get("account") or {}).get("ig") or {}).get("followers")
        if fb_f is not None:
            m["followers"] = fb_f
        elif ig_f is not None and not prev.get("fb") and m.get("followers") is None:
            m["followers"] = ig_f                              # no Page: Instagram's own count
        m.setdefault("leads", 0)
    if base:
        m["baseline"] = base
    if posts:
        _merge_posts(d, posts)
    return m


def daily(bid=None, days=3, now=None, force_baseline=False):
    """The daily account pull for every brand with credentials (or just `bid`)."""
    now = now or utcnow()
    snap = ap.load()
    done = 0
    for b in snap.get("brands") or []:
        if not isinstance(b, dict) or not b.get("id") or (bid and b["id"] != bid):
            continue
        c = pub.creds(b["id"])
        if not c:
            print(f"{b['id']}: no credentials (meta-{b['id']}.json) — skipped")
            continue
        got = account_days(b, c, days, now)
        posts = pull_stories(snap, b["id"], c, now)
        cur = ((snap.get("metrics") or {}).get(b["id"]) or {}).get("baseline")
        base = pull_baseline(snap, b, c, now) if (force_baseline or needs_baseline(cur, now)) else None
        with ap.transaction() as d:
            store(d, b["id"], got, base, posts)
        done += 1
        ig = sum(1 for v in got["daily"].values() if v.get("ig"))
        fb = sum(1 for v in got["daily"].values() if v.get("fb"))
        print(f"{b['id']}: account numbers for {ig} Instagram / {fb} Facebook day(s) · followers "
              f"{(got['account'].get('ig') or {}).get('followers', '—')} IG / {(got['account'].get('fb') or {}).get('followers', '—')} FB"
              + (f" · {len(posts)} stor{'y' if len(posts) == 1 else 'ies'}" if posts else "")
              + (f" · baseline {base['since']}…{base['until']} ({'final' if base['final'] else 'provisional'})" if base else "")
              + (f" · errors: {'; '.join(got['errors'])}" if got["errors"] else "")
              + (f" · baseline errors: {'; '.join(base['errors'])}" if base and base.get("errors") else ""))
    return done


def baseline(bid, force=False, now=None):
    now = now or utcnow()
    snap = ap.load()
    b = ap.brand(snap, bid)
    if not b:
        raise SystemExit(f"unknown brand {bid}")
    c = pub.creds(bid)
    if not c:
        print(f"{bid}: no credentials (meta-{bid}.json) — no baseline")
        return None
    cur = ((snap.get("metrics") or {}).get(bid) or {}).get("baseline")
    if not force and not needs_baseline(cur, now):
        print(f"{bid}: baseline {cur.get('since')}…{cur.get('until')} is in place (--force pulls it again)")
        return cur
    base = pull_baseline(snap, b, c, now)
    if base is None:
        print(f"{bid}: joined more than two years ago — Meta has no data for a baseline")
        return None
    with ap.transaction() as d:
        store(d, bid, base=base)
    print(f"{bid}: baseline {base['since']}…{base['until']} · IG {base['ig'] or '—'} · FB {base['fb'] or '—'}"
          + (f" · errors: {'; '.join(base['errors'])}" if base["errors"] else ""))
    return base


# ============================================================================================
# the weekly loop
# ============================================================================================

def run(dry=False, bid=None, days=7):
    snap = ap.load()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pulled = {}                                     # brand -> {"page":…, "posts": {id: metrics}, "baseline": …}
    for b in snap["brands"]:
        if bid and b["id"] != bid:
            continue
        c = None if dry else pub.creds(b["id"])
        posts = [p for p in snap["posts"] if p["brand"] == b["id"] and p["status"] == "published"]
        recent = [p for p in posts if (_utc(p.get("published_at")) or since - timedelta(days=1)) >= since]
        if c:
            got = {"page": pull_page(c) if c.get("page_id") else {}, "posts": {}}
            for p in recent:
                try:
                    m = pull_post(p, c)
                    if m is not None:
                        m["pulled_at"] = ap.now_iso(); got["posts"][p["id"]] = m
                except pub.GraphError as e:
                    got["posts"][p["id"]] = {"error": str(e)}
                except Exception as e:
                    got["posts"][p["id"]] = {"error": f"{type(e).__name__}: {e}"[:200]}
            if needs_baseline(((snap.get("metrics") or {}).get(b["id"]) or {}).get("baseline")):
                got["baseline"] = pull_baseline(snap, b, c)          # an old box without the daily job still gets one
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
                        keep = {k: v for k, v in (q.get("metrics") or {}).items() if k == "final"}
                        q["metrics"] = dict(keep, **m)
                recent = [p for p in posts if p["id"] in got["posts"]]
                page = got["page"]
                prev = d.get("metrics", {}).get(b["id"], {})
                prev = prev if isinstance(prev, dict) else {}
                tot = dict(prev)                               # daily / account / baseline stay; the weekly keys are replaced
                tot.update({"reach": sum(_n((p.get("metrics") or {}).get("reach")) for p in recent),
                            "saves": sum(_n((p.get("metrics") or {}).get("saves")) for p in recent),
                            "clicks": sum(_n((p.get("metrics") or {}).get("clicks")) for p in recent),
                            "leads": _n(prev.get("leads")),
                            "followers": page.get("followers") if page.get("followers") is not None else prev.get("followers"),
                            "page_reach_week": page.get("page_reach_week")})
                d.setdefault("metrics", {})[b["id"]] = tot
                if got.get("baseline"):
                    store(d, b["id"], base=got["baseline"])
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


def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a and not a[0].startswith("-") else None
    if cmd == "daily":
        daily(_opt(a, "--brand"), days=int(_opt(a, "--days", 3)), force_baseline="--force-baseline" in a)
    elif cmd == "baseline" and _opt(a, "--brand"):
        baseline(_opt(a, "--brand"), force="--force" in a)
    elif cmd == "stories":
        stories(_opt(a, "--brand"))
    elif cmd is None:
        run(dry="--dry" in a, bid=_opt(a, "--brand"), days=int(_opt(a, "--days", 7)))
    else:
        print(__doc__)
        sys.exit(2)
