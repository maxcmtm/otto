#!/usr/bin/env python3
"""Otto landing analytics — first-party, no cookies, no third-party scripts, no raw IPs.

  POST /otto-track   (public, like /otto-peek; nginx rate-limits it first)
       body (≤ 4 KB, application/json or text/plain — navigator.sendBeacon sends a string as text/plain):
       {"p": "/pilot-landing.html", "s": "<page-load id>", "r": "google.com", "u": {"source": "…", …}, "dv": "mobile",
        "ev": [{"e": "view"}, {"e": "scroll", "d": 50}, {"e": "section", "id": "pricing"}, {"e": "cta", "id": "get_started@pricing"},
               {"e": "scan_start", "domain": "example.com"}, {"e": "scan_result", "domain": "example.com", "ok": true},
               {"e": "faq_open", "q": "does-anything-publish-without-my-approval"}, {"e": "video_play", "id": "showreel"}]}

  otto_track.py tail [n]            # last n stored events
  otto_track.py prune --days 400    # drop events older than N days (rewrites the file atomically)

What is stored (one JSON line per event in $OTTO_EVENTS, default events.jsonl next to data.json, git-ignored):
  {"ts", "e", "v": visitor, "s": page-load id, "p": path, +event fields}; a "view" also carries "r" (referrer host),
  "u" (utm_*), "dv" (mobile|tablet|desktop) and "cc" (country from the nginx X-Country header, when nginx sets one).
  v = sha256(daily salt + client IP + user agent)[:16]. The salt lives in .track-salt (chmod 600) and is replaced every UTC day,
  so a visitor can be counted once per day and never followed across days; the IP itself is never written anywhere.
  The only personal-ish value kept is the domain a visitor typed into the scan box (that is the lead).
Privacy: Do Not Track (DNT: 1) or Global Privacy Control (Sec-GPC: 1, or "anon": 1 from the page) → only an anonymous page view
  ({"ts","e":"view","p","anon":1}: no visitor id, referrer, utm, device or country); every other event is dropped.
Validation: allowlisted event names and fields only, strict formats and lengths, ≤ 20 events per request, e-mail-like utm values
  dropped. Rate limit: 60 events / minute per client (keyed by the hashed IP; an IPv6 client by its /64), 3000 / minute overall; the file stops growing
  at $OTTO_EVENTS_MAX_MB (default 512).
Meta Conversions API (Otto's own ad measurement, server-side; no Meta script ever runs in the visitor's browser):
  only when $OTTO_SECRETS/meta-capi.json exists with a pixel_id and an access_token ({"pixel_id", "access_token",
  "test_event_code"?, "site_url"?}) AND the request carries the consent cookie otto_consent=v1.granted (set by
  assets/consent.js when the visitor presses Accept) AND no DNT / GPC signal. Then, after the events are stored:
  scan_start → ViewContent, scan_result with ok → Lead, a CTA click whose kind is get_started / start_trial / trial / signup
  (cta id "<kind>@<where>", CAPI_CTA_KINDS) → InitiateCheckout, posted in a background thread. Sign-up itself is never taken
  from the public beacon (it could be spoofed): the server code that completes a sign-up calls
  capi_track("signup" → CompleteRegistration | "trial_start" → StartTrial, ip, request headers) with the same rules.
  Sent: event name, time, an event id, the page URL (Origin + path), and user_data = the client IP address and user agent
  (Meta needs them to match the event; neither is stored by us), the Meta click id from the otto_fbc cookie (set only
  after consent, only from a ?fbclid= link), sha256 of the day's visitor code (external_id) and sha256 of the country code.
  Never sent: the scanned domain, referrer, utm tags, anything typed. No file, no id or no consent → no network call at all.
  otto_track.py capi-status         # is forwarding configured? (no network call)
  otto_track.py capi-test           # send one ViewContent test event (needs "test_event_code"; shows in Events Manager → Test events)
"""
import hashlib, ipaddress, json, os, re, secrets, sys, threading, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap

EVENTS = {"view", "scroll", "section", "cta", "scan_start", "scan_result", "faq_open", "video_play"}
UTM_KEYS = ("source", "medium", "campaign", "content", "term")
DEVICES = {"mobile", "tablet", "desktop"}
SCROLL = {25, 50, 75, 100}
MAX_BODY, MAX_EVENTS = 4096, 20
RATE_PER_MIN, GLOBAL_PER_MIN = 60, 3000

_PATH = re.compile(r"^/[A-Za-z0-9/._~-]{0,119}$")
_SID = re.compile(r"^[a-z0-9]{6,16}$")
_HOST = re.compile(r"^(?=.{3,100}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_:@.-]{0,47}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_UTM = re.compile(r"^[\w .+%:/()|!-]{1,64}$", re.UNICODE)
_IP_LIKE = re.compile(r"^[0-9.]+$|:")
_SCHEME = re.compile(r"^\s*[a-z][a-z0-9+.-]*\s*:", re.I)

_lock = threading.Lock()
_salt_lock = threading.Lock()
_buckets = {}                 # hashed ip -> [tokens, last ts]
_global = [float(GLOBAL_PER_MIN), time.time()]
_salt = {"day": None, "salt": None}
_full_warned = [False]


def events_path():
    return Path(os.environ.get("OTTO_EVENTS") or ap.DATA.parent / "events.jsonl")


def salt_path():
    return events_path().with_name(".track-salt")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_salt():
    """Random salt for today's visitor ids. Kept in a file so every API worker/restart agrees within the day;
    replaced (the old one is gone) as soon as the UTC day changes."""
    day = today()
    if _salt["day"] == day:
        return _salt["salt"]
    with _salt_lock:              # two threads at midnight must not each write a different salt for the same day
        if _salt["day"] == day:
            return _salt["salt"]
        return _new_salt(day)


def _new_salt(day):
    f = salt_path()
    try:
        cur = json.loads(f.read_text())
        if cur.get("day") == day and len(cur.get("salt", "")) >= 32:
            _salt["salt"] = cur["salt"]; _salt["day"] = day        # salt first: the lock-free fast path reads day, then salt
            return cur["salt"]
    except Exception:
        pass
    cur = {"day": day, "salt": secrets.token_hex(32)}
    f.parent.mkdir(parents=True, exist_ok=True)
    ap._atomic_write(f, json.dumps(cur))
    os.chmod(f, 0o600)
    _salt["salt"] = cur["salt"]; _salt["day"] = day
    return cur["salt"]


def rate_key(ip):
    """What a per-client rate limit counts: an IPv4 address, or a whole IPv6 /64 (one subscriber owns a /64 and can
    rotate through it at will, so a per-address limit would not limit anything)."""
    ip = str(ip or "").strip()[:64]
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if a.version == 6 and a.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(getattr(a, "ipv4_mapped", None) or a)


def visitor_id(ip, ua):
    return hashlib.sha256(f"{daily_salt()}|{ip}|{ua}".encode()).hexdigest()[:16]


def _take(bucket, rate_per_min, now):
    tokens, last = bucket
    tokens = min(float(rate_per_min), tokens + (now - last) * rate_per_min / 60.0)
    bucket[1] = now
    if tokens < 1:
        bucket[0] = tokens
        return False
    bucket[0] = tokens - 1
    return True


def allow(key, n=1, now=None):
    """Token buckets: per client (hashed IP) and overall. n = events in this request."""
    now = now or time.time()
    with _lock:
        if len(_buckets) > 20000:                           # forget idle clients (a full bucket is the default anyway)
            for k in [k for k, (_, ts) in _buckets.items() if now - ts > 120]:
                _buckets.pop(k, None)
        b = _buckets.setdefault(key, [float(RATE_PER_MIN), now])
        for _ in range(n):
            if not (_take(b, RATE_PER_MIN, now) and _take(_global, GLOBAL_PER_MIN, now)):
                return False
        return True


def clean_domain(v):
    """What a visitor typed into the scan box → bare host (lowercase, no scheme/www/path), or None."""
    if not isinstance(v, str):
        return None
    v = v.strip().lower()
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = re.split(r"[/?#\s]", v, 1)[0].split("@")[-1].split(":")[0].rstrip(".")
    if v.startswith("www."):
        v = v[4:]
    try:
        v = v.encode("idna").decode("ascii")
    except Exception:
        return None
    if not _HOST.match(v) or v.endswith((".local", ".localhost", ".internal", ".lan")):
        return None
    return v


def clean_host(v):
    return clean_domain(v) if v else None


def clean_utm(u):
    if not isinstance(u, dict):
        return None
    out = {}
    for k in UTM_KEYS:
        v = u.get(k)
        if isinstance(v, str):
            v = v.strip()[:64]
            if v and "@" not in v and _UTM.match(v) and not _SCHEME.match(v):   # no e-mail, no javascript:/data: URL
                out[k] = v
    return out or None


def clean_event(ev):
    """One raw event → the stored fields (without ts/v/s/p), or None when it is not allowed."""
    if not isinstance(ev, dict) or not isinstance(ev.get("e"), str) or ev["e"] not in EVENTS:
        return None                                           # (a list / dict "e" would be unhashable: a 400, never a 500)
    e = ev["e"]
    out = {"e": e}
    if e == "scroll":
        d = ev.get("d")
        if isinstance(d, bool) or not isinstance(d, (int, float)) or d not in SCROLL:
            return None
        out["d"] = int(d)
    elif e in ("section", "cta", "video_play"):
        i = ev.get("id")
        if not (isinstance(i, str) and _ID.match(i)):
            return None
        out["id"] = i
    elif e in ("scan_start", "scan_result"):
        dom = clean_domain(ev.get("domain"))
        if not dom:
            return None
        out["domain"] = dom
        if e == "scan_result":
            out["ok"] = ev.get("ok") is True
    elif e == "faq_open":
        q = ev.get("q")
        if not (isinstance(q, str) and _SLUG.match(q)):
            return None
        out["q"] = q
    return out


def _append(lines):
    f = events_path()
    limit = float(os.environ.get("OTTO_EVENTS_MAX_MB") or 512) * 1024 * 1024
    try:
        if f.exists() and f.stat().st_size > limit:
            if not _full_warned[0]:
                _full_warned[0] = True
                print(f"otto_track: {f} is over {limit / 1048576:.0f} MB — not writing (otto_track.py prune)", file=sys.stderr)
            return False
    except OSError:
        pass
    f.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in lines).encode()
    with _lock:
        fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, data)                               # one write per request: lines never interleave
        finally:
            os.close(fd)
    return True


def ingest(body, ip, headers, now=None):
    """Validate + store one beacon request. headers: a mapping with .get() (DNT, Sec-GPC, User-Agent, X-Country).
    Returns (http status, response object or None)."""
    if not body or len(body) > MAX_BODY:
        return 413 if body else 400, {"error": "empty or too large"}
    try:
        req = json.loads(body)
    except Exception:
        return 400, {"error": "bad json"}
    if not isinstance(req, dict):
        return 400, {"error": "object expected"}
    evs = req.get("ev")
    if isinstance(req.get("e"), str):                         # a single event without the batch wrapper
        evs = [{k: v for k, v in req.items() if k not in ("p", "s", "r", "u", "dv", "anon")}]
    if not isinstance(evs, list) or not evs or len(evs) > MAX_EVENTS:
        return 400, {"error": f"1-{MAX_EVENTS} events expected"}
    path = req.get("p") if isinstance(req.get("p"), str) else ""
    path = path.split("?")[0].split("#")[0]
    if not _PATH.match(path):
        return 400, {"error": "bad path"}
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    anon = (str(headers.get("DNT") or "").strip() == "1" or str(headers.get("Sec-GPC") or "").strip() == "1"
            or (isinstance(req.get("anon"), (int, str)) and req.get("anon") in (1, True, "1")))
    if anon:                                                  # Do Not Track / GPC: one anonymous page view, nothing else
        if not any(isinstance(x, dict) and x.get("e") == "view" for x in evs):
            return 204, None
        if not allow("anon:" + hashlib.sha256(f"{daily_salt()}|{rate_key(ip)}".encode()).hexdigest()[:16], 1):
            return 429, {"error": "slow down"}
        _append([{"ts": ts, "e": "view", "p": path, "anon": 1}])
        return 204, None
    cleaned = [c for c in (clean_event(x) for x in evs) if c]
    if not cleaned:
        return 400, {"error": "no allowed events"}
    ua = str(headers.get("User-Agent") or "")[:400]
    v = visitor_id(ip, ua)
    if not allow(hashlib.sha256(f"{daily_salt()}|{rate_key(ip)}".encode()).hexdigest()[:16], len(cleaned)):
        return 429, {"error": "slow down"}
    sid = req.get("s") if isinstance(req.get("s"), str) and _SID.match(req.get("s")) else None
    ref = clean_host(req.get("r"))
    utm = clean_utm(req.get("u"))
    dv = req.get("dv") if isinstance(req.get("dv"), str) and req.get("dv") in DEVICES else None
    cc = str(headers.get("X-Country") or headers.get("CF-IPCountry") or "").strip().upper()
    cc = cc if re.fullmatch(r"[A-Z]{2}", cc) and cc not in ("XX", "ZZ", "T1", "A1", "A2") else None
    lines = []
    for c in cleaned:
        row = {"ts": ts, "e": c.pop("e"), "v": v}
        if sid:
            row["s"] = sid
        row["p"] = path
        if row["e"] == "view":
            row.update({k: val for k, val in (("r", ref), ("u", utm), ("dv", dv), ("cc", cc)) if val})
        row.update(c)
        lines.append(row)
    if not _append(lines):
        return 507, {"error": "analytics storage full"}
    capi_forward(lines, ip, headers, ua=ua, cc=cc)          # Meta CAPI: only with meta-capi.json AND the consent cookie
    return 204, None


# ---------------- Meta Conversions API (consented events only; see the module docstring) ----------------

CAPI_FILE = "meta-capi.json"
CAPI_GRAPH = "https://graph.facebook.com/" + os.environ.get("GRAPH_API_VERSION", "v25.0")
CAPI_TIMEOUT = 6
CAPI_MAX_THREADS = 4                       # a slow Graph API never piles up threads: past this, events are dropped
CONSENT_COOKIE, CONSENT_GRANTED, FBC_COOKIE = "otto_consent", "v1.granted", "otto_fbc"
_PIXEL = re.compile(r"^\d{5,20}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_|.-]{20,600}$")
_TEST_CODE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_FBC = re.compile(r"^fb\.1\.\d{10,13}\.[A-Za-z0-9_-]{10,500}$")
_ORIGIN = re.compile(r"^https?://[a-z0-9.-]{1,253}(?::\d{1,5})?$")
CAPI_CTA_KINDS = ("get_started", "start_trial", "trial", "signup", "sign_up")      # landing CTA kinds → InitiateCheckout
# server-confirmed moments (capi_track only; not accepted from the public beacon) → Meta standard events
CAPI_SERVER_EVENTS = {"signup": ("CompleteRegistration", {"content_name": "sign-up", "status": "completed"}),
                      "trial_start": ("StartTrial", {"content_name": "trial"})}
CAPI_METHODS = ("google", "email", "apple", "microsoft")
_capi_cache = {"key": None, "cfg": None}
_capi_threads = []
_capi_lock = threading.Lock()


def _secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or Path(__file__).resolve().parent.parent.parent / "otto-secrets")


def capi_config():
    """The Conversions API settings, or None (no file, an empty / malformed pixel_id or token = forwarding is off).
    Re-read only when the file changes."""
    f = _secrets_dir() / CAPI_FILE
    try:
        st = f.stat()
    except OSError:
        return None
    key = (str(f), st.st_mtime_ns, st.st_size)
    if _capi_cache["key"] == key:
        return _capi_cache["cfg"]
    cfg = None
    try:
        raw = json.loads(f.read_text())
        pid, tok = str(raw.get("pixel_id") or "").strip(), str(raw.get("access_token") or "").strip()
        if _PIXEL.match(pid) and _TOKEN.match(tok):
            code = str(raw.get("test_event_code") or "").strip()
            site = str(raw.get("site_url") or "").strip().rstrip("/").lower()
            cfg = {"pixel_id": pid, "access_token": tok, "test_event_code": code if _TEST_CODE.match(code) else "",
                   "site_url": site if _ORIGIN.match(site) else ""}
        elif pid or tok:
            print(f"otto_track: {f.name} has no valid pixel_id / access_token — Meta forwarding is off", file=sys.stderr)
    except Exception as e:                                     # noqa: BLE001 — a broken file means off, never a crash
        print(f"otto_track: {f.name} unreadable ({type(e).__name__}) — Meta forwarding is off", file=sys.stderr)
    _capi_cache.update(key=key, cfg=cfg)
    return cfg


def _cookies(headers):
    out = {}
    for part in str(headers.get("Cookie") or "")[:4096].split(";"):
        k, sep, v = part.strip().partition("=")
        if sep and k and k not in out:
            out[k] = v.strip().strip('"')
    return out


def capi_consent(headers):
    """(granted, fbc or None) from the request's first-party cookies. Anything but exactly v1.granted is no."""
    c = _cookies(headers)
    granted = c.get(CONSENT_COOKIE) == CONSENT_GRANTED
    fbc = c.get(FBC_COOKIE) if granted else None
    return granted, (fbc if fbc and _FBC.match(fbc) else None)


def _sha(s):
    return hashlib.sha256(str(s).strip().lower().encode()).hexdigest()


def capi_event(row, ip, ua, fbc, cc, source_url, now=None):
    """One stored row → one CAPI event (dict), or None when the row is not an event Meta gets."""
    e = row.get("e")
    if e == "scan_start":
        name, custom = "ViewContent", {"content_name": "website scan", "content_category": "scan"}
    elif e == "scan_result" and row.get("ok") is True:
        name, custom = "Lead", {"content_name": "scan result", "content_category": "scan"}
    elif e == "cta" and str(row.get("id") or "").split("@")[0] in CAPI_CTA_KINDS:
        name, custom = "InitiateCheckout", {"content_name": str(row["id"]).split("@")[0].replace("_", " "), "content_category": "checkout"}
    elif e in CAPI_SERVER_EVENTS and row.get("_server"):
        name, custom = CAPI_SERVER_EVENTS[e][0], dict(CAPI_SERVER_EVENTS[e][1])
        if row.get("method") in CAPI_METHODS:
            custom["content_category"] = row["method"]
        if isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool) and 0 <= row["value"] <= 100000 \
                and re.fullmatch(r"[A-Z]{3}", str(row.get("currency") or "")):
            custom.update(value=round(float(row["value"]), 2), currency=row["currency"])
    else:
        return None
    ident = row.get("domain") or row.get("id") or row.get("ref") or ""
    user = {"client_user_agent": ua}
    try:
        user["client_ip_address"] = str(ipaddress.ip_address(str(ip).strip()))
    except ValueError:
        pass
    if fbc:
        user["fbc"] = fbc
    if row.get("v"):
        user["external_id"] = [_sha(row["v"])]
    if cc:
        user["country"] = [_sha(cc)]
    return {"event_name": name, "event_time": int(now or time.time()), "action_source": "website",
            "event_id": hashlib.sha256(f"{row.get('s') or row.get('v')}|{name}|{ident}".encode()).hexdigest()[:32],
            "event_source_url": source_url, "user_data": user, "custom_data": custom}


def capi_forward(rows, ip, headers, ua=None, cc=None, wait=False):
    """Stored rows → Meta, when (and only when) forwarding is configured and the visitor consented. Returns the number of
    events handed to the sender (0 = nothing sent). The HTTP call runs in a background thread unless wait=True."""
    cfg = capi_config()
    if not cfg:
        return 0
    granted, fbc = capi_consent(headers)
    if not granted:
        return 0
    ua = str(ua if ua is not None else headers.get("User-Agent") or "")[:400]
    origin = str(headers.get("Origin") or "").strip().rstrip("/").lower()
    base = origin if _ORIGIN.match(origin) else cfg["site_url"]
    if not ua or not base:
        return 0                                               # a website event without a user agent or a URL is rejected by Meta
    evs = [x for x in (capi_event(r, ip, ua, fbc, cc, base + str(r.get("p") or "/")) for r in rows) if x]
    if not evs:
        return 0
    if wait:
        _capi_send(cfg, evs)
        return len(evs)
    with _capi_lock:
        _capi_threads[:] = [t for t in _capi_threads if t.is_alive()]
        if len(_capi_threads) >= CAPI_MAX_THREADS:
            print("otto_track: Meta CAPI busy — events dropped", file=sys.stderr)
            return 0
        t = threading.Thread(target=_capi_send, args=(cfg, evs), daemon=True, name="otto-capi")
        _capi_threads.append(t)
    t.start()
    return len(evs)


def capi_track(event, ip, headers, path="/", ref=None, method=None, value=None, currency=None, wait=False):
    """A server-confirmed moment → Meta, under the same rules as the beacon (meta-capi.json + the consent cookie on this
    request, never with DNT / GPC). event: "signup" (CompleteRegistration) or "trial_start" (StartTrial). ref: the
    account or order id, used only (hashed) for Meta's de-duplication, never sent as such. Returns the events handed on."""
    if event not in CAPI_SERVER_EVENTS:
        return 0
    if str(headers.get("DNT") or "").strip() == "1" or str(headers.get("Sec-GPC") or "").strip() == "1":
        return 0
    path = str(path or "/").split("?")[0].split("#")[0]
    path = path if _PATH.match(path) else "/"
    ua = str(headers.get("User-Agent") or "")[:400]
    cc = str(headers.get("X-Country") or headers.get("CF-IPCountry") or "").strip().upper()
    cc = cc if re.fullmatch(r"[A-Z]{2}", cc) and cc not in ("XX", "ZZ", "T1", "A1", "A2") else None
    row = {"e": event, "_server": True, "v": visitor_id(ip, ua), "p": path,
           "ref": hashlib.sha256(str(ref).encode()).hexdigest()[:24] if ref else None,
           "method": method, "value": value, "currency": str(currency or "").upper() or None}
    return capi_forward([row], ip, headers, ua=ua, cc=cc, wait=wait)


def capi_join(timeout=10):
    """Wait for the background sends (tests, CLI)."""
    for t in list(_capi_threads):
        t.join(timeout)


def _capi_send(cfg, evs):
    import urllib.error, urllib.parse, urllib.request
    form = {"data": json.dumps(evs, separators=(",", ":")), "access_token": cfg["access_token"]}
    if cfg.get("test_event_code"):
        form["test_event_code"] = cfg["test_event_code"]
    req = urllib.request.Request(f"{CAPI_GRAPH}/{cfg['pixel_id']}/events", data=urllib.parse.urlencode(form).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=CAPI_TIMEOUT) as r:
            body = r.read(4096)
        return json.loads(body or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = (json.loads(e.read(4096) or b"{}").get("error") or {}).get("message") or ""
        except Exception:                                      # noqa: BLE001
            msg = ""
        print(f"otto_track: Meta CAPI HTTP {e.code} {msg.replace(cfg['access_token'], '…')[:160]}", file=sys.stderr)
    except Exception as e:                                     # noqa: BLE001 — never let a Meta outage touch the beacon
        print(f"otto_track: Meta CAPI {type(e).__name__}", file=sys.stderr)
    return None


# ---------------- reading (used by otto_admin) ----------------

def _line_date(line):
    """'2026-09-29' from a stored line without parsing it (every line starts with {"ts":"…)."""
    return line[7:17] if line.startswith(b'{"ts":"') else None


def _seek_date(f, size, day):
    """Byte offset of the first line whose date is >= day (the file is append-only, so it is sorted by ts)."""
    lo, hi = 0, size
    while hi - lo > 4096:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()                                          # skip the partial line
        pos = f.tell()
        line = f.readline()
        d = _line_date(line)
        if not line or d is None:
            hi = mid
        elif d.decode() < day:
            lo = pos
        else:
            hi = mid
    return lo


READ_MAX_MB = 48             # the most read_events() parses for the console (the newest part of the file)


def read_events(since_day=None, path=None, max_bytes=None):
    """Stored events from since_day (YYYY-MM-DD, inclusive) to the end. Binary-searches the start in a large file,
    so reading the last 90 days of a multi-GB log costs only those 90 days. max_bytes (default READ_MAX_MB) bounds
    what is parsed: past it only the newest max_bytes are read (a flood of beacons must not run the console out of
    memory); read_events.truncated tells the caller."""
    f = Path(path) if path else events_path()
    read_events.truncated = False
    if not f.exists():
        return []
    cap = int(max_bytes if max_bytes is not None else READ_MAX_MB * 1048576)
    out = []
    with open(f, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        start = _seek_date(fh, size, since_day) if since_day and size > 65536 else 0     # always a line start
        if cap and size - start > cap:
            fh.seek(size - cap)
            fh.readline()                                     # skip the partial line
            read_events.truncated = True
        else:
            fh.seek(start)
        for line in fh:
            if since_day:
                d = _line_date(line)
                if d is None or d.decode() < since_day:
                    continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if isinstance(e, dict) and isinstance(e.get("ts"), str):     # a hand-edited or torn line is skipped, not fatal
                out.append(e)
    return out


def prune(days):
    """Drop events older than `days` days (atomic rewrite)."""
    f = events_path()
    if not f.exists():
        return 0
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    kept, dropped = [], 0
    with _lock:
        for line in f.read_bytes().splitlines(keepends=True):
            d = _line_date(line)
            if d is not None and d.decode() < cut:
                dropped += 1
            else:
                kept.append(line)
        ap._atomic_write(f, b"".join(kept).decode("utf-8", "replace"))
    return dropped


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["tail"]:
        n = int(a[1]) if len(a) > 1 else 20
        for e in read_events()[-n:]:
            print(json.dumps(e, ensure_ascii=False))
    elif a[:1] == ["prune"]:
        print(f"dropped {prune(int(a[a.index('--days') + 1]) if '--days' in a else 400)} events")
    elif a[:1] in (["capi-status"], ["capi-test"]):
        cfg = capi_config()
        if not cfg:
            sys.exit(f"Meta forwarding is OFF: no valid {_secrets_dir() / CAPI_FILE} (pixel_id + access_token)")
        print(f"Meta forwarding is ON for consented visitors · pixel …{cfg['pixel_id'][-4:]} · "
              f"test code {'set' if cfg['test_event_code'] else 'not set'} · site {cfg['site_url'] or '(from the Origin header)'}")
        if a[0] == "capi-test":
            if not cfg["test_event_code"]:
                sys.exit("add \"test_event_code\" (Events Manager → Test events) to send a test event")
            ev = capi_event({"e": "scan_start", "v": secrets.token_hex(8), "s": "capitest", "p": "/", "domain": "example.com"},
                            "127.0.0.1", "otto_track capi-test", None, None, (cfg["site_url"] or "https://example.com") + "/")
            print(json.dumps(_capi_send(cfg, [ev])))
    else:
        print(__doc__)
