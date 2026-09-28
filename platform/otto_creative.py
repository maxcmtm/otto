#!/usr/bin/env python3
"""Otto creative — ad variants in every style, built from the angles that work in the category.

  otto_creative.py variants <campaign-id> [--dry]            # angles × formats → campaign.creatives (statics with copy, carousels, video)
  otto_creative.py overlay <src.png> <dst.png> "<text>" [--color #2447F0] [--pos bottom|center]
  otto_creative.py angles <brand>                            # print the angle bank Otto would use

Angle bank, in order of trust: brands/<slug>/angles.json (written by otto_competitors.py from the
ad-library sweep: longevity winners = proven), the profile's "Winning angles" section, then the
brand's best hooks. Every variant = one angle, one hook, one proof line, one CTA — and the copy is
tested by Meta's dynamic creative (otto_ads.py launches all titles/bodies/images in one ad set).
Text on image is rendered by ffmpeg (deterministic typography, brand band), never by the image model.
"""
import json, os, re, shutil, subprocess, sys, tempfile, textwrap
from pathlib import Path

import ap

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
OUT = HERE / "assets" / "ads"
FONT_CANDIDATES = [os.environ.get("OTTO_FONT", ""), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"]
CTA = {"leads": "SIGN_UP", "traffic": "LEARN_MORE", "sales": "SHOP_NOW", "engagement": "LEARN_MORE", "awareness": "LEARN_MORE"}


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
    """ffmpeg's drawtext has no bidi shaping: for RTL lines, reverse token order and RTL runs so the
    rendered glyphs read correctly (digits and Latin tokens stay as they are)."""
    if not RTL.search(line):
        return line
    toks = line.split(" ")[::-1]
    return " ".join(t[::-1] if RTL.search(t) else t for t in toks)


def prep_lines(text, width=22, max_lines=4):
    return [bidi_line(l) for l in textwrap.wrap(clean_text(text), width)[:max_lines]]


def text_color_for(band_hex):
    """White on dark bands, near-black on light ones (WCAG-ish luminance split)."""
    h = band_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "0x1D1D1F" if lum > 0.62 else "white"


def overlay_text(src, dst, text, color="#2447F0", pos="bottom", size=None):
    """Brand band + headline on an image. Returns dst path; raises if ffmpeg/font missing."""
    fp, ff = font_path(), ffmpeg()
    if not ff or not fp:
        raise RuntimeError("ffmpeg or a TTF font is missing (set OTTO_FONT)")
    lines = prep_lines(text, 22)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(lines)); tfile = tf.name
    size = size or (64 if len(lines) <= 2 else 56)
    band_h = size * len(lines) + 120
    color = color if hex_ok(color) else "#2447F0"
    fc = text_color_for(color)
    y = f"h-{band_h}+60" if pos == "bottom" else "(h-text_h)/2"
    x = "w-tw-60" if RTL.search(text or "") else "60"          # right-align right-to-left copy
    band = f"drawbox=x=0:y=ih-{band_h}:w=iw:h={band_h}:color={color}@0.92:t=fill," if pos == "bottom" else f"drawbox=x=0:y=0:w=iw:h=ih:color={color}@0.55:t=fill,"
    vf = (band + f"drawtext=fontfile='{fp}':textfile='{tfile}':fontcolor={fc}:fontsize={size}:line_spacing=10:x={x}:y={y}")
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, str(dst)], capture_output=True, text=True)
    os.unlink(tfile)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return str(dst)


# ---------------- angle bank ----------------

def profile_angles(bid):
    prof = BRANDS / bid / "brand-profile.md"
    if not prof.exists():
        return []
    t = prof.read_text()
    m = re.search(r"Winning angles.*?\n(.*?)(?=\n## |\Z)", t, re.S)
    out = []
    if m:
        for ln in m.group(1).splitlines():
            ln = clean_text(ln.strip().lstrip("-*0123456789. "))
            if 8 < len(ln) < 160 and "(?)" not in ln and "agent" not in ln.lower():
                out.append({"angle": ln, "source": "profile"})
    return out[:5]


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
    for i, a in enumerate(angles, 1):
        hook = trim(a["angle"], 40)
        body = trim(a["angle"], 90) + (f" {proof}" if proof else "") + f" — {b['name']}."
        cr["angles"].append({"n": i, "angle": a["angle"], "source": a.get("source")})
        cr["titles"].append(hook)
        cr["bodies"].append(trim(body, 125))
        img_post = ap.post(d, a.get("post") or "") or src_post
        if img_post and img_post.get("image"):
            src = HERE / img_post["image"]
            dst = OUT / f"{c['id']}-{i}-static.png"
            if dry:
                cr["images"].append({"file": f"assets/ads/{dst.name}", "from": img_post["id"], "text": hook, "planned": True})
            else:
                try:
                    overlay_text(src, dst, hook, pal)
                    cr["images"].append({"file": f"assets/ads/{dst.name}", "from": img_post["id"], "text": hook})
                except Exception as e:
                    cr["images"].append({"file": img_post["image"], "from": img_post["id"], "text": None, "note": str(e)[:120]})
            # carousel: hook / proof / cta on three images (rotating through the brand's visuals)
            cards = []
            for j, txt in enumerate([hook, trim(proof or a["angle"], 40), f"{b['name']}: talk to us"], 1):
                ip = posts[(i + j) % len(posts)] if posts else img_post
                dst = OUT / f"{c['id']}-{i}-c{j}.png"
                if dry:
                    cards.append({"file": f"assets/ads/{dst.name}", "text": txt, "planned": True})
                else:
                    try:
                        overlay_text(HERE / ip["image"], dst, txt, pal, pos="bottom", size=52)
                        cards.append({"file": f"assets/ads/{dst.name}", "text": txt})
                    except Exception as e:
                        cards.append({"file": ip["image"], "text": txt, "note": str(e)[:80]})
            cr["carousels"].append({"angle": i, "cards": cards})
        reel = HERE / "assets" / "reels" / f"{(img_post or {}).get('id', '')}.mp4"
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
        cr = build(d, c, dry="--dry" in a)
        if "--dry" not in a:
            ap.save(d)
        print(json.dumps({k: cr[k] for k in ("angles", "titles", "bodies", "cta")}, ensure_ascii=False, indent=1))
        print(f"images {len(cr['images'])} · carousels {len(cr['carousels'])} · videos {len(cr['videos'])}{' (dry)' if cr['dry'] else ''}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
