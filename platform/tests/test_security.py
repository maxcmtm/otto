#!/usr/bin/env python3
"""Launch security / robustness regression tests for the server side: the SSRF guard and the scanner (otto_scan), the API's
routes (otto_api: admin gate, bodies, shapes, errors, peek cache + rate limit, slow clients, concurrency), analytics privacy
(otto_track), the Whop webhook (otto_whop), the console snapshot on bad data (otto_admin), compliance failing closed
(otto_compliance), Telegram owner checks (otto_telegram), asset paths (otto_paths) and secrets hygiene.
Stdlib unittest; the only network is 127.0.0.1 servers started here; nothing outside a throwaway workspace.

  cd platform && python3 tests/test_security.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites

Under discover, earlier suites have imported the modules with their own OTTO_* paths, so setUpModule pins every
module-level path this suite touches to its own workspace and tearDownModule puts them back (as test_admin does).
"""
import contextlib, gzip, hashlib, http.server, io, json, os, re, shutil, socket, socketserver, subprocess, sys
import tempfile, threading, time, unittest, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-security-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_LEADS": str(TMP / "leads.json")}
CLEAR = ("WHOP_API_KEY", "WHOP_WEBHOOK_SECRET", "WHOP_COMPANY_ID", "OTTO_ADMIN_USERS", "OTTO_EVENTS_MAX_MB",
         "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "OTTO_OWNER_USER_ID", "OTTO_SINGLE_TENANT", "OTTO_FALLBACK",
         "OTTO_PROXY_KEY")
ORIGIN = "https://dash.monyflow.work"
SECRET = "ws_security_test_secret_do_not_use"
J = {"Content-Type": "application/json", "Origin": ORIGIN}


def seed():
    posts = [{"id": f"al-{i:03d}", "brand": "alpha", "pillar": "A", "platform": "fb", "hook": f"Hook {i}", "status": "pending_approval",
              "slot": "2030-01-01T09:00"} for i in range(1, 31)]
    posts += [{"id": "al-900", "brand": "alpha", "platform": "fb", "hook": "live", "status": "published", "slot": "2026-01-01T09:00"},
              {"id": "al-901", "brand": "alpha", "platform": "fb", "hook": "sending", "status": "publishing", "slot": "2026-01-01T09:00"},
              {"id": "al-902", "brand": "alpha", "platform": "fb", "hook": "broke", "status": "failed", "slot": "2026-01-01T09:00"}]
    return {"brands": [{"id": "alpha", "name": "Alpha Dental", "url": "alpha-dental.example", "lang": "EN", "tz": "UTC",
                        "status": "active", "pillars": ["A"], "compliance": ""},
                       {"id": "beta", "name": "Beta Cafe", "url": "beta-cafe.example", "lang": "EN", "tz": "UTC",
                        "status": "active", "pillars": ["A"], "compliance": ""}],
            "posts": posts, "connections": [], "campaigns": [],
            "recommendations": [{"id": "rec-001", "priority": "P1", "title": "t", "why": "w", "impact": "i", "cta": "c",
                                 "status": "proposed"},
                                {"id": "rec-002", "priority": "P1", "title": "t2", "why": "w", "impact": "i", "cta": "c",
                                 "status": "done"}]}


def reset_workspace():
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    shutil.rmtree(TMP / "brands", ignore_errors=True)
    shutil.rmtree(TMP / "secrets", ignore_errors=True)
    (TMP / "brands").mkdir()
    (TMP / "secrets").mkdir()
    (TMP / "data.json").write_text(json.dumps(seed(), ensure_ascii=False, indent=2))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    otto_track._buckets.clear()
    otto_track._global[:] = [float(otto_track.GLOBAL_PER_MIN), time.time()]
    otto_track._salt.update(day=None, salt=None)
    otto_api._snap_cache.clear()
    otto_api._peek_cache.clear()
    otto_api._peek_last.clear()
    otto_onboard._rl_last.clear()
    otto_onboard._public_creates.clear()


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


_SAVED = {}
# State files that live in the repo's platform/ dir. Read when discover LOADS this module (before any suite runs), so the
# check at the end catches any suite that wrote into the real workspace (a module imported with the default paths).
REPO_STATE = {n: (PLATFORM / n).read_bytes() if (PLATFORM / n).exists() else None
              for n in (".watch-state.json", "data.json", ".telegram-state.json", "actions.log", "publish.log")}


def setUpModule():
    _SAVED["repo_data"] = (PLATFORM / "data.json").exists()
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_api, otto_scan, otto_track, otto_whop, otto_admin, otto_onboard, otto_compliance, otto_telegram
    global otto_publish, otto_paths, otto_strategy, otto_plan
    import ap, otto_api, otto_scan, otto_track, otto_whop, otto_admin, otto_onboard, otto_compliance   # noqa: E401
    import otto_telegram, otto_publish, otto_paths, otto_strategy, otto_plan                          # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG, otto_scan.BRANDS, otto_publish.SECRETS, otto_publish.LOG,
                       otto_telegram.SECRETS, otto_telegram.STATE, otto_strategy.BRANDS, otto_plan.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_api.LOG, otto_publish.LOG = TMP / "actions.log", TMP / "publish.log"
    otto_scan.BRANDS = otto_strategy.BRANDS = otto_plan.BRANDS = TMP / "brands"
    otto_publish.SECRETS = otto_telegram.SECRETS = TMP / "secrets"
    otto_telegram.STATE = TMP / ".telegram-state.json"
    reset_workspace()


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG, otto_scan.BRANDS, otto_publish.SECRETS, otto_publish.LOG,
     otto_telegram.SECRETS, otto_telegram.STATE, otto_strategy.BRANDS, otto_plan.BRANDS) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class _Server:
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def req(self, path, method="GET", body=None, headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=15) as x:
                raw = x.read()
                return x.status, dict(x.headers), (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, dict(e.headers), json.loads(raw) if raw else None
            except ValueError:
                return e.code, dict(e.headers), None

    def raw(self, data, wait=5.0):
        """Send raw bytes on a socket, return what the server answers (b'' when it just closes)."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=wait) as s:
            s.sendall(data)
            out = b""
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    out += chunk
            except socket.timeout:
                out += b"<timeout>"
            return out


# ============================================================================================
# a hostile web: 127.0.0.1 servers the scanner may reach only inside local_ok()
# ============================================================================================

class _Web(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def handle(self):
        try:
            super().handle()
        except OSError:                                         # the scanner hangs up at its size limit: expected
            pass

    def do_GET(self):
        _Web.seen.append((self.path, self.headers.get("Host")))
        port = self.server.server_address[1]
        redirects = {"/to-meta": "http://169.254.169.254/latest/meta-data/", "/to-port": f"http://127.0.0.1:22/",
                     "/to-file": "file:///etc/passwd", "/loop": "/loop", "/to-v6": "http://[::1]/",
                     "/to-6to4": "http://[2002:7f00:1::]/", "/to-ok": f"http://127.0.0.1:{port}/ok",
                     "/to-cred": f"http://user:pw@127.0.0.1:{port}/ok"}
        if self.path in redirects:
            self.send_response(302); self.send_header("Location", redirects[self.path]); self.send_header("Content-Length", "0")
            self.end_headers(); return
        if self.path == "/big":
            body = b"a" * 3_000_000
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if self.path == "/bomb":
            body = gzip.compress(b"\0" * 20_000_000)
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = b"<html><title>ok</title></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


class _Trickle(socketserver.BaseRequestHandler):
    """Answers one byte every 0.2 s forever: in the status line/headers (/headers) or in the body (anything else)."""

    def handle(self):
        try:
            first = self.request.recv(65536).split(b"\r\n", 1)[0]
            if b" /headers " in first:
                self.request.sendall(b"HTTP/1.1 200 OK\r\n")
            else:
                self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 1000000\r\n\r\n")
            for _ in range(600):
                self.request.sendall(b"a")
                time.sleep(0.2)
        except OSError:
            pass


class _TServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def setUpWeb():
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Web)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    trickle = _TServer(("127.0.0.1", 0), _Trickle)
    threading.Thread(target=trickle.serve_forever, daemon=True).start()
    return web, trickle


@contextlib.contextmanager
def local_ok(*ports):
    """Let the SSRF guard through for 127.0.0.1 on the given ports only (the test servers); everything else is as in production."""
    orig_ok, orig_ports = otto_scan.ip_ok, otto_scan.ALLOWED_PORTS
    otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig_ok(ip)
    otto_scan.ALLOWED_PORTS = orig_ports | set(ports)
    try:
        yield
    finally:
        otto_scan.ip_ok, otto_scan.ALLOWED_PORTS = orig_ok, orig_ports


# ============================================================================================
# SSRF guard
# ============================================================================================

class ScanGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.trickle = setUpWeb()
        cls.wport, cls.tport = cls.web.server_address[1], cls.trickle.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.web, cls.trickle):
            s.shutdown(); s.server_close()

    def test_special_addresses_are_never_public(self):
        for ip in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "255.255.255.255",
                   "224.0.0.1", "192.0.0.8", "198.18.0.1", "192.88.99.1", "::1", "::", "fe80::1", "fc00::1", "fd00:ec2::254",
                   "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::127.0.0.1", "64:ff9b::7f00:1", "64:ff9b:1::a00:1",
                   "2002:7f00:1::", "2002:a9fe:a9fe::", "2001::1", "2001:db8::1", "fec0::1", "ff02::1"):
            self.assertFalse(otto_scan.ip_ok(ip), ip)
        for ip in ("1.1.1.1", "8.8.8.8", "2606:4700:4700::1111", "2a00:1450:4001:80b::200e"):
            self.assertTrue(otto_scan.ip_ok(ip), ip)

    def test_url_rules(self):
        for bad in ("ftp://example.com/", "file:///etc/passwd", "gopher://example.com/", "http://example.com:8080/", "http://example.com:0/",
                    "http://user:pw@example.com/", "http://localhost/", "http://intranet.local/", "http://db.internal/",
                    "http://router.lan/", "http://x.home.arpa/", "http:///nohost", "http://example.com:99999/", "https://['a.com']/",
                    'https://exa"mple.com/', "https://a..com/", "https://<svg>.com/"):
            with self.assertRaises(otto_scan.Blocked, msg=bad):
                otto_scan.check_url(bad)
        self.assertEqual(otto_scan.check_url("https://WWW.Grüns.de./x")[1:], ("www.xn--grns-1ra.de", 443))

    def test_bracketed_hosts_never_escape_as_value_errors(self):
        # regression (CI on Python 3.12, the server's version): urlsplit raises ValueError for "[not-an-ip]" hosts there (and
        # for unbalanced brackets everywhere) — check_url let it escape instead of Blocked, and host_of() crashed a whole
        # scan on one odd link of the client's site
        for bad in ("https://[a.com]/", "https://[x/", "http://[::1/x"):
            with self.assertRaises(otto_scan.Blocked, msg=bad):
                otto_scan.check_url(bad)
        self.assertNotIn(otto_scan.host_of("https://[x/about"), ("x", "[x"))
        links = [("https://[a.com]/about", "About", "a", {}), ("https://[x/team", "Team", "a", {}),
                 ("https://shop.example/about-us", "About us", "a", {})]
        self.assertEqual(otto_scan.pick_internal("https://shop.example/", links, 5), ["https://shop.example/about-us"])

    def test_every_resolved_address_must_be_public(self):
        real = socket.getaddrinfo
        answers = {"mixed.example": ["93.184.216.34", "10.0.0.5"], "v6private.example": ["2606:4700::1", "fd00::1"]}

        def fake(host, port, *a, **kw):
            if host in answers:
                return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers[host]]
            return real(host, port, *a, **kw)
        socket.getaddrinfo = fake
        try:
            for host in answers:
                with self.assertRaises(otto_scan.Blocked, msg=host):
                    otto_scan.resolve_public(host, 443)
                self.assertFalse(otto_scan.safe_host(f"https://{host}/"))
        finally:
            socket.getaddrinfo = real

    def test_connection_is_pinned_to_the_checked_address(self):
        """DNS rebinding: the name is resolved once per hop and the socket goes to that address; a resolver that answers
        a private address next time cannot redirect the request that was already checked."""
        real, real_conn = socket.getaddrinfo, socket.create_connection
        lookups, connects = [], []
        answer = ["127.0.0.1"]

        def fake(host, port, *a, **kw):
            if host == "pinned.example":
                lookups.append(host)
                ip = answer[0]
                answer[0] = "10.0.0.1"                          # the rebinding resolver: private from now on
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
            return real(host, port, *a, **kw)

        def conn(addr, *a, **kw):
            connects.append(addr[0])
            return real_conn(addr, *a, **kw)
        socket.getaddrinfo, socket.create_connection = fake, conn
        _Web.seen.clear()
        try:
            with local_ok(self.wport):
                final, body, _, _ = otto_scan.guarded_get(f"http://pinned.example:{self.wport}/ok", timeout=5)
                self.assertIn(b"<title>ok</title>", body)
                with self.assertRaises(otto_scan.Blocked):
                    otto_scan.guarded_get(f"http://pinned.example:{self.wport}/ok", timeout=5)
        finally:
            socket.getaddrinfo, socket.create_connection = real, real_conn
        self.assertEqual(lookups, ["pinned.example", "pinned.example"])
        self.assertEqual(connects, ["127.0.0.1"], "one connection, to the address that was checked")
        self.assertEqual(_Web.seen, [("/ok", f"pinned.example:{self.wport}")], "the real host name still goes in Host")

    def test_every_redirect_hop_is_checked(self):
        base = f"http://127.0.0.1:{self.wport}"
        with local_ok(self.wport):
            self.assertIn(b"ok", otto_scan.guarded_get(base + "/to-ok", timeout=5)[1])
            for path, why in (("/to-meta", "non-public address 169.254.169.254"), ("/to-port", "port 22"), ("/to-file", "scheme file"),
                              ("/to-v6", "non-public address ::1"), ("/to-6to4", "non-public"), ("/to-cred", "credentials"),
                              ("/loop", "too many redirects")):
                with self.assertRaises(otto_scan.Blocked, msg=path) as cm:
                    otto_scan.guarded_get(base + path, timeout=5)
                self.assertIn(why, str(cm.exception), path)
            self.assertTrue(otto_scan.fetch(base + "/to-meta")[2].startswith("error:"), "fetch never raises")

    def test_a_trickling_server_is_cut_at_the_deadline(self):
        base = f"http://127.0.0.1:{self.tport}"
        with local_ok(self.tport):
            for path in ("/body", "/headers"):
                t = time.time()
                with self.assertRaises(otto_scan.Blocked, msg=path):
                    otto_scan.guarded_get(base + path, timeout=5, deadline=time.time() + 1.0)
                self.assertLess(time.time() - t, 3.0, path)
            orig = otto_scan.MAX_FETCH_SECONDS
            otto_scan.MAX_FETCH_SECONDS = 1.0                  # no deadline given: the hard cap still ends it
            try:
                t = time.time()
                with self.assertRaises(otto_scan.Blocked):
                    otto_scan.guarded_get(base + "/headers", timeout=5)
                self.assertLess(time.time() - t, 3.0)
            finally:
                otto_scan.MAX_FETCH_SECONDS = orig

    def test_size_limit_and_no_decompression(self):
        base = f"http://127.0.0.1:{self.wport}"
        with local_ok(self.wport):
            self.assertEqual(len(otto_scan.guarded_get(base + "/big", limit=100_000, timeout=5)[1]), 100_000)
            raw = otto_scan.guarded_get(base + "/bomb", timeout=5)[1]
        self.assertLess(len(raw), 100_000, "a gzip body is kept as the compressed bytes, never inflated")
        self.assertEqual(raw[:2], b"\x1f\x8b")


# ============================================================================================
# what a hostile site can write: scan fields + the saved logo
# ============================================================================================

HOSTILE = """<html lang="&lt;img src=x onerror=alert(1)&gt;"><head><title>Acme &lt;script&gt;</title>
<meta property="og:image" content="javascript:alert(1)">
<link rel="apple-touch-icon" href="javascript:alert(2)">
<link rel="alternate" hreflang="&quot;&gt;&lt;svg onload=alert(3)&gt;" href="/x"><link rel="alternate" hreflang="de-AT" href="/de">
<style>body{font-family:"<script>alert(1)</script>",serif} h1{font-family:Inter} p{font-family:'x;}body{background:url(//evil.example)'}</style>
</head><body><a href="https://instagram.com/evil<script>">ig</a><a href="https://facebook.com/acme&quot;onmouseover=alert(1)">fb</a>
<h1>Hello</h1></body></html>"""


class ScanOutputTest(unittest.TestCase):
    def scan_of(self, html):
        orig = otto_scan.fetch
        otto_scan.fetch = lambda u, limit=0, timeout=0, deadline=None: (u, html, "text/html") if u.rstrip("/").endswith("acme.example") \
            else (u, "", "error:x")
        try:
            return otto_scan.scan("https://acme.example/", pages=2)
        finally:
            otto_scan.fetch = orig

    def test_page_controlled_fields_are_constrained(self):
        s = self.scan_of(HOSTILE)
        self.assertEqual(s["languages"], ["de"], "only language codes")
        self.assertIsNone(s["visual"]["logo"], "a javascript: icon is not a logo")
        self.assertIsNone(s["identity"]["og_image"])
        self.assertIn("Inter", s["visual"]["fonts"])
        self.assertTrue(all(re.fullmatch(r"[\w .-]{1,40}", f) for f in s["visual"]["fonts"]), "font names only, never CSS or markup")
        self.assertEqual(s["socials"], {"instagram": "https://instagram.com/evil", "facebook": "https://facebook.com/acme"})
        self.assertTrue(all(re.fullmatch(r"#[0-9A-F]{6}", p["hex"]) for p in s["visual"]["palette"] + s["visual"]["neutrals"]))

    def test_web_url(self):
        for bad in ("javascript:alert(1)", "data:image/svg+xml,<svg onload=alert(1)>", "//evil.example/x.png", "ftp://x/y.png",
                    'https://x.example/a"onerror="alert(1).png', "https://x.example/<svg>.png", "", None):
            self.assertIsNone(otto_scan.web_url(bad), bad)
        self.assertEqual(otto_scan.web_url("https://cdn.example/my logo.svg"), "https://cdn.example/my%20logo.svg")


def make_png(w, h, pixel, ftype=0, ctype=6, claim=None):
    """A real PNG whose rows use filter `ftype` (0 none … 4 Paeth), so the decoder's unfiltering is exercised."""
    import struct, zlib
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    rows, prev = [], bytes(w * ch)
    for y in range(h):
        raw = bytes(pixel(x, y)[k] for x in range(w) for k in range(ch))
        enc = bytearray()
        for i, v in enumerate(raw):
            a = raw[i - ch] if i >= ch else 0
            b, c = prev[i], (prev[i - ch] if i >= ch else 0)
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            pred = [0, a, b, (a + b) >> 1, a if pa <= pb and pa <= pc else b if pb <= pc else c][ftype]
            enc.append((v - pred) & 255)
        rows.append(bytes([ftype]) + bytes(enc))
        prev = raw
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    w, h = claim or (w, h)                                      # claim: what the header says (a lie about the size)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class LogoToneAndQuotesTest(unittest.TestCase):
    def test_logo_tone(self):
        white = lambda x, y: (250, 250, 250, 255) if (x + y) % 3 else (0, 0, 0, 0)
        navy = lambda x, y: (20 + x % 7, 30, 90 + y % 5, 255)
        for f in range(5):
            self.assertEqual(otto_scan.logo_tone(make_png(40, 12, white, f)), "light", f"filter {f}")
            self.assertEqual(otto_scan.logo_tone(make_png(40, 12, navy, f)), "dark", f"filter {f}")
        self.assertEqual(otto_scan.logo_tone(make_png(10, 4, lambda x, y: (240,), 0, ctype=0)), "light")
        self.assertIsNone(otto_scan.logo_tone(make_png(10, 4, lambda x, y: (255, 255, 255, 0))), "all transparent")
        self.assertEqual(otto_scan.logo_tone(b'<svg><path fill="#FFFFFF" d="M0"/><text style="fill:white">A</text></svg>'), "light")
        self.assertEqual(otto_scan.logo_tone(b'<svg viewBox="0 0 9 9"><path d="M0 0h9v9z"/></svg>'), "dark", "no fill = SVG black")
        big = make_png(4, 4, lambda x, y: (255, 255, 255, 255), claim=(20000, 20000))
        self.assertIsNone(otto_scan.logo_tone(big), "too many pixels to read in a request: no guess")
        self.assertIsNone(otto_scan.logo_tone(b"\x89PNG\r\n\x1a\n" + b"\0" * 40))
        self.assertIsNone(otto_scan.logo_tone(b"GIF89a"))

    def test_page_chrome_is_neither_a_quote_nor_proof(self):
        for junk in ("4.8 stars • 100K+ from 100,000 reviews • 1M+ 1,000,000+ members",
                     "Testimonials featured in videos may include individuals who have received compensation, free product.",
                     "Grüns Daily Nutrition ⭐️ Exclüsives is live!", "⭐️ Save up to $80, get limited flavors, and VIP access ✨ NEW!"):
            self.assertIsNone(otto_scan.clean_quote(junk), junk)
        self.assertEqual(otto_scan.clean_quote("4 months ago Katzenleckerlis Tom Berger Reviewer 5/5 Unser Katze hat das Produkt gut angenommen."),
                         "Unser Katze hat das Produkt gut angenommen.")
        self.assertEqual(otto_scan.clean_quote('"The best Earl Grey I have had in years, and the tin is lovely." ★★★★★'),
                         '"The best Earl Grey I have had in years, and the tin is lovely."')
        text = ("Third Party Testing Every lot of our products undergoes rigorous testing to ensure quality and safety standards across "
                "hundreds of batches and more words that run on without a full stop at all because it is card text "
                "78/day Free Shipping Today Pause Or Cancel Any Time 30-Day Money-Back Guarantee One Time Purchase $66. "
                "We accept all refund requests with no hassle. Certified organic since 2014. 30-day money-back guarantee.")
        trust = otto_scan.trust_from(text)
        self.assertIn("30-day money-back guarantee.", trust)
        self.assertIn("Certified organic since 2014.", trust)
        self.assertFalse(any("hassle" in t for t in trust), "'ssl' is not 'hassle'")
        self.assertFalse(any("Pause Or Cancel" in t or "Free Shipping Today" in t for t in trust))
        self.assertTrue(all(t.endswith((".", "…", "!", "?")) for t in trust), trust)


class SaveLogoTest(unittest.TestCase):
    SVG_OK = (b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
              b'viewBox="0 0 10 10"><defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="10" height="10"/>'
              b'<use xlink:href="#g"/><image href="data:image/png;base64,iVBORw0KGgo="/></svg>')
    BAD = [b'<svg><script>alert(1)</script></svg>', b'<svg onload="alert(1)"/>', b'<svg><g ONLOAD =x/></svg>',
           b'<svg><a href="javascript:alert(1)"><rect/></a></svg>', b'<svg><a xlink:href="&#106;avascript:alert(1)">x</a></svg>',
           b'<svg><a href=javascript:alert(1)>x</a></svg>', b'<svg><foreignObject><iframe src="x"></iframe></foreignObject></svg>',
           b'<svg><animate attributeName="href" values="javascript:alert(1)"/></svg>',
           b'<svg><set attributeName="xlink:href" to="javascript:alert(1)"/></svg>',
           b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
           b'<!DOCTYPE svg [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><svg>&b;</svg>',
           b'<svg><use href="https://evil.example/x.svg#a"/></svg>', b'<svg><image href="data:image/svg+xml;base64,PHN2Zz4="/></svg>',
           b'<svg><style>@import url(https://evil.example/x.css);</style></svg>', b'<html><body>not an svg</body></html>',
           b'<svg><embed src="x"/></svg>', b'\xff\xfe<\x00s\x00v\x00g\x00>\x00']

    def setUp(self):
        self.out = TMP / "brands" / "logo-test"
        shutil.rmtree(self.out, ignore_errors=True)
        self.out.mkdir(parents=True)
        self._get = otto_scan.guarded_get

    def tearDown(self):
        otto_scan.guarded_get = self._get

    def save(self, raw, url="https://acme.example/img/logo.svg", og=None):
        otto_scan.guarded_get = lambda u, limit=0, timeout=0, deadline=None, headers=None: (u, raw, "image/svg+xml", "utf-8")
        return otto_scan.save_logo({"visual": {"logo": url}, "identity": {"og_image": og}}, self.out)

    def test_scriptable_or_external_svg_is_never_saved(self):
        for raw in self.BAD:
            self.assertIsNone(self.save(raw), raw[:60])
            self.assertEqual(list(self.out.iterdir()), [], raw[:60])

    def test_clean_files_are_saved_in_place(self):
        f = self.save(self.SVG_OK)
        self.assertEqual(f, self.out / "logo.svg")
        self.assertIsNone(self.save(self.SVG_OK), "never overwrites an existing logo")
        shutil.rmtree(self.out); self.out.mkdir()
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 100
        self.assertEqual(self.save(png, "https://acme.example/logo.png"), self.out / "logo.png")
        shutil.rmtree(self.out); self.out.mkdir()
        self.assertIsNone(self.save(b"GIF89a....", "https://acme.example/logo.png"), "the bytes must be a PNG")
        self.assertIsNone(self.save(b"\x89PNG\r\n\x1a\n" + b"\0" * (otto_scan.LOGO_MAX + 10), "https://acme.example/logo.png"),
                          "a file cut at the size limit is not kept")
        self.assertIsNone(self.save(self.SVG_OK, "https://acme.example/og.svg", og="https://acme.example/og.svg"), "og:image fallback")
        self.assertIsNone(self.save(self.SVG_OK, "javascript:alert(1)//logo.svg"))
        self.assertIsNone(self.save(self.SVG_OK, "https://acme.example/logo.svg.php"))
        self.assertEqual(list(self.out.iterdir()), [])


# ============================================================================================
# the API
# ============================================================================================

class ApiTest(_Server, unittest.TestCase):
    def setUp(self):
        reset_workspace()
        os.environ.pop("OTTO_ADMIN_USERS", None)

    def tearDown(self):
        os.environ.pop("OTTO_ADMIN_USERS", None)

    def action(self, body, headers=None):
        return self.req("/otto-api/action", "POST", body, dict(J, **(headers or {})))

    def test_500s_never_leak_internals(self):
        boom = RuntimeError("/home/ubuntu/.openclaw/otto-secrets/whop.json: EAAG_SECRET_TOKEN")
        orig = (otto_admin.snapshot, otto_api.apply_action, otto_api.peek, otto_onboard.http_create)

        def raise_(*a, **kw):
            raise boom
        otto_admin.snapshot = otto_api.apply_action = otto_api.peek = otto_onboard.http_create = raise_
        try:
            outs = [self.req("/otto-api/admin/snapshot"), self.action({"kind": "post", "id": "al-001", "status": "approved"}),
                    self.req("/otto-peek?url=example.com"), self.req("/otto-api/onboard", "POST", {"site": "x.com"}, J)]
        finally:
            otto_admin.snapshot, otto_api.apply_action, otto_api.peek, otto_onboard.http_create = orig
        for code, _, body in outs:
            self.assertEqual((code, body), (500, {"error": "internal error"}))
        log = (TMP / "api-errors.log").read_text()
        self.assertIn("RuntimeError", log, "the detail goes to the error log")

    def test_bodies_and_shapes(self):
        long = {"kind": "post", "id": "al-001", "status": "approved", "note": "x" * 5000}
        self.assertEqual(self.action(long)[0], 413)
        self.assertEqual(self.req("/otto-api/action", "POST", b"", J)[0], 400)
        self.assertEqual(self.req("/otto-api/action", "POST", b"[1,2]", J)[0], 400)
        self.assertEqual(self.req("/otto-api/action", "POST", b"[" * 2000 + b"]" * 2000, J)[0], 400, "deep nesting is a 400")
        for bad in ({"kind": "post", "id": "al-001", "status": ["approved"]}, {"kind": "post", "id": ["al-001"], "status": "approved"},
                    {"kind": {"a": 1}, "id": "al-001", "status": "approved"}, {"kind": "post", "id": "", "status": "approved"},
                    {"kind": "post", "id": "al-001", "status": "hacked"}, {"kind": "user", "id": "al-001", "status": "approved"}):
            self.assertEqual(self.action(bad)[0], 400, bad)
        self.assertEqual(self.req("/otto-api/decide", "POST", {"id": "al-001", "decision": {"x": 1}}, J)[0], 400)
        self.assertEqual(self.action({"kind": "post", "id": "nope-1", "status": "approved"})[0], 404)
        self.assertEqual(ap.post(ap.load(), "al-001")["status"], "pending_approval", "nothing refused changed anything")
        # a negative or bogus Content-Length is refused at once, never read until the client hangs up
        for length in (b"-5", b"abc"):
            out = self.raw(b"POST /otto-api/action HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nOrigin: " + ORIGIN.encode()
                           + b"\r\nContent-Length: " + length + b"\r\n\r\n")
            self.assertTrue(out.startswith(b"HTTP/1.0 400"), out[:80])

    def test_a_slow_client_is_dropped(self):
        orig = otto_api.Handler.timeout
        otto_api.Handler.timeout = 0.5
        try:
            t = time.time()
            out = self.raw(b"POST /otto-api/action HTTP/1.1\r\nHost: x\r\nContent-Length: 50\r\n", wait=5)
            self.assertLess(time.time() - t, 3)
            self.assertNotIn(b"<timeout>", out, "the server closed the connection itself")
        finally:
            otto_api.Handler.timeout = orig

    def test_transition_rules_hold_through_the_api(self):
        for pid, st in (("al-900", "approved"), ("al-900", "draft"), ("al-901", "approved"), ("al-901", "skipped"), ("al-902", "approved")):
            self.assertEqual(self.action({"kind": "post", "id": pid, "status": st})[0], 400, (pid, st))
        self.assertEqual(self.req("/otto-api/decide", "POST", {"id": "al-900", "decision": "approve"}, J)[0], 400)
        self.assertEqual(self.action({"kind": "rec", "id": "rec-002", "status": "proposed"})[0], 400)
        d = ap.load()
        self.assertEqual([ap.post(d, p)["status"] for p in ("al-900", "al-901", "al-902")], ["published", "publishing", "failed"])

    def test_concurrent_decisions_all_land(self):
        ids = [f"al-{i:03d}" for i in range(1, 31)]
        codes = []

        def go(pid):
            codes.append(self.req("/otto-api/decide", "POST", {"id": pid, "decision": "approve" if int(pid[-2:]) % 2 else "skip"}, J)[0])
        threads = [threading.Thread(target=go, args=(p,)) for p in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        d = ap.load()
        self.assertEqual(codes, [200] * 30)
        self.assertEqual({ap.post(d, p)["status"] for p in ids[0::2]}, {"approved"})
        self.assertEqual({ap.post(d, p)["status"] for p in ids[1::2]}, {"skipped"})
        self.assertEqual(len(d["taste_log"]), 30, "no lost update under the lock")

    def test_peek_rate_limit_and_cache_come_before_dns(self):
        looked, fetched = [], []
        orig = (otto_scan.host_status, otto_scan.peek)
        otto_scan.host_status = lambda u: looked.append(u) or "ok"
        otto_scan.peek = lambda u, deadline=None: fetched.append(u) or {"url": u + "/", "title": "T " + u, "palette": []}
        try:
            ip = {"X-Real-IP": "198.51.100.9"}
            code, h, out = self.req("/otto-peek?url=first.example", headers=ip)
            self.assertEqual((code, out["title"], h.get("Access-Control-Allow-Origin")), (200, "T https://first.example", "*"))
            self.assertEqual(self.req("/otto-peek?url=second.example", headers=ip)[0], 429)
            self.assertEqual(self.req("/otto-peek?url=second.example", headers=dict(ip, **{"X-Forwarded-For": "1.2.3.4"}))[0], 429,
                             "X-Forwarded-For is not the client")
            code, _, out = self.req("/otto-peek?url=first.example", headers=ip)
            self.assertEqual((code, out["cached"], out["title"]), (200, True, "T https://first.example"))
            self.assertEqual(self.req("/otto-peek?url=http://localhost/", headers={"X-Real-IP": "198.51.100.10"})[0], 400)
            self.assertEqual(self.req("/otto-peek?url=http://example.com:6379/", headers={"X-Real-IP": "198.51.100.11"})[0], 400)
            self.assertEqual(otto_api._cached_peek("https://first.example")["title"], "T https://first.example")
            self.assertIsNone(otto_api._cached_peek("https://second.example"), "the cache only holds what this server fetched")
        finally:
            otto_scan.host_status, otto_scan.peek = orig
        self.assertEqual(looked, ["https://first.example"], "a rate-limited, cached or malformed request never reaches the resolver")
        self.assertEqual(fetched, ["https://first.example"])
        self.assertNotIn("Access-Control-Allow-Origin", self.req("/otto-api/data")[1], "CORS only on the public peek")

    def test_a_domain_that_does_not_exist_is_a_404_not_a_refusal(self):
        orig = (otto_scan.host_status, otto_scan.peek)
        otto_scan.host_status = lambda u: "not_found" if "nosuch" in u else "blocked"
        otto_scan.peek = lambda u, deadline=None: self.fail("never fetched")
        try:
            self.assertEqual(self.req("/otto-peek?url=nosuch-domain.example", headers={"X-Real-IP": "192.0.2.90"})[:3:2],
                             (404, {"error": "site not found"}))
            self.assertEqual(self.req("/otto-peek?url=internal.example", headers={"X-Real-IP": "192.0.2.91"})[:3:2],
                             (400, {"error": "unsupported or unsafe url"}))
        finally:
            otto_scan.host_status, otto_scan.peek = orig

    def test_an_ipv6_client_is_limited_by_its_64(self):
        orig = (otto_scan.host_status, otto_scan.peek)
        otto_scan.host_status = lambda u: "ok"
        otto_scan.peek = lambda u, deadline=None: {"url": u, "title": "x"}
        try:
            self.assertEqual(self.req("/otto-peek?url=v6-one.example", headers={"X-Real-IP": "2001:db8:aa:bb::1"})[0], 200)
            self.assertEqual(self.req("/otto-peek?url=v6-two.example", headers={"X-Real-IP": "2001:db8:aa:bb:ffff::9"})[0], 429)
            self.assertEqual(self.req("/otto-peek?url=v6-two.example", headers={"X-Real-IP": "2001:db8:aa:cc::1"})[0], 200)
        finally:
            otto_scan.host_status, otto_scan.peek = orig
        self.assertEqual(otto_track.rate_key("::ffff:192.0.2.1"), "192.0.2.1")

    def test_a_failed_peek_says_why_in_fixed_words(self):
        orig = (otto_scan.host_status, otto_scan.peek)
        otto_scan.host_status = lambda u: "ok"
        try:
            for err, want in (("error:non-public address 10.20.30.40", "redirects somewhere"), ("error:dns lookup failed", "does not resolve"),
                              ("error:deadline reached", "too long"), ("error:HTTP Error 403: Forbidden", "HTTP 403"),
                              ("error:[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: /etc/ssl/x", "certificate"),
                              ("error:Traceback /usr/lib/python3/x.py line 3", "could not be read")):
                otto_api._peek_last.clear()
                otto_scan.peek = lambda u, deadline=None, e=err: {"url": u, "error": e}
                code, _, out = self.req("/otto-peek?url=broken.example", headers={"X-Real-IP": "192.0.2.77"})
                self.assertEqual(code, 502)
                self.assertIn(want, out["detail"], err)
                self.assertNotRegex(out["detail"], r"10\.20|/etc|/usr|Traceback")
            self.assertIsNone(otto_api._cached_peek("https://broken.example"), "a failure is never cached")
        finally:
            otto_scan.host_status, otto_scan.peek = orig

    def test_a_failed_fallback_sync_does_not_fail_a_saved_write(self):
        orig = ap.HTML
        ap.HTML = TMP / "no-such-dir" / "index.html"
        (TMP / "no-such-dir").mkdir()
        (TMP / "no-such-dir" / "index.html").write_text('<script id="fallback-data" type="application/json">{}</script>')
        os.chmod(TMP / "no-such-dir", 0o500)                   # the html exists but its directory is read-only
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code, _, out = self.action({"kind": "post", "id": "al-004", "status": "approved"})
        finally:
            os.chmod(TMP / "no-such-dir", 0o700)
            shutil.rmtree(TMP / "no-such-dir")
            ap.HTML = orig
        self.assertEqual((code, ap.post(ap.load(), "al-004")["status"]), (200, "approved"))

    def test_actions_log_failure_does_not_drop_the_answer(self):
        otto_api.LOG = TMP / "no-such-dir" / "actions.log"
        try:
            code, _, out = self.action({"kind": "post", "id": "al-003", "status": "approved"})
        finally:
            otto_api.LOG = TMP / "actions.log"
        self.assertEqual((code, out["ok"]), (200, True), "the change happened: the client must hear so")
        self.assertEqual(ap.post(ap.load(), "al-003")["status"], "approved")


# ============================================================================================
# tenants: a client sees and changes only their own brands
# ============================================================================================

def canned_scan(host, title):
    return {"url": f"https://{host}", "final_url": f"https://{host}/", "scanned_at": "2026-09-29T10:00:00Z", "pages": [f"https://{host}/"],
            "identity": {"title": title, "description": "", "site_name": "", "og_title": "", "og_image": None},
            "industry": "E-commerce & retail", "industry_candidates": [], "languages": ["en"], "platform": "Shopify",
            "visual": {"palette": [], "neutrals": [], "logo": None, "fonts": [], "theme_color": None}, "socials": {},
            "contact": {"emails": [], "phones": []}, "commerce": {"currency": "EUR", "prices": [], "promos": []},
            "trust": [], "quotes": [], "headings": [], "nav": [], "text_sample": ""}


class TenantTest(_Server, unittest.TestCase):
    ANNA = {"X-Real-IP": "203.0.113.20", "X-Otto-User": "Anna@Alpha-Dental.example"}
    BEN = {"X-Real-IP": "203.0.113.21", "X-Otto-User": "ben@beta-cafe.example"}

    def setUp(self):
        reset_workspace()
        for k in ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_FALLBACK"):
            os.environ.pop(k, None)
        with ap.transaction(sync=False) as d:
            ap.brand(d, "alpha")["members"] = ["anna@alpha-dental.example"]
            ap.brand(d, "beta")["members"] = ["@beta-cafe.example"]
            ap.brand(d, "beta")["paused"] = {"at": "2026-09-29T10:00:00Z", "by": "max", "note": "client is late paying"}
            d["posts"].append({"id": "be-001", "brand": "beta", "platform": "ig", "hook": "Beta secret launch", "status": "pending_approval",
                               "slot": "2030-01-01T09:00"})
            d["recommendations"] += [
                {"id": "rec-010", "priority": "P1", "title": "Alpha: post more reels", "brand": "alpha", "status": "proposed"},
                {"id": "rec-011", "priority": "P1", "title": "Move Otto from €197 one-time to monthly plans", "status": "proposed"},
                {"id": "rec-012", "priority": "P0", "title": "Pause cp-9 by hand", "brand": "alpha", "source": "otto_admin", "status": "proposed"},
                {"id": "rec-013", "priority": "P1", "title": "Upsell alpha", "brand": "alpha", "audience": "owner", "status": "proposed"},
                {"id": "rec-014", "priority": "P1", "title": "Beta: menu photos", "brand": "beta", "status": "proposed"}]
            d["campaigns"] = [{"id": "cp-1", "brand": "alpha", "status": "draft"}, {"id": "cp-2", "brand": "beta", "status": "live"}]
            d["metrics"] = {"alpha": {"reach": 1}, "beta": {"reach": 2}}
            d["growth"] = {"alpha": {"current": "2026-09"}, "beta": {"current": "2026-09"}}
            d["ads"] = {"beta": {"daily": {}}}
            d["competitors"] = {"beta": {"items": []}}
            d["brands"].append({"id": "shop-beta", "name": "Alpha Dental", "url": "shop-beta.example", "status": "active"})
            d["connections"] = [{"id": "meta-alpha", "service": "Instagram + Facebook", "brand": "Alpha Dental", "status": "connected"},
                                {"id": "meta-shop-beta", "service": "Instagram + Facebook", "brand": "Alpha Dental", "status": "connected"},
                                {"id": "meta-beta", "service": "Instagram + Facebook", "brand": "Beta Cafe", "status": "not_connected"},
                                {"id": "linkedin", "service": "LinkedIn", "brand": "Shared", "status": "planned"}]
            d["edit_requests"] = [{"post": "al-001", "note": "shorter"}, {"post": "be-001", "note": "beta only"}]
            d["taste_log"] = [{"post": "al-001", "brand": "alpha", "decision": "approve"}, {"post": "be-001", "brand": "beta", "decision": "skip"}]
            d["fleet"] = [{"id": "quill", "feed": ["Drafted 11 posts across 2 brands"]}]
            d["controls"] = {"publishing_paused": {"by": "max", "note": "incident at beta"}}

    def data(self, headers):
        return self.req("/otto-api/data", headers=headers)

    def test_a_client_sees_only_their_brands(self):
        code, _, d = self.data(self.ANNA)
        self.assertEqual(code, 200)
        blob = json.dumps(d, ensure_ascii=False)
        self.assertEqual([b["id"] for b in d["brands"]], ["alpha"])
        self.assertEqual({p["brand"] for p in d["posts"]}, {"alpha"})
        self.assertEqual([r["id"] for r in d["recommendations"]], ["rec-010"], "owner-internal recommendations never reach a client")
        self.assertEqual((list(d["metrics"]), list(d["growth"]), d["ads"], d["competitors"]), (["alpha"], ["alpha"], {}, {}))
        self.assertEqual([c["id"] for c in d["connections"]], ["meta-alpha"])
        self.assertEqual(d["edit_requests"], [{"post": "al-001", "note": "shorter"}])
        self.assertEqual([c["id"] for c in d["campaigns"]], ["cp-1"])
        for leak in ("beta", "Beta", "monthly plans", "Pause cp-9", "Upsell", "Drafted 11", "incident", "members", "seq"):
            self.assertNotIn(leak, blob, leak)
        self.assertNotIn("fleet", d)
        self.assertNotIn("controls", d)
        code, _, d = self.data(self.BEN)                       # "@domain" membership
        self.assertEqual(([b["id"] for b in d["brands"]], d["brands"][0]["paused"]), (["beta"], True))
        self.assertNotIn("late paying", json.dumps(d), "an admin's pause note stays with the admin")

    def test_who_gets_everything_and_who_gets_nothing(self):
        proxied = {"X-Real-IP": "203.0.113.22"}
        self.assertEqual(self.data(proxied)[0], 401, "a proxied call that names nobody")
        self.assertEqual(self.data(dict(proxied, **{"X-Otto-User": "stranger@nowhere.example"}))[0], 403)
        self.assertEqual(self.data({"X-Forwarded-For": "1.2.3.4"})[0], 401, "a proxy that forgot X-Real-IP is still a proxy")
        full = lambda h: {b["id"] for b in self.data(h)[2]["brands"]} == {"alpha", "beta", "shop-beta"}
        self.assertTrue(full({}), "a direct local call (CLI, tests, sim) sees everything")
        os.environ["OTTO_SINGLE_TENANT"] = "1"
        self.assertTrue(full(proxied), "single-login box: today's behaviour")
        os.environ.pop("OTTO_SINGLE_TENANT")
        os.environ["OTTO_ADMIN_USERS"] = "max@cmtm.co.il"
        self.assertTrue(full(dict(proxied, **{"X-Otto-User": "MAX@cmtm.co.il"})))
        self.assertEqual({b["id"] for b in self.data(self.ANNA)[2]["brands"]}, {"alpha"})
        os.environ["OTTO_ADMIN_USERS"] = "*"
        self.assertTrue(full(proxied))

    def test_proxy_key_guards_the_user_header(self):
        os.environ["OTTO_ADMIN_USERS"] = "max@cmtm.co.il"
        os.environ["OTTO_PROXY_KEY"] = "k-proxy-test"
        try:
            forged = {"X-Real-IP": "203.0.113.40", "X-Otto-User": "max@cmtm.co.il"}
            self.assertEqual(self.data(forged)[0], 401, "a name without the proxy's key is nobody")
            self.assertEqual(self.req("/otto-api/admin/snapshot", headers=forged)[0], 403)
            ok = dict(forged, **{"X-Otto-Proxy-Key": "k-proxy-test"})
            self.assertEqual(self.data(ok)[0], 200)
            self.assertEqual(self.req("/otto-api/admin/snapshot", headers=ok)[0], 200)
        finally:
            os.environ.pop("OTTO_PROXY_KEY", None)

    def test_a_client_cannot_act_on_another_brand(self):
        J2 = lambda h: dict(J, **h)
        for body in ({"kind": "post", "id": "be-001", "status": "approved"}, {"kind": "rec", "id": "rec-014", "status": "dismissed"},
                     {"kind": "rec", "id": "rec-011", "status": "done"}, {"kind": "rec", "id": "rec-012", "status": "done"}):
            self.assertEqual(self.req("/otto-api/action", "POST", body, J2(self.ANNA))[0], 404, body)
        self.assertEqual(self.req("/otto-api/decide", "POST", {"id": "be-001", "decision": "approve"}, J2(self.ANNA))[0], 404)
        d = ap.load()
        self.assertEqual((ap.post(d, "be-001")["status"], ap.rec(d, "rec-014")["status"], ap.rec(d, "rec-011")["status"]),
                         ("pending_approval", "proposed", "proposed"))
        code, _, out = self.req("/otto-api/decide", "POST", {"id": "al-001", "decision": "approve"}, J2(self.ANNA))
        self.assertEqual(code, 200)
        self.assertEqual({b["id"] for b in out["data"]["brands"]}, {"alpha"}, "the answer is the client's own view too")
        self.assertEqual(self.req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-010", "status": "done"}, J2(self.ANNA))[0], 200)
        self.assertEqual(self.req("/otto-api/action", "POST", {"kind": "post", "id": "al-002", "status": "approved"},
                                  J2({"X-Real-IP": "203.0.113.22"}))[0], 401)

    def test_signed_in_onboarding_is_scoped_to_the_client(self):
        orig = (otto_scan.scan, otto_scan.host_status)
        otto_scan.host_status = lambda u: "ok"
        otto_scan.scan = lambda url, pages=5, page_limit=0, deadline=None: canned_scan(otto_onboard.host_key(url), "New Shop")
        try:
            h = dict(J, **self.ANNA)
            code, _, out = quiet(self.req, "/otto-api/onboard", "POST", {"site": "beta-cafe.example", "answers": {"corrections": {"name": "Mine"}}}, h)
            self.assertEqual(code, 409, "another client's site")
            self.assertEqual(ap.brand(ap.load(), "beta")["name"], "Beta Cafe")
            otto_onboard._rl_last.clear()
            code, _, out = quiet(self.req, "/otto-api/onboard", "POST", {"site": "annas-second-shop.example"}, h)
            self.assertEqual((code, out["created"]), (200, True))
            self.assertEqual(ap.brand(ap.load(), out["brand"])["members"], ["anna@alpha-dental.example"])
            self.assertEqual({b["id"] for b in self.data(self.ANNA)[2]["brands"]}, {"alpha", out["brand"]})
            otto_onboard._rl_last.clear()
            code, _, _ = quiet(self.req, "/otto-api/onboard", "POST", {"site": "alpha-dental.example", "answers": {"goal": "leads"}}, h)
            self.assertEqual(code, 200, "a member may re-run onboarding for their own brand")
        finally:
            otto_scan.scan, otto_scan.host_status = orig

    def test_the_embedded_fallback_carries_no_client_data(self):
        (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{"old": 1}</script></html>')
        with ap.transaction() as d:
            ap.post(d, "al-001")["hook"] = "Alpha private hook"
        html = (TMP / "index.html").read_text()
        block = json.loads(re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(block, ap.NEUTRAL_FALLBACK)
        os.environ["OTTO_FALLBACK"] = "full"                 # local dev / demo on the owner's machine
        try:
            quiet(ap.sync_fallback)
        finally:
            os.environ.pop("OTTO_FALLBACK")
        self.assertIn("Alpha private hook", (TMP / "index.html").read_text())

    def test_members_are_managed_by_the_owner(self):
        post = lambda body: self.req("/otto-api/admin", "POST", body, J)
        self.assertEqual(post({"action": "members", "brand": "alpha", "add": ["not an email"]})[0], 400)
        self.assertEqual(post({"action": "members", "brand": "nope", "add": ["a@b.example"]})[0], 404)
        code, _, out = post({"action": "members", "brand": "alpha", "add": ["Dr.Who@Alpha-Dental.example", "@alpha-team.example"],
                             "remove": ["anna@alpha-dental.example"]})
        self.assertEqual((code, out["members"]), (200, ["dr.who@alpha-dental.example", "@alpha-team.example"]))
        self.assertEqual(self.data(self.ANNA)[0], 403, "removed: no brand left")
        self.assertEqual(self.data({"X-Real-IP": "203.0.113.30", "X-Otto-User": "zoe@alpha-team.example"})[0], 200)
        with otto_whop.transaction() as b:
            b["customers"]["mem_Q"] = {"id": "mem_Q", "status": "active", "email": "Payer@Gmail.com"}
        self.assertEqual(post({"action": "link_customer", "customer": "mem_Q", "brand": "beta"})[0], 200)
        self.assertIn("payer@gmail.com", ap.brand(ap.load(), "beta")["members"], "linking a payer lets them sign in to their brand")
        snap = self.req("/otto-api/admin/snapshot")[2]
        self.assertIn("payer@gmail.com", next(b for b in snap["brands"] if b["id"] == "beta")["members"])
        item = next(x for x in snap["setup"] if x["key"] == "tenants")
        self.assertEqual(item["status"], "missing")
        self.assertIn("shop-beta", item["detail"], "a brand no client can see yet is flagged")
        log = (TMP / "actions.log").read_text()
        self.assertIn("admin admin members alpha +2 -1 now=2", log)
        self.assertIn("link-customer mem_Q -> beta (+member)", log)


# ============================================================================================
# analytics privacy
# ============================================================================================

class TrackTest(_Server, unittest.TestCase):
    def setUp(self):
        reset_workspace()

    def lines(self):
        f = TMP / "events.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def test_raw_ip_is_never_stored_in_any_mode(self):
        ip = "203.0.113.200"
        body = json.dumps({"p": "/pilot-landing.html", "r": "www.google.com", "ev": [{"e": "view"}, {"e": "cta", "id": "get_started@nav"}]})
        for extra in ({}, {"DNT": "1"}, {"Sec-GPC": "1"}):
            h = dict({"Content-Type": "text/plain", "Origin": ORIGIN, "X-Real-IP": ip, "User-Agent": "UA"}, **extra)
            self.assertEqual(self.req("/otto-track", "POST", body.encode(), h)[0], 204)
        blob = b"".join(f.read_bytes() for f in TMP.iterdir() if f.is_file())
        self.assertNotIn(ip.encode(), blob, "no raw IP in events, salt, logs or anything else next to data.json")
        self.assertNotIn(hashlib.sha256(ip.encode()).hexdigest()[:16].encode(), blob, "nor an unsalted hash of it")

    def test_script_urls_in_utm_are_dropped(self):
        code, _ = otto_track.ingest(json.dumps({"p": "/x", "u": {"source": "javascript:alert(1)", "medium": "data:text/html,x",
                                                                 "campaign": "spring sale (EU) | 20%"}, "ev": [{"e": "view"}]}).encode(),
                                    "192.0.2.1", {"User-Agent": "UA"})
        self.assertEqual(code, 204)
        self.assertEqual(self.lines()[0]["u"], {"campaign": "spring sale (EU) | 20%"})

    def test_odd_json_types_are_a_400_never_a_500(self):
        for body in ({"p": "/x", "ev": [{"e": ["view"]}]}, {"p": "/x", "ev": [{"e": "scroll", "d": [50]}]}, {"p": "/x", "e": {"a": 1}},
                     {"p": ["/x"], "ev": [{"e": "view"}]}, {"p": "/x", "ev": {"e": "view"}}):
            self.assertEqual(otto_track.ingest(json.dumps(body).encode(), "192.0.2.3", {})[0], 400, body)
        code, _ = otto_track.ingest(json.dumps({"p": "/x", "dv": ["mobile"], "anon": [1], "u": {"source": {"$gt": 1}}, "r": ["x"],
                                                "s": {"a": 1}, "ev": [{"e": "view"}]}).encode(), "192.0.2.3", {})
        self.assertEqual(code, 204)
        self.assertEqual(set(self.lines()[-1]), {"ts", "e", "v", "p"}, "odd types are dropped, never stored")
        self.assertFalse((TMP / "api-errors.log").exists())

    def test_malformed_lines_are_skipped_and_reading_is_bounded(self):
        f = TMP / "events.jsonl"
        good = [{"ts": f"2026-09-{d:02d}T10:00:00Z", "e": "view", "v": f"{d:016x}", "p": "/x"} for d in range(1, 29)]
        rows = [json.dumps(g) for g in good[:10]] + ["not json", "[1,2,3]", '{"e":"view"}', '{"ts": 5, "e": "view"}', "\x00\xff"]
        rows += [json.dumps(g) for g in good[10:]]
        f.write_text("\n".join(rows) + "\n")
        got = otto_track.read_events()
        self.assertEqual([e["v"] for e in got], [g["v"] for g in good])
        self.assertFalse(otto_track.read_events.truncated)
        tail = otto_track.read_events(max_bytes=400)
        self.assertTrue(otto_track.read_events.truncated)
        self.assertTrue(0 < len(tail) < len(good))
        self.assertEqual(tail[-1]["v"], good[-1]["v"], "the newest events are the ones kept")

    def test_storage_cap(self):
        os.environ["OTTO_EVENTS_MAX_MB"] = "0.0001"
        try:
            (TMP / "events.jsonl").write_text("x" * 200 + "\n")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(otto_track.ingest(json.dumps({"p": "/x", "ev": [{"e": "view"}]}).encode(), "192.0.2.2", {})[0], 507)
        finally:
            os.environ.pop("OTTO_EVENTS_MAX_MB", None)

    def test_one_salt_per_day_under_threads(self):
        otto_track._salt.update(day=None, salt=None)
        got = []
        threads = [threading.Thread(target=lambda: got.append(otto_track.daily_salt())) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(got)), 1)
        self.assertEqual(json.loads((TMP / ".track-salt").read_text())["salt"], got[0])
        self.assertEqual(os.stat(TMP / ".track-salt").st_mode & 0o777, 0o600)


# ============================================================================================
# Whop webhook
# ============================================================================================

def signed(body, wid="msg_1", ts=None, secret=SECRET):
    ts = str(int(ts if ts is not None else time.time()))
    return {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": otto_whop.sign(secret, wid, ts, body),
            "Content-Type": "application/json"}


class WhopTest(_Server, unittest.TestCase):
    def setUp(self):
        reset_workspace()

    def connect(self):
        (TMP / "secrets" / "whop.json").write_text(json.dumps({"otto_webhook_secret": SECRET}))

    def event(self, etype, data, eid):
        return json.dumps({"id": eid, "type": etype, "data": data}).encode()

    def test_not_connected_is_503_and_stores_nothing(self):
        body = self.event("membership.activated", {"id": "mem_1", "status": "active"}, "e1")
        code, _, out = self.req("/otto-api/whop", "POST", body, signed(body))
        self.assertEqual(code, 503)
        self.assertFalse((TMP / "billing.json").exists())

    def test_timestamp_window_and_exact_bytes(self):
        self.connect()
        body = self.event("payment.succeeded", {"id": "pay_1", "status": "paid", "total": 10}, "e1")
        now = time.time()
        self.assertTrue(otto_whop.verify(body, signed(body, ts=now - 299), [SECRET], now=now)[0])
        for ts in (now - 301, now + 301):
            self.assertFalse(otto_whop.verify(body, signed(body, ts=ts), [SECRET], now=now)[0], ts)
        h = signed(body)
        self.assertFalse(otto_whop.verify(body, dict(h, **{"webhook-timestamp": h["webhook-timestamp"] + "0"}), [SECRET])[0])
        self.assertFalse(otto_whop.verify(body, dict(h, **{"webhook-timestamp": "12e8"}), [SECRET])[0])
        self.assertFalse(otto_whop.verify(body, dict(h, **{"webhook-id": "other"}), [SECRET])[0], "the id is signed too")
        self.assertFalse(otto_whop.verify(json.dumps(json.loads(body)).encode() + b" ", h, [SECRET])[0])
        self.assertFalse(otto_whop.verify(body, dict(h, **{"webhook-signature": "v1a," + h["webhook-signature"][3:]}), [SECRET])[0])
        code, _, out = self.req("/otto-api/whop", "POST", body, dict(h, **{"webhook-signature": "v1,AAAA"}))
        self.assertEqual(code, 401)
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertNotIn(SECRET, (TMP / "api-errors.log").read_text())

    def test_replay_unknown_and_bad_json(self):
        self.connect()
        body = self.event("membership.activated", {"id": "mem_R", "status": "active", "user": {"email": "r@shop.example"}}, "e1")
        h = signed(body, wid="msg_R")
        self.assertEqual(self.req("/otto-api/whop", "POST", body, h)[2].get("duplicate"), None)
        self.assertTrue(self.req("/otto-api/whop", "POST", body, h)[2]["duplicate"], "the same delivery twice is processed once")
        b = otto_whop.load()
        self.assertEqual((len(b["events"]), b["seen"]), (1, ["msg_R"]))
        odd = self.event("app.installed", {"id": "x"}, "e2")
        code, _, out = self.req("/otto-api/whop", "POST", odd, signed(odd, wid="msg_U"))
        self.assertEqual((code, out["ok"], out["type"]), (200, True, "app.installed"))
        junk = b"{not json"
        self.assertEqual(self.req("/otto-api/whop", "POST", junk, signed(junk, wid="msg_J"))[0], 400)
        self.assertEqual(len(otto_whop.load()["events"]), 2, "a bad body stores nothing")
        self.assertEqual(self.req("/otto-api/whop", "POST", b"", {"Content-Type": "application/json"})[0], 413)

    def test_state_machine_edges(self):
        self.connect()

        def send(etype, data, wid):
            body = self.event(etype, data, wid)
            return otto_whop.webhook(body, signed(body, wid=wid))
        send("payment.succeeded", {"id": "pay_X", "status": "paid", "total": 197, "currency": "eur", "membership": {"id": "mem_X"}}, "w1")
        send("refund.created", {"payment": {"id": "pay_X"}, "amount": 197, "status": "succeeded"}, "w2")
        send("payment.succeeded", {"id": "pay_X", "status": "paid", "total": 197, "currency": "eur", "membership": {"id": "mem_X"}}, "w3")
        self.assertEqual(otto_whop.load()["payments"]["pay_X"]["status"], "refunded", "a late success never undoes a refund")
        self.assertEqual(send("membership.activated", "not a dict", "w4")[0], 200)
        self.assertEqual(send("payment.succeeded", {"id": "pay_Y", "total": "1.0e999"}, "w5")[0], 200)
        self.assertIsNone(otto_whop.load()["payments"]["pay_Y"].get("amount"), "a non-finite amount is not a number")
        json.loads((TMP / "billing.json").read_text(), parse_constant=lambda c: self.fail(f"{c} in billing.json"))


# ============================================================================================
# the owner console on bad data + its controls
# ============================================================================================

class AdminEdgeTest(_Server, unittest.TestCase):
    def setUp(self):
        reset_workspace()

    def test_snapshot_survives_malformed_state(self):
        d = seed()
        d["brands"] += [{"name": "No id"}, {"id": "gamma", "name": None, "url": None}, "a string", {"id": 7}]
        d["posts"] += [{"brand": "alpha", "status": "failed"}, {"id": "x-1", "status": "pending_approval"}, None,
                       {"id": "x-2", "brand": "ghost", "status": "publishing"}]
        d["recommendations"] += [{"title": "no id", "status": "proposed"}, {"id": "rec-9", "status": "proposed", "priority": None}]
        d["campaigns"] = [{"id": "cp-1", "brand": "alpha", "status": "live", "daily_budget": "abc", "start": "bad", "end": None},
                          {"brand": "alpha"}]
        d["controls"] = "yes"
        d["ads"] = []
        (TMP / "data.json").write_text(json.dumps(d))
        (TMP / "events.jsonl").write_text('{"ts":"2026-09-28T10:00:00Z","e":"view","v":"aaaaaaaaaaaaaaaa","p":"/x"}\n[1]\nnot json\n'
                                          '{"ts":"2026-09-28T10:00:00Z","e":"scan_start","domain":null}\n')
        (TMP / "billing.json").write_text(json.dumps({"customers": {"m": "x", "m2": {"id": "m2", "status": "active"}}, "payments": []}))
        (TMP / "leads.json").write_text("[]")
        snap = otto_admin.snapshot(window=7)
        json.dumps(snap, allow_nan=False)
        self.assertIn("gamma", {b["id"] for b in snap["brands"]})
        self.assertEqual(self.req("/otto-api/admin/snapshot?days=90")[0], 200)

    def test_huge_events_file_is_read_bounded(self):
        orig = otto_track.READ_MAX_MB
        otto_track.READ_MAX_MB = 0.02                          # ~20 KB
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with (TMP / "events.jsonl").open("w") as f:
                for i in range(2000):
                    f.write(json.dumps({"ts": f"{day}T10:00:00Z", "e": "view", "v": f"{i:016x}", "p": "/x"}, separators=(",", ":")) + "\n")
            snap = otto_admin.snapshot(window=7)
        finally:
            otto_track.READ_MAX_MB = orig
        self.assertTrue(snap["system"]["events_file"]["truncated"])
        self.assertLess(snap["traffic"]["visitors"], 2000)

    def test_controls_validate_and_log_one_line_each(self):
        J2 = dict(J, **{"X-Otto-User": "evil\tadmin"})
        post = lambda body, h=J: self.req("/otto-api/admin", "POST", body, h)
        self.assertEqual(post({"action": "kill_switch", "state": "ON"})[0], 400)
        self.assertEqual(post({"action": "campaign", "id": "cp-1\nadmin max kill-switch off", "decision": "approve"})[0], 404)
        self.assertEqual(post({"action": "lead", "id": "d:good.example\n", "status": "won"})[0], 400)
        self.assertEqual(post({"action": "pause_brand", "brand": ["alpha"]})[0], 404)
        self.assertEqual(post({"action": "kill_switch", "state": "on", "note": 'line one\nadmin max kill-switch off\u202e "x"'}, J2)[0], 200)
        log = (TMP / "actions.log").read_text().splitlines()
        self.assertEqual(len(log), 1, "a note can never forge a second audit line")
        self.assertRegex(log[0], r"^\S+ admin admin kill-switch on note=\"line one admin max kill-switch off \\\"x\\\"\"$")
        self.assertEqual(ap.load()["controls"]["publishing_paused"]["by"], "admin", "a header with odd characters is not a name")

    def test_full_events_file_is_flagged(self):
        os.environ["OTTO_EVENTS_MAX_MB"] = "0.01"
        try:
            (TMP / "events.jsonl").write_text(("x" * 99 + "\n") * 200)
            item = next(x for x in otto_admin.snapshot()["setup"] if x["key"] == "analytics")
        finally:
            os.environ.pop("OTTO_EVENTS_MAX_MB", None)
        self.assertEqual(item["status"], "missing")
        self.assertIn("prune", item["detail"])
        msg = otto_admin.act({"action": "kill_switch", "state": "on"}, "max")["message"]
        self.assertIn("No campaign was live", msg, "the switch says what it did to the ads")

    def test_open_secret_files_are_flagged(self):
        f = TMP / "secrets" / "meta-alpha.json"
        f.write_text("{}")
        os.chmod(f, 0o644)
        item = next(x for x in otto_admin.snapshot()["setup"] if x["key"] == "secrets_mode")
        self.assertEqual((item["status"], "meta-alpha.json" in item["detail"]), ("missing", True))
        os.chmod(f, 0o600)
        self.assertEqual(next(x for x in otto_admin.snapshot()["setup"] if x["key"] == "secrets_mode")["status"], "connected")


# ============================================================================================
# compliance fails closed; Telegram only obeys the owner; asset paths
# ============================================================================================

class ComplianceTest(unittest.TestCase):
    def setUp(self):
        reset_workspace()
        (TMP / "brands" / "alpha").mkdir(exist_ok=True)

    def rules(self, text):
        (TMP / "brands" / "alpha" / "compliance.json").write_text(text)

    def test_malformed_rules_hold_everything(self):
        for text in ("not json", "[]", '"cure"', '{"banned": "cure"}', '{"banned": ["re:("]}', '{"required_disclaimer": ["x"]}',
                     '{"banned": ["fine", "re:[unclosed"]}'):
            self.rules(text)
            with contextlib.redirect_stderr(io.StringIO()):
                v = otto_compliance.check_texts("alpha", ["A perfectly ordinary post about teeth."])
            self.assertTrue(v, text)
            self.assertTrue(v[0]["rule"].startswith("compliance.json"), text)

    def test_dshea_is_not_a_claim_but_a_claim_next_to_it_is(self):
        dshea = ("These statements have not been evaluated by the Food and Drug Administration. This product is not intended to "
                 "diagnose, treat, cure, or prevent any disease.")
        self.rules(json.dumps({"banned": otto_compliance.HEALTH_BASELINE}))
        self.assertEqual(otto_compliance.check_texts("alpha", ["Daily greens for busy mornings. " + dshea]), [])
        self.assertTrue(otto_compliance.check_texts("alpha", ["It cures bloating. " + dshea]))

    def test_publisher_never_sends_a_post_when_the_rules_are_broken(self):
        self.rules("{broken")
        calls = []
        orig = otto_publish.graph
        otto_publish.graph = lambda *a, **kw: calls.append(a) or {"id": "1"}
        (TMP / "secrets" / "meta-alpha.json").write_text(json.dumps({"access_token": "T", "page_id": "P"}))
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        with ap.transaction(sync=False) as d:
            ap.post(d, "al-001").update(status="approved", slot=slot)
        try:
            quiet(otto_publish.run)
        finally:
            otto_publish.graph = orig
        p = ap.post(ap.load(), "al-001")
        self.assertEqual((p["status"], calls), ("draft", []))
        self.assertIn("compliance.json unreadable", p["compliance_block"]["rules"])


class PublisherRobustnessTest(unittest.TestCase):
    def test_a_malformed_post_does_not_stop_the_run(self):
        reset_workspace()
        (TMP / "secrets" / "meta-alpha.json").write_text(json.dumps({"access_token": "T", "page_id": "P"}))
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        with ap.transaction(sync=False) as d:
            d["posts"][:0] = [{"id": "x-1", "status": "approved", "slot": slot}, {"brand": "alpha", "status": "approved", "slot": slot},
                              "not a post"]
            ap.post(d, "al-005").update(status="approved", slot=slot, caption="Fresh start.")
        calls, orig = [], otto_publish.graph
        otto_publish.graph = lambda method, path, token, **kw: calls.append(path) or {"id": "r1", "post_id": "r1"}
        try:
            quiet(otto_publish.run)
        finally:
            otto_publish.graph = orig
        self.assertEqual(ap.post(ap.load(), "al-005")["status"], "published")
        self.assertTrue(calls)


class TelegramTest(unittest.TestCase):
    def setUp(self):
        reset_workspace()
        (TMP / "secrets" / "telegram.json").write_text(json.dumps({"bot_token": "x", "owner_chat_id": "42"}))
        self.calls = []
        self._api = otto_telegram.api
        otto_telegram.api = lambda method, files=None, **kw: self.calls.append((method, kw.get("text"))) or {"message_id": 1}

    def tearDown(self):
        otto_telegram.api = self._api

    def cq(self, data, user=42, chat=42):
        return {"id": "cb", "data": data, "from": {"id": user}, "message": {"message_id": 5, "chat": {"id": chat}, "text": "card"}}

    def answers(self):
        return [t for m, t in self.calls if m == "answerCallbackQuery"]

    def test_only_the_owner_in_the_owner_chat_decides(self):
        otto_telegram.handle_callback(self.cq("otto:al-001:approve", user=666))
        otto_telegram.handle_callback(self.cq("otto:al-001:approve", chat=999))
        otto_telegram.handle_callback({"id": "cb", "data": "otto:al-001:approve", "message": {"chat": {"id": 42}}})
        self.assertEqual(self.answers(), ["Not your Otto."] * 3)
        self.assertEqual(ap.post(ap.load(), "al-001")["status"], "pending_approval")
        otto_telegram.handle_callback(self.cq("otto:al-001:approve"))
        self.assertEqual(ap.post(ap.load(), "al-001")["status"], "approved")

    def test_forged_callback_data(self):
        for data in ("otto:rec:rec-001:approve_everything", "otto:rec:rec-001:", "otto:al-001:publish", "otto:../../x:approve",
                     "otto:al-900:approve", "x" * 300, "", "otto:rec:nope:approve"):
            otto_telegram.handle_callback(self.cq(data))
        d = ap.load()
        self.assertEqual((ap.rec(d, "rec-001")["status"], ap.post(d, "al-900")["status"], ap.post(d, "al-001")["status"]),
                         ("proposed", "published", "pending_approval"))
        self.assertNotIn("✅ Approved", " ".join(t or "" for t in self.answers()))

    def test_edit_replies_only_from_the_owner(self):
        (TMP / ".telegram-state.json").write_text(json.dumps({"pending_edits": {"77": {"post": "al-002", "ts": ap.now_iso()}}}))
        otto_telegram.handle_message({"from": {"id": 666}, "chat": {"id": 42}, "text": "make it rude", "reply_to_message": {"message_id": 77}})
        self.assertNotIn("edit_note", ap.post(ap.load(), "al-002"))
        otto_telegram.handle_message({"from": {"id": 42}, "chat": {"id": 42}, "text": "shorter", "reply_to_message": {"message_id": 77}})
        self.assertEqual(ap.post(ap.load(), "al-002")["edit_note"], "shorter")


class PathsTest(unittest.TestCase):
    def test_only_repo_relative_assets(self):
        for bad in ("../secrets/meta.json", "/etc/passwd", "assets/../../otto-secrets/x.json", "brands/alpha/scan.json", "", None,
                    "./../x", "assets/../data.json"):
            with self.assertRaises(otto_paths.AssetError, msg=bad):
                otto_paths.clean_rel(bad)
        self.assertEqual(otto_paths.clean_rel("./assets/posts/a.jpg"), "assets/posts/a.jpg")

    def test_the_new_domain_is_one_setting(self):
        # regression (integration review): with only OTTO_DOMAIN set, the API still allowed nothing but dash.monyflow.work
        # (every POST from app.<domain> → 403) and media URLs pointed at the old box; OTTO_PUBLIC_BASE / OTTO_ALLOWED_ORIGINS win
        code = ("import otto_paths, otto_api, otto_admin, otto_email; print(otto_paths.BASE); print(sorted(otto_api.ALLOWED_ORIGINS)); "
                "print(otto_admin.PUBLIC_BASE); print(otto_email.app_url({}))")
        env = {k: v for k, v in os.environ.items() if not k.startswith("OTTO_")}
        env.update(OTTO_DATA=str(TMP / "data.json"), OTTO_HTML=str(TMP / "index.html"), OTTO_SECRETS=str(TMP / "secrets"))
        run = lambda **kw: subprocess.run([sys.executable, "-c", code], cwd=str(PLATFORM), env=dict(env, **kw), capture_output=True,
                                          text=True, timeout=60).stdout.splitlines()
        self.assertEqual(run(OTTO_DOMAIN="otto.example"),
                         ["https://otto.example/", str(["https://admin.otto.example", "https://app.otto.example", "https://otto.example"]),
                          "https://otto.example", "https://app.otto.example/"])
        self.assertEqual(run(OTTO_DOMAIN="otto.example", OTTO_PUBLIC_BASE="https://cdn.otto.example/", OTTO_ALLOWED_ORIGINS="https://x.example")[:2],
                         ["https://cdn.otto.example/", str(["https://x.example"])])
        self.assertEqual(run()[:3], ["https://dash.monyflow.work/otto/", str(["https://dash.monyflow.work"]), "https://dash.monyflow.work"])


# ============================================================================================
# secrets hygiene
# ============================================================================================

TOKEN = re.compile(r"EAA[A-Za-z0-9]{30,}|\bsk-[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,}|xox[bpa]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|"
                   r"\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|whsec_[A-Za-z0-9+/=]{24,}|\bws_[a-f0-9]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY|"
                   r"AIza[0-9A-Za-z_-]{35}")


class SecretsTest(unittest.TestCase):
    def test_no_token_in_the_repository(self):
        repo = PLATFORM.parent
        try:
            files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=repo, capture_output=True, text=True,
                                   timeout=60).stdout.split("\n")
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git not available")
        hits = []
        for name in files:
            f = repo / name
            if not name or not f.is_file() or f.stat().st_size > 3_000_000 or f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".webp",
                                                                                                   ".woff2", ".woff", ".gif", ".mp3", ".wav"):
                continue
            try:
                m = TOKEN.search(f.read_text(errors="ignore"))
            except OSError:
                continue
            if m:
                hits.append(f"{name}: {m.group(0)[:12]}…")
        self.assertEqual(hits, [])

    def test_the_committed_dashboard_embeds_no_client_data(self):
        """index.html is served to every signed-in client: its fallback block is the neutral document (test fixtures live in
        tests/fixtures/data.json, never in the page)."""
        html = (PLATFORM / "index.html").read_text()
        m = re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', html, re.S)
        block = json.loads(m.group(1)) if m else None
        self.assertTrue(block is None or not any(block.get(k) for k in ("brands", "posts", "recommendations", "campaigns", "fleet")),
                        "run: OTTO_FALLBACK= python3 ap.py sync-fallback")
        self.assertTrue((PLATFORM / "tests" / "fixtures" / "data.json").exists())

    def test_secrets_stay_in_otto_secrets(self):
        reset_workspace()
        (TMP / "secrets" / "whop.json").write_text(json.dumps({"api_key": "k_LEAKCHECK", "otto_webhook_secret": "ws_LEAKCHECK"}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print(json.dumps(otto_whop.status()))
        self.assertNotIn("LEAKCHECK", out.getvalue())
        self.assertNotIn("LEAKCHECK", json.dumps(otto_admin.snapshot()))
        for mod in (otto_whop, otto_publish, otto_telegram):
            src = Path(mod.__file__).read_text()
            self.assertIn("OTTO_SECRETS", src, f"{mod.__name__} reads secrets from OTTO_SECRETS")


class IsolationTest(unittest.TestCase):
    def test_real_workspace_untouched(self):
        self.assertEqual((PLATFORM / "data.json").exists(), _SAVED["repo_data"])
        for n, before in REPO_STATE.items():
            now = (PLATFORM / n).read_bytes() if (PLATFORM / n).exists() else None
            self.assertEqual(now, before, f"platform/{n} was written by a test run")
        for name in ("events.jsonl", "billing.json", "leads.json", ".track-salt", "api-errors.log"):
            self.assertFalse((PLATFORM / name).exists(), f"{name} written into the repo")


if __name__ == "__main__":
    unittest.main()
