#!/usr/bin/env python3
"""Country × industry compliance baselines (otto_baselines + otto_compliance): real Dutch and English sentences that must be
blocked, held for review or held for a missing disclosure, sentences that must pass, and false-positive guards (a cat treat
is not a treatment, the FDA / EU disclaimers are not claims, "groene thee" is not a green claim). Also: how a brand's
countries and industries are resolved, clearances and per-item reviews, fail-closed rules files, campaign audiences
(countries + age), and the summary the onboarding response and the owner console carry.

  cd platform && python3 tests/test_country_compliance.py

Stdlib unittest, no network, a throwaway workspace. Under discover, setUpModule pins the module paths it touches.
"""
import contextlib, io, json, os, shutil, sys, tempfile, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-country-compliance-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": ""}
_SAVED = {}

# id: (brands[].countries or None, url, scan industry, title, extra scan fields)
BRANDS = {
    "nl-shop": (["NL"], "fietsenwinkel.nl", "E-commerce & retail", "Fietsenwinkel Utrecht", {"platform": "shopify"}),
    "nl-supp": (["NL"], "vitaalpuur.nl", "Supplements & nutrition", "VitaalPuur voedingssupplementen", {}),
    "nl-bar": (["NL"], "cafedegracht.nl", "Restaurant & food", "Café De Gracht", {}),
    "nl-wine": (["NL"], "wijnhandelvandam.nl", "E-commerce & retail", "Wijnhandel Van Dam", {}),
    "nl-clinic": (["NL"], "kliniekmooi.nl", "Clinic & medical", "Kliniek Mooi — botox en fillers", {}),
    "nl-salon": (["NL"], "studioglow.nl", "Beauty & spa", "Studio Glow huidverzorging", {}),
    "nl-casino": (["NL"], "oranjecasino.nl", "Unknown (?)", "Oranje Casino", {}),
    "ie-dental": (["IE"], "dublinsmile.ie", "Clinic & medical", "Dublin Smile Dental", {}),
    "ie-pub": (["IE"], "thebrazenhead.ie", "Restaurant & food", "The Brazen Head", {}),
    "ie-supp": (["IE"], "greenisle.ie", "Supplements & nutrition", "Green Isle Vitamins", {}),
    "ie-trades": (["IE"], "murphyroofing.ie", "Home & construction", "Murphy Roofing", {}),
    "be-clinic": (["BE"], "skinclinicgent.be", "Clinic & medical", "Skin Clinic Gent — fillers", {}),
    "eu-cbd": (None, "calmdrops.com", "CBD & hemp wellness", "Calm Drops CBD", {"commerce": {"currency": "EUR"}}),
    "us-supp": (["US"], "gummyco.com", "Supplements & nutrition", "GummyCo", {}),
}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    sys.path.insert(0, str(PLATFORM))
    global ap, oc, BL, otto_admin
    import ap, otto_compliance as oc, otto_baselines as BL, otto_admin    # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    brands = []
    for bid, (ccs, url, industry, title, extra) in BRANDS.items():
        (TMP / "brands" / bid).mkdir(parents=True, exist_ok=True)
        scan = dict({"industry": industry, "identity": {"title": title}, "final_url": "https://" + url}, **extra)
        (TMP / "brands" / bid / "scan.json").write_text(json.dumps(scan, ensure_ascii=False))
        b = {"id": bid, "name": title, "url": url, "status": "active", "pillars": ["A"]}
        if ccs:
            b["countries"] = ccs
        brands.append(b)
    (TMP / "data.json").write_text(json.dumps({"brands": brands, "posts": [], "recommendations": [], "campaigns": []}))


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def ids(violations):
    return sorted({v.get("id") or v["rule"] for v in violations})


def rules_file(bid, **raw):
    f = TMP / "brands" / bid / "compliance.json"
    if raw:
        f.write_text(json.dumps(dict({"banned": [], "required_disclaimer": None}, **raw), ensure_ascii=False))
    elif f.exists():
        f.unlink()


class Base(unittest.TestCase):
    def check(self, bid, text, context="posts", **kw):
        return oc.check_texts(bid, [text] if isinstance(text, str) else text, context, **kw)

    def assertHeld(self, bid, text, rule_id, severity=None, context="posts", **kw):
        v = self.check(bid, text, context, **kw)
        hit = [x for x in v if x.get("id") == rule_id]
        self.assertTrue(hit, f"{bid}: expected {rule_id} for {text!r}, got {ids(v)}")
        if severity:
            self.assertEqual(hit[0]["severity"], severity)
        self.assertTrue(hit[0]["rule"] and hit[0]["why"] and hit[0]["source"].startswith("https://"))
        return hit[0]

    def assertClean(self, bid, text, context="posts", **kw):
        v = self.check(bid, text, context, **kw)
        self.assertEqual(v, [], f"{bid}: {text!r} should pass, got {ids(v)}")

    def assertNot(self, bid, text, rule_id, context="posts", **kw):
        v = self.check(bid, text, context, **kw)
        self.assertNotIn(rule_id, ids(v), f"{bid}: {text!r} must not trip {rule_id}")


class ResolutionTest(Base):
    def test_countries_from_record_domain_currency_language(self):
        r = oc.rules("nl-shop")
        self.assertEqual((r["countries"], r["countries_source"]), (["NL"], "brand"))
        self.assertEqual(oc.countries("eu-cbd")[0], ["EU"], "a .com shop pricing in EUR gets the EU-wide rules only")
        self.assertEqual(oc.countries("x", {}, {"brands": [{"id": "x", "url": "bakkerij.nl"}]}, {}), (["NL"], "domain"))
        self.assertEqual(oc.countries("x", {}, {"brands": [{"id": "x", "url": "shop.ie"}]}, {}), (["IE"], "domain"))
        self.assertEqual(oc.countries("x", {}, {"brands": [{"id": "x", "url": "brand.eu"}]}, {}), (["EU"], "domain"))
        self.assertEqual(oc.countries("x", {}, {"brands": []}, {"languages": ["nl"]}), (["NL"], "language"))
        self.assertEqual(oc.countries("x", {}, {"brands": []}, {"languages": ["en"]}), ([], "unknown"))
        self.assertEqual(oc.countries("x", {"countries": ["be"]}, {"brands": []}, {}), (["BE"], "compliance.json"))

    def test_industry_tags_and_evidence(self):
        self.assertEqual(oc.industries("nl-supp")["supplements"], "industry")
        self.assertEqual(oc.industries("nl-wine")["alcohol"], "keywords")
        self.assertIn("goods", oc.industries("nl-wine"))
        self.assertEqual(oc.industries("nl-clinic")["aesthetic"], "keywords")
        self.assertIn("clinic", oc.industries("nl-clinic"))
        self.assertIn("gambling", oc.industries("nl-casino"))
        self.assertEqual(oc.industries("nl-shop")["goods"], "industry")
        self.assertNotIn("alcohol", oc.industries("nl-bar"), "a café is hospitality; alcohol rules follow its copy")
        self.assertEqual(oc.industries("x", {"industries": ["Alcohol"]}), {"alcohol": "compliance.json"})

    def test_non_eu_brands_get_no_country_baselines(self):
        self.assertEqual(oc.applicable(oc.rules("us-supp")), [])
        self.assertEqual(self.check("us-supp", "Our gummies prevent colds and flu. Last chance: 30% off!"), [])


class DiseaseClaimsTest(Base):
    BLOCKED = [("nl-shop", "Onze kruidenthee helpt tegen verkoudheid."), ("nl-salon", "Deze olie geneest eczeem binnen een week."),
               ("nl-shop", "Vitamine D voorkomt botontkalking."), ("nl-salon", "Magnesiumolie verlicht spierpijn na het sporten."),
               ("nl-bar", "Onze gemberthee tegen griep en hoofdpijn."), ("nl-shop", "Een echt wondermiddel voor je huid."),
               ("ie-pub", "Our hot toddy cures a cold."), ("eu-cbd", "CBD drops that fight anxiety and insomnia."),
               ("ie-trades", "This water filter prevents cancer."), ("eu-cbd", "Our balm heals eczema overnight.")]
    ALLOWED = [("nl-shop", "Vitamine C draagt bij tot de normale werking van het immuunsysteem."),
               ("ie-pub", "Treat yourself to a cold pint of stout on the terrace."), ("eu-cbd", "New cat treats: salmon flavour."),
               ("nl-shop", "Helpt tegen vlekken op je aanrecht."), ("nl-bar", "Een warme soep tegen de kou."),
               ("ie-pub", "Beat the cold with our winter stew."), ("nl-shop", "Voorkomt kalkaanslag in je waterkoker."),
               ("ie-trades", "Stop the cold calls: book a roofer in two clicks."), ("eu-cbd", "Treat your family to a Sunday roast."),
               ("nl-shop", "Onze fietsen voorkomen rugpijn niet, een goede zithouding wel.")]

    def test_disease_claims_are_blocked_in_nl_ie_and_eu(self):
        for bid, text in self.BLOCKED:
            with self.subTest(text=text):
                self.assertHeld(bid, text, "eu-disease-claim", "block")

    def test_everyday_language_is_not_a_claim(self):
        for bid, text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertNot(bid, text, "eu-disease-claim")

    def test_disclaimers_are_never_claims(self):
        rules_file("eu-cbd")
        for disc in ("These statements have not been evaluated by the Food and Drug Administration. This product is not intended "
                     "to diagnose, treat, cure, or prevent any disease.",
                     "This product is not intended to diagnose, treat, cure or prevent any disease.",
                     "Dit product is niet bedoeld om ziekten te diagnosticeren, behandelen, genezen of voorkomen.",
                     "Dieses Produkt ist nicht dazu bestimmt, Krankheiten zu diagnostizieren, zu behandeln, zu heilen oder zu verhindern.",
                     "Een voedingssupplement is geen vervanging van een gevarieerd en evenwichtig voedingspatroon en een gezonde levensstijl.",
                     "Lees voor gebruik de bijsluiter."):
            with self.subTest(disc=disc[:40]):
                self.assertClean("eu-cbd", "Calm evenings start with two drops. " + disc)
        self.assertHeld("eu-cbd", "It cures anxiety. This product is not intended to diagnose, treat, cure or prevent any disease.",
                        "eu-disease-claim")

    def test_negated_claim_is_not_a_claim(self):
        self.assertNot("nl-shop", "Onze thee geneest geen verkoudheid, maar smaakt heerlijk.", "eu-disease-claim")
        self.assertNot("eu-cbd", "CBD does not cure insomnia; it is a daily ritual.", "eu-disease-claim")
        self.assertHeld("eu-cbd", "Not only calming: it also cures insomnia.", "eu-disease-claim")

    def test_clinics_may_say_what_they_treat(self):
        self.assertClean("ie-dental", "We treat gum disease and toothache. Book a check-up in Rathmines.")
        self.assertHeld("ie-dental", "Our whitening cures yellow teeth.", "ie-cure-rejuvenation", "needs-review")


class HealthProductsTest(Base):
    def test_unauthorised_wording_needs_review(self):
        for bid, text in (("eu-cbd", "Our drops boost your immune system."), ("ie-supp", "A 7-day detox for your gut."),
                          ("ie-supp", "Clinically proven collagen."), ("eu-cbd", "Superfood for your skin.")):
            with self.subTest(text=text):
                self.assertHeld(bid, text, "eu-health-claim-wording", "needs-review")
        self.assertClean("ie-supp", "Vitamin C contributes to the normal function of the immune system.")

    def test_weight_loss_and_doctor_endorsements_are_blocked(self):
        self.assertHeld("ie-supp", "Lose 5kg in 2 weeks with our shakes.", "eu-food-weightloss-doctor", "block")
        self.assertHeld("ie-supp", "Lose 5kg in 2 weeks with our shakes.", "ie-weight-loss-period", "block")
        self.assertHeld("ie-trades", "Our crew lost 5 kg in 3 weeks of summer jobs — lose 5kg in 3 weeks yourself!",
                        "ie-weight-loss-period")
        self.assertHeld("ie-supp", "Recommended by doctors across Ireland.", "eu-food-weightloss-doctor")
        self.assertNot("ie-trades", "Recommended by builders across Ireland.", "eu-food-weightloss-doctor")

    def test_nl_supplements_need_keuringsraad_then_the_number(self):
        rules_file("nl-supp")
        post = "Magnesium draagt bij tot een normale werking van de spieren."
        v = self.assertHeld("nl-supp", post, "nl-kag-preapproval", "needs-review")
        self.assertEqual(v["rule"], "Health product ad in NL: needs Keuringsraad pre-approval")
        self.assertHeld("nl-supp", post, "nl-kag-number", "disclose")
        with contextlib.redirect_stdout(io.StringIO()):
            oc.clear("nl-supp", "keuringsraad", "KOAG/KAG K-12345/06 (brand page)")
        self.assertNot("nl-supp", post, "nl-kag-preapproval")
        self.assertHeld("nl-supp", post, "nl-kag-number")
        self.assertClean("nl-supp", post + " KOAG/KAG K-12345/06")
        # ads: every ad is pre-vetted on its own, whatever the brand page has
        self.assertHeld("nl-supp", post + " KOAG/KAG K-12345/06", "nl-kag-ad-preapproval", "needs-review", context="ads")
        rules_file("nl-supp")

    def test_guarantees_are_blocked_for_health_and_beauty(self):
        self.assertHeld("nl-salon", "Gegarandeerd resultaat na één behandeling, zonder bijwerkingen.", "health-guarantee", "block")
        self.assertHeld("ie-dental", "Guaranteed results or your money back.", "health-guarantee")
        self.assertNot("nl-shop", "Gegarandeerd resultaat: je fiets rijdt als nieuw.", "health-guarantee")


class PrescriptionAndAestheticsTest(Base):
    def test_prescription_medicines_are_never_advertised(self):
        for bid, text in (("nl-clinic", "Botox-behandeling nu bij Kliniek Mooi."), ("ie-dental", "Anti-wrinkle injections now in Dublin 6."),
                          ("nl-shop", "Afslankprik zonder wachtlijst."), ("eu-cbd", "A natural alternative to Ozempic.")):
            with self.subTest(text=text):
                self.assertHeld(bid, text, "eu-prescription-medicine", "block")

    def test_aesthetic_rules_nl(self):
        self.assertHeld("nl-clinic", "Lipfillers voor je eindexamenfeest!", "aesthetic-minors", "block")
        self.assertHeld("nl-clinic", "Voor en na: het resultaat na twee weken.", "nl-aesthetic-before-after", "needs-review")
        self.assertHeld("nl-clinic", "Huidverbetering met een peeling door onze arts.", "nl-aesthetic-big", "disclose")
        self.assertNot("nl-clinic", "Huidverbetering met een peeling door Dr. A. Jansen, cosmetisch arts, BIG 12345678901.",
                       "nl-aesthetic-big")
        c = {"id": "cp-x", "brand": "nl-clinic", "name": "Peeling najaar", "audience": {"countries": ["NL"], "age": [16, 45]},
             "creative": {"headlines": ["Peeling door Dr. Jansen, BIG 12345678901"]}}
        v = [x for x in oc.check_campaign(c) if x["id"] == "aesthetic-minors"]
        self.assertTrue(v and v[0]["match"] == "age 16+", "an aesthetic ad may not reach under-18s")
        c["audience"]["age"] = [25, 60]
        self.assertNotIn("aesthetic-minors", ids(oc.check_campaign(c)))

    def test_belgium_bans_aesthetic_advertising_also_via_a_dutch_campaign(self):
        self.assertHeld("be-clinic", "Lipfillers bij ons in Gent.", "be-aesthetic-ban", "block")
        self.assertHeld("be-clinic", "Médecine esthétique à Gand.", "be-aesthetic-ban")
        self.assertHeld("be-clinic", "Welkom in onze praktijk.", "be-aesthetic-practice", "block")
        c = {"id": "cp-y", "brand": "nl-clinic", "name": "Najaar", "audience": {"countries": ["NL", "BE"], "age": [25, 60]},
             "creative": {"headlines": ["Lipfillers door onze arts, BIG 12345678901"]}}
        self.assertIn("be-aesthetic-ban", ids(oc.check_campaign(c)), "Flanders spillover must get the Belgian rules")
        c["audience"]["countries"] = ["NL"]
        self.assertNotIn("be-aesthetic-ban", ids(oc.check_campaign(c)))


class AlcoholTest(Base):
    def setUp(self):
        rules_file("nl-bar")

    def test_nl_alcohol_needs_nix18_and_age_gate(self):
        post = "Nieuwe wijnkaart! Kom vrijdag proeven."
        self.assertHeld("nl-bar", post, "nl-alcohol-nix18", "disclose")
        self.assertHeld("nl-bar", post, "nl-alcohol-age-gate", "needs-review")
        self.assertClean("nl-bar", "Onze nieuwe lunchkaart staat online.")
        rules_file("nl-bar", clearances={"age_gate_18": "Instagram + Facebook 18+ since 2026-09-30"})
        self.assertClean("nl-bar", post + " NIX18")
        c = {"id": "cp-b", "brand": "nl-bar", "name": "Wijnavond", "audience": {"countries": ["NL"], "age": [16, 65]},
             "creative": {"headlines": ["Wijnproeverij vrijdag NIX18"]}}
        v = [x for x in oc.check_campaign(c) if x["id"] == "nl-alcohol-age-gate"]
        self.assertEqual((v[0]["severity"], v[0]["match"]), ("block", "age 16+"))
        c["audience"]["age"] = [18, 65]
        self.assertEqual(oc.check_campaign(c), [])

    def test_alcohol_promotions_blocked_nl_and_ie(self):
        for bid, text in (("nl-bar", "Gratis biertje bij elke burger."), ("nl-bar", "Happy hour: 2 voor 1 cocktails."),
                          ("ie-pub", "Two for one cocktails until 8pm.")):
            with self.subTest(text=text):
                self.assertHeld(bid, text, "alcohol-themes", "block")
        for bid, text in (("nl-bar", "Onbeperkt drinken voor €25."), ("ie-pub", "Bottomless brunch with unlimited prosecco."),
                          ("ie-pub", "Free pints for the first 20 in the door!")):
            with self.subTest(text=text):
                self.assertHeld(bid, text, "alcohol-excess", "block")
        self.assertNot("nl-shop", "2 voor 1 op alle fietslampjes.", "alcohol-themes")      # no drink in sight

    def test_off_trade_discount_over_25_percent(self):
        self.assertHeld("nl-wine", "30% korting op alle rode wijn.", "nl-alcohol-offtrade-discount", "block")
        self.assertNot("nl-wine", "Tweede fles halve prijs op alle rosé.", "nl-alcohol-offtrade-discount")
        self.assertNot("nl-wine", "20% korting op alle wijn.", "nl-alcohol-offtrade-discount")
        self.assertNot("nl-bar", "30% korting op alle wijn bij je diner.", "nl-alcohol-offtrade-discount")  # on-trade

    def test_ie_needs_a_responsible_drinking_message(self):
        self.assertHeld("ie-pub", "Live music and pints this Friday.", "ie-alcohol-responsible", "disclose")
        self.assertClean("ie-pub", "Live music and pints this Friday. Please enjoy responsibly.")
        self.assertClean("ie-pub", "Live music this Friday from 9pm.")

    def test_pending_irish_health_warnings_are_listed_not_enforced(self):
        rows = {r["id"]: r for r in oc.summary("ie-pub")["baselines"]}
        self.assertEqual(rows["ie-alcohol-health-warnings"]["status"], "pending")
        self.assertNotIn("ie-alcohol-health-warnings", ids(self.check("ie-pub", "Pints tonight. Enjoy responsibly.")))


class GamblingTest(Base):
    def test_gambling_is_not_a_vertical_and_offers_are_blocked(self):
        self.assertHeld("nl-casino", "Welkom bij Oranje Casino.", "eu-gambling", "block")
        self.assertHeld("nl-shop", "Gratis spins bij je eerste bestelling!", "eu-gambling-offer", "block")
        self.assertHeld("ie-pub", "Place your bets for Cheltenham at the bar.", "eu-gambling-offer")
        self.assertClean("nl-shop", "Niet meer gokken welke framemaat je nodig hebt.")


class ConsumerLawTest(Base):
    def test_price_reductions_need_the_30_day_reference(self):
        rules_file("nl-shop")
        for text in ("Van €49,95 voor €29,95", "20% korting op alle helmen", "Nu €29,95 (was €49,95)", "Black Friday: alles -30%"):
            with self.subTest(text=text):
                self.assertHeld("nl-shop", text, "eu-price-reduction-30d", "needs-review")
        self.assertClean("nl-shop", "Nu met gratis verzending door heel Nederland.")
        self.assertNot("ie-trades", "Roof repairs from €250. Winter sale on gutters!", "eu-price-reduction-30d")  # a service
        rules_file("nl-shop", clearances={"prior_price_30d": "Shopify compare-at = lowest price of the last 30 days"})
        self.assertClean("nl-shop", "20% korting op alle helmen")
        rules_file("nl-shop")

    def test_hidden_prices_and_trials(self):
        self.assertHeld("nl-shop", "Onderhoudsbeurt €89 excl. btw", "eu-price-incl-vat", "needs-review")
        self.assertHeld("ie-trades", "Gutter clean €120 plus VAT", "eu-price-incl-vat")
        self.assertHeld("nl-shop", "Eerste maand gratis fietslease!", "eu-free-trial-price", "disclose")
        self.assertNot("nl-shop", "Eerste maand gratis fietslease, daarna €24,95 per maand.", "eu-free-trial-price")
        self.assertNot("ie-trades", "Bikes for sale in Cork.", "eu-price-reduction-30d")

    def test_urgency_needs_review_per_item_and_an_edit_reopens_it(self):
        rules_file("nl-shop")
        text = "Laatste kans: nog maar 3 stuks!"
        self.assertHeld("nl-shop", text, "eu-urgency-scarcity", "needs-review")
        with ap.transaction(sync=False) as d:
            d["posts"].append({"id": "ns-001", "brand": "nl-shop", "pillar": "A", "platform": "ig", "hook": text, "status": "draft",
                               "slot": "2031-01-01T09:00", "compliance_block": {"rules": ["x"], "at": "2026-09-30T10:00:00Z"}})
        kind, left = oc.review("ns-001", ["eu-urgency-scarcity"], by="max", note="3 left in Shopify on 30.09")
        p = ap.post(ap.load(), "ns-001")
        self.assertEqual((kind, left, p["status"], "compliance_block" in p), ("post", [], "pending_approval", False))
        self.assertEqual(oc.check_post(p), [])
        p["hook"] = "Laatste kans: nog maar 2 stuks!"
        self.assertIn("eu-urgency-scarcity", ids(oc.check_post(p)), "the review covers the reviewed text only")
        with self.assertRaises(ValueError):
            oc.review("ns-001", ["eu-disease-claim"])                         # a block rule is fixed by rewriting
        with self.assertRaises(ValueError):
            oc.review("ns-001", ["no-such-rule"])

    def test_green_claims(self):
        self.assertHeld("nl-shop", "Onze fietstassen zijn milieuvriendelijk.", "eu-generic-green-claim", "needs-review")
        self.assertHeld("nl-shop", "Een duurzame keuze voor de stad.", "eu-generic-green-claim")
        self.assertHeld("nl-shop", "Wij verzenden CO2-neutraal.", "eu-offset-neutral-claim", "block")
        self.assertHeld("ie-trades", "Our vans are carbon neutral.", "eu-offset-neutral-claim")
        self.assertClean("nl-shop", "Verpakking van 100% gerecycled karton.")
        self.assertClean("nl-bar", "Verse muntthee en groene thee.")

    def test_influencer_disclosure_nl_and_ie(self):
        self.assertHeld("nl-shop", "Gebruik mijn code SANNE10 voor 10% korting op je helm.", "nl-influencer-disclosure", "disclose")
        self.assertHeld("nl-shop", "#spon Gebruik mijn code SANNE10 voor een helm.", "nl-influencer-disclosure")
        self.assertNot("nl-shop", "AD | Gebruik mijn code SANNE10 voor een helm.", "nl-influencer-disclosure")
        self.assertNot("nl-shop", "Betaalde samenwerking met @fietsenwinkel — gebruik mijn code SANNE10.", "nl-influencer-disclosure")
        self.assertHeld("ie-trades", "Use my code AOIFE15 for a free survey #spon", "ie-influencer-disclosure", "disclose")
        self.assertNot("ie-trades", "#Ad Use my code AOIFE15 for a free roof survey.", "ie-influencer-disclosure")
        late = "Use my code AOIFE15 for a free roof survey. " + "Great crew, tidy work, fair price. " * 4 + "#ad"
        self.assertHeld("ie-trades", late, "ie-influencer-disclosure")          # the label goes first, not at the end
        self.assertClean("nl-shop", "Gebruik kortingscode WELKOM10 bij je eerste bestelling.")   # the brand's own post

    def test_cosmetic_free_from(self):
        self.assertHeld("nl-salon", "Onze serum is parabenenvrij en hypoallergeen.", "eu-cosmetic-free-from", "needs-review")
        self.assertClean("nl-salon", "Hydraterende crème met hyaluronzuur, parfumvrij.")


class RulesFileAndSummaryTest(Base):
    def test_malformed_baseline_settings_fail_closed(self):
        for bad in ({"clearances": ["keuringsraad"]}, {"baselines_off": "all"}, {"countries": "NL"}, {"industries": "alcohol"}):
            with self.subTest(bad=bad):
                rules_file("nl-shop", **bad)
                v = self.check("nl-shop", "Nieuwe fietsen binnen.")
                self.assertTrue(v and v[0]["rule"] == "compliance.json invalid", v)
        rules_file("nl-shop", baselines_off={"eu-urgency-scarcity": "only runs stock-true countdowns from Shopify"})
        self.assertNot("nl-shop", "Laatste kans: nog maar 3 stuks!", "eu-urgency-scarcity")
        row = next(r for r in oc.summary("nl-shop")["baselines"] if r["id"] == "eu-urgency-scarcity")
        self.assertEqual((row["status"], row["off_reason"]), ("off", "only runs stock-true countdowns from Shopify"))
        rules_file("nl-shop")
        with self.assertRaises(ValueError):
            oc.clear("nl-shop", "not-a-key", "x")

    def test_brand_rules_and_baselines_merge(self):
        rules_file("nl-shop", banned=["re:\\bgoedkoopste\\b"])
        v = self.check("nl-shop", "De goedkoopste fiets, milieuvriendelijk geproduceerd.")
        self.assertEqual(ids(v), ["eu-generic-green-claim", "re:\\bgoedkoopste\\b"])
        self.assertEqual(v[0]["rule"], "re:\\bgoedkoopste\\b", "the brand's own rules come first")
        rules_file("nl-shop")

    def test_summary_for_onboarding_and_console(self):
        rules_file("nl-supp")
        s = oc.summary("nl-supp")
        self.assertEqual((s["countries"], s["countries_source"]), (["NL"], "brand"))
        self.assertIn("supplements", s["industries"])
        rows = {r["id"]: r for r in s["baselines"]}
        self.assertTrue({"nl-kag-preapproval", "eu-disease-claim", "eu-health-claim-wording"} <= set(rows))
        self.assertNotIn("ie-alcohol-responsible", rows)
        self.assertEqual(rows["nl-kag-preapproval"]["source"], "https://keuringsraad.nl/wp-content/uploads/2025/10/CAG-2019-def.pdf")
        standing = [x["id"] for x in s["standing_holds"]]
        self.assertIn("nl-kag-preapproval", standing, "the owner must see up front that every post waits for the number")
        # onboarding before the files exist: in-memory scan + the country it detected
        s2 = oc.summary("nl-new", d={"brands": []}, scan={"industry": "Restaurant & food", "identity": {"title": "Bar Noord"}},
                        countries=["NL"])
        self.assertEqual((s2["countries"], s2["countries_source"]), (["NL"], "onboarding"))
        self.assertIn("nl-alcohol-nix18", [r["id"] for r in s2["baselines"]])
        # AI media counts from post.media_ai
        d = {"brands": [{"id": "nl-supp", "countries": ["NL"]}], "posts": [
            {"id": "a", "brand": "nl-supp", "media_ai": {"assets/posts/a.jpg": {"generated": True, "kind": "image", "marked": "xmp"}}},
            {"id": "b", "brand": "nl-supp", "media_ai": {"assets/reels/b.mp4": {"generated": True, "kind": "voice", "marked": False}}}]}
        self.assertEqual(oc.summary("nl-supp", d=d)["ai_media"], {"generated": 2, "marked": 1, "unmarked": ["assets/reels/b.mp4"]})

    def test_console_drill_down_carries_it(self):
        from datetime import datetime, timezone
        d = ap.load()
        rows = otto_admin.brand_health(d, {"secrets": {}}, [], datetime.now(timezone.utc))
        row = next(r for r in rows if r["id"] == "ie-pub")
        self.assertEqual(row["compliance"]["countries"], ["IE"])
        self.assertIn("ie-alcohol-responsible", [b["id"] for b in row["compliance"]["baselines"]])

    def test_file_block_says_why_and_what_to_do(self):
        v = self.check("nl-shop", "Laatste kans! Wij verzenden CO2-neutraal.")
        with ap.transaction(sync=False) as d:
            r = oc.file_block(d, "nl-shop", "ns-9 “Laatste kans”", v, "test", post="ns-9")
        self.assertTrue(r["title"].startswith("Compliance hold"))
        self.assertIn("Blocked before it reached you", r["why"])
        self.assertIn("Needs review: Urgency or scarcity claim", r["why"])
        self.assertIn("NL baselines", r["why"])
        self.assertEqual(r["compliance"], ["eu-urgency-scarcity", "eu-offset-neutral-claim"])

    def test_every_rule_is_well_formed(self):
        self.assertIsNone(oc.BASELINE_ERROR)
        seen = set()
        for r in BL.RULES:
            with self.subTest(rule=r["id"]):
                self.assertNotIn(r["id"], seen)
                seen.add(r["id"])
                self.assertIn(r["severity"], oc.SEVERITIES)
                self.assertTrue(r["title"] and r["why"] and r["fix"])
                srcs = r["source"] if isinstance(r["source"], list) else [r["source"]]
                self.assertTrue(srcs and all(s.startswith("https://") for s in srcs))
                self.assertTrue(set(r["countries"]) <= BL.EU | {"EU"})
                tags = {t for t, _, _ in BL.INDUSTRY_TAGS} | {"*"}
                self.assertTrue(set(r.get("industries") or ["*"]) | set(r.get("not_industries") or []) <= tags)
                if r["severity"] == "disclose":
                    self.assertTrue(r.get("require"), "a disclose rule names what must be in the text")


if __name__ == "__main__":
    unittest.main()
