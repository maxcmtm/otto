#!/usr/bin/env python3
"""Engine hardening tests — stdlib unittest, never touches the real data.json / index.html / brands.

  cd platform && python3 tests/test_engine.py

Every test runs against a throwaway fixture: data.json built from index.html's fallback block, a copy of
index.html, a copy of brands/, and a temp secrets / public-assets dir. No network is used (Graph / Telegram
calls are mocked; the SSRF test runs a local http.server).
"""
import http.server, json, os, re, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.parse, urllib.request
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
       "OTTO_BRANDS": str(TMP / "brands"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_MOTION_ROOT": str(TMP / "motion")}
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
import otto_competitors      # noqa: E402
import otto_demo             # noqa: E402
import otto_motion           # noqa: E402
import otto_plan             # noqa: E402
import otto_strategy         # noqa: E402
import otto_video            # noqa: E402
import otto_watch            # noqa: E402

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

    def test_dashboard_feeds_taste_log_and_edit_notes(self):
        a = add_post(status="pending_approval")
        otto_api.apply_action("post", a["id"], "approved")
        d = ap.load()
        self.assertEqual(ap.post(d, a["id"])["status"], "approved")
        self.assertTrue(any(t["post"] == a["id"] and t["decision"] == "approve" and t["via"] == "dashboard"
                            for t in d.get("taste_log", [])))
        b = add_post(status="pending_approval")
        otto_api.apply_action("post", b["id"], "draft", note="  Shorter, mention the lab tests  ")
        d = ap.load()
        q = ap.post(d, b["id"])
        self.assertEqual((q["status"], q["edit_note"]), ("draft", "Shorter, mention the lab tests"))
        self.assertTrue(any(r["post"] == b["id"] and r["via"] == "dashboard" for r in d.get("edit_requests", [])))


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


# ---------------------------------------------------------------------------------------------------------------
# launch-simulation fixes (tests/simulate.py found these; docs/LAUNCH-READINESS.md lists them)
# ---------------------------------------------------------------------------------------------------------------

def _local_slot(bid, delta):
    """A naive slot string `delta` from now in the brand's timezone."""
    return (datetime.now(timezone.utc) + delta).astimezone(ap.brand_tz(ap.brand(ap.load(), bid))).strftime("%Y-%m-%dT%H:%M")


def _add_brand(**b):
    with ap.transaction(sync=False) as d:
        d["brands"] = [x for x in d["brands"] if x["id"] != b["id"]] + [dict({"status": "active", "pillars": ["A", "B"]}, **b)]


class _Pages(http.server.BaseHTTPRequestHandler):
    pages = {}

    def do_GET(self):
        body = self.pages.get(self.path.split("?")[0], "").encode()
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class _FakeGraph:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, token, **params):
        self.calls.append((method, path, params))
        if method == "GET" and path.startswith("act_") and "/" not in path:
            return {"currency": "EUR"}
        if path.endswith("/adimages"):
            return {"images": {"x": {"hash": "h1"}}}
        return {"id": f"ID{len(self.calls)}", "success": True}


class IsolationTest(unittest.TestCase):
    def test_every_module_follows_the_otto_env(self):
        code = ("import json, otto_strategy as s, otto_telegram as t, otto_watch as w, otto_growth as g, otto_demo as d, otto_motion as m\n"
                "print(json.dumps([str(x) for x in (s.BRANDS, t.STATE, w.HIST, w.STATE, g.HIST, d.BRANDS, m.BRANDS, m.REELS, m.MOTION)]))")
        out = subprocess.run([sys.executable, "-c", code], cwd=str(PLATFORM), env=dict(os.environ, **ENV), capture_output=True,
                             text=True, check=True).stdout
        for p in json.loads(out):
            self.assertTrue(Path(p).resolve().is_relative_to(TMP.resolve()), f"{p} is outside the OTTO_* workspace")

    def test_demo_reads_the_workspace_and_uses_neutral_defaults(self):
        _add_brand(id="t-demo", name="Demo College", url="demo-college.co.il", lang="HE", countries=["IL"])
        out = TMP / "demo" / "t-demo.json"
        quiet(otto_demo.journey, "t-demo", 30, 7, str(out))
        doc = json.loads(out.read_text())
        self.assertEqual(doc["brand"]["name"], "Demo College")
        self.assertEqual(doc["assumptions"]["currency"], "₪")
        self.assertNotIn("CBD", doc["assumptions"]["paid_note"])
        self.assertFalse(next(e for e in doc["events"] if e["title"] == "The month is planned")["real"])   # no plan yet → not "real"


class OnboardingDefaultsTest(unittest.TestCase):
    def test_brand_add_infers_timezone_and_market(self):
        env = dict(os.environ, **ENV)
        for bid, url, lang, tz, cc in (("t-de", "praxis-test.de", "DE", "Europe/Berlin", ["DE"]),
                                       ("t-pt", "surf-test.com", "PT/EN", "Europe/Lisbon", ["PT"]),
                                       ("t-il", "college-test.co.il", "HE", "Asia/Jerusalem", ["IL"])):
            subprocess.run([sys.executable, "ap.py", "brand-add", bid, "N", url, lang, "A,B"], cwd=str(PLATFORM), env=env,
                           check=True, capture_output=True)
            b = ap.brand(ap.load(), bid)
            self.assertEqual((b["tz"], b["countries"]), (tz, cc), bid)
        subprocess.run([sys.executable, "ap.py", "brand-add", "t-us", "N", "x.com", "EN", "--tz", "America/New_York", "--countries",
                        "US,CA", "--currency", "usd"], cwd=str(PLATFORM), env=env, check=True, capture_output=True)
        b = ap.brand(ap.load(), "t-us")
        self.assertEqual((b["tz"], b["countries"], b["currency"], b["pillars"]), ("America/New_York", ["US", "CA"], "USD", []))
        self.assertEqual(ap.brand_currency(ap.load(), "t-il"), "ILS")          # no scan yet → the country's currency, not EUR
        self.assertEqual(ap.slot_dt({"slot": "2026-10-01T09:00"}, ap.brand(ap.load(), "t-pt")).astimezone(timezone.utc).hour, 8)

    def test_strategy_takes_tz_and_currency_from_the_brand(self):
        _add_brand(id="t-lis", name="Surf", url="surf-lis.com", lang="PT/EN", tz="Europe/Lisbon", countries=["PT"])
        _add_brand(id="t-tlv", name="College", url="college-tlv.co.il", lang="HE", tz="Asia/Jerusalem", countries=["IL"])
        s1, s2 = quiet(otto_strategy.init, "t-lis"), quiet(otto_strategy.init, "t-tlv")
        self.assertEqual((s1["tz"], s1["currency"]), ("Europe/Lisbon", "EUR"))
        self.assertEqual((s2["tz"], s2["currency"]), ("Asia/Jerusalem", "ILS"))
        self.assertTrue((TMP / "brands" / "t-lis" / "strategy.json").exists())

    def test_markets_follow_the_brand(self):
        self.assertEqual(ap.brand_countries({"url": "studio.it", "lang": "IT"}), ["IT"])
        self.assertEqual(ap.brand_countries({"url": "x.com", "lang": "NL/EN"}, ["nl", "en"]), ["NL"])
        self.assertEqual(ap.brand_countries({"url": "x.com", "lang": "EN/DE"}, ["en", "de"]), ["DE", "AT", "CH"])   # unchanged
        self.assertEqual(ap.brand_countries({"countries": ["FR"], "url": "x.de"}), ["FR"])
        _add_brand(id="t-nl", name="NL shop", url="shop-test.nl", lang="NL/EN")
        self.assertEqual(otto_ads.profile_bits("t-nl", ap.brand(ap.load(), "t-nl"))["countries"], ["NL"])
        self.assertEqual(otto_competitors.guess_country("t-nl"), "NL")
        self.assertEqual(otto_competitors.guess_country("cmtm"), "IL")


class ScanParseTest(unittest.TestCase):
    def test_prices_with_thousands_separators(self):
        self.assertEqual(otto_scan.prices_from("Aligner ab 2.900 € · Zahnreinigung 89 €"), ("EUR", ["2.900 €", "89 €"]))
        self.assertEqual(otto_scan.prices_from("שכר לימוד ₪18,500 לשנה או 2,900 ₪")[1], ["₪18,500", "2,900 ₪"])
        self.assertEqual(otto_scan.prices_from("€14,50 · €1,234.56 · Pack 150 €")[1], ["€14,50", "€1,234.56", "150 €"])
        self.assertEqual(otto_scan.prices_from("4.800 Bewertungen, 4,9 Sterne")[1], [])

    def test_localized_subpages_and_industries(self):
        links = [(h, t, "a", "") for h, t in (("/ueber-uns", "Über uns"), ("/preise", "Preise"), ("/leistungen", "Leistungen"),
                                               ("/chi-siamo", "Chi siamo"), ("/impressum", "Impressum"))]
        got = [urllib.parse.urlsplit(u).path for u in otto_scan.pick_internal("https://praxis.example/", links, 5)]
        self.assertEqual(got, ["/ueber-uns", "/preise", "/leistungen", "/chi-siamo"])
        self.assertEqual(otto_scan.industry_guess("Zahnarztpraxis Mitte", "Ihr Zahnarzt in Berlin", ["Zahnmedizin für Patienten"], [],
                                                  "Zahnarzt Patienten")[0], "Clinic & medical")
        self.assertEqual(otto_scan.industry_guess("Grachten", "Koffie bestellen", [], ["Winkelwagen"],
                                                  "winkelwagen afrekenen verzending")[0], "E-commerce & retail")
        self.assertEqual(otto_scan.industry_guess("Onda Viva", "Escola de surf", ["Aulas de surf"], [], "aulas escola cursos")[0],
                         "Education & courses")

    def test_store_vertical_logo_and_objective(self):
        """Found on gruns.co: a Shopify supplement store must read as its vertical, sell (not collect leads), stay
        unrestricted, and take its own logo — not a sub-brand's whose CDN path merely carries the host."""
        self.assertEqual(otto_scan.industry_guess("Grüns Daily Nutrition", "Superfood greens gummies, one daily pack",
                                                  ["Greens in a gummy"], ["Shop", "Cart"],
                                                  "add to cart checkout free shipping gummies superfood greens vitamins "
                                                  "supplement nutrition")[0], "Supplements & nutrition")
        self.assertTrue(otto_ads.is_shop({"platform": "Shopify"}, "Supplements & nutrition"))
        self.assertFalse(otto_ads.is_shop({}, "Clinic & medical"))
        self.assertFalse(otto_ads.RESTRICTED.search("Supplements & nutrition"))
        imgs = [("//gruns.co/cdn/shop/files/logo-forbes-black.svg?v=1", "", "block"),
                ("//gruns.co/cdn/shop/t/165/assets/usnacks_logo.svg?v=3", "", ""),
                ("//gruns.co/cdn/shop/files/Shrek-pouch.png", "Grüns x Shrek limited edition pouch of greens gummies, with the Shrek logo on the front", ""),
                ("//gruns.co/cdn/shop/files/gruns_logo_yellow.svg?v=17", "Grüns Logo in yellow", "footer-logo")]
        self.assertEqual(otto_scan.logo_from("https://gruns.co/", imgs, [], {}),
                         "https://gruns.co/cdn/shop/files/gruns_logo_yellow.svg?v=17")

    def test_theme_color_must_be_a_colour(self):
        _Pages.pages = {"/js": '<html><head><meta name="theme-color" content="javascript:alert(1)"><title>x</title></head></html>',
                        "/ok": '<html><head><meta name="theme-color" content="#0E7C86"><title>y</title></head></html>'}
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        orig_ok, orig_ports = otto_scan.ip_ok, otto_scan.ALLOWED_PORTS
        otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig_ok(ip)
        otto_scan.ALLOWED_PORTS = orig_ports | {port}
        try:
            self.assertIsNone(otto_scan.scan(f"http://127.0.0.1:{port}/js", pages=0)["visual"]["theme_color"])
            s = otto_scan.scan(f"http://127.0.0.1:{port}/ok", pages=0)
            self.assertEqual(s["visual"]["theme_color"], "#0E7C86")
            self.assertEqual(s["visual"]["palette"][0]["hex"], "#0E7C86")
        finally:
            otto_scan.ip_ok, otto_scan.ALLOWED_PORTS = orig_ok, orig_ports
            srv.shutdown(); srv.server_close()


class ComplianceBaselineTest(unittest.TestCase):
    def _brand(self, bid, industry, title):
        bdir = TMP / "brands" / bid
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "scan.json").write_text(json.dumps({"industry": industry, "identity": {"title": title}}, ensure_ascii=False))

    def test_health_brand_without_rules_gets_the_baseline(self):
        self._brand("t-clinic", "Clinic & medical", "Zahnarztpraxis Spreebogen")
        self.assertTrue(otto_compliance.check_texts("t-clinic", ["Wir heilen Parodontitis in einer Sitzung"]))
        self.assertTrue(otto_compliance.check_texts("t-clinic", ["Do you suffer from anxiety at the dentist?"]))
        self.assertEqual(otto_compliance.check_texts("t-clinic", ["Zahnreinigung am Samstag, 60 Minuten, ein Ansprechpartner."]), [])
        self._brand("t-college", "Education & courses", "מכללת אופק | לימודי טיפול באמנות")
        self.assertTrue(otto_compliance.check_texts("t-college", ["האם אתה סובל מחרדה? בוא ללמוד"]))
        self.assertEqual(otto_compliance.check_texts("t-college", ["בגיל 41 היא פתחה קליניקה משלה"]), [])
        self._brand("t-coffee", "E-commerce & retail", "Grachten Koffie")          # not a health brand: nothing invented
        self.assertEqual(otto_compliance.check_texts("t-coffee", ["This coffee cures Monday mornings"]), [])

    def test_fda_disclaimer_is_never_a_claim(self):
        """The DSHEA line names 'diagnose, treat, cure, or prevent' by law; either agency spelling satisfies the rule."""
        bdir = TMP / "brands" / "t-supp"
        bdir.mkdir(parents=True, exist_ok=True)
        disc = ("These statements have not been evaluated by the Food and Drug Administration. This product is not "
                "intended to diagnose, treat, cure, or prevent any disease.")
        (bdir / "compliance.json").write_text(json.dumps({"banned": [r"re:\bcur(e|es|ed|ing)\b", r"re:\bdiagnos(e|es|ed|is)\b"],
                                                          "required_disclaimer": disc, "disclaimer_on": ["posts"]}))
        short = ("Supports digestion. *These statements have not been evaluated by the FDA. This product is not intended to "
                 "diagnose, treat, cure, or prevent any disease.")
        self.assertEqual(otto_compliance.check_texts("t-supp", [short]), [])
        self.assertEqual(otto_compliance.check_texts("t-supp", ["Supports digestion. " + disc]), [])
        self.assertEqual(otto_compliance.check_texts("t-supp", ["Supports digestion."])[0]["rule"], "required_disclaimer")
        self.assertEqual(otto_compliance.check_texts("t-supp", ["It can cure your gut. " + short])[0]["match"], "cure")

    def test_unreadable_rules_fail_closed(self):
        bdir = TMP / "brands" / "t-broken"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "compliance.json").write_text('{"banned": ["cure"')
        v = otto_compliance.check_texts("t-broken", ["a perfectly harmless sentence"])
        self.assertEqual(v[0]["rule"], "compliance.json unreadable")

    def test_publisher_holds_a_violating_approved_post(self):
        p = add_post(status="approved", slot=_local_slot("cmtm", -timedelta(minutes=5)), platform="fb",
                     hook="Do you suffer from anxiety? The course is open", caption="x")
        g = _FakeGraph()
        orig = otto_publish.graph
        otto_publish.graph = g
        try:
            quiet(otto_publish.run)
        finally:
            otto_publish.graph = orig
        q = ap.post(ap.load(), p["id"])
        self.assertEqual(q["status"], "draft")
        self.assertTrue(q.get("compliance_block"))
        self.assertFalse([c for c in g.calls if "anxiety" in json.dumps(c[2])], "violating copy reached Meta")
        self.assertTrue(any(r.get("post") == p["id"] and r["title"].startswith("Compliance hold") for r in ap.load()["recommendations"]))


class LanguageTest(unittest.TestCase):
    def test_non_english_brands_get_their_language(self):
        self.assertEqual(otto_creative.cta_card_text({"name": "S", "lang": "PT/EN"}), "Saiba mais")
        self.assertEqual(otto_creative.cta_card_text({"name": "S", "lang": "NL"}), "Meer informatie")
        script = otto_video.plan_script({"hook": "A tua primeira onda", "caption": "Uma frase bastante longa aqui."}, {"name": "Onda", "lang": "PT"})
        self.assertEqual(script[-1]["text"], "Onda. Link na bio.")
        self.assertEqual(otto_ads.LANG_CONST["pt"], 1014)

    def test_search_ads_never_carry_broken_phrases(self):
        c = {"name": "S", "creative": {"headlines": ["Segurança primeiro: como escolhemos o spot", "Surf camp: uma semana que muda o verão",
                                                     "Onde surfar em outubro perto de Lisboa"],
                                       "descriptions": ["Escola de surf certificada perto de Lisboa. Aulas para iniciantes, famílias e grupos com material incluído."]},
             "audience": {"languages": ["pt"]}}
        heads, descs = otto_ads.rsa_assets(c, {"name": "Onda Viva"}, "pt")
        self.assertIn("Segurança primeiro", heads)
        self.assertIn("Surf camp", heads)
        self.assertIn("Site oficial", heads)                                   # Portuguese fallbacks, not "Official Site"
        self.assertNotIn("Onde surfar em outubro perto", heads)
        self.assertEqual(descs[0], "Escola de surf certificada perto de Lisboa")
        self.assertTrue(all(len(h) <= 30 for h in heads) and all(len(x) <= 90 for x in descs))

    def test_shop_search_ads_sell_and_drop_symbols(self):
        c = {"name": "G", "objective": "sales", "creative": {"headlines": ["4.8★ reviews", "6 grams of fiber"], "descriptions": []},
             "audience": {"languages": ["en"]}}
        heads, descs = otto_ads.rsa_assets(c, {"name": "Grüns"}, "en")
        self.assertIn("4.8 stars reviews", heads)
        self.assertIn("Official Store", heads)
        self.assertNotIn("Get in Touch", heads)
        self.assertNotIn("Talk to our team today", descs)
        self.assertEqual(otto_ads._sentences_fit("6 grams of fiber. One snack pack.", 30), "6 grams of fiber.")
        self.assertEqual(otto_ads._sentences_fit("Prebiotic fiber that tastes like fruit.", 30), "")

    def test_plan_headlines_skip_labels_and_violating_hooks(self):
        _add_brand(id="t-ads", name="Praxis Test", url="praxis-ads.de", lang="DE", tz="Europe/Berlin", countries=["DE"])
        bdir = TMP / "brands" / "t-ads"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "scan.json").write_text(json.dumps({"industry": "Clinic & medical", "final_url": "https://praxis-ads.de/",
                                                    "identity": {"description": "Zahnmedizin in Berlin."}}))
        with ap.transaction(sync=False) as d:
            for i, h in enumerate(["Wir heilen Parodontitis garantiert", "Zahnreinigung ohne Stress"]):
                d["posts"].append({"id": f"ta-{900 + i}", "brand": "t-ads", "pillar": "A", "platform": "fb", "hook": h,
                                   "status": "draft", "slot": "2031-01-01T09:00"})
        b = ap.brand(ap.load(), "t-ads")
        flights = quiet(otto_ads.plan_flights, ap.load(), b, "2031-03", 20, otto_ads.profile_bits("t-ads", b))
        g = next(f for f in flights if f["network"] == "google")
        text = json.dumps(g["creative"], ensure_ascii=False)
        self.assertNotIn("Clinic & medical", text)
        self.assertNotIn("heilen", text)
        self.assertIn("Zahnreinigung ohne Stress", text)
        self.assertEqual(g["audience"]["countries"], ["DE"])

    def test_reel_brief_language_and_whisper_model(self):
        _add_brand(id="t-it", name="Studio Test", url="studio-test.it", lang="IT", tz="Europe/Rome", countries=["IT"])
        with ap.transaction(sync=False) as d:
            d["posts"].append({"id": "ti-001", "brand": "t-it", "pillar": "Progetti", "platform": "ig", "hook": "Un bilocale trasformato",
                               "status": "draft", "slot": "2031-01-01T09:00", "format": "reel"})
        orig = otto_motion.sh

        def fake_sh(cmd, cwd=None, check=True, both=False):
            if "init" in cmd:
                Path(cmd[4]).mkdir(parents=True, exist_ok=True)
            return ""
        otto_motion.sh = fake_sh
        try:
            pdir = quiet(otto_motion.prepare, "ti-001")
        finally:
            otto_motion.sh = orig
        self.assertTrue(Path(pdir).resolve().is_relative_to(TMP.resolve()))
        self.assertIn("language: it", (Path(pdir) / "BRIEF.md").read_text())
        self.assertEqual((otto_motion.whisper_model("en"), otto_motion.whisper_model("he")), ("small.en", "small"))


    def test_finished_reel_is_public_and_attached(self):
        _add_brand(id="t-reel", name="Reel Test", url="reel-test.it", lang="IT", tz="Europe/Rome", countries=["IT"])
        with ap.transaction(sync=False) as d:
            d["posts"].append({"id": "tr-001", "brand": "t-reel", "pillar": "A", "platform": "ig", "hook": "h", "status": "draft",
                               "slot": "2031-01-01T09:00", "format": "reel"})
        pdir = otto_motion.project_dir(ap.load(), ap.post(ap.load(), "tr-001"))
        (pdir / "compositions" / "frames").mkdir(parents=True, exist_ok=True)
        (pdir / "compositions" / "frames" / "01.html").write_text("<div></div>")
        (pdir / "index.html").write_text("<html></html>")
        (pdir / "audio_engine_meta.json").write_text(json.dumps({"bgm_pending": False}))
        (pdir / "renders").mkdir(exist_ok=True)
        (pdir / "renders" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
        orig_sh, orig_dur = otto_motion.sh, otto_motion._dur
        otto_motion.sh = lambda cmd, cwd=None, check=True, both=False: ""        # node / npx HyperFrames stubbed
        otto_motion._dur = lambda f: 42.0
        try:
            quiet(otto_motion.finish, "tr-001")
        finally:
            otto_motion.sh, otto_motion._dur = orig_sh, orig_dur
        q = ap.post(ap.load(), "tr-001")
        self.assertEqual((q["video"], q["status"]), ("assets/reels/tr-001.mp4", "pending_approval"))
        self.assertTrue((TMP / "assets" / "reels" / "tr-001.mp4").exists(), "not written under OTTO_ASSETS")
        self.assertTrue((TMP / "public" / "reels" / "tr-001.mp4").exists(), "rendered reel never copied to the public dir")


class SchedulingTest(unittest.TestCase):
    def test_plan_skips_slots_in_the_past(self):
        _add_brand(id="t-plan", name="Plan Test", url="plan-test.it", lang="IT", tz="Europe/Rome", countries=["IT"])
        tz = ap.brand_tz(ap.brand(ap.load(), "t-plan"))
        now = datetime.now(tz)
        created = quiet(otto_plan.build, "t-plan", now.strftime("%Y-%m"))
        self.assertTrue(all(datetime.fromisoformat(p["slot"]).replace(tzinfo=tz) > now for p in created))
        self.assertEqual(quiet(otto_plan.build, "t-plan", "2020-01"), [])

    def test_no_card_for_a_past_slot_and_claimed_posts_are_skipped(self):
        past = add_post(status="pending_approval", slot=_local_slot("cmtm", -timedelta(hours=2)), hook="past slot card")
        claimed = add_post(status="pending_approval", slot=_local_slot("cmtm", timedelta(hours=3)), hook="claimed elsewhere")
        ok = add_post(status="pending_approval", slot=_local_slot("cmtm", timedelta(hours=4)), hook="a fine card")
        with ap.transaction(sync=False) as d:
            ap.post(d, claimed["id"])["tg_claim"] = ap.now_iso()
        sent = []
        orig = otto_telegram.api
        otto_telegram.api = lambda method, files=None, **kw: sent.append(kw.get("caption") or kw.get("text")) or {"message_id": 9}
        try:
            quiet(otto_telegram.send_cards, "cmtm")
        finally:
            otto_telegram.api = orig
        d = ap.load()
        self.assertFalse(ap.post(d, past["id"]).get("tg_message_id"))
        self.assertFalse(ap.post(d, claimed["id"]).get("tg_message_id"))
        q = ap.post(d, ok["id"])
        self.assertTrue(q.get("tg_message_id"))
        self.assertNotIn("tg_claim", q)
        self.assertFalse([t for t in sent if "past slot card" in (t or "") or "claimed elsewhere" in (t or "")])

    def test_card_hides_the_planner_placeholder(self):
        p = {"id": "x", "brand": "cmtm", "platform": "ig", "slot": "2026-10-01T09:00", "pillar": "P", "caption": "cap",
             "brief": "P · post · angle TBD by Quill · visual on-brand per brand-profile.md"}
        self.assertNotIn("TBD", otto_telegram.card_caption(ap.load(), p))
        p["why"] = "Your best pillar last week"
        self.assertIn("Your best pillar last week", otto_telegram.card_caption(ap.load(), p))


class PaidLaunchTest(unittest.TestCase):
    def _campaign(self, **c):
        base = {"network": "meta", "objective": "traffic", "start": "2000-01-01", "end": "2999-01-01", "daily_budget": 5, "status": "approved",
                "currency_code": "EUR", "audience": {"countries": ["IT"]}, "creative": {}, "remote": {}, "landing_url": "https://x.example/"}
        base.update(c)
        with ap.transaction(sync=False) as d:
            d.setdefault("campaigns", []).append(base)

    def test_approved_flight_without_credentials_files_one_connect_card(self):
        _add_brand(id="t-nocreds", name="No Creds", url="nocreds.it", lang="IT")
        self._campaign(id="cp-nc1", brand="t-nocreds", name="NC")
        quiet(otto_ads.launch, "t-nocreds")
        quiet(otto_ads.launch, "t-nocreds")
        recs = [r for r in ap.load()["recommendations"] if r.get("brand") == "t-nocreds" and r["title"].startswith("Connect Meta ads")]
        self.assertEqual(len(recs), 1)

    def _meta_brand(self, bid):
        _add_brand(id=bid, name=bid, url=f"{bid}.it", lang="IT", countries=["IT"])
        (TMP / "secrets" / f"meta-{bid}.json").write_text(json.dumps({"access_token": "T", "page_id": "PG", "ad_account_id": f"act_{bid}"}))

    def test_boost_uses_a_live_facebook_post(self):
        self._meta_brand("t-boost")
        with ap.transaction(sync=False) as d:
            d["posts"] += [{"id": "tb-001", "brand": "t-boost", "pillar": "A", "platform": "ig", "hook": "planned", "status": "published",
                            "remote_id": "IGM1", "image": "assets/posts/hg-001.png", "slot": "2026-09-01T09:00"},
                           {"id": "tb-002", "brand": "t-boost", "pillar": "A", "platform": "fb", "hook": "live on fb", "status": "published",
                            "remote_id": "PG_55", "image": "assets/posts/hg-001.png", "slot": "2026-09-02T09:00"}]
        self._campaign(id="cp-b1", brand="t-boost", name="Boost", objective="engagement", creative={"post": "tb-001"})
        g = _FakeGraph()
        orig = otto_publish.graph
        otto_publish.graph = g
        otto_ads._acct.clear()
        try:
            quiet(otto_ads.launch, "t-boost")
        finally:
            otto_publish.graph = orig
        c = ap.campaign(ap.load(), "cp-b1")
        self.assertEqual((c["status"], c["creative"]["post"]), ("live", "tb-002"))
        self.assertTrue(any(p.get("object_story_id") == "PG_55" for m, path, p in g.calls if path.endswith("/adcreatives")))

    def test_a_claimed_flight_is_not_launched_twice(self):
        self._meta_brand("t-claim")
        self._campaign(id="cp-cl1", brand="t-claim", name="Claimed", launching_at=ap.now_iso())
        g = _FakeGraph()
        orig = otto_publish.graph
        otto_publish.graph = g
        otto_ads._acct.clear()
        try:
            quiet(otto_ads.launch, "t-claim")
            self.assertFalse([c for c in g.calls if c[1].endswith("/campaigns")], "a flight claimed by another run was launched")
            with ap.transaction(sync=False) as d:                     # a crashed run's claim goes stale → taken over
                ap.campaign(d, "cp-cl1")["launching_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            quiet(otto_ads.launch, "t-claim")
        finally:
            otto_publish.graph = orig
        c = ap.campaign(ap.load(), "cp-cl1")
        self.assertEqual(c["status"], "live")
        self.assertFalse(c.get("launching_at"))
        self.assertEqual(len([x for x in g.calls if x[1].endswith("/campaigns")]), 1)

    def test_plan_card_says_which_flights_are_on_hold(self):
        _add_brand(id="t-held", name="Held College", url="held-college.co.il", lang="HE", countries=["IL"])
        bdir = TMP / "brands" / "t-held"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "scan.json").write_text(json.dumps({"industry": "Education & courses", "languages": ["he"],
                                                    "identity": {"description": "לימודי טיפול באמנות"}}, ensure_ascii=False))
        (bdir / "brand-profile.md").write_text("# Strategic Profile — Held College\n- Industry: Education & courses · art therapy training\n")
        quiet(otto_ads.plan, "t-held", "2031-02")
        r = next(r for r in ap.load()["recommendations"] if r.get("brand") == "t-held" and r.get("action") == "approve_plan")
        self.assertIn("compliance hold", r["why"])


class WatchAndGrowthTest(unittest.TestCase):
    def test_missed_publish_alert_for_a_brand_with_credentials(self):
        p = add_post(status="approved", slot=_local_slot("cmtm", -timedelta(hours=3)), hook="watch missed test")
        alerts = []
        orig = otto_watch.send
        otto_watch.send = lambda text: alerts.append(text) or True
        try:
            quiet(otto_watch.watch)
        finally:
            otto_watch.send = orig
        self.assertTrue(any("watch missed test" in a for a in alerts), "no connections[] entry → the guard stayed silent")
        self.assertTrue(otto_watch.STATE.resolve().is_relative_to(TMP.resolve()))

    def test_reports_go_to_the_owner_bot(self):
        calls = []
        orig = otto_telegram.api
        otto_telegram.api = lambda method, files=None, **kw: calls.append((method, kw)) or {"message_id": 1}
        try:
            self.assertTrue(otto_watch.send("*Otto daily* · all quiet"))
        finally:
            otto_telegram.api = orig
        self.assertEqual(calls[0][0], "sendMessage")
        self.assertEqual((calls[0][1]["chat_id"], calls[0][1]["text"]), ("42", "Otto daily · all quiet"))

    def test_review_not_sent_while_another_run_is_sending(self):
        sent = []
        orig = otto_ads.notify
        otto_ads.notify = lambda text: sent.append(text) or True
        try:
            with ap.transaction(sync=False) as d:
                mk = d.setdefault("markers", {})
                mk.pop(otto_growth.MARKER, None)
                mk[otto_growth.SENDING] = ap.now_iso()
            quiet(otto_growth.rollup, send=True)
            self.assertEqual(sent, [])
            with ap.transaction(sync=False) as d:                     # stale claim (crashed run) → sent once
                d["markers"][otto_growth.SENDING] = "2020-01-01T00:00:00Z"
            quiet(otto_growth.rollup, send=True)
            quiet(otto_growth.rollup, send=True)
        finally:
            otto_ads.notify = orig
        self.assertEqual(len(sent), 1)
        self.assertNotIn(otto_growth.SENDING, ap.load()["markers"])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
