#!/usr/bin/env python3
"""Otto job dispatcher — one systemd timer per job, one run per brand that needs it (replaces the per-brand cron lines).

  otto_cron.py <job> [--dry] [--all | --brand B]   # the timers call this. --dry prints the commands and runs nothing;
                                                   # --all runs every active brand now, whatever its local time (by hand);
                                                   # --brand B runs only B, now
  otto_cron.py list                                # jobs, schedule, scope
  otto_cron.py status [--json]                     # last run of every job, from heartbeats.json
  otto_cron.py beat <job> <ok|failed|skipped|running> [--note text] [--started ISO] [--every MIN] [--label text] [--log text]
                                                   # heartbeat for the shell jobs (infra/backup.sh, infra/deploy.sh)
  otto_cron.py timers <dir>                        # (re)write the systemd .timer files from JOBS (infra/systemd/)

Jobs — wall-clock times are LOCAL: a per-brand job at the brand's time (brands[].tz), an owner job at the owner's time
(OTTO_OWNER_TZ, else OTTO_TZ, else Asia/Jerusalem). The old crontab's IL times, now DST-proof and right for every market:
  publish       every 15 min (UTC)  per brand   otto_publish.py --brand B                        kill switch
  watch         hourly at :15 (UTC) once        otto_watch.py watch
  watch-report  07:30 owner         once        otto_watch.py snapshot       (the daily metrics snapshot: drop alerts, growth)
  morning-report 07:35 brand        per brand   otto_report.py send --brand B               approvals channel: email and/or
                                                (the 7:35 message: yesterday, paid vs budget, today, decisions — by e-mail   telegram
                                                with the approvals inside, in Telegram followed by the cards; plan: reports)
  cards         08:00 brand         per brand   otto_telegram.py send-cards --brand B       approvals channel: telegram
                                                (catch-up: the 07:35 report already sent the cards it could)
  recs          18:30 owner         once        otto_telegram.py send-recs   (recommendation cards go to the owner)
  email-cards   08:00 brand         per brand   otto_email.py send-cards --brand B          approvals channel: email
                                                (catch-up: the 07:35 report e-mail already carried the posts due)
  email-recs    18:30 brand         per brand   otto_email.py send-recs --brand B           approvals channel: email
  genvisuals    18:00 brand         per brand   genvisuals.py --brand B --limit 12
  reels         18:30 brand         per brand   otto_video.py missing --brand B → otto_video.py render <id> for each id
  ads-launch    06:00 brand         per brand   otto_ads.py launch --brand B                     kill switch
  ads-guard     06:05 owner         once        otto_ads.py guard            (keeps pausing ended campaigns, kill switch or not)
  ads-report    07:15 brand         per brand   otto_ads.py report --brand B [--no-send]    (pulls yesterday's paid numbers
                                                for the 07:35 report; --no-send when the brand's Telegram report carries them)
  growth        05:10 owner         once        otto_growth.py rollup [--send on the owner's days 1-3: the month marker sends once]
  competitors   Mon 06:00 brand     per brand   otto_competitors.py sweep B [--country C]
  insights      Fri 06:00 brand     per brand   otto_insights.py --brand B
  plan-month    25th 06:00 brand    per brand   otto_plan.py build B <the brand's next month>
  ads-plan      25th 06:15 brand    per brand   otto_ads.py plan B <next month> [--budget N]
  whop-sync     02:20 (UTC)         once        otto_whop.py backfill        (only once api_key + company_id exist)
  track-prune   1st 04:00 (UTC)     once        otto_track.py prune --days 400
  retention     04:40 owner         once        otto_retention.py run   (deletion 90 days after a plan ended, notices, leads)
  trials        hourly at :05 (UTC) once        otto_trial.py run       (free trials: end them on the hour, reminder e-mails)
A local job's timer ticks every hour at the job's minute; each tick runs the brands (or the owner job) whose local time has
reached the job's time today, on the right local weekday / day of month, and that have not run it yet that local day. A tick
up to 3 hours late still counts (a reboot or an outage catches up); later than that, the day is skipped. Each brand runs once
per local day whether it succeeded or not — a failure alerts, and `otto run <job> --brand B` repeats it by hand.
In a zone with a half-hour offset the job runs at the first tick inside its hour (e.g. 08:30 instead of 08:00).

Brands: a per-brand job runs for every brand whose status is "active" (a brand without a status counts as active).
Onboarding, paused (brands[].paused or status "paused") and any other status sit it out; the heartbeat says why.
Plans (plans.json via ap.plan_of — PLAN_GATES): a brand whose plan does not include a job's feature sits it out with the
reason ("plan content has no paid ads" for ads-plan / ads-launch / ads-report; a free trial plans and reports paid ads but
sits ads-launch out: "plan trial plans and previews paid ads but launches none"; reels, Telegram cards, insights, competitor
sweep, visuals + the monthly plan likewise); a plan with a monthly competitor sweep runs it on the first Monday of the local
month only (--all / --brand run it anyway); a brand on the ended plan ("none": membership canceled) sits every job out.
ads-guard runs once for all brands whatever their plan, so a downgrade still pauses live campaigns and ends old flights.
Approvals channel (brands[].approvals, otto_email.approval_channels): "cards" runs for brands whose approvals include telegram
(a brand without the field = telegram, as before), "email-cards" / "email-recs" for brands whose approvals include email,
"morning-report" for brands with either; "app" sends nothing. The heartbeat names the channel as the reason.
Kill switch: while controls.publishing_paused is set, publish and ads-launch run nothing (checked again before every brand,
so flipping it mid-run stops the rest). Everything else keeps running.
Nothing to do is not a failure: plan-month / ads-plan skip a brand whose next month is already planned, ads-plan skips a
brand that answered "no ad budget yet" in onboarding, competitors skips a brand with no competitor list.
Per-brand overrides (optional, data.json brands[].cron): {"off": ["competitors", …], "ads_budget": 30, "country": "IL",
"visuals_limit": 12, "per_week": 12}. The ad market for competitors defaults to brands[].countries[0].
Leonardo key for genvisuals / reels: env LEONARDO_API_KEY, else $OTTO_SECRETS/leonardo.json {"api_key": …} (passed to the
child's environment only; never printed).

Heartbeat: heartbeats.json next to data.json (OTTO_HEARTBEATS) — {"updated", "jobs": {job: {label, schedule, every_min, log,
started, ended, duration_s, status ok|failed|skipped, exit, summary, brands: {id: {status, exit, duration_s, at, day,
tail | why}}, last_ok, last_failed, fails_in_row, checked, running: {started, pid, host} while it runs}}} — every write under
an flock on heartbeats.json.lock, then an atomic replace. A local job keeps each brand's latest result (and the local day it
ran, which is how a later tick knows it is done); an hourly tick with nothing due only updates "checked". The owner console
reads it through heartbeat_rows().
Lock: one run per job at a time (flock on locks/<job>.lock next to data.json, OTTO_LOCKS); a second run exits 75.
Exit: 0 = every brand ok, skipped or not due · 1 = at least one failed · 75 = the previous run still holds the lock · 2 = usage.
Output: each child's stdout/stderr is appended to the job's log next to data.json (publish.log, ads.log, … — the files the
owner console tails), this process prints one line per brand (the journal: journalctl -u otto-job@<job>).
Env for tests: OTTO_CRON_BIN (where the job scripts are), OTTO_CRON_TIMEOUT_S (per-brand time limit), OTTO_CRON_NOW (ISO time).
Stdlib only.
"""
import fcntl, json, os, re, shlex, signal, socket, subprocess, sys, threading, time
from collections import deque, namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import ap

HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("OTTO_CRON_BIN") or HERE)
PY = sys.executable or "python3"
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
EXIT_BUSY = 75
BRAND, ONCE = "brand", "once"
CATCH_UP = timedelta(hours=3)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# label · UTC OnCalendar (fixed jobs) · local time (wall-clock jobs: "HH:MM", "Mon HH:MM", "25th HH:MM") · cadence in minutes
# · log next to data.json · scope · kill switch applies · minutes per brand
Job = namedtuple("Job", "label calendar local every log scope kill timeout")
JOBS = {
    "publish": Job("Publisher", "*-*-* *:00/15:00", None, 15, "publish.log", BRAND, True, 20),
    "watch": Job("Hourly guard", "*-*-* *:15:00", None, 60, "watch.log", ONCE, False, 20),
    "watch-report": Job("Metrics snapshot", None, "07:30", 1440, "watch.log", ONCE, False, 20),
    "morning-report": Job("Morning report", None, "07:35", 1440, "report.log", BRAND, False, 30),
    "cards": Job("Approval cards", None, "08:00", 1440, "telegram.log", BRAND, False, 30),
    "recs": Job("Recommendation cards", None, "18:30", 1440, "telegram.log", ONCE, False, 20),
    "email-cards": Job("Approval e-mails", None, "08:00", 1440, "email.log", BRAND, False, 20),
    "email-recs": Job("Recommendation e-mails", None, "18:30", 1440, "email.log", BRAND, False, 20),
    "genvisuals": Job("Visuals", None, "18:00", 1440, "genvisuals.log", BRAND, False, 90),
    "reels": Job("Reels", None, "18:30", 1440, "reels.log", BRAND, False, 180),
    "ads-launch": Job("Paid launch", None, "06:00", 1440, "ads.log", BRAND, True, 30),
    "ads-guard": Job("Paid guard", None, "06:05", 1440, "ads.log", ONCE, False, 30),
    "ads-report": Job("Paid numbers", None, "07:15", 1440, "ads.log", BRAND, False, 30),
    "growth": Job("Growth ledger", None, "05:10", 1440, "growth.log", ONCE, False, 20),
    "competitors": Job("Competitor sweep", None, "Mon 06:00", 10080, "competitors.log", BRAND, False, 45),
    "insights": Job("Insights", None, "Fri 06:00", 10080, "insights.log", BRAND, False, 30),
    "plan-month": Job("Monthly plan", None, "25th 06:00", 44640, "plan.log", BRAND, False, 20),
    "ads-plan": Job("Monthly paid plan", None, "25th 06:15", 44640, "ads.log", BRAND, False, 30),
    "whop-sync": Job("Whop safety sync", "*-*-* 02:20:00", None, 1440, "whop.log", ONCE, False, 20),
    "track-prune": Job("Analytics prune", "*-*-01 04:00:00", None, 44640, "track.log", ONCE, False, 30),
}
# ---- data retention (otto_retention.py) — its own block: a brand's data 90 days after its plan ended (owner notices 14 and
# 3 days before), exports after 30 days, leads after OTTO_LEAD_RETENTION_DAYS. Daily at the owner's 04:40; the kill switch
# does not stop it (deletion is a legal promise, not publishing). ----
JOBS["retention"] = Job("Data retention", None, "04:40", 1440, "retention.log", ONCE, False, 30)
# ---- end data retention ----
# ---- free trials (otto_trial.py): hourly, so a trial ends on its hour (not up to a day late) and the day-5 / day-7 / day-8
# e-mails go out in their window. The kill switch does not stop it (ending a trial pauses work; it never starts any). ----
JOBS["trials"] = Job("Free trials", "*-*-* *:05:00", None, 60, "trials.log", ONCE, False, 20)
LEONARDO_JOBS = ("genvisuals", "reels")

# one unit of work: brand id ("*" = a job that runs once), argv, why it is skipped (None = run it), for reels the command
# each printed id is appended to, and the local day it counts for (wall-clock jobs)
Task = namedtuple("Task", "brand argv skip expand day")


def now_iso():
    return ap.now_iso()


def utcnow():
    v = os.environ.get("OTTO_CRON_NOW")
    dt = ap.parse_iso(v) if v else None
    if dt is not None:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def heartbeats_path():
    return Path(os.environ.get("OTTO_HEARTBEATS") or ap.DATA.parent / "heartbeats.json")


def locks_dir():
    return Path(os.environ.get("OTTO_LOCKS") or ap.DATA.parent / "locks")


def log_path(job):
    return ap.DATA.parent / JOBS[job].log


def owner_tz():
    for name in (os.environ.get("OTTO_OWNER_TZ"), os.environ.get("OTTO_TZ"), ap.DEFAULT_TZ):
        try:
            if name:
                return ZoneInfo(name)
        except Exception:
            continue
    return ZoneInfo(ap.DEFAULT_TZ)


def parse_local(spec):
    """"08:00" → (None, None, 8, 0) · "Mon 06:00" → (0, None, 6, 0) · "25th 06:00" → (None, 25, 6, 0)."""
    m = re.fullmatch(r"(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+|(\d{1,2})(?:st|nd|rd|th)\s+)?(\d{2}):(\d{2})", spec.strip())
    if not m:
        raise ValueError(f"bad local time {spec!r}")
    return (DAYS.index(m.group(1)) if m.group(1) else None, int(m.group(2)) if m.group(2) else None,
            int(m.group(3)), int(m.group(4)))


def calendar(job):
    """systemd OnCalendar (UTC): the fixed one, or for a local job an hourly tick at its minute."""
    j = JOBS[job]
    return j.calendar if j.local is None else f"*-*-* *:{parse_local(j.local)[3]:02d}:00"


def when(job):
    j = JOBS[job]
    if j.local:
        return f"{j.local} {'brand' if j.scope == BRAND else 'owner'} time"
    return {"*-*-* *:00/15:00": "every 15 min (UTC)", "*-*-* *:15:00": "hourly at :15 (UTC)", "*-*-* *:05:00": "hourly at :05 (UTC)",
            "*-*-01 04:00:00": "1st 04:00 (UTC)"}.get(j.calendar) or j.calendar.replace("*-*-* ", "").rsplit(":", 1)[0] + " (UTC)"


def local_due(job, tz, now, last_day=None):
    """(due, local day, why not). Due when the local time has reached the job's time on the right weekday / day of month,
    at most CATCH_UP ago, and this local day has not had its run yet."""
    wday, mday, hh, mm = parse_local(JOBS[job].local)
    loc = now.astimezone(tz)
    day = loc.date().isoformat()
    target = loc.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if (wday is not None and loc.weekday() != wday) or (mday is not None and loc.day != mday):
        return False, day, f"not its day (local {loc:%a %d})"
    if loc < target:
        return False, day, f"later today (local {loc:%H:%M}, runs {hh:02d}:{mm:02d})"
    if loc - target >= CATCH_UP:
        return False, day, f"missed today's window (local {loc:%H:%M})"
    if last_day == day:
        return False, day, "already ran today"
    return True, day, None


def next_month(today):
    return f"{today.year + today.month // 12:04d}-{today.month % 12 + 1:02d}"


def script(name):
    return str(BIN / name)


# ---------- who runs, and with what ----------

def cron_cfg(b):
    c = b.get("cron")
    return c if isinstance(c, dict) else {}


def brand_skip(b, job):
    """Why this brand sits `job` out, or None."""
    st = str(b.get("status") or "active").strip().lower()
    if b.get("paused") or st == "paused":
        return "paused"
    if st != "active":
        return st                                    # onboarding, churned, …
    if job in (cron_cfg(b).get("off") or []):
        return "turned off for this brand (brands[].cron.off)"
    return None


# plans.json gates: job → the plan feature it needs ("ads" = paid ads on any network). ads-guard is not here on purpose.
PLAN_GATES = {"ads-plan": "ads", "ads-launch": "ads", "ads-report": "ads", "reels": "reels", "cards": "telegram",
              "insights": "reports", "competitors": "competitor_sweep", "genvisuals": "organic", "plan-month": "organic",
              "email-cards": "organic", "email-recs": "organic",     # e-mail approvals come with every plan that makes content
              "morning-report": "reports"}
GATE_TEXT = {"reels": "reels", "telegram": "Telegram approvals", "reports": "reports", "competitor_sweep": "competitor sweep",
             "organic": "organic content"}


def plan_skip(job, b, d, today, force=False):
    """Why the brand's plan keeps it out of `job`, or None. Never raises: an unreadable plans.json only switches paid ads
    off (ap.no_ads_why says so)."""
    bid = b["id"]
    if ap.plan_ended(d, bid):
        return "no active plan (membership ended)"
    feat = PLAN_GATES.get(job)
    if not feat:
        return None
    if feat == "ads":                                # ads-launch: a trial plans + reports paid ads, launches none
        return ap.no_launch_why(d, bid) if job == "ads-launch" else ap.no_ads_why(d, bid)
    p = ap.plan_of(d, bid)
    if not p["features"].get(feat):
        return f"plan {p['id']} has no {GATE_TEXT[feat]}"
    if feat == "competitor_sweep" and p["features"][feat] == "monthly" and not force and today.day > 7:
        return f"plan {p['id']} sweeps competitors monthly (first Monday of the month)"
    return None


# approvals channel gates: job → the channel(s) brands[].approvals must include (a tuple: any of them)
CHANNEL_GATES = {"cards": "telegram", "email-cards": "email", "email-recs": "email", "morning-report": ("email", "telegram")}


def channel_skip(job, b):
    """Why the brand's approvals channel keeps it out of `job`, or None."""
    need = CHANNEL_GATES.get(job)
    if not need:
        return None
    import otto_email
    if set(need if isinstance(need, tuple) else (need,)) & set(otto_email.approval_channels(b)):
        return None
    return f"approvals {'in the app only' if not otto_email.approval_channels(b) else 'by ' + otto_email.approvals_label(b).lower()}" \
           " (brands[].approvals)"


def whop_connected():
    try:
        import otto_whop
        c = otto_whop.config()
        return bool(c.get("api_key") and c.get("company_id"))
    except Exception:
        return False


def once_argv(job, today):
    if job == "watch":
        return [PY, script("otto_watch.py"), "watch"]
    if job == "watch-report":
        return [PY, script("otto_watch.py"), "snapshot"]
    if job == "recs":
        return [PY, script("otto_telegram.py"), "send-recs"]
    if job == "ads-guard":
        return [PY, script("otto_ads.py"), "guard"]
    if job == "growth":                              # the monthly review goes out once (month marker); days 1-3 cover a missed 1st
        return [PY, script("otto_growth.py"), "rollup"] + (["--send"] if today.day <= 3 else [])
    if job == "whop-sync":
        return [PY, script("otto_whop.py"), "backfill"]
    if job == "track-prune":
        return [PY, script("otto_track.py"), "prune", "--days", "400"]
    # ---- data retention (otto_retention.py) ----
    if job == "retention":
        return [PY, script("otto_retention.py"), "run"]
    # ---- end data retention ----
    if job == "trials":
        return [PY, script("otto_trial.py"), "run"]
    raise KeyError(job)


def brand_task(job, b, d, today, brands_dir, day=None):
    """Task for one active brand (skip set when there is nothing to do). today = the brand's local date."""
    bid, cfg = b["id"], cron_cfg(b)
    ym = next_month(today)
    T = lambda argv, skip=None, expand=None: Task(bid, argv, skip, expand, day)
    if job == "publish":
        return T([PY, script("otto_publish.py"), "--brand", bid])
    if job == "cards":
        return T([PY, script("otto_telegram.py"), "send-cards", "--brand", bid])
    if job == "email-cards":
        return T([PY, script("otto_email.py"), "send-cards", "--brand", bid])
    if job == "email-recs":
        return T([PY, script("otto_email.py"), "send-recs", "--brand", bid])
    if job == "genvisuals":
        return T([PY, script("genvisuals.py"), "--brand", bid, "--limit", str(int(cfg.get("visuals_limit") or 12))])
    if job == "reels":
        return T([PY, script("otto_video.py"), "missing", "--brand", bid], expand=[PY, script("otto_video.py"), "render"])
    if job == "ads-launch":
        return T([PY, script("otto_ads.py"), "launch", "--brand", bid])
    if job == "morning-report":
        return T([PY, script("otto_report.py"), "send", "--brand", bid])
    if job == "ads-report":                          # the Telegram morning report carries the paid numbers: no 2nd message
        import otto_email
        quiet = "telegram" in otto_email.approval_channels(b) and all(ap.plan_of(d, bid)["features"].get(f) for f in ("reports", "telegram"))
        return T([PY, script("otto_ads.py"), "report", "--brand", bid] + (["--no-send"] if quiet else []))
    if job == "insights":
        return T([PY, script("otto_insights.py"), "--brand", bid])
    if job == "competitors":
        folder = Path(brands_dir) / bid
        if not (folder / "competitors.json").exists() and not (folder / "brand-profile.md").exists():
            return T(None, "no competitor list yet (brands/<id>/competitors.json)")
        country = cfg.get("country") or (b.get("countries") or [None])[0]
        return T([PY, script("otto_competitors.py"), "sweep", bid] + (["--country", str(country)] if country else []))
    if job == "plan-month":
        if any(p.get("brand") == bid and p.get("plan") == ym for p in d.get("posts", [])):
            return T(None, f"{ym} is already planned")
        extra = ["--per-week", str(int(cfg["per_week"]))] if cfg.get("per_week") else []
        return T([PY, script("otto_plan.py"), "build", bid, ym] + extra)
    if job == "ads-plan":
        if any(c.get("brand") == bid and c.get("plan") == ym for c in d.get("campaigns", [])):
            return T(None, f"{ym} paid plan already exists")
        if (b.get("onboarding") or {}).get("budget") == "not_yet":
            return T(None, "no ad budget yet (onboarding answer)")
        extra = ["--budget", f"{float(cfg['ads_budget']):g}"] if cfg.get("ads_budget") else []
        return T([PY, script("otto_ads.py"), "plan", bid, ym] + extra)
    raise KeyError(job)


def plan(job, d, now=None, brands_dir=None, last=None, force=False, only=None):
    """(tasks, not_due): what `job` does at `now`. tasks = [Task] to run or to record as skipped; not_due = {brand: why} for
    wall-clock jobs whose time it is not (never recorded). last = {brand: local day of its last run} (from the heartbeat).
    force (--all / --brand) ignores the clock; only = one brand id."""
    spec = JOBS[job]
    now = now or utcnow()
    brands_dir = brands_dir or ap.BRANDS
    last = last or {}
    ks = ap.paused(d) if spec.kill else None
    tasks, not_due = [], {}
    if spec.scope == ONCE:
        tz = owner_tz()
        day = None
        if spec.local and not force:
            due, day, why = local_due(job, tz, now, last.get("*"))
            if not due:
                return [], {"*": why}
        elif spec.local:
            day = now.astimezone(tz).date().isoformat()
        skip = ks
        if job == "whop-sync" and not skip and not whop_connected():
            skip = "Whop is not connected (no api_key + company_id in whop.json)"
        return [Task("*", once_argv(job, now.astimezone(tz).date()), skip, None, day)], {}
    for b in d.get("brands", []):
        bid = b.get("id") if isinstance(b, dict) else None
        if not bid or (only and bid != only):
            continue
        tz = ap.brand_tz(b)
        today = now.astimezone(tz).date()
        day = today.isoformat() if spec.local else None
        if spec.local and not force:
            due, day, why = local_due(job, tz, now, (last.get(bid) or None))
            if not due:
                not_due[bid] = why
                continue
        why = ks or brand_skip(b, job) or plan_skip(job, b, d, today, force) or channel_skip(job, b)
        tasks.append(Task(bid, None, why, None, day) if why else brand_task(job, b, d, today, brands_dir, day))
    return tasks, not_due


def tasks(job, d, today=None, brands_dir=None):
    """Every active brand's task for `job` regardless of the clock (today = the local date used for month / day logic)."""
    now = datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc) if today else None
    return plan(job, d, now, brands_dir, force=True)[0]


def child_env(job):
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if job in LEONARDO_JOBS and not env.get("LEONARDO_API_KEY"):
        try:
            k = json.loads((SECRETS / "leonardo.json").read_text()).get("api_key")
        except (OSError, ValueError, AttributeError):
            k = None
        if k:
            env["LEONARDO_API_KEY"] = str(k).strip()
    return env


def shown(argv):
    """argv as a human reads it: python3 otto_publish.py --brand alpha."""
    return shlex.join(["python3" if a == PY else Path(a).name if a.startswith(str(BIN) + os.sep) else a for a in argv])


# ---------- running ----------

def _kill(p, why):
    why.append("timed out")
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def time_limit(job):
    return float(os.environ.get("OTTO_CRON_TIMEOUT_S") or JOBS[job].timeout * 60)


def _run(argv, job, logf, tail, deadline, capture=False):
    """One command; output streamed into the job log. Returns (exit, captured stdout)."""
    logf.write(f"== {now_iso()} {job}: {shown(argv)}\n")
    logf.flush()
    out, why = [], []
    try:
        p = subprocess.Popen(argv, cwd=str(BIN), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, errors="replace", env=child_env(job), start_new_session=True)
    except OSError as e:
        tail.append(f"could not start: {e}")
        logf.write(f"could not start: {e}\n")
        return 127, ""
    killer = threading.Timer(max(1.0, deadline - time.time()), _kill, (p, why))
    killer.daemon = True
    killer.start()
    try:
        for line in p.stdout:
            logf.write(line)
            if line.strip():
                tail.append(line.strip()[:300])
            if capture:
                out.append(line)
        p.wait()
    finally:
        killer.cancel()
    logf.flush()
    if why:
        tail.append(f"killed: {why[0]} (limit {time_limit(job):.0f}s per brand)")
        return 124, "".join(out)
    return p.returncode, "".join(out)


def run_task(job, t, logf):
    """One brand: its command (for reels, then one render per printed id). Returns (exit, tail lines)."""
    deadline = time.time() + time_limit(job)
    tail = deque(maxlen=4)
    code, out = _run(t.argv, job, logf, tail, deadline, capture=bool(t.expand))
    if code or not t.expand:
        return code, list(tail)
    worst = 0
    for ident in [x.strip() for x in out.splitlines() if x.strip()]:
        c, _ = _run(t.expand + [ident], job, logf, tail, deadline)
        worst = worst or c
        if c == 124:
            break
    return worst, list(tail)


def acquire(job):
    """Exclusive, non-blocking flock for this job; None when the previous run still holds it. Held until exit."""
    d = locks_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = open(d / f"{job}.lock", "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


# ---------- heartbeats ----------

def read_heartbeats():
    try:
        hb = json.loads(heartbeats_path().read_text())
        return hb if isinstance(hb, dict) else {}
    except (OSError, ValueError):
        return {}


def job_beat(job):
    rec = (read_heartbeats().get("jobs") or {}).get(job)
    return rec if isinstance(rec, dict) else {}


def beat(job, update, drop=()):
    """Merge `update` into heartbeats.json jobs[job] under the heartbeat lock (atomic replace). Returns the new record."""
    path = heartbeats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        hb = read_heartbeats()
        jobs = hb.setdefault("jobs", {})
        rec = jobs.get(job) if isinstance(jobs.get(job), dict) else {}
        rec.update(update)
        for k in drop:
            rec.pop(k, None)
        jobs[job] = rec
        hb["updated"] = now_iso()
        ap._atomic_write(path, json.dumps(hb, ensure_ascii=False, indent=1) + "\n")
        return rec


def _meta(job):
    j = JOBS[job]
    return {"label": j.label, "schedule": when(job), "every_min": j.every, "log": j.log}


def finish(job, started, t0, status, code, summary, brands=None, meta=None):
    prev = job_beat(job)
    ended = now_iso()
    if brands is not None and job in JOBS and JOBS[job].local:
        merged = {k: v for k, v in (prev.get("brands") or {}).items() if isinstance(v, dict)}
        merged.update(brands)                            # wall-clock jobs keep every brand's latest result + its local day
        brands = merged
    rec = dict(meta or {}, started=started, ended=ended, duration_s=round(time.time() - t0, 1), status=status, exit=code,
               summary=summary, brands=brands or {},
               last_ok=ended if status == "ok" else prev.get("last_ok"),
               last_failed=ended if status == "failed" else prev.get("last_failed"),
               fails_in_row=(int(prev.get("fails_in_row") or 0) + 1) if status == "failed" else 0)
    return beat(job, rec, drop=("running",))


def summarize(results):
    ok = [b for b, r in results.items() if r["status"] == "ok"]
    bad = [b for b, r in results.items() if r["status"] == "failed"]
    skip = [r.get("why") or "" for r in results.values() if r["status"] == "skipped"]
    if list(results) == ["*"]:
        r = results["*"]
        return {"ok": "ok", "skipped": f"skipped: {r.get('why')}"}.get(r["status"]) or \
            f"failed (exit {r.get('exit')}): {(r.get('tail') or [''])[-1]}"[:300]
    parts = [f"{len(ok)} ok"]
    if bad:
        parts.append(f"{len(bad)} failed ({', '.join(bad[:6])}{' …' if len(bad) > 6 else ''})")
    if skip:
        kinds = {}
        for w in skip:
            k = w if len(w) < 40 else "other"
            kinds[k] = kinds.get(k, 0) + 1
        parts.append(f"{len(skip)} skipped (" + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])) + ")")
    return " · ".join(parts)


def last_days(job):
    return {b: r.get("day") for b, r in (job_beat(job).get("brands") or {}).items() if isinstance(r, dict) and r.get("day")}


def run(job, dry=False, force=False, only=None, now=None):
    spec = JOBS[job]
    now = now or utcnow()
    force = force or bool(only)
    if dry:
        todo, not_due = plan(job, ap.load(), now, last=last_days(job), force=force, only=only)
        n = sum(1 for t in todo if not t.skip)
        print(f"{job} (dry, {when(job)}) — {n} to run, {len(todo) - n} skipped, {len(not_due)} not due · log {log_path(job)}")
        for t in todo:
            if t.skip:
                print(f"  {t.brand:16} skipped: {t.skip}")
            else:
                print(f"  {t.brand:16} {shown(t.argv)}" + (f"  → then {shown(t.expand)} <id> for each id it prints" if t.expand else ""))
        for b, why in not_due.items():
            print(f"  {b:16} not due: {why}")
        return 0
    lock = acquire(job)
    if lock is None:
        print(f"{job}: the previous run is still going (lock {locks_dir() / (job + '.lock')}) — nothing started")
        return EXIT_BUSY
    started, t0 = now_iso(), time.time()
    meta = _meta(job)
    try:
        todo, not_due = plan(job, ap.load(), now, last=last_days(job), force=force, only=only)
    except Exception as e:                                   # data.json unreadable: that is a failure worth an alert
        msg = f"cannot plan {job}: {type(e).__name__}: {e}"[:300]
        print(msg, file=sys.stderr)
        finish(job, started, t0, "failed", 1, msg, meta=meta)
        return 1
    if not todo:                                             # a wall-clock tick with nobody due: note it, keep the last run
        beat(job, dict(meta, checked=started), drop=("running",))
        print(f"{job}: nothing due ({len(not_due)} not due)")
        return 0
    beat(job, dict(meta, running={"started": started, "pid": os.getpid(), "host": socket.gethostname()}))
    results = {}
    log_path(job).parent.mkdir(parents=True, exist_ok=True)
    with log_path(job).open("a", encoding="utf-8") as logf:
        for t in todo:
            why = t.skip
            if not why and spec.kill:                        # the kill switch or a brand pause can land mid-run
                try:
                    why = ap.paused(ap.load(), None if t.brand == "*" else t.brand)
                except Exception as e:
                    why = f"could not re-check the kill switch: {e}"[:200]
            stamp = {"at": now_iso()}
            if t.day:
                stamp["day"] = t.day
            if why:
                results[t.brand] = dict(stamp, status="skipped", why=why)
                print(f"{job} · {t.brand} skipped: {why}")
                continue
            b0 = time.time()
            code, tail = run_task(job, t, logf)
            r = dict(stamp, status="ok" if code == 0 else "failed", exit=code, duration_s=round(time.time() - b0, 1))
            if code:
                r["tail"] = tail
            results[t.brand] = r
            print(f"{job} · {t.brand} " + ("ok" if code == 0 else f"FAILED (exit {code})") + f" {r['duration_s']}s"
                  + (f": {tail[-1] if tail else ''}" if code else ""))
    failed = any(r["status"] == "failed" for r in results.values())
    ran = any(r["status"] == "ok" for r in results.values())
    status = "failed" if failed else "ok" if ran else "skipped"
    summary = summarize(results)
    finish(job, started, t0, status, 1 if failed else 0, summary, results, meta)
    print(f"{job}: {summary} — {time.time() - t0:.1f}s")
    return 1 if failed else 0


# ---------- the owner console + status ----------

def heartbeat_rows(now=None, path=None):
    """heartbeats.json as the owner console's scheduled-job rows (the shape of otto_admin.cron_rows): one row per timer job,
    plus the shell jobs that beat with a cadence (backup). [] while heartbeats.json does not exist (the console then falls
    back to log mtimes). status: running | never | failed | ok | late | stale — "failed" while the job's last run failed or
    any brand's latest result is a failure."""
    now = now or datetime.now(timezone.utc)
    try:
        hb = json.loads(Path(path or heartbeats_path()).read_text())
        jobs = hb.get("jobs") or {}
    except (OSError, ValueError, AttributeError):
        return []
    extra = sorted(k for k, v in jobs.items() if k not in JOBS and isinstance(v, dict) and v.get("every_min"))
    out = []
    for job in list(JOBS) + extra:
        h = jobs.get(job) if isinstance(jobs.get(job), dict) else {}
        spec = JOBS.get(job)
        every = spec.every if spec else int(h.get("every_min") or 1440)
        last = ap.parse_iso(h.get("ended"))
        age = round((now - last).total_seconds() / 60) if last and last.tzinfo else None
        started = ap.parse_iso((h.get("running") or {}).get("started"))
        limit = (spec.timeout if spec else 240) * 60 + 600
        failed_brands = sorted(b for b, r in (h.get("brands") or {}).items() if isinstance(r, dict) and r.get("status") == "failed")
        if started and started.tzinfo and (now - started).total_seconds() < limit:
            st = "running"
        elif age is None:
            st = "never"
        elif h.get("status") == "failed" or failed_brands:
            st = "failed"
        elif age <= every * 1.5 + 10:
            st = "ok"
        elif age <= every * 3 + 30:
            st = "late"
        else:
            st = "stale"
        out.append({"job": job, "label": (spec.label if spec else h.get("label")) or job,
                    "log": spec.log if spec else h.get("log") or f"journalctl -u otto-{job}", "every_min": every,
                    "last_run": h.get("ended"), "age_min": age, "status": st,
                    "last_line": (h.get("summary") or "")[:200] or None, "schedule": when(job) if spec else h.get("schedule"),
                    "failed_brands": failed_brands, "fails_in_row": int(h.get("fails_in_row") or 0)})
    return out


def status(as_json=False):
    rows = heartbeat_rows()
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print(f"no heartbeats yet ({heartbeats_path()})")
        return 0
    for r in rows:
        age = "—" if r["age_min"] is None else f"{r['age_min']} min ago" if r["age_min"] < 180 else f"{r['age_min'] // 60} h ago"
        extra = f"  [failed: {', '.join(r['failed_brands'])}]" if r["failed_brands"] else ""
        print(f"{r['job']:13} {r['status']:8} {age:>12}  {r['last_line'] or ''}{extra}")
    return 0


def timer_text(job):
    j = JOBS[job]
    return (f"# Generated by `python3 platform/otto_cron.py timers infra/systemd` from otto_cron.JOBS — edit JOBS, not this file.\n"
            + (f"# {j.local} is local time: this ticks hourly and otto_cron.py runs whoever's local time it is.\n" if j.local else "")
            + f"[Unit]\nDescription=Otto timer: {job} — {j.label}, {when(job)}\n\n"
            f"[Timer]\nOnCalendar={calendar(job)} UTC\nUnit=otto-job@{job}.service\nAccuracySec=30s\n"
            f"Persistent={'true' if j.local is None and j.every >= 1440 else 'false'}\n\n"
            f"[Install]\nWantedBy=timers.target\n")


def write_timers(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("otto-job-*.timer"):
        if old.name[len("otto-job-"):-len(".timer")] not in JOBS:
            old.unlink()
    for job in JOBS:
        (out / f"otto-job-{job}.timer").write_text(timer_text(job))
    print(f"{len(JOBS)} timers → {out}")


def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def main(a):
    cmd = a[0] if a else ""
    if cmd in JOBS:
        only = _opt(a, "--brand")
        if "--brand" in a and not only:
            print("--brand needs an id")
            return 2
        return run(cmd, dry="--dry" in a, force="--all" in a, only=only)
    if cmd == "list":
        for job, j in JOBS.items():
            print(f"{job:13} {when(job):24} {'per brand' if j.scope == BRAND else 'once':10}"
                  f"{'kill switch  ' if j.kill else '             '}{j.label} → {j.log}")
        return 0
    if cmd == "status":
        return status("--json" in a)
    if cmd == "timers" and len(a) > 1:
        write_timers(a[1])
        return 0
    if cmd == "beat" and len(a) > 2 and a[2] in ("ok", "failed", "skipped", "running"):
        job, st = a[1], a[2]
        started = _opt(a, "--started") or now_iso()
        meta = {k: v for k, v in (("label", _opt(a, "--label")), ("every_min", int(_opt(a, "--every")) if _opt(a, "--every") else None),
                                  ("log", _opt(a, "--log"))) if v is not None}
        if st == "running":
            beat(job, dict(meta, running={"started": started, "pid": os.getppid(), "host": socket.gethostname()}))
            return 0
        t0 = ap.parse_iso(started)
        t0 = t0.timestamp() if t0 and t0.tzinfo else time.time()
        finish(job, started, t0, st, 1 if st == "failed" else 0, (_opt(a, "--note") or st)[:300], meta=meta)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
