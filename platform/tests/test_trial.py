#!/usr/bin/env python3
"""The free trial (otto_trial) end to end through the real API server: a Google sign-up (fake Google, tests/fake_google.py)
onboards its first brand on the 7-day trial; one trial per Google account e-mail and per website domain (and per user);
paid ads are planned and previewed but never launched during the trial (otto_ads, otto_cron); the reminder e-mails on day 5,
day 7 and day 8 go out once each; the trial ends on the hour into the ended plan with the retention clock at the trial's end
and a 402 paywall in the app; the "add a card" offers open Otto's Billing page (Stripe: tests/test_stripe.py pays and
links by the signed checkout reference); a LEGACY Whop membership with the verified e-mail still links itself
(idempotently) and converts the trial; the owner's manual link still works; the console counts it all.

  cd platform && python3 tests/test_trial.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, copy, email, email.policy, io, json, os, shutil, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_google as G                                                        # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="otto-trial-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_SESSIONS": str(TMP / "sessions.json"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"),
       "OTTO_PLANS": str(TMP / "plans.json"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_LEADS": str(TMP / "leads.json"), "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_EXPORTS": str(TMP / "exports"),
       "WHOP_WEBHOOK_SECRET": "ws_trial_test_secret_do_not_use", "OTTO_APP_URL": "https://app.otto.example/"}
CLEAR = ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_DOMAIN", "OTTO_GOOGLE_REDIRECT_URI", "OTTO_FALLBACK",
         "WHOP_API_KEY", "WHOP_COMPANY_ID", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "OTTO_EMAIL_BASE")
PROXIED = {"X-Real-IP": "203.0.113.20"}
STARTER_WHOP, GROWTH_WHOP = "plan_trial_starter", "plan_trial_growth"
ANSWERS = {"goal": "sales", "budget": "300_1000", "approvals": "email"}


def scan_doc(host):
    return {"url": f"https://{host}", "final_url": f"https://{host}/", "scanned_at": "2026-09-29T10:00:00Z", "pages": [f"https://{host}/"],
            "identity": {"title": f"{host.split('.')[0].title()} | Coffee", "description": "Fresh coffee.", "site_name": host.split(".")[0].title(),
                         "og_title": "", "og_image": None},
            "industry": "E-commerce & retail", "industry_candidates": [], "languages": ["en"], "platform": "Shopify",
            "visual": {"palette": [], "neutrals": [], "logo": None, "fonts": [], "theme_color": None}, "socials": {},
            "contact": {"emails": [], "phones": []}, "commerce": {"currency": "EUR", "prices": ["12 €"], "promos": []},
            "trust": [], "quotes": [], "headings": [], "nav": [], "text_sample": ""}


def seed():
    return {"brands": [{"id": "keep", "name": "Keep Cafe", "url": "keepcafe.example", "tz": "UTC", "status": "active",
                        "plan": "starter", "members": ["kim@keepcafe.example"], "pillars": ["A"], "compliance": ""}],
            "posts": [], "recommendations": [], "connections": [], "campaigns": [], "users": []}


_SAVED, S = {}, {}
MODS = ("ap", "otto_api", "otto_auth", "otto_trial", "otto_onboard", "otto_scan", "otto_strategy", "otto_plan", "otto_whop",
        "otto_ads", "otto_cron", "otto_retention", "otto_admin", "otto_email", "otto_publish")
PINS = [("ap", "DATA", "data.json"), ("ap", "HTML", "index.html"), ("ap", "BRANDS", "brands"), ("otto_scan", "BRANDS", "brands"),
        ("otto_strategy", "BRANDS", "brands"), ("otto_plan", "BRANDS", "brands"), ("otto_api", "LOG", "actions.log"),
        ("otto_ads", "BRANDS", "brands"), ("otto_ads", "SECRETS", "secrets"), ("otto_publish", "SECRETS", "secrets"),
        ("otto_publish", "LOG", "publish.log")]


def reset():
    (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
    for f in ("sessions.json", "billing.json", "actions.log"):
        (TMP / f).unlink(missing_ok=True)
    shutil.rmtree(TMP / "outbox", ignore_errors=True)
    for x in (TMP / "brands").iterdir():
        if x.name != "keep":
            shutil.rmtree(x, ignore_errors=True)
    otto_auth._rl.clear()
    otto_auth.PENDING.clear()
    otto_onboard._rl_last.clear()
    otto_onboard._public_creates.clear()
    otto_api._snap_cache.clear()
    for k in CLEAR:
        os.environ.pop(k, None)


def setUpModule():
    for d in ("brands/keep", "secrets", "assets", "outbox"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    plans = json.loads((PLATFORM / "plans.json").read_text())
    plans["plans"]["starter"]["whop_plan_ids"] = [STARTER_WHOP]
    plans["plans"]["growth"]["whop_plan_ids"] = [GROWTH_WHOP]
    plans["plans"]["starter"]["stripe_price_ids"] = {"monthly": "price_trial_starter_m", "yearly": None}
    plans["plans"]["growth"]["stripe_price_ids"] = {"monthly": "price_trial_growth_m", "yearly": "price_trial_growth_y"}
    (TMP / "plans.json").write_text(json.dumps(plans, indent=1))
    (TMP / "secrets" / "stripe.json").write_text(json.dumps({"secret_key": "sk_test_trial_never_called", "publishable_key": "pk_test_trial"}))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    g = globals()
    for m in MODS:
        g[m] = __import__(m)
    _SAVED["pins"] = [(m, a, getattr(g[m], a)) for m, a, _ in PINS]
    for m, a, rel in PINS:
        setattr(g[m], a, TMP / rel)
    S["google"] = G.FakeGoogle()
    (TMP / "secrets" / "google-oauth.json").write_text(json.dumps(S["google"].config()))
    S["graph"] = []
    _SAVED["fakes"] = (otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_whop.SPAWN, otto_ads.notify)
    otto_scan.scan = lambda url, pages=5, page_limit=1_200_000, deadline=None: scan_doc(otto_onboard.host_key(url))
    otto_scan.host_status = lambda url: "ok"
    otto_publish.graph = lambda *a, **kw: S["graph"].append(a) or {"id": "X"}
    otto_whop.SPAWN = lambda args: None
    otto_ads.notify = lambda text: True
    S["srv"] = otto_api.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
    threading.Thread(target=S["srv"].serve_forever, daemon=True).start()
    S["base"] = f"http://127.0.0.1:{S['srv'].server_address[1]}"
    S["origin"] = sorted(otto_api.ALLOWED_ORIGINS)[0]
    reset()


def tearDownModule():
    if "srv" in S:
        S["srv"].shutdown(); S["srv"].server_close()
    if "google" in S:
        S["google"].close()
    if "fakes" in _SAVED:
        otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_whop.SPAWN, otto_ads.notify = _SAVED["fakes"]
    g = globals()
    for m, a, v in _SAVED.get("pins", []):
        setattr(g[m], a, v)
    for k, v in _SAVED.get("env", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        out = fn(*a, **kw)
    quiet.last = buf.getvalue()
    return out


def req(method, path, body=None, sid=None, headers=None):
    h = dict(PROXIED, **(headers or {}))
    if body is not None:
        body = json.dumps(body).encode()
        h.update({"Content-Type": "application/json", "Origin": S["origin"]})
    if sid:
        h["Cookie"] = f"otto_sid={sid}"
    st, msg, raw = G.request(S["base"], method, path, h, body)
    try:
        return st, json.loads(raw) if raw else None
    except ValueError:
        return st, raw.decode(errors="replace")


def signup(email_, sub):
    st, _, sid, _ = quiet(G.sign_in, S["base"], S["google"], email_, sub, headers=PROXIED)
    assert st == 303 and sid, st
    return sid


def onboard(sid, site):
    otto_onboard._rl_last.clear()
    return quiet(req, "POST", "/otto-api/onboard", {"site": site, "answers": ANSWERS}, sid)


def user(email_):
    return otto_trial.user_by_email(ap.load(), email_)


def brand(bid):
    return ap.brand(ap.load(), bid)


def outbox():
    """The outbox in the order the e-mails were written (file names start with a one-second stamp)."""
    d = TMP / "outbox"
    return sorted(d.glob("*.eml"), key=lambda f: (f.stat().st_mtime_ns, f.name)) if d.is_dir() else []


def by_subject(pattern):
    import re
    return [f for f in outbox() if re.search(pattern, subject(f))]


def subject(f):
    return email.message_from_bytes(Path(f).read_bytes(), policy=email.policy.default)["Subject"]


def body_text(f):
    return email.message_from_bytes(Path(f).read_bytes(), policy=email.policy.default).get_body(("plain",)).get_content()


def whop(etype, data, wid):
    body = json.dumps({"type": etype, "data": data}).encode()
    ts = str(int(time.time()))
    sig = otto_whop.sign(os.environ["WHOP_WEBHOOK_SECRET"], wid, ts, body)
    st, msg, raw = G.request(S["base"], "POST", "/otto-api/whop", {"webhook-id": wid, "webhook-timestamp": ts,
                                                                   "webhook-signature": sig, "Content-Type": "application/json"}, body)
    return st, json.loads(raw)


def membership(mid, email_, plan=STARTER_WHOP, status="active"):
    return {"id": mid, "status": status, "plan": {"id": plan}, "user": {"email": email_, "name": "Eva"},
            "created_at": int(time.time()), "renewal_period_end": int(time.time()) + 30 * 86400}


class TrialTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_the_trial_week_is_planned_at_sign_up_and_flagged_for_copy(self):
        """A trial that waits for the 25th shows an empty app for seven days: onboarding plans every month it overlaps."""
        sid, out = self.trial_brand()
        bid = out["brand"]
        b = brand(bid)
        k = b.get("kickoff") or {}
        self.assertTrue(k.get("done") and k.get("copy_needed"), k)
        tz = ap.brand_tz(b)
        start = datetime.now(timezone.utc).astimezone(tz).date()
        end = ap.parse_iso(b["trial"]["ends_at"]).astimezone(tz).date()
        self.assertEqual(k["months"], otto_trial._months(start, end))
        posts = [p for p in ap.load()["posts"] if p["brand"] == bid]
        self.assertTrue(posts, "no post planned for the trial")
        self.assertTrue(all(p["slot"][:10] >= start.isoformat() for p in posts), "a past slot was planned")
        recs = [r for r in ap.load()["recommendations"] if r.get("brand") == bid and r.get("source") == "otto_trial"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].get("audience"), "owner")          # the copy task is the team's, not the client's card
        n = len(posts)
        self.assertEqual(otto_trial.kickoff(bid), [])                  # idempotent: a done kickoff is never redone
        self.assertEqual(len([p for p in ap.load()["posts"] if p["brand"] == bid]), n)
        otto_trial.copy_done(bid)
        self.assertFalse(brand(bid)["kickoff"]["copy_needed"])

    def test_months_span_the_year_end(self):
        from datetime import date
        self.assertEqual(otto_trial._months(date(2026, 12, 28), date(2027, 1, 4)), ["2026-12", "2027-01"])
        self.assertEqual(otto_trial._months(date(2026, 10, 3), date(2026, 10, 10)), ["2026-10"])

    def trial_brand(self, mail="eva@koffiezon.nl", sub="4001", site="koffiezon.nl"):
        sid = signup(mail, sub)
        st, out = onboard(sid, site)
        self.assertEqual(st, 200, out)
        return sid, out

    def test_signup_then_the_first_brand_runs_on_the_trial(self):
        sid, out = self.trial_brand()
        self.assertTrue(out["created"])
        self.assertTrue(out["trial"]["granted"], out["trial"])
        bid = out["brand"]
        b, u = brand(bid), user("eva@koffiezon.nl")
        self.assertEqual((b["plan"], b["status"], b["members"]), ("trial", "active", ["eva@koffiezon.nl"]))
        self.assertNotIn("plan_billing", b)
        ends = ap.parse_iso(u["trial_ends_at"])
        self.assertEqual(b["plan_until"], ends.astimezone(ap.brand_tz(b)).date().isoformat())
        self.assertEqual((b["trial"]["user"], b["trial"]["ends_at"], u["brands"]), (u["id"], u["trial_ends_at"], [bid]))
        keys = {x["k"] for x in ap.load()["trial_ledger"]}
        self.assertEqual(keys, {otto_trial.ledger_key("e", "eva@koffiezon.nl"), otto_trial.ledger_key("d", "koffiezon.nl")})
        self.assertNotIn("koffiezon", json.dumps(ap.load()["trial_ledger"]), "the ledger holds hashes only")
        st, d = req("GET", "/otto-api/data", sid=sid)
        self.assertEqual(st, 200)
        bv = d["brands"][0]
        self.assertNotIn("trial", bv, "the trial record (user id, reminders) stays on the server")
        self.assertEqual((bv["plan_view"]["label"], bv["plan_view"]["trial"]["state"], bv["plan_view"]["trial"]["days_left"]),
                         ("Free trial", "running", 7))
        self.assertTrue(any("planned and previewed" in x for x in bv["plan_view"]["included"]))
        self.assertIn("Approvals by e-mail", bv["plan_view"]["included"])
        st, me = req("GET", "/auth/me", sid=sid)
        offers = {o["plan"]: o for o in me["checkout"]}
        self.assertEqual(sorted(offers), ["starter"], "only the approved price (Starter, EUR 79 a month) is offered")
        self.assertEqual(offers["starter"]["checkout_url"], "https://app.otto.example/billing.html?plan=starter",
                         "Otto's own Billing page, never a third-party checkout")
        self.assertEqual((offers["starter"]["month"], offers["starter"]["year"]), (True, False))
        self.assertEqual(me["billing_url"], "https://app.otto.example/billing.html")
        self.assertNotIn("whop", json.dumps(me))
        self.assertIn("trial=granted", (TMP / "actions.log").read_text())

    def test_one_trial_per_user_per_email_and_per_domain(self):
        sid, out = self.trial_brand()
        st, second = onboard(sid, "second-shop.example")
        self.assertEqual((st, second["trial"]["granted"], second["trial"]["why"]), (200, False, "one_brand"))
        self.assertEqual(brand(second["brand"])["plan"], "none")
        # the site's brand is deleted (retention); another Google account tries the same domain: no second trial
        with ap.transaction(sync=False) as d:
            otto_retention.purge_records(d, out["brand"])
            otto_retention.purge_records(d, second["brand"])
        self.assertIsNone(user("eva@koffiezon.nl"), "the sign-in account went with its last brand")
        bob = signup("bob@other.example", "4002")
        st, again = onboard(bob, "www.koffiezon.nl")
        self.assertEqual((st, again["trial"]["why"]), (200, "domain"))
        st, pw = req("GET", "/otto-api/data", sid=bob)
        self.assertEqual((st, pw["code"]), (402, "no_trial"))
        self.assertIn("already had a free trial", pw["message"])
        self.assertEqual(pw["checkout"][0]["checkout_url"], "https://app.otto.example/billing.html?plan=starter")
        # the same Google e-mail signs up again after its account was deleted: no second trial either
        eva = signup("eva@koffiezon.nl", "4001")
        self.assertEqual((user("eva@koffiezon.nl")["status"], user("eva@koffiezon.nl")["trial_denied"]), ("none", "email"))
        st, third = onboard(eva, "third-shop.example")
        self.assertEqual(third["trial"]["why"], "email")
        st, pw = req("GET", "/otto-api/data", sid=eva)
        self.assertEqual((st, pw["code"]), (402, "no_trial"))
        st, me = req("GET", "/auth/me", sid=eva)
        self.assertEqual((me["trial"]["state"], me["trial"]["denied"]), ("none", "email"))

    def test_paid_ads_are_planned_and_previewed_but_never_launched(self):
        sid, out = self.trial_brand()
        bid = out["brand"]
        d = ap.load()
        self.assertIsNone(ap.no_ads_why(d, bid), "the month's ads may be planned")
        self.assertIn("launches none", ap.no_launch_why(d, bid))
        self.assertEqual(ap.matrix_preset(d, bid), "micro", "the matrix is rendered for preview")
        self.assertEqual(ap.limit(d, bid, "video_ads_per_month"), 3, "a small video preview cap")
        launch = otto_cron.plan("ads-launch", d, force=True, only=bid)[0][0]
        self.assertIn("launches none", launch.skip, "the heartbeat says why")
        self.assertIsNone(otto_cron.plan("ads-plan", d, force=True, only=bid)[0][0].skip)
        self.assertIsNone(otto_cron.plan("ads-report", d, force=True, only=bid)[0][0].skip)
        today = datetime.now(ap.brand_tz(brand(bid))).date().isoformat()
        with ap.transaction(sync=False) as d:
            d["campaigns"].append({"id": "cp-900", "brand": bid, "network": "meta", "name": "Trial preview", "status": "approved",
                                   "start": today, "end": today, "daily_budget": 10, "objective": "sales", "creative": {}, "remote": {}})
            d["campaigns"].append({"id": "cp-901", "brand": bid, "network": "meta", "name": "Trial paused", "status": "paused",
                                   "start": today, "end": today, "daily_budget": 10, "creative": {}, "remote": {}})
        quiet(otto_ads.launch, bid)
        self.assertIn("SKIPPED", quiet.last)
        self.assertIn("launches none", quiet.last)
        self.assertEqual(ap.campaign(ap.load(), "cp-900")["status"], "approved")
        self.assertEqual(S["graph"], [], "Meta was never called")
        with self.assertRaises(otto_ads.LaunchError):
            quiet(otto_ads.resume, "cp-901")

    def test_reminders_once_each_then_the_trial_ends_on_the_hour(self):
        sid, out = self.trial_brand()
        bid = out["brand"]
        E = ap.parse_iso(user("eva@koffiezon.nl")["trial_ends_at"])
        run = lambda when: quiet(otto_trial.run, when)
        self.assertEqual(run(E - timedelta(days=3)), 0)
        self.assertEqual(outbox(), [], "three days left: nothing yet")
        run(E - timedelta(hours=47))
        run(E - timedelta(hours=46))
        self.assertEqual([subject(f) for f in outbox()], ["2 days left in your Otto trial"])
        run(E - timedelta(hours=23))
        run(E - timedelta(hours=1))
        self.assertEqual(len(outbox()), 2)
        self.assertEqual(len(by_subject(r"^Your Otto trial ends (today|tomorrow)$")), 1)
        self.assertEqual(brand(bid)["plan"], "trial", "not over before its hour")
        run(E + timedelta(hours=5))                                         # the job ran late: the clock is still the end
        b = brand(bid)
        self.assertEqual(b["plan"], "none")
        self.assertNotIn("plan_until", b)
        h = b["plan_history"][-1]
        self.assertEqual((h["to"], h["via"], h["effective"]), ("none", "trial", E.strftime("%Y-%m-%dT%H:%M:%SZ")))
        self.assertEqual(user("eva@koffiezon.nl")["status"], "expired")
        self.assertEqual(len(outbox()), 3)
        (day8,) = by_subject(r"has ended .* is paused")
        self.assertIn("kept for 90 days", body_text(day8))
        self.assertIn("https://app.otto.example/billing.html", body_text(day8), "the button opens the Billing page")
        (day5,) = by_subject(r"^2 days left")
        body5 = " ".join(body_text(day5).split())
        self.assertIn("The plan starts when the trial ends, and that is when the first payment is taken.", body5)
        self.assertIn("If you don't choose one, nothing is charged", body5)
        self.assertNotIn("same e-mail", body5, "no e-mail matching any more: the checkout carries a signed reference")
        run(E + timedelta(hours=6))
        run(E + timedelta(days=2))
        self.assertEqual(len(outbox()), 3, "each reminder once")
        self.assertEqual(sorted(user("eva@koffiezon.nl")["trial_reminders"]), ["day5", "day7", "day8"])
        d = ap.load()
        self.assertTrue(ap.paused(d, bid), "publishing and ads pause")
        self.assertTrue(any(r.get("source") == "trials" and r.get("audience") == "owner" and r.get("brand") == bid
                            for r in d["recommendations"]), "the owner is told")
        t = otto_retention.timeline(b, E.date() + timedelta(days=1))
        self.assertEqual((t["ended"], t["delete_on"]), (E.date().isoformat(), (E.date() + timedelta(days=90)).isoformat()),
                         "the 90 days count from the trial's end")
        st, pw = req("GET", "/otto-api/data", sid=sid)
        self.assertEqual((st, pw["code"], pw["error"]), (402, "trial_ended", "trial ended"))
        self.assertEqual(pw["kept_until"][:10], (E + timedelta(days=90)).date().isoformat())
        self.assertEqual([x["id"] for x in pw["brands"]], [bid])
        st, _ = req("POST", "/otto-api/decide", {"id": "x-001", "decision": "approve"}, sid)
        self.assertEqual(st, 402)
        self.assertTrue(ap.brand(ap.load(), bid), "nothing was deleted")

    def test_the_reminders_quote_starter_at_79_in_every_language(self):
        """Starter is EUR 79 a month, a monthly subscription (approved by Max, 2 Oct 2026): the "add a card" offers carry it
        and the day-5 / day-7 e-mails say it in English, Dutch and German, with no yearly price; Growth's is still a draft."""
        import otto_i18n
        offers = {o["plan"]: o for o in otto_trial.checkout_offers()}
        self.assertEqual((offers["starter"]["monthly_eur"], offers["starter"]["yearly_eur"], offers["starter"]["draft"]), (79, None, False))
        self.assertFalse(offers["starter"]["year"], "Starter is a monthly subscription: never offered yearly")
        self.assertNotIn("growth", offers, "Growth's price is still a draft: never offered")
        now = datetime(2031, 3, 3, 9, 0, tzinfo=timezone.utc)
        want = {"en": ("Plans start at €79 a month.", "Starter · €79 a month"),
                "nl": ("Plannen beginnen bij € 79 per maand.", "Starter · € 79 per maand"),
                "de": ("Tarife gibt es ab 79 € im Monat.", "Starter · 79 € im Monat")}
        for lang, (line, offer) in want.items():
            d = {"brands": [{"id": "kz", "name": "Koffiezon", "tz": "Europe/Amsterdam", "comms_lang": lang}]}
            u = {"email": "eva@koffiezon.nl", "brands": ["kz"], "trial_ends_at": "2031-03-05T09:00:00Z"}
            self.assertIn(otto_i18n.Tr(lang).money(79, "EUR"), line)
            for key in ("day5", "day7"):
                _, html_body, text = otto_trial.render(key, u, d, now)
                self.assertIn(line, text, f"{lang} {key}")
                self.assertIn(offer, text, f"{lang} {key}")
                self.assertNotIn("99", text.replace("2031", ""), f"{lang} {key}: an old price")
                self.assertNotIn("790", text, f"{lang} {key}: no yearly Starter price")

    def test_an_expired_trial_never_falls_back_to_the_free_content_plan(self):
        sid, out = self.trial_brand()
        bid = out["brand"]
        with ap.transaction(sync=False) as d:
            ap.brand(d, bid)["plan_until"] = "2020-01-01"
        d = ap.load()
        p = ap.plan_of(d, bid)
        self.assertEqual((p["id"], p["source"]), ("none", "expired"))
        self.assertTrue(ap.plan_ended(d, bid))
        self.assertTrue(ap.paused(d, bid), "before the hourly job gets to it, nothing publishes")
        with ap.transaction(sync=False) as d:
            self.assertEqual(ap.plan_expiry_notices(d), [], "the trial's end is otto_trial's card")

    def test_legacy_whop_membership_with_the_verified_email_links_itself(self):
        sid, out = self.trial_brand()
        bid = out["brand"]
        E = ap.parse_iso(user("eva@koffiezon.nl")["trial_ends_at"])
        quiet(otto_trial.run, E + timedelta(hours=1))
        self.assertEqual(req("GET", "/otto-api/data", sid=sid)[0], 402)
        st, res = quiet(whop, "membership.activated", membership("mem_T1", "Eva@Koffiezon.nl"), "msg_t1")
        self.assertEqual((st, res.get("auto_linked")), (200, bid), res)
        self.assertEqual(res["plan"], {"brand": bid, "from": "none", "to": "starter"})
        b, u = brand(bid), user("eva@koffiezon.nl")
        self.assertEqual((b["plan"], b.get("plan_until"), b["status"]), ("starter", None, "active"))
        self.assertEqual(b["trial"]["converted_to"], "starter")
        self.assertEqual(u["status"], "active")
        c = otto_whop.load()["customers"]["mem_T1"]
        self.assertEqual(c["brand_id"], bid)
        self.assertTrue(c["brand_link"]["by"].startswith("auto"))
        st, d = req("GET", "/otto-api/data", sid=sid)
        self.assertEqual(st, 200, "the paywall is gone")
        self.assertEqual(d["brands"][0]["plan_view"]["trial"]["state"], "converted")
        n_hist = len(b["plan_history"])
        st, res = quiet(whop, "membership.activated", membership("mem_T1", "eva@koffiezon.nl"), "msg_t2")
        self.assertNotIn("auto_linked", res, "a linked membership is never linked again")
        self.assertEqual(len(brand(bid)["plan_history"]), n_hist)
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertEqual((me["trial"]["state"], me["checkout"]), ("converted", []))
        # console: conversion counted
        snap = otto_admin.build(ap.load(), [], {}, {}, {}, now=datetime.now(timezone.utc))
        self.assertEqual((snap["trials"]["counts"]["converted"], snap["trials"]["conversion_rate"]), (1, 100.0))
        self.assertEqual(snap["trials"]["funnel"][-1]["n"], 1)

    def test_other_emails_and_unmapped_plans_stay_manual(self):
        sid, out = self.trial_brand()
        bid = out["brand"]
        st, res = quiet(whop, "membership.activated", membership("mem_S1", "stranger@else.example"), "msg_s1")
        self.assertNotIn("auto_linked", res)
        st, res = quiet(whop, "membership.activated", membership("mem_S2", "eva@koffiezon.nl", plan="plan_not_mapped"), "msg_s2")
        self.assertNotIn("auto_linked", res, "a Whop plan plans.json does not map: the owner decides")
        st, res = quiet(whop, "membership.activated", membership("mem_S3", "eva@koffiezon.nl", status="drafted"), "msg_s3")
        self.assertNotIn("auto_linked", res, "an unfinished checkout links nothing")
        self.assertEqual(brand(bid)["plan"], "trial")
        c = quiet(otto_whop.link, "mem_S1", bid, "test")
        self.assertEqual(c["brand_id"], bid)
        self.assertEqual(brand(bid)["plan"], "starter", "the owner's manual link still works (and converts the trial)")
        self.assertTrue(brand(bid)["trial"]["converted_at"])

    def test_paid_before_the_brand_existed_links_at_onboarding(self):
        sid = signup("eva@koffiezon.nl", "4001")
        st, res = quiet(whop, "membership.activated", membership("mem_P1", "eva@koffiezon.nl", plan=GROWTH_WHOP), "msg_p1")
        self.assertNotIn("auto_linked", res, "no brand yet")
        st, out = onboard(sid, "koffiezon.nl")
        self.assertEqual(out["linked"]["membership"], "mem_P1")
        self.assertEqual(brand(out["brand"])["plan"], "growth")
        self.assertEqual(user("eva@koffiezon.nl")["status"], "active")

    def test_idle_accounts_without_a_brand_are_removed(self):
        sid = signup("idle@nowhere.example", "4100")
        signup("fresh@nowhere.example", "4101")
        old = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with ap.transaction(sync=False) as d:
            for u in d["users"]:
                u["last_login_at"] = old
                if u["email"].startswith("idle"):
                    u["status"] = "expired"
        quiet(otto_trial.prune_users)
        self.assertIsNone(user("idle@nowhere.example"))
        self.assertIsNotNone(user("fresh@nowhere.example"), "a running trial is kept")
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertFalse(me["signed_in"], "its sessions ended")

    def test_the_hourly_job_is_scheduled(self):
        j = otto_cron.JOBS["trials"]
        self.assertEqual((j.calendar, j.scope, j.kill), ("*-*-* *:05:00", "once", False))
        self.assertTrue(otto_cron.once_argv("trials", datetime.now().date())[-2].endswith("otto_trial.py"))
        self.assertTrue((PLATFORM.parent / "infra" / "systemd" / "otto-job-trials.timer").is_file())

    def test_console_trials_section(self):
        sid, out = self.trial_brand()
        signup("nobrand@x.example", "4200")
        snap = otto_admin.build(ap.load(), [], {}, {}, {}, now=datetime.now(timezone.utc))
        t = snap["trials"]
        self.assertTrue(t["enabled"])
        self.assertEqual((t["counts"]["active"], t["counts"]["signups"], t["active"][0]["brand"], t["active"][0]["days_left"]),
                         (1, 2, out["brand"], 7))
        self.assertEqual(t["active"][0]["email"], "e•••@koffiezon.nl", "masked")
        self.assertEqual([s["key"] for s in t["funnel"]], ["visitors", "scanned", "signups", "trials", "paid"])
        self.assertEqual({x["key"]: x["status"] for x in snap["setup"]}["google_signin"], "connected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
