#!/usr/bin/env python3
"""Stripe billing (otto_stripe + otto_billing) end to end through the real API server, against a fake Stripe
(tests/fake_stripe.py) and a fake Google (tests/fake_google.py): the Checkout Session's exact request shape (signed
reference, the verified e-mail, payment methods, tax, VAT ID, billing address, the trial's end), the webhook signature
(tolerance, secret rotation, several v1, replay), every event → the brand's plan, past_due → canceled → plan none, refunds,
our own account management (change plan now / at period end, cancel / resume, payment method, VAT ID, invoices), the
optional Customer Portal, "Payments aren't set up yet" without a config, tenant scoping on /billing/*, and the console.

  cd platform && python3 tests/test_stripe.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, math, os, shutil, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_google as G                                                        # noqa: E402
import fake_stripe as F                                                        # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="otto-stripe-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_SESSIONS": str(TMP / "sessions.json"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"),
       "OTTO_PLANS": str(TMP / "plans.json"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": "",
       "OTTO_LEADS": str(TMP / "leads.json"), "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_EXPORTS": str(TMP / "exports"),
       "OTTO_APP_URL": "https://app.otto.example/"}
CLEAR = ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_DOMAIN", "OTTO_GOOGLE_REDIRECT_URI", "OTTO_FALLBACK",
         "WHOP_API_KEY", "WHOP_COMPANY_ID", "WHOP_WEBHOOK_SECRET", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "OTTO_EMAIL_BASE",
         "OTTO_STRIPE_SECRET_KEY", "OTTO_STRIPE_PUBLISHABLE_KEY", "OTTO_STRIPE_WEBHOOK_SECRET")
PROXIED = {"X-Real-IP": "203.0.113.30"}
ANSWERS = {"goal": "sales", "budget": "300_1000", "approvals": "email"}
WH_NEW, WH_OLD = "whsec_new_test_secret_do_not_use", "whsec_old_test_secret_do_not_use"
PRICES = {"starter": {"monthly": "price_starter_m", "yearly": "price_starter_y"},
          "growth": {"monthly": "price_growth_m", "yearly": "price_growth_y"}}


def scan_doc(host):
    return {"url": f"https://{host}", "final_url": f"https://{host}/", "scanned_at": "2026-09-29T10:00:00Z", "pages": [f"https://{host}/"],
            "identity": {"title": f"{host.split('.')[0].title()} | Coffee", "description": "Fresh coffee.", "site_name": host.split(".")[0].title(),
                         "og_title": "", "og_image": None},
            "industry": "E-commerce & retail", "industry_candidates": [], "languages": ["en"], "platform": "Shopify",
            "visual": {"palette": [], "neutrals": [], "logo": None, "fonts": [], "theme_color": None}, "socials": {},
            "contact": {"emails": [], "phones": []}, "commerce": {"currency": "EUR", "prices": ["12 €"], "promos": []},
            "trust": [], "quotes": [], "headings": [], "nav": [], "text_sample": ""}


_SAVED, S = {}, {}
MODS = ("ap", "otto_api", "otto_auth", "otto_trial", "otto_onboard", "otto_scan", "otto_strategy", "otto_plan", "otto_whop",
        "otto_billing", "otto_stripe", "otto_ads", "otto_admin", "otto_publish")
PINS = [("ap", "DATA", "data.json"), ("ap", "HTML", "index.html"), ("ap", "BRANDS", "brands"), ("otto_scan", "BRANDS", "brands"),
        ("otto_strategy", "BRANDS", "brands"), ("otto_plan", "BRANDS", "brands"), ("otto_api", "LOG", "actions.log"),
        ("otto_ads", "BRANDS", "brands"), ("otto_ads", "SECRETS", "secrets"), ("otto_publish", "SECRETS", "secrets"),
        ("otto_publish", "LOG", "publish.log")]


def stripe_json(**over):
    cfg = {"secret_key": F.KEY, "publishable_key": "pk_test_otto_fake", "webhook_secrets": [WH_NEW, WH_OLD],
           "ref_secret": "r" * 40}
    cfg.update(over)
    (TMP / "secrets" / "stripe.json").write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))


def write_plans(founding=None):
    plans = json.loads((PLATFORM / "plans.json").read_text())
    for pid, ids in PRICES.items():
        plans["plans"][pid]["stripe_price_ids"] = dict(ids)
    plans["plans"]["founding"]["stripe_price_ids"] = {"one_time": founding}
    (TMP / "plans.json").write_text(json.dumps(plans, indent=1))


def reset():
    (TMP / "data.json").write_text(json.dumps({"brands": [{"id": "keep", "name": "Keep Cafe", "url": "keepcafe.example", "tz": "UTC",
                                                           "status": "active", "plan": "starter", "members": ["kim@keepcafe.example"],
                                                           "pillars": ["A"], "compliance": ""}],
                                               "posts": [], "recommendations": [], "connections": [], "campaigns": [], "users": []}, indent=1))
    for f in ("sessions.json", "billing.json", "actions.log", "api-errors.log"):
        (TMP / f).unlink(missing_ok=True)
    for x in (TMP / "brands").iterdir():
        if x.name != "keep":
            shutil.rmtree(x, ignore_errors=True)
    otto_auth._rl.clear()
    otto_auth.PENDING.clear()
    otto_onboard._rl_last.clear()
    otto_onboard._public_creates.clear()
    otto_api._snap_cache.clear()
    otto_stripe._rl.clear()
    otto_stripe._live.clear()
    for k in CLEAR:
        os.environ.pop(k, None)
    write_plans()
    stripe_json()
    S["spawned"].clear()
    S["stripe"].log.clear()
    S["stripe"].fail_next = None


def setUpModule():
    for d in ("brands/keep", "secrets", "assets", "outbox"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR) + ["OTTO_STRIPE_API_BASE"]}
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
    S["google"], S["stripe"], S["graph"], S["spawned"] = G.FakeGoogle(), F.FakeStripe(), [], []
    os.environ["OTTO_STRIPE_API_BASE"] = S["stripe"].base
    (TMP / "secrets" / "google-oauth.json").write_text(json.dumps(S["google"].config()))
    _SAVED["fakes"] = (otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_whop.SPAWN, otto_billing.SPAWN, otto_ads.notify)
    otto_scan.scan = lambda url, pages=5, page_limit=1_200_000, deadline=None: scan_doc(otto_onboard.host_key(url))
    otto_scan.host_status = lambda url: "ok"
    otto_publish.graph = lambda *a, **kw: S["graph"].append(a) or {"id": "X"}
    otto_whop.SPAWN = otto_billing.SPAWN = lambda args: S["spawned"].append(list(args))
    otto_ads.notify = lambda text: True
    S["srv"] = otto_api.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
    threading.Thread(target=S["srv"].serve_forever, daemon=True).start()
    S["base"] = f"http://127.0.0.1:{S['srv'].server_address[1]}"
    S["origin"] = sorted(otto_api.ALLOWED_ORIGINS)[0]
    reset()


def tearDownModule():
    if "srv" in S:
        S["srv"].shutdown(); S["srv"].server_close()
    for k in ("google", "stripe"):
        if k in S:
            S[k].close()
    if "fakes" in _SAVED:
        otto_scan.scan, otto_scan.host_status, otto_publish.graph, otto_whop.SPAWN, otto_billing.SPAWN, otto_ads.notify = _SAVED["fakes"]
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


def req(method, path, body=None, sid=None, headers=None, origin=True):
    h = dict(PROXIED, **(headers or {}))
    if body is not None:
        body = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
        if origin:
            h.setdefault("Origin", S["origin"])
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


def trial_brand(mail="eva@koffiezon.nl", sub="5001", site="koffiezon.nl"):
    sid = signup(mail, sub)
    otto_onboard._rl_last.clear()
    st, out = quiet(req, "POST", "/otto-api/onboard", {"site": site, "answers": ANSWERS}, sid)
    assert st == 200, out
    return sid, out["brand"]


def hook(evt, secret=WH_NEW, ts=None, body=None):
    body = body if body is not None else json.dumps(evt).encode()
    st, msg, raw = G.request(S["base"], "POST", "/hooks/stripe", {"Stripe-Signature": otto_stripe.sign(secret, body, ts),
                                                                  "Content-Type": "application/json"}, body)
    return st, json.loads(raw)


def deliver(etype, obj, created=None):
    st, out = quiet(hook, S["stripe"].event(etype, obj, created))
    assert st == 200, out
    return out


def user(email_):
    return otto_trial.user_by_email(ap.load(), email_)


def brand(bid):
    return ap.brand(ap.load(), bid)


def checkout(sid, plan="growth", interval="month", bid=None):
    body = {"plan": plan, "interval": interval}
    if bid:
        body["brand"] = bid
    return req("POST", "/billing/checkout", body, sid)


def paid(sid, bid, plan="growth", interval="month", status=None):
    """Eva pays: our checkout session → the fake's completion → the two webhooks Stripe sends."""
    st, co = checkout(sid, plan, interval, bid)
    assert st == 200, co
    s, sub = S["stripe"].complete(co["session"], status=status)
    out = deliver("checkout.session.completed", s)
    if sub:
        deliver("customer.subscription.created", sub)
    return co, s, sub, out


class CheckoutTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_checkout_session_request_shape(self):
        sid, bid = trial_brand()
        st, co = checkout(sid)
        self.assertEqual(st, 200, co)
        self.assertEqual((co["ui"], co["publishable_key"]), ("embedded", "pk_test_otto_fake"))
        self.assertTrue(co["client_secret"].startswith(co["session"]))
        c = S["stripe"].last("POST", "/v1/checkout/sessions")
        p, h = c["params"], c["headers"]
        self.assertEqual(h["Authorization"], f"Bearer {F.KEY}")
        self.assertEqual(h["Stripe-Version"], otto_stripe.API_VERSION)
        self.assertTrue(h.get("Idempotency-Key"))
        self.assertEqual((p["mode"], p["line_items[0][price]"], p["line_items[0][quantity]"]), ("subscription", "price_growth_m", "1"))
        u = user("eva@koffiezon.nl")
        self.assertEqual(otto_stripe.read_ref(p["client_reference_id"]), {"brand": bid, "user": u["id"]}, "the signed reference")
        self.assertRegex(p["client_reference_id"], r"^[A-Za-z0-9_-]{1,200}$")
        self.assertEqual(p["customer_email"], "eva@koffiezon.nl", "the verified Google e-mail")
        self.assertNotIn("customer", p)
        self.assertEqual([p[f"payment_method_types[{i}]"] for i in range(4)], ["card", "sepa_debit", "ideal", "bancontact"])
        self.assertEqual((p["tax_id_collection[enabled]"], p["automatic_tax[enabled]"], p["billing_address_collection"]),
                         ("true", "true", "required"))
        self.assertIn("businesses", p["custom_text[submit][message]"])
        self.assertEqual(p["ui_mode"], "embedded")
        self.assertEqual(p["return_url"], "https://app.otto.example/billing.html?session_id={CHECKOUT_SESSION_ID}")
        self.assertEqual((p["metadata[otto_brand]"], p["subscription_data[metadata][otto_brand]"], p["metadata[otto_plan]"]),
                         (bid, bid, "growth"))
        ends = ap.parse_iso(brand(bid)["trial"]["ends_at"])
        self.assertEqual(int(p["subscription_data[trial_end]"]), int(ends.timestamp()), "the subscription starts when Otto's trial ends")
        self.assertNotIn("subscription_data[trial_period_days]", p)
        self.assertEqual(p["payment_method_collection"], "always")
        self.assertIn("billing checkout", (TMP / "actions.log").read_text())

    def test_trial_alignment_under_48_hours_and_after_the_trial(self):
        sid, bid = trial_brand()
        end = datetime.now(timezone.utc) + timedelta(hours=30)
        with ap.transaction(sync=False) as d:
            ap.brand(d, bid)["trial"]["ends_at"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(checkout(sid)[0], 200)
        p = S["stripe"].last("POST", "/v1/checkout/sessions")["params"]
        self.assertNotIn("subscription_data[trial_end]", p, "Stripe wants trial_end ≥ 48 hours ahead")
        self.assertEqual(p["subscription_data[trial_period_days]"], "2", "rounded up: never charged before the trial ends")
        with ap.transaction(sync=False) as d:
            ap.brand(d, bid)["trial"]["ends_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(checkout(sid)[0], 200)
        p = S["stripe"].last("POST", "/v1/checkout/sessions")["params"]
        self.assertFalse([k for k in p if "trial" in k], "the trial is over: no Stripe trial at all")

    def test_yearly_and_hosted_fallback(self):
        sid, bid = trial_brand()
        stripe_json(checkout_ui="hosted", publishable_key=None)
        st, co = checkout(sid, "starter", "year")
        self.assertEqual((st, co["ui"]), (200, "hosted"), co)
        self.assertTrue(co["url"].startswith("https://checkout.stripe.com/"))
        p = S["stripe"].last("POST", "/v1/checkout/sessions")["params"]
        self.assertEqual(p["line_items[0][price]"], "price_starter_y")
        self.assertNotIn("ui_mode", p)
        self.assertTrue(p["success_url"].startswith("https://app.otto.example/billing.html?session_id="))
        self.assertIn("canceled=1", p["cancel_url"])

    def test_not_on_sale_and_unknown_plans(self):
        sid, bid = trial_brand()
        st, out = checkout(sid, "scale")
        self.assertEqual((st, out["code"]), (409, "not_on_sale"))
        self.assertEqual(checkout(sid, "nope")[0], 400)
        self.assertEqual(checkout(sid, "growth", "week")[0], 400)
        st, me = req("GET", "/auth/me", sid=sid)
        offers = {o["plan"]: o for o in me["checkout"]}
        self.assertEqual(offers["growth"]["checkout_url"], "https://app.otto.example/billing.html?plan=growth")
        self.assertTrue(me["payments"])

    def test_founding_seat_is_off_until_a_price_is_set(self):
        sid, bid = trial_brand()
        st, out = req("GET", "/billing/offers")
        self.assertEqual((st, out["payments"], out["founding"]["on"], out["founding"]["url"]), (200, True, False, None))
        self.assertNotRegex(json.dumps(out), r"price_(starter|growth|founding)", "no price id leaves the server")
        self.assertEqual(checkout(sid, "founding")[1]["code"], "not_on_sale")
        write_plans(founding="price_founding")
        st, out = req("GET", "/billing/offers")
        self.assertEqual((out["founding"]["on"], out["founding"]["url"], out["founding"]["price_eur"]),
                         (True, "https://app.otto.example/billing.html?plan=founding", 197))
        st, co = checkout(sid, "founding")
        self.assertEqual(st, 200, co)
        p = S["stripe"].last("POST", "/v1/checkout/sessions")["params"]
        self.assertEqual((p["mode"], p["line_items[0][price]"], p["customer_creation"], p["invoice_creation[enabled]"]),
                         ("payment", "price_founding", "always", "true"))
        self.assertFalse([k for k in p if k.startswith("subscription_data")])
        s, _ = S["stripe"].complete(co["session"])
        out = deliver("checkout.session.completed", s)
        self.assertEqual(out.get("auto_linked"), bid, out)
        b = brand(bid)
        self.assertEqual((b["plan"], b["trial"]["converted_to"]), ("founding", "founding"))
        c = otto_billing.load()["customers"][s["id"]]
        self.assertEqual((c["kind"], c["status"], c["amount"]), ("one_time", "active", 197.0))
        self.assertEqual(checkout(sid, "founding")[1]["code"], "subscribed", "one seat per brand")
        st, co = checkout(sid, "growth")
        self.assertEqual(st, 200, "a founder may still start a subscription")


class WebhookTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_signature_tolerance_rotation_and_several_v1(self):
        body = b'{"id":"evt_x","type":"ping"}'
        now = time.time()
        good = otto_stripe.sign(WH_NEW, body, now)
        self.assertEqual(otto_stripe.verify(body, good, [WH_NEW]), (True, "ok"))
        self.assertFalse(otto_stripe.verify(body + b" ", good, [WH_NEW])[0], "one byte changed")
        self.assertFalse(otto_stripe.verify(body, good, ["whsec_other"])[0])
        self.assertTrue(otto_stripe.verify(body, otto_stripe.sign(WH_OLD, body, now), [WH_NEW, WH_OLD])[0], "secret rotation")
        self.assertFalse(otto_stripe.verify(body, otto_stripe.sign(WH_NEW, body, now - 301), [WH_NEW])[0], "older than 5 minutes")
        self.assertFalse(otto_stripe.verify(body, otto_stripe.sign(WH_NEW, body, now + 301), [WH_NEW])[0], "from the future")
        self.assertTrue(otto_stripe.verify(body, otto_stripe.sign(WH_NEW, body, now - 290), [WH_NEW])[0])
        t = int(now)
        old_v1 = otto_stripe.sign(WH_OLD, body, t).split("v1=")[1]
        new_v1 = otto_stripe.sign(WH_NEW, body, t).split("v1=")[1]
        self.assertTrue(otto_stripe.verify(body, f"t={t},v1={old_v1},v1={new_v1},v0=deadbeef", [WH_NEW])[0], "any v1 may match")
        self.assertFalse(otto_stripe.verify(body, f"t={t},v0={new_v1}", [WH_NEW])[0], "only v1 counts")
        self.assertFalse(otto_stripe.verify(body, "", [WH_NEW])[0])
        self.assertFalse(otto_stripe.verify(body, f"t=abc,v1={new_v1}", [WH_NEW])[0])

    def test_http_webhook_refuses_bad_signatures_and_replays(self):
        evt = S["stripe"].event("invoice.paid", {"id": "in_orphan", "customer": "cus_x", "amount_paid": 9900, "currency": "eur"})
        body = json.dumps(evt).encode()
        st, out = hook(None, WH_NEW, body=body)
        self.assertEqual((st, out.get("type")), (200, "invoice.paid"))
        self.assertIn("in_orphan", otto_billing.load()["payments"])
        st, out = hook(None, WH_NEW, body=body)                                  # Stripe retries: the same event id
        self.assertTrue(out.get("duplicate"))
        st, out = quiet(hook, None, WH_NEW, ts=time.time() - 600, body=body)    # a captured request replayed later
        self.assertEqual(st, 400)
        st, out = quiet(hook, None, "whsec_wrong", body=body)
        self.assertEqual(st, 400)
        self.assertIn("400 /hooks/stripe", (TMP / "api-errors.log").read_text())
        st, msg, raw = G.request(S["base"], "POST", "/hooks/stripe", {"Content-Type": "application/json"}, body)
        self.assertEqual(st, 400, "no signature header")
        self.assertEqual(sum(1 for e in otto_billing.load()["events"] if e["id"] == evt["id"]), 1, "applied once")
        self.assertIn("stripe", otto_billing.load()["last_webhook"])

    def test_every_event_moves_the_plan(self):
        sid, bid = trial_brand()
        co, s, sub, out = paid(sid, bid)
        self.assertEqual(out.get("auto_linked"), bid, "linked by our signed reference, not by e-mail")
        b, u = brand(bid), user("eva@koffiezon.nl")
        self.assertEqual((b["plan"], b.get("plan_until"), b["status"]), ("growth", None, "active"))
        self.assertEqual((b["trial"]["converted_to"], u["status"]), ("growth", "active"))
        self.assertTrue(u.get("paid_at"))
        self.assertIn("eva@koffiezon.nl", b["members"])
        self.assertEqual(b["plan_history"][-1]["via"], "stripe")
        c = otto_billing.load()["customers"][sub["id"]]
        self.assertEqual((c["status"], c["plan"], c["interval"], c["amount"], c["brand_id"]), ("trialing", "growth", "month", 249.0, bid))
        self.assertEqual(otto_billing.load()["accounts"][bid]["customer"], sub["customer"])
        st, stt = req("GET", f"/billing/status?session_id={co['session']}", sid=sid)
        self.assertEqual((st, stt["state"], stt["plan"]), (200, "active", "growth"))
        # the trial ends: Stripe charges, the subscription is active; the invoice is stored
        sub2 = dict(sub, status="active", trial_end=None)
        deliver("customer.subscription.updated", sub2)
        inv = S["stripe"].invoice(sub["id"])
        deliver("invoice.paid", inv)
        p = otto_billing.load()["payments"][inv["id"]]
        self.assertEqual((p["status"], p["amount"], p["membership"], p["number"]), ("paid", 249.0, sub["id"], inv["number"]))
        self.assertTrue(p["invoice_pdf"].startswith("https://"))
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertEqual((me["billing"][0]["status"], me["billing"][0]["plan"], me["checkout"]), ("active", "growth", []))
        # a late, older event changes nothing (Stripe does not promise order)
        deliver("customer.subscription.updated", dict(sub, status="past_due"), created=int(time.time()) - 3600)
        self.assertEqual(otto_billing.load()["customers"][sub["id"]]["status"], "active")
        # the plan changes in Stripe (e.g. the schedule's next phase) → the brand follows
        sub3 = json.loads(json.dumps(sub2))
        sub3["items"]["data"][0]["price"] = S["stripe"]._price("price_starter_m")
        out = deliver("customer.subscription.updated", sub3)
        self.assertEqual(out["plan"], {"brand": bid, "from": "growth", "to": "starter"})

    def test_past_due_then_canceled_after_the_retries(self):
        sid, bid = trial_brand()
        co, s, sub, _ = paid(sid, bid, status="active")
        inv = S["stripe"].invoice(sub["id"], status="open")
        deliver("invoice.payment_failed", inv)
        c = otto_billing.load()["customers"][sub["id"]]
        self.assertEqual(c["status"], "past_due")
        self.assertEqual(brand(bid)["plan"], "growth", "past due keeps the plan while Stripe retries")
        d = ap.load()
        cards = [r for r in d["recommendations"] if r.get("source") == "billing" and r.get("brand") == bid]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["audience"], "owner")
        deliver("invoice.payment_failed", dict(inv, id=inv["id"]))           # a second attempt: still one card
        self.assertEqual(len([r for r in ap.load()["recommendations"] if r.get("source") == "billing"]), 1)
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertTrue(me["billing"][0]["past_due"], "the app shows the banner")
        st, acc = req("GET", f"/billing/account?brand={bid}", sid=sid)
        self.assertEqual((acc["subscription"]["status"], acc["subscription"]["past_due"]), ("past_due", True))
        deliver("customer.subscription.updated", dict(sub, status="past_due"))
        deliver("customer.subscription.deleted", dict(sub, status="canceled", ended_at=int(time.time())))
        b = brand(bid)
        self.assertEqual(b["plan"], "none", "Stripe's retries ended: no plan")
        self.assertTrue(any(r.get("brand") == bid and "subscription ended" in r["title"] for r in ap.load()["recommendations"]))
        self.assertEqual(user("eva@koffiezon.nl")["status"], "none", "the app offers the plans again")
        self.assertIn("no active plan", ap.paused(ap.load(), bid))
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertTrue(me["checkout"], "plans are offered again")
        deliver("customer.subscription.updated", dict(sub, status="active"), created=int(time.time()) - 60)
        self.assertEqual(brand(bid)["plan"], "none", "an older 'active' never resurrects a canceled subscription")

    def test_a_first_payment_that_never_succeeds_leaves_the_trial_alone(self):
        sid, bid = trial_brand()
        st, co = checkout(sid)
        s, sub = S["stripe"].complete(co["session"], status="incomplete")
        deliver("customer.subscription.created", sub)
        deliver("customer.subscription.updated", dict(sub, status="incomplete_expired"))
        self.assertEqual(brand(bid)["plan"], "trial")
        self.assertIsNone(otto_billing.load()["customers"][sub["id"]].get("brand_id"))

    def test_refunds(self):
        write_plans(founding="price_founding")
        sid, bid = trial_brand()
        st, co = checkout(sid, "founding")
        s, _ = S["stripe"].complete(co["session"])
        deliver("checkout.session.completed", s)
        self.assertEqual(brand(bid)["plan"], "founding")
        pi = s["payment_intent"]
        deliver("charge.refunded", {"id": "ch_1", "payment_intent": pi, "customer": s["customer"], "amount": 19700,
                                    "amount_refunded": 5000, "refunded": False})
        p = otto_billing.load()["payments"][pi]
        self.assertEqual((p["status"], p["refunded_eur"]), ("paid", 50.0))
        self.assertEqual(brand(bid)["plan"], "founding", "a partial refund keeps the seat")
        deliver("charge.refunded", {"id": "ch_1", "payment_intent": pi, "customer": s["customer"], "amount": 19700,
                                    "amount_refunded": 19700, "refunded": True})
        self.assertEqual(otto_billing.load()["payments"][pi]["status"], "refunded")
        self.assertEqual(brand(bid)["plan"], "none", "a full refund of the one-time seat ends it")
        rows = {r["id"]: r for r in otto_billing.customer_rows()}
        self.assertEqual(rows[s["id"]]["ltv_eur"], 0.0)

    def test_sepa_one_time_waits_for_the_money(self):
        write_plans(founding="price_founding")
        sid, bid = trial_brand()
        st, co = checkout(sid, "founding")
        s, _ = S["stripe"].complete(co["session"], pm="sepa")
        self.assertEqual(s["payment_status"], "unpaid")
        deliver("checkout.session.completed", s)
        self.assertEqual(brand(bid)["plan"], "trial", "SEPA is still processing: nothing changes")
        st, stt = req("GET", f"/billing/status?session_id={co['session']}", sid=sid)
        self.assertEqual(stt["state"], "processing")
        deliver("checkout.session.async_payment_succeeded", dict(s, payment_status="paid"))
        self.assertEqual(brand(bid)["plan"], "founding")


class AccountTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.sid, self.bid = trial_brand()
        self.co, self.s, self.sub, _ = paid(self.sid, self.bid, "starter", status="active")

    def test_account_view(self):
        S["stripe"].invoice(self.sub["id"])
        st, acc = req("GET", f"/billing/account?brand={self.bid}", sid=self.sid)
        self.assertEqual(st, 200, acc)
        sub = acc["subscription"]
        self.assertEqual((sub["plan"], sub["label"], sub["interval"], sub["amount"], sub["status"]), ("starter", "Starter", "month", 99.0, "active"))
        self.assertTrue(sub["renews"])
        self.assertEqual((acc["payment_method"]["brand"], acc["payment_method"]["last4"]), ("visa", "4242"))
        self.assertEqual(acc["tax_ids"][0]["value"], "NL123456789B01")
        self.assertTrue(acc["invoices"] and acc["invoices"][0]["pdf"].startswith("https://pay.stripe.com/"))
        self.assertEqual((acc["configured"], acc["publishable_key"], acc["portal"]), (True, "pk_test_otto_fake", False))
        self.assertNotIn(F.KEY, json.dumps(acc))
        self.assertIn("growth", [o["plan"] for o in acc["offers"]])

    def test_upgrade_now_prorated(self):
        st, out = req("POST", "/billing/change", {"brand": self.bid, "plan": "growth", "interval": "month"}, self.sid)
        self.assertEqual((st, out["when"]), (200, "now"), out)
        p = S["stripe"].last("POST", f"/v1/subscriptions/{self.sub['id']}")["params"]
        self.assertEqual((p["items[0][id]"], p["items[0][price]"], p["proration_behavior"], p["payment_behavior"]),
                         (self.sub["items"]["data"][0]["id"], "price_growth_m", "always_invoice", "pending_if_incomplete"))
        self.assertEqual(brand(self.bid)["plan"], "growth", "applied from Stripe's own answer (server side)")

    def test_downgrade_at_period_end_then_keep(self):
        quiet(req, "POST", "/billing/change", {"brand": self.bid, "plan": "growth", "interval": "month"}, self.sid)
        st, out = req("POST", "/billing/change", {"brand": self.bid, "plan": "starter", "interval": "month"}, self.sid)
        self.assertEqual((st, out["when"]), (200, "period_end"), out)
        self.assertEqual([c for c in S["stripe"].calls("POST", "/v1/subscription_schedules") if c["path"] == "/v1/subscription_schedules"][-1]
                         ["params"]["from_subscription"], self.sub["id"])
        upd = [c for c in S["stripe"].calls("POST", "/v1/subscription_schedules/") if not c["path"].endswith("release")][-1]["params"]
        self.assertEqual((upd["end_behavior"], upd["phases[0][items][0][price]"], upd["phases[1][items][0][price]"], upd["phases[1][iterations]"]),
                         ("release", "price_growth_m", "price_starter_m", "1"))
        self.assertEqual(brand(self.bid)["plan"], "growth", "nothing changes until the period ends")
        st, acc = req("GET", f"/billing/account?brand={self.bid}", sid=self.sid)
        self.assertEqual(acc["subscription"]["pending"]["plan"], "starter")
        st, out = req("POST", "/billing/change", {"brand": self.bid, "plan": "growth", "interval": "month"}, self.sid)
        self.assertEqual(out["when"], "kept")
        self.assertTrue(S["stripe"].calls("POST", "/v1/subscription_schedules/")[-1]["path"].endswith("/release"))
        st, acc = req("GET", f"/billing/account?brand={self.bid}", sid=self.sid)
        self.assertIsNone(acc["subscription"]["pending"])
        self.assertEqual(req("POST", "/billing/change", {"brand": self.bid, "plan": "growth", "interval": "month"}, self.sid)[1]["code"], "same_plan")

    def test_monthly_to_yearly_is_now_yearly_to_monthly_at_period_end(self):
        st, out = req("POST", "/billing/change", {"brand": self.bid, "plan": "starter", "interval": "year"}, self.sid)
        self.assertEqual(out["when"], "now")
        st, out = req("POST", "/billing/change", {"brand": self.bid, "plan": "starter", "interval": "month"}, self.sid)
        self.assertEqual(out["when"], "period_end")

    def test_cancel_and_resume(self):
        st, out = req("POST", "/billing/cancel", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 200, out)
        self.assertEqual(S["stripe"].last("POST", f"/v1/subscriptions/{self.sub['id']}")["params"]["cancel_at_period_end"], "true")
        c = otto_billing.load()["customers"][self.sub["id"]]
        self.assertTrue(c["cancel_at_period_end"])
        self.assertIsNone(c["renews"], "no next charge")
        self.assertEqual(brand(self.bid)["plan"], "starter", "runs until the period ends")
        st, out = req("POST", "/billing/resume", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 200, out)
        self.assertFalse(otto_billing.load()["customers"][self.sub["id"]]["cancel_at_period_end"])
        self.assertEqual(req("POST", "/billing/resume", {"brand": self.bid}, self.sid)[1]["code"], "not_canceling")
        # a pending downgrade is released before cancelling (a schedule would refuse it)
        quiet(req, "POST", "/billing/change", {"brand": self.bid, "plan": "starter", "interval": "month"}, self.sid)
        req("POST", "/billing/change", {"brand": self.bid, "plan": "growth", "interval": "month"}, self.sid)
        req("POST", "/billing/change", {"brand": self.bid, "plan": "starter", "interval": "month"}, self.sid)
        st, out = req("POST", "/billing/cancel", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 200, out)

    def test_payment_method_via_setup_intent_and_webhook(self):
        st, out = req("POST", "/billing/payment-method", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 200, out)
        self.assertTrue(out["client_secret"].startswith("seti_"))
        p = S["stripe"].last("POST", "/v1/setup_intents")["params"]
        self.assertEqual((p["customer"], p["usage"], p["metadata[otto_purpose]"], p["payment_method_types[1]"]),
                         (self.sub["customer"], "off_session", "payment_method", "sepa_debit"))
        # past due: the new card becomes the default and the open invoice is retried with it
        inv = S["stripe"].invoice(self.sub["id"], status="open")
        deliver("invoice.payment_failed", inv)
        si = S["stripe"].setups[out["client_secret"].split("_secret")[0]]
        si.update(status="succeeded", payment_method="pm_new")
        res = deliver("setup_intent.succeeded", si)
        self.assertEqual(res.get("retried"), inv["id"], res)
        self.assertEqual(S["stripe"].customers[self.sub["customer"]]["invoice_settings"]["default_payment_method"], "pm_new")
        self.assertEqual(S["stripe"].last("POST", f"/v1/subscriptions/{self.sub['id']}")["params"]["default_payment_method"], "pm_new")
        self.assertEqual(S["stripe"].invoices[inv["id"]]["status"], "paid")

    def test_vat_id(self):
        st, out = req("POST", "/billing/tax-id", {"brand": self.bid, "value": "de 123.456.789"}, self.sid)
        self.assertEqual(st, 200, out)
        self.assertEqual([t["value"] for t in S["stripe"].tax_ids[self.sub["customer"]]], ["DE123456789"], "replaced, not added")
        self.assertEqual(req("POST", "/billing/tax-id", {"brand": self.bid, "value": "hello"}, self.sid)[1]["code"], "bad_vat")

    def test_portal_is_an_optional_fallback(self):
        st, out = req("POST", "/billing/portal", {"brand": self.bid}, self.sid)
        self.assertEqual((st, out["code"]), (404, "portal_off"))
        stripe_json(portal_fallback=True, portal_configuration="bpc_123")
        st, out = req("POST", "/billing/portal", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 200, out)
        self.assertTrue(out["url"].startswith("https://billing.stripe.com/"))
        p = S["stripe"].last("POST", "/v1/billing_portal/sessions")["params"]
        self.assertEqual((p["customer"], p["configuration"]), (self.sub["customer"], "bpc_123"))
        self.assertEqual(p["return_url"], f"https://app.otto.example/billing.html?brand={self.bid}")

    def test_a_second_checkout_reuses_the_customer_and_is_refused_while_subscribed(self):
        st, out = checkout(self.sid, "growth", "month", self.bid)
        self.assertEqual((st, out["code"]), (409, "subscribed"))
        deliver("customer.subscription.deleted", dict(self.sub, status="canceled", ended_at=int(time.time())))
        st, out = checkout(self.sid, "growth", "month", self.bid)
        self.assertEqual(st, 200, out)
        p = S["stripe"].last("POST", "/v1/checkout/sessions")["params"]
        self.assertEqual((p["customer"], p["customer_update[address]"], p["customer_update[name]"]), (self.sub["customer"], "auto", "auto"))
        self.assertNotIn("customer_email", p, "the existing customer locks the e-mail")

    def test_stripe_errors_never_leak(self):
        S["stripe"].fail_next = (400, "No such customer: 'cus_secret_internal'", "resource_missing")
        st, out = req("POST", "/billing/cancel", {"brand": self.bid}, self.sid)
        self.assertEqual(st, 502)
        self.assertNotIn("cus_secret_internal", json.dumps(out))
        self.assertIn("cus_secret_internal", (TMP / "api-errors.log").read_text())


class ScopeAndConfigTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_no_config_means_clean_503s(self):
        sid, bid = trial_brand()
        (TMP / "secrets" / "stripe.json").unlink()
        st, acc = req("GET", "/billing/account", sid=sid)
        self.assertEqual((st, acc["configured"]), (200, False))
        st, out = checkout(sid)
        self.assertEqual((st, out["code"], out["error"]), (503, "not_configured", "Payments aren't set up yet."))
        for path in ("/billing/change", "/billing/cancel", "/billing/resume", "/billing/payment-method", "/billing/tax-id"):
            self.assertEqual(req("POST", path, {"brand": bid}, sid)[0], 503, path)
        self.assertEqual(req("POST", "/billing/portal", {"brand": bid}, sid)[0], 404)
        st, out = hook(S["stripe"].event("invoice.paid", {"id": "in_1"}))
        self.assertEqual(st, 503)
        st, me = req("GET", "/auth/me", sid=sid)
        self.assertEqual({(o["why"], o["checkout_url"]) for o in me["checkout"]}, {("not_configured", None)})
        self.assertFalse(me["payments"])
        st, off = req("GET", "/billing/offers")
        self.assertEqual((off["payments"], off["founding"]["on"]), (False, False))
        self.assertEqual(S["stripe"].calls("POST", "/v1/checkout"), [], "no Stripe call without a config")

    def test_tenant_scoping(self):
        eva, bid = trial_brand()
        bob, bob_bid = trial_brand("bob@other.example", "5002", "other-shop.example")
        self.assertEqual(checkout(bob, "growth", "month", bid)[0], 404, "another client's brand does not exist for bob")
        self.assertEqual(req("GET", f"/billing/account?brand={bid}", sid=bob)[0], 404)
        self.assertEqual(req("POST", "/billing/cancel", {"brand": bid}, bob)[0], 404)
        self.assertEqual(req("GET", f"/billing/account?brand=keep", sid=bob)[0], 404)
        st, co = checkout(eva)
        self.assertEqual(req("GET", f"/billing/status?session_id={co['session']}", sid=bob)[0], 404, "only your own checkout")
        self.assertEqual(req("GET", "/billing/account")[0], 401, "signed in with Google only")
        self.assertEqual(req("GET", "/billing/account", headers={"X-Otto-User": "eva@koffiezon.nl"})[0], 401, "a proxy name is not enough")
        self.assertEqual(req("POST", "/billing/checkout", {"plan": "growth"}, eva, origin=False)[0], 403, "no Origin behind the proxy")
        self.assertEqual(req("POST", "/billing/checkout", {"plan": "growth"}, eva, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(req("POST", "/billing/checkout", {"plan": "growth"}, eva, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(req("GET", "/billing/nothing", sid=eva)[0], 404)
        st, acc = req("GET", "/billing/account", sid=eva)
        self.assertEqual([x["id"] for x in acc["brands"]], [bid])

    def test_rate_limit(self):
        sid, bid = trial_brand()
        otto_stripe._rl[user("eva@koffiezon.nl")["id"]] = [time.time()] * otto_stripe.RL_MAX
        self.assertEqual(checkout(sid)[0], 429)

    def test_status_never_shows_a_secret_and_the_key_only_goes_to_stripe(self):
        blob = json.dumps(otto_stripe.status())
        for secret in (F.KEY, WH_NEW, WH_OLD, "r" * 40):
            self.assertNotIn(secret, blob)
        old = os.environ["OTTO_STRIPE_API_BASE"]
        try:
            os.environ["OTTO_STRIPE_API_BASE"] = "https://evil.example"
            self.assertEqual(otto_stripe.config()["api_base"], "https://api.stripe.com", "only Stripe (or a local fake) gets the key")
        finally:
            os.environ["OTTO_STRIPE_API_BASE"] = old

    def test_reference_is_signed_and_rotates(self):
        ref = otto_stripe.make_ref("koffiezon", "u-1")
        self.assertEqual(otto_stripe.read_ref(ref), {"brand": "koffiezon", "user": "u-1"})
        self.assertIsNone(otto_stripe.read_ref(ref[:-2] + ("A" if ref[-2] != "A" else "B") + ref[-1]), "payload changed")
        self.assertIsNone(otto_stripe.read_ref("o1" + "0" * 32 + ref[34:]), "signature forged")
        self.assertIsNone(otto_stripe.read_ref("cus_123"))
        self.assertEqual(otto_stripe.read_ref(otto_stripe.make_ref("", "u-2")), {"brand": None, "user": "u-2"})
        stripe_json(ref_secret="n" * 40, previous_ref_secrets=["r" * 40])
        self.assertEqual(otto_stripe.read_ref(ref), {"brand": "koffiezon", "user": "u-1"}, "an old reference still verifies")

    def test_paid_before_the_brand_existed_links_at_onboarding(self):
        write_plans(founding="price_founding")
        sid = signup("eva@koffiezon.nl", "5001")
        st, co = checkout(sid, "founding")
        self.assertEqual(st, 200, co)
        self.assertEqual(otto_stripe.read_ref(S["stripe"].last("POST", "/v1/checkout/sessions")["params"]["client_reference_id"])["brand"], None)
        s, _ = S["stripe"].complete(co["session"])
        out = deliver("checkout.session.completed", s)
        self.assertNotIn("auto_linked", out, "no brand yet")
        otto_onboard._rl_last.clear()
        st, ob = quiet(req, "POST", "/otto-api/onboard", {"site": "koffiezon.nl", "answers": ANSWERS}, sid)
        self.assertEqual(ob["linked"]["membership"], s["id"])
        self.assertEqual(brand(ob["brand"])["plan"], "founding")


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_console_billing_and_setup(self):
        sid, bid = trial_brand()
        co, s, sub, _ = paid(sid, bid, "growth", status="active")
        deliver("invoice.paid", S["stripe"].invoice(sub["id"], reason="subscription_create"))
        with otto_billing.transaction() as b:                    # a founder from the Whop days (no provider field)
            b["customers"]["mem_old"] = {"id": "mem_old", "status": "active", "whop_status": "completed", "plan_id": "plan_joHl1qsZoiJc9",
                                         "email": "f@founder.example", "started": "2026-08-01T10:00:00Z"}
        snap = otto_admin.snapshot()
        R = snap["revenue"]
        rows = {c["id"]: c for c in R["customers"]}
        self.assertEqual((rows[sub["id"]]["provider"], rows[sub["id"]]["mrr_eur"], rows[sub["id"]]["linkable"]), ("stripe", 249.0, True))
        self.assertEqual((rows["mem_old"]["provider"], rows["mem_old"]["linkable"]), ("whop", False))
        self.assertEqual([r["id"] for r in R["legacy_whop"]], ["mem_old"])
        self.assertEqual((R["mrr_eur"], R["paying"], R["arpu_eur"]), (249.0, 2, 249.0))
        self.assertNotIn("eva@koffiezon.nl", json.dumps(R), "e-mails are masked in billing")
        setup = {x["key"]: x for x in snap["setup"]}
        self.assertEqual((setup["stripe_keys"]["status"], setup["stripe_webhook"]["status"]), ("connected", "connected"))
        self.assertIn("/hooks/stripe", setup["stripe_webhook"]["how"])
        self.assertEqual(setup["stripe_prices"]["status"], "partial", "scale and agency have no price yet")
        self.assertNotIn(F.KEY, json.dumps(snap))
        self.assertNotIn(WH_NEW, json.dumps(snap))
        self.assertEqual(setup["stripe_tax"]["status"], "waiting", "not checked yet")
        res = quiet(otto_stripe.check)
        self.assertEqual(res["tax"], "active")
        self.assertEqual(res["prices"]["growth.monthly"], "ok")
        S["stripe"].tax_status = "pending"
        res = quiet(otto_stripe.check)
        self.assertTrue(any("Stripe Tax" in p for p in res["problems"]))
        S["stripe"].tax_status = "active"
        quiet(otto_stripe.check)
        setup = {x["key"]: x["status"] for x in otto_admin.snapshot()["setup"]}
        self.assertEqual((setup["stripe_tax"], setup["stripe_branding"]), ("connected", "connected"))
        with self.assertRaises(ValueError):
            otto_admin.act({"action": "whop_sync"}, "max")
        spawned = []
        orig = otto_admin.SPAWN
        otto_admin.SPAWN = lambda args, log: spawned.append(args)
        try:
            out = otto_admin.act({"action": "stripe_check"}, "max")
        finally:
            otto_admin.SPAWN = orig
        self.assertTrue(out["ok"] and spawned[0][-2:] == [str(PLATFORM / "otto_stripe.py"), "check"])

    def test_manual_link_stays_for_edge_cases(self):
        sid, bid = trial_brand()
        st, co = checkout(sid)
        s, sub = S["stripe"].complete(co["session"], status="active")
        sub["metadata"] = {}                                        # paid outside our flow: no reference
        with otto_billing.transaction() as b:
            otto_stripe.apply_subscription(b, sub, int(time.time()))
        self.assertIsNone(otto_billing.load()["customers"][sub["id"]].get("brand_id"))
        out = otto_admin.act({"action": "link_customer", "customer": sub["id"], "brand": bid}, "max")
        self.assertIn("linked", out["message"])
        self.assertEqual((brand(bid)["plan"], otto_billing.load()["accounts"][bid]["customer"]), ("growth", sub["customer"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
