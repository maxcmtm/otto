#!/usr/bin/env python3
"""Otto scanner — "Drop your URL. Otto reads your business."

  otto_scan.py <url> [--slug <slug>] [--pages 5] [--json] [--no-profile] [--force]
  otto_scan.py --peek <url>            # compact JSON (used by /otto-peek on the landing + dashboard)

Pure stdlib. Fetches the homepage plus up to N internal pages (about / products / pricing /
reviews / faq / blog / contact / menu / treatments), then extracts the brand DNA:
identity (title, description, og:*), languages, platform, VISUAL IDENTITY (palette from
inline + linked CSS, logo, fonts), socials, contact, currency + price points, trust anchors,
review-style quotes, headings, navigation, and an industry guess.

Every fetch (homepage, subpages, CSS) is SSRF-guarded: each redirect hop is re-validated (http/https, ports
80/443, public IPs only — ip.is_global) and the connection is pinned to the validated address. --peek honours
a total deadline (used by the public /otto-peek endpoint).

Writes brands/<slug>/scan.json and — if the brand has no profile yet — a
brands/<slug>/brand-profile.md draft following BRAND-PROFILE-TEMPLATE.md (AUTO sections
filled from the scan, inference sections marked for the creative engine to complete).
"""
import http.client, ipaddress, json, os, re, socket, ssl, sys, threading, time, unicodedata, urllib.parse, zlib
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).parent
BRANDS = Path(os.environ.get("OTTO_BRANDS") or HERE.parent / "brands")
TEMPLATE = BRANDS / "BRAND-PROFILE-TEMPLATE.md"
# "Scan" in a user agent trips common WAF rules for vulnerability scanners (ModSecurity CRS and hosting firewalls answer
# 403 to "…OttoScan/1.0": found on thefumbally.ie, 2026-10). OttoBot still says who is reading.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 OttoBot/1.0")
# a site that picks its language from Accept-Language should answer in the language of its own country (.nl → Dutch):
# that is the language Otto writes the brand's posts in
_TLD_LANG = {"nl": "nl", "be": "nl", "de": "de", "at": "de", "ch": "de", "fr": "fr", "es": "es", "it": "it", "pt": "pt",
             "il": "he", "pl": "pl", "dk": "da", "se": "sv", "no": "nb", "fi": "fi"}


def accept_language(host):
    tld = (host or "").rstrip(".").rsplit(".", 1)[-1].lower()
    lang = _TLD_LANG.get(tld)
    return f"{lang},en;q=0.8" if lang else "en,nl;q=0.8,de;q=0.7"
PAGE_KEYS = ["about", "story", "team", "product", "shop", "collection", "service", "treatment", "menu",
             "pricing", "price", "plans", "review", "testimonial", "faq", "blog", "contact", "course",
             # localized slugs (de / pt / nl / it / fr / es) — without them a European site is read as its homepage only
             "ueber", "uber-uns", "leistung", "preis", "angebot", "bewertung", "kontakt", "kurs",
             "sobre", "servico", "preco", "aulas", "curso", "testemunho", "contacto", "contato", "loja",
             "over-ons", "dienst", "prijs", "prijz", "winkel", "cursus",
             "chi-siamo", "servizi", "prezzi", "listino", "progetti", "contatti", "recensioni", "corsi", "negozio",
             "a-propos", "tarif", "prestation", "avis", "boutique", "servicios", "precios", "tienda", "opiniones"]
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
GENERIC_FONTS = {"inherit", "initial", "sans-serif", "serif", "monospace", "system-ui", "-apple-system",
                 "blinkmacsystemfont", "segoe ui", "roboto", "helvetica neue", "helvetica", "arial",
                 "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "cursive", "fantasy", "emoji", "math", "fangsong",
                 "var(--font-sans)", "unset", "revert", "sfmono-regular", "menlo", "consolas", "courier new", "courier",
                 "apple color emoji", "segoe ui emoji", "segoe ui symbol", "noto color emoji", "courier 10 pitch"}
# icon fonts (glyphs, not a typeface the brand writes in): Font Awesome, Material Icons / Symbols, "HemaSvgIcons", icomoon,
# Divi's ETmodules, WooCommerce's star font, Judge.me / Trustindex review widgets, Astra / Slick / Video.js glyphs, and the
# builders' placeholder / editor-UI families (Framer "Inter Placeholder", "Squarespace Ui Font") …
ICON_FONT = re.compile(r"icon|awesome|material.?symbols|glyph|dashicons|fontello|ionic|feather|remixicon|bootstrap.?icons|"
                       r"etmodules|icomoon|woocommerce|^star$|judgeme|^astra$|trustindex|video-?js|^slick$|swiper|eicons|revicons|"
                       r"themify|linearicons|lineicons|entypo|socicon|genericons|placeholder|ui.?font", re.I)
TRUST_WORDS = ["gmp", "iso 9001", "iso ", "fda", "lab tested", "lab-tested", "third-party", "third party",
               "certified", "certificate", "guarantee", "money-back", "money back", "free shipping",
               "kostenloser versand", "משלוח חינם", "secure checkout", "ssl", "since 19", "since 20",
               "years of experience", "award", "trustpilot", "google reviews", "5 stars", "5-star",
               "★", "⭐", "reviews", "bewertungen", "המלצות", "בוגרים", "graduates", "clients", "customers served",
               # Dutch (the NL launch): "sinds 1952", "30 jaar ervaring", certified, quality marks, guarantees
               "sinds 19", "sinds 20", "jaar ervaring", "jaren ervaring", "gecertificeerd", "keurmerk", "erkend", "garantie",
               "geld terug", "gratis verzending", "beoordelingen", "tevreden klanten", "familiebedrijf", "big-geregistreerd"]
PROMO_RE = re.compile(r"((?<!\d)\d{1,2}\s?%\s?(?:off|rabatt|הנחה|discount)|free shipping|kostenloser versand|black friday|"
                      r"cyber monday|new arrival|limited time|bundle|gift card|use code [A-Z0-9]{3,}|sale\b)", re.I)
# amounts with thousands separators first ("2.900 €", "₪18,500", "€1,234.56") — the plain form alone read them as "900 €" / "₪18,50"
AMOUNT = r"(?:\d{1,3}(?:[.,\u00a0\u202f]\d{3})+(?:[.,]\d{2})?(?!\d)|\d{1,5}(?:[.,]\d{2})?)"
PRICE_RE = re.compile(r"(?:(?:€|\$|£|₪|EUR|USD|ILS|NIS|GBP|CHF|NOK|SEK|DKK)\s?" + AMOUNT + r")|"
                      r"(?:" + AMOUNT + r"\s?(?:€|₪|\$|£|EUR|USD|ILS|NIS|kr\b|CHF))")
# Keywords per industry. Generic words every site uses are out: "learn" ("Learn more" buttons), "menu" (the hamburger
# button), "legal" / "tax" / "trading" (footers, "incl. tax"), "booking" / "program" / "sign up" / "platform" / "training"
# (salons book, gyms train, newsletters sign up) — the 2026-10 scan QA read a crisps maker and Huel as "Education", a
# chocolatier as "Hotel & travel" and Oatly as "Legal & finance" on them. Dutch words cover the NL launch.
INDUSTRIES = {
    "CBD & hemp wellness": ["cbd", "hemp", "cannabinoid", "cbg", "cbn", "full spectrum", "broad spectrum"],
    "Restaurant & food": ["restaurant", "menukaart", "our menu", "the menu", "lunch menu", "dinner menu", "food menu",
                          "reservation", "reserveren", "chef", "dish", "dishes", "brunch", "lunch", "breakfast", "ontbijt",
                          "dinner", "diner", "pizza", "sushi", "café", "cafe", "bistro", "bakery", "bakkerij", "bakker",
                          "patisserie", "pâtisserie", "banketbakker", "coffee", "koffie", "coffee shop", "coffee roasters",
                          "espresso", "barista", "ice cream", "gelato", "chocolate", "chocolates", "chocolatier", "chocolade",
                          "crisps", "snacks", "cookies", "koekjes", "taart", "taarten", "gebak", "brood", "bread", "sourdough",
                          "cakes", "deli", "delicatessen", "grocer", "catering", "takeaway", "afhaalmenu", "eten en drinken",
                          "keuken open", "wine bar", "wijnbar", "borrel", "pub", "brewery", "brouwerij"],
    "Clinic & medical": ["clinic", "patient", "treatment", "dental", "dentist", "doctor", "appointment", "therapy",
                         "botox", "aesthetic", "laser", "physio", "physiotherapy", "physiotherapist", "physiotherapists",
                         "fysiotherapie", "fysiotherapeut", "fysiotherapeuten", "fysio", "fysiopraktijk", "manuele therapie",
                         "osteopathy", "osteopaat", "chiropractor", "chiropractie", "podotherapie", "podotherapeut", "podiatrist",
                         "dry needling", "huisarts", "klachten", "zorgverzekeraar", "verwijzing", "sports injury", "injuries",
                         "rehabilitation", "revalidatie", "psycholoog", "psychologist", "orthodontist",
                         "מרפאה", "מרפאת", "רופא", "קליניקה", "טיפולים",
                         "zahnarzt", "zahnarztpraxis", "zahnmedizin", "arztpraxis", "patienten", "clínica", "dentista",
                         "tandarts", "tandartspraktijk", "studio dentistico", "odontoiatria", "cabinet dentaire", "médecin"],
    "Education & courses": ["courses", "online course", "academy", "college", "students", "curriculum", "e-learning",
                            "diploma", "webinar", "lessons", "enrol", "enroll", "enrolment", "graduates", "masterclass",
                            "מכללה", "מכללת", "קורס", "בוגרים",
                            "לימודים", "לימודי", "הכשרה", "הכשרת", "דיפלומה", "סילבוס", "סטודנטים",
                            "kurs", "kurse", "ausbildung", "weiterbildung", "curso", "cursos", "aulas", "escola", "formação",
                            "cursus", "cursussen", "opleiding", "opleidingen", "corso", "corsi", "scuola", "formazione", "école",
                            "formation", "escuela"],
    "Marketing & agency": ["marketing agency", "agency", "seo", "social media", "branding", "campaign", "content creation",
                           "autopilot", "advertising", "ads", "marketingbureau", "reclamebureau"],
    "Supplements & nutrition": ["supplement", "supplements", "vitamin", "vitamins", "multivitamin", "gummies", "gummy",
                                "superfood", "superfoods", "greens powder", "probiotic", "prebiotic", "collagen", "protein powder",
                                "nutrients", "daily nutrition", "electrolytes", "creatine", "adaptogen", "nahrungsergänzung",
                                "vitamine", "suplemento", "suplementos", "integratore", "integratori", "complément alimentaire",
                                "nutritionally complete", "complete nutrition", "meal replacement", "voedingssupplementen"],
    "E-commerce & retail": ["add to cart", "cart", "checkout", "shipping", "shop", "collection", "free shipping",
                            "returns", "warenkorb", "versand", "winkelwagen", "afrekenen", "verzending", "webshop", "bestellen",
                            "gratis verzending", "retourneren", "in winkelmand", "winkelmand", "florist", "bloemist", "bouquet",
                            "boeket", "flower delivery", "bloemen bezorgen",
                            "carrinho", "loja online", "envio", "carrello", "spedizione", "panier", "livraison", "carrito", "envío"],
    "Real estate": ["real estate", "property", "apartment", "villa", "sqm", "m²", "for sale", "listing", "mortgage", "נדל",
                    "makelaar", "makelaardij", "te koop", "koopwoning", "estate agent"],
    "SaaS & software": ["software", "api", "integration", "integrations", "dashboard", "saas", "workflow", "no-code"],
    "Fitness & gym": ["gym", "fitness", "workout", "membership", "trainer", "yoga", "pilates", "crossfit", "sportschool",
                      "personal training", "personal trainer", "groepslessen", "bootcamp", "boxing", "spinning", "kickboksen"],
    "Beauty & spa": ["spa", "massage", "facial", "salon", "beauty", "nails", "lashes", "med spa", "skincare", "barber",
                     "barbershop", "barbier", "kapper", "kappers", "kapsalon", "hair salon", "hairdresser", "hairdressers",
                     "hairdressing", "haircut", "haircuts", "knippen", "schoonheidssalon", "schoonheidsspecialist", "wimpers",
                     "nagels", "manicure", "pedicure", "gezichtsbehandeling", "nail bar", "brows", "waxing", "harsen", "balayage"],
    "Legal & finance": ["attorney", "lawyer", "law firm", "solicitor", "solicitors", "accountant", "accountancy", "bookkeeping",
                        "tax advice", "tax return", "financial advice", "financial advisor", "insurance broker", "advocaat",
                        "advocatenkantoor", "notaris", "boekhouding", "belastingadvies", "hypotheekadvies", "financieel advies",
                        "rechtsanwalt", "steuerberater", "forex", "עורך דין"],
    "Hotel & travel": ["hotel", "hostel", "b&b", "bed and breakfast", "bed & breakfast", "resort", "our rooms", "hotel rooms",
                       "suites", "check-in", "guesthouse", "guest house", "travel agency", "holiday home", "vakantiehuis", "camping",
                       "accommodation", "accommodatie", "overnachten", "book your stay"],
    "Coaching & consulting": ["coach", "coaching", "consulting", "consultancy", "mentor", "mastermind", "1:1", "advies op maat"],
    "Home & construction": ["renovation", "construction", "roofing", "plumbing", "solar", "interior design", "furniture",
                            "kitchens", "plumber", "loodgieter", "loodgietersbedrijf", "lekkage", "verstopping", "cv-ketel",
                            "installateur", "elektricien", "electrician", "dakdekker", "roofer", "schilder", "schildersbedrijf",
                            "painter", "aannemer", "contractor", "badkamer", "bathroom", "boiler", "heating", "verwarming",
                            "warmtepomp", "heat pump", "zonnepanelen", "schoonmaakbedrijf", "glazenwasser", "hovenier",
                            "landscaping", "slotenmaker", "locksmith", "meubels",
                            "arredamento", "arredo", "ristrutturazione", "interni", "innenarchitektur", "renovierung",
                            "verbouwing", "remodelação", "decoração"],
    "Automotive": ["dealership", "vehicle", "tires", "garage", "car wash", "auto repair", "autobedrijf", "occasions", "apk",
                   "car dealer", "autogarage"],
}
# schema.org types a site declares in its JSON-LD (LocalBusiness subtypes …): the owner's own word for the business
SCHEMA_INDUSTRY = {
    **dict.fromkeys(("Restaurant", "Bakery", "CafeOrCoffeeShop", "FoodEstablishment", "BarOrPub", "IceCreamShop",
                     "FastFoodRestaurant", "Winery", "Brewery", "Distillery"), "Restaurant & food"),
    **dict.fromkeys(("HairSalon", "BeautySalon", "DaySpa", "NailSalon", "HealthAndBeautyBusiness", "TattooParlor"), "Beauty & spa"),
    **dict.fromkeys(("Physiotherapy", "MedicalClinic", "Dentist", "MedicalBusiness", "Physician", "Optician", "Hospital",
                     "MedicalOrganization", "Pharmacy", "Chiropractic"), "Clinic & medical"),
    **dict.fromkeys(("HealthClub", "ExerciseGym", "SportsClub"), "Fitness & gym"),
    **dict.fromkeys(("Plumber", "Electrician", "HomeAndConstructionBusiness", "HousePainter", "RoofingContractor",
                     "GeneralContractor", "HVACBusiness", "Locksmith", "MovingCompany", "FurnitureStore"), "Home & construction"),
    **dict.fromkeys(("LegalService", "Attorney", "Notary", "AccountingService", "FinancialService", "InsuranceAgency"),
                    "Legal & finance"),
    **dict.fromkeys(("Hotel", "LodgingBusiness", "BedAndBreakfast", "Hostel", "Resort", "TravelAgency", "Campground"), "Hotel & travel"),
    **dict.fromkeys(("RealEstateAgent",), "Real estate"),
    **dict.fromkeys(("AutoDealer", "AutoRepair", "AutomotiveBusiness", "AutoBodyShop"), "Automotive"),
    **dict.fromkeys(("EducationalOrganization", "School", "CollegeOrUniversity", "Course"), "Education & courses"),
    **dict.fromkeys(("Florist", "ClothingStore", "OnlineStore", "ShoeStore", "JewelryStore", "GardenStore", "PetStore",
                     "BookStore", "GiftShop"), "E-commerce & retail"),
}


# ---------------- fetching (SSRF-guarded) ----------------
# Every fetch — homepage, subpages, CSS, competitor pages — goes through guarded_get(): each hop (redirects
# included) must be http/https on port 80/443, must not name a local host, and must resolve ONLY to global
# unicast IPs (ip.is_global — rejects RFC1918, loopback, link-local/metadata 169.254/16, CGNAT 100.64/10,
# ULA, v4-mapped private …). The connection then goes to that validated IP (DNS pinned per request, with
# the real hostname for Host/SNI/cert checks), so a rebinding resolver cannot swap the address after the check.
# A watchdog shuts the connection down at the deadline (at most MAX_FETCH_SECONDS per fetch), so a server that
# trickles one byte per socket timeout cannot hold a worker; the body is read raw (Accept-Encoding: identity,
# nothing is ever decompressed) and never past `limit`.

ALLOWED_PORTS = {None, 80, 443}
BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".localdomain")
MAX_REDIRECTS = 5
READ_CHUNK = 65536
MAX_FETCH_SECONDS = 45
# Never a public web server, whatever this Python's ipaddress tables say: 3.9 calls 6to4 (2002::/16, which embeds any
# IPv4 incl. 127.0.0.1), 192.0.0.0/24 and the deprecated site-local fec0::/10 "global"; NAT64 prefixes reach IPv4
# behind a translator. Listed explicitly so the guard does not depend on the interpreter version.
_DENY_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4",
    "::/8", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20",
    "5f00::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8")]


class Blocked(Exception):
    pass


def normalize_url(u):
    """What a person typed → an absolute URL: https:// unless they said http://, a mistyped scheme repaired
    ("http//x", "https:/x"), another scheme kept as it is (check_url refuses it), scheme and host in lower case, no
    trailing dot on the host, no #fragment. The path and query stay (a page the owner pasted)."""
    u = str(u or "").strip().strip("<>\"'").strip()
    u = re.sub(r"^(https?)(?::/*|/+)(?=[^/\s])", lambda m: m.group(1).lower() + "://", u, count=1, flags=re.I)
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    try:
        p = urllib.parse.urlsplit(u)
        netloc = p.netloc if "@" in p.netloc else re.sub(r"\.(?=:\d*$|$)", "", p.netloc.lower())
        return urllib.parse.urlunsplit((p.scheme.lower(), netloc, p.path, p.query, ""))
    except ValueError:                  # unbalanced brackets: check_url refuses it
        return u


# Pages ON a platform, not a website of the business's own. The host is shared by everyone on it — a brand keyed on
# instagram.com would turn every other Instagram user away with "already set up" — and the scan would read the
# platform's login wall. The builders' own homepages (wix.com, not <name>.wixsite.com) are no one's site either.
_PLATFORM_PAGES = [(re.compile(p + r"$"), name) for p, name in (
    (r"(?:^|\.)(?:instagram\.com|instagr\.am)", "Instagram"), (r"(?:^|\.)(?:facebook\.com|fb\.com|fb\.me|fb\.watch)", "Facebook"),
    (r"(?:^|\.)tiktok\.com", "TikTok"), (r"(?:^|\.)(?:linkedin\.com|lnkd\.in)", "LinkedIn"), (r"(?:^|\.)(?:twitter\.com|x\.com|t\.co)", "X"),
    (r"(?:^|\.)(?:youtube\.com|youtu\.be)", "YouTube"), (r"(?:^|\.)pinterest\.[a-z.]+", "Pinterest"), (r"(?:^|\.)threads\.(?:net|com)", "Threads"),
    (r"(?:^|\.)snapchat\.com", "Snapchat"), (r"(?:^|\.)(?:linktr\.ee|linktree\.com|beacons\.ai|lnk\.bio|bio\.link)", "a link-in-bio page"),
    (r"(?:^|\.)(?:wa\.me|whatsapp\.com)", "WhatsApp"), (r"(?:^|\.)(?:t\.me|telegram\.me|telegram\.org)", "Telegram"),
    (r"(?:^|\.)etsy\.com", "Etsy"), (r"(?:^|\.)bol\.com", "bol"), (r"(?:^|\.)marktplaats\.nl", "Marktplaats"),
    (r"(?:^|\.)amazon\.(?:com|co\.uk|de|nl|fr|es|it|ie)", "Amazon"), (r"(?:^|\.)ebay\.[a-z.]+", "eBay"),
    (r"(?:^|\.)(?:google\.[a-z.]+|goo\.gl|g\.page|g\.co|maps\.app\.goo\.gl)", "Google"),
    (r"(?:^|\.)treatwell\.[a-z.]+", "Treatwell"), (r"(?:^|\.)(?:thuisbezorgd\.nl|just-eat\.[a-z.]+|justeat\.[a-z.]+|lieferando\.[a-z.]+)", "Just Eat"),
    (r"(?:^|\.)deliveroo\.[a-z.]+", "Deliveroo"), (r"(?:^|\.)ubereats\.com", "Uber Eats"), (r"(?:^|\.)booking\.com", "Booking.com"),
    (r"(?:^|\.)tripadvisor\.[a-z.]+", "Tripadvisor"), (r"(?:^|\.)airbnb\.[a-z.]+", "Airbnb"), (r"(?:^|\.)yelp\.[a-z.]+", "Yelp"),
    (r"(?:^|\.)trustpilot\.com", "Trustpilot"), (r"(?:^|\.)(?:fresha\.com|salonized\.com|setmore\.com|calendly\.com)", "a booking page"),
    (r"^(?:www\.)?(?:wix|wixsite|squarespace|shopify|myshopify|webflow|webflow\.io|framer|wordpress|godaddy|jimdo|jimdofree|weebly|"
     r"strikingly|carrd|lightspeedhq|mijnwebwinkel|jouwweb|hubspot|mailchimp)\.(?:com|co|nl|io|site|website)", "a website builder"))]


def platform_page(url):
    """The platform's name when the address is a page on someone else's platform (Instagram, Facebook, Etsy, Google …)
    rather than the business's own website, else None."""
    host = host_of(normalize_url(url)).rstrip(".")
    return next((name for rx, name in _PLATFORM_PAGES if rx.search(host)), None) if host else None


EMAIL = re.compile(r"^(?:mailto:)?[\w.+'-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)\.?$", re.I)
FREE_MAIL = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.nl", "hotmail.co.uk", "outlook.com", "outlook.nl", "live.com",
             "live.nl", "live.ie", "msn.com", "yahoo.com", "yahoo.co.uk", "yahoo.ie", "ymail.com", "icloud.com", "me.com", "mac.com",
             "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.net", "gmx.de", "web.de", "t-online.de", "mail.com",
             "ziggo.nl", "kpnmail.nl", "kpnplanet.nl", "planet.nl", "home.nl", "xs4all.nl", "hetnet.nl", "casema.nl", "upcmail.nl",
             "chello.nl", "online.nl", "telfort.nl", "tele2.nl", "quicknet.nl", "zeelandnet.nl", "solcon.nl", "caiway.nl",
             "eircom.net", "eir.ie", "vodafone.ie", "btinternet.com", "sky.com", "virginmedia.com", "skynet.be", "telenet.be",
             "yandex.com", "zoho.com", "fastmail.com", "hey.com", "tutanota.com"}


def email_site(text):
    """'jan@bakkerij.nl' → ('bakkerij.nl', False); 'jan@gmail.com' → ('gmail.com', True) (a mailbox provider, not the
    business's site); anything that is not an e-mail address → (None, False)."""
    m = EMAIL.match(str(text or "").strip())
    if not m:
        return None, False
    dom = m.group(1).lower()
    return dom, dom in FREE_MAIL


# Hosted builders whose free sites live under a path of the owner's own subdomain (jan.wixsite.com/bakkerij): the path
# is part of the site's address (the subdomain's root answers 404), so it is kept wherever the site is stored.
PATH_SITE_HOSTS = re.compile(r"\.wixsite\.com$")


def site_path(url):
    """The first path segment when it belongs to the site's address (PATH_SITE_HOSTS), e.g. '/bakkerij', else ''."""
    try:
        p = urllib.parse.urlsplit(normalize_url(url))
    except ValueError:
        return ""
    if not PATH_SITE_HOSTS.search((p.hostname or "").rstrip(".")):
        return ""
    m = re.match(r"^/[A-Za-z0-9_-]{1,64}", p.path or "")
    return m.group(0) if m else ""


def host_of(u):
    try:
        return (urllib.parse.urlsplit(u).hostname or "").lower()
    except ValueError:                  # Python ≥ 3.11.4 refuses "https://[not-an-ip]/…" (a link on a scanned page): no host
        return ""


def ip_ok(ip):
    ip = ipaddress.ip_address(ip)
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if any(ip in n for n in _DENY_NETS if n.version == ip.version):
        return False
    return bool(ip.is_global) and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                       or ip.is_reserved or ip.is_unspecified)


def check_url(u):
    """→ (split, ascii host, port) or raises Blocked."""
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:                  # unbalanced brackets; on Python ≥ 3.11.4 also "[a.com]" (not an IP) — never a host
        raise Blocked("bad url")
    if p.scheme not in ("http", "https"):
        raise Blocked(f"scheme {p.scheme or '?'} not allowed")
    try:
        port = p.port
    except ValueError:
        raise Blocked("bad port")
    if port not in ALLOWED_PORTS:
        raise Blocked(f"port {port} not allowed")
    if p.username or p.password:
        raise Blocked("credentials in url")
    host = (p.hostname or "").rstrip(".")
    if not host:
        raise Blocked("no host")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise Blocked("bad host")
    if not re.fullmatch(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*", host):
        try:
            ipaddress.ip_address(host)                        # an IPv6 literal ("::1") is checked like any address
        except ValueError:
            raise Blocked("bad host")                         # quotes, brackets, @, spaces … are never a host name
    if "[" in p.netloc and ":" not in host:                   # "[a.com]" is no IPv6 literal: refused on every Python (3.9's
        raise Blocked("bad host")                             # urlsplit strips the brackets, 3.12's raises)
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise Blocked("local host name")
    return p, host, port or (443 if p.scheme == "https" else 80)


def resolve_public(host, port):
    """All addresses the name resolves to must be public; returns the one to connect to."""
    try:
        ipaddress.ip_address(host)
        literal = [host]
    except ValueError:
        literal = None
    if literal:
        ips = literal
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise Blocked("dns lookup failed")
        ips = list(dict.fromkeys(i[4][0].split("%")[0] for i in infos))
    if not ips:
        raise Blocked("no address")
    for ip in ips:
        if not ip_ok(ip):
            raise Blocked(f"non-public address {ip}")
    return ips[0]


def host_status(u):
    """"ok" (a public http(s) host), "not_found" (the name does not resolve) or "blocked" (not a URL we fetch: a local /
    private address, a bad port or scheme …) — the pre-check of /otto-peek and onboarding."""
    try:
        _, host, port = check_url(u)
        resolve_public(host, port)
        return "ok"
    except Blocked as e:
        return "not_found" if str(e) in ("dns lookup failed", "no address") else "blocked"


def safe_host(u):
    """Only public http(s) hosts."""
    return host_status(u) == "ok"


def twin_url(u):
    """The same address with 'www.' added (or removed): people type the bare domain and the landing strips 'www.', but
    some domains only answer on one of the two."""
    try:
        p = urllib.parse.urlsplit(u)
        port = p.port
    except ValueError:
        return None
    host = (p.hostname or "").rstrip(".")
    if not host or "@" in p.netloc or re.fullmatch(r"[\d.]+|.*:.*", host) or PATH_SITE_HOSTS.search(host):
        return None
    alt = host[4:] if host.startswith("www.") else "www." + host
    if "." not in alt:
        return None
    return urllib.parse.urlunsplit((p.scheme, alt + (f":{port}" if port else ""), p.path, p.query, ""))


def site_status(u):
    """host_status, trying the www. twin when the name does not resolve → (status, url to read)."""
    st = host_status(u)
    if st == "not_found":
        alt = twin_url(u)
        if alt and host_status(alt) == "ok":
            return "ok", alt
    return st, u


class _Watchdog:
    """Cuts one fetch off at its deadline. Socket timeouts bound each recv, not the fetch: a server that sends one byte
    just inside every timeout (status line, headers, TLS handshake or body) would otherwise hold the worker — and a
    /otto-peek or onboarding slot — for hours. At the deadline every socket of the fetch is shut down, which wakes
    whatever read is blocked."""

    def __init__(self, at):
        self._lock, self.fired, self._socks = threading.Lock(), False, []
        self._timer = threading.Timer(max(0.01, at - time.time()), self._fire)
        self._timer.daemon = True
        self._timer.start()

    def watch(self, sock):
        with self._lock:
            if self.fired:
                raise Blocked("deadline reached")
            self._socks.append(sock.dup())        # shutdown() acts on the connection: the dup outlives wrap_socket's detach

    def _fire(self):
        with self._lock:
            self.fired = True
            for s in self._socks:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self._timer.cancel()
        with self._lock:
            for s in self._socks:
                s.close()
            self._socks = []


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, port, timeout, dog=None):
        super().__init__(host, port, timeout=timeout)
        self._pin, self._dog = ip, dog

    def _open(self):
        sock = socket.create_connection((self._pin, self.port), self.timeout)
        if self._dog is not None:
            try:
                self._dog.watch(sock)
            except Blocked:
                sock.close()
                raise
        return sock

    def connect(self):
        self.sock = self._open()


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout, dog=None):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._pin, self._dog = ip, dog

    _open = _PinnedHTTP._open

    def connect(self):
        self.sock = self._context.wrap_socket(self._open(), server_hostname=self.host)


def _request_target(p):
    path = urllib.parse.quote(p.path or "/", safe="/%:@!$&'()*+,;=~-._")
    if p.query:
        path += "?" + urllib.parse.quote(p.query, safe="=&%/:@!$'()*+,;~-._?")
    return path


def _remaining(deadline, timeout):
    if deadline is None:
        return timeout
    left = deadline - time.time()
    if left <= 0.2:
        raise Blocked("deadline reached")
    return min(timeout, left)


def guarded_get(url, limit=1_500_000, timeout=12, deadline=None, headers=None):
    """GET with the SSRF guard on every hop. Returns (final_url, bytes, content_type, charset); raises on error.
    The whole fetch (every hop) ends by `deadline` and never lasts longer than MAX_FETCH_SECONDS."""
    hdrs = {"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": accept_language(host_of(url)),
            "Accept-Encoding": "identity", "Connection": "close"}
    hdrs.update(headers or {})
    hard = time.time() + MAX_FETCH_SECONDS
    deadline = min(deadline, hard) if deadline else hard
    dog = _Watchdog(deadline)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            p, host, port = check_url(url)
            ip = resolve_public(host, port)
            t = _remaining(deadline, timeout)
            conn = (_PinnedHTTPS if p.scheme == "https" else _PinnedHTTP)(host, ip, port, t, dog)
            try:
                conn.request("GET", _request_target(p), headers=hdrs)
                r = conn.getresponse()
                if r.status in (301, 302, 303, 307, 308):
                    loc = r.getheader("Location")
                    if not loc:
                        raise Blocked(f"HTTP {r.status} without Location")
                    url = urllib.parse.urljoin(url, loc.strip())
                    continue
                if r.status >= 400:
                    raise Blocked(f"HTTP Error {r.status}: {r.reason}")
                chunks, got = [], 0
                while got < limit:
                    if conn.sock is not None:
                        conn.sock.settimeout(_remaining(deadline, timeout))
                    chunk = r.read(min(READ_CHUNK, limit - got))
                    if not chunk:
                        break
                    chunks.append(chunk); got += len(chunk)
                if dog.fired:                         # the watchdog cut the body short: never return half a page as whole
                    raise Blocked("deadline reached")
                return url, b"".join(chunks), r.getheader("Content-Type", "") or "", r.headers.get_content_charset() or "utf-8"
            except Blocked:
                raise
            except Exception:
                if dog.fired:
                    raise Blocked("deadline reached") from None
                raise
            finally:
                conn.close()
        raise Blocked("too many redirects")
    finally:
        dog.close()


def fetch(url, limit=1_500_000, timeout=12, deadline=None):
    """Returns (final_url, text, content_type). Follows redirects (each hop re-validated).
    Never raises: on any error returns (url, '', 'error:<reason>')."""
    try:
        final, raw, ctype, charset = guarded_get(url, limit=limit, timeout=timeout, deadline=deadline)
        try:
            text = raw.decode(charset, "ignore")
        except LookupError:
            text = raw.decode("utf-8", "ignore")
        return final, text, ctype
    except Exception as e:  # network / http errors / blocked: caller decides
        return url, "", "error:" + str(e)[:120]


def absolute(base, href):
    try:
        return urllib.parse.urljoin(base, href.strip())
    except Exception:
        return href


# ---------------- parsing ----------------

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""; self.metas = {}; self.links = []; self.imgs = []; self.headings = []
        self.texts = []; self.quotes = []; self.styles = []; self.lang = ""; self.hreflangs = set()
        self.jsonld = []; self._skip = 0; self._cur = None; self._buf = []; self._quote_depth = 0
        self._qbuf = []; self._in_title = False; self._in_style = False; self._in_ld = False; self._depth = 0
        self.inline_styles = []; self.refresh = ""; self.paras = []; self._pbuf = None; self._style_chars = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); self._depth += 1
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        if a.get("style") and not self._skip and tag not in SKIP_TAGS and self._style_chars < 200_000:
            self.inline_styles.append(a["style"]); self._style_chars += len(a["style"])   # not an SVG icon's fill (payment badges)
        if tag == "p" and not self._skip:
            self._pbuf = []
        if tag == "meta" and (a.get("http-equiv") or "").strip().lower() == "refresh" and a.get("content"):
            self.refresh = a["content"]
        if tag in SKIP_TAGS:
            if tag == "style":
                self._in_style = True
            elif tag == "script" and (a.get("type") or "").strip() == "application/ld+json":
                self._in_ld = True
            else:
                self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k and a.get("content"):
                self.metas.setdefault(k, a["content"])
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if a.get("href"):
                self.links.append((a["href"], "", rel, a.get("hreflang") or ""))
                if a.get("hreflang"):
                    self.hreflangs.add(a["hreflang"].lower())
        elif tag == "a" and a.get("href"):
            self._cur = [a["href"], []]
        elif tag == "img":
            self.imgs.append((a.get("src") or a.get("data-src") or "", a.get("alt") or "", a.get("class") or ""))
        elif tag in ("h1", "h2", "h3"):
            self._buf = [tag]
        cls = ((a.get("class") or "") + " " + (a.get("id") or "")).lower()
        if tag == "blockquote" or re.search(r"review|testimonial|quote|rating", cls):
            if not self._quote_depth:
                self._qdepth_start = self._depth; self._qbuf = []
            self._quote_depth += 1

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            if tag == "style":
                self._in_style = False
            elif tag == "script":
                if self._in_ld:
                    self._in_ld = False
                elif self._skip:
                    self._skip -= 1
            elif self._skip:
                self._skip -= 1
        if tag == "p" and self._pbuf is not None:
            t = re.sub(r"\s+", " ", " ".join(self._pbuf)).strip()
            if t and len(self.paras) < 200:
                self.paras.append(t)
            self._pbuf = None
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._cur:
            self.links.append((self._cur[0], " ".join(self._cur[1]).strip(), "a", ""))
            self._cur = None
        elif tag in ("h1", "h2", "h3") and self._buf:
            t = " ".join(self._buf[1:]).strip()
            if t:
                self.headings.append((tag, re.sub(r"\s+", " ", t)[:160]))
            self._buf = []
        if self._quote_depth and self._depth == getattr(self, "_qdepth_start", -1):
            q = re.sub(r"\s+", " ", " ".join(self._qbuf)).strip()
            if 40 <= len(q) <= 400:
                self.quotes.append(q)
            self._quote_depth = 0
        self._depth -= 1

    def handle_data(self, data):
        if self._in_style:
            self.styles.append(data); return
        if self._in_ld:
            self.jsonld.append(data); return
        if self._skip:
            return
        t = data.strip()
        if not t:
            return
        if self._in_title:
            self.title += t
        if self._buf:
            self._buf.append(t)
        if self._cur:
            self._cur[1].append(t)
        if self._quote_depth:
            self._qbuf.append(t)
        if self._pbuf is not None:
            self._pbuf.append(t)
        self.texts.append(t)


def parse(html):
    p = Page()
    try:
        p.feed(html)
    except Exception:
        pass
    return p


# ---------------- extraction helpers ----------------

def hex6(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def is_neutral(h):
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return (max(r, g, b) - min(r, g, b)) < 26 or lum > 0.93 or lum < 0.07


# Colours that are some framework's, plugin's or network's default, not a brand's choice: the WordPress block-editor
# presets, Divi / Elementor / Astra / Flatsome / Kadence defaults, Bootstrap, Tailwind and Material palettes, Webflow /
# Framer / Wix / Swiper link blues, cookie-banner and form-plugin colours, Judge.me, WooCommerce, and the social networks'
# and payment cards' own colours (share buttons, payment badges). Found across unrelated sites in the 2026-10 scan QA.
DEFAULT_COLOURS = frozenset("#" + h for h in """
ABB8C3 F78DA7 CF2E2E FF6900 FCB900 7BDCB5 00D084 8ED1FC 0693E3 9B51E0
2EA3F2 E02B20 E09900 EDF000 7CDA24 0C71C3 8300E9 6EC1E4 54595F 7A7A7A 61CE70 4054B2 23A455
0274BE 0170B9 045CB4 1E73BE 446084 D26E4B 7A9C59 B20000 627D47 3182CE 2B6CB0 13AFF0 0B7CAC 65BC7B
DC3232 46B450 FFB900 00A0D2 F56E28 0073AA 00A32A D63638 DBA617 2271B1 135E96 C02B0A
96588A A46497 7F54B3 E2401C 0F834D 3D9CD2 77A464 720EEC B81C23
337AB7 286090 204D74 2E6DA4 3C763D A94442 8A6D3B 31708F 5CB85C 5BC0DE F0AD4E D9534F 449D44 31B0D5 EC971F C9302C
DFF0D8 F2DEDE FCF8E3 D9EDF7 23527C
007BFF 0D6EFD 6C757D 28A745 198754 DC3545 FFC107 17A2B8 0DCAF0 343A40 6610F2 6F42C1 E83E8C D63384 FD7E14 20C997 0A58CA
0056B3 0062CC 545B62 1E7E34 BD2130 D39E00 117A8B
2563EB 3B82F6 1D4ED8 60A5FA EF4444 DC2626 10B981 059669 F59E0B 6366F1 4F46E5 8B5CF6 EC4899 14B8A6 22C55E 16A34A EAB308
F97316 A855F7 1E40AF 374151 4B5563 6B7280
2196F3 F44336 4CAF50 FFEB3B FF9800 9C27B0 E91E63 3F51B5 00BCD4 009688 8BC34A CDDC39 FF5722 795548 607D8B 1976D2 66BB6A
81C784 388E3C D32F2F
3898EC 0099FF 116DFF 0F2CCF 2F5DFF 597DFF 3899EC 007AFF
1863DC 1032CF 61A229 0045A5 108474 339999
3B5998 1877F2 4267B2 1DA1F2 55ACEE 00ACED 00ACEE E4405F C13584 833AB4 F56040 FCAF45 405DE6 5851DB FD1D1D 3F729B 517FA4
125688 0077B5 0A66C2 007BB6 0E76A8 FF0000 CD201F E52D27 BD081C E60023 CB2027 CC2127 25D366 128C7E 075E54 34AF23 4DC247
FE2C55 25F4EE 69C9D0 EE1D52 EA4C89 1769FF 053EFF 007EE5 0061FF 1AB7EA 00ADEF 35465C 32506D FF4500 FFFC00 0088CC 2AABEE
229ED9 4285F4 DB4437 F4B400 0F9D58 EA4335 FBBC05 34A853 DD4B39 D32323 C41200 00AF87 34E0A1 00B67A 04DA8D 1DB954 1ED760
FF5500 00AFF0 FF0084 0063DC F26522 00B4B3
EB001B F79E1B FF5F00 1A1F71 1434CB 142688 F7B600 2E77BC 006FCF 003087 009CDE 012169 0070BA FFC439 CC0066 FFB3C7 B2FCE4
005498 FFD800 0099DF 635BFF 6772E5 5A31F4 FF6000 0079BE 0071CE
7ADCB4 00D082 A9B8C3 4AEADC 9778D1 CF2ABA EE2C82 FB6962 FEF84C FFCEEC 9896F0 FECDA5 FE2D2D 6B003E FFCB70 C751C0 4158D0
FFF5CB B6E3D4 33A7B5 CAF880 71CE7E 020381 2874FC 007CBA 005A87 006BA1 21759B CC1818 CD2653 29C4A9 008BDB 2C324C
E93636 56AD6A 1990C6 136F99 108043 DE3618 0099E5 F94877 CC3B3B BD0000 E99292 DF3131 CC3366 333366 FFFF00 7A00DF 34E2E4 4721FB AB1DFE B94A48 468847 A0CE4E""".split())
_HEX = re.compile(r"(?<![&\w#])#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")        # never "&#038;" (an HTML entity, not #003388)
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*[,)/]")
# a theme's own brand variables (--wp--preset--color--primary, --e-global-color-accent, --color-button, --brand …)
_BRAND_VAR = re.compile(r"--[\w-]*(?:primary|secondary|accent|brand|main|theme|highlight|button|btn|cta)[\w-]*\s*:\s*"
                        r"(?:#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*[;}])", re.I)
# hsl(): Squarespace 7.1 writes its site colours as "--accent-hsl: 2,60%,45%" (no hex anywhere); hsl()/hsla() elsewhere
_HSL = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%")
_HSL_VAR = re.compile(r"--([\w-]*)-hsl\s*:\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%", re.I)


def _hsl_hex(h, s_, l):
    import colorsys
    try:
        r, g, b = colorsys.hls_to_rgb((float(h) % 360) / 360, min(float(l), 100) / 100, min(float(s_), 100) / 100)
    except ValueError:
        return None
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _close(a, b, d=24):
    """Two colours a viewer would call the same (#E12727 / #E12827, #4DA8B3 / #4CA9B4)."""
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5)) < d * d


def _rgb_hex(r, g, b):
    vals = [int(x) for x in (r, g, b)]
    return "#%02X%02X%02X" % tuple(vals) if all(v <= 255 for v in vals) else None


# stylesheets that are WordPress core, a plugin or a library — their colours are defaults, the brand's live in the theme
LIBRARY_CSS = re.compile(r"/wp-(?:includes|admin)/|/wp-content/plugins/|cookie-?(?:law|notice|consent|bar|yes|bot|script)|complianz|"
                         r"consent|gdpr|font-?awesome|bootstrap(?:\.min)?\.css|"
                         r"animate(?:\.min)?\.css|swiper|slick|owl\.carousel|magnific|fancybox|lightbox|select2|flatpickr|"
                         r"fonts\.googleapis\.com|use\.typekit\.net", re.I)
# WordPress writes every preset into the page, the core ones and all gradients / duotones even when no block uses them
_WP_PRESETS = re.compile(r"--wp--preset--(?:gradient|duotone)--[\w-]+\s*:[^;}]*|--wp--preset--color--(?:black|cyan-bluish-gray|white|"
                         r"pale-pink|vivid-red|luminous-vivid-orange|luminous-vivid-amber|light-green-cyan|vivid-green-cyan|"
                         r"pale-cyan-blue|vivid-cyan-blue|vivid-purple)\s*:[^;}]*", re.I)


def palette_from(texts):
    """Brand colours and neutrals from CSS (stylesheets, <style> blocks, style="" attributes): hex and rgb() colours by how
    often they are used, a theme's brand variables counting extra, framework / plugin / network defaults left out."""
    c = Counter()
    for t in texts:
        t = _WP_PRESETS.sub("", t)
        for m in _HEX.findall(t):
            c[hex6(m)] += 1
        for m in _RGB.findall(t):
            h = _rgb_hex(*m)
            if h:
                c[h] += 1
        for m in _BRAND_VAR.findall(t):
            h = hex6(m[0]) if m[0] else _rgb_hex(*m[1:])
            if h:
                c[h] += 8
        for m in _HSL.findall(t):
            h = _hsl_hex(*m)
            if h:
                c[h] += 1
        for name, *hsl in _HSL_VAR.findall(t):
            h = _hsl_hex(*hsl)
            if h:
                c[h] += 8 if re.search(r"accent|primary|brand", name, re.I) else 2
    ranked = [(h, n) for h, n in c.most_common() if h not in DEFAULT_COLOURS]
    brand, neutral = [], []
    for h, n in ranked:
        bucket = neutral if is_neutral(h) else brand
        if len(bucket) < 8 and not any(_close(h, x) for x, _ in bucket):
            bucket.append((h, n))
    brand, neutral = brand[:8], neutral[:4]
    return [{"hex": h, "count": n} for h, n in brand], [{"hex": h, "count": n} for h, n in neutral]


def fonts_from(css_texts, links):
    c = Counter()
    for t in css_texts:
        for fam in re.findall(r"font-family\s*:\s*([^;}]+)", t, re.I):
            first = fam.split(",")[0].strip().strip("'\"").strip()
            if first and first.lower() not in GENERIC_FONTS and not first.startswith("var(") and len(first) < 40 \
                    and not ICON_FONT.search(first):
                c[first] += 1
    for href, *_ in links:
        if "fonts.googleapis.com" in href:
            for group in re.findall(r"family=([^&]+)", urllib.parse.unquote(href)):
                for fam in group.split("|"):
                    name = fam.split(":")[0].replace("+", " ").strip()
                    if name and not ICON_FONT.search(name):
                        c[name] += 5
    out = [pretty_font(f) for f, _ in c.most_common(12) if "fallback" not in f.lower()]
    out = [f for f in out if not ICON_FONT.search(f) and f.lower() not in GENERIC_FONTS]   # also after prettifying
    return list(dict.fromkeys(f for f in out if FONT_NAME.fullmatch(f)))[:5]   # a family name, never CSS or markup


FONT_NAME = re.compile(r"[\w .-]{1,40}")


def pretty_font(name):
    """'adobe-caslon-w01-smbd' → 'Adobe Caslon Smbd'; keeps proper names as they are."""
    n = re.sub(r"-w\d\d-?", "-", name)
    if re.fullmatch(r"[a-z0-9 -]+", n):                 # "libre baskerville" → "Libre Baskerville"
        n = " ".join(w.capitalize() for w in re.split(r"[- ]", n) if w)
    return n.strip()


SOCIAL = [("facebook", r"facebook\.com/(?:profile\.php\?id=\d+|pages/[^/?#\s\"'<>]+/\d+|people/[^/?#\s\"'<>]+/\d+|pg/[\w.%+~-]+|"
                       r"(?!sharer|share|dialog|plugins|tr\b|login|watch|hashtag|help|policies|privacy|business|events|groups|"
                       r"photo|story\.php|permalink|profile\.php|pages\b|people\b|pg\b)[\w.@%+~-]+)"),
          ("instagram", r"instagram\.com/(?!p/|reels?/|explore|stories|accounts|tv/|share|direct)[\w.@%+~-]+"),
          ("tiktok", r"tiktok\.com/@[\w.@%+~-]+"),
          ("linkedin", r"linkedin\.com/(?:company|in)/[\w.@%+~-]+"),
          ("youtube", r"youtube\.com/(?:@|channel/|c/|user/)[\w.@%+~-]+"),
          ("x", r"(?:twitter|x)\.com/(?!intent|share|home|search|hashtag|i/)[\w.@%+~-]+"),
          ("whatsapp", r"(?:wa\.me/\d+|api\.whatsapp\.com/send[\w.@%+~=&?/-]*)"),
          ("telegram", r"t\.me/(?!share)[\w.@%+~-]+"),
          ("pinterest", r"pinterest\.[a-z.]+/(?!pin\b|search|share)[\w.@%+~-]+")]
# a builder's template links to the builder's own accounts until the owner replaces them (instagram.com/wix on a Wix site)
TEMPLATE_HANDLES = re.compile(r"/@?(?:wix|wixcom|squarespace|shopify|wordpress|wordpressdotcom|elementor|webflow|framer|framerapp|"
                              r"godaddy|jimdo|weebly|strikingly|hubspot|mailchimp|elegantthemes|divithemes|themeforest|envato|"
                              r"lightspeedhq|joomla|username|yourusername|yourpage|your-page|yourcompany|example|company|page)/?$", re.I)


def socials_from(hrefs):
    """The brand's own profile on each network: not a share / like button, a post, the network's own pages, or a template's
    placeholder link to the builder's account."""
    out = {}
    for h in hrefs:
        for name, pat in SOCIAL:
            if name in out:
                continue
            m = re.search(pat, h, re.I)
            if m and not TEMPLATE_HANDLES.search(m.group(0)) and not re.search(r"\.(?:ico|png|jpe?g|svg|gif|js|css)$", m.group(0), re.I):
                out[name] = "https://" + re.sub(r"^(?:www\.|m\.)", "", m.group(0))
    return out


def detect_platform(html):
    h = html
    checks = [("Shopify", "cdn.shopify.com"), ("WooCommerce", "plugins/woocommerce"), ("WordPress", "wp-content"),
              ("Wix", "wixstatic.com"), ("Webflow", "website-files.com"), ("Squarespace", "squarespace.com"),
              ("Next.js", "/_next/"), ("Nuxt", "/_nuxt/"), ("Elementor", "plugins/elementor"), ("HubSpot", "hs-scripts"),
              ("Framer", "framerusercontent"), ("Duda", "cdn-cms.duda"), ("Wix", "parastorage.com"), ("Magento", "Magento_"),
              ("Lightspeed", "webshopapp.com"), ("Shopware", "shopware"), ("PrestaShop", "prestashop"),
              ("BigCommerce", "bigcommerce.com"), ("Jimdo", "jimdo"), ("Weebly", "weebly.com")]
    found = [n for n, s in checks if s in h]
    return " + ".join(dict.fromkeys(found)) or "custom"


def lang_code(v):
    """'de-AT' / 'pt_BR' → 'de' / 'pt'; None for anything that is not a language code (the page wrote it)."""
    c = re.split(r"[-_]", str(v or "").strip().lower(), maxsplit=1)[0]
    return c if re.fullmatch(r"[a-z]{2,3}", c) else None


def web_url(u):
    """An http(s) URL we are willing to store and show (a logo, an og:image), else None: never javascript:/data:."""
    u = str(u or "").strip().replace(" ", "%20")
    return u if len(u) <= 1000 and re.match(r"^https?://[^\s\"'<>\\]+$", u, re.I) else None


# Words that say which language a text is in, and only that one: no word two of these languages share ("die", "de",
# "en", "per", "que", "para", "das", "com" …). A WordPress theme ships lang="en-US" whatever the owner writes in, and many
# sites have no lang at all (coffeecompany.nl), so the text decides the language Otto writes the brand's posts in.
_STOPWORDS = {
    "nl": "het een van voor met niet zijn wij onze ook naar bij uit maar wordt worden kunnen meer deze jouw uw ons heeft "
          "hebben waar nieuwe bekijk bestel graag onder tot wat hoe jij zich kun",
    "en": "the and for with our you your are this that from have more about will we what all can",
    "de": "und der mit nicht für ist wir unsere sie ein eine auf dem von bei ihre auch sind oder wird",
    "fr": "les des une pour avec vous nous est sur dans qui votre aux sont cette",
    "es": "los las nuestro nuestra más también nuestros usted cómo",
    "it": "gli della sono nostro nostra più anche delle questo nella",
    "pt": "uma não nosso nossa você também nossos está",
}
_STOP_SETS = {k: set(v.split()) for k, v in _STOPWORDS.items()}
_SCRIPTS = (("he", r"[֐-׿]"), ("ar", r"[؀-ۿ]"), ("ru", r"[Ѐ-ӿ]"), ("el", r"[Ͱ-Ͽ]"),
            ("ja", r"[぀-ヿ]"))


def text_langs(text):
    """{language: score} from the visible text: Latin languages by their own stop words, other scripts by characters."""
    sample = text[:40000]
    words = Counter(re.findall(r"[^\W\d_]+", sample.lower()))
    scores = {lang: sum(words[w] for w in ws) for lang, ws in _STOP_SETS.items()}
    for lang, rx in _SCRIPTS:
        n = len(re.findall(rx, sample))
        if n > 200:
            scores[lang] = max(scores.get(lang, 0), n // 4)
    return {k: v for k, v in scores.items() if v}


def detect_langs(lang_attr, hreflangs, text, content=None):
    """The site's languages, the one its text is written in first: a clearly dominant text language (≥ 20 words, twice
    the next) goes before the lang attribute; then the attribute, other languages the text really uses (≥ a third of the
    first), other scripts, and last the hreflang alternates. content (a list) receives the languages the text itself
    shows (or the attribute when the text says nothing) — what the brand writes in, as opposed to its translations."""
    attr = lang_code(lang_attr)
    ranked = sorted(text_langs(text).items(), key=lambda kv: -kv[1])
    top = ranked[0][1] if ranked and ranked[0][1] >= 20 else 0
    used = [k for k, v in ranked if top and v >= 20 and v >= top / 3]
    dominant = used[0] if used and (len(ranked) == 1 or ranked[0][1] >= 2 * ranked[1][1]) else None
    if dominant:
        own = [dominant] + [k for k in used if k != dominant]
    elif used:                                            # a bilingual text: the attribute says which comes first
        own = ([attr] if attr in used else []) + [k for k in used if k != attr]
    else:                                                 # too little text to tell: trust the attribute
        own = [attr] if attr else []
    if content is not None:
        content[:] = own
    alternates = [lang_code(h) for h in sorted(hreflangs) if h != "x-default" and lang_code(h)]
    # an attribute the text contradicts (a theme's lang="en-US" on a Dutch site) only counts as one more alternate
    return list(dict.fromkeys(own + ([attr] if attr and not dominant else []) + alternates + ([attr] if attr else [])))


SHOP_VERTICALS = ("Supplements & nutrition", "CBD & hemp wellness", "Clinic & medical", "Beauty & spa")
SHOP_PLATFORM = re.compile(r"shopify|woocommerce|magento|lightspeed|shopware|prestashop|bigcommerce", re.I)
# what makes a food business a place people visit (and plan posts like a restaurant: dishes, the kitchen, guests, events)
FOOD_PLACE = re.compile(r"restaurant|menukaart|(?:our|the|food|lunch|dinner) menu|reserv|caf[eé]s?\b|bistro|brunch|lunch|dinner|"
                        r"\bdiner\b|ontbijt|breakfast|opening ?hours|openingstijden|terras|takeaway|afhaalmenu|bakery|bakkerij|"
                        r"patisserie|coffee ?shops?\b|visit us|bezoek ons", re.I)


def industry_guess(title, desc, headings, nav, body, types=(), shop=False):
    """types: the schema.org @types the site declares (SCHEMA_INDUSTRY), worth 40 points to their industry. shop: the site
    runs on a shop platform. A food or drinks brand that sells online (a shop platform, or plenty of cart / checkout words:
    Death Wish Coffee, Dille & Kamille) plans like a shop — product, proof, how-to — unless its title, description,
    headings or menu say it is a place to visit (café, lunch, opening hours …)."""
    strong = " ".join([title, desc] + headings).lower()
    navs = " ".join(nav).lower()
    body = body.lower()[:60000]
    def cnt(text, k):
        return len(re.findall(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", text))
    scores, named = {}, set()
    for name, kws in INDUSTRIES.items():
        s = 0
        for k in kws:
            n = cnt(strong, k)
            s += 5 * n + 3 * cnt(navs, k) + min(cnt(body, k), 20)
            if n:
                named.add(name)
        scores[name] = s
    for t in dict.fromkeys(types or ()):
        if SCHEMA_INDUSTRY.get(t) in scores:
            scores[SCHEMA_INDUSTRY[t]] += 40
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    # "E-commerce & retail" describes the channel, not the business: when a vertical whose claims rules apply (a
    # supplement, CBD, clinic or beauty shop) scores at least a third of it, the vertical wins. Other verticals do not:
    # a coffee or chocolate webshop plans like a shop (product, proof, how-to), not like a restaurant, and words like
    # "interior" or "travel" on a shop are no hotel or builder.
    # (the vertical must be named in the title, description or headings: a hair salon's shop says "hairdressers" there; a
    # pet shop's grooming products don't make it a beauty salon)
    if ranked and ranked[0][0] == "E-commerce & retail":
        vert = next(((n, v) for n, v in ranked[1:] if n in SHOP_VERTICALS and (n in named or n in {SCHEMA_INDUSTRY.get(t) for t in types or ()})), None)
        if vert and vert[1] >= max(12, ranked[0][1] / 3):
            ranked.remove(vert); ranked.insert(0, vert)
    ecom_score = scores["E-commerce & retail"]
    if ranked and ranked[0][0] == "Restaurant & food" and ((shop and ecom_score >= 8) or ecom_score >= 20) \
            and "Restaurant & food" not in {SCHEMA_INDUSTRY.get(t) for t in types or ()} and not FOOD_PLACE.search(strong + " " + navs):
        ecom = next(x for x in ranked if x[0] == "E-commerce & retail")
        ranked.remove(ecom); ranked.insert(0, ecom)
    top = [{"industry": n, "score": s} for n, s in ranked[:3] if s > 0]
    guess = ranked[0][0] if ranked and ranked[0][1] >= 6 else "Unknown (?)"
    return guess, top


_ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Store", "OnlineStore", "OnlineBusiness", "Brand"} | set(SCHEMA_INDUSTRY)


def jsonld_info(blobs):
    """The site's own schema.org JSON-LD → (business names, @types). Names of Organization / LocalBusiness-like nodes come
    first, then WebSite names; types are every @type seen (for SCHEMA_INDUSTRY). Bounded: a few blobs, a few hundred nodes."""
    names, site_names, types, seen = [], [], [], [0]

    def walk(x, depth=0):
        if depth > 6 or seen[0] > 400:
            return
        seen[0] += 1
        if isinstance(x, list):
            for v in x[:50]:
                walk(v, depth + 1)
        elif isinstance(x, dict):
            t = x.get("@type")
            ts = [t] if isinstance(t, str) else [v for v in t if isinstance(v, str)] if isinstance(t, list) else []
            ts = [v.rsplit("/", 1)[-1] for v in ts]
            types.extend(ts)
            n = x.get("name")
            if isinstance(n, str) and 1 < len(n.strip()) <= 80:
                if set(ts) & _ORG_TYPES:
                    names.append(n.strip())
                elif "WebSite" in ts:
                    site_names.append(n.strip())
            for k, v in list(x.items())[:60]:
                if isinstance(v, (dict, list)) and k not in ("review", "reviews", "offers", "itemListElement", "author"):
                    walk(v, depth + 1)

    for b in blobs[:8]:
        try:
            walk(json.loads(b[:200_000]))
        except (ValueError, RecursionError):
            continue
    return list(dict.fromkeys(names + site_names)), list(dict.fromkeys(types))


_NAME_SEP = re.compile(r"\s*[|•·;»]\s*|\s+[–—-]\s+|:\s+|\s{2,}|\n")
_GENERIC_NAME = re.compile(r"^(?:home ?page|home|start(?:pagina)?|welkom|welcome|willkommen|hoofdpagina|accueil|inicio|index|"
                           r"official (?:site|website|store|webshop|online store)|offici[eë]le (?:webshop|website)|webshop|"
                           r"online ?(?:shop|store)|shop|store|homepage \d.*)$", re.I)


def _name_key(s, amp="and"):
    """'Ace & Tate' → 'aceandtate' (amp="" → 'acetate'), 'Grüns' → 'gruns': for comparing a title part with the domain."""
    return re.sub(r"[^a-z0-9]+", "", _fold((s or "").replace("&", amp).replace("+", amp)))


def host_core(host):
    """The business part of a host: 'www.shop.acme.co.uk' → 'acme', 'jan.wixsite.com' → 'jan'."""
    labels = [x for x in (host or "").lower().rstrip(".").split(".") if x]
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "ac", "gov", "edu", "or", "ne", "ltd", "plc") and len(labels[-1]) == 2:
        labels = labels[:-2]
    elif len(labels) >= 2:
        labels = labels[:-1]
    while len(labels) > 1 and labels[0] in ("www", "shop", "store", "app", "my", "en", "nl", "de", "home", "web", "m"):
        labels = labels[1:]
    if len(labels) > 1 and labels[-1] in ("wixsite", "myshopify", "squarespace", "webflow", "framer", "wordpress", "blogspot"):
        labels = labels[:-1]
    return _name_key(labels[-1] if labels else "")


def brand_name_from(idn, host, ld_names=()):
    """The business's name from the page title, og:site_name and JSON-LD: the part that matches the domain wins
    ('Home • LOT61 Coffee Roasters • Amsterdam' on lot61.com → 'LOT61 Coffee Roasters'; 'Fysiotherapie en manuele therapie
    in Utrecht - Praktijk Wittevrouwen' → 'Praktijk Wittevrouwen'); else the JSON-LD organisation, og:site_name (unless it
    is just the domain in lower case) or the first part of the title; else the domain itself."""
    core = host_core(host)
    cands = []
    for prio, val in [(0, n) for n in ld_names] + [(1, idn.get("site_name")), (2, idn.get("title")), (3, idn.get("og_title"))]:
        for seg in _NAME_SEP.split(str(val or "")):
            seg = seg.strip(" .,-–—|:\"'“”")
            if 2 <= len(seg) <= 60 and not _GENERIC_NAME.match(seg):
                cands.append((prio, seg))

    def score(seg):
        return max(score1(seg, "and"), score1(seg, ""))         # aceandtate.com ← "Ace & Tate"; dille-kamille.nl ← "Dille & Kamille"

    def score1(seg, amp):
        k = _name_key(seg, amp)
        if not k or not core or len(core) < 3:
            return 0
        if k == core:
            return 100
        if core in k:
            return 85 - min(35, len(k) - len(core))           # the shortest part that still holds the whole name
        if k in core and len(k) >= 4:
            return 40 + 40 * len(k) // len(core)
        words = [_name_key(w) for w in re.findall(r"[^\W_]{3,}", seg)]
        hit = sum(len(w) for w in words if w and w in core)
        return 50 * hit // len(core) if hit * 2 >= len(core) else 0

    domainish = lambda s: bool(re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", s))       # "loavies.com" (not "deLoodgieter.nl")
    scored = sorted(((score(seg), -prio, -len(seg), seg) for prio, seg in cands), reverse=True)
    if scored and scored[0][0] >= 40:
        name = scored[0][3]
    else:
        pick = [seg for prio, seg in cands if prio <= 1 and not domainish(seg)] or [seg for prio, seg in cands if prio == 2]
        name = pick[0] if pick else ""
    if not name:
        name = core.capitalize() if core else host
    # "Screaming Beans Store" → "Screaming Beans" when what is left still names the domain
    short = re.sub(r"\s+(?:webshop|online store|official store|store|shop|online|official)$", "", name, flags=re.I)
    if short != name and core and (core in _name_key(short) or core in _name_key(short, "")):
        name = short
    return name[:80]


def clip(t, n):
    """At most n characters, cut at a word boundary with an ellipsis — never mid-word ("…across h")."""
    t = re.sub(r"\s+", " ", t or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n - 1]
    cut = cut[:cut.rfind(" ")] if " " in cut[n // 2:] else cut
    return cut.rstrip(" ,;:-–—") + "…"


# Page chrome that is not proof and not a customer's words: the brand's own promos and announcements, review-widget
# summaries ("4.8 stars • 100K+ reviews"), testimonial disclaimers, and button soup ("Shop Now Shop All …").
_PROMO_TALK = re.compile(r"\b(?:shop now|shop all|buy now|order now|sign up|subscribe|join (?:to|our|now)|save up to|save \d+ ?%|"
                         r"\d+ ?% off|limited (?:time|edition|flavou?rs?)|is live|new!|vip access|use code|add to cart|"
                         r"one time purchase|pause or cancel|delivered once|jetzt kaufen|jetzt bestellen|in den warenkorb|"
                         r"sale price|regular price|unit price|in winkelwagen|bestel nu|leave a review|write a review|"
                         r"read (?:all|more) reviews|view all (?:reviews|treatments)|bekijk alle reviews|reviews widget|"
                         r"lees (?:alle|meer) (?:reviews|beoordelingen)|send us your|stuur ons|"
                         r"ga naar de inhoud|skip to (?:main )?content|meteen naar de content|naar de inhoud)\b|"
                         r"free shipping on", re.I)
# a review widget's metadata ("3 years ago", "4.7 869 reviews") or code that leaked into the text ('{"themeColor":…')
_WIDGET_TALK = re.compile(r"\b\d+\s+(?:days?|weeks?|months?|years?|dagen|weken|maanden|jaar|jaren)\s+(?:ago|geleden)\b|"
                          r"\b\d[.,]\d\s+\d[\d.,]*\s+(?:reviews?|beoordelingen|recensies|bewertungen)\b|[{}<>]|\":|\\u00", re.I)
_RATING_SUMMARY = re.compile(r"\d(?:[.,]\d)?\s*(?:stars?|sterne|/\s*5|out of 5)\b.*\d+\s*(?:k\+?|m\+?|,\d{3}|\+)?\s*"
                             r"(?:reviews?|ratings?|bewertungen|members|customers|kunden)", re.I)
_DISCLAIMER = re.compile(r"testimonials? (?:featured|shown|may|are)|received compensation|free product|results (?:may )?vary|"
                         r"not typical|individual results|affiliate", re.I)
_WIDGET_META = re.compile(r"^.*?(?:\bverified (?:buyer|purchase|reviewer)\b|\breviewer\b\s*\d(?:[.,]\d)?\s*/\s*5|"
                          r"\brated \d(?:[.,]\d)? out of 5\b|\b\d(?:[.,]\d)?\s*/\s*5\b)\s*[:\-–—]?\s*", re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2728]")


def is_chrome(t):
    """True for page chrome (promo, rating summary, disclaimer, button soup), which is neither proof nor a quote."""
    words = re.findall(r"[^\W\d_]{2,}", t)
    caps = sum(1 for w in words if w[0].isupper())
    soup = len(words) >= 8 and caps / len(words) > 0.6 and not re.search(r"[.!?]\s", t)       # "Free Shipping Today Pause Or …"
    return bool(_PROMO_TALK.search(t) or _RATING_SUMMARY.search(t) or _DISCLAIMER.search(t) or soup or _WIDGET_TALK.search(t)
                or len(_EMOJI.findall(t)) >= 3 or len(re.findall(r"[●•|]", t)) >= 3)


_TRUST_RES = [(w, re.compile((r"(?<![\w])" if w[:1].isalnum() else "") + re.escape(w.lower().strip())
                             + (r"(?![\w])" if w.strip()[-1:].isalnum() else ""))) for w in TRUST_WORDS]


def trust_from(text, chunks=None):
    """Sentences that carry a trust signal (certifications, lab tests, guarantees …). Words match whole ("ssl" is not
    "hassle"); promos, review-widget metadata and button soup are dropped; long sentences are cut at a word, with an
    ellipsis. chunks = the page's own text pieces (paragraphs, text nodes): a snippet never runs across them, so the
    title and the navigation never become "proof" ("Hybrid Gym | Personal training … Ga naar de inhoud Home Aanbod")."""
    pieces = [text] if chunks is None else [c for c in chunks if len(c) >= 12]
    lows = [p.lower() for p in pieces]
    out, seen = [], set()
    for w, rx in _TRUST_RES:
        found = 0
        for piece, low in zip(pieces, lows):
            for m in rx.finditer(low):
                found += 1
                if found > 5:                                # the first mentions may sit in a promo bar: try a few
                    break
                i = m.start()
                s = max(0, max(low.rfind(". ", 0, i), low.rfind("! ", 0, i), low.rfind("? ", 0, i)) + 1)
                e = min([x for x in (low.find(". ", i), low.find("! ", i), low.find("? ", i)) if x > 0] or [len(low)])
                snippet = clip(piece[s:e + 1] if e < i + 200 else piece[s:i + 400], 200)
                key = snippet[:60].lower()
                if key in seen or len(re.findall(r"[^\W\d_]{2,}", snippet)) < 3 or is_chrome(snippet):
                    continue
                seen.add(key); out.append(snippet)
                found = 99
                break
            if found > 5:
                break
    return out[:10]


def prices_from(text):
    found = [re.sub(r"[\u00a0\u202f]", " ", f) for f in PRICE_RE.findall(text)
             if re.search(r"[1-9]", f)]                    # "€0,00" is an empty cart, not a price
    cur = Counter()
    for f in found:
        for sym, code in (("€", "EUR"), ("₪", "ILS"), ("$", "USD"), ("£", "GBP"), ("EUR", "EUR"), ("USD", "USD"),
                          ("ILS", "ILS"), ("NIS", "ILS"), ("GBP", "GBP"), ("CHF", "CHF"), ("kr", "NOK/SEK/DKK")):
            if sym in f:
                cur[code] += 1; break
    uniq = list({re.sub(r"\s+", "", f): f.strip() for f in reversed(found)}.values())[::-1]   # "€ 55,00" and "€55,00" are one
    return (cur.most_common(1)[0][0] if cur else None), uniq[:10]


def clean_quote(q):
    """A customer's words from a review widget, or None: the widget's metadata before them ("4 months ago … Tom Berger
    Reviewer 5/5") is cut off, star runs are dropped, and page chrome (promo, rating summary, disclaimer) is no quote."""
    q = re.sub(r"\s+", " ", q or "").strip()
    q = _WIDGET_META.sub("", q, count=1) if _WIDGET_META.search(q) else q
    q = re.sub(r"[★☆⭐️]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip(" -–—|•")
    if len(q) < 25 or is_chrome(q) or not re.search(r"[^\W\d_]{3,}.*\s.*[^\W\d_]{3,}", q) or _BRAND_VOICE.match(q):
        return None
    return clip(q, 260)


# the brand speaking about itself in a quote-styled block ("We believe in doing things…", "Our team…"), not a customer
_BRAND_VOICE = re.compile(r"^(?:we (?:believe|make|are|offer|bake|create|have been|love|roast|serve|help|work)|our |"
                          r"for our customers|wij (?:zijn|maken|bakken|geloven)|onze |bij ons)\b", re.I)


def quotes_from(pages_quotes, text):
    out = list(dict.fromkeys(pages_quotes))
    for sent in re.split(r"(?<=[.!?])\s+", text[:80000]):
        if ("★" in sent or "⭐" in sent or re.search(r"\b5 stars\b|\b5/5\b", sent, re.I)) and 40 <= len(sent) <= 300:
            out.append(sent.strip())
    return [q for q in dict.fromkeys(clean_quote(q) for q in out) if q][:8]


PRESS_LOGO = re.compile(r"forbes|mens-?journal|today|people|womens-?health|good-?housekeeping|\bgq\b|logo-gq|vogue|travel-?leisure|"
                        r"nytimes|new-?york-?times|wsj|cnn|bbc|techcrunch|buzzfeed|elle|cosmopolitan|allure|oprah|shape|"
                        r"as-?seen|featured|press|media", re.I)


def _logo_hint(src, alt, cls):
    """'logo' in the file name, the class, or a short alt — never in a long product description ("…the Shrek logo…")."""
    name = src.split("?")[0].rsplit("/", 1)[-1].lower()
    return "logo" in name or "logo" in (cls or "").lower() or (len(alt or "") <= 60 and "logo" in (alt or "").lower())


def _fold(s):
    """Lower-case without accents: 'Grüns Logo' → 'gruns logo'."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


# someone else's logo on the page: review and payment badges, app stores, certifications, social networks
# (found: catalados.nl and physioroomscork.com showed Google's logo, aceandtate.com the B Corp badge)
THIRD_PARTY_LOGO = re.compile(r"google|facebook|instagram|tiktok|youtube|linkedin|pinterest|whatsapp|twitter|trustpilot|kiyoh|"
                              r"tripadvisor|thuisbezorgd|treatwell|visa\b|mastercard|paypal|klarna|apple-?pay|app-?store|"
                              r"google-?play|play-?store|b-?corp|keurmerk|webwinkelkeur|thuiswinkel|feedback-?company|trusted-?shops|"
                              r"qshops|klantenvertellen|judge-?me|yotpo|stamped|reviews?-?io|iso-?\d{4}|cookiebot|cookieyes|wix-?logo|"
                              r"coru|iscp|kngf|zorgkaart|qualicor", re.I)    # health registers / associations (physioroomscork: CORU)


def _logo_src(base, src):
    """An <img> src as an absolute URL: a Shopify width template ('logo_{width}x.png') filled in; None for a src that
    is no image address at all (empty, '/', data:)."""
    src = re.sub(r"\{width\}|%7Bwidth%7D", "600", (src or "").strip(), flags=re.I)
    if not src or src.startswith("data:") or re.search(r"//(?:www\.)?(?:wix|squarespace|shopify|webflow|framer|wordpress|godaddy|jimdo)\.com/", src, re.I):
        return None
    u = absolute(base, src)
    try:
        return u if urllib.parse.urlsplit(u).path not in ("", "/") else None
    except ValueError:
        return None


def logo_from(base, imgs, links, metas):
    host = re.sub(r"^www\.", "", host_of(base) or "").split(".")[0]
    # 1. an image that names the brand itself (header logos usually carry the brand in src/alt). Match the file
    #    name, not the whole src: on a store every CDN path carries the host ("//gruns.co/cdn/…/usnacks_logo.svg")
    for src, alt, cls in imgs:
        name = src.split("?")[0].rsplit("/", 1)[-1]
        blob = _fold(name + " " + alt + " " + cls)
        if host and len(host) > 2 and host in blob and _logo_hint(src, alt, cls) and _logo_src(base, src) \
                and not PRESS_LOGO.search(name) and not THIRD_PARTY_LOGO.search(_fold(name).replace(host, " ")):
            return _logo_src(base, src)
    for src, alt, cls in imgs:
        name = src.split("?")[0].rsplit("/", 1)[-1]
        if PRESS_LOGO.search((name + " " + alt).lower()) or THIRD_PARTY_LOGO.search(name + " " + alt):
            continue                                     # "As seen in" strips (Forbes, GQ…), Google reviews, B Corp …
        blob = (src + " " + alt + " " + cls).lower()
        if _logo_hint(src, alt, cls) and _logo_src(base, src) and not re.search(
                r"investor|partner|client|customer|badge|payment|trust|press|award|brand-?logos|sponsor|testimonial|review", blob):
            return _logo_src(base, src)
    for href, _, rel, _ in links:
        if "apple-touch-icon" in rel and _logo_src(base, href):
            return _logo_src(base, href)
    if metas.get("og:image") and _logo_src(base, metas["og:image"]):
        return _logo_src(base, metas["og:image"])
    for href, _, rel, _ in links:
        if "icon" in rel and _logo_src(base, href):
            return _logo_src(base, href)
    return None


# ---------------- main scan ----------------

def pick_internal(base, links, n, lang=None):
    """Up to n internal pages worth reading (about, shop, pricing … — PAGE_KEYS), each once ('/about' and '/about/' are one
    page), never the homepage again, and — when the homepage's language is known — not another language's copy of a page
    ('/en/about-us' on a Dutch site would make its text look bilingual)."""
    host = host_of(base)
    key = lambda u: u.split("#")[0].split("?")[0].rstrip("/").lower()
    try:
        home_seg = (urllib.parse.urlsplit(base).path.strip("/").split("/") + [""])[0].lower()
    except ValueError:
        home_seg = ""
    seen, out = {key(base)}, []
    for href, text, rel, _ in links:
        if rel != "a":
            continue
        u = absolute(base, href)
        if host_of(u) != host or key(u) in seen:
            continue
        try:
            path = urllib.parse.urlsplit(u).path.lower()
        except ValueError:
            continue
        seg = (path.strip("/").split("/") + [""])[0]
        if lang and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", seg) and seg[:2] != lang and seg != home_seg:
            continue
        if any(k in path for k in PAGE_KEYS) and not re.search(r"\.(png|jpe?g|pdf|zip)$", path):
            seen.add(key(u)); out.append(u.split("#")[0])
        if len(out) >= n:
            break
    return out


# a registrar's or reseller's parking page: the domain has no website of its own (yet)
PARKED = re.compile(r"sedoparking|parkingcrew|bodis\.com|parklogic|above\.com/marketplace|dan\.com/buy|afternic|"
                    r"domain (?:is|may be) for sale|buy this domain|this domain (?:is parked|has been registered)|"
                    r"related searches|sponsored listings|(?:dit|deze) domein(?:naam)? is te koop|domein is geparkeerd|"
                    r"website coming soon|under construction|binnenkort online", re.I)
_RETRY_ON = re.compile(r"dns lookup failed|no address|refused|ssl|certificate|unrecognized name|reset|unreachable|"
                       r"nodename|name or service", re.I)


def _looks_html(ctype, text):
    if re.search(r"html|xml", ctype or "", re.I):
        return True
    head = (text or "")[:3000].lower()
    return (not ctype or "text/plain" in ctype.lower()) and bool(re.search(r"<(?:!doctype html|html|head|body|title)\b", head))


def fetch_home(url, deadline=None):
    """The homepage, as fetch() → (final, text, ctype). A name that does not resolve, a refused connection or a TLS error
    on the address as typed gets one more try on its www. twin (and on plain http:// for a site without working HTTPS),
    while the deadline allows; a <meta http-equiv="refresh"> on an almost empty page is followed once."""
    t0 = time.time()
    final, html, ctype = fetch(url, deadline=deadline)
    if not html and _RETRY_ON.search(ctype or "") and time.time() - t0 < 8:
        alts = [twin_url(url)]
        if url.lower().startswith("https://") and re.search(r"ssl|certificate|refused|unrecognized", ctype or "", re.I):
            alts += ["http://" + url[8:]]
        for alt in [a for a in alts if a]:
            if deadline and time.time() > deadline - 4:
                break
            f2, h2, c2 = fetch(alt, deadline=deadline)
            if h2:
                return f2, h2, c2
    if html and _looks_html(ctype, html) and re.search(r"http-equiv\s*=\s*[\"']?refresh", html[:20000], re.I):
        p = parse(html)
        m = re.search(r"url\s*=\s*['\"]?([^'\";\s]+)", p.refresh or "", re.I)
        if m and len(" ".join(p.texts).split()) < 60 and not (deadline and time.time() > deadline - 4):
            f2, h2, c2 = fetch(absolute(final, m.group(1)), deadline=deadline)
            if h2 and _looks_html(c2, h2):
                return f2, h2, c2
    return final, html, ctype


def about_from(page):
    """The first real sentence about the business on its homepage (a <p> of 8+ words that is no cookie notice, no
    promo, no navigation): what the landing shows as "In your words" when the meta description is missing or a
    fragment ("Complete Care", "Screaming Beans Store")."""
    for t in page.paras + page.texts:
        t = re.sub(r"\s+", " ", t).strip()
        n = len(t.split())
        if not (10 <= n and len(t) <= 600) or t == page.title.strip() or (n < 20 and not re.search(r"[.!?…]$", t)):
            continue                                      # a sentence, not a label or a call to action ("Find us here")
        if re.search(r"cookie|privacy|consent|gdpr|\bavg\b|toestemming|javascript|browser|copyright|©|all rights|"
                     r"alle rechten|newsletter|nieuwsbrief|dichtst(?:e|bij)|nearest|closest|near you|check nu|find us|"
                     r"lees meer|read more|klik hier|click here", t, re.I) or is_chrome(t):
            continue
        if sum(ch.isdigit() for ch in t) > 0.12 * len(t):  # opening hours, prices, phone numbers
            continue
        return clip(t, 400)
    return ""


def scan(url, pages=5, page_limit=1_200_000, deadline=None):
    """deadline (epoch seconds) bounds the whole scan: fetches past it are skipped."""
    url = normalize_url(url)
    final, html, ctype = fetch_home(url, deadline=deadline)
    if not html:
        return {"url": url, "error": ctype or "empty response"}
    if not _looks_html(ctype, html):                  # a PDF, an image, a JSON API: no website to read
        return {"url": url, "error": "not a web page (" + (ctype.split(";")[0].strip() or "unknown type")[:40] + ")"}
    home = parse(html)
    if not home.title.strip() and not (home.metas.get("description") or home.metas.get("og:title")) \
            and len(" ".join(home.texts).split()) < 12:
        return {"url": url, "error": "empty page (a parked domain or a site that is not built yet)"}
    host = host_of(final)
    if PARKED.search(html[:200_000]) or re.match(r"ww\d+\.", host):     # a registrar's parking lander (bakkerij.com → ww16.)
        t = home.title.strip().lower()
        if not t or t.rstrip("/") in (host, host.removeprefix("www."), host_of(url)) or PARKED.search(t) or re.match(r"ww\d+\.", host):
            return {"url": url, "error": "empty page (a parked domain or a site that is not built yet)"}
    own = []                                          # the homepage's own language: its text first, the attribute if it says little
    detect_langs(home.lang, set(), " ".join(home.texts), content=own)
    internal = pick_internal(final, home.links, pages, lang=own[0] if own else lang_code(home.lang))
    subpages = []
    for u in internal:
        if deadline and time.time() > deadline - 1:
            break
        _, h, ct = fetch(u, limit=page_limit, deadline=deadline)
        if h and "text/html" in ct:
            subpages.append((u, parse(h)))

    # css for palette + fonts
    css_texts = list(home.styles)
    css_links = [u for u in (absolute(final, href) for href, _, rel, _ in home.links if "stylesheet" in rel)
                 if not LIBRARY_CSS.search(u)][:5]
    for cu in css_links:
        if deadline and time.time() > deadline - 1:
            break
        _, c, _ = fetch(cu, limit=400_000, deadline=deadline)
        if c:
            css_texts.append(c)
    palette, neutrals = palette_from(css_texts + home.inline_styles)
    theme = (home.metas.get("theme-color") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|rgba?\([\d\s.,%]+\)", theme):
        theme = None                                  # only a CSS colour is stored (it lands in scan.json + the profile)
    if theme and re.match(r"^#[0-9a-fA-F]{3,6}$", theme):
        t = hex6(theme)
        if not any(p["hex"] == t for p in palette) and not is_neutral(t) and t not in DEFAULT_COLOURS:
            palette.insert(0, {"hex": t, "count": 0, "source": "theme-color"})

    all_pages = [(final, home)] + subpages
    text = " ".join(t for _, p in all_pages for t in p.texts)
    chunks = [t for _, p in all_pages for t in p.paras + p.texts if t.strip() != p.title.strip()]
    headings = [h for _, p in all_pages for _, h in p.headings]
    nav = [t for href, t, rel, _ in home.links if rel == "a" and t and len(t) < 32][:40]
    hrefs = [absolute(final, href) for _, p in all_pages for href, _, _, _ in p.links]
    quotes = quotes_from([q for _, p in all_pages for q in p.quotes], text)
    currency, prices = prices_from(text)
    ld_names, ld_types = jsonld_info(home.jsonld)
    platform = detect_platform(html)
    guess, candidates = industry_guess(home.title, home.metas.get("description", ""), headings[:20], nav, text, types=ld_types,
                                       shop=bool(SHOP_PLATFORM.search(platform)))
    emails = list(dict.fromkeys(re.findall(r"mailto:([^\s\"'?]+)", html)))[:3]
    phones = list(dict.fromkeys(re.findall(r"tel:([+\d][\d\-\s().]{6,})", html)))[:3]
    promos = list(dict.fromkeys(m.strip() for m in PROMO_RE.findall(text)))[:8]
    content_langs = []
    meta_desc = re.sub(r"\s+", " ", home.metas.get("description") or home.metas.get("og:description") or "").strip()
    # the title and meta description are the owner's own words for search: they count three times
    langs = detect_langs(home.lang, home.hreflangs, text + (" " + home.title + " " + meta_desc) * 3, content=content_langs)
    about = about_from(home)
    idn = {"title": re.sub(r"\s+", " ", home.title).strip()[:200], "description": meta_desc[:400],
           "site_name": (home.metas.get("og:site_name") or "").strip(), "og_title": (home.metas.get("og:title") or "").strip(),
           "og_image": web_url(absolute(final, home.metas["og:image"])) if home.metas.get("og:image") else None}
    weak = (len(meta_desc.split()) < 6 or meta_desc.lower() == idn["title"].lower()       # "Complete Care", the title again,
            or sum(ch.isdigit() for ch in meta_desc) > 0.08 * len(meta_desc) or "@" in meta_desc)  # opening hours and phone
    if weak and about:
        idn["description"], idn["description_source"] = about, "page"
    idn["name"] = brand_name_from(idn, host_of(final), ld_names)

    return {
        "url": url, "final_url": final, "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages": [final] + [u for u, _ in subpages],
        "identity": idn,
        "industry": guess, "industry_candidates": candidates,
        "languages": langs, "content_languages": content_langs, "platform": platform,
        "visual": {"palette": palette[:6], "neutrals": neutrals[:3], "logo": web_url(logo_from(final, home.imgs, home.links, home.metas)),
                   "fonts": fonts_from(css_texts, home.links), "theme_color": theme},
        "socials": socials_from(hrefs), "contact": {"emails": emails, "phones": [p.strip() for p in phones]},
        "commerce": {"currency": currency, "prices": prices, "promos": promos},
        "trust": trust_from(text, chunks), "quotes": quotes,
        "headings": list(dict.fromkeys(headings))[:25], "nav": list(dict.fromkeys(nav))[:25],
        "text_sample": re.sub(r"\s+", " ", text)[:1500],
    }


# ---------------- logo tone ----------------
# The browser cannot read a cross-origin logo's pixels, so the server says whether the logo is light (a white logo needs
# a dark ground) or dark. Pure stdlib: 8-bit non-interlaced PNG (gray / RGB / palette, with or without alpha) up to
# LOGO_TONE_MAX_BYTES of pixel data, and SVG by the colours it paints with (no fill at all = black, the SVG default).

LOGO_TONE_MAX_BYTES = 1_600_000
_NAMED = {"white": "#FFFFFF", "black": "#000000", "currentcolor": None, "none": None, "transparent": None}


def _lum(r, g, b):
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _tone(lums):
    lums = [x for x in lums if x is not None]
    if not lums:
        return None
    return "light" if sum(lums) / len(lums) >= 0.6 else "dark"


def _png_lums(raw):
    """Luminance samples of the opaque pixels of an 8-bit PNG, or None when the file is not one we decode."""
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, ihdr, plte, trns, idat = 8, None, b"", b"", []
    while pos + 8 <= len(raw):
        n, typ = int.from_bytes(raw[pos:pos + 4], "big"), raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + n]
        pos += 12 + n
        if typ == b"IHDR":
            ihdr = data
        elif typ == b"PLTE":
            plte = data
        elif typ == b"tRNS":
            trns = data
        elif typ == b"IDAT":
            idat.append(data)
        elif typ == b"IEND":
            break
    if not ihdr or len(ihdr) < 13:
        return None
    w, h, depth, ctype, interlace = int.from_bytes(ihdr[:4], "big"), int.from_bytes(ihdr[4:8], "big"), ihdr[8], ihdr[9], ihdr[12]
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or not ch or w <= 0 or h <= 0:
        return None
    stride = w * ch
    need = (stride + 1) * h
    if need > LOGO_TONE_MAX_BYTES:
        return None
    try:
        buf = zlib.decompressobj().decompress(b"".join(idat), need)      # never inflates past what the header promises
    except zlib.error:
        return None
    if len(buf) < need:
        return None
    prev, out = bytes(stride), []
    sx, sy = max(1, w // 120), max(1, h // 120)
    for y in range(h):
        f, line = buf[y * (stride + 1)], bytearray(buf[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - ch] if i >= ch else 0) + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a, b, c = (line[i - ch] if i >= ch else 0), prev[i], (prev[i - ch] if i >= ch else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif f != 0:
            return None
        prev = line
        if y % sy:
            continue
        for x in range(0, w, sx):
            px = line[x * ch:(x + 1) * ch]
            if ctype == 3:
                k = px[0]
                if 3 * k + 2 >= len(plte) or (k < len(trns) and trns[k] < 128):
                    continue
                r, g, b = plte[3 * k:3 * k + 3]
            elif ctype in (0, 4):
                if ctype == 4 and px[1] < 128:
                    continue
                r = g = b = px[0]
            else:
                if ctype == 6 and px[3] < 128:
                    continue
                r, g, b = px[0], px[1], px[2]
            out.append(_lum(r, g, b))
    return out


def _svg_lums(raw):
    """Luminance of every colour an SVG paints with (fill / stroke / stop-color, attributes and inline CSS)."""
    t = raw.decode("utf-8", "ignore")
    if "<svg" not in t.lower():
        return None
    out = []
    for v in re.findall(r"(?:fill|stroke|stop-color|color)\s*[=:]\s*[\"']?\s*(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|[a-zA-Z]+)", t):
        v = _NAMED.get(v.lower(), v) if not v.startswith(("#", "rgb")) else v
        if not v:
            continue
        if v.startswith("#") and len(v) in (4, 5, 7, 9):
            h = hex6(v[:4] if len(v) in (4, 5) else v[:7])
            out.append(_lum(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)))
        elif v.startswith("rgb"):
            nums = [float(x) for x in re.findall(r"[\d.]+", v)[:3]]
            if len(nums) == 3:
                out.append(_lum(*nums))
    has_shape = re.search(r"<(?:path|rect|circle|ellipse|polygon|polyline|text|use|g)\b", t, re.I)
    if not out and has_shape:
        out.append(0.0)                                  # nothing coloured: SVG paints black
    return out


def logo_tone(raw, url=""):
    """'light' | 'dark' | None for a logo file's bytes (PNG or SVG)."""
    if not raw:
        return None
    try:
        lums = _png_lums(raw) if raw[:8] == b"\x89PNG\r\n\x1a\n" else _svg_lums(raw) if b"<svg" in raw[:2000].lower() else None
    except (ValueError, IndexError, TypeError):
        return None
    return _tone(lums or [])


def fetch_logo_tone(url, deadline=None):
    """Fetch the logo (SSRF-guarded, at most LOGO_MAX bytes) and read its tone; None on any failure."""
    if not web_url(url):
        return None
    try:
        _f, raw, _ct, _cs = guarded_get(url, limit=LOGO_MAX, timeout=6, deadline=deadline)
    except Exception:
        return None
    return logo_tone(raw, url)


def peek(url, deadline=None):
    """Compact scan for the landing/dashboard 'peek' (homepage + 2 pages, fast)."""
    s = scan(url, pages=2, page_limit=600_000, deadline=deadline)
    if "error" in s:
        return s
    logo = s["visual"]["logo"]
    tone = fetch_logo_tone(logo, deadline) if logo and (deadline is None or deadline - time.time() > 2) else None
    idn = s["identity"]
    name = idn.get("name") or brand_name_from(idn, host_of(s["final_url"]))
    return {"url": s["final_url"], "title": idn["title"] or idn["site_name"], "name": name,   # the part of the title that is the brand
            "description": s["identity"]["description"], "industry": s["industry"],
            "candidates": s["industry_candidates"], "palette": [p["hex"] for p in s["visual"]["palette"][:5]],
            "neutrals": [p["hex"] for p in s["visual"]["neutrals"][:2]], "logo": s["visual"]["logo"], "logo_tone": tone,
            "fonts": s["visual"]["fonts"][:3], "socials": s["socials"], "languages": s["languages"],
            "platform": s["platform"], "trust": s["trust"][:5], "quotes": s["quotes"][:3],
            "currency": s["commerce"]["currency"], "prices": s["commerce"]["prices"][:5],
            "headings": s["headings"][:8], "pages": len(s["pages"])}


# ---------------- profile draft ----------------

def slug_for(url):
    h = host_of(normalize_url(url)).replace("www.", "")
    return re.sub(r"[^a-z0-9]+", "", h.split(".")[0]) or "brand"


def bullet(items, empty="(?)"):
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


def profile_draft(s):
    idn, v, c = s["identity"], s["visual"], s["commerce"]
    name = idn.get("name") or idn["site_name"] or idn["title"].split("|")[0].split("–")[0].split("-")[0].strip() or host_of(s["final_url"])
    pal = ", ".join(p["hex"] for p in v["palette"][:5]) or "(?)"
    neu = ", ".join(p["hex"] for p in v["neutrals"][:3]) or "—"
    return f"""# Strategic Profile — {name}
Generated: {s['scanned_at'][:10]} by otto_scan.py (URL → profile draft) · Source: {s['final_url']}
> AUTO sections below are filled from the site scan. Sections marked **(creative engine)** are inferred by
> otto-creative-engine on first run; `(?)` = unverified, confirm with the customer (≤4 questions total).

## 📋 Business snapshot (AUTO)
- What they sell (as an outcome): {idn['description'] or '(?)'}
- Industry: {s['industry']} · Platform: {s['platform']} · Languages: {', '.join(s['languages']) or '(?)'}
- Price point: {', '.join(c['prices'][:6]) or '(ASK — hidden)'} · Currency: {c['currency'] or '(?)'}
- Promotions seen: {', '.join(c['promos']) or 'none visible'}
- USP / core promise: {idn['og_title'] or idn['title'] or '(?)'}
- Trust anchors:
{bullet(s['trust'][:8], '(?) none detected on site')}
- Socials: {', '.join(f'{k}: {u}' for k, u in s['socials'].items()) or '(?) none linked'}
- Contact: {', '.join(s['contact']['emails'] + s['contact']['phones']) or '—'}

## 👥 Core audience (creative engine)
- (?) infer from offer, price point, language and headings below

## 🔥 Avatars (creative engine — 2-4 personas)
- (?)

## 😰 Pain points, ranked (creative engine, customer's own language where possible)
- (?)

## ⚡ Purchase triggers (creative engine)
- (?)

## 🚫 Objections + counters (creative engine; top real-world objection = ASK)
- (?)

## ❌ Failed alternatives they tried (creative engine)
- (?)

## 💬 Customer language — verbatim quotes from reviews (AUTO)
{bullet(s['quotes'], '(?) no review text found on site — ASK for reviews / screenshots')}

## ✅ Proof assets (AUTO from site; offline proof = ASK)
{bullet(s['trust'][:6], '(?)')}

## 🏷️ Core promise + positioning (creative engine)
- Not: (?)
- Yes: (?)

## 📐 Winning angles, ranked (creative engine; past winners = ASK if they ran ads)
- (?)

## 🎨 VISUAL IDENTITY (AUTO from site scan — this drives every creative)
- Palette: **{pal}** · neutrals: {neu}{' · theme-color ' + v['theme_color'] if v.get('theme_color') else ''}
- Logo: {v['logo'] or '(?) not found — ASK for logo file'} → download to brands/<slug>/logo.png
- Typography: {', '.join(v['fonts']) or '(?)'}
- Style: (creative engine — from screenshots: photography vs illustration, light vs dark, motifs)
- Logo placement rule: (?) default bottom-right, clear space

## ⚖️ Compliance (AUTO by industry)
- {'Restricted category on Meta — organic-first, claims audit on every post' if any(k in s['industry'].lower() for k in ('cbd', 'clinic', 'medical', 'finance', 'legal')) else 'No restricted-category flags detected (verify)'}

## 📅 Content pillars (creative engine, 4-6)
- (?) derive from headings + nav: {', '.join(s['headings'][:8]) or '—'}

## 🔎 Scan appendix (AUTO)
- Pages read: {', '.join(s['pages'])}
- Navigation: {', '.join(s['nav'][:15]) or '—'}
- Headings: {' · '.join(s['headings'][:12]) or '—'}
"""


LOGO_MAX = 600_000
# An SVG logo is kept only when nothing in it can run or reach out: no script / event handler / javascript: URL, no
# embedded HTML (foreignObject, iframe, embed, object), no animation that rewrites a link, no external entity (XXE) or
# nested entity (billion laughs), no @import, and every href is an internal #fragment or an inline raster image.
_SVG_BAD = re.compile(rb"<\s*(?:script|foreignobject|iframe|embed|object|handler|listener|audio|video)\b|\bon[a-z]+\s*=|"
                      rb"(?:java|vb)script\s*:|@import|<\s*(?:set|animate)\b[^>]*attributename\s*=\s*[\"']?\s*(?:xlink:)?href|"
                      rb"<!entity[^>]*\b(?:system|public)\b|<!entity[^>]*&|\bhref\s*=\s*[^\"'\s>]", re.I)
_SVG_HREF = re.compile(rb"\bhref\s*=\s*([\"'])(.*?)\1", re.I | re.S)
_SVG_HREF_OK = re.compile(rb"\s*(?:#[\w.:-]*|data:image/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]*)\s*$", re.I)


def svg_safe(raw):
    """True for an SVG document with nothing scriptable or external in it (see _SVG_BAD)."""
    head = raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:400].lower()
    if b"<svg" not in head or _SVG_BAD.search(raw) or raw.lower().count(b"<!entity") > 20:
        return False
    return all(_SVG_HREF_OK.match(m.group(2)) for m in _SVG_HREF.finditer(raw))


def save_logo(s, out, deadline=None):
    """Download the scanned logo to brands/<slug>/logo.svg|png (the renderer's wordmark) unless one is already
    there. Only real logo files — never the og:image / touch-icon fallbacks, which are photos or app icons —
    complete (never cut at the size limit), and for SVG only a document svg_safe() accepts."""
    url = web_url((s.get("visual") or {}).get("logo")) or ""
    try:
        ext = urllib.parse.urlsplit(url).path.lower().rsplit(".", 1)[-1]
    except ValueError:                  # a logo url Python ≥ 3.11.4 cannot split ("https://[x]/logo.png"): no logo
        return None
    if not url or ext not in ("svg", "png") or any(out.glob("logo.*")):
        return None
    if url == (s.get("identity") or {}).get("og_image"):
        return None
    try:
        _final, raw, ctype, _cs = guarded_get(url, limit=LOGO_MAX + 1, timeout=12, deadline=deadline)
    except Exception:
        return None
    if not raw or len(raw) > LOGO_MAX:
        return None
    ok = svg_safe(raw) if ext == "svg" else raw[:8] == b"\x89PNG\r\n\x1a\n"
    if not ok:
        return None
    f = out / f"logo.{ext}"
    f.write_bytes(raw)
    return f


def run_cli(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return
    if argv[0] == "--peek":
        print(json.dumps(peek(argv[1]), ensure_ascii=False, indent=2)); return
    url = argv[0]
    slug = argv[argv.index("--slug") + 1] if "--slug" in argv else slug_for(url)
    pages = int(argv[argv.index("--pages") + 1]) if "--pages" in argv else 5
    s = scan(url, pages=pages)
    if "error" in s:
        sys.exit(f"scan failed: {s['error']}")
    out = BRANDS / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "scan.json").write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    wrote = [str(out / "scan.json")]
    lf = save_logo(s, out) if "--no-logo" not in argv else None
    if lf:
        wrote.append(str(lf))
    prof = out / "brand-profile.md"
    if "--no-profile" not in argv and (not prof.exists() or "--force" in argv):
        target = prof if not prof.exists() else out / "brand-profile.draft.md"
        target.write_text(profile_draft(s))
        wrote.append(str(target))
    if "--json" in argv:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        v = s["visual"]
        print(f"{s['identity']['title'] or s['final_url']}\n  industry: {s['industry']}  langs: {','.join(s['languages'])}  platform: {s['platform']}")
        print(f"  palette: {' '.join(p['hex'] for p in v['palette'][:5])}  fonts: {', '.join(v['fonts'][:3])}  logo: {v['logo']}")
        print(f"  socials: {', '.join(s['socials']) or '—'}  prices: {', '.join(s['commerce']['prices'][:4]) or '—'}  trust: {len(s['trust'])}  quotes: {len(s['quotes'])}")
        print("  wrote: " + ", ".join(wrote))


if __name__ == "__main__":
    run_cli(sys.argv[1:])
