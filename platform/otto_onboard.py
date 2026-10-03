#!/usr/bin/env python3
"""Otto onboarding: the engine side of platform/onboarding.html. A paying client's site + four answers → a brand.

  otto_onboard.py create <site> [--answers answers.json] [--peek peek.json] [--dry] [--no-scan] [--json]
  otto_onboard.py show <site|slug>

create(site, answers, peek=None) validates the site and the answers, then, keyed on the site's host (re-running
for the same site updates the same brand, never a second one):
  brands/<slug>/scan.json          otto_scan.scan (5 pages). If the site can't be read, the landing's /otto-peek result
                                   (peek=) stands in, marked "source": "peek". The owner's corrections from step 2 are
                                   applied in place (industry, colours, name…) so the planner, ads and compliance follow
                                   them; the scanned originals are kept under "corrected".
  brands/<slug>/logo.svg|png       otto_scan.save_logo, unless the owner said the logo is wrong
  brands/<slug>/brand-profile.md   otto_scan.profile_draft + an "Owner answers" section. A profile someone has edited
                                   since is never overwritten: the new draft goes to brand-profile.draft.md.
  brands/<slug>/strategy.json      otto_strategy.init + "inputs" (goal, budget, objection, never-say, channels,
                                   corrections); the owner's objection joins objections[]
  brands/<slug>/compliance.json    only when the owner listed words to avoid: merged into an existing file, or created
                                   with the health baseline included for a health brand (a new file must not drop it)
  data.json                        one ap.transaction(): brands[] (status "onboarding", plan plans.json defaults.new —
                                   "starter" — flagged plan_billing "not_billed" while no price sells it, until a
                                   subscription is linked; an existing brand keeps its status and plan), connections[] as
                                   "not_connected" (never connected here — OAuth happens later),
                                   one P0 recommendation per missing connection (add_rec_once)
Returns {"ok", "brand", "created", "files", "scan", "first_week", "first_review", "next_steps"}.

answers (every field optional; unknown keys are ignored, bad values raise ValueError):
  {"goal": "sales|leads|audience|launch", "goal_note": str, "budget": "not_yet|under_300|300_1000|1000_3000|3000_plus",
   "budget_amount": number, "objection": str, "never_say": str, "tz": "Europe/Berlin",
   "corrections": {"name", "industry", "description", "prices": [..], "fonts": [..], "palette": ["#RRGGBB"..],
                   "language": "en", "logo_wrong": bool, "proof": [..]},
   "channels": {"meta": bool, "google_ads": bool, "telegram": bool}, "approvals": "email|telegram|app", "comms_lang": "en|nl|de"}
  approvals: how posts reach the owner for approval — "email" (the default for new onboarding: a morning digest with one-tap
  buttons, otto_email), "telegram", or "app" (only the app's Review). A brand created here gets brands[].approvals; an existing
  brand keeps its own (the client changes it in the app's Settings).
  comms_lang: the language of what Otto sends the owner (e-mails, the 07:35 report, one-tap pages, Telegram cards —
  otto_i18n): "en" (the default: missing = English), "nl" or "de"; anything else is refused. Not the content language
  (corrections.language: what the posts are written in). A brand created here gets brands[].comms_lang; an existing brand
  keeps its own (Settings).

http_create() is the body of POST /otto-api/onboard (otto_api.py wires it after its JSON + Origin checks): per-IP rate
limit, at most two creates at once, and the client's own peek is never trusted (the server's cached one is).
A Google sign-in (otto_auth; account = its users[] record) that creates a brand gets the free trial on it
(otto_trial.brand_on_signup: plan "trial" until the trial's end, status "active", or — trial over, e-mail / domain already
trialled — the ended plan and "add a card"); the answer carries "trial": {granted, ends_at | why, message}.
public=True is the unauthenticated /otto-onboard: it may only CREATE a brand (a site that already has one → 409, nothing
written — otherwise anyone could rename a client, rewrite its scan, proof and strategy, or ban its words), and at most
PUBLIC_CREATES_PER_HOUR new brands are created that way per hour.
Stdlib only. Env: the usual OTTO_DATA / OTTO_HTML / OTTO_BRANDS (all brand files go under ap.BRANDS).
"""
import contextlib, copy, hashlib, io, json, re, sys, threading, time, unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import ap
import otto_compliance
import otto_i18n
import otto_plan
import otto_scan
import otto_strategy

Q = "(?)"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
RESERVED = {"new", "demo", "data", "assets", "templates", "api", "admin", "otto", "brand", "brands", "platform",
            "shared", "default", "template", "test", "www",
            "oauth", "auth", "account", "users"}     # oauth: google-oauth.json is Otto's own sign-in client, not brand "oauth"'s
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "or", "ne", "ltd", "plc"}
LEADING_SUBS = {"www", "shop", "store", "app", "my", "en", "de", "home", "web", "m", "go", "get"}
# hosted-site domains: the business is the subdomain (acme.myshopify.com → acme)
PLATFORM_HOSTS = ("myshopify.com", "wixsite.com", "squarespace.com", "webflow.io", "github.io", "netlify.app",
                  "vercel.app", "pages.dev", "carrd.co", "framer.website", "wordpress.com", "blogspot.com")

GOALS = {"sales": "More sales", "leads": "More leads or bookings", "audience": "A bigger audience",
         "launch": "Launch something new"}
BUDGETS = {"not_yet": "Not yet", "under_300": "Under 300 a month", "300_1000": "300 to 1,000 a month",
           "1000_3000": "1,000 to 3,000 a month", "3000_plus": "More than 3,000 a month"}
SOCIAL_KEYS = {"facebook", "instagram", "tiktok", "linkedin", "youtube", "x", "whatsapp", "telegram", "pinterest"}

# content pillars by scanned industry (the landing's brand panel uses the same map)
PILLARS = [("cbd", ["Education", "Trust and proof", "Use cases", "Product", "Engagement"]),
           ("supplement", ["Product", "Ingredients", "Daily routine", "Customer stories", "Offers"]),
           ("restaurant", ["Dishes and seasons", "Behind the kitchen", "Guests and reviews", "Events", "Offers"]),
           ("clinic", ["Education", "Patient stories", "Before and after", "Meet the team", "Booking"]),
           ("education", ["Method", "Student stories", "Career change", "Community", "Enrolment"]),
           ("e-commerce", ["Product", "Social proof", "How-to", "Behind the brand", "Offers"]),
           ("real estate", ["Listings", "Neighbourhood", "Buyer education", "Client stories", "Market updates"]),
           ("saas", ["Product", "Use cases", "Customer stories", "Education", "Launches"]),
           ("fitness", ["Workouts", "Member stories", "Nutrition", "Community", "Offers"]),
           ("beauty", ["Treatments", "Before and after", "Skin education", "Team", "Offers"]),
           ("legal", ["Education", "Case stories", "FAQ", "Team", "Consultations"]),
           ("hotel", ["Rooms and views", "Local guide", "Guest stories", "Seasonal offers", "Behind the scenes"]),
           ("coaching", ["Insights", "Client wins", "Framework", "Personal story", "Programme"]),
           ("home", ["Projects", "Before and after", "Tips", "Reviews", "Quotes"]),
           ("automotive", ["Inventory", "Service tips", "Customer stories", "Offers", "Team"]),
           ("marketing", ["Results", "Playbooks", "Client stories", "Behind the scenes", "Offers"])]
DEFAULT_PILLARS = ["Education", "Proof", "Product", "Behind the scenes", "Engagement"]
LEAD_INDUSTRIES = re.compile(r"clinic|education|legal|real estate|coaching|home|automotive|hotel|beauty|restaurant|marketing", re.I)
SHOP_PLATFORM = re.compile(r"shopify|woocommerce|magento|bigcommerce|shopware|prestashop", re.I)   # as otto_ads.is_shop
SHOP_INDUSTRY = re.compile(r"e-commerce|retail|supplement|nutrition|cbd", re.I)
RESTRICTED = re.compile(r"cbd|hemp|cannab|clinic|medical|therap|psycholog|legal|finance", re.I)     # the brand-add note
REVIEW_TIME = "08:00"          # the app's Review fills at 08:00 brand time
REPORT_TIME = "07:35"          # e-mail and Telegram approvals arrive with the 07:35 morning report (otto_report)
FIRST_REVIEW = {"email": "by e-mail in the 07:35 morning report, or in the app",
                "telegram": "in Telegram right after the 07:35 morning report, or in the app",
                "app": "in the app's Review from 08:00"}


# ---------------------------------------------------------------------------------------------------------------
# site → host key → slug
# ---------------------------------------------------------------------------------------------------------------

NOT_READABLE = "that is not a website address Otto can read (use the public address, like example.com)"
EMAIL_TYPED = "that is an e-mail address: enter your website address instead, like example.com"
PLATFORM_PAGE = "that is a page on a social network or marketplace, not your own website: enter your website address, like example.com"


def site_url(site):
    """Validate the site the owner typed → normalised https URL. Raises ValueError, in words the owner can act on, for
    anything that isn't a public http(s) web address of their own (the DNS / public-IP check happens on every fetch in
    otto_scan): an e-mail address, a page on Instagram / Facebook / Etsy … (a shared host is no brand's identity)."""
    s = str(site or "").strip()
    if not s:
        raise ValueError("a website address is required")
    if len(s) > 300:
        raise ValueError("that website address is too long: enter just the domain, like example.com")
    if re.search(r"\s", s):
        raise ValueError("a website address has no spaces in it, like example.com")
    if otto_scan.email_site(s)[0]:
        raise ValueError(EMAIL_TYPED)
    url = otto_scan.normalize_url(s)
    try:
        _, host, _ = otto_scan.check_url(url)
    except otto_scan.Blocked as e:
        raise ValueError(NOT_READABLE)
    if "." not in host.strip(".") and not _is_ip(host):
        raise ValueError("the website address needs a domain, like example.com")
    if otto_scan.platform_page(url):
        raise ValueError(PLATFORM_PAGE)
    return url


def _is_ip(host):
    import ipaddress
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def host_key(site):
    """The identity of a brand's site: ascii host, lower case, without www. ('https://www.Grüns.co/x' → 'xn--grns-lva.co')."""
    try:
        _, host, _ = otto_scan.check_url(otto_scan.normalize_url(str(site or "").strip()))
    except (otto_scan.Blocked, ValueError):
        return ""
    return host[4:] if host.startswith("www.") else host


def _fold(label):
    try:
        label = label.encode("ascii").decode("idna") if label.startswith("xn--") else label
    except UnicodeError:
        pass
    label = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", label)


def base_slug(host):
    """acme.com → acme · shop.acme.co.uk → acme · acme.myshopify.com → acme · grüns.de → gruns."""
    host = host.lower().strip(".")
    if _is_ip(host):
        return "site" + re.sub(r"[^0-9]", "", host)[-8:]
    labels = host.split(".")
    if any(host.endswith("." + p) for p in PLATFORM_HOSTS):
        core = labels[:-len(next(p for p in PLATFORM_HOSTS if host.endswith("." + p)).split("."))]
    elif len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2:
        core = labels[:-2]
    else:
        core = labels[:-1] or labels
    while len(core) > 1 and core[0] in LEADING_SUBS:
        core = core[1:]
    name = _fold(core[-1] if core else labels[0])
    if len(name) < 2:
        name = _fold("".join(labels))
    return name[:32] or "brand"


def _brand_host(b):
    return host_key(b.get("url") or "") if b.get("url") else ""


def resolve_slug(d, site, brands_dir=None):
    """→ (slug, existing brand or None). The same host always resolves to the same brand (whatever its id); a new
    host gets base_slug(host), and on a clash with another site's brand (or a reserved name, or a brands/ folder
    that belongs to another site) the TLD is appended (gruns.de → grunsde), then a number."""
    key = host_key(site)
    if not key:
        raise ValueError("unsupported website address")
    for b in d.get("brands", []):
        if _brand_host(b) == key:
            return b["id"], b
    brands_dir = Path(brands_dir or ap.BRANDS)
    taken = {b["id"] for b in d.get("brands", [])}

    def free(slug):
        if not SLUG.match(slug) or slug in RESERVED or slug in taken:
            return False
        scan = brands_dir / slug / "scan.json"
        if scan.exists():                                  # a folder from an earlier manual scan: ours only if same host
            try:
                s = json.loads(scan.read_text())
                return host_key(s.get("final_url") or s.get("url") or "") == key
            except Exception:
                return False
        return not (brands_dir / slug).exists() or not any((brands_dir / slug).iterdir())

    base = base_slug(key)
    tld = _fold(key.rsplit(".", 1)[-1]) if "." in key and not _is_ip(key) else ""
    for cand in [base, base + tld] + [f"{base}{n}" for n in range(2, 100)]:
        if free(cand[:40]):
            return cand[:40], None
    raise ValueError("could not find a free brand id")


# ---------------------------------------------------------------------------------------------------------------
# answers
# ---------------------------------------------------------------------------------------------------------------

class Exists(ValueError):
    """The site already has a brand, and this caller may not change it (public onboarding)."""


LABELS = {"goal_note": "The note on your goal", "objection": "What customers say", "never_say": "Words to avoid", "tz": "Time zone",
          "name": "Business name", "industry": "Industry", "description": "Description", "prices": "Prices", "fonts": "Fonts",
          "proof": "Proof", "language": "Language", "goal": "Goal", "budget": "Monthly ad budget", "approvals": "Approvals",
          "comms_lang": "Language for e-mails and reports"}


def label(field):
    """Validation messages reach the owner's screen: a field's human name, never its key ("never_say")."""
    return LABELS.get(field) or field.replace("_", " ").capitalize()


def _text(v, n, field):
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ValueError(f"{label(field)} must be text")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(v)).strip()
    return re.sub(r"[ \t]+", " ", t)[:n].strip()


def _list(v, n_items, n_chars, field):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r"[\n,;]+|\s·\s", v)]
    if not isinstance(v, list):
        raise ValueError(f"{label(field)} must be a list")
    out = [_text(x, n_chars, field) for x in v[:n_items * 2]]
    return list(dict.fromkeys(x for x in out if x))[:n_items]


def _bool(v):
    return v is True or (isinstance(v, str) and v.lower() in ("1", "true", "yes", "on"))


def clean_answers(a):
    """The owner's answers → a validated, bounded dict. Raises ValueError on a malformed value; empty is fine."""
    if a is None:
        a = {}
    if not isinstance(a, dict):
        raise ValueError("the answers could not be read")
    out = {}
    goal = _text(a.get("goal"), 20, "goal")
    if goal and goal not in GOALS:
        raise ValueError(f"Goal must be one of: {', '.join(GOALS.values())}")
    out["goal"] = goal or None
    out["goal_note"] = _text(a.get("goal_note"), 200, "goal_note")
    budget = _text(a.get("budget"), 20, "budget")
    if budget and budget not in BUDGETS:
        raise ValueError(f"Monthly ad budget must be one of: {', '.join(BUDGETS.values())}")
    out["budget"] = budget or None
    amt = a.get("budget_amount")
    if amt not in (None, ""):
        try:
            amt = float(str(amt).replace(",", "").strip())
        except ValueError:
            raise ValueError("Monthly ad budget must be a number")
        if not 0 <= amt <= 10_000_000:
            raise ValueError("Monthly ad budget must be between 0 and 10,000,000")
    out["budget_amount"] = amt if amt not in (None, "") else None
    out["objection"] = _text(a.get("objection"), 500, "objection")
    out["never_say"] = _text(a.get("never_say"), 500, "never_say")
    tz = _text(a.get("tz"), 60, "tz")
    try:
        out["tz"] = tz if tz and ZoneInfo(tz) else None
    except Exception:
        out["tz"] = None                                   # a browser hint, never an error

    c = {} if a.get("corrections") is None else a["corrections"]
    if not isinstance(c, dict):
        raise ValueError("the brand corrections could not be read")
    cor = {}
    for k, n in (("name", 80), ("industry", 60), ("description", 400)):
        t = _text(c.get(k), n, k)
        if t:
            cor[k] = t
    for k, items, chars in (("prices", 8, 40), ("fonts", 4, 40), ("proof", 6, 200)):
        xs = _list(c.get(k), items, chars, k)
        if k == "fonts" and any(not otto_scan.FONT_NAME.fullmatch(x) for x in xs):
            raise ValueError("Fonts must be font names, like Inter or Playfair Display")        # they reach CSS in the renderer
        if xs:
            cor[k] = xs
    if c.get("palette") not in (None, "", []):
        pal = c["palette"]
        if not isinstance(pal, list) or not all(isinstance(h, str) and HEX.match(h.strip()) for h in pal):
            raise ValueError("Colours must be hex codes like #2F5D50")
        cor["palette"] = list(dict.fromkeys(h.strip().upper() for h in pal))[:8]
    lang = _text(c.get("language"), 5, "language").lower()
    if lang:
        if not re.fullmatch(r"[a-z]{2}", lang):
            raise ValueError("Language must be a two-letter code, like en or de")
        cor["language"] = lang
    if _bool(c.get("logo_wrong")):
        cor["logo_wrong"] = True
    out["corrections"] = cor

    ch = {} if a.get("channels") is None else a["channels"]
    if not isinstance(ch, dict):
        raise ValueError("the channel choices could not be read")
    appr = _text(a.get("approvals"), 10, "approvals").lower() or ("telegram" if _bool(ch.get("telegram")) else "email")
    if appr not in ("email", "telegram", "app"):
        raise ValueError("Approvals must be email, Telegram or the app")
    out["channels"] = {k: _bool(ch.get(k, k == "meta" or (k == "telegram" and appr == "telegram")))
                       for k in ("meta", "google_ads", "telegram")}
    out["approvals"] = appr
    if appr == "telegram":
        out["channels"]["telegram"] = True
    cl = _text(a.get("comms_lang"), 5, "comms_lang").lower() or "en"
    if cl not in otto_i18n.COMMS_LANGS:
        raise ValueError("The language for e-mails and reports must be English, Nederlands or Deutsch")
    out["comms_lang"] = cl
    return out


def never_say_phrases(text):
    """'cheap, "miracle cure"; guaranteed' → ['miracle cure', 'cheap', 'guaranteed']. Only short
    phrases become compliance rules; a longer instruction stays guidance in strategy.json (inputs.never_say)."""
    text = str(text or "")
    qre = re.compile(r"[\"“„«]([^\"”“„«»]{2,60})[\"”“»]")
    items = qre.findall(text) + re.split(r"[\n,;]+", qre.sub(",", text))
    out = []
    for it in items:
        it = re.sub(r"^\s*(?:re:)+", "", it.strip(), flags=re.I).strip(" .!?'’-–—").strip()   # never a regex
        if 2 <= len(it) <= 60 and len(it.split()) <= 6:
            out.append(it)
    return list({x.lower(): x for x in out}.values())[:20]


def default_goal(industry, shop):
    return "sales" if shop or not LEAD_INDUSTRIES.search(industry or "") else "leads"


def pillars_for(industry):
    low = (industry or "").lower()
    return next((p for k, p in PILLARS if k in low), DEFAULT_PILLARS)


# ---------------------------------------------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------------------------------------------

def _clean_peek(p):
    """A /otto-peek result is data from a web page: keep only well-typed, bounded fields."""
    if not isinstance(p, dict) or p.get("error"):
        return None
    s = lambda v, n: v.strip()[:n] if isinstance(v, str) else ""
    strs = lambda v, k, n: [x.strip()[:n] for x in v if isinstance(x, str) and x.strip()][:k] if isinstance(v, list) else []
    hexes = lambda v: [h.upper() for h in (v if isinstance(v, list) else []) if isinstance(h, str) and HEX.match(h)][:6]
    logo = s(p.get("logo"), 500)
    socials = p.get("socials") if isinstance(p.get("socials"), dict) else {}
    return {"url": s(p.get("url"), 300), "title": s(p.get("title"), 200), "description": s(p.get("description"), 400),
            "industry": s(p.get("industry"), 60) or "Unknown (?)",
            "candidates": [{"industry": s(c.get("industry"), 60), "score": c.get("score") if isinstance(c.get("score"), int) else 0}
                           for c in (p.get("candidates") or [])[:3] if isinstance(c, dict) and s(c.get("industry"), 60)],
            "palette": hexes(p.get("palette")), "neutrals": hexes(p.get("neutrals")),
            "logo": logo if re.match(r"^https?://", logo) else None, "fonts": strs(p.get("fonts"), 4, 40),
            "socials": {k: s(v, 200) for k, v in socials.items() if k in SOCIAL_KEYS and re.match(r"^https://", s(v, 200))},
            "languages": [x.lower() for x in strs(p.get("languages"), 4, 5) if re.fullmatch(r"[A-Za-z]{2}", x)],
            "platform": s(p.get("platform"), 40), "trust": strs(p.get("trust"), 8, 200), "quotes": strs(p.get("quotes"), 4, 260),
            "currency": s(p.get("currency"), 12) or None, "prices": strs(p.get("prices"), 8, 40),
            "headings": strs(p.get("headings"), 12, 160), "pages": p.get("pages") if isinstance(p.get("pages"), int) else 1}


def scan_from_peek(url, peek):
    """A scan.json-shaped document from a (cleaned) peek, for a site the server could not read in full."""
    p = _clean_peek(peek) or {}
    final = p.get("url") or url
    return {"url": url, "final_url": final, "scanned_at": ap.now_iso(), "source": "peek", "pages": [final],
            "identity": {"title": p.get("title", ""), "description": p.get("description", ""), "site_name": "", "og_title": "",
                         "og_image": None},
            "industry": p.get("industry") or "Unknown (?)", "industry_candidates": p.get("candidates", []),
            "languages": p.get("languages", []), "platform": p.get("platform") or "unknown",
            "visual": {"palette": [{"hex": h, "count": 0, "source": "peek"} for h in p.get("palette", [])],
                       "neutrals": [{"hex": h, "count": 0, "source": "peek"} for h in p.get("neutrals", [])],
                       "logo": p.get("logo"), "fonts": p.get("fonts", []), "theme_color": None},
            "socials": p.get("socials", {}), "contact": {"emails": [], "phones": []},
            "commerce": {"currency": p.get("currency"), "prices": p.get("prices", []), "promos": []},
            "trust": p.get("trust", []), "quotes": p.get("quotes", []), "headings": p.get("headings", []), "nav": [],
            "text_sample": ""}


def apply_corrections(s, cor):
    """The owner's step-2 fixes, applied to the scan in place (every module reads scan.json); the scanned values are
    kept under s["corrected"][field]["was"]."""
    was = s.setdefault("corrected", {})

    def put(field, old, new):
        if old != new:
            was.setdefault(field, {"was": old})["now"] = new

    idn, vis, com = s.setdefault("identity", {}), s.setdefault("visual", {}), s.setdefault("commerce", {})
    if cor.get("name"):
        put("name", idn.get("name") or idn.get("site_name") or idn.get("title") or "", cor["name"])
        idn["site_name"] = idn["name"] = cor["name"]
    if cor.get("description"):
        put("description", idn.get("description") or "", cor["description"]); idn["description"] = cor["description"]
    if cor.get("industry"):
        put("industry", s.get("industry"), cor["industry"]); s["industry"] = cor["industry"]
    if cor.get("palette"):
        put("palette", [p.get("hex") for p in vis.get("palette") or []], cor["palette"])
        vis["palette"] = [{"hex": h, "count": 0, "source": "owner"} for h in cor["palette"]]
    if cor.get("fonts"):
        put("fonts", vis.get("fonts") or [], cor["fonts"]); vis["fonts"] = cor["fonts"]
    if cor.get("prices"):
        put("prices", com.get("prices") or [], cor["prices"]); com["prices"] = cor["prices"]
    if cor.get("proof"):
        put("proof", s.get("trust") or [], cor["proof"]); s["trust"] = cor["proof"]
    if cor.get("language"):
        langs = s.get("languages") or []
        new = [cor["language"]] + [x for x in langs if x != cor["language"]]
        put("languages", langs, new); s["languages"] = new
        s["content_languages"] = [cor["language"]]          # the owner's word: Otto writes in this one
    if cor.get("logo_wrong"):
        put("logo", vis.get("logo"), None); vis["logo"] = None
    if not was:
        s.pop("corrected")
    return s


def brand_name(s, host):
    idn = (s or {}).get("identity") or {}
    name = idn.get("name") or idn.get("site_name") or re.split(r"\s+[|–—·:-]\s+|\s[|]\s?", idn.get("title") or "")[0].strip()
    return (name or base_slug(host).capitalize())[:80]


# ---------------------------------------------------------------------------------------------------------------
# first week preview
# ---------------------------------------------------------------------------------------------------------------

def first_review_at(tz, now=None, approvals=None):
    """When the owner's first review lands, at least six hours from now: the next 07:35 brand time for e-mail and Telegram
    approvals (they come with the morning report), the next 08:00 for the app."""
    now = now or datetime.now(tz)
    h, m = (int(x) for x in (REPORT_TIME if approvals in ("email", "telegram") else REVIEW_TIME).split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    while t - now < timedelta(hours=6):
        t += timedelta(days=1)
    return t


def first_week(d, slug, now=None, approvals=None):
    """The posts of the first seven days after the first review: the brand's real planned posts when a plan exists,
    else otto_plan's own slot logic run as a dry build (nothing is written). Every slot — like first_review — is the
    brand's wall-clock time as ISO 8601 with its UTC offset ("2026-10-02T09:00+02:00")."""
    b = ap.brand(d, slug)
    if not b:
        return [], None
    tz = ap.brand_tz(b)
    now = now or datetime.now(tz)
    start = first_review_at(tz, now, approvals)
    end = start + timedelta(days=7)
    within = lambda slot: start < datetime.fromisoformat(slot).replace(tzinfo=tz) <= end
    real = [p for p in d.get("posts", []) if p.get("brand") == slug and p.get("slot") and ap.slot_dt(p, b)
            and start < ap.slot_dt(p, b) <= end]
    if real:
        items = [{"slot": ap.slot_dt(p, b).astimezone(tz).isoformat(timespec="minutes"), "platform": p.get("platform"),
                  "format": p.get("format") or "post", "pillar": p.get("pillar"), "id": p["id"], "status": p.get("status")}
                 for p in real]
    else:
        items = []
        for ym in sorted({start.strftime("%Y-%m"), end.strftime("%Y-%m")}):
            snap = copy.deepcopy(d)
            snap.setdefault("posts", [])
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    plan = otto_plan._build(snap, slug, ym, 12, ("fb", "ig"), True, False, True)
            except SystemExit:
                continue
            items += [{"slot": datetime.fromisoformat(x["slot"]).replace(tzinfo=tz).isoformat(timespec="minutes"),
                       "platform": x["platform"], "format": x["format"], "pillar": x["pillar"]} for x in plan if within(x["slot"])]
    return sorted(items, key=lambda x: x["slot"]), start


# ---------------------------------------------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------------------------------------------

def _write(path, text):
    ap._atomic_write(path, text)
    return str(path)


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _profile_answers(a, s, restricted):
    c = a["corrections"]
    amount = f" · {a['budget_amount']:,.0f} a month" if a["budget_amount"] else ""
    lines = [f"\n## 🗣️ Owner answers (onboarding, {ap.now_iso()[:10]})",
             f"- Goal this quarter: {GOALS.get(a['goal'] or '', Q)}{' · ' + a['goal_note'] if a['goal_note'] else ''}"
             f"{' (default from the industry)' if a.get('_goal_default') else ''}",
             f"- Monthly ad budget: {BUDGETS.get(a['budget'] or '', Q)}{amount}",
             f"- What customers say / main objection: {a['objection'] or Q}",
             f"- Never say: {a['never_say'] or 'nothing added'}{' (plus the health baseline: no cure or healing claims)' if restricted else ''}",
             "- Corrections to the scan: " + (", ".join(f"{k} (was {json.dumps(v.get('was'), ensure_ascii=False)[:80]})"
                                                       for k, v in (s.get("corrected") or {}).items()) or "none"),
             "- Channels: " + ", ".join(n for k, n in (("meta", "Instagram + Facebook"), ("google_ads", "Google Ads"),
                                                         ("telegram", "Telegram approvals")) if a["channels"].get(k))
             + " (not connected yet: the owner connects each through its own sign-in)"]
    if c.get("logo_wrong"):
        lines.append("- Logo: the scanned logo is wrong. ASK for the logo file.")
    return "\n".join(lines) + "\n"


STEP_I18N = {"meta": "rec.connect_meta", "telegram": "rec.pair_telegram", "google_ads": "rec.connect_google"}


def _rec_once(d, slug, step, prio, title, why, impact, cta):
    """One open next-step card per brand and onboarding step: a re-run (or a renamed brand) updates it in place. The card
    carries an i18n key (otto_i18n rec.*) so the client's e-mail / Telegram shows it in the brand's language."""
    name = (ap.brand(d, slug) or {}).get("name") or slug
    spec = {"key": STEP_I18N[step], "args": {"name": name}} if step in STEP_I18N else None
    for r in d.get("recommendations", []):
        if r.get("brand") == slug and r.get("onboard_step") == step and r.get("status") == "proposed":
            r.update(title=title, why=why, **({"i18n": spec} if spec else {}))
            return r
    return ap.add_rec(d, prio, title, why, impact, cta, brand=slug, source="otto_onboard", onboard_step=step,
                      **({"i18n": spec} if spec else {}))


def _may_update(allow_update, bid):
    """allow_update: True (owner / CLI), False (public onboarding), or the brand ids the signed-in client belongs to."""
    return allow_update is True or (not isinstance(allow_update, bool) and bid in (allow_update or ()))


def create(site, answers=None, peek=None, dry=False, scan=True, deadline=40.0, now=None, allow_update=True, member=None,
           account=None):
    """Onboard (or re-onboard) one site. See the module docstring. dry=True reads and scans but writes nothing.
    allow_update=False (public onboarding) or a set of brand ids (a signed-in client) raises Exists — before any network
    or write, and again inside the transaction — when the site already has a brand the caller may not change.
    member = the signed-in client's e-mail: added to brands[].members of the brand it creates (or already belongs to).
    account = the Google sign-in's users[] record (otto_auth): a brand it creates starts its free trial (otto_trial)."""
    url = site_url(site)
    key = host_key(url)
    a = clean_answers(answers)
    peek = _clean_peek(peek)
    member = ap.norm_member(member) if member else None
    existing = resolve_slug(ap.load(), url)[1]
    if existing is not None and not _may_update(allow_update, existing["id"]):
        raise Exists("this site is already set up with Otto: sign in to change it")
    t_end = time.time() + deadline

    # 1 · read the site (network, outside any lock)
    s, scan_info = None, {"ok": False}
    if scan:
        s = otto_scan.scan(url, pages=5, deadline=t_end)
        if "error" in s:
            scan_info = {"ok": False, "error": str(s["error"])[:160]}
            s = None
        else:
            scan_info = {"ok": True, "source": "site", "pages": len(s["pages"])}
    if s is None and peek:
        s = scan_from_peek(url, peek)
        scan_info.update({"ok": True, "source": "peek", "pages": peek.get("pages") or 1})
    if s is not None:
        apply_corrections(s, a["corrections"])

    industry = (s or {}).get("industry") or a["corrections"].get("industry") or "Unknown (?)"
    # the languages the site's text is written in (not every hreflang translation: "NL/DE" for a Dutch shop with a German
    # copy, "EN/ES" from an alphabetical list, would have Otto write in the wrong second language)
    langs = ((s or {}).get("content_languages") or ((s or {}).get("languages") or [])[:1]
             or ([a["corrections"]["language"]] if a["corrections"].get("language") else [])
             or [otto_scan.accept_language(key).split(",")[0]])     # unread bakkerij.nl writes Dutch, not English
    shop = bool(s) and bool(SHOP_PLATFORM.search(str(s.get("platform") or ""))
                            or (SHOP_INDUSTRY.search(industry) and (s.get("commerce") or {}).get("prices")))
    if not a["goal"]:
        a["goal"], a["_goal_default"] = default_goal(industry, shop), True
    restricted = bool(otto_compliance.HEALTH.search(" ".join([industry, ((s or {}).get("identity") or {}).get("title") or ""])))
    name = a["corrections"].get("name") or brand_name(s, key)
    lang = "/".join(x.upper() for x in langs[:2]) or "EN"
    # where the brand sells: a country TLD wins (.de → DE); then the currency its prices are in (USD → US; EUR says
    # nothing); then the owner's browser timezone (sent by the page); then the site language — brand-add's order plus
    # two signals. The timezone follows that country; the browser's own zone is used when it is in that country or
    # when nothing else is known.
    tld_country = ap.guess_country(key)
    currency = ap.currency_code(((s or {}).get("commerce") or {}).get("currency"))
    cur_country = ap.CURRENCY_COUNTRY.get(currency or "")
    tz_country = {tz_: cc for cc, tz_ in reversed(list(ap.COUNTRY_TZ.items()))}      # tz → country
    country = tld_country or cur_country or tz_country.get(a["tz"]) or ap.guess_country(key, lang)
    if tld_country or (country and tz_country.get(a["tz"]) != country and country in ap.COUNTRY_TZ):
        tz = ap.COUNTRY_TZ[country]
    else:
        tz = a["tz"] or ap.COUNTRY_TZ.get(country) or ap.DEFAULT_TZ
    note = "Restricted category on Meta: organic first, claims checked on every post" if RESTRICTED.search(industry) else ""
    stamp = ap.now_iso()
    onboarding = {"source": "onboarding.html", "updated_at": stamp, "goal": a["goal"], "budget": a["budget"],
                  "approvals": a["approvals"], "comms_lang": a.get("comms_lang") or "en", "channels": a["channels"],
                  "scan": scan_info.get("source") or "none"}
    wanted = [(k, sv) for k, sv in (("meta", "Instagram + Facebook"), ("google_ads", "Google Ads"), ("telegram", "Telegram"))
              if a["channels"].get(k)]

    # 2 · the brand record, connections and next-step cards: one transaction
    trial = None
    if dry:
        d = ap.load()
        slug, existing = resolve_slug(d, url)
        created = existing is None
    else:
        with ap.transaction() as d:
            slug, existing = resolve_slug(d, url)
            created = existing is None
            if not created and not _may_update(allow_update, existing["id"]):
                raise Exists("this site is already set up with Otto: sign in to change it")
            if created:
                plan_id, billing = ap.new_brand_plan()      # "starter"; "not billed yet" until a subscription is linked
                b = {"id": slug, "name": name, "url": key + otto_scan.site_path(url), "lang": lang, "tz": tz, "status": "onboarding",
                     "pillars": pillars_for(industry), "compliance": note, "plan": plan_id, "approvals": a["approvals"],
                     "comms_lang": a.get("comms_lang") or "en",
                     "copy_auto": True}                # self-serve: the copywriter (otto_copy) keeps its next 7 days written
                if billing:
                    b["plan_billing"] = billing
                if country:
                    b["countries"] = [country]
                if currency:
                    b["currency"] = currency
                d.setdefault("brands", []).append(b)
                if account and account.get("id"):         # a Google sign-up: the free trial (or "add a card") decides the plan
                    import otto_trial
                    trial = otto_trial.brand_on_signup(d, b, account["id"], key)
            else:
                b = existing
                if a["corrections"].get("name"):
                    b["name"] = name
                for k, v in (("lang", lang), ("tz", tz), ("pillars", pillars_for(industry)), ("compliance", note)):
                    if not b.get(k):
                        b[k] = v
                if currency and not b.get("currency"):
                    b["currency"] = currency
            onboarding["started_at"] = (b.get("onboarding") or {}).get("started_at") or stamp
            b["onboarding"] = onboarding
            if member and member not in (b.get("members") or []):
                b["members"] = list(b.get("members") or []) + [member]      # the client who set it up can see it
            conns = d.setdefault("connections", [])
            for k, service in wanted:
                cid = f"{'meta' if k == 'meta' else 'gads' if k == 'google_ads' else 'tg'}-{slug}"
                c = next((c for c in conns if c.get("id") == cid), None)
                if c is None:
                    conns.append({"id": cid, "service": service, "brand": b["name"], "status": "not_connected"})
                else:
                    c["brand"] = b["name"]                    # never touches status: a connected account stays connected
            status = {c["id"]: c.get("status") for c in conns}
            if a["channels"]["meta"] and status.get(f"meta-{slug}") != "connected":
                _rec_once(d, slug, "meta", "P0", f"Connect Instagram and Facebook for {b['name']}",
                          "Otto prepares the first week now, but it can only publish once Meta's own sign-in has linked "
                          "the Page and the Instagram account. You choose them; nothing posts without your approval.",
                          "Unblocks publishing", "Connect")
            if a["approvals"] == "telegram" and status.get(f"tg-{slug}") != "connected":
                _rec_once(d, slug, "telegram", "P1", f"Pair Telegram for {b['name']}",
                          "Approvals, the 07:35 report and alerts arrive in Telegram once your phone is paired. "
                          "Until then everything waits in the app.", "Approve from your phone", "Pair")
            if a["channels"]["google_ads"] and a["budget"] not in (None, "not_yet") and status.get(f"gads-{slug}") != "connected":
                _rec_once(d, slug, "google_ads", "P2", f"Connect Google Ads for {b['name']}",
                          "Search ads need your Google Ads account, linked through Google's own sign-in.",
                          "Search ads on your budget", "Connect")

    # 3 · brand files
    out = Path(ap.BRANDS) / slug
    files = []
    if not dry:
        out.mkdir(parents=True, exist_ok=True)
        if s is not None:
            files.append(_write(out / "scan.json", json.dumps(s, ensure_ascii=False, indent=2) + "\n"))
            if scan_info.get("source") == "site" and not a["corrections"].get("logo_wrong"):
                lf = otto_scan.save_logo(s, out, deadline=max(t_end, time.time() + 8))
                if lf:
                    files.append(str(lf))
        # strategy: init reads the brand record (tz, currency) + scan + profile; the owner's answers go in "inputs"
        with contextlib.redirect_stdout(io.StringIO()):
            st = otto_strategy.init(slug)
        sp = otto_strategy.BRANDS / slug / "strategy.json"
        prev_inputs = st.get("inputs") if isinstance(st.get("inputs"), dict) else {}
        cor = dict(prev_inputs.get("corrections") or {}, **a["corrections"])
        inputs = {"goal": a["goal"], "goal_label": GOALS[a["goal"]], "goal_source": "default" if a.get("_goal_default") else "owner",
                  "goal_note": a["goal_note"], "budget": a["budget"], "budget_label": BUDGETS.get(a["budget"] or ""),
                  "budget_amount": a["budget_amount"], "objection": a["objection"], "never_say": a["never_say"],
                  "channels": a["channels"], "approvals": a["approvals"], "corrections": cor, "source": "onboarding",
                  "answered_at": prev_inputs.get("answered_at") or stamp, "updated_at": stamp}
        if prev_inputs.get("profile_sha"):
            inputs["profile_sha"] = prev_inputs["profile_sha"]
        st["inputs"] = inputs
        if a["objection"] and not any((o.get("text") or "").strip().lower() == a["objection"][:160].lower()
                                      for o in st.get("objections") or []):
            st.setdefault("objections", []).insert(0, {"text": a["objection"][:160], "answer": Q, "proof_id": Q, "source": "owner"})
        st["ask"] = otto_strategy.gaps(st)[:4]
        # profile draft: brand-profile.md unless someone has edited it since Otto wrote it
        if s is not None:
            prof = out / "brand-profile.md"
            text = otto_scan.profile_draft(s) + _profile_answers(a, s, restricted)
            current = prof.read_text() if prof.exists() else None
            if current is None or _sha(current) == inputs.get("profile_sha"):
                files.append(_write(prof, text))
                inputs["profile_sha"] = _sha(text)
            else:
                files.append(_write(out / "brand-profile.draft.md", text))
        files.append(_write(sp, json.dumps(st, ensure_ascii=False, indent=2) + "\n"))
        # compliance: the owner's words to avoid
        phrases = never_say_phrases(a["never_say"])
        if phrases:
            cf = out / "compliance.json"
            try:
                rules = json.loads(cf.read_text()) if cf.exists() else None
            except Exception:
                rules = False                                # unreadable: leave it alone (it already fails closed)
            if rules is not False:
                if rules is None:
                    rules = {"banned": list(otto_compliance.HEALTH_BASELINE) if otto_compliance.baseline(slug) else [],
                             "required_disclaimer": None, "notes": "Created at onboarding from the owner's never-say list."}
                banned = [str(x) for x in rules.get("banned") or []]
                low = {x.lower() for x in banned}
                rules["banned"] = banned + [p for p in phrases if p.lower() not in low]
                rules["owner_never_say"] = list(dict.fromkeys((rules.get("owner_never_say") or []) + phrases))
                files.append(_write(cf, json.dumps(rules, ensure_ascii=False, indent=2) + "\n"))

    # 4 · what happens next
    if trial and trial.get("granted") and not dry:     # the trial's week is planned now, not on the 25th (otto_trial.kickoff)
        try:
            import otto_trial
            otto_trial.kickoff(slug, now=now)
        except Exception as e:                             # noqa: BLE001 — the hourly trials job retries it
            print(f"kickoff for {slug} deferred to the trials job: {type(e).__name__}: {e}", file=sys.stderr)
    d = ap.load()
    if dry:
        d = copy.deepcopy(d)
        if created:
            d.setdefault("brands", []).append({"id": slug, "name": name, "url": key, "tz": tz, "pillars": pillars_for(industry),
                                               "plan": ap.new_brand_plan()[0]})
    week, review = first_week(d, slug, now=now, approvals=a.get("approvals"))
    b = ap.brand(d, slug) or {}
    months = sorted({x["slot"][:7] for x in week}) or [(review or datetime.now()).strftime("%Y-%m")]
    stories = sum(1 for x in week if x.get("format") == "story")
    steps = [{"id": "scan", "title": "Read the site", "state": "done" if scan_info.get("source") == "site" else "todo",
              "detail": (f"{scan_info.get('pages')} pages read" if scan_info.get("source") == "site" else
                         "Read from the landing scan; the full read is retried" if scan_info.get("ok") else
                         "The site could not be read from the server yet")},
             {"id": "profile", "title": "Brand profile and strategy", "state": "done" if not dry and s is not None else "todo",
              "detail": "brand-profile.md and strategy.json, with your answers"},
             {"id": "plan", "title": "Plan the month", "state": "todo",
              "cmd": " && ".join(f"otto_plan.py build {slug} {ym}" for ym in months),
              "detail": f"{len(week) - stories} posts and {stories} stories in the first week"},
             {"id": "first_review", "title": "First review on your phone", "state": "todo",
              "when": review.isoformat(timespec="minutes") if review else None,
              "detail": (review.strftime("%A %d %B") + ", " + FIRST_REVIEW.get(a["approvals"], FIRST_REVIEW["app"])) if review else ""}]
    for k, title, how in (("telegram", "Pair Telegram", "A one-time link opens Otto's bot and pairs your phone."),
                          ("meta", "Connect Instagram and Facebook", "Through Meta's own sign-in. You pick the Page and account."),
                          ("google_ads", "Connect Google Ads", "Through Google's own sign-in, when you want search ads.")):
        if a["channels"].get(k):
            st_ = next((c.get("status") for c in d.get("connections", []) if c.get("id") ==
                        f"{'meta' if k == 'meta' else 'gads' if k == 'google_ads' else 'tg'}-{slug}"), "not_connected")
            steps.append({"id": k, "title": title, "state": "done" if st_ == "connected" else "todo", "detail": how})
    try:    # the country × industry compliance baselines that will check this brand's posts and ads (and what they hold)
        comp = otto_compliance.summary(slug, d=d, scan=s, countries=None if b.get("countries") else ([country] if country else None))
    except Exception as e:                                   # noqa: BLE001 — the summary never fails an onboarding
        comp = {"error": f"{type(e).__name__}: {e}"[:160]}
    out = {"ok": True, "dry": dry, "brand": slug, "name": b.get("name") or name, "created": created,
            "status": b.get("status") or "onboarding", "tz": b.get("tz") or tz, "files": files, "scan": scan_info,
            "first_review": review.isoformat(timespec="minutes") if review else None, "first_week": week,
            "pillars": b.get("pillars") or pillars_for(industry), "next_steps": steps, "compliance": comp}
    if trial is not None:
        out["trial"] = trial
    return out


# ---------------------------------------------------------------------------------------------------------------
# HTTP: POST /otto-api/onboard
# ---------------------------------------------------------------------------------------------------------------

MAX_BODY = 16384
MIN_GAP = 20.0               # seconds between two creates from one client
PUBLIC_CREATES_PER_HOUR = 30  # new brands from the unauthenticated route, all clients together
_rl_lock = threading.Lock()
_rl_last = {}
_public_creates = []         # timestamps of public creates in the last hour
_busy = threading.BoundedSemaphore(2)   # a create runs a 5-page scan: at most two at once


def http_create(raw, ip, cached_peek=None, deadline=25.0, public=False, bids=None, user=None, account=None):
    """Body of POST /otto-api/onboard, after otto_api's Content-Type + Origin checks. raw = request body (bytes),
    cached_peek = callable(url) → the server's own cached /otto-peek result or None. → (status code, JSON object).
    public=True (/otto-onboard, no login): create only — an existing brand answers 409 — and a global hourly cap.
    bids = the brand ids a signed-in client belongs to (None = the owner / admin, who may update any brand); such a
    client may update only those, and becomes a member (user) of a brand they create. account = a Google sign-in's users[]
    record: a brand it creates gets the free trial (otto_trial)."""
    allow_update = False if public else True if bids is None else set(bids)
    if raw is None or len(raw) > MAX_BODY:
        return 413, {"error": "request too large"}
    try:
        req = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "invalid JSON"}
    if not isinstance(req, dict):
        return 400, {"error": "JSON object expected"}
    try:
        url = site_url(req.get("site"))
        clean_answers(req.get("answers"))                  # validate before spending a slot
    except ValueError as e:
        return 400, {"error": str(e)[:200]}
    existing = resolve_slug(ap.load(), url)[1]
    if existing is not None and not _may_update(allow_update, existing["id"]):
        return 409, {"error": "this site is already set up with Otto: sign in to change it"}
    now = time.time()
    with _rl_lock:                                         # the rate limit comes before any DNS lookup
        if now - _rl_last.get(ip, 0) < MIN_GAP:
            return 429, {"error": "slow down"}
        _rl_last[ip] = now
        while len(_rl_last) > 5000:
            _rl_last.pop(next(iter(_rl_last)))
        if public:
            _public_creates[:] = [t for t in _public_creates if now - t < 3600]
            if len(_public_creates) >= PUBLIC_CREATES_PER_HOUR:
                return 429, {"error": "too many new sign-ups right now, try again later"}
            _public_creates.append(now)
    typed = url
    st, url = otto_scan.site_status(url)                 # example.nl that only answers as www.example.nl is read there
    if st != "ok":
        return 400, {"error": "that website address does not exist (check the spelling)" if st == "not_found"
                     else NOT_READABLE}
    if not _busy.acquire(timeout=2):
        return 503, {"error": "busy, try again in a few seconds"}
    try:
        peek = None
        if cached_peek:
            try:
                peek = cached_peek(typed) or (cached_peek(url) if url != typed else None)
            except Exception:
                peek = None
        return 200, create(url, req.get("answers"), peek=peek, deadline=deadline, allow_update=allow_update,
                           member=user if bids is not None else None, account=account if bids is not None else None)
    except Exists as e:
        return 409, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)[:200]}
    finally:
        _busy.release()


# ---------------------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------------------

def _print(res):
    print(f"{'would onboard' if res['dry'] else 'onboarded'} {res['name']} as {res['brand']} "
          f"({'new' if res['created'] else 'updated'}, status {res['status']}, tz {res['tz']})")
    sc = res["scan"]
    print(f"  scan: {'ok · ' + str(sc.get('source')) + ' · ' + str(sc.get('pages')) + ' page(s)' if sc.get('ok') else 'not read · ' + str(sc.get('error', 'skipped'))}")
    for f in res["files"]:
        print(f"  wrote {f}")
    if res["first_review"]:
        print(f"  first review: {res['first_review']} · first week: {len(res['first_week'])} posts")
    for x in res["first_week"][:8]:
        print(f"    {x['slot'].replace('T', ' ')}  {x['platform']:2}  {x['format']:8}  {x['pillar']}")
    print("  next:")
    for st in res["next_steps"]:
        print(f"    [{'x' if st['state'] == 'done' else ' '}] {st['title']}" + (f" · {st['cmd']}" if st.get("cmd") else "")
              + (f" · {st['detail']}" if st.get("detail") and not st.get("cmd") else ""))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "create" and len(argv) >= 2:
        def opt(k):
            return argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else None
        answers = json.loads(Path(opt("--answers")).read_text()) if opt("--answers") else {}
        peek = json.loads(Path(opt("--peek")).read_text()) if opt("--peek") else None
        try:
            res = create(argv[1], answers, peek=peek, dry="--dry" in argv, scan="--no-scan" not in argv)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr); return 2
        print(json.dumps(res, ensure_ascii=False, indent=2)) if "--json" in argv else _print(res)
        return 0
    if argv[0] == "show" and len(argv) >= 2:
        d = ap.load()
        slug = argv[1] if ap.brand(d, argv[1]) else next((b["id"] for b in d.get("brands", []) if _brand_host(b) == host_key(argv[1])), None)
        if not slug:
            print(f"no brand for {argv[1]}", file=sys.stderr); return 1
        sp = Path(ap.BRANDS) / slug / "strategy.json"
        st = json.loads(sp.read_text()) if sp.exists() else {}
        print(json.dumps({"brand": ap.brand(d, slug), "inputs": st.get("inputs"), "ask": st.get("ask")}, ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
