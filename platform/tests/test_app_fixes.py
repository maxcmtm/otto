#!/usr/bin/env python3
"""Regression tests for the front-end QA round 2 server-side findings:
  1. approving a suggestion in the app runs its action (the monthly paid plan → otto_ads.approve) like e-mail and Telegram do
     — tenant-checked, same transitions, a failure → the owner's P0 card and an honest error to the app;
  2. the plan's "what's included" follows the brand's approvals channel (e-mail / Telegram / app);
  3. no owner-console setup text talks about nginx or /otto-api/whop (Caddy + Cloudflare: /hooks/stripe, legacy /hooks/whop),
     and nothing a client sees offers a Whop checkout any more (Stripe on Otto's own Billing page);
  4. the first review is 08:00 (the approval cards / e-mails), worded for the brand's channel;
  5. no retention / notice field of a brand reaches a client;
  6. the owner's full /otto-api/data applies the installed-credentials overlay on connections;
  7. the pages: the landing's "Log in" links point at the app host, the app shows EUR plan cards.

  cd platform && python3 tests/test_app_fixes.py
"""
import contextlib, io, json, os, re, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-appfix-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_EVENTS": str(TMP / "events.jsonl"),
       "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"), "OTTO_SESSIONS": str(TMP / "sessions.json"),
       "OTTO_PLANS": str(PLATFORM / "plans.json"), "OTTO_LEADS": str(TMP / "leads.json")}
CLEAR = ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_DOMAIN", "OTTO_FALLBACK")
YM = "2031-01"


def seed():
    camp = lambda cid, bid: {"id": cid, "brand": bid, "network": "meta", "name": cid, "status": "draft", "plan": YM,
                             "start": "2031-01-05", "end": "2031-01-20", "daily_budget": 10, "creative": {}, "remote": {}}
    rec = lambda rid, bid: {"id": rid, "priority": "P0", "title": f"Approve the {YM} paid plan", "why": "w", "impact": "i", "cta": "c",
                            "status": "proposed", "brand": bid, "source": "otto_ads", "action": "approve_plan", "plan": YM}
    return {"brands": [{"id": "alpha", "name": "Alpha", "url": "alpha.example", "tz": "UTC", "status": "active", "plan": "starter",
                        "members": ["ann@alpha.example"], "approvals": "email", "pillars": ["A"], "compliance": "",
                        "retention": {"ended": "2031-01-01", "notices": {"14": "2031-03-18"}}, "retention_hold": True,
                        "plan_notice": "expired:x", "retention_notice_at": "2031-03-18", "notice_3_sent": "2031-03-29"},
                       {"id": "beta", "name": "Beta", "url": "beta.example", "tz": "UTC", "status": "active", "plan": "starter",
                        "members": ["bob@beta.example"], "pillars": ["A"], "compliance": ""}],
            "posts": [], "campaigns": [camp("cp-001", "alpha"), camp("cp-002", "alpha"), camp("cp-003", "beta")],
            "recommendations": [rec("rec-001", "alpha"), rec("rec-002", "beta"),
                                {"id": "rec-003", "priority": "P1", "title": "Film the latte art", "why": "w", "impact": "i",
                                 "cta": "c", "status": "proposed", "brand": "alpha"}],
            "connections": [{"id": "meta-alpha", "service": "Instagram + Facebook", "brand": "Alpha", "status": "not_connected"}]}


_SAVED, S = {}, {}


def setUpModule():
    for d in ("brands", "secrets"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_api, otto_ads, otto_admin, otto_onboard, otto_strategy, otto_plan, otto_scan
    import ap, otto_api, otto_ads, otto_admin, otto_onboard, otto_strategy, otto_plan, otto_scan     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG, otto_strategy.BRANDS, otto_plan.BRANDS, otto_scan.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = TMP / "data.json", TMP / "index.html", TMP / "brands", TMP / "actions.log"
    otto_strategy.BRANDS = otto_plan.BRANDS = otto_scan.BRANDS = TMP / "brands"
    S["srv"] = otto_api.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
    threading.Thread(target=S["srv"].serve_forever, daemon=True).start()
    S["base"] = f"http://127.0.0.1:{S['srv'].server_address[1]}"
    S["origin"] = sorted(otto_api.ALLOWED_ORIGINS)[0]


def tearDownModule():
    if "srv" in S:
        S["srv"].shutdown(); S["srv"].server_close()
    if "paths" in _SAVED:
        (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG, otto_strategy.BRANDS, otto_plan.BRANDS, otto_scan.BRANDS) = _SAVED["paths"]
    for k, v in _SAVED.get("env", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def req(path, method="GET", body=None, user=None):
    h = {"X-Real-IP": "203.0.113.30"}
    if user:
        h["X-Otto-User"] = user
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.update({"Content-Type": "application/json", "Origin": S["origin"]})
    r = urllib.request.Request(S["base"] + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Fixes(unittest.TestCase):
    def setUp(self):
        (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
        (TMP / "secrets" / "meta-alpha.json").unlink(missing_ok=True)

    def test_1_approving_the_plan_card_in_the_app_approves_the_campaigns(self):
        st, out = req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-001", "status": "done"}, "ann@alpha.example")
        self.assertEqual(st, 200, out)
        d = ap.load()
        self.assertEqual([(c["id"], c["status"], c.get("approved_via")) for c in d["campaigns"]],
                         [("cp-001", "approved", "dashboard"), ("cp-002", "approved", "dashboard"), ("cp-003", "draft", None)])
        r = ap.rec(d, "rec-001")
        self.assertEqual((r["status"], r["approved_via"]), ("done", "dashboard"))
        self.assertIn("2 campaign(s) approved", r["action_result"])
        self.assertIn("dashboard rec rec-001 · 2 campaign(s) approved", (TMP / "actions.log").read_text())
        # another brand's card: unknown to her, nothing approved
        st, _ = req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-002", "status": "done"}, "ann@alpha.example")
        self.assertEqual(st, 404)
        self.assertEqual(ap.campaign(ap.load(), "cp-003")["status"], "draft")
        # a card with no action just changes status; a done card cannot be approved again
        self.assertEqual(req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-003", "status": "done"}, "ann@alpha.example")[0], 200)
        self.assertEqual(ap.rec(ap.load(), "rec-003")["status"], "done")
        self.assertEqual(req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-001", "status": "approved"}, "ann@alpha.example")[0], 400)

    def test_1_a_failed_action_is_saved_told_honestly_and_filed_for_the_owner(self):
        orig = otto_ads.approve
        otto_ads.approve = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Meta is down"))
        try:
            st, out = req("/otto-api/action", "POST", {"kind": "rec", "id": "rec-001", "status": "done"}, "ann@alpha.example")
        finally:
            otto_ads.approve = orig
        self.assertEqual((st, out["saved"]), (502, True))
        self.assertIn("approval is saved", out["error"])
        self.assertNotIn("Meta is down", out["error"], "no internals to the client")
        d = ap.load()
        r = ap.rec(d, "rec-001")
        self.assertEqual(r["status"], "approved")
        self.assertIn("Meta is down", r["action_error"])
        self.assertTrue(any(x["title"].startswith("Approved but not applied") and x["priority"] == "P0" and x.get("audience") == "owner"
                            for x in d["recommendations"]))
        self.assertEqual({c["status"] for c in d["campaigns"]}, {"draft"})

    def test_2_whats_included_follows_the_approvals_channel(self):
        d = ap.load()
        inc = lambda approvals: (ap.brand(d, "alpha").update(approvals=approvals), ap.plan_view(d, "alpha")["included"])[1]
        e = inc("email")
        self.assertIn("Approvals by e-mail", e)
        self.assertIn("Weekly insights and the 07:35 morning report by e-mail", e, "e-mail clients get the 07:35 report too")
        self.assertFalse(any("Telegram" in x for x in e), e)
        self.assertIn("Weekly insights", inc("app"), "the app only: nothing is pushed")
        t = inc("telegram")
        self.assertIn("Approvals in Telegram", t)
        self.assertIn("Weekly insights and the 07:35 morning report in Telegram", t)
        self.assertIn("Approvals in the app", inc("app"))
        self.assertIn("Approvals by e-mail and in Telegram", inc(["email", "telegram"]))
        ap.brand(d, "alpha").pop("approvals")
        self.assertIn("Approvals in Telegram", ap.plan_view(d, "alpha")["included"], "no field = Telegram, as before")

    def test_3_setup_texts_follow_caddy_and_cloudflare(self):
        blob = json.dumps(otto_admin.build(ap.load(), [], {}, {}, {})["setup"])
        self.assertNotIn("nginx", blob)
        self.assertNotIn("/otto-api/whop", blob)
        self.assertIn("/hooks/stripe", blob)
        self.assertIn("/hooks/whop", blob, "the legacy founders' webhook is still documented")
        for page in ("index.html", "landing.html", "onboarding.html", "billing.html"):
            self.assertNotIn("whop.com", (PLATFORM / page).read_text(), f"{page} still sends someone to Whop")
        self.assertIn("CF-IPCountry", blob)

    def test_4_first_review_is_worded_and_timed_for_the_channel(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Amsterdam")
        self.assertEqual(otto_onboard.first_review_at(tz, datetime(2031, 1, 6, 9, 0, tzinfo=tz)).strftime("%a %H:%M"), "Tue 08:00")
        self.assertEqual(otto_onboard.first_review_at(tz, datetime(2031, 1, 6, 9, 0, tzinfo=tz), "email").strftime("%a %H:%M"), "Tue 07:35")
        # e-mail and Telegram approvals come with the 07:35 morning report; the app's Review fills at 08:00
        for appr, words, at in (("email", "by e-mail in the 07:35 morning report", "07:35"),
                                ("telegram", "after the 07:35 morning report", "07:35"), ("app", "Review from 08:00", "08:00")):
            with contextlib.redirect_stdout(io.StringIO()):
                res = otto_onboard.create(f"{appr}-shop.example", {"approvals": appr}, dry=True, scan=False)
            step = next(s for s in res["next_steps"] if s["id"] == "first_review")
            self.assertIn(words, step["detail"], appr)
            self.assertTrue(step["when"][11:16] == at, step["when"])
            self.assertNotIn("with the morning report", step["detail"])

    def test_5_no_retention_or_notice_field_reaches_a_client(self):
        st, d = req("/otto-api/data", user="ann@alpha.example")
        self.assertEqual(st, 200)
        b = d["brands"][0]
        for k in b:
            self.assertFalse(re.search(r"retention|notice", k), k)
        self.assertNotIn("2031-03-18", json.dumps(d))
        owner = otto_api.with_plans(otto_api.owner_view(ap.load()))
        self.assertIn("retention", owner["brands"][0], "the owner keeps them")

    def test_6_the_owner_view_applies_installed_credentials(self):
        (TMP / "secrets" / "meta-alpha.json").write_text("{}")
        os.environ["OTTO_ADMIN_USERS"] = "max@otto.example"
        try:
            st, d = req("/otto-api/data", user="max@otto.example")
        finally:
            os.environ.pop("OTTO_ADMIN_USERS", None)
        self.assertEqual(st, 200)
        self.assertEqual(next(c for c in d["connections"] if c["id"] == "meta-alpha")["status"], "connected")
        st, d = req("/otto-api/data", user="ann@alpha.example")
        self.assertEqual(d["connections"][0]["status"], "connected", "the client and the owner agree")

    def test_7_pages(self):
        landing = (PLATFORM / "landing.html").read_text()
        self.assertNotIn('href="https://dash.monyflow.work/otto/"', landing, "Log in goes to the app host, not the old box")
        self.assertIn("/auth/google/start", landing, "Start free trial → Google sign-in")
        app = (PLATFORM / "index.html").read_text()
        m = re.search(r"const INTERNAL = (/.*?/i);", app)
        self.assertTrue(m)
        self.assertNotIn("€", m.group(1), "EUR plan cards are shown to the client")


if __name__ == "__main__":
    unittest.main(verbosity=2)
