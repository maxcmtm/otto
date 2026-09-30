#!/usr/bin/env python3
"""Otto creative — ad variants in every style, built from the angles that work in the category.

  otto_creative.py variants <campaign-id> [--dry]            # angles × formats → campaign.creatives (statics with copy, carousels, video)
  otto_creative.py overlay <src.jpg> <dst.jpg> "<text>" [--color #2447F0] [--pos bottom|center]
  otto_creative.py angles <brand>                            # print the angle bank Otto would use
  otto_creative.py matrix <brand> <YYYY-MM> --plan [--preset launch|micro|scale | --budget <daily> [--currency EUR]]
                                                             # write the month's ad matrix skeleton (angles × styles) if none;
                                                             # default preset = the brand's plan (plans.json), micro under ~€36/day
  otto_creative.py matrix <brand> <YYYY-MM> --check          # coverage gaps + every cell's status and compliance (exit 1 on a
                                                             # writing gap; scripted / planned / hold are listed, not failures)
  otto_creative.py matrix <brand> <YYYY-MM> --render <dir>   # render every ready image cell into <dir> (nothing is stored)

The ad matrix (brands/<id>/ads-<YYYY-MM>.json, format and rules in otto_styles.py) is how paid creative is made: ≥6
angles × ≥3 styles each (Notes list, search page, text thread, reviews, us-vs-them, product huge, ingredients, …), image
and video cells. When the month has one with cells ready to run, build() renders every ready image cell with otto_render
(feed + story versions), takes rendered video cells as they are (otto_motion renders them), groups them per angle
(creatives.concepts → one Meta ad set per angle in otto_ads) and tags every file with its style and angle. Every cell's
texts pass otto_compliance first: a violating, unwritten or invalid cell is skipped and reported (creatives.matrix.skipped),
never rendered; a scripted video cell (copy written, kit JSON not generated) waits in creatives.matrix.scripted_videos and a
cell on hold ("status": "hold", e.g. licence pending) in creatives.matrix.held — neither launches. An image cell without its
own "cta" shows the words of the Meta button it runs with (SHOP_NOW → "Shop now" in the brand's language). Without a matrix (or before any cell is written) build() makes today's angle-bank creatives below.

Angle bank, in order of trust: brands/<slug>/angles.json (written by otto_competitors.py from the
ad-library sweep: longevity winners = proven), the profile's "Winning angles" section, then the
brand's best hooks. Every variant = one angle, one hook, one proof line, one CTA — and the copy is
tested by Meta's dynamic creative (otto_ads.py launches all titles/bodies/images in one ad set).
Text on image is rendered by ffmpeg (deterministic typography, brand band), never by the image model:
one drawtext per line (expansion=none, so "20% off" is literal), right-aligned for Hebrew/Arabic. When this
ffmpeg's drawtext has text_shaping (libfribidi) it shapes RTL itself; otherwise lines are pre-reordered
(bidi_line). Statics / carousel cards are written as real JPEG (Instagram and Meta both take it) and
copied to the public assets dir right away (otto_paths.publish).
CTA card text follows the brand language (he → "לפרטים בלינק", de → "Mehr erfahren", else English).
"""
import json, os, re, shutil, subprocess, sys, tempfile, textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ap
import otto_paths as paths

try:
    import otto_render                    # studio templates via headless Chrome
except Exception:
    otto_render = None
try:
    import otto_styles                    # style catalogue + the angle × style ad matrix
except Exception:
    otto_styles = None

HERE = Path(__file__).parent
BRANDS = ap.BRANDS
OUT = paths.ASSETS / "ads"
FONT_CANDIDATES = [os.environ.get("OTTO_FONT", ""), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"]
CTA = {"leads": "SIGN_UP", "traffic": "LEARN_MORE", "sales": "SHOP_NOW", "engagement": "LEARN_MORE", "awareness": "LEARN_MORE"}
CTA_CARD = {"he": "לפרטים בלינק", "de": "Mehr erfahren", "fr": "En savoir plus", "es": "Más información", "it": "Scopri di più",
            "pt": "Saiba mais", "nl": "Meer informatie", "pl": "Dowiedz się więcej", "ro": "Află mai multe", "hu": "Tudj meg többet"}


def font_path():
    for f in FONT_CANDIDATES:
        if f and Path(f).exists():
            return f
    return None


def ffmpeg():
    return shutil.which("ffmpeg")


def hex_ok(h):
    return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", h or ""))


RTL = re.compile(r"[\u0590-\u05FF\u0600-\u06FF]")


def clean_text(t):
    """Strip markdown and stray markers before anything is rendered or sent to an ad."""
    t = re.sub(r"\*\*|__|`|^[#>\-\*\s]+", "", t or "").strip()
    return re.sub(r"\s+", " ", t)


def bidi_line(line):
    """Fallback for an ffmpeg without text_shaping: for RTL lines, reverse token order and RTL runs so the
    rendered glyphs read correctly (digits and Latin tokens stay as they are)."""
    if not RTL.search(line):
        return line
    toks = line.split(" ")
    kind = ["rtl" if RTL.search(t) else "ltr" if re.search(r"[A-Za-z0-9]", t) else "neutral" for t in toks]
    runs = []                                # consecutive LTR tokens (and neutrals between them) stay one run
    for i, (t, k) in enumerate(zip(toks, kind)):
        if k == "neutral" and runs and runs[-1][0] == "ltr" and "ltr" in kind[i + 1:i + 2]:
            k = "ltr"
        if runs and k == "ltr" and runs[-1][0] == "ltr":
            runs[-1][1].append(t)
        else:
            runs.append([k, [t]])
    out = []
    for k, ts in reversed(runs):
        out.append(" ".join(ts) if k == "ltr" else " ".join(_flip_token(t) for t in reversed(ts)))
    return " ".join(out)


def _flip_token(t):
    """One RTL-context token → visual order: RTL letters reversed, digit/Latin pieces kept ("ב-50%" → "50%-ב")."""
    segs = []
    for seg in re.findall(r"[\u0590-\u05FF\u0600-\u06FF]+|[^\u0590-\u05FF\u0600-\u06FF]+", t):
        if RTL.search(seg):
            segs.append(seg[::-1])
        else:
            m = re.match(r"^([^A-Za-z0-9]*)(.*)$", seg)
            segs += [x for x in (m.group(1), m.group(2)) if x]
    return "".join(reversed(segs))


_SHAPING = None


def drawtext_shaping():
    """True when this ffmpeg's drawtext has the text_shaping option (built with libfribidi).
    OTTO_TEXT_SHAPING=0/1 overrides the probe."""
    global _SHAPING
    env = os.environ.get("OTTO_TEXT_SHAPING")
    if env in ("0", "1"):
        return env == "1"
    if _SHAPING is None:
        _SHAPING = False
        ff = ffmpeg()
        if ff:
            try:
                r = subprocess.run([ff, "-hide_banner", "-h", "filter=drawtext"], capture_output=True, text=True, timeout=20)
                _SHAPING = bool(re.search(r"^\s*text_shaping\b", r.stdout + r.stderr, re.M))
            except Exception:
                _SHAPING = False
    return _SHAPING


def prep_lines(text, width=22, max_lines=4, shaping=None):
    """Wrapped lines in logical order; pre-reordered for RTL only when drawtext cannot shape."""
    shaping = drawtext_shaping() if shaping is None else shaping
    lines = textwrap.wrap(clean_text(text), width)[:max_lines]
    return lines if shaping else [bidi_line(l) for l in lines]


def drawtext_chain(lines, font, fontcolor, size, y_top, rtl, margin=60, spacing=10):
    """One drawtext per line (so RTL lines are each right-aligned). y_top is an ffmpeg expression for the
    first line's top. Returns (filter string, temp files to delete)."""
    shaping = drawtext_shaping()
    parts, files = [], []
    for i, ln in enumerate(lines):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write(ln)
            files.append(tf.name)
        x = f"w-text_w-{margin}" if rtl else str(margin)
        opt = (f"drawtext=fontfile='{font}':textfile='{tf.name}':expansion=none:fontcolor={fontcolor}:fontsize={size}"
               f":x={x}:y={y_top}+{i * (size + spacing)}")
        if shaping:
            opt += ":text_shaping=1"
        parts.append(opt)
    return ",".join(parts), files


def text_color_for(band_hex):
    """White on dark bands, near-black on light ones (WCAG-ish luminance split)."""
    h = band_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "0x1D1D1F" if lum > 0.62 else "white"


def overlay_text(src, dst, text, color="#2447F0", pos="bottom", size=None):
    """Brand band + headline on an image. Returns dst path; raises if ffmpeg/font missing.
    A .jpg/.jpeg dst is written as high-quality JPEG (-q:v 2)."""
    fp, ff = font_path(), ffmpeg()
    if not ff or not fp:
        raise RuntimeError("ffmpeg or a TTF font is missing (set OTTO_FONT)")
    lines = prep_lines(text, 22)
    if not lines:
        raise RuntimeError("no text to render")
    size = size or (64 if len(lines) <= 2 else 56)
    spacing = 10
    text_h = size * len(lines) + spacing * (len(lines) - 1)
    band_h = text_h + 120
    color = color if hex_ok(color) else "#2447F0"
    fc = text_color_for(color)
    y_top = f"h-{band_h}+60" if pos == "bottom" else f"(h-{text_h})/2"
    rtl = bool(RTL.search(text or ""))                          # right-align right-to-left copy
    band = f"drawbox=x=0:y=ih-{band_h}:w=iw:h={band_h}:color={color}@0.92:t=fill," if pos == "bottom" else f"drawbox=x=0:y=0:w=iw:h=ih:color={color}@0.55:t=fill,"
    chain, files = drawtext_chain(lines, fp, fc, size, y_top, rtl, margin=60, spacing=spacing)
    vf = band + chain
    out_opts = ["-frames:v", "1"]
    if str(dst).lower().endswith((".jpg", ".jpeg")):
        out_opts += ["-q:v", "2"]
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf] + out_opts + [str(dst)],
                           capture_output=True, text=True)
    finally:
        for f in files:
            os.unlink(f)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return str(dst)


def _mark_from(src, dst):
    """A card built on an AI-generated photo contains a generated element: carry the AI mark over (EU AI Act Art. 50(2)).
    Cards on the client's real photos stay unmarked — propagate() does nothing when src carries no mark."""
    try:
        import otto_provenance
        p = str(src or "")
        if p.startswith("assets/"):
            p = str(paths.local_path(p))
        if p and os.path.exists(p) and os.path.exists(str(dst)):
            otto_provenance.propagate(p, str(dst), tool="otto_render", log=lambda *a, **k: None)
    except Exception:                                      # a mark never stops a render (the console flags unmarked AI media)
        pass


def render_card(template, data, src, dst, text, color, bid, **overlay_kw):
    """otto_render template; the ffmpeg band when no headless Chrome (or OTTO_RENDERER=ffmpeg)."""
    if otto_render is not None and os.environ.get("OTTO_RENDERER", "html") != "ffmpeg":
        try:
            out = otto_render.render(template, dict(data, photo=str(src)), dst, brand=bid)
            _mark_from(src, dst)
            return out
        except otto_render.CopyError:
            raise                                          # a placeholder never falls back to a text band: it fails
        except otto_render.RenderError as e:
            print(f"otto_render fallback: {str(e)[:160]}", file=sys.stderr)
    return overlay_text(src, dst, text, color, **overlay_kw)


# ---------------- angle bank ----------------

# internal notes that must never become ad copy: performance numbers, currency, lead counts, arrows,
# unverified markers, agent notes, "don't" markers
NOT_COPY = re.compile(r"\bCPL\b|\bCPA\b|ROAS|₪|€|\$\s?\d|→|->|\(\?\)|❌|✗|\bleads?\b|לידים|\d+\s*%?\s*(clicks|conv)|"
                      r"\bagent\b|\bTODO\b|\bTBD\b|hypothes|placeholder", re.I)
QUOTED = re.compile(r"[\"“”„«»]([^\"“”„«»]{6,140})[\"“”„«»]")


def profile_angles(bid):
    """Angles from the profile's "Winning angles" section — only quoted hooks ("…" on the line) or a clean
    angle label (the **bold** title / text before " — "); lines carrying CPL, ₪/€, lead counts, arrows,
    (?) or ❌ never become copy."""
    prof = BRANDS / bid / "brand-profile.md"
    if not prof.exists():
        return []
    t = prof.read_text()
    m = re.search(r"Winning angles.*?\n(.*?)(?=\n## |\Z)", t, re.S)
    out = []
    if m:
        for raw in m.group(1).splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            quotes = [q.strip() for q in QUOTED.findall(raw)]
            if quotes:
                if "❌" in raw or "✗" in raw:          # a quoted myth / don't — never an ad line
                    continue
                cands = quotes
            else:
                if NOT_COPY.search(raw):
                    continue
                body = raw.lstrip("-*0123456789. ")
                bold = re.search(r"\*\*(.+?)\*\*", body)
                label = bold.group(1) if bold else re.split(r"\s[—–-]\s", body)[0]
                cands = [re.sub(r"\([^)]*\)", "", label)]
            for c in cands:
                c = clean_text(c).strip(" -—–:")
                if 6 < len(c) < 160 and not NOT_COPY.search(c):
                    out.append({"angle": c, "source": "profile"})
    return out[:5]


def cta_card_text(b):
    lang = ap.brand_lang(b)
    return CTA_CARD.get(lang) or f"{b.get('name', '')}: talk to us".strip(": ")


def angle_bank(d, bid, n=3):
    aj = BRANDS / bid / "angles.json"
    bank = []
    if aj.exists():
        bank += [a for a in json.loads(aj.read_text()).get("angles", []) if a.get("angle")]
    bank += profile_angles(bid)
    hooks = [p for p in d["posts"] if p["brand"] == bid and p.get("hook")]
    hooks.sort(key=lambda p: -((p.get("metrics") or {}).get("reach", 0)))
    for p in hooks[:4]:
        bank.append({"angle": p["hook"][:120], "source": "post", "post": p["id"]})
    seen, out = set(), []
    for a in bank:
        k = a["angle"].lower()[:50]
        if k not in seen:
            seen.add(k); out.append(a)
    return out[:n]


def trim(t, n):
    t = clean_text(t)
    return t if len(t) <= n else t[:n - 1].rsplit(" ", 1)[0] + "…"


def proof_line(bid):
    sj = BRANDS / bid / "scan.json"
    if sj.exists():
        s = json.loads(sj.read_text())
        for q in s.get("trust", []):
            if 12 < len(q) < 110:
                return q
        for q in s.get("quotes", []):
            return "“" + trim(q, 90) + "”"
    return ""


# ---------------- variants ----------------

def build(d, c, dry=False, base=None):
    """A campaign's creatives, stored on c["creatives"]: the month's ad matrix when it has cells ready to run (every cell
    rendered — planned when dry — and grouped per angle), else the angle bank × (editorial static + 3-card carousel)."""
    base = base or paths.BASE                        # OTTO_PUBLIC_BASE (the app host on the new domain)
    bid = c["brand"]
    ym = str(c.get("plan") or c.get("start") or "")[:7]
    info = None
    if otto_styles is not None and re.fullmatch(r"\d{4}-\d{2}", ym):
        try:
            mx = otto_styles.load_matrix(bid, ym)
        except ValueError as e:                           # a broken matrix is reported, never read as "empty"
            mx, info = None, {"file": f"brands/{bid}/ads-{ym}.json", "error": str(e)[:200]}
            print(f"ad matrix: {e} — angle-bank creatives instead", file=sys.stderr)
        if mx is not None:
            cr = plan_video(d, c, build_matrix(d, c, mx, dry=dry))
            if cr["concepts"]:
                c["creatives"] = cr
                return cr
            info = dict(cr["matrix"], note="no cell of the matrix is ready to run yet — angle-bank creatives meanwhile")
    cr = build_angles(d, c, dry=dry, base=base)
    if info:
        cr["matrix"] = info
    return plan_video(d, c, cr)


def plan_video(d, c, cr):
    """The brand's plan (plans.json) decides the video in a campaign's creatives, in place: without video_ads no Otto-made
    video ad runs (matrix video cells, angle-bank reels), without creator_briefs no creator video, and video_ads_per_month
    caps the faceless ones (in concept order). Whatever is left out is named in creatives.plan (and, for matrix cells, in
    creatives.matrix.skipped) — the statics of every concept still run."""
    p = ap.plan_of(d, c.get("brand"))
    f, cap = p["features"], p["limits"].get("video_ads_per_month")
    out, n = [], 0
    for con in cr.get("concepts") or []:
        keep = []
        for ad in con.get("ads") or []:
            why = None
            if ad.get("format") == "creator" and not f.get("creator_briefs"):
                why = f"plan {p['id']} has no creator videos"
            elif ad.get("format") == "video":
                if not f.get("video_ads"):
                    why = f"plan {p['id']} has no video ads"
                elif cap is not None and n >= cap:
                    why = f"plan {p['id']} allows {cap:g} video ads a month"
                else:
                    n += 1
            if why:
                out.append({"id": ad.get("id"), "angle": ad.get("angle"), "style": ad.get("style"), "status": "plan", "reason": why})
            else:
                keep.append(ad)
        con["ads"] = keep
    if "concepts" in cr:
        cr["concepts"] = [con for con in cr["concepts"] if con["ads"]]
    gone = {x["id"] for x in out}
    vids = cr.get("videos") or []
    if not f.get("video_ads") and vids and not cr.get("concepts"):      # angle bank: reels as video ads
        out += [{"file": v.get("file"), "status": "plan", "reason": f"plan {p['id']} has no video ads"} for v in vids]
        cr["videos"] = []
    elif gone:
        cr["videos"] = [v for v in vids if v.get("cell") not in gone]
    if out:
        cr["plan"] = {"plan": p["id"], "left_out": out}
        if isinstance((cr.get("matrix") or {}).get("skipped"), list):
            cr["matrix"]["skipped"] += [x for x in out if x.get("id")]
        print(f"plan {p['id']}: {len(out)} video creative(s) left out — {out[0]['reason']}", file=sys.stderr)
    return cr


def _palette(bid):
    sj = BRANDS / bid / "scan.json"
    try:
        pl = json.loads(sj.read_text()).get("visual", {}).get("palette") or [] if sj.exists() else []
    except (OSError, ValueError):
        pl = []
    return pl[0]["hex"] if pl and hex_ok(pl[0].get("hex")) else "#2447F0"


def _cell_asset(bid, v):
    """A bare file name in render data ("pack.png") → the brand's file: brands/<id>/assets/, assets/site/<id>/, assets/site/."""
    if not isinstance(v, str) or not v.strip() or "/" in v or ":" in v:
        return v
    for p in (BRANDS / bid / "assets" / v, paths.ASSETS / "site" / bid / v, paths.ASSETS / "site" / v):
        if p.is_file():
            return paths.rel_of(p) if p.resolve().is_relative_to(paths.ASSETS.resolve()) else str(p.resolve())
    return v


def _resolve_assets(bid, v, key="", depth=0):
    """Photo fields of render data → files the renderer can load. Top level: the renderer resolves "assets/…" itself;
    inside objects / lists (us_vs_them us.photo, ingredients items[].photo) templates need an absolute path."""
    if isinstance(v, dict):
        return {k: _resolve_assets(bid, x, k, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve_assets(bid, x, key, depth + 1) for x in v]
    if not (isinstance(v, str) and otto_styles.ASSET_KEY.search(str(key))):
        return v
    ref = _cell_asset(bid, v)
    if depth > 1 and _local(ref):
        return str(_local(ref).resolve())
    return ref


def _local(ref):
    try:
        p = paths.local_path(ref) if str(ref).startswith("assets/") else Path(str(ref)).expanduser()
    except Exception:
        return None
    return p if p.is_file() else None


def _local_photo(data):
    for k, v in (data or {}).items():
        if isinstance(v, str) and v and otto_styles.ASSET_KEY.search(str(k)) and _local(v):
            return _local(v)
    return None


def _render_cell_card(template, data, dst, size, tok, text, pal):
    """One matrix card: otto_render; without headless Chrome (or OTTO_RENDERER=ffmpeg) the ffmpeg band on the cell's photo."""
    err = "OTTO_RENDERER=ffmpeg"
    if otto_render is not None and os.environ.get("OTTO_RENDERER", "html") != "ffmpeg":
        try:
            out = otto_render.render(template, data, dst, otto_styles.SIZES[size], tok)
            _mark_from(data.get("photo"), dst)
            return out
        except otto_render.CopyError:
            raise                                          # a placeholder never falls back to a text band: it fails
        except otto_render.RenderError as e:
            err = str(e)[:120]
    src = _local_photo(data)
    if src and text:
        return overlay_text(src, dst, text, pal)
    raise RuntimeError(f"{template}: {err}; no photo for the ffmpeg fallback")


def _carousel_cards(data):
    """Carousel cell data {cover, slides[1-4], end} → [(template, card data)] with the n / total counter."""
    slides = [x for x in data.get("slides") or [] if isinstance(x, dict)][:4]
    total = len(slides) + 2
    cards = [("carousel_cover", dict(data.get("cover") or {}, n=1, total=total))]
    cards += [("carousel_inner", dict(sl, n=k, total=total, step=sl.get("step") or f"{k - 1:02d}")) for k, sl in enumerate(slides, 2)]
    return cards + [("carousel_cta", dict(data.get("end") or {}, n=total, total=total))]


def _namer(c):
    """(stem, ext) → the campaign's unguessable public file name (otto_paths.token_name with its media token, kept on the
    campaign and in its creatives, so a re-render — or the launch after a dry plan — gives the same names)."""
    cr = c.get("creatives") if isinstance(c.get("creatives"), dict) else {}
    t = paths.record_token(c, cr.get("media_token"))
    return lambda stem, ext: paths.token_name(stem, ext, t)


def _to_assets(src, name, dry):
    """A delivered file outside assets/ (a creator's footage in brands/<id>/) → a copy in assets/ads/ (public), since Meta
    uploads only take files from there. dry = the name it would get."""
    src = Path(src)
    try:
        if src.resolve().is_relative_to(paths.ASSETS.resolve()):
            return paths.rel_of(src)
    except OSError:
        pass
    dst = OUT / name
    if not dry:
        OUT.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        paths.publish(dst)
    return f"assets/ads/{dst.name}"


def _poster(ref, cell, dry, bid=None):
    """A video ad needs a thumbnail: the cell's "poster", a .jpg next to the video, else a frame at 1 s (ffmpeg)."""
    if cell.get("poster"):
        src = otto_styles._media_file(bid, cell["poster"]) if bid else _local(cell["poster"])
        if src:
            return _to_assets(src, paths.token_name(f"{Path(str(ref)).stem}-poster", src.suffix), dry)
    src = _local(ref)
    if not src:
        return None
    jpg = src.with_suffix(".jpg")
    if not jpg.exists() and not dry and ffmpeg():
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", "1", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(jpg)],
                       capture_output=True)
    if not jpg.exists():
        return None
    return paths.rel_of(jpg) if jpg.resolve().is_relative_to(paths.ASSETS.resolve()) else str(jpg)


def build_matrix(d, c, mx, dry=False, out=None, publish=True, jobs=3):
    """The month's matrix → creatives grouped per angle (creatives.concepts[].ads[].files), each file tagged with style +
    angle. Only "ready" cells (otto_styles.check_matrix: written, valid, compliant, template on disk) are rendered: feed and
    story versions (a carousel = one file per card); a video cell joins once otto_motion has rendered its "file". Every other
    cell is listed in creatives.matrix.skipped with the reason; a creator cell waits in creatives.matrix.planned_creators
    until the real creator's footage (with name + consent) is its "file". Copy = the angle's headlines / primaries rotated
    over its cells (otto_styles.ad_copy) unless a cell overrides. dry = plan the file names, render nothing."""
    bid = c["brand"]
    nm = _namer(c)                                     # unguessable public file names
    rep = otto_styles.check_matrix(bid, matrix=mx)
    status = {(r["angle"], r["id"]): r for r in rep["cells"]}
    out = Path(out) if out else OUT
    pub_ok = publish and out.resolve() == OUT.resolve()
    rel = (lambda p: f"assets/ads/{p.name}") if out.resolve() == OUT.resolve() else str
    pal, tok = _palette(bid), bid
    if otto_render is not None and not dry:
        try:
            tok = otto_render.brand_tokens(bid)            # once for every card
        except Exception:
            tok = bid
    cr = {"angles": [], "titles": [], "bodies": [], "descriptions": [], "images": [], "carousels": [], "videos": [],
          "cta": CTA.get(c.get("objective"), "LEARN_MORE"), "built_at": ap.now_iso(), "dry": dry, "concepts": [],
          "matrix": {"file": f"brands/{bid}/ads-{mx.get('month') or str(c.get('plan') or '')}.json", "size": rep["size"],
                     "gaps": rep["gaps"], "copy": rep["copy"], "skipped": [], "planned_videos": [], "planned_creators": [],
                     "scripted_videos": [], "held": [dict(id=r["id"], angle=r["angle"], style=r["style"], reason=r["reasons"][0])
                                                     for r in rep["cells"] if r["status"] == "hold"]}}
    cr["media_token"] = c["media_token"]
    lang = (tok.get("lang") if isinstance(tok, dict) else None) or "en"
    if lang == "en" and otto_render is not None and not isinstance(tok, dict):
        try:
            lang = otto_render.brand_tokens(bid).get("lang") or "en"
        except Exception:
            pass
    todo, concepts = [], []
    for i, a in enumerate(otto_styles.live_angles(mx), 1):
        name = a.get("name") or otto_styles.short_name(a.get("angle")) or str(a.get("id"))
        con = {"angle": a.get("id"), "name": name, "ad_set": a.get("ad_set") or " · ".join(dict.fromkeys([str(a.get("id")), name])),
               "stage": a.get("stage"), "source": a.get("source"), "persona": a.get("persona"), "ads": []}
        cr["angles"].append({"n": i, "id": a.get("id"), "angle": a.get("angle") or name, "name": name, "source": a.get("source")})
        for cell in otto_styles.live_cells(a):
            r = status.get((a.get("id"), cell.get("id"))) or {"status": "invalid", "reasons": ["duplicate or missing cell id"],
                                                               "style": cell.get("style")}
            tag = {"id": cell.get("id"), "angle": a.get("id"), "style": r["style"]}
            if r["status"] == "planned":                  # a creator brief waiting for real footage — not a failure
                cr["matrix"]["planned_creators"].append(dict(tag, reason="; ".join(r["reasons"])[:160]))
                continue
            if r["status"] == "scripted":                 # copy written, motion has not generated the kit JSON yet
                cr["matrix"]["scripted_videos"].append(dict(tag, kit=(cell.get("video") or {}).get("kit") or
                                                            otto_styles.STYLES[r["style"]]["video"],
                                                            data=(cell.get("video") or {}).get("data")))
                continue
            if r["status"] != "ready":
                cr["matrix"]["skipped"].append(dict(tag, status=r["status"], reason="; ".join(r["reasons"])[:240]))
                continue
            style, S = r["style"], otto_styles.STYLES[r["style"]]
            cp = r.get("copy") or otto_styles.ad_copy(a, cell)
            ad = dict(tag, format=otto_styles.fmt(cell), template=cell.get("template") or ("carousel" if S.get("cards") else S["template"]),
                      primary=cp["primary"], headline=cp["headline"], description=cp["description"], cta=cp["cta"].upper(), files=[])
            if ad["format"] == "creator":                  # real footage, name + consent checked by otto_styles.validate_cell
                src = otto_styles._media_file(bid, cell.get("file"))
                safe = re.sub(r"[^A-Za-z0-9_-]", "", str(cell.get("id")))
                ref = _to_assets(src, nm(f"{c['id']}-{safe}", src.suffix), dry)
                ad["files"] = [{"file": ref, "size": "story", "kind": "video", "poster": _poster(ref, cell, dry, bid)}]
                ad["creator"] = (cell.get("creator") or {}).get("name")
                con["ads"].append(ad)
                cr["videos"].append({"file": ref, "style": style, "angle": a.get("id"), "cell": cell.get("id"), "creator": ad["creator"]})
                continue
            if ad["format"] == "video":
                kit = (cell.get("video") or {}).get("kit") or S["video"]
                src = otto_styles._media_file(bid, cell.get("file")) if cell.get("file") else None
                if src:                                   # rendered: into assets/ (Meta uploads only take public files)
                    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(cell.get("id")))
                    ref = _to_assets(src, nm(f"{c['id']}-{safe}", src.suffix), dry)
                    ad["files"] = [{"file": ref, "size": "story", "kind": "video", "poster": _poster(ref, cell, dry, bid)}]
                    ad["kit"] = kit
                    con["ads"].append(ad)
                    cr["videos"].append({"file": ref, "style": style, "angle": a.get("id"), "cell": cell.get("id"), "kit": kit})
                else:
                    cr["matrix"]["planned_videos"].append(dict(tag, kit=kit, data=(cell.get("video") or {}).get("data")))
                continue
            data = _resolve_assets(bid, cell.get("data") or {})
            # the words on the image say what the Meta button does: the cell's / angle's cta (SHOP_NOW → "Shop now" in the
            # brand's language), else the campaign objective's — never a generic "Learn more" over a Shop Now button
            if not str(data.get("cta") or "").strip() and otto_render is not None:
                btn = ad["cta"] if ad["cta"] in otto_styles.META_CTAS else cr["cta"]
                label = otto_render.cta_label(btn, lang)
                if label:
                    data = dict(data, cta=label)
            safe = re.sub(r"[^A-Za-z0-9_-]", "", str(cell.get("id")))
            text = ad["headline"] or next((str(data.get(k)) for k in ("headline", "title", "quote", "word", "name") if data.get(k)), "")
            for size in otto_styles.cell_sizes(cell):
                sfx = "" if size == "feed" else f"-{size}"
                if style == "carousel":
                    cards = []
                    for j, (tpl, cd) in enumerate(_carousel_cards(data), 1):
                        dst = out / nm(f"{c['id']}-{safe}-c{j}{sfx}", ".jpg")
                        todo.append({"ad": ad, "template": tpl, "data": cd, "size": size, "dst": dst,
                                     "text": cd.get("headline") or cd.get("title") or text})
                        cards.append({"file": rel(dst), "text": cd.get("headline") or cd.get("title") or ""})
                    ad["files"].append({"file": cards[0]["file"], "size": size, "cards": cards})
                else:
                    dst = out / nm(f"{c['id']}-{safe}{sfx}", ".jpg")
                    todo.append({"ad": ad, "template": S["template"], "data": data, "size": size, "dst": dst, "text": text})
                    ad["files"].append({"file": rel(dst), "size": size})
            con["ads"].append(ad)
        concepts.append(con)
    if dry:
        for con in concepts:
            for ad in con["ads"]:
                for f in ad["files"]:
                    f.setdefault("planned", True)
    elif todo:
        def one(t):
            try:
                _render_cell_card(t["template"], t["data"], t["dst"], t["size"], tok, t["text"], pal)
                if pub_ok:
                    paths.publish(t["dst"])
                return None
            except Exception as e:
                return f"{t['dst'].name}: {str(e)[:160]}"
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for t, err in zip(todo, ex.map(one, todo)):
                if err:
                    t["ad"].setdefault("errors", []).append(err)
        for con in concepts:                               # a card that failed takes its whole ad out (never half a carousel)
            for ad in [x for x in con["ads"] if x.get("errors")]:
                con["ads"].remove(ad)
                cr["matrix"]["skipped"].append({"id": ad["id"], "angle": ad["angle"], "style": ad["style"], "status": "render failed",
                                                "reason": "; ".join(ad["errors"])[:240]})
    for con in concepts:
        for ad in con["ads"]:
            for k, key in (("headline", "titles"), ("primary", "bodies"), ("description", "descriptions")):
                if ad[k] and ad[k] not in cr[key]:
                    cr[key].append(ad[k])
            meta = {"style": ad["style"], "angle": ad["angle"], "cell": ad["id"]}
            for f in ad["files"]:
                if f.get("kind") == "video":
                    continue
                if f.get("cards"):
                    cr["carousels"].append(dict(meta, size=f["size"], cards=f["cards"]))
                else:
                    cr["images"].append(dict(meta, file=f["file"], text=ad["headline"], size=f["size"],
                                             **({"planned": True} if f.get("planned") else {})))
    cr["concepts"] = [con for con in concepts if con["ads"]]
    return cr


def build_angles(d, c, dry=False, base=None):
    """Today's angle-bank creatives: top 3 angles × (editorial static + 3-card carousel) + a reel when one exists."""
    base = base or paths.BASE                        # OTTO_PUBLIC_BASE (the app host on the new domain)
    bid = c["brand"]
    b = ap.brand(d, bid) or {"name": bid}
    angles = angle_bank(d, bid)
    posts = [p for p in d["posts"] if p["brand"] == bid and p.get("image")]
    posts.sort(key=lambda p: -((p.get("metrics") or {}).get("reach", 0)))
    src_post = ap.post(d, (c.get("creative") or {}).get("post") or "") or (posts[0] if posts else None)
    proof = proof_line(bid)
    pal = "#2447F0"
    sj = BRANDS / bid / "scan.json"
    if sj.exists():
        pl = json.loads(sj.read_text()).get("visual", {}).get("palette") or []
        if pl:
            pal = pl[0]["hex"]
    cr = {"angles": [], "titles": [], "bodies": [], "descriptions": [], "images": [], "carousels": [], "videos": [],
          "cta": CTA.get(c.get("objective"), "LEARN_MORE"), "built_at": ap.now_iso(), "dry": dry}
    nm = _namer(c)                                   # unguessable public file names
    cr["media_token"] = c["media_token"]
    OUT.mkdir(parents=True, exist_ok=True)
    cta_card = cta_card_text(b)
    for i, a in enumerate(angles, 1):
        # an angle is a strategist's note ("Nutrition support for people on GLP-1…"), not ad copy: use the copy
        # written for it (angles.json "ad": {headline, primary, description, proof}) and fall back to the note
        ad = a.get("ad") if isinstance(a.get("ad"), dict) else {}
        hook = trim(ad.get("headline") or a["angle"], 40)
        body = ad.get("primary") or (trim(a["angle"], 90) + (f" {proof}" if proof else "") + f" — {b['name']}.")
        cr["angles"].append({"n": i, "angle": a["angle"], "source": a.get("source")})
        cr["titles"].append(hook)
        cr["bodies"].append(trim(body, 125))
        if ad.get("description"):
            cr["descriptions"].append(trim(ad["description"], 30))
        img_post = ap.post(d, a.get("post") or "") or src_post
        if img_post and img_post.get("image"):
            dst = OUT / nm(f"{c['id']}-{i}-static", ".jpg")
            if dry:
                cr["images"].append({"file": f"assets/ads/{dst.name}", "from": img_post["id"], "text": hook, "planned": True})
            else:
                try:
                    render_card("editorial", {"headline": hook, "sub": proof.strip("“”")}, paths.local_path(img_post["image"]),
                                dst, hook, pal, bid)
                    paths.publish(dst)
                    cr["images"].append({"file": f"assets/ads/{dst.name}", "from": img_post["id"], "text": hook})
                except Exception as e:
                    cr["images"].append({"file": img_post["image"], "from": img_post["id"], "text": None, "note": str(e)[:120]})
            # carousel: hook / proof / cta on three images (rotating through the brand's visuals)
            cards = []
            card_data = [("carousel_cover", {"headline": hook}),
                         ("carousel_inner", {"title": trim(ad.get("proof") or proof or a["angle"], 140)}),
                         ("carousel_cta", {"headline": hook, "cta": cta_card})]
            for j, txt in enumerate([hook, trim(ad.get("proof") or proof or a["angle"], 40), cta_card], 1):
                ip = posts[(i + j) % len(posts)] if posts else img_post
                dst = OUT / nm(f"{c['id']}-{i}-c{j}", ".jpg")
                if dry:
                    cards.append({"file": f"assets/ads/{dst.name}", "text": txt, "planned": True})
                else:
                    try:
                        tpl, data = card_data[j - 1]
                        render_card(tpl, dict(data, n=j, total=3), paths.local_path(ip["image"]), dst, txt, pal, bid,
                                    pos="bottom", size=52)
                        paths.publish(dst)
                        cards.append({"file": f"assets/ads/{dst.name}", "text": txt})
                    except Exception as e:
                        cards.append({"file": ip["image"], "text": txt, "note": str(e)[:80]})
            cr["carousels"].append({"angle": i, "cards": cards})
        reel = paths.ASSETS / "reels" / f"{(img_post or {}).get('id', '')}.mp4"
        if (img_post or {}).get("video") or reel.exists():
            cr["videos"].append({"file": (img_post or {}).get("video") or f"assets/reels/{reel.name}", "from": img_post["id"]})
    cr["descriptions"] = cr["descriptions"] or ([trim(proof, 30)] if proof else [])
    c["creatives"] = cr
    return cr


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    if a[0] == "overlay":
        color = a[a.index("--color") + 1] if "--color" in a else "#2447F0"
        pos = a[a.index("--pos") + 1] if "--pos" in a else "bottom"
        print(overlay_text(a[1], a[2], a[3], color, pos))
    elif a[0] == "angles":
        d = ap.load()
        for x in angle_bank(d, a[1], 6):
            print(f"[{x.get('source')}] {x['angle']}")
    elif a[0] == "variants":
        d = ap.load()
        c = next((x for x in d.get("campaigns", []) if x["id"] == a[1]), None)
        assert c, f"unknown campaign {a[1]}"
        cr = build(d, c, dry="--dry" in a)            # renders outside the lock
        if "--dry" not in a:
            with ap.transaction() as d2:              # then patch just this campaign
                c2 = ap.campaign(d2, a[1])
                if c2 is not None:
                    c2["creatives"] = cr
        print(json.dumps({k: cr[k] for k in ("angles", "titles", "bodies", "cta")}, ensure_ascii=False, indent=1))
        print(f"images {len(cr['images'])} · carousels {len(cr['carousels'])} · videos {len(cr['videos'])}{' (dry)' if cr['dry'] else ''}")
    elif a[0] == "matrix" and len(a) >= 3:
        sys.exit(matrix_cli(a[1], a[2], a[3:]))
    else:
        print(__doc__)


def matrix_cli(bid, ym, opts):
    """--plan: write the skeleton if the month has none · --check: gaps + cell status (1 = something to fix) · --render <dir>."""
    assert otto_styles is not None, "otto_styles did not import"
    assert re.fullmatch(r"\d{4}-\d{2}", ym), f"month must be YYYY-MM, got {ym}"
    f = otto_styles.matrix_path(bid, ym)
    if "--plan" in opts:
        if f.exists():
            mx = otto_styles.load_matrix(bid, ym)
            print(f"{f} exists · {otto_styles.size_text(mx)} (not overwritten)")
        else:
            n = int(opts[opts.index("--per-angle") + 1]) if "--per-angle" in opts else None
            k = int(opts[opts.index("--angles") + 1]) if "--angles" in opts else None
            if "--preset" in opts:                        # the owner's explicit choice
                preset = opts[opts.index("--preset") + 1]
            else:                                         # the brand's plan (plans.json); a daily budget can cap it at micro
                cur = opts[opts.index("--currency") + 1] if "--currency" in opts else "EUR"
                bp = otto_styles.preset_for_budget(opts[opts.index("--budget") + 1], cur) if "--budget" in opts else None
                preset = ap.matrix_preset(ap.load(), bid, bp)
                if preset == "none":
                    print(f"{bid}: plan {ap.plan_of(ap.load(), bid)['id']} has no ad matrix — nothing written "
                          "(--preset launch|micro|scale writes one anyway)")
                    return 1
            assert preset in otto_styles.PRESETS, f"preset must be one of {', '.join(otto_styles.PRESETS)}"
            if n is None and preset == "scale":           # scale runs more styles per concept than there are slots
                n = otto_styles.PRESETS["scale"]["min_styles_per_angle"]
            mx = otto_styles.plan_matrix(bid, n_per_angle=n, ym=ym, n_angles=k, preset=preset)
            if not mx["angles"]:
                print(f"{bid}: no angles to plan from (strategy.json angles, angles.json, pains) — run otto_strategy init / "
                      "the competitor research first")
                return 1
            otto_styles.save_matrix(bid, ym, mx)
            print(f"wrote {f} · {preset} · {otto_styles.size_text(mx)}")
            for a in mx["angles"]:
                print(f"  {a['family']:10} {a['id']:8} {a['name'][:40]:40} " + ", ".join(
                    c["style"] + {"video": " (video)", "creator": " (creator)"}.get(c["format"], "") for c in a["ads"]))
            for st, why in mx.get("excluded", {}).items():
                print(f"  not planned: {st} — {why}")
        for g in otto_styles.coverage(mx):
            print(f"  gap: {g}")
        return 0
    mx = otto_styles.load_matrix(bid, ym)
    if mx is None:
        print(f"no matrix at {f} — run: otto_creative.py matrix {bid} {ym} --plan")
        return 1
    if "--check" in opts:
        rep = otto_styles.check_matrix(bid, ym, mx)
        counts = {}
        for r in rep["cells"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"{bid} {ym}: {rep['size']} · " + " · ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        for g in rep["gaps"]:
            print(f"  gap: {g}")
        for g in rep["copy"]:
            print(f"  copy: {g}")
        for g in rep["refresh"]:
            print(f"  refresh: {g}")
        order = {"invalid": 0, "violation": 1, "unwritten": 2, "pending": 3, "scripted": 4, "planned": 5, "hold": 6, "ready": 7}
        for r in sorted(rep["cells"], key=lambda r: order.get(r["status"], 9)):
            if r["status"] != "ready" or r["warnings"] or r["reasons"]:
                print(f"  {r['status']:9} {r['id']:28} {r['format']:7} {'; '.join(r['reasons'] + r['warnings'])[:200]}")
        writing = sum(1 for r in rep["cells"] if r["status"] in ("unwritten", "invalid", "violation"))
        production = sum(1 for r in rep["cells"] if r["status"] in ("scripted", "planned", "pending"))
        held = sum(1 for r in rep["cells"] if r["status"] == "hold")
        print(f"  writing gaps: {writing} · production gaps: {production} (scripted videos wait for motion's kit JSON, "
              f"creator cells for footage) · on hold: {held} (never launched)")
        # planned / scripted (production: footage, motion's kit JSON) and hold (parked on purpose) are not writing failures;
        # refresh is advice for the weekly batch
        ok = ("ready", "planned", "scripted", "hold")
        return 1 if rep["gaps"] or rep["copy"] or any(r["status"] not in ok for r in rep["cells"]) else 0
    if "--render" in opts:
        out = Path(opts[opts.index("--render") + 1])
        d = ap.load()
        b = ap.brand(d, bid) or {}
        c = {"id": f"{bid}-{ym}", "brand": bid, "plan": ym, "objective": "sales" if b.get("objective") == "sales" else "traffic"}
        cr = build_matrix(d, c, mx, dry=False, out=out, publish=False)
        for con in cr["concepts"]:
            print(f"{con['ad_set']}  ({len(con['ads'])} ads)")
            for ad in con["ads"]:
                print(f"  {ad['style']:13} {ad['format']:5} " + "  ".join(str(Path(x['file']).name) for x in ad["files"]))
        for s in cr["matrix"]["skipped"]:
            print(f"  skipped {s['id']}: {s['status']} — {s['reason'][:140]}")
        for v in cr["matrix"]["planned_videos"]:
            print(f"  video to render (otto_motion): {v['id']} kit {v['kit']} data {v['data']}")
        for v in cr["matrix"]["planned_creators"]:
            print(f"  creator video, waiting for footage: {v['id']} — {v['reason']}")
        for v in cr["matrix"]["scripted_videos"]:
            print(f"  video scripted, waiting for motion's kit JSON: {v['id']} kit {v['kit']} → {v['data']}")
        for v in cr["matrix"]["held"]:
            print(f"  on hold (never launched): {v['id']} — {v['reason']}")
        return 0
    print(matrix_cli.__doc__)
    return 1


if __name__ == "__main__":
    main()
