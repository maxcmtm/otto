#!/usr/bin/env python3
"""Otto walkthrough — the real system on this Mac, laid out the way infra/Caddyfile serves it, with test stand-ins for the
outside accounts that are not connected yet (Google sign-in and Stripe). Everything else is the real code from this
checkout: the landing, the scan, onboarding, the trial, the copywriter, the app, billing, the e-mails and the owner console.
Local only (127.0.0.1); never deployed or started on the server.

    python3 tools/walkthrough.py [--reset]          (launch config "otto-walk")

  http://localhost:8790/pilot-landing.html   the landing (apex) — "Start free trial" begins the client journey
  http://localhost:8790/                     the client app (app.) — same host locally, as the landing expects
  http://127.0.0.1:8790/                     the owner console (admin.) — a different host, so no client cookie reaches it
  http://localhost:8790/sim/tools            test controls: jump a trial to day 5 / 7 / 8, send the 07:35 report, read e-mails

The workspace (data.json, brands, sessions, outbox …) lives in ~/.otto-walk/ (OTTO_WALK_HOME) — not in /tmp, so a restart
keeps it — and starts empty; --reset (or "Start over" on /sim/tools) empties it again. With ~/otto-launch-keys/anthropic-key.txt
present the real copywriter (otto_copy) writes and designs every new trial's first week, as on the server.
"""
import email, email.policy, hashlib, html, http.client, json, os, re, secrets, shutil, subprocess, sys, threading, time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("OTTO_WALK_HOME") or Path.home() / ".otto-walk")
WS, SITE = HOME / "ws", HOME / "site"
KEYS = Path.home() / "otto-launch-keys"
PORT = int(os.environ.get("OTTO_WALK_PORT") or 8790)    # a second instance (the filled-in demo, tools/walkthrough_demo.py) runs on 8792
API_PORT = PORT - 627                                     # 8790 → 8163
ORIGIN, ADMIN_ORIGIN = f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"
OWNER = "owner@otto.local"
PROXY_KEY = secrets.token_hex(16)
WEBHOOK_SECRET = "whsec_walkthrough_" + "0" * 24


# ------------------------------------------------------------------ workspace

def seed():
    if WS.exists():
        shutil.rmtree(WS)
    for d in ("brands", "assets", "public/assets", "secrets", "outbox", "exports", "locks", "motion"):
        (WS / d).mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (WS / "data.json").write_text(json.dumps({"generated": now, "brands": [], "posts": [], "recommendations": [],
                                              "campaigns": [], "connections": []}, indent=1))
    plans = json.loads((PLATFORM / "plans.json").read_text())
    ids = {"starter": {"monthly": "price_starter_m"},                                  # monthly subscription only
           "growth": {"monthly": "price_growth_m", "yearly": "price_growth_y"},
           "scale": {"monthly": "price_scale_m", "yearly": "price_scale_y"}}
    for pid, v in ids.items():
        if pid in plans["plans"]:
            plans["plans"][pid]["stripe_price_ids"] = v
    (WS / "plans.json").write_text(json.dumps(plans, indent=1))
    (WS / "secrets" / "email.json").write_text(json.dumps({"link_secret": secrets.token_hex(32), "action_base": ORIGIN,
                                                           "app_url": ORIGIN + "/"}))


if "--reset" in sys.argv or not (WS / "data.json").exists():
    seed()
(WS / "secrets").mkdir(parents=True, exist_ok=True)
_ak = KEYS / "anthropic-key.txt"
if _ak.is_file() and _ak.read_text().strip():
    (WS / "secrets" / "anthropic.json").write_text(json.dumps({"api_key": _ak.read_text().strip()}))
    os.chmod(WS / "secrets" / "anthropic.json", 0o600)

ENV = {"OTTO_DATA": WS / "data.json", "OTTO_HTML": WS / "app-fallback.html", "OTTO_BRANDS": WS / "brands",
       "OTTO_ASSETS": WS / "assets", "OTTO_PUBLIC_ASSETS": WS / "public" / "assets", "OTTO_SECRETS": WS / "secrets",
       "OTTO_EVENTS": WS / "events.jsonl", "OTTO_BILLING": WS / "billing.json", "OTTO_LEADS": WS / "leads.json",
       "OTTO_OUTBOX": WS / "outbox", "OTTO_EMAIL_STATE": WS / ".email-state.json", "OTTO_HEARTBEATS": WS / "heartbeats.json",
       "OTTO_LOCKS": WS / "locks", "OTTO_EXPORTS": WS / "exports", "OTTO_MOTION_ROOT": WS / "motion", "OTTO_PLANS": WS / "plans.json",
       "OTTO_SESSIONS": WS / "sessions.json", "OTTO_REPORT_STATE": WS / ".report-state.json",
       "OTTO_OWNER_EMAIL": OWNER, "OTTO_ADMIN_USERS": OWNER, "OTTO_PROXY_KEY": PROXY_KEY,
       "OTTO_ALLOWED_ORIGINS": f"{ORIGIN},{ADMIN_ORIGIN}", "OTTO_EMAIL_BASE": ORIGIN, "OTTO_APP_URL": ORIGIN + "/",
       "OTTO_PUBLIC_BASE": ORIGIN + "/", "OTTO_GOOGLE_REDIRECT_URI": ORIGIN + "/auth/google/callback"}
for k, v in ENV.items():
    os.environ[k] = str(v)
for k in ("OTTO_SINGLE_TENANT", "OTTO_DOMAIN", "OTTO_FALLBACK", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "WHOP_API_KEY",
          "OTTO_STRIPE_SECRET_KEY", "OTTO_STRIPE_PUBLISHABLE_KEY", "OTTO_STRIPE_WEBHOOK_SECRET", "OTTO_CRON_NOW", "LEONARDO_API_KEY",
          "OTTO_COPY_QUEUE", "OTTO_ANTHROPIC_API_BASE"):
    os.environ.pop(k, None)
(WS / "app-fallback.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')

# ------------------------------------------------------------------ the two stand-ins (in-process, 127.0.0.1 only)

sys.path.insert(0, str(PLATFORM / "tests"))
sys.path.insert(0, str(PLATFORM))
import fake_google as FG          # noqa: E402
FG.REDIRECT = f"http://localhost:{PORT}/auth/google/callback"   # the stand-in checks the redirect URI of this instance
import fake_stripe as FS          # noqa: E402

FS.PRICES.update({"price_scale_m": (49900, "month"), "price_scale_y": (499000, "year")})
GOOGLE, STRIPE = FG.FakeGoogle(), FS.FakeStripe()
os.environ["OTTO_STRIPE_API_BASE"] = STRIPE.base
(WS / "secrets" / "google-oauth.json").write_text(json.dumps(GOOGLE.config(auth_url=ORIGIN + "/sim/google/auth")))
(WS / "secrets" / "stripe.json").write_text(json.dumps({"secret_key": FS.KEY, "publishable_key": "pk_test_walkthrough",
                                                        "webhook_secrets": [WEBHOOK_SECRET], "checkout_ui": "hosted"}))

import ap, otto_api, otto_stripe, otto_trial    # noqa: E402  (after the environment: they read it at import)
sys.path.insert(0, str(PLATFORM / "tools"))
import csp                                      # noqa: E402

api_srv = ThreadingHTTPServer(("127.0.0.1", API_PORT), otto_api.Handler)
threading.Thread(target=api_srv.serve_forever, daemon=True).start()

# ------------------------------------------------------------------ the web roots (built from the checkout on every start)

STRIPE_PAY = "https://checkout.stripe.com/c/pay/"
LOCAL_PAY = ORIGIN + "/sim/pay/"


def build_site():
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    for f in ("landing.html", "onboarding.html", "billing.html", "approve.html", "ads.html", "analytics.html", "admin.html"):
        if (PLATFORM / f).exists():
            shutil.copy2(PLATFORM / f, SITE / f)
    # app.: the client app with the neutral embedded fallback, as infra/deploy.sh publishes it
    shutil.copy2(PLATFORM / "index.html", SITE / "index.html")
    subprocess.run([sys.executable, "ap.py", "sync-fallback"], cwd=PLATFORM, check=True, stdout=subprocess.DEVNULL,
                   env=dict(os.environ, OTTO_HTML=str(SITE / "index.html"), OTTO_FALLBACK="neutral"))
    # billing: the stand-in's checkout page is http://localhost, the page only follows https links — let it follow this one
    # (and re-hash the page's CSP for the edited script, as tools/csp.py does)
    p = SITE / "billing.html"
    t = p.read_text()
    old = r"""const https = u => /^https:\/\/[^\s"'<>]+$/.test(String(u || "")) ? u : null;"""
    assert old in t, "billing.html: the https() guard moved — update tools/walkthrough.py"
    t = t.replace(old, r"""const https = u => /^(https:\/\/|http:\/\/localhost:PORT\/sim\/pay\/)[^\s"'<>]+$/.test(String(u || "")) ? u : null;""".replace("PORT", str(PORT)))
    t = csp.META.sub("", t)
    pol, _ = csp.policy(t, csp.PAGES["billing.html"])
    t = t.replace('<meta charset="utf-8">\n', '<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="%s">\n' % pol, 1)
    p.write_text(t)


build_site()

# ------------------------------------------------------------------ front (Caddy's job)

SECURITY = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "server", "date", "proxy-connection"}
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".mjs": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
         ".webm": "video/webm", ".woff2": "font/woff2", ".woff": "font/woff", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
         ".vtt": "text/vtt", ".mp3": "audio/mpeg", ".glb": "model/gltf-binary", ".hdr": "application/octet-stream"}

PAGES = {"/": "index.html", "/index.html": "index.html", "/pilot-landing.html": "landing.html", "/landing": "landing.html",
         "/landing.html": "landing.html"}
APP_PAGES = ("onboarding", "billing", "approve", "ads", "analytics")
PAGE_CSP = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self' " + ORIGIN


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


class Front(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    @property
    def admin_host(self):
        return (self.headers.get("Host") or "").split(":")[0] == "127.0.0.1"

    def _out(self, code, body=b"", ctype="text/html; charset=utf-8", headers=(), extra_csp=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        sent = set()
        for k, v in headers:
            if k in SECURITY:
                continue
            self.send_header(k, v)
            sent.add(k.lower())
        for k, v in SECURITY.items():
            self.send_header(k, extra_csp if (k == "Content-Security-Policy" and extra_csp) else v)
        if "content-type" not in sent:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, url):
        self._out(302, b"", headers=[("Location", url)])

    def _file(self, path):
        if not path.is_file():
            return self._out(404, "Not found", "text/plain; charset=utf-8")
        self._out(200, path.read_bytes(), TYPES.get(path.suffix.lower(), "application/octet-stream"))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _proxy(self, admin=False):
        body = self._body() if self.command == "POST" else None
        h = {k: v for k, v in self.headers.items()
             if k.lower() in ("content-type", "origin", "referer", "user-agent", "cookie", "dnt", "sec-gpc", "accept", "stripe-signature")}
        h["X-Real-IP"] = self.client_address[0]
        h["X-Otto-Proxy-Key"] = PROXY_KEY
        if admin:
            h["X-Otto-User"] = OWNER          # Cloudflare Access on admin.: the signed-in team member
        c = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=120)
        try:
            c.request(self.command, self.path, body=body, headers=h)
            r = c.getresponse()
            data = r.read()
        except Exception as e:                # noqa: BLE001
            return self._out(502, f"API not reachable: {type(e).__name__}", "text/plain; charset=utf-8")
        finally:
            c.close()
        if self.path.startswith("/billing/") and STRIPE_PAY.encode() in data:
            data = data.replace(STRIPE_PAY.encode(), LOCAL_PAY.encode())     # the stand-in's checkout page instead of Stripe's
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in HOP and k not in SECURITY and k.lower() != "content-security-policy":
                self.send_header(k, v)
        for k, v in SECURITY.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self, p):
        if p.startswith("/assets/"):
            rel = urllib.parse.unquote(p[len("/assets/"):])
            if ".." in rel.split("/"):
                return self._out(404, "Not found", "text/plain")
            gen = WS / "public" / "assets" / rel
            return self._file(gen if gen.is_file() else PLATFORM / "assets" / rel)
        if p.startswith("/legal/"):
            rel = urllib.parse.unquote(p[len("/legal/"):]).strip("/")
            if ".." in rel or not rel:
                return self._out(404, "Not found", "text/plain")
            f = PLATFORM / "legal" / rel
            return self._file(f if f.suffix else f.with_suffix(".html"))
        return None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        p = u.path
        if p.startswith("/sim/"):
            return self.sim_get(p, urllib.parse.parse_qs(u.query))
        if self.admin_host:
            if p.startswith("/otto-api/admin"):
                return self._proxy(admin=True)
            if p in ("/", "/index.html", "/admin.html"):
                return self._file(SITE / "admin.html")
            return self._static(p) or self._out(404, "Not found", "text/plain")
        if p.startswith(("/otto-api/admin", "/otto-api/whop")):
            return self._out(404, "Not found", "text/plain")
        if p.startswith(("/auth/", "/billing/", "/otto-api/", "/otto-peek", "/otto-email/")):
            return self._proxy()
        if p in PAGES:
            return self._file(SITE / PAGES[p])
        name = p.strip("/").removesuffix(".html")
        if name in APP_PAGES:
            return self._file(SITE / f"{name}.html")
        if p in ("/admin", "/admin.html"):
            return self._redirect(ADMIN_ORIGIN + "/")
        return self._static(p) or self._out(404, "Not found", "text/plain")

    def do_POST(self):
        p = urllib.parse.urlsplit(self.path).path
        if p.startswith("/sim/"):
            return self.sim_post(p)
        if self.admin_host:
            return self._proxy(admin=True) if p.startswith("/otto-api/admin") else self._out(404, "Not found", "text/plain")
        if p.startswith(("/otto-api/admin", "/otto-api/whop")):
            return self._out(404, "Not found", "text/plain")
        if p.startswith(("/auth/", "/billing/", "/otto-api/", "/otto-track", "/otto-onboard", "/otto-email/", "/hooks/stripe")):
            return self._proxy()
        self._out(404, "Not found", "text/plain")

    # ---- the stand-ins' pages and the test controls
    def sim_get(self, p, q):
        one = lambda k: (q.get(k) or [""])[0]
        if p == "/sim/google/auth":
            return self._out(200, google_page(one("state"), one("nonce"), one("code_challenge"), one("redirect_uri")), extra_csp=PAGE_CSP)
        if p.startswith("/sim/pay/"):
            return self._out(200, pay_page(p.rsplit("/", 1)[1]), extra_csp=PAGE_CSP)
        if p == "/sim/tools":
            return self._out(200, tools_page(one("msg")), extra_csp=PAGE_CSP)
        if p.startswith("/sim/mail/"):
            return self.mail(p.rsplit("/", 1)[1])
        self._out(404, "Not found", "text/plain")

    def sim_post(self, p):
        form = dict(urllib.parse.parse_qsl(self._body().decode(errors="replace")))
        if p == "/sim/google/auth":
            em = (form.get("email") or "").strip().lower()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", em):
                return self._out(200, google_page(form.get("state"), form.get("nonce"), form.get("code_challenge"),
                                                  form.get("redirect_uri"), "Enter an e-mail address."), extra_csp=PAGE_CSP)
            sub = str(int(hashlib.sha256(em.encode()).hexdigest()[:16], 16))
            claims = FG.claims_for(em, sub, form.get("nonce") or "", name=(form.get("name") or "").strip() or None)
            code = GOOGLE.issue(form.get("code_challenge") or "", FG.jwt(claims, GOOGLE.key))
            return self._redirect(ORIGIN + "/auth/google/callback?" + urllib.parse.urlencode({"code": code, "state": form.get("state") or ""}))
        if p.startswith("/sim/pay/"):
            return self.pay(p.rsplit("/", 1)[1], form)
        if p == "/sim/tools":
            return self._redirect("/sim/tools?" + urllib.parse.urlencode({"msg": tool(form)}))
        self._out(404, "Not found", "text/plain")

    def pay(self, sid, form):
        s = STRIPE.sessions.get(sid)
        if not s:
            return self._out(200, shell("Checkout", "<div class=card><p>This checkout has expired. Go back to Billing and choose a plan again.</p></div>"),
                             extra_csp=PAGE_CSP)
        pr = s["_params"]
        if form.get("go") == "cancel":
            return self._redirect(pr.get("cancel_url") or ORIGIN + "/billing.html")
        session, sub = STRIPE.complete(sid)
        for etype, obj in (("checkout.session.completed", session), ("customer.subscription.created", sub)):
            if obj:
                hook(STRIPE.event(etype, obj))
        if sub and sub.get("status") == "active":
            hook(STRIPE.event("invoice.paid", STRIPE.invoice(sub["id"], reason="subscription_create")))
        self._redirect((pr.get("success_url") or ORIGIN + "/billing.html").replace("{CHECKOUT_SESSION_ID}", sid))

    def mail(self, name):
        f = WS / "outbox" / name
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.eml", name) or not f.is_file():
            return self._out(404, "Not found", "text/plain")
        msg = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        part = msg.get_body(("html", "plain"))
        body = part.get_content() if part else ""
        if part and part.get_content_type() == "text/plain":
            body = f"<pre style='white-space:pre-wrap;font:14px/1.5 ui-monospace,monospace;padding:24px'>{esc(body)}</pre>"
        head = (f"<div style='font:13px/1.5 -apple-system,system-ui,sans-serif;padding:12px 20px;background:#f2f2f4;color:#1d1d1f;border-bottom:1px solid #ddd'>"
                f"<b style='color:#1d1d1f'>To</b> <span style='color:#1d1d1f'>{esc(msg['To'])}</span> &nbsp; <b style='color:#1d1d1f'>Subject</b> "
                f"<span style='color:#1d1d1f'>{esc(msg['Subject'])}</span> &nbsp; <a style='color:#0071e3' href='/sim/tools'>Back to test controls</a></div>")
        self._out(200, head + body, extra_csp=PAGE_CSP)


def hook(evt):
    body = json.dumps(evt).encode()
    c = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=60)
    try:
        c.request("POST", "/hooks/stripe", body=body,
                  headers={"Content-Type": "application/json", "Stripe-Signature": otto_stripe.sign(WEBHOOK_SECRET, body)})
        r = c.getresponse()
        r.read()
        return r.status
    finally:
        c.close()


# ------------------------------------------------------------------ test controls

def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def users():
    return [u for u in (ap.load().get("users") or []) if isinstance(u, dict)]


def set_trial_end(email_addr, ends):
    """Move this user's trial (and the trial of the brand it started) so it ends at `ends`; the days before shift with it."""
    start = ends - timedelta(days=otto_trial.trial_days())
    with ap.transaction() as d:
        u = next((x for x in d.get("users") or [] if (x.get("email") or "").lower() == email_addr), None)
        if not u:
            return False
        u["trial_started_at"], u["trial_ends_at"] = iso(start), iso(ends)
        if u.get("status") == "expired" and ends > datetime.now(timezone.utc):
            u["status"] = "trial"
        for b in d.get("brands") or []:
            t = b.get("trial") if isinstance(b.get("trial"), dict) else None
            if t and t.get("user") == u.get("id") and not t.get("denied"):
                t["started_at"], t["ends_at"] = iso(start), iso(ends)
                if b.get("plan") == ap.trial_plan_id():
                    b["plan_until"] = ends.astimezone(ap.brand_tz(b)).date().isoformat()
    return True


def tool(form):
    act, who = form.get("act"), (form.get("user") or "").strip().lower()
    now = datetime.now(timezone.utc)
    log = []
    if act in ("day5", "day7", "day8"):
        ends = {"day5": now + timedelta(hours=47), "day7": now + timedelta(hours=23), "day8": now - timedelta(minutes=30)}[act]
        if not set_trial_end(who, ends):
            return f"No signed-up user {who}."
        otto_trial.run(now=now, out=log.append)
        label = {"day5": "day 5 (2 days left)", "day7": "day 7 (ends tomorrow)", "day8": "day 8 (trial over)"}[act]
        return f"{who}: trial moved to {label}. " + " ".join(log)[:400]
    if act == "report":
        bid = form.get("brand") or ""
        r = subprocess.run([sys.executable, "otto_report.py", "send", "--brand", bid, "--channel", "email", "--force", "--no-refresh"],
                           cwd=PLATFORM, capture_output=True, text=True, timeout=180)
        out = [x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip() != "fallback synced"]
        return f"07:35 report for {bid}: " + (" ".join(out[-3:]) if out else ("sent" if r.returncode == 0 else "failed"))[:400]
    if act == "trials":
        otto_trial.run(now=now, out=log.append)
        return "Trial job ran. " + (" ".join(log)[:400] or "Nothing to do.")
    if act == "reset":
        threading.Thread(target=lambda: (time.sleep(0.5), os.execv(sys.executable, [sys.executable, __file__, "--reset"])),
                         daemon=True).start()
        return "Starting over: the workspace is being emptied (nobody signed up). Reload in a few seconds."
    return "Unknown action."


# ------------------------------------------------------------------ pages

CSS = """
:root{--bg:#f5f5f7;--card:#fff;--ink:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--acc:#0071e3;--warn:#b25000;color-scheme:light}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;padding:32px 16px}
.wrap{max-width:720px;margin:0 auto;display:grid;gap:16px}
.tag{display:inline-block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--warn);border:1px solid #f0c9a0;background:#fff7ef;border-radius:999px;padding:2px 10px}
h1{font-size:28px;letter-spacing:-.02em;margin:4px 0 0;text-wrap:balance}h2{font-size:17px;margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px}
p{margin:0 0 8px;color:var(--mut)}label{display:grid;gap:4px;font-size:13px;color:var(--mut);margin-bottom:12px}
input,select{font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);width:100%}
button{font:inherit;font-weight:600;border:0;border-radius:999px;padding:10px 18px;background:var(--acc);color:#fff;cursor:pointer}
button.gray{background:#e8e8ed;color:var(--ink)}.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:8px 6px;border-top:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:500;border-top:0}.num{font-variant-numeric:tabular-nums}.msg{background:#eef6ff;border-color:#b6d6fb;color:var(--ink)}
a{color:var(--acc)}
"""


def shell(title, inner):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><div class=wrap>{inner}</div></body></html>")


def google_page(state, nonce, challenge, redirect, err=""):
    return shell("Sign in (test)", f"""
<div><span class=tag>Test stand-in for Google</span><h1>Sign in with Google</h1></div>
<div class=card>
<p>On the live site this is Google's own account picker. Here you type the address you want to sign up with; Otto receives a
signed Google ID token for it exactly as it would from Google.</p>
{f"<p style='color:#c00'>{esc(err)}</p>" if err else ""}
<form method=post action="/sim/google/auth">
<label>E-mail<input name=email type=email required autofocus placeholder="you@yourbusiness.com" autocomplete=off></label>
<label>Name<input name=name placeholder="Your name"></label>
<input type=hidden name=state value="{esc(state)}"><input type=hidden name=nonce value="{esc(nonce)}">
<input type=hidden name=code_challenge value="{esc(challenge)}"><input type=hidden name=redirect_uri value="{esc(redirect)}">
<div class=row><button>Continue</button></div></form>
<p style="margin-top:12px">Each e-mail and each website domain gets one free trial. To try the sign-up again, use a new address
(or "Start over" on the <a href="/sim/tools">test controls</a>).</p></div>""")


def pay_page(sid):
    s = STRIPE.sessions.get(sid)
    if not s:
        return shell("Checkout", "<div class=card><p>This checkout has expired. Go back to Billing and choose a plan again.</p></div>")
    pr = s["_params"]
    price = pr.get("line_items[0][price]") or ""
    amount, interval = FS.PRICES.get(price, (0, None))
    trial_end = pr.get("subscription_data[trial_end]")
    when = ""
    if trial_end:
        when = (f"<p>Nothing is charged today. The first charge is on "
                f"{datetime.fromtimestamp(int(trial_end), timezone.utc):%-d %B %Y}, when the free trial ends.</p>")
    per = {"month": " / month", "year": " / year"}.get(interval or "", " once")
    plan = re.sub(r"_(m|y)$", "", price.replace("price_", "")).title()
    return shell("Checkout (test)", f"""
<div><span class=tag>Test stand-in for Stripe Checkout</span><h1>Otto {esc(plan)}</h1></div>
<div class=card>
<p style="font-size:32px;color:var(--ink);font-weight:600;letter-spacing:-.02em;margin:0" class=num>€{amount / 100:,.0f}<span style="font-size:15px;color:var(--mut);font-weight:400">{per} + VAT</span></p>
{when}
<p>{esc(s.get("customer_email") or "")}</p>
<p>On the live site this is Stripe's payment page. Here the card is Stripe's test card (Visa ending 4242); pressing Pay plays what
Stripe does: it creates the customer and the subscription and sends Otto the signed webhooks.</p>
<form method=post action="/sim/pay/{esc(sid)}" class=row>
<button name=go value=pay>Pay with test card 4242</button><button name=go value=cancel class=gray>Cancel</button></form></div>""")


def tools_page(msg=""):
    d = ap.load()
    now = datetime.now(timezone.utc)
    rows = []
    for u in users():
        end = otto_trial._dt(u.get("trial_ends_at")) if u.get("trial_ends_at") else None
        left = "—" if not end else ("over" if end <= now else f"{(end - now).total_seconds() / 86400:.1f} days")
        if u.get("status") == "active":
            left = "paid" + (f" · first charge {end:%-d %b}" if end and end > now else "")
        mine = [b.get("name") or b["id"] for b in d.get("brands") or []
                if (u.get("email") or "").lower() in [m.lower() for m in b.get("members") or []]]
        em = esc(u.get("email"))
        rows.append(f"<tr><td>{em}<br><span style='color:var(--mut)'>{esc(', '.join(mine) or 'no brand yet')}</span></td>"
                    f"<td>{esc(u.get('status'))}</td><td class=num>{left}</td><td><form method=post action='/sim/tools' class=row>"
                    f"<input type=hidden name=user value='{em}'>"
                    f"<button class=gray name=act value=day5>Day 5</button><button class=gray name=act value=day7>Day 7</button>"
                    f"<button class=gray name=act value=day8>Day 8 (ended)</button></form></td></tr>")
    users_t = ("<table><tr><th>Signed-up user</th><th>Status</th><th>Trial left</th><th>Jump to</th></tr>" + "".join(rows) + "</table>") \
        if rows else "<p>Nobody has signed up yet. Start on the landing page and press “Start free trial”.</p>"
    brands = [b for b in d.get("brands") or [] if isinstance(b, dict)]
    opts = "".join(f"<option value='{esc(b['id'])}'>{esc(b.get('name') or b['id'])} · {esc(b.get('plan') or '')}</option>" for b in brands)
    report = (f"<form method=post action='/sim/tools' class=row><select name=brand style='width:auto'>{opts}</select>"
              f"<button name=act value=report>Send report now</button></form>") if brands else "<p>No brand yet.</p>"
    ob = WS / "outbox"
    mrows = []
    for f in (sorted(ob.glob("*.eml"), reverse=True)[:40] if ob.is_dir() else []):
        try:
            m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
            mrows.append(f"<tr><td class=num>{esc(f.name[9:11])}:{esc(f.name[11:13])} UTC</td><td>{esc(m['To'])}</td>"
                         f"<td><a href='/sim/mail/{esc(f.name)}'>{esc(m['Subject'])}</a></td></tr>")
        except Exception:                     # noqa: BLE001
            pass
    mails_t = ("<table><tr><th>Time</th><th>To</th><th>Subject</th></tr>" + "".join(mrows) + "</table>") if mrows \
        else "<p>No e-mails yet. Reminders, the 07:35 report and approval e-mails land here (no mail service is connected).</p>"
    copy_on = (WS / "secrets" / "anthropic.json").is_file()
    copy_t = ("<p>The copywriter is on (Anthropic key from ~/otto-launch-keys): a new trial's first week is written and designed "
              "within minutes, then waits for approval in the app and in the 07:35 e-mail.</p>") if copy_on else \
        ("<p>No Anthropic key yet (~/otto-launch-keys/anthropic-key.txt), so a new trial's posts stay “drafting”. Save the key "
         "and restart the walkthrough to see the first week written and designed.</p>")
    return shell("Otto test controls", f"""
<div><span class=tag>Walkthrough only — not part of Otto</span><h1>Test controls</h1>
<p>Time travel for the free trial, the morning report on demand, and the e-mails Otto would have sent.</p></div>
{f"<div class='card msg'>{esc(msg)}</div>" if msg else ""}
<div class=card><h2>Where things are</h2>
<p><a href="/pilot-landing.html">Landing page</a> · <a href="/">Client app</a> · <a href="{ADMIN_ORIGIN}/">Owner console</a> (opens on 127.0.0.1, a separate host, like admin.)</p></div>
<div class=card><h2>Copywriter</h2>{copy_t}</div>
<div class=card><h2>Free trials</h2><p>Moves the trial's end date, then runs the hourly trial job (reminders, ending the trial).</p>{users_t}</div>
<div class=card><h2>07:35 morning report</h2><p>Sends today's report by e-mail now, to the brand's members.</p>{report}</div>
<div class=card><h2>E-mails (outbox)</h2>{mails_t}</div>
<div class=card><h2>Start over</h2><p>Empties this test workspace: nobody signed up, no brands.</p>
<form method=post action="/sim/tools"><button class=gray name=act value=reset>Start over</button></form></div>""")


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"Otto walkthrough on {ORIGIN}/pilot-landing.html  (console {ADMIN_ORIGIN}/, test controls {ORIGIN}/sim/tools)", flush=True)
    try:
        Server(("127.0.0.1", PORT), Front).serve_forever()
    finally:
        api_srv.shutdown()
