"""A stand-in for the Higgsfield Cloud API, for tests/test_imagegen.py (not a test module itself).

FakeHiggsfield runs a 127.0.0.1 HTTP server that speaks enough of api.higgsfield.ai for otto_imagegen, in the shapes verified
against the real API on 3 Oct 2026:
  POST /<model>                      Authorization: Key KEY_ID:KEY_SECRET (+ Idempotency-Key) → {"status": "queued",
                                     "request_id", "status_url", "cancel_url"}; the same key with the same body → the same
                                     request (with a different body → 422), FastAPI's {"detail"} error shape
  GET  /requests/<id>/status         walks the request's script (default queued → in_progress → completed); completed has
                                     {"images": [{"url": <base>/cdn/<id>.png}]}, failed has "error"
  POST /requests/<id>/cancel         202 while queued (the script then ends "canceled"), else 400
  GET  /cdn/<id>.png                 the image bytes (no key needed: the test checks none is sent)
  POST /estimate/<model>             {"type": "estimate", "credits", "usd"} (usd = self.price)
  POST /files/generate-upload-url    {"public_url", "upload_url", "content_type", "upload_headers"}; PUT /put/<id> stores the
                                     bytes, GET /uploads/<id> serves them
Every request is logged (method, path, headers with lower-case names, parsed JSON body) so a test can assert the exact
request. Knobs: `replies` (queued answers for the next generation submissions: ("error", status, detail[, headers]) or
("concurrency",) — the real API's 400 when the account's concurrent requests are used up), `estimate_replies` (the same for
estimates), `status_errors` (queued HTTP errors for the next status polls), `script` (the status sequence new requests get),
`image` (the bytes the CDN serves), `status_url_origin` (an origin to put in status_url / cancel_url instead of the base:
the client must not send its key there). Stdlib only; no network beyond 127.0.0.1.
"""
import http.server, itertools, json, re, struct, threading, uuid, zlib

KEY_ID = "fake-hf-key-id-otto-tests"
KEY_SECRET = "fake-hf-secret-otto-tests-do-not-use-0123456789"
AUTH = f"Key {KEY_ID}:{KEY_SECRET}"


def tiny_png(w=8, h=8, rgb=(36, 71, 240)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeHiggsfield:
    def __init__(self):
        self.log, self.replies, self.estimate_replies, self.status_errors = [], [], [], []
        self.requests, self.idem, self.uploads = {}, {}, {}
        self.script = ["queued", "in_progress", "completed"]
        self.image = tiny_png()
        self.price = "0.076"
        self.status_url_origin = None
        self.lock = threading.Lock()
        self.n = itertools.count(1)
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None, ctype="application/json", headers=None):
                body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Correlation-ID", "corr-%04d" % next(me.n))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _record(self, raw):
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    body = None
                entry = {"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                         "body": body, "size": len(raw)}
                with me.lock:
                    me.log.append(entry)
                return entry

            def _authed(self):
                if self.headers.get("Authorization") != AUTH:
                    self._send(401, {"detail": "Invalid credentials"})
                    return False
                return True

            def _origin(self):
                return me.status_url_origin or me.base

            def do_GET(self):
                self._record(b"")
                path = self.path.split("?")[0]
                m = re.fullmatch(r"/cdn/([0-9a-f-]+)\.png", path)
                if m:
                    return self._send(200, raw=me.image, ctype="image/png")
                m = re.fullmatch(r"/uploads/([0-9a-f]+)", path)
                if m:
                    data = me.uploads.get(m.group(1))
                    return self._send(200, raw=data["data"], ctype=data["ctype"]) if data else self._send(404, {"detail": "Not found"})
                m = re.fullmatch(r"/requests/([0-9a-f-]+)/status", path)
                if m:
                    if not self._authed():
                        return
                    with me.lock:
                        err = me.status_errors.pop(0) if me.status_errors else None
                    if err:
                        return self._send(err[0], {"detail": err[1] if len(err) > 1 else "boom"})
                    with me.lock:
                        r = me.requests.get(m.group(1))
                        if not r:
                            return self._send(404, {"detail": "Not found"})
                        st = r["script"][min(r["i"], len(r["script"]) - 1)]
                        r["i"] += 1
                    out = {"status": st, "request_id": r["id"], "status_url": f"{self._origin()}/requests/{r['id']}/status",
                           "cancel_url": f"{self._origin()}/requests/{r['id']}/cancel"}
                    if st == "completed":
                        out["images"] = [{"url": f"{me.base}/cdn/{r['id']}.png"}]
                    if st == "failed":
                        out["error"] = "Generation failed"
                    return self._send(200, out)
                return self._send(404, {"detail": "Not found"})

            def do_PUT(self):
                raw = self._body()
                self._record(raw)
                m = re.fullmatch(r"/put/([0-9a-f]+)", self.path.split("?")[0])
                if not m or m.group(1) not in me.uploads:
                    return self._send(403, raw=b"<Error>AccessDenied</Error>", ctype="application/xml")
                me.uploads[m.group(1)].update(data=raw, put_headers={k.lower(): v for k, v in self.headers.items()})
                return self._send(200, raw=b"")

            def do_POST(self):
                raw = self._body()
                entry = self._record(raw)
                body = entry["body"]
                path = self.path.split("?")[0]
                if not self._authed():
                    return
                m = re.fullmatch(r"/requests/([0-9a-f-]+)/cancel", path)
                if m:
                    with me.lock:
                        r = me.requests.get(m.group(1))
                        if not r:
                            return self._send(404, {"detail": "Not found"})
                        cur = r["script"][min(max(r["i"] - 1, 0), len(r["script"]) - 1)]
                        if cur != "queued":
                            return self._send(400, {"detail": "Request is already being processed"})
                        r["script"], r["i"] = ["canceled"], 0
                    return self._send(202, raw=b"")
                if path == "/files/generate-upload-url":
                    ct = (body or {}).get("content_type")
                    if ct not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif", "audio/wav", "video/mp4"):
                        return self._send(422, {"detail": [{"loc": ["body", "content_type"], "msg": "unsupported"}]})
                    uid = uuid.uuid4().hex
                    me.uploads[uid] = {"ctype": ct, "data": None}
                    return self._send(200, {"public_url": f"{me.base}/uploads/{uid}", "upload_url": f"{me.base}/put/{uid}?X-Amz-Signature=fake",
                                            "content_type": ct, "upload_headers": {"Content-Type": ct, "x-amz-tagging": "retention=temporary"}})
                if path.startswith("/estimate/"):
                    with me.lock:
                        r = me.estimate_replies.pop(0) if me.estimate_replies else None
                    if r and r[0] == "error":
                        return self._send(r[1], {"detail": r[2]}, headers=r[3] if len(r) > 3 else None)
                    if r and r[0] == "description":
                        return self._send(200, {"type": "description", "pricing_description": "per token"})
                    return self._send(200, {"type": "estimate", "credits": "1.211", "usd": me.price,
                                            "discount": {"percentage": "15.00", "credits": "0.2", "usd": "0.01"}})
                if not isinstance(body, dict) or not str(body.get("prompt") or "").strip():
                    return self._send(422, {"detail": [{"loc": ["body", "prompt"], "msg": "field required"}]})
                with me.lock:
                    r = me.replies.pop(0) if me.replies else None
                if r and r[0] == "error":
                    return self._send(r[1], {"detail": r[2]}, headers=r[3] if len(r) > 3 else None)
                if r and r[0] == "concurrency":
                    return self._send(400, {"detail": "Maximum number of concurrent requests (4) has been reached"})
                key = self.headers.get("Idempotency-Key")
                with me.lock:
                    if key and key in me.idem:
                        rid, old = me.idem[key]
                        if old != body:
                            return self._send(422, {"detail": "Idempotency-Key was already used with different request parameters"})
                    else:
                        rid = str(uuid.uuid4())
                        me.requests[rid] = {"id": rid, "model": path.strip("/"), "body": body, "script": list(me.script), "i": 0}
                        if key:
                            me.idem[key] = (rid, body)
                return self._send(200, {"status": "queued", "request_id": rid,
                                        "status_url": f"{self._origin()}/requests/{rid}/status",
                                        "cancel_url": f"{self._origin()}/requests/{rid}/cancel"})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def submissions(self):
        return [x for x in self.log if x["method"] == "POST" and not x["path"].startswith(("/estimate/", "/files/", "/requests/"))]

    def calls(self, prefix, method=None):
        return [x for x in self.log if x["path"].startswith(prefix) and (method is None or x["method"] == method)]

    def reset(self):
        with self.lock:
            self.log.clear(); self.replies.clear(); self.estimate_replies.clear(); self.status_errors.clear()
            self.requests.clear(); self.idem.clear(); self.uploads.clear()
        self.script = ["queued", "in_progress", "completed"]
        self.image = tiny_png()
        self.price = "0.076"
        self.status_url_origin = None

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
