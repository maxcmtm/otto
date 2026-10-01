#!/usr/bin/env python3
"""The 07:35 morning report (otto_report + otto_email.send_report + the otto_cron morning-report job): who gets it (channel,
plan, local time), what it says with and without data (yesterday's posts and numbers, paid spend vs budget only for plans with
paid ads, today, the decisions waiting), honest empty states, the one-tap links inside it working end to end, once per brand
per local day, the approvals it carries not being sent again by the 08:00 / 18:30 catch-up runs, the Telegram twin followed by
the cards, the plain-digest fallback, and the fresh-numbers pull. Stdlib unittest, no network, a throwaway workspace.

  cd platform && python3 tests/test_morning_report.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, email, email.policy, io, json, os, re, shutil, sys, tempfile, unittest, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-report-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public_assets"),
       "OTTO_PUBLIC_BASE": "https://otto.example/", "OTTO_OUTBOX": str(TMP / "outbox"),
       "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"), "OTTO_REPORT_STATE": str(TMP / ".report-state.json")}
CLEAR = ("OTTO_DOMAIN", "OTTO_APP_URL", "OTTO_EMAIL_BASE", "OTTO_ADMIN_USERS", "OTTO_PLANS", "TELEGRAM_BOT_TOKEN",
         "OTTO_OWNER_CHAT_ID", "OTTO_TZ")
NOW = datetime(2026, 11, 5, 6, 35, tzinfo=timezone.utc)            # Thu 5 Nov, 07:35 in Amsterdam (winter time)
YDAY = "2026-11-04"
SECRET = "r" * 48
CFG = {"link_secret": SECRET, "app_url": "https://app.otto.example/", "action_base": "https://otto.example"}
EVA, SEAN, JANA, PIET, TOM = "eva@koffie.example", "sean@heating.example", "jana@spree.example", "piet@nieuw.example", "tom@tele.example"
NBSP = " "


def post(pid, brand, status, slot, **kw):
    return dict({"id": pid, "brand": brand, "pillar": "Koffie", "platform": "ig", "hook": f"Hook {pid}", "status": status,
                 "slot": slot}, **kw)


def day_entry(spend, leads, cur="EUR"):
    rows = [{"id": "111", "name": "Lunch reel", "objective": "OUTCOME_LEADS", "conversion": True, "spend": round(spend * .6, 2),
             "results": leads - 1, "cost_per_result": round(spend * .6 / max(1, leads - 1), 2), "link_clicks": 50},
            {"id": "222", "name": "Weekend boost", "objective": "OUTCOME_LEADS", "conversion": True, "spend": round(spend * .4, 2),
             "results": 1, "cost_per_result": round(spend * .4, 2), "link_clicks": 30}]
    tot = {"spend": spend, "results": leads, "results_by_type": {"leads": leads}, "clicks": 100, "link_clicks": 80,
           "impressions": 5000, "cpl": round(spend / leads, 2), "ctr": 2.0}
    return {"meta": {"yesterday": tot, "week": tot, "campaigns": rows, "currency": cur}, "google": None}


def seed():
    daily = {}
    for i, (sp, ld) in enumerate([(14.2, 2), (16.8, 3), (19.1, 4), (12.5, 2), (17.9, 3), (15.0, 3), (18.4, 4)]):
        data_day = datetime(2026, 10, 29) + timedelta(days=i)                 # 29 Oct … 4 Nov
        daily[(data_day + timedelta(days=1)).strftime("%Y-%m-%d")] = day_entry(sp, ld)
    return {
        "brands": [
            {"id": "koffie", "name": "Grachten Koffie", "url": "koffie.example", "lang": "NL", "tz": "Europe/Amsterdam",
             "status": "active", "plan": "growth", "approvals": "email", "members": [EVA], "currency": "EUR", "comms_lang": "nl"},
            {"id": "heating", "name": "Galway Heating", "url": "heating.example", "lang": "EN", "tz": "Europe/Dublin",
             "status": "active", "plan": "trial", "approvals": "email", "members": [SEAN]},
            {"id": "spree", "name": "Studio Spree", "url": "spree.example", "lang": "DE", "tz": "Europe/Berlin",
             "status": "active", "plan": "content", "approvals": "email", "members": [JANA], "comms_lang": "de"},
            {"id": "nieuw", "name": "Bakkerij Nieuw", "url": "nieuw.example", "lang": "NL", "tz": "Europe/Amsterdam",
             "status": "active", "plan": "content", "approvals": "email", "members": [PIET], "comms_lang": "nl"},
            {"id": "tele", "name": "Tele Bikes", "url": "tele.example", "lang": "NL", "tz": "Europe/Amsterdam",
             "status": "active", "plan": "starter", "approvals": "telegram", "members": [TOM], "comms_lang": "nl"},
            {"id": "both", "name": "Both Bakes", "url": "both.example", "lang": "EN", "tz": "Europe/Amsterdam",
             "status": "active", "plan": "content", "approvals": ["email", "telegram"], "members": ["bo@both.example"]},
            {"id": "appy", "name": "Appy", "url": "appy.example", "tz": "Europe/Amsterdam", "status": "active", "plan": "content",
             "approvals": "app", "members": ["a@appy.example"]},
            {"id": "lapsed", "name": "Lapsed", "url": "lapsed.example", "tz": "Europe/Amsterdam", "status": "active", "plan": "none",
             "approvals": "email", "members": ["l@lapsed.example"]},
            {"id": "dublin", "name": "Dublin Later", "url": "dublin.example", "tz": "Europe/Dublin", "status": "active",
             "plan": "content", "approvals": "email", "members": ["d@dublin.example"]}],
        "posts": [
            post("ko-001", "koffie", "published", f"{YDAY}T12:00", format="reel", hook="Zo zetten wij een flat white",
                 image="https://otto.example/assets/posts/ko-001.jpg", published_at=f"{YDAY}T11:00:12Z", remote_id="r1",
                 metrics={"reach": 1240, "clicks": 32, "likes": 61, "comments": 7, "saves": 12}),
            post("ko-002", "koffie", "published", f"{YDAY}T18:00", platform="fb", hook="Nieuwe oogst uit Kenia",
                 published_at=f"{YDAY}T17:00:05Z", remote_id="r2", metrics={"reach": 410, "clicks": 9, "likes": 14}),
            post("ko-003", "koffie", "published", f"{YDAY}T20:00", format="story", hook="Vanavond open tot 22:00",
                 published_at=f"{YDAY}T19:00:03Z", remote_id="r3"),
            post("ko-010", "koffie", "approved", "2026-11-05T12:00", hook="Sinterklaasblend is binnen"),
            post("ko-020", "koffie", "pending_approval", "2026-11-06T09:00", format="reel", hook="Achter de brander",
                 caption="Om 6 uur gaat de brander aan.", image="https://otto.example/assets/posts/ko-020.jpg"),
            post("ko-021", "koffie", "pending_approval", "2026-11-07T12:00", platform="fb", hook="Proefochtend zaterdag"),
            post("ko-022", "koffie", "pending_approval", "2026-11-07T18:00", hook="Het wondermiddel",
                 caption="Onze koffie is een wondermiddel."),                                   # compliance hold
            post("ko-030", "koffie", "pending_approval", "2026-11-20T09:00", hook="Ver weg"),        # beyond 72 h
            post("he-001", "heating", "published", f"{YDAY}T09:00", platform="fb", hook="Is your boiler ready?",
                 published_at=f"{YDAY}T09:00:00Z", metrics={"reach": 860, "clicks": 21}),
            post("he-002", "heating", "pending_approval", "2026-11-06T08:00", platform="fb", hook="The 5-minute boiler check"),
            post("sp-001", "spree", "published", f"{YDAY}T10:00", hook="Neue Kurse ab Dezember",
                 published_at=f"{YDAY}T09:00:00Z"),
            post("nw-001", "nieuw", "pending_approval", "2026-11-05T16:00", hook="Ons zuurdesembrood"),
            post("te-001", "tele", "pending_approval", "2026-11-06T10:00", hook="Fietsen voor de winter"),
            post("bo-001", "both", "pending_approval", "2026-11-06T10:00", hook="Both ways")],
        "recommendations": [
            {"id": "rec-001", "priority": "P1", "title": "Approve the 2026-12 paid plan: 2 campaigns, ≈€720", "why": "Evergreen.",
             "impact": "Paid runs", "cta": "Approve plan", "status": "proposed", "brand": "koffie", "source": "otto_ads",
             "action": "approve_plan", "plan": "2026-12"},
            {"id": "rec-002", "priority": "P1", "title": "Owner only", "why": "w", "impact": "i", "cta": "c", "status": "proposed",
             "brand": "koffie", "audience": "owner"},
            {"id": "rec-003", "priority": "P0", "title": "Connect Instagram and Facebook for Bakkerij Nieuw", "why": "…",
             "impact": "Unblocks publishing", "cta": "Connect", "status": "proposed", "brand": "nieuw", "source": "otto_onboard",
             "onboard_step": "meta", "i18n": {"key": "rec.connect_meta", "args": {"name": "Bakkerij Nieuw"}}}],
        "campaigns": [
            {"id": "cp-001", "brand": "koffie", "plan": "2026-11", "status": "live", "network": "meta", "name": "Lunch reel",
             "daily_budget": 12, "start": "2026-10-29", "end": "2026-11-30", "currency": "€", "currency_code": "EUR",
             "remote": {"campaign_id": "111"}},
            {"id": "cp-002", "brand": "koffie", "plan": "2026-11", "status": "live", "network": "meta", "name": "Weekend boost",
             "daily_budget": 8, "start": "2026-11-01", "end": "2026-11-30", "currency": "€", "currency_code": "EUR",
             "remote": {"campaign_id": "222"}},
            {"id": "cp-010", "brand": "koffie", "plan": "2026-12", "status": "draft", "network": "meta", "name": "December evergreen",
             "daily_budget": 20, "start": "2026-12-01", "end": "2026-12-31", "currency": "€", "currency_code": "EUR"},
            {"id": "cp-011", "brand": "koffie", "plan": "2026-12", "status": "draft", "network": "meta", "name": "Kerstboost",
             "daily_budget": 10, "start": "2026-12-15", "end": "2026-12-24", "currency": "€", "currency_code": "EUR"}],
        "ads": {"koffie": {"connections": {"meta": True, "google": False}, "targets": {"cpl": None}, "daily": daily}},
        "connections": [], "taste_log": []}


def reset(data=None):
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    for d in ("brands", "secrets", "outbox", "public_assets"):
        shutil.rmtree(TMP / d, ignore_errors=True)
    (TMP / "brands" / "koffie").mkdir(parents=True)
    (TMP / "brands" / "koffie" / "compliance.json").write_text(json.dumps({"banned": ["wondermiddel"]}))
    (TMP / "secrets").mkdir()
    (TMP / "secrets" / "email.json").write_text(json.dumps(CFG))
    (TMP / "public_assets" / "posts").mkdir(parents=True)
    (TMP / "data.json").write_text(json.dumps(data or seed(), ensure_ascii=False, indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    otto_email._rl.clear()
    otto_email._rl_global[:] = [0, 0]
    otto_i18n._voice_cache.clear()
    TG.clear()


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        r = fn(*a, **kw)
    quiet.last = out.getvalue()
    return r


def outbox():
    d = TMP / "outbox"
    return sorted(d.glob("*.eml")) if d.is_dir() else []


def parse(f):
    msg = email.message_from_bytes(Path(f).read_bytes(), policy=email.policy.default)
    return msg, msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()


def plain(s):
    return s.replace(NBSP, " ")


TG = []                                   # Telegram messages (otto_watch.send) and API calls (otto_telegram.api)
_SAVED = {}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_email, otto_report, otto_cron, otto_i18n, otto_watch, otto_telegram, otto_api
    import ap, otto_email, otto_report, otto_cron, otto_i18n, otto_watch, otto_telegram, otto_api     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_watch.HIST, otto_watch.STATE, otto_api.LOG)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_watch.HIST, otto_watch.STATE, otto_api.LOG = TMP / "metrics_history.jsonl", TMP / ".watch-state.json", TMP / "actions.log"
    _SAVED["send"], _SAVED["api"] = otto_watch.send, otto_telegram.api
    otto_watch.send = lambda text: TG.append(("report", text)) or True
    otto_telegram.api = lambda method, files=None, **kw: TG.append((method, kw)) or {"message_id": len(TG)}
    os.environ["TELEGRAM_BOT_TOKEN"], os.environ["OTTO_OWNER_CHAT_ID"] = "t", "42"
    reset()


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS, otto_watch.HIST, otto_watch.STATE, otto_api.LOG = _SAVED["paths"]
    otto_watch.send, otto_telegram.api = _SAVED["send"], _SAVED["api"]
    for k in ("TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID"):
        os.environ.pop(k, None)
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def model(bid, now=NOW):
    d = ap.load()
    return otto_report.model(d, ap.brand(d, bid), now)


def send(bid, now=NOW, **kw):
    kw.setdefault("refresh_numbers", False)
    kw.setdefault("verify_media", False)
    return quiet(otto_report.send, bid, now=now, **kw)


# ============================================================================================
# who gets it: channel, plan, local time
# ============================================================================================

class SelectionTest(unittest.TestCase):
    def setUp(self):
        reset()

    def plan(self, now=NOW, last=None, force=False):
        todo, not_due = otto_cron.plan("morning-report", ap.load(), now, TMP / "brands", last=last, force=force)
        return {t.brand: t for t in todo}, not_due

    def test_job_is_07_35_brand_time_per_brand(self):
        j = otto_cron.JOBS["morning-report"]
        self.assertEqual((j.local, j.scope), ("07:35", otto_cron.BRAND))
        self.assertEqual(otto_cron.calendar("morning-report"), "*-*-* *:35:00")
        self.assertEqual(otto_cron.JOBS["ads-report"].local, "07:15", "yesterday's paid numbers land before the report")
        self.assertEqual(otto_cron.JOBS["email-cards"].local, "08:00", "the digest stays as the catch-up")

    def test_channel_and_plan_gates(self):
        run, _ = self.plan(force=True)
        argv = lambda b: [Path(run[b].argv[1]).name] + run[b].argv[2:]
        self.assertEqual(argv("koffie"), ["otto_report.py", "send", "--brand", "koffie"])
        for bid in ("koffie", "heating", "spree", "nieuw", "tele", "both"):
            self.assertIsNone(run[bid].skip, bid)                  # e-mail, Telegram and both
        self.assertEqual(run["appy"].skip, "approvals in the app only (brands[].approvals)")
        self.assertEqual(run["lapsed"].skip, "no active plan (membership ended)")
        self.assertEqual(otto_cron.PLAN_GATES["morning-report"], "reports")

    def test_local_time_and_once_per_local_day(self):
        run, wait = self.plan(NOW - timedelta(minutes=5))           # 07:30 Amsterdam
        self.assertNotIn("koffie", run)
        self.assertIn("later today", wait["koffie"])
        run, wait = self.plan()                                     # 07:35 Amsterdam, 06:35 Dublin
        self.assertIn("koffie", run)
        self.assertEqual(run["koffie"].day, "2026-11-05")
        self.assertIn("later today", wait["dublin"])
        run, _ = self.plan(NOW + timedelta(hours=1))                # 07:35 Dublin
        self.assertIn("dublin", run)
        run, wait = self.plan(NOW, last={"koffie": "2026-11-05"})
        self.assertEqual(wait["koffie"], "already ran today")
        summer = datetime(2026, 10, 22, 5, 35, tzinfo=timezone.utc)  # Amsterdam summer time (UTC+2): 07:35 local
        self.assertIn("koffie", self.plan(summer)[0])

    def test_ads_report_is_quiet_when_the_telegram_report_carries_it(self):
        tasks = {t.brand: t for t in otto_cron.plan("ads-report", ap.load(), NOW, TMP / "brands", force=True)[0]}
        self.assertIn("--no-send", tasks["tele"].argv, "the Telegram morning report carries the paid numbers")
        self.assertNotIn("--no-send", tasks["koffie"].argv, "an e-mail brand: the owner's Telegram block is unchanged")

    def test_skip_reasons_inside_send(self):
        self.assertEqual(send("appy")["skipped"], "approvals in the app only (brands[].approvals)")
        self.assertEqual(send("lapsed")["skipped"], "no active plan (membership ended)")
        self.assertEqual(outbox(), [])


# ============================================================================================
# content: with data, without data, paid only when entitled
# ============================================================================================

class ContentTest(unittest.TestCase):
    def setUp(self):
        reset()

    def render(self, bid, now=NOW):
        d = ap.load()
        b = ap.brand(d, bid)
        m = otto_report.model(d, b, now)
        cfg = otto_email.safe_config()
        return m, otto_email.render_report(b, m, b["members"][0], cfg, now, otto_email.link_secrets(cfg)[0], verify=False)

    def test_with_data_like_the_ads(self):
        m, (subj, html, text) = self.render("koffie")
        p = m["paid"]
        self.assertEqual((p["state"], p["spend"], p["results"], p["budget"], p["kind"]), ("ok", 18.4, 4, 20.0, "leads"))
        self.assertEqual(p["avg7"], 2.8)                         # the 7 days before yesterday that exist (6 of them)
        self.assertEqual(p["month"], {"spent": sum([12.5, 17.9, 15.0, 18.4]), "planned": 600.0})
        self.assertEqual(len(p["chart"]), 7)
        self.assertEqual(p["best"]["name"], "Lunch reel")
        # the ad: "Goedemorgen. Gisteren: €18 aan advertenties, 4 aanvragen." · "Best gelopen" · "3 posts staan klaar"
        self.assertTrue(plain(m["summary"]).startswith("Goedemorgen. Gisteren: € 18,40 aan advertenties, 4 aanvragen."), m["summary"])
        self.assertIn("2 posts en 1 beslissing wachten op je.", m["summary"])
        self.assertEqual(plain(subj), "Ochtendrapport do 5 nov · Grachten Koffie · 3 wachten op je")
        h = plain(html)
        for want in ("Ochtendrapport", "donderdag 5 november · 07:35", "Uitgegeven", "€ 18,40", "binnen je dagbudget van € 20",
                     "Aanvragen", "7-daags gemiddelde 2,8", "Aanvragen per dag", "Kosten per aanvraag gisteren: € 4,60.",
                     "Beste advertentie: ‘Lunch reel’", "Deze maand tot nu toe: € 63,80 van € 600 gepland.",
                     "Zo zetten wij een flat white", "1.240 bereikt · 32 klikken · 68 reacties · 12 keer bewaard", "Best gelopen",
                     "De cijfers volgen morgen in je rapport.", "Wacht op jou", "Achter de brander", "Proefochtend zaterdag",
                     "Goedkeuren", "Overslaan", "Wijzigen", "Advertentieplan voor december goedkeuren",
                     "2 campagnes, ca. € 720 · max. € 30 per dag · 1 dec t/m 31 dec", "Plan goedkeuren", "Niet nu",
                     "Vandaag", "Sinterklaasblend is binnen", "Er wacht nog 1 post in de app.", "Alle tijden in lokale tijd (Amsterdam)."):
            self.assertIn(want, h, want)
        self.assertNotIn("wondermiddel", h, "a compliance-held post never gets a button")
        self.assertNotIn("Owner only", h, "an owner card never reaches the client")
        self.assertIn('<html lang="nl"', html)
        self.assertIn("€" + NBSP + "18,40", html, "the price never wraps")
        # the text part says the same
        self.assertIn("Goedkeuren:", text)
        self.assertIn("Plan goedkeuren:", text)
        self.assertIn("4 aanvragen · € 4,60 per aanvraag · 7-daags gemiddelde 2,8", plain(text))

    def test_english_unless_the_client_chose(self):
        d = ap.load()
        ap.brand(d, "koffie").pop("comms_lang")                    # a Dutch café that never picked a language
        ap.save(d)
        m, (subj, html, text) = self.render("koffie")
        self.assertEqual(plain(subj), "Morning report Thu 5 Nov · Grachten Koffie · 3 to approve")
        self.assertTrue(plain(m["summary"]).startswith("Good morning. Yesterday: €18.40 on ads, 4 enquiries."), m["summary"])
        self.assertIn('<html lang="en"', html)
        self.assertIn("Zo zetten wij een flat white", html, "its posts are still Dutch")
        self.assertIn("1,240 reached · 32 clicks", html)

    def test_design_language_of_the_digest(self):
        _, (subj, html, text) = self.render("koffie")
        self.assertIn("max-width:600px", html)
        self.assertIn("prefers-color-scheme:dark", html)
        self.assertIn(".o-bar-hi{background:#4461F5!important}", html, "the chart follows dark mode")
        self.assertIn("[data-ogsc]", html)
        self.assertNotRegex(html, r"(?i)<script|@import|fonts\.googleapis|<link ", "no script, no web font")
        self.assertNotRegex(html, r'<img[^>]+(width="1"|height="1")', "no tracking pixel")
        for src in re.findall(r'<img[^>]+src="([^"]+)"', html):
            self.assertTrue(src.startswith("https://"), src)
        for href in re.findall(r'href="([^"]+)"', html):
            self.assertTrue(href.startswith("https://"), href)

    def test_paid_section_only_when_entitled(self):
        m = model("spree")                                        # content plan: organic only
        self.assertIsNone(m["paid"])
        _, (_, html, _) = self.render("spree")
        self.assertNotIn("Ausgegeben", html)
        self.assertNotIn("Anzeigen", re.sub(r"<[^>]+>", " ", html).replace("Meta-Anzeigen", ""))
        m = model("heating")                                      # free trial: planned for preview, nothing spent
        self.assertEqual(m["paid"]["state"], "trial")
        _, (_, html, _) = self.render("heating")
        self.assertIn("Your paid ads are planned for preview. They start once you choose a plan; nothing is spent during your trial.", html)
        self.assertNotIn("Spent", html)
        m = model("tele")                                         # starter, no ad account connected
        self.assertEqual(m["paid"]["state"], "not_connected")
        (TMP / "secrets" / "meta-tele.json").write_text("{}")     # connected, but today's numbers are not in yet
        self.assertEqual(model("tele")["paid"]["state"], "pending")
        self.assertIn("De advertentiecijfers van gisteren zijn er nog niet", otto_report.telegram_text(model("tele"), "https://x/"))

    def test_idle_paid_day_is_one_honest_line(self):
        d = ap.load()
        e = d["ads"]["koffie"]["daily"]["2026-11-05"]
        e["meta"]["yesterday"].update(spend=0, results=0, results_by_type={})
        for r in e["meta"]["campaigns"]:
            r.update(spend=0, results=0)
        ap.save(d)
        m = model("koffie")
        self.assertEqual(m["paid"]["state"], "idle")
        _, (_, html, _) = self.render("koffie")
        self.assertIn("Gisteren liepen er geen advertentiecampagnes.", html)
        self.assertNotIn("Uitgegeven", html, "no zero tiles")

    def test_new_client_empty_states(self):
        m, (subj, html, text) = self.render("nieuw")
        self.assertEqual((m["yday"], m["organic"], m["ever"]), ([], None, False))
        self.assertIn("Goedemorgen. Je eerste posts komen eraan.", m["summary"])
        h = plain(html)
        self.assertIn("Je eerste post staat klaar voor do 5 nov om 16:00: keur hem hieronder goed", h)
        self.assertNotIn('class="o-ink o-kpi"', html, "no number tiles without numbers")
        self.assertNotRegex(re.sub(r"<[^>]+>", " ", h), r"(?<![\d.,:])0 (bereikt|klikken|aanvragen)", "no invented zeros")
        self.assertIn("Koppel Instagram en Facebook voor Bakkerij Nieuw", h, "the engine's card in the client's language")
        self.assertIn("16:00", h)
        self.assertIn("wacht op je akkoord", h, "today's post that still waits says so")
        # nothing at all waiting: one line, in the subject too
        d = ap.load()
        for q in d["posts"]:
            if q["brand"] == "nieuw":
                q["status"] = "approved"
        for r in d["recommendations"]:
            if r["brand"] == "nieuw":
                r["status"] = "done"
        ap.save(d)
        m, (subj, html, _) = self.render("nieuw")
        self.assertTrue(subj.endswith("· niets te doen"), subj)
        self.assertIn("Vandaag hoef je niets te doen.", m["summary"])
        self.assertEqual(html.count("Vandaag hoef je niets te doen."), 3, "preheader, summary and the one-line card, nothing more")
        self.assertIn("Je eerste post gaat online op do 5 nov om 16:00", plain(html))

    def test_quiet_day_for_an_existing_client(self):
        d = ap.load()
        for q in d["posts"]:
            if q["id"] == "sp-001":
                q["published_at"] = "2026-10-20T09:00:00Z"
                q["slot"] = "2026-10-20T10:00"
        ap.save(d)
        m, (_, html, _) = self.render("spree")
        self.assertIn("Gestern ging nichts online.", m["summary"])
        self.assertIn("Für heute ist nichts geplant.", html)

    def test_post_without_numbers_and_a_drop(self):
        rows = [{"date": f"2026-10-{d:02d}", "metrics": {"spree": {"reach": 1000}}} for d in range(27, 32)]
        rows.append({"date": "2026-11-05", "metrics": {"spree": {"reach": 400}}})
        otto_watch.HIST.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        m, (_, html, _) = self.render("spree")
        self.assertEqual(m["yday"][0]["numbers"], None)
        self.assertIn("Die Zahlen folgen morgen in Ihrem Bericht.", html)
        self.assertIn("Achtung: Reichweite auf 400 gefallen (7-Tage-Schnitt 1.000).", html)


# ============================================================================================
# the links inside work, once per day, the catch-up runs find nothing left
# ============================================================================================

class SendTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_sent_once_with_working_links(self):
        r = send("koffie")
        self.assertEqual((r["email"]["emails"], r["email"]["posts"], r["failed"]), (1, 2, False), quiet.last)
        (f,) = outbox()
        msg, text, html = parse(f)
        self.assertEqual(msg["To"], EVA)
        self.assertEqual(msg["X-Otto-Kind"], "report")
        self.assertTrue(plain(msg["Subject"]).startswith("Ochtendrapport do 5 nov · Grachten Koffie"))
        approve = re.search(r"^Goedkeuren:\s+(\S+)", text, re.M).group(1)
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(approve).query)["t"][0]
        p, _ = otto_email.read_token(token, NOW)
        self.assertEqual((p["b"], p["k"], p["i"], p["a"]), ("koffie", "post", "ko-020", "approve"))
        # one tap: GET only shows (in Dutch), POST acts, a second POST is refused
        real = datetime.now(timezone.utc)
        code, page, _, _ = otto_email.http_act("GET", token, now=NOW + timedelta(minutes=2))
        self.assertEqual(code, 200)
        self.assertIn("Deze post goedkeuren?", page)
        self.assertIn(">Post goedkeuren</button>", page)
        self.assertEqual(ap.post(ap.load(), "ko-020")["status"], "pending_approval")
        nonce = re.search(r'name="f" value="([^"]+)"', page).group(1)
        code, page, _, line = otto_email.http_act("POST", token, nonce, now=NOW + timedelta(minutes=3))
        self.assertEqual(code, 200, page)
        self.assertIn("Goedgekeurd", page)
        self.assertIn("De post gaat online op vr 6 nov · 09:00.", page)
        self.assertEqual((ap.post(ap.load(), "ko-020")["status"], ap.post(ap.load(), "ko-020")["approved_via"]), ("approved", "email"))
        code, page, _, _ = otto_email.http_act("POST", token, nonce, now=NOW + timedelta(minutes=4))
        self.assertEqual(code, 409)
        self.assertIn("Deze link is al gebruikt", page)
        self.assertIn("Goedgekeurd op", page)
        self.assertLess(real.year, 2100)
        # the plan card's link approves the plan
        plan = re.search(r"^Plan goedkeuren:\s+(\S+)", text, re.M).group(1)
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(plan).query)["t"][0]
        code, page, _, _ = otto_email.http_act("GET", token, now=NOW + timedelta(minutes=5))
        self.assertIn("Advertentieplan voor december goedkeuren?", page)
        nonce = re.search(r'name="f" value="([^"]+)"', page).group(1)
        code, page, _, line = quiet(otto_email.http_act, "POST", token, nonce, now=NOW + timedelta(minutes=6))
        self.assertEqual(code, 200, page)
        self.assertIn("2 campagnes goedgekeurd voor december.", page)
        self.assertEqual({c["status"] for c in ap.load()["campaigns"] if c["plan"] == "2026-12"}, {"approved"})

    def test_once_per_local_day_and_force(self):
        send("koffie")
        self.assertEqual(len(outbox()), 1)
        r = send("koffie", now=NOW + timedelta(hours=2))
        self.assertEqual(r["email"]["skipped"], "already sent today (2026-11-05)")
        self.assertEqual(len(outbox()), 1)
        self.assertEqual(otto_report.last("koffie", "email")["day"], "2026-11-05")
        send("koffie", now=NOW + timedelta(hours=2), force=True)
        self.assertEqual(len(outbox()), 2, "--force sends again")
        send("koffie", now=NOW + timedelta(days=1))
        self.assertEqual(len(outbox()), 3, "the next local day")

    def test_a_running_send_holds_the_day(self):
        ok, why = otto_report.claim("koffie", "email", "2026-11-05", now=NOW)
        self.assertTrue(ok)
        r = send("koffie")
        self.assertEqual(r["email"]["skipped"], "being sent by another run")
        self.assertEqual(outbox(), [])
        otto_report.release("koffie", "email")
        self.assertEqual(send("koffie")["email"]["emails"], 1)

    def test_the_catch_up_runs_find_nothing_left(self):
        send("koffie")
        d = ap.load()
        self.assertTrue(all(ap.post(d, i).get("email_sent_at") for i in ("ko-020", "ko-021")))
        self.assertFalse(ap.post(d, "ko-022").get("email_sent_at"))
        self.assertIn("wondermiddel", ap.post(d, "ko-022")["compliance_block"]["rules"], "held, as the digest holds it")
        self.assertTrue(ap.rec(d, "rec-001").get("email_sent_at"), "the plan card went out with the report")
        self.assertFalse(ap.rec(d, "rec-002").get("email_sent_at"))
        self.assertEqual(quiet(otto_email.send_cards, "koffie", now=NOW + timedelta(minutes=25))["emails"], 0, "08:00: nothing new")
        self.assertEqual(quiet(otto_email.send_recs, "koffie", now=NOW + timedelta(hours=11))["emails"], 0, "18:30: nothing new")
        self.assertEqual(len(outbox()), 1, "one e-mail this morning")

    def test_a_failed_send_releases_the_day_and_the_posts(self):
        saved = otto_email.deliver

        def boom(*a, **kw):
            raise otto_email.SendError("421 try later")
        otto_email.deliver = boom
        try:
            r = send("koffie")
        finally:
            otto_email.deliver = saved
        self.assertTrue(r["failed"])
        self.assertIsNone((otto_report.last("koffie", "email") or {}).get("day"))
        self.assertFalse(ap.post(ap.load(), "ko-020").get("email_sent_at"), "the posts wait for the retry")
        self.assertEqual(send("koffie")["email"]["emails"], 1, "the retry sends")

    def test_fallback_to_the_plain_digest(self):
        saved = otto_email.render_report
        otto_email.render_report = lambda *a, **kw: 1 / 0
        try:
            r = send("koffie")
        finally:
            otto_email.render_report = saved
        self.assertTrue(r["failed"], "the job fails, so the owner is alerted")
        (f,) = outbox()
        msg, _, _ = parse(f)
        self.assertEqual(msg["X-Otto-Kind"], "digest", "the approvals did not wait a day")
        self.assertIn("om goed te keuren", msg["Subject"])

    def test_nobody_to_mail_fails_loudly(self):
        d = ap.load()
        ap.brand(d, "koffie")["members"] = ["@koffie.example"]
        ap.save(d)
        self.assertTrue(send("koffie")["failed"])
        self.assertIn("nobody to send to", otto_email.read_state()["brands"]["koffie"]["error"]["why"])

    def test_retention_strips_the_ledger(self):
        import otto_retention
        send("koffie")
        self.assertTrue(otto_report.last("koffie"))
        otto_retention._strip_state_files("koffie")
        self.assertEqual(otto_report.last("koffie"), {}, "the 90-day deletion reaches the report ledger too")

    def test_console_health_shows_the_last_report(self):
        send("koffie")
        h = otto_email.brand_health(ap.brand(ap.load(), "koffie"), otto_email.health())
        self.assertEqual((h["last_report"]["emails"], h["last_report"]["lang"]), (1, "nl"))


class TelegramTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_report_then_the_cards_once(self):
        r = send("tele")
        self.assertTrue(r["telegram"]["sent"], quiet.last)
        reports = [x for x in TG if x[0] == "report"]
        self.assertEqual(len(reports), 1)
        text = reports[0][1]
        self.assertTrue(text.startswith("Ochtendrapport · Tele Bikes\ndonderdag 5 november · 07:35"), text)
        self.assertIn("1 post: tik op ✅ Goedkeuren op de kaart", text)
        cards = [x for x in TG if x[0] in ("sendPhoto", "sendMessage")]
        self.assertEqual(len(cards), 1, "the card follows the report")
        kb = cards[0][1]["reply_markup"]["inline_keyboard"]
        self.assertEqual(kb[0][0]["text"], "✅ Goedkeuren")
        self.assertTrue(ap.post(ap.load(), "te-001").get("tg_message_id"), "the 08:00 cards run has nothing left")
        TG.clear()
        self.assertEqual(send("tele")["telegram"]["skipped"], "already sent today (2026-11-05)")
        self.assertEqual(TG, [])
        self.assertEqual(outbox(), [], "a Telegram brand gets no e-mail")

    def test_both_channels_get_both(self):
        r = send("both")
        self.assertEqual((r["email"]["emails"], r["telegram"]["sent"]), (1, True))
        self.assertEqual(len([x for x in TG if x[0] == "report"]), 1)
        self.assertTrue(plain(parse(outbox()[0])[0]["Subject"]).startswith("Morning report Thu 5 Nov · Both Bakes"))

    def test_watch_report_by_hand_sends_the_same_report(self):
        sent = quiet(otto_watch.report, "tele")
        self.assertEqual(sent, 1)
        self.assertIn("Ochtendrapport · Tele Bikes", [x for x in TG if x[0] == "report"][0][1])
        self.assertTrue(otto_watch.HIST.exists(), "the snapshot is taken too")


class RefreshTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_pulls_missing_paid_numbers_and_yesterdays_post_numbers(self):
        import otto_ads, otto_insights, otto_publish
        d = ap.load()
        d["ads"]["koffie"]["daily"].pop("2026-11-05")
        ap.save(d)
        calls = []
        saved = (otto_ads.report, otto_ads.meta_creds, otto_publish.creds, otto_insights.pull_post)
        otto_ads.meta_creds = lambda bid: {"ad_account_id": "act_1"}
        otto_ads.report = lambda bid=None, days=7, dry=False, send=True: calls.append(("ads", bid, send))
        otto_publish.creds = lambda bid: {"access_token": "x"}
        otto_insights.pull_post = lambda p, c: calls.append(("post", p["id"])) or {"reach": 99, "clicks": 3}
        try:
            quiet(otto_report.refresh, "koffie", NOW)
        finally:
            otto_ads.report, otto_ads.meta_creds, otto_publish.creds, otto_insights.pull_post = saved
        self.assertIn(("ads", "koffie", False), calls, "the paid numbers are pulled without a second Telegram message")
        self.assertEqual(sorted(c[1] for c in calls if c[0] == "post"), ["ko-001", "ko-002", "ko-003"])
        m = ap.post(ap.load(), "ko-003")["metrics"]
        self.assertEqual((m["reach"], m["clicks"]), (99, 3))
        self.assertTrue(m["pulled_at"])
        self.assertEqual(ap.post(ap.load(), "ko-001")["metrics"]["saves"], 12, "older numbers are kept, new ones merged")

    def test_no_credentials_no_network(self):
        import otto_insights
        saved = otto_insights.pull_post
        otto_insights.pull_post = lambda p, c: self.fail("no Graph call without credentials")
        try:
            quiet(otto_report.refresh, "spree", NOW)
        finally:
            otto_insights.pull_post = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
