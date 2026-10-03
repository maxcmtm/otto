#!/usr/bin/env python3
"""Otto progress — what Otto is making for a brand right now, said honestly to the client app.

otto_api.with_work adds to every answer of GET /otto-api/data (and the data an action returns), per brand of that answer:
  brands[].work = {
    "copy":   {"state", "done", "total", "first_week", "eta_minutes"?, "next_run"?}   the next 7 days' copy (otto_copy)
    "images": {"state", "pending", "eta_minutes"?, "next_run"?}                      cards a copy run left to render
    "reels":  {"state", "pending", "eta_minutes"?, "next_run"?}                      reel videos (otto_cron "reels")
    "active": bool,     something is being made right now (the app polls every ~10 s while it is)
    "at": ISO UTC}      when this was worked out (the app counts eta_minutes down between answers)
and on every post that is still being made: posts[].work = {"what": "copy" | "image" | "video", "state", "next_run"?}.
next_run is the brand's wall clock ("2026-10-03T05:30", like posts[].slot); eta_minutes is minutes from "at".

States — only what is true:
  writing    a copy run is writing this brand now: a claimed queue file (OTTO_COPY_QUEUE/<id>.work), a run that started
             (kickoff.copy_try_at) and has not finished (the usage ledger's last run for the brand is older — otto_copy
             note_run stamps a run's end), or posts saved by a run that has not finished (each batch is saved when done)
  queued     a run is about to start: OTTO_COPY_QUEUE/<id>.week, a trial kickoff of the last 15 minutes (it spawned the run),
             or the daily copy job is running and has not reached this brand yet
  rendering  images: the claimed queue run renders them now · reels: the reels job is running and has not done this brand
  scheduled  the next automatic run does it, at next_run: the hourly trials job (:05 UTC) — a trial's first week 15 minutes
             after the kickoff and 50 minutes after the last try (otto_trial.copy_catchup), and the cards a run left pending
             (render_pending, no key needed); the daily copy job at 05:30 brand time (brands[].copy_auto, status active, a
             plan with organic content — otto_cron's own gates); the reels job at 18:30 brand time
  waiting    nothing automatic will do it: no Anthropic key or the copywriter switched off, copy written by hand
             (copy_auto off), paused or no plan, a format the plan lacks, a post held for review, a render that failed — the
             app then says Otto's team prepares it, without a spinner
  done       nothing left to make in the next 7 days
eta_minutes while writing: the run's own pace once it has saved two posts, before that rounds of batch × parallel posts
(anthropic.json) at ~2.5 minutes each plus a minute for the cards; queued: that estimate plus a minute; scheduled: the
minutes until next_run.
Never in the answer: a cost, a token count, a model, a cap, a key, a job name or a reason from the owner's ledger. It only
adds to an answer otto_api has already scoped to the caller's brands (client_view's tenant rule holds: the posts it marks
are that answer's own). Read-only: it never writes data.json, the ledger or the queue and never takes a run's lock.
Stdlib only.
"""
import math, os
from datetime import datetime, time as dtime, timedelta, timezone

import ap

RUN_MAX = timedelta(minutes=45)        # otto_cron's copy job limit: a run that started longer ago and never ended is gone
QUEUE_STALE = timedelta(hours=2)       # a .week file this old is not being picked up: the hourly catch-up is what is left
JOB_RUNNING_MAX = timedelta(hours=3)   # a job heartbeat "running" older than this is a crashed run
ROUND_MIN = 2.5                        # minutes for one round of parallel batches (draft, checks, the odd rewrite)
RENDER_MIN = 1                         # minutes for a run's cards
FIRST_WEEK_SHOWN = timedelta(days=2)   # how long after a trial's kickoff its first week counts as "the first week"
TRIALS_MINUTE = 5                      # otto_cron "trials": hourly at :05 UTC
IMAGE_STATUSES = ("draft", "pending_approval", "approved", "scheduled")      # otto_copy.render_pending's posts
REEL_STATUSES = ("draft", "pending_approval")                                # otto_video.py missing
ACTIVE = ("writing", "queued", "rendering")


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(v):
    x = ap.parse_iso(v) if isinstance(v, str) and v else None
    return (x if x.tzinfo else x.replace(tzinfo=timezone.utc)) if x else None


def _mtime(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def _copy(p):
    c = p.get("copy")
    return c if isinstance(c, dict) else {}


def _written(p):
    return bool(str(p.get("hook") or "").strip() or str(p.get("caption") or "").strip())


def _mins(dt, now):
    return max(1, math.ceil((dt - now).total_seconds() / 60))


def next_tick(after, minute):
    """The first hourly systemd tick at :minute UTC at or after `after`."""
    t = after.astimezone(timezone.utc).replace(minute=minute, second=0, microsecond=0)
    return t if t >= after else t + timedelta(hours=1)


def next_local(job, tz, now, last_day=None):
    """When otto_cron's wall-clock job (JOBS[job].local, "05:30") runs next for a brand in `tz`: later today, the next
    hourly tick while today's run is due but has not happened (last_day = the local day of its last run), else tomorrow."""
    import otto_cron
    _, _, hh, mm = otto_cron.parse_local(otto_cron.JOBS[job].local)
    loc = now.astimezone(tz)
    target = loc.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if loc < target:
        return target
    if loc - target < otto_cron.CATCH_UP and last_day != loc.date().isoformat():
        return next_tick(now, mm)
    return datetime.combine(loc.date() + timedelta(days=1), dtime(hh, mm), tzinfo=tz)


class Ctx:
    """What one answer needs once, whatever the number of brands: the copywriter's config, its ledger of runs, the queue,
    the job heartbeats."""

    def __init__(self, now):
        import otto_copy, otto_cron
        self.copy, self.cron, self.now = otto_copy, otto_cron, now
        cfg = otto_copy.config()
        self.ready = otto_copy.ready(cfg)
        self.per_round = max(1, int(cfg.get("batch") or 4) * int(cfg.get("parallel") or 2))
        _, runs = otto_copy.usage_today(now)
        self.runs = runs if isinstance(runs, dict) else {}
        self.queue = otto_copy.queue_dir()
        jobs = otto_cron.read_heartbeats().get("jobs")
        self.beats = jobs if isinstance(jobs, dict) else {}

    def beat(self, job):
        x = self.beats.get(job)
        return x if isinstance(x, dict) else {}

    def last_day(self, job, bid):
        r = (self.beat(job).get("brands") or {}).get(bid)
        return r.get("day") if isinstance(r, dict) else None

    def running(self, job):
        r = self.beat(job).get("running")
        started = _dt(r.get("started")) if isinstance(r, dict) else None
        return started if started and self.now - started < JOB_RUNNING_MAX else None

    def job_runs(self, job, d, b):
        """Does otto_cron's `job` run for this brand at all (status, paused, brands[].cron.off, copy_auto, plan gates)?"""
        today = self.now.astimezone(ap.brand_tz(b)).date()
        return self.cron.brand_skip(b, job) is None and self.cron.plan_skip(job, b, d, today) is None


def _run_state(b, posts, ctx):
    """Is a copy run on this brand right now? → ("writing", its start or None) | ("queued", None) | (None, None)."""
    now, bid = ctx.now, b["id"]
    k = b.get("kickoff") if isinstance(b.get("kickoff"), dict) else {}
    last = ctx.runs.get(bid) if isinstance(ctx.runs.get(bid), dict) else {}
    end = _dt(last.get("at"))
    if ctx.queue:
        m = _mtime(ctx.queue / f"{bid}.work")
        if m and now - m < RUN_MAX:
            return "writing", m
    tried = _dt(k.get("copy_try_at"))
    if tried and now - tried < RUN_MAX and (end is None or end < tried):
        return "writing", tried
    saved = [t for t in (_dt(_copy(p).get("at")) for p in posts if _copy(p).get("by") == "otto_copy") if t]
    fresh = [t for t in saved if end is None or t > end]
    if fresh and now - max(fresh) < RUN_MAX:
        return "writing", min(fresh)
    if ctx.queue:
        m = _mtime(ctx.queue / f"{bid}.week")
        if m and now - m < QUEUE_STALE:
            return "queued", None
    elif k.get("copy_needed") and not tried:
        import otto_trial
        at = _dt(k.get("at"))
        if at and timedelta(0) <= now - at < otto_trial.COPY_CATCHUP:
            return "queued", None                          # the kickoff spawned the run a moment ago
    return None, None


def _next_copy(d, b, ctx):
    """When the next automatic run writes this brand's copy, or None (nothing automatic will)."""
    import otto_trial
    now, out = ctx.now, []
    k = b.get("kickoff") if isinstance(b.get("kickoff"), dict) else {}
    if k.get("copy_needed") and not ap.plan_ended(d, b["id"]):
        at, tried = _dt(k.get("at")), _dt(k.get("copy_try_at"))
        t0 = max([now] + ([at + otto_trial.COPY_CATCHUP] if at else []) + ([tried + otto_trial.COPY_RETRY] if tried else []))
        out.append(next_tick(t0, TRIALS_MINUTE))
    if ctx.job_runs("copy", d, b):
        out.append(next_local("copy", ap.brand_tz(b), now, ctx.last_day("copy", b["id"])))
    return min(out) if out else None


def _daily_queued(d, b, ctx):
    """The daily copy job is running and this brand's turn today has not come yet."""
    started = ctx.running("copy")
    if not started or not ctx.job_runs("copy", d, b):
        return False
    tz = ap.brand_tz(b)
    loc = ctx.now.astimezone(tz)
    _, _, hh, mm = ctx.cron.parse_local(ctx.cron.JOBS["copy"].local)
    return loc >= loc.replace(hour=hh, minute=mm, second=0, microsecond=0) and ctx.last_day("copy", b["id"]) != loc.date().isoformat()


def brand_work(d, b, posts, ctx):
    """(brands[].work, {post id: posts[].work}) for one brand. d = the whole data.json, b = its full brand record, posts =
    that brand's posts."""
    now, bid, cp = ctx.now, b["id"], ctx.copy
    tz = ap.brand_tz(b)
    wall = lambda t: t.astimezone(tz).strftime("%Y-%m-%dT%H:%M")
    lo, hi = now + cp.LEAD, now + timedelta(days=cp.DAYS)
    due = cp.due_posts(d, b, now, cp.DAYS, retry_failed=True)       # exactly what the next run writes
    due_ids = {p["id"] for p in due}
    done, retry, later, team = [], [], [], []
    for p in posts:
        if not isinstance(p, dict) or not p.get("id") or p.get("status") == "skipped":
            continue
        slot = ap.slot_dt(p, b)
        if slot is not None and lo <= slot <= hi and _written(p):
            done.append(p)
        if p.get("status") != "draft" or p["id"] in due_ids:
            continue
        if _written(p):
            if _copy(p).get("state") == "held":
                team.append(p)                             # written, held by Otto's checks for a person
            continue
        if slot is None or slot < lo:
            continue                                       # its slot is (nearly) gone: no run writes it any more
        if slot > hi:
            later.append((p, slot))
        elif _copy(p).get("state") == "failed":
            retry.append(p)                                # the last try failed: retried 50 minutes later
        else:
            team.append(p)                                 # a format the plan does not include
    marks = {}                                             # post id → posts[].work (copy first, then image, then video)
    k = b.get("kickoff") if isinstance(b.get("kickoff"), dict) else {}
    kat = _dt(k.get("at"))
    first_week = bool(k.get("done")) and (bool(k.get("copy_needed")) or bool(kat and now - kat < FIRST_WEEK_SHOWN))
    skip = cp.plan_skip(d, b)
    can = ctx.ready and not skip
    nxt = _next_copy(d, b, ctx) if can else None

    # ---- copy: the next 7 days
    copy = {"state": "done", "done": len(done), "total": len(done) + len(due) + len(retry), "first_week": first_week}
    run, start = _run_state(b, posts, ctx)
    if due:
        if run == "writing":
            copy["state"] = "writing"
        elif not can:
            copy["state"] = "waiting"
        elif run == "queued" or _daily_queued(d, b, ctx):
            copy["state"] = "queued"
        elif nxt:
            copy.update(state="scheduled", next_run=wall(nxt), eta_minutes=_mins(nxt, now))
        else:
            copy["state"] = "waiting"
        if copy["state"] in ("writing", "queued"):
            est = math.ceil(len(due) / ctx.per_round) * ROUND_MIN + RENDER_MIN
            eta = est + 1
            if copy["state"] == "writing" and start:
                el = max(0.0, (now - start).total_seconds() / 60)
                n = sum(1 for p in posts if _copy(p).get("by") == "otto_copy" and (_dt(_copy(p).get("at")) or start) >= start)
                eta = len(due) * el / n if n >= 2 and el > 0 else est - el
            copy["eta_minutes"] = max(1, min(60, math.ceil(eta)))
    elif retry:
        copy.update({"state": "scheduled", "next_run": wall(nxt), "eta_minutes": _mins(nxt, now)} if nxt else {"state": "waiting"})
    for p in due:
        marks.setdefault(p["id"], {"what": "copy", "state": copy["state"], **({"next_run": copy["next_run"]} if "next_run" in copy else {})})
    for p in retry:
        marks.setdefault(p["id"], {"what": "copy", "state": "scheduled", "next_run": wall(nxt)} if nxt else {"what": "copy", "state": "waiting"})
    daily = can and ctx.job_runs("copy", d, b)
    for p, slot in later:                                  # written by the first daily run with the slot inside its 7 days
        enters = slot - timedelta(days=cp.DAYS)
        at = next_local("copy", tz, enters, enters.astimezone(tz).date().isoformat()) if daily else None
        marks.setdefault(p["id"], {"what": "copy", "state": "scheduled", "next_run": wall(at)} if at else {"what": "copy", "state": "waiting"})
    for p in team:
        marks.setdefault(p["id"], {"what": "copy", "state": "waiting"})

    # ---- images: the cards a run could not render where it ran (copy.render "pending" → otto_copy.render_pending)
    img_pend = [p for p in posts if isinstance(p, dict) and _copy(p).get("render") == "pending" and not p.get("image")
                and p.get("status") in IMAGE_STATUSES and _written(p)]
    img_bad = [p for p in posts if isinstance(p, dict) and _copy(p).get("render") == "failed" and not p.get("image")
               and p.get("status") in IMAGE_STATUSES]
    images = {"state": "done", "pending": len(img_pend) + len(img_bad)}
    if img_pend:
        claimed = ctx.queue and _mtime(ctx.queue / f"{bid}.work")
        if claimed and now - claimed < RUN_MAX:            # the queued run renders right after it writes
            images.update(state="rendering", eta_minutes=max(1, math.ceil(len(img_pend) / 3)))
        else:
            t = next_tick(now, TRIALS_MINUTE)
            images.update(state="scheduled", next_run=wall(t), eta_minutes=_mins(t, now))
    elif img_bad:
        images["state"] = "waiting"
    for p in img_pend:
        marks.setdefault(p["id"], {"what": "image", "state": images["state"], **({"next_run": images["next_run"]} if "next_run" in images else {})})
    for p in img_bad:
        marks.setdefault(p["id"], {"what": "image", "state": "waiting"})

    # ---- reels: the video of a written reel (otto_cron "reels", 18:30 brand time)
    reels_todo = [p for p in posts if isinstance(p, dict) and p.get("format") == "reel" and not p.get("video")
                  and p.get("status") in REEL_STATUSES and _written(p)]
    reels = {"state": "done", "pending": len(reels_todo)}
    if reels_todo:
        last = ctx.last_day("reels", bid)
        loc = now.astimezone(tz)
        if not ctx.job_runs("reels", d, b):
            reels["state"] = "waiting"
        elif ctx.running("reels") and last != loc.date().isoformat() and next_local("reels", tz, now, last) <= now + timedelta(hours=1):
            reels["state"] = "rendering"
        else:
            t = next_local("reels", tz, now, last)
            reels.update(state="scheduled", next_run=wall(t), eta_minutes=_mins(t, now))
    for p in reels_todo:
        marks.setdefault(p["id"], {"what": "video", "state": reels["state"], **({"next_run": reels["next_run"]} if "next_run" in reels else {})})

    brand = {"copy": copy, "images": images, "reels": reels, "at": iso(now),
             "active": copy["state"] in ACTIVE or images["state"] in ACTIVE or reels["state"] in ACTIVE}
    return brand, marks


def with_work(view, full=None, now=None, on_error=None):
    """brands[].work and posts[].work on an answer of /otto-api/data: a client_view (full = the whole data.json it was cut
    from) or the owner's whole data (full None). Only the answer's own brands and posts are touched; a post that gets work
    is a copy (the loaded data is never changed). Never fails the request: without the copywriter module or on any error a
    brand simply carries no work."""
    src = full if full is not None else view
    now = now or utcnow()
    try:
        ctx = Ctx(now)
    except Exception as e:                                  # noqa: BLE001 — the app works without it
        if on_error:
            on_error(f"work: {type(e).__name__}: {e}")
        return view
    mine = {b.get("id") for b in view.get("brands") or [] if isinstance(b, dict) and b.get("id")}
    posts = {}
    for p in src.get("posts") or []:
        if isinstance(p, dict) and p.get("brand") in mine:
            posts.setdefault(p["brand"], []).append(p)
    marks = {}
    for b in view.get("brands") or []:
        if not isinstance(b, dict) or not b.get("id"):
            continue
        try:
            w, pw = brand_work(src, ap.brand(src, b["id"]) or b, posts.get(b["id"], []), ctx)
        except Exception as e:                              # noqa: BLE001 — one brand never fails the answer
            if on_error:
                on_error(f"work {b['id']}: {type(e).__name__}: {e}")
            continue
        b["work"] = w
        marks.update(pw)
    if marks:
        view["posts"] = [dict(p, work=marks[p["id"]]) if isinstance(p, dict) and p.get("brand") in mine and p.get("id") in marks
                         else p for p in view.get("posts") or []]
    return view


def copy_summary(bid, now=None):
    """The copy part of one brand's work, for onboarding's answer (state, done, total, eta_minutes, next_run) or None."""
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        return None
    v = with_work({"brands": [dict(b)], "posts": []}, full=d, now=now)
    c = ((v["brands"][0].get("work") or {}).get("copy")) or None
    return {k: c[k] for k in ("state", "done", "total", "first_week", "eta_minutes", "next_run") if k in c} if c else None
