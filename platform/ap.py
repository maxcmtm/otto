#!/usr/bin/env python3
"""Otto platform state CLI. All writes to data.json go through here — either via the
CLI or via the helper functions below, which the engine scripts import.

Usage:
  ap.py list [brand] | pending
  ap.py add <brand> <pillar> <platform> <slot ISO> <hook...>
  ap.py status <post-id> <draft|pending_approval|approved|scheduled|publishing|published|skipped|failed>   # admin: no transition check
  ap.py decide <post-id> <approve|skip|later> [--via telegram|dashboard|auto]
  ap.py set <post-id> '<json-object>'          # merge fields into a post (hook, caption, image, format, brief…)
  ap.py brand-add <id> <name> <url> <lang> [pillar,pillar,...] [--tz Europe/Berlin] [--countries DE,AT] [--currency EUR]
                 [--plan content]                # tz/countries default from the url's country TLD, then the language;
                                                 # plan defaults to plans.json defaults.new (a paid subscription sets the paid one)
  ap.py plans                                    # the plans in plans.json and every brand's resolved plan
  ap.py recs | rec <rec-id> <proposed|approved|dismissed|done>
  ap.py rec-add <P0|P1|P2> <title> | <why> | <impact> | <cta>
  ap.py taste [brand]                            # what the owner's decisions taught us
  ap.py sync-fallback                            # rewrite index.html's fallback block: neutral (default) or, with
                                                 # OTTO_FALLBACK=full, the live data.json (owner-only machines)

Concurrency: every writer uses `with ap.transaction() as d:` — an exclusive flock on data.json.lock,
a fresh load, the change, then an atomic write (temp file + os.replace). Long network work (Meta,
Google, Leonardo, Telegram) happens OUTSIDE the lock; only the per-id patch runs inside it.

Env: OTTO_DATA (default ./data.json), OTTO_HTML (default ./index.html), OTTO_BRANDS (default ../brands),
     OTTO_TZ (default brand timezone when brands[].tz is not set; default Asia/Jerusalem)
"""
import fcntl, json, math, os, re, sys, tempfile, threading, urllib.parse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
DATA = Path(os.environ.get("OTTO_DATA") or HERE / "data.json")
HTML = Path(os.environ.get("OTTO_HTML") or HERE / "index.html")
BRANDS = Path(os.environ.get("OTTO_BRANDS") or HERE.parent / "brands")
STATUSES = {"draft", "pending_approval", "approved", "scheduled", "publishing", "published", "skipped", "failed"}
REC_STATUSES = {"proposed", "approved", "dismissed", "done"}
PLATFORMS = {"fb", "ig", "li"}
FORMATS = {"post", "carousel", "reel", "story", "video"}
DEFAULT_TZ = "Asia/Jerusalem"

# What the owner-facing surfaces (dashboard API, Telegram) may do to a post. The publisher and the
# admin CLI (`ap.py status`) move posts to publishing/published/failed themselves; nothing owner-facing
# can put a published/publishing/failed post back to approved (that is how double posts happen).
POST_TRANSITIONS = {
    "draft": {"pending_approval", "approved", "skipped"},
    "pending_approval": {"draft", "approved", "skipped"},
    "approved": {"pending_approval", "draft", "skipped", "scheduled"},
    "scheduled": {"approved", "pending_approval", "draft", "skipped"},
    "skipped": {"draft", "pending_approval"},
    "failed": {"draft", "pending_approval", "skipped"},     # re-review first; never straight back to approved
    "publishing": set(),                                    # may already be live — a human checks Meta first
    "published": set(),
}
REC_TRANSITIONS = {
    "proposed": {"approved", "dismissed", "done"},
    "approved": {"done", "dismissed"},
    "dismissed": {"proposed"},
    "done": set(),
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- storage: lock + atomic write ----------

_tx = threading.local()


def lock_path():
    return DATA.with_name(DATA.name + ".lock")


@contextmanager
def locked():
    """Exclusive flock on data.json.lock (re-entrant within one thread)."""
    if getattr(_tx, "depth", 0):
        _tx.depth += 1
        try:
            yield
        finally:
            _tx.depth -= 1
        return
    lp = lock_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        _tx.depth = 1
        try:
            yield
        finally:
            _tx.depth = 0
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextmanager
def transaction(sync=True):
    """with ap.transaction() as d: … — lock, fresh load, yield, atomic save. An exception inside the
    block discards the change (nothing is written). Nested blocks in the same thread share the outer d."""
    if getattr(_tx, "d", None) is not None:
        yield _tx.d
        return
    with locked():
        d = load()
        _tx.d = d
        try:
            yield d
        finally:
            _tx.d = None
        _write(d, sync)


def load():
    return json.loads(DATA.read_text())


def _atomic_write(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _write(d, sync=True):
    d["generated"] = now_iso()
    _atomic_write(DATA, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    if sync:
        try:
            sync_fallback(d)
        except OSError as e:          # the embedded copy is a convenience: data.json is already saved, the write stands
            print(f"ap: fallback sync failed ({type(e).__name__}: {e})", file=sys.stderr)


def save(d, sync=True):
    """Legacy whole-document save (atomic, under the lock). Prefer transaction(): a load() … save()
    pair around slow work can still overwrite someone else's change. Inside a transaction this is a no-op
    (the transaction writes on exit)."""
    if getattr(_tx, "d", None) is not None:
        return
    with locked():
        _write(d, sync)


def embed_json(d):
    """JSON safe to embed in <script type=application/json>: no '</' (closes the tag) and no '<!--'."""
    return json.dumps(d, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "\\u003c!--")


# What the dashboard's embedded fallback block carries. index.html is served to every signed-in client, so by default it
# holds no client data at all (a neutral, empty document the app renders as "nothing yet"); OTTO_FALLBACK=full embeds
# the live data.json for local development / demos on a machine only the owner uses.
NEUTRAL_FALLBACK = {"generated": None, "fallback": "neutral", "brands": [], "posts": [], "recommendations": [], "campaigns": [],
                    "connections": [], "metrics": {}}


def fallback_full():
    return (os.environ.get("OTTO_FALLBACK") or "").strip().lower() in ("full", "1", "true", "yes")


def sync_fallback(d=None):
    d = (d or load()) if fallback_full() else NEUTRAL_FALLBACK
    if not HTML.exists():
        return
    html = HTML.read_text()
    blob = embed_json(d)
    new = re.sub(r'(<script id="fallback-data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    if new != html:
        _atomic_write(HTML, new)
    print("fallback synced")


# ---------- helpers used by the engine scripts ----------

def _find(items, ident):
    """The record with this id; a malformed entry (not a dict, no id) is skipped, never a KeyError for every lookup."""
    return next((x for x in items or [] if isinstance(x, dict) and x.get("id") == ident), None) if ident is not None else None


def brand(d, bid):
    return _find(d.get("brands"), bid)


EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")


def norm_member(v):
    """A brand member as stored: a lower-case e-mail, or "@domain" for everyone signed in with that domain. None if invalid."""
    v = str(v or "").strip().lower()
    if v.startswith("@") and re.fullmatch(r"@[a-z0-9-]+(\.[a-z0-9-]+)+", v):
        return v
    return v if EMAIL.fullmatch(v) else None


def is_member(b, user, domains=True):
    """True when the signed-in user (an e-mail from the proxy or a Google sign-in) is on brands[].members (exactly, or by
    "@domain" when domains is true — a Google sign-in passes domains only for a Workspace account of that domain)."""
    user = str(user or "").strip().lower()
    if not user or "@" not in user:
        return False
    members = {str(m).strip().lower() for m in (b or {}).get("members") or []}
    return user in members or (bool(domains) and "@" + user.rsplit("@", 1)[1] in members)


def member_brands(d, user, domains=True):
    """Ids of the brands this signed-in user may see and act on."""
    return {b["id"] for b in d.get("brands", []) if isinstance(b, dict) and b.get("id") and is_member(b, user, domains)}


def post(d, pid):
    return _find(d.get("posts"), pid)


def rec(d, rid):
    return _find(d.get("recommendations"), rid)


def campaign(d, cid):
    return _find(d.get("campaigns"), cid)


def _num_suffix(ident, prefix):
    if not ident.startswith(prefix + "-"):
        return 0
    tail = ident[len(prefix) + 1:]
    return int(tail) if tail.isdigit() else 0


def next_seq(d, key, floor=0):
    """Persistent counter in d["seq"] — ids are never reused, even after posts are deleted (--replace)."""
    seq = d.setdefault("seq", {})
    n = max(int(seq.get(key, 0) or 0), int(floor or 0)) + 1
    seq[key] = n
    return n


def next_id(d, prefix, items):
    floor = max([_num_suffix(x.get("id", ""), prefix) for x in items] or [0])
    return f"{prefix}-{next_seq(d, 'id:' + prefix, floor):03d}"


def id_prefix(d, bid):
    b = brand(d, bid) or {}
    if b.get("prefix"):
        return b["prefix"]
    seq = d.setdefault("seq", {})
    if seq.get("prefix:" + bid):
        return seq["prefix:" + bid]
    seen = [p["id"].split("-")[0] for p in d.get("posts", []) if p.get("brand") == bid and "-" in p["id"]]
    prefix = max(set(seen), key=seen.count) if seen else bid[:2]
    seq["prefix:" + bid] = prefix
    return prefix


def new_post_id(d, bid):
    return next_id(d, id_prefix(d, bid), d.get("posts", []))


def add_post(d, bid, pillar, platform, slot, hook="", **fields):
    assert brand(d, bid), f"unknown brand {bid}"
    assert platform in PLATFORMS, f"bad platform {platform}"
    p = {"id": new_post_id(d, bid), "brand": bid, "pillar": pillar, "platform": platform,
         "hook": hook, "status": "draft", "slot": slot, "created_at": now_iso()}
    p.update({k: v for k, v in fields.items() if v is not None})
    d.setdefault("posts", []).append(p)
    return p


def add_rec(d, prio, title, why, impact, cta, **fields):
    assert prio in {"P0", "P1", "P2"}, f"bad priority {prio}"
    r = {"id": next_id(d, "rec", d.get("recommendations", [])), "priority": prio, "title": title, "why": why,
         "impact": impact, "cta": cta, "status": "proposed", "created_at": now_iso()}
    r.update(fields)
    d.setdefault("recommendations", []).append(r)
    return r


def add_rec_once(d, prio, title, why, impact, cta, **fields):
    """add_rec, unless a proposed recommendation with the same title for the same brand already exists
    (re-running a cron must not stack duplicate cards)."""
    for r in d.get("recommendations", []):
        if r.get("status") == "proposed" and r.get("title") == title and r.get("brand") == fields.get("brand"):
            return r
    return add_rec(d, prio, title, why, impact, cta, **fields)


def rec_action_failed(d, r, err, via):
    """An approved recommendation whose action raised (the paid plan's approval, a pause): the error stays on the card
    (action_error) and one owner card says so — whoever approved was just told "approved", so the failure must not stay silent."""
    q = rec(d, (r or {}).get("id"))
    if q is not None:
        q["action_error"] = str(err)[:300]
    return add_rec_once(d, "P0", f"Approved but not applied: {str((r or {}).get('title') or '')[:60]}",
                        f"{(r or {}).get('id')} was approved {via}, but what it starts failed: {str(err)[:240]}. Nothing it starts "
                        "has started; run it by hand (e.g. otto_ads.py approve <brand> <month>) once the cause is fixed.",
                        "Whoever approved it believes it is running", "Apply it by hand", brand=(r or {}).get("brand"),
                        source="otto_admin", audience="owner", rec=(r or {}).get("id"))


def paused(d, bid=None):
    """Why publishing and ad launches are stopped right now, or None. The owner console (otto_admin) sets
    controls.publishing_paused (the global kill switch) and brands[].paused; otto_publish and otto_ads launch honour both.
    A brand on the "ended" plan (plans.json defaults.ended, "none": a canceled / expired membership) is paused too."""
    ks = (d.get("controls") or {}).get("publishing_paused")
    if ks:
        return "all publishing is paused (kill switch" + (f", {ks.get('by')}" if isinstance(ks, dict) and ks.get("by") else "") + ")"
    if bid:
        b = brand(d, bid) or {}
        if b.get("paused") or b.get("status") == "paused":
            return f"{b.get('name') or bid} is paused"
        if b and plan_ended(d, bid):
            return f"{b.get('name') or bid} has no active plan (membership ended)"
    return None


# ---------- plans (plans.json): what each brand gets ----------
#
# plans.json is the single source of truth (edited without code): plans keyed by id with label, features, limits and
# optional prices / Stripe price ids (stripe_price_ids: monthly, yearly, one_time) / legacy Whop plan ids; "inherits" merges a
# parent's features + limits. brands[].plan names the brand's plan
# (missing = a brand from before plans → defaults.legacy, "founding"); brands[].plan_until (YYYY-MM-DD, brand-local)
# ends it → defaults.after_expiry ("content"); an unknown id → defaults.unknown ("content": fail-safe, no paid ads).
# New brands get defaults.new ("starter"), flagged brands[].plan_billing "not_billed" while that plan cannot be bought yet
# (no stripe_price_ids); a running subscription linked to the brand (otto_billing) clears the flag.
# The paid budget band (limits.ad_spend_managed_eur_month) is a soft cap (ad_band): the first month above it is planned in
# full, the second month in a row above it at the cap with the next plan offered; a plan with "overage" is never capped
# and shows overage.pct % of the spend above overage.above_eur_month. brands[].ad_band keeps the last months' decisions.
# An unreadable or invalid plans.json never pauses anything: plan_of answers SAFE_PLAN (organic only, config_error set),
# so paid work is refused / skipped with the reason and the guard leaves live campaigns alone.
# Free trial (otto_trial, docs/AUTH-AND-TRIAL.md): defaults.trial names the trial plan (optional — without it there is no
# trial). A plan may name its own "after_expiry" (the trial: "none", so a trial whose plan_until passed never falls back to
# the free Content plan), and the optional feature "ads_launch" (default true) set to false plans and renders paid ads for
# preview but launches none (no_launch_why: otto_ads launch / resume and otto_cron ads-launch refuse with the reason).

FEATURES = ("organic", "stories", "reels", "ads_meta", "ads_google", "ad_matrix", "video_ads", "creator_briefs",
            "competitor_sweep", "reports", "telegram", "multi_brand")
LIMITS = ("brands", "posts_per_month", "reels_per_month", "ad_matrix_preset", "ad_spend_managed_eur_month",
          "video_ads_per_month", "refresh_per_angle_week")
PRESET_ORDER = ("none", "micro", "launch", "scale")
SWEEPS = (False, "monthly", "weekly")
OPTIONAL_FEATURES = {"ads_launch": True}      # feature → the value a plan that does not name it gets (plans from before it)
PLAN_DEFAULTS = {"legacy": "founding", "new": "starter", "after_expiry": "content", "unknown": "content", "ended": "none"}
SAFE_PLAN = {"label": "Content (plans.json unreadable)", "upgrade_to": None, "overage": None, "public": False,
             "features": {"organic": True, "stories": True, "reels": True, "ads_meta": False, "ads_google": False, "ad_matrix": False,
                          "video_ads": False, "creator_briefs": False, "competitor_sweep": "monthly", "reports": True,
                          "telegram": True, "multi_brand": False, "ads_launch": False},
             "limits": {"brands": 1, "posts_per_month": 66, "reels_per_month": 4, "ad_matrix_preset": "none",
                        "ad_spend_managed_eur_month": 0, "video_ads_per_month": 0, "refresh_per_angle_week": 0}}
_plans_cache = {"key": None, "cfg": None}


def plans_path():
    return Path(os.environ.get("OTTO_PLANS") or HERE / "plans.json")


def _plan_problems(raw):
    """Why a parsed plans.json cannot be used ([] = fine), and the resolved plans (inheritance merged)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("plans"), dict) or not raw["plans"]:
        return ["no \"plans\" object"], {}
    src, out, probs = raw["plans"], {}, []

    def resolve(pid, seen=()):
        if pid in out:
            return out[pid]
        p = src.get(pid)
        if not isinstance(p, dict):
            raise ValueError(f"plan {pid!r} is not an object")
        if pid in seen:
            raise ValueError(f"plan {pid!r} inherits itself")
        feats, lims = {}, {}
        if p.get("inherits") is not None:
            if p["inherits"] not in src:
                raise ValueError(f"plan {pid!r} inherits unknown plan {p['inherits']!r}")
            parent = resolve(p["inherits"], seen + (pid,))
            feats, lims = dict(parent["features"]), dict(parent["limits"])
        for k, box in (("features", feats), ("limits", lims)):
            if p.get(k) is not None and not isinstance(p[k], dict):
                raise ValueError(f"plan {pid!r}: {k} must be an object")
            box.update(p.get(k) or {})
        for f, dv in OPTIONAL_FEATURES.items():
            feats.setdefault(f, dv)
            if not isinstance(feats[f], bool):
                raise ValueError(f"plan {pid!r}: feature {f!r} must be true or false")
        for f in FEATURES:
            if f not in feats:
                raise ValueError(f"plan {pid!r}: feature {f!r} missing")
            v = feats[f]
            if f == "competitor_sweep" and v not in SWEEPS:
                raise ValueError(f"plan {pid!r}: competitor_sweep must be false, \"monthly\" or \"weekly\"")
            if f != "competitor_sweep" and not isinstance(v, bool):
                raise ValueError(f"plan {pid!r}: feature {f!r} must be true or false")
        for k in LIMITS:
            if k not in lims:
                raise ValueError(f"plan {pid!r}: limit {k!r} missing (null = no limit)")
            v = lims[k]
            if k == "ad_matrix_preset":
                if v not in PRESET_ORDER:
                    raise ValueError(f"plan {pid!r}: ad_matrix_preset must be one of {', '.join(PRESET_ORDER)}")
            elif v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                raise ValueError(f"plan {pid!r}: limit {k!r} must be a number ≥ 0 or null")
        ids = p.get("whop_plan_ids") or []
        if not isinstance(ids, list) or not all(isinstance(x, str) and x.strip() for x in ids):
            raise ValueError(f"plan {pid!r}: whop_plan_ids must be a list of Whop plan ids")
        spi = p.get("stripe_price_ids")
        if spi is not None:
            if not isinstance(spi, dict) or set(spi) - set(STRIPE_INTERVALS):
                raise ValueError(f"plan {pid!r}: stripe_price_ids must be {{\"monthly\", \"yearly\", \"one_time\"}} → a Stripe "
                                 "price id (price_…) or null")
            for k, v in spi.items():
                if v is not None and not (isinstance(v, str) and re.fullmatch(r"price_[A-Za-z0-9_]{3,80}", v.strip())):
                    raise ValueError(f"plan {pid!r}: stripe_price_ids.{k} must be a Stripe price id (price_…) or null")
        if p.get("upgrade_to") is not None and p["upgrade_to"] not in src:
            raise ValueError(f"plan {pid!r}: upgrade_to names unknown plan {p['upgrade_to']!r}")
        if p.get("after_expiry") is not None and p["after_expiry"] not in src:
            raise ValueError(f"plan {pid!r}: after_expiry names unknown plan {p['after_expiry']!r}")
        cp = p.get("checkout_plans")
        if cp is not None and not (isinstance(cp, list) and all(isinstance(x, str) and x in src for x in cp)):
            raise ValueError(f"plan {pid!r}: checkout_plans must list known plan ids")
        td = p.get("trial_days")
        if td is not None and (isinstance(td, bool) or not isinstance(td, int) or not 1 <= td <= 90):
            raise ValueError(f"plan {pid!r}: trial_days must be a whole number of days (1-90)")
        ov = p.get("overage")
        if ov is not None and not (isinstance(ov, dict) and all(isinstance(ov.get(k), (int, float)) and not isinstance(ov.get(k), bool)
                                                                 and ov[k] >= 0 for k in ("above_eur_month", "pct"))):
            raise ValueError(f"plan {pid!r}: overage must be {{\"above_eur_month\": number, \"pct\": number}}")
        for k in ("monthly_eur", "yearly_eur", "one_time_eur", "extra_brand_eur"):
            v = p.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                raise ValueError(f"plan {pid!r}: {k} must be a number or null")
        extra = {k: v for k, v in p.items() if k not in ("features", "limits", "inherits") and not k.startswith("_")}
        extra["stripe_price_ids"] = {k: (v.strip() if isinstance(v, str) else None) for k, v in (spi or {}).items()}
        out[pid] = dict(extra, label=str(p.get("label") or pid), features=feats, limits=lims, whop_plan_ids=list(ids),
                        inherits=p.get("inherits"), upgrade_to=p.get("upgrade_to"), overage=ov,
                        public=bool(p.get("public", True)))
        return out[pid]

    for pid in src:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(pid)):
            probs.append(f"plan id {pid!r}: lower-case letters, digits, - and _ only")
            continue
        try:
            resolve(pid)
        except ValueError as e:
            probs.append(str(e))
    defaults = dict(PLAN_DEFAULTS, **{k: v for k, v in (raw.get("defaults") or {}).items() if not str(k).startswith("_")})
    for k, v in defaults.items():
        if v not in src:
            probs.append(f"defaults.{k} names unknown plan {v!r}")
    seen = {}
    for pid, p in out.items():
        for w in p["whop_plan_ids"]:
            if w in seen and seen[w] != pid:
                probs.append(f"Whop plan {w} is listed on both {seen[w]!r} and {pid!r}")
            seen[w] = pid
    prices = {}
    for pid, p in out.items():
        for k, v in (p.get("stripe_price_ids") or {}).items():
            if v and v in prices and prices[v] != (pid, k):
                probs.append(f"Stripe price {v} is listed twice ({prices[v][0]}.{prices[v][1]} and {pid}.{k})")
            if v:
                prices[v] = (pid, k)
    return probs, out


def plans_config():
    """plans.json parsed, validated and inheritance-resolved: {"plans": {id: {label, features, limits, whop_plan_ids, …}},
    "defaults", "order", "file", "error"}. Re-read whenever the file changes (mtime + size). error is a short reason when the
    file cannot be used; then "plans" is empty and plan_of answers SAFE_PLAN."""
    f = plans_path()
    try:
        st = f.stat()
        key = (str(f), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(f), None, None)
    if _plans_cache["key"] == key and _plans_cache["cfg"] is not None:
        return _plans_cache["cfg"]
    try:
        raw = json.loads(f.read_text())
        probs, plans_ = _plan_problems(raw)
    except (OSError, ValueError) as e:
        raw, probs, plans_ = {}, [f"cannot read {f.name}: {type(e).__name__}: {str(e)[:160]}"], {}
    if probs:
        cfg = {"plans": {}, "defaults": dict(PLAN_DEFAULTS), "order": [], "file": str(f),
               "error": "; ".join(probs)[:400]}
    else:
        order = [x for x in raw.get("order") or [] if x in plans_] + [x for x in plans_ if x not in (raw.get("order") or [])]
        cfg = {"plans": plans_, "order": order, "file": str(f), "error": None,
               "defaults": dict(PLAN_DEFAULTS, **{k: v for k, v in (raw.get("defaults") or {}).items() if not str(k).startswith("_")})}
    _plans_cache.update(key=key, cfg=cfg)
    return cfg


def _plan_date(v):
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(v or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%Y-%m-%d").date()
    except ValueError:
        return None


def plan_of(d, bid, today=None):
    """The brand's resolved plan: {id, label, features, limits, prices…, requested, source, until, expired, config_error}.
    source: "brand" (brands[].plan) · "legacy" (no plan on the record → defaults.legacy) · "expired" (plan_until passed →
    defaults.after_expiry) · "unknown" (an id plans.json does not have → defaults.unknown) · "config_error"."""
    b = brand(d, bid) or {}
    cfg = plans_config()
    dflt = cfg["defaults"]
    raw = b.get("plan")
    requested = raw.strip() if isinstance(raw, str) and raw.strip() else None
    pid, source = requested or dflt["legacy"], "brand" if requested else "legacy"
    until = _plan_date(b.get("plan_until"))
    today = today or datetime.now(brand_tz(b)).date()
    expired = bool(until and today > until and pid != dflt["ended"])
    if expired:                                               # the plan's own after_expiry (the trial: "none"), else the default
        pid, source = ((cfg["plans"].get(pid) or {}).get("after_expiry") or dflt["after_expiry"]), "expired"
    if cfg.get("error"):
        base, pid, source = SAFE_PLAN, dflt["unknown"], "config_error"
    elif pid in cfg["plans"]:
        base = cfg["plans"][pid]
    else:
        pid, source = dflt["unknown"], "unknown"
        base = cfg["plans"].get(pid) or SAFE_PLAN
    out = json.loads(json.dumps(base))                        # callers may change what they get, never the cache
    out.update(id=pid, requested=requested or dflt["legacy"], source=source, until=until.isoformat() if until else None,
               expired=expired, config_error=cfg.get("error"))
    return out


def plan_ended(d, bid):
    """True when the brand sits on the "ended" plan (a canceled / expired membership): publishing is paused. A plan whose
    plan_until passed into the ended plan (the free trial's after_expiry) counts too — before otto_trial moves it there."""
    b = brand(d, bid) or {}
    raw = b.get("plan")
    ended = plans_config()["defaults"]["ended"]
    if isinstance(raw, str) and raw.strip() == ended:
        return True
    if not b or not b.get("plan_until"):
        return False
    p = plan_of(d, bid)
    return p["source"] == "expired" and p["id"] == ended


def trial_plan_id():
    """The free trial's plan id (plans.json defaults.trial), or None when no trial is configured."""
    cfg = plans_config()
    t = (cfg.get("defaults") or {}).get("trial")
    return t if t and t in cfg["plans"] else None


def trial_ended(d, bid):
    """The brand came from a free trial that ended without a paid plan: on the ended plan with brands[].trial and never
    converted. The client app answers 402 (paywall) for it; its data is kept (otto_retention counts 90 days)."""
    b = brand(d, bid) or {}
    tr = b.get("trial")
    return isinstance(tr, dict) and not tr.get("converted_at") and plan_ended(d, bid)


AD_FEATURE = {"meta": "ads_meta", "google": "ads_google"}


def entitled(d, bid, feature, today=None):
    """Does the brand's plan include `feature` (a plans.json feature; "ads" = paid ads on any network, "meta" / "google"
    = that network)? competitor_sweep counts as included when it is monthly or weekly."""
    f = plan_of(d, bid, today)["features"]
    if feature in ("ads", "paid_ads"):
        return bool(f.get("ads_meta") or f.get("ads_google"))
    return bool(f.get(AD_FEATURE.get(feature, feature)))


def limit(d, bid, name, today=None):
    """The brand's plan limit `name` (None = no limit)."""
    return plan_of(d, bid, today)["limits"].get(name)


def no_ads_why(d, bid, network=None):
    """Why this brand's plan does not cover paid ads (on `network`), or None when it does."""
    p = plan_of(d, bid)
    if p.get("config_error"):
        return f"plans.json is unreadable ({p['config_error'][:120]}) — paid ads are off until it is fixed"
    if not (p["features"].get("ads_meta") or p["features"].get("ads_google")):
        return f"plan {p['id']} has no paid ads"
    if network and not p["features"].get(AD_FEATURE.get(network, network)):
        return f"plan {p['id']} has no {'Meta' if network == 'meta' else 'Google'} ads"
    return None


def no_launch_why(d, bid, network=None):
    """Why a campaign of this brand may not go live (launch, resume) — no_ads_why, or a plan that plans and previews paid
    ads without launching them (features.ads_launch false: the free trial) — or None."""
    why = no_ads_why(d, bid, network)
    if why:
        return why
    p = plan_of(d, bid)
    if p["features"].get("ads_launch") is False:
        return (f"plan {p['id']} plans and previews paid ads but launches none (free trial: campaigns launch once a card "
                "is on file)")
    return None


def preset_rank(p):
    return PRESET_ORDER.index(p) if p in PRESET_ORDER else 0


def matrix_preset(d, bid, budget_preset=None):
    """The ad-matrix preset the brand's plan allows ("none" | "micro" | "launch" | "scale"), capped at micro when the
    daily budget calls for the micro floor (otto_styles.preset_for_budget → budget_preset "micro")."""
    p = plan_of(d, bid)
    preset = p["limits"].get("ad_matrix_preset") or "none"
    if not p["features"].get("ad_matrix"):
        return "none"
    if budget_preset == "micro" and preset_rank(preset) > preset_rank("micro"):
        return "micro"
    return preset


def plan_for_whop(whop_plan_id):
    """The Otto plan a Whop plan id sells (plans.json whop_plan_ids), or None."""
    if not whop_plan_id:
        return None
    return next((pid for pid, p in plans_config()["plans"].items() if whop_plan_id in p["whop_plan_ids"]), None)


STRIPE_INTERVALS = {"monthly": "month", "yearly": "year", "one_time": "one_time"}   # plans.json key → billing interval


def plan_for_price(price_id):
    """(Otto plan id, interval "month" | "year" | "one_time") a Stripe price sells (plans.json stripe_price_ids), or None."""
    if not price_id:
        return None
    for pid, p in plans_config()["plans"].items():
        for k, v in (p.get("stripe_price_ids") or {}).items():
            if v and v == price_id:
                return pid, STRIPE_INTERVALS[k]
    return None


def price_for(plan_id, interval):
    """The Stripe price id that sells `plan_id` at `interval` ("month" | "year" | "one_time"), or None (not on sale yet)."""
    key = {v: k for k, v in STRIPE_INTERVALS.items()}.get(interval)
    p = plans_config()["plans"].get(plan_id) or {}
    return (p.get("stripe_price_ids") or {}).get(key) if key else None


def new_brand_plan():
    """(plan id, plan_billing flag or None) for a brand created now: plans.json defaults.new, flagged "not_billed" while
    that plan has no price to buy it with (stripe_price_ids, or a legacy Whop plan id)."""
    cfg = plans_config()
    pid = cfg["defaults"]["new"]
    p = cfg["plans"].get(pid) or {}
    sold = bool(p.get("whop_plan_ids") or any((p.get("stripe_price_ids") or {}).values()))
    return pid, (None if sold else "not_billed")


def _prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"


def ad_band(d, bid, ym, asked_eur):
    """The soft cap for `ym`'s paid plan (research §4.2) given the budget asked for, in EUR → {mode, cap_eur, asked_eur,
    plan_eur, overage_eur, upgrade_to, upgrade_label, upgrade_cap_eur, plan}. mode: "within" · "grace" (the first month
    above the band: planned in full, the card says so) · "capped" (the second month in a row above it on the same plan:
    planned at the cap, the card offers upgrade_to) · "overage" (a plan with overage: planned in full, overage_eur =
    pct % of the spend above above_eur_month, shown, never billed by Otto). Pure: record_band() stores the decision."""
    p = plan_of(d, bid)
    cap = p["limits"].get("ad_spend_managed_eur_month")
    up = plans_config()["plans"].get(p.get("upgrade_to") or "") or {}
    out = {"plan": p["id"], "cap_eur": cap, "asked_eur": round(asked_eur or 0, 2), "plan_eur": round(asked_eur or 0, 2),
           "overage_eur": 0.0, "mode": "within", "upgrade_to": p.get("upgrade_to"), "upgrade_label": up.get("label"),
           "upgrade_cap_eur": (up.get("limits") or {}).get("ad_spend_managed_eur_month")}
    if cap is None or (asked_eur or 0) <= cap:
        return out
    ov = p.get("overage")
    if ov:
        out.update(mode="overage", overage_eur=round(max(0.0, asked_eur - ov["above_eur_month"]) * ov["pct"] / 100, 2),
                   overage_pct=ov["pct"], overage_above_eur=ov["above_eur_month"])
        return out
    hist = (brand(d, bid) or {}).get("ad_band")
    prev = (hist if isinstance(hist, dict) else {}).get(_prev_month(ym))
    prev = prev if isinstance(prev, dict) else {}
    if prev.get("over") and prev.get("plan") == p["id"]:
        out.update(mode="capped", plan_eur=float(cap))
    else:
        out["mode"] = "grace"
    return out


def record_band(d, bid, ym, band):
    """Remember `ym`'s band decision on brands[].ad_band (the last 6 months) — next month's ad_band reads it."""
    b = brand(d, bid)
    if b is None:
        return
    hist = b.get("ad_band") if isinstance(b.get("ad_band"), dict) else {}
    hist[ym] = {"plan": band["plan"], "over": band["mode"] != "within", "mode": band["mode"], "asked_eur": band["asked_eur"],
                "plan_eur": band["plan_eur"], "cap_eur": band["cap_eur"], "overage_eur": band["overage_eur"], "at": now_iso()}
    if band["mode"] == "overage":
        hist[ym].update(overage_pct=band.get("overage_pct"), overage_above_eur=band.get("overage_above_eur"))
    b["ad_band"] = {k: hist[k] for k in sorted(hist)[-6:]}


KEEP = object()


def set_plan(d, bid, plan_id, until=KEEP, by="admin", via="admin", note="", **extra):
    """Put a brand on a plan (validated against plans.json) inside the caller's transaction and keep a short history
    (brands[].plan_history: who, when, from → to, until, note). until: "YYYY-MM-DD", None / "" = no expiry, KEEP = unchanged.
    → (plan before, plan after) as plan_of resolves them."""
    cfg = plans_config()
    if cfg.get("error"):
        raise ValueError(f"plans.json is unreadable: {cfg['error'][:200]}")
    if plan_id not in cfg["plans"]:
        raise ValueError(f"unknown plan {plan_id!r} — one of {', '.join(cfg['order'])}")
    b = brand(d, bid)
    if b is None:
        raise KeyError(bid)
    before = plan_of(d, bid)
    b["plan"] = plan_id
    tr = b.get("trial")
    if isinstance(tr, dict) and not tr.get("converted_at") and plan_id not in (trial_plan_id(), cfg["defaults"]["ended"]):
        tr["converted_at"], tr["converted_to"] = now_iso(), plan_id       # a trial brand on a paid plan (Stripe, the console)
        for u in d.get("users") or []:
            if isinstance(u, dict) and u.get("id") == tr.get("user"):
                u["status"] = "active"
                u.setdefault("paid_at", tr["converted_at"])
    if until is not KEEP:
        if until in (None, ""):
            b.pop("plan_until", None)
        else:
            day = _plan_date(until)
            if day is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(until).strip()):
                raise ValueError("until must be a date (YYYY-MM-DD)")
            b["plan_until"] = day.isoformat()
    b.pop("plan_notice", None)                              # a fresh plan gets a fresh expiry notice
    entry = {"at": now_iso(), "by": by, "via": via, "from": before["id"], "to": plan_id,
             "until": b.get("plan_until"), "note": str(note or "")[:300]}
    entry.update({k: v for k, v in extra.items() if v is not None})
    b["plan_history"] = (b.get("plan_history") or [])[-19:] + [entry]
    return before, plan_of(d, bid)


def plan_expiry_notices(d, today=None):
    """One owner recommendation per brand whose plan_until has passed (brands[].plan_notice remembers it was filed).
    Runs inside the caller's transaction. → brand ids noticed now."""
    out = []
    for b in d.get("brands", []):
        if not isinstance(b, dict) or not b.get("id"):
            continue
        p = plan_of(d, b["id"], today)
        if not p["expired"] or p["requested"] == trial_plan_id():      # a trial's end is otto_trial's card, not this one
            continue
        key = f"expired:{p['requested']}:{p['until']}"
        if b.get("plan_notice") == key:
            continue
        b["plan_notice"] = key
        cfg = plans_config()["plans"]
        old = (cfg.get(p["requested"]) or {}).get("label") or p["requested"]
        name = b.get("name") or b["id"]
        paid = p["features"].get("ads_meta") or p["features"].get("ads_google")
        add_rec(d, "P1", f"{name}: the {old} plan ended on {p['until']}",
                f"{name} is on {p['label']} now." + ("" if paid else " Paid ads are not part of it: nothing new is planned or "
                                                                       "launched, and the daily guard pauses live campaigns.")
                + " Nothing was deleted.", "Keeps what the client gets in line with what they pay for",
                "Renew or change the plan", brand=b["id"], source="plans", audience="owner", action="plan", plan=p["id"])
        out.append(b["id"])
    return out


PRESET_TEXT = {"micro": "4 concepts × 5 styles", "launch": "6 concepts × 6 styles", "scale": "6 concepts × 8 styles"}


def to_eur(amount, code):
    """A brand-currency amount in EUR (otto_billing's approximate table); None when the currency is unknown."""
    try:
        import otto_billing
        return otto_billing.to_eur(amount, currency_code(code) or "EUR")
    except Exception:
        return amount if (currency_code(code) or "EUR") == "EUR" else None


def plan_usage(d, bid, today=None):
    """This month (brand-local) against the plan: posts + reels planned (not skipped), and the paid budget Otto manages
    (approved / live / paused / ended flights × days in the month, in EUR)."""
    b = brand(d, bid) or {}
    today = today or datetime.now(brand_tz(b)).date()
    ym = today.strftime("%Y-%m")
    month = [p for p in d.get("posts", []) if isinstance(p, dict) and p.get("brand") == bid
             and str(p.get("slot") or "").startswith(ym) and p.get("status") != "skipped"]
    y, m = today.year, today.month
    first = today.replace(day=1)
    last = (first.replace(year=y + (m == 12), month=m % 12 + 1)) - timedelta(days=1)
    budget = 0.0
    for c in d.get("campaigns", []):
        if not isinstance(c, dict) or c.get("brand") != bid or c.get("status") not in ("approved", "live", "paused", "ended"):
            continue
        s, e = _plan_date(c.get("start")), _plan_date(c.get("end"))
        if not (s and e):
            continue
        days = (min(e, last) - max(s, first)).days + 1
        if days > 0:
            budget += (num(c.get("daily_budget")) or 0) * days
    return {"month": ym, "posts": len(month), "reels": sum(1 for p in month if p.get("format") == "reel"),
            "ad_budget_eur": round(to_eur(budget, brand_currency(d, bid)) or 0, 2)}


def plan_view(d, bid, today=None):
    """The plan as the owner console and the client's Settings show it: label, what is included (plain English lines),
    limits and this month's usage against them."""
    p = plan_of(d, bid, today)
    f, L = p["features"], p["limits"]
    inc = []
    if f.get("organic"):
        inc.append(f"{L['posts_per_month']} posts a month" + (", carousels and stories included" if f.get("stories") else "")
                   if L.get("posts_per_month") is not None else "Organic posts on Facebook and Instagram")
    if f.get("reels"):
        inc.append(f"{L['reels_per_month']} reels a month" if L.get("reels_per_month") is not None else "Reels")
    if f.get("competitor_sweep"):
        inc.append(f"{str(f['competitor_sweep']).capitalize()} competitor sweep")
    b = brand(d, bid) or {}
    chans = approval_channels(b)
    tele = bool(f.get("telegram")) and "telegram" in chans     # the plan allows Telegram and the brand approves there
    if f.get("organic"):                                      # approvals: how this brand's posts reach it (brands[].approvals)
        how = [w for w, on in (("by e-mail", "email" in chans), ("in Telegram", tele)) if on]
        inc.append("Approvals " + (" and ".join(how) if how else "in the app"))
    if f.get("reports"):                                      # the 07:35 morning report goes where the approvals go
        how = [w for w, on in (("by e-mail", "email" in chans), ("in Telegram", tele)) if on]
        inc.append("Weekly insights" + (" and the 07:35 morning report " + " and ".join(how) if how else ""))
    nets = " and ".join(n for n, k in (("Meta", "ads_meta"), ("Google", "ads_google")) if f.get(k))
    if nets:
        cap, ov = L.get("ad_spend_managed_eur_month"), p.get("overage")
        if f.get("ads_launch") is False:
            inc.append(f"Paid campaigns on {nets} planned and previewed (they launch once a card is on file)")
        else:
            inc.append(f"Paid campaigns on {nets}" + (f", ad spend up to €{cap:,.0f} a month" if cap else "")
                       + (f" (above €{ov['above_eur_month']:,.0f}: {ov['pct']:g}% of the excess)" if ov else ""))
    if f.get("ad_matrix") and PRESET_TEXT.get(L.get("ad_matrix_preset")):
        inc.append(f"Monthly ad matrix: {PRESET_TEXT[L['ad_matrix_preset']]}")
    if f.get("video_ads"):
        inc.append("Video ads" + (f", up to {L['video_ads_per_month']} a month" if L.get("video_ads_per_month") else ""))
    if f.get("creator_briefs"):
        inc.append("Creator briefs")
    if f.get("multi_brand") and L.get("brands"):
        inc.append(f"Up to {L['brands']} brands")
    u = plan_usage(d, bid, today)
    usage = {"posts": {"used": u["posts"], "limit": L.get("posts_per_month")},
             "reels": {"used": u["reels"], "limit": L.get("reels_per_month")}}
    overage = None
    if nets:
        usage["ad_budget_eur"] = {"used": u["ad_budget_eur"], "limit": L.get("ad_spend_managed_eur_month")}
        ov = p.get("overage")
        if ov and u["ad_budget_eur"] > ov["above_eur_month"]:
            overage = {"above_eur": ov["above_eur_month"], "pct": ov["pct"], "excess_eur": round(u["ad_budget_eur"] - ov["above_eur_month"], 2),
                       "fee_eur": round((u["ad_budget_eur"] - ov["above_eur_month"]) * ov["pct"] / 100, 2)}
    band = (b["ad_band"] if isinstance(b.get("ad_band"), dict) else {}).get(u["month"])
    band = band if isinstance(band, dict) else None
    up = plans_config()["plans"].get(p.get("upgrade_to") or "") or {}
    return {"id": p["id"], "label": p["label"], "requested": p["requested"], "source": p["source"], "until": p["until"],
            "expired": p["expired"], "paid_ads": bool(nets), "ended": plan_ended(d, bid), "included": inc,
            "limits": dict(L), "features": dict(f), "usage": usage, "month": u["month"], "config_error": p["config_error"],
            "overage": overage, "band": band, "not_billed": b.get("plan_billing") == "not_billed",
            "upgrade_to": p.get("upgrade_to"), "upgrade_label": up.get("label")}


def approval_channels(b):
    """otto_email.approval_channels (the push channels of brands[].approvals; [] = the app only), without the import cost
    when otto_email cannot load."""
    try:
        import otto_email
        return otto_email.approval_channels(b)
    except Exception:                                         # noqa: BLE001 — a plan view never fails over it
        raw = (b or {}).get("approvals", "telegram")
        raw = raw if isinstance(raw, list) else [raw]
        return [c for c in ("email", "telegram") if c in {str(x).strip().lower() for x in raw}]


def can_transition(kind, cur, new):
    table = POST_TRANSITIONS if kind == "post" else REC_TRANSITIONS
    if new == cur:
        return cur not in ("publishing",)
    return new in table.get(cur, set())


def check_transition(kind, cur, new):
    if not can_transition(kind, cur, new):
        raise ValueError(f"{kind} is {cur} — cannot move it to {new}")


DECISIONS = {"approve": "approved", "skip": "skipped", "later": "pending_approval"}


def decide(d, pid, decision, via="dashboard", enforce=True):
    """Owner decision on a post. Writes status + taste log (what the agency learns)."""
    p = post(d, pid)
    if p is None:
        raise KeyError(pid)
    if decision not in DECISIONS:
        raise ValueError(f"bad decision {decision}")
    if enforce:
        check_transition("post", p.get("status"), DECISIONS[decision])
    p["status"] = DECISIONS[decision]
    p["approved_via"] = via
    p["decided_at"] = now_iso()
    d.setdefault("taste_log", []).append({"post": pid, "brand": p.get("brand"), "pillar": p.get("pillar"),
                                          "platform": p.get("platform"), "decision": decision,
                                          "via": via, "ts": p["decided_at"]})
    return p


def taste(d, bid=None):
    """Per-pillar approve/skip counts — the visible 'what the agency learned'."""
    out = {}
    for t in d.get("taste_log", []):
        if bid and t["brand"] != bid:
            continue
        k = (t["brand"], t.get("pillar") or "?")
        out.setdefault(k, {"approve": 0, "skip": 0, "later": 0})
        out[k][t["decision"]] = out[k].get(t["decision"], 0) + 1
    return out


# ---------- brand helpers: timezone, language, currency ----------

def brand_tz(b):
    name = (b or {}).get("tz") or os.environ.get("OTTO_TZ") or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def slot_dt(p, b=None):
    """The post's slot as an aware datetime. A naive slot ("2026-10-01T09:00") is brand-local time
    (brands[].tz, default Asia/Jerusalem); an explicit offset is respected. None if unparsable."""
    dt = parse_iso((p or {}).get("slot"))
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=brand_tz(b))


LANGS = {"en", "de", "he", "fr", "es", "it", "nl", "pt", "pl", "ar", "ru", "hu", "ro"}


def scan_of(bid):
    f = BRANDS / bid / "scan.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        return {}


def brand_lang(b):
    """Primary content language: first language code in brands[].lang ("HE · shown in English" → he,
    "EN/DE" → en), else the site scan's first language, else en."""
    b = b or {}
    for tok in re.findall(r"[A-Za-z]+", b.get("lang") or ""):
        if len(tok) == 2 and tok.lower() in LANGS:
            return tok.lower()
    langs = (scan_of(b["id"]).get("languages") or []) if b.get("id") else []
    return langs[0] if langs else "en"


CURRENCY_SYMBOLS = {"EUR": "€", "ILS": "₪", "USD": "$", "GBP": "£", "CHF": "CHF ", "HUF": "Ft ", "PLN": "zł ",
                    "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "CZK": "Kč ", "RON": "lei ", "JPY": "¥"}
_SYMBOL_TO_CODE = {"€": "EUR", "₪": "ILS", "$": "USD", "£": "GBP", "NIS": "ILS", "¥": "JPY"}


def currency_code(x):
    """'€' / 'eur' / 'EUR' → 'EUR'. None for unknown / ambiguous ('NOK/SEK/DKK')."""
    if not x:
        return None
    x = str(x).strip()
    if x in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[x]
    if re.fullmatch(r"[A-Za-z]{3}", x):
        return _SYMBOL_TO_CODE.get(x.upper(), x.upper())
    return None


def currency_symbol(code):
    code = currency_code(code) or "EUR"
    return CURRENCY_SYMBOLS.get(code, code + " ")


def brand_currency(d, bid):
    """ISO code: brands[].currency → site scan commerce.currency → the brand's first country → EUR."""
    b = brand(d, bid) or {}
    return (currency_code(b.get("currency")) or currency_code((scan_of(bid).get("commerce") or {}).get("currency"))
            or COUNTRY_CURRENCY.get(((b.get("countries") or [None])[0] or "").upper()) or "EUR")


# Where a new brand lives, before anything is scanned: the url's country TLD, then the language (brand-add).
COUNTRY_TZ = {"DE": "Europe/Berlin", "AT": "Europe/Vienna", "CH": "Europe/Zurich", "PT": "Europe/Lisbon", "NL": "Europe/Amsterdam",
              "BE": "Europe/Brussels", "LU": "Europe/Luxembourg", "IT": "Europe/Rome", "FR": "Europe/Paris", "ES": "Europe/Madrid",
              "IL": "Asia/Jerusalem", "GB": "Europe/London", "IE": "Europe/Dublin", "PL": "Europe/Warsaw", "HU": "Europe/Budapest",
              "RO": "Europe/Bucharest", "DK": "Europe/Copenhagen", "SE": "Europe/Stockholm", "NO": "Europe/Oslo", "FI": "Europe/Helsinki",
              "CZ": "Europe/Prague", "GR": "Europe/Athens", "US": "America/New_York"}
COUNTRY_CURRENCY = {"IL": "ILS", "GB": "GBP", "CH": "CHF", "PL": "PLN", "HU": "HUF", "RO": "RON", "DK": "DKK", "SE": "SEK",
                    "NO": "NOK", "CZ": "CZK", "US": "USD"}
CURRENCY_COUNTRY = {cur: cc for cc, cur in COUNTRY_CURRENCY.items()}     # a price in USD says US; EUR says nothing
LANG_COUNTRY = {"de": "DE", "he": "IL", "pt": "PT", "nl": "NL", "it": "IT", "fr": "FR", "es": "ES", "pl": "PL", "hu": "HU", "ro": "RO"}


def guess_country(url="", lang=""):
    """ISO country from the url's TLD (.de, .co.il, .co.uk …), else from the first language code; None when unknown."""
    url = str(url or "").strip()
    host = (urllib.parse.urlsplit(url if "//" in url else "//" + url).hostname or "").rstrip(".")
    tld = host.rsplit(".", 1)[-1].upper() if "." in host else ""
    tld = "GB" if tld == "UK" else tld
    if tld in COUNTRY_TZ:
        return tld
    for tok in re.findall(r"[A-Za-z]+", lang or ""):
        if tok.lower() in LANG_COUNTRY:
            return LANG_COUNTRY[tok.lower()]
    return None


def brand_countries(b, langs=()):
    """Ad / research market: brands[].countries → the url's TLD → the site languages (he → IL, de → DACH, pt → PT …) → DE."""
    b = b or {}
    if b.get("countries"):
        return list(b["countries"])
    cc = guess_country(b.get("url") or "")
    if cc:
        return [cc]
    langs = list(langs) or [brand_lang(b)]
    if "he" in langs:
        return ["IL"]
    if "de" in langs:
        return ["DE", "AT", "CH"]
    for l in langs:
        if l in LANG_COUNTRY:
            return [LANG_COUNTRY[l]]
    return ["DE"]


def money(v, code, digits=0):
    if v is None:
        return "—"
    return f"{currency_symbol(code)}{v:,.{digits}f}"


def num(v):
    """Metric value if it is a real, finite number, else None (Graph sometimes returns dicts/strings/None; "1e999"
    or NaN would reach json.dumps as Infinity/NaN, which no browser JSON.parse accepts)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v) if re.search(r"[.eE]|inf|nan", v, re.I) else int(v)
        except ValueError:
            return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    return None


# ---------- CLI ----------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("list", "pending"):
        d = load()
        posts = d["posts"]
        if args and args[0] == "pending":
            posts = [p for p in posts if p["status"] == "pending_approval"]
        elif len(args) > 1:
            posts = [p for p in posts if p["brand"] == args[1]]
        for p in posts:
            print(f'{p["id"]:8} {p["brand"]:12} {p["status"]:17} {p["slot"]:17} {p.get("hook","")}')
        print(f'-- {len(posts)} posts')
    elif args[0] == "add":
        bid, pillar, platform, slot = args[1:5]
        with transaction() as d:
            p = add_post(d, bid, pillar, platform, slot, " ".join(args[5:]))
        print(f"added {p['id']}")
    elif args[0] == "status":
        pid, st = args[1], args[2]
        assert st in STATUSES, f"bad status {st}"
        with transaction() as d:
            p = post(d, pid)
            assert p, f"unknown post {pid}"
            p["status"] = st
        print(f'{pid} -> {st}')
    elif args[0] == "decide":
        pid, decision = args[1], args[2]
        via = args[args.index("--via") + 1] if "--via" in args else "dashboard"
        with transaction() as d:
            p = decide(d, pid, decision, via)
        print(f'{pid} -> {p["status"]} (via {via})')
    elif args[0] == "set":
        pid, fields = args[1], json.loads(" ".join(args[2:]))
        with transaction() as d:
            p = post(d, pid)
            assert p, f"unknown post {pid}"
            if "status" in fields:
                assert fields["status"] in STATUSES, f"bad status {fields['status']}"
            p.update(fields)
        print(f'{pid} updated: {", ".join(fields)}')
    elif args[0] == "brand-add":
        opts = {}
        for k in ("--tz", "--countries", "--currency", "--plan", "--approvals"):
            if k in args:
                i = args.index(k)
                opts[k] = args[i + 1]
                del args[i:i + 2]
        bid, name, url, lang = args[1:5]
        pillars = [s.strip() for s in args[5].split(",")] if len(args) > 5 else []
        country = guess_country(url, lang)
        countries = [c.strip().upper() for c in opts["--countries"].split(",")] if "--countries" in opts else ([country] if country else [])
        tz = opts.get("--tz") or COUNTRY_TZ.get((countries or [None])[0], DEFAULT_TZ)
        ZoneInfo(tz)                                     # a typo fails here, not at publish time
        plan_id, billing = new_brand_plan()
        plan_id = opts.get("--plan") or plan_id
        assert plan_id in plans_config()["plans"], f"unknown plan {plan_id} ({plans_config().get('error') or 'see plans.json'})"
        b = {"id": bid, "name": name, "url": url, "lang": lang, "tz": tz, "status": "onboarding", "pillars": pillars, "compliance": "",
             "plan": plan_id, "approvals": opts.get("--approvals") or "email"}   # EU default; Telegram is opt-in
        if billing and "--plan" not in opts:
            b["plan_billing"] = billing                  # not billed yet: no price sells it; a linked subscription clears it
        if countries:
            b["countries"] = countries
        if "--currency" in opts:
            b["currency"] = currency_code(opts["--currency"])
        with transaction() as d:
            assert not brand(d, bid), f"brand {bid} exists"
            d.setdefault("brands", []).append(b)
        print(f"added brand {bid} · tz {tz} · countries {','.join(countries) or '—'} · plan {plan_id}")
    elif args[0] == "plans":
        cfg = plans_config()
        if cfg.get("error"):
            print(f"plans.json cannot be used: {cfg['error']}")
        for pid in cfg["order"]:
            p = cfg["plans"][pid]
            f = p["features"]
            print(f"{pid:9} {p['label']:16} ads {'meta' if f['ads_meta'] else '-':4} {'google' if f['ads_google'] else '-':6} "
                  f"matrix {p['limits']['ad_matrix_preset']:6} posts {p['limits']['posts_per_month']} reels {p['limits']['reels_per_month']} "
                  f"cap €{p['limits']['ad_spend_managed_eur_month']} stripe {','.join(k for k, v in p['stripe_price_ids'].items() if v) or '—'}"
                  f" whop {','.join(p['whop_plan_ids']) or '—'}")
        try:
            d = load()
        except (OSError, ValueError) as e:
            print(f"(no brands: {DATA.name} cannot be read — {type(e).__name__})")
            d = {}
        for b in d.get("brands", []):
            p = plan_of(d, b["id"])
            print(f"  {b['id']:16} {p['id']:9} ({p['source']}{', until ' + p['until'] if p['until'] else ''})")
    elif args[0] == "recs":
        for r in load().get("recommendations", []):
            print(f'{r["id"]:8} {r["priority"]:3} {r["status"]:10} {r["title"]}')
    elif args[0] == "rec":
        rid, st = args[1], args[2]
        assert st in REC_STATUSES, f"bad status {st}"
        with transaction() as d:
            r = rec(d, rid)
            assert r, f"unknown recommendation {rid}"
            r["status"] = st
        print(f'{rid} -> {st}')
    elif args[0] == "rec-add":
        prio = args[1]
        title, why, impact, cta = [s.strip() for s in " ".join(args[2:]).split("|")]
        with transaction() as d:
            r = add_rec(d, prio, title, why, impact, cta)
        print(f"added {r['id']}")
    elif args[0] == "taste":
        d = load()
        for (b, pillar), c in sorted(taste(d, args[1] if len(args) > 1 else None).items()):
            print(f'{b:12} {pillar:22} ✓{c["approve"]:2}  ✗{c["skip"]:2}  ↷{c["later"]:2}')
    elif args[0] == "sync-fallback":
        with locked():
            sync_fallback(load() if fallback_full() else None)        # neutral needs no data.json (a checkout has none)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
