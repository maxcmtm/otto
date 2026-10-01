#!/usr/bin/env python3
"""Otto dashboard action API. Localhost-only; nginx proxies /otto-api/ behind mm-check auth.

GET  /otto-api/data                 -> data.json (live; a client gets client_view() of their own brands only); every brand
                                       carries plan_view (ap.plan_view: its plans.json plan, what is included, usage)
POST /otto-api/action  {"kind":"post","id":"hg-001","status":"approved"}
POST /otto-api/action  {"kind":"rec","id":"rec-002","status":"done"}
POST /otto-api/decide  {"id":"hg-001","decision":"approve|skip|later","via":"dashboard"}   (taste log)
POST /otto-api/action  {"kind":"brand","id":"<brand>","approvals":"email|telegram|app"}   (how approvals reach the brand;
                                       tenant-scoped like every action; ["email","telegram"] = both; logged to actions.log)
GET  /otto-email/act?t=<token>      -> PUBLIC one-tap page from an approval e-mail (otto_email): shows what the button will do,
                                       never acts (mail scanners prefetch links). No login — the signed, single-use, 72-hour token
                                       is the credential. Rate-limited per client (otto_email.rate_ok). Strict CSP (no script).
POST /otto-email/act                -> the page's one button: form-encoded t=<token>&f=<form nonce>; Origin (or Referer) must be
                                       ours (OTTO_ALLOWED_ORIGINS or the e-mail link host). Applies the decision like the dashboard
                                       and Telegram (ap.decide via="email", taste log, transitions, tenant) and burns the nonce.
GET  /otto-api/peek?url=<site>      -> brand DNA peek (authenticated, for the dashboard)
GET  /otto-peek?url=<site>          -> same, PUBLIC — nginx: `location /otto-peek { proxy_pass http://127.0.0.1:8161; }`
                                       (no auth; SSRF-guarded on every hop, rate-limited 1 req / 4 s per client IP,
                                        at most 4 peeks at once, 20 s total deadline, cached 1 h)
POST /otto-track                    -> landing analytics beacon, PUBLIC (otto_track: ≤ 4 KB, allowlisted events, 60 events/min
                                       per client, hashed visitor id with a daily salt, no raw IP stored, DNT/GPC honoured) → 204
POST /otto-api/whop                 -> Whop webhook, PUBLIC in nginx (otto_whop: Standard Webhooks signature, 5-minute window,
                                       each event once) — no Origin check, the signature is the authentication
GET  /auth/google/start?next=/path   -> Google sign-in (otto_auth: OIDC code flow + PKCE + state + nonce) → 302 to Google
GET  /auth/google/callback          -> code exchanged at Google (TLS), ID token verified (RS256 / JWKS, iss, aud, exp, nonce,
                                       email_verified) → user (first login = sign-up + free trial, otto_trial) → session cookie
                                       → 303 to next. Without google-oauth.json both answer 503 "Google sign-in isn't set up yet".
POST /auth/logout                   -> ends the session, clears the cookie (Origin rule as below; no body needed)
GET  /auth/me                       -> {signed_in, google (sign-in configured), email, name, status, trial, brands, checkout}
GET  /otto-api/admin/snapshot?days=30   -> owner console data (otto_admin.snapshot; cached 15 s)
POST /otto-api/admin  {"action":"kill_switch","state":"on","note":"…"} | {"action":"pause_brand"|"resume_brand","brand":…}
                      | {"action":"campaign","id":…,"decision":"approve"|"reject"} | {"action":"rescan","brand":…}
                      | {"action":"lead","id":…,"status":"new|contacted|won|lost","note":…} | {"action":"link_customer",…}
                      | {"action":"whop_sync"} | {"action":"members","brand":…,"add":[…],"remove":[…]}
                      | {"action":"plan","brand":…,"plan":<plans.json id>,"until":"YYYY-MM-DD"|"","note":…}
                      — same JSON + Origin rules as /otto-api/action; logged to actions.log with who

Hardening:
  * Client IP = X-Real-IP only (nginx: `proxy_set_header X-Real-IP $remote_addr;` — never X-Forwarded-For,
    which the client controls). Without the header (direct local call) the socket address is used. Rate limits count an
    IPv6 client by its /64 (otto_track.rate_key).
  * CORS: Access-Control-Allow-Origin only on /otto-peek (the public landing). /otto-api/* sends none.
  * POST: Content-Type must be application/json and Origin (or Referer) must be one of OTTO_ALLOWED_ORIGINS
    (default: the apex, app. and admin. of OTTO_DOMAIN; without it the old box, https://dash.monyflow.work). A proxied request
    (any PROXY_HEADERS header) with neither header is refused.
    Every proxy location in front of this port MUST set X-Real-IP itself (overwriting the client's); Caddy and Cloudflare do
    not by default (Caddy: `header_up X-Real-IP {remote_host}`, or CF-Connecting-IP when only Cloudflare can reach it).
  * Status changes follow ap.POST_TRANSITIONS / ap.REC_TRANSITIONS: published / publishing / failed posts
    cannot be put back to approved from the dashboard.
  * Admin (/otto-api/admin*): behind the same nginx auth as the app, and fail-closed: a proxied request (any of
    PROXY_HEADERS present, or not from 127.0.0.1) is refused unless OTTO_ADMIN_USERS is set — a comma list of users
    (nginx must pass the signed-in user as X-Otto-User, overwriting any client header), or "*" for "anyone the proxy
    let in" (today's single-login mm-check setup). A direct local call (from 127.0.0.1 with no proxy header) is the
    CLI / tests / local sim and is allowed. X-Otto-User is also the "who" in actions.log (default "admin").
  * Tenants: a client sees and changes only their own brands. The proxy names the signed-in user in X-Otto-User
    (Cloudflare Access: Cf-Access-Authenticated-User-Email → X-Otto-User); brands[].members lists who belongs to a
    brand (e-mails, or "@domain"). GET /otto-api/data answers client_view(): that user's brands and what hangs off them —
    posts, campaigns, their recommendations (never owner-internal ones: no brand, audience "owner", internal, or filed by the
    console), metrics / ads / growth / competitors for those ids, connections, taste log, edit requests — and nothing else
    (no fleet, controls, counters). /otto-api/action and /decide answer 404 for another brand's id; /otto-api/onboard
    makes the signed-in user a member of a brand it creates and refuses (409) a site that is someone else's brand.
  * Who is signed in — one source per request, never both: (a) the Google session cookie (otto_auth; app.<domain>, where
    Caddy sends no X-Otto-User any more) — the session's verified e-mail is the user; it is scoped to its member brands
    (brands[].members; "@domain" entries only for a Google Workspace account of that domain) even on OTTO_SINGLE_TENANT or a
    direct local call, and sees everything only when that exact address is in OTTO_ADMIN_USERS ("*" never counts for a
    session); a request carrying both a session and a different X-Otto-User is refused (401). (b) Otherwise the proxy's
    X-Otto-User (Cloudflare Access on admin.) under the OTTO_PROXY_KEY rule below. The console API (/otto-api/admin*) takes
    only (b): a session never opens it. A client whose every brand came from a free trial that ended without a card gets
    402 {"code": "trial_ended" | "no_trial", checkout: […]} from /data, /action and /decide (the data is kept).
    Everything is visible to: admins (OTTO_ADMIN_USERS, or "*"), OTTO_SINGLE_TENANT=1 (today's one-login box), and a
    direct local call. The proxy must overwrite X-Otto-User; OTTO_PROXY_KEY (sent by the proxy as X-Otto-Proxy-Key)
    makes the name count only on requests that came through it. A proxied request with no X-Otto-User gets 401; a user
    with no brand gets 403 on /data.
  * Public onboarding (/otto-onboard) only ever creates a brand; a site that already has one answers 409 (only the
    signed-in /otto-api/onboard may update an existing brand). At most PUBLIC_CREATES_PER_HOUR new brands an hour.
  * Bodies: JSON routes read at most 4 KB (onboarding 16 KB) and answer 413 past it; ids / statuses must be strings.
  * Errors: a 500 says "internal error" and nothing else (the detail goes to api-errors.log: path, status, reason — never a
    body); a failed peek says why in a few fixed words (never an internal address from a redirect).
  * Sockets: a client that stops sending mid-request is dropped after Handler.timeout seconds.

All writes go through ap.transaction() (lock + atomic write; fallback block re-synced)
and are appended to actions.log with approved_via=dashboard.
"""
import hmac, json, os, re, threading, time, urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ap  # same directory — reuse load/transaction
import otto_admin
import otto_auth
import otto_email
import otto_onboard
import otto_scan
import otto_track
import otto_trial
import otto_whop

HERE = Path(__file__).parent
LOG = ap.DATA.parent / "actions.log"
PORT = 8161

POST_STATUSES = ap.STATUSES
REC_STATUSES = ap.REC_STATUSES
_DOMAIN = (os.environ.get("OTTO_DOMAIN") or "").strip()
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in (os.environ.get("OTTO_ALLOWED_ORIGINS") or (    # the new server: its three hosts
    f"https://{_DOMAIN},https://app.{_DOMAIN},https://admin.{_DOMAIN}" if _DOMAIN else "https://dash.monyflow.work")).split(",") if o.strip()}

_peek_lock = threading.Lock()
_peek_sem = threading.BoundedSemaphore(4)
_peek_cache = {}      # url -> (ts, result)
_peek_last = {}       # ip -> ts
PEEK_TTL, PEEK_MIN_GAP, PEEK_MAX_CACHE, PEEK_MAX_IPS, PEEK_DEADLINE = 3600, 4.0, 300, 5000, 20.0
MAX_WEBHOOK = 256 * 1024
MAX_JSON = 4096               # /otto-api/action, /decide, /admin
MAX_FORM = 4096               # /otto-email/act (token + form nonce)
PROXY_HEADERS = ("X-Real-IP", "X-Forwarded-For", "Forwarded", "CF-Connecting-IP", "X-Forwarded-Host", "Via")
SNAP_TTL = 15.0
_snap_cache = {}      # window -> (ts, snapshot)
_snap_lock = threading.Lock()


def _log(line):
    """actions.log line. The write it records has already happened, so a full disk must not turn it into a dropped
    connection (the client would retry an action that went through)."""
    try:
        with LOG.open("a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except OSError as e:
        _log_error("actions.log", 0, f"{type(e).__name__}: {e}")


def _log_error(path, code, why):
    try:
        with (LOG.parent / "api-errors.log").open("a") as f:
            f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {code} {path} {str(why)[:200]}\n")
    except OSError:
        pass


def admin_snapshot(window):
    window = window if window in otto_admin.WINDOWS else 30
    now = time.time()
    with _snap_lock:
        hit = _snap_cache.get(window)
        if hit and now - hit[0] < SNAP_TTL:
            return hit[1]
    snap = otto_admin.snapshot(window=window)
    with _snap_lock:
        _snap_cache[window] = (now, snap)
    return snap


class NoUser(Exception):
    """A proxied request that does not say who is signed in (and the box is not single-tenant)."""


class Ambiguous(Exception):
    """A session cookie and a different proxy-named user on one request: never guess which one counts."""


def admin_users():
    return {u.strip().lower() for u in (os.environ.get("OTTO_ADMIN_USERS") or "").split(",") if u.strip()}


def single_tenant():
    return (os.environ.get("OTTO_SINGLE_TENANT") or "").strip().lower() in ("1", "true", "yes", "on")


OWNER_REC_SOURCES = {"otto_admin"}       # console-filed operational cards ("pause cp-003 by hand") stay with the owner
CLIENT_LIST_KEYS = ("posts", "campaigns", "taste_log")
# owner-side brand fields a client never gets: sign-ins, the console's pause / re-scan notes, who changed the plan and why, the
# retention job's countdown and a legal hold (otto_retention)
CLIENT_HIDDEN_BRAND_KEYS = ("members", "paused", "rescan", "plan_history", "plan_notice", "plan_billing", "ad_band", "retention",
                            "retention_hold", "trial", "activated_by", "activated_at")
HIDDEN_BRAND_KEY = re.compile(r"^retention|notice")      # every retention / notice field, whatever a later module names it
CLIENT_DICT_KEYS = ("metrics", "ads", "competitors", "growth")


def rec_visible(r, bids):
    """A recommendation a client may see / act on: one of their brands', and not owner-internal."""
    return (isinstance(r, dict) and r.get("brand") in bids and r.get("audience") != "owner" and not r.get("internal")
            and r.get("source") not in OWNER_REC_SOURCES)


def client_view(d, bids):
    """data.json as one client sees it (bids = the brand ids they belong to). Allowlist: anything not named here —
    fleet, agents, controls, counters, keys added later — never leaves the server for a client."""
    bids = set(bids)
    brands = [b for b in d.get("brands", []) if isinstance(b, dict) and b.get("id") in bids]
    names = {str(b.get("name") or "").strip().lower() for b in brands} - {""}
    out = {"generated": d.get("generated"), "scope": "client",
           "brands": [dict({k: v for k, v in b.items() if k not in CLIENT_HIDDEN_BRAND_KEYS and not HIDDEN_BRAND_KEY.search(k)},
                           **({"paused": True} if b.get("paused") else {})) for b in brands]}
    for k in CLIENT_LIST_KEYS:
        out[k] = [x for x in d.get(k) or [] if isinstance(x, dict) and x.get("brand") in bids]
    for k in CLIENT_DICT_KEYS:
        v = d.get(k)
        out[k] = {b: x for b, x in v.items() if b in bids} if isinstance(v, dict) else {}
    out["recommendations"] = [r for r in d.get("recommendations") or [] if rec_visible(r, bids)]
    post_ids = {p.get("id") for p in out["posts"]}
    out["edit_requests"] = [e for e in d.get("edit_requests") or [] if isinstance(e, dict) and e.get("post") in post_ids]
    all_ids = {b.get("id") for b in d.get("brands", []) if isinstance(b, dict)}
    own = lambda c: str(c.get("id") or "").split("-", 1)[-1]           # "meta-<brand id>", "tg-<brand id>" …
    out["connections"] = [c for c in d.get("connections") or [] if isinstance(c, dict) and (
        own(c) in bids or (own(c) not in all_ids and str(c.get("brand") or "").strip().lower() in names))]   # legacy: by name
    out["connections"] = [installed_state(c) for c in out["connections"]]
    return out


def installed_state(c):
    """A connection shows "connected" once its credentials are installed (meta-<brand>.json / google-<brand>.json in
    OTTO_SECRETS): tokens arrive out of band today, so connections[] alone would say "not connected" forever."""
    cid = str(c.get("id") or "")
    kind, _, bid = cid.partition("-")
    f = {"meta": f"meta-{bid}.json", "gads": f"google-{bid}.json"}.get(kind)
    secrets = Path(os.environ.get("OTTO_SECRETS") or Path(__file__).resolve().parent.parent.parent / "otto-secrets")
    if f and bid and c.get("status") != "connected" and (secrets / f).is_file():
        return dict(c, status="connected")
    return c


def with_plans(d, full=None):
    """Each brand of the answer carries plan_view (ap.plan_view: label, what is included, this month's usage) for the app's
    Settings, and plan_view.trial {state, ends_at, days_left} while it came from a free trial. A plan that cannot be resolved
    never fails the request. full = the whole data.json when d is a client view (the trial record is not in it)."""
    src = full if full is not None else d
    now = otto_trial.utcnow()
    for b in d.get("brands") or []:
        if isinstance(b, dict) and b.get("id"):
            try:
                b["plan_view"] = {k: v for k, v in ap.plan_view(src, b["id"]).items() if k not in ("config_error", "not_billed", "band")}
                full_b = ap.brand(src, b["id"]) or {}
                rt = full_b.get("retention")
                if b["plan_view"].get("ended") and isinstance(rt, dict) and rt.get("delete_on"):
                    b["plan_view"]["delete_on"] = str(rt["delete_on"])[:10]      # the date only: the notices stay the owner's
                tr = full_b.get("trial")
                if isinstance(tr, dict):
                    end = otto_trial._dt(tr.get("ends_at"))
                    state = ("converted" if tr.get("converted_at") else "denied" if tr.get("denied") else
                             "running" if end and now < end else "ended")
                    b["plan_view"]["trial"] = {"state": state, "ends_at": tr.get("ends_at"), "denied": tr.get("denied"),
                                               "days_left": max(1, -(-int((end - now).total_seconds()) // 86400))
                                               if state == "running" else None}
            except Exception as e:                            # the app works without it
                _log_error("/otto-api/data", 200, f"plan_view {b['id']}: {type(e).__name__}: {e}")
    return d


def owner_view(d):
    """data.json as the owner / admin gets it: everything, with the same installed-credentials overlay on connections as
    the client's view (installed_state), so both say "connected" for the same brand."""
    d["connections"] = [installed_state(c) if isinstance(c, dict) else c for c in d.get("connections") or []]
    return d


DASHBOARD_DECISIONS = {"approved": "approve", "skipped": "skip"}


def apply_action(kind, item_id, status, note=None, bids=None):
    """Dashboard status change. Approve/skip go through ap.decide so the taste log learns from the web app
    exactly as from Telegram; a Change note (status → draft) is stored as an edit request for Quill.
    bids: the brand ids the caller may act on (None = all); another brand's id is "unknown" (404), never a 403 that
    would confirm it exists."""
    if not isinstance(kind, str) or not isinstance(status, str):
        raise ValueError("kind and status must be strings")
    if kind == "post":
        if status not in POST_STATUSES:
            raise ValueError(f"bad post status {status}")
    elif kind == "rec":
        if status not in REC_STATUSES:
            raise ValueError(f"bad rec status {status}")
    else:
        raise ValueError(f"bad kind {kind}")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("id must be a string")
    note = str(note).strip()[:500] if note else ""
    snap = None
    with ap.transaction() as d:
        item = ap.post(d, item_id) if kind == "post" else ap.rec(d, item_id)
        if item is None or (bids is not None and not (item.get("brand") in bids if kind == "post" else rec_visible(item, bids))):
            raise KeyError(item_id)
        if kind == "post" and status in DASHBOARD_DECISIONS:
            ap.decide(d, item_id, DASHBOARD_DECISIONS[status], "dashboard")      # status + taste log
        else:
            ap.check_transition(kind, item.get("status"), status)
            acts = kind == "rec" and status in ("approved", "done") and item.get("status") == "proposed" and has_rec_action(item)
            item["status"] = "approved" if acts else status        # an action card is "approved" until its action ran
            item["approved_via"] = "dashboard"
            item["decided_at"] = ap.now_iso()
            snap = dict(item) if acts else None
        if kind == "post" and status == "draft" and note:
            item["edit_note"] = note
            d.setdefault("edit_requests", []).append({"post": item_id, "note": note, "ts": ap.now_iso(), "via": "dashboard"})
    _log(f"dashboard {kind} {item_id} -> {status}" + (" (edit note)" if note else ""))
    if snap is not None:
        run_dashboard_rec(snap, status)
    return ap.load()


class ActionFailed(Exception):
    """The approval is saved, but what it starts failed (the owner has a P0 card). str(e) is for the client."""


def has_rec_action(r):
    """A recommendation whose approval runs code — the same cards e-mail and Telegram act on (otto_ads: the monthly paid
    plan, a pause-campaign card)."""
    return isinstance(r, dict) and r.get("source") == "otto_ads" and (
        otto_email.is_plan_card(r) or r.get("action") in ("approve_plan", "pause_campaign"))


def run_rec_action(r, via="dashboard"):
    """What approving a recommendation does in code, as the e-mail (otto_email.run_rec_action) and Telegram paths do it,
    recorded as approved from the app. → a short result, or None for an informational card."""
    if r.get("source") != "otto_ads":
        return None
    import otto_ads
    if otto_email.is_plan_card(r):
        ym = otto_email.plan_month(r)
        if not (ym and r.get("brand")):
            return None
        n = otto_ads.approve(r["brand"], ym, via=via)
        return f"{n} campaign(s) approved for {otto_email.month_label(ym)}"
    return otto_ads.rec_action(r)


def run_dashboard_rec(snap, status):
    """Run an approved card's action outside the data lock; the card ends "done" with action_result, or stays "approved"
    with action_error + the owner's P0 card (ap.rec_action_failed) and ActionFailed for the app."""
    import contextlib, io
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out = run_rec_action(snap)
    except Exception as e:
        _log_error("/otto-api/action", 502, f"rec action {snap.get('id')}: {type(e).__name__}: {e}")
        with ap.transaction() as d:
            ap.rec_action_failed(d, snap, f"{type(e).__name__}: {e}", "in the app")
        _log(f"dashboard rec {snap.get('id')} action FAILED")
        raise ActionFailed("Your approval is saved, but Otto could not start it just now. Otto's team has been told and will "
                           "finish it; nothing spends meanwhile.")
    with ap.transaction() as d:
        q = ap.rec(d, snap["id"])
        if q is not None:
            if out:
                q["action_result"] = out
            q["status"] = "done" if (out or status == "done") else "approved"
    if out:
        _log(f"dashboard rec {snap['id']} · {out}")


def apply_decision(item_id, decision, via, bids=None):
    if not isinstance(item_id, str) or not isinstance(decision, str):
        raise ValueError("id and decision must be strings")
    via = via if via in ("dashboard", "telegram", "email", "auto") else "dashboard"
    with ap.transaction() as d:
        if bids is not None and (ap.post(d, item_id) or {}).get("brand") not in bids:
            raise KeyError(item_id)                     # another client's post is not there for this caller
        ap.decide(d, item_id, decision, via)            # enforces the transition table
    _log(f"{via} decide {item_id} -> {decision}")
    return ap.load()


BRAND_SETTINGS = ("approvals",)


def apply_brand(bid, req, bids=None):
    """A brand setting the client changes in the app's Settings (today: how approvals reach them). Same tenant rule as
    apply_action: another brand's id is "unknown" (404)."""
    if not isinstance(bid, str) or not bid.strip():
        raise ValueError("id must be a string")
    if not any(k in req for k in BRAND_SETTINGS):
        raise ValueError("nothing to change (approvals)")
    value = otto_email.normalize_approvals(req.get("approvals"))       # ValueError on anything but email / telegram / app
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None or (bids is not None and bid not in bids):
            raise KeyError(bid)
        before = otto_email.approvals_label(b)
        b["approvals"] = value
        b["approvals_set"] = {"at": ap.now_iso(), "via": "dashboard"}
        after = otto_email.approvals_label(b)
    _log(f"dashboard brand {bid} approvals {before.lower()} -> {after.lower()}")
    return ap.load()


def _prune_last(now):
    """Forget IPs whose gap has passed (the map only needs the last PEEK_MIN_GAP seconds); hard cap on size."""
    if len(_peek_last) > 1000:
        for ip in [ip for ip, ts in _peek_last.items() if now - ts > PEEK_MIN_GAP]:
            _peek_last.pop(ip, None)
    while len(_peek_last) > PEEK_MAX_IPS:
        _peek_last.pop(next(iter(_peek_last)))


def _cached_peek(url):
    """This server's own /otto-peek result for the site (never the client's copy), or None."""
    with _peek_lock:
        hit = _peek_cache.get(otto_scan.normalize_url(url))
    return hit[1] if hit and time.time() - hit[0] < PEEK_TTL else None


def peek_reason(err):
    """otto_scan's error → a few fixed words for the public page (never an internal address or a stack detail)."""
    e = str(err or "").lower()
    for keys, why in ((("non-public", "local host", "scheme", "port", "credentials", "no host", "bad host", "too many redirects"),
                       "the site redirects somewhere Otto does not read"),
                      (("dns", "no address", "name or service", "nodename"), "the domain does not resolve"),
                      (("deadline", "timed out", "timeout"), "the site took too long to answer"),
                      (("ssl", "certificate"), "the site's HTTPS certificate is not valid"),
                      (("refused", "unreachable", "reset"), "the site refused the connection")):
        if any(k in e for k in keys):
            return why
    m = re.search(r"http (?:error )?(\d{3})", e)
    return f"the site answered HTTP {m.group(1)}" if m else "the site could not be read"


def peek(url, ip):
    url = otto_scan.normalize_url(url)
    try:
        otto_scan.check_url(url)                              # syntax only: no DNS before the cache and the rate limit
    except otto_scan.Blocked:
        return 400, {"error": "unsupported or unsafe url"}
    if len(url) > 300:
        return 400, {"error": "unsupported or unsafe url"}
    now = time.time()
    with _peek_lock:
        hit = _peek_cache.get(url)
        if hit and now - hit[0] < PEEK_TTL:
            return 200, dict(hit[1], cached=True)
        if now - _peek_last.get(ip, 0) < PEEK_MIN_GAP:
            return 429, {"error": "slow down"}
        _peek_last[ip] = now
        _prune_last(now)
    st = otto_scan.host_status(url)                           # DNS: every address must be public
    if st == "not_found":
        return 404, {"error": "site not found"}
    if st != "ok":
        return 400, {"error": "unsupported or unsafe url"}
    if not _peek_sem.acquire(timeout=2):
        return 503, {"error": "busy — try again in a few seconds"}
    try:
        result = otto_scan.peek(url, deadline=time.time() + PEEK_DEADLINE)
    finally:
        _peek_sem.release()
    if "error" in result:
        return 502, {"error": "could not read the site", "detail": peek_reason(result["error"])}
    with _peek_lock:
        for k in [k for k, (ts, _) in _peek_cache.items() if now - ts >= PEEK_TTL]:
            _peek_cache.pop(k, None)
        while len(_peek_cache) >= PEEK_MAX_CACHE:
            _peek_cache.pop(next(iter(_peek_cache)))
        _peek_cache[url] = (now, result)
    return 200, result


class Handler(BaseHTTPRequestHandler):
    timeout = 30                  # a client that stops sending mid-request (slowloris) is dropped, not waited on forever

    def log_message(self, *a):  # keep journal quiet
        pass

    def _public(self):
        return urllib.parse.urlsplit(self.path).path.rstrip("/") == "/otto-peek"

    def _direct_local(self):
        """A call made on this machine straight to the port (CLI, tests, a local sim), not through nginx / Caddy / Cloudflare.
        Any proxy header counts as "proxied", so a proxy location that forgot `X-Real-IP` still does not look local
        (Caddy adds X-Forwarded-For by default; Cloudflare adds CF-Connecting-IP)."""
        return self.client_address[0] in ("127.0.0.1", "::1") and not any(self.headers.get(h) for h in PROXY_HEADERS)

    def _user(self):
        """The signed-in user the proxy names (lower case), or "". The proxy MUST overwrite any X-Otto-User the browser sent;
        with OTTO_PROXY_KEY set, the name only counts on a request that also carries X-Otto-Proxy-Key with that value
        (so a request that reached this port some other way cannot name itself an admin)."""
        key = (os.environ.get("OTTO_PROXY_KEY") or "").strip()
        if key and not hmac.compare_digest((self.headers.get("X-Otto-Proxy-Key") or "").strip().encode(), key.encode()):
            return ""
        return (self.headers.get("X-Otto-User") or "").strip().lower()[:200]

    def _session(self):
        """The Google session of this request (otto_auth.current: {"user", "token", "refresh"}) or None; read once. A slid
        session re-sends its cookie on this response."""
        if not hasattr(self, "_sess"):
            try:
                self._sess = otto_auth.current(self.headers.get("Cookie"))
            except Exception as e:                            # an unreadable session store signs nobody in
                _log_error(self.path.split("?")[0], 500, f"session: {type(e).__name__}: {e}")
                self._sess = None
            if self._sess and self._sess.get("refresh"):
                self._extra.append(otto_auth.refresh_cookie(self._sess["token"]))
        return self._sess

    def _scope(self):
        """(bids, user): bids None = sees everything (admin, single tenant, direct local call), else the set of brand ids
        the signed-in user is a member of (possibly empty). Raises NoUser for a proxied call that names nobody, Ambiguous
        for a session and a different proxy user on one request. A Google session always scopes (see the module doc)."""
        sess = self._session()
        if sess:
            email = str(sess["user"].get("email") or "").lower()
            proxy = self._user()
            if proxy and proxy != email:
                raise Ambiguous()
            if email in admin_users():                         # an exact address; "*" never makes a session an admin
                return None, email
            return ap.member_brands(ap.load(), email, domains=otto_trial.domain_ok(sess["user"])), email
        if single_tenant() or self._direct_local():
            return None, self._user() or None
        user, admins = self._user(), admin_users()
        if "*" in admins or (user and user in admins):
            return None, user or None
        if not user:
            raise NoUser()
        return ap.member_brands(ap.load(), user), user

    def _no_user(self, ambiguous=False):
        if ambiguous:
            return self._send(401, {"error": "two different sign-ins on one request — sign out and sign in again", "signin": True})
        return self._send(401, {"error": "sign in first", "signin": True, "google": otto_auth.configured()})

    def _paywall(self, bids):
        """402 when every brand of a scoped caller came from a free trial that ended without a card (otto_trial.paywall)."""
        if not bids:
            return None
        sess = self._session()
        return otto_trial.paywall(ap.load(), bids, sess["user"] if sess else None)

    def _admin_ok(self):
        """Fail-closed: behind the proxy the console needs OTTO_ADMIN_USERS ("*" = anyone the proxy authenticated);
        a direct local call (CLI, tests) is allowed."""
        users = admin_users()
        if otto_auth.session_token_from(self.headers.get("Cookie")) and not self._user():
            return False                                      # a Google session never opens the console (admin. is Access)
        if "*" in users:
            return True
        if not users:
            return self._direct_local()
        return bool(self._user()) and self._user() in users

    def _not_admin(self):
        why = "not an admin" if (os.environ.get("OTTO_ADMIN_USERS") or "").strip() else \
            "the owner console is locked: set OTTO_ADMIN_USERS in the otto-api service (a user list, or * for anyone nginx lets in)"
        return self._send(403, {"error": why})

    def _fail(self, path, e):
        """500 without internals: the client gets two words, api-errors.log gets the exception."""
        _log_error(path, 500, f"{type(e).__name__}: {e}")
        return self._send(500, {"error": "internal error"})

    def _who(self):
        return otto_admin.clean_who(self._user())

    def setup(self):
        super().setup()
        self._extra = []                                      # extra response headers (a slid session's cookie)

    def _length(self):
        """Content-Length as an int; -1 when it is missing, negative or not a number (never read until EOF)."""
        try:
            n = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            return -1
        return n if n >= 0 else -1

    def _body(self, limit):
        """Raw body, or None when it is missing or bigger than `limit` (never read past it)."""
        n = self._length()
        if n <= 0 or n > limit:
            return None
        return self.rfile.read(n)

    def _empty(self, code):
        self.send_response(code)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in self._pop_extra():
            self.send_header(k, v)
        if self._public():
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _pop_extra(self):
        out, self._extra = list(getattr(self, "_extra", [])), []
        return out

    def _reply(self, r):
        """An otto_auth.Reply (redirect, page or JSON): never cached, never framed, no referrer (the callback URL carries the
        code), its own CSP for pages; an actions.log line when it has one."""
        if r.log:
            _log(f"{r.log} ip={self._client_ip()}")
        if r.event:
            self._measure(*r.event)
        self.send_response(r.code)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in list(r.headers) + self._pop_extra():
            self.send_header(k, v)
        self.send_header("Content-Type", r.ctype)
        self.send_header("Content-Length", str(len(r.body)))
        self.end_headers()
        self.wfile.write(r.body)

    def _measure(self, event, ref):
        """A server-confirmed sign-up / trial start → Meta, only under otto_track's rules (meta-capi.json + the visitor's
        consent cookie on this request, never with DNT / GPC); never fails the request."""
        try:
            otto_track.capi_track(event, self._client_ip(), self.headers, path=urllib.parse.urlsplit(self.path).path, ref=ref)
        except Exception as e:
            _log_error(self.path.split("?")[0], 200, f"capi {event}: {type(e).__name__}")

    def _me(self):
        """GET /auth/me: who is signed in (Google session, else the proxy's user) and what they may buy."""
        try:
            sess = self._session()
            google = otto_auth.configured()
            if sess:
                return self._send(200, dict(otto_trial.account_view(ap.load(), sess["user"]), google=google, via="google"))
            proxy = self._user()
            if proxy and not self._direct_local():
                return self._send(200, {"signed_in": True, "email": proxy, "via": "proxy", "google": google, "checkout": []})
            return self._send(200, {"signed_in": False, "google": google})
        except Exception as e:
            self._fail("/auth/me", e)

    def _client_ip(self):
        return (self.headers.get("X-Real-IP") or self.client_address[0]).strip()

    def _origin_ok(self):
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin:
            return origin in ALLOWED_ORIGINS
        ref = (self.headers.get("Referer") or "").strip()
        if ref:
            u = urllib.parse.urlsplit(ref)
            return f"{u.scheme}://{u.netloc}" in ALLOWED_ORIGINS
        # no browser headers at all: only a direct local call (not through a proxy) is accepted
        return self._direct_local()

    def do_OPTIONS(self):
        if not self._public():
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _begin(self):
        """Per-request state (a keep-alive connection must never carry one request's session into the next)."""
        self._extra = []
        self.__dict__.pop("_sess", None)

    def do_GET(self):
        self._begin()
        u = urllib.parse.urlsplit(self.path)
        path = u.path.rstrip("/")
        if path == "/auth/google/start":
            try:
                return self._reply(otto_auth.start(u.query, otto_track.rate_key(self._client_ip())))
            except Exception as e:
                return self._fail(path, e)
        if path == "/auth/google/callback":
            try:
                return self._reply(otto_auth.callback(u.query, self.headers.get("Cookie"), otto_track.rate_key(self._client_ip())))
            except Exception as e:
                return self._fail(path, e)
        if path == "/auth/me":
            return self._me()
        if path == "/otto-api/data":
            try:
                bids, user = self._scope()
            except NoUser:
                return self._no_user()
            except Ambiguous:
                return self._no_user(ambiguous=True)
            if bids is None:
                return self._send(200, with_plans(owner_view(ap.load())))
            if not bids:
                return self._send(403, {"error": "no brand is linked to this login yet", "code": "no_brand",
                                        "onboarding": "/onboarding.html" if self._session() else None})
            pw = self._paywall(bids)
            if pw:
                return self._send(402, pw)
            d = ap.load()
            self._send(200, with_plans(client_view(d, bids), full=d))
        elif path == "/otto-api/admin/snapshot":
            if not self._admin_ok():
                return self._not_admin()
            q = urllib.parse.parse_qs(u.query)
            try:
                days = int((q.get("days") or ["30"])[0])
            except ValueError:
                return self._send(400, {"error": "days must be 7, 30 or 90"})
            try:
                self._send(200, admin_snapshot(days))
            except Exception as e:
                self._fail(path, e)
        elif path == "/otto-email/act":
            q = urllib.parse.parse_qs(u.query)
            self._email_act("GET", (q.get("t") or [""])[0], None)
        elif path in ("/otto-peek", "/otto-api/peek"):
            q = urllib.parse.parse_qs(u.query)
            url = (q.get("url") or [""])[0].strip()
            if not url:
                return self._send(400, {"error": "url required"})
            try:
                code, obj = peek(url, otto_track.rate_key(self._client_ip()))
                self._send(code, obj)
            except Exception as e:
                self._fail(path, e)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        self._begin()
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path == "/otto-track":
            return self._track()
        if path == "/otto-api/whop":
            return self._whop()
        if path == "/otto-email/act":
            return self._email_post()
        if path == "/auth/logout":
            if not self._origin_ok():
                return self._send(403, {"error": "cross-origin request refused"})
            if self._length() > MAX_JSON:
                return self._send(413, {"error": "request too large"})
            try:
                return self._reply(otto_auth.logout(self.headers.get("Cookie")))
            except Exception as e:
                return self._fail(path, e)
        if path not in ("/otto-api/action", "/otto-api/decide", "/otto-api/admin", "/otto-api/onboard", "/otto-onboard"):
            return self._send(404, {"error": "not found"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._send(415, {"error": "Content-Type must be application/json"})
        if not self._origin_ok():
            return self._send(403, {"error": "cross-origin request refused"})
        if path == "/otto-api/admin" and not self._admin_ok():
            return self._not_admin()
        if path == "/otto-onboard":
            # the public twin for a buyer who has no login yet (same origin + JSON rules, rate-limited in otto_onboard;
            # the brand starts as "onboarding" until its Whop membership is linked). It only creates: an existing brand
            # is never changed from the public route.
            return self._onboard(public=True)
        try:
            bids, user = self._scope()
        except NoUser:
            return self._no_user()
        except Ambiguous:
            return self._no_user(ambiguous=True)
        if path == "/otto-api/onboard":
            return self._onboard(bids=bids, user=user)
        if path in ("/otto-api/action", "/otto-api/decide"):
            pw = self._paywall(bids)
            if pw:
                return self._send(402, pw)
        n = self._length()
        if n > MAX_JSON:
            return self._send(413, {"error": f"request too large (at most {MAX_JSON} bytes)"})
        if n <= 0:
            return self._send(400, {"error": "JSON body required"})
        try:
            req = json.loads(self.rfile.read(n))
            if not isinstance(req, dict):
                raise ValueError("JSON object expected")
            if path == "/otto-api/admin":
                out = otto_admin.act(req, self._who())
                with _snap_lock:
                    _snap_cache.clear()
                if req.get("window") in otto_admin.WINDOWS:
                    out["snapshot"] = admin_snapshot(req["window"])
                return self._send(200, out)
            if path == "/otto-api/decide":
                data = apply_decision(req.get("id"), req.get("decision"), req.get("via"), bids=bids)
            elif req.get("kind") == "brand":
                data = apply_brand(req.get("id"), req, bids=bids)
            else:
                data = apply_action(req.get("kind"), req.get("id"), req.get("status"), req.get("note"), bids=bids)
            self._send(200, {"ok": True, "data": with_plans(owner_view(data)) if bids is None
                             else with_plans(client_view(data, bids), full=data)})
        except ActionFailed as e:
            self._send(502, {"error": str(e), "saved": True})
        except KeyError as e:
            self._send(404, {"error": f"unknown id {str(e)[:80]}"})
        except (ValueError, AssertionError, RecursionError) as e:     # JSONDecodeError is a ValueError
            self._send(400, {"error": str(e)[:300] or "bad request"})
        except Exception as e:
            self._fail(path, e)

    def _send_page(self, code, body, csp):
        """An HTML page of the e-mail flow: no caching, no framing, no sniffing, a strict CSP (the page repeats it in a meta
        tag, so it holds even where the proxy sets its own CSP header), no referrer beyond this origin, not indexed."""
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Content-Security-Policy", csp)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _email_origin_ok(self):
        """Like _origin_ok, plus the host the e-mail links point at (the page posts to itself there)."""
        allowed = set(ALLOWED_ORIGINS) | {otto_email._origin(otto_email.action_base())}
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin:
            return origin in allowed
        ref = (self.headers.get("Referer") or "").strip()
        if ref:
            u = urllib.parse.urlsplit(ref)
            return f"{u.scheme}://{u.netloc}" in allowed
        return self._direct_local()

    def _email_act(self, method, token, form, origin_ok=True):
        try:
            code, body, csp, line = otto_email.http_act(method, token, form, otto_track.rate_key(self._client_ip()), origin_ok)
        except Exception as e:
            _log_error("/otto-email/act", 500, f"{type(e).__name__}: {e}")
            code, (body, csp), line = 500, otto_email.token_page("config"), None
        if line:
            _log(line)
            with _snap_lock:
                _snap_cache.clear()
        self._send_page(code, body, csp)

    def _email_post(self):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            return self._send(415, {"error": "Content-Type must be application/x-www-form-urlencoded"})
        body = self._body(MAX_FORM)
        if body is None:
            return self._send(413, {"error": f"body required, at most {MAX_FORM} bytes"})
        try:
            q = urllib.parse.parse_qs(body.decode("ascii"), max_num_fields=4)
        except (UnicodeDecodeError, ValueError):
            return self._send(400, {"error": "bad form"})
        self._email_act("POST", (q.get("t") or [""])[0], (q.get("f") or [""])[0], self._email_origin_ok())

    def _onboard(self, public=False, bids=None, user=None):
        n = self._length()
        if n > otto_onboard.MAX_BODY:                        # 16 KB; the 4 KB JSON limit would cut answers off
            return self._send(413, {"error": "request too large"})
        if n <= 0:
            return self._send(400, {"error": "JSON body required"})
        sess = None if public else self._session()
        try:
            code, obj = otto_onboard.http_create(self.rfile.read(n), otto_track.rate_key(self._client_ip()), cached_peek=_cached_peek,
                                                 public=public, bids=bids, user=user, account=sess["user"] if sess else None)
        except Exception as e:
            return self._fail("/otto-onboard" if public else "/otto-api/onboard", e)
        if code == 200:
            tr = obj.get("trial")
            if tr and tr.get("granted") and sess:
                self._measure("trial_start", obj["brand"])
            _log(f"onboard {obj['brand']} {'created' if obj['created'] else 'updated'}{' (public)' if public else ''}"
                 + (f" trial={'granted' if tr.get('granted') else tr.get('why')}" if tr else "") + f" ip={self._client_ip()}")
            if sess and obj.get("created"):
                try:                                          # paid on Whop before the brand existed: link it now
                    linked = otto_trial.link_pending(sess["user"])
                    if linked:
                        obj["linked"] = {"membership": linked.get("id"), "plan": (linked.get("plan_sync") or {}).get("to")}
                        _log(f"onboard {obj['brand']} linked to Whop {linked.get('id')} (verified e-mail)")
                except Exception as e:
                    _log_error("/otto-api/onboard", 200, f"link_pending: {type(e).__name__}: {e}")
        self._send(code, obj)

    def _track(self):
        """Public analytics beacon. sendBeacon posts a string as text/plain, so both types are accepted; a browser always
        sends Origin on POST, and a foreign one is refused. Everything else is otto_track's job."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in ("application/json", "text/plain"):
            return self._send(415, {"error": "Content-Type must be application/json or text/plain"})
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin and origin not in ALLOWED_ORIGINS:
            return self._send(403, {"error": "cross-origin request refused"})
        body = self._body(otto_track.MAX_BODY)
        if body is None:
            return self._send(413, {"error": f"body required, at most {otto_track.MAX_BODY} bytes"})
        try:
            code, obj = otto_track.ingest(body, self._client_ip(), self.headers)
        except Exception as e:
            _log_error("/otto-track", 500, f"{type(e).__name__}: {e}")
            return self._send(500, {"error": "tracking failed"})
        return self._empty(code) if obj is None else self._send(code, obj)

    def _whop(self):
        """Whop → us, server to server. The signature (otto_whop.verify) is the authentication; no Origin involved."""
        body = self._body(MAX_WEBHOOK)
        if body is None:
            return self._send(413, {"error": "body required"})
        try:
            code, obj = otto_whop.webhook(body, self.headers)
        except Exception as e:
            code, obj = 500, {"error": f"{type(e).__name__}"}
            _log_error("/otto-api/whop", 500, f"{type(e).__name__}: {e}")
        else:
            if code != 200:
                _log_error("/otto-api/whop", code, obj.get("error"))
            else:
                _log(f"whop {obj.get('type')} {obj.get('ref') or ''}{' (duplicate)' if obj.get('duplicate') else ''}")
                with _snap_lock:
                    _snap_cache.clear()
        self._send(code, obj)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
