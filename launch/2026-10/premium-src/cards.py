"""Showcase ads (sample ads for fictional demo brands) laid on the cobalt surface as printed cards with real shadows."""
from PIL import Image, ImageDraw, ImageFilter
SHOW = "/Users/maxsalkov/otto/brands/otto/assets/showcase/"


def card(name, w, radius=0.035):
    im = Image.open(SHOW + name).convert("RGB").resize((w, w), Image.LANCZOS)
    b = max(6, round(w * 0.022))                         # a thin white print border
    c = Image.new("RGBA", (w + 2 * b, w + 2 * b), (255, 255, 255, 255))
    c.paste(im, (b, b))
    mask = Image.new("L", c.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, c.width - 1, c.height - 1), radius=round(w * radius), fill=255)
    c.putalpha(mask)
    return c


def place(canvas, crd, cx, cy, rot, lift=1.0):
    """Rotate a card, drop a two-layer shadow (contact + soft), paste centred at (cx, cy)."""
    r = crd.rotate(rot, Image.BICUBIC, expand=True)
    a = r.getchannel("A")
    for off, blur, op in ((round(10 * lift), round(26 * lift), 0.42), (round(3 * lift), round(5 * lift), 0.30)):
        sh = Image.new("RGBA", r.size, (5, 12, 60, 0))
        sh.putalpha(a.point(lambda v: int(v * op)))
        pad = blur * 3
        big = Image.new("RGBA", (r.width + 2 * pad, r.height + 2 * pad), (0, 0, 0, 0))
        big.paste(sh, (pad, pad))
        big = big.filter(ImageFilter.GaussianBlur(blur))
        canvas.alpha_composite(big, (int(cx - r.width / 2 - pad + off * 0.6), int(cy - r.height / 2 - pad + off)))
    canvas.alpha_composite(r, (int(cx - r.width / 2), int(cy - r.height / 2)))
    return canvas


def fan(bg, layout):
    """layout = [(file, width, cx, cy, rot)] back to front."""
    cv = bg.convert("RGBA")
    for f, w, cx, cy, rot in layout:
        place(cv, card(f, w), cx, cy, rot)
    return cv.convert("RGB")
