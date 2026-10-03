#!/usr/bin/env python3
"""Otto's premium top-layer ads (3 Oct 2026): 6 concepts x (1:1, 9:16) x (NL, IE) → creatives/<market>/premium/.

  python3 premium-src/build_premium.py [concept …]     # from launch/2026-10/: re-set the type on the saved backgrounds

bg/<concept>-<1x1|9x16>.jpg are the finished backgrounds WITHOUT text: Higgsfield gpt-image-2 scenes generated with a
chroma-key screen / price tag, Otto's real app screens (brands/otto/assets/otto-phone-*-cutout.png and
approved-reel-cutout.png, a Review screen with "Approved · posted") warped in with a perspective homography (comp.py),
the showcase ads laid as printed cards (cards.py). Every word is set here (layout.py: Inter Tight 800 headline, Mona Sans,
Otto's logo SVG) and shot by headless Chrome, so spelling is exact. Copy edits: change COPY, re-run, then
`render.py premium`, `render.py compliance` (the matrix cells' "data" must carry the same words) and `build.py`."""
import json, sys
from pathlib import Path
from PIL import Image

import layout as L

HERE = Path(__file__).resolve().parent
BG = HERE / "bg"
OUT = Path(__import__("tempfile").mkdtemp(prefix="otto-premium-"))   # PNG renders; the JPEGs go to KIT
KIT = HERE.parent / "creatives"
LIGHT = "#8FA4FF"                     # accent on dark photos (the landing's dark-mode cobalt, a touch lighter)
NB = " "


def sz(img_path, W, H, out):
    """Scene → exactly W x H (centre crop to the ratio, then resize)."""
    im = Image.open(img_path).convert("RGB")
    r = W / H
    if abs(im.width / im.height - r) > 1e-3:
        if im.width / im.height > r:
            w = round(im.height * r); x = (im.width - w) // 2
            im = im.crop((x, 0, x + w, im.height))
        else:
            h = round(im.width / r); y = (im.height - h) // 2
            im = im.crop((0, y, im.width, y + h))
    im.resize((W, H), Image.LANCZOS).save(out)
    return out


FINE = f"7 days free, no card. Then €79{NB}a{NB}month."

# copy per concept (the texts the compliance check reads; IE differs only where noted)
COPY = {
    "automate": dict(kicker="Marketing by Otto", h1=["Automate", "your", "marketing."], accent=["marketing."],
                     sub="Posts, reels, stories and ads, made for you. You approve with one tap.",
                     cta="Try 7 days free", fine=FINE),
    "agency": dict(h1=["Stop paying", "agency prices."], accent=["agency prices."],
                   sub=f"Otto does your posts and ads for €79{NB}a{NB}month.",
                   cta="Try 7 days free",
                   left_label="Social media agency", left_fig={"nl": f"€500–1,500 a{NB}month", "ie": f"€1,000+ a{NB}month"},
                   left_note={"nl": "just for posts", "ie": "for posts and ads"},
                   tag="€79 a month", tag_note="posts, reels, stories and ads",
                   fine="Agency prices: public 2026 price lists, NL/IE. Prices excl. VAT."),
    "report": dict(kicker="Your daily ads report", h1={"nl": ["07:35.", "Your ads,", "reported."], "ie": ["7:35.", "Your ads,", "reported."]},
                   accent={"nl": ["07:35."], "ie": ["7:35."]},
                   sub="Spend, clicks, enquiries. Every morning.", cta="Try 7 days free", fine=FINE, chip="Sample report"),
    "ads": dict(h1=["Ads that stop", "the scroll.", "Made for you."], accent=["Made for you."],
                sub="Feed and story ads in your brand. You approve every one before it runs.",
                cta="Try 7 days free", chip="Sample ads for demo brands", fine=FINE),
    "posts": dict(kicker="Posts, reels and stories", h1=["You run the", "business.", "Otto posts."], accent=["Otto posts."],
                  sub="Every week, planned and made for you. One tap to approve.", cta="Try 7 days free", fine=FINE),
    "launch": dict(kicker="New business?", h1=["Launching?", "Marketing’s", "handled."], accent=["Marketing’s", "handled."],
                   sub=f"7 days free. No card. Then €79{NB}a{NB}month. Cancel anytime.",
                   cta="Try 7 days free", fine="Monthly plan, no contract. Prices excl. VAT."),
}


def mk_val(v, mk):
    return v[mk] if isinstance(v, dict) else v


def h1_html(lines, accent, accent_color, br_join=True):
    out = []
    for ln in lines:
        e = L.esc(ln)
        out.append(f'<em style="color:{accent_color}">{e}</em>' if ln in accent else e)
    return "<br>".join(out)


def texts(concept, mk):
    """Every word on the image, for the matrix cell (compliance reads these)."""
    c = COPY[concept]
    t = {"headline": " ".join(mk_val(c["h1"], mk)), "sub": c["sub"].replace(NB, " "), "cta": c["cta"],
         "fine": c["fine"].replace(NB, " ")}
    if c.get("kicker"):
        t["kicker"] = c["kicker"]
    if concept == "agency":
        t.update({"left_label": c["left_label"], "left_figure": mk_val(c["left_fig"], mk).replace(NB, " "),
                  "left_note": mk_val(c["left_note"], mk), "tag": c["tag"], "tag_note": c["tag_note"]})
    if c.get("chip"):
        t["tag"] = c["chip"]
    return t


# ---------------------------------------------------------------- per concept layouts

def ad(concept, ratio, mk):
    W, H = (1080, 1080) if ratio == "1x1" else (1080, 1920)
    sq = ratio == "1x1"
    c = COPY[concept]
    lines, acc = mk_val(c["h1"], mk), mk_val(c.get("accent", []), mk)
    scene = BG / f"{concept}-{ratio}.jpg"
    bg = sz(scene, W, H, OUT / f"_bg-{concept}-{ratio}.png")
    blk = dict(kicker=c.get("kicker"), sub=c["sub"], cta=c["cta"], fine=c.get("fine"), kick_color="#C9D3FF")
    layers, extra, logo = "", "", ("white", 64, 64, 40) if sq else ("white", 72, 300, 44)
    if concept == "automate":
        if sq:
            layers = '<div class="layer" style="background:linear-gradient(90deg,rgba(18,12,6,.84) 0%,rgba(18,12,6,.58) 40%,rgba(18,12,6,0) 63%)"></div>'
            blk.update(x=64, y=236, w=540, h1_size=92, sub_size=30, sub_w=470, cta_size=30, fine_size=20)
        else:
            layers = ('<div class="layer" style="background:linear-gradient(180deg,rgba(18,12,6,.80) 0%,rgba(18,12,6,.66) 34%,'
                      'rgba(18,12,6,.10) 56%,rgba(18,12,6,0) 70%)"></div>')
            logo = ("white", 72, 300, 44)
            blk.update(x=72, y=392, w=880, h1_size=124, sub_size=36, sub_w=760, cta_size=33, fine_size=23, gap=28)
            lines = ["Automate your", "marketing."]
    elif concept == "agency":
        fig, note = mk_val(c["left_fig"], mk), mk_val(c["left_note"], mk)
        blk.update(kicker=None, cta_bg="#fff", cta_fg=L.COBALT, sub_color="#E3E9FF")
        def callout(x, y, fs, line_to):
            return (f'<div style="position:absolute;left:{x}px;top:{y}px;color:#fff;width:{round(fs * 11)}px">'
                    f'<div style="position:absolute;left:{line_to - x}px;top:{round(fs * .24)}px;width:{x - line_to - 14}px;height:2px;background:rgba(255,255,255,.8)"></div>'
                    f'<div style="position:absolute;left:{line_to - x - 5}px;top:{round(fs * .24) - 5}px;width:12px;height:12px;border-radius:50%;background:#fff"></div>'
                    f'<div style="font:700 {round(fs * .42)}px/1 Mona;letter-spacing:.16em;text-transform:uppercase;opacity:.86">{L.esc(c["left_label"])}</div>'
                    f'<div style="font:800 {fs}px/1.02 Tight;letter-spacing:-.03em;margin-top:{round(fs * .28)}px;white-space:nowrap">{fig}</div>'
                    f'<div style="font:500 {round(fs * .55)}px/1.2 Mona;margin-top:{round(fs * .18)}px;opacity:.9">{L.esc(note)}</div></div>')
        if sq:
            blk.update(x=64, y=122, w=900, h1_size=96, sub=None, cta=None, fine=None)
            extra = (callout(650, 380, 36, 560)
                     + f'<div class="blk" style="left:650px;top:556px"><span class="cta" style="font-size:28px;padding:20px 32px;background:#fff;color:{L.COBALT}">{L.esc(c["cta"])}{L.ARROW}</span></div>'
                     + f'<div class="note" style="left:64px;top:1030px;color:rgba(16,24,43,.68);font-size:17px">{L.esc(c["fine"])}</div>')
        else:
            blk.update(x=72, y=392, w=940, h1_size=128, sub_size=38, sub_w=900, cta_size=33, gap=26, cta_gap=34,
                       fine=c["fine"], fine_size=21, fine_color="#fff", fine_op=.78, fine_gap=26)
            extra = callout(652, 1004, 38, 598)
        blk["h1"] = h1_html(lines, [], "#fff")
    elif concept == "report":
        if sq:
            layers = ('<div class="layer" style="background:linear-gradient(180deg,rgba(26,16,8,.78) 0%,rgba(26,16,8,.55) 42%,'
                      'rgba(26,16,8,.28) 72%,rgba(26,16,8,0) 84%)"></div>')
            blk.update(x=64, y=150, w=640, h1_size=104, sub_size=32, sub_w=560, cta_size=30, fine_size=20)
            extra = (f'<div class="chip" style="left:470px;top:968px;background:rgba(255,255,255,.95);color:{L.INK}">'
                     f'<span style="width:9px;height:9px;border-radius:50%;background:{L.COBALT}"></span>{L.esc(c["chip"])}</div>')
        else:
            layers = ('<div class="layer" style="background:linear-gradient(180deg,rgba(26,16,8,.80) 0%,rgba(26,16,8,.62) 40%,'
                      'rgba(26,16,8,0) 60%)"></div>')
            blk.update(x=72, y=392, w=900, h1_size=132, sub_size=38, sub_w=800, cta_size=33, fine_size=23, gap=28)
            extra = (f'<div class="chip" style="left:236px;top:1362px;background:rgba(255,255,255,.95);color:{L.INK};font-size:22px;'
                     f'padding:12px 18px"><span style="width:10px;height:10px;border-radius:50%;background:{L.COBALT}"></span>'
                     f'{L.esc(c["chip"])}</div>')
    elif concept == "ads":
        blk.update(cta_bg="#fff", cta_fg=L.COBALT, sub_color="#E3E9FF", kicker=None)
        layers = '<div class="layer" style="background:linear-gradient(180deg,rgba(8,18,90,.35) 0%,rgba(8,18,90,0) 45%)"></div>'
        if sq:
            blk.update(x=64, y=134, w=900, h1_size=84, sub_size=28, sub_w=640, cta_size=27, fine=None, gap=18, cta_gap=22)
            lines = ["Ads that stop the scroll.", "Made for you."]
            extra = f'<div class="chip" style="right:56px;top:66px;background:rgba(255,255,255,.94);color:{L.INK}">{L.esc(c["chip"])}</div>'
        else:
            blk.update(x=72, y=392, w=940, h1_size=118, sub_size=36, sub_w=860, cta_size=33, fine=None, gap=26, cta_gap=30)
            extra = (f'<div class="chip" style="left:72px;top:1478px;background:rgba(255,255,255,.94);color:{L.INK};font-size:24px;'
                     f'padding:13px 20px">{L.esc(c["chip"])}</div>')
    elif concept == "posts":
        if sq:
            layers = '<div class="layer" style="background:linear-gradient(90deg,rgba(14,12,10,.84) 0%,rgba(14,12,10,.6) 42%,rgba(14,12,10,0) 66%)"></div>'
            blk.update(x=64, y=232, w=600, h1_size=100, sub_size=31, sub_w=520, cta_size=30, fine_size=20)
        else:
            layers = ('<div class="layer" style="background:linear-gradient(180deg,rgba(14,12,10,.82) 0%,rgba(14,12,10,.66) 38%,'
                      'rgba(14,12,10,.1) 56%,rgba(14,12,10,0) 66%)"></div>')
            blk.update(x=72, y=392, w=900, h1_size=124, sub_size=36, sub_w=800, cta_size=33, fine_size=23, gap=28)
            lines = ["You run the", "business.", "Otto posts."]
    elif concept == "launch":
        if sq:
            layers = '<div class="layer" style="background:linear-gradient(90deg,rgba(12,22,18,.80) 0%,rgba(12,22,18,.55) 46%,rgba(12,22,18,0) 66%)"></div>'
            blk.update(x=64, y=236, w=600, h1_size=90, sub_size=30, sub_w=520, cta_size=30, fine_size=20)
        else:
            layers = ('<div class="layer" style="background:linear-gradient(180deg,rgba(12,22,18,.80) 0%,rgba(12,22,18,.64) 38%,'
                      'rgba(12,22,18,.08) 56%,rgba(12,22,18,0) 64%)"></div>')
            layers += ('<div class="layer" style="background:radial-gradient(ellipse 620px 420px at 0% 76%,rgba(12,22,18,.82) 0%,'
                       'rgba(12,22,18,.5) 55%,rgba(12,22,18,0) 100%)"></div>')
            blk.update(x=72, y=392, w=900, h1_size=112, sub_size=35, sub_w=860, cta_size=29, gap=26, cta_gap=28,
                       cta="Try 7 days free", fine=None)
            extra = (f'<div class="note" style="left:72px;top:1462px;width:290px;color:#fff;opacity:.88;font-size:20px">'
                     f'{L.esc(c["fine"])}</div>')
    if "h1" not in blk:
        blk["h1"] = h1_html(lines, acc, LIGHT)
    if not sq:
        logo = ("white", 72, 296, 44)
    htm = L.page(W, H, bg, layers, logo=logo, block=blk, extra=extra)
    out = OUT / mk / f"{concept}-{ratio}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    L.shoot(htm, out, (W, H))
    return out


if __name__ == "__main__":
    only = sys.argv[1:]
    for mk in ("nl", "ie"):
        for concept in COPY:
            if only and concept not in only:
                continue
            for ratio in ("1x1", "9x16"):
                print(ad(concept, ratio, mk))
    sys.path.insert(0, str(L.REPO / "platform"))
    import otto_provenance as prov                       # noqa: E402
    for mk in ("nl", "ie"):
        for f in sorted((OUT / mk).glob("*.png")):
            dst = KIT / mk / "premium" / (f.stem + ".jpg")
            dst.parent.mkdir(parents=True, exist_ok=True)
            Image.open(f).convert("RGB").save(dst, quality=92, optimize=True, progressive=True)
            prov.mark_safely(dst, ("image",), "Higgsfield gpt-image-2 scene + Otto UI + set type", composite=True)
            print("wrote", dst.relative_to(L.REPO))
    (HERE / "texts.json").write_text(json.dumps({mk: {k: texts(k, mk) for k in COPY} for mk in ("nl", "ie")}, ensure_ascii=False, indent=1))
