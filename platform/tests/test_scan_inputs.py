#!/usr/bin/env python3
"""The moment a prospect types their website: what people actually type (otto_scan.normalize_url, e-mail addresses, pages
on Instagram / Facebook / Etsy, the www. twin), the public /otto-peek answers (otto_api.peek), and what the scanner reads
from a real-looking small-business page — name, language, colours, fonts, logo, socials, proof, prices, "in your words".
Every case here was found on a real site in the 2026-10 scan QA (research/SCAN-QA-2026-10.md); the pages are local fixtures.
Stdlib unittest; the only network is a 127.0.0.1 server started here; nothing is written anywhere.

  cd platform && python3 tests/test_scan_inputs.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, http.server, json, os, sys, tempfile, threading, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-scan-inputs-test-"))
for _k, _v in {"OTTO_DATA": TMP / "data.json", "OTTO_HTML": TMP / "index.html", "OTTO_BRANDS": TMP / "brands"}.items():
    os.environ.setdefault(_k, str(_v))           # only if no earlier suite set them: this suite writes nothing
sys.path.insert(0, str(PLATFORM))
import otto_api, otto_onboard, otto_scan          # noqa: E402

# ------------------------------------------------------------------------------------------- fixture pages (local server)

DUTCH = """<!doctype html><html lang="en-US"><head><title>Home • Bakkerij De Molen • Utrecht</title>
<meta name="description" content="Bakkerij De Molen">
<link rel="alternate" hreflang="de" href="/de/"><link rel="alternate" hreflang="en" href="/en/">
<style>:root{--wp--preset--color--pale-pink:#f78da7;--wp--preset--color--vivid-red:#cf2e2e;--e-global-color-primary:#7A3E1D}
body{font-family:'ETmodules';color:#7a3e1d} .b{font-family:"Lora",serif;background:#E8C07D} .i{font-family:Icomoon} .s{font-family:Star}
.w{font-family:WooCommerce} .d{color:#2ea3f2}</style>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":["Bakery","Organization"],
"name":"Bakkerij De Molen","url":"https://bakkerijdemolen.nl"}]}</script></head>
<body><a href="#main">Ga naar de inhoud</a>
<link rel="alternate" type="application/json+oembed" href="/wp-json/oembed/1.0/embed?url=x&#038;format=xml&#039;">
<img src="/wp-content/uploads/google-white-logo.png" alt="Google reviews logo"><img src="/files/molen_logo_{width}x.png" alt="Bakkerij De Molen logo">
<nav><a href="/over-ons">Over ons</a> <a href="/over-ons/">Over ons</a> <a href="/en/about-us">About</a> <a href="/menukaart">Menukaart</a></nav>
<h1>Ambachtelijk brood uit Utrecht</h1>
<p>Wij bakken elke ochtend ons brood met de hand. Bij ons kun je terecht voor zuurdesem, taart en een goede kop koffie, en
onze bakkers staan al sinds 1952 voor je klaar. Bekijk ook onze webshop en bestel jouw taart voor het weekend.</p>
<p>Wij zijn niet alleen een bakkerij maar ook een plek om samen te komen. Onze winkel is zes dagen per week open en de koffie
staat altijd klaar. We bakken met meel van de molen uit de buurt, zonder toevoegingen, en dat proef je.</p>
<p>Sinds 1952 een familiebedrijf met vakmanschap, in de vierde generatie.</p>
<p>Taart van de week €0,00 · Appeltaart €24,50 · Zuurdesembrood €4,95</p>
<p>De winkel gaat even dicht voor een verbouwing: vanaf maandag zijn we weer open.</p>
<div class="reviews">Rotterdam 4.7 869 reviews Heerlijk brood en super vriendelijk personeel, wij komen elke zaterdag terug!</div>
<a href="https://www.facebook.com/profile.php?id=100064">Facebook</a> <a href="https://pinterest.com/pin/create/button/?url=x">Pin</a>
<a href="https://instagram.com/wix">Instagram</a> <a href="https://www.instagram.com/p/Cx123/">post</a>
<a href="https://www.tiktok.com/@bakkerijdemolen">TikTok</a>
</body></html>"""

PAGES = {"/": ("text/html; charset=utf-8", DUTCH),
         "/over-ons": ("text/html", "<html><title>Over ons</title><body><p>Wij zijn een familiebakkerij.</p></body></html>"),
         "/en/about-us": ("text/html", "<html><title>About</title><body><p>We are a family bakery and you will love our bread.</p></body></html>"),
         "/parked": ("text/html", '<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>'),
         "/api": ("application/json", '{"slideshow": {"title": "Sample Slide Show", "author": "Yours Truly"}}'),
         "/doc.pdf": ("application/pdf", "%PDF-1.4 not a page"),
         "/hop": ("text/html", '<html><head><meta http-equiv="refresh" content="0; url=/real"></head><body></body></html>'),
         "/lander": ("text/html", "<html><head><title>127.0.0.1</title></head><body><h1>127.0.0.1</h1><p>This domain may be for sale. "
                                  "Related searches: bakery bread cake coffee shop near me.</p></body></html>"),
         "/real": ("text/html", "<html><head><title>Real Site | Cafe Noord</title></head><body><p>Real content of the cafe "
                                "with a long enough sentence to read.</p></body></html>")}


class _Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ctype, body = PAGES.get(self.path.split("?")[0], ("text/html", ""))
        body = body.encode()
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


_SRV = {}


def setUpModule():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _SRV["srv"] = srv


def tearDownModule():
    _SRV["srv"].shutdown(); _SRV["srv"].server_close()


@contextlib.contextmanager
def local_site():
    """The SSRF guard lets 127.0.0.1 through on the fixture's port only, for the duration of the block."""
    port = _SRV["srv"].server_address[1]
    orig = (otto_scan.ip_ok, otto_scan.ALLOWED_PORTS)
    otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig[0](ip)
    otto_scan.ALLOWED_PORTS = orig[1] | {port}
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        otto_scan.ip_ok, otto_scan.ALLOWED_PORTS = orig


# ------------------------------------------------------------------------------------------------------------- tests

class WhatPeopleTypeTest(unittest.TestCase):
    def test_normalize_url(self):
        n = otto_scan.normalize_url
        for typed, want in (("example.com", "https://example.com"), ("  Example.COM.  ", "https://example.com"),
                            ("HTTPS://EXAMPLE.COM/Shop?utm=x#top", "https://example.com/Shop?utm=x"),
                            ("http//example.com", "http://example.com"), ("https:/example.com", "https://example.com"),
                            ("<https://example.com/>", "https://example.com/"), ("www.example.com", "https://www.example.com")):
            self.assertEqual(n(typed), want, typed)
        for bad in ("ftp://example.com", "file:///etc/passwd", "http://", "javascript:alert(1)", "jan@bakkerij.nl", "example.com:8080"):
            with self.assertRaises(otto_scan.Blocked, msg=bad):
                otto_scan.check_url(n(bad))

    def test_email_addresses_give_their_domain_but_never_a_mailbox(self):
        self.assertEqual(otto_scan.email_site("jan@bakkerij.nl"), ("bakkerij.nl", False))
        self.assertEqual(otto_scan.email_site("mailto:Info@Kapsalon-Anna.NL"), ("kapsalon-anna.nl", False))
        self.assertEqual(otto_scan.email_site("jan@gmail.com"), ("gmail.com", True))
        self.assertEqual(otto_scan.email_site("piet@ziggo.nl"), ("ziggo.nl", True))
        self.assertEqual(otto_scan.email_site("bakkerij.nl"), (None, False))
        self.assertEqual(otto_scan.email_site("user:pass@example.com"), (None, False))

    def test_pages_on_someone_elses_platform(self):
        for u in ("instagram.com/lot61coffee", "https://www.facebook.com/brotherhubbard", "m.facebook.com/x", "linktr.ee/somebakery",
                  "www.etsy.com/shop/x", "sites.google.com/view/bakkerij", "maps.app.goo.gl/x", "www.treatwell.nl/salon/x",
                  "www.thuisbezorgd.nl/menu/x", "wix.com", "www.squarespace.com"):
            self.assertTrue(otto_scan.platform_page(u), u)
        for u in ("bakkerij.nl", "jannekemoor.wixsite.com/bakkerij", "bigcitysmallworld.squarespace.com", "acme.myshopify.com",
                  "facebookfan.nl", "www.instagramfotograaf.nl", "lot61.com"):
            self.assertIsNone(otto_scan.platform_page(u), u)

    def test_onboarding_says_what_is_wrong(self):
        for typed, word in (("jan@bakkerij.nl", "e-mail"), ("instagram.com/lot61", "social network"), ("exa mple.com", "spaces"),
                            ("x" * 301 + ".com", "too long"), ("bakkerij", "domain"), ("http://", "not a website address")):
            with self.assertRaises(ValueError, msg=typed) as e:
                otto_onboard.site_url(typed)
            self.assertIn(word, str(e.exception), typed)
        self.assertEqual(otto_onboard.site_url("Bakkerij.nl."), "https://bakkerij.nl")

    def test_a_wix_free_site_keeps_its_path(self):
        self.assertEqual(otto_scan.site_path("jannekemoor.wixsite.com/bakkerij/contact"), "/bakkerij")
        self.assertEqual(otto_scan.site_path("bakkerij.nl/over-ons"), "")
        self.assertIsNone(otto_scan.twin_url("https://jannekemoor.wixsite.com/bakkerij"))
        self.assertEqual(otto_scan.twin_url("https://bakkerij.nl/x"), "https://www.bakkerij.nl/x")
        self.assertEqual(otto_scan.twin_url("https://www.bakkerij.nl"), "https://bakkerij.nl")
        self.assertIsNone(otto_scan.twin_url("https://10.0.0.1/"))

    def test_the_user_agent_does_not_say_scan(self):
        """thefumbally.ie (and WAFs on the ModSecurity CRS) answer 403 to a user agent with 'Scan' in it."""
        self.assertNotRegex(otto_scan.UA, r"(?i)scan")
        self.assertEqual(otto_scan.accept_language("www.bakkerij.nl"), "nl,en;q=0.8")
        self.assertTrue(otto_scan.accept_language("3fe.com").startswith("en"))


class PeekEndpointTest(unittest.TestCase):
    def setUp(self):
        otto_api._peek_cache.clear(); otto_api._peek_last.clear()
        self.orig = (otto_scan.host_status, otto_scan.peek)

    def tearDown(self):
        otto_scan.host_status, otto_scan.peek = self.orig
        otto_api._peek_cache.clear(); otto_api._peek_last.clear()

    def test_email_and_platform_pages_never_reach_the_network(self):
        otto_scan.host_status = lambda u: self.fail("no DNS for " + u)
        otto_scan.peek = lambda u, deadline=None: self.fail("never fetched")
        self.assertEqual(otto_api.peek("jan@bakkerij.nl", "192.0.2.1"),
                         (400, {"error": "that is an e-mail address", "code": "email", "site": "bakkerij.nl"}))
        self.assertEqual(otto_api.peek("jan@gmail.com", "192.0.2.2")[1]["site"], None)
        code, body = otto_api.peek("instagram.com/lot61coffee", "192.0.2.3")
        self.assertEqual((code, body["code"], body["platform"]), (400, "platform_page", "Instagram"))

    def test_the_www_twin_is_read_when_the_bare_domain_does_not_resolve(self):
        otto_scan.host_status = lambda u: "ok" if "//www." in u else "not_found"
        read = []
        otto_scan.peek = lambda u, deadline=None: read.append(u) or {"url": u + "/", "title": "Bakkerij", "name": "Bakkerij"}
        code, body = otto_api.peek("bakkerij.nl", "192.0.2.4")
        self.assertEqual((code, read), (200, ["https://www.bakkerij.nl"]))
        self.assertEqual(otto_api._cached_peek("bakkerij.nl")["name"], "Bakkerij", "cached under what the visitor typed")

    def test_a_failed_read_says_what_to_do(self):
        otto_scan.host_status = lambda u: "ok"
        for err, code in (("empty page (a parked domain or a site that is not built yet)", "empty"),
                          ("HTTP Error 403: Forbidden", "blocked"), ("HTTP Error 429: Too Many Requests", "blocked"),
                          ("not a web page (application/pdf)", "file"), ("deadline reached", "unreadable")):
            otto_api._peek_last.clear()
            otto_scan.peek = lambda u, deadline=None, e=err: {"url": u, "error": e}
            status, body = otto_api.peek("broken.example", "192.0.2.5")
            self.assertEqual((status, body["code"]), (502, code), err)
        self.assertIn("parked", otto_api.peek_reason("empty page (a parked domain)"))


class ReadThePageTest(unittest.TestCase):
    """One Dutch bakery page with everything the corpus found wrong on real sites."""

    @classmethod
    def setUpClass(cls):
        with local_site() as base:
            cls.s = otto_scan.scan(base + "/", pages=5)
            cls.base = base

    def test_dutch_text_beats_a_themes_english_lang_attribute(self):
        self.assertEqual(self.s["languages"][0], "nl")
        self.assertEqual(self.s["content_languages"], ["nl"], "hreflang alternates are translations, not what the brand writes in")
        self.assertIn("de", self.s["languages"])

    def test_pages_read_once_and_in_the_homes_language(self):
        paths = [p.split(self.base, 1)[1] for p in self.s["pages"]]
        self.assertEqual(paths.count("/over-ons"), 1, paths)
        self.assertNotIn("/over-ons/", paths)
        self.assertNotIn("/en/about-us", paths, "an English copy of a page would make a Dutch site look bilingual")

    def test_name_from_json_ld_and_the_title_part_that_is_the_brand(self):
        self.assertEqual(self.s["identity"]["name"], "Bakkerij De Molen")
        for idn, host, want in (({"title": "Home • LOT61 Coffee Roasters • Amsterdam"}, "lot61.com", "LOT61 Coffee Roasters"),
                                ({"title": "Fysiotherapie en manuele therapie in Utrecht - Praktijk Wittevrouwen"},
                                 "praktijk-wittevrouwen.nl", "Praktijk Wittevrouwen"),
                                ({"title": "Bloemen bezorgen door de lokale bloemist; Bloemenhuis Hofman"}, "bloemenhuishofman.nl",
                                 "Bloemenhuis Hofman"),
                                ({"title": "LOAVIES | Shop Fashion Online", "site_name": "loavies.com"}, "www.loavies.com", "LOAVIES"),
                                ({"title": "Quality Prescription Glasses from €145 | Ace & Tate"}, "www.aceandtate.com", "Ace & Tate"),
                                ({"title": "Winkel 43: Café & beroemde appeltaart"}, "winkel43.nl", "Winkel 43"),
                                ({"title": "Dille & Kamille Webshop - Cadeaus", "site_name": "Dille & Kamille Webshop"},
                                 "www.dille-kamille.nl", "Dille & Kamille"),
                                ({"title": ""}, "hutspot.com", "Hutspot")):
            self.assertEqual(otto_scan.brand_name_from(idn, host), want, idn)

    def test_industry_from_schema_type_and_dutch_words(self):
        self.assertEqual(self.s["industry"], "Restaurant & food", "a Bakery in JSON-LD, whatever the renovation notice says")
        g = otto_scan.industry_guess
        self.assertEqual(g("Keogh's Crisps", "Hand-cooked crisps", ["Our Range"], ["Shop", "Learn more"],
                           "learn more " * 80 + "crisps snacks shop")[0], "Restaurant & food")
        self.assertNotEqual(g("Oatly", "An oat drink company", ["Products"], ["Legal", "Privacy"], "legal legal products")[0],
                            "Legal & finance")
        self.assertEqual(g("FysioDomstad | Fysiotherapie Utrecht", "Pijn? Klachten?", ["Fysiotherapie Utrecht"], ["Behandelingen"],
                           "fysiotherapie manuele therapie dry needling klachten training")[0], "Clinic & medical")
        self.assertEqual(g("Loodgietersbedrijf in Rotterdam", "Lekkage, verstopping, cv-storing", ["24/7 bereikbaar"], [],
                           "loodgieter lekkage verstopping cv-ketel")[0], "Home & construction")
        self.assertEqual(g("Schorem Barbier Rotterdam", "Haircuts and shaves", ["Barbershop Schorem"], ["Shop", "Cart"],
                           "barber haircut shop cart checkout")[0], "Beauty & spa")
        self.assertNotIn(g("Butlers Chocolates", "Chocolate gifts", ["The icons"], ["Shop", "Cart"],    # was "Hotel & travel"
                           "add to cart checkout shipping shop chocolate guest travel retail")[0], ("Hotel & travel", "Education & courses"))
        self.assertNotEqual(g("Huel", "Nutritionally complete food", ["Learn"], ["Shop", "Learn"],
                              "learn " * 60 + "add to cart checkout shop nutritionally complete protein vitamins")[0], "Education & courses")

    def test_colours_are_the_brands_not_entities_or_defaults(self):
        pal = [p["hex"] for p in self.s["visual"]["palette"]]
        self.assertEqual(pal[0], "#7A3E1D", "the theme's primary variable leads")
        self.assertIn("#E8C07D", pal)
        for junk in ("#003388", "#003399", "#F78DA7", "#CF2E2E", "#2EA3F2"):     # &#038; / &#039; entities, WP + Divi defaults
            self.assertNotIn(junk, pal)

    def test_fonts_are_typefaces_not_icon_glyphs(self):
        self.assertEqual(self.s["visual"]["fonts"], ["Lora"])

    def test_logo_is_the_brands_not_googles(self):
        self.assertEqual(self.s["visual"]["logo"], self.base + "/files/molen_logo_600x.png")

    def test_socials_are_profiles(self):
        self.assertEqual(self.s["socials"], {"facebook": "https://facebook.com/profile.php?id=100064",
                                             "tiktok": "https://tiktok.com/@bakkerijdemolen"})

    def test_prices_proof_and_words(self):
        self.assertEqual(self.s["commerce"]["prices"], ["€24,50", "€4,95"], "an empty cart's €0,00 is no price")
        self.assertTrue(any("1952" in t for t in self.s["trust"]), self.s["trust"])
        self.assertFalse(any("Ga naar de inhoud" in t or "Home •" in t for t in self.s["trust"]), self.s["trust"])
        self.assertFalse(any("869 reviews" in q for q in self.s["quotes"]), self.s["quotes"])
        self.assertEqual(self.s["identity"]["description_source"], "page", "a meta description that is just the name is replaced")
        self.assertTrue(self.s["identity"]["description"].startswith("Wij bakken elke ochtend"), self.s["identity"]["description"])

    def test_no_website_there(self):
        with local_site() as base:
            self.assertIn("empty page", otto_scan.scan(base + "/parked")["error"])
            self.assertIn("empty page", otto_scan.scan(base + "/lander")["error"], "a registrar's parking page (bakkerij.com)")
            self.assertIn("not a web page", otto_scan.scan(base + "/api")["error"])
            self.assertIn("not a web page", otto_scan.scan(base + "/doc.pdf")["error"])
            hop = otto_scan.scan(base + "/hop", pages=0)
            self.assertEqual((hop["final_url"], hop["identity"]["name"]), (base + "/real", "Real Site"))

    def test_the_peek_carries_the_name_and_language(self):
        with local_site() as base:
            p = otto_scan.peek(base + "/")
        self.assertEqual((p["name"], p["languages"][0], p["industry"]), ("Bakkerij De Molen", "nl", "Restaurant & food"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
