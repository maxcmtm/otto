#!/usr/bin/env python3
"""Otto launch kit, October 2026 — the phone cut-outs and sample-post images the new concepts need.

  python3 phones.py            # writes the assets the matrices use into brands/otto/assets/ (+ sheets/phones.jpg)
  python3 phones.py --only report_ads,week,campaign,ads,fan
  python3 phones.py --all      # also the unused extras (other sample-post phones, the showcase grid, more ad samples)

Same look as the existing cut-outs (otto-phone-*-cutout.png: a 900x1848 transparent canvas, the phone body at x 60-840,
y 112-1736, Otto's app screen in its own tokens), shot by headless Chrome through platform/otto_render.screenshot (read
only). Every post on a phone is a SAMPLE and says so ("Sample post" / "Sample"); no person, no customer name, no review
text is invented (the review post shows its quote as placeholder lines: Otto makes it from the client's real reviews).

Writes (brands/otto/assets/):
  otto-phone-report-ads-cutout.png     the 07:35 ads report: spent, clicks, enquiries (Sample), pause / approve
  otto-phone-week-cutout.png           "This week": six post types ready to approve (Sample)
  otto-phone-post-<type>-cutout.png    one sample post in Otto's Review screen: carousel, reel, story, opening (--all:
                                       offer, howto, review too)
  otto-phones-post-types-cutout.png    three of them fanned (reel · carousel · story): the gallery hero
  otto-post-<type>-sample.png          the post itself (1080x1080, "Sample post" corner label) for chat attachments
  otto-phone-campaign-cutout.png       the campaign Otto runs: one campaign, an ad set per angle, yesterday's totals (Sample)
  otto-phone-ads-cutout.png            "New ads": four sample ads for demo brands (assets/showcase/), ready to approve
  otto-ads-grid-sample.png             the same four ads as a clean 2x2 grid, captioned "Sample ads for demo brands"
  otto-ad-<n>-sample.png               one showcase ad with a "Sample ad · demo brand" corner label (chat attachments)
  otto-phone-story-ad-cutout.png       one showcase ad's 9:16 version playing as a story (generic story UI, "Sample ad")
  otto-phones-ads-duo-cutout.png       the ads phone and the story-ad phone together (feed ads + story ads)
The showcase ads are fictional demo brands made by another pass (assets/showcase/BRANDS.md); the picks below leave out
every image with people or hands and every discount code.
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = REPO / "brands" / "otto" / "assets"
FONT = REPO / "motion" / "otto-kit" / "fonts" / "Inter-var-latin.woff2"
sys.path.insert(0, str(REPO / "platform"))
import otto_render  # noqa: E402  (used read-only: headless Chrome screenshot)

CSS = """
@font-face{font-family:'UI';src:url('%(font)s') format('woff2');font-weight:100 900}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;overflow:hidden;font-family:UI,-apple-system,sans-serif;color:#10182B;-webkit-font-smoothing:antialiased}
.phone{position:absolute;left:60px;top:112px;width:780px;height:1624px;border-radius:124px;background:#0B0D12;
  box-shadow:inset 0 0 0 3px #2A2F3A}
.screen{position:absolute;left:24px;top:24px;right:24px;bottom:24px;border-radius:100px;background:#F5F7FB;overflow:hidden}
.time{position:absolute;top:50px;left:68px;font:650 30px/1 UI;letter-spacing:-.01em}
.island{position:absolute;top:22px;left:50%%;margin-left:-108px;width:216px;height:64px;border-radius:32px;background:#0B0D12}
.batt{position:absolute;top:52px;right:62px;width:48px;height:24px;border:3px solid #10182B;border-radius:7px}
.batt::after{content:'';position:absolute;left:3px;top:3px;bottom:3px;right:8px;background:#10182B;border-radius:3px}
.content{position:absolute;top:134px;left:44px;right:44px}
.brand{display:flex;align-items:center;gap:16px;font:600 31px/1 UI;color:#5B6478}
.logo{width:36px;height:36px;border-radius:9px;background:#2447F0;position:relative;flex:none}
.logo::after{content:'';position:absolute;left:9px;top:9px;right:9px;bottom:9px;border:3.5px solid #fff;border-radius:5px}
h1{font:750 62px/1.04 UI;letter-spacing:-.04em;margin:36px 0 12px}
.sub{font:400 28px/1.3 UI;color:#5B6478}
.sub b{color:#2447F0;font-weight:700}
.card{position:relative;margin:44px -12px 0;background:#fff;border-radius:40px;padding:32px;
  box-shadow:0 0 0 2px rgba(16,24,43,.06),0 24px 44px -26px rgba(16,24,43,.3)}
.chip{background:#EEF1F6;color:#5B6478;font:650 22px/1 UI;padding:11px 15px;border-radius:12px;white-space:nowrap}
.btns{display:flex;gap:20px;margin-top:30px}
.btn{flex:1;height:88px;border-radius:44px;display:flex;align-items:center;justify-content:center;font:700 30px/1 UI;
  letter-spacing:-.01em;white-space:nowrap}
.btn.sec{background:#EEF1F6;color:#10182B;flex:0 0 236px}
.btn.pri{background:#2447F0;color:#fff}
.tabs{position:absolute;left:0;right:0;bottom:0;height:168px;background:#fff;border-top:2px solid #EBEEF3;display:flex;
  justify-content:space-around;padding:24px 30px 0}
.tab{display:flex;flex-direction:column;align-items:center;gap:12px;font:400 22px/1 UI;color:#7A8295;width:130px}
.tab i{display:block;width:50px;height:50px;border:3.5px solid #7A8295;border-radius:12px}
.tab.on{color:#2447F0}.tab.on i{border-color:#2447F0}
/* post card */
.acct{display:flex;align-items:center;gap:20px}
.av{width:68px;height:68px;border-radius:50%%;background:#EDF1FF;color:#2447F0;font:700 30px/68px UI;text-align:center;flex:none}
.who{flex:1;min-width:0}
.who b{display:block;font:700 30px/1.15 UI;letter-spacing:-.01em}
.who span{display:block;font:400 25px/1.3 UI;color:#7A8295;margin-top:4px}
.media{position:relative;margin-top:26px;border-radius:26px;overflow:hidden}
.cap{margin-top:24px;font:400 28px/1.42 UI;color:#10182B}
.cap b{font-weight:700}
.dots{display:flex;gap:10px;justify-content:center;margin-top:18px}
.dots i{width:12px;height:12px;border-radius:50%%;background:#D5DAE4}.dots i.on{background:#2447F0}
"""

PHONE = """<!doctype html><html><head><meta charset="utf-8"><style>%(css)s%(extra)s</style></head><body style="width:900px;height:1848px">
<div class="phone"><div class="screen">
<div class="island"></div><div class="time">07:35</div><div class="batt"></div>
<div class="content">
 <div class="brand"><div class="logo"></div>Otto</div>
 <h1>%(title)s</h1><div class="sub">%(sub)s</div>
 %(body)s
</div>
<div class="tabs">%(tabs)s</div>
</div></div></body></html>"""


def tabs(on):
    return "".join(f'<div class="tab{" on" if t == on else ""}"><i></i>{t}</div>' for t in ("Today", "Review", "Calendar", "Results"))


# ---------------------------------------------------------------- the sample posts (media blocks)

MEDIA_CSS = """
.m-carousel{background:linear-gradient(140deg,#F4E6D2 0%,#DDB98F 100%)}
.m-carousel .slide{position:absolute;left:0;top:0;bottom:0;right:58px;padding:44px 40px;display:flex;flex-direction:column;justify-content:flex-end;
  background:linear-gradient(150deg,#F7EBDA,#E2C29C)}
.m-carousel .peek{position:absolute;right:0;top:0;bottom:0;width:46px;background:linear-gradient(160deg,#C9D9C2,#93AE8C)}
.m-carousel .k{font:700 22px/1 UI;letter-spacing:.14em;color:#8A5A2B}
.m-carousel .t{font:780 54px/1.02 UI;letter-spacing:-.035em;color:#3A2716;margin-top:16px}
.m-carousel .loaf{position:absolute;left:46px;top:40px;width:250px;height:150px;border-radius:125px 125px 60px 60px;
  background:radial-gradient(ellipse at 40% 30%,#F6D9A8,#C88A45 70%,#9A6230);box-shadow:0 18px 30px -12px rgba(80,45,10,.45)}
.pill{position:absolute;top:24px;right:82px;background:rgba(16,24,43,.72);color:#fff;font:650 22px/1 UI;padding:10px 14px;border-radius:20px}
.m-reel{background:radial-gradient(circle at 30% 28%,#F2B66B 0,#B5652A 22%,rgba(40,24,16,0) 46%),
  radial-gradient(circle at 76% 64%,#E9D3B0 0,#7A5236 20%,rgba(30,20,14,0) 44%),linear-gradient(170deg,#3A2A20,#15110E)}
.m-reel .play{position:absolute;left:50%;top:44%;width:132px;height:132px;margin:-66px 0 0 -66px;border-radius:50%;
  background:rgba(255,255,255,.26);backdrop-filter:blur(6px);box-shadow:inset 0 0 0 3px rgba(255,255,255,.55)}
.m-reel .play::after{content:'';position:absolute;left:52px;top:38px;border-left:44px solid #fff;border-top:28px solid transparent;border-bottom:28px solid transparent}
.m-reel .shade{position:absolute;left:0;right:0;bottom:0;height:46%;background:linear-gradient(to bottom,rgba(0,0,0,0),rgba(0,0,0,.62))}
.m-reel .t{position:absolute;left:36px;right:36px;bottom:40px;font:760 46px/1.06 UI;letter-spacing:-.03em;color:#fff}
.tagl{position:absolute;top:24px;left:24px;background:rgba(255,255,255,.92);color:#10182B;font:700 22px/1 UI;padding:10px 14px;border-radius:20px}
.m-story{background:linear-gradient(165deg,#F6CEDA 0%,#C9B3F2 60%,#9C8BEA 100%)}
.m-story .bars{position:absolute;top:22px;left:22px;right:22px;display:flex;gap:8px}
.m-story .bars i{flex:1;height:6px;border-radius:3px;background:rgba(255,255,255,.5)}.m-story .bars i.on{background:#fff}
.m-story .stk{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-3deg);background:#fff;border-radius:28px;
  padding:30px 36px;box-shadow:0 22px 40px -18px rgba(60,30,90,.45);text-align:center;width:420px}
.m-story .stk b{display:block;font:780 48px/1.04 UI;letter-spacing:-.035em;color:#2B1B45}
.m-story .stk span{display:block;margin-top:12px;font:600 25px/1.2 UI;color:#7A4FD6}
.m-offer{background:linear-gradient(150deg,#FFF0BF 0%,#F7C95A 100%);padding:44px 40px;display:flex;flex-direction:column;justify-content:center}
.m-offer .badge{align-self:flex-start;background:#2B1D05;color:#FFE59A;font:700 23px/1 UI;padding:12px 16px;border-radius:14px;letter-spacing:.02em}
.m-offer .t{font:800 76px/.98 UI;letter-spacing:-.045em;color:#2B1D05;margin-top:26px}
.m-offer .s{font:600 30px/1.2 UI;color:#6B4A0E;margin-top:16px}
.m-offer .cup{position:absolute;right:40px;bottom:36px;width:120px;height:110px;border-radius:0 0 46px 46px;background:#fff;
  box-shadow:0 14px 24px -10px rgba(90,60,0,.4)}
.m-offer .cup::after{content:'';position:absolute;right:-34px;top:20px;width:40px;height:48px;border:10px solid #fff;border-left:none;border-radius:0 26px 26px 0}
.m-howto{background:#E6EDFF;padding:40px 40px}
.m-howto .k{font:700 22px/1 UI;letter-spacing:.14em;color:#2447F0}
.m-howto .t{font:780 46px/1.04 UI;letter-spacing:-.035em;color:#10182B;margin-top:14px}
.m-howto ol{list-style:none;margin-top:26px;display:flex;flex-direction:column;gap:16px}
.m-howto li{display:flex;gap:18px;align-items:center;font:600 28px/1.2 UI;color:#26304A}
.m-howto li i{flex:none;width:50px;height:50px;border-radius:50%;background:#2447F0;color:#fff;font:750 26px/50px UI;text-align:center;font-style:normal}
.m-review{background:#FFFDF8;box-shadow:inset 0 0 0 2px #EFE9DC;padding:40px 44px}
.m-review .q{font:800 150px/.8 Georgia,serif;color:#2447F0;height:90px}
.m-review .ln{height:24px;border-radius:12px;background:#E9E5DA;margin-top:22px}
.m-review .stars{margin-top:30px;display:flex;gap:10px}
.m-review .stars i{width:34px;height:34px;background:#D9D3C4;clip-path:polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)}
.m-review .from{margin-top:26px;font:650 26px/1.2 UI;color:#7A6F55}
.m-opening{background:radial-gradient(circle at 80% 20%,#3C7A5D 0,#1F4D3A 55%,#163A2B 100%);padding:44px 40px;display:flex;flex-direction:column;justify-content:flex-end}
.m-opening .k{font:700 22px/1 UI;letter-spacing:.14em;color:#F3D9A4}
.m-opening .t{font:800 92px/.95 UI;letter-spacing:-.05em;color:#FFF6E4;margin-top:16px}
.m-opening .s{font:600 30px/1.2 UI;color:#F3D9A4;margin-top:18px}
.m-opening .sun{position:absolute;right:44px;top:40px;width:120px;height:120px;border-radius:50%;background:#F3D9A4;opacity:.92}
.samp{position:absolute;top:24px;right:24px;background:rgba(255,255,255,.94);color:#10182B;font:700 24px/1 UI;padding:11px 15px;border-radius:14px;
  box-shadow:0 6px 16px -8px rgba(0,0,0,.3)}
"""

POSTS = {
    # type: (business, network · time, media height in the phone, media html, caption html)
    "carousel": ("Your bakery", "Instagram · Mon 08:00", 470,
                 '<div class="slide"><div class="loaf"></div><div class="k">CAROUSEL</div><div class="t">3 ways to enjoy<br>our sourdough</div></div>'
                 '<div class="peek"></div><div class="pill">1/5</div>',
                 "<b>3 ways to enjoy our sourdough:</b> toasted with butter, in Saturday's soup, or fresh with cheese."),
    "reel": ("Your café", "Instagram · Tue 12:00", 560,
             '<div class="play"></div><div class="shade"></div><div class="tagl">Reel · 0:15</div>'
             '<div class="t">Saturday prep,<br>in 15 seconds</div>',
             "<b>Saturday prep, in 15 seconds.</b> From the first loaf to the last coffee."),
    "story": ("Your salon", "Instagram · Wed 17:00", 560,
              '<div class="bars"><i class="on"></i><i></i><i></i></div><div class="tagl" style="top:44px">Story</div>'
              '<div class="stk"><b>Open late<br>this Friday</b><span>Book a late slot</span></div>',
              "<b>Story:</b> late appointments this Friday. Tap the link to book."),
    "offer": ("Your lunchroom", "Facebook · Thu 11:00", 470,
              '<div class="badge">THIS WEEK</div><div class="t">Lunch<br>+ coffee</div><div class="s">Monday to Wednesday</div><div class="cup"></div>',
              "<b>This week:</b> lunch with a coffee, Monday to Wednesday. See you at the counter."),
    "howto": ("Your heating company", "Facebook · Fri 09:00", 470,
              '<div class="k">HOW-TO</div><div class="t">Bleed a radiator<br>in 3 steps</div><ol><li><i>1</i>Turn the heating off</li>'
              '<li><i>2</i>Open the valve a quarter turn</li><li><i>3</i>Close it when water appears</li></ol>',
              "<b>How-to:</b> three steps to warm radiators before the cold sets in."),
    "review": ("Your shop", "Instagram · Sat 10:00", 470,
               '<div class="q">“</div><div class="ln" style="width:92%"></div><div class="ln" style="width:84%"></div>'
               '<div class="ln" style="width:58%"></div><div class="stars"><i></i><i></i><i></i><i></i><i></i></div>'
               '<div class="from">Made from your real reviews</div>',
               "<b>Review post:</b> the kind words your customers already left, turned into a post."),
    "opening": ("Your café", "Instagram · Sat 09:00", 470,
                '<div class="sun"></div><div class="k">GRAND OPENING</div><div class="t">We’re<br>open!</div><div class="s">From Saturday, 09:00</div>',
                "<b>We're open!</b> Come by from Saturday at 09:00 for the first coffee."),
}
LABEL = {"carousel": "Carousel", "reel": "Reel", "story": "Story", "offer": "Offer", "howto": "How-to", "review": "Review post",
         "opening": "Opening post"}


def post_phone(kind):
    biz, net, mh, media, cap = POSTS[kind]
    body = (f'<div class="card"><div class="acct"><div class="av">{biz.split()[-1][0].upper()}</div><div class="who"><b>{biz}</b>'
            f'<span>{net}</span></div><div class="chip">Sample</div></div>'
            f'<div class="media m-{kind}" style="height:{mh}px">{media}</div>'
            + ('<div class="dots"><i class="on"></i><i></i><i></i><i></i><i></i></div>' if kind == "carousel" else "")
            + f'<div class="cap">{cap}</div>'
            '<div class="btns"><div class="btn sec">Change</div><div class="btn pri">Approve</div></div></div>')
    return PHONE % {"css": CSS % {"font": FONT.as_uri()}, "extra": MEDIA_CSS, "title": "Review",
                    "sub": f'<b>Sample post</b> · {LABEL[kind]}', "body": body, "tabs": tabs("Review")}


def post_square(kind):
    """The post alone, 1080x1080, for a chat attachment."""
    _, _, _, media, _ = POSTS[kind]
    media = media.replace('<div class="pill">1/5</div>', "")      # the corner carries the "Sample post" label instead
    media = media.replace('<div class="sun"></div>', '<div class="sun" style="top:auto;bottom:44px"></div>')
    css = CSS % {"font": FONT.as_uri()} + MEDIA_CSS
    scale = 1080 / 668
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body style="width:1080px;height:1080px">'
            f'<div style="position:absolute;left:0;top:0;width:668px;height:668px;transform:scale({scale});transform-origin:0 0">'
            f'<div class="media m-{kind}" style="margin:0;height:668px;border-radius:0">{media}'
            f'</div></div><div class="samp" style="top:{30}px;right:{30}px;font-size:34px;padding:14px 20px;border-radius:18px">Sample post</div>'
            '</body></html>')


# ---------------------------------------------------------------- the 07:35 ads report

REPORT_CSS = """
.hd{display:flex;align-items:flex-start;justify-content:space-between}
.hd b{display:block;font:700 30px/1.2 UI}.hd span{display:block;font:400 26px/1.3 UI;color:#7A8295;margin-top:4px}
.rule{height:2px;background:#EEF1F6;margin:28px -32px 0}
.mx{display:grid;grid-template-columns:1fr 1fr 1fr;margin:0 -32px}
.mx div{padding:26px 0 22px 32px;border-right:2px solid #EEF1F6}.mx div:last-child{border-right:none}
.mx em{display:block;font:400 25px/1 UI;color:#7A8295;font-style:normal}
.mx b{display:block;font:780 66px/1 UI;letter-spacing:-.045em;margin-top:16px}
.mx span{display:block;font:400 22px/1.25 UI;color:#7A8295;margin-top:12px}
.chart{display:flex;align-items:flex-end;gap:16px;height:150px;margin-top:22px}
.chart i{flex:1;border-radius:10px 10px 4px 4px;background:#D5DEFF}.chart i.on{background:#2447F0}
.days{display:flex;gap:16px;margin-top:12px}.days span{flex:1;text-align:center;font:400 22px/1 UI;color:#7A8295}
.note{font:400 28px/1.42 UI;margin-top:26px}.note b{font-weight:700}
.today{display:flex;gap:14px;align-items:center;margin-top:22px;font:500 25px/1.3 UI;color:#5B6478}
.today i{width:14px;height:14px;border-radius:50%;background:#2447F0;flex:none}
"""


def report_phone():
    bars = [42, 55, 48, 62, 50, 71, 96]
    body = ('<div class="card"><div class="hd"><div><b>Yesterday</b><span>Your Meta ads</span></div><div class="chip">Sample</div></div>'
            '<div class="rule"></div><div class="mx">'
            '<div><em>Spent</em><b>€18</b><span>within your cap</span></div>'
            '<div><em>Clicks</em><b>31</b><span>7-day avg 26</span></div>'
            '<div><em>Enquiries</em><b>4</b><span>7-day avg 3</span></div></div>'
            '<div class="chart">' + "".join(f'<i class="{"on" if i == 6 else ""}" style="height:{h}%"></i>' for i, h in enumerate(bars))
            + '</div><div class="days">' + "".join(f"<span>{d}</span>" for d in "WTFSSMT") + '</div>'
            '<div class="note"><b>Best ad:</b> the lunch reel. <b>3 posts</b> are waiting for your tap.</div>'
            '<div class="today"><i></i>Today: a post at 12:00 and a story at 17:00</div>'
            '<div class="btns"><div class="btn sec">Pause an ad</div><div class="btn pri">Approve posts</div></div></div>')
    return PHONE % {"css": CSS % {"font": FONT.as_uri()}, "extra": REPORT_CSS, "title": "Morning report",
                    "sub": 'Tuesday · 07:35 · <b>Sample</b>', "body": body, "tabs": tabs("Today")}


# ---------------------------------------------------------------- this week: six post types

WEEK_CSS = MEDIA_CSS + """
.row{display:flex;align-items:center;gap:22px;padding:15px 0;border-bottom:2px solid #F0F2F6}
.row:last-of-type{border-bottom:none}
.th{position:relative;width:96px;height:96px;border-radius:20px;overflow:hidden;flex:none}
.th .ic{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:800 30px/1 UI}
.rw{flex:1;min-width:0}.rw b{display:block;font:700 29px/1.15 UI;letter-spacing:-.01em}.rw span{display:block;font:400 23px/1.3 UI;color:#7A8295;margin-top:4px}
.ok{font:650 22px/1 UI;color:#1A7F4B;background:#E3F5EA;padding:10px 14px;border-radius:12px}
"""


def week_phone():
    rows = [("carousel", "Carousel", "Mon 08:00 · 5 slides", '<div class="ic" style="color:#8A5A2B">1/5</div>'),
            ("reel", "Reel", "Tue 12:00 · 15 seconds", '<div class="ic"><div style="width:0;height:0;border-left:26px solid #fff;border-top:16px solid transparent;border-bottom:16px solid transparent;margin-left:6px"></div></div>'),
            ("story", "Story", "Wed 17:00 · 3 frames", '<div class="ic" style="color:#fff;font-size:24px">Fri</div>'),
            ("offer", "Offer", "Thu 11:00 · feed post", '<div class="ic" style="color:#2B1D05;font-size:24px">Week</div>'),
            ("howto", "How-to", "Fri 09:00 · 3 steps", '<div class="ic" style="color:#2447F0">1·2·3</div>'),
            ("review", "Review post", "Sat 10:00 · from your reviews", '<div class="ic" style="color:#2447F0;font:800 64px/1 Georgia,serif;padding-top:22px">“</div>')]
    body = ('<div class="card" style="padding:18px 32px 32px">'
            + "".join(f'<div class="row"><div class="th m-{k}" style="padding:0">{ic}</div><div class="rw"><b>{t}</b><span>{s}</span></div>'
                      f'<div class="ok">Ready</div></div>' for k, t, s, ic in rows)
            + '<div class="btns" style="margin-top:22px"><div class="btn sec">One by one</div><div class="btn pri">Approve all</div></div></div>')
    return PHONE % {"css": CSS % {"font": FONT.as_uri()}, "extra": WEEK_CSS, "title": "This week",
                    "sub": '6 posts ready for you · <b>Sample</b>', "body": body, "tabs": tabs("Review")}


# ---------------------------------------------------------------- the campaign Otto runs (one campaign, an ad set per angle)

CAMPAIGN_CSS = REPORT_CSS + """
.mx.sm b{font-size:52px;margin-top:12px}.mx.sm div{padding:22px 0 20px 32px}
.sets{margin-top:28px}
.set{display:flex;align-items:center;gap:20px;padding:16px 0;border-bottom:2px solid #F0F2F6}
.set:last-child{border-bottom:none}
.set .th{width:84px;height:84px;border-radius:18px;flex:none;display:flex;align-items:center;justify-content:center;
  font:800 22px/1.05 UI;text-align:center;letter-spacing:-.01em}
.set .rw{flex:1;min-width:0}.set .rw b{display:block;font:700 28px/1.15 UI;letter-spacing:-.01em}
.set .rw span{display:block;font:400 23px/1.3 UI;color:#7A8295;margin-top:4px}
.st{font:650 21px/1 UI;padding:10px 13px;border-radius:12px;white-space:nowrap}
.st.best{color:#1A7F4B;background:#E3F5EA}.st.run{color:#2447F0;background:#EDF1FF}.st.off{color:#7A8295;background:#EEF1F6}
.lbl{font:650 23px/1 UI;color:#7A8295;letter-spacing:.06em;margin-top:30px;text-transform:uppercase}
"""


def campaign_phone():
    sets = [("Lunch deal", "€6 · 2 enquiries", "best", "Best", "background:linear-gradient(150deg,#FFF0BF,#F7C95A);color:#2B1D05", "Lunch<br>deal"),
            ("Gift cards", "€5 · 1 enquiry", "run", "Running", "background:linear-gradient(150deg,#F6CEDA,#C9B3F2);color:#2B1B45", "Gift<br>cards"),
            ("New on the menu", "€4 · 1 enquiry", "run", "Running", "background:linear-gradient(150deg,#F7EBDA,#E2C29C);color:#3A2716", "New"),
            ("Behind the scenes", "€3 · 0 enquiries", "off", "Paused", "background:linear-gradient(170deg,#3A2A20,#15110E);color:#F3D9A4", "Reel")]
    body = ('<div class="card" style="margin-top:36px"><div class="hd"><div><b>Yesterday</b><span>Autumn campaign · Meta ads</span></div>'
            '<div class="chip">Sample</div></div><div class="rule"></div><div class="mx sm">'
            '<div><em>Spent</em><b>€18</b></div><div><em>Clicks</em><b>31</b></div><div><em>Enquiries</em><b>4</b></div></div>'
            '<div class="lbl">Ad sets · one per angle</div><div class="sets">'
            + "".join(f'<div class="set"><div class="th" style="{st}">{t}</div><div class="rw"><b>{n}</b><span>{m}</span></div>'
                      f'<div class="st {c}">{lab}</div></div>' for n, m, c, lab, st, t in sets)
            + '</div><div class="btns" style="margin-top:22px"><div class="btn sec">Pause one</div><div class="btn pri">See the ads</div></div></div>')
    return PHONE % {"css": CSS % {"font": FONT.as_uri()}, "extra": CAMPAIGN_CSS, "title": "Your campaign",
                    "sub": 'Reported at 07:35 · <b>Sample</b>', "body": body, "tabs": tabs("Results")}


# ---------------------------------------------------------------- the ads Otto makes (showcase: sample ads for demo brands)

SHOWCASE = ASSETS / "showcase"
ADS_CSS = """
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:26px}
.grid img{display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:22px;box-shadow:0 0 0 2px rgba(16,24,43,.06)}
.cap2{margin-top:22px;font:500 24px/1.3 UI;color:#7A8295;text-align:center}
"""


# the picks: no people or hands (Otto's ads show no AI-made people), no discount codes (a demo brand's "20% off" would read
# as Otto's offer), four brands and four ad styles in the grid (playful scene, offer card, infographic, flat-lay)
GRID = ["01-snapleaf-mascots.png", "12-korrel-offer.png", "07-aurive-infographic.png", "10-hushroom-flatlay.png"]
SAMPLES = ["04-korrel-counter.png", "11-aurive-split.png", "09-snapleaf-macro.png"]


def showcase(files):
    """The showcase entries for these files (manifest order kept as given), or [] while the folder is not there yet."""
    mf = SHOWCASE / "manifest.json"
    if not mf.exists():
        return []
    import json
    by = {x["file"]: x for x in json.loads(mf.read_text())}
    return [by[f] for f in files if f in by and (SHOWCASE / f).exists()]


def ads_phone(items):
    imgs = "".join(f'<img src="{(SHOWCASE / x["file"]).as_uri()}" alt="">' for x in items[:4])
    body = ('<div class="card"><div class="hd"><div><b>4 new ads</b><span>Feed and stories · ready to run</span></div>'
            '<div class="chip">Sample</div></div><div class="grid">' + imgs + '</div>'
            '<div class="cap2">Sample ads for demo brands</div>'
            '<div class="btns" style="margin-top:20px"><div class="btn sec">Change</div><div class="btn pri">Approve</div></div></div>')
    return PHONE % {"css": CSS % {"font": FONT.as_uri()}, "extra": REPORT_CSS + ADS_CSS, "title": "New ads",
                    "sub": 'Made by Otto · <b>Sample</b>', "body": body, "tabs": tabs("Review")}


STORY = "04-korrel-counter.png"                             # the 9:16 variant of this ad plays the story ad


def variant_916(item):
    """The 9:16 file of a showcase entry ("variants" in manifest.json, or <stem>-9x16.png next to it), or None."""
    v = item.get("variants")
    cands = []
    if isinstance(v, dict):
        cands = [x.get("file") if isinstance(x, dict) else x for k, x in v.items() if "9x16" in str(k) or "9x16" in str(x)]
    elif isinstance(v, list):
        cands = [x.get("file") if isinstance(x, dict) else x for x in v if "9x16" in json_dumps(x)]
    cands.append(item["file"].replace(".png", "-9x16.png"))
    for c in cands:
        if c and (SHOWCASE / c).exists():
            return SHOWCASE / c
    return None


def json_dumps(x):
    import json
    return json.dumps(x)


STORY_CSS = """
.full{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:blur(28px) brightness(.7);transform:scale(1.15)}
.fit{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);width:100%;height:auto}
.sbars{position:absolute;top:96px;left:40px;right:40px;display:flex;gap:8px}
.sbars i{flex:1;height:6px;border-radius:3px;background:rgba(255,255,255,.55)}.sbars i.on{background:#fff}
.sacct{position:absolute;top:120px;left:40px;display:flex;align-items:center;gap:14px;font:700 26px/1 UI;color:#fff;
  text-shadow:0 1px 6px rgba(0,0,0,.45)}
.sacct i{width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,.9)}
.sacct span{font-weight:500;opacity:.9}
.schip{position:absolute;top:196px;right:36px;background:rgba(255,255,255,.95);color:#10182B;font:700 24px/1 UI;padding:11px 15px;
  border-radius:14px;box-shadow:0 6px 16px -8px rgba(0,0,0,.4)}
"""


def story_phone(item, f916):
    """A phone playing one showcase ad as a 9:16 story: generic story UI (progress bars, account line), no platform marks."""
    brand = (item.get("brand") or "").lower()
    css = CSS % {"font": FONT.as_uri()} + STORY_CSS
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body style="width:900px;height:1848px">'
            f'<div class="phone"><div class="screen" style="background:#000"><img class="full" src="{f916.as_uri()}" alt="">'
            f'<img class="fit" src="{f916.as_uri()}" alt="">'
            '<div class="island"></div><div class="time" style="color:#fff">07:35</div>'
            '<div class="batt" style="border-color:#fff"></div>'
            '<div class="sbars"><i class="on"></i><i></i><i></i></div>'
            f'<div class="sacct"><i></i>{brand} <span>· Sponsored</span></div>'
            '<div class="schip">Sample ad · demo brand</div>'
            '</div></div></body></html>')


def duo(names, out):
    """Two phone cut-outs side by side (feed ads + story ads): the second one a little smaller and tilted, overlapping only
    the first one's bezel, so both screens and both "Sample" labels stay readable."""
    a, b = [Image.open(ASSETS / n).convert("RGBA") for n in names]
    a, b = a.crop(a.getbbox()), b.crop(b.getbbox())
    b = b.resize((int(b.width * .9), int(b.height * .9)), Image.LANCZOS).rotate(-4, resample=Image.BICUBIC, expand=True)
    W, H = a.width * 3, int(a.height * 1.4)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ax, ay = a.width // 2, (H - a.height) // 2
    canvas.alpha_composite(a, (ax, ay))
    canvas.alpha_composite(b, (ax + int(a.width * .95), ay + int(a.height * .07)))
    canvas = canvas.crop(canvas.getbbox())
    canvas.save(out, optimize=True)
    print("wrote", out.relative_to(REPO), canvas.size)


def ads_grid(items):
    """2x2 grid of showcase ads, clean, with the caption: for framed photos and chat attachments."""
    css = CSS % {"font": FONT.as_uri()}
    imgs = "".join(f'<img src="{(SHOWCASE / x["file"]).as_uri()}" style="display:block;width:500px;height:500px;object-fit:cover;'
                   f'border-radius:26px;box-shadow:0 18px 34px -22px rgba(16,24,43,.45)">' for x in items[:4])
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            '<body style="width:1080px;height:1160px;background:#EEF1F6">'
            f'<div style="position:absolute;left:30px;top:30px;display:grid;grid-template-columns:500px 500px;gap:20px">{imgs}</div>'
            '<div style="position:absolute;left:0;right:0;top:1066px;text-align:center;font:600 34px/1 UI;color:#5B6478">'
            'Sample ads for demo brands</div></body></html>')


def ad_sample(item):
    """One showcase ad with a corner label, for a chat attachment."""
    css = CSS % {"font": FONT.as_uri()} + MEDIA_CSS
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body style="width:1080px;height:1080px">'
            f'<img src="{(SHOWCASE / item["file"]).as_uri()}" style="position:absolute;inset:0;width:1080px;height:1080px;object-fit:cover">'
            '<div class="samp" style="top:30px;right:30px;font-size:32px;padding:14px 20px;border-radius:18px">Sample ad · demo brand</div>'
            '</body></html>')


# ---------------------------------------------------------------- shoot + compose

def shoot(html_text, out, size):
    tmp = out.with_suffix(".tmp.png")
    otto_render.screenshot(html_text, str(tmp), size, budget=4000)
    im = Image.open(tmp).convert("RGBA")
    im.save(out, optimize=True)
    tmp.unlink()
    print("wrote", out.relative_to(REPO), im.size)
    return out


def fan(names, out):
    """Three phone cut-outs fanned: the middle one in front, the outer two smaller, tilted and behind."""
    ims = [Image.open(ASSETS / n).convert("RGBA") for n in names]
    ims = [im.crop(im.getbbox()) for im in ims]
    w, h = ims[1].size
    side = [im.resize((int(im.width * .84), int(im.height * .84)), Image.LANCZOS) for im in (ims[0], ims[2])]
    left = side[0].rotate(7, resample=Image.BICUBIC, expand=True)
    right = side[1].rotate(-7, resample=Image.BICUBIC, expand=True)
    W, H = w * 4, int(h * 1.3)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx = W // 2
    top = (H - h) // 2
    canvas.alpha_composite(left, (cx - w // 2 - int(left.width * .62), top + int(h * .5 - left.height * .5 + h * .03)))
    canvas.alpha_composite(right, (cx + w // 2 - int(right.width * .38), top + int(h * .5 - right.height * .5 + h * .03)))
    canvas.alpha_composite(ims[1], (cx - w // 2, top))
    canvas = canvas.crop(canvas.getbbox())
    canvas.save(out, optimize=True)
    print("wrote", out.relative_to(REPO), canvas.size)


USED_POSTS = ("carousel", "reel", "story", "opening")      # the reel, carousel and story phones also feed the fan
USED_SQUARES = ("carousel",)                                # a5's chat attachment
USED_ADS = 1                                                # a4's chat attachment: otto-ad-1-sample.png


def main():
    """Writes the assets the October matrices use. --all also writes the other sample-post phones (offer, how-to, review
    post), the other square posts, the 2x2 showcase grid and three ad samples (not used by the launch kit)."""
    every = "--all" in sys.argv
    only = set((sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "").split(",")) - {""}
    jobs = {"report_ads": lambda: shoot(report_phone(), ASSETS / "otto-phone-report-ads-cutout.png", (900, 1848)),
            "week": lambda: shoot(week_phone(), ASSETS / "otto-phone-week-cutout.png", (900, 1848)),
            "campaign": lambda: shoot(campaign_phone(), ASSETS / "otto-phone-campaign-cutout.png", (900, 1848))}
    for k in POSTS:
        if every or k in USED_POSTS:
            jobs[f"post_{k}"] = (lambda k=k: shoot(post_phone(k), ASSETS / f"otto-phone-post-{k}-cutout.png", (900, 1848)))
    for k in ("carousel", "opening", "offer"):
        if every or k in USED_SQUARES:
            jobs[f"square_{k}"] = (lambda k=k: shoot(post_square(k), ASSETS / f"otto-post-{k}-sample.png", (1080, 1080)))
    sc, samples = showcase(GRID), showcase(SAMPLES)
    if len(sc) == 4 and samples:
        jobs["ads"] = lambda: shoot(ads_phone(sc), ASSETS / "otto-phone-ads-cutout.png", (900, 1848))
        if every:
            jobs["ads_grid"] = lambda: shoot(ads_grid(sc), ASSETS / "otto-ads-grid-sample.png", (1080, 1160))
        for i, x in enumerate(samples if every else samples[:USED_ADS], 1):
            jobs[f"ad_{i}"] = (lambda i=i, x=x: shoot(ad_sample(x), ASSETS / f"otto-ad-{i}-sample.png", (1080, 1080)))
        story = showcase([STORY])
        f916 = variant_916(story[0]) if story else None
        if f916:
            jobs["story_ad"] = lambda: shoot(story_phone(story[0], f916), ASSETS / "otto-phone-story-ad-cutout.png", (900, 1848))
        else:
            print(f"no 9:16 variant of {STORY} yet: the story-ad phone is skipped")
    else:
        print("showcase/ has no manifest yet: the ads phone and the ad samples are skipped")
    for name, job in jobs.items():
        if not only or name in only:
            job()
    if (not only or "duo" in only) and (ASSETS / "otto-phone-story-ad-cutout.png").exists():
        duo(["otto-phone-ads-cutout.png", "otto-phone-story-ad-cutout.png"], ASSETS / "otto-phones-ads-duo-cutout.png")
    if not only or "fan" in only:
        fan(["otto-phone-post-reel-cutout.png", "otto-phone-post-carousel-cutout.png", "otto-phone-post-story-cutout.png"],
            ASSETS / "otto-phones-post-types-cutout.png")
    # review sheet
    files = sorted(ASSETS.glob("otto-phone*-cutout.png")) + sorted(ASSETS.glob("otto-post-*-sample.png")) \
        + sorted(ASSETS.glob("otto-ad*-sample.png"))
    otto_render.contact_sheet([("Otto phone cut-outs and sample posts (brands/otto/assets)", [(str(f), f.stem) for f in files])],
                              HERE / "sheets" / "phones.jpg", cols=6, thumb_w=300)
    print("sheet", HERE / "sheets" / "phones.jpg")


if __name__ == "__main__":
    main()
