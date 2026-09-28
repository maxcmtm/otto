#!/usr/bin/env python3
"""Otto dashboard action API. Localhost-only; nginx proxies /otto-api/ behind mm-check auth.

GET  /otto-api/data                 -> data.json (live)
POST /otto-api/action  {"kind":"post","id":"hg-001","status":"approved"}
POST /otto-api/action  {"kind":"rec","id":"rec-002","status":"done"}
POST /otto-api/decide  {"id":"hg-001","decision":"approve|skip|later","via":"dashboard"}   (taste log)
GET  /otto-api/peek?url=<site>      -> brand DNA peek (authenticated, for the dashboard)
GET  /otto-peek?url=<site>          -> same, PUBLIC — nginx: `location /otto-peek { proxy_pass http://127.0.0.1:8161; }`
                                       (no auth; SSRF-guarded, rate-limited 1 req / 4 s per IP, cached 1 h)

All writes go through the same load/save as ap.py (fallback block re-synced),
and are appended to actions.log with approved_via=dashboard.
"""
import json, threading, time, urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ap  # same directory — reuse load/save/sync_fallback
import otto_scan

HERE = Path(__file__).parent
LOG = HERE / "actions.log"
PORT = 8161

POST_STATUSES = ap.STATUSES
REC_STATUSES = ap.REC_STATUSES

_peek_lock = threading.Lock()
_peek_cache = {}      # url -> (ts, result)
_peek_last = {}       # ip -> ts
PEEK_TTL, PEEK_MIN_GAP, PEEK_MAX_CACHE = 3600, 4.0, 300


def apply_action(kind, item_id, status):
    d = ap.load()
    if kind == "post":
        if status not in POST_STATUSES:
            raise ValueError(f"bad post status {status}")
        item = ap.post(d, item_id)
    elif kind == "rec":
        if status not in REC_STATUSES:
            raise ValueError(f"bad rec status {status}")
        item = next((r for r in d.get("recommendations", []) if r["id"] == item_id), None)
    else:
        raise ValueError(f"bad kind {kind}")
    if item is None:
        raise KeyError(item_id)
    item["status"] = status
    item["approved_via"] = "dashboard"
    ap.save(d)
    with LOG.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} dashboard {kind} {item_id} -> {status}\n")
    return ap.load()


def apply_decision(item_id, decision, via):
    d = ap.load()
    ap.decide(d, item_id, decision, via or "dashboard")
    ap.save(d)
    with LOG.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {via or 'dashboard'} decide {item_id} -> {decision}\n")
    return ap.load()


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
    result = otto_scan.peek(url)
    if "error" in result:
        return 502, {"error": "could not read the site", "detail": result["error"][:160]}
    with _peek_lock:
        if len(_peek_cache) >= PEEK_MAX_CACHE:
            _peek_cache.pop(next(iter(_peek_cache)))
        _peek_cache[url] = (now, result)
    return 200, result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep journal quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self):
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        path = self.path.rstrip("/")
        if path not in ("/otto-api/action", "/otto-api/decide"):
            return self._send(404, {"error": "not found"})
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            req = json.loads(self.rfile.read(n) or b"{}")
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
