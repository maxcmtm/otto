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
    return 204, None


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
    else:
        print(__doc__)
