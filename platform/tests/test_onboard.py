#!/usr/bin/env python3
"""otto_onboard tests: create() on a local fixture site, idempotency, slug rules, answers, the HTTP body, and that
nothing outside the temp workspace is touched. Stdlib unittest, no network.

  cd platform && python3 tests/test_onboard.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites

Runs on its own throwaway workspace (data.json, index.html, brands/). Under discover, test_engine has already imported
ap / otto_scan / otto_strategy / otto_plan with its own OTTO_* paths, so setUpModule pins every module-level path to
this suite's workspace and tearDownModule puts them back.
"""
import contextlib, copy, hashlib, http.server, io, json, os, shutil, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
REPO = PLATFORM.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-onboard-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": ""}
SEED = {"brands": [{"id": "cmtm", "name": "CMTM College", "url": "cmtm.co.il", "lang": "HE", "tz": "Asia/Jerusalem",
                    "status": "active", "pillars": ["Community"], "compliance": ""}],
        "posts": [], "recommendations": [], "connections": []}

HOME = """<!doctype html><html lang="en"><head><title>Brightleaf Tea | Organic loose-leaf tea</title>
<meta name="description" content="Organic loose-leaf teas, blended in Bristol and sent in plastic-free tins.">
<meta name="theme-color" content="#2F5D50"><style>body{color:#2F5D50;background:#F3EDE2}.b{color:#C8553D}.c{background:#2F5D50}</style>
</head><body><img src="/logo.svg" alt="Brightleaf logo" class="logo"><h1>Tea that tastes like a slow morning</h1>
<a href="/shop">Shop</a> <a href="/about">About</a> <a href="https://instagram.com/brightleaftea">Instagram</a>
<p>Earl Grey 12.50 € · Sencha 14 € · Add to cart · checkout · free shipping over 30 € · shop</p>
<blockquote>"The best Earl Grey I have had in years, and the tin is lovely." ★★★★★</blockquote>
<p>Certified organic since 2014. 30-day money-back guarantee.</p></body></html>"""
LOGO = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="#2F5D50"/></svg>'


class _Site(http.server.BaseHTTPRequestHandler):
    pages = {"/": HOME, "/about": "<html><title>About</title><body><h2>Our story</h2><p>Family blenders since 2014.</p></body></html>",
             "/shop": "<html><title>Shop</title><body><h2>All teas</h2><p>Add to cart</p></body></html>", "/logo.svg": LOGO}

    def do_GET(self):
        body = self.pages.get(self.path.split("?")[0], "").encode()
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "image/svg+xml" if self.path.endswith(".svg") else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _fingerprint(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p):
    return sorted(str(x.relative_to(p)) for x in Path(p).rglob("*")) if Path(p).exists() else []


_SAVED = {}


def setUpModule():
    (TMP / "brands").mkdir()
    (TMP / "data.json").write_text(json.dumps(SEED, ensure_ascii=False, indent=2))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["repo"] = {f: _fingerprint(PLATFORM / f) for f in ("data.json", "index.html")}
    _SAVED["repo_brands"] = _listing(REPO / "brands")
    _SAVED["env"] = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_scan, otto_strategy, otto_plan, otto_compliance, otto_onboard, otto_api
    import ap, otto_scan, otto_strategy, otto_plan, otto_compliance, otto_onboard, otto_api     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_scan.BRANDS, otto_strategy.BRANDS, otto_plan.BRANDS, otto_api.LOG)
    ap.DATA, ap.HTML = TMP / "data.json", TMP / "index.html"
    ap.BRANDS = otto_scan.BRANDS = otto_strategy.BRANDS = otto_plan.BRANDS = TMP / "brands"
    otto_api.LOG = TMP / "actions.log"          # under discover, otto_api was imported by an earlier suite with its own paths
    # the fixture site runs on 127.0.0.1: let the SSRF guard through for this address and port only
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _SAVED["srv"] = srv
    _SAVED["guard"] = (otto_scan.ip_ok, otto_scan.ALLOWED_PORTS, otto_scan.scan, otto_scan.host_status)
    orig_ok = otto_scan.ip_ok
    otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig_ok(ip)
    otto_scan.ALLOWED_PORTS = otto_scan.ALLOWED_PORTS | {srv.server_address[1]}


def tearDownModule():
    srv = _SAVED.get("srv")
    if srv:
        srv.shutdown(); srv.server_close()
    if "guard" in _SAVED:
        otto_scan.ip_ok, otto_scan.ALLOWED_PORTS, otto_scan.scan, otto_scan.host_status = _SAVED["guard"]
    if "paths" in _SAVED:
        ap.DATA, ap.HTML, ap.BRANDS, otto_scan.BRANDS, otto_strategy.BRANDS, otto_plan.BRANDS, otto_api.LOG = _SAVED["paths"]
    for k, v in _SAVED.get("env", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def local_site():
    return f"http://127.0.0.1:{_SAVED['srv'].server_address[1]}/"


def canned(host, title="Acme", industry="E-commerce & retail", langs=("en",), palette=("#123456",), prices=("19 €",),
           platform="Shopify", currency="EUR"):
    """A scan.json-shaped result for a fake public host (no network)."""
    return {"url": f"https://{host}", "final_url": f"https://{host}/", "scanned_at": "2026-09-29T10:00:00Z",
            "pages": [f"https://{host}/", f"https://{host}/about"],
            "identity": {"title": title, "description": f"{title} sells things.", "site_name": "", "og_title": "", "og_image": None},
            "industry": industry, "industry_candidates": [{"industry": industry, "score": 40}], "languages": list(langs),
            "platform": platform, "visual": {"palette": [{"hex": h, "count": 3, "source": "css"} for h in palette],
                                             "neutrals": [], "logo": None, "fonts": ["Inter"], "theme_color": None},
            "socials": {}, "contact": {"emails": [], "phones": []}, "commerce": {"currency": currency, "prices": list(prices), "promos": []},
            "trust": ["Certified organic"], "quotes": [], "headings": ["Welcome"], "nav": ["Shop"], "text_sample": ""}


@contextlib.contextmanager
def fake_web(sites):
    """otto_scan.scan answers from `sites` ({host: scan}); anything else is unreadable. host_status says ok."""
    def scan(url, pages=5, page_limit=1_200_000, deadline=None):
        s = sites.get(otto_onboard.host_key(url))
        return copy.deepcopy(s) if s else {"url": url, "error": "HTTP 403"}
    prev = otto_scan.scan, otto_scan.host_status
    otto_scan.scan, otto_scan.host_status = scan, (lambda u: "ok")
    try:
        yield
    finally:
        otto_scan.scan, otto_scan.host_status = prev


def brand_of(slug):
    return ap.brand(ap.load(), slug)


ANSWERS = {"goal": "sales", "budget": "under_300", "objection": "Is loose-leaf a hassle?",
           "never_say": 'cheap, "best in the world"; a sentence that is far too long to be a single banned phrase really',
           "corrections": {"name": "Brightleaf Tea Co.", "palette": ["#2F5D50", "#e9c46a"]},
           "channels": {"meta": True, "google_ads": False, "telegram": True}, "approvals": "telegram", "tz": "Europe/London"}


class CreateTest(unittest.TestCase):
    def test_create_on_a_local_site_writes_the_brand(self):
        res = quiet(otto_onboard.create, local_site(), ANSWERS)
        slug = res["brand"]
        self.assertTrue(res["ok"] and res["created"])
        self.assertEqual(res["scan"]["source"], "site")
        bdir = TMP / "brands" / slug
        for f in ("scan.json", "brand-profile.md", "strategy.json", "compliance.json", "logo.svg"):
            self.assertTrue((bdir / f).exists(), f)
        b = brand_of(slug)
        self.assertEqual((b["status"], b["name"], b["tz"], b["countries"]), ("onboarding", "Brightleaf Tea Co.", "Europe/London", ["GB"]))
        self.assertEqual(b["onboarding"]["channels"], {"meta": True, "google_ads": False, "telegram": True})
        # the scan keeps what the site said; the owner's fixes are applied on top and remembered
        scan = json.loads((bdir / "scan.json").read_text())
        self.assertEqual(scan["identity"]["site_name"], "Brightleaf Tea Co.")
        self.assertEqual([p["hex"] for p in scan["visual"]["palette"]], ["#2F5D50", "#E9C46A"])
        self.assertIn("palette", scan["corrected"])
        self.assertIn("Organic loose-leaf", scan["identity"]["description"])
        # answers land in strategy inputs; the objection joins objections; long never-say text stays guidance
        st = json.loads((bdir / "strategy.json").read_text())
        self.assertEqual((st["inputs"]["goal"], st["inputs"]["budget"], st["inputs"]["goal_source"]), ("sales", "under_300", "owner"))
        self.assertEqual(st["objections"][0], {"text": "Is loose-leaf a hassle?", "answer": "(?)", "proof_id": "(?)", "source": "owner"})
        rules = json.loads((bdir / "compliance.json").read_text())
        self.assertEqual(rules["owner_never_say"], ["best in the world", "cheap"])
        self.assertTrue(otto_compliance.check_texts(slug, ["Simply the best in the world."]))
        self.assertIn("Owner answers", (bdir / "brand-profile.md").read_text())
        # honest connections: wanted, never connected; a next-step card each
        d = ap.load()
        conns = {c["id"]: c for c in d["connections"]}
        self.assertEqual(conns[f"meta-{slug}"]["status"], "not_connected")
        self.assertEqual(conns[f"tg-{slug}"]["status"], "not_connected")
        self.assertNotIn(f"gads-{slug}", conns)
        self.assertEqual(sorted(r["priority"] for r in d["recommendations"] if r.get("brand") == slug), ["P0", "P1"])
        # the first week: after the first review, inside seven days
        self.assertTrue(res["first_week"])
        review = datetime.fromisoformat(res["first_review"])
        self.assertEqual(review.strftime("%H:%M"), "07:35")   # Telegram approvals come with the 07:35 morning report
        for x in res["first_week"]:
            self.assertRegex(x["slot"], r"T\d\d:\d\d[+-]\d\d:\d\d$", "slots carry the brand's UTC offset, like first_review")
            t = datetime.fromisoformat(x["slot"]).replace(tzinfo=review.tzinfo)
            self.assertTrue(review < t <= review + timedelta(days=7), x)

    def test_rerun_updates_and_never_duplicates(self):
        with fake_web({"brightside.com": canned("brightside.com", "Brightside | Candles")}):
            r1 = quiet(otto_onboard.create, "brightside.com", {"goal": "sales", "objection": "Too pricey"})
            with ap.transaction(sync=False) as d:            # the team moved it on, and the owner connected Meta
                ap.brand(d, r1["brand"])["status"] = "active"
                next(c for c in d["connections"] if c["id"] == f"meta-{r1['brand']}")["status"] = "connected"
            before = ap.load()
            r2 = quiet(otto_onboard.create, "https://www.Brightside.com/shop?x=1", {"goal": "leads", "objection": "Too pricey",
                                                                                   "corrections": {"name": "Brightside Candles"}})
        after = ap.load()
        self.assertEqual(r2["brand"], r1["brand"])
        self.assertFalse(r2["created"])
        self.assertEqual(len(after["brands"]), len(before["brands"]))
        self.assertEqual(len(after["connections"]), len(before["connections"]))
        self.assertEqual(len(after["recommendations"]), len(before["recommendations"]))
        b = brand_of(r2["brand"])
        self.assertEqual((b["status"], b["name"]), ("active", "Brightside Candles"))
        self.assertEqual(next(c for c in after["connections"] if c["id"] == f"meta-{r2['brand']}")["status"], "connected")
        st = json.loads((TMP / "brands" / r2["brand"] / "strategy.json").read_text())
        self.assertEqual(st["inputs"]["goal"], "leads")
        self.assertEqual(sum(1 for o in st["objections"] if o["text"] == "Too pricey"), 1)
        self.assertEqual(b["onboarding"]["started_at"], ap.brand(before, r1["brand"])["onboarding"]["started_at"])

    def test_an_edited_profile_is_never_overwritten(self):
        with fake_web({"quietpine.com": canned("quietpine.com", "Quiet Pine")}):
            r = quiet(otto_onboard.create, "quietpine.com", {})
            prof = TMP / "brands" / r["brand"] / "brand-profile.md"
            quiet(otto_onboard.create, "quietpine.com", {"goal": "audience"})       # untouched → refreshed in place
            self.assertIn("A bigger audience", prof.read_text())
            prof.write_text(prof.read_text() + "\n- Owner: we never discount.\n")
            edited = prof.read_text()
            quiet(otto_onboard.create, "quietpine.com", {"goal": "launch"})
        self.assertEqual(prof.read_text(), edited)
        self.assertIn("Launch something new", (prof.parent / "brand-profile.draft.md").read_text())

    def test_unreadable_site_uses_the_peek_and_says_so(self):
        peek = {"url": "https://walled.shop/", "title": "Walled Garden Shop", "industry": "Clinic & medical",
                "palette": ["#0E7C86", "javascript:alert(1)"], "fonts": ["Lora"], "prices": ["€49"], "pages": 3,
                "socials": {"instagram": "https://instagram.com/walled", "evil": "javascript:x"}, "logo": "javascript:alert(1)"}
        with fake_web({}):
            r = quiet(otto_onboard.create, "walled.shop", {"never_say": "miracle"}, peek=peek)
            r_none = quiet(otto_onboard.create, "nothing-here.shop", {})
        self.assertEqual((r["scan"]["ok"], r["scan"]["source"]), (True, "peek"))
        scan = json.loads((TMP / "brands" / r["brand"] / "scan.json").read_text())
        self.assertEqual((scan["source"], [p["hex"] for p in scan["visual"]["palette"]]), ("peek", ["#0E7C86"]))
        self.assertIsNone(scan["visual"]["logo"])
        self.assertEqual(list(scan["socials"]), ["instagram"])
        self.assertEqual(r["next_steps"][0]["state"], "todo")
        # a health brand keeps the cure/heal baseline when the owner adds words of their own
        rules = json.loads((TMP / "brands" / r["brand"] / "compliance.json").read_text())
        self.assertIn(otto_compliance.HEALTH_BASELINE[0], rules["banned"])
        self.assertIn("miracle", rules["banned"])
        # no scan and no peek: the brand still exists, nothing pretends it was read
        self.assertFalse(r_none["scan"]["ok"])
        self.assertFalse((TMP / "brands" / r_none["brand"] / "scan.json").exists())
        self.assertEqual(brand_of(r_none["brand"])["status"], "onboarding")

    def test_dry_run_writes_nothing(self):
        data, listing = (TMP / "data.json").read_text(), _listing(TMP / "brands")
        with fake_web({"drytest.io": canned("drytest.io", "Dry Test")}):
            r = quiet(otto_onboard.create, "drytest.io", ANSWERS, dry=True)
        self.assertTrue(r["dry"] and r["created"])
        self.assertEqual(r["files"], [])
        self.assertEqual((TMP / "data.json").read_text(), data)
        self.assertEqual(_listing(TMP / "brands"), listing)

    def test_market_follows_tld_then_currency_then_browser(self):
        with fake_web({"praxis-mitte.de": canned("praxis-mitte.de", "Praxis Mitte", "Clinic & medical", ("de",), platform="WordPress"),
                       "sunnyside.co": canned("sunnyside.co", "Sunnyside"),
                       "greens-daily.co": canned("greens-daily.co", "Greens", prices=("$29",), currency="USD"),
                       "lisbon-surf.com": canned("lisbon-surf.com", "Surf", currency="EUR")}):
            de = quiet(otto_onboard.create, "praxis-mitte.de", {"tz": "America/New_York"})        # the TLD wins
            us = quiet(otto_onboard.create, "sunnyside.co", {"tz": "America/New_York"})          # EUR says nothing: browser
            usd = quiet(otto_onboard.create, "greens-daily.co", {"tz": "Asia/Jerusalem"})       # USD prices beat an operator abroad
            pt = quiet(otto_onboard.create, "lisbon-surf.com", {"tz": "Europe/Lisbon"})
        market = lambda r: (brand_of(r["brand"])["tz"], brand_of(r["brand"])["countries"])
        self.assertEqual(market(de), ("Europe/Berlin", ["DE"]))
        self.assertEqual(market(us), ("America/New_York", ["US"]))
        self.assertEqual(market(usd), ("America/New_York", ["US"]))
        self.assertEqual(market(pt), ("Europe/Lisbon", ["PT"]))
        self.assertEqual(json.loads((TMP / "brands" / de["brand"] / "strategy.json").read_text())["inputs"]["goal"], "leads")


class SlugTest(unittest.TestCase):
    def test_base_slug(self):
        for host, want in (("acme.com", "acme"), ("shop.acme.co.uk", "acme"), ("www.cmtm.co.il", "cmtm"),
                           ("acme.myshopify.com", "acme"), ("xn--grns-1ra.de", "gruns"), ("happy-garden.eu", "happygarden"),
                           ("x.com", "xcom"), ("24seven.com", "24seven")):
            self.assertEqual(otto_onboard.base_slug(host), want, host)
            self.assertRegex(otto_onboard.base_slug(host), otto_onboard.SLUG)
        self.assertEqual(otto_onboard.host_key("https://WWW.Grüns.de/path?q=1"), "xn--grns-1ra.de")

    def test_same_host_same_brand_and_clashes_get_the_tld(self):
        d = ap.load()
        self.assertEqual(otto_onboard.resolve_slug(d, "https://www.cmtm.co.il/about")[0], "cmtm")
        self.assertEqual(otto_onboard.resolve_slug(d, "cmtm.com"), ("cmtmcom", None))
        self.assertEqual(otto_onboard.resolve_slug(d, "demo.com")[0], "democom")                   # reserved
        stray = TMP / "brands" / "harbor"
        stray.mkdir(exist_ok=True)
        (stray / "scan.json").write_text(json.dumps({"final_url": "https://harbor.org/"}))
        self.assertEqual(otto_onboard.resolve_slug(d, "harbor.io")[0], "harborio")                 # folder belongs to harbor.org
        self.assertEqual(otto_onboard.resolve_slug(d, "https://harbor.org")[0], "harbor")           # …and is harbor.org's

    def test_bad_sites_are_refused(self):
        for bad in ("", "   ", "localhost", "http://intranet.local/", "ftp://acme.com", "http://user:pw@acme.com",
                    "acme .com", "http://acme.com:8080/", "acme", "x" * 400 + ".com", "['acme.com']", 'acme"x.com', "<svg>.com",
                    ["acme.com"], {"site": "acme.com"}):
            with self.assertRaises(ValueError, msg=bad):
                otto_onboard.site_url(bad)


class AnswersTest(unittest.TestCase):
    def test_defaults_and_bounds(self):
        a = otto_onboard.clean_answers({})                  # new onboarding approves by e-mail unless it picks otherwise
        self.assertEqual(a["channels"], {"meta": True, "google_ads": False, "telegram": False})
        self.assertEqual((a["approvals"], a["goal"], a["budget"]), ("email", None, None))
        self.assertEqual(otto_onboard.clean_answers({"channels": {"telegram": True}})["approvals"], "telegram")
        a = otto_onboard.clean_answers({"approvals": "app", "channels": {"telegram": False}, "objection": "x" * 900,
                                        "corrections": {"prices": "€10, €20 · €30", "language": "DE"}})
        self.assertEqual((a["approvals"], a["channels"]["telegram"], len(a["objection"])), ("app", False, 500))
        self.assertEqual((a["corrections"]["prices"], a["corrections"]["language"]), (["€10", "€20", "€30"], "de"))
        self.assertIsNone(otto_onboard.clean_answers({"tz": "Mars/Olympus"})["tz"])

    def test_malformed_values_raise(self):
        for bad in ({"goal": "world domination"}, {"budget": "lots"}, {"budget_amount": "ten"}, {"budget_amount": -5},
                    {"corrections": {"palette": ["red"]}}, {"corrections": {"language": "english"}}, {"corrections": []},
                    {"objection": {"a": 1}}, {"approvals": "fax"}, "not an object"):
            with self.assertRaises(ValueError, msg=bad):
                otto_onboard.clean_answers(bad)

    def test_errors_use_human_labels(self):
        for bad, want in (({"never_say": {"a": 1}}, "Words to avoid must be text"), ({"goal": "x"}, "Goal must be one of: More sales"),
                          ({"corrections": {"palette": ["red"]}}, "Colours must be hex codes"), ({"budget_amount": "ten"}, "Monthly ad budget")):
            with self.assertRaises(ValueError) as cm:
                otto_onboard.clean_answers(bad)
            self.assertIn(want, str(cm.exception))
            self.assertNotRegex(str(cm.exception), r"never_say|budget_amount|goal_note")

    def test_never_say_phrases(self):
        self.assertEqual(otto_onboard.never_say_phrases('cheap, "miracle cure"; re:.*\nguaranteed.'),
                         ["miracle cure", "cheap", "guaranteed"])
        self.assertEqual(otto_onboard.never_say_phrases("Please never compare us with the big chains in town or mention prices"), [])


class HttpTest(unittest.TestCase):
    def test_body_validation_rate_limit_and_cached_peek(self):
        otto_onboard._rl_last.clear()
        call = otto_onboard.http_create
        self.assertEqual(call(b"x" * (otto_onboard.MAX_BODY + 1), "1.1.1.1")[0], 413)
        self.assertEqual(call(b"{not json", "1.1.1.1")[0], 400)
        self.assertEqual(call(b"[]", "1.1.1.1")[0], 400)
        self.assertEqual(call(json.dumps({"site": "localhost"}).encode(), "1.1.1.1")[0], 400)
        self.assertEqual(call(json.dumps({"site": "ok.com", "answers": {"goal": "x"}}).encode(), "1.1.1.1")[0], 400)
        seen = []
        peek = lambda url: seen.append(url) or {"url": url, "title": "Peek Only", "palette": ["#111111"]}
        with fake_web({}):
            code, res = quiet(call, json.dumps({"site": "peek-only.net", "answers": {}, "peek": {"title": "client says"}}).encode(),
                              "2.2.2.2", cached_peek=peek)
            self.assertEqual(code, 200)
            self.assertEqual((res["scan"]["source"], res["name"]), ("peek", "Peek Only"))      # the server's peek, not the client's
            self.assertEqual(seen, ["https://peek-only.net"])
            self.assertEqual(quiet(call, json.dumps({"site": "peek-only.net"}).encode(), "2.2.2.2")[0], 429)
            self.assertEqual(quiet(call, json.dumps({"site": "peek-only.net"}).encode(), "3.3.3.3")[0], 200)


class TypedSiteTest(unittest.TestCase):
    """What a buyer types at step 1 (found in the 2026-10 scan QA): their Instagram, an e-mail address, a bare domain that only
    answers as www., a free Wix site under a path, a Dutch shop with translations."""

    def setUp(self):
        otto_onboard._rl_last.clear()

    def body(self, site, **answers):
        return json.dumps({"site": site, "answers": answers}).encode()

    def test_a_page_on_instagram_is_no_brand(self):
        """instagram.com/<name> once became brand "instagram" — every later Instagram user got "already set up"."""
        with fake_web({"instagram.com": canned("instagram.com", "Instagram")}):
            for i, typed in enumerate(("instagram.com/lot61coffee", "https://www.instagram.com/other/", "linktr.ee/bakkerij")):
                code, res = quiet(otto_onboard.http_create, self.body(typed), f"5.5.5.{i}")
                self.assertEqual((code, res["error"]), (400, otto_onboard.PLATFORM_PAGE), typed)
        self.assertFalse(any(b["url"] in ("instagram.com", "linktr.ee") for b in ap.load()["brands"]))

    def test_an_email_address_and_a_private_address_say_what_to_do(self):
        code, res = quiet(otto_onboard.http_create, self.body("jan@bakkerij-typed.nl"), "5.5.6.1")
        self.assertEqual((code, res["error"]), (400, otto_onboard.EMAIL_TYPED))
        code, res = quiet(otto_onboard.http_create, self.body("10.0.0.1"), "5.5.6.2")
        self.assertEqual((code, res["error"]), (400, otto_onboard.NOT_READABLE), "never 'unsupported or unsafe url'")

    def test_a_bare_domain_that_only_answers_on_www(self):
        read = []
        with fake_web({"www-only.nl": canned("www-only.nl", "Www Only", langs=("nl",))}):
            otto_scan.host_status = lambda u: "ok" if "//www." in u else "not_found"
            orig_scan = otto_scan.scan
            otto_scan.scan = lambda url, **kw: read.append(url) or orig_scan(url, **kw)
            code, res = quiet(otto_onboard.http_create, self.body("www-only.nl"), "5.5.7.1")
        self.assertEqual((code, read), (200, ["https://www.www-only.nl"]))
        self.assertEqual(brand_of(res["brand"])["url"], "www-only.nl")

    def test_brand_language_is_what_the_site_is_written_in(self):
        """A Dutch shop with German and English copies was "NL/DE" (hreflang, alphabetical); Loavies came out "EN/ES"."""
        dutch = canned("translated-shop.nl", "Vertaald", langs=("nl", "de", "en", "fr"))
        dutch["content_languages"] = ["nl"]
        older = canned("older-scan.nl", "Oud", langs=("nl", "de"))           # a scan.json from before content_languages
        with fake_web({"translated-shop.nl": dutch, "older-scan.nl": older}):
            _, a = quiet(otto_onboard.http_create, self.body("translated-shop.nl"), "5.5.8.1")
            _, b = quiet(otto_onboard.http_create, self.body("older-scan.nl"), "5.5.8.2")
        self.assertEqual((brand_of(a["brand"])["lang"], brand_of(b["brand"])["lang"]), ("NL", "NL"))

    def test_a_free_wix_site_keeps_its_path(self):
        with fake_web({"jannekemoor.wixsite.com": canned("jannekemoor.wixsite.com", "Jannekes Bakkerij", langs=("nl",))}):
            code, res = quiet(otto_onboard.http_create, self.body("jannekemoor.wixsite.com/bakkerij"), "5.5.9.1")
        self.assertEqual(code, 200)
        self.assertEqual(brand_of(res["brand"])["url"], "jannekemoor.wixsite.com/bakkerij", "the rescan reads the site, not a 404")
        self.assertEqual(otto_onboard.host_key("jannekemoor.wixsite.com/bakkerij"), "jannekemoor.wixsite.com")


class PublicOnboardTest(unittest.TestCase):
    """/otto-onboard has no login: it may create a brand, never change one (a paying client's name, scan corrections, proof,
    strategy and never-say list would otherwise be anyone's to rewrite)."""

    def setUp(self):
        otto_onboard._rl_last.clear()
        otto_onboard._public_creates.clear()

    def body(self, site, **answers):
        return json.dumps({"site": site, "answers": answers}).encode()

    def test_existing_brand_is_refused_and_untouched(self):
        before = ap.brand(ap.load(), "cmtm")
        data_before = (TMP / "data.json").read_text()
        with fake_web({"cmtm.co.il": canned("cmtm.co.il", "Hacked")}):
            code, res = quiet(otto_onboard.http_create, self.body("https://www.cmtm.co.il/", corrections={"name": "Hacked Inc",
                              "proof": ["FDA approved cure"]}, never_say="CMTM"), "9.9.9.9", public=True)
        self.assertEqual(code, 409)
        self.assertNotIn("Hacked", json.dumps(res))
        self.assertEqual(ap.brand(ap.load(), "cmtm"), before)
        self.assertEqual((TMP / "data.json").read_text(), data_before)
        for f in ("compliance.json", "scan.json", "strategy.json", "brand-profile.md", "brand-profile.draft.md", "logo.svg", "logo.png"):
            self.assertFalse((TMP / "brands" / "cmtm" / f).exists(), f"{f}: no scan, strategy, profile or compliance rewrite")
        d = ap.load()
        self.assertFalse(any(c.get("id", "").endswith("-cmtm") for c in d.get("connections", [])), "no connections added")
        self.assertFalse(any(r.get("brand") == "cmtm" for r in d.get("recommendations", [])), "no next-step cards added")
        # the same through the HTTP route, with a renamed site spelling and a parallel attempt
        import otto_api
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            otto_onboard._rl_last.clear()
            r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/otto-onboard", method="POST",
                                       data=self.body("HTTPS://CMTM.co.il/about", corrections={"name": "X"}),
                                       headers={"Content-Type": "application/json", "Origin": "https://dash.monyflow.work"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                with fake_web({"cmtm.co.il": canned("cmtm.co.il", "Hacked")}):
                    urllib.request.urlopen(r, timeout=10)
            self.assertEqual(cm.exception.code, 409)
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual((TMP / "data.json").read_text(), data_before)
        with self.assertRaises(otto_onboard.Exists):
            otto_onboard.create("cmtm.co.il", {}, scan=False, allow_update=False)

    def test_public_create_works_once_then_is_create_only(self):
        with fake_web({"fresh-public.com": canned("fresh-public.com", "Fresh")}):
            code, res = quiet(otto_onboard.http_create, self.body("fresh-public.com", goal="sales"), "8.8.4.4", public=True)
            self.assertEqual((code, res["created"]), (200, True))
            otto_onboard._rl_last.clear()
            code, _ = quiet(otto_onboard.http_create, self.body("fresh-public.com", corrections={"name": "Renamed"}), "8.8.4.4",
                            public=True)
            self.assertEqual(code, 409)
            self.assertEqual(brand_of(res["brand"])["name"], "Fresh")
            # the signed-in route still updates (idempotent re-run)
            code, res2 = quiet(otto_onboard.http_create, self.body("fresh-public.com", corrections={"name": "Renamed"}), "8.8.4.5")
        self.assertEqual((code, res2["created"], brand_of(res["brand"])["name"]), (200, False, "Renamed"))

    def test_hourly_cap_on_public_creates(self):
        otto_onboard._public_creates[:] = [time.time()] * otto_onboard.PUBLIC_CREATES_PER_HOUR
        with fake_web({"capped.com": canned("capped.com", "Capped")}):
            code, _ = quiet(otto_onboard.http_create, self.body("capped.com"), "7.7.7.7", public=True)
        self.assertEqual(code, 429)
        self.assertFalse(any(b["url"] == "capped.com" for b in ap.load()["brands"]))

    def test_rate_limit_comes_before_dns(self):
        looked = []
        with fake_web({}):
            otto_scan.host_status = lambda u: looked.append(u) or "ok"
            quiet(otto_onboard.http_create, self.body("dns-once.com"), "6.6.6.6")
            self.assertEqual(quiet(otto_onboard.http_create, self.body("dns-twice.com"), "6.6.6.6")[0], 429)
        self.assertEqual(looked, ["https://dns-once.com"], "a rate-limited request never reaches the resolver")

    def test_font_corrections_must_be_family_names(self):
        with self.assertRaises(ValueError):
            otto_onboard.clean_answers({"corrections": {"fonts": ["Inter;}body{background:url(https://evil.example)"]}})
        self.assertEqual(otto_onboard.clean_answers({"corrections": {"fonts": ["Playfair Display"]}})["corrections"]["fonts"],
                         ["Playfair Display"])


class RouteTest(unittest.TestCase):
    def test_api_routes_to_onboard_with_origin_and_type_checks(self):
        """/otto-api/onboard (signed-in) and /otto-onboard (a buyer with no login yet) share the handler and the rules."""
        import otto_api
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        calls, orig, public = [], otto_onboard.http_create, []
        otto_onboard.http_create = lambda raw, ip, cached_peek=None, **kw: (
            calls.append(json.loads(raw)) or public.append(kw.get("public")) or (200, {"brand": "t", "created": True}))
        origin = (os.environ.get("OTTO_ALLOWED_ORIGINS") or "https://dash.monyflow.work").split(",")[0].strip()

        def post(path, body, headers):
            r = urllib.request.Request(base + path, data=body, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(r, timeout=10) as x:
                    return x.status
            except urllib.error.HTTPError as e:
                return e.code
        try:
            body = json.dumps({"site": "shop.example"}).encode()
            ok = {"Content-Type": "application/json", "Origin": origin}
            for path in ("/otto-onboard", "/otto-api/onboard"):
                self.assertEqual(post(path, body, ok), 200)
                self.assertEqual(post(path, body, {"Content-Type": "text/plain", "Origin": origin}), 415)
                self.assertEqual(post(path, body, {"Content-Type": "application/json", "Origin": "https://evil.example"}), 403)
            self.assertEqual(post("/otto-onboard", b"x" * (otto_onboard.MAX_BODY + 1), ok), 413)
            self.assertEqual(calls, [{"site": "shop.example"}] * 2)
            self.assertEqual(public, [True, False], "only the public route is create-only")
        finally:
            otto_onboard.http_create = orig
            srv.shutdown(); srv.server_close()


class WorkspaceTest(unittest.TestCase):
    def test_first_week_prefers_real_planned_posts(self):
        with fake_web({"weekly.com": canned("weekly.com", "Weekly")}):
            r = quiet(otto_onboard.create, "weekly.com", {})
        d = ap.load()
        b = ap.brand(d, r["brand"])
        tz = ap.brand_tz(b)
        review = otto_onboard.first_review_at(tz)
        slot = (review + timedelta(days=1)).strftime("%Y-%m-%dT09:00")
        with ap.transaction(sync=False) as d:
            p = ap.add_post(d, r["brand"], "Product", "ig", slot, "Real hook")
        week, _ = otto_onboard.first_week(ap.load(), r["brand"])
        self.assertEqual([x.get("id") for x in week], [p["id"]])

    def test_real_repo_is_never_touched(self):
        with fake_web({"isolation.eu": canned("isolation.eu", "Isolation")}):
            quiet(otto_onboard.create, "isolation.eu", ANSWERS)
        self.assertEqual({f: _fingerprint(PLATFORM / f) for f in ("data.json", "index.html")}, _SAVED["repo"])
        self.assertEqual(_listing(REPO / "brands"), _SAVED["repo_brands"])
        self.assertTrue(Path(ap.DATA).resolve().is_relative_to(TMP.resolve()))
        self.assertTrue((TMP / "brands" / "isolation").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
