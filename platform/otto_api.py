#!/usr/bin/env python3
"""Otto dashboard action API. Localhost-only; nginx proxies /otto-api/ behind mm-check auth.

GET  /otto-api/data                 -> data.json (live)
POST /otto-api/action  {"kind":"post","id":"hg-001","status":"approved"}
POST /otto-api/action  {"kind":"rec","id":"rec-002","status":"done"}
POST /otto-api/decide  {"id":"hg-001","decision":"approve|skip|later","via":"dashboard"}   (taste log)
GET  /otto-api/peek?url=<site>      -> brand DNA peek (authenticated, for the dashboard)
GET  /otto-peek?url=<site>          -> same, PUBLIC — nginx: `location /otto-peek { proxy_pass http://127.0.0.1:8161; }`
                                       (no auth; SSRF-guarded on every hop, rate-limited 1 req / 4 s per client IP,
                                        at most 4 peeks at once, 20 s total deadline, cached 1 h)

Hardening:
  * Client IP = X-Real-IP only (nginx: `proxy_set_header X-Real-IP $remote_addr;` — never X-Forwarded-For,
    which the client controls). Without the header (direct local call) the socket address is used.
  * CORS: Access-Control-Allow-Origin only on /otto-peek (the public landing). /otto-api/* sends none.
  * POST: Content-Type must be application/json and Origin (or Referer) must be one of OTTO_ALLOWED_ORIGINS
    (default https://dash.monyflow.work). A proxied request (X-Real-IP set) with neither header is refused.
  * Status changes follow ap.POST_TRANSITIONS / ap.REC_TRANSITIONS: published / publishing / failed posts
    cannot be put back to approved from the dashboard.

All writes go through ap.transaction() (lock + atomic write; fallback block re-synced)
and are appended to actions.log with approved_via=dashboard.
"""
import json, os, threading, time, urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ap  # same directory — reuse load/transaction
import otto_scan

HERE = Path(__file__).parent
LOG = ap.DATA.parent / "actions.log"
PORT = 8161

POST_STATUSES = ap.STATUSES
REC_STATUSES = ap.REC_STATUSES
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in
                   (os.environ.get("OTTO_ALLOWED_ORIGINS") or "https://dash.monyflow.work").split(",") if o.strip()}

_peek_lock = threading.Lock()
_peek_sem = threading.BoundedSemaphore(4)
_peek_cache = {}      # url -> (ts, result)
_peek_last = {}       # ip -> ts
PEEK_TTL, PEEK_MIN_GAP, PEEK_MAX_CACHE, PEEK_MAX_IPS, PEEK_DEADLINE = 3600, 4.0, 300, 5000, 20.0


def _log(line):
    with LOG.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")


def apply_action(kind, item_id, status):
    if kind == "post":
        if status not in POST_STATUSES:
            raise ValueError(f"bad post status {status}")
    elif kind == "rec":
        if status not in REC_STATUSES:
            raise ValueError(f"bad rec status {status}")
    else:
        raise ValueError(f"bad kind {kind}")
    with ap.transaction() as d:
        item = ap.post(d, item_id) if kind == "post" else ap.rec(d, item_id)
        if item is None:
            raise KeyError(item_id)
        ap.check_transition(kind, item.get("status"), status)
        item["status"] = status
        item["approved_via"] = "dashboard"
        item["decided_at"] = ap.now_iso()
    _log(f"dashboard {kind} {item_id} -> {status}")
    return ap.load()


def apply_decision(item_id, decision, via):
    via = via if via in ("dashboard", "telegram", "auto") else "dashboard"
    with ap.transaction() as d:
        ap.decide(d, item_id, decision, via)            # enforces the transition table
    _log(f"{via} decide {item_id} -> {decision}")
    return ap.load()


def _prune_last(now):
    """Forget IPs whose gap has passed (the map only needs the last PEEK_MIN_GAP seconds); hard cap on size."""
    if len(_peek_last) > 1000:
        for ip in [ip for ip, ts in _peek_last.items() if now - ts > PEEK_MIN_GAP]:
            _peek_last.pop(ip, None)
    while len(_peek_last) > PEEK_MAX_IPS:
        _peek_last.pop(next(iter(_peek_last)))


def peek(url, ip):
    url = otto_scan.normalize_url(url)
    if len(url) > 300 or not otto_scan.safe_host(url):
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
    if not _peek_sem.acquire(timeout=2):
        return 503, {"error": "busy — try again in a few seconds"}
    try:
        result = otto_scan.peek(url, deadline=time.time() + PEEK_DEADLINE)
    finally:
        _peek_sem.release()
    if "error" in result:
        return 502, {"error": "could not read the site", "detail": result["error"][:160]}
    with _peek_lock:
        for k in [k for k, (ts, _) in _peek_cache.items() if now - ts >= PEEK_TTL]:
            _peek_cache.pop(k, None)
        while len(_peek_cache) >= PEEK_MAX_CACHE:
            _peek_cache.pop(next(iter(_peek_cache)))
        _peek_cache[url] = (now, result)
    return 200, result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep journal quiet
        pass

    def _public(self):
        return urllib.parse.urlsplit(self.path).path.rstrip("/") == "/otto-peek"

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self._public():
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        # no browser headers at all: only a direct local call (not through nginx) is accepted
        return not self.headers.get("X-Real-IP") and self.client_address[0] in ("127.0.0.1", "::1")

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

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        path = u.path.rstrip("/")
        if path == "/otto-api/data":
            self._send(200, ap.load())
        elif path in ("/otto-peek", "/otto-api/peek"):
            q = urllib.parse.parse_qs(u.query)
            url = (q.get("url") or [""])[0].strip()
            if not url:
                return self._send(400, {"error": "url required"})
            try:
                code, obj = peek(url, self._client_ip())
                self._send(code, obj)
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path not in ("/otto-api/action", "/otto-api/decide"):
            return self._send(404, {"error": "not found"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._send(415, {"error": "Content-Type must be application/json"})
        if not self._origin_ok():
            return self._send(403, {"error": "cross-origin request refused"})
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            req = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("JSON object expected")
            if path == "/otto-api/decide":
                data = apply_decision(req.get("id"), req.get("decision"), req.get("via"))
            else:
                data = apply_action(req.get("kind"), req.get("id"), req.get("status"))
            self._send(200, {"ok": True, "data": data})
        except KeyError as e:
            self._send(404, {"error": f"unknown id {e}"})
        except (ValueError, AssertionError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": str(e)})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
