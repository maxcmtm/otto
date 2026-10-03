#!/usr/bin/env python3
"""The client dashboard's data (otto_dashboard → GET /otto-api/data brands[].today / ledger / results / ad_review), the
client's post copy (posts[].copy reaches a client as {state} only), the Connect sheet's request (connect_help) and the 18:30
reels job (an unwritten reel is never rendered).

Checked: Today's line is the 07:35 report's own sentence (otto_report.summary_parts) and its numbers; this month's work
(made / out / planned per format, the ads the plan runs, the budget, the connect checklist); Results for 7 / 30 / 90 days —
sums, the previous period only when it is fully covered, never a number without a source (not_connected / pending / none /
trial), best posts and ads, ad sets, the template sentences; the month's ads for Review (copy, rendered media only, the plan
card); and the tenant rule: a client's answer carries these for its own brands only, and never a model, attempts, a held /
error reason, a compliance rule list, a cost of Otto's own or a strategist note.
Stdlib unittest, a throwaway workspace, no network beyond 127.0.0.1.

  cd platform && python3 tests/test_dashboard.py
"""
import http.server, json, os, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-dashboard-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_COPY_LEDGER": str(TMP / "copy-usage.json"), "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"),
       "OTTO_LOCKS": str(TMP / "locks"), "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_SESSIONS": str(TMP / "sessions.json"), "OTTO_REPORT_STATE": str(TMP / ".report-state.json")}
CLEAR = ("ANTHROPIC_API_KEY", "OTTO_COPY", "OTTO_COPY_QUEUE", "OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY",
         "OTTO_TZ", "OTTO_PLANS", "OTTO_CRON_NOW")
NOW = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)          # 12:00 in Amsterdam; yesterday = 1 Oct
YDAY = date(2026, 10, 1)
OTHER_MARK = "ZZOTHERBRANDZZ"
_SAVED = {}


def iso(d, h=9):
    return f"{d.isoformat()}T{h:02d}:00"


def brand(bid, **kw):
    b = {"id": bid, "name": bid.title(), "url": f"{bid}.example", "lang": "EN", "tz": "Europe/Amsterdam", "status": "active",
         "plan": "starter", "countries": ["NL"], "currency": "EUR", "members": [f"owner@{bid}.example"], "pillars": ["Craft"],
         "copy_auto": False, "approvals": "email"}
    b.update(kw)
    return b


SECRET_COPY = {"by": "otto_copy", "model": "claude-opus-5-5", "at": "2026-10-01T05:00:00Z", "attempts": 3, "state": "held",
               "job": "daily", "held_for": ["health claim"], "error": "api", "render": "pending"}


def seed():
    posts = []
    # bake: published posts 1 Sep → 1 Oct (one a day; numbers on all but yesterday's), October's plan, a held draft
    for i in range(31):
        day = date(2026, 9, 1) + timedelta(days=i)
        m = {"reach": 100 + i, "likes": 10, "comments": 2, "shares": 1, "saves": 3} if day < YDAY else None
        posts.append({"id": f"bk-{i:03d}", "brand": "bake", "platform": "ig", "format": "post", "status": "published",
                      "slot": iso(day), "published_at": f"{day.isoformat()}T07:00:00Z", "hook": f"Loaf {i}", "caption": "c",
                      "image": f"assets/posts/bk-{i:03d}.jpg", "metrics": m})
    posts[-2]["metrics"] = {"reach": 900, "likes": 10, "comments": 2, "shares": 1, "saves": 40}     # 30 Sep: the best post
    posts += [{"id": "bk-s1", "brand": "bake", "platform": "ig", "format": "story", "status": "published", "slot": iso(YDAY, 12),
               "published_at": "2026-10-01T10:00:00Z", "hook": "Story", "image": "assets/posts/s1.jpg"},
              {"id": "bk-p1", "brand": "bake", "platform": "fb", "format": "carousel", "status": "pending_approval",
               "slot": iso(date(2026, 10, 3)), "hook": "Weekend loaves", "caption": "c", "image": "assets/posts/p1.jpg",
               "copy": dict(SECRET_COPY, state="written"), "compliance_block": {"rules": ["guarantee claim"], "at": "x"}},
              {"id": "bk-r1", "brand": "bake", "platform": "ig", "format": "reel", "status": "pending_approval",
               "slot": iso(date(2026, 10, 4)), "hook": "Oven reel", "caption": "c", "image": "assets/posts/r1.jpg"},
              {"id": "bk-r2", "brand": "bake", "platform": "ig", "format": "reel", "status": "draft", "slot": iso(date(2026, 10, 20))},
              {"id": "bk-d1", "brand": "bake", "platform": "ig", "format": "post", "status": "draft", "slot": iso(date(2026, 10, 9)),
               "hook": "Held one", "caption": "c", "copy": SECRET_COPY},
              {"id": "bk-x1", "brand": "bake", "platform": "ig", "format": "post", "status": "skipped", "slot": iso(date(2026, 10, 10))},
              {"id": "ot-1", "brand": "other", "platform": "ig", "format": "post", "status": "published", "slot": iso(YDAY),
               "published_at": "2026-10-01T07:00:00Z", "hook": OTHER_MARK + " post", "metrics": {"reach": 7777}}]
    daily = {}
    for k in range(10):                                   # ads reports for 22 Sep → 1 Oct (filed the day after)
        data_day = YDAY - timedelta(days=k)
        ad_rows = [{"id": "ad-1", "ad_id": "ad-1", "ad_name": "x · c1", "adset_id": "set-1", "adset_name": "x · Fresh",
                    "campaign_id": "rc-1", "objective": "OUTCOME_LEADS", "result_type": "leads", "conversion": True,
                    "spend": 6.0, "results": 1 if k % 2 == 0 else 0, "link_clicks": 4, "clicks": 5, "impressions": 500},
                   {"id": "ad-2", "ad_id": "ad-2", "ad_name": "x · c2", "adset_id": "set-2", "adset_name": "x · Offer",
                    "campaign_id": "rc-1", "objective": "OUTCOME_LEADS", "result_type": "leads", "conversion": True,
                    "spend": 4.0, "results": 0, "link_clicks": 2, "clicks": 3, "impressions": 300}]
        res = sum(r["results"] for r in ad_rows)
        y = {"spend": 10.0, "results": res, "results_by_type": {"leads": res} if res else {}, "clicks": 8, "link_clicks": 6,
             "impressions": 800, "cpl": 10.0 if res else None, "cost_by_type": {"leads": 10.0} if res else {}, "leads": res}
        daily[(data_day + timedelta(days=1)).isoformat()] = {"meta": {
            "yesterday": y, "week": y, "currency": "EUR", "ads": ad_rows,
            "campaigns": [{"id": "rc-1", "name": "x", "objective": "OUTCOME_LEADS", "result_type": "leads", "conversion": True,
                           "spend": 10.0, "results": res, "link_clicks": 6, "clicks": 8, "impressions": 800}]}}
    camp = {"id": "cp-001", "brand": "bake", "network": "meta", "name": "Bake · October", "objective": "leads", "plan": "2026-10",
            "start": "2026-09-20", "end": "2026-10-31", "daily_budget": 10, "status": "live", "currency_code": "EUR",
            "remote": {"campaign_id": "rc-1", "concepts": {"a1": {"adset_id": "set-1", "active": True, "ads": {"c1": {"ad_id": "ad-1"}}},
                                                          "a2": {"adset_id": "set-2", "active": True, "ads": {"c2": {"ad_id": "ad-2"}}}}},
            "creatives": {"concepts": [
                {"angle": "a1", "name": "Fresh", "ads": [{"id": "c1", "style": "notes_app", "format": "image", "headline": "Fresh at 7",
                                                         "files": [{"file": "assets/ads/c1-feed.jpg", "size": "feed"}]}]},
                {"angle": "a2", "name": "Offer", "ads": [{"id": "c2", "style": "offer", "format": "image", "headline": "Weekend",
                                                         "files": [{"file": "assets/ads/c2-feed.jpg", "size": "feed", "planned": True}]}]}]}}
    nov = [{"id": f"cp-n{k}", "brand": "bake", "network": "meta", "name": f"Bake · November {k}", "objective": "leads",
            "plan": "2026-11", "start": f"2026-11-{1 + 10 * k:02d}", "end": f"2026-11-{10 + 10 * k:02d}", "daily_budget": 10,
            "status": "draft"} for k in range(3)]
    other_camp = {"id": "cp-900", "brand": "other", "network": "meta", "name": OTHER_MARK + " campaign", "plan": "2026-10",
                  "start": "2026-10-01", "end": "2026-10-31", "daily_budget": 99, "status": "live",
                  "remote": {"campaign_id": "rc-9", "concepts": {"z": {"adset_id": "set-9", "active": True, "ads": {"z1": {"ad_id": "ad-9"}}}}}}
    acct = {(YDAY - timedelta(days=k)).isoformat(): {"ig": {"follows": 5, "unfollows": 1, "link_taps": 3}, "fb": {"follows": 1}}
            for k in range(7)}
    return {"generated": "2026-10-02T06:00:00Z",
            "brands": [brand("bake", otto_since="2026-09-01"), brand("other", name=OTHER_MARK, plan="content"),
                       brand("trial", plan="trial", trial={"user": "u1", "started_at": "2026-10-01T10:00:00Z",
                                                          "ends_at": "2099-01-01T00:00:00Z"})],
            "posts": posts, "campaigns": [camp, other_camp] + nov,
            "recommendations": [{"id": "rec-001", "priority": "P1", "title": "Approve the 2026-11 paid plan: 3 campaigns, ≈€300",
                                 "why": "w", "impact": "", "cta": "Approve plan", "status": "proposed", "brand": "bake",
                                 "source": "otto_ads", "action": "approve_plan", "plan": "2026-11"},
                                {"id": "rec-002", "priority": "P0", "title": OTHER_MARK + " card", "why": "w", "impact": "",
                                 "cta": "x", "status": "proposed", "brand": "other", "source": "otto_insights"}],
            "connections": [{"id": "meta-bake", "service": "Instagram + Facebook", "brand": "Bake", "status": "connected"},
                            {"id": "meta-other", "service": "Instagram + Facebook", "brand": OTHER_MARK, "status": "connected"}],
            "ads": {"bake": {"connections": {"meta": True}, "daily": daily},
                    "other": {"connections": {"meta": True}, "daily": {"2026-10-02": {"meta": {"yesterday": {"spend": 999.0},
                                                                                              "campaigns": [{"id": "rc-9", "name": OTHER_MARK}]}}}}},
            "metrics": {"bake": {"daily": acct}, "other": {"daily": {YDAY.isoformat(): {"ig": {"follows": 999}}}}}}


MATRIX = {"brand": "bake", "month": "2026-11", "preset": "micro", "angles": [
    {"id": "a1", "name": "Fresh", "family": "pain", "angle": "STRATEGIST NOTE never shown", "persona": "p-secret",
     "source": "profile", "headlines": ["Fresh at 7", "Baked this morning"], "primaries": ["P one", "P two"],
     "description": "Bakery", "cta": "SIGN_UP",
     "ads": [{"id": "n-c1", "style": "notes_app", "format": "video", "brief": "BRIEF never shown"},
             {"id": "n-c2", "style": "text_message", "format": "image", "brief": "BRIEF never shown"},
             {"id": "n-c3", "style": "ugc_talking_head", "format": "creator", "brief": "BRIEF never shown"},
             {"id": "n-c4", "style": "quote", "format": "image", "status": "dropped"}]},
    {"id": "a2", "name": "Offer", "family": "offer", "headlines": ["Weekend"], "primaries": ["Order by Friday"], "cta": "ORDER_NOW",
     "ads": [{"id": "n-c5", "style": "offer", "format": "image", "headline": "Own headline"}]}]}


def save(d):
    (TMP / "data.json").write_text(json.dumps(d, indent=1))


def data():
    return json.loads((TMP / "data.json").read_text())


def view(bids, now=NOW):
    d = data()
    v = otto_api.client_view(d, bids) if bids is not None else json.loads(json.dumps(d))
    otto_dashboard.with_dashboard(v, full=d, now=now)
    return v, {b["id"]: b for b in v["brands"]}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    for f in ("brands/bake", "brands/other", "secrets", "assets", "locks"):
        (TMP / f).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_api, otto_dashboard, otto_report, otto_video
    import ap, otto_api, otto_dashboard, otto_report, otto_video          # noqa: E401
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
        (TMP / "brands" / "bake" / "ads-2026-11.json").write_text(json.dumps(MATRIX))
        (TMP / "brands" / "bake" / "scan.json").write_text("{}")
        (TMP / "brands" / "other" / "ads-2026-10.json").write_text(json.dumps(dict(MATRIX, brand="other", angles=[
            dict(MATRIX["angles"][1], name=OTHER_MARK)])))


INTERNAL = ("claude-", '"attempts"', "held_for", "compliance_block", "guarantee claim", "health claim", '"model"', '"job"',
            "usd", "input_tokens", "STRATEGIST NOTE", "BRIEF never", "p-secret", '"brief"', '"persona"')


class ClientCopyTest(_Reset, unittest.TestCase):
    def test_post_copy_reaches_a_client_as_its_state_only(self):
        v, _ = view({"bake"})
        p = {x["id"]: x for x in v["posts"]}
        self.assertEqual(p["bk-d1"]["copy"], {"state": "held"})
        self.assertEqual(p["bk-p1"]["copy"], {"state": "written"})
        self.assertNotIn("compliance_block", p["bk-p1"])
        self.assertNotIn("copy", p["bk-000"], "a post without copy meta gets none")
        blob = json.dumps(v)
        for s in INTERNAL:
            self.assertNotIn(s, blob, s)

    def test_the_owner_keeps_the_ledger(self):
        d = data()
        self.assertEqual(otto_api.owner_view(d)["posts"][[x["id"] for x in d["posts"]].index("bk-d1")]["copy"]["model"],
                         "claude-opus-5-5")
        self.assertEqual(SECRET_COPY["model"], data()["posts"][[x["id"] for x in d["posts"]].index("bk-d1")]["copy"]["model"],
                         "the stored post is never changed")

    def test_an_odd_copy_value_is_emptied(self):
        d = data()
        d["posts"][0]["copy"] = "garbage"
        d["posts"][1]["copy"] = {"state": "something new", "model": "x"}
        save(d)
        v, _ = view({"bake"})
        self.assertEqual(v["posts"][0]["copy"], {})
        self.assertEqual(v["posts"][1]["copy"], {})


class TodayTest(_Reset, unittest.TestCase):
    def test_the_line_is_the_reports_own_sentence_and_numbers(self):
        _, B = view({"bake"})
        t = B["bake"]["today"]
        d = data()
        m = otto_report.model(d, dict(ap.brand(d, "bake"), comms_lang="en"), NOW)
        self.assertEqual(t["line"], otto_report.summary_parts(m)["yesterday"])
        self.assertEqual(t["day"], "2026-10-01")
        self.assertEqual(t["paid"]["state"], "ok")
        self.assertEqual(t["paid"]["spend"], m["paid"]["spend"])
        self.assertEqual(t["paid"]["results"], 1.0)
        self.assertIn("1 enquiry", t["line"])
        self.assertEqual(t["yesterday"]["posts"], 2, "yesterday's post and story went out")
        self.assertIsNone(t["yesterday"]["reach"], "no numbers yet: not a zero")

    def test_the_email_in_dutch_counts_the_same(self):
        d = data()
        ap.brand(d, "bake")["comms_lang"] = "nl"
        save(d)
        _, B = view({"bake"})
        m = otto_report.model(d, ap.brand(d, "bake"), NOW)
        self.assertEqual(B["bake"]["today"]["paid"]["spend"], m["paid"]["spend"])
        self.assertTrue(B["bake"]["today"]["line"].startswith("Yesterday"), "the app stays English")
        self.assertTrue(otto_report.summary(m).startswith("Goedemorgen"))

    def test_summary_is_unchanged_by_the_split(self):
        d = data()
        m = otto_report.model(d, ap.brand(d, "bake"), NOW)
        s = otto_report.summary_parts(m)
        self.assertEqual(otto_report.summary(m), " ".join([s["greeting"], s["yesterday"], s["waiting"]]))


class LedgerTest(_Reset, unittest.TestCase):
    def test_this_months_work(self):
        _, B = view({"bake"})
        L = B["bake"]["ledger"]
        self.assertEqual(L["month"], "2026-10")
        self.assertEqual(L["posts"], {"planned": 3, "made": 2, "out": 1}, "bk-030 out; bk-p1 made; the held draft has no image")
        self.assertEqual(L["stories"], {"planned": 1, "made": 1, "out": 1})
        self.assertEqual(L["reels"], {"planned": 2, "made": 0, "out": 0}, "a reel is made once its video exists")
        self.assertEqual(L["ads"]["live"], 2)
        self.assertEqual(L["budget"]["planned"], 310.0)
        self.assertEqual(L["budget"]["spent"], 10.0, "1 Oct's report: €10")
        ids = {c["id"]: c for c in L["connect"]}
        self.assertEqual(list(ids), ["site", "meta", "ad_account", "approvals"])
        self.assertTrue(ids["meta"]["done"] and ids["ad_account"]["done"] and ids["approvals"]["done"] and ids["site"]["done"])

    def test_a_plan_without_ads_has_no_ad_lines(self):
        _, B = view({"other"})
        L = B["other"]["ledger"]
        self.assertIsNone(L["ads"])
        self.assertIsNone(L["budget"])
        self.assertNotIn("ad_account", [c["id"] for c in L["connect"]])
        self.assertIsNone(B["other"]["ad_review"])

    def test_not_connected_and_telegram_not_paired(self):
        d = data()
        d["connections"] = []
        d["ads"]["bake"]["connections"] = {}
        ap.brand(d, "bake")["approvals"] = "telegram"
        save(d)
        _, B = view({"bake"})
        ids = {c["id"]: c for c in B["bake"]["ledger"]["connect"]}
        self.assertFalse(ids["meta"]["done"])
        self.assertEqual(ids["meta"]["state"], "not_connected")
        self.assertFalse(ids["ad_account"]["done"])
        self.assertFalse(ids["approvals"]["done"])


class ResultsTest(_Reset, unittest.TestCase):
    def test_seven_days_against_the_seven_before(self):
        _, B = view({"bake"})
        r = B["bake"]["results"]
        self.assertEqual(r["state"], "ok")
        self.assertEqual(r["started"], "2026-09-01")
        p = r["periods"]["7"]
        self.assertEqual((p["from"], p["to"], p["prev_from"], p["prev_to"]), ("2026-09-25", "2026-10-01", "2026-09-18", "2026-09-24"))
        nb = p["numbers"]
        # 25–30 Sep have numbers (bk-024..029, bk-029 = 900), 1 Oct has none yet
        self.assertEqual(nb["reach"]["v"], sum(100 + i for i in range(24, 29)) + 900)
        self.assertEqual(nb["reach"]["posts"], 8)
        self.assertEqual(nb["reach"]["with_numbers"], 6)
        self.assertEqual(p["waiting_numbers"], 2)
        self.assertEqual(nb["reach"]["prev"], sum(100 + i for i in range(17, 24)))
        self.assertEqual(nb["followers"]["v"], 7 * 5)
        self.assertIsNone(nb["followers"]["prev"], "no account numbers for the week before: no comparison")
        self.assertEqual(nb["link_clicks"]["v"], 21)
        self.assertEqual(nb["spend"]["v"], 70.0)
        self.assertEqual(nb["results"]["v"], 4)
        self.assertEqual(nb["cost"]["v"], 17.5)
        self.assertIsNone(nb["spend"]["prev"], "3 of the 7 days before have a report: no comparison")
        self.assertEqual(p["best_posts"][0]["id"], "bk-029")
        self.assertEqual(p["best_posts"][0]["reason"], "Most reached")
        self.assertEqual(p["ads"][0]["ad_id"], "ad-1")
        self.assertEqual(p["ads"][0]["media"], {"image": "assets/ads/c1-feed.jpg"})
        self.assertIsNone(p["ads"][1]["media"], "a planned (not rendered) file is not media")
        self.assertEqual([a["name"] for a in p["adsets"]], ["Fresh", "Offer"])
        self.assertEqual(p["adsets"][0]["status"], "Live")
        self.assertEqual(p["adsets_level"], "adset")
        self.assertTrue(p["summary"][0].startswith("You got 4 enquiries at €17.50 each"), p["summary"])
        self.assertTrue(any("went out" in s for s in p["summary"]))
        self.assertTrue(any("“Fresh” ads brought 4 of the 4" in s for s in p["summary"]), p["summary"])

    def test_the_series(self):
        _, B = view({"bake"})
        s = B["bake"]["results"]["series"]
        self.assertEqual(len(s["reach"]), 180)
        start = date.fromisoformat(s["start"])
        self.assertEqual(start + timedelta(days=179), YDAY)
        i = (date(2026, 8, 31) - start).days
        self.assertIsNone(s["reach"][i], "before Otto's first post: no number")
        self.assertEqual(s["reach"][i + 1], 100)
        self.assertIsNone(s["reach"][-1], "yesterday's posts have no numbers yet")
        self.assertIsNone(s["spend"][-11], "no ads report that day")
        self.assertEqual(s["spend"][-1], 10.0)

    def test_thirty_days_has_no_full_earlier_period(self):
        _, B = view({"bake"})
        nb = B["bake"]["results"]["periods"]["30"]["numbers"]
        self.assertIsNone(nb["reach"]["prev"], "Otto started 1 Sep: 2–31 Aug is not an earlier Otto period")
        self.assertIsNone(nb["results"]["prev"])

    def test_no_source_is_never_a_zero(self):
        d = data()
        d["connections"] = []
        d["metrics"] = {}
        save(d)
        _, B = view({"bake"})
        nb = B["bake"]["results"]["periods"]["7"]["numbers"]
        self.assertEqual(nb["followers"], {"v": None, "prev": None, "state": "not_connected", "days": 0})
        d["connections"] = [{"id": "meta-bake", "status": "connected"}]
        save(d)
        _, B = view({"bake"})
        self.assertEqual(B["bake"]["results"]["periods"]["7"]["numbers"]["followers"]["state"], "pending")

    def test_a_new_trial_is_empty_and_its_ads_wait_for_a_plan(self):
        _, B = view({"trial"})
        r = B["trial"]["results"]
        self.assertEqual(r["state"], "empty")
        nb = r["periods"]["7"]["numbers"]
        self.assertEqual(nb["results"]["state"], "trial")
        self.assertIsNone(nb["spend"]["v"])
        self.assertEqual(nb["reach"]["state"], "none")
        self.assertIsNone(nb["reach"]["v"])
        self.assertEqual(r["periods"]["7"]["summary"], [])

    def test_before_otto_is_metas_baseline_as_context(self):
        _, B = view({"bake"})
        self.assertIsNone(B["bake"]["results"]["before"], "no baseline pulled: nothing shown")
        d = data()
        d["metrics"]["bake"]["baseline"] = {"joined": "2026-09-01", "since": "2026-08-02", "until": "2026-09-01", "days": 30,
                                            "final": True, "ig": {"reach": 4321, "interactions": 210, "follows": 30, "unfollows": 4,
                                                                  "link_taps": 17}, "fb": {"follows": 2, "unfollows": 1}}
        save(d)
        _, B = view({"bake"})
        bf = B["bake"]["results"]["before"]
        self.assertEqual((bf["reach"], bf["followers"], bf["link_taps"], bf["joined"]), (4321, 27, 17, "2026-09-01"))

    def test_campaign_rows_when_there_are_no_ad_rows(self):
        d = data()
        for e in d["ads"]["bake"]["daily"].values():
            e["meta"].pop("ads", None)
        save(d)
        _, B = view({"bake"})
        p = B["bake"]["results"]["periods"]["7"]
        self.assertEqual(p["adsets_level"], "campaign")
        self.assertEqual([a["name"] for a in p["adsets"]], ["Bake · October"])
        self.assertEqual(p["ads"], [])


class AdReviewTest(_Reset, unittest.TestCase):
    def test_the_months_ads_for_the_plan_card(self):
        _, B = view({"bake"})
        a = B["bake"]["ad_review"]
        self.assertEqual((a["month"], a["label"], a["plan_rec"], a["state"]), ("2026-11", "November", "rec-001", "proposed"))
        self.assertEqual(a["campaigns"], 3)
        self.assertEqual(a["budget"]["total"], 300.0)
        cells = [c for g in a["angles"] for c in g["cells"]]
        self.assertEqual([c["id"] for c in cells], ["n-c1", "n-c2", "n-c5"],
                         "the dropped cell and the creator video (Starter has no creator briefs) are left out")
        self.assertEqual((cells[0]["headline"], cells[0]["primary"]), ("Fresh at 7", "P one"))
        self.assertEqual((cells[1]["headline"], cells[1]["primary"]), ("Baked this morning", "P two"), "rotated over the cells")
        self.assertEqual(cells[2]["headline"], "Own headline")
        self.assertEqual((cells[2]["cta"], cells[2]["cta_label"]), ("ORDER_NOW", "Order now"))
        self.assertEqual(cells[1]["style_label"], "Text message")
        self.assertIsNone(cells[0]["media"])
        self.assertEqual(a["count"], 3)

    def test_rendered_files_become_media(self):
        d = data()
        d["campaigns"].append({"id": "cp-n9", "brand": "bake", "plan": "2026-11", "status": "draft", "start": "2026-11-01",
                               "end": "2026-11-02", "daily_budget": 1,
                               "creatives": {"concepts": [{"angle": "a1", "ads": [
                                   {"id": "n-c2", "files": [{"file": "assets/ads/n-c2-x.jpg", "size": "feed"}]},
                                   {"id": "n-c1", "files": [{"file": "assets/ads/n-c1.mp4", "kind": "video", "poster": "assets/ads/n-c1.jpg"}]},
                                   {"id": "n-c5", "files": [{"file": "/srv/secret/path.jpg", "size": "feed"}]}]}]}})
        save(d)
        _, B = view({"bake"})
        cells = {c["id"]: c for g in B["bake"]["ad_review"]["angles"] for c in g["cells"]}
        self.assertEqual(cells["n-c2"]["media"], {"image": "assets/ads/n-c2-x.jpg"})
        self.assertEqual(cells["n-c1"]["media"], {"video": "assets/ads/n-c1.mp4", "poster": "assets/ads/n-c1.jpg"})
        self.assertIsNone(cells["n-c5"]["media"], "a server path is never sent")

    def test_after_approval_the_approved_month(self):
        d = data()
        d["recommendations"][0]["status"] = "done"
        for c in d["campaigns"]:
            if c.get("plan") == "2026-11":
                c["status"] = "approved"
        save(d)
        (TMP / "brands" / "bake" / "ads-2026-10.json").write_text(json.dumps(dict(MATRIX, month="2026-10")))
        try:
            _, B = view({"bake"})
            a = B["bake"]["ad_review"]
            self.assertEqual((a["month"], a["plan_rec"], a["state"]), ("2026-11", None, "approved"))
        finally:
            (TMP / "brands" / "bake" / "ads-2026-10.json").unlink()

    def test_without_a_plan_card_this_months_matrix(self):
        d = data()
        d["recommendations"][0]["status"] = "done"
        save(d)
        (TMP / "brands" / "bake" / "ads-2026-10.json").write_text(json.dumps(dict(MATRIX, month="2026-10")))
        try:
            _, B = view({"bake"})
            a = B["bake"]["ad_review"]
            self.assertEqual((a["month"], a["plan_rec"], a["state"]), ("2026-10", None, "live"))
        finally:
            (TMP / "brands" / "bake" / "ads-2026-10.json").unlink()


class TenantTest(_Reset, unittest.TestCase):
    def test_a_clients_answer_carries_its_own_brand_only(self):
        v, B = view({"bake"})
        self.assertEqual(list(B), ["bake"])
        for k in ("today", "ledger", "results", "ad_review"):
            self.assertIn(k, B["bake"])
        blob = json.dumps(v)
        self.assertNotIn(OTHER_MARK, blob)
        for s in ("7777", "999.0", "ad-9", "set-9", "rc-9", "cp-900"):
            self.assertNotIn(s, json.dumps(B["bake"]), s)
        for s in INTERNAL:
            self.assertNotIn(s, blob, s)

    def test_the_other_client_sees_none_of_bake(self):
        v, B = view({"other"})
        self.assertEqual(list(B), ["other"])
        blob = json.dumps(v)
        for s in ("Loaf ", "Fresh at 7", "ad-1", "set-1", "rec-001", "Weekend loaves"):
            self.assertNotIn(s, blob, s)

    def test_the_owner_gets_every_brand(self):
        _, B = view(None)
        self.assertEqual(set(B), {"bake", "other", "trial"})
        self.assertTrue(all("results" in b for b in B.values()))

    def test_a_broken_brand_never_fails_the_answer(self):
        d = data()
        ap.brand(d, "bake")["tz"] = "Not/AZone"
        d["ads"]["bake"]["daily"] = {"garbage": "x", "2026-10-01": {"meta": "nope"}}
        d["metrics"]["bake"] = {"daily": {"x": 1}}
        save(d)
        _, B = view({"bake"})
        self.assertIn("results", B["bake"])


class ConnectHelpTest(_Reset, unittest.TestCase):
    def test_asking_otto_to_connect(self):
        otto_api.apply_brand("bake", {"connect_help": "meta"}, bids={"bake"})
        d = data()
        b = ap.brand(d, "bake")
        self.assertEqual(b["connect_help"]["meta"]["via"], "dashboard")
        cards = [r for r in d["recommendations"] if "asks for help connecting" in r["title"]]
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["audience"], cards[0]["priority"], cards[0]["brand"]), ("owner", "P0", "bake"))
        otto_api.apply_brand("bake", {"connect_help": "meta"}, bids={"bake"})
        self.assertEqual(len([r for r in data()["recommendations"] if "asks for help" in r["title"]]), 1, "never stacks")
        v = otto_api.client_view(data(), {"bake"})
        self.assertNotIn("asks for help", json.dumps(v["recommendations"]), "the card is the owner's")
        _, B = view({"bake"})
        meta = next(c for c in B["bake"]["ledger"]["connect"] if c["id"] == "meta")
        self.assertTrue(meta["requested"])
        self.assertIn("dashboard brand bake connect_help meta", (TMP / "actions.log").read_text())

    def test_another_brand_and_bad_values(self):
        with self.assertRaises(KeyError):
            otto_api.apply_brand("other", {"connect_help": "meta"}, bids={"bake"})
        for bad in ("instagram", 1, None, ["meta"]):
            with self.assertRaises(ValueError):
                otto_api.apply_brand("bake", {"connect_help": bad}, bids={"bake"})
        self.assertNotIn("connect_help", ap.brand(data(), "other"))


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
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, json.loads(x.read())

    def test_get_data_as_a_client(self):
        (TMP / "copy-usage.json").write_text(json.dumps({"days": {"2026-10-02": {"usd": 4.5678, "input_tokens": 12345}},
                                                         "brands": {"bake": {"usd": 4.5678, "stop": "the daily spend cap"}}}))
        code, d = self.get("owner@bake.example")
        self.assertEqual(code, 200)
        self.assertEqual([b["id"] for b in d["brands"]], ["bake"])
        b = d["brands"][0]
        for k in ("today", "ledger", "results", "ad_review", "work", "plan_view"):
            self.assertIn(k, b)
        blob = json.dumps(d)
        for s in INTERNAL + (OTHER_MARK, "4.5678", "12345", "spend cap"):
            self.assertNotIn(s, blob, s)

    def test_connect_help_over_http_is_tenant_scoped(self):
        def post(bid):
            body = json.dumps({"kind": "brand", "id": bid, "connect_help": "meta"}).encode()
            r = urllib.request.Request(self.base + "/otto-api/action", data=body, method="POST",
                                       headers={"Content-Type": "application/json", "X-Real-IP": "203.0.113.9",
                                                "X-Otto-User": "owner@bake.example", "Origin": "https://dash.monyflow.work"})
            try:
                with urllib.request.urlopen(r, timeout=20) as x:
                    return x.status, json.loads(x.read())
            except urllib.error.HTTPError as e:
                return e.code, None
        code, out = post("bake")
        self.assertEqual(code, 200)
        self.assertTrue(next(c for c in out["data"]["brands"][0]["ledger"]["connect"] if c["id"] == "meta").get("requested"))
        self.assertEqual(post("other")[0], 404)


class ReelsJobTest(_Reset, unittest.TestCase):
    def test_an_unwritten_reel_is_never_rendered(self):
        d = data()
        d["posts"] += [{"id": "rl-1", "brand": "bake", "format": "reel", "status": "draft", "slot": iso(date(2026, 10, 5))},
                       {"id": "rl-2", "brand": "bake", "format": "reel", "status": "draft", "slot": iso(date(2026, 10, 6)),
                        "script": [{"text": "  "}]},
                       {"id": "rl-3", "brand": "bake", "format": "reel", "status": "draft", "slot": iso(date(2026, 10, 7)),
                        "script": [{"text": "Scene one", "seconds": 5}]},
                       {"id": "rl-4", "brand": "bake", "format": "reel", "status": "pending_approval", "hook": "Hook"},
                       {"id": "rl-5", "brand": "bake", "format": "reel", "status": "draft", "caption": "Only a caption"},
                       {"id": "rl-6", "brand": "bake", "format": "reel", "status": "approved", "hook": "Approved one"},
                       {"id": "rl-7", "brand": "bake", "format": "reel", "status": "draft", "hook": "Has video", "video": "assets/x.mp4"},
                       {"id": "rl-8", "brand": "other", "format": "reel", "status": "draft", "hook": "Other brand"}]
        save(d)
        self.assertEqual(otto_video.missing(data(), "bake"), ["bk-r1", "rl-3", "rl-4", "rl-5"])
        self.assertNotIn("bk-r2", otto_video.missing(data()), "the October draft reel has no words yet")
        self.assertIn("rl-8", otto_video.missing(data()))

    def test_render_refuses_an_unwritten_reel(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertIsNone(otto_video.render("bk-r2", dry=True))
        self.assertIn("not written yet", buf.getvalue())
        self.assertNotIn("script", next(p for p in data()["posts"] if p["id"] == "bk-r2"), "no script made from the brand name")

    def test_the_cron_line_prints_only_written_reels(self):
        import subprocess
        out = subprocess.run([sys.executable, str(PLATFORM / "otto_video.py"), "missing", "--brand", "bake"], cwd=PLATFORM,
                             capture_output=True, text=True, env=dict(os.environ), timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), ["bk-r1"])


if __name__ == "__main__":
    unittest.main()
