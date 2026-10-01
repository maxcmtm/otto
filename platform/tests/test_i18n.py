#!/usr/bin/env python3
"""Client-facing language (otto_i18n): catalog completeness (every English key in Dutch and German, the same placeholders,
plural forms, both German registers, nothing left untranslated), locale formatting of dates, numbers, money and percent, and
the rule: everything the client receives is ENGLISH unless the brand chose Dutch or German (brands[].comms_lang — set in
onboarding, the app's Settings or the owner console, validated everywhere), never inferred from the language its posts are
written in. With comms_lang nl a brand gets Dutch subjects and bodies across the approval digest, the morning report, the
paid-plan and recommendation e-mails, the trial reminders, the one-tap pages and the Telegram cards and alerts; with de,
German with Sie / du. Stdlib unittest, no network.

  cd platform && python3 tests/test_i18n.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, os, re, shutil, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-i18n-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public_assets"),
       "OTTO_PUBLIC_BASE": "https://otto.example/", "OTTO_OUTBOX": str(TMP / "outbox"),
       "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"), "OTTO_REPORT_STATE": str(TMP / ".report-state.json")}
CLEAR = ("OTTO_DOMAIN", "OTTO_APP_URL", "OTTO_EMAIL_BASE", "OTTO_ADMIN_USERS", "OTTO_PLANS", "TELEGRAM_BOT_TOKEN",
         "OTTO_OWNER_CHAT_ID", "OTTO_TZ")
NOW = datetime(2026, 11, 5, 6, 35, tzinfo=timezone.utc)            # Thu 5 Nov 2026, 07:35 in Amsterdam / Berlin
THU = datetime(2026, 11, 5, 7, 35)
NBSP = " "
CFG = {"link_secret": "i" * 48, "app_url": "https://app.otto.example/", "action_base": "https://otto.example"}


def seed():
    post = lambda pid, brand, slot, **kw: dict({"id": pid, "brand": brand, "pillar": "P", "platform": "ig", "hook": f"Hook {pid}",
                                                "status": "pending_approval", "slot": slot}, **kw)
    brand = lambda bid, name, lang, tz="Europe/Amsterdam", **kw: dict({"id": bid, "name": name, "url": f"{bid}.example",
                                                                       "lang": lang, "tz": tz, "status": "active", "plan": "growth",
                                                                       "approvals": "email", "members": [f"o@{bid}.example"]}, **kw)
    return {"brands": [brand("nl", "Bakkerij Noord", "NL", comms_lang="nl"), brand("de", "Praxis Spree", "DE", "Europe/Berlin", comms_lang="de"),
                       brand("du", "Spree Surf", "DE", "Europe/Berlin", address="informal", comms_lang="de"),
                       brand("en", "Galway Heating", "EN", "Europe/Dublin"), brand("fr", "Café Lumière", "FR", "Europe/Paris"),
                       brand("tg", "Fiets Noord", "NL", approvals="telegram", comms_lang="nl"),
                       brand("nlx", "Kaasmakerij Oost", "NL")],                  # a Dutch shop that never chose: English
            "posts": [post("nl-1", "nl", "2026-11-06T09:00", caption="Zuurdesem, 36 uur gerezen.", why="Brood doet het goed"),
                      post("nl-2", "nl", "2026-11-03T09:00", status="published", published_at="2026-11-04T08:00:00Z"),
                      post("de-1", "de", "2026-11-06T09:00"), post("du-1", "du", "2026-11-06T09:00"),
                      post("en-1", "en", "2026-11-06T09:00"), post("fr-1", "fr", "2026-11-06T09:00"),
                      post("nlx-1", "nlx", "2026-11-06T09:00", hook="Jonge kaas, net van de boerderij"),
                      post("tg-1", "tg", "2026-11-06T09:00", platform="fb", format="carousel")],
            "recommendations": [
                {"id": "rec-1", "priority": "P1", "title": "Approve the 2026-12 paid plan: 1 campaigns, ≈€310", "why": "Evergreen.",
                 "impact": "Paid", "cta": "Approve plan", "status": "proposed", "brand": "nl", "source": "otto_ads",
                 "action": "approve_plan", "plan": "2026-12"},
                {"id": "rec-2", "priority": "P0", "title": "Double down on “Brood” next week", "why": "Top post …", "impact": "Next batch",
                 "cta": "Approve", "status": "proposed", "brand": "nl", "source": "otto_insights",
                 "i18n": {"key": "rec.double_down", "args": {"pillar": "Brood", "hook": "Zuurdesem", "reach": 1240, "saves": 12, "k": 3}}},
                {"id": "rec-3", "priority": "P1", "title": "Plain English card", "why": "Kept as written.", "impact": "",
                 "cta": "Ok", "status": "proposed", "brand": "nl"}],
            "campaigns": [{"id": "cp-1", "brand": "nl", "plan": "2026-12", "status": "draft", "network": "meta", "name": "December",
                           "daily_budget": 10, "start": "2026-12-01", "end": "2026-12-31", "currency": "€", "currency_code": "EUR"}],
            "users": [{"id": "u1", "email": "o@nl.example", "status": "trial", "brands": ["nl"],
                       "trial_started_at": "2026-10-30T10:00:00Z", "trial_ends_at": "2026-11-06T10:00:00Z"}],
            "connections": [], "taste_log": []}


def reset():
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    for d in ("brands", "secrets", "outbox", "public_assets"):
        shutil.rmtree(TMP / d, ignore_errors=True)
    (TMP / "brands").mkdir()
    (TMP / "secrets").mkdir()
    (TMP / "secrets" / "email.json").write_text(json.dumps(CFG))
    (TMP / "data.json").write_text(json.dumps(seed(), ensure_ascii=False, indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    otto_i18n._voice_cache.clear()
    otto_email._rl.clear()
    otto_email._rl_global[:] = [0, 0]


def plain(s):
    return s.replace(NBSP, " ")


def visible(html):
    """The words a reader sees: no tags, no style block, no URLs."""
    html = re.sub(r"(?s)<style>.*?</style>|<title>.*?</title>", " ", html)
    return plain(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


_SAVED = {}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_i18n, otto_email, otto_report, otto_trial, otto_telegram, otto_watch
    import ap, otto_i18n, otto_email, otto_report, otto_trial, otto_telegram, otto_watch     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_watch.HIST, otto_watch.STATE)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_watch.HIST, otto_watch.STATE = TMP / "metrics_history.jsonl", TMP / ".watch-state.json"
    reset()


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS, otto_watch.HIST, otto_watch.STATE = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def brand(bid):
    return ap.brand(ap.load(), bid)


def tr(bid):
    return otto_i18n.Tr.for_brand(brand(bid))


# ============================================================================================
# the catalogs
# ============================================================================================

class CatalogTest(unittest.TestCase):
    def test_complete(self):
        self.assertEqual(otto_i18n.problems(), [])
        for lang in ("nl", "de"):
            missing = sorted(set(otto_i18n.EN) - set(otto_i18n.CATALOGS[lang]))
            self.assertEqual(missing, [], f"{lang} misses keys")
            extra = sorted(set(otto_i18n.CATALOGS[lang]) - set(otto_i18n.EN))
            self.assertEqual(extra, [], f"{lang} has keys English does not")

    def test_plurals_and_registers(self):
        for key, ev in otto_i18n.EN.items():
            if isinstance(ev, dict):
                for lang in ("nl", "de"):
                    for reg in ("formal", "informal"):
                        t = otto_i18n.Tr(lang, reg)
                        one, many = t(key, n=1, **{f: "x" for f in otto_i18n.fields(ev["other"]) - {"n"}}), \
                            t(key, n=3, **{f: "x" for f in otto_i18n.fields(ev["other"]) - {"n"}})
                        self.assertNotEqual(one, many, f"{lang} {key}: one and other read the same")
                        self.assertIn("3", many, f"{lang} {key}")
        de = {k: v for k, v in otto_i18n.DE.items() if isinstance(v, dict) and ("Sie" in v or "du" in v)}
        self.assertGreater(len(de), 30, "German addresses the reader in many places")
        for k, v in de.items():
            sie = json.dumps(v["Sie"], ensure_ascii=False)
            du = json.dumps(v["du"], ensure_ascii=False)
            self.assertNotEqual(sie, du, k)
            self.assertNotRegex(du, r"\b(Sie|Ihnen|Ihr|Ihre|Ihrem|Ihren|Ihrer)\b", f"{k}: Sie in the du form")
            self.assertNotRegex(sie, r"\b(du|dich|dir|dein|deine|deinem|deinen|deiner)\b", f"{k}: du in the Sie form")
        self.assertFalse(any(isinstance(v, dict) and ("Sie" in v or "du" in v) for v in otto_i18n.NL.values()), "Dutch is je")

    def test_nothing_left_in_english(self):
        same = []
        allowed = {"fmt.reel", "fmt.story", "fmt.video", "btn.open_otto", "tg.open", "tg.later", "kpi.conversions",
                   "res.conversions", "noun.post", "report.sub.posts", "cost.conversions", "tz.label", "metric.followers"}
        for lang in ("nl", "de"):
            for key, ev in otto_i18n.EN.items():
                if key in allowed:
                    continue
                if json.dumps(otto_i18n.CATALOGS[lang][key], ensure_ascii=False) == json.dumps(ev, ensure_ascii=False) \
                        and len(re.findall(r"[A-Za-z]{3,}", json.dumps(ev))) >= 2:
                    same.append(f"{lang}:{key}")
        self.assertEqual(same, [], "untranslated strings")
        nl = " ".join(json.dumps(v, ensure_ascii=False) for v in otto_i18n.NL.values())
        self.assertNotRegex(nl, r"\b(u|uw)\b", "Dutch SMB owners are addressed with je, never u")


# ============================================================================================
# formatting per locale
# ============================================================================================

class FormatTest(unittest.TestCase):
    def test_dates(self):
        nl, de, en = otto_i18n.Tr("nl"), otto_i18n.Tr("de"), otto_i18n.Tr("en")
        self.assertEqual(nl.day_time(THU), "do 5 nov · 07:35")
        self.assertEqual(de.day_time(THU), "Do., 5. Nov. · 07:35")
        self.assertEqual(en.day_time(THU), "Thu 5 Nov · 07:35")
        self.assertEqual((nl.long_day(THU), de.long_day(THU), en.long_day(THU)),
                         ("donderdag 5 november", "Donnerstag, 5. November", "Thursday 5 November"))
        self.assertEqual((nl.day_at(THU), de.day_at(THU), en.day_at(THU)),
                         ("do 5 nov om 07:35", "Do., 5. Nov. um 07:35 Uhr", "Thu 5 Nov, 07:35"))
        self.assertEqual((nl.month("2026-03"), de.month("2026-03"), en.month("2026-03")), ("maart", "März", "March"))
        self.assertEqual(de.day(datetime(2026, 5, 1)), "Fr., 1. Mai", "no period after a month written out")
        self.assertEqual((nl.day_month(THU), de.day_month(THU)), ("5 nov", "5. Nov."))
        self.assertEqual([nl.initial(THU + timedelta(days=i)) for i in range(7)], list("DVZZMDW"))

    def test_numbers_money_percent(self):
        nl, de, en = otto_i18n.Tr("nl"), otto_i18n.Tr("de"), otto_i18n.Tr("en")
        self.assertEqual((nl.num(1234.5, 2), de.num(1234.5, 2), en.num(1234.5, 2)), ("1.234,50", "1.234,50", "1,234.50"))
        self.assertEqual(nl.num(12480), "12.480")
        self.assertEqual(plain(nl.money(1234.5, "EUR")), "€ 1.234,50")
        self.assertEqual(plain(de.money(1234.5, "EUR")), "1.234,50 €")
        self.assertEqual(en.money(1234.5, "EUR"), "€1,234.50")
        self.assertEqual(nl.money(1234.5, "EUR"), "€" + NBSP + "1.234,50", "a no-break space: the amount never wraps")
        self.assertEqual((plain(nl.money(20, "EUR")), plain(de.money(20, "€")), en.money(20, "EUR")), ("€ 20", "20 €", "€20"))
        self.assertEqual((en.money(12, "GBP"), plain(de.money(12, "CHF")), plain(nl.money(3.5, "USD"))), ("£12", "12 CHF", "$ 3,50"))
        self.assertEqual((nl.pct(2.4), plain(de.pct(2.4)), en.pct(2.4)), ("2,4%", "2,4 %", "2.4%"))
        self.assertEqual(nl("noun.post", n=1234), "1.234 posts", "the count is formatted too")

    def test_words(self):
        nl, de = otto_i18n.Tr("nl"), otto_i18n.Tr("de")
        self.assertEqual(nl.join(["a", "b", "c"]), "a, b en c")
        self.assertEqual(de.join(["a", "b"]), "a und b")
        self.assertEqual((de.city(ZoneInfo("Europe/Vienna")), nl.city(ZoneInfo("Europe/Brussels")), nl.city(ZoneInfo("Europe/Amsterdam"))),
                         ("Wien", "Brussel", "Amsterdam"))


# ============================================================================================
# which language, which register
# ============================================================================================

class ResolveTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_english_unless_chosen(self):
        lang = lambda **b: otto_i18n.lang_of(dict({"id": "x"}, **b))
        self.assertEqual((lang(), lang(lang="NL"), lang(lang="DE"), lang(countries=["NL"]), lang(tz="Europe/Berlin")),
                         ("en",) * 5, "never inferred from the content language, country or zone")
        (TMP / "brands" / "scanned").mkdir()
        (TMP / "brands" / "scanned" / "scan.json").write_text(json.dumps({"languages": ["nl"]}))
        self.assertEqual(otto_i18n.lang_of({"id": "scanned", "lang": "NL"}), "en", "a Dutch site still gets English")
        self.assertEqual(ap.brand_lang({"id": "scanned", "lang": "NL"}), "nl", "while its posts stay Dutch")
        self.assertEqual((lang(comms_lang="nl"), lang(comms_lang="DE"), lang(comms_lang="en")), ("nl", "de", "en"))
        self.assertEqual((lang(comms_lang="fr"), lang(comms_lang=""), lang(comms_lang=None)), ("en", "en", "en"))
        self.assertEqual(otto_i18n.norm_lang("de_AT"), "de")
        for ok in ("en", "NL", " de "):
            self.assertIn(otto_i18n.normalize_comms_lang(ok), ("en", "nl", "de"))
        for bad in ("fr", "", None, "dutch", ["nl"]):
            with self.assertRaises(ValueError):
                otto_i18n.normalize_comms_lang(bad)

    def test_a_dutch_brand_without_the_setting_gets_english(self):
        cfg = otto_email.safe_config()
        b = brand("nlx")
        it = otto_email.digest_item(b, ap.post(ap.load(), "nlx-1"), b["members"][0], cfg, NOW, otto_email.link_secrets(cfg)[0], False)
        s, h, t = otto_email.render_digest(b, [it])
        self.assertEqual(s, "1 post to approve for Kaasmakerij Oost · from Fri 6 Nov")
        self.assertIn("Jonge kaas, net van de boerderij", h, "the post itself stays Dutch")
        self.assertIn('<html lang="en"', h)
        d = ap.load()
        m = otto_report.model(d, ap.brand(d, "nlx"), NOW)
        self.assertTrue(otto_report.subject(m).startswith("Morning report Thu 5 Nov · Kaasmakerij Oost"))
        ap_set = lambda v: otto_i18n.set_comms_lang("nlx", v, via="test")
        self.assertEqual(ap_set("nl"), ("en", "nl"))
        s, _, _ = otto_email.render_digest(brand("nlx"), [it])
        self.assertTrue(s.startswith("1 post om goed te keuren voor Kaasmakerij Oost"), s)
        self.assertEqual(brand("nlx")["comms_lang_set"]["via"], "test")

    def test_german_register(self):
        self.assertEqual(tr("de").register, "formal", "Sie is the B2B default")
        self.assertEqual(tr("du").register, "informal", "brands[].address")
        (TMP / "brands" / "surf").mkdir()
        (TMP / "brands" / "surf" / "scan.json").write_text(json.dumps({"languages": ["de"], "text_sample":
            "Hol dir dein Board! Du lernst bei uns in drei Tagen surfen. Dein Kurs, deine Welle, dein Sommer."}))
        self.assertEqual(otto_i18n.Tr.for_brand({"id": "surf", "lang": "DE", "comms_lang": "de"}).register, "informal", "the brand's own voice says du")
        self.assertEqual(otto_i18n.Tr.for_brand({"id": "surf", "comms_lang": "de", "address": "formal"}).register, "formal",
                         "the setting wins over the voice")
        (TMP / "brands" / "praxis").mkdir()
        (TMP / "brands" / "praxis" / "scan.json").write_text(json.dumps({"languages": ["de"], "text_sample":
            "Termine bekommen Sie online. Wir erklären Ihnen jeden Schritt. Ihre Zähne in guten Händen."}))
        self.assertEqual(otto_i18n.Tr.for_brand({"id": "praxis", "comms_lang": "de"}).register, "formal")
        self.assertIn("Ihre Freigabe", otto_i18n.Tr("de", "formal")("digest.title", n=2))
        self.assertIn("deine Freigabe", otto_i18n.Tr("de", "informal")("digest.title", n=2))

    def test_address_cli(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            otto_i18n.main(["address", "de", "du"])
        self.assertIn("du", out.getvalue())
        self.assertEqual(brand("de")["address"], "informal")
        with contextlib.redirect_stdout(io.StringIO()):
            otto_i18n.main(["address", "de", "auto"])
        self.assertNotIn("address", brand("de"))

    def test_lang_cli(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            otto_i18n.main(["lang", "en", "de"])
        self.assertIn("Deutsch", out.getvalue())
        self.assertEqual(brand("en")["comms_lang"], "de")
        with self.assertRaises(SystemExit):
            otto_i18n.main(["lang", "en", "fr"])


class SettingTest(unittest.TestCase):
    """Where comms_lang is set: the app's Settings (tenant-scoped), onboarding (validated), the owner console."""

    def setUp(self):
        reset()

    def test_app_settings_tenant_scoped_and_validated(self):
        import otto_api
        saved = otto_api.LOG
        otto_api.LOG = TMP / "actions.log"
        try:
            d = otto_api.apply_brand("nlx", {"comms_lang": "nl"}, bids={"nlx"})
            self.assertEqual(ap.brand(d, "nlx")["comms_lang"], "nl")
            self.assertEqual(ap.brand(d, "nlx")["comms_lang_set"]["via"], "dashboard")
            self.assertIn("dashboard brand nlx comms_lang en -> nl", (TMP / "actions.log").read_text())
            with self.assertRaises(KeyError):
                otto_api.apply_brand("nl", {"comms_lang": "de"}, bids={"nlx"})        # another tenant's brand
            self.assertEqual(brand("nl")["comms_lang"], "nl")
            for bad in ("fr", "", None, 7):
                with self.assertRaises(ValueError):
                    otto_api.apply_brand("nlx", {"comms_lang": bad}, bids={"nlx"})
            with self.assertRaises(ValueError):                                        # nothing half-written
                otto_api.apply_brand("nlx", {"comms_lang": "de", "approvals": "fax"}, bids={"nlx"})
            self.assertEqual((brand("nlx")["comms_lang"], brand("nlx")["approvals"]), ("nl", "email"))
            d = otto_api.apply_brand("nlx", {"comms_lang": "de", "approvals": "app"}, bids={"nlx"})
            self.assertEqual((ap.brand(d, "nlx")["comms_lang"], ap.brand(d, "nlx")["approvals"]), ("de", "app"))
            view = otto_api.client_view(ap.load(), {"nlx"})
            self.assertEqual(view["brands"][0]["comms_lang"], "de", "the app's Settings shows the current choice")
        finally:
            otto_api.LOG = saved

    def test_onboarding_answer(self):
        import otto_onboard
        self.assertEqual(otto_onboard.clean_answers({})["comms_lang"], "en", "English preselected")
        self.assertEqual(otto_onboard.clean_answers({"comms_lang": "NL"})["comms_lang"], "nl")
        for bad in ("fr", "nederlands", ["nl"]):
            with self.assertRaises(ValueError):
                otto_onboard.clean_answers({"comms_lang": bad})

    def test_owner_console(self):
        import otto_admin
        out = otto_admin.act({"action": "comms_lang", "brand": "en", "lang": "nl"}, "max@otto.example")
        self.assertTrue(out["ok"])
        self.assertEqual(brand("en")["comms_lang"], "nl")
        self.assertEqual(brand("en")["comms_lang_set"]["via"], "admin")
        with self.assertRaises(ValueError):
            otto_admin.act({"action": "comms_lang", "brand": "en", "lang": "es"}, "max@otto.example")
        with self.assertRaises(KeyError):
            otto_admin.act({"action": "comms_lang", "brand": "nope", "lang": "de"}, "max@otto.example")


# ============================================================================================
# a Dutch brand gets Dutch everywhere; an unknown language gets English
# ============================================================================================

class DutchEverywhereTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.cfg = otto_email.safe_config()
        self.secret = otto_email.link_secrets(self.cfg)[0]

    def digest(self, bid):
        b = brand(bid)
        items = [otto_email.digest_item(b, p, b["members"][0], self.cfg, NOW, self.secret, False)
                 for p in ap.load()["posts"] if p["brand"] == bid and p["status"] == "pending_approval"]
        return otto_email.render_digest(b, items, 2)

    def report(self, bid):
        d = ap.load()
        b = ap.brand(d, bid)
        return otto_email.render_report(b, otto_report.model(d, b, NOW), b["members"][0], self.cfg, NOW, self.secret, verify=False)

    def test_digest(self):
        s, h, t = self.digest("nl")
        self.assertEqual(plain(s), "1 post om goed te keuren voor Bakkerij Noord · vanaf vr 6 nov")
        for want in ("1 post wacht op je akkoord", "<b>Goedkeuren</b>", "Waarom deze post: Brood doet het goed", "vr 6 nov · 09:00",
                     "Alles bekijken in de app", "Er wachten nog 2 posts in de app.", "Instellingen", "Alle tijden in lokale tijd (Amsterdam)."):
            self.assertIn(want, plain(h), want)
        self.assertIn('<html lang="nl"', h)
        self.assertRegex(t, r"(?m)^Goedkeuren: https://otto\.example/otto-email/act\?t=")
        self.assertRegex(t, r"(?m)^Overslaan:  https://")

    def test_report(self):
        s, h, t = self.report("nl")
        self.assertTrue(plain(s).startswith("Ochtendrapport do 5 nov · Bakkerij Noord"), s)
        v = visible(h)
        for english in ("Approve", "Skip", "Change", "Yesterday", "Waiting for you", "Today", "Settings", "Morning report",
                        "Good morning", "Nothing", "posts are", "per day", "Spent", "Open in"):
            self.assertNotIn(english, v, f"English left in the Dutch report: {english!r}")
        self.assertIn("Volgende week meer ‘Brood’", v, "the engine's card, filed with an i18n key, reads Dutch")
        self.assertIn("bereik 1.240", v)
        self.assertIn("Plain English card", v, "a card without a key is shown as written (honest, not machine-translated)")

    def test_plan_and_recommendation_mails(self):
        b = brand("nl")
        r = ap.rec(ap.load(), "rec-1")
        camps = [c for c in ap.load()["campaigns"] if c["plan"] == "2026-12"]
        s, h, t = otto_email.render_plan(b, r, camps, otto_email.plan_links(b, r, "o@nl.example", self.cfg, NOW, self.secret))
        self.assertEqual(s, "Advertentieplan voor december goedkeuren · Bakkerij Noord")
        self.assertIn("1 campagne, ca. € 310.", plain(h))
        self.assertIn("€ 10 per dag", plain(h))
        self.assertIn("1 dec t/m 31 dec", plain(h))
        self.assertRegex(t, r"(?m)^Plan goedkeuren: https://")
        self.assertNotIn("Evergreen.", h, "the engine's English reasoning is not mixed into a Dutch mail")
        rows = [(ap.rec(ap.load(), i), otto_email.rec_links(b, ap.rec(ap.load(), i), "o@nl.example", self.cfg, NOW, self.secret))
                for i in ("rec-2", "rec-3")]
        s, h, t = otto_email.render_recs(b, rows)
        self.assertEqual(s, "2 aanbevelingen voor Bakkerij Noord")
        self.assertIn("2 beslissingen voor je", h)
        self.assertIn("De voorstellen van je bureau voor deze week.", h)
        self.assertIn("DRINGEND".lower(), h.lower())
        s, _, _ = otto_email.render_recs(b, rows[:1])
        self.assertEqual(s, "Otto raadt aan: Volgende week meer ‘Brood’")

    def test_trial_reminders(self):
        d = ap.load()
        u = d["users"][0]
        subj = {k: otto_trial.render(k, u, d, now)[0] for k, now in
                (("day5", NOW - timedelta(days=1)), ("day7", NOW), ("day8", NOW + timedelta(days=2)))}
        self.assertEqual(subj, {"day5": "Nog 2 dagen in je proefperiode van Otto", "day7": "Je proefperiode van Otto eindigt morgen",
                                "day8": "Je proefperiode van Otto is afgelopen: Bakkerij Noord staat op pauze"})
        s, h, t = otto_trial.render("day5", u, d, NOW - timedelta(days=1))
        self.assertIn("Je gratis proefperiode van Otto eindigt op vr 6 nov om 11:00.", plain(t))
        self.assertIn("Kies je geen plan, dan wordt er niets afgeschreven", t)
        self.assertIn("gaat in zodra de proefperiode afloopt", t, "a chosen plan starts, and is charged, at the trial's end")
        self.assertIn("Kies een plan", h)
        self.assertNotIn("e-mailadres", t, "no e-mail matching any more")
        self.assertIn('<html lang="nl"', h)
        s, h, t = otto_trial.render("day8", u, d, NOW + timedelta(days=2))
        self.assertIn("bewaren we 90 dagen, tot do 4 feb", t)

    def test_one_tap_pages(self):
        tok = otto_email.make_token("nl", "post", "nl-1", "approve", "o@nl.example", now=NOW)
        code, page, csp, _ = otto_email.http_act("GET", tok, now=NOW + timedelta(minutes=1))
        self.assertEqual(code, 200)
        for want in ("Deze post goedkeuren?", ">Post goedkeuren</button>", "Liever openen in de app",
                     "De post gaat op het geplande moment online op Instagram.", "Deze knop werkt één keer. De link verloopt op"):
            self.assertIn(want, page, want)
        self.assertIn('<html lang="nl"', page)
        code, page, _, _ = otto_email.http_act("GET", tok, now=NOW + timedelta(days=4))
        self.assertEqual(code, 410)
        self.assertIn("Deze link is verlopen", page, "an expired link still knows its brand")
        code, page, _, _ = otto_email.http_act("GET", "x" * 20 + ".y")
        self.assertIn("This link doesn&#x27;t work", page, "a link that names no brand: English")
        de = otto_email.make_token("du", "post", "du-1", "skip", "o@du.example", now=NOW)
        code, page, _, _ = otto_email.http_act("GET", de, now=NOW + timedelta(minutes=1))
        self.assertIn("Diesen Beitrag überspringen?", page)
        self.assertIn("Fr., 6. Nov. · 09:00", page)

    def test_telegram_cards_and_alerts(self):
        d = ap.load()
        cap = otto_telegram.card_caption(d, ap.post(d, "tg-1"))
        self.assertIn("vr 6 nov · 09:00", cap)
        kb = otto_telegram.post_keyboard("tg-1", otto_telegram.tr_for(d, "tg"))["inline_keyboard"]
        self.assertEqual([b["text"] for row in kb for b in row], ["✅ Goedkeuren", "❌ Overslaan", "✏️ Wijzigen", "↷ Later"])
        sent = []
        saved = otto_watch.send
        otto_watch.send = lambda text: sent.append(text) or True
        try:
            with ap.transaction() as dd:
                q = ap.post(dd, "tg-1")
                q["slot"] = (datetime.now(timezone.utc) + timedelta(hours=3)).astimezone(ZoneInfo("Europe/Amsterdam")).strftime("%Y-%m-%dT%H:%M")
            with contextlib.redirect_stdout(io.StringIO()):
                otto_watch.watch()
        finally:
            otto_watch.send = saved
        nl = [x for x in sent if "Melding van Otto" in x]
        self.assertTrue(nl, sent)
        self.assertIn("‘Hook tg-1’ staat gepland voor", nl[0])
        self.assertIn("en is nog niet goedgekeurd. Nog 3 uur.", nl[0])

    def test_no_choice_gets_english(self):
        s, h, _ = self.digest("fr")
        self.assertEqual(s, "1 post to approve for Café Lumière · from Fri 6 Nov")
        self.assertIn('<html lang="en"', h)
        s, _, _ = self.report("fr")
        self.assertTrue(s.startswith("Morning report Thu 5 Nov · Café Lumière"), s)
        self.assertIn("Times are Paris time.", self.digest("fr")[1])

    def test_german_sie_and_du_side_by_side(self):
        s1, h1, _ = self.digest("de")
        s2, h2, _ = self.digest("du")
        self.assertEqual(s1, "1 Beitrag zur Freigabe für Praxis Spree · ab Fr., 6. Nov.")
        self.assertIn("Tippen Sie auf <b>Freigeben</b>", h1)
        self.assertIn("Sie erhalten diese E-Mail", h1)
        self.assertIn("Tippe auf <b>Freigeben</b>", h2)
        self.assertIn("Du erhältst diese E-Mail", h2)
        self.assertIn('<html lang="de"', h1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
