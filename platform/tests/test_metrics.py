#!/usr/bin/env python3
"""Otto's Meta numbers against Graph API v26.0 (otto_metrics, otto_insights, otto_ads report, otto_report, otto_admin), with
recorded-shape Graph answers (tests/fixtures/meta_graph_v26.json) and no network:
  - the metric names Otto asks for (no metric Meta retired; the version pinned to v26.0),
  - the invalid-metric fallback (a refused metric is dropped, logged once, not asked again; other metrics survive;
    errors that are not about a metric are raised),
  - Instagram account + Facebook Page parsing and how they are stored in data.json metrics[brand] (backward compatible),
  - lead counting without double counting, cost per lead per kind, messaging conversations,
  - the baseline window math (30 days before joining, Meta's 2 years, the 48 h lag),
  - the 07:35 report and the owner console showing the same paid numbers, stories pulled before they expire.

  cd platform && python3 tests/test_metrics.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, os, shutil, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PLATFORM = Path(__file__).resolve().parent.parent
FIX = json.loads((PLATFORM / "tests" / "fixtures" / "meta_graph_v26.json").read_text())
TMP = Path(tempfile.mkdtemp(prefix="otto-metrics-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_REPORT_STATE": str(TMP / ".report-state.json"),
       "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"), "OTTO_OUTBOX": str(TMP / "outbox")}
CLEAR = ("GRAPH_API_VERSION", "OTTO_GRAPH_STATE", "OTTO_PLANS", "OTTO_TZ")
AMS = ZoneInfo("Europe/Amsterdam")
_SAVED = {}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, om, ins, pub, otto_ads, otto_report, otto_admin, otto_watch, otto_cron
    import ap, otto_metrics as om, otto_insights as ins, otto_publish as pub, otto_ads, otto_report, otto_admin  # noqa: E401
    import otto_watch, otto_cron                                                                                 # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, pub.SECRETS, otto_ads.SECRETS, otto_watch.HIST, pub.graph)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    pub.SECRETS = otto_ads.SECRETS = TMP / "secrets"
    otto_watch.HIST = TMP / "metrics_history.jsonl"


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS, pub.SECRETS, otto_ads.SECRETS, otto_watch.HIST, pub.graph = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        r = fn(*a, **kw)
    quiet.out = out.getvalue()
    return r


def fresh(data=None, creds=None):
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
        else:
            shutil.rmtree(f, ignore_errors=True)
    (TMP / "secrets").mkdir()
    (TMP / "brands").mkdir()
    for bid, c in (creds or {}).items():
        (TMP / "secrets" / f"meta-{bid}.json").write_text(json.dumps(c))
    (TMP / "data.json").write_text(json.dumps(data or {"brands": [], "posts": []}, ensure_ascii=False))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    om._logged.clear()
    om._memo.update(mtime=None, st={})
    otto_ads._acct.clear()


CREDS = {"access_token": "EAAG-test", "page_id": "1020000000001", "ig_user_id": "17841400000000001",
         "ad_account_id": "act_1234567890"}


class FakeGraph:
    """otto_publish.graph stand-in: routes each call to a recorded answer, raising the way otto_publish.graph does."""

    def __init__(self, refuse=(), refuse_with="err_fb_invalid_metric", fail=None):
        self.calls = []
        self.refuse, self.refuse_with, self.fail = set(refuse), refuse_with, fail      # fail: (predicate, fixture name)

    @staticmethod
    def answer(name):
        out = json.loads(json.dumps(FIX[name]))
        if "error" in out:
            err = out["error"]
            raise pub.GraphError(f"Graph {err.get('code')}: {err.get('message')}", code=err.get("code"),
                                 subcode=err.get("error_subcode"))
        return out

    def metrics(self, i):
        return [m for m in str(self.calls[i][2].get("metric") or "").split(",") if m]

    def asked(self):
        return {m for i in range(len(self.calls)) for m in self.metrics(i)}

    def __call__(self, method, path, token, **params):
        self.calls.append((method, path, params))
        if self.fail and self.fail[0](path, params):
            return self.answer(self.fail[1])
        names = [m for m in str(params.get("metric") or "").split(",") if m]
        if self.refuse & set(names):
            return self.answer(self.refuse_with)
        obj, _, edge = path.partition("/")
        if edge == "insights" and obj.startswith("act_"):
            return self.answer("ads_ad_yesterday" if params.get("level") == "ad" else "ads_campaign_yesterday")
        if obj.startswith("act_"):
            return self.answer("act_currency")
        if edge == "insights" and obj == CREDS["ig_user_id"]:
            if params.get("breakdown") == "follow_type":
                return self.answer("ig_follows_day")
            if params.get("metric_type") == "time_series":
                return self.answer("ig_reach_series")
            rows = self.answer("ig_account_day")["data"]
            return {"data": [r for r in rows if r["name"] in names]}
        if edge == "insights" and obj == CREDS["page_id"]:
            rows = self.answer("fb_page_week" if params.get("period") == "week" else "fb_page_day")["data"]
            return {"data": [r for r in rows if r["name"] in names]}
        if edge == "insights" and "_" in obj:                       # a Facebook post id (page_post)
            return {"data": [r for r in self.answer("fb_post_insights")["data"] if r["name"] in names]}
        if edge == "insights":                                      # an Instagram media id
            return {"data": [r for r in self.answer("ig_reel_insights")["data"] if r["name"] in names]}
        if obj == CREDS["ig_user_id"]:
            return self.answer("ig_profile")
        if obj == CREDS["page_id"]:
            return self.answer("fb_followers")
        if "_" in obj and "shares" in str(params.get("fields")):
            return self.answer("fb_post_fields")
        raise AssertionError(f"unexpected Graph call {method} {path} {params}")


def use(fake):
    pub.graph = fake
    return fake


def brand(**kw):
    return dict({"id": "koffie", "name": "Grachten Koffie", "tz": "Europe/Amsterdam", "status": "active", "plan": "growth",
                 "approvals": "app", "currency": "EUR", "onboarding": {"started_at": "2026-10-02T09:12:00Z"}}, **kw)


# ============================================================================================
# the version and the names Otto asks for
# ============================================================================================

class VersionAndNamesTest(unittest.TestCase):
    def setUp(self):
        fresh({"brands": [brand()], "posts": []}, {"koffie": CREDS})

    def test_one_pinned_version(self):
        self.assertEqual(pub.GRAPH_VERSION, "v26.0")
        self.assertTrue(pub.GRAPH.endswith("/v26.0"))
        import otto_track
        self.assertTrue(otto_track.CAPI_GRAPH.endswith("/v26.0"))
        mcp = (PLATFORM.parent / "mcp" / "otto-social-mcp" / "server.py").read_text()
        self.assertIn('"v26.0"', mcp)
        self.assertNotIn("page_impressions,", mcp)

    def test_graph_error_carries_meta_code(self):
        fake = FakeGraph()
        with self.assertRaises(pub.GraphError) as cm:
            fake.answer("err_token_expired")
        self.assertEqual((cm.exception.code, cm.exception.subcode), (190, 463))
        self.assertEqual(om.code_of(pub.GraphError("Graph 100: (#100) x")), 100)   # an error built from text only (fakes)

    def test_no_retired_metric_is_ever_asked(self):
        fake = use(FakeGraph())
        b = ap.brand(ap.load(), "koffie")
        now = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
        quiet(ins.account_days, b, CREDS, 3, now)
        quiet(ins.pull_page, CREDS)
        quiet(ins.pull_baseline, ap.load(), b, CREDS, now)
        for fmt in ("post", "reel", "story", "carousel"):
            quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": fmt}, CREDS)
        quiet(ins.pull_post, {"remote_id": "1020000000001_99", "platform": "fb"}, CREDS)
        asked = fake.asked()
        retired = {m for m in asked if m in om.RETIRED or m.startswith(("page_impressions", "page_fans", "post_impressions"))}
        self.assertEqual(retired, set())
        for m in ("reach", "views", "accounts_engaged", "total_interactions", "profile_links_taps", "follows_and_unfollows",
                  "page_media_view", "page_total_media_view_unique", "page_follows", "page_daily_follows",
                  "page_post_engagements", "post_media_view", "post_total_media_view_unique", "post_clicks", "saved",
                  "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"):
            self.assertIn(m, asked)

    def test_instagram_account_request_shape(self):
        fake = use(FakeGraph())
        since, until = om.local_bounds(date(2026, 10, 1), AMS)
        quiet(ins.ig_window, CREDS, since, until)
        main, follows = fake.calls[0][2], fake.calls[1][2]
        self.assertEqual((main["period"], main["metric_type"], main["since"], main["until"]), ("day", "total_value", since, until))
        self.assertEqual(set(main["metric"].split(",")), set(om.IG_ACCOUNT))
        self.assertEqual((follows["metric"], follows["breakdown"]), ("follows_and_unfollows", "follow_type"))
        self.assertEqual(until - since, 86400)

    def test_media_metrics_follow_the_format(self):
        fake = use(FakeGraph())
        for fmt, want, never in (("story", "replies", "saved"), ("reel", "ig_reels_avg_watch_time", "profile_visits"),
                                 ("carousel", "saved", "follows"), ("post", "profile_visits", "replies")):
            fake.calls.clear()
            quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": fmt}, CREDS)
            self.assertIn(want, fake.metrics(0), fmt)
            self.assertNotIn(never, fake.metrics(0), fmt)

    def test_ads_ask_ads_manager_attribution_and_new_fields(self):
        fake = use(FakeGraph())
        quiet(otto_ads.meta_insights, CREDS, "yesterday")
        quiet(otto_ads.meta_insights, CREDS, "yesterday", level="ad")
        camp, ad = fake.calls[0][2], fake.calls[1][2]
        self.assertEqual(camp["use_unified_attribution_setting"], "true")
        for f in ("spend", "reach", "frequency", "cpm", "inline_link_clicks", "actions", "cost_per_action_type", "objective"):
            self.assertIn(f, camp["fields"].split(","))
        self.assertEqual(ad["level"], "ad")
        self.assertTrue({"ad_id", "ad_name", "adset_id", "campaign_id"} <= set(ad["fields"].split(",")))

    def test_ads_fall_back_to_core_fields_when_meta_refuses_one(self):
        fake = use(FakeGraph(fail=(lambda path, p: path.endswith("/insights") and "cost_per_action_type" in str(p.get("fields")),
                                   "err_fb_invalid_metric")))
        rows = quiet(otto_ads.meta_insights, CREDS, "yesterday")
        self.assertEqual(len(rows), 3)
        self.assertNotIn("use_unified_attribution_setting", fake.calls[-1][2])
        self.assertIn("core fields", quiet.out)

    def test_cron_runs_the_daily_pull(self):
        d = {"brands": [{"id": "x", "status": "active", "plan": "growth"}], "posts": [], "campaigns": []}
        t = otto_cron.tasks("insights-daily", d, date(2026, 10, 2), TMP)
        self.assertEqual(t[0].argv[2:], ["daily", "--brand", "x"])
        self.assertEqual(otto_cron.JOBS["insights-daily"].local, "07:05")
        self.assertEqual(otto_cron.PLAN_GATES["insights-daily"], "reports")


# ============================================================================================
# the invalid-metric fallback
# ============================================================================================

class FallbackTest(unittest.TestCase):
    def setUp(self):
        fresh({"brands": [brand()], "posts": []}, {"koffie": CREDS})

    def test_named_metric_is_dropped_logged_once_and_not_asked_again(self):
        # Instagram names the metric by listing the valid ones: "replies" is not among them in this answer
        fake = use(FakeGraph(refuse={"replies"}, refuse_with="err_ig_invalid_metric"))
        FIX_copy = FIX["err_ig_invalid_metric"]["error"]["message"]
        self.assertIn("replies", FIX_copy)                         # the recorded list includes replies …
        FIX["err_ig_invalid_metric"]["error"]["message"] = FIX_copy.replace(" replies,", "")   # … this account's does not
        try:
            since, until = om.local_bounds(date(2026, 10, 1), AMS)
            v = quiet(ins.ig_window, CREDS, since, until)
            first_log = quiet.out
            self.assertNotIn("replies", v)
            self.assertEqual((v["reach"], v["views"], v["link_taps"], v["follows"], v["unfollows"]), (1840, 5210, 7, 14, 3))
            self.assertEqual(first_log.count("Meta refused ig_user metric replies"), 1)
            fake.calls.clear()
            v2 = quiet(ins.ig_window, CREDS, since, until)
            self.assertEqual(v2, v)
            self.assertNotIn("replies", fake.metrics(0))           # remembered: not asked at all
            self.assertEqual(len(fake.calls), 2)                  # no retry storm
            self.assertNotIn("refused", quiet.out)                # logged once
            st = json.loads((TMP / ".graph-metrics.json").read_text())
            self.assertIn("ig_user:replies", st["v26.0"])
        finally:
            FIX["err_ig_invalid_metric"]["error"]["message"] = FIX_copy

    def test_unnamed_refusal_is_found_one_by_one(self):
        # Facebook only says "must be a valid insights metric": Otto asks one by one and keeps the rest
        fake = use(FakeGraph(refuse={"page_views_total"}))
        out = quiet(ins.fb_days, CREDS, date(2026, 9, 29), date(2026, 10, 2))
        self.assertEqual(out["2026-09-30"]["views"], 1250)
        self.assertNotIn("page_views", out["2026-09-30"])
        self.assertEqual(quiet.out.count("Meta refused fb_page:day metric page_views_total"), 1)
        self.assertTrue(om.refused("fb_page:day", "page_views_total"))
        self.assertFalse(om.refused("fb_page:week", "page_views_total"))       # per edge and period
        fake.calls.clear()
        quiet(ins.fb_days, CREDS, date(2026, 9, 29), date(2026, 10, 2))
        self.assertEqual(len(fake.calls), 1)

    def test_refusal_expires_after_30_days(self):
        use(FakeGraph(refuse={"page_views_total"}))
        quiet(ins.fb_days, CREDS, date(2026, 9, 29), date(2026, 10, 2))
        later = datetime.now(timezone.utc) + timedelta(days=31)
        self.assertFalse(om.refused("fb_page:day", "page_views_total", now=later))
        self.assertTrue(om.refused("fb_page:day", "page_views_total", now=later - timedelta(days=2)))

    def test_every_metric_refused_returns_nothing_without_raising(self):
        use(FakeGraph(refuse=set(om.FB_PAGE_WEEK)))
        page = quiet(ins.pull_page, CREDS)
        self.assertNotIn("page_reach_week", page)
        self.assertEqual(page["followers"], 812)                  # the rest of the pull goes on

    def test_story_replies_below_five_only_lose_that_metric_this_time(self):
        fake = use(FakeGraph(refuse={"replies"}, refuse_with="err_story_not_enough"))
        m = quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": "story"}, CREDS)
        self.assertEqual(m["reach"], 4100)
        self.assertNotIn("replies", m)
        self.assertFalse(om.refused("ig_media:story", "replies"))   # error 10 is not a retired metric
        fake.calls.clear()
        quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": "story"}, CREDS)
        self.assertIn("replies", fake.metrics(0))

    def test_small_account_without_the_follows_breakdown_keeps_its_totals(self):
        use(FakeGraph(fail=(lambda path, p: p.get("breakdown") == "follow_type", "err_bad_since")))
        since, until = om.local_bounds(date(2026, 10, 1), AMS)
        v = quiet(ins.ig_window, CREDS, since, until)
        self.assertEqual(v["reach"], 1840)
        self.assertNotIn("follows", v)
        use(FakeGraph(fail=(lambda path, p: p.get("breakdown") == "follow_type", "err_token_expired")))
        with self.assertRaises(pub.GraphError):                  # a dead token is still an error, not "no follows"
            quiet(ins.ig_window, CREDS, since, until)

    def test_errors_that_are_not_about_a_metric_are_raised(self):
        use(FakeGraph(fail=(lambda path, p: True, "err_token_expired")))
        with self.assertRaises(pub.GraphError):
            quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": "reel"}, CREDS)
        use(FakeGraph(fail=(lambda path, p: path.endswith("/insights"), "err_bad_since")))
        with self.assertRaises(pub.GraphError):
            quiet(ins.fb_days, CREDS, date(2026, 9, 29), date(2026, 10, 2))
        self.assertFalse((TMP / ".graph-metrics.json").exists())   # nothing remembered as retired

    def test_culprits_parsing(self):
        e = pub.GraphError("Graph 100: (#100) metric[0] must be one of the following values: reach, views", code=100)
        self.assertEqual(om.culprits(e, ["impressions", "reach"]), ["impressions"])
        e = pub.GraphError("Graph 100: (#100) metric[1] is invalid", code=100)
        self.assertEqual(om.culprits(e, ["reach", "plays"]), ["plays"])
        e = pub.GraphError("Graph 100: (#100) The value must be a valid insights metric", code=100)
        self.assertEqual(om.culprits(e, ["page_media_view", "page_follows"]), [])
        self.assertTrue(om.invalid_metric(e))
        self.assertFalse(om.invalid_metric(pub.GraphError("Graph 100: (#100) Invalid since", code=100)))
        self.assertFalse(om.invalid_metric(pub.GraphError("Graph 190: valid insights metric", code=190)))


# ============================================================================================
# Instagram account + Facebook Page: parsing and storing
# ============================================================================================

class AccountNumbersTest(unittest.TestCase):
    NOW = datetime(2026, 10, 2, 5, 5, tzinfo=timezone.utc)          # 07:05 in Amsterdam

    def setUp(self):
        fresh({"brands": [brand()], "posts": [],
               "metrics": {"koffie": {"reach": 3100, "saves": 40, "clicks": 12, "leads": 0, "followers": 790,
                                      "page_reach_week": 3000}}},
              {"koffie": CREDS})
        use(FakeGraph())

    def test_account_days_parse(self):
        got = quiet(ins.account_days, ap.brand(ap.load(), "koffie"), CREDS, 3, self.NOW)
        self.assertEqual(sorted(got["daily"]), ["2026-09-29", "2026-09-30", "2026-10-01"])
        ig = got["daily"]["2026-10-01"]["ig"]
        self.assertEqual(ig, {"reach": 1840, "views": 5210, "engaged": 96, "interactions": 212, "likes": 160, "comments": 21,
                              "shares": 9, "saves": 18, "replies": 4, "link_taps": 7, "follows": 14, "unfollows": 3})
        fb = got["daily"]["2026-10-01"]["fb"]                       # end_time 2026-10-02T07:00 = 1 October
        self.assertEqual(fb, {"views": 1300, "viewers": 720, "engagements": 61, "followers": 812, "follows": 3, "unfollows": 1})
        self.assertEqual(got["daily"]["2026-09-29"]["fb"]["views"], 1100)
        self.assertNotIn("2026-10-02", got["daily"])                 # today is not complete: never stored
        self.assertNotIn("2026-09-27", got["daily"])                 # the extra day Meta was asked for is cut off
        self.assertEqual(got["account"], {"ig": {"followers": 2310, "media": 148}, "fb": {"followers": 812}})
        self.assertEqual(got["errors"], [])

    def test_daily_job_stores_backward_compatible(self):
        quiet(ins.daily, "koffie", now=self.NOW)
        m = ap.load()["metrics"]["koffie"]
        for k, v in (("reach", 3100), ("saves", 40), ("clicks", 12), ("leads", 0), ("page_reach_week", 3000)):
            self.assertEqual(m[k], v)                                 # the weekly keys are untouched
        self.assertEqual(m["followers"], 812)                        # Facebook Page followers, as before (now daily)
        self.assertEqual(m["account"]["ig"]["followers"], 2310)
        self.assertEqual(len(m["daily"]), 3)
        self.assertIn("baseline", m)
        # the snapshot line (drop alerts, growth) keeps flat numbers + account, not the series
        import otto_watch
        line = otto_watch.snapshot_metrics(ap.load()["metrics"])["koffie"]
        self.assertNotIn("daily", line)
        self.assertNotIn("baseline", line)
        self.assertEqual(line["followers"], 812)
        self.assertEqual(otto_watch.drops([{"date": "x", "metrics": {"koffie": m}}] * 5), [])   # nested dicts never compared

    def test_a_failed_network_keeps_the_days_earlier_numbers(self):
        quiet(ins.daily, "koffie", now=self.NOW)
        use(FakeGraph(fail=(lambda path, p: path.startswith(CREDS["page_id"]), "err_token_expired")))
        quiet(ins.daily, "koffie", now=self.NOW)
        m = ap.load()["metrics"]["koffie"]
        self.assertEqual(m["daily"]["2026-10-01"]["fb"]["views"], 1300)
        self.assertEqual(m["account"]["fb"]["followers"], 812)
        self.assertTrue(any("facebook" in e for e in m["account"]["errors"]))

    def test_weekly_run_keeps_the_series_and_reads_page_reach_from_the_new_metric(self):
        quiet(ins.daily, "koffie", now=self.NOW)
        quiet(ins.run, False, "koffie")
        m = ap.load()["metrics"]["koffie"]
        self.assertEqual(m["page_reach_week"], 4200)                  # page_total_media_view_unique, period=week
        self.assertEqual(len(m["daily"]), 3)
        self.assertIn("baseline", m)
        self.assertEqual(m["followers"], 812)

    def test_post_numbers(self):
        fb = quiet(ins.pull_post, {"remote_id": "1020000000001_99", "platform": "fb"}, CREDS)
        self.assertEqual(fb, {"reach": 640, "views": 910, "clicks": 23, "shares": 4, "comments": 6, "likes": 51})
        reel = quiet(ins.pull_post, {"remote_id": "17900000000000001", "platform": "ig", "format": "reel"}, CREDS)
        self.assertEqual((reel["reach"], reel["saves"], reel["interactions"], reel["avg_watch_ms"]), (4100, 88, 366, 6420))
        self.assertNotIn("saved", reel)

    def test_stories_are_pulled_before_they_expire(self):
        now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        posts = [{"id": f"ko-00{i}", "brand": "koffie", "platform": "ig", "format": "story", "status": "published",
                  "remote_id": f"1790000000000000{i}", "published_at": (now - timedelta(hours=h)).isoformat()}
                 for i, h in ((1, 21), (2, 25), (3, 3))]
        d = ap.load()
        d["posts"] = posts
        ap.save(d)
        quiet(ins.stories, "koffie", now=now)                        # the publisher's tick: only the 20-24 h one
        got = {p["id"]: p.get("metrics") for p in ap.load()["posts"]}
        self.assertTrue(got["ko-001"]["final"])
        self.assertIsNone(got["ko-002"])                             # expired at Meta: never asked
        self.assertIsNone(got["ko-003"])                             # still young: the daily pull takes it
        quiet(ins.daily, "koffie", now=now)
        got = {p["id"]: p.get("metrics") for p in ap.load()["posts"]}
        self.assertEqual(got["ko-003"]["reach"], 4100)
        self.assertNotIn("final", got["ko-003"])

    def test_publisher_tick_runs_the_story_sweep_but_not_when_dry(self):
        calls = []
        saved = ins.stories
        ins.stories = lambda bid=None, now=None: calls.append(bid)
        try:
            quiet(pub.run, True, "koffie")
            self.assertEqual(calls, [])
            quiet(pub.run, False, "koffie")
            self.assertEqual(calls, ["koffie"])
        finally:
            ins.stories = saved


# ============================================================================================
# the baseline: the 30 days before Otto
# ============================================================================================

class BaselineTest(unittest.TestCase):
    def test_window_math(self):
        today = date(2026, 10, 2)
        self.assertEqual(ins.baseline_window(date(2026, 10, 2), today), (date(2026, 9, 2), date(2026, 10, 2)))
        since, until = ins.baseline_window(date(2026, 3, 1), today)
        self.assertEqual(((until - since).days, since), (30, date(2026, 1, 30)))
        self.assertEqual(ins.baseline_window(date(2026, 12, 1), today), (date(2026, 9, 2), date(2026, 10, 2)))   # future → today
        since, until = ins.baseline_window(date(2024, 10, 20), today)     # partly beyond Meta's 2 years: clipped
        self.assertEqual((since, until), (date(2024, 10, 3), date(2024, 10, 20)))
        self.assertIsNone(ins.baseline_window(date(2024, 9, 1), today))   # entirely beyond: nothing to pull
        self.assertLessEqual((until - since).days, 90)                     # inside Meta's 90 days per Page query

    def test_local_bounds_follow_the_brand_clock(self):
        s, u = om.local_bounds(date(2026, 10, 25), AMS)                    # summer time ends: a 25-hour day
        self.assertEqual(u - s, 25 * 3600)
        self.assertEqual(datetime.fromtimestamp(s, AMS).hour, 0)

    def test_joined_date(self):
        b = brand(onboarding={"started_at": "2026-09-20T23:30:00Z"}, trial={"started_at": "2026-09-22T10:00:00Z"},
                  plan_history=[{"at": "2026-09-25T10:00:00Z"}])
        d = {"posts": [{"brand": "koffie", "created_at": "2026-09-21T08:00:00Z"}]}
        self.assertEqual(ins.joined_date(d, b, date(2026, 10, 2)), date(2026, 9, 21))   # 23:30Z = 01:30 Amsterdam
        self.assertEqual(ins.joined_date(d, dict(b, otto_since="2026-08-01"), date(2026, 10, 2)), date(2026, 8, 1))
        self.assertEqual(ins.joined_date({}, {"id": "x"}, date(2026, 10, 2)), date(2026, 10, 2))

    def test_pull_and_refresh_rules(self):
        fresh({"brands": [brand()], "posts": []}, {"koffie": CREDS})
        fake = use(FakeGraph())
        now = datetime(2026, 10, 2, 5, 5, tzinfo=timezone.utc)
        base = quiet(ins.pull_baseline, ap.load(), ap.brand(ap.load(), "koffie"), CREDS, now)
        self.assertEqual((base["joined"], base["since"], base["until"], base["days"]), ("2026-10-02", "2026-09-02", "2026-10-02", 30))
        self.assertFalse(base["final"])                                       # yesterday is still inside Meta's 48 h lag
        ig_main = next(c[2] for c in fake.calls if c[2].get("metric_type") == "total_value" and "reach" in c[2]["metric"])
        self.assertEqual(ig_main["until"] - ig_main["since"], 30 * 86400)     # one 30-day total_value request
        self.assertEqual(ig_main["until"], int(datetime(2026, 10, 2, tzinfo=AMS).timestamp()))
        fb = next(c[2] for c in fake.calls if c[1].startswith(CREDS["page_id"]))
        self.assertEqual((fb["since"], fb["until"]), ("2026-09-01", "2026-10-03"))   # a day wider, cut to the window
        self.assertEqual(base["ig"]["reach"], 1840)
        self.assertEqual(base["daily"]["2026-09-02"]["ig"]["reach"], 1500)
        self.assertNotIn("2026-10-02", base["daily"])                         # the join day is "after"
        self.assertEqual(base["fb"]["followers"], 812)                        # a level: the last day, not a sum
        self.assertEqual(base["fb"]["views"], 900 + 1100 + 1250 + 1300)
        self.assertEqual(base["errors"], [])
        self.assertFalse(ins.needs_baseline(base, now + timedelta(hours=30)))
        self.assertTrue(ins.needs_baseline(base, now + timedelta(days=3)))     # re-pulled once Meta's numbers settled
        self.assertFalse(ins.needs_baseline(dict(base, final=True), now + timedelta(days=30)))
        empty = dict(base, ig={}, fb={})
        self.assertFalse(ins.needs_baseline(empty, now + timedelta(hours=2)))
        self.assertTrue(ins.needs_baseline(empty, datetime.now(timezone.utc) + timedelta(days=1)))
        self.assertTrue(ins.needs_baseline(None))

    def test_baseline_cli_and_daily_take_it_once(self):
        fresh({"brands": [brand(onboarding={"started_at": "2026-08-01T09:00:00Z"})], "posts": []}, {"koffie": CREDS})
        fake = use(FakeGraph())
        quiet(ins.daily, "koffie", now=datetime(2026, 10, 2, 5, 5, tzinfo=timezone.utc))
        base = ap.load()["metrics"]["koffie"]["baseline"]
        self.assertEqual((base["since"], base["until"], base["final"]), ("2026-07-02", "2026-08-01", True))
        n = len(fake.calls)
        quiet(ins.daily, "koffie", now=datetime(2026, 10, 3, 5, 5, tzinfo=timezone.utc))
        self.assertFalse(any(c[2].get("metric_type") == "time_series" for c in fake.calls[n:]))   # final: not pulled again
        quiet(ins.baseline, "koffie", force=True)
        self.assertIn("baseline 2026-07-02…2026-08-01", quiet.out)


# ============================================================================================
# paid: lead counting, cost per lead, conversations; the report and the console agree
# ============================================================================================

class PaidNumbersTest(unittest.TestCase):
    def rows(self, level="campaign"):
        fx = FIX["ads_ad_yesterday" if level == "ad" else "ads_campaign_yesterday"]["data"]
        return [om.paid_row(x, level) for x in fx]

    def test_lead_is_the_total_never_a_sum(self):
        lead, sales, boost = self.rows()
        self.assertEqual((lead["results"], lead["leads"], lead["leads_form"], lead["leads_website"]), (9, 9, 7, 2))
        self.assertEqual(lead["cost_per_lead"], round(42.10 / 9, 2))
        self.assertEqual((sales["results"], sales["result_type"], sales["leads"]), (2, "purchases", 1))
        self.assertEqual((boost["results"], boost["messages"], boost["cost_per_message"]), (340, 5, 1.6))
        self.assertEqual((boost["result_type"], boost["conversion"], boost["cpl"]), ("engagements", False, None))
        self.assertEqual((lead["frequency"], lead["cpm"]), (1.31, 8.22))
        a1, a2, chat, idle = self.rows("ad")
        self.assertEqual((a1["leads"], a1["id"], a1["campaign_id"], a1["adset_id"]), (6, "120210000101", "120210000001", "120210000011"))
        self.assertEqual(a2["leads"], 2)                     # no `lead`: the first part only — 2 + 1 are never added
        self.assertEqual(chat["messages"], 5)
        self.assertEqual(idle["spend"], 0)

    def test_totals_keep_each_kind_apart(self):
        t = om.paid_totals(self.rows())
        self.assertEqual(t["results_by_type"], {"leads": 9, "purchases": 2, "engagements": 340})
        self.assertEqual(t["leads"], 9)                       # the sales campaign's pixel lead is not an enquiry result
        self.assertEqual(t["cost_by_type"], {"leads": round(42.10 / 9, 2), "purchases": 15.0})
        self.assertEqual(t["cost_per_lead"], round(42.10 / 9, 2))
        self.assertEqual(t["messages"], 5)
        self.assertEqual(t["cpl"], round(72.10 / 11, 2))      # the old mixed figure stays for old readers only
        self.assertEqual((t["leads_form"], t["leads_website"]), (7, 2))

    def test_report_and_console_show_the_same_numbers(self):
        fresh({"brands": [brand(plan="growth", approvals="email", members=["eva@koffie.example"])], "posts": [],
               "campaigns": [{"id": "cp-001", "brand": "koffie", "status": "live", "network": "meta", "name": "Lead form · kitchens",
                              "daily_budget": 45, "start": "2026-09-01", "end": "2026-12-31", "remote": {"campaign_id": "120210000001"}}]},
              {"koffie": CREDS})
        use(FakeGraph())
        quiet(otto_ads.report, "koffie", send=False)
        d = ap.load()
        entry = d["ads"]["koffie"]["daily"][otto_ads.today()]
        self.assertEqual(entry["meta"]["attribution"], "7d_click,1d_view")
        self.assertEqual([r["id"] for r in entry["meta"]["ads"]], ["120210000101", "120210000102", "120210000301"])   # idle ad dropped
        b = ap.brand(d, "koffie")
        p = otto_report.model(d, b, datetime.now(timezone.utc))["paid"]
        self.assertEqual(p["state"], "ok")
        console = otto_admin._paid_numbers(d, "koffie", otto_ads.today()[:7])["yesterday"]
        self.assertEqual(p["spend"], console["spend"])
        self.assertEqual(p["spend"], 80.10)
        self.assertEqual((p["by"]["leads"], console["leads"]), (9, 9))
        self.assertEqual((p["kind"], p["cost"], console["cost_per_lead"]), ("leads", 4.68, 4.68))   # 42.10 / 9, not 72.10 / 11
        self.assertEqual((p["by"]["purchases"], console["purchases"], console["cost_per_purchase"]), (2, 2, 15.0))
        self.assertEqual((p["messages"], console["messages"]), (5, 5))
        self.assertEqual(p["link_clicks"], console["link_clicks"])
        t = otto_report.i18n.Tr.for_brand(b)
        lines = otto_report.paid_lines(t, p)
        self.assertTrue(any("5 people started a chat" in x for x in lines), lines)
        self.assertTrue(any("4.68" in x for x in lines), lines)
        month = otto_admin._paid_numbers(d, "koffie", otto_ads.today()[:7])["month"]
        if month:                                             # the entry's data day may sit in the previous month
            self.assertEqual(month["cost_per_lead"], 4.68)

    def test_old_entries_without_the_new_fields_still_add_up(self):
        old = {"meta": {"yesterday": {"spend": 30.0, "results": 3, "results_by_type": {"leads": 3}, "link_clicks": 40},
                        "campaigns": [{"id": "1", "objective": "OUTCOME_LEADS", "conversion": True, "spend": 18.0, "results": 2},
                                      {"id": "2", "objective": "OUTCOME_LEADS", "conversion": True, "spend": 12.0, "results": 1}]},
               "google": {"yesterday": {"spend": 10.0, "results": 2, "clicks": 25}}}
        x = om.paid_day(old)
        self.assertEqual((x["spend"], x["by"], x["cost"]), (40.0, {"leads": 3, "conversions": 2}, {"leads": 10.0, "conversions": 5.0}))
        self.assertEqual((x["messages"], x["link_clicks"], x["networks"]), (0, 65, ["meta", "google"]))
        self.assertEqual(om.paid_period([old, old])["cost"], {"leads": 10.0, "conversions": 5.0})

    def test_per_ad_rows_are_kept_14_days(self):
        fresh({"brands": [brand()], "posts": [], "ads": {"koffie": {"daily": {
            (date(2026, 9, 1) + timedelta(days=i)).isoformat(): {"meta": {"yesterday": {"spend": 1}, "ads": [{"id": "a"}]}}
            for i in range(20)}}}}, {"koffie": CREDS})
        use(FakeGraph())
        quiet(otto_ads.report, "koffie", send=False)
        daily = ap.load()["ads"]["koffie"]["daily"]
        with_ads = [k for k, v in daily.items() if (v.get("meta") or {}).get("ads")]
        self.assertEqual(len(with_ads), 14)
        self.assertEqual(len(daily), 21)


if __name__ == "__main__":
    unittest.main()
