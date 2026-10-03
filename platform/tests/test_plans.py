#!/usr/bin/env python3
"""Plan-based entitlements (plans.json): resolution, defaults and expiry (ap.plan_of / entitled / limit), the cron gates
(otto_cron — ads jobs skipped, ads-guard still running), paid refusals and the soft ad-spend band (otto_ads plan / launch /
resume / guard), month limits (otto_plan), the ad-matrix preset and video gating (otto_creative / otto_styles), Whop plan
mapping incl. a cancellation → "none" (otto_whop), the owner console's plan action + snapshot (otto_admin) and the client's
plan_view (otto_api). Stdlib unittest, no network, nothing outside a throwaway workspace (Meta / Google calls are fakes).

  cd platform && python3 tests/test_plans.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites

Under discover other suites have already imported these modules with their own OTTO_* paths, so setUpModule pins every
module-level path this suite touches to its own workspace and tearDownModule puts them back (the test_admin pattern).
"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-plans-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_LEADS": str(TMP / "leads.json"), "OTTO_EVENTS": str(TMP / "events.jsonl")}
CLEAR = ("WHOP_API_KEY", "WHOP_WEBHOOK_SECRET", "WHOP_COMPANY_ID", "OTTO_ADMIN_USERS", "OTTO_PLANS")
FOUNDING_WHOP = "plan_joHl1qsZoiJc9"
TODAY = datetime.now(timezone.utc).date()


def quiet(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        res = fn(*a, **kw)
    quiet.out = out.getvalue()
    return res


def brand(bid, plan=None, **kw):
    b = {"id": bid, "name": bid.replace("-", " ").title(), "url": f"{bid}.example", "lang": "EN", "tz": "Europe/Berlin",
         "countries": ["DE"], "currency": "EUR", "status": "active", "pillars": ["Education", "Proof"], "compliance": ""}
    if plan:
        b["plan"] = plan
    b.update(kw)
    return b


def seed():
    return {"brands": [brand("legacy"), brand("t-content", "content"), brand("t-starter", "starter"), brand("t-growth", "growth"),
                       brand("t-scale", "scale"), brand("t-none", "none")],
            "posts": [], "recommendations": [], "connections": [], "campaigns": [], "controls": {}}


def reset():
    for name in ("data.json", "billing.json", "actions.log", "heartbeats.json"):
        (TMP / name).unlink(missing_ok=True)
    (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    shutil.rmtree(TMP / "secrets", ignore_errors=True)
    shutil.rmtree(TMP / "brands", ignore_errors=True)
    (TMP / "secrets").mkdir()
    (TMP / "brands").mkdir()
    for b in ("legacy", "t-content", "t-starter", "t-growth", "t-scale"):
        (TMP / "secrets" / f"meta-{b}.json").write_text(json.dumps({"access_token": "T", "page_id": "P", "ig_user_id": "IG",
                                                                    "ad_account_id": "act_1"}))
    os.environ.pop("OTTO_PLANS", None)


def edit(fn):
    with ap.transaction(sync=False) as d:
        fn(d)


def camp(cid, bid, status="live", network="meta", start=-3, end=10, **kw):
    c = {"id": cid, "brand": bid, "network": network, "name": f"Flight {cid}", "status": status, "objective": "leads",
         "start": (TODAY + timedelta(days=start)).isoformat(), "end": (TODAY + timedelta(days=end)).isoformat(),
         "daily_budget": 10, "creative": {}, "remote": {"campaign_id": "M-" + cid} if network == "meta" else
         {"campaign": f"customers/1/campaigns/{cid}"}}
    c.update(kw)
    return c


def plans_file(mutate):
    """A copy of the real plans.json changed by `mutate`, used through OTTO_PLANS for one test."""
    cfg = json.loads((PLATFORM / "plans.json").read_text())
    mutate(cfg)
    f = TMP / f"plans-{len(list(TMP.glob('plans-*.json')))}.json"
    f.write_text(json.dumps(cfg))
    os.environ["OTTO_PLANS"] = str(f)
    return f


_SAVED = {}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    _SAVED["repo_data"] = (PLATFORM / "data.json").exists()
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_cron, otto_plan, otto_ads, otto_publish, otto_creative, otto_styles, otto_whop, otto_admin, otto_api, otto_onboard
    import ap, otto_cron, otto_plan, otto_ads, otto_publish, otto_creative, otto_styles, otto_whop, otto_admin, otto_api, otto_onboard  # noqa
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_publish.SECRETS, otto_publish.LOG, otto_ads.SECRETS, otto_ads.BRANDS,
                       otto_api.LOG, otto_plan.BRANDS, otto_creative.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_publish.SECRETS = otto_ads.SECRETS = TMP / "secrets"
    otto_publish.LOG, otto_api.LOG = TMP / "publish.log", TMP / "actions.log"
    otto_ads.BRANDS = otto_plan.BRANDS = otto_creative.BRANDS = TMP / "brands"
    reset()


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_publish.SECRETS, otto_publish.LOG, otto_ads.SECRETS, otto_ads.BRANDS, otto_api.LOG,
     otto_plan.BRANDS, otto_creative.BRANDS) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class _Fakes:
    """Meta through otto_publish.graph, Google through otto_ads.google_call: both record every status change; launches
    through a fake otto_ads.launch_meta; background runs through otto_whop.SPAWN."""

    def setUp(self):
        reset()
        self.status, self.launched, self.spawned = [], [], []
        saved = (otto_publish.graph, otto_ads.google_call, otto_ads.launch_meta, otto_whop.SPAWN)

        def graph(method, path, token, **params):
            if path in getattr(self, "meta_fails", ()):
                raise otto_publish.GraphError("Graph 100: campaign is locked")
            self.status.append(("meta", path, params.get("status")))
            return {"success": True, "id": "remote-1"}

        def google_call(g, path, body):
            op = body["operations"][0]["update"]
            self.status.append(("google", op["resourceName"], op["status"]))
            return {"results": [{}]}
        otto_publish.graph, otto_ads.google_call = graph, google_call
        otto_ads.launch_meta = lambda d, c, m, base, persist=None: self.launched.append(c["id"]) or {"campaign_id": "C1", "done": True}
        otto_whop.SPAWN = lambda args: self.spawned.append([Path(a).name for a in args[1:]])

        def restore():
            otto_publish.graph, otto_ads.google_call, otto_ads.launch_meta, otto_whop.SPAWN = saved
            os.environ.pop("OTTO_PLANS", None)
        self.addCleanup(restore)
        for b in ("t-growth", "t-starter"):
            (TMP / "secrets" / f"google-{b}.json").write_text(json.dumps({"client_id": "x", "client_secret": "y", "refresh_token": "z",
                                                                          "developer_token": "t", "customer_id": "1"}))


# ============================================================================================
# resolution, defaults, expiry
# ============================================================================================

class ResolutionTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.addCleanup(lambda: os.environ.pop("OTTO_PLANS", None))

    def test_plans_json_is_valid_and_matches_the_research_values(self):
        cfg = ap.plans_config()
        self.assertIsNone(cfg["error"])
        P = cfg["plans"]
        self.assertEqual(cfg["defaults"]["legacy"], "founding")
        self.assertEqual(cfg["defaults"]["new"], "starter")
        # Starter: EUR 79 a month, a monthly subscription (no yearly price), approved by Max on 2 Oct 2026
        # (docs/MESSAGE-2026-10.md); every other priced plan stays draft
        self.assertEqual((P["starter"]["monthly_eur"], P["starter"]["yearly_eur"], P["starter"]["status"]), (79, None, "approved"))
        self.assertNotIn("yearly", P["starter"]["stripe_price_ids"], "no yearly Stripe price slot for a monthly-only plan")
        self.assertEqual((P["starter"]["price_approved"]["by"], P["starter"]["price_approved"]["on"]), ("Max", "2026-10-02"))
        for pid in ("growth", "scale", "agency", "founding"):
            self.assertEqual(P[pid]["status"], "draft", f"{pid}: only Starter's price is approved")
        self.assertEqual((P["starter"]["features"]["ads_meta"], P["starter"]["features"]["ads_google"]), (True, False))
        self.assertEqual(P["starter"]["limits"]["ad_matrix_preset"], "micro")
        self.assertEqual((P["growth"]["limits"]["ad_spend_managed_eur_month"], P["growth"]["limits"]["reels_per_month"]), (5000, 8))
        self.assertEqual(P["growth"]["features"]["competitor_sweep"], "weekly")
        self.assertEqual((P["scale"]["limits"]["ad_matrix_preset"], P["scale"]["overage"]), ("scale", {"above_eur_month": 15000, "pct": 2}))
        self.assertEqual((P["agency"]["limits"]["brands"], P["agency"]["extra_brand_eur"]), (5, 79))
        self.assertFalse(P["content"]["public"])
        self.assertFalse(P["content"]["features"]["ads_meta"] or P["content"]["features"]["ads_google"])
        self.assertEqual(P["founding"]["founding_bridge"], {"growth_eur": 179, "starter_eur": 79, "locked_months": 12, "seat_cap": 50})
        self.assertEqual(P["founding"]["features"], P["growth"]["features"], "founding runs as Growth during the pilot")
        for pid in ("growth", "scale", "agency"):
            self.assertEqual(P[pid]["yearly_eur"], 10 * P[pid]["monthly_eur"], "yearly = two months free")

    def test_legacy_explicit_and_unknown(self):
        d = ap.load()
        p = ap.plan_of(d, "legacy")
        self.assertEqual((p["id"], p["source"]), ("founding", "legacy"))
        self.assertTrue(ap.entitled(d, "legacy", "ads") and ap.entitled(d, "legacy", "google"))
        self.assertEqual(ap.limit(d, "legacy", "ad_matrix_preset"), "launch")
        self.assertFalse(ap.entitled(d, "t-content", "ads"))
        self.assertEqual(ap.limit(d, "t-content", "posts_per_month"), 66)
        self.assertTrue(ap.entitled(d, "t-starter", "meta"))
        self.assertFalse(ap.entitled(d, "t-starter", "google"))
        d["brands"].append(brand("t-bogus", "platinum"))
        p = ap.plan_of(d, "t-bogus")
        self.assertEqual((p["id"], p["source"], p["requested"]), ("content", "unknown", "platinum"))
        self.assertFalse(ap.entitled(d, "t-bogus", "ads"), "an unknown plan id never gets paid ads")
        self.assertEqual(ap.plan_of(d, "nobody")["id"], "founding")

    def test_expiry_falls_back_to_content_after_the_last_day(self):
        d = ap.load()
        d["brands"].append(brand("t-pilot", "founding", plan_until=TODAY.isoformat()))
        self.assertEqual(ap.plan_of(d, "t-pilot", today=TODAY)["id"], "founding", "valid through plan_until")
        p = ap.plan_of(d, "t-pilot", today=TODAY + timedelta(days=1))
        self.assertEqual((p["id"], p["source"], p["expired"], p["requested"]), ("content", "expired", True, "founding"))
        self.assertFalse(ap.entitled(d, "t-pilot", "ads", today=TODAY + timedelta(days=1)))

    def test_one_owner_card_per_expired_plan(self):
        edit(lambda d: d["brands"].append(brand("t-pilot", "founding", plan_until=(TODAY - timedelta(days=2)).isoformat())))
        for _ in range(2):
            with ap.transaction(sync=False) as d:
                ap.plan_expiry_notices(d)
        recs = [r for r in ap.load()["recommendations"] if r.get("brand") == "t-pilot"]
        self.assertEqual(len(recs), 1)
        self.assertIn("Founding pilot plan ended", recs[0]["title"])
        self.assertEqual((recs[0]["audience"], recs[0]["source"]), ("owner", "plans"))
        self.assertFalse(otto_api.rec_visible(recs[0], {"t-pilot"}), "the client never sees the owner's card")

    def test_none_pauses_publishing(self):
        d = ap.load()
        self.assertIn("no active plan", ap.paused(d, "t-none"))
        self.assertIsNone(ap.paused(d, "t-content"))

    def test_new_brands_get_starter_not_billed_until_a_price_sells_it(self):
        self.assertEqual(ap.new_brand_plan(), ("starter", "not_billed"))
        plans_file(lambda c: c["plans"]["starter"].update(stripe_price_ids={"monthly": "price_1StarterTest", "yearly": None}))
        self.assertEqual(ap.new_brand_plan(), ("starter", None))
        plans_file(lambda c: c["plans"]["starter"].update(whop_plan_ids=["plan_starter_test"]))       # legacy Whop ids still count
        self.assertEqual(ap.new_brand_plan(), ("starter", None))

    def test_stripe_price_ids_map_prices_to_plans(self):
        plans_file(lambda c: (c["plans"]["growth"].update(stripe_price_ids={"monthly": "price_1GrowthM", "yearly": "price_1GrowthY"}),
                              c["plans"]["founding"].update(stripe_price_ids={"one_time": "price_1Founding"})))
        self.assertEqual(ap.plan_for_price("price_1GrowthY"), ("growth", "year"))
        self.assertEqual(ap.plan_for_price("price_1Founding"), ("founding", "one_time"))
        self.assertIsNone(ap.plan_for_price("price_unknown"))
        self.assertEqual((ap.price_for("growth", "month"), ap.price_for("starter", "month"), ap.price_for("growth", "week")),
                         ("price_1GrowthM", None, None))
        self.assertEqual(ap.plans_config()["plans"]["trial"]["stripe_price_ids"], {}, "a plan without prices has none")
        plans_file(lambda c: c["plans"]["growth"].update(stripe_price_ids={"monthly": "prod_123"}))
        self.assertIn("must be a Stripe price id", ap.plans_config()["error"])
        plans_file(lambda c: c["plans"]["growth"].update(stripe_price_ids={"weekly": None}))
        self.assertIn("stripe_price_ids must be", ap.plans_config()["error"])
        plans_file(lambda c: (c["plans"]["growth"].update(stripe_price_ids={"monthly": "price_1Same"}),
                              c["plans"]["starter"].update(stripe_price_ids={"monthly": "price_1Same"})))
        self.assertIn("listed twice", ap.plans_config()["error"])

    def test_onboarding_creates_a_starter_brand_flagged_not_billed(self):
        res = quiet(otto_onboard.create, "https://fresh-bakery.example", {"goal": "sales"}, scan=False)
        b = ap.brand(ap.load(), res["brand"])
        self.assertEqual((b["plan"], b["plan_billing"]), ("starter", "not_billed"))
        before = ap.brand(ap.load(), res["brand"])
        quiet(otto_onboard.create, "https://fresh-bakery.example", {"goal": "leads"}, scan=False)
        self.assertEqual(ap.brand(ap.load(), res["brand"])["plan"], before["plan"], "re-onboarding keeps the plan")

    def test_broken_or_invalid_plans_json_is_fail_safe(self):
        bad = TMP / "plans-broken.json"
        bad.write_text("{ not json")
        os.environ["OTTO_PLANS"] = str(bad)
        d = ap.load()
        p = ap.plan_of(d, "t-growth")
        self.assertEqual(p["source"], "config_error")
        self.assertIn("plans.json is unreadable", ap.no_ads_why(d, "t-growth"))
        self.assertTrue(p["features"]["organic"], "organic keeps running")
        plans_file(lambda c: c["plans"]["growth"].update(inherits="gold"))
        self.assertIn("inherits unknown plan", ap.plans_config()["error"])
        plans_file(lambda c: c["plans"]["content"]["features"].pop("reels"))
        self.assertIn("feature 'reels' missing", ap.plans_config()["error"])
        plans_file(lambda c: c["plans"]["starter"]["limits"].update(ad_matrix_preset="huge"))
        self.assertIn("ad_matrix_preset", ap.plans_config()["error"])
        plans_file(lambda c: c["plans"]["growth"].update(whop_plan_ids=[FOUNDING_WHOP]))
        self.assertIn("listed on both", ap.plans_config()["error"])

    def test_plans_json_edits_apply_without_a_restart(self):
        f = plans_file(lambda c: None)
        self.assertEqual(ap.limit(ap.load(), "t-content", "posts_per_month"), 66)
        cfg = json.loads(f.read_text())
        cfg["plans"]["content"]["limits"]["posts_per_month"] = 40
        f.write_text(json.dumps(cfg, indent=2))
        self.assertEqual(ap.limit(ap.load(), "t-content", "posts_per_month"), 40)


# ============================================================================================
# otto_cron gates
# ============================================================================================

class CronGateTest(unittest.TestCase):
    MON_LATE = datetime(2026, 11, 16, 5, 30, tzinfo=timezone.utc)     # a Monday, day 16 (Berlin 06:30: the sweep's hour)
    MON_FIRST = datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)     # the month's first Monday

    def tasks(self, job, **kw):
        return {t.brand: t for t in otto_cron.plan(job, seed(), kw.pop("now", self.MON_LATE), TMP / "brands", force=kw.pop("force", True))[0]}

    def test_ads_jobs_skip_brands_without_paid_ads(self):
        for job in ("ads-plan", "ads-launch", "ads-report"):
            t = self.tasks(job)
            self.assertEqual(t["t-content"].skip, "plan content has no paid ads", job)
            self.assertEqual(t["t-none"].skip, "no active plan (membership ended)", job)
            for bid in ("legacy", "t-starter", "t-growth", "t-scale"):
                self.assertIsNone(t[bid].skip, f"{job} {bid}")

    def test_guard_runs_whatever_the_plans(self):
        d = seed()
        for b in d["brands"]:
            b["plan"] = "content"
        d["campaigns"] = [camp("cp-1", "t-content")]
        guard = otto_cron.plan("ads-guard", d, self.MON_LATE, TMP / "brands", force=True)[0]
        self.assertEqual(len(guard), 1)
        self.assertIsNone(guard[0].skip)
        self.assertEqual(Path(guard[0].argv[1]).name, "otto_ads.py")
        self.assertEqual(guard[0].argv[2:], ["guard"])

    def test_none_sits_every_job_out(self):
        for job in ("publish", "cards", "reels", "genvisuals", "plan-month", "insights"):
            self.assertEqual(self.tasks(job)["t-none"].skip, "no active plan (membership ended)", job)
            self.assertIsNone(self.tasks(job)["t-content"].skip, job)

    def test_competitor_sweep_cadence_follows_the_plan(self):
        (TMP / "brands").mkdir(exist_ok=True)
        for bid in ("t-content", "t-growth", "legacy"):
            (TMP / "brands" / bid).mkdir(exist_ok=True)
            (TMP / "brands" / bid / "competitors.json").write_text("[]")
        late = self.tasks("competitors", force=False)
        self.assertIn("monthly", late["t-content"].skip)
        self.assertIsNone(late["t-growth"].skip, "growth sweeps weekly")
        self.assertIsNone(late["legacy"].skip, "the pilots (founding = growth) keep their weekly sweep")
        first = self.tasks("competitors", now=self.MON_FIRST, force=False)
        self.assertIsNone(first["t-content"].skip, "monthly = the first Monday of the month")
        self.assertIsNone(self.tasks("competitors")["t-content"].skip, "a run by hand (--all / --brand) sweeps anyway")

    def test_a_real_run_records_the_skip_in_the_heartbeat(self):
        work = Path(tempfile.mkdtemp(prefix="otto-plans-cron-"))
        self.addCleanup(shutil.rmtree, work, True)
        (work / "bin").mkdir()
        stub = ('import json, os, sys\nwith open(os.environ["STUB_RECORD"], "a") as f:\n'
                '    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")\n')
        for name in ("otto_ads.py",):
            (work / "bin" / name).write_text(stub)
        d = {"brands": [brand("t-content", "content"), brand("legacy")], "posts": [], "campaigns": [camp("cp-1", "t-content")]}
        (work / "data.json").write_text(json.dumps(d))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OTTO_", "STUB_"))}
        env.update(OTTO_DATA=str(work / "data.json"), OTTO_BRANDS=str(work / "brands"), OTTO_SECRETS=str(work / "secrets"),
                   OTTO_HTML=str(work / "index.html"), OTTO_CRON_BIN=str(work / "bin"), STUB_RECORD=str(work / "record.jsonl"))
        run = lambda *a: subprocess.run([sys.executable, str(PLATFORM / "otto_cron.py"), *a], env=env, capture_output=True,
                                        text=True, timeout=90)
        r = run("ads-launch", "--all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("t-content skipped: plan content has no paid ads", r.stdout)
        hb = json.loads((work / "heartbeats.json").read_text())["jobs"]["ads-launch"]
        self.assertEqual(hb["brands"]["t-content"], dict(hb["brands"]["t-content"], status="skipped", why="plan content has no paid ads"))
        self.assertEqual(hb["brands"]["legacy"]["status"], "ok")
        self.assertIn("1 skipped (1 plan content has no paid ads)", hb["summary"])
        r = run("ads-guard", "--all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = [json.loads(x) for x in (work / "record.jsonl").read_text().splitlines()]
        self.assertEqual(rec, [["otto_ads.py", "launch", "--brand", "legacy"], ["otto_ads.py", "guard"]])


# ============================================================================================
# otto_ads: refusal, networks, soft band, overage, launch / resume / guard
# ============================================================================================

class AdsPlanTest(_Fakes, unittest.TestCase):
    def cards(self, bid):
        return [r for r in ap.load()["recommendations"] if r.get("brand") == bid and r.get("action") == "approve_plan"]

    def month_eur(self, bid, ym):
        return sum(c["daily_budget"] * ((date.fromisoformat(c["end"]) - date.fromisoformat(c["start"])).days + 1)
                   for c in ap.load()["campaigns"] if c["brand"] == bid and c.get("plan") == ym)

    def test_plan_refuses_a_brand_without_paid_ads(self):
        for bid in ("t-content", "t-none"):
            self.assertEqual(quiet(otto_ads.plan, bid, "2031-04"), [])
            self.assertIn("REFUSED", quiet.out)
        self.assertEqual(ap.load()["campaigns"], [])
        self.assertEqual(self.cards("t-content"), [])

    def test_starter_plans_meta_only(self):
        quiet(otto_ads.plan, "t-starter", "2031-04", 20.0)
        nets = {c["network"] for c in ap.load()["campaigns"] if c["brand"] == "t-starter"}
        self.assertEqual(nets, {"meta"})
        self.assertIn("has no Google ads", quiet.out)

    def test_soft_band_grace_month_then_capped_with_the_next_plan_offered(self):
        quiet(otto_ads.plan, "t-starter", "2031-04", 50.0)          # 50/day evergreen + boosts ≈ €1,750 > €1,000
        self.assertGreater(self.month_eur("t-starter", "2031-04"), 1000, "the first month above the band is planned in full")
        card = self.cards("t-starter")[0]
        self.assertIn("plans it in full this once", card["why"])
        self.assertIn("suggests Growth", card["why"])
        self.assertEqual(card["band"]["mode"], "grace")
        self.assertEqual(ap.brand(ap.load(), "t-starter")["ad_band"]["2031-04"]["over"], True)
        quiet(otto_ads.plan, "t-starter", "2031-05", 50.0)          # the second month in a row above it
        total = self.month_eur("t-starter", "2031-05")
        self.assertLessEqual(total, 1000)
        self.assertGreater(total, 950)
        card = next(r for r in self.cards("t-starter") if r["plan"] == "2031-05")
        self.assertEqual(card["band"]["mode"], "capped")
        self.assertIn("second month in a row", card["why"])
        self.assertIn("Growth runs the full budget", card["why"])
        quiet(otto_ads.plan, "t-starter", "2031-07", 50.0)          # a gap month → a fresh grace month
        self.assertEqual(next(r for r in self.cards("t-starter") if r["plan"] == "2031-07")["band"]["mode"], "grace")

    def test_within_the_band_nothing_is_said(self):
        quiet(otto_ads.plan, "t-growth", "2031-04", 20.0)
        card = self.cards("t-growth")[0]
        self.assertNotIn("band", card)
        self.assertNotIn("plan covers", card["why"])
        self.assertEqual(ap.brand(ap.load(), "t-growth")["ad_band"]["2031-04"]["mode"], "within")

    def test_scale_above_15k_is_planned_in_full_and_shows_2_percent(self):
        quiet(otto_ads.plan, "t-scale", "2031-04", 600.0)           # ≈ €30,000 this month
        total = self.month_eur("t-scale", "2031-04")
        self.assertGreater(total, 15000)
        card = self.cards("t-scale")[0]
        self.assertEqual(card["band"]["mode"], "overage")
        self.assertAlmostEqual(card["band"]["overage_eur"], round((total - 15000) * 0.02, 2), places=1)
        self.assertIn("2% of the excess", card["why"])
        self.assertIn("Nothing is charged automatically", card["why"])
        s = otto_admin.build(ap.load(), [], {}, {}, {}, now=datetime(2031, 4, 10, 12, tzinfo=timezone.utc))
        b = next(x for x in s["brands"] if x["id"] == "t-scale")
        self.assertEqual(b["plan"]["band"]["mode"], "overage")
        self.assertTrue(any(i.startswith("Overage: 2% of") for i in b["issues"]))
        with ap.transaction(sync=False) as d:                      # approved flights → the console's usage overage
            for c in d["campaigns"]:
                c["status"] = "approved"
        s = otto_admin.build(ap.load(), [], {}, {}, {}, now=datetime(2031, 4, 10, 12, tzinfo=timezone.utc))
        ov = next(x for x in s["brands"] if x["id"] == "t-scale")["plan"]["overage"]
        self.assertAlmostEqual(ov["fee_eur"], round((total - 15000) * 0.02, 2), places=1)

    def test_launch_and_claim_refuse_networks_the_plan_does_not_cover(self):
        edit(lambda d: d["campaigns"].extend([camp("cp-1", "t-content", "approved", remote={}),
                                               camp("cp-2", "t-starter", "approved", network="google", remote={}),
                                               camp("cp-3", "t-starter", "approved", remote={})]))
        quiet(otto_ads.launch)
        self.assertIn("SKIPPED cp-1", quiet.out)
        self.assertIn("plan content has no paid ads", quiet.out)
        self.assertIn("SKIPPED cp-2", quiet.out)
        self.assertEqual(self.launched, ["cp-3"])
        st = {c["id"]: c["status"] for c in ap.load()["campaigns"]}
        self.assertEqual(st, {"cp-1": "approved", "cp-2": "approved", "cp-3": "live"})
        self.assertIsNone(otto_ads._claim("cp-1"), "the claim re-checks the plan inside its transaction")

    def test_resume_refuses_a_campaign_the_plan_does_not_cover(self):
        edit(lambda d: d["campaigns"].append(camp("cp-1", "t-content", "paused", paused_by="plan")))
        with self.assertRaises(otto_ads.LaunchError) as e:
            quiet(otto_ads.resume, "cp-1")
        self.assertIn("plan content has no paid ads", str(e.exception))
        self.assertEqual(self.status, [])


class GuardTest(_Fakes, unittest.TestCase):
    def test_guard_pauses_what_the_plan_no_longer_covers_and_says_so(self):
        edit(lambda d: d["campaigns"].extend([camp("cp-1", "t-content"), camp("cp-2", "t-growth"),
                                               camp("cp-3", "t-starter", network="google"),
                                               camp("cp-4", "t-content", end=-1)]))           # an ended flight
        quiet(otto_ads.guard)
        self.assertIn(("meta", "M-cp-1", "PAUSED"), self.status)
        self.assertIn(("google", "customers/1/campaigns/cp-3", "PAUSED"), self.status)
        d = ap.load()
        c = {x["id"]: x for x in d["campaigns"]}
        self.assertEqual((c["cp-1"]["status"], c["cp-1"]["paused_by"]), ("paused", "plan"))
        self.assertEqual(c["cp-2"]["status"], "live", "growth covers Meta")
        self.assertEqual((c["cp-3"]["status"], c["cp-3"]["paused_by"]), ("paused", "plan"))
        self.assertEqual(c["cp-4"]["status"], "ended", "ended flights still end on a content brand")
        cards = [r for r in d["recommendations"] if r.get("source") == "plans"]
        self.assertEqual(sorted(r["brand"] for r in cards), ["t-content", "t-starter"])
        self.assertTrue(all("not covered by the plan" in r["title"] and r["audience"] == "owner" for r in cards))
        self.assertEqual(len(d["campaigns"]), 4, "nothing is deleted")

    def test_a_pause_that_fails_stays_live_and_becomes_a_p0_card(self):
        edit(lambda d: d["campaigns"].append(camp("cp-1", "t-content")))
        self.meta_fails = ("M-cp-1",)
        quiet(otto_ads.guard)
        d = ap.load()
        self.assertEqual(ap.campaign(d, "cp-1")["status"], "live")
        self.assertTrue(any(r["priority"] == "P0" and r.get("campaign_id") == "cp-1" for r in d["recommendations"]))

    def test_guard_files_the_expiry_card_and_pauses_the_downgraded_pilot(self):
        edit(lambda d: (ap.brand(d, "legacy").update(plan="founding", plan_until=(TODAY - timedelta(days=3)).isoformat()),
                        d["campaigns"].append(camp("cp-1", "legacy"))))
        quiet(otto_ads.guard)
        quiet(otto_ads.guard)
        d = ap.load()
        self.assertEqual(ap.campaign(d, "cp-1")["paused_by"], "plan")
        self.assertEqual(len([r for r in d["recommendations"] if r.get("brand") == "legacy" and "plan ended" in r["title"]]), 1)

    def test_a_broken_plans_json_pauses_nothing(self):
        edit(lambda d: d["campaigns"].append(camp("cp-1", "t-growth")))
        bad = TMP / "plans-broken2.json"
        bad.write_text("[]")
        os.environ["OTTO_PLANS"] = str(bad)
        quiet(otto_ads.guard)
        d = ap.load()
        self.assertEqual(ap.campaign(d, "cp-1")["status"], "live")
        self.assertEqual(self.status, [])
        self.assertTrue(any(r["title"] == "Fix plans.json" and r["priority"] == "P0" for r in d["recommendations"]))


# ============================================================================================
# otto_plan limits
# ============================================================================================

class MonthLimitsTest(unittest.TestCase):
    def setUp(self):
        reset()

    def build(self, bid, ym="2031-03", **kw):
        return quiet(otto_plan._build, ap.load(), bid, ym, kw.get("per_week", 12), ("fb", "ig"), True, False, True)

    def counts(self, plan):
        c = {}
        for x in plan:
            c[x["format"]] = c.get(x["format"], 0) + 1
        return c

    def test_posts_and_reels_follow_the_plan(self):
        for bid, cap, reels in (("t-content", 66, 4), ("t-starter", 66, 4), ("t-growth", 70, 8), ("legacy", 70, 8)):
            plan = self.build(bid, per_week=20)
            self.assertLessEqual(len(plan), cap, bid)
            self.assertEqual(self.counts(plan).get("reel", 0), reels, bid)
        self.assertEqual(self.build("t-none"), [])
        self.assertIn("no organic content", quiet.out)

    def test_existing_posts_count_toward_the_month(self):
        edit(lambda d: [ap.add_post(d, "t-content", "A", "fb", f"2031-03-{i + 1:02d}T07:00", "kept", plan="2031-03", status="approved")
                        for i in range(20)])
        with ap.transaction(sync=False) as d:
            created = quiet(otto_plan._build, d, "t-content", "2031-03", 20, ("fb", "ig"), False, True, True)
        month = [p for p in ap.load()["posts"] if p["brand"] == "t-content" and p.get("plan") == "2031-03"]
        self.assertEqual(len(month), 66)
        self.assertEqual(len(created), 46)
        self.assertIn("allows 66 posts a month", quiet.out)
        days = sorted({p["slot"][:10] for p in created})
        self.assertGreaterEqual(days[-1], "2031-03-25", "thinned evenly, not cut at the end of the month")

    def test_hand_added_posts_count_like_the_console_counts_them(self):
        # regression (integration review): the build counted only posts tagged plan=<month>; a post added by hand (ap.py add,
        # the first week) has no tag, so the month ended above the limit the console measures (ap.plan_usage)
        edit(lambda d: [ap.add_post(d, "t-growth", "A", "ig", f"2031-03-{i + 1:02d}T07:00", "by hand", format="reel" if i < 3 else "post")
                        for i in range(10)])
        with ap.transaction(sync=False) as d:
            created = quiet(otto_plan._build, d, "t-growth", "2031-03", 20, ("fb", "ig"), False, False, True)
        self.assertEqual(len(created), 60, quiet.out)
        self.assertEqual(sum(1 for p in created if p["format"] == "reel"), 5, "8 reels a month, 3 already there")
        u = ap.plan_usage(ap.load(), "t-growth", today=date(2031, 3, 1))
        self.assertEqual((u["posts"], u["reels"]), (70, 8))


# ============================================================================================
# the ad matrix preset + video gating
# ============================================================================================

ANGLES = ["Pack vs powder: no shaker, no grit, a pack you eat instead of a powder", "Fiber gap: most people miss their fiber, 6 g in one pack",
          "For the guy who won't take vitamins", "Tastes like fruit snacks: the easy daily habit",
          "Subscription without the trap: pause or cancel anytime, money-back guarantee",
          "Halloween limited drop: the seasonal flavor before it sells out", "Kids ask for their pack: parents' picky-eater test",
          "Do gummies even absorb? The blood-test study, explained"]


def matrix_brand(bid):
    bdir = TMP / "brands" / bid
    bdir.mkdir(parents=True, exist_ok=True)
    stages = ["cold", "cold", "cold", "warm", "hot", "hot", "cold", "warm"]
    s = {"brand": bid, "personas": [{"id": "p1", "label": "Powder dropout", "words": ["the shaker was the worst part"]}],
         "angles": [{"id": f"a{i}", "angle": t, "persona": "p1", "stage": stages[i - 1], "source": "competitor" if i in (1, 8) else "profile",
                     "status": "idea"} for i, t in enumerate(ANGLES, 1)],
         "proof_bank": [], "offers": [], "events": []}
    (bdir / "strategy.json").write_text(json.dumps(s))
    (bdir / "competitors.json").write_text(json.dumps([{"name": "RivalCo", "site": ""}]))


class MatrixPresetTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_matrix_preset_comes_from_the_plan(self):
        d = ap.load()
        self.assertEqual([ap.matrix_preset(d, b) for b in ("t-content", "t-starter", "t-growth", "t-scale", "legacy")],
                         ["none", "micro", "launch", "scale", "launch"])
        self.assertEqual(ap.matrix_preset(d, "t-scale", "micro"), "micro", "the budget floor still wins")
        self.assertEqual(ap.matrix_preset(d, "t-starter", "launch"), "micro", "never above the plan")

    def test_matrix_cli_plans_the_plans_preset(self):
        for bid, preset, angles, per in (("t-starter", "micro", 4, 5), ("t-growth", "launch", 6, 6), ("t-scale", "scale", 6, 8)):
            matrix_brand(bid)
            self.assertEqual(quiet(otto_creative.matrix_cli, bid, "2031-06", ["--plan"]), 0, quiet.out)
            m = otto_styles.load_matrix(bid, "2031-06")
            self.assertEqual(m["preset"], preset, bid)
            self.assertEqual(len(m["angles"]), angles, bid)
            self.assertGreaterEqual(min(len(a["ads"]) for a in m["angles"]), per, bid)
        matrix_brand("t-content")
        self.assertEqual(quiet(otto_creative.matrix_cli, "t-content", "2031-06", ["--plan"]), 1)
        self.assertIn("has no ad matrix", quiet.out)
        self.assertIsNone(otto_styles.load_matrix("t-content", "2031-06"))
        self.assertIn("scale", otto_styles.PRESETS)

    def test_matrix_size_and_ad_band_use_one_exchange_rate(self):
        # regression (integration review): otto_styles had its own FX table (USD 1.08 per EUR) next to otto_whop.FX_EUR (0.86 EUR
        # per USD) — $40/day was "launch" for the matrix and €34 for the plan's band
        for amount, cur in ((40, "USD"), (45, "USD"), (30, "GBP"), (150, "ILS"), (9000, "HUF"), (36, "EUR"), (35.99, "EUR")):
            eur = ap.to_eur(amount, cur)
            self.assertEqual(otto_styles.preset_for_budget(amount, cur), "micro" if eur < otto_styles.MICRO_BELOW_DAILY_EUR else "launch",
                             (amount, cur, eur))
        self.assertEqual(otto_styles.preset_for_budget(100, "BGN"), "launch", "a currency FX_EUR lacks still converts")
        import otto_compliance
        self.assertIs(otto_compliance.CURRENCY_COUNTRY, ap.CURRENCY_COUNTRY)

    def test_ads_plan_writes_the_plans_matrix_with_its_refresh(self):
        matrix_brand("t-growth")
        quiet(otto_ads.plan, "t-growth", "2031-06", 60.0)
        m = otto_styles.load_matrix("t-growth", "2031-06")
        self.assertEqual((m["preset"], m["rules"]["refresh_per_angle_week"]), ("launch", 1))
        matrix_brand("t-starter")
        quiet(otto_ads.plan, "t-starter", "2031-06", 60.0)
        self.assertEqual(otto_styles.load_matrix("t-starter", "2031-06")["preset"], "micro", "Starter never gets more than micro")


class VideoGateTest(unittest.TestCase):
    def setUp(self):
        reset()

    @staticmethod
    def creatives(n_video=12, n_creator=2):
        ads = [{"id": f"v{i}", "angle": "a1", "style": "notes_app", "format": "video", "files": []} for i in range(n_video)]
        ads += [{"id": f"c{i}", "angle": "a1", "style": "ugc_talking_head", "format": "creator", "files": []} for i in range(n_creator)]
        ads += [{"id": "s1", "angle": "a1", "style": "quote", "format": "image", "files": []}]
        return {"concepts": [{"angle": "a1", "ads": ads}], "videos": [{"file": f"x{i}.mp4", "cell": f"v{i}"} for i in range(n_video)],
                "matrix": {"skipped": []}}

    def test_video_ads_follow_the_plan(self):
        d = ap.load()
        cr = quiet(otto_creative.plan_video, d, {"brand": "t-starter"}, self.creatives())
        fmts = [a["format"] for a in cr["concepts"][0]["ads"]]
        self.assertEqual((fmts.count("video"), fmts.count("creator"), fmts.count("image")), (10, 0, 1),
                         "Starter: 10 video ads a month, no creator briefs")
        self.assertEqual(len(cr["videos"]), 10)
        reasons = {x["reason"] for x in cr["plan"]["left_out"]}
        self.assertEqual(reasons, {"plan starter allows 10 video ads a month", "plan starter has no creator videos"})
        self.assertEqual(len(cr["matrix"]["skipped"]), 4)
        cr = quiet(otto_creative.plan_video, d, {"brand": "t-growth"}, self.creatives())
        self.assertEqual(len(cr["concepts"][0]["ads"]), 15, "Growth: all of them")
        self.assertNotIn("plan", cr)
        cr = quiet(otto_creative.plan_video, d, {"brand": "t-content"},
                   {"concepts": [], "videos": [{"file": "assets/reels/x.mp4", "from": "p1"}]})
        self.assertEqual(cr["videos"], [], "no video ads without the feature, even from the angle bank")


# ============================================================================================
# Whop mapping
# ============================================================================================

class WhopPlanTest(_Fakes, unittest.TestCase):
    def customer(self, mid, **kw):
        with otto_whop.transaction() as b:
            b["customers"][mid] = dict({"id": mid, "status": "active", "email": f"{mid}@gmail.com"}, **kw)

    def test_link_maps_the_whop_plan_and_clears_not_billed(self):
        edit(lambda d: d["brands"].append(brand("t-new", "starter", plan_billing="not_billed")))
        self.customer("mem_F", plan_id=FOUNDING_WHOP)
        c = otto_whop.link("mem_F", "t-new", by="max")
        self.assertEqual((c["plan_sync"]["from"], c["plan_sync"]["to"], c["plan_sync"]["changed"]), ("starter", "founding", True))
        b = ap.brand(ap.load(), "t-new")
        self.assertEqual(b["plan"], "founding")
        self.assertNotIn("plan_billing", b)
        h = b["plan_history"][-1]
        self.assertEqual((h["via"], h["membership"], h["whop_plan"], h["by"]), ("whop", "mem_F", FOUNDING_WHOP, "max"))

    def test_a_paid_link_takes_an_onboarding_brand_active(self):
        # regression (journey): a public sign-up stays "onboarding" and otto_cron runs "active" brands only — linking its paid
        # membership left it out of every job forever
        edit(lambda d: d["brands"].append(brand("t-signup", "starter", plan_billing="not_billed", status="onboarding")))
        self.assertEqual(otto_cron.brand_skip(ap.brand(ap.load(), "t-signup"), "publish"), "onboarding")
        self.customer("mem_S", plan_id=FOUNDING_WHOP)
        c = otto_whop.link("mem_S", "t-signup")
        self.assertTrue(c["plan_sync"]["activated"])
        b = ap.brand(ap.load(), "t-signup")
        self.assertEqual((b["status"], b["plan"]), ("active", "founding"))
        self.assertIsNone(otto_cron.brand_skip(b, "publish"))
        self.assertEqual(b["members"], ["mem_s@gmail.com"], "the CLI link makes the payer a member, like the console")
        self.assertEqual(c["member_added"], "mem_s@gmail.com")
        edit(lambda d: ap.brand(d, "t-signup").update(status="paused", paused={"at": "x", "by": "max"}))
        otto_whop.link("mem_S", "t-signup")
        self.assertEqual(ap.brand(ap.load(), "t-signup")["status"], "paused", "a console pause is never undone by billing")
        self.customer("mem_X", plan_id=FOUNDING_WHOP, status="canceled")
        edit(lambda d: d["brands"].append(brand("t-signup-2", "starter", status="onboarding")))
        otto_whop.link("mem_X", "t-signup-2")
        self.assertEqual(ap.brand(ap.load(), "t-signup-2")["status"], "onboarding", "an ended membership activates nothing")

    def test_a_subscription_plan_mapped_in_plans_json(self):
        plans_file(lambda cfg: cfg["plans"]["growth"].update(whop_plan_ids=["plan_growth_test"]))
        edit(lambda d: ap.brand(d, "t-content").update(plan_until="2031-01-01"))
        self.customer("mem_G", plan_id="plan_growth_test")
        otto_whop.link("mem_G", "t-content")
        b = ap.brand(ap.load(), "t-content")
        self.assertEqual(b["plan"], "growth")
        self.assertNotIn("plan_until", b, "another plan starts without the old end date")

    def test_an_unmapped_whop_plan_leaves_the_plan_alone(self):
        self.customer("mem_U", plan_id="plan_mystery")
        c = otto_whop.link("mem_U", "t-growth")
        self.assertFalse(c["plan_sync"]["changed"])
        self.assertIn("not mapped", c["plan_sync"]["why"])
        self.assertEqual(ap.brand(ap.load(), "t-growth")["plan"], "growth")
        msg = quiet(otto_admin.act, {"action": "link_customer", "customer": "mem_U", "brand": "t-growth"}, "max")["message"]
        self.assertIn("Plan unchanged", msg)

    def test_cancellation_moves_the_brand_to_none_and_pauses_it(self):
        edit(lambda d: (d["campaigns"].append(camp("cp-1", "t-growth")),
                        [ap.add_post(d, "t-growth", "A", "fb", "2031-01-01T09:00", "a post", status="approved") for _ in range(3)]))
        self.customer("mem_C", plan_id=FOUNDING_WHOP)
        otto_whop.link("mem_C", "t-growth")
        self.assertEqual(ap.brand(ap.load(), "t-growth")["plan"], "founding")
        before = ap.load()
        out = otto_whop.handle_event({"type": "membership.deactivated", "id": "evt_1",
                                      "data": {"id": "mem_C", "status": "canceled", "plan": {"id": FOUNDING_WHOP}}})
        self.assertEqual(out["plan"], {"brand": "t-growth", "from": "founding", "to": "none"})
        d = ap.load()
        self.assertEqual(ap.brand(d, "t-growth")["plan"], "none")
        self.assertIn("no active plan", ap.paused(d, "t-growth"))
        card = next(r for r in d["recommendations"] if r.get("brand") == "t-growth" and "membership ended" in r["title"])
        self.assertEqual(card["audience"], "owner")
        self.assertIn("1 live campaign is being paused", card["why"])
        self.assertEqual(self.spawned, [["otto_ads.py", "guard"]], "the guard pauses it now, not tomorrow")
        self.assertEqual((len(d["posts"]), len(d["campaigns"])), (len(before["posts"]), len(before["campaigns"])), "nothing deleted")
        quiet(otto_ads.guard)                                    # what the spawned guard does
        self.assertEqual(ap.campaign(ap.load(), "cp-1")["paused_by"], "plan")
        self.assertEqual(otto_whop.handle_event({"type": "membership.deactivated", "id": "evt_1", "data": {"id": "mem_C"}}),
                         {"duplicate": True, "type": "membership.deactivated"})

    def test_a_domain_match_never_changes_a_plan(self):
        self.customer("mem_D", plan_id=FOUNDING_WHOP, email="owner@t-content.example")        # the brand's domain, not linked
        otto_whop.handle_event({"type": "membership.deactivated", "id": "evt_2", "data": {"id": "mem_D", "status": "canceled"}})
        self.assertEqual(ap.brand(ap.load(), "t-content")["plan"], "content")
        self.assertEqual(self.spawned, [])


# ============================================================================================
# owner console: the plan action + snapshot; the client's plan_view
# ============================================================================================

class AdminPlanTest(_Fakes, unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError):
            otto_admin.act({"action": "plan", "brand": "t-growth", "plan": "platinum"}, "max")
        with self.assertRaises(KeyError):
            otto_admin.act({"action": "plan", "brand": "nope", "plan": "growth"}, "max")
        with self.assertRaises(ValueError):
            otto_admin.act({"action": "plan", "brand": "t-growth", "plan": "growth", "until": "next friday"}, "max")
        with self.assertRaises(ValueError):
            otto_admin.act({"action": "plan", "brand": "t-growth", "plan": "growth", "until": 20311231}, "max")
        self.assertEqual(ap.brand(ap.load(), "t-growth")["plan"], "growth")

    def test_downgrade_pauses_live_campaigns_through_the_pause_path(self):
        edit(lambda d: d["campaigns"].extend([camp("cp-1", "legacy"), camp("cp-2", "legacy", network="google"),
                                               camp("cp-3", "legacy", "draft")]))
        (TMP / "secrets" / "google-legacy.json").write_text(json.dumps({"client_id": "x", "client_secret": "y", "refresh_token": "z",
                                                                        "developer_token": "t", "customer_id": "1"}))
        out = quiet(otto_admin.act, {"action": "plan", "brand": "legacy", "plan": "content", "note": "client asked"}, "max")
        self.assertIn("Founding pilot → Content", out["message"])
        self.assertIn("Live campaigns paused: 2 of 2", out["message"])
        self.assertEqual(sorted(out["paused_campaigns"]), ["cp-1", "cp-2"])
        self.assertEqual(sorted(self.status), [("google", "customers/1/campaigns/cp-2", "PAUSED"), ("meta", "M-cp-1", "PAUSED")])
        d = ap.load()
        self.assertEqual({c["id"]: (c["status"], c.get("paused_by")) for c in d["campaigns"]},
                         {"cp-1": ("paused", "plan"), "cp-2": ("paused", "plan"), "cp-3": ("draft", None)})
        b = ap.brand(d, "legacy")
        self.assertEqual(b["plan"], "content")
        self.assertEqual({k: b["plan_history"][-1][k] for k in ("by", "via", "from", "to", "note")},
                         {"by": "max", "via": "admin", "from": "founding", "to": "content", "note": "client asked"})
        log = (TMP / "actions.log").read_text()
        self.assertIn("admin max plan legacy founding -> content live=2 failed=0", log)

    def test_growth_to_starter_pauses_only_google(self):
        edit(lambda d: d["campaigns"].extend([camp("cp-1", "t-growth"), camp("cp-2", "t-growth", network="google")]))
        out = quiet(otto_admin.act, {"action": "plan", "brand": "t-growth", "plan": "starter"}, "max")
        self.assertEqual(out["paused_campaigns"], ["cp-2"])
        self.assertEqual(ap.campaign(ap.load(), "cp-1")["status"], "live")

    def test_until_none_and_back(self):
        out = quiet(otto_admin.act, {"action": "plan", "brand": "t-content", "plan": "founding", "until": "2031-12-31"}, "max")
        self.assertIn("until 2031-12-31", out["message"])
        self.assertEqual(ap.brand(ap.load(), "t-content")["plan_until"], "2031-12-31")
        self.assertEqual(out["plan"]["id"], "founding")
        quiet(otto_admin.act, {"action": "plan", "brand": "t-content", "plan": "founding", "note": "same plan"}, "max")
        self.assertEqual(ap.brand(ap.load(), "t-content")["plan_until"], "2031-12-31", "the same plan keeps its end date")
        out = quiet(otto_admin.act, {"action": "plan", "brand": "t-content", "plan": "none"}, "max")
        self.assertIn("publishing and ad launches are paused", out["message"])
        self.assertNotIn("plan_until", ap.brand(ap.load(), "t-content"))
        self.assertTrue(ap.paused(ap.load(), "t-content"))
        quiet(otto_admin.act, {"action": "plan", "brand": "t-content", "plan": "starter"}, "max")
        self.assertIsNone(ap.paused(ap.load(), "t-content"), "a plan again resumes publishing")

    def test_kill_switch_resume_leaves_uncovered_campaigns_paused(self):
        edit(lambda d: d["campaigns"].append(camp("cp-1", "t-growth")))
        quiet(otto_admin.act, {"action": "kill_switch", "state": "on"}, "max")
        quiet(otto_admin.act, {"action": "plan", "brand": "t-growth", "plan": "content"}, "max")
        out = quiet(otto_admin.act, {"action": "kill_switch", "state": "off"}, "max")
        self.assertIn("1 stay paused", out["message"])
        c = ap.campaign(ap.load(), "cp-1")
        self.assertEqual((c["status"], c["paused_by"]), ("paused", "plan"))

    def test_snapshot_carries_plans_usage_and_the_catalogue(self):
        now = datetime(2031, 3, 10, 12, tzinfo=timezone.utc)
        edit(lambda d: (ap.brand(d, "t-starter").update(plan_billing="not_billed"),
                        [ap.add_post(d, "t-starter", "A", "ig", f"2031-03-{i + 1:02d}T09:00", "x", format="reel" if i < 5 else "post")
                         for i in range(70)],
                        d["campaigns"].append(camp("cp-1", "t-content", start=-400, end=400))))
        s = otto_admin.build(ap.load(), [], {}, {}, {}, now=now)
        self.assertEqual([p["id"] for p in s["plans"]["items"]],
                         ["starter", "growth", "scale", "agency", "founding", "trial", "content", "none"])
        self.assertIsNone(s["plans"]["error"])
        b = {x["id"]: x for x in s["brands"]}
        P = b["t-starter"]["plan"]
        self.assertEqual((P["id"], P["label"], P["usage"]["posts"], P["usage"]["reels"]),
                         ("starter", "Starter", {"used": 70, "limit": 66}, {"used": 5, "limit": 4}))
        self.assertEqual(P["usage"]["ad_budget_eur"], {"used": 0, "limit": 1000})
        self.assertIn("70 posts planned this month, the plan allows 66", b["t-starter"]["issues"])
        self.assertIn("Not billed yet: on Starter without a subscription", b["t-starter"]["issues"])
        self.assertIn("1 live campaign not covered by the plan (the daily guard pauses them)", b["t-content"]["issues"])
        self.assertEqual(b["t-none"]["health"], "blocked")
        self.assertEqual(b["legacy"]["plan"]["source"], "legacy")
        self.assertIn("Paid campaigns on Meta, ad spend up to €1,000 a month", P["included"])
        setup = next(x for x in s["setup"] if x["key"] == "plans")
        self.assertEqual(setup["status"], "waiting")
        self.assertIn("draft prices", setup["detail"])

    def test_the_client_sees_its_plan_but_not_the_owners_notes(self):
        edit(lambda d: ap.brand(d, "t-content").update(plan_billing="not_billed", plan_history=[{"by": "max", "note": "late payer"}],
                                                        ad_band={"2031-03": {"over": True}}, members=["a@t-content.example"]))
        view = otto_api.with_plans(otto_api.client_view(ap.load(), {"t-content"}))
        b = view["brands"][0]
        for k in ("plan_history", "plan_billing", "ad_band", "members"):
            self.assertNotIn(k, b)
        self.assertEqual(b["plan_view"]["label"], "Content")
        self.assertFalse(b["plan_view"]["paid_ads"])
        self.assertNotIn("not_billed", b["plan_view"])
        self.assertNotIn("late payer", json.dumps(view))
        html = (PLATFORM / "index.html").read_text()
        self.assertIn("/pilot-landing.html#pricing", html)
        self.assertIn("Add paid campaigns", html)


class IsolationTest(unittest.TestCase):
    def test_real_workspace_untouched(self):
        self.assertEqual((PLATFORM / "data.json").exists(), _SAVED["repo_data"])
        self.assertFalse((PLATFORM / "billing.json").exists())


if __name__ == "__main__":
    unittest.main()


class ActivationAndDefaultsTest(unittest.TestCase):
    """Closing the round-2 judgment calls: a client outside Whop can be activated; defaults match plans.json."""

    def test_new_brands_default_to_starter_and_email(self):
        self.assertEqual(ap.PLAN_DEFAULTS["new"], "starter")

    def test_activate_and_plan_by_hand_take_an_onboarding_brand_active(self):
        import otto_admin
        with ap.transaction(sync=False) as d:
            for bid in ("t-act1", "t-act2"):
                d["brands"] = [b for b in d.get("brands", []) if b.get("id") != bid]
                d["brands"].append({"id": bid, "name": bid, "url": f"{bid}.example", "lang": "EN", "tz": "UTC",
                                    "status": "onboarding", "pillars": ["A"], "compliance": "", "plan": "starter"})
        out = otto_admin.act({"action": "activate", "brand": "t-act1"}, who="test")
        self.assertIn("active", out["message"])
        self.assertEqual(ap.brand(ap.load(), "t-act1")["status"], "active")
        self.assertIn("already active", otto_admin.act({"action": "activate", "brand": "t-act1"}, who="test")["message"])
        out = otto_admin.act({"action": "plan", "brand": "t-act2", "plan": "growth"}, who="test")
        self.assertEqual(ap.brand(ap.load(), "t-act2")["status"], "active")
        self.assertIn("active now", out["message"])
