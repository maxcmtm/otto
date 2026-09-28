#!/usr/bin/env python3
"""Otto scanner — "Drop your URL. Otto reads your business."

  otto_scan.py <url> [--slug <slug>] [--pages 5] [--json] [--no-profile] [--force]
  otto_scan.py --peek <url>            # compact JSON (used by /otto-peek on the landing + dashboard)

Pure stdlib. Fetches the homepage plus up to N internal pages (about / products / pricing /
reviews / faq / blog / contact / menu / treatments), then extracts the brand DNA:
identity (title, description, og:*), languages, platform, VISUAL IDENTITY (palette from
inline + linked CSS, logo, fonts), socials, contact, currency + price points, trust anchors,
review-style quotes, headings, navigation, and an industry guess.

Writes brands/<slug>/scan.json and — if the brand has no profile yet — a
brands/<slug>/brand-profile.md draft following BRAND-PROFILE-TEMPLATE.md (AUTO sections
filled from the scan, inference sections marked for the creative engine to complete).
"""
import ipaddress, json, re, socket, sys, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
TEMPLATE = BRANDS / "BRAND-PROFILE-TEMPLATE.md"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 OttoScan/1.0")
PAGE_KEYS = ["about", "story", "team", "product", "shop", "collection", "service", "treatment", "menu",
             "pricing", "price", "plans", "review", "testimonial", "faq", "blog", "contact", "course"]
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
GENERIC_FONTS = {"inherit", "initial", "sans-serif", "serif", "monospace", "system-ui", "-apple-system",
                 "blinkmacsystemfont", "segoe ui", "roboto", "helvetica neue", "helvetica", "arial",
                 "ui-sans-serif", "ui-serif", "cursive", "fantasy", "var(--font-sans)", "unset"}
TRUST_WORDS = ["gmp", "iso 9001", "iso ", "fda", "lab tested", "lab-tested", "third-party", "third party",
               "certified", "certificate", "guarantee", "money-back", "money back", "free shipping",
               "kostenloser versand", "משלוח חינם", "secure checkout", "ssl", "since 19", "since 20",
               "years of experience", "award", "trustpilot", "google reviews", "5 stars", "5-star",
               "★", "⭐", "reviews", "bewertungen", "המלצות", "בוגרים", "graduates", "clients", "customers served"]
PROMO_RE = re.compile(r"((?<!\d)\d{1,2}\s?%\s?(?:off|rabatt|הנחה|discount)|free shipping|kostenloser versand|black friday|"
                      r"cyber monday|new arrival|limited time|bundle|gift card|use code [A-Z0-9]{3,}|sale\b)", re.I)
PRICE_RE = re.compile(r"(?:(?:€|\$|£|₪|EUR|USD|ILS|NIS|GBP|CHF|NOK|SEK|DKK)\s?\d{1,5}(?:[.,]\d{2})?)|"
                      r"(?:\d{1,5}(?:[.,]\d{2})?\s?(?:€|₪|\$|£|EUR|USD|ILS|NIS|kr\b|CHF))")
INDUSTRIES = {
    "CBD & hemp wellness": ["cbd", "hemp", "cannabinoid", "cbg", "cbn", "full spectrum", "broad spectrum"],
    "Restaurant & food": ["restaurant", "menu", "reservation", "chef", "dish", "brunch", "pizza", "sushi", "café", "cafe", "bistro"],
    "Clinic & medical": ["clinic", "patient", "treatment", "dental", "dentist", "doctor", "appointment", "therapy",
                         "botox", "aesthetic", "laser", "physio", "מרפאה", "מרפאת", "רופא", "קליניקה", "טיפולים"],
    "Education & courses": ["course", "academy", "college", "student", "curriculum", "learn", "training",
                            "certificate", "diploma", "webinar", "lesson", "מכללה", "מכללת", "קורס", "בוגרים",
                            "לימודים", "לימודי", "הכשרה", "הכשרת", "דיפלומה", "סילבוס", "סטודנטים"],
    "Marketing & agency": ["marketing", "agency", "seo", "social media", "branding", "campaign", "content creation",
                           "autopilot", "advertising", "ads"],
    "E-commerce & retail": ["add to cart", "cart", "checkout", "shipping", "shop", "collection", "free shipping",
                            "returns", "warenkorb", "versand"],
    "Real estate": ["real estate", "property", "apartment", "villa", "sqm", "m²", "for sale", "listing", "mortgage", "נדל"],
    "SaaS & software": ["software", "platform", "api", "integration", "dashboard", "free trial", "sign up", "saas", "workflow"],
    "Fitness & gym": ["gym", "fitness", "workout", "membership", "trainer", "yoga", "pilates", "crossfit"],
    "Beauty & spa": ["spa", "massage", "facial", "salon", "beauty", "nails", "lashes", "med spa", "skincare"],
    "Legal & finance": ["attorney", "lawyer", "legal", "accounting", "tax", "insurance", "loan", "trading", "broker", "עורך דין"],
    "Hotel & travel": ["hotel", "rooms", "booking", "resort", "guest", "travel", "tour", "check-in"],
    "Coaching & consulting": ["coach", "coaching", "consulting", "mentor", "mastermind", "program", "1:1"],
    "Home & construction": ["renovation", "construction", "roofing", "plumbing", "solar", "interior", "furniture", "kitchen"],
    "Automotive": ["dealership", "vehicle", "tires", "garage", "car wash", "auto repair"],
}


# ---------------- fetching ----------------

def normalize_url(u):
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def host_of(u):
    return (urllib.parse.urlsplit(u).hostname or "").lower()


def safe_host(u):
    """Only public http(s) hosts — used by the public /otto-peek endpoint (SSRF guard)."""
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.port not in (None, 80, 443):
        return False
    if p.hostname in ("localhost",) or p.hostname.endswith(".local") or p.hostname.endswith(".internal"):
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def fetch(url, limit=1_500_000, timeout=12):
    """Returns (final_url, text, content_type). Follows redirects. Never raises on HTTP errors > returns ''."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                                               "Accept-Language": "en,de;q=0.8,he;q=0.7"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(limit)
            ctype = r.headers.get("Content-Type", "")
            charset = r.headers.get_content_charset() or "utf-8"
            return r.geturl(), raw.decode(charset, "ignore"), ctype
    except Exception as e:  # network / http errors: caller decides
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

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); self._depth += 1
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
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


def palette_from(texts):
    c = Counter()
    for t in texts:
        for m in re.findall(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", t):
            c[hex6(m)] += 1
    brand = [(h, n) for h, n in c.most_common() if not is_neutral(h)][:8]
    neutral = [(h, n) for h, n in c.most_common() if is_neutral(h)][:4]
    return [{"hex": h, "count": n} for h, n in brand], [{"hex": h, "count": n} for h, n in neutral]


def fonts_from(css_texts, links):
    c = Counter()
    for t in css_texts:
        for fam in re.findall(r"font-family\s*:\s*([^;}]+)", t, re.I):
            first = fam.split(",")[0].strip().strip("'\"").strip()
            if first and first.lower() not in GENERIC_FONTS and not first.startswith("var(") and len(first) < 40:
                c[first] += 1
    for href, *_ in links:
        if "fonts.googleapis.com" in href:
            for group in re.findall(r"family=([^&]+)", urllib.parse.unquote(href)):
                for fam in group.split("|"):
                    name = fam.split(":")[0].replace("+", " ").strip()
                    if name:
                        c[name] += 5
    return [pretty_font(f) for f, _ in c.most_common(8) if "fallback" not in f.lower()][:5]


def pretty_font(name):
    """'adobe-caslon-w01-smbd' → 'Adobe Caslon Smbd'; keeps proper names as they are."""
    n = re.sub(r"-w\d\d-?", "-", name)
    if re.fullmatch(r"[a-z0-9-]+", n):
        n = " ".join(w.capitalize() for w in n.split("-") if w)
    return n.strip()


SOCIAL = [("facebook", r"facebook\.com/(?!sharer|share|dialog|plugins)[^/?#\s\"']+"),
          ("instagram", r"instagram\.com/[^/?#\s\"']+"),
          ("tiktok", r"tiktok\.com/@[^/?#\s\"']+"),
          ("linkedin", r"linkedin\.com/(?:company|in)/[^/?#\s\"']+"),
          ("youtube", r"youtube\.com/(?:@|channel/|c/|user/)[^/?#\s\"']+"),
          ("x", r"(?:twitter|x)\.com/(?!intent|share)[^/?#\s\"']+"),
          ("whatsapp", r"(?:wa\.me/\d+|api\.whatsapp\.com/send[^\s\"']*)"),
          ("telegram", r"t\.me/[^/?#\s\"']+"),
          ("pinterest", r"pinterest\.[a-z.]+/[^/?#\s\"']+")]


def socials_from(hrefs):
    out = {}
    for h in hrefs:
        for name, pat in SOCIAL:
            if name in out:
                continue
            m = re.search(pat, h, re.I)
            if m:
                out[name] = "https://" + m.group(0)
    return out


def detect_platform(html):
    h = html
    checks = [("Shopify", "cdn.shopify.com"), ("WooCommerce", "plugins/woocommerce"), ("WordPress", "wp-content"),
              ("Wix", "wixstatic.com"), ("Webflow", "assets.website-files.com"), ("Squarespace", "squarespace.com"),
              ("Next.js", "/_next/"), ("Nuxt", "/_nuxt/"), ("Elementor", "plugins/elementor"), ("HubSpot", "hs-scripts"),
              ("Framer", "framerusercontent"), ("Duda", "cdn-cms.duda"), ("Wix", "parastorage.com")]
    found = [n for n, s in checks if s in h]
    return " + ".join(dict.fromkeys(found)) or "custom"


def detect_langs(lang_attr, hreflangs, text):
    langs = []
    if lang_attr:
        langs.append(lang_attr.split("-")[0].lower())
    for h in sorted(hreflangs):
        if h != "x-default":
            langs.append(h.split("-")[0])
    sample = text[:20000]
    if len(re.findall(r"[֐-׿]", sample)) > 200:
        langs.append("he")
    if len(re.findall(r"[؀-ۿ]", sample)) > 200:
        langs.append("ar")
    if len(re.findall(r"[Ѐ-ӿ]", sample)) > 200:
        langs.append("ru")
    if len(re.findall(r"\b(und|der|die|das|mit|nicht|für)\b", sample)) > 25:
        langs.append("de")
    if len(re.findall(r"\b(les|des|une|pour|avec|vous)\b", sample)) > 25:
        langs.append("fr")
    return list(dict.fromkeys(langs))


def industry_guess(title, desc, headings, nav, body):
    strong = " ".join([title, desc] + headings).lower()
    navs = " ".join(nav).lower()
    body = body.lower()[:60000]
    def cnt(text, k):
        return len(re.findall(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", text))
    scores = {}
    for name, kws in INDUSTRIES.items():
        s = 0
        for k in kws:
            s += 5 * cnt(strong, k) + 3 * cnt(navs, k) + min(cnt(body, k), 20)
        scores[name] = s
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top = [{"industry": n, "score": s} for n, s in ranked[:3] if s > 0]
    guess = ranked[0][0] if ranked and ranked[0][1] >= 6 else "Unknown (?)"
    return guess, top


def trust_from(text):
    low = text.lower()
    out, seen = [], set()
    for w in TRUST_WORDS:
        i = low.find(w.lower())
        if i < 0:
            continue
        s = max(0, low.rfind(".", 0, i) + 1); e = low.find(".", i)
        snippet = re.sub(r"\s+", " ", text[s:(e if 0 < e < i + 160 else i + 120)]).strip()
        key = snippet[:60].lower()
        if snippet and key not in seen and 8 <= len(snippet) <= 200:
            seen.add(key); out.append(snippet)
    return out[:10]


def prices_from(text):
    found = PRICE_RE.findall(text)
    cur = Counter()
    for f in found:
        for sym, code in (("€", "EUR"), ("₪", "ILS"), ("$", "USD"), ("£", "GBP"), ("EUR", "EUR"), ("USD", "USD"),
                          ("ILS", "ILS"), ("NIS", "ILS"), ("GBP", "GBP"), ("CHF", "CHF"), ("kr", "NOK/SEK/DKK")):
            if sym in f:
                cur[code] += 1; break
    uniq = list(dict.fromkeys(f.strip() for f in found))
    return (cur.most_common(1)[0][0] if cur else None), uniq[:10]


def quotes_from(pages_quotes, text):
    out = list(dict.fromkeys(pages_quotes))
    for sent in re.split(r"(?<=[.!?])\s+", text[:80000]):
        if ("★" in sent or "⭐" in sent or re.search(r"\b5 stars\b|\b5/5\b", sent, re.I)) and 40 <= len(sent) <= 300:
            out.append(sent.strip())
    return [q[:260] for q in dict.fromkeys(out)][:8]


def logo_from(base, imgs, links, metas):
    for src, alt, cls in imgs:
        blob = (src + " " + alt + " " + cls).lower()
        if "logo" in blob and src and not src.startswith("data:") and not re.search(
                r"investor|partner|client|customer|badge|payment|trust|press|award|brand-?logos|sponsor|testimonial|review", blob):
            return absolute(base, src)
    for href, _, rel, _ in links:
        if "apple-touch-icon" in rel:
            return absolute(base, href)
    if metas.get("og:image"):
        return absolute(base, metas["og:image"])
    for href, _, rel, _ in links:
        if "icon" in rel:
            return absolute(base, href)
    return None


# ---------------- main scan ----------------

def pick_internal(base, links, n):
    host = host_of(base)
    seen, out = set(), []
    for href, text, rel, _ in links:
        if rel != "a":
            continue
        u = absolute(base, href)
        if host_of(u) != host or u.split("#")[0] == base.split("#")[0]:
            continue
        path = urllib.parse.urlsplit(u).path.lower()
        if any(k in path for k in PAGE_KEYS) and u not in seen and not re.search(r"\.(png|jpe?g|pdf|zip)$", path):
            seen.add(u); out.append(u.split("#")[0])
        if len(out) >= n:
            break
    return out


def scan(url, pages=5, page_limit=1_200_000):
    url = normalize_url(url)
    final, html, ctype = fetch(url)
    if not html:
        return {"url": url, "error": ctype or "empty response"}
    home = parse(html)
    internal = pick_internal(final, home.links, pages)
    subpages = []
    for u in internal:
        _, h, ct = fetch(u, limit=page_limit)
        if h and "text/html" in ct:
            subpages.append((u, parse(h)))

    # css for palette + fonts
    css_texts = list(home.styles)
    css_links = [absolute(final, href) for href, _, rel, _ in home.links if "stylesheet" in rel][:4]
    for cu in css_links:
        _, c, _ = fetch(cu, limit=400_000)
        if c:
            css_texts.append(c)
    palette, neutrals = palette_from([html] + css_texts)
    theme = home.metas.get("theme-color")
    if theme and re.match(r"^#[0-9a-fA-F]{3,6}$", theme):
        t = hex6(theme)
        if not any(p["hex"] == t for p in palette) and not is_neutral(t):
            palette.insert(0, {"hex": t, "count": 0, "source": "theme-color"})

    all_pages = [(final, home)] + subpages
    text = " ".join(t for _, p in all_pages for t in p.texts)
    headings = [h for _, p in all_pages for _, h in p.headings]
    nav = [t for href, t, rel, _ in home.links if rel == "a" and t and len(t) < 32][:40]
    hrefs = [absolute(final, href) for _, p in all_pages for href, _, _, _ in p.links]
    quotes = quotes_from([q for _, p in all_pages for q in p.quotes], text)
    currency, prices = prices_from(text)
    guess, candidates = industry_guess(home.title, home.metas.get("description", ""), headings[:20], nav, text)
    emails = list(dict.fromkeys(re.findall(r"mailto:([^\s\"'?]+)", html)))[:3]
    phones = list(dict.fromkeys(re.findall(r"tel:([+\d][\d\-\s().]{6,})", html)))[:3]
    promos = list(dict.fromkeys(m.strip() for m in PROMO_RE.findall(text)))[:8]

    return {
        "url": url, "final_url": final, "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages": [final] + [u for u, _ in subpages],
        "identity": {"title": home.title.strip()[:200], "description": (home.metas.get("description") or home.metas.get("og:description") or "")[:400],
                     "site_name": home.metas.get("og:site_name") or "", "og_title": home.metas.get("og:title") or "",
                     "og_image": absolute(final, home.metas["og:image"]) if home.metas.get("og:image") else None},
        "industry": guess, "industry_candidates": candidates,
        "languages": detect_langs(home.lang, home.hreflangs, text), "platform": detect_platform(html),
        "visual": {"palette": palette[:6], "neutrals": neutrals[:3], "logo": logo_from(final, home.imgs, home.links, home.metas),
                   "fonts": fonts_from(css_texts, home.links), "theme_color": theme},
        "socials": socials_from(hrefs), "contact": {"emails": emails, "phones": [p.strip() for p in phones]},
        "commerce": {"currency": currency, "prices": prices, "promos": promos},
        "trust": trust_from(text), "quotes": quotes,
        "headings": list(dict.fromkeys(headings))[:25], "nav": list(dict.fromkeys(nav))[:25],
        "text_sample": re.sub(r"\s+", " ", text)[:1500],
    }


def peek(url):
    """Compact scan for the landing/dashboard 'peek' (homepage + 2 pages, fast)."""
    s = scan(url, pages=2, page_limit=600_000)
    if "error" in s:
        return s
    return {"url": s["final_url"], "title": s["identity"]["title"] or s["identity"]["site_name"],
            "description": s["identity"]["description"], "industry": s["industry"],
            "candidates": s["industry_candidates"], "palette": [p["hex"] for p in s["visual"]["palette"][:5]],
            "neutrals": [p["hex"] for p in s["visual"]["neutrals"][:2]], "logo": s["visual"]["logo"],
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
    name = idn["site_name"] or idn["title"].split("|")[0].split("–")[0].split("-")[0].strip() or host_of(s["final_url"])
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
