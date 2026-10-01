#!/usr/bin/env python3
"""One client's whole life through the real modules, together — the integration test the per-module suites cannot be.

A Dutch coffee roaster (koffiezon.nl) signs up on the public onboarding route, lands on Starter "not billed yet", pays for
Growth on Whop (signed webhook) and is linked by the owner, gets its month planned inside the plan's limits, has a disease
claim held by the NL / EU baselines, approves a post from the e-mail digest (GET shows, POST acts), is published through a
fake Graph with an unguessable, AI-marked image, gets its paid month planned (matrix preset from the plan, Google because
Growth has it), approves that plan from its e-mail and launches (one campaign, one ad set per angle), shows up in the owner
console (plan usage, e-mail health, heartbeats), sits out the kill switch, is downgraded to Starter (Google pauses), cancels
on Whop (plan none, everything pauses), gets the 14 / 3-day retention notices and is deleted 90 days later with an export —
while another client in the same data.json is never touched.

Stdlib unittest; the only network is the 127.0.0.1 API server started here; Meta, Google, the scanner and the renderer are
fakes; nothing outside a throwaway workspace (every OTTO_* path points into it, module-level paths are pinned).

  cd platform && python3 tests/test_journey.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, copy, email, email.policy, hashlib, http.server, io, json, os, re, shutil, sys, tempfile, threading
import time, unittest, urllib.error, urllib.parse, urllib.request, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-journey-test-"))
BASE = "https://app.otto.example/otto/"
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_PUBLIC_BASE": BASE, "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_LEADS": str(TMP / "leads.json"), "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"),
       "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_LOCKS": str(TMP / "locks"), "OTTO_EXPORTS": str(TMP / "exports"),
       "OTTO_MOTION_ROOT": str(TMP / "motion"), "OTTO_PLANS": str(TMP / "plans.json"), "OTTO_CRON_BIN": str(TMP / "bin"),
       "OTTO_OWNER_EMAIL": "owner@otto.example", "WHOP_WEBHOOK_SECRET": "ws_journey_secret_do_not_use"}
CLEAR = ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_DOMAIN", "OTTO_APP_URL", "OTTO_EMAIL_BASE",
         "OTTO_FALLBACK", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "WHOP_API_KEY", "WHOP_COMPANY_ID", "OTTO_RENDERER",
         "OTTO_CRON_NOW", "OTTO_TZ", "LEONARDO_API_KEY")
SITE, BID = "koffiezon.nl", "koffiezon"
EVA = "eva@koffiezon.nl"
GROWTH_WHOP = "plan_journey_growth"
MEMBERSHIP = "mem_journey_1"
TOKEN_NAME = re.compile(r"-[0-9a-f]{32}\.(?:jpe?g|png|mp4)$")

# a JPEG the provenance writer can parse (SOI, APP0 / JFIF, SOS … EOI); nothing here decodes pixels
JPEG = (b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34\x56\x78" * 8 + b"\xff\xd9")

STUB = "import sys\nprint('stub', ' '.join(sys.argv[1:]))\n"


def scan_doc():
    """What otto_scan would read on koffiezon.nl (canned: no network)."""
    return {"url": f"https://{SITE}", "final_url": f"https://{SITE}/", "scanned_at": "2026-09-29T10:00:00Z",
            "pages": [f"https://{SITE}/", f"https://{SITE}/over-ons"],
            "identity": {"title": "Koffie Zon | Specialty koffie uit Utrecht",
                         "description": "Versgebrande specialty koffie uit onze branderij in Utrecht, binnen 48 uur bij je thuis.",
                         "site_name": "Koffie Zon", "og_title": "", "og_image": None},
            "industry": "E-commerce & retail", "industry_candidates": [{"industry": "E-commerce & retail", "score": 40}],
            "languages": ["nl"], "platform": "Shopify",
            "visual": {"palette": [{"hex": "#6B3E26", "count": 5, "source": "css"}], "neutrals": [], "logo": None,
                       "fonts": ["Inter"], "theme_color": None},
            "socials": {}, "contact": {"emails": [], "phones": []},
            "commerce": {"currency": "EUR", "prices": ["12,50 €"], "promos": []},
            "trust": ["Elke dinsdag en vrijdag vers gebrand"], "quotes": [], "headings": ["Onze koffie"], "nav": ["Winkel"],
            "text_sample": ""}


def other_seed():
    """The other client in the same data file: every kind of record, none of which the journey may touch."""
    return {"brands": [{"id": "keep", "name": "Keep Cafe", "url": "keepcafe.example", "lang": "EN", "tz": "Europe/Dublin",
                        "status": "active", "plan": "starter", "approvals": "telegram", "countries": ["IE"],
                        "members": ["kim@keepcafe.example"], "pillars": ["Coffee"], "compliance": ""}],
            "posts": [{"id": "kc-001", "brand": "keep", "pillar": "Coffee", "platform": "fb", "hook": "Our flat white",
                       "status": "published", "slot": "2026-09-01T09:00", "image": "assets/posts/kc-001-" + "a" * 32 + ".jpg",
                       "remote_id": "PG_1"},
                      {"id": "kc-002", "brand": "keep", "pillar": "Coffee", "platform": "ig", "hook": "Autumn menu",
                       "status": "pending_approval", "slot": "2031-01-05T09:00"}],
            "recommendations": [{"id": "rec-001", "priority": "P1", "title": "Keep: film the latte art", "why": "w",
                                 "impact": "i", "cta": "c", "status": "proposed", "brand": "keep"}],
            "campaigns": [{"id": "cp-001", "brand": "keep", "network": "meta", "name": "Keep · Evergreen", "status": "draft",
                           "plan": "2031-01", "start": "2031-01-01", "end": "2031-01-31", "daily_budget": 10,
                           "currency_code": "EUR", "audience": {"countries": ["IE"]}, "creative": {}, "remote": {}}],
            "connections": [{"id": "meta-keep", "service": "Instagram + Facebook", "brand": "Keep Cafe", "status": "connected"}],
            "taste_log": [{"post": "kc-001", "brand": "keep", "pillar": "Coffee", "platform": "fb", "decision": "approve",
                           "via": "telegram", "ts": "2026-08-30T08:00:00Z"}],
            "metrics": {"keep": {"reach": 1200}}, "ads": {"keep": {"connections": {"meta": True}, "daily": {}}},
            "seq": {"id:kc": 2, "id:cp": 1, "id:rec": 1}}


def other_records(d):
    """Everything data.json holds about the other client (compared before and after the journey)."""
    return {"brand": next(b for b in d["brands"] if b["id"] == "keep"),
            "posts": [p for p in d.get("posts", []) if p.get("brand") == "keep"],
            "recs": [r for r in d.get("recommendations", []) if r.get("brand") == "keep"],
            "campaigns": [c for c in d.get("campaigns", []) if c.get("brand") == "keep"],
            "connections": [c for c in d.get("connections", []) if c.get("id") == "meta-keep"],
            "taste": [t for t in d.get("taste_log", []) if t.get("brand") == "keep"],
            "metrics": (d.get("metrics") or {}).get("keep"), "ads": (d.get("ads") or {}).get("keep")}


def other_files():
    out = {}
    for root in (TMP / "brands" / "keep", TMP / "assets", TMP / "public", TMP / "secrets"):
        for f in sorted(root.rglob("*")) if root.exists() else []:
            if f.is_file() and ("keep" in str(f.relative_to(TMP)) or "kc-001" in f.name):
                out[str(f.relative_to(TMP))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


class FakeGraph:
    """Meta Graph stand-in for publishing and ads: records (method, path, params); ids are sequential."""

    def __init__(self):
        self.calls, self.n = [], 1000

    def _id(self, prefix=""):
        self.n += 1
        return f"{prefix}{self.n}"

    def graph(self, method, path, token, **params):
        self.calls.append((method, path, dict(params)))
        last = path.rsplit("/", 1)[-1]
        if method == "GET" and params.get("fields") == "status_code":
            return {"status_code": "FINISHED"}
        if method == "GET" and path.startswith("act_") and "/" not in path:
            return {"currency": "EUR"}
        if method == "POST" and last == "media":
            return {"id": self._id("C")}
        if method == "POST" and last in ("media_publish", "feed", "videos"):
            return {"id": self._id("M")}
        if method == "POST" and last == "photos":
            return {"id": self._id("P"), "post_id": self._id("PG_")}
        if method == "POST" and last == "adimages":
            return {"images": {params.get("name", "x"): {"hash": self._id("h")}}}
        if method == "POST" and last in ("campaigns", "adsets", "adcreatives", "ads", "advideos"):
            return {"id": self._id(last[:3].upper())}
        if method == "POST" and "status" in params:
            return {"success": True}
        return {"id": self._id()}

    def posts(self, suffix):
        return [p for m, path, p in self.calls if m == "POST" and path.endswith(suffix)]


class FakeGoogle:
    def __init__(self):
        self.calls = []

    def call(self, g, path, body):
        self.calls.append((path, body))
        if path == "googleAds:searchStream":
            return []
        if path == "googleAds:mutate":
            return {"mutateOperationResponses": [{"campaignResult": {"resourceName": "customers/1234567890/campaigns/77"}}
                                                 if "campaignOperation" in op else {"x": {}} for op in body["mutateOperations"]]}
        return {}


def fake_render(calls):
    def render(template, data, out_path, size=(1080, 1350), brand=None, budget=6000, strict=True):
        calls.append((template, dict(data), tuple(size)))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(JPEG)
        return str(out_path)
    return render


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        out = fn(*a, **kw)
    quiet.last = buf.getvalue()
    return out


def brand_month(offset=0):
    """(YYYY-MM, first day) of the brand's local month + offset."""
    loc = datetime.now(timezone.utc).astimezone(ap.brand_tz({"tz": "Europe/Amsterdam"})).date().replace(day=1)
    for _ in range(offset):
        loc = (loc + timedelta(days=32)).replace(day=1)
    return loc.strftime("%Y-%m"), loc


_SAVED, S = {}, {}
MODS = ("ap", "otto_paths", "otto_scan", "otto_strategy", "otto_plan", "otto_compliance", "otto_onboard", "otto_api", "otto_admin",
        "otto_whop", "otto_email", "otto_publish", "otto_ads", "otto_creative", "otto_styles", "otto_cron", "otto_retention",
        "otto_provenance", "genvisuals", "otto_telegram", "otto_track", "otto_render")
PINS = [("ap", "DATA", "data.json"), ("ap", "HTML", "index.html"), ("ap", "BRANDS", "brands"), ("otto_paths", "ASSETS", "assets"),
        ("otto_paths", "BASE", None), ("otto_scan", "BRANDS", "brands"), ("otto_strategy", "BRANDS", "brands"),
        ("otto_plan", "BRANDS", "brands"), ("otto_ads", "BRANDS", "brands"), ("otto_ads", "SECRETS", "secrets"),
        ("otto_creative", "BRANDS", "brands"), ("otto_creative", "OUT", "assets/ads"), ("genvisuals", "BRANDS", "brands"),
        ("genvisuals", "OUT", "assets/posts"), ("otto_publish", "SECRETS", "secrets"), ("otto_publish", "LOG", "publish.log"),
        ("otto_publish", "BASE", None), ("otto_telegram", "SECRETS", "secrets"),
        ("otto_telegram", "STATE", ".telegram-state.json"), ("otto_api", "LOG", "actions.log"), ("otto_cron", "BIN", "bin"),
        ("otto_cron", "SECRETS", "secrets"), ("otto_render", "BRANDS", "brands")]


def setUpModule():
    for d in ("brands/keep/assets", "secrets", "assets/posts", "public/posts", "bin", "outbox", "motion"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    plans = json.loads((PLATFORM / "plans.json").read_text())
    plans["plans"]["growth"]["whop_plan_ids"] = [GROWTH_WHOP]                 # Growth is sold on Whop; Starter is not (yet)
    (TMP / "plans.json").write_text(json.dumps(plans, indent=1))
    (TMP / "data.json").write_text(json.dumps(other_seed(), ensure_ascii=False, indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    (TMP / "brands" / "keep" / "compliance.json").write_text(json.dumps({"banned": ["cheap"]}))
    for root in ("assets", "public"):
        (TMP / root / "posts" / ("kc-001-" + "a" * 32 + ".jpg")).write_bytes(JPEG)
    (TMP / "secrets" / "meta-keep.json").write_text(json.dumps({"access_token": "KEEP", "page_id": "PG", "ad_account_id": "act_keep"}))
    (TMP / "secrets" / f"meta-{BID}.json").write_text(json.dumps({"access_token": "EAAB-zon", "page_id": "PGZON", "ig_user_id": "IGZON",
                                                                   "ad_account_id": "act_zon"}))
    (TMP / "secrets" / f"google-{BID}.json").write_text(json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r",
                                                                     "developer_token": "d", "customer_id": "123-456-7890"}))
    for name in ("otto_publish.py", "otto_email.py", "otto_ads.py"):
        (TMP / "bin" / name).write_text(STUB)
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    g = globals()
    for m in MODS:
        g[m] = __import__(m)
    _SAVED["pins"] = [(m, a, getattr(g[m], a)) for m, a, _ in PINS]
    for m, a, rel in PINS:
        setattr(g[m], a, BASE if rel is None else TMP / rel)
    # fakes: the scanner (no network), Meta, Google, the renderer, background spawns
    S["graph"], S["google"], S["render"], S["spawned"] = FakeGraph(), FakeGoogle(), [], []
    _SAVED["fakes"] = (otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_ads.google_call, otto_render.render,
                       otto_whop.SPAWN, otto_admin.SPAWN, otto_ads.notify)
    otto_scan.scan = lambda url, pages=5, page_limit=1_200_000, deadline=None: (
        copy.deepcopy(scan_doc()) if otto_onboard.host_key(url) == SITE else {"url": url, "error": "HTTP 403"})
    otto_scan.host_status = lambda url: "ok"
    otto_publish.graph = S["graph"].graph
    otto_ads.google_call = S["google"].call
    otto_render.render = fake_render(S["render"])
    otto_whop.SPAWN = lambda args: S["spawned"].append(list(args))
    otto_admin.SPAWN = lambda args, log: S["spawned"].append(list(args))
    otto_ads.notify = lambda text: True
    otto_ads._acct.clear()
    otto_api._snap_cache.clear()
    otto_email._rl.clear()
    otto_email._rl_global[:] = [0, 0]
    otto_onboard._rl_last.clear()                          # other suites' sign-ups within the hour must not rate-limit this one
    otto_onboard._public_creates.clear()
    S["srv"] = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
    threading.Thread(target=S["srv"].serve_forever, daemon=True).start()
    S["base"] = f"http://127.0.0.1:{S['srv'].server_address[1]}"
    S["other_before"] = other_records(ap.load())
    S["other_files"] = other_files()


def tearDownModule():
    if "srv" in S:
        S["srv"].shutdown(); S["srv"].server_close()
    if "fakes" in _SAVED:
        (otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_ads.google_call, otto_render.render,
         otto_whop.SPAWN, otto_admin.SPAWN, otto_ads.notify) = _SAVED["fakes"]
    g = globals()
    for m, a, v in _SAVED.get("pins", []):
        setattr(g[m], a, v)
    for k, v in _SAVED.get("env", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def api(path, method="GET", body=None, headers=None, raw=False):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        headers = dict({"Content-Type": "application/json"}, **(headers or {}))
    r = urllib.request.Request(S["base"] + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            data = x.read()
            return x.status, (data.decode() if raw else json.loads(data) if data else None)
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, (data.decode() if raw else json.loads(data) if data else None)
        except ValueError:
            return e.code, data.decode(errors="replace")


def admin(req):
    otto_api._snap_cache.clear()
    return api("/otto-api/admin", "POST", req)


def whop_event(etype, data, wid):
    body = json.dumps({"type": etype, "data": data}).encode()
    ts = str(int(time.time()))
    sig = otto_whop.sign(os.environ["WHOP_WEBHOOK_SECRET"], wid, ts, body)
    return api("/otto-api/whop", "POST", body, {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": sig,
                                                  "Content-Type": "application/json"})


def brand():
    return ap.brand(ap.load(), BID)


def outbox():
    d = TMP / "outbox"
    return sorted(d.glob("*.eml")) if d.is_dir() else []


def mail_links(f):
    msg = email.message_from_bytes(Path(f).read_bytes(), policy=email.policy.default)
    text = msg.get_body(("plain",)).get_content()
    return msg, text, dict(re.findall(r"^(Approve|Skip|Approve plan|Not now|Change)\s*:\s*(\S+)", text, re.M))


def one_tap(url):
    """The e-mail button as a phone uses it: GET shows the page (nothing happens), its one button POSTs the form."""
    q = urllib.parse.urlsplit(url)
    token = urllib.parse.parse_qs(q.query)["t"][0]
    code, page = api("/otto-email/act?t=" + urllib.parse.quote(token), raw=True)
    m = re.search(r'name="f" value="([^"]+)"', page or "")
    return code, page, token, (m.group(1) if m else None)


def post_form(token, nonce):
    body = urllib.parse.urlencode({"t": token, "f": nonce}).encode()
    origin = otto_email._origin(otto_email.action_base())
    return api("/otto-email/act", "POST", body, {"Content-Type": "application/x-www-form-urlencoded", "Origin": origin}, raw=True)


class Journey(unittest.TestCase):
    """The steps run in order and share state (S); a failed step stops the rest."""
    broken = None

    def setUp(self):
        if Journey.broken:
            self.skipTest(f"the journey broke at {Journey.broken}")

    def run(self, result=None):
        n = len((result.failures + result.errors) if result else [])
        out = super().run(result)
        if result is not None and len(result.failures + result.errors) > n:
            Journey.broken = self._testMethodName
        return out

    # ------------------------------------------------------------------ 1 · public onboarding → Starter, not billed
    def test_01_public_onboarding(self):
        origin = next(iter(otto_api.ALLOWED_ORIGINS))
        answers = {"goal": "sales", "budget": "1000_3000", "never_say": "goedkoop", "approvals": "email", "tz": "Europe/Amsterdam",
                   "channels": {"meta": True, "google_ads": True}, "corrections": {"language": "nl"}}
        code, out = api("/otto-onboard", "POST", {"site": SITE, "answers": answers},
                         {"Origin": origin, "X-Real-IP": "198.51.100.77"})
        self.assertEqual(code, 200, out)
        self.assertEqual((out["brand"], out["created"]), (BID, True))
        b = brand()
        self.assertEqual((b["status"], b["plan"], b.get("plan_billing")), ("onboarding", "starter", "not_billed"))
        self.assertEqual((b["countries"], b["tz"], b.get("currency"), b["approvals"]), (["NL"], "Europe/Amsterdam", "EUR", "email"))
        self.assertNotIn("members", b, "the public route has nobody signed in to add")
        pv = ap.plan_view(ap.load(), BID)
        self.assertTrue(pv["not_billed"] and pv["id"] == "starter" and pv["paid_ads"])
        comp = out["compliance"]
        self.assertEqual(comp["countries"], ["NL"])
        self.assertTrue({"eu-disease-claim", "nl-influencer-disclosure"} <= {r["id"] for r in comp["baselines"]}, comp)
        self.assertEqual(json.loads((TMP / "brands" / BID / "compliance.json").read_text())["banned"], ["goedkoop"])
        # the public route never updates an existing brand
        code, out = api("/otto-onboard", "POST", {"site": "https://www." + SITE, "answers": {}},
                         {"Origin": origin, "X-Real-IP": "198.51.100.78"})
        self.assertEqual(code, 409, out)
        # cron: an onboarding brand sits the jobs out until it is paid for
        tasks, _ = otto_cron.plan("publish", ap.load(), force=True, only=BID)
        self.assertEqual(tasks[0].skip, "onboarding")

    # ------------------------------------------------------------------ 2 · Whop webhook + owner link → Growth
    def test_02_whop_growth_and_link(self):
        mem = {"id": MEMBERSHIP, "status": "active", "plan": {"id": GROWTH_WHOP}, "user": {"email": EVA, "name": "Eva"},
               "created_at": int(time.time()) - 60, "renewal_period_end": int(time.time()) + 30 * 86400, "currency": "eur",
               "metadata": {"website": SITE}}
        code, out = whop_event("membership.activated", mem, "msg_journey_1")
        self.assertEqual(code, 200, out)
        self.assertEqual(ap.plan_of(ap.load(), BID)["id"], "starter", "an unlinked membership changes no brand")
        code, out = whop_event("membership.activated", mem, "msg_journey_1")
        self.assertTrue(out.get("duplicate"), "Whop retries: each webhook id is processed once")
        code, out = admin({"action": "link_customer", "customer": MEMBERSHIP, "brand": BID})
        self.assertEqual(code, 200, out)
        self.assertIn("starter → growth", out["message"])
        b = brand()
        self.assertEqual(b["plan"], "growth")
        self.assertNotIn("plan_billing", b, "a running membership pays for it: billed")
        self.assertEqual(b["members"], [EVA], "the payer can sign in")
        self.assertEqual(b["plan_history"][-1]["via"], "whop")
        self.assertEqual(b["status"], "active", "a paid, linked brand leaves onboarding (otherwise no job ever runs for it)")
        tasks, _ = otto_cron.plan("publish", ap.load(), force=True, only=BID)
        self.assertIsNone(tasks[0].skip)
        self.assertTrue(ap.entitled(ap.load(), BID, "google") and ap.limit(ap.load(), BID, "ad_matrix_preset") == "launch")
        # tenant isolation: the client sees their brand, never the other client
        code, view = api("/otto-api/data", headers={"X-Real-IP": "203.0.113.9", "X-Otto-User": EVA})
        self.assertEqual(code, 200, view)
        self.assertEqual([x["id"] for x in view["brands"]], [BID])
        self.assertFalse([p for p in view["posts"] if p["brand"] != BID])
        self.assertNotIn("plan_billing", view["brands"][0])
        self.assertEqual(view["brands"][0]["plan_view"]["id"], "growth")
        code, _ = api("/otto-api/decide", "POST", {"id": "kc-002", "decision": "approve"},
                       {"X-Real-IP": "203.0.113.9", "X-Otto-User": EVA, "Origin": next(iter(otto_api.ALLOWED_ORIGINS))})
        self.assertEqual(code, 404, "another client's post does not exist for this login")

    # ------------------------------------------------------------------ 3 · the month, inside the plan's limits
    def test_03_monthly_plan_within_limits(self):
        ym, first = brand_month(1)
        S["ym_next"] = ym
        with ap.transaction() as d:                      # three feed slots a day: more than Growth's 70 items a month
            ap.brand(d, BID)["slots"] = {day: ["08:00", "12:30", "19:00"] for day in otto_plan.DAYS}
        created = quiet(otto_plan.build, BID, ym, per_week=21)
        lim = ap.plan_of(ap.load(), BID)["limits"]
        self.assertEqual(len(created), lim["posts_per_month"], quiet.last)
        self.assertIn("allows 70 posts a month", quiet.last)
        reels = [p for p in created if p["format"] == "reel"]
        self.assertEqual(len(reels), lim["reels_per_month"])
        self.assertTrue(any(p["format"] == "story" for p in created), "Growth has stories")
        u = ap.plan_usage(ap.load(), BID, today=first)
        self.assertEqual((u["posts"], u["reels"]), (70, 8))
        self.assertIn("already has", str(self._exit(otto_plan.build, BID, ym)), "a month is planned once")

    def _exit(self, fn, *a):
        try:
            quiet(fn, *a)
        except SystemExit as e:
            return e.code
        return None

    # ------------------------------------------------------------------ 4 · compliance by country + the e-mail digest
    def test_04_compliance_and_email_digest(self):
        now = datetime.now(timezone.utc)
        soon = lambda h: (now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        with ap.transaction() as d:
            ok = ap.add_post(d, BID, "Coffee", "ig", soon(20), "Vers gebrand op dinsdag", format="post",
                             caption="Elke dinsdag branden we kleine batches. Bestel voor 22:00, morgen in huis.")
            bad = ap.add_post(d, BID, "Coffee", "fb", soon(26), "Gemberkoffie", format="post",
                              caption="Onze gemberkoffie helpt tegen hoofdpijn.")
            for p in (ok, bad):
                p["status"] = "pending_approval"
        S["ok"], S["bad"] = ok["id"], bad["id"]
        v = otto_compliance.check_post(ap.post(ap.load(), bad["id"]))
        self.assertEqual([x.get("id") for x in v], ["eu-disease-claim"])
        self.assertFalse(otto_compliance.check_post(ap.post(ap.load(), ok["id"])))
        # the AI image for the clean post (the genvisuals producer path: unguessable name, marked, then public)
        ai = {}
        ref = genvisuals.save_image(ok["id"], JPEG, ai)
        self.assertTrue(quiet(genvisuals._patch, ok["id"], {"image": ref, "media_ai": ai}))
        self.assertRegex(ref, r"^assets/posts/" + re.escape(ok["id"]) + TOKEN_NAME.pattern)
        self.assertTrue((TMP / "public" / "posts" / Path(ref).name).exists())
        self.assertEqual(ai[ref]["marked"], "xmp")
        S["image"] = ref
        tot = quiet(otto_email.send_cards, BID)
        self.assertEqual((tot["emails"], tot["posts"], tot["blocked"]), (1, 1, 1), quiet.last)
        d = ap.load()
        self.assertTrue(ap.post(d, ok["id"]).get("email_sent_at"))
        self.assertEqual(ap.post(d, bad["id"])["compliance_block"]["rules"], [v[0]["rule"]])
        self.assertTrue(any(r.get("post") == bad["id"] and r["title"].startswith("Compliance hold") for r in d["recommendations"]))
        files = outbox()
        self.assertEqual(len(files), 1)
        msg, text, links = mail_links(files[0])
        self.assertEqual(msg["To"], EVA)
        self.assertNotIn("hoofdpijn", text, "the held post never reaches the owner")
        self.assertIn(otto_paths.media_url(ref, BASE, verify=False), text)
        S["approve_url"] = links["Approve"]
        self.assertEqual(quiet(otto_email.send_cards, BID)["emails"], 0, "claimed and sent once")

    # ------------------------------------------------------------------ 5 · one tap: GET shows, POST acts
    def test_05_one_tap_approve(self):
        code, page, token, nonce = one_tap(S["approve_url"])
        self.assertEqual(code, 200, page)
        self.assertTrue(nonce, "no confirmation button on the page")
        self.assertEqual(ap.post(ap.load(), S["ok"])["status"], "pending_approval", "a GET (a mail scanner) never acts")
        code, page = post_form(token, nonce)
        self.assertEqual(code, 200, page)
        p = ap.post(ap.load(), S["ok"])
        self.assertEqual((p["status"], p["approved_via"]), ("approved", "email"))
        self.assertTrue(any(t["post"] == S["ok"] and t["via"] == "email" for t in ap.load()["taste_log"]))
        code, _ = post_form(token, nonce)
        self.assertEqual(code, 409, "each button works once")

    # ------------------------------------------------------------------ 6 · publish through the fake Graph
    def test_06_publish(self):
        with ap.transaction() as d:                      # its slot arrives
            ap.post(d, S["ok"])["slot"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        quiet(otto_publish.run, bid=BID, base=BASE)
        p = ap.post(ap.load(), S["ok"])
        self.assertEqual(p["status"], "published", quiet.last)
        self.assertTrue(p["remote_id"])
        media = [x for x in S["graph"].posts("/media") if x.get("image_url")]
        self.assertEqual(len(media), 1)
        url = media[0]["image_url"]
        self.assertTrue(url.startswith(BASE + "assets/posts/"), url)
        self.assertRegex(url, TOKEN_NAME, "published under an unguessable name")
        public = TMP / "public" / "posts" / url.rsplit("/", 1)[1]
        self.assertTrue(public.exists())
        self.assertTrue(otto_provenance.inspect(public)["generated"], "the public copy carries the AI mark")
        self.assertEqual(p["media_ai"][S["image"]]["source_type"], "trainedAlgorithmicMedia")
        self.assertFalse(otto_provenance.inspect(TMP / "public" / "posts" / ("kc-001-" + "a" * 32 + ".jpg"))["generated"])

    # ------------------------------------------------------------------ 7 · the paid plan
    def test_07_ads_plan(self):
        # the strategist's angles (what a matrix is built from)
        sp = TMP / "brands" / BID / "strategy.json"
        st = json.loads(sp.read_text())
        st["angles"] = [{"id": f"a{i}", "angle": t, "persona": "p1", "stage": s, "source": src, "status": "idea"} for i, (t, s, src) in enumerate([
            ("Supermarket beans sit on the shelf for months; ours are roasted this week", "cold", "competitor"),
            ("Bitter coffee at home is a stale-bean problem", "cold", "profile"),
            ("For people who grind their own beans every morning", "cold", "profile"),
            ("What a fresh-roast subscription tastes like after a month", "warm", "profile"),
            ("Subscription: pause or cancel anytime", "hot", "profile"),
            ("The winter roast, only while this harvest lasts", "hot", "profile")], 1)]
        sp.write_text(json.dumps(st, ensure_ascii=False))
        snap, ym_next = ap.load(), S["ym_next"]
        mx, new, line, _ = otto_ads.plan_matrix_for(BID, ym_next, snap, 40, "EUR")
        self.assertTrue(new and mx, line)
        self.assertEqual(mx["preset"], "launch", "Growth: the 6 × 6 launch matrix")
        cells = [c for a in mx["angles"] for c in a["ads"]]
        video = sum(1 for c in cells if c["format"] in ("video", "creator"))
        self.assertGreaterEqual(video / len(cells), otto_styles.PRESETS["launch"]["min_video_share"], line)
        self.assertEqual(otto_ads.plan_matrix_for(BID, ym_next, snap, 20, "EUR")[0]["preset"], "micro", "micro floor under ~€36/day")
        self.assertIsNone(otto_styles.load_matrix(BID, ym_next), "asking writes nothing")
        # this month's paid plan, with a ready matrix: one AI-photo cell, one on the client's own photo
        ym, _ = brand_month(0)
        S["ym_now"] = ym
        (TMP / "brands" / BID / "assets").mkdir(parents=True, exist_ok=True)
        (TMP / "brands" / BID / "assets" / "winkel.jpg").write_bytes(JPEG)              # the client's own shop photo
        P = ["Elke dinsdag vers gebrande bonen, binnen 48 uur bij je thuis.", "Specialty koffie uit onze eigen branderij in Utrecht."]
        otto_styles.save_matrix(BID, ym, {"brand": BID, "month": ym, "preset": "launch", "angles": [
            {"id": "a1", "name": "Vers gebrand", "family": "enemy", "source": "competitor", "stage": "cold", "cta": "SHOP_NOW",
             "headlines": ["Vers gebrand in Utrecht"], "primaries": P, "ads": [
                 {"id": "a1-editorial", "style": "editorial", "format": "image", "size": ["feed", "story"],
                  "data": {"headline": "Deze week gebrand", "photo": S["image"]}},
                 {"id": "a1-before_after", "style": "before_after", "format": "image", "size": "feed",
                  "data": {"before": "Bonen van maanden oud", "after": "Bonen van deze week"}}]},
            {"id": "a2", "name": "Thuis gemalen", "family": "identity", "source": "profile", "stage": "cold", "cta": "SHOP_NOW",
             "headlines": ["Voor wie zelf maalt"], "primaries": P, "ads": [
                 {"id": "a2-editorial", "style": "editorial", "format": "image", "size": "feed",
                  "data": {"headline": "Zelf malen, vers zetten", "photo": "winkel.jpg"}},
                 {"id": "a2-before_after", "style": "before_after", "format": "image", "size": "feed",
                  "data": {"before": "Koffie van de supermarkt", "after": "Koffie van de branderij"}}]}]})
        created = quiet(otto_ads.plan, BID, ym, 40.0)
        out = quiet.last
        nets = sorted({c["network"] for c in created})
        self.assertEqual(nets, ["google", "meta"], out)
        ever = next(c for c in created if "Evergreen" in c["name"])
        self.assertEqual(len(ever["creatives"]["concepts"]), 2, ever["creatives"].get("matrix"))
        self.assertTrue(all(c["status"] == "draft" and not c.get("compliance_hold") for c in created), created)
        rec = next(r for r in ap.load()["recommendations"] if r.get("brand") == BID and r.get("action") == "approve_plan")
        self.assertEqual(rec["plan"], ym)
        S["plan_rec"] = rec["id"]
        S["camps"] = {"meta": ever["id"], "google": next(c["id"] for c in created if c["network"] == "google")}

    # ------------------------------------------------------------------ 8 · approve the paid plan from the e-mail, launch
    def test_08_approve_plan_by_email_and_launch(self):
        before = set(outbox())
        tot = quiet(otto_email.send_recs, BID)
        self.assertGreaterEqual(tot["emails"], 1, quiet.last)
        plan_mail = [f for f in outbox() if f not in before and "-plan-" in f.name]
        self.assertEqual(len(plan_mail), 1, [f.name for f in outbox()])
        _, text, links = mail_links(plan_mail[0])
        code, page, token, nonce = one_tap(links["Approve plan"])
        self.assertEqual(code, 200, page)
        code, page = post_form(token, nonce)
        self.assertEqual(code, 200, page)
        d = ap.load()
        self.assertEqual(ap.rec(d, S["plan_rec"])["status"], "done")
        mine = [c for c in d["campaigns"] if c["brand"] == BID]
        self.assertTrue(all(c["status"] == "approved" and c["approved_via"] == "email" for c in mine), mine)
        quiet(otto_ads.launch, bid=BID, base=BASE)
        out = quiet.last
        d = ap.load()
        ever, goog = ap.campaign(d, S["camps"]["meta"]), ap.campaign(d, S["camps"]["google"])
        self.assertEqual((ever["status"], goog["status"]), ("live", "live"), out)
        self.assertEqual(ever["remote"]["structure"], "concepts")
        camps = [x for x in S["graph"].posts("/campaigns") if "Evergreen" in x["name"]]
        self.assertEqual(len(camps), 1, "one Meta campaign for the evergreen flight")
        self.assertEqual(camps[0]["daily_budget"], 4000, "CBO: €40/day on the campaign")
        adsets = [x for x in S["graph"].posts("/adsets") if "Evergreen" in x["name"]]
        self.assertEqual(len(adsets), 2, "one ad set per angle")
        self.assertEqual(ever["remote"]["ads"], 4)
        # the ad statics: unguessable, public, and AI-marked only where the photo was generated
        files = {f["file"] for con in ever["creatives"]["concepts"] for ad in con["ads"] for f in ad["files"]}
        self.assertTrue(files and all(TOKEN_NAME.search(f) for f in files), files)
        marked = {f: otto_provenance.inspect(TMP / "public" / f[len("assets/"):])["generated"] for f in files}
        self.assertTrue(all(v for f, v in marked.items() if "a1-editorial" in f), marked)
        self.assertFalse(any(v for f, v in marked.items() if "a2-" in f or "before_after" in f), marked)
        self.assertEqual(goog["remote"]["campaign"], "customers/1234567890/campaigns/77")

    # ------------------------------------------------------------------ 9 · the owner console + heartbeats
    def test_09_admin_snapshot(self):
        self.assertEqual(quiet(otto_cron.run, "publish", only=BID), 0, quiet.last)
        otto_api._snap_cache.clear()
        code, snap = api("/otto-api/admin/snapshot?days=30")
        self.assertEqual(code, 200, snap)
        row = next(b for b in snap["brands"] if b["id"] == BID)
        pv = ap.plan_view(ap.load(), BID)
        self.assertEqual((row["plan"]["id"], row["plan"]["usage"]), ("growth", pv["usage"]))
        self.assertGreater(row["plan"]["usage"]["ad_budget_eur"]["used"], 0)
        self.assertFalse(row["plan"]["not_billed"])
        self.assertEqual(row["approvals"]["channels"], ["email"])
        self.assertEqual(row["approvals"]["recipients"], 1)
        self.assertTrue(row["approvals"]["last_digest"] and row["approvals"]["last_plan"])
        self.assertIn("Approval e-mails wait in the outbox: no mail transport yet (otto-secrets/email.json)", row["issues"])
        self.assertEqual(row["campaigns"]["live"], 2)
        cron = next(c for c in snap["system"]["crons"] if c["job"] == "publish")
        self.assertEqual(cron["status"], "ok", cron)
        self.assertEqual(snap["revenue"]["customers"][0]["brand_id"], BID)
        email_setup = next(x for x in snap["setup"] if x["key"] == "email")
        self.assertIn("1 brand approve", email_setup["detail"])

    # ------------------------------------------------------------------ 10 · kill switch on / off
    def test_10_kill_switch(self):
        code, out = admin({"action": "kill_switch", "state": "on", "note": "journey"})
        self.assertEqual(code, 200, out)
        d = ap.load()
        live = [ap.campaign(d, i) for i in S["camps"].values()]
        self.assertTrue(live and all(c["status"] == "paused" and c["paused_by"] == "kill_switch" for c in live), live)
        with ap.transaction() as d:                      # an approved post comes due while everything is paused
            p = ap.post(d, S["bad"])
            p.update(status="approved", caption="Onze gemberkoffie, mild en kruidig.",
                     slot=(datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
            p.pop("compliance_block", None)
        n = len(S["graph"].calls)
        quiet(otto_publish.run, bid=BID, base=BASE)
        self.assertIn("PAUSED", quiet.last)
        self.assertEqual(ap.post(ap.load(), S["bad"])["status"], "approved")
        self.assertEqual(len(S["graph"].calls), n, "nothing reaches Meta under the kill switch")
        tasks, _ = otto_cron.plan("publish", ap.load(), force=True, only=BID)
        self.assertIn("kill switch", tasks[0].skip)
        code, out = admin({"action": "kill_switch", "state": "off"})
        self.assertEqual(code, 200, out)
        d = ap.load()
        self.assertEqual({ap.campaign(d, i)["status"] for i in (S["camps"]["meta"], S["camps"]["google"])}, {"live"})
        quiet(otto_publish.run, bid=BID, base=BASE)
        self.assertEqual(ap.post(ap.load(), S["bad"])["status"], "published", quiet.last)

    # ------------------------------------------------------------------ 11 · downgrade to Starter pauses Google
    def test_11_downgrade_to_starter(self):
        code, out = admin({"action": "plan", "brand": BID, "plan": "starter", "note": "client asked"})
        self.assertEqual(code, 200, out)
        d = ap.load()
        goog, ever = ap.campaign(d, S["camps"]["google"]), ap.campaign(d, S["camps"]["meta"])
        self.assertEqual((goog["status"], goog["paused_by"]), ("paused", "plan"))
        self.assertEqual(ever["status"], "live", "Starter still has Meta ads")
        self.assertTrue(any(path == "campaigns:mutate" for path, _ in S["google"].calls), "paused on Google, not only in data.json")
        self.assertEqual(out["plan"]["id"], "starter")
        mx = otto_ads.plan_matrix_for(BID, S["ym_next"], d, 40, "EUR")[0]
        self.assertEqual(mx["preset"], "micro", "Starter: the micro matrix whatever the budget")
        flights = quiet(otto_ads.plan, BID, S["ym_next"], 40.0, True)
        self.assertEqual({f["network"] for f in flights}, {"meta"}, "no Google on Starter")
        with self.assertRaises(otto_ads.LaunchError):
            quiet(otto_ads.resume, goog["id"])

    # ------------------------------------------------------------------ 12 · Whop cancellation → plan none
    def test_12_whop_cancellation(self):
        mem = {"id": MEMBERSHIP, "status": "canceled", "plan": {"id": GROWTH_WHOP}, "user": {"email": EVA},
               "canceled_at": int(time.time()), "updated_at": int(time.time()) + 5}
        code, out = whop_event("membership.deactivated", mem, "msg_journey_2")
        self.assertEqual(code, 200, out)
        self.assertEqual(out["plan"]["to"], "none", out)
        self.assertTrue(S["spawned"] and S["spawned"][-1][-1] == "guard", "live campaigns the plan no longer covers: guard now")
        quiet(otto_ads.guard)                                 # what the spawned guard does
        d = ap.load()
        ever = ap.campaign(d, S["camps"]["meta"])
        self.assertEqual((ever["status"], ever["paused_by"]), ("paused", "plan"), quiet.last)
        self.assertIn("no active plan", ap.paused(d, BID))
        self.assertTrue(any(r.get("brand") == BID and "membership ended" in r["title"] for r in d["recommendations"]))
        tasks, _ = otto_cron.plan("email-cards", d, force=True, only=BID)
        self.assertEqual(tasks[0].skip, "no active plan (membership ended)")
        self.assertEqual(otto_email.email_brands(d, None), [], "no e-mail for an ended plan")
        S["ended"] = datetime.now(timezone.utc).date()

    # ------------------------------------------------------------------ 13 · retention: notices, then deletion with export
    def test_13_retention(self):
        ended = S["ended"]
        self.assertEqual(quiet(otto_retention.run, ended + timedelta(days=10)), 0, quiet.last)
        self.assertNotIn("notice", quiet.last)
        before = set(outbox())
        self.assertEqual(quiet(otto_retention.run, ended + timedelta(days=76)), 0, quiet.last)
        self.assertIn("14-day notice", quiet.last)
        self.assertEqual(quiet(otto_retention.run, ended + timedelta(days=87)), 0, quiet.last)
        self.assertIn("3-day notice", quiet.last)
        notices = [f for f in outbox() if f not in before and "-retention-" in f.name]
        self.assertEqual(len(notices), 2, "the owner is told twice, by e-mail")
        self.assertIsNotNone(brand(), "nothing is deleted before the day")
        self.assertEqual(quiet(otto_retention.run, ended + timedelta(days=90)), 0, quiet.last)
        self.assertIn("DELETED", quiet.last)
        d = ap.load()
        self.assertIsNone(ap.brand(d, BID))
        for k in ("posts", "campaigns", "taste_log", "connections"):
            self.assertFalse([x for x in d.get(k, []) if x.get("brand") == BID or str(x.get("id", "")).endswith("-" + BID)], k)
        self.assertFalse((TMP / "brands" / BID).exists())
        self.assertFalse([f for f in (TMP / "secrets").iterdir() if BID in f.name])
        mine = [S["ok"], S["bad"]] + list(S["camps"].values())
        self.assertFalse([f for root in ("assets", "public") for f in (TMP / root).rglob("*")
                          if f.is_file() and any(f.name.startswith(x + "-") for x in mine)], "its media, ad statics included")
        hb = json.loads((TMP / "heartbeats.json").read_text())
        self.assertNotIn(BID, hb["jobs"]["publish"].get("brands") or {})
        self.assertNotIn(BID, (json.loads((TMP / ".email-state.json").read_text()).get("brands") or {}))
        zips = sorted((TMP / "exports").glob(f"otto-export-{BID}-*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as z:
            man = json.loads(z.read("manifest.json"))
            self.assertEqual(man["brand"], BID)
            self.assertIn(f"media/{S['image']}", z.namelist())
            self.assertTrue(json.loads(z.read("data.json"))["lists"]["posts"])
        self.assertTrue(json.loads((TMP / "billing.json").read_text())["customers"][MEMBERSHIP], "billing records stay")

    # ------------------------------------------------------------------ 14 · the other client, untouched
    def test_14_other_client_untouched(self):
        self.assertEqual(other_records(ap.load()), S["other_before"])
        self.assertEqual(other_files(), S["other_files"])
        self.assertTrue(otto_compliance.rules("keep")["patterns"], "its compliance.json still applies")


if __name__ == "__main__":
    unittest.main(verbosity=2)
