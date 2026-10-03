"""Type layer for Otto's premium ads: every word is set here (HTML + headless Chrome via otto_render.screenshot), never by
the image model. Inter Tight 800 (Otto's motion kit) for the condensed headline, Mona Sans (the landing's font) for the rest,
Otto's real logo SVG."""
import base64, html, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "platform"))
import otto_render  # noqa: E402

COBALT, COBALT_DARK_UI = "#2447F0", "#6E88FF"
INK = "#10182B"


def _b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()


FONTS = (f"@font-face{{font-family:Mona;src:url(data:font/woff2;base64,{_b64(REPO / 'brands/otto/assets/mona-sans-latin.woff2')}) "
         f"format('woff2');font-weight:200 900}}"
         f"@font-face{{font-family:Tight;src:url(data:font/woff2;base64,{_b64(REPO / 'motion/otto-kit/fonts/InterTight-var-latin.woff2')}) "
         f"format('woff2');font-weight:100 900}}")
LOGO = {"white": (REPO / "brands/otto/logo-white.svg").read_text(), "color": (REPO / "brands/otto/logo.svg").read_text()}

BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{overflow:hidden;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
body{position:relative;font-family:Mona,sans-serif;color:#fff}
.bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.layer{position:absolute;inset:0}
.logo{position:absolute}
.logo svg{display:block;width:auto;height:100%}
.blk{position:absolute}
.kick{font:700 20px/1 Mona;letter-spacing:.18em;text-transform:uppercase;margin-bottom:22px;display:flex;align-items:center;gap:14px}
.kick i{display:block;width:34px;height:3px;background:currentColor;border-radius:2px}
h1{font-family:Tight,sans-serif;font-weight:800;letter-spacing:-.038em;line-height:.93;text-wrap:balance}
h1 em{font-style:normal}
.sub{font-weight:500;letter-spacing:-.008em;line-height:1.28;text-wrap:pretty}
.cta{display:inline-flex;align-items:center;gap:14px;border-radius:999px;font-weight:700;letter-spacing:-.005em;white-space:nowrap;
  box-shadow:0 18px 40px -18px rgba(10,20,80,.65)}
.cta svg{width:.9em;height:.9em}
.fine{font-weight:450;letter-spacing:.005em;line-height:1.35}
.chip{position:absolute;display:inline-flex;align-items:center;gap:10px;border-radius:999px;font:650 20px/1 Mona;padding:11px 16px;
  white-space:nowrap}
.note{position:absolute;font:500 18px/1.35 Mona;letter-spacing:.005em}
"""
ARROW = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" '
         'stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>')


def esc(s):
    return html.escape(s, quote=False)


def page(W, H, bg, layers="", logo=None, block=None, extra=""):
    """logo = (variant, x, y, height); block = dict(x, y, w, kicker, h1 (html allowed), h1_size, sub, sub_size, cta, cta_size,
    fine, fine_size, color, sub_color, accent, gap)."""
    parts = [f'<img class="bg" src="{Path(bg).resolve().as_uri()}">', layers]
    if logo:
        v, x, y, h = logo
        parts.append(f'<div class="logo" style="left:{x}px;top:{y}px;height:{h}px">{LOGO[v]}</div>')
    if block:
        b = block
        col, scol = b.get("color", "#fff"), b.get("sub_color", b.get("color", "#fff"))
        inner = []
        if b.get("kicker"):
            inner.append(f'<div class="kick" style="color:{b.get("kick_color", col)}"><i></i>{esc(b["kicker"])}</div>')
        inner.append(f'<h1 style="font-size:{b["h1_size"]}px;color:{col}">{b["h1"]}</h1>')
        if b.get("sub"):
            inner.append(f'<p class="sub" style="font-size:{b["sub_size"]}px;color:{scol};margin-top:{b.get("gap", 26)}px;'
                         f'max-width:{b.get("sub_w", b["w"])}px">{b["sub"]}</p>')
        tail = []
        if b.get("cta"):
            cs = b.get("cta_size", 30)
            tail.append(f'<div style="margin-top:{0 if b.get("cta_xy") else b.get("cta_gap", 34)}px"><span class="cta" style="font-size:{cs}px;'
                        f'padding:{round(cs * .72)}px {round(cs * 1.15)}px;background:{b.get("cta_bg", COBALT)};'
                        f'color:{b.get("cta_fg", "#fff")}">{esc(b["cta"])}{ARROW}</span></div>')
        if b.get("fine"):
            tail.append(f'<p class="fine" style="font-size:{b.get("fine_size", 20)}px;color:{b.get("fine_color", scol)};'
                        f'margin-top:{b.get("fine_gap", 20)}px;opacity:{b.get("fine_op", .86)};max-width:{b.get("fine_w", b["w"])}px">{b["fine"]}</p>')
        if b.get("cta_xy"):
            x, y = b["cta_xy"]
            parts.append(f'<div class="blk" style="left:{b["x"]}px;top:{b["y"]}px;width:{b["w"]}px">{"".join(inner)}</div>')
            parts.append(f'<div class="blk" style="left:{x}px;top:{y}px">{"".join(tail)}</div>')
        else:
            parts.append(f'<div class="blk" style="left:{b["x"]}px;top:{b["y"]}px;width:{b["w"]}px">{"".join(inner + tail)}</div>')
    parts.append(extra)
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{FONTS}{BASE_CSS}</style></head>'
            f'<body style="width:{W}px;height:{H}px">{"".join(parts)}</body></html>')


def shoot(htm, out, size):
    otto_render.screenshot(htm, str(out), size, budget=3000)
    return out
