#!/usr/bin/env python3
"""Engine hardening tests — stdlib unittest, never touches the real data.json / index.html / brands.

  cd platform && python3 tests/test_engine.py

Every test runs against a throwaway fixture: data.json built from index.html's fallback block, a copy of
index.html, a copy of brands/, and a temp secrets / public-assets dir. No network is used (Graph / Telegram
calls are mocked; the SSRF test runs a local http.server).
"""
import http.server, json, os, re, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-test-"))


def _build_fixture():
    html = (PLATFORM / "index.html").read_text()
    m = re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    (TMP / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    (TMP / "index.html").write_text(html)
    shutil.copytree(PLATFORM.parent / "brands", TMP / "brands")
    shutil.copytree(PLATFORM / "assets" / "posts", TMP / "assets" / "posts")
    (TMP / "secrets").mkdir()
    (TMP / "public").mkdir()
    for b in ("cmtm", "happygarden"):
        (TMP / "secrets" / f"meta-{b}.json").write_text(json.dumps({"access_token": "T", "page_id": "P1", "ig_user_id": "IG1",
                                                                     "ad_account_id": "act_1"}))
    (TMP / "secrets" / "telegram.json").write_text(json.dumps({"bot_token": "x", "owner_chat_id": "42"}))


_build_fixture()
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_SECRETS": str(TMP / "secrets"),
       "OTTO_BRANDS": str(TMP / "brands"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public")}
os.environ.update(ENV)
sys.path.insert(0, str(PLATFORM))

import ap                    # noqa: E402  (env must be set first)
import otto_ads              # noqa: E402
import otto_api              # noqa: E402
import otto_compliance       # noqa: E402
import otto_creative         # noqa: E402
import otto_growth           # noqa: E402
import otto_paths            # noqa: E402
import otto_publish          # noqa: E402
import otto_scan             # noqa: E402
import otto_telegram         # noqa: E402

otto_telegram.STATE = TMP / ".telegram-state.json"
otto_publish.LOG = TMP / "publish.log"
otto_api.LOG = TMP / "actions.log"


def quiet(fn, *a, **kw):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def add_post(**fields):
    with ap.transaction(sync=False) as d:
        base = dict(brand="cmtm", pillar="Community", platform="fb", slot="2026-09-01T09:00")
        base.update(fields)
        return ap.add_post(d, base.pop("brand"), base.pop("pillar"), base.pop("platform"), base.pop("slot"),
                           base.pop("hook", "test hook"), **base)


class TransactionTest(unittest.TestCase):
    def test_two_processes_appending_lose_nothing(self):
        n = 25
        before = len(ap.load().get("recommendations", []))
        code = ("import ap\n"
                f"for i in range({n}):\n"
                "    with ap.transaction(sync=False) as d:\n"
                "        ap.add_rec(d, 'P2', 'proc {tag} %d' % i, 'w', 'i', 'c')\n")
        procs = [subprocess.Popen([sys.executable, "-c", code.replace("{tag}", t)], cwd=str(PLATFORM), env=dict(os.environ, **ENV))
                 for t in ("A", "B")]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0)
        recs = ap.load()["recommendations"]
        self.assertEqual(len(recs), before + 2 * n, "a concurrent writer lost updates")
        self.assertEqual(len({r["id"] for r in recs}), len(recs), "duplicate recommendation ids")

    def test_exception_rolls_back_and_write_is_atomic(self):
        before = ap.DATA.read_text()
        with self.assertRaises(RuntimeError):
            with ap.transaction(sync=False) as d:
                d["posts"].clear()
                raise RuntimeError("boom")
        self.assertEqual(ap.DATA.read_text(), before)
        self.assertFalse([f for f in ap.DATA.parent.glob(".data.json.*.tmp")], "temp file left behind")

    def test_nested_transaction_shares_document(self):
        with ap.transaction(sync=False) as d1:
            with ap.transaction(sync=False) as d2:
                self.assertIs(d1, d2)

    def test_fallback_escapes_script_close(self):
        with ap.transaction() as d:
            ap.add_rec(d, "P2", "evil </script><script>alert(1)</script>", "w", "i", "c")
        html = ap.HTML.read_text()
        block = re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        self.assertNotIn("</script", block.lower())
        self.assertIn("evil </script>", json.dumps(json.loads(block)["recommendations"], ensure_ascii=False))


class IdTest(unittest.TestCase):
    def test_post_ids_never_reused_after_delete(self):
        p1 = add_post()
        with ap.transaction(sync=False) as d:
            d["posts"] = [p for p in d["posts"] if p["id"] != p1["id"]]      # what --replace does
        p2 = add_post()
        self.assertNotEqual(p1["id"], p2["id"])
        self.assertGreater(int(p2["id"].split("-")[1]), int(p1["id"].split("-")[1]))

    def test_rec_and_campaign_ids_use_counters(self):
        with ap.transaction(sync=False) as d:
            r1 = ap.add_rec(d, "P2", "a", "b", "c", "d")
            d["recommendations"].remove(r1)
            r2 = ap.add_rec(d, "P2", "a", "b", "c", "d")
            c1 = otto_ads.new_campaign_id(d)
            c2 = otto_ads.new_campaign_id(d)
        self.assertNotEqual(r1["id"], r2["id"])
        self.assertNotEqual(c1, c2)


class TransitionTest(unittest.TestCase):
    def test_table(self):
        self.assertTrue(ap.can_transition("post", "pending_approval", "approved"))
        for cur in ("published", "publishing", "failed"):
            self.assertFalse(ap.can_transition("post", cur, "approved"), cur)
        self.assertTrue(ap.can_transition("post", "failed", "pending_approval"))
        self.assertFalse(ap.can_transition("rec", "done", "proposed"))

    def test_decide_and_api_enforce(self):
        p = add_post(status="published")
        with self.assertRaises(ValueError):
            with ap.transaction(sync=False) as d:
                ap.decide(d, p["id"], "approve")
        f = add_post(status="failed")
        with self.assertRaises(ValueError):
            otto_api.apply_action("post", f["id"], "approved")
        otto_api.apply_action("post", f["id"], "pending_approval")
        self.assertEqual(ap.post(ap.load(), f["id"])["status"], "pending_approval")


class SlotTest(unittest.TestCase):
    def test_brand_timezone(self):
        p = {"slot": "2026-07-01T09:00"}
        il = ap.slot_dt(p, {"tz": "Asia/Jerusalem"})
        ny = ap.slot_dt(p, {"tz": "America/New_York"})
        self.assertEqual(il.utcoffset(), timedelta(hours=3))                 # IDT in July
        self.assertEqual(ny.astimezone(timezone.utc).hour, 13)
        self.assertEqual(ap.slot_dt(p, {}).utcoffset(), timedelta(hours=3))  # default Asia/Jerusalem
        self.assertEqual(ap.slot_dt({"slot": "2026-07-01T09:00Z"}, {"tz": "America/New_York"}).utcoffset(), timedelta(0))
        self.assertIsNone(ap.slot_dt({"slot": "tomorrow"}, {}))


class ComplianceTest(unittest.TestCase):
    def test_cmtm_personal_attributes_and_cures(self):
        self.assertTrue(otto_compliance.check_texts("cmtm", ["Do you suffer from anxiety? Join the course."]))
        self.assertTrue(otto_compliance.check_texts("cmtm", ["Is your child too sensitive?"]))
        self.assertTrue(otto_compliance.check_texts("cmtm", ["האם אתה סובל מחרדה בלילות?"]))
        self.assertTrue(otto_compliance.check_texts("cmtm", ["השיטה שלנו מרפאת חרדה", "תרפא את עצמך"]))
        self.assertEqual(otto_compliance.check_texts("cmtm", ["At 43 she opened her own practice. 10,000 graduates."]), [])
        self.assertEqual(otto_compliance.check_texts("cmtm", ["מרפאת שיניים בפתח תקווה"]), [])   # "clinic", not a claim

    def test_happygarden_claims_and_thc(self):
        self.assertTrue(otto_compliance.check_texts("happygarden", ["CBD cures insomnia"]))
        self.assertTrue(otto_compliance.check_texts("happygarden", ["This oil gets you high"]))
        self.assertEqual(otto_compliance.check_texts("happygarden", ["Treat yourself to better evenings — minus THC."]), [])

    def test_blocks_telegram_card(self):
        p = add_post(status="pending_approval", slot=(datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
                     hook="Do you suffer from sleepless nights?", caption="x")
        sent = []
        orig = otto_telegram.api
        otto_telegram.api = lambda method, files=None, **kw: sent.append(method) or {"message_id": 1}
        try:
            quiet(otto_telegram.send_cards, ids={p["id"]})
        finally:
            otto_telegram.api = orig
        self.assertEqual(sent, [])
        d = ap.load()
        self.assertTrue(ap.post(d, p["id"]).get("compliance_block"))
        self.assertTrue(any(r["title"].startswith("Compliance hold") and r.get("post") == p["id"] for r in d["recommendations"]))


class _Redirector(http.server.BaseHTTPRequestHandler):
    target = "http://169.254.169.254/latest/meta-data/"

    def do_GET(self):
        if self.path.startswith("/ok"):
            body = b"<html><title>ok</title></html>"
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        self.send_response(302)
        self.send_header("Location", self.path.split("to=", 1)[1] if "to=" in self.path else self.target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class SsrfTest(unittest.TestCase):
    def test_blocks_private_cgnat_metadata(self):
        for u in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://100.64.1.1/", "http://10.0.0.5/",
                  "http://192.168.1.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://localhost/", "http://foo.internal/",
                  "https://example.com:8443/", "ftp://example.com/", "http://2130706433/"):
            self.assertFalse(otto_scan.safe_host(u), u)
            self.assertTrue(otto_scan.fetch(u)[2].startswith("error:"), u)

    def test_every_redirect_hop_is_revalidated(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        orig_ok, orig_ports = otto_scan.ip_ok, otto_scan.ALLOWED_PORTS
        # let ONLY the first hop (this test server) through, exactly as a public site would be
        otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig_ok(ip)
        otto_scan.ALLOWED_PORTS = orig_ports | {port}
        try:
            final, text, ctype = otto_scan.fetch(f"http://127.0.0.1:{port}/ok")
            self.assertIn("ok", text)                               # the test harness itself works
            for target in ("http://169.254.169.254/latest/meta-data/", "http://10.1.2.3/", "http://localhost/admin",
                           "http://100.64.0.9/", "file:///etc/passwd", f"http://127.0.0.1:{port + 1 if port < 65535 else 1}/"):
                _, text, ctype = otto_scan.fetch(f"http://127.0.0.1:{port}/r?to={target}")
                self.assertTrue(ctype.startswith("error:"), f"redirect to {target} was followed: {ctype}")
                self.assertEqual(text, "")
        finally:
            otto_scan.ip_ok, otto_scan.ALLOWED_PORTS = orig_ok, orig_ports
            srv.shutdown(); srv.server_close()


class AdsTest(unittest.TestCase):
    def test_dict_fromkeys_slicing_fixed(self):
        c = {"name": "X · Search", "start": "2026-11-01", "end": "2026-11-30", "daily_budget": 10, "landing_url": "https://x.example/",
             "audience": {"countries": ["DE", "AT"], "languages": ["de"]},
             "creative": {"headlines": ["Great deals!", "Great deals!", "Great deals! and more words beyond thirty chars"] * 10,
                          "descriptions": ["Same", "Same"], "keywords": {"brand": ["x brand", "x brand"], "generic": ["k"] * 30}}}
        ops = otto_ads.google_ops(c, {"customer_id": "123-456-7890"}, {"id": "x", "name": "X Brand", "lang": "DE"})
        heads = [h["text"] for o in ops if "adGroupAdOperation" in o
                 for h in o["adGroupAdOperation"]["create"]["ad"]["responsiveSearchAd"]["headlines"]]
        self.assertTrue(all("!" not in h and len(h) <= 30 for h in heads))
        self.assertGreaterEqual(len(set(heads)), 3)
        geo = [o for o in ops if "campaignCriterionOperation" in o and "location" in o["campaignCriterionOperation"]["create"]]
        self.assertEqual(len(geo), 2)
        kws = [o["adGroupCriterionOperation"]["create"]["keyword"]["text"] for o in ops if "adGroupCriterionOperation" in o]
        self.assertEqual(sorted(kws), ["k", "x brand"])
        c["audience"]["countries"] = ["ZZ"]
        with self.assertRaises(otto_ads.LaunchError):
            otto_ads.google_ops(c, {"customer_id": "1"}, {"id": "x", "name": "X"})

    def test_leads_never_lead_generation_without_form(self):
        c = {"objective": "leads", "creative": {}}
        self.assertEqual(otto_ads.meta_mode({}, c, {"page_id": "P"})["objective"], "OUTCOME_TRAFFIC")
        self.assertEqual(otto_ads.meta_mode({}, c, {"page_id": "P", "pixel_id": "px"})["optimization_goal"], "OFFSITE_CONVERSIONS")
        m = otto_ads.meta_mode({}, c, {"page_id": "P", "lead_form_id": "F"})
        self.assertEqual((m["optimization_goal"], m["destination_type"]), ("LEAD_GENERATION", "ON_AD"))

    def test_minor_units(self):
        self.assertEqual(otto_ads.minor_units(20, "EUR"), 2000)
        self.assertEqual(otto_ads.minor_units(5000, "HUF"), 5000)
        self.assertEqual(otto_ads.minor_units(1000, "JPY"), 1000)

    def test_launch_meta_resumes_without_duplicates(self):
        calls, fail = [], {"adsets": 1}

        def graph(method, path, token, **params):
            calls.append((method, path))
            if path == "act_1":
                return {"currency": "EUR"}
            if path.endswith("/campaigns"):
                return {"id": "C1"}
            if path.endswith("/adsets"):
                if fail["adsets"]:
                    fail["adsets"] -= 1
                    raise otto_publish.GraphError("Graph 2: temporary")
                return {"id": "S1"}
            if path.endswith("/adcreatives"):
                return {"id": "CR1"}
            if path.endswith("/ads"):
                return {"id": "AD1"}
            return {"success": True}

        c = {"id": "cp-x", "brand": "cmtm", "name": "T", "objective": "traffic", "start": "2026-09-01", "end": "2026-12-01",
             "daily_budget": 20, "currency_code": "EUR", "audience": {"countries": ["IL"], "age": [25, 60]}, "creative": {"post": None},
             "creatives": {"titles": ["A"], "bodies": ["B"], "images": [], "carousels": [], "videos": [], "cta": "LEARN_MORE"},
             "remote": {"creatives_built": "yes"}, "landing_url": "https://x.example/"}
        orig = otto_publish.graph
        otto_publish.graph = graph
        otto_ads._acct.clear()
        try:
            with self.assertRaises(otto_publish.GraphError):
                otto_ads.launch_meta({"posts": [], "brands": []}, c, {"access_token": "T", "ad_account_id": "act_1", "page_id": "P"},
                                     "https://x/", persist=lambda **kw: c.update(kw))
            self.assertEqual(c["remote"]["campaign_id"], "C1")
            out = otto_ads.launch_meta({"posts": [], "brands": []}, c, {"access_token": "T", "ad_account_id": "act_1", "page_id": "P"},
                                       "https://x/", persist=lambda **kw: c.update(kw))
        finally:
            otto_publish.graph = orig
        self.assertTrue(out["done"])
        self.assertEqual(sum(1 for m, p in calls if p.endswith("/campaigns")), 1, "campaign created twice")
        adset_calls = [p for m, p in calls if p.endswith("/adsets")]
        self.assertEqual(len(adset_calls), 2)


class PublishTest(unittest.TestCase):
    def _run(self, raise_exc):
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).astimezone(ap.brand_tz({})).strftime("%Y-%m-%dT%H:%M")
        p = add_post(status="approved", slot=slot, platform="fb", hook="publish test")
        calls = []

        def graph(method, path, token, **params):
            calls.append(path)
            raise raise_exc
        orig = otto_publish.graph
        otto_publish.graph = graph
        try:
            quiet(otto_publish.run)
            first = ap.post(ap.load(), p["id"])
            quiet(otto_publish.run)
        finally:
            otto_publish.graph = orig
        return p, first, ap.post(ap.load(), p["id"]), calls

    def test_ambiguous_failure_stays_publishing_and_is_not_retried(self):
        p, first, second, calls = self._run(urllib.error.URLError("timed out"))
        self.assertEqual(first["status"], "publishing")
        self.assertEqual(len(calls), 1, "a post stuck in publishing was retried")
        self.assertTrue(any(r.get("post") == p["id"] and r["priority"] == "P0" for r in ap.load()["recommendations"]))

    def test_definite_failure_goes_back_to_approved(self):
        p, first, second, calls = self._run(otto_publish.GraphError("Graph 100: invalid parameter"))
        self.assertEqual(first["status"], "approved")
        self.assertEqual(second["attempts"], 2)

    def test_linkedin_is_never_sent_to_instagram(self):
        slot = (datetime.now(timezone.utc) - timedelta(minutes=5)).astimezone(ap.brand_tz({})).strftime("%Y-%m-%dT%H:%M")
        p = add_post(status="approved", slot=slot, platform="li")
        orig = otto_publish.graph
        otto_publish.graph = lambda *a, **k: self.fail("Graph called for a LinkedIn post")
        try:
            quiet(otto_publish.run)
        finally:
            otto_publish.graph = orig
        self.assertIn("LinkedIn", ap.post(ap.load(), p["id"])["error"])

    def test_relative_media_never_reaches_meta(self):
        self.assertTrue(otto_paths.media_url("assets/posts/hg-001.png").startswith("https://"))
        self.assertTrue((TMP / "public" / "posts" / "hg-001.png").exists(), "not copied to the public dir")
        with self.assertRaises(otto_paths.AssetError):
            otto_paths.media_url("assets/posts/does-not-exist.jpg")
        with self.assertRaises(otto_paths.AssetError):
            otto_paths.media_url("../secrets/x.jpg")
        self.assertEqual(otto_paths.sniff(otto_paths.local_path(otto_paths.ensure_jpeg("assets/posts/hg-001.png"))), "jpeg")


class DrawtextTest(unittest.TestCase):
    def test_expansion_none_and_shaping_switch(self):
        os.environ["OTTO_TEXT_SHAPING"] = "1"
        try:
            chain, files = otto_creative.drawtext_chain(["20% off", "שלום"], "/f.ttf", "white", 50, "10", True)
            self.assertIn("expansion=none", chain)
            self.assertIn("text_shaping=1", chain)
            self.assertIn("w-text_w-60", chain)
            self.assertEqual(otto_creative.prep_lines("שלום עולם"), ["שלום עולם"])      # shaped by ffmpeg: logical order
        finally:
            for f in files:
                os.unlink(f)
        os.environ["OTTO_TEXT_SHAPING"] = "0"
        try:
            chain, files = otto_creative.drawtext_chain(["x"], "/f.ttf", "white", 50, "10", False)
            self.assertIn("expansion=none", chain)
            self.assertNotIn("text_shaping", chain)
            self.assertEqual(otto_creative.prep_lines("שלום עולם"), ["םלוע םולש"])      # pre-reordered fallback
        finally:
            for f in files:
                os.unlink(f)
            os.environ.pop("OTTO_TEXT_SHAPING", None)

    @unittest.skipUnless(shutil.which("ffmpeg") and otto_creative.font_path(), "ffmpeg / font missing")
    def test_overlay_writes_jpeg_with_percent(self):
        dst = TMP / "overlay.jpg"
        otto_creative.overlay_text(TMP / "assets" / "posts" / "hg-001.png", dst, "20% off today — כל הקורסים בהנחה")
        self.assertEqual(otto_paths.sniff(dst), "jpeg")


class AngleTest(unittest.TestCase):
    def test_no_internal_notes_become_copy(self):
        for bid in ("cmtm", "happygarden"):
            for a in otto_creative.profile_angles(bid):
                self.assertNotRegex(a["angle"], r"CPL|₪|€|→|\(\?\)|לידים|❌")
        self.assertEqual(otto_creative.cta_card_text({"name": "C", "lang": "HE"}), "לפרטים בלינק")
        self.assertEqual(otto_creative.cta_card_text({"name": "C", "lang": "DE"}), "Mehr erfahren")


class TelegramTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.orig = otto_telegram.api
        otto_telegram.api = lambda method, files=None, **kw: self.calls.append((method, kw)) or {"message_id": 777}

    def tearDown(self):
        otto_telegram.api = self.orig

    def cq(self, data, user=42):
        return {"id": "q", "from": {"id": user}, "data": data,
                "message": {"message_id": 5, "chat": {"id": 42}, "photo": [{}], "caption": "card"}}

    def test_owner_only_and_later_resends(self):
        p = add_post(status="pending_approval", tg_message_id=5)
        otto_telegram.handle_callback(self.cq(f"otto:{p['id']}:approve", user=7))
        self.assertEqual(ap.post(ap.load(), p["id"])["status"], "pending_approval")
        otto_telegram.handle_callback(self.cq(f"otto:{p['id']}:later"))
        q = ap.post(ap.load(), p["id"])
        self.assertEqual(q["status"], "pending_approval")
        self.assertNotIn("tg_message_id", q)
        self.assertIn("editMessageCaption", [m for m, _ in self.calls])      # photo card edited as a photo

    def test_edit_needs_reply_to_prompt_within_ttl(self):
        p = add_post(status="pending_approval")
        otto_telegram.handle_callback(self.cq(f"otto:{p['id']}:edit"))
        otto_telegram.handle_message({"from": {"id": 42}, "chat": {"id": 42}, "text": "shorter"})          # not a reply
        self.assertEqual(ap.post(ap.load(), p["id"])["status"], "pending_approval")
        otto_telegram.handle_message({"from": {"id": 42}, "chat": {"id": 42}, "text": "shorter",
                                      "reply_to_message": {"message_id": 777}})
        q = ap.post(ap.load(), p["id"])
        self.assertEqual((q["status"], q["edit_note"]), ("draft", "shorter"))

    def test_plan_card_runs_approve(self):
        with ap.transaction(sync=False) as d:
            d.setdefault("campaigns", []).append({"id": "cp-t1", "brand": "cmtm", "plan": "2031-01", "status": "draft", "network": "meta"})
            r = ap.add_rec(d, "P1", "Approve the 2031-01 paid plan: 1 campaigns, ≈€1", "w", "i", "c", brand="cmtm",
                           source="otto_ads", action="approve_plan", plan="2031-01")
            info = ap.add_rec(d, "P2", "Just information", "w", "i", "c", brand="cmtm")
        quiet(otto_telegram.handle_callback, self.cq(f"otto:rec:{r['id']}:approve"))
        d = ap.load()
        self.assertEqual(ap.campaign(d, "cp-t1")["status"], "approved")
        self.assertIn("on it", [kw.get("text", "") for m, kw in self.calls if m == "answerCallbackQuery"][-1])
        otto_telegram.handle_callback(self.cq(f"otto:rec:{info['id']}:approve"))
        self.assertNotIn("on it", [kw.get("text", "") for m, kw in self.calls if m == "answerCallbackQuery"][-1])


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def req(self, path, method="GET", body=None, headers=None):
        r = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=10) as x:
                return x.status, dict(x.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    def test_cors_and_post_guards(self):
        code, h = self.req("/otto-api/data")
        self.assertEqual(code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        code, h = self.req("/otto-peek", method="OPTIONS")
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "*")
        p = add_post(status="pending_approval")
        body = json.dumps({"id": p["id"], "decision": "approve"}).encode()
        self.assertEqual(self.req("/otto-api/decide", "POST", body, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("/otto-api/decide", "POST", body, {"Content-Type": "application/json",
                                                                     "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/otto-api/decide", "POST", body, {"Content-Type": "application/json", "X-Real-IP": "1.2.3.4"})[0], 403)
        self.assertEqual(self.req("/otto-api/decide", "POST", body, {"Content-Type": "application/json",
                                                                     "Origin": "https://dash.monyflow.work"})[0], 200)
        self.assertEqual(ap.post(ap.load(), p["id"])["status"], "approved")
        pub = add_post(status="published")
        bad = json.dumps({"kind": "post", "id": pub["id"], "status": "approved"}).encode()
        self.assertEqual(self.req("/otto-api/action", "POST", bad, {"Content-Type": "application/json",
                                                                   "Origin": "https://dash.monyflow.work"})[0], 400)


class GrowthTest(unittest.TestCase):
    def test_send_once_per_month_and_no_decisions_kpi(self):
        sent = []
        orig = otto_ads.notify
        otto_ads.notify = lambda text: sent.append(text) or True
        try:
            quiet(otto_growth.rollup, send=True)
            quiet(otto_growth.rollup, send=True)
        finally:
            otto_ads.notify = orig
        self.assertEqual(len(sent), 1)
        self.assertNotIn("decisions", sent[0])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
