#!/usr/bin/env python3
"""Otto creative — ad variants in every style, built from the angles that work in the category.

  otto_creative.py variants <campaign-id> [--dry]            # angles × formats → campaign.creatives (statics with copy, carousels, video)
  otto_creative.py overlay <src.jpg> <dst.jpg> "<text>" [--color #2447F0] [--pos bottom|center]
  otto_creative.py angles <brand>                            # print the angle bank Otto would use

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
from pathlib import Path

import ap
import otto_paths as paths

try:
    import otto_render                    # studio templates via headless Chrome
except Exception:
    otto_render = None

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


def render_card(template, data, src, dst, text, color, bid, **overlay_kw):
    """otto_render template; the ffmpeg band when no headless Chrome (or OTTO_RENDERER=ffmpeg)."""
    if otto_render is not None and os.environ.get("OTTO_RENDERER", "html") != "ffmpeg":
        try:
            return otto_render.render(template, dict(data, photo=str(src)), dst, brand=bid)
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

def build(d, c, dry=False, base="https://dash.monyflow.work/otto/"):
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
    OUT.mkdir(parents=True, exist_ok=True)
    cta_card = cta_card_text(b)
    for i, a in enumerate(angles, 1):
        hook = trim(a["angle"], 40)
        body = trim(a["angle"], 90) + (f" {proof}" if proof else "") + f" — {b['name']}."
        cr["angles"].append({"n": i, "angle": a["angle"], "source": a.get("source")})
        cr["titles"].append(hook)
        cr["bodies"].append(trim(body, 125))
        img_post = ap.post(d, a.get("post") or "") or src_post
        if img_post and img_post.get("image"):
            dst = OUT / f"{c['id']}-{i}-static.jpg"
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
                         ("carousel_inner", {"title": trim(proof or a["angle"], 140)}),
                         ("carousel_cta", {"headline": hook, "cta": cta_card})]
            for j, txt in enumerate([hook, trim(proof or a["angle"], 40), cta_card], 1):
                ip = posts[(i + j) % len(posts)] if posts else img_post
                dst = OUT / f"{c['id']}-{i}-c{j}.jpg"
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
    cr["descriptions"] = [trim(proof, 30)] if proof else []
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
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
