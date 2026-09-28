#!/usr/bin/env python3
"""Otto dashboard action API. Localhost-only; nginx proxies /otto-api/ behind mm-check auth.

GET  /otto-api/data                 -> data.json (live)
POST /otto-api/action  {"kind":"post","id":"hg-001","status":"approved"}
POST /otto-api/action  {"kind":"rec","id":"rec-002","status":"done"}

All writes go through the same load/save as ap.py (fallback block re-synced),
and are appended to actions.log with approved_via=dashboard.
"""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ap  # same directory — reuse load/save/sync_fallback

HERE = Path(__file__).parent
LOG = HERE / "actions.log"
PORT = 8161

POST_STATUSES = ap.STATUSES
REC_STATUSES = {"proposed", "approved", "dismissed", "done"}


def apply_action(kind, item_id, status):
    d = ap.load()
    if kind == "post":
        if status not in POST_STATUSES:
            raise ValueError(f"bad post status {status}")
        item = next((p for p in d["posts"] if p["id"] == item_id), None)
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep journal quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/otto-api/data":
            self._send(200, ap.load())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/otto-api/action":
            return self._send(404, {"error": "not found"})
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            req = json.loads(self.rfile.read(n) or b"{}")
            data = apply_action(req.get("kind"), req.get("id"), req.get("status"))
            self._send(200, {"ok": True, "data": data})
        except KeyError as e:
            self._send(404, {"error": f"unknown id {e}"})
        except (ValueError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": str(e)})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
