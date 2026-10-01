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
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36 OttoScan/1.0")
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
                 "apple color emoji", "segoe ui emoji", "segoe ui symbol", "noto color emoji"}
# icon fonts (glyphs, not a typeface the brand writes in): Font Awesome, Material Icons / Symbols, "HemaSvgIcons", icomoon …
ICON_FONT = re.compile(r"icon|awesome|material.?symbols|glyph|dashicons|fontello|ionic|feather|remixicon|bootstrap.?icons", re.I)
TRUST_WORDS = ["gmp", "iso 9001", "iso ", "fda", "lab tested", "lab-tested", "third-party", "third party",
               "certified", "certificate", "guarantee", "money-back", "money back", "free shipping",
               "kostenloser versand", "משלוח חינם", "secure checkout", "ssl", "since 19", "since 20",
               "years of experience", "award", "trustpilot", "google reviews", "5 stars", "5-star",
               "★", "⭐", "reviews", "bewertungen", "המלצות", "בוגרים", "graduates", "clients", "customers served"]
PROMO_RE = re.compile(r"((?<!\d)\d{1,2}\s?%\s?(?:off|rabatt|הנחה|discount)|free shipping|kostenloser versand|black friday|"
                      r"cyber monday|new arrival|limited time|bundle|gift card|use code [A-Z0-9]{3,}|sale\b)", re.I)
# amounts with thousands separators first ("2.900 €", "₪18,500", "€1,234.56") — the plain form alone read them as "900 €" / "₪18,50"
AMOUNT = r"(?:\d{1,3}(?:[.,\u00a0\u202f]\d{3})+(?:[.,]\d{2})?(?!\d)|\d{1,5}(?:[.,]\d{2})?)"
PRICE_RE = re.compile(r"(?:(?:€|\$|£|₪|EUR|USD|ILS|NIS|GBP|CHF|NOK|SEK|DKK)\s?" + AMOUNT + r")|"
                      r"(?:" + AMOUNT + r"\s?(?:€|₪|\$|£|EUR|USD|ILS|NIS|kr\b|CHF))")
INDUSTRIES = {
    "CBD & hemp wellness": ["cbd", "hemp", "cannabinoid", "cbg", "cbn", "full spectrum", "broad spectrum"],
    "Restaurant & food": ["restaurant", "menu", "reservation", "chef", "dish", "brunch", "pizza", "sushi", "café", "cafe", "bistro"],
    "Clinic & medical": ["clinic", "patient", "treatment", "dental", "dentist", "doctor", "appointment", "therapy",
                         "botox", "aesthetic", "laser", "physio", "מרפאה", "מרפאת", "רופא", "קליניקה", "טיפולים",
                         "zahnarzt", "zahnarztpraxis", "zahnmedizin", "arztpraxis", "patienten", "clínica", "dentista",
                         "tandarts", "tandartspraktijk", "studio dentistico", "odontoiatria", "cabinet dentaire", "médecin"],
    "Education & courses": ["course", "academy", "college", "student", "curriculum", "learn", "training",
                            "certificate", "diploma", "webinar", "lesson", "מכללה", "מכללת", "קורס", "בוגרים",
                            "לימודים", "לימודי", "הכשרה", "הכשרת", "דיפלומה", "סילבוס", "סטודנטים",
                            "kurs", "kurse", "ausbildung", "weiterbildung", "curso", "cursos", "aulas", "escola", "formação",
                            "cursus", "opleiding", "corso", "corsi", "scuola", "formazione", "école", "formation", "escuela"],
    "Marketing & agency": ["marketing", "agency", "seo", "social media", "branding", "campaign", "content creation",
                           "autopilot", "advertising", "ads"],
    "Supplements & nutrition": ["supplement", "supplements", "vitamin", "vitamins", "multivitamin", "gummies", "gummy",
                                "superfood", "superfoods", "greens powder", "probiotic", "prebiotic", "collagen", "protein powder",
                                "nutrients", "daily nutrition", "electrolytes", "creatine", "adaptogen", "nahrungsergänzung",
                                "vitamine", "suplemento", "suplementos", "integratore", "integratori", "complément alimentaire"],
    "E-commerce & retail": ["add to cart", "cart", "checkout", "shipping", "shop", "collection", "free shipping",
                            "returns", "warenkorb", "versand", "winkelwagen", "afrekenen", "verzending", "webshop", "bestellen",
                            "carrinho", "loja online", "envio", "carrello", "spedizione", "panier", "livraison", "carrito", "envío"],
    "Real estate": ["real estate", "property", "apartment", "villa", "sqm", "m²", "for sale", "listing", "mortgage", "נדל"],
    "SaaS & software": ["software", "platform", "api", "integration", "dashboard", "free trial", "sign up", "saas", "workflow"],
    "Fitness & gym": ["gym", "fitness", "workout", "membership", "trainer", "yoga", "pilates", "crossfit"],
    "Beauty & spa": ["spa", "massage", "facial", "salon", "beauty", "nails", "lashes", "med spa", "skincare"],
    "Legal & finance": ["attorney", "lawyer", "legal", "accounting", "tax", "insurance", "loan", "trading", "broker", "עורך דין"],
    "Hotel & travel": ["hotel", "rooms", "booking", "resort", "guest", "travel", "tour", "check-in"],
    "Coaching & consulting": ["coach", "coaching", "consulting", "mentor", "mastermind", "program", "1:1"],
    "Home & construction": ["renovation", "construction", "roofing", "plumbing", "solar", "interior", "furniture", "kitchen",
                            "arredamento", "arredo", "ristrutturazione", "interni", "innenarchitektur", "renovierung", "interieur",
                            "verbouwing", "remodelação", "decoração"],
    "Automotive": ["dealership", "vehicle", "tires", "garage", "car wash", "auto repair"],
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
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


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
    hdrs = {"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en,de;q=0.8,he;q=0.7",
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
    out = [pretty_font(f) for f, _ in c.most_common(8) if "fallback" not in f.lower()]
    return [f for f in out if FONT_NAME.fullmatch(f)][:5]           # a family name, never CSS or markup from the page


FONT_NAME = re.compile(r"[\w .-]{1,40}")


def pretty_font(name):
    """'adobe-caslon-w01-smbd' → 'Adobe Caslon Smbd'; keeps proper names as they are."""
    n = re.sub(r"-w\d\d-?", "-", name)
    if re.fullmatch(r"[a-z0-9-]+", n):
        n = " ".join(w.capitalize() for w in n.split("-") if w)
    return n.strip()


SOCIAL = [("facebook", r"facebook\.com/(?!sharer|share|dialog|plugins)[\w.@%+~-]+"),
          ("instagram", r"instagram\.com/[\w.@%+~-]+"),
          ("tiktok", r"tiktok\.com/@[\w.@%+~-]+"),
          ("linkedin", r"linkedin\.com/(?:company|in)/[\w.@%+~-]+"),
          ("youtube", r"youtube\.com/(?:@|channel/|c/|user/)[\w.@%+~-]+"),
          ("x", r"(?:twitter|x)\.com/(?!intent|share)[\w.@%+~-]+"),
          ("whatsapp", r"(?:wa\.me/\d+|api\.whatsapp\.com/send[\w.@%+~=&?/-]*)"),
          ("telegram", r"t\.me/[\w.@%+~-]+"),
          ("pinterest", r"pinterest\.[a-z.]+/[\w.@%+~-]+")]


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


def lang_code(v):
    """'de-AT' / 'pt_BR' → 'de' / 'pt'; None for anything that is not a language code (the page wrote it)."""
    c = re.split(r"[-_]", str(v or "").strip().lower(), maxsplit=1)[0]
    return c if re.fullmatch(r"[a-z]{2,3}", c) else None


def web_url(u):
    """An http(s) URL we are willing to store and show (a logo, an og:image), else None: never javascript:/data:."""
    u = str(u or "").strip().replace(" ", "%20")
    return u if len(u) <= 1000 and re.match(r"^https?://[^\s\"'<>\\]+$", u, re.I) else None


def detect_langs(lang_attr, hreflangs, text):
    langs = []
    for code in [lang_attr] + sorted(h for h in hreflangs if h != "x-default"):
        if lang_code(code):
            langs.append(lang_code(code))
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
    # "E-commerce & retail" describes the channel, not the business: when a specific vertical scores at least
    # a third of it, the vertical wins (a supplement shop is a supplement brand first — its claims rules apply).
    if ranked and ranked[0][0] == "E-commerce & retail":
        vert = next(((n, v) for n, v in ranked[1:] if n not in ("Marketing & agency", "SaaS & software")), None)
        if vert and vert[1] >= max(12, ranked[0][1] / 3):
            ranked.remove(vert); ranked.insert(0, vert)
    top = [{"industry": n, "score": s} for n, s in ranked[:3] if s > 0]
    guess = ranked[0][0] if ranked and ranked[0][1] >= 6 else "Unknown (?)"
    return guess, top


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
                         r"one time purchase|pause or cancel|delivered once|jetzt kaufen|jetzt bestellen|in den warenkorb)\b|"
                         r"free shipping on", re.I)
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
    return bool(_PROMO_TALK.search(t) or _RATING_SUMMARY.search(t) or _DISCLAIMER.search(t) or soup
                or len(_EMOJI.findall(t)) >= 3 or len(re.findall(r"[●•|]", t)) >= 3)


_TRUST_RES = [(w, re.compile((r"(?<![\w])" if w[:1].isalnum() else "") + re.escape(w.lower().strip())
                             + (r"(?![\w])" if w.strip()[-1:].isalnum() else ""))) for w in TRUST_WORDS]


def trust_from(text):
    """Sentences that carry a trust signal (certifications, lab tests, guarantees …). Words match whole ("ssl" is not
    "hassle"); promos and button soup are dropped; long sentences are cut at a word, with an ellipsis."""
    low = text.lower()
    out, seen = [], set()
    for w, rx in _TRUST_RES:
        for n, m in enumerate(rx.finditer(low)):             # the first mention may sit in a promo bar: try a few
            if n >= 5:
                break
            i = m.start()
            s = max(0, low.rfind(".", 0, i) + 1); e = low.find(".", i)
            snippet = clip(text[s:e + 1] if 0 < e < i + 200 else text[s:i + 400], 200)
            key = snippet[:60].lower()
            if key in seen:
                continue
            if 8 <= len(snippet) and not is_chrome(snippet):
                seen.add(key); out.append(snippet)
                break
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


def clean_quote(q):
    """A customer's words from a review widget, or None: the widget's metadata before them ("4 months ago … Tom Berger
    Reviewer 5/5") is cut off, star runs are dropped, and page chrome (promo, rating summary, disclaimer) is no quote."""
    q = re.sub(r"\s+", " ", q or "").strip()
    q = _WIDGET_META.sub("", q, count=1) if _WIDGET_META.search(q) else q
    q = re.sub(r"[★☆⭐️]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip(" -–—|•")
    if len(q) < 25 or is_chrome(q) or not re.search(r"[^\W\d_]{3,}.*\s.*[^\W\d_]{3,}", q):
        return None
    return clip(q, 260)


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


def logo_from(base, imgs, links, metas):
    host = re.sub(r"^www\.", "", host_of(base) or "").split(".")[0]
    # 1. an image that names the brand itself (header logos usually carry the brand in src/alt). Match the file
    #    name, not the whole src: on a store every CDN path carries the host ("//gruns.co/cdn/…/usnacks_logo.svg")
    for src, alt, cls in imgs:
        blob = _fold(src.split("?")[0].rsplit("/", 1)[-1] + " " + alt + " " + cls)
        if host and len(host) > 2 and host in blob and _logo_hint(src, alt, cls) and src and not src.startswith("data:") \
                and not PRESS_LOGO.search(src.rsplit("/", 1)[-1]):
            return absolute(base, src)
    for src, alt, cls in imgs:
        if PRESS_LOGO.search((src.rsplit("/", 1)[-1] + " " + alt).lower()):
            continue                                     # "As seen in" strips: Forbes, GQ, Today…
        blob = (src + " " + alt + " " + cls).lower()
        if _logo_hint(src, alt, cls) and src and not src.startswith("data:") and not re.search(
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


def scan(url, pages=5, page_limit=1_200_000, deadline=None):
    """deadline (epoch seconds) bounds the whole scan: fetches past it are skipped."""
    url = normalize_url(url)
    final, html, ctype = fetch(url, deadline=deadline)
    if not html:
        return {"url": url, "error": ctype or "empty response"}
    home = parse(html)
    internal = pick_internal(final, home.links, pages)
    subpages = []
    for u in internal:
        if deadline and time.time() > deadline - 1:
            break
        _, h, ct = fetch(u, limit=page_limit, deadline=deadline)
        if h and "text/html" in ct:
            subpages.append((u, parse(h)))

    # css for palette + fonts
    css_texts = list(home.styles)
    css_links = [absolute(final, href) for href, _, rel, _ in home.links if "stylesheet" in rel][:4]
    for cu in css_links:
        if deadline and time.time() > deadline - 1:
            break
        _, c, _ = fetch(cu, limit=400_000, deadline=deadline)
        if c:
            css_texts.append(c)
    palette, neutrals = palette_from([html] + css_texts)
    theme = (home.metas.get("theme-color") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|rgba?\([\d\s.,%]+\)", theme):
        theme = None                                  # only a CSS colour is stored (it lands in scan.json + the profile)
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
                     "og_image": web_url(absolute(final, home.metas["og:image"])) if home.metas.get("og:image") else None},
        "industry": guess, "industry_candidates": candidates,
        "languages": detect_langs(home.lang, home.hreflangs, text), "platform": detect_platform(html),
        "visual": {"palette": palette[:6], "neutrals": neutrals[:3], "logo": web_url(logo_from(final, home.imgs, home.links, home.metas)),
                   "fonts": fonts_from(css_texts, home.links), "theme_color": theme},
        "socials": socials_from(hrefs), "contact": {"emails": emails, "phones": [p.strip() for p in phones]},
        "commerce": {"currency": currency, "prices": prices, "promos": promos},
        "trust": trust_from(text), "quotes": quotes,
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
    name = idn["site_name"] or re.split(r"\s[|–—-]\s", idn["title"] or "")[0].strip() or host_of(s["final_url"])
    return {"url": s["final_url"], "title": idn["title"] or idn["site_name"], "name": name,   # og:site_name "Grüns", not the page title
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
