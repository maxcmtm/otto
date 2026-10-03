#!/usr/bin/env python3
"""What Otto is making right now (otto_progress → GET /otto-api/data brands[].work, posts[].work): each state only when it is
true — writing (a run started and has not ended, a claimed queue file, posts saved after the last run's end), queued (a queue
file, a kickoff that just spawned the run, the daily job not at this brand yet), scheduled (the trials job's catch-up, the
daily 05:30 copy job, the hourly card rendering, the 18:30 reels job — with the brand-local time), waiting (no key, copy by
hand, paused, a failed render), done — the counts, the ETA, the per-post marks; and the tenant rule: a client's answer
carries work for its own brands and posts only, and never a cost, a token count, a model, a cap reason or the key.
Stdlib unittest, nothing outside a throwaway workspace, no network beyond 127.0.0.1, no Claude call.

  cd platform && python3 tests/test_progress.py
"""
import contextlib, http.server, io, json, os, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-progress-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_COPY_LEDGER": str(TMP / "copy-usage.json"), "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"),
       "OTTO_LOCKS": str(TMP / "locks"), "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_SESSIONS": str(TMP / "sessions.json")}
CLEAR = ("ANTHROPIC_API_KEY", "OTTO_COPY", "OTTO_COPY_QUEUE", "OTTO_COPY_MODEL", "OTTO_ANTHROPIC_API_BASE", "OTTO_ADMIN_USERS",
         "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_TZ", "OTTO_PLANS", "OTTO_CRON_NOW")
KEY = "otto-progress-test-key-not-real"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)        # 14:00 in Amsterdam
_SAVED = {}


def brand(bid, **kw):
    b = {"id": bid, "name": bid.title(), "url": f"{bid}.example", "lang": "EN", "tz": "Europe/Amsterdam", "status": "active",
         "plan": "starter", "countries": ["NL"], "members": [f"owner@{bid}.example"], "pillars": ["Education"], "copy_auto": True}
    b.update(kw)
    return b


def post(pid, bid, slot, status="draft", fmt="post", hook="", **kw):
    p = {"id": pid, "brand": bid, "platform": "ig", "format": fmt, "pillar": "Education", "status": status, "slot": slot, "hook": hook}
    p.update(kw)
    return p


def written(at="2026-10-01T10:00:00Z", **kw):
    return dict({"by": "otto_copy", "model": "claude-opus-5-5", "at": at, "attempts": 1, "state": "written", "job": "week"}, **kw)


def seed():
    return {"brands": [brand("tri", kickoff={"done": True, "at": "2026-10-02T11:55:00Z", "months": ["2026-10"], "copy_needed": True},
                             trial={"user": "u1", "started_at": "2026-10-02T11:50:00Z", "ends_at": "2099-01-01T00:00:00Z"}),
                       brand("day"), brand("hand", copy_auto=False)],
            "posts": [post("tr-1", "tri", "2026-10-03T09:00"),
                      post("tr-2", "tri", "2026-10-04T09:00", fmt="carousel"),
                      post("tr-3", "tri", "2026-10-03T18:00", status="pending_approval", hook="Fresh beans", caption="c",
                           copy=written(), image="assets/posts/tr-3.jpg"),
                      post("tr-4", "tri", "2026-10-05T09:00", fmt="reel"),
                      post("tr-5", "tri", "2026-10-20T09:00"),
                      post("tr-6", "tri", "2026-10-04T12:00", status="skipped"),
                      post("tr-7", "tri", "2026-10-01T09:00"),                       # its slot has passed: nobody writes it
                      post("dy-1", "day", "2026-10-03T09:00"),
                      post("dy-2", "day", "2026-10-03T12:00", status="pending_approval", hook="Ready", caption="c", copy=written()),
                      post("hd-1", "hand", "2026-10-03T09:00")],
            "recommendations": [], "connections": [], "campaigns": []}


def save(d):
    (TMP / "data.json").write_text(json.dumps(d, indent=1))


def data():
    return json.loads((TMP / "data.json").read_text())


def edit(fn):
    d = data()
    fn(d)
    save(d)


def P(d, pid):
    return next(p for p in d["posts"] if p["id"] == pid)


def B(d, bid):
    return next(b for b in d["brands"] if b["id"] == bid)


def ledger(**runs):
    (TMP / "copy-usage.json").write_text(json.dumps({"days": {"2026-10-02": {"calls": 9, "usd": 1.2345, "input_tokens": 99999,
                                                                             "output_tokens": 55555, "brands": {}}},
                                                     "brands": runs}))


def work(now=NOW, bids=None):
    """with_work over a client view (bids) or the owner's whole data → (brands by id, posts by id)."""
    d = data()
    view = otto_api.client_view(d, bids) if bids is not None else json.loads(json.dumps(d))
    otto_progress.with_work(view, full=d, now=now)
    return {b["id"]: b.get("work") for b in view["brands"]}, {p["id"]: p.get("work") for p in view["posts"]}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    for f in ("brands", "secrets", "assets", "locks"):
        (TMP / f).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_api, otto_progress
    import ap, otto_api, otto_progress                      # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG)
    ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = TMP / "data.json", TMP / "index.html", TMP / "brands", TMP / "actions.log"


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class _Reset:
    def setUp(self):
        save(seed())
        for f in ("copy-usage.json", "heartbeats.json"):
            (TMP / f).unlink(missing_ok=True)
        shutil.rmtree(TMP / "queue", ignore_errors=True)
        for k in ("ANTHROPIC_API_KEY", "OTTO_COPY_QUEUE", "OTTO_COPY"):
            os.environ.pop(k, None)

    def key(self):
        os.environ["ANTHROPIC_API_KEY"] = KEY


class StatesTest(_Reset, unittest.TestCase):
    def test_no_key_the_otto_team_prepares_it(self):
        bw, pw = work()
        c = bw["tri"]["copy"]
        self.assertEqual((c["state"], c["done"], c["total"], c["first_week"]), ("waiting", 1, 4, True))
        self.assertNotIn("next_run", c)
        self.assertNotIn("eta_minutes", c)
        self.assertFalse(bw["tri"]["active"])
        for pid in ("tr-1", "tr-2", "tr-4", "tr-5"):
            self.assertEqual(pw[pid], {"what": "copy", "state": "waiting"}, pid)
        self.assertIsNone(pw["tr-3"], "a written post with its image is not in progress")
        self.assertIsNone(pw["tr-6"], "a skipped post is nobody's work")
        self.assertIsNone(pw["tr-7"], "a slot that has passed is not promised to anyone")
        self.assertEqual(bw["day"]["copy"]["state"], "waiting")
        os.environ["OTTO_COPY"] = "off"
        self.key()
        self.assertEqual(work()[0]["tri"]["copy"]["state"], "waiting", "a key with the copywriter switched off writes nothing")

    def test_a_kickoff_that_just_spawned_its_run_is_queued(self):
        self.key()
        bw, pw = work()
        c = bw["tri"]["copy"]
        self.assertEqual(c["state"], "queued")
        self.assertEqual(c["eta_minutes"], 5)                  # one round of 8 posts (2.5 min) + the cards + the start
        self.assertTrue(bw["tri"]["active"])
        self.assertEqual(pw["tr-1"], {"what": "copy", "state": "queued"})
        self.assertEqual(pw["tr-5"], {"what": "copy", "state": "scheduled", "next_run": "2026-10-14T05:30"},
                         "a slot beyond the 7 days: the first daily run with it inside its week")
        later = work(NOW + timedelta(minutes=20))[0]["tri"]["copy"]
        self.assertEqual((later["state"], later["next_run"]), ("scheduled", "2026-10-02T15:05"),
                         "no run showed up: the hourly trials job (:05 UTC) catches up 15 minutes after the kickoff")

    def test_a_started_run_is_writing_until_the_ledger_says_it_ended(self):
        self.key()
        edit(lambda d: B(d, "tri")["kickoff"].update(copy_try_at="2026-10-02T11:59:00Z"))
        ledger(tri={"at": "2026-10-01T10:00:00Z", "job": "daily", "written": 3, "usd": 0.5, "stop": "the daily spend cap of $40 is reached"})
        bw, pw = work()
        c = bw["tri"]["copy"]
        self.assertEqual((c["state"], c["done"], c["total"]), ("writing", 1, 4))
        self.assertEqual(c["eta_minutes"], 3)                  # 3.5 minutes estimated, one gone
        self.assertEqual({pw[x]["state"] for x in ("tr-1", "tr-2", "tr-4")}, {"writing"})
        edit(lambda d: [P(d, "tr-1").update(hook="One", caption="c", status="pending_approval", copy=written("2026-10-02T11:59:40Z")),
                        P(d, "tr-2").update(hook="Two", caption="c", status="pending_approval", copy=written("2026-10-02T11:59:50Z"))])
        c = work(NOW + timedelta(minutes=1))[0]["tri"]["copy"]
        self.assertEqual((c["state"], c["done"], c["total"], c["eta_minutes"]), ("writing", 3, 4, 1), "the run's own pace")
        ledger(tri={"at": "2026-10-02T12:00:30Z", "job": "week", "written": 2})
        c = work(NOW + timedelta(minutes=1))[0]["tri"]["copy"]
        self.assertEqual((c["state"], c["next_run"]), ("scheduled", "2026-10-02T15:05"),
                         "ended with one post left: the catch-up 50 minutes after the try, on the next :05 tick")
        self.assertGreater(c["eta_minutes"], 60)

    def test_posts_saved_after_the_last_end_mean_a_run_is_still_going(self):
        self.key()
        ledger(day={"at": "2026-10-02T03:40:00Z", "job": "daily"})
        edit(lambda d: P(d, "dy-2").update(copy=written("2026-10-02T11:58:00Z", job="daily")))
        self.assertEqual(work()[0]["day"]["copy"]["state"], "writing")
        ledger(day={"at": "2026-10-02T11:59:00Z", "job": "daily"})
        c = work()[0]["day"]["copy"]
        self.assertEqual((c["state"], c["next_run"]), ("scheduled", "2026-10-03T05:30"), "the daily copy job, 05:30 brand time")
        self.assertFalse(c["first_week"])

    def test_the_daily_job_running_but_not_at_this_brand_yet_is_queued(self):
        self.key()
        (TMP / "heartbeats.json").write_text(json.dumps({"jobs": {"copy": {"running": {"started": "2026-10-02T03:31:00Z"},
                                                                           "brands": {"day": {"day": "2026-10-01"}}}}}))
        early = NOW.replace(hour=4)                            # 06:00 in Amsterdam: today's 05:30 run is on
        self.assertEqual(work(early)[0]["day"]["copy"]["state"], "queued")
        (TMP / "heartbeats.json").write_text(json.dumps({"jobs": {"copy": {"brands": {"day": {"day": "2026-10-01"}}}}}))
        c = work(early)[0]["day"]["copy"]
        self.assertEqual((c["state"], c["next_run"]), ("scheduled", "2026-10-02T06:30"), "due, not run: the next hourly tick")

    def test_copy_written_by_hand_waits_for_the_team(self):
        self.key()
        bw, pw = work()
        self.assertEqual(bw["hand"]["copy"]["state"], "waiting")
        self.assertEqual(pw["hd-1"], {"what": "copy", "state": "waiting"})
        edit(lambda d: B(d, "day").update(paused={"at": "2026-10-01T10:00:00Z"}))
        self.assertEqual(work()[0]["day"]["copy"]["state"], "waiting", "a paused brand gets nothing automatic")

    def test_the_server_queue(self):
        self.key()
        q = TMP / "queue"
        q.mkdir()
        os.environ["OTTO_COPY_QUEUE"] = str(q)
        edit(lambda d: B(d, "tri")["kickoff"].update(at="2026-10-02T11:00:00Z"))
        self.assertEqual(work()[0]["tri"]["copy"]["state"], "scheduled", "nothing queued: the catch-up")
        (q / "tri.week").write_text("{}")
        self.assertEqual(work()[0]["tri"]["copy"]["state"], "queued")
        (q / "tri.week").rename(q / "tri.work")
        edit(lambda d: P(d, "tr-3").update(image=None, copy=written(render="pending")))
        bw, pw = work()
        self.assertEqual((bw["tri"]["copy"]["state"], bw["tri"]["images"]["state"], bw["tri"]["images"]["pending"]),
                         ("writing", "rendering", 1), "the queued run renders right after it writes")
        self.assertEqual(pw["tr-3"], {"what": "image", "state": "rendering"})
        old = (NOW - timedelta(hours=3)).timestamp()
        os.utime(q / "tri.work", (old, old))
        self.assertNotEqual(work()[0]["tri"]["copy"]["state"], "writing", "a claimed file 3 hours old is a dead run")

    def test_images_and_reels(self):
        edit(lambda d: [P(d, "tr-3").update(image=None, copy=written(render="pending")),
                        P(d, "dy-2").update(image=None, copy=written(render="failed")),
                        d["posts"].append(post("dy-3", "day", "2026-10-04T09:00", status="pending_approval", fmt="reel", hook="Reel",
                                               caption="c", copy=written(), image="assets/posts/dy-3.jpg")),
                        d["posts"].append(post("dy-4", "day", "2026-10-04T10:00", status="published", fmt="reel", hook="Old",
                                               caption="c", copy=written()))])
        bw, pw = work()
        im = bw["tri"]["images"]
        self.assertEqual((im["state"], im["pending"], im["next_run"], im["eta_minutes"]), ("scheduled", 1, "2026-10-02T14:05", 5),
                         "the trials job renders pending cards every hour at :05 UTC, key or not")
        self.assertEqual(pw["tr-3"], {"what": "image", "state": "scheduled", "next_run": "2026-10-02T14:05"})
        self.assertEqual(bw["day"]["images"]["state"], "waiting", "a render that failed is the team's")
        self.assertEqual(pw["dy-2"], {"what": "image", "state": "waiting"})
        r = bw["day"]["reels"]
        self.assertEqual((r["state"], r["pending"], r["next_run"]), ("scheduled", 1, "2026-10-02T18:30"))
        self.assertEqual(pw["dy-3"], {"what": "video", "state": "scheduled", "next_run": "2026-10-02T18:30"})
        self.assertIsNone(pw["dy-4"], "a published reel is nobody's work")
        self.assertEqual(pw["tr-4"]["what"], "copy", "an unwritten reel needs its copy before its video")
        evening = NOW.replace(hour=16, minute=45)              # 18:45 in Amsterdam
        (TMP / "heartbeats.json").write_text(json.dumps({"jobs": {"reels": {"running": {"started": "2026-10-02T16:31:00Z"}, "brands": {}}}}))
        self.assertEqual(work(evening)[0]["day"]["reels"]["state"], "rendering")
        (TMP / "heartbeats.json").write_text(json.dumps({"jobs": {"reels": {"brands": {"day": {"day": "2026-10-02"}}}}}))
        self.assertEqual(work(evening)[0]["day"]["reels"]["next_run"], "2026-10-03T18:30", "ran today: tomorrow")
        edit(lambda d: B(d, "day").update(plan="none"))
        self.assertEqual(work()[0]["day"]["reels"]["state"], "waiting", "no plan, no reels job")

    def test_done(self):
        self.key()
        edit(lambda d: [p.update(hook="H " + p["id"], caption="c", status="pending_approval", copy=written())
                        for p in d["posts"] if p["brand"] == "tri" and p["status"] == "draft"])
        bw, pw = work()
        c = bw["tri"]["copy"]
        self.assertEqual((c["state"], c["done"], c["total"], c["first_week"]), ("done", 4, 4, True), "the next 7 days")
        self.assertFalse(bw["tri"]["active"])
        self.assertEqual([pid for pid, w in pw.items() if w and pid.startswith("tr-")], ["tr-4"], "only the reel's video is left")
        edit(lambda d: B(d, "tri")["kickoff"].update(copy_needed=False, at="2026-09-20T10:00:00Z"))
        self.assertFalse(work()[0]["tri"]["copy"]["first_week"], "a first week is the first week for two days")

    def test_onboarding_summary(self):
        self.key()
        s = otto_progress.copy_summary("tri", now=NOW)
        self.assertEqual(s, {"state": "queued", "done": 1, "total": 4, "first_week": True, "eta_minutes": 5})
        self.assertIsNone(otto_progress.copy_summary("nobody"))

    def test_never_fails_the_answer(self):
        edit(lambda d: B(d, "tri").update(tz="Not/AZone", kickoff="garbage"))
        edit(lambda d: P(d, "tr-1").update(copy="garbage", slot="not a time"))
        bw, _ = work()
        self.assertIn(bw["tri"]["copy"]["state"], ("waiting", "done"))


SECRETS = ("usd", "tokens", "token", "cost", "claude-opus", "model", "calls", "spend cap", "stop", "job", KEY, "1.2345", "3.21")


def assert_clean(tc, obj):
    """No owner-internal ledger data in any work field of an answer."""
    blob = json.dumps({"brands": [b.get("work") for b in obj["brands"]], "posts": [p.get("work") for p in obj["posts"]]})
    for s in SECRETS:
        tc.assertNotIn(s, blob, s)


class TenantTest(_Reset, unittest.TestCase):

    def test_a_client_view_carries_work_for_its_own_brands_only(self):
        self.key()
        ledger(tri={"at": "2026-10-01T10:00:00Z", "usd": 3.21, "stop": "the daily spend cap of $40 is reached"},
               day={"at": "2026-10-02T11:59:59Z", "usd": 9.99})
        d = data()
        view = otto_progress.with_work(otto_api.client_view(d, {"tri"}), full=d, now=NOW)
        self.assertEqual([b["id"] for b in view["brands"]], ["tri"])
        self.assertTrue(view["brands"][0]["work"]["copy"])
        self.assertEqual({p["brand"] for p in view["posts"]}, {"tri"})
        self.assertEqual({p["brand"] for p in view["posts"] if p.get("work")}, {"tri"})
        self.assertNotIn("day", json.dumps(view), "another brand's work never shows up")
        assert_clean(self, view)
        self.assertNotIn("work", json.dumps(data()), "the stored data is never changed")
        self.assertTrue(all("work" not in p for p in d["posts"]), "the loaded data is not changed either: marked posts are copies")

    def test_the_owner_gets_every_brand(self):
        bw, _ = work(bids=None)
        self.assertEqual(set(bw), {"tri", "day", "hand"})


class HttpTest(_Reset, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, user):
        r = urllib.request.Request(self.base + "/otto-api/data", headers={"X-Real-IP": "203.0.113.9", "X-Otto-User": user})
        try:
            with urllib.request.urlopen(r, timeout=15) as x:
                return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_get_data_as_a_client(self):
        self.key()
        ledger(tri={"at": "2026-10-01T10:00:00Z", "usd": 3.21, "stop": "the daily spend cap of $40 is reached"})
        code, d = self.get("owner@tri.example")
        self.assertEqual(code, 200)
        self.assertEqual([b["id"] for b in d["brands"]], ["tri"])
        w = d["brands"][0]["work"]
        self.assertEqual(set(w), {"copy", "images", "reels", "active", "at"})
        self.assertIn(w["copy"]["state"], ("writing", "queued", "scheduled", "waiting", "done"))
        self.assertTrue(any(p.get("work") for p in d["posts"]))
        self.assertEqual({p["brand"] for p in d["posts"]}, {"tri"})
        assert_clean(self, d)
        self.assertNotIn(KEY, json.dumps(d))
        self.assertNotIn("spend cap", json.dumps(d))
        code, d = self.get("owner@day.example")
        self.assertEqual([b["id"] for b in d["brands"]], ["day"])
        self.assertNotIn("tri", json.dumps([p.get("work") for p in d["posts"]]))


if __name__ == "__main__":
    unittest.main()
