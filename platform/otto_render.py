#!/usr/bin/env python3
"""Otto render: agency-grade static ads and carousel cards, HTML templates shot by headless Chrome.

  otto_render.py demo <brand> <out_dir> [--only a,b]          # every template, realistic copy, brand photos
  otto_render.py one <template> <json-data|file.json> <out> [--brand <id>] [--size 1080x1920|story|square]
  otto_render.py check <template> <json-data|file.json> [--brand <id>] [--size …]   # does the copy fit? exit 3 if not
  otto_render.py sheet <out.jpg> <dir-or-image> [...]         # labelled contact sheet of renders
  otto_render.py tokens <brand>                               # the design tokens a brand renders with
  otto_render.py list                                         # templates

Templates (platform/templates/ads/<name>.html; data fields documented at the top of each file):
  editorial · big_number · quote · before_after · myth_fact · checklist · offer · comparison ·
  carousel_cover · carousel_inner · carousel_cta · founder_note · event
Plain HTML + CSS with {{key}} (HTML-escaped; inside a tag it is attribute-escaped), {{&key}} (raw, internal),
{{#each list}}…{{/each}} ({{.}}, {{@n}}, {{@nn}}, {{@first}}, {{@last}}), {{#if}}…{{else}}…{{/if}}, {{#unless}},
{{> partial}} (_partial.html). A missing key renders as nothing, never as a literal placeholder. In copy,
*word* becomes the accent <em>, \n a line break, a blank line a paragraph; numbers are bidi-isolated so
"10,000+" never flips in Hebrew.

Every string is cleaned first: markdown markers, arrows, "(?)", {placeholders}, [TBD]s and emoji go, and a
field carrying internal data (CPL, CPA, ROAS, budget, lead counts) is dropped with a warning. Copy shrinks
to fit its box (_fit.js); fit_report() / `check` say when it still does not fit. Sizes: 1080x1350 feed
(default), 1080x1920 story (text only between the top 14 % and the bottom 35 %, the Meta Reels/Stories
safe zone), 1080x1080 square. layout "auto" keeps text off bright photos (ffmpeg luma probe → split).

Brand tokens (brand_tokens): palette from the profile's VISUAL IDENTITY section (a colour labelled CTA is
the accent, "UI only" colours are skipped, a labelled background is the deep tone) plus scan.json;
contrast-checked derivatives (accent on dark ≥ 4.5:1; on paper the accent itself, a darker shade, or a
highlighter band behind ink for light accents such as yellow); a font pair by language (he: Heebo +
Assistant + Frank Ruhl Libre; else Inter Tight + Inter + Instrument Serif). brands/<slug>/render.json
overrides any token; brands/<slug>/logo.svg|png replaces the wordmark. Google Fonts are fetched once,
inlined as data URIs and cached in ~/.cache/otto/fonts (OTTO_FONT_CACHE); offline: <link> + system fonts.

Browser: env OTTO_CHROME, then google-chrome, chromium, chromium-browser, macOS Google Chrome, then the
HyperFrames chrome-headless-shell cache. None found → BrowserNotFound (callers fall back to the ffmpeg
overlay in otto_creative). JPEG out via ffmpeg -q:v 2; a .png out path keeps the PNG. OTTO_RENDER_TMP sets
where page files are written (a snap Chromium cannot read /tmp). Python 3.9 stdlib only.
"""
import base64, glob, hashlib, html, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATES = Path(os.environ.get("OTTO_TEMPLATES") or HERE / "templates" / "ads")
BRANDS = Path(os.environ.get("OTTO_BRANDS") or ROOT / "brands")
FONT_CACHE = Path(os.environ.get("OTTO_FONT_CACHE") or Path.home() / ".cache" / "otto" / "fonts")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

SIZES = {"feed": (1080, 1350), "story": (1080, 1920), "square": (1080, 1080)}
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HF_SHELL = "~/.cache/hyperframes/chrome/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell"


class RenderError(RuntimeError):
    pass


class BrowserNotFound(RenderError):
    pass


# ---------------------------------------------------------------- browser

def find_browser():
    """Path of a Chrome/Chromium that can run --headless --screenshot. Raises BrowserNotFound."""
    env = os.environ.get("OTTO_CHROME", "").strip()
    if env:
        p = shutil.which(env) or (env if Path(env).expanduser().is_file() else None)
        if p:
            return str(Path(p).expanduser())
        raise BrowserNotFound(f"OTTO_CHROME={env} is not an executable")
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    if Path(MAC_CHROME).is_file():
        return MAC_CHROME
    shells = sorted(glob.glob(os.path.expanduser(HF_SHELL)), reverse=True)
    if shells:
        return shells[0]
    raise BrowserNotFound("no headless Chrome found: set OTTO_CHROME, or install one "
                          "(Ubuntu: sudo apt-get install -y chromium-browser fonts-noto-core, or Google Chrome's .deb)")


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _tmp_root():
    """Where page files go. OTTO_RENDER_TMP overrides: a snap-packaged Chromium cannot read the host's /tmp."""
    d = os.environ.get("OTTO_RENDER_TMP")
    if d:
        Path(d).mkdir(parents=True, exist_ok=True)
    return d or None


def screenshot(html_text, png_path, size, budget=6000, timeout=120, browser=None):
    """Write html_text to a temp file and shoot it at exactly size=(w, h). Returns png_path.
    No --user-data-dir: headless already runs on a throwaway profile, and a fresh explicit profile makes the
    macOS Chrome app hang on first-run/keychain setup."""
    w, h = size
    browser = browser or find_browser()
    with tempfile.TemporaryDirectory(prefix="otto-render-", dir=_tmp_root()) as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html_text, encoding="utf-8")
        cmd = [browser, "--headless", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
               "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--disable-dev-shm-usage",
               "--force-device-scale-factor=1", "--font-render-hinting=none", "--allow-file-access-from-files",
               "--run-all-compositor-stages-before-draw", "--default-background-color=00000000",
               "--use-mock-keychain", "--password-store=basic", f"--window-size={w},{h}",
               f"--virtual-time-budget={int(budget)}", f"--screenshot={png_path}", page.as_uri()]
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RenderError(f"headless Chrome timed out after {timeout}s")
        if not Path(png_path).exists() or Path(png_path).stat().st_size < 200:
            raise RenderError("headless Chrome wrote no screenshot: " + (r.stderr or r.stdout)[-300:])
    return png_path


def _ffmpeg():
    return shutil.which("ffmpeg")


def _finish(png, out_path, size):
    """Screenshot PNG → out_path (JPEG q2 via ffmpeg, or PNG), at exactly size."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    got = _png_size(png)
    exact = got == tuple(size)
    if out.suffix.lower() == ".png" and exact:
        shutil.copyfile(png, out)
        return str(out)
    ff = _ffmpeg()
    if not ff:
        raise RenderError("ffmpeg is needed to write JPEG (or pass a .png out path)")
    vf = [] if exact else ["-vf", f"crop={size[0]}:{min(size[1], (got or size)[1])}:0:0,scale={size[0]}:{size[1]}"]
    opts = ["-q:v", "2", "-pix_fmt", "yuvj420p"] if out.suffix.lower() in (".jpg", ".jpeg") else []
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(png)] + vf + ["-frames:v", "1"] + opts + [str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RenderError("ffmpeg: " + r.stderr[-300:])
    return str(out)


# ---------------------------------------------------------------- mini templates

_TAG = re.compile(r"{{(.*?)}}", re.S)
_PARTIAL = re.compile(r"{{>\s*([a-z0-9_\-]+)\s*}}")


def _inline_partials(src, depth=0):
    """{{> name}} → contents of templates/ads/_name.html (nested up to 4 deep)."""
    if depth > 4 or "{{>" not in src:
        return src
    return _PARTIAL.sub(lambda m: _inline_partials(_partial(f"_{m.group(1)}.html"), depth + 1), src)


def _parse(src):
    src = _inline_partials(src)
    root = {"kind": "root", "body": []}
    stack = [(root, root["body"])]
    pos = 0
    for m in _TAG.finditer(src):
        stack[-1][1].append(src[pos:m.start()])
        pos = m.end()
        tag = m.group(1).strip()
        if not tag or tag.startswith("!"):
            continue
        if tag.startswith("#"):
            kind, _, arg = tag[1:].partition(" ")
            node = {"kind": kind.strip(), "arg": arg.strip(), "body": [], "else": []}
            stack[-1][1].append(node)
            stack.append((node, node["body"]))
        elif tag == "else":
            node = stack[-1][0]
            if node["kind"] == "root":
                raise RenderError("{{else}} outside a section")
            stack[-1] = (node, node["else"])
        elif tag.startswith("/"):
            kind = tag[1:].strip()
            if len(stack) < 2 or stack[-1][0]["kind"] != kind:
                raise RenderError(f"unbalanced {{{{/{kind}}}}}")
            stack.pop()
        elif tag.startswith("&"):
            stack[-1][1].append(("raw", tag[1:].strip()))
        else:
            # inside an open tag (an attribute value) → plain escaping, never <bdi>/<em> markup
            in_tag = src.rfind("<", 0, m.start()) > src.rfind(">", 0, m.start())
            stack[-1][1].append(("attr" if in_tag else "var", tag))
    stack[-1][1].append(src[pos:])
    if len(stack) != 1:
        raise RenderError(f"unclosed {{{{#{stack[-1][0]['kind']}}}}}")
    return root


def _lookup(ctx, key):
    if key in (".", "this"):
        return ctx[-1].get(".", "")
    for scope in reversed(ctx):
        cur, ok = scope, True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def _truthy(v):
    return bool(v) and v not in ("0", "false", "False", "no")


EM = re.compile(r"\*(?=\S)([^*\n]+?)(?<=\S)\*")
# numbers with attached signs ("10,000+", "+972", "€1.50", "24/7", "19:00") are bidi-isolated so an RTL
# paragraph never moves the sign to the wrong side ("+10,000")
NUMTOK = re.compile(r"(?<![\w&#])([+\-−]?[€$£₪]?\d(?:[\d,.:/]*\d)?(?:[+%]|\s?[€₪£$])?)(?![\w;])")


def fmt_text(v):
    """Escape a value for HTML text; *word* → <em>, newline → <br>, numbers bidi-isolated."""
    if v is None or v is False:
        return ""
    if isinstance(v, bool):
        return "1" if v else ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v)
    s = html.escape(str(v), quote=True)
    if re.match(r"^(file|https?|data):", s):
        return s
    s = NUMTOK.sub(r'<bdi class="n">\1</bdi>', s)
    s = EM.sub(r"<em>\1</em>", s)
    s = re.sub(r"\n\s*\n", '<span class="pb"></span>', s)
    return s.replace("\n", "<br>")


def _emit(nodes, ctx, out):
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, tuple):
            kind, key = n
            v = _lookup(ctx, key)
            if v is None or v is False:
                out.append("")
            elif kind == "raw":
                out.append(str(v))
            elif kind == "attr":
                out.append(html.escape(str(v), quote=True))
            else:
                out.append(fmt_text(v))
        elif n["kind"] == "each":
            items = _lookup(ctx, n["arg"]) or []
            if not isinstance(items, (list, tuple)) or not items:
                _emit(n["else"], ctx, out)
                continue
            total = len(items)
            for i, it in enumerate(items):
                scope = dict(it) if isinstance(it, dict) else {}
                scope.update({".": it if not isinstance(it, dict) else "", "@index": i, "@n": i + 1,
                              "@nn": f"{i + 1:02d}", "@first": i == 0, "@last": i == total - 1, "@total": total})
                _emit(n["body"], ctx + [scope], out)
        elif n["kind"] in ("if", "unless"):
            t = _truthy(_lookup(ctx, n["arg"]))
            if n["kind"] == "unless":
                t = not t
            _emit(n["body"] if t else n["else"], ctx, out)
        elif n["kind"] == "with":
            v = _lookup(ctx, n["arg"])
            _emit(n["body"] if isinstance(v, dict) else n["else"], ctx + ([v] if isinstance(v, dict) else []), out)
        else:
            raise RenderError(f"unknown section {{{{#{n['kind']}}}}}")


def fill(src, data):
    """Render a template string with data (dict). Values are escaped unless the tag is {{&key}}."""
    out = []
    _emit(_parse(src)["body"], [data], out)
    return "".join(out)


# ---------------------------------------------------------------- copy hygiene

INTERNAL = re.compile(r"\bCPL\b|\bCPA\b|\bCPM\b|\bCTR\b|\bROAS\b|\bbudget\b|\bKPI\b|\bper lead\b|\bleads?\b|לידים|"
                      r"תקציב|עלות לליד|\bad ?set\b|\bhypothes|\bplaceholder\b|\bTODO\b|\bTBD\b|lorem ipsum", re.I)
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF️‍⃣]")
ARROWS = re.compile(r"\s*(?:->|=>|<-|[←-⇿⟰-⟿⤀-⥿⬅-⬇➜-➿])\s*")
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}|\{[a-z_][a-z0-9_.]*\}|\[(?:TBD|TODO|placeholder|insert[^\]]*|x+)\]|\(\?\)", re.I)
SKIP_CLEAN = ("photo", "image", "logo", "href", "url", "layout", "theme", "date", "_pos")
ASSET_KEY = re.compile(r"(^|_)(photo|image|img|logo|portrait)(_(?!pos$)[a-z0-9]+)?$", re.I)
POS_OK = re.compile(r"[\d.%\sa-z-]{1,40}")


def clean_copy(s):
    """Markdown, arrows, placeholders and emoji out; whitespace tidy. Keeps \\n and *emphasis*."""
    s = str(s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = PLACEHOLDER.sub("", s)
    s = EMOJI.sub("", s)
    s = ARROWS.sub(" ", s)
    s = re.sub(r"^[#>\-•\s]+", "", s)
    s = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def sanitize(data, warn=None, _path=""):
    """Deep-clean a data dict for rendering. Fields carrying internal data are dropped (warn(msg) is called)."""
    warn = warn or (lambda m: print("otto_render:", m, file=sys.stderr))
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if str(k).startswith("_"):
                out[k] = v
                continue
            if isinstance(v, str) and any(t in str(k).lower() for t in SKIP_CLEAN):
                out[k] = v
                continue
            cv = sanitize(v, warn, f"{_path}{k}.")
            if cv is not None:
                out[k] = cv
        return out
    if isinstance(data, (list, tuple)):
        return [x for x in (sanitize(v, warn, _path) for v in data) if x not in (None, "")]
    if isinstance(data, str):
        if INTERNAL.search(data):
            warn(f"dropped {_path.rstrip('.') or 'value'}: internal data ({INTERNAL.search(data).group(0)})")
            return None
        return clean_copy(data)
    return data


# ---------------------------------------------------------------- colour + brand tokens

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _lum(h):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hsl(h):
    r, g, b = (c / 255 for c in _rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    s = 0 if mx == mn else (mx - mn) / (1 - abs(2 * l - 1))
    return s, l


def _hue(h):
    r, g, b = (c / 255 for c in _rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    hh = ((g - b) / d) % 6 if mx == r else (b - r) / d + 2 if mx == g else (r - g) / d + 4
    return hh * 60


def _hue_gap(a, b):
    d = abs(_hue(a) - _hue(b)) % 360
    return min(d, 360 - d)


def mix(a, b, t):
    """a blended toward b by t (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def _rgb_str(h):
    return ",".join(str(c) for c in _rgb(h))


LABELS = {
    "en": {"myth": "Myth", "fact": "Fact", "before": "Before", "after": "After", "swipe": "Swipe", "cta": "Learn more",
           "usual": "The usual way", "vs": "vs", "note": "A note from the team", "save": "Save your seat", "of": "/",
           "verified": "Verified review", "new": "New"},
    "he": {"myth": "מיתוס", "fact": "עובדה", "before": "לפני", "after": "אחרי", "swipe": "החליקו", "cta": "לפרטים בלינק",
           "usual": "הדרך הרגילה", "vs": "מול", "note": "מכתב מהצוות", "save": "לשמירת מקום", "of": "/",
           "verified": "ביקורת מאומתת", "new": "חדש"},
    "de": {"myth": "Mythos", "fact": "Fakt", "before": "Vorher", "after": "Nachher", "swipe": "Wischen", "cta": "Mehr erfahren",
           "usual": "Der übliche Weg", "vs": "vs", "note": "Ein Wort vom Team", "save": "Platz sichern", "of": "/",
           "verified": "Verifizierte Bewertung", "new": "Neu"},
}
RTL_LANGS = {"he", "ar", "fa", "ur"}
FONT_PAIRS = {
    "he": {"display": "Heebo", "text": "Assistant", "serif": "Frank Ruhl Libre", "w_display": 800, "w_serif": 500},
    "ar": {"display": "Rubik", "text": "Rubik", "serif": "Rubik", "w_display": 700, "w_serif": 500},
    "default": {"display": "Inter Tight", "text": "Inter", "serif": "Instrument Serif", "w_display": 700, "w_serif": 400},
}
FONT_SPECS = {
    "Inter Tight": "Inter+Tight:ital,wght@0,400;0,500;0,600;0,700;0,800;1,500",
    "Inter": "Inter:wght@400;500;600;700",
    "Instrument Serif": "Instrument+Serif:ital@0;1",
    "Heebo": "Heebo:wght@300;400;500;600;700;800;900",
    "Assistant": "Assistant:wght@400;500;600;700;800",
    "Frank Ruhl Libre": "Frank+Ruhl+Libre:wght@400;500;700;900",
    "Rubik": "Rubik:wght@400;500;600;700;800",
    "Fraunces": "Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..600",
    "DM Serif Display": "DM+Serif+Display:ital@0;1",
    "Manrope": "Manrope:wght@400;500;600;700;800",
}
# A brand's own web font, when the scan finds one of these Google families (sans only — the serif pairing stays
# ours): spec for css2 + the heaviest display weight it has, capped at 800.
BRAND_SANS = {
    "DM Sans": ("DM+Sans:wght@400..900", 800), "Work Sans": ("Work+Sans:wght@400..900", 800),
    "Poppins": ("Poppins:wght@400;500;600;700;800;900", 800), "Montserrat": ("Montserrat:wght@400..900", 800),
    "Plus Jakarta Sans": ("Plus+Jakarta+Sans:wght@400..800", 800), "Outfit": ("Outfit:wght@400..900", 800),
    "Figtree": ("Figtree:wght@400..900", 800), "Space Grotesk": ("Space+Grotesk:wght@400..700", 700),
    "Nunito": ("Nunito:wght@400..900", 800), "Raleway": ("Raleway:wght@400..900", 800),
    "Open Sans": ("Open+Sans:wght@400..800", 800), "Lato": ("Lato:wght@400;700;900", 900),
    "Roboto": ("Roboto:wght@400..900", 800), "Sora": ("Sora:wght@400..800", 800),
    "Urbanist": ("Urbanist:wght@400..900", 800), "Lexend": ("Lexend:wght@400..900", 800),
    "Karla": ("Karla:wght@400..800", 800), "Mulish": ("Mulish:wght@400..900", 800),
    "Barlow": ("Barlow:wght@400;500;600;700;800;900", 800), "Archivo": ("Archivo:wght@400..900", 800),
    "Onest": ("Onest:wght@400..900", 800), "Instrument Sans": ("Instrument+Sans:wght@400..700", 700),
    "Syne": ("Syne:wght@400..800", 800), "Unbounded": ("Unbounded:wght@400..900", 800),
    "Bricolage Grotesque": ("Bricolage+Grotesque:wght@400..800", 800),
}
FONT_SPECS.update({k: v[0] for k, v in BRAND_SANS.items()})
_SANS_KEY = {k.replace(" ", "").lower(): k for k in BRAND_SANS}


def brand_font(scan):
    """The site's own Google sans family ('DMSans' → 'DM Sans'), or None."""
    for f in ((scan or {}).get("visual") or {}).get("fonts") or []:
        k = _SANS_KEY.get(re.sub(r"[\s_-]", "", str(f)).lower())
        if k:
            return k
    return None


FALLBACK = {
    "sans": '-apple-system, "Helvetica Neue", "Segoe UI", Roboto, "Noto Sans", Arial, sans-serif',
    "serif": '"Iowan Old Style", Georgia, "Noto Serif", "Times New Roman", serif',
    "he_sans": '"Arial Hebrew", "Noto Sans Hebrew", "DejaVu Sans", Arial, sans-serif',
    "he_serif": '"Noto Serif Hebrew", "Times New Roman", "David", serif',
}


def _read(p):
    try:
        return Path(p).read_text()
    except Exception:
        return ""


def _json(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return {}


def _visual_section(md):
    m = re.search(r"VISUAL IDENTITY.*?(?=\n#+ |\n---|\Z)", md, re.S)
    return m.group(0) if m else ""


CTA_LABEL = re.compile(r"\bCTA\b|call to action|button|כפתור", re.I)
UI_ONLY = re.compile(r"UI only|not (for )?creatives|whatsapp|לא לקריאייטיב", re.I)
BG_LABEL = re.compile(r"\bbackground\b|\bbg\b|רקע", re.I)


def palette_labels(vis):
    """VISUAL IDENTITY text → [(hex, label)], label = the words around the hex within its '·' / '|' segment."""
    out = []
    for seg in re.split(r"\s[·|•]\s|\n", vis):
        hexes = HEX.findall(seg)
        for h in hexes:
            out.append((h.upper(), re.sub(r"\s+", " ", HEX.sub("", seg)).strip(" -:*()/")))
    return out


def logo_ratio(path):
    """Width / height of a logo file (SVG viewBox or width/height, PNG header); 3.0 when unknown."""
    try:
        p = Path(path)
        if p.suffix.lower() == ".svg":
            head = p.read_text(errors="ignore")[:4000]
            m = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', head)
            m = m or re.search(r'<svg[^>]*?\bwidth="([\d.]+)(?:px)?"[^>]*?\bheight="([\d.]+)', head)
            if m and float(m.group(2)):
                return round(float(m.group(1)) / float(m.group(2)), 3)
        elif p.suffix.lower() == ".png":
            b = p.read_bytes()[:32]
            w, h = int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
            if h:
                return round(w / h, 3)
    except OSError:
        pass
    return 3.0


def brand_tokens(bid=None, **over):
    """Design tokens for a brand (dict). Works for unknown brands (neutral defaults).
    Palette: the profile's VISUAL IDENTITY section first (a colour labelled CTA becomes the accent; colours labelled
    'UI only' / WhatsApp are skipped; a labelled background becomes the deep tone), then scan.json."""
    d = BRANDS / bid if bid else None
    prof = _read(d / "brand-profile.md") if d else ""
    scan = _json(d / "scan.json") if d else {}
    strat = _json(d / "strategy.json") if d else {}
    custom = _json(d / "render.json") if d else {}
    vis = _visual_section(prof)
    labelled = [(h, lab) for h, lab in palette_labels(vis) if not UI_ONLY.search(lab)]
    cols = list(dict.fromkeys(h for h, _ in labelled))
    for x in ((scan.get("visual") or {}).get("palette") or []):
        if x.get("hex") and x["hex"].upper() not in cols:
            cols.append(x["hex"].upper())
    neutrals = [x["hex"].upper() for x in ((scan.get("visual") or {}).get("neutrals") or []) if x.get("hex")]

    def sat(h):
        return _hsl(h)[0]

    def light(h):
        return _hsl(h)[1]

    def usable(c):
        return sat(c) > 0.3 and 0.22 < light(c) < 0.8

    cta = next((h for h, lab in labelled if CTA_LABEL.search(lab) and usable(h)), None)
    primary = next((c for c in cols if usable(c)), None) or "#2B2B2B"
    darks = [c for c in cols + neutrals if light(c) < 0.2]
    ink = darks[0] if darks else "#161616"
    if ink in ("#000000",) or light(ink) < 0.04 and sat(ink) < 0.2:
        ink = "#151515"
    dark_sat = [c for c in cols if light(c) < 0.22 and sat(c) > 0.2]
    bg = [h for h, lab in labelled if BG_LABEL.search(lab) and h in dark_sat]
    # a colour with some body (navy, forest) beats near-black: first labelled background, else first dark tone
    pool = bg or dark_sat
    deep = next((c for c in pool if light(c) >= 0.08), None) or (pool[0] if pool else ink)
    if light(ink) < 0.1 and sat(ink) > 0.3 and deep != ink:     # a tinted near-black ink → use the deep tone
        ink = deep
    lights = [c for c in cols + neutrals if light(c) > 0.93]
    warm_light = next((c for c in lights if c not in ("#FFFFFF",) and sat(c) > 0.2 and _hsl(c)[1] < 0.985), None)
    accent = cta or primary
    surface = warm_light or mix("#F6F3ED", accent, 0.025)        # warm paper with a breath of the brand
    white = "#FFFFFF"
    accent_ink = ink if contrast(accent, ink) >= contrast(accent, white) else white
    # a two-colour identity (green + yellow): the brand's second hue, when it has one
    second = next((c for c in cols if c != accent and usable(c) and _hue_gap(c, accent) >= 60), None)
    accent_on_dark = accent
    if contrast(accent, deep) < 4.5 and second and contrast(second, deep) >= 4.5:
        accent_on_dark = second                                 # yellow on forest, not a washed-out green
    t = 0.0
    while contrast(accent_on_dark, deep) < 4.5 and t < 0.9:
        t += 0.05
        accent_on_dark = mix(accent, white, t)
    # emphasis on paper: the accent itself when it reads as large text (3:1), a darker shade of it when that
    # stays recognisable, else a highlighter band behind ink text (light accents such as yellow)
    em_light, accent_text = "color", accent
    if contrast(accent, surface) < 3:
        dark = accent
        t = 0.0
        while contrast(dark, surface) < 3 and t < 0.45:
            t += 0.05
            dark = mix(accent, ink, t)
        if contrast(dark, surface) >= 3 and t <= 0.3:
            accent_text = dark
        else:
            em_light, accent_text = "marker", ink

    lang = (custom.get("lang") or strat.get("language") or ((scan.get("languages") or [None])[0]) or "en").lower()[:2]
    pair = dict(FONT_PAIRS.get(lang) or FONT_PAIRS["default"])
    own = brand_font(scan) if lang not in RTL_LANGS else None      # Latin families lack Hebrew/Arabic glyphs
    em_style, marker = "serif", accent
    if own:
        pair.update(display=own, text=own, w_display=BRAND_SANS[own][1])
        em_style = "brand"            # the brand's own face carries emphasis too — our serif italic is not their voice
        # colour alone must then carry the emphasis: an accent too close to the ink (green on forest) becomes a
        # highlighter band in the brand's second hue
        if em_light == "color" and second and _hue_gap(accent_text, ink) < 30 and contrast(second, surface) < 3:
            em_light, marker = "marker", second
    name = (scan.get("identity") or {}).get("site_name") or ""
    m = re.search(r"\*\*Brand:\*\*\s*(.+)", prof)
    if m:
        name = re.split(r"\s[—–-]\s", m.group(1).strip())[0].strip() or name
    name = name or (bid or "Brand").replace("-", " ").title()
    url = scan.get("final_url") or scan.get("url") or ""
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0].split("?")[0])
    logo = ""
    for ext in ("svg", "png", "webp"):
        for nm in (f"logo.{ext}", f"logo-white.{ext}"):
            if d and (d / nm).exists():
                logo = logo or str(d / nm)
    tok = {"id": bid or "", "name": name, "lang": lang, "dir": "rtl" if lang in RTL_LANGS else "ltr",
           "primary": primary, "accent": accent, "accent_ink": accent_ink, "accent_on_dark": accent_on_dark,
           "accent_text": accent_text, "em_light": em_light, "ink": ink, "deep": deep, "surface": surface,
           "surface2": mix(surface, ink, 0.06), "on_deep": white, "host": host, "logo": logo,
           "logo_ratio": 0, "logo_mode": "mono", "em_style": em_style, "marker": marker,
           "font_display": pair["display"], "font_text": pair["text"], "font_serif": pair["serif"],
           "w_display": pair["w_display"], "w_serif": pair["w_serif"], "currency": strat.get("currency") or ""}
    tok.update({k: v for k, v in custom.items() if k in tok or k.startswith("font")})
    tok.update({k: v for k, v in over.items() if v is not None})
    if tok["logo"] and not tok["logo_ratio"]:
        tok["logo_ratio"] = logo_ratio(tok["logo"])
    return tok


def _stack(font, kind, rtl):
    fb = FALLBACK[("he_" if rtl else "") + kind]
    return f'"{font}", {fb}' if font else fb


def tokens_css(tok):
    rtl = tok.get("dir") == "rtl"
    v = {
        "--primary": tok["primary"], "--accent": tok["accent"], "--accent-ink": tok["accent_ink"],
        "--accent-on-dark": tok["accent_on_dark"], "--accent-text": tok["accent_text"], "--ink": tok["ink"],
        "--marker": tok.get("marker") or tok["accent"],
        "--ink-rgb": _rgb_str(tok["ink"]), "--deep": tok["deep"], "--deep-rgb": _rgb_str(tok["deep"]),
        "--surface": tok["surface"], "--surface2": tok["surface2"], "--on-deep": tok["on_deep"],
        "--accent-rgb": _rgb_str(tok["accent"]),
        "--f-display": _stack(tok["font_display"], "sans", rtl), "--f-text": _stack(tok["font_text"], "sans", rtl),
        "--f-serif": _stack(tok["font_serif"], "serif", rtl), "--w-display": str(tok.get("w_display", 700)),
        "--w-serif": str(tok.get("w_serif", 400)),
    }
    return ":root{" + ";".join(f"{k}:{val}" for k, val in v.items()) + "}"


# ---------------------------------------------------------------- fonts

def _google_url(families):
    fams = "&".join("family=" + FONT_SPECS.get(f, f.replace(" ", "+")) for f in families)
    return f"https://fonts.googleapis.com/css2?{fams}&display=block"


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def font_css(families, subsets=("latin", "latin-ext")):
    """@font-face CSS for Google font families, woff2 inlined as data URIs and cached on disk.
    Offline and not cached → a <link> tag (Chrome may still fetch it) — returned as ("link", html)."""
    families = [f for f in dict.fromkeys(families) if f]
    mode = os.environ.get("OTTO_RENDER_FONTS", "")
    if not families or mode == "system":
        return ""
    key = hashlib.sha1((json.dumps(families) + json.dumps(sorted(subsets))).encode()).hexdigest()[:16]
    cached = FONT_CACHE / f"{key}.css"
    if cached.exists() and cached.stat().st_size > 100:
        return "<style>" + cached.read_text() + "</style>"
    url = _google_url(families)
    if mode == "link":
        return f'<link rel="stylesheet" href="{html.escape(url)}">'
    try:
        css = _fetch(url).decode("utf-8")
        blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*{[^}]*})", css)
        merged, order = {}, []
        for subset, block in blocks:
            if subset not in subsets:
                continue
            fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
            style = (re.search(r"font-style:\s*(\w+)", block) or [None, "normal"])[1]
            wt = re.search(r"font-weight:\s*([\d ]+);", block).group(1).split()
            src = re.search(r"url\((https://[^)]+)\)", block).group(1)
            rng = (re.search(r"unicode-range:\s*([^;]+);", block) or [None, ""])[1]
            k = (fam, style, subset, src)
            if k not in merged:
                merged[k] = {"w": [], "range": rng}
                order.append(k)
            merged[k]["w"] += [int(x) for x in wt]
        FONT_CACHE.mkdir(parents=True, exist_ok=True)
        out = []
        for k in order:
            fam, style, subset, src = k
            fn = FONT_CACHE / (hashlib.sha1(src.encode()).hexdigest()[:20] + ".woff2")
            if not fn.exists():
                fn.write_bytes(_fetch(src))
            b64 = base64.b64encode(fn.read_bytes()).decode()
            ws = merged[k]["w"]
            wr = f"{min(ws)} {max(ws)}" if min(ws) != max(ws) else str(ws[0])
            out.append(f"@font-face{{font-family:'{fam}';font-style:{style};font-weight:{wr};font-display:block;"
                       f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
                       + (f"unicode-range:{merged[k]['range']};" if merged[k]["range"] else "") + "}")
        text = "\n".join(out)
        if text:
            cached.write_text(text)
            return "<style>" + text + "</style>"
    except Exception as e:
        print(f"otto_render: fonts offline ({str(e)[:80]}), using a <link> + system fallbacks", file=sys.stderr)
    return f'<link rel="stylesheet" href="{html.escape(url)}">'


# ---------------------------------------------------------------- assets + page assembly

def resolve_asset(v):
    """Photo/logo reference → URL Chrome can load ('' when missing)."""
    if not v:
        return ""
    v = str(v).strip()
    if re.match(r"^(https?|data|file):", v):
        return v
    cands = [Path(v).expanduser()]
    if v.startswith("assets/"):
        try:
            import otto_paths
            cands.insert(0, otto_paths.local_path(v))
        except Exception:
            pass
    cands += [HERE / v, ROOT / v, Path.cwd() / v]
    for c in cands:
        try:
            if c.is_file():
                return c.resolve().as_uri()
        except OSError:
            continue
    print(f"otto_render: image not found: {v}", file=sys.stderr)
    return ""


MONTHS = {
    "en": "January February March April May June July August September October November December".split(),
    "he": "ינואר פברואר מרץ אפריל מאי יוני יולי אוגוסט ספטמבר אוקטובר נובמבר דצמבר".split(),
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split(),
}
WEEKDAYS = {
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
    "he": ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"],
    "de": "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag".split(),
}


def date_parts(v, lang="en"):
    """'2026-10-09' → {date_day: '9', date_month: 'October', date_mon: 'Oct', date_weekday: 'Thursday', date_year}.
    Anything else is passed through as date_label."""
    import datetime
    m = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", str(v))
    if not m:
        return {"date_label": str(v)}
    try:
        dt = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return {"date_label": str(v)}
    months = MONTHS.get(lang) or MONTHS["en"]
    wd = WEEKDAYS.get(lang) or WEEKDAYS["en"]
    mon = months[dt.month - 1]
    return {"date_day": str(dt.day), "date_month": mon, "date_mon": mon if lang == "he" else mon[:3],
            "date_weekday": wd[dt.weekday()], "date_year": str(dt.year),
            "date_label": f"{dt.day} {mon}" if lang in ("he", "de") else f"{mon} {dt.day}"}


_LUMA = {}


def photo_luma(uri, region=(0.0, 0.45, 1.0, 1.0)):
    """Mean luma 0..1 of a region (x0, y0, x1, y1 as fractions) of a local photo, via ffmpeg; None when unknown.
    Used to keep text off bright photos: a light image under a dark scrim turns muddy."""
    if not uri or not uri.startswith("file:"):
        return None
    key = (uri, region)
    if key in _LUMA:
        return _LUMA[key]
    ff = _ffmpeg()
    val = None
    if ff:
        from urllib.parse import unquote, urlparse
        path = unquote(urlparse(uri).path)
        x0, y0, x1, y1 = region
        vf = (f"crop=iw*{x1 - x0:.3f}:ih*{y1 - y0:.3f}:iw*{x0:.3f}:ih*{y0:.3f},scale=24:24,format=gray")
        try:
            r = subprocess.run([ff, "-v", "error", "-i", path, "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-"],
                               capture_output=True, timeout=30)
            if r.returncode == 0 and r.stdout:
                val = sum(r.stdout) / (255.0 * len(r.stdout))
        except Exception:
            val = None
    _LUMA[key] = val
    return val


_CUT = {}


def is_cutout(uri):
    """A transparent packshot (PNG/WebP whose corners are clear). It is shown whole on a ground, never cropped
    full-bleed like a photo with text laid over the product."""
    if not uri or not uri.startswith("file:") or not re.search(r"\.(png|webp)$", uri, re.I):
        return False
    if uri in _CUT:
        return _CUT[uri]
    ff = _ffmpeg()
    val = False
    if ff:
        from urllib.parse import unquote, urlparse
        path = unquote(urlparse(uri).path)
        try:
            r = subprocess.run([ff, "-v", "error", "-i", path, "-vf", "scale=16:16,format=rgba,alphaextract,format=gray",
                                "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=30)
            a = r.stdout
            if r.returncode == 0 and len(a) == 256:
                corners = [a[i] for i in (0, 1, 16, 14, 15, 31, 224, 240, 241, 239, 254, 255)]
                val = max(corners) < 16
        except Exception:
            val = False
    _CUT[uri] = val
    return val


def fmt_of(size):
    w, h = size
    r = h / float(w)
    return "story" if r >= 1.6 else "square" if r <= 1.1 else "feed"


def template_path(name):
    name = re.sub(r"[^a-z0-9_\-]", "", str(name).lower())
    p = TEMPLATES / f"{name}.html"
    if not p.exists():
        raise RenderError(f"unknown template {name!r} (have: {', '.join(list_templates())})")
    return p


def list_templates():
    return sorted(p.stem for p in TEMPLATES.glob("*.html") if not p.stem.startswith("_"))


_BASE = {}


def _partial(name):
    if name not in _BASE:
        _BASE[name] = (TEMPLATES / name).read_text(encoding="utf-8") if (TEMPLATES / name).exists() else ""
    return _BASE[name]


def _logo_mask(tok):
    """A mono logo is drawn as a CSS mask in the ground's own text colour, so one file reads on photo, paper and
    deep grounds alike. Inlined as a data: URI (Chrome fetches file:// masks in CORS mode and drops them).
    render.json {"logo_mode": "color"} keeps the file's own colours instead."""
    if tok.get("logo_mode") != "mono" or not tok.get("logo"):
        return ""
    p = Path(tok["logo"])
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower())
    try:
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode() if mime else ""
    except OSError:
        return ""


def build_context(data, size, brand, warn=None):
    tok = dict(brand or brand_tokens())
    lang = tok.get("lang", "en")
    d = sanitize(data or {}, warn)
    for k, v in list(d.items()):
        if isinstance(v, str) and ASSET_KEY.search(k):
            d[k] = resolve_asset(v)
    for k in [k for k in d if ASSET_KEY.search(k)] + ["photo"]:
        pos = str(d.get(k + "_pos") or "50% 50%")
        d[k + "_pos"] = pos if POS_OK.fullmatch(pos) else "50% 50%"
    lay = re.sub(r"[^a-z0-9_]", "", str(d.get("layout") or "auto").lower())
    cut = is_cutout(d.get("photo")) or is_cutout(d.get("photo_after"))
    if cut and lay == "auto":
        lay = "split"                                  # a packshot sits on paper above the copy, never under it
    if lay == "auto":                                  # text over a photo only when the photo is dark enough there
        lum = photo_luma(d.get("photo"), (0.0, 0.3, 1.0, 0.85) if fmt_of(size) == "story" else (0.0, 0.5, 1.0, 1.0))
        lay = "split" if lum is not None and lum > 0.45 else "overlay"
    d["layout"] = lay
    d[lay] = True                                      # {{#if split}} … in templates
    n, total = d.get("n"), d.get("total")
    if isinstance(n, int) and isinstance(total, int) and total > 0:
        d.setdefault("counter", f"{n:02d} / {total:02d}")
        d["_segments"] = [{"on": i < n} for i in range(total)]
    labels = dict(LABELS["en"])
    labels.update(LABELS.get(lang, {}))
    w, h = size
    fmt = fmt_of(size)
    ctx = {"brand": tok, "L": labels, "W": w, "H": h, "fmt": fmt, "lang": lang, "dir": tok.get("dir", "ltr"),
           "logo_src": resolve_asset(tok.get("logo")), "logo_mask": _logo_mask(tok), "cta": labels["cta"],
           "html_class": f"f-{fmt} em-{tok.get('em_light', 'color')} ems-{tok.get('em_style', 'serif')}"
                         + (" has-cutout" if cut else "")}
    ctx.update(d)
    if d.get("date"):
        ctx.update(date_parts(d["date"], lang))
    table_cells(ctx)
    if d.get("rating"):
        try:
            r = max(0, min(5, int(round(float(d["rating"])))))
            ctx["_stars"] = [{"on": i < r} for i in range(5)]
        except (TypeError, ValueError):
            pass
    rtl = tok.get("dir") == "rtl"
    subsets = ("latin", "latin-ext", "hebrew") if rtl or lang == "he" else ("latin", "latin-ext")
    fonts = font_css([tok.get("font_display"), tok.get("font_text"), tok.get("font_serif")], subsets)
    ctx["_head"] = (fonts + "<style>" + tokens_css(tok) + f":root{{--w:{w}px;--h:{h}px}}" + _partial("_base.css") + "</style>")
    ctx["_foot"] = "<script>" + _partial("_fit.js") + "</script>"
    return ctx


YES = {"yes", "y", "true", "1", "✓", "✔", "כן", "ja", "oui", "sí", "si"}
NO = {"no", "n", "false", "0", "✗", "✕", "-", "–", "—", "לא", "nein", "non"}


def table_cells(ctx):
    """comparison data: columns → dicts + _ncols; each row's values → _cells [{text, yes, no, hi}]."""
    cols = ctx.get("columns")
    if not isinstance(cols, list) or not cols:
        return
    cols = [c if isinstance(c, dict) else {"name": c} for c in cols]
    ctx["columns"], ctx["_ncols"] = cols, len(cols)
    hi = [_truthy(c.get("highlight")) for c in cols]
    for r in ctx.get("rows") or []:
        if isinstance(r, dict):
            vals = list(r.get("values") or [])[:len(cols)]
            vals += [""] * (len(cols) - len(vals))
            r["_cells"] = [{"text": v, "yes": str(v).strip().lower() in YES, "no": str(v).strip().lower() in NO,
                            "hi": hi[i]} for i, v in enumerate(vals)]


def render_html(template, data, size=(1080, 1350), brand=None, warn=None):
    """Template + data → complete HTML page (no browser needed)."""
    ctx = build_context(data, size, brand, warn)
    return fill(template_path(template).read_text(encoding="utf-8"), ctx)


def render(template, data, out_path, size=(1080, 1350), brand=None, budget=6000):
    """Render one ad to out_path (.jpg → JPEG q2 via ffmpeg, .png → PNG). brand = brand_tokens(...) dict or a
    brand id. Returns the out path. Raises BrowserNotFound / RenderError (callers fall back to the overlay)."""
    if isinstance(brand, str):
        brand = brand_tokens(brand)
    size = tuple(int(x) for x in size)
    page = render_html(template, data, size, brand)
    browser = find_browser()
    with tempfile.TemporaryDirectory(prefix="otto-shot-", dir=_tmp_root()) as tmp:
        png = str(Path(tmp) / "shot.png")
        screenshot(page, png, size, budget=budget, browser=browser)
        return _finish(png, out_path, size)


_PROBE = """<script>(function(){function done(){var d=document.documentElement;if(!d.classList.contains('fitted')){
return setTimeout(done,50);}var o={fitted:true,overflow:d.classList.contains('overflow'),sizes:{}};
document.querySelectorAll('[data-fit],[data-fitw]').forEach(function(e,i){o.sizes[(e.className||e.tagName)+'#'+i]=
parseFloat(getComputedStyle(e).fontSize);});var p=document.createElement('pre');p.id='otto-report';
p.textContent=JSON.stringify(o);document.body.appendChild(p);}done();})();</script>"""


def fit_report(template, data, size=(1080, 1350), brand=None, budget=6000, browser=None):
    """Lay an ad out in headless Chrome without shooting it. Returns {"fitted", "overflow", "sizes"}:
    overflow = the copy still does not fit at the templates' minimum sizes (shorten it)."""
    if isinstance(brand, str):
        brand = brand_tokens(brand)
    size = tuple(int(x) for x in size)
    page = render_html(template, data, size, brand).replace("</body>", _PROBE + "</body>")
    browser = browser or find_browser()
    with tempfile.TemporaryDirectory(prefix="otto-check-", dir=_tmp_root()) as tmp:
        f = Path(tmp) / "page.html"
        f.write_text(page, encoding="utf-8")
        cmd = [browser, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--disable-extensions",
               "--force-device-scale-factor=1", "--allow-file-access-from-files", "--use-mock-keychain",
               f"--window-size={size[0]},{size[1]}", f"--virtual-time-budget={int(budget)}", "--dump-dom", f.as_uri()]
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise RenderError("headless Chrome timed out")
    m = re.search(r'<pre id="otto-report">(.*?)</pre>', r.stdout, re.S)
    if not m:
        return {"fitted": False, "overflow": None, "sizes": {}}
    return json.loads(html.unescape(m.group(1)))


# ---------------------------------------------------------------- sets (posts, campaigns)

def _lang_label(tok, key):
    return (LABELS.get(tok.get("lang")) or LABELS["en"]).get(key) or LABELS["en"][key]


def _sentences(text, lo=15, hi=140):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [s.strip() for s in parts if lo <= len(s.strip()) <= hi and not s.strip().startswith("#")
            and not DSHEA_LINE.match(s.strip())]                  # the FDA disclaimer is never display copy


def _post_image(ref):
    if not ref:
        return ""
    return resolve_asset(ref)


def _campaign_photo(c, i):
    cr = c.get("creatives") or {}
    imgs = cr.get("images") or []
    img = imgs[i] if i < len(imgs) else (imgs[0] if imgs else {})
    for k in ("src", "photo", "source_image"):
        if img.get(k):
            return img[k]
    pid = img.get("from") or ((c.get("creative") or {}).get("post"))
    if pid:
        try:
            import ap
            p = ap.post(ap.load(), pid)
            if p and p.get("image"):
                return p["image"]
        except Exception:
            pass
    return ""


DSHEA_LINE = re.compile(r"^\*?\s*(these statements have not been evaluated|this product is not intended to)", re.I)


def _echoes(sent, hook):
    """A caption sentence that only repeats the hook ('Ogres have layers.' under 'Ogres have layers. This…')."""
    a, b = (re.sub(r"[^\w]+", " ", t or "").strip().lower() for t in (sent, hook))
    return bool(a and b) and (a in b or b in a or a[:28] == b[:28])


def post_card(obj, photo=""):
    """(template, data) for a single-image post: the copy's own template when hook + caption carry what it needs
    (quote, myth_fact, big_number), else editorial. The FDA disclaimer is never a subtitle."""
    hook = (obj.get("hook") or "").strip()
    sents = [x for x in _sentences(obj.get("caption")) if not _echoes(x, hook)]
    kicker = obj.get("kicker") or ""                         # the pillar is a planning label, not audience copy
    tpl = obj.get("template") or ""
    if tpl == "quote" and re.fullmatch(r"[“\"][^“”\"]+[”\"]", hook):
        who = next((m.group(1) for x in sents for m in [re.search(r"\b([A-Z][a-z]+ [A-Z]\.)", x)] if m), "")
        return "quote", {"quote": hook.strip("“”\" "), "name": who, "detail": "Verified review" if who else "",
                         "photo": photo if obj.get("format") in ("story", "reel") else ""}
    if tpl == "myth_fact" and re.match(r"^myth\s*:", hook, re.I):
        fact = next((re.sub(r"^fact\s*:\s*", "", x, flags=re.I) for x in sents if re.match(r"^fact\s*:", x, re.I)), "")
        if fact:
            return "myth_fact", {"myth": re.sub(r"^myth\s*:\s*", "", hook, flags=re.I), "fact": fact}
    if tpl == "big_number":                                  # only a number that leads the hook ("6 g of fiber…")
        m = re.match(r"^(\d[\d.,]*\s?(?:%|g\b|★|k\+?|\+)?)\s+(.{8,})$", hook)
        if m:
            return "big_number", {"number": m.group(1).strip(), "label": m.group(2).strip(), "kicker": kicker}
    return "editorial", {"headline": hook, "sub": sents[0] if sents else "", "kicker": kicker, "photo": photo}


def render_set(obj, brand_id, out_dir, sizes=None, jobs=3):
    """Render every card a post or a campaign needs. Returns [{"file", "template", "role", "size", "text"}].

    post (has "hook"/"format"): an explicit post["render"] = [{"template", "data", "size"?}] wins; a carousel
      → cover + inner slides + CTA card (<id>-<n>.jpg); a story → editorial 1080x1920; else editorial 4:5.
    campaign (has "creatives"): per angle an editorial static (<cid>-<i>-static.jpg) + a 3-card carousel
      (<cid>-<i>-c<j>.jpg: cover / proof / CTA) — the names otto_creative already uses."""
    tok = brand_tokens(brand_id)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = []
    if isinstance(obj.get("render"), (list, dict)):
        specs = obj["render"] if isinstance(obj["render"], list) else [obj["render"]]
        for k, s in enumerate(specs, 1):
            plan.append((s["template"], s.get("data") or {}, tuple(s.get("size") or SIZES["feed"]),
                         out / f"{obj.get('id', 'card')}-{k}.jpg", s.get("role") or "custom"))
    elif "creatives" in obj or "objective" in obj:
        cr = obj.get("creatives") or {}
        titles, bodies = cr.get("titles") or [], cr.get("bodies") or []
        desc = (cr.get("descriptions") or [""])[0]
        for i, title in enumerate(titles, 1):
            photo = _campaign_photo(obj, i - 1)
            body = bodies[i - 1] if i - 1 < len(bodies) else ""
            plan.append(("editorial", {"headline": title, "sub": body, "photo": photo, "kicker": desc},
                         SIZES["feed"], out / f"{obj['id']}-{i}-static.jpg", "static"))
            plan.append(("carousel_cover", {"headline": title, "photo": photo, "n": 1, "total": 3},
                         SIZES["feed"], out / f"{obj['id']}-{i}-c1.jpg", "cover"))
            plan.append(("carousel_inner", {"title": desc or title, "body": body, "n": 2, "total": 3},
                         SIZES["feed"], out / f"{obj['id']}-{i}-c2.jpg", "inner"))
            plan.append(("carousel_cta", {"headline": title, "cta": _lang_label(tok, "cta"), "n": 3, "total": 3},
                         SIZES["feed"], out / f"{obj['id']}-{i}-c3.jpg", "cta"))
    else:
        pid = obj.get("id", "post")
        photo = obj.get("photo") or obj.get("image") or ""
        if photo in ("none", "null"):
            photo = ""
        elif photo and "/" not in photo:
            photo = f"assets/site/{photo}"                   # a bare file name from the copy = a scanned site image
        fmt = obj.get("format") or "feed"
        if fmt == "carousel":
            slides = [s for s in (obj.get("slides") or []) if isinstance(s, (str, dict))]
            closing = obj.get("cta_headline") or ""
            if not slides:
                sents = [s for s in _sentences(obj.get("caption")) if s != obj.get("hook")]
                if not closing and len(sents) > 4:
                    closing = sents[-1]                           # the caption's sign-off closes the carousel
                slides = [obj.get("hook") or (sents[0] if sents else "")] + sents[:4]
            total = len(slides) + 1
            for k, s in enumerate(slides, 1):
                sd = s if isinstance(s, dict) else {"text": s}
                if k == 1:
                    plan.append(("carousel_cover", {"headline": sd.get("title") or sd.get("text"), "kicker": obj.get("kicker") or "",
                                                    "photo": sd.get("photo") or photo, "n": 1, "total": total},
                                 SIZES["feed"], out / f"{pid}-1.jpg", "cover"))
                else:
                    plan.append(("carousel_inner", {"title": sd.get("title") or sd.get("text"), "body": sd.get("body", ""),
                                                    "step": f"{k - 1:02d}", "points": sd.get("points") or [],
                                                    "photo": sd.get("photo", ""), "n": k, "total": total},
                                 SIZES["feed"], out / f"{pid}-{k}.jpg", "inner"))
            plan.append(("carousel_cta", {"headline": closing or obj.get("hook"),
                                          "cta": obj.get("cta_text") or _lang_label(tok, "cta"), "n": total, "total": total},
                         SIZES["feed"], out / f"{pid}-{total}.jpg", "cta"))
        else:
            size = SIZES["story"] if fmt in ("story", "reel") else SIZES["square"] if fmt == "square" else SIZES["feed"]
            tpl, data = post_card(obj, photo)
            plan.append((tpl, data, size, out / f"{pid}-ad.jpg", "static"))
    if sizes:
        plan = [(t, d, s2, p.with_name(p.stem + ("" if s2 == SIZES["feed"] else f"-{fmt_of(s2)}") + p.suffix), r)
                for (t, d, _s, p, r) in plan for s2 in sizes]

    def one(item):
        t, d, s, p, role = item
        render(t, d, p, s, tok)
        return {"file": str(p), "template": t, "role": role, "size": list(s),
                "text": d.get("headline") or d.get("title") or d.get("quote") or ""}

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        return list(ex.map(one, plan))


# ---------------------------------------------------------------- demo + contact sheet

def _demo_specs(bid):
    spec = _json(TEMPLATES / "_demo.json")
    tok = brand_tokens(bid)
    if bid in spec:
        return spec[bid]
    generic = spec.get("_generic_he" if tok["lang"] == "he" else "_generic_en") or []
    return json.loads(json.dumps(generic).replace("{brand}", tok["name"].replace('"', "")))


def compliance_issues(bid, texts):
    try:
        import otto_compliance
        return otto_compliance.check_texts(bid, texts, "ads")
    except Exception as e:
        return [{"rule": "compliance check unavailable", "match": "", "excerpt": str(e)[:80]}]


def _texts(d):
    if isinstance(d, dict):
        return [t for v in d.values() for t in _texts(v)]
    if isinstance(d, list):
        return [t for v in d for t in _texts(v)]
    return [d] if isinstance(d, str) and not re.match(r"^(/|[\w.-]+/|https?:|file:)", d) else []


def demo(bid, out_dir, jobs=4, only=None):
    """Render every template for a brand with realistic copy (templates/ads/_demo.json). only = name prefixes.
    Returns [(file, label)]."""
    tok = brand_tokens(bid)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for s in _demo_specs(bid):
        size = SIZES.get(s.get("size", "feed")) or tuple(s["size"])
        name = s.get("name") or f"{s['template']}-{fmt_of(size)}"
        if only and not any(name.startswith(o) for o in only):
            continue
        issues = compliance_issues(bid, _texts(s["data"]))
        if issues:
            print(f"  COMPLIANCE {name}: " + "; ".join(i["match"] or i["rule"] for i in issues), file=sys.stderr)
        items.append((s["template"], s["data"], size, out / f"{name}.jpg", s.get("label") or name))

    def one(it):
        t, d, size, p, label = it
        t0 = time.time()
        render(t, d, p, size, tok)
        print(f"  {p.name}  {size[0]}x{size[1]}  {time.time() - t0:.1f}s")
        return str(p), label

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(one, items))


def sheet_groups(srcs):
    """Dirs/images → contact-sheet groups. A dir named after a brand gets the brand's name as its title; files
    named like a _demo.json entry get that entry's label."""
    spec = _json(TEMPLATES / "_demo.json")
    groups = []
    for src in srcs:
        p = Path(src)
        fs = sorted(p.glob("*.jpg")) if p.is_dir() else [p]
        entries = spec.get(p.name) if isinstance(spec.get(p.name), list) else [s for v in spec.values() if isinstance(v, list) for s in v]
        labels = {s["name"]: s.get("label") for s in entries if s.get("name")}
        title = ""
        if p.is_dir():
            title = p.name
            if (BRANDS / p.name).is_dir():
                tok = brand_tokens(p.name)
                title = f"{tok['name']}  ·  {tok['lang'].upper()}  ·  {len(fs)} renders"
        groups.append((title, [(str(f), labels.get(f.stem) or f.stem) for f in fs]))
    return groups


def contact_sheet(groups, out_path, cols=6, thumb_w=360):
    """groups: [(title, [(file, label), ...]), ...] → one labelled JPEG sheet (rendered by Chrome)."""
    gap, pad = 28, 56
    rows_html, total_h = [], pad
    for title, files in groups:
        rows_html.append(f'<h2>{html.escape(title)}</h2><div class="grid">')
        total_h += 90
        row_h, col = 0, 0
        for f, label in files:
            w, h = _img_size(f) or (1080, 1350)
            th = round(thumb_w * h / w)
            row_h = max(row_h, th + 44)
            rows_html.append(f'<figure><img src="{Path(f).resolve().as_uri()}" style="height:{th}px">'
                             f'<figcaption>{html.escape(label)}</figcaption></figure>')
            col += 1
            if col == cols:
                total_h += row_h + gap
                row_h, col = 0, 0
        if col:
            total_h += row_h + gap
        rows_html.append("</div>")
    width = pad * 2 + cols * thumb_w + (cols - 1) * gap
    total_h += pad
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}body{{background:#EDEBE6;font:500 18px -apple-system,"Helvetica Neue",Arial,sans-serif;
color:#222;padding:{pad}px;width:{width}px}}h2{{font-size:30px;font-weight:700;margin:26px 0 22px;letter-spacing:-.01em}}
.grid{{display:grid;grid-template-columns:repeat({cols},{thumb_w}px);gap:{gap}px;align-items:start}}
figure img{{width:{thumb_w}px;display:block;box-shadow:0 1px 2px rgba(0,0,0,.12),0 8px 24px rgba(0,0,0,.08)}}
figcaption{{margin-top:10px;font-size:16px;color:#555}}</style></head><body>{''.join(rows_html)}</body></html>"""
    with tempfile.TemporaryDirectory(prefix="otto-sheet-", dir=_tmp_root()) as tmp:
        png = str(Path(tmp) / "sheet.png")
        screenshot(page, png, (width, total_h), budget=8000)
        return _finish(png, out_path, _png_size(png) or (width, total_h))


def _img_size(f):
    ff = shutil.which("ffprobe")
    if not ff:
        return None
    r = subprocess.run([ff, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return None


# ---------------------------------------------------------------- CLI

def _json_arg(raw):
    """A JSON string, or the path of a JSON file."""
    if raw.lstrip().startswith(("{", "[")):
        return json.loads(raw)
    return json.loads(Path(raw).read_text(encoding="utf-8"))


def _size_arg(a):
    if "--size" in a:
        v = a[a.index("--size") + 1]
        if v in SIZES:
            return SIZES[v]
        w, h = v.lower().split("x")
        return int(w), int(h)
    return SIZES["feed"]


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "list":
        print("\n".join(list_templates()))
    elif cmd == "tokens":
        print(json.dumps(brand_tokens(a[1]), ensure_ascii=False, indent=1))
    elif cmd == "one":
        tpl, raw, out = a[1], a[2], a[3]
        data = _json_arg(raw)
        bid = a[a.index("--brand") + 1] if "--brand" in a else None
        print(render(tpl, data, out, _size_arg(a), brand_tokens(bid)))
    elif cmd == "check":
        tpl, raw = a[1], a[2]
        data = _json_arg(raw)
        bid = a[a.index("--brand") + 1] if "--brand" in a else None
        rep = fit_report(tpl, data, _size_arg(a), brand_tokens(bid))
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 3 if rep.get("overflow") else 0
    elif cmd == "demo":
        bid, out = a[1], a[2]
        only = a[a.index("--only") + 1].split(",") if "--only" in a else None
        t0 = time.time()
        files = demo(bid, out, only=only)
        print(f"{len(files)} renders in {time.time() - t0:.0f}s → {out}")
    elif cmd == "sheet":
        out, srcs = a[1], a[2:]
        print(contact_sheet(sheet_groups(srcs), out))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RenderError as e:
        print(f"otto_render: {e}", file=sys.stderr)
        sys.exit(1)
