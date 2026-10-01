#!/usr/bin/env python3
"""Owner console tests: landing analytics (otto_track), the legacy Whop founders (otto_whop through otto_billing), the console
snapshot and controls (otto_admin: Stripe setup items, billing from otto_billing — Stripe itself is tests/test_stripe.py), the
kill switch in otto_publish / otto_ads launch, and the /otto-track, /otto-api/whop, /otto-api/admin routes.
Stdlib unittest, no network, nothing outside a throwaway workspace.

  cd platform && python3 tests/test_admin.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites

Under discover, test_engine has already imported ap / otto_publish / otto_ads / otto_api with its own OTTO_* paths, so
setUpModule pins every module-level path this suite touches to its own workspace and tearDownModule puts them back.
"""
import base64, contextlib, hashlib, hmac, http.server, io, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest
import urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-admin-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_LEADS": str(TMP / "leads.json")}
CLEAR = ("WHOP_API_KEY", "WHOP_WEBHOOK_SECRET", "WHOP_COMPANY_ID", "OTTO_ADMIN_USERS", "OTTO_DOMAIN", "OTTO_STRIPE_SECRET_KEY",
         "OTTO_STRIPE_PUBLISHABLE_KEY", "OTTO_STRIPE_WEBHOOK_SECRET")
ORIGIN = "https://dash.monyflow.work"
SECRET = "ws_test_secret_do_not_use"


def seed():
    today = datetime.now(timezone.utc).date().isoformat()
    return {"brands": [{"id": "alpha", "name": "Alpha Dental", "url": "alpha-dental.example", "lang": "EN", "tz": "UTC",
                        "status": "active", "pillars": ["A"], "compliance": ""},
                       {"id": "beta", "name": "Beta Cafe", "url": "beta-cafe.example", "lang": "EN", "tz": "UTC",
                        "status": "active", "pillars": ["A"], "compliance": ""}],
            "posts": [], "recommendations": [], "connections": [],
            "campaigns": [{"id": "cp-001", "brand": "alpha", "network": "meta", "name": "Consults", "status": "draft", "start": today,
                           "end": today, "daily_budget": 10, "objective": "OUTCOME_LEADS", "creative": {}}]}


def reset_workspace():
    for name in ("data.json", "events.jsonl", "billing.json", "leads.json", "actions.log", "api-errors.log", "publish.log", ".track-salt"):
        f = TMP / name
        if f.exists():
            f.unlink()
    (TMP / "data.json").write_text(json.dumps(seed(), ensure_ascii=False, indent=2))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    shutil.rmtree(TMP / "secrets", ignore_errors=True)
    (TMP / "secrets").mkdir()
    for b in ("alpha", "beta"):
        (TMP / "secrets" / f"meta-{b}.json").write_text(json.dumps({"access_token": "T", "page_id": "P", "ig_user_id": "IG",
                                                                    "ad_account_id": "act_1"}))
    otto_track._buckets.clear()
    otto_track._global[:] = [float(otto_track.GLOBAL_PER_MIN), time.time()]
    otto_track._salt.update(day=None, salt=None)
    otto_api._snap_cache.clear()


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


_SAVED = {}


def setUpModule():
    (TMP / "brands").mkdir(exist_ok=True)
    _SAVED["repo_data"] = (PLATFORM / "data.json").exists()
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_track, otto_whop, otto_admin, otto_publish, otto_ads, otto_api
    import ap, otto_track, otto_whop, otto_admin, otto_publish, otto_ads, otto_api     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_publish.SECRETS, otto_publish.LOG, otto_ads.SECRETS, otto_ads.BRANDS,
                       otto_api.LOG)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_publish.SECRETS = otto_ads.SECRETS = TMP / "secrets"
    otto_publish.LOG, otto_api.LOG, otto_ads.BRANDS = TMP / "publish.log", TMP / "actions.log", TMP / "brands"
    reset_workspace()


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_publish.SECRETS, otto_publish.LOG, otto_ads.SECRETS, otto_ads.BRANDS,
     otto_api.LOG) = _SAVED["paths"]
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
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def req(self, path, method="GET", body=None, headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=10) as x:
                raw = x.read()
                return x.status, dict(x.headers), (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, dict(e.headers), json.loads(raw) if raw else None
            except ValueError:
                return e.code, dict(e.headers), None


def lines():
    f = TMP / "events.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


# ============================================================================================
# landing analytics
# ============================================================================================

class TrackTest(_Server, unittest.TestCase):
    H = {"User-Agent": "Mozilla/5.0 test", "X-Country": "de"}

    def setUp(self):
        reset_workspace()

    def ingest(self, body, ip="203.0.113.7", headers=None):
        return otto_track.ingest(json.dumps(body).encode() if not isinstance(body, bytes) else body, ip, headers or self.H)

    def test_batch_is_stored_without_the_raw_ip(self):
        code, _ = self.ingest({"p": "/pilot-landing.html", "s": "abc123def", "r": "www.google.com",
                               "u": {"source": "newsletter", "medium": "email", "term": "anna@example.com"}, "dv": "mobile",
                               "ev": [{"e": "view"}, {"e": "scroll", "d": 50}, {"e": "section", "id": "pricing"},
                                      {"e": "cta", "id": "get_started@pricing"}, {"e": "scan_start", "domain": "HTTPS://www.Example.COM/about?x=1"},
                                      {"e": "scan_result", "domain": "example.com", "ok": True}, {"e": "faq_open", "q": "what-do-i-need-to-bring"}]})
        self.assertEqual(code, 204)
        raw = (TMP / "events.jsonl").read_text()
        self.assertNotIn("203.0.113.7", raw)
        self.assertNotIn("anna@example.com", raw, "an e-mail-like utm value must be dropped")
        rows = lines()
        self.assertEqual([r["e"] for r in rows], ["view", "scroll", "section", "cta", "scan_start", "scan_result", "faq_open"])
        self.assertTrue(all(len(r["v"]) == 16 and r["v"] == rows[0]["v"] for r in rows))
        self.assertTrue(all(raw_line.startswith('{"ts":"') for raw_line in raw.splitlines()))
        view = rows[0]
        self.assertEqual((view["r"], view["dv"], view["cc"], view["u"]), ("google.com", "mobile", "DE", {"source": "newsletter", "medium": "email"}))
        self.assertNotIn("r", rows[1], "referrer / utm / device only ride on the view")
        self.assertEqual(rows[4]["domain"], "example.com")
        self.assertIs(rows[5]["ok"], True)
        self.assertEqual(os.stat(TMP / ".track-salt").st_mode & 0o777, 0o600)

    def test_validation(self):
        self.assertEqual(self.ingest({"p": "/x", "ev": [{"e": "purchase"}]})[0], 400)            # not allowlisted
        self.assertEqual(self.ingest({"p": "https://evil/x", "ev": [{"e": "view"}]})[0], 400)    # path must be a path
        self.assertEqual(self.ingest({"p": "/x", "ev": [{"e": "view"}] * 21})[0], 400)
        self.assertEqual(self.ingest(b"not json")[0], 400)
        self.assertEqual(self.ingest(b"[1]")[0], 400)
        self.assertEqual(self.ingest(b"{" + b" " * 5000 + b"}")[0], 413)
        code, _ = self.ingest({"p": "/x", "ev": [{"e": "view"}, {"e": "scroll", "d": 33}, {"e": "scan_start", "domain": "localhost"},
                                                 {"e": "scan_start", "domain": "10.0.0.1"}, {"e": "cta", "id": "<script>"},
                                                 {"e": "section", "id": "pricing", "extra": "x" * 50}]})
        self.assertEqual(code, 204)
        rows = lines()
        self.assertEqual([r["e"] for r in rows], ["view", "section"], "invalid events are dropped, valid ones kept")
        self.assertNotIn("extra", rows[1], "unknown fields are never stored")

    def test_rate_limit_per_client(self):
        codes = [self.ingest({"p": "/x", "ev": [{"e": "section", "id": f"s{i}"}]}, ip="198.51.100.1")[0] for i in range(70)]
        self.assertIn(429, codes)
        self.assertLessEqual(codes.count(204), otto_track.RATE_PER_MIN)
        self.assertEqual(self.ingest({"p": "/x", "ev": [{"e": "view"}]}, ip="198.51.100.2")[0], 204, "another client is not limited")

    def test_do_not_track_and_gpc_keep_only_an_anonymous_view(self):
        body = {"p": "/pilot-landing.html", "r": "google.com", "dv": "mobile", "ev": [{"e": "view"}, {"e": "scan_start", "domain": "example.com"}]}
        self.assertEqual(self.ingest(body, headers={"DNT": "1", "User-Agent": "x", "X-Country": "DE"})[0], 204)
        self.assertEqual(self.ingest(body, headers={"Sec-GPC": "1"})[0], 204)
        self.assertEqual(self.ingest(dict(body, anon=1))[0], 204)
        self.assertEqual(self.ingest({"p": "/x", "ev": [{"e": "cta", "id": "get_started@nav"}]}, headers={"DNT": "1"})[0], 204)
        rows = lines()
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertEqual(set(r), {"ts", "e", "p", "anon"})
            self.assertEqual(r["e"], "view")

    def test_visitor_id_is_stable_within_a_day_and_changes_with_the_salt(self):
        a = otto_track.visitor_id("1.2.3.4", "UA")
        self.assertEqual(a, otto_track.visitor_id("1.2.3.4", "UA"))
        self.assertNotEqual(a, otto_track.visitor_id("1.2.3.5", "UA"))
        (TMP / ".track-salt").write_text(json.dumps({"day": "2000-01-01", "salt": "0" * 64}))
        otto_track._salt.update(day=None, salt=None)
        self.assertNotEqual(a, otto_track.visitor_id("1.2.3.4", "UA"), "a new day → a new salt → a new id")
        self.assertNotEqual(json.loads((TMP / ".track-salt").read_text())["salt"], "0" * 64)

    def test_read_events_seeks_to_the_start_date(self):
        f = TMP / "events.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with f.open("w") as fh:
            for i in range(6000):
                ts = (base + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                fh.write(json.dumps({"ts": ts, "e": "view", "v": f"{i:016x}", "p": "/x"}, separators=(",", ":")) + "\n")
        got = otto_track.read_events("2026-04-01")
        want = sum(1 for i in range(6000) if (base + timedelta(minutes=30 * i)).strftime("%Y-%m-%d") >= "2026-04-01")
        self.assertEqual(len(got), want)
        self.assertTrue(got[0]["ts"].startswith("2026-04-01"))
        self.assertEqual(len(otto_track.read_events()), 6000)

    def test_http_route(self):
        body = json.dumps({"p": "/pilot-landing.html", "ev": [{"e": "view"}]}).encode()
        code, h, _ = self.req("/otto-track", "POST", body, {"Content-Type": "text/plain;charset=UTF-8", "Origin": ORIGIN, "X-Real-IP": "192.0.2.9"})
        self.assertEqual(code, 204)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        self.assertEqual(self.req("/otto-track", "POST", body, {"Content-Type": "text/plain", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/otto-track", "POST", body, {"Content-Type": "text/html"})[0], 415)
        self.assertEqual(self.req("/otto-track", "POST", b"x" * 5000, {"Content-Type": "text/plain"})[0], 413)
        self.assertNotIn("192.0.2.9", (TMP / "events.jsonl").read_text())
        self.assertEqual(len(lines()), 1)


# ============================================================================================
# Whop
# ============================================================================================

def signed(body, secret=SECRET, wid="msg_1", ts=None):
    ts = str(int(ts if ts is not None else time.time()))
    return {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": otto_whop.sign(secret, wid, ts, body),
            "Content-Type": "application/json"}


def whop_json(**kw):
    (TMP / "secrets" / "whop.json").write_text(json.dumps(kw))


def event(etype, data, eid):
    return {"id": eid, "type": etype, "api_version": "v1", "timestamp": "2026-09-29T10:00:00Z", "data": data}


MEMBER = {"id": "mem_A1", "status": "active", "created_at": "2026-09-20T10:00:00Z", "updated_at": "2026-09-20T10:00:00Z",
          "renewal_period_end": None, "cancel_at_period_end": False, "currency": "eur",
          "plan": {"id": "plan_joHl1qsZoiJc9"}, "user": {"id": "user_1", "email": "anna@alpha-dental.example", "name": "Anna"}}
PAYMENT = {"id": "pay_1", "status": "paid", "substatus": "succeeded", "total": 197.0, "currency": "eur",
           "created_at": "2026-09-20T10:00:05Z", "paid_at": "2026-09-20T10:00:06Z", "membership": {"id": "mem_A1", "status": "active"},
           "plan": {"id": "plan_joHl1qsZoiJc9"}, "user": {"email": "anna@alpha-dental.example"}, "billing_reason": "one_time"}


class WhopTest(_Server, unittest.TestCase):
    def setUp(self):
        reset_workspace()

    def test_signature(self):
        body = b'{"type":"payment.succeeded"}'
        h = signed(body)
        self.assertEqual(otto_whop.verify(body, h, [SECRET]), (True, "ok"))
        self.assertFalse(otto_whop.verify(body + b" ", h, [SECRET])[0], "one byte changed")
        self.assertFalse(otto_whop.verify(body, h, ["ws_other"])[0])
        self.assertFalse(otto_whop.verify(body, signed(body, ts=time.time() - 600), [SECRET])[0], "replayed after 5 minutes")
        self.assertFalse(otto_whop.verify(body, {"webhook-id": "x"}, [SECRET])[0])
        self.assertTrue(otto_whop.verify(body, {k.upper(): v for k, v in h.items()}, [SECRET])[0], "header names are case-insensitive")
        key = base64.b64encode(b"raw-key-bytes").decode()                # vanilla Standard Webhooks whsec_<base64>
        ts = str(int(time.time()))
        sig = base64.b64encode(hmac.new(b"raw-key-bytes", f"m.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
        self.assertTrue(otto_whop.verify(body, {"webhook-id": "m", "webhook-timestamp": ts, "webhook-signature": "v0,x v1," + sig},
                                         ["whsec_" + key])[0])

    def test_not_connected(self):
        self.assertEqual(otto_whop.webhook(b"{}", signed(b"{}"))[0], 503)
        with self.assertRaises(otto_whop.NotConnected):
            otto_whop.backfill(fetch=lambda url, key: self.fail("no network without a key"))

    def test_events_become_customer_state(self):
        whop_json(otto_webhook_secret=SECRET)
        def send(evt):
            body = json.dumps(evt).encode()
            return otto_whop.webhook(body, signed(body, wid=evt["id"]))
        self.assertEqual(send(event("membership.activated", MEMBER, "msg_1"))[0], 200)
        self.assertEqual(send(event("payment.succeeded", PAYMENT, "msg_2"))[0], 200)
        code, out = send(event("payment.succeeded", PAYMENT, "msg_2"))
        self.assertTrue(out.get("duplicate"), "a retried delivery is processed once")
        rows = otto_whop.customer_rows()
        self.assertEqual(len(rows), 1)
        c = rows[0]
        self.assertEqual((c["status"], c["plan"], c["mrr_eur"], c["ltv_eur"], c["email"]), ("active", "Founding pilot", 0, 197.0, "anna@alpha-dental.example"))
        fail = dict(PAYMENT, id="pay_2", status="open", substatus="failed", paid_at=None, created_at="2026-09-25T10:00:00Z")
        send(event("payment.failed", fail, "msg_3"))
        self.assertEqual(otto_whop.load()["payments"]["pay_2"]["status"], "failed")
        gone = dict(MEMBER, status="canceled", canceled_at="2026-09-28T09:00:00Z", updated_at="2026-09-28T09:00:00Z")
        send(event("membership.deactivated", gone, "msg_4"))
        c = otto_whop.customer_rows()[0]
        self.assertEqual((c["status"], c["canceled_at"], c["renews"]), ("canceled", "2026-09-28T09:00:00Z", None))
        late = dict(MEMBER, status="active", updated_at="2026-09-21T00:00:00Z")      # an older delivery arriving last
        send(event("membership.activated", late, "msg_5"))
        self.assertEqual(otto_whop.customer_rows()[0]["status"], "canceled")
        # a renewal plan carries MRR; a drafted checkout is not a customer
        whop_json(otto_webhook_secret=SECRET, plans={"plan_m": {"name": "Growth", "type": "renewal", "price": 149, "currency": "EUR", "period_days": 30}})
        send(event("membership.activated", dict(MEMBER, id="mem_B", plan={"id": "plan_m"}, user={"email": "b@beta-cafe.example"}), "msg_6"))
        send(event("membership.activated", dict(MEMBER, id="mem_C", status="drafted"), "msg_7"))
        rows = {c["id"]: c for c in otto_whop.customer_rows()}
        self.assertEqual(rows["mem_B"]["mrr_eur"], 149.0)
        self.assertNotIn("mem_C", rows)
        self.assertEqual(os.stat(TMP / "billing.json").st_mode & 0o777, 0o600)

    def test_http_webhook_needs_the_signature_not_an_origin(self):
        whop_json(otto_webhook_secret=SECRET)
        body = json.dumps(event("membership.activated", MEMBER, "msg_h1")).encode()
        code, h, out = self.req("/otto-api/whop", "POST", body, signed(body, wid="msg_h1"))
        self.assertEqual((code, out["ok"]), (200, True))
        self.assertIn("mem_A1", otto_whop.load()["customers"])
        bad = self.req("/otto-api/whop", "POST", body, dict(signed(body, wid="msg_h2"), **{"webhook-signature": "v1,AAAA"}))
        self.assertEqual(bad[0], 401)
        self.assertIn("401 /otto-api/whop", (TMP / "api-errors.log").read_text())
        self.assertNotIn(body.decode(), (TMP / "api-errors.log").read_text(), "a refused body is never logged")

    def test_backfill_pages_and_plans(self):
        whop_json(api_key="k_test", company_id="biz_T")
        calls = []
        pages = {"memberships": [{"data": [MEMBER], "page_info": {"has_next_page": True, "end_cursor": "c1"}},
                                 {"data": [dict(MEMBER, id="mem_Z", plan={"id": "plan_x"})], "page_info": {"has_next_page": False}}],
                 "payments": [{"data": [PAYMENT], "page_info": {"has_next_page": False}}]}

        def fetch(url, key):
            calls.append(url)
            self.assertEqual(key, "k_test")
            if "/plans/" in url:
                return {"id": "plan_x", "title": "Starter", "plan_type": "renewal", "renewal_price": 69, "currency": "eur", "billing_period": 30}
            kind = "memberships" if "/memberships?" in url else "payments"
            self.assertIn("account_id=biz_T", url)
            return pages[kind].pop(0)
        counts = otto_whop.backfill(fetch=fetch)
        self.assertEqual(counts, {"memberships": 2, "payments": 1, "plans": 1})
        self.assertIn("after=c1", calls[1])
        rows = {c["id"]: c for c in otto_whop.customer_rows()}
        self.assertEqual((rows["mem_Z"]["plan"], rows["mem_Z"]["mrr_eur"]), ("Starter", 69.0))
        self.assertIsNotNone(otto_whop.load()["last_backfill_at"])


# ============================================================================================
# the snapshot
# ============================================================================================

def ts_days_ago(n, hour=10):
    d = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=n)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        reset_workspace()

    def fixture(self):
        t = ts_days_ago(2)
        events = [
            {"ts": t, "e": "view", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "r": "google.de", "dv": "mobile", "cc": "DE"},
            {"ts": t, "e": "scroll", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "d": 50},
            {"ts": t, "e": "section", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "id": "pricing"},
            {"ts": t, "e": "scan_start", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "domain": "alpha-dental.example"},
            {"ts": t, "e": "scan_result", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "domain": "alpha-dental.example", "ok": True},
            {"ts": t, "e": "cta", "v": "a" * 16, "s": "s1", "p": "/pilot-landing.html", "id": "get_started@pricing"},
            {"ts": t, "e": "view", "v": "b" * 16, "s": "s2", "p": "/pilot-landing.html", "u": {"source": "newsletter", "medium": "email"}, "dv": "desktop"},
            {"ts": t, "e": "cta", "v": "b" * 16, "s": "s2", "p": "/pilot-landing.html", "id": "get_started@nav"},
            {"ts": t, "e": "view", "p": "/pilot-landing.html", "anon": 1},
            {"ts": ts_days_ago(40), "e": "view", "v": "c" * 16, "s": "s3", "p": "/pilot-landing.html"},    # previous window
        ]
        billing = otto_whop.empty()
        billing["customers"] = {
            "mem_1": {"id": "mem_1", "status": "active", "plan_id": "plan_joHl1qsZoiJc9", "email": "anna@alpha-dental.example", "started": ts_days_ago(1)},
            "mem_2": {"id": "mem_2", "status": "drafted", "plan_id": "plan_joHl1qsZoiJc9", "started": ts_days_ago(1)},
            "mem_3": {"id": "mem_3", "status": "canceled", "plan_id": "plan_m", "email": "x@gmail.com", "started": ts_days_ago(50),
                      "canceled_at": ts_days_ago(3)}}
        billing["payments"] = {"pay_1": {"id": "pay_1", "membership": "mem_1", "status": "paid", "amount": 197, "currency": "EUR",
                                         "amount_eur": 197.0, "at": ts_days_ago(1)},
                               "pay_2": {"id": "pay_2", "membership": "mem_3", "status": "failed", "amount": 149, "currency": "EUR",
                                         "amount_eur": 149.0, "at": ts_days_ago(4), "email": "x@gmail.com"}}
        d = seed()
        now_slot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        d["posts"] = [{"id": "al-001", "brand": "alpha", "platform": "fb", "status": "failed", "slot": now_slot, "hook": "h", "error": "Graph 190"},
                      {"id": "al-002", "brand": "alpha", "platform": "ig", "status": "pending_approval", "slot": now_slot, "hook": "h2",
                       "tg_sent_at": ts_days_ago(3)}]
        d["brands"][1]["paused"] = {"at": ts_days_ago(0), "by": "max"}
        d["recommendations"] = [{"id": "rec-2", "priority": "P2", "title": "later", "status": "proposed", "created_at": ts_days_ago(1)},
                                {"id": "rec-1", "priority": "P0", "title": "now", "status": "proposed", "created_at": ts_days_ago(0)},
                                {"id": "rec-3", "priority": "P0", "title": "done", "status": "done"}]
        overlay = {"d:alpha-dental.example": {"status": "contacted", "note": "called"}}
        sysinfo = {"logs": {"publish.log": {"mtime": otto_admin.fmt(datetime.now(timezone.utc) - timedelta(minutes=5)), "last": "nothing due"},
                            "insights.log": {"mtime": ts_days_ago(30), "last": "old"}},
                   "secrets": {"meta-alpha.json": True, "telegram.json": True}, "plans": dict(otto_whop.PLANS, plan_m={"name": "M", "type": "renewal", "price": 149}),
                   "billing_meta": {"webhook_secret": True}}
        return d, events, billing, overlay, sysinfo

    def test_build_counts_the_funnel_and_joins_leads_to_customers(self):
        s = otto_admin.build(*self.fixture(), window=30)
        steps = {x["key"]: x["n"] for x in s["funnel"]["steps"]}
        self.assertEqual(steps, {"visitors": 3, "scanned": 1, "get_started": 2, "checkouts": 2, "paying": 1, "onboarded": 1})
        self.assertEqual(s["kpis"]["visitors"]["prev"], 1)
        self.assertEqual(s["kpis"]["scans"]["value"], 1)
        self.assertEqual((s["kpis"]["customers"]["value"], s["kpis"]["churn"]["value"]), (1, 1))
        leads = {r["id"]: r for r in s["leads"]["rows"]}
        lead = leads["d:alpha-dental.example"]
        self.assertEqual((lead["paid"], lead["stage"], lead["status"], lead["note"], lead["source"]), (True, "paid", "contacted", "called", "Google"))
        anon = [r for r in s["leads"]["rows"] if r["id"].startswith("v:")]
        self.assertEqual(len(anon), 1, "the visitor who clicked Get started without scanning is a lead too")
        self.assertEqual(anon[0]["source"], "newsletter · email")
        T = s["traffic"]
        self.assertEqual((T["visitors"], T["anonymous"], T["pricing_views"]), (3, 1, 1))
        self.assertEqual(T["scroll"][1], {"depth": 50, "loads": 1, "share": 50.0})
        R = s["revenue"]
        self.assertEqual((R["paying"], R["open_checkouts"], R["revenue_30d_eur"], len(R["failed_payments_30d"])), (1, 1, 197.0, 1))
        self.assertEqual(R["customers"][0]["email"], "a•••@alpha-dental.example", "e-mails leave the server masked")
        self.assertNotIn("anna@", json.dumps(s))
        brands = {b["id"]: b for b in s["brands"]}
        self.assertEqual(brands["beta"]["health"], "blocked")
        self.assertEqual(brands["alpha"]["health"], "attention")
        self.assertEqual(brands["alpha"]["customers"], ["mem_1"], "matched to the brand by e-mail domain")
        self.assertGreater(brands["alpha"]["pending_oldest_h"], 48)
        self.assertEqual(brands["alpha"]["connections"]["meta"], "connected")
        self.assertEqual(brands["beta"]["connections"]["meta"], "missing")
        self.assertEqual(brands["alpha"]["campaign_list"][0]["currency"], "EUR", "every campaign row says its currency")
        self.assertEqual([r["id"] for r in s["recommendations"]["items"]], ["rec-1", "rec-2"])
        crons = {c["job"]: c["status"] for c in s["system"]["crons"]}
        self.assertEqual((crons["publish"], crons["insights"], crons["ads"]), ("ok", "stale", "never"))
        self.assertEqual(s["system"]["publisher"]["failed"][0]["id"], "al-001")

    def test_snapshot_from_disk_never_contains_a_secret(self):
        whop_json(api_key="k_SECRET_VALUE", otto_webhook_secret="ws_SECRET_VALUE", company_id="biz_T")
        (TMP / "secrets" / "stripe.json").write_text(json.dumps({"secret_key": "sk_test_SECRET_VALUE", "publishable_key": "pk_test_x",
                                                                 "webhook_secrets": ["whsec_SECRET_VALUE"], "ref_secret": "SECRET_VALUE" * 4}))
        (TMP / "secrets" / "meta-alpha.json").write_text(json.dumps({"access_token": "EAAG_SECRET_VALUE", "ad_account_id": "act_1"}))
        otto_track.ingest(json.dumps({"p": "/pilot-landing.html", "ev": [{"e": "view"}]}).encode(), "192.0.2.1", {"User-Agent": "x"})
        s = otto_admin.snapshot(window=7)
        blob = json.dumps(s)
        self.assertNotIn("SECRET_VALUE", blob)
        self.assertNotIn("192.0.2.1", blob)
        setup = {x["key"]: x["status"] for x in s["setup"]}
        self.assertEqual((setup["stripe_keys"], setup["stripe_webhook"], setup["whop_legacy"], setup["analytics"]),
                         ("connected", "waiting", "optional", "connected"))
        self.assertNotIn("whop_api", setup, "no Whop sync any more: the founders are a read-only list")
        self.assertEqual(s["window"], 7)
        self.assertEqual(s["traffic"]["visitors"], 1)

    def test_webhook_urls_match_the_proxy(self):
        # Caddy takes Stripe's webhook only at https://<domain>/hooks/stripe (and the legacy Whop one at /hooks/whop) and answers
        # 404 for /otto-api/* on the apex: the console must tell the owner exactly those URLs
        how = lambda key: next(x for x in otto_admin.snapshot()["setup"] if x["key"] == key)["how"]
        self.assertIn(f"URL: {otto_admin.PUBLIC_BASE}/hooks/stripe ", how("stripe_webhook"), "without OTTO_DOMAIN: the public base's host")
        self.assertNotIn("nginx", json.dumps(otto_admin.snapshot()["setup"]), "no setup text talks about nginx any more")
        os.environ["OTTO_DOMAIN"] = "otto.example"
        try:
            self.assertIn("URL: https://otto.example/hooks/stripe ", how("stripe_webhook"))
            self.assertIn("https://otto.example/hooks/whop", how("whop_legacy"))
        finally:
            os.environ.pop("OTTO_DOMAIN", None)
        caddy = (PLATFORM.parent / "infra" / "Caddyfile").read_text()
        self.assertIn("handle /hooks/stripe", caddy)
        self.assertIn("handle /billing/*", caddy)
        self.assertIn("handle /hooks/whop", caddy)
        self.assertIn("rewrite * /otto-api/whop", caddy)

    def test_empty_workspace_says_not_connected(self):
        s = otto_admin.snapshot()
        self.assertEqual(s["funnel"]["steps"][0]["n"], 0)
        self.assertFalse(s["revenue"]["connected"])
        setup = {x["key"]: x["status"] for x in s["setup"]}
        self.assertEqual((setup["stripe_keys"], setup["stripe_webhook"]), ("missing", "missing"))
        self.assertIn("Payments aren't set up yet", next(x for x in s["setup"] if x["key"] == "stripe_keys")["detail"])

    def test_sample_is_labelled_and_invented(self):
        s = otto_admin.sample_snapshot(window=30)
        self.assertTrue(s["sample"])
        self.assertTrue(all(b["url"].endswith(".example") for b in s["brands"]))
        self.assertTrue(all(r["domain"] is None or r["domain"].endswith(".example") for r in s["leads"]["rows"]))
        self.assertGreater(s["funnel"]["steps"][0]["n"], 0)

    def test_admin_html_embeds_the_sample(self):
        html = (PLATFORM / "admin.html").read_text()
        import re
        m = re.search(r'<script id="sample-snapshot" type="application/json">(.*?)</script>', html, re.S)
        blob = json.loads(m.group(1))
        self.assertEqual(set(blob), {"7", "30", "90"})
        self.assertTrue(all(v["sample"] for v in blob.values()))
        self.assertIn("assets/platform.css", html)

    def test_cli_snapshot_json(self):
        env = dict(os.environ, **ENV)
        r = subprocess.run([sys.executable, str(PLATFORM / "otto_admin.py"), "snapshot", "--json", "--days", "7"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["window"], 7)


# ============================================================================================
# kill switch: otto_publish + otto_ads launch
# ============================================================================================

class KillSwitchTest(unittest.TestCase):
    def setUp(self):
        reset_workspace()
        self.calls = []
        self._graph, self._launch_meta = otto_publish.graph, otto_ads.launch_meta
        n = [0]

        def graph(method, path, token, **params):
            self.calls.append(path)
            n[0] += 1
            return {"id": f"remote-{n[0]}", "post_id": f"remote-{n[0]}"}
        otto_publish.graph = graph
        otto_ads.launch_meta = lambda d, c, m, base, persist=None: self.calls.append("launch:" + c["id"]) or {"campaign_id": "C1", "done": True}

    def tearDown(self):
        otto_publish.graph, otto_ads.launch_meta = self._graph, self._launch_meta

    def add_post(self, bid, pid):
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        with ap.transaction(sync=False) as d:
            d["posts"].append({"id": pid, "brand": bid, "pillar": "A", "platform": "fb", "hook": "Hello there", "caption": "Hello there",
                               "status": "approved", "slot": slot})

    def status(self, pid):
        return ap.post(ap.load(), pid)["status"]

    def test_kill_switch_blocks_publishing_until_resumed(self):
        self.add_post("alpha", "al-100")
        otto_admin.act({"action": "kill_switch", "state": "on", "note": "incident"}, "max")
        self.assertIn("kill switch", ap.paused(ap.load()))
        quiet(otto_publish.run)
        self.assertEqual((self.status("al-100"), self.calls), ("approved", []), "nothing published, nothing marked missed")
        otto_admin.act({"action": "kill_switch", "state": "off"}, "max")
        quiet(otto_publish.run)
        self.assertEqual(self.status("al-100"), "published")
        self.assertTrue(self.calls)
        log = (TMP / "actions.log").read_text()
        self.assertIn("admin max kill-switch on", log)
        self.assertIn('note="incident"', log)
        self.assertIn("admin max kill-switch off", log)

    def test_paused_brand_is_skipped_others_publish(self):
        self.add_post("alpha", "al-101")
        self.add_post("beta", "be-101")
        otto_admin.act({"action": "pause_brand", "brand": "beta"}, "max")
        quiet(otto_publish.run)
        self.assertEqual((self.status("al-101"), self.status("be-101")), ("published", "approved"))
        self.assertEqual(ap.brand(ap.load(), "beta")["status"], "paused")
        otto_admin.act({"action": "resume_brand", "brand": "beta"}, "max")
        self.assertEqual(ap.brand(ap.load(), "beta")["status"], "active")
        self.assertNotIn("paused", ap.brand(ap.load(), "beta"))

    def test_switch_flipped_mid_run_stops_the_post_before_meta(self):
        self.add_post("alpha", "al-102")
        orig = otto_publish.creds

        def creds(bid):                                   # the owner hits the switch while this run is already working
            otto_admin.act({"action": "kill_switch", "state": "on"}, "max")
            return orig(bid)
        otto_publish.creds = creds
        try:
            quiet(otto_publish.run)
        finally:
            otto_publish.creds = orig
        self.assertEqual((self.status("al-102"), self.calls), ("approved", []))

    def campaigns(self, rows):
        with ap.transaction(sync=False) as d:
            d["campaigns"] = rows
        (TMP / "secrets" / "google-beta.json").write_text(json.dumps({"client_id": "x", "client_secret": "y", "refresh_token": "z",
                                                                      "developer_token": "t", "customer_id": "123"}))

    def fake_networks(self, meta_fails=()):
        """Meta through the publisher's graph fake, Google through otto_ads.google_call: both record every status change."""
        self.status = []
        orig = (otto_publish.graph, otto_ads.google_call)

        def graph(method, path, token, **params):
            if path in meta_fails:
                raise otto_publish.GraphError("Graph 100: campaign is locked")
            self.status.append(("meta", path, params.get("status")))
            return {"success": True}

        def google_call(g, path, body):
            op = body["operations"][0]["update"]
            self.status.append(("google", op["resourceName"], op["status"]))
            return {"results": [{}]}
        otto_publish.graph, otto_ads.google_call = graph, google_call
        self.addCleanup(lambda: setattr(otto_publish, "graph", orig[0]) or setattr(otto_ads, "google_call", orig[1]))

    def test_kill_switch_pauses_live_campaigns_and_resumes_only_its_own(self):
        today = datetime.now(timezone.utc).date()
        end, gone = (today + timedelta(days=9)).isoformat(), (today - timedelta(days=1)).isoformat()
        base = {"objective": "OUTCOME_LEADS", "daily_budget": 10, "start": (today - timedelta(days=5)).isoformat(), "end": end}
        self.campaigns([dict(base, id="cp-001", brand="alpha", network="meta", name="A", status="live", remote={"campaign_id": "M1"}),
                        dict(base, id="cp-002", brand="beta", network="google", name="B", status="live",
                             remote={"campaign": "customers/123/campaigns/9"}),
                        dict(base, id="cp-003", brand="alpha", network="meta", name="C", status="paused", paused_by="manual",
                             remote={"campaign_id": "M3"}),
                        dict(base, id="cp-004", brand="beta", network="meta", name="D", status="live", remote={"campaign_id": "M4"}),
                        dict(base, id="cp-005", brand="alpha", network="meta", name="E", status="live", remote={"campaign_id": "M5"}),
                        dict(base, id="cp-006", brand="alpha", network="meta", name="F", status="draft")])
        self.fake_networks(meta_fails=("M4",))
        out = quiet(otto_admin.act, {"action": "kill_switch", "state": "on", "note": "incident"}, "max")
        self.assertEqual((sorted(out["paused_campaigns"]), out["failed_campaigns"]), (["cp-001", "cp-002", "cp-005"], ["cp-004"]))
        self.assertIn("Live campaigns paused: 3 of 4", out["message"])
        self.assertEqual(sorted(self.status), [("google", "customers/123/campaigns/9", "PAUSED"), ("meta", "M1", "PAUSED"),
                                               ("meta", "M5", "PAUSED")])
        d = ap.load()
        st = {c["id"]: (c["status"], c.get("paused_by")) for c in d["campaigns"]}
        self.assertEqual(st, {"cp-001": ("paused", "kill_switch"), "cp-002": ("paused", "kill_switch"), "cp-003": ("paused", "manual"),
                              "cp-004": ("live", None), "cp-005": ("paused", "kill_switch"), "cp-006": ("draft", None)})
        self.assertTrue(any(r["priority"] == "P0" and r.get("campaign_id") == "cp-004" for r in d["recommendations"]),
                        "a campaign that could not be paused becomes an urgent recommendation")
        # the flight of cp-005 ends while everything is off
        with ap.transaction(sync=False) as d:
            ap.campaign(d, "cp-005")["end"] = gone
        self.status.clear()
        out = quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.assertEqual(sorted(out["resumed_campaigns"]), ["cp-001", "cp-002"])
        self.assertIn("Campaigns the switch paused are live again: 2 of 3. 1 ended meanwhile.", out["message"])
        self.assertIn("paused before the switch stay paused", out["message"])
        self.assertEqual(sorted(self.status), [("google", "customers/123/campaigns/9", "ENABLED"), ("meta", "M1", "ACTIVE")])
        st = {c["id"]: c["status"] for c in ap.load()["campaigns"]}
        self.assertEqual(st, {"cp-001": "live", "cp-002": "live", "cp-003": "paused", "cp-004": "live", "cp-005": "ended", "cp-006": "draft"})
        log = (TMP / "actions.log").read_text()
        self.assertIn("admin max kill-switch on live=4 failed=1", log)
        self.assertIn("admin max kill-switch off resumed=2 ended=1 kept=0 failed=0", log)

    def test_a_brand_paused_during_the_switch_keeps_its_campaigns_paused(self):
        today = datetime.now(timezone.utc).date()
        self.campaigns([{"id": "cp-001", "brand": "beta", "network": "meta", "name": "A", "status": "live", "objective": "OUTCOME_LEADS",
                         "daily_budget": 5, "start": today.isoformat(), "end": (today + timedelta(days=3)).isoformat(),
                         "remote": {"campaign_id": "M1"}}])
        self.fake_networks()
        quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
        quiet(otto_admin.act, {"action": "pause_brand", "brand": "beta"}, "max")
        out = quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.assertIn("1 stay paused with their brand", out["message"])
        c = ap.campaign(ap.load(), "cp-001")
        self.assertEqual((c["status"], c["paused_by"]), ("paused", "brand"))
        quiet(otto_admin.act, {"action": "resume_brand", "brand": "beta"}, "max")
        quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
        quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.assertEqual(ap.campaign(ap.load(), "cp-001")["status"], "paused", "a later switch cycle does not resume it either")
        self.assertEqual([x for x in self.status if x[2] == "ACTIVE"], [])

    def test_a_resume_that_fails_is_filed_and_the_campaign_stays_paused(self):
        today = datetime.now(timezone.utc).date()
        self.campaigns([{"id": "cp-001", "brand": "alpha", "network": "meta", "name": "A", "status": "live", "objective": "OUTCOME_LEADS",
                         "daily_budget": 5, "start": today.isoformat(), "end": (today + timedelta(days=3)).isoformat(),
                         "remote": {"campaign_id": "M1"}}])
        self.fake_networks()
        quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
        self.fake_networks(meta_fails=("M1",))
        out = quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.assertEqual(out["failed_campaigns"], ["cp-001"])
        d = ap.load()
        self.assertEqual(ap.campaign(d, "cp-001")["status"], "paused")
        self.assertTrue(any(r.get("campaign_id") == "cp-001" and r["title"].startswith("Resume campaign") for r in d["recommendations"]))

    def test_a_launch_racing_the_switch_never_stays_live(self):
        with ap.transaction(sync=False) as d:
            ap.campaign(d, "cp-001")["status"] = "approved"
        quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
        self.assertIsNone(otto_ads._claim("cp-001"), "the claim re-checks the switch inside its transaction")
        quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.fake_networks()

        def launch_meta(d, c, m, base, persist=None):          # the owner hits the switch while Meta is creating the campaign
            quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
            return {"campaign_id": "M9", "done": True}
        otto_ads.launch_meta = launch_meta
        quiet(otto_ads.launch)
        c = ap.campaign(ap.load(), "cp-001")
        self.assertEqual((c["status"], c["paused_by"]), ("paused", "kill_switch"))
        self.assertIn(("meta", "M9", "PAUSED"), self.status)

    def test_kill_switch_and_brand_pause_block_ad_launches(self):
        with ap.transaction(sync=False) as d:
            ap.campaign(d, "cp-001")["status"] = "approved"
        otto_admin.act({"action": "kill_switch", "state": "on"}, "max")
        quiet(otto_ads.launch)
        c = ap.campaign(ap.load(), "cp-001")
        self.assertEqual((c["status"], c.get("launching_at"), self.calls), ("approved", None, []))
        otto_admin.act({"action": "kill_switch", "state": "off"}, "max")
        otto_admin.act({"action": "pause_brand", "brand": "alpha"}, "max")
        quiet(otto_ads.launch)
        self.assertEqual(self.calls, [])
        otto_admin.act({"action": "resume_brand", "brand": "alpha"}, "max")
        quiet(otto_ads.launch)
        self.assertEqual(self.calls, ["launch:cp-001"])
        self.assertEqual(ap.campaign(ap.load(), "cp-001")["status"], "live")


# ============================================================================================
# admin actions: auth + origin + transitions
# ============================================================================================

class AdminApiTest(_Server, unittest.TestCase):
    J = {"Content-Type": "application/json", "Origin": ORIGIN}

    def setUp(self):
        reset_workspace()
        os.environ.pop("OTTO_ADMIN_USERS", None)

    def tearDown(self):
        os.environ.pop("OTTO_ADMIN_USERS", None)

    def post(self, body, headers=None):
        return self.req("/otto-api/admin", "POST", body, dict(self.J, **(headers or {})))

    def test_origin_and_type_rules(self):
        body = {"action": "kill_switch", "state": "on"}
        self.assertEqual(self.req("/otto-api/admin", "POST", body, {"Content-Type": "text/plain", "Origin": ORIGIN})[0], 415)
        self.assertEqual(self.req("/otto-api/admin", "POST", body, {"Content-Type": "application/json", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/otto-api/admin", "POST", body, {"Content-Type": "application/json", "X-Real-IP": "1.2.3.4"})[0], 403)
        self.assertEqual(self.req("/otto-api/admin", "POST", body, {"Content-Type": "application/json", "Referer": "https://evil.example/x"})[0], 403)
        self.assertIsNone(ap.load().get("controls"), "nothing changed by a refused request")
        code, h, out = self.post(body, {"X-Otto-User": "max@cmtm"})
        self.assertEqual((code, out["ok"]), (200, True))
        self.assertNotIn("Access-Control-Allow-Origin", h)
        self.assertEqual(ap.load()["controls"]["publishing_paused"]["by"], "max@cmtm")
        self.assertIn("admin max@cmtm kill-switch on", (TMP / "actions.log").read_text())

    def test_admin_user_allowlist(self):
        os.environ["OTTO_ADMIN_USERS"] = "max,owner"
        self.assertEqual(self.req("/otto-api/admin/snapshot")[0], 403)
        self.assertEqual(self.req("/otto-api/admin/snapshot", headers={"X-Otto-User": "client1"})[0], 403)
        self.assertEqual(self.post({"action": "kill_switch", "state": "on"}, {"X-Otto-User": "client1"})[0], 403)
        code, _, snap = self.req("/otto-api/admin/snapshot?days=7", headers={"X-Otto-User": "max"})
        self.assertEqual((code, snap["window"]), (200, 7))
        self.assertEqual(self.post({"action": "kill_switch", "state": "on"}, {"X-Otto-User": "owner"})[0], 200)

    def test_admin_is_fail_closed_behind_the_proxy(self):
        proxied = {"X-Real-IP": "203.0.113.5"}
        code, _, out = self.req("/otto-api/admin/snapshot", headers=proxied)
        self.assertEqual(code, 403)
        self.assertIn("OTTO_ADMIN_USERS", out["error"])
        self.assertEqual(self.post({"action": "kill_switch", "state": "on"}, proxied)[0], 403)
        self.assertIsNone(ap.load().get("controls"), "a refused admin call changes nothing")
        os.environ["OTTO_ADMIN_USERS"] = "*"
        self.assertEqual(self.req("/otto-api/admin/snapshot", headers=proxied)[0], 200)
        os.environ["OTTO_ADMIN_USERS"] = "Max@CMTM.co.il, owner"
        self.assertEqual(self.req("/otto-api/admin/snapshot", headers=dict(proxied, **{"X-Otto-User": "max@cmtm.co.il"}))[0], 200)
        code, _, out = self.req("/otto-api/admin/snapshot", headers=dict(proxied, **{"X-Otto-User": "client@shop.example"}))
        self.assertEqual((code, out["error"]), (403, "not an admin"))
        self.assertEqual(self.req("/otto-api/admin/snapshot", headers=proxied)[0], 403, "no user header, not an admin")
        os.environ.pop("OTTO_ADMIN_USERS")
        for h in ({"X-Forwarded-For": "198.51.100.1"}, {"CF-Connecting-IP": "198.51.100.1"}, {"Via": "1.1 caddy"}):
            self.assertEqual(self.req("/otto-api/admin/snapshot", headers=h)[0], 403, f"a proxy that forgot X-Real-IP: {h}")
            self.assertEqual(self.post({"action": "kill_switch", "state": "on"}, dict(h, Origin=""))[0], 403)

    def test_snapshot_route(self):
        code, h, snap = self.req("/otto-api/admin/snapshot")
        self.assertEqual(code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        for k in ("kpis", "funnel", "traffic", "leads", "revenue", "brands", "system", "setup", "recommendations"):
            self.assertIn(k, snap)
        self.assertEqual(self.req("/otto-api/admin/snapshot?days=x")[0], 400)
        code, _, out = self.post({"action": "kill_switch", "state": "on", "window": 30})
        self.assertIsNotNone(out["snapshot"]["kill_switch"], "the action answers with a fresh snapshot, not the cached one")

    def test_bad_requests(self):
        self.assertEqual(self.post({"action": "drop_tables"})[0], 400)
        self.assertEqual(self.post({"action": "kill_switch", "state": "maybe"})[0], 400)
        self.assertEqual(self.post({"action": "pause_brand", "brand": "nope"})[0], 404)
        self.assertEqual(self.post([1, 2])[0], 400)
        self.assertEqual(self.post({"action": "lead", "id": "../../etc", "status": "won"})[0], 400)
        self.assertEqual(self.post({"action": "lead", "id": "d:alpha-dental.example", "status": "married"})[0], 400)
        self.assertEqual(self.post({"action": "whop_sync"})[0], 400, "no Whop sync any more")
        self.assertEqual(self.post({"action": "stripe_check"})[0], 400, "Stripe not set up")
        self.assertEqual(self.post({"action": "resume_brand", "brand": "alpha"})[0], 400, "not paused")

    def test_campaign_transitions(self):
        self.assertEqual(self.post({"action": "campaign", "id": "cp-001", "decision": "approve"})[0], 200)
        self.assertEqual(ap.campaign(ap.load(), "cp-001")["status"], "approved")
        self.assertEqual(self.post({"action": "campaign", "id": "cp-001", "decision": "approve"})[0], 400, "only a draft can be approved")
        self.assertEqual(self.post({"action": "campaign", "id": "cp-001", "decision": "reject", "note": "too early"})[0], 200)
        c = ap.campaign(ap.load(), "cp-001")
        self.assertEqual((c["status"], c["rejected"]["note"]), ("skipped", "too early"))
        with ap.transaction(sync=False) as d:
            c = ap.campaign(d, "cp-001")
            c.update(status="draft", compliance_hold=True)
        self.assertEqual(self.post({"action": "campaign", "id": "cp-001", "decision": "approve"})[0], 400, "compliance hold")
        with ap.transaction(sync=False) as d:
            ap.campaign(d, "cp-001").update(status="live", compliance_hold=False)
        self.assertEqual(self.post({"action": "campaign", "id": "cp-001", "decision": "reject"})[0], 400, "a live campaign is paused, not rejected")
        self.assertEqual(self.post({"action": "campaign", "id": "cp-404", "decision": "approve"})[0], 404)

    def test_lead_notes(self):
        self.assertEqual(self.post({"action": "lead", "id": "d:alpha-dental.example", "status": "contacted", "note": "called Monday"})[0], 200)
        self.assertEqual(self.post({"action": "lead", "id": "d:alpha-dental.example", "status": "won"})[0], 200)
        row = json.loads((TMP / "leads.json").read_text())["leads"]["d:alpha-dental.example"]
        self.assertEqual((row["status"], row["note"], len(row["history"])), ("won", "called Monday", 2))
        self.assertEqual(self.post({"action": "lead", "id": "d:alpha-dental.example", "status": "won", "note": ""})[0], 200)
        row = json.loads((TMP / "leads.json").read_text())["leads"]["d:alpha-dental.example"]
        self.assertEqual((row["note"], len(row["history"])), ("", 3), "an explicit empty note clears it")
        self.assertEqual(os.stat(TMP / "leads.json").st_mode & 0o777, 0o600)

    def test_rescan_runs_in_the_background_once(self):
        spawned = []
        orig = otto_admin.SPAWN
        otto_admin.SPAWN = lambda args, log: spawned.append(args)
        try:
            self.assertEqual(self.post({"action": "rescan", "brand": "alpha"})[0], 200)
            self.assertEqual(self.post({"action": "rescan", "brand": "alpha"})[0], 400, "not twice within 10 minutes")
        finally:
            otto_admin.SPAWN = orig
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][1:], [str(PLATFORM / "otto_scan.py"), "alpha-dental.example", "--slug", "alpha", "--no-profile"])

    def test_pausing_a_brand_pauses_its_live_campaigns(self):
        with ap.transaction(sync=False) as d:
            ap.campaign(d, "cp-001")["status"] = "live"
        paused = []
        orig = otto_ads.pause

        def pause(cid, dry=False, by=None):
            paused.append((cid, by))
            raise otto_ads.LaunchError("Meta said no")
        otto_ads.pause = pause
        try:
            code, _, out = self.post({"action": "pause_brand", "brand": "alpha", "note": "client asked"})
        finally:
            otto_ads.pause = orig
        self.assertEqual((code, paused, out["failed_campaigns"]), (200, [("cp-001", "brand")], ["cp-001"]))
        d = ap.load()
        self.assertTrue(ap.paused(d, "alpha"))
        self.assertTrue(any(r["priority"] == "P0" and r.get("campaign_id") == "cp-001" for r in d["recommendations"]),
                        "a campaign that could not be paused becomes an urgent recommendation")

    def test_link_customer(self):
        with otto_whop.transaction() as b:
            b["customers"]["mem_L"] = {"id": "mem_L", "status": "active", "email": "z@gmail.com"}
        self.assertEqual(self.post({"action": "link_customer", "customer": "mem_L", "brand": "beta"})[0], 200)
        self.assertEqual(otto_whop.load()["customers"]["mem_L"]["brand_id"], "beta")
        self.assertEqual(self.post({"action": "link_customer", "customer": "mem_L", "brand": "nope"})[0], 404)
        self.assertEqual(self.post({"action": "link_customer", "customer": "mem_404", "brand": "beta"})[0], 404)

    def test_client_api_is_untouched(self):
        code, _, data = self.req("/otto-api/data")
        self.assertEqual(code, 200)
        self.assertNotIn("customers", data, "billing never enters data.json (the client app reads it)")


class IsolationTest(unittest.TestCase):
    def test_real_workspace_untouched(self):
        self.assertEqual((PLATFORM / "data.json").exists(), _SAVED["repo_data"])
        for name in ("events.jsonl", "billing.json", "leads.json", ".track-salt", "api-errors.log"):
            self.assertFalse((PLATFORM / name).exists(), f"{name} written into the repo")


if __name__ == "__main__":
    unittest.main()
