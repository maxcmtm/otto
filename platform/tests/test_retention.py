#!/usr/bin/env python3
"""Data retention (otto_retention): the timeline (90 days after the plan ended, notices 14 and 3 days before, never sooner than
3 days after the 3-day notice), the owner notices (recommendation + Telegram + e-mail), the hold, the export's content, what a
deletion removes and what it keeps, idempotency and crash resume, never touching another brand, leads after
OTTO_LEAD_RETENTION_DAYS, exports after 30 days, restore, and the otto_cron job. Stdlib unittest, no network, nothing outside a
throwaway workspace.

  cd platform && python3 tests/test_retention.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites

Under discover other suites have already imported ap / otto_paths with their own OTTO_* paths, so setUpModule pins the
module-level paths this suite touches to its own workspace and tearDownModule puts them back (the test_admin pattern).
"""
import contextlib, io, json, os, re, shutil, sys, tempfile, unittest, zipfile
from datetime import date, timedelta
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-retention-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_EXPORTS": str(TMP / "exports"), "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_LEADS": str(TMP / "leads.json"),
       "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_OUTBOX": str(TMP / "outbox"),
       "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"), "OTTO_MOTION_ROOT": str(TMP / "motion"),
       "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_OWNER_EMAIL": "owner@otto.example"}
CLEAR = ("OTTO_ADMIN_USERS", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "OTTO_PLANS", "OTTO_LEAD_RETENTION_DAYS")
ENDED = date(2026, 6, 1)                    # "gone" moved to plan none on this day
DELETE_ON = ENDED + timedelta(days=90)      # 2026-08-30
TOK = "0123456789abcdef0123456789abcdef"
IMG = f"assets/posts/go-001-{TOK}.jpg"      # a tokenized image (otto_paths.token_name)
_SAVED = {}


def quiet(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        res = fn(*a, **kw)
    quiet.out = out.getvalue()
    return res


def brand(bid, name, plan, url, **kw):
    b = {"id": bid, "name": name, "url": url, "lang": "en", "tz": "UTC", "status": "active", "plan": plan, "pillars": ["A"]}
    b.update(kw)
    return b


def seed():
    ended_hist = [{"at": "2026-01-10T09:00:00Z", "by": "whop", "via": "whop", "from": "founding", "to": "starter"},
                  {"at": f"{ENDED.isoformat()}T10:00:00Z", "by": "whop", "via": "whop", "from": "starter", "to": "none"}]
    return {
        "brands": [brand("gone", "Gone Shop", "none", "https://www.gone-shop.example", plan_history=ended_hist,
                         members=["anna@gone-shop.example"]),
                   brand("gone-2", "Gone Shop 2", "starter", "https://gone2.example"),
                   brand("alive", "Alive Cafe", "starter", "https://alive.example"),
                   brand("held", "Held Co", "none", "https://held.example", retention_hold=True,
                         plan_history=[{"at": "2025-01-01T00:00:00Z", "to": "none"}]),
                   brand("fresh", "Fresh Co", "none", "https://fresh.example")],
        "posts": [{"id": "go-001", "brand": "gone", "status": "published", "image": IMG, "images": [f"assets/posts/go-001-1-{TOK}.jpg"],
                   "media_ai": {IMG: {"generated": True}}, "caption": "Gone caption", "platform": "ig"},
                  {"id": "go-002", "brand": "gone", "status": "draft", "video": "assets/reels/go-002.mp4", "platform": "ig",
                   "image": "https://otto.example/assets/posts/go-002.jpg"},
                  {"id": "go-003", "brand": "gone", "status": "draft", "image": "assets/posts/shared.jpg", "platform": "fb"},
                  {"id": "gn-001", "brand": "gone-2", "status": "draft", "image": "assets/posts/gn-001.jpg", "platform": "fb"},
                  {"id": "al-001", "brand": "alive", "status": "draft", "image": "assets/posts/al-001.jpg", "platform": "fb"},
                  {"id": "al-002", "brand": "alive", "status": "draft", "image": "assets/posts/shared.jpg", "platform": "fb"}],
        "campaigns": [{"id": "cp-001", "brand": "gone", "status": "ended", "creatives": {"images": [{"file": "assets/ads/cp-001-1-static.jpg"}]}},
                      {"id": "cp-002", "brand": "alive", "status": "draft", "creatives": {"images": [{"file": "assets/ads/cp-002-1-static.jpg"}]}}],
        "recommendations": [{"id": "rec-001", "brand": "gone", "title": "Gone rec", "status": "proposed", "priority": "P1"},
                            {"id": "rec-002", "brand": "alive", "title": "Alive rec", "status": "proposed", "priority": "P1"}],
        "connections": [{"id": "meta-gone", "service": "Meta", "brand": "Gone Shop", "status": "connected"},
                        {"id": "meta-gs", "service": "Meta", "brand": "Gone Shop", "status": "connected"},      # legacy: by name
                        {"id": "meta-gone-2", "service": "Meta", "brand": "Gone Shop 2", "status": "connected"},
                        {"id": "meta-alive", "service": "Meta", "brand": "Alive Cafe", "status": "connected"},
                        {"id": "linkedin", "service": "LinkedIn", "brand": "Shared", "status": "planned"}],
        "taste_log": [{"post": "go-001", "brand": "gone", "decision": "approve"}, {"post": "al-001", "brand": "alive", "decision": "skip"}],
        "edit_requests": [{"post": "go-001", "note": "warmer please"}, {"post": "al-001", "note": "shorter"}],
        "metrics": {"gone": {"reach": 5}, "alive": {"reach": 7}}, "ads": {"gone": {"daily": {}}, "alive": {"daily": {}}},
        "growth": {"gone": {}, "alive": {}}, "controls": {}, "fleet": [{"id": "quill"}],
        "seq": {"prefix:gone": "go", "prefix:alive": "al", "id:go": 3},
    }


def write(p, data=b"x"):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p


def reset():
    for x in list(TMP.iterdir()):
        shutil.rmtree(x) if x.is_dir() else x.unlink()
    (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    for root in ("assets", "public"):
        r = TMP / root
        for rel in (f"posts/go-001-{TOK}.jpg", f"posts/go-001-1-{TOK}.jpg", "posts/go-001.png", "posts/go-002.jpg", "reels/go-002.mp4",
                    "reels/go-002.mp4.provenance.json", "ads/cp-001-1-static.jpg", "ads/cp-001-2-c1.jpg", "posts/shared.jpg",
                    "posts/gn-001.jpg", "posts/al-001.jpg", "ads/cp-002-1-static.jpg", "site/gone/logo.png", "site/alive/logo.png"):
            write(r / rel, f"{root}:{rel}")
    write(TMP / "assets" / "reels" / "go-002" / "s1.jpg")                          # scene cache
    write(TMP / "motion" / "gone-go-002" / "STORYBOARD.md", "storyboard")
    write(TMP / "brands" / "gone" / "brand-profile.md", "# Gone Shop")
    write(TMP / "brands" / "gone" / "scan.json", "{}")
    write(TMP / "brands" / "alive" / "brand-profile.md", "# Alive")
    write(TMP / "brands" / "gone-2" / "brand-profile.md", "# Gone 2")
    for name in ("meta-gone.json", "google-gone.json", "meta-gone-2.json", "meta-alive.json", "meta-notgone.json", "telegram.json.example"):
        write(TMP / "secrets" / name, '{"access_token": "SECRET-TOKEN"}')
    ev = [{"ts": "2026-05-01T10:00:00Z", "e": "scan_start", "v": "a", "domain": "gone-shop.example"},
          {"ts": "2026-05-01T10:00:01Z", "e": "scan_result", "v": "a", "domain": "www.gone-shop.example", "ok": True},
          {"ts": "2026-05-02T10:00:00Z", "e": "scan_start", "v": "b", "domain": "alive.example"},
          {"ts": "2026-05-03T10:00:00Z", "e": "view", "v": "c", "p": "/"},
          {"ts": "2023-01-05T10:00:00Z", "e": "scan_start", "v": "d", "domain": "old-lead.example"},
          {"ts": "2026-08-01T10:00:00Z", "e": "scan_start", "v": "e", "domain": "recent-lead.example"}]
    write(TMP / "events.jsonl", "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in ev))
    leads = {"leads": {"d:gone-shop.example": {"status": "won", "note": "spoke to Anna", "updated": "2026-05-02T00:00:00Z"},
                       "d:alive.example": {"status": "won", "note": "Ben", "updated": "2026-05-02T00:00:00Z"},
                       "d:old-lead.example": {"status": "lost", "note": "Carl", "updated": "2023-02-01T00:00:00Z"},
                       "d:recent-lead.example": {"status": "new", "note": "", "updated": "2026-08-02T00:00:00Z"},
                       "v:2023-03-01:abcd1234": {"status": "new", "note": "", "updated": "2023-03-01T00:00:00Z"},
                       "v:2026-08-01:beef1234": {"status": "new", "note": "", "updated": "2026-08-01T00:00:00Z"}}}
    write(TMP / "leads.json", json.dumps(leads))
    write(TMP / "actions.log", '2026-05-01T00:00:00Z admin max pause gone note="client Anna asked"\n'
                               '2026-05-01T00:00:01Z admin max lead d:gone-shop.example contacted note="Anna, 0612345678"\n'
                               "2026-05-01T00:00:02+00:00 onboard gone created (public) ip=203.0.113.9\n"
                               '2026-05-01T00:00:03Z admin max pause gone-2 note="keep this"\n'
                               '2026-05-01T00:00:04Z admin max pause alive note="keep that"\n'
                               "2026-05-01T00:00:05+00:00 dashboard post go-001 -> approved\n")
    write(TMP / "heartbeats.json", json.dumps({"jobs": {"publish": {"brands": {"gone": {"tail": ["Gone caption"]}, "alive": {}}}}}))
    write(TMP / ".email-state.json", json.dumps({"brands": {"gone": {"digest": {}}, "alive": {}},
                                                 "bounces": {"k1": {"type": "hard", "brands": ["gone"]}, "k2": {"type": "hard", "brands": ["alive"]}},
                                                 "sent_ids": [{"id": "1", "brand": "gone"}, {"id": "2", "brand": "alive"}]}))
    write(TMP / "outbox" / "20260501T100000-gone-digest-0a1b2c3d-00ff.eml", "to anna")
    write(TMP / "outbox" / "20260501T100000-gone-2-digest-0a1b2c3d-00ff.eml", "to gone 2")
    write(TMP / "outbox" / "20260501T100000-alive-digest-0a1b2c3d-00ff.eml", "to ben")
    write(TMP / "metrics_history.jsonl", json.dumps({"date": "2026-05-01", "metrics": {"gone": {"reach": 1}, "alive": {"reach": 2}}}) + "\n")
    write(TMP / "billing.json", json.dumps({"customers": {"mem_1": {"id": "mem_1", "brand_id": "gone", "email": "anna@gone-shop.example"}}}))
    TG.clear()


TG = []


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_paths, otto_retention, otto_telegram, otto_cron
    import ap, otto_paths, otto_retention, otto_telegram, otto_cron   # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, otto_paths.BASE, otto_telegram.config, otto_telegram.send)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_paths.ASSETS, otto_paths.BASE = TMP / "assets", "https://otto.example/"
    otto_telegram.config = lambda: ("bot-token", "42")
    otto_telegram.send = lambda text: TG.append(text) or {"message_id": 1}
    reset()


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, otto_paths.BASE, otto_telegram.config, otto_telegram.send) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def D():
    return json.loads((TMP / "data.json").read_text())


def B(bid):
    return next((b for b in D()["brands"] if b["id"] == bid), None)


def run(day):
    return quiet(otto_retention.run, day)


def recs(**kw):
    return [r for r in D()["recommendations"] if all(r.get(k) == v for k, v in kw.items())]


class TimelineTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_dates_from_the_plan_history(self):
        t = otto_retention.timeline(B("gone"), date(2026, 7, 1))
        self.assertEqual((t["state"], t["ended"], t["source"], t["delete_on"]), ("counting", "2026-06-01", "plan_history", "2026-08-30"))
        self.assertEqual((t["notice_14"], t["notice_3"], t["due"]), ("2026-08-16", "2026-08-27", None))
        self.assertEqual(otto_retention.timeline(B("gone"), DELETE_ON - timedelta(days=14))["due"], "notice-14")
        self.assertEqual(otto_retention.timeline(B("gone"), DELETE_ON - timedelta(days=3))["due"], "notice-3")
        self.assertEqual(otto_retention.timeline(B("alive"), DELETE_ON)["state"], "active")

    def test_the_3_day_notice_always_comes_3_days_before(self):
        b = B("gone")
        b["retention"] = {"ended": "2026-06-01", "notices": {"14": "2026-08-16", "3": "2026-08-27"}}
        self.assertEqual(otto_retention.timeline(b, DELETE_ON - timedelta(days=1))["due"], None)
        self.assertEqual(otto_retention.timeline(b, DELETE_ON)["due"], "delete")
        late = dict(b, retention={"ended": "2026-06-01", "notices": {"3": "2026-09-20"}})     # the notice went out late
        t = otto_retention.timeline(late, date(2026, 9, 22))
        self.assertEqual((t["effective"], t["due"]), ("2026-09-23", None))
        self.assertEqual(otto_retention.timeline(late, date(2026, 9, 23))["due"], "delete")

    def test_first_seen_and_old_cycles(self):
        t = otto_retention.timeline(B("fresh"), date(2026, 9, 1))
        self.assertEqual((t["source"], t["ended"], t["delete_on"]), ("first_seen", "2026-09-01", "2026-11-30"))
        b = B("gone")                                          # notices of an earlier end never count for this one
        b["retention"] = {"ended": "2025-01-01", "notices": {"14": "2025-03-18", "3": "2025-03-29"}}
        self.assertEqual(otto_retention.timeline(b, DELETE_ON)["due"], "notice-3")

    def test_first_run_long_after_the_date_gives_notice_then_deletes_3_days_later(self):
        day = date(2026, 12, 1)
        run(day)
        self.assertIsNotNone(B("gone"), "deleted without a notice")
        self.assertEqual(B("gone")["retention"]["notices"], {"3": "2026-12-01"})
        run(day + timedelta(days=2))
        self.assertIsNotNone(B("gone"))
        run(day + timedelta(days=3))
        self.assertIsNone(B("gone"))


class NoticeTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_14_and_3_day_notices_reach_the_owner_once(self):
        run(date(2026, 8, 1))
        self.assertEqual(recs(source="retention"), [])
        run(DELETE_ON - timedelta(days=14))
        r14 = recs(source="retention", brand="gone")
        self.assertEqual(len(r14), 1)
        self.assertEqual((r14[0]["priority"], r14[0]["audience"]), ("P1", "owner"))
        self.assertIn("2026-08-30", r14[0]["title"])
        self.assertTrue(any("gone" in t and "2026-08-30" in t for t in TG), TG)
        mails = sorted((TMP / "outbox").glob("*-gone-retention-*.eml"))
        self.assertEqual(len(mails), 1)
        self.assertIn("owner@otto.example", mails[0].read_text())
        self.assertEqual(B("gone")["retention"]["notices"], {"14": "2026-08-16"})
        run(DELETE_ON - timedelta(days=14))                    # the same day again: nothing new
        self.assertEqual(len(recs(source="retention", brand="gone")), 1)
        self.assertEqual(len(TG), 1)
        run(DELETE_ON - timedelta(days=3))
        r3 = [r for r in recs(source="retention", brand="gone") if r["priority"] == "P0"]
        self.assertEqual(len(r3), 1)
        self.assertEqual(len(TG), 2)
        self.assertIn("3 days", r3[0]["title"])
        import otto_api                                          # the client never sees them
        view = otto_api.client_view(D(), {"gone"})
        self.assertFalse([r for r in view["recommendations"] if r.get("source") == "retention"])
        # regression (integration review): the brand record itself carried the owner's countdown (and a legal hold) to the client
        self.assertNotIn("retention", view["brands"][0])
        with ap.transaction(sync=False) as d:
            d["brands"][0]["retention_hold"] = "dispute with the client, see mail 2026-08-20"
        self.assertNotIn("dispute", json.dumps(otto_api.client_view(D(), {"gone"})))
        log = (TMP / "actions.log").read_text()
        self.assertIn("retention notice-14 gone", log)
        self.assertIn("retention notice-3 gone", log)

    def test_ended_again_starts_a_new_countdown(self):
        """Renewed and ended again between two runs: the first end's notices never count for the second."""
        run(DELETE_ON - timedelta(days=3))
        self.assertEqual(B("gone")["retention"]["notices"], {"3": "2026-08-27"})
        with ap.transaction(sync=False) as d:
            ap.set_plan(d, "gone", "starter", by="whop", via="whop")
            ap.brand(d, "gone")["plan_history"][-1]["at"] = "2026-08-28T08:00:00Z"
            ap.set_plan(d, "gone", "none", by="whop", via="whop")
            ap.brand(d, "gone")["plan_history"][-1]["at"] = "2026-08-28T09:00:00Z"
        run(DELETE_ON)
        b = B("gone")
        self.assertIsNotNone(b)
        self.assertEqual((b["retention"]["ended"], b["retention"]["delete_on"]), ("2026-08-28", "2026-11-26"))
        self.assertNotIn("notices", b["retention"])
        run(date(2026, 11, 26))                                  # a fresh 3-day notice first
        self.assertIsNotNone(B("gone"))
        run(date(2026, 11, 29))
        self.assertIsNone(B("gone"))

    def test_renewal_clears_the_countdown(self):
        run(DELETE_ON - timedelta(days=14))
        with ap.transaction(sync=False) as d:
            ap.set_plan(d, "gone", "starter", by="whop", via="whop")
        run(DELETE_ON)
        run(DELETE_ON + timedelta(days=10))
        b = B("gone")
        self.assertIsNotNone(b)
        self.assertNotIn("retention", b)
        self.assertEqual([r["status"] for r in recs(source="retention", brand="gone")], ["dismissed"])


class HoldTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_hold_stops_notices_and_deletion_release_restarts_them(self):
        far = date(2027, 6, 1)
        run(far)
        self.assertIsNotNone(B("held"))
        self.assertFalse(recs(source="retention", brand="held"))
        self.assertIn("on hold", quiet.out)
        self.assertEqual(next(t for t in otto_retention.plan(far)["brands"] if t["brand"] == "held")["state"], "held")
        quiet(otto_retention.set_hold, "held", False, "dispute settled")
        self.assertNotIn("retention_hold", B("held"))
        run(far)
        self.assertIsNotNone(B("held"))
        self.assertEqual(B("held")["retention"]["notices"], {"3": far.isoformat()})
        run(far + timedelta(days=3))
        self.assertIsNone(B("held"))
        self.assertIn('retention release held by=cli note=', (TMP / "actions.log").read_text())

    def test_hold_set_after_the_notice_still_protects(self):
        run(DELETE_ON - timedelta(days=3))
        quiet(otto_retention.set_hold, "gone", True, "legal dispute")
        run(DELETE_ON + timedelta(days=30))
        self.assertIsNotNone(B("gone"))
        self.assertTrue((TMP / "brands" / "gone" / "brand-profile.md").exists())


class ExportTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_export_holds_the_brand_and_no_secret(self):
        zp = quiet(otto_retention.export, "gone")
        self.assertEqual(zp.parent, TMP / "exports")
        self.assertRegex(zp.name, r"^otto-export-gone-\d{8}T\d{6}Z\.zip$")
        self.assertEqual(zp.stat().st_mode & 0o777, 0o600)
        with zipfile.ZipFile(zp) as z:
            names = set(z.namelist())
            man = json.loads(z.read("manifest.json"))
            data = json.loads(z.read("data.json"))
            blob = b"".join(z.read(n) for n in names)
        self.assertEqual((man["format"], man["brand"], man["name"]), ("otto-brand-export/1", "gone", "Gone Shop"))
        self.assertEqual(data["brand"]["id"], "gone")
        self.assertEqual(sorted(p["id"] for p in data["lists"]["posts"]), ["go-001", "go-002", "go-003"])
        self.assertEqual([c["id"] for c in data["lists"]["campaigns"]], ["cp-001"])
        self.assertEqual(sorted(c["id"] for c in data["lists"]["connections"]), ["meta-gone", "meta-gs"])
        self.assertEqual(sorted(data["keyed"]), ["ads", "growth", "metrics"])
        self.assertEqual([e["post"] for e in data["lists"]["edit_requests"]], ["go-001"])
        self.assertTrue({"brand/brand-profile.md", "brand/scan.json", f"media/{IMG}", f"media/assets/posts/go-001-1-{TOK}.jpg",
                         "media/assets/reels/go-002.mp4", "media/assets/posts/go-002.jpg", "media/assets/ads/cp-001-1-static.jpg",
                         "media/assets/site/gone/logo.png"} <= names, names)
        self.assertFalse(any("al-001" in n or "gn-001" in n or "alive" in n for n in names), names)
        self.assertNotIn(b"SECRET-TOKEN", blob)
        self.assertNotIn(b"Alive Cafe", blob)


class DeletionTest(unittest.TestCase):
    def setUp(self):
        reset()
        run(DELETE_ON - timedelta(days=14))
        run(DELETE_ON - timedelta(days=3))
        self.before = D()
        self.billing = (TMP / "billing.json").read_text()
        run(DELETE_ON)

    def test_records_of_the_brand_are_gone_others_stay(self):
        d = D()
        self.assertEqual([b["id"] for b in d["brands"]], ["gone-2", "alive", "held", "fresh"])
        self.assertEqual(sorted(p["id"] for p in d["posts"]), ["al-001", "al-002", "gn-001"])
        self.assertEqual([c["id"] for c in d["campaigns"]], ["cp-002"])
        self.assertEqual(sorted(c["id"] for c in d["connections"]), ["linkedin", "meta-alive", "meta-gone-2"])
        self.assertEqual([t["brand"] for t in d["taste_log"]], ["alive"])
        self.assertEqual([e["post"] for e in d["edit_requests"]], ["al-001"])
        for k in ("metrics", "ads", "growth"):
            self.assertEqual(list(d[k]), ["alive"], k)
        self.assertNotIn("prefix:gone", d["seq"])
        self.assertEqual(d["seq"]["id:go"], 3)                  # ids are never reused
        self.assertFalse([r for r in d["recommendations"] if r.get("brand") == "gone"])
        self.assertTrue([r for r in d["recommendations"] if r.get("brand") == "alive"])
        done = [r for r in d["recommendations"] if r.get("deleted") == "gone"]
        self.assertEqual((len(done), done[0]["audience"]), (1, "owner"))
        self.assertEqual(d["fleet"], [{"id": "quill"}])

    def test_files_of_the_brand_are_gone_others_stay(self):
        for root in ("assets", "public"):
            r = TMP / root
            for rel in (f"posts/go-001-{TOK}.jpg", f"posts/go-001-1-{TOK}.jpg", "posts/go-001.png", "posts/go-002.jpg",
                        "reels/go-002.mp4", "reels/go-002.mp4.provenance.json", "ads/cp-001-1-static.jpg", "ads/cp-001-2-c1.jpg",
                        "site/gone"):
                self.assertFalse((r / rel).exists(), f"{root}/{rel} was kept")
            for rel in ("posts/shared.jpg", "posts/gn-001.jpg", "posts/al-001.jpg", "ads/cp-002-1-static.jpg", "site/alive/logo.png"):
                self.assertTrue((r / rel).exists(), f"{root}/{rel} of another brand was deleted")
        self.assertFalse((TMP / "assets" / "reels" / "go-002").exists())
        self.assertFalse((TMP / "motion" / "gone-go-002").exists())
        self.assertFalse((TMP / "brands" / "gone").exists())
        self.assertTrue((TMP / "brands" / "alive" / "brand-profile.md").exists())
        self.assertTrue((TMP / "brands" / "gone-2" / "brand-profile.md").exists())
        self.assertEqual(sorted(f.name for f in (TMP / "secrets").iterdir()),
                         ["meta-alive.json", "meta-gone-2.json", "meta-notgone.json", "telegram.json.example"])
        self.assertEqual(sorted(f.name for f in (TMP / "outbox").glob("*-digest-*.eml")),
                         ["20260501T100000-alive-digest-0a1b2c3d-00ff.eml", "20260501T100000-gone-2-digest-0a1b2c3d-00ff.eml"])

    def test_billing_and_audit_lines_are_kept_content_stripped(self):
        self.assertEqual((TMP / "billing.json").read_text(), self.billing)
        log = (TMP / "actions.log").read_text().splitlines()
        self.assertEqual(log[0], "2026-05-01T00:00:00Z admin max pause gone note=[deleted]")
        self.assertEqual(log[1], "2026-05-01T00:00:01Z admin max lead d:gone-shop.example contacted note=[deleted]")
        self.assertEqual(log[2], "2026-05-01T00:00:02+00:00 onboard gone created (public) ip=[deleted]")
        self.assertEqual(log[3], '2026-05-01T00:00:03Z admin max pause gone-2 note="keep this"')
        self.assertEqual(log[4], '2026-05-01T00:00:04Z admin max pause alive note="keep that"')
        self.assertEqual(log[5], "2026-05-01T00:00:05+00:00 dashboard post go-001 -> approved")
        self.assertTrue(any(re.search(r"retention delete gone \(plan ended 2026-06-01; export otto-export-gone-", l) for l in log), log[-3:])
        self.assertNotIn("Anna", "\n".join(log))

    def test_lead_events_and_state_files(self):
        ev = [json.loads(l) for l in (TMP / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len(ev), 6)                              # the events stay (statistics) …
        self.assertEqual([e.get("domain") for e in ev[:3]], [None, None, "alive.example"])   # … without the brand's domain
        leads = json.loads((TMP / "leads.json").read_text())["leads"]
        self.assertNotIn("d:gone-shop.example", leads)
        self.assertIn("d:alive.example", leads)
        hb = json.loads((TMP / "heartbeats.json").read_text())
        self.assertEqual(list(hb["jobs"]["publish"]["brands"]), ["alive"])
        st = json.loads((TMP / ".email-state.json").read_text())
        self.assertEqual((list(st["brands"]), list(st["bounces"]), [x["brand"] for x in st["sent_ids"]]), (["alive"], ["k2"], ["alive"]))
        hist = json.loads((TMP / "metrics_history.jsonl").read_text().splitlines()[0])
        self.assertEqual(list(hist["metrics"]), ["alive"])
        self.assertFalse((TMP / ".retention-journal.json").exists() and json.loads((TMP / ".retention-journal.json").read_text()).get("pending"))

    def test_export_made_before_and_restore_brings_it_back(self):
        zips = sorted((TMP / "exports").glob("otto-export-gone-*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as z:
            self.assertIn(f"media/{IMG}", z.namelist())
        with ap.transaction(sync=False) as d:                     # never over an existing brand
            d["brands"].append({"id": "gone", "name": "impostor"})
        with self.assertRaises(ValueError):
            quiet(otto_retention.restore, zips[0], True)
        with ap.transaction(sync=False) as d:
            d["brands"] = [b for b in d["brands"] if b.get("name") != "impostor"]
        self.assertFalse((TMP / "brands" / "gone").exists(), "files written before the refusal")
        quiet(otto_retention.restore, zips[0], True)
        d = D()
        b = B("gone")
        self.assertEqual((b["name"], b["plan"], b["plan_history"][-1]["via"]), ("Gone Shop", "none", "restore"))
        self.assertNotIn("retention", b)
        self.assertEqual(sorted(p["id"] for p in d["posts"] if p["brand"] == "gone"), ["go-001", "go-002", "go-003"])
        self.assertEqual(d["metrics"]["gone"], {"reach": 5})
        self.assertTrue((TMP / "brands" / "gone" / "brand-profile.md").exists())
        self.assertTrue((TMP / "assets" / IMG[len("assets/"):]).exists())
        self.assertTrue((TMP / "public" / IMG[len("assets/"):]).exists(), "restored media are public again")
        t = otto_retention.timeline(b, date(2026, 9, 1))            # restored on the ended plan: a new 90 days from today
        self.assertEqual(t["source"], "plan_history")

    def test_idempotent(self):
        before = D()
        log = (TMP / "actions.log").read_text()
        exports = sorted(f.name for f in (TMP / "exports").iterdir())
        for day in (DELETE_ON, DELETE_ON + timedelta(days=1)):
            self.assertEqual(run(day), 0)
        after = D()
        for k in ("brands", "posts", "campaigns", "recommendations", "connections", "metrics", "seq"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(sorted(f.name for f in (TMP / "exports").iterdir()), exports)
        self.assertEqual((TMP / "actions.log").read_text().count("retention delete"), log.count("retention delete"))


class SafetyTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_plan_is_dry_and_lists_what_and_when(self):
        before = (TMP / "data.json").read_text()
        p = otto_retention.plan(DELETE_ON)
        self.assertEqual((TMP / "data.json").read_text(), before)
        g = next(t for t in p["brands"] if t["brand"] == "gone")
        self.assertEqual((g["effective"], g["due"]), ("2026-09-02", "notice-3"))        # no notice yet: 3 days after it goes out
        w = g["would_delete"]
        self.assertEqual(sorted(w["secrets"]), ["google-gone.json", "meta-gone.json"])
        self.assertIn("assets/posts/shared.jpg", w["kept_shared"])
        self.assertEqual(w["lead_domains"], ["gone-shop.example"])
        self.assertTrue(any(f.endswith("reels/go-002.mp4.provenance.json") for f in w["files"]))
        out = io.StringIO()
        otto_retention.print_plan(p, out=lambda s: out.write(s + "\n"))
        self.assertIn("gone: plan ended 2026-06-01 (plan_history) · deletion 2026-09-02", out.getvalue())

    def test_unreadable_plans_delete_nothing(self):
        bad = TMP / "broken-plans.json"
        bad.write_text("{not json")
        os.environ["OTTO_PLANS"] = str(bad)
        try:
            b = B("gone")
            with ap.transaction(sync=False) as d:
                ap.brand(d, "gone")["retention"] = {"ended": "2026-06-01", "notices": {"3": "2026-08-27"}}
            self.assertEqual(run(DELETE_ON + timedelta(days=10)), 1)
            self.assertIsNotNone(B("gone"))
            self.assertTrue((TMP / "secrets" / "meta-gone.json").exists())
        finally:
            os.environ.pop("OTTO_PLANS", None)

    def test_renewed_between_check_and_delete_keeps_everything(self):
        run(DELETE_ON - timedelta(days=3))
        real = otto_retention.export

        def export_then_renew(*a, **kw):
            zp = real(*a, **kw)
            with ap.transaction(sync=False) as d:                   # the Whop webhook lands while the export runs
                ap.set_plan(d, "gone", "starter", by="whop", via="whop")
            return zp
        otto_retention.export = export_then_renew
        try:
            run(DELETE_ON)
        finally:
            otto_retention.export = real
        self.assertIsNotNone(B("gone"))
        self.assertTrue((TMP / "assets" / IMG[len("assets/"):]).exists())
        self.assertEqual(list((TMP / "exports").glob("*.zip")), [])

    def test_a_crash_after_the_records_resumes_on_the_next_run(self):
        run(DELETE_ON - timedelta(days=3))
        real = otto_retention._finish_journal
        otto_retention._finish_journal = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("power cut"))
        try:
            run(DELETE_ON)
        finally:
            otto_retention._finish_journal = real
        self.assertIsNone(B("gone"))
        self.assertTrue((TMP / "brands" / "gone").exists(), "files went before the crash?")
        self.assertIn("gone", json.loads((TMP / ".retention-journal.json").read_text())["pending"])
        self.assertEqual(run(DELETE_ON + timedelta(days=1)), 0)
        self.assertFalse((TMP / "brands" / "gone").exists())
        self.assertFalse((TMP / "secrets" / "meta-gone.json").exists())
        self.assertEqual(json.loads((TMP / ".retention-journal.json").read_text())["pending"], {})
        self.assertTrue((TMP / "secrets" / "meta-alive.json").exists())

    def test_a_file_it_cannot_remove_becomes_an_owner_card(self):
        run(DELETE_ON - timedelta(days=3))
        real = otto_retention._remove
        otto_retention._remove = lambda p, roots: False if Path(p).name == "meta-gone.json" else real(p, roots)
        try:
            run(DELETE_ON)
        finally:
            otto_retention._remove = real
        self.assertIsNone(B("gone"))
        card = [r for r in D()["recommendations"] if r.get("deleted") == "gone" and r["priority"] == "P0"]
        self.assertEqual(len(card), 1)
        self.assertIn("meta-gone.json", card[0]["why"])
        self.assertEqual(json.loads((TMP / ".retention-journal.json").read_text())["pending"], {})

    def test_remove_refuses_paths_outside_the_data_dirs(self):
        outside = Path(tempfile.mkdtemp(prefix="otto-retention-outside-")) / "keep.txt"
        outside.write_text("keep")
        try:
            self.assertFalse(quiet(otto_retention._remove, outside, otto_retention._allowed_roots("gone")))
            self.assertTrue(outside.exists())
            self.assertFalse(quiet(otto_retention._remove, TMP / "assets", otto_retention._allowed_roots("gone")))
            self.assertTrue((TMP / "assets").is_dir())
        finally:
            shutil.rmtree(outside.parent, ignore_errors=True)


class LeadsAndExportsTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_leads_without_activity_for_the_retention_are_pruned(self):
        today = date(2026, 9, 30)
        quiet(otto_retention.prune_leads, today)                 # default 730 days
        leads = json.loads((TMP / "leads.json").read_text())["leads"]
        self.assertEqual(sorted(leads), ["d:alive.example", "d:gone-shop.example", "d:recent-lead.example", "v:2026-08-01:beef1234"])
        ev = [json.loads(l) for l in (TMP / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len(ev), 6)
        old = next(e for e in ev if e["ts"].startswith("2023"))
        self.assertNotIn("domain", old)
        self.assertEqual(sum(1 for e in ev if e.get("domain")), 4)
        self.assertIn("retention leads pruned 2", (TMP / "actions.log").read_text())
        quiet(otto_retention.prune_leads, today)                 # idempotent
        self.assertEqual(len(json.loads((TMP / "leads.json").read_text())["leads"]), 4)

    def test_lead_retention_is_a_setting(self):
        os.environ["OTTO_LEAD_RETENTION_DAYS"] = "60"
        try:
            self.assertEqual(otto_retention.lead_days(), 60)
            quiet(otto_retention.prune_leads, date(2026, 9, 30))
        finally:
            os.environ.pop("OTTO_LEAD_RETENTION_DAYS", None)
        self.assertEqual(otto_retention.lead_days(), 730)
        self.assertEqual(sorted(json.loads((TMP / "leads.json").read_text())["leads"]), ["d:recent-lead.example", "v:2026-08-01:beef1234"])

    def test_a_run_ahead_of_the_clock_keeps_the_export_it_just_made(self):
        # regression (journey): the export is stamped with the wall clock; a run with a --today more than 30 days ahead pruned
        # the deleted client's only export in the same run
        day = date.today() + timedelta(days=400)
        run(day)                                                   # the 3-day notice (the date passed long ago)
        self.assertEqual(run(day + timedelta(days=3)), 0, quiet.out)
        self.assertIsNone(B("gone"))
        self.assertEqual(len(list((TMP / "exports").glob("otto-export-gone-*.zip"))), 1, "the export of a deleted brand was pruned")

    def test_exports_are_kept_30_days(self):
        (TMP / "exports").mkdir()
        for name in ("otto-export-gone-20260801T040000Z.zip", "otto-export-gone-20260901T040000Z.zip", "notes.txt"):
            (TMP / "exports" / name).write_text("x")
        quiet(otto_retention.prune_exports, date(2026, 9, 5))
        self.assertEqual(sorted(f.name for f in (TMP / "exports").iterdir()), ["notes.txt", "otto-export-gone-20260901T040000Z.zip"])


class CronTest(unittest.TestCase):
    def test_retention_is_a_daily_owner_job(self):
        j = otto_cron.JOBS["retention"]
        self.assertEqual((j.local, j.scope, j.every, j.kill), ("04:40", otto_cron.ONCE, 1440, False))
        argv = otto_cron.once_argv("retention", date(2026, 10, 1))
        self.assertEqual([Path(argv[1]).name] + argv[2:], ["otto_retention.py", "run"])
        timer = PLATFORM.parent / "infra" / "systemd" / "otto-job-retention.timer"
        self.assertEqual(timer.read_text(), otto_cron.timer_text("retention"))
        dropin = PLATFORM.parent / "infra" / "systemd" / "otto-job@retention.service.d" / "secrets.conf"
        self.assertIn("ReadWritePaths=/etc/otto/secrets", dropin.read_text())


if __name__ == "__main__":
    unittest.main()
