#!/usr/bin/env python3
"""Job dispatcher tests (otto_cron): who runs what over a fixture data.json (active, paused, onboarding and legacy brands),
the kill switch, the per-brand pre-checks, heartbeat content, a failing brand → exit 1, --dry, the per-job lock, the reels
expansion, the per-brand time limit, heartbeat_rows() for the owner console, and the committed systemd timers matching JOBS.
Stdlib unittest, no network. Real runs execute otto_cron.py in a subprocess against a throwaway workspace whose job scripts
are stubs (OTTO_CRON_BIN) that record their argv; nothing outside the workspace is touched.

  cd platform && python3 tests/test_cron.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import fcntl, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
REPO = PLATFORM.parent
otto_cron = None     # imported in setUpModule: importing it at load time would import ap with the real repo paths under discover


def setUpModule():
    global otto_cron
    sys.path.insert(0, str(PLATFORM))
    import otto_cron as oc      # plan() / tasks() / heartbeat_rows() take their data and paths explicitly; runs are subprocesses
    otto_cron = oc

TODAY = date(2026, 10, 25)            # plan day: the next month is 2026-11
SCRIPTS = ["otto_publish.py", "otto_telegram.py", "genvisuals.py", "otto_video.py", "otto_ads.py", "otto_insights.py",
           "otto_competitors.py", "otto_plan.py", "otto_watch.py", "otto_growth.py", "otto_whop.py", "otto_track.py"]
STUB = r'''
import json, os, sys, time
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.environ["STUB_RECORD"], "a") as f:
    f.write(json.dumps([name] + args) + "\n")
if name == "otto_video.py" and args[:1] == ["missing"]:
    if "alpha" in args:
        print("r-001")
        print("r-002")
    sys.exit(0)
if os.environ.get("STUB_SLEEP") and os.environ["STUB_SLEEP"] in args:
    time.sleep(60)
print("stub", name, " ".join(args), "key" if os.environ.get("LEONARDO_API_KEY") else "nokey")
if os.environ.get("STUB_FAIL") and os.environ["STUB_FAIL"] in args:
    print("boom: token rejected", file=sys.stderr)
    sys.exit(1)
'''


def fixture():
    return {"brands": [
        {"id": "alpha", "name": "Alpha", "status": "active", "countries": ["DE"]},
        {"id": "beta", "name": "Beta", "status": "active", "paused": {"at": "2026-10-20T10:00:00Z", "by": "max"}},
        {"id": "gamma", "name": "Gamma", "status": "onboarding"},
        {"id": "delta", "name": "Delta"},                                    # an old record without a status counts as active
        {"id": "zeta", "name": "Zeta", "status": "active",
         "cron": {"off": ["genvisuals"], "ads_budget": 30, "country": "IL", "visuals_limit": 4, "per_week": 8}},
        {"id": "eta", "name": "Eta", "status": "active", "onboarding": {"budget": "not_yet"}},
        {"id": "theta", "name": "Theta", "status": "paused"}],
        "posts": [{"id": "al-001", "brand": "alpha", "plan": "2026-11", "status": "draft"}],
        "campaigns": [{"id": "cp-001", "brand": "delta", "plan": "2026-11", "status": "draft"}],
        "recommendations": [], "controls": {}}


def by_brand(ts):
    return {t.brand: t for t in ts}


def tail(argv):
    """argv without the interpreter, script path as its file name."""
    return [Path(argv[1]).name] + argv[2:]


class PlanTest(unittest.TestCase):
    """tasks(): what each job would run for each brand."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="otto-cron-plan-"))
        (cls.tmp / "alpha").mkdir()
        (cls.tmp / "alpha" / "competitors.json").write_text("[]")
        (cls.tmp / "zeta").mkdir()
        (cls.tmp / "zeta" / "brand-profile.md").write_text("# Competitors\nAcme\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def plan(self, job, d=None, today=TODAY):
        return by_brand(otto_cron.tasks(job, d or fixture(), today, self.tmp))

    def test_publish_runs_active_brands_only(self):
        t = self.plan("publish")
        self.assertEqual(sorted(b for b, x in t.items() if not x.skip), ["alpha", "delta", "eta", "zeta"])
        self.assertEqual(t["beta"].skip, "paused")
        self.assertEqual(t["theta"].skip, "paused")
        self.assertEqual(t["gamma"].skip, "onboarding")
        self.assertEqual(tail(t["alpha"].argv), ["otto_publish.py", "--brand", "alpha"])

    def test_kill_switch_stops_publish_and_launch_only(self):
        d = fixture()
        d["controls"]["publishing_paused"] = {"at": "2026-10-25T01:00:00Z", "by": "max", "note": "migration"}
        for job in ("publish", "ads-launch"):
            t = self.plan(job, d)
            self.assertTrue(all(x.skip and "kill switch" in x.skip for x in t.values()), job)
        cards = self.plan("cards", d)
        self.assertIsNone(cards["alpha"].skip)
        guard = otto_cron.tasks("ads-guard", d, TODAY, self.tmp)
        self.assertEqual(len(guard), 1)
        self.assertIsNone(guard[0].skip)                     # ended campaigns must still be paused
        self.assertEqual(tail(guard[0].argv), ["otto_ads.py", "guard"])

    def test_monthly_plan_prechecks(self):
        t = self.plan("plan-month")
        self.assertIn("already planned", t["alpha"].skip)
        self.assertEqual(tail(t["delta"].argv), ["otto_plan.py", "build", "delta", "2026-11"])
        self.assertEqual(tail(t["zeta"].argv), ["otto_plan.py", "build", "zeta", "2026-11", "--per-week", "8"])
        a = self.plan("ads-plan")
        self.assertIn("already exists", a["delta"].skip)
        self.assertIn("no ad budget", a["eta"].skip)
        self.assertEqual(tail(a["zeta"].argv), ["otto_ads.py", "plan", "zeta", "2026-11", "--budget", "30"])
        self.assertEqual(tail(a["alpha"].argv), ["otto_ads.py", "plan", "alpha", "2026-11"])

    def test_next_month_rolls_over_the_year(self):
        self.assertEqual(otto_cron.next_month(date(2026, 12, 25)), "2027-01")
        self.assertEqual(otto_cron.next_month(date(2026, 11, 25)), "2026-12")

    def test_competitors_country_and_missing_list(self):
        t = self.plan("competitors")
        self.assertEqual(tail(t["alpha"].argv), ["otto_competitors.py", "sweep", "alpha", "--country", "DE"])
        self.assertEqual(tail(t["zeta"].argv), ["otto_competitors.py", "sweep", "zeta", "--country", "IL"])
        self.assertIn("no competitor list", t["delta"].skip)
        self.assertIn("no competitor list", t["eta"].skip)

    def test_visuals_limits_off_switch_and_reels(self):
        g = self.plan("genvisuals")
        self.assertEqual(tail(g["alpha"].argv), ["genvisuals.py", "--brand", "alpha", "--limit", "12"])
        self.assertIn("cron.off", g["zeta"].skip)
        r = self.plan("reels")
        self.assertEqual(tail(r["alpha"].argv), ["otto_video.py", "missing", "--brand", "alpha"])
        self.assertEqual(tail(r["alpha"].expand), ["otto_video.py", "render"])

    def test_once_jobs(self):
        for day, send in ((1, True), (3, True), (4, False), (25, False)):
            g = otto_cron.tasks("growth", fixture(), date(2026, 11, day), self.tmp)[0]
            self.assertEqual("--send" in g.argv, send, day)
        saved = otto_cron.whop_connected
        try:
            otto_cron.whop_connected = lambda: False
            self.assertIn("not connected", otto_cron.tasks("whop-sync", fixture(), TODAY, self.tmp)[0].skip)
            otto_cron.whop_connected = lambda: True
            w = otto_cron.tasks("whop-sync", fixture(), TODAY, self.tmp)[0]
            self.assertIsNone(w.skip)
            self.assertEqual(tail(w.argv), ["otto_whop.py", "backfill"])
        finally:
            otto_cron.whop_connected = saved

    def test_every_job_script_exists(self):
        d = {"brands": [{"id": "x", "status": "active", "countries": ["DE"], "approvals": ["email", "telegram"]}], "posts": [], "campaigns": []}
        (self.tmp / "x").mkdir(exist_ok=True)
        (self.tmp / "x" / "competitors.json").write_text("[]")
        saved = otto_cron.whop_connected
        otto_cron.whop_connected = lambda: True
        try:
            for job in otto_cron.JOBS:
                for t in otto_cron.tasks(job, d, TODAY, self.tmp):
                    self.assertIsNone(t.skip, job)
                    self.assertTrue((PLATFORM / Path(t.argv[1]).name).is_file(), f"{job}: {t.argv[1]}")
        finally:
            otto_cron.whop_connected = saved


class RunTest(unittest.TestCase):
    """otto_cron.py <job> in a subprocess, with stub job scripts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="otto-cron-run-"))
        (self.tmp / "bin").mkdir()
        for name in SCRIPTS:
            (self.tmp / "bin" / name).write_text(STUB)
        (self.tmp / "brands" / "alpha").mkdir(parents=True)
        (self.tmp / "secrets").mkdir()
        self.write(fixture())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, d):
        (self.tmp / "data.json").write_text(json.dumps(d))

    def run_cron(self, *args, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("OTTO_", "STUB_")) and k not in ("LEONARDO_API_KEY", "WHOP_API_KEY", "WHOP_COMPANY_ID")}
        env.update(OTTO_DATA=str(self.tmp / "data.json"), OTTO_BRANDS=str(self.tmp / "brands"), OTTO_SECRETS=str(self.tmp / "secrets"),
                   OTTO_HTML=str(self.tmp / "index.html"), OTTO_CRON_BIN=str(self.tmp / "bin"), STUB_RECORD=str(self.tmp / "record.jsonl"))
        env.update(extra)
        return subprocess.run([sys.executable, str(PLATFORM / "otto_cron.py")] + list(args), env=env, capture_output=True,
                              text=True, timeout=90)

    def record(self):
        f = self.tmp / "record.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def hb(self, job=None):
        h = json.loads((self.tmp / "heartbeats.json").read_text())
        return h["jobs"][job] if job else h

    def test_failing_brand_exits_1_and_the_heartbeat_says_who(self):
        r = self.run_cron("publish", STUB_FAIL="delta")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(sorted(x[2] for x in self.record()), ["alpha", "delta", "eta", "zeta"])
        h = self.hb("publish")
        self.assertEqual((h["status"], h["exit"], h["fails_in_row"]), ("failed", 1, 1))
        self.assertEqual(h["brands"]["alpha"]["status"], "ok")
        self.assertEqual((h["brands"]["delta"]["status"], h["brands"]["delta"]["exit"]), ("failed", 1))
        self.assertIn("boom: token rejected", h["brands"]["delta"]["tail"])
        self.assertEqual((h["brands"]["beta"]["status"], h["brands"]["beta"]["why"]), ("skipped", "paused"))
        self.assertEqual((h["brands"]["gamma"]["status"], h["brands"]["gamma"]["why"]), ("skipped", "onboarding"))
        self.assertNotIn("day", h["brands"]["alpha"])                           # publish is not a wall-clock job
        for k in ("started", "ended", "duration_s", "last_failed", "label", "schedule", "every_min", "summary"):
            self.assertIn(k, h)
        self.assertNotIn("running", h)
        self.assertIn("1 failed (delta)", h["summary"])
        self.assertIn("FAILED", r.stdout)
        log = (self.tmp / "publish.log").read_text()
        self.assertIn("== ", log)
        self.assertIn("stub otto_publish.py --brand alpha", log)
        self.assertIn("boom: token rejected", log)
        # the next clean run resets the streak and keeps when it last failed
        r = self.run_cron("publish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        h2 = self.hb("publish")
        self.assertEqual((h2["status"], h2["fails_in_row"]), ("ok", 0))
        self.assertEqual(h2["last_failed"], h["last_failed"])
        self.assertTrue(h2["last_ok"])

    def test_dry_prints_the_commands_and_runs_nothing(self):
        r = self.run_cron("publish", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("python3 otto_publish.py --brand alpha", r.stdout)
        self.assertIn("skipped: paused", r.stdout)
        self.assertIn("skipped: onboarding", r.stdout)
        self.assertEqual(self.record(), [])
        self.assertFalse((self.tmp / "heartbeats.json").exists())
        self.assertFalse((self.tmp / "publish.log").exists())

    def test_kill_switch_run_starts_nothing(self):
        d = fixture()
        d["controls"]["publishing_paused"] = {"at": "2026-10-25T01:00:00Z", "by": "max"}
        self.write(d)
        r = self.run_cron("publish")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record(), [])
        h = self.hb("publish")
        self.assertEqual(h["status"], "skipped")
        self.assertTrue(all("kill switch" in b["why"] for b in h["brands"].values()))
        r = self.run_cron("ads-guard", "--all")                # guard keeps running under the kill switch
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record(), [["otto_ads.py", "guard"]])

    def test_second_run_while_the_first_holds_the_lock(self):
        (self.tmp / "locks").mkdir()
        with open(self.tmp / "locks" / "publish.lock", "a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            r = self.run_cron("publish")
        self.assertEqual(r.returncode, otto_cron.EXIT_BUSY, r.stdout + r.stderr)
        self.assertEqual(self.record(), [])
        self.assertFalse((self.tmp / "heartbeats.json").exists())

    def test_reels_render_every_missing_id(self):
        r = self.run_cron("reels", "--all", STUB_FAIL="r-002")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        calls = self.record()
        self.assertIn(["otto_video.py", "missing", "--brand", "alpha"], calls)
        self.assertIn(["otto_video.py", "render", "r-001"], calls)
        self.assertIn(["otto_video.py", "render", "r-002"], calls)
        h = self.hb("reels")
        self.assertEqual(h["brands"]["alpha"]["status"], "failed")
        self.assertEqual(h["brands"]["delta"]["status"], "ok")          # nothing missing → just the listing

    def test_a_hanging_brand_is_killed_and_the_rest_still_run(self):
        r = self.run_cron("cards", "--all", STUB_SLEEP="alpha", OTTO_CRON_TIMEOUT_S="4")   # 4 s: a loaded CI box starts python slowly
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        h = self.hb("cards")
        self.assertEqual(h["brands"]["alpha"]["exit"], 124)
        self.assertTrue(any("timed out" in x for x in h["brands"]["alpha"]["tail"]))
        self.assertEqual(h["brands"]["zeta"]["status"], "ok")

    def test_leonardo_key_reaches_only_the_visual_jobs(self):
        (self.tmp / "secrets" / "leonardo.json").write_text(json.dumps({"api_key": "leo-test-not-real"}))
        self.assertEqual(self.run_cron("genvisuals", "--all").returncode, 0)
        self.assertEqual(self.run_cron("insights", "--brand", "alpha").returncode, 0)
        self.assertIn("--limit 12 key", (self.tmp / "genvisuals.log").read_text())
        self.assertIn("--brand alpha nokey", (self.tmp / "insights.log").read_text())
        self.assertNotIn("leo-test-not-real", (self.tmp / "genvisuals.log").read_text() + (self.tmp / "heartbeats.json").read_text())

    def test_beat_cli_and_unknown_job(self):
        r = self.run_cron("beat", "backup", "ok", "--note", "otto-x.tar.zst.age 12 MB", "--every", "1440", "--label", "Backups")
        self.assertEqual(r.returncode, 0, r.stderr)
        h = self.hb("backup")
        self.assertEqual((h["status"], h["every_min"], h["label"], h["summary"]), ("ok", 1440, "Backups", "otto-x.tar.zst.age 12 MB"))
        rows = {x["job"]: x for x in otto_cron.heartbeat_rows(path=self.tmp / "heartbeats.json")}
        self.assertEqual(rows["backup"]["status"], "ok")
        self.assertEqual(rows["publish"]["status"], "never")
        self.assertEqual(self.run_cron("nope").returncode, 2)


class LocalTimeTest(unittest.TestCase):
    """Wall-clock jobs run at the brand's own local time (the owner's for owner jobs), DST included."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("OTTO_OWNER_TZ", "OTTO_TZ")}
        os.environ.pop("OTTO_TZ", None)
        os.environ["OTTO_OWNER_TZ"] = "Europe/Berlin"

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @staticmethod
    def data():
        return {"brands": [{"id": "il", "status": "active", "tz": "Asia/Jerusalem"},
                           {"id": "de", "status": "active", "tz": "Europe/Berlin"},
                           {"id": "ny", "status": "active", "tz": "America/New_York"},
                           {"id": "off", "status": "onboarding", "tz": "Europe/Berlin"}],
                "posts": [], "campaigns": []}

    def at(self, job, iso, last=None):
        now = datetime.fromisoformat(iso)
        todo, not_due = otto_cron.plan(job, self.data(), now, Path(tempfile.gettempdir()), last=last)
        return {t.brand: t for t in todo}, not_due

    def test_each_brand_at_its_own_eight_oclock(self):
        run, wait = self.at("cards", "2026-11-25T06:00:00+00:00")             # IL 08:00 · DE 07:00 · NY 01:00
        self.assertEqual(list(run), ["il"])
        self.assertIn("later today", wait["de"])
        self.assertEqual(run["il"].day, "2026-11-25")
        self.assertIn("later today", wait["off"])                              # an onboarding brand is only recorded …
        run, wait = self.at("cards", "2026-11-25T07:00:00+00:00", last={"il": "2026-11-25"})   # DE 08:00; IL already done
        self.assertEqual(sorted(run), ["de", "off"])
        self.assertIsNone(run["de"].skip)
        self.assertEqual(run["off"].skip, "onboarding")                        # … as skipped when its hour comes
        self.assertEqual(wait["il"], "already ran today")
        done = {"il": "2026-11-25", "de": "2026-11-25", "off": "2026-11-25"}
        run, wait = self.at("cards", "2026-11-25T13:00:00+00:00", last=done)
        self.assertEqual(list(run), ["ny"])                                     # NY 08:00

    def test_late_tick_catches_up_then_gives_up(self):
        run, _ = self.at("cards", "2026-11-25T08:00:00+00:00")                  # IL 10:00: a reboot delayed it, still today
        self.assertIn("il", run)
        run, wait = self.at("cards", "2026-11-25T09:00:00+00:00")               # IL 11:00: three hours late → the day is skipped
        self.assertNotIn("il", run)
        self.assertIn("missed", wait["il"])

    def test_daylight_saving_moves_the_utc_hour_not_the_local_one(self):
        run, _ = self.at("cards", "2026-10-24T06:00:00+00:00")                  # Berlin summer time (UTC+2): 08:00
        self.assertIn("de", run)
        run, _ = self.at("cards", "2026-10-26T06:00:00+00:00")                  # winter time (UTC+1): only 07:00 …
        self.assertNotIn("de", run)
        run, _ = self.at("cards", "2026-10-26T07:00:00+00:00")                  # … 08:00 an hour later in UTC
        self.assertIn("de", run)

    def test_weekly_and_monthly_use_the_local_day(self):
        run, wait = self.at("competitors", "2026-11-23T04:00:00+00:00")         # Mon: IL 06:00 · NY Sun 23:00
        self.assertEqual(list(run), ["il"])
        self.assertIn("not its day", wait["ny"])
        run, wait = self.at("plan-month", "2026-11-25T04:00:00+00:00")          # 25th: IL 06:00 → plans December
        self.assertEqual(run["il"].argv[-1], "2026-12")
        self.assertIn("not its day", wait["ny"])                                # still the 24th in New York

    def test_owner_jobs_follow_the_owner_timezone(self):
        run, _ = self.at("watch-report", "2026-11-25T06:30:00+00:00")           # owner (Berlin) 07:30
        self.assertEqual(list(run), ["*"])
        run, wait = self.at("watch-report", "2026-11-25T06:30:00+00:00", last={"*": "2026-11-25"})
        self.assertEqual((run, wait["*"]), ({}, "already ran today"))
        run, wait = self.at("recs", "2026-11-25T06:30:00+00:00")
        self.assertEqual(run, {})
        self.assertIn("later today", wait["*"])

    def test_forced_and_single_brand_runs_ignore_the_clock(self):
        todo, not_due = otto_cron.plan("cards", self.data(), datetime(2026, 11, 25, 3, tzinfo=timezone.utc), force=True)
        self.assertEqual(sorted(t.brand for t in todo if not t.skip), ["de", "il", "ny"])
        todo, _ = otto_cron.plan("cards", self.data(), datetime(2026, 11, 25, 3, tzinfo=timezone.utc), force=True, only="ny")
        self.assertEqual([t.brand for t in todo], ["ny"])


class LocalRunTest(RunTest):
    """A wall-clock job end to end: due brands run once per local day; a tick with nobody due keeps the last result."""

    def setUp(self):
        super().setUp()
        self.write({"brands": [{"id": "il", "status": "active", "tz": "Asia/Jerusalem"},
                               {"id": "de", "status": "active", "tz": "Europe/Berlin"}], "posts": [], "campaigns": []})

    def test_once_per_local_day(self):
        r = self.run_cron("cards", OTTO_CRON_NOW="2026-11-25T06:00:00Z")        # IL 08:00
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x[3] for x in self.record()], ["il"])
        first = self.hb("cards")
        self.assertEqual(first["brands"]["il"]["day"], "2026-11-25")
        r = self.run_cron("cards", OTTO_CRON_NOW="2026-11-25T06:30:00Z")        # same hour again: nothing due
        self.assertIn("nothing due", r.stdout)
        self.assertEqual(len(self.record()), 1)
        again = self.hb("cards")
        self.assertEqual((again["ended"], again["summary"]), (first["ended"], first["summary"]))
        self.assertTrue(again["checked"])
        r = self.run_cron("cards", OTTO_CRON_NOW="2026-11-25T07:00:00Z", STUB_FAIL="de")   # DE 08:00, fails
        self.assertEqual(r.returncode, 1)
        h = self.hb("cards")
        self.assertEqual((h["brands"]["il"]["status"], h["brands"]["de"]["status"]), ("ok", "failed"))
        self.assertEqual(h["brands"]["de"]["day"], "2026-11-25")               # counted: no automatic retry next hour
        r = self.run_cron("cards", OTTO_CRON_NOW="2026-11-25T08:00:00Z")
        self.assertIn("nothing due", r.stdout)
        rows = {x["job"]: x for x in otto_cron.heartbeat_rows(datetime(2026, 11, 25, 8, 5, tzinfo=timezone.utc),
                                                              self.tmp / "heartbeats.json")}
        self.assertEqual((rows["cards"]["status"], rows["cards"]["failed_brands"]), ("failed", ["de"]))
        r = self.run_cron("cards", "--brand", "de", OTTO_CRON_NOW="2026-11-25T08:10:00Z")   # the fix, by hand
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.hb("cards")["brands"]["de"]["status"], "ok")

    # the inherited RunTest cases run against this fixture too only where they make sense
    test_failing_brand_exits_1_and_the_heartbeat_says_who = None
    test_dry_prints_the_commands_and_runs_nothing = None
    test_kill_switch_run_starts_nothing = None
    test_second_run_while_the_first_holds_the_lock = None
    test_reels_render_every_missing_id = None
    test_a_hanging_brand_is_killed_and_the_rest_still_run = None
    test_leonardo_key_reaches_only_the_visual_jobs = None
    test_beat_cli_and_unknown_job = None


class HeartbeatRowsTest(unittest.TestCase):
    def test_rows_for_the_owner_console(self):
        now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        iso = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        jobs = {"publish": {"ended": iso(5), "status": "ok", "summary": "3 ok"},
                "watch": {"ended": iso(180), "status": "ok"},                            # hourly, 3 h ago → late
                "cards": {"ended": iso(60), "status": "failed", "summary": "1 failed (alpha)", "fails_in_row": 2,
                          "brands": {"alpha": {"status": "failed", "exit": 1}, "beta": {"status": "ok"}}},
                "genvisuals": {"ended": iso(1500), "status": "ok", "running": {"started": iso(1)}},
                "growth": {"ended": iso(60 * 24 * 10), "status": "ok"},                  # daily, 10 days ago → stale
                "backup": {"ended": iso(600), "status": "ok", "every_min": 1440, "label": "Backups"},
                "deploy": {"ended": iso(30), "status": "ok"}}                            # no cadence → not a row
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "heartbeats.json"
            self.assertEqual(otto_cron.heartbeat_rows(now, p), [])                       # no file → the console uses log mtimes
            p.write_text(json.dumps({"jobs": jobs}))
            rows = {r["job"]: r for r in otto_cron.heartbeat_rows(now, p)}
        self.assertEqual({k: rows[k]["status"] for k in ("publish", "watch", "cards", "genvisuals", "growth", "backup", "plan-month")},
                         {"publish": "ok", "watch": "late", "cards": "failed", "genvisuals": "running", "growth": "stale",
                          "backup": "ok", "plan-month": "never"})
        self.assertNotIn("deploy", rows)
        self.assertEqual(rows["cards"]["failed_brands"], ["alpha"])
        self.assertEqual(rows["cards"]["fails_in_row"], 2)
        self.assertEqual(rows["publish"]["last_line"], "3 ok")
        for key in ("job", "label", "log", "every_min", "last_run", "age_min", "status", "last_line"):   # otto_admin.cron_rows shape
            self.assertIn(key, rows["publish"])
        self.assertEqual(rows["backup"]["label"], "Backups")


class SystemdTest(unittest.TestCase):
    """The committed units match the dispatcher: one timer per job, same schedule (UTC), nothing stray."""
    UNITS = REPO / "infra" / "systemd"

    def test_timers_match_jobs(self):
        self.assertTrue(self.UNITS.is_dir(), "infra/systemd missing")
        for job in otto_cron.JOBS:
            f = self.UNITS / f"otto-job-{job}.timer"
            self.assertTrue(f.is_file(), f"{f.name} missing — python3 platform/otto_cron.py timers infra/systemd")
            self.assertEqual(f.read_text(), otto_cron.timer_text(job), f"{f.name} is stale — regenerate it")
        stray = [f.name for f in self.UNITS.glob("otto-job-*.timer") if f.name[9:-6] not in otto_cron.JOBS]
        self.assertEqual(stray, [])

    def test_job_service_runs_the_dispatcher_as_otto(self):
        s = (self.UNITS / "otto-job@.service").read_text()
        for line in ("User=otto", "EnvironmentFile=/etc/otto/otto.env", "OnFailure=otto-alert@%N.service",
                     f"SuccessExitStatus={otto_cron.EXIT_BUSY}", "otto_cron.py %i"):
            self.assertIn(line, s)


if __name__ == "__main__":
    unittest.main()
