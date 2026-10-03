#!/usr/bin/env python3
"""The walkthrough with a FILLED-IN client: a sample bakery ("Brood & Co") with posts and their numbers, ads reports, an
ad matrix and a plan card, so the client dashboard (Today, Review, Results) can be seen with data. Never touches the
walkthrough's own workspace (~/.otto-walk) or any real data; the numbers are invented samples.

    python3 tools/walkthrough_demo.py            (launch config "otto-walk-demo")

Seeds ~/.otto-walk-demo/ws on every start, then runs tools/walkthrough.py there on http://localhost:8792.
Sign in on its test Google page as demo@broodenco.example to open the bakery's app.
"""
import json, os, random, shutil, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HOME = Path(os.environ.get("OTTO_WALK_DEMO_HOME") or Path.home() / ".otto-walk-demo")
WS = HOME / "ws"
PLATFORM = Path(__file__).resolve().parent.parent
BID = "brood"
TODAY = datetime.now(timezone.utc).date()
rnd = random.Random(7)

if WS.exists():
    shutil.rmtree(WS)
for d in ("brands", "assets", "public/assets/posts", "public/assets/ads", "secrets", "outbox", "exports", "locks", "motion"):
    (WS / d).mkdir(parents=True, exist_ok=True)

FONT = next((f for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                         "/System/Library/Fonts/Helvetica.ttc") if Path(f).exists()), None)
PAL = [("#7A4B2A", "#F7EBDD"), ("#2F4A3A", "#EEF3EC"), ("#B4532A", "#FFF1E6"), ("#3B3F6B", "#EEF0FA"), ("#8C6D1F", "#FBF5E4")]


def card(path, text, i, size=(1080, 1350)):
    fg, bg = PAL[i % len(PAL)]
    im = Image.new("RGB", size, bg)
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, size[1] - 220, size[0], size[1]], fill=fg)
    f = ImageFont.truetype(FONT, 76) if FONT else ImageFont.load_default()
    small = ImageFont.truetype(FONT, 40) if FONT else ImageFont.load_default()
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur + " " + w) > 18:
            lines.append(cur.strip()); cur = w
        else:
            cur += " " + w
    lines.append(cur.strip())
    y = 220
    for ln in lines[:5]:
        dr.text((90, y), ln, font=f, fill=fg)
        y += 96
    dr.ellipse([size[0] - 300, 120, size[0] - 120, 300], outline=fg, width=10)
    dr.text((90, size[1] - 150), "Brood & Co · Utrecht", font=small, fill=bg)
    im.save(path, quality=86)


HOOKS = ["Why our sourdough takes 36 hours", "Three loaves for the weekend", "Meet Sanne, our early baker",
         "The crust test: tap, listen, smile", "Spelt or rye? A quick guide", "Saturday's cinnamon knots are back",
         "Our flour comes from 40 km away", "How to keep bread fresh for 3 days", "Behind the oven at 4:30",
         "The loaf our regulars order most", "Rye that tastes like holidays", "One dough, five breads",
         "Why we score every loaf by hand", "Your Sunday breakfast, sorted", "Fresh at 7, gone by 11"]
FMTS = ["post", "carousel", "post", "reel", "post", "carousel", "story"]
posts, seq = [], 0


def P(**kw):
    global seq
    seq += 1
    p = {"id": f"br-{seq:03d}", "brand": BID, "pillar": rnd.choice(["Craft", "Behind the oven", "Offers", "Tips"])}
    p.update(kw)
    posts.append(p)
    return p


start = date(2026, 7, 1)
img_i = 0
d = start
while d <= TODAY + timedelta(days=29):
    for slot_h in ((9,) if d.weekday() >= 5 else (9, 18)):
        fmt = FMTS[(d.toordinal() + slot_h) % len(FMTS)]
        plat = "ig" if (d.toordinal() + slot_h) % 3 else "fb"
        slot = f"{d.isoformat()}T{slot_h:02d}:00"
        hook = HOOKS[(d.toordinal() * 3 + slot_h) % len(HOOKS)]
        if d < TODAY or (d == TODAY and slot_h == 9):
            pubd = datetime(d.year, d.month, d.day, slot_h - 2, 0, tzinfo=timezone.utc)
            m = None
            if d < TODAY - timedelta(days=1) or (d == TODAY - timedelta(days=1) and slot_h == 9):
                reach = int(rnd.lognormvariate(6.6, 0.5)) + (300 if fmt == "reel" else 0)
                m = {"reach": reach, "likes": int(reach * rnd.uniform(.03, .08)), "comments": rnd.randint(0, 12),
                     "shares": rnd.randint(0, 9), "saves": int(reach * rnd.uniform(.004, .03)),
                     "pulled_at": "2026-10-02T05:07:00Z"}
                if plat == "fb":
                    m["clicks"] = rnd.randint(4, 40)
            p = P(platform=plat, format=fmt, slot=slot, status="published", hook=hook, caption=hook + ". Fresh daily in Utrecht.",
                  published_at=pubd.strftime("%Y-%m-%dT%H:%M:%SZ"), metrics=m, copy={"by": "otto_copy", "model": "claude-x", "attempts": 2,
                  "state": "written", "job": "daily", "held_for": ["claims"]})
            if d >= TODAY - timedelta(days=20):
                f = WS / "public/assets/posts" / f"{p['id']}-{'a' * 32}.jpg"
                card(f, hook, img_i); img_i += 1
                p["image"] = f"assets/posts/{f.name}"
        else:
            st = "pending_approval" if d <= TODAY + timedelta(days=3) else "approved" if d <= TODAY + timedelta(days=6) else "draft"
            p = P(platform=plat, format=fmt, slot=slot, status=st)
            if st != "draft" or d <= TODAY + timedelta(days=8):
                p.update(hook=hook, caption=hook + ". Order before Friday noon for Saturday pick-up.",
                         copy={"by": "otto_copy", "model": "claude-x", "attempts": 1, "state": "written", "job": "daily"})
                f = WS / "public/assets/posts" / f"{p['id']}-{'b' * 32}.jpg"
                card(f, hook, img_i); img_i += 1
                p["image"] = f"assets/posts/{f.name}"
                if fmt == "reel":
                    p.pop("image", None) if st == "draft" else None
    d += timedelta(days=1)

# ---------------- ads: September (ended) + October (live), concept flights, per-ad rows for 14 days
ANGLES = [("a1", "Fresh every morning", "pain", ["Bread baked this morning, not last week", "Fresh at 7, every day"],
           ["Real sourdough, baked at 4:30 and on the shelf at 7. Order before 10 and pick it up warm.",
            "Supermarket bread is baked days ago. Ours is baked this morning, 2 km from your door."]),
          ("a2", "Sourdough people", "identity", ["For people who read the ingredients", "Four ingredients. 36 hours."],
           ["Flour, water, salt and time. That's the whole list.", "If you check labels, you'll like ours: four ingredients, nothing else."]),
          ("a3", "Supermarket bread", "enemy", ["Your bread shouldn't last two weeks", "Bread without the extras"],
           ["Why does supermarket bread stay soft for 14 days? Ours doesn't, and that's the point.",
            "No improvers, no preservatives. Just bread that tastes like bread."]),
          ("a4", "Weekend order", "offer", ["Order your weekend loaves", "Saturday breakfast, sorted"],
           ["Order by Friday noon, pick up Saturday from 7. Free cinnamon knot with every order over €15.",
            "Three loaves, one pick-up, zero queue. Order for the weekend in a minute."])]
STYLES = [("notes_app", "video", "faceless"), ("text_message", "image", "native"), ("product_hero", "image", "product"),
          ("us_vs_them", "image", "comparison"), ("search", "image", "native")]


def matrix(ym):
    return {"brand": BID, "month": ym, "preset": "micro", "angles": [
        {"id": aid, "name": name, "family": fam, "stage": "cold", "kinds": ["benefit"], "ad_set": f"{aid} · {name}",
         "angle": "STRATEGIST NOTE — never shown", "persona": "p1", "source": "profile",
         "headlines": heads, "primaries": prims, "description": "Brood & Co, Utrecht", "cta": "SIGN_UP" if fam != "offer" else "ORDER_NOW",
         "ads": [{"id": f"{ym[5:]}-{aid}-{st}", "style": st, "slot": slot, "format": fm, "size": ["feed", "story"] if fm == "image" else ["story"],
                  "brief": "BRIEF — never shown", "data": {"title": heads[0]},
                  **({"video": {"kit": "notes", "data": f"video/{ym}/{aid}.json"}} if fm == "video" else {})}
                 for st, fm, slot in STYLES]} for aid, name, fam, heads, prims in ANGLES]}


bdir = WS / "brands" / BID
bdir.mkdir(parents=True, exist_ok=True)
for ym in ("2026-09", "2026-10", "2026-11"):
    (bdir / f"ads-{ym}.json").write_text(json.dumps(matrix(ym), indent=1))
(bdir / "scan.json").write_text(json.dumps({"name": "Brood & Co", "commerce": {"currency": "EUR"}}))
(bdir / "brand-profile.md").write_text("# Brood & Co\nSample brand for a dashboard check.\n")

campaigns, ad_index = [], []
for cid, ym, s, e, status, budget in (("cp-001", "2026-09", "2026-09-01", "2026-09-30", "ended", 18),
                                       ("cp-002", "2026-10", "2026-10-01", "2026-10-31", "live", 20)):
    concepts, remote_c = [], {}
    for k, (aid, name, fam, heads, prims) in enumerate(ANGLES):
        ads = []
        st = {"adset_id": f"23{cid[-1]}{k}00", "active": True, "ads": {}}
        for j, (style, fm, slot) in enumerate(STYLES):
            cell = f"{ym[5:]}-{aid}-{style}"
            files = []
            if fm == "image":
                f = WS / "public/assets/ads" / f"{cid}-{cell}-{'c' * 32}.jpg"
                card(f, heads[j % 2], k + j)
                files.append({"file": f"assets/ads/{f.name}", "size": "feed"})
            ads.append({"id": cell, "angle": aid, "style": style, "format": fm, "headline": heads[j % 2], "primary": prims[j % 2],
                        "description": "Brood & Co, Utrecht", "cta": "SIGN_UP", "files": files})
            ad_id = f"6{cid[-1]}{k}{j}0012345"
            st["ads"][cell] = {"ad_id": ad_id, "creative_id": "x", "style": style}
            ad_index.append((cid, ad_id, st["adset_id"], f"{name}", cell, fam))
        concepts.append({"angle": aid, "name": name, "ad_set": f"{aid} · {name}", "ads": ads})
        remote_c[aid] = st
    campaigns.append({"id": cid, "brand": BID, "network": "meta", "name": f"Brood & Co · {datetime.strptime(ym, '%Y-%m'):%B} leads",
                      "objective": "leads", "plan": ym, "start": s, "end": e, "daily_budget": budget, "currency": "€",
                      "currency_code": "EUR", "status": status, "media_token": "f" * 32,
                      "remote": {"campaign_id": f"1200{cid[-1]}", "structure": "concepts", "concepts": remote_c, "done": True,
                                 "campaign_active": True, "ads": 20},
                      "creatives": {"concepts": concepts, "media_token": "f" * 32}})
for k in range(4):                                       # November: drafts waiting for the plan card
    campaigns.append({"id": f"cp-00{3 + k}", "brand": BID, "network": "meta", "name": f"Brood & Co · November · week {k + 1}",
                      "objective": "leads", "plan": "2026-11", "start": f"2026-11-{1 + 7 * k:02d}",
                      "end": f"2026-11-{min(30, 7 + 7 * k + (2 if k == 3 else 0)):02d}", "daily_budget": 20, "currency": "€",
                      "currency_code": "EUR", "status": "draft", "remote": {}})

daily = {}
for back in range(1, 91):
    data_day = TODAY - timedelta(days=back)
    camp = "cp-002" if data_day >= date(2026, 10, 1) else "cp-001" if data_day >= date(2026, 9, 1) else None
    if camp is None:
        continue
    rows_ads = [x for x in ad_index if x[0] == camp]
    ad_rows, total = [], {"spend": 0, "results": 0, "link": 0, "imp": 0, "reach": 0}
    for (_, ad_id, adset_id, aname, cell, fam) in rows_ads:
        w = {"pain": 1.3, "identity": 1.0, "enemy": 0.8, "offer": 1.5}[fam] * rnd.uniform(.5, 1.5)
        spend = round(0.9 * w, 2)
        res = 1 if rnd.random() < 0.06 * w else 0
        link = int(rnd.uniform(1, 4) * w)
        imp = int(spend * 95)
        ad_rows.append({"id": ad_id, "name": f"{camp} · {cell}", "objective": "OUTCOME_LEADS", "result_type": "leads",
                        "conversion": True, "spend": spend, "impressions": imp, "reach": int(imp * .8), "clicks": link + 2,
                        "link_clicks": link, "results": res, "leads": res, "cpl": round(spend / res, 2) if res else None,
                        "cost_per_result": round(spend / res, 2) if res else None, "ad_id": ad_id, "ad_name": f"{camp} · {cell}",
                        "adset_id": adset_id, "adset_name": f"{camp} · {aname}", "campaign_id": f"1200{camp[-1]}",
                        "campaign_name": camp})
        total["spend"] += spend; total["results"] += res; total["link"] += link; total["imp"] += imp
    sp = round(total["spend"], 2)
    crow = {"id": f"1200{camp[-1]}", "name": camp, "objective": "OUTCOME_LEADS", "result_type": "leads", "conversion": True,
            "spend": sp, "impressions": total["imp"], "reach": int(total["imp"] * .7), "clicks": total["link"] + 30,
            "link_clicks": total["link"], "results": total["results"], "leads": total["results"],
            "cpl": round(sp / total["results"], 2) if total["results"] else None,
            "cost_per_result": round(sp / total["results"], 2) if total["results"] else None}
    y = {"spend": sp, "results": total["results"], "results_by_type": {"leads": total["results"]} if total["results"] else {},
         "clicks": total["link"] + 30, "link_clicks": total["link"], "impressions": total["imp"],
         "cpl": crow["cpl"], "ctr": 1.2, "cost_by_type": {"leads": crow["cpl"]} if crow["cpl"] else {}, "leads": total["results"],
         "cost_per_lead": crow["cpl"], "messages": 0}
    entry = {"meta": {"yesterday": y, "week": y, "campaigns": [crow], "currency": "EUR", "attribution": "7d_click,1d_view"},
             "google": None}
    if back <= 14:
        entry["meta"]["ads"] = ad_rows
    daily[(data_day + timedelta(days=1)).isoformat()] = entry

acct = {}
for back in range(1, 62):
    day = TODAY - timedelta(days=back)
    acct[day.isoformat()] = {"ig": {"reach": rnd.randint(600, 1900), "views": rnd.randint(2000, 6000), "follows": rnd.randint(2, 14),
                                    "unfollows": rnd.randint(0, 4), "link_taps": rnd.randint(3, 25)},
                             "fb": {"viewers": rnd.randint(200, 700), "follows": rnd.randint(0, 4), "unfollows": rnd.randint(0, 2)}}

now = "2026-10-02T06:10:00Z"
data = {"generated": now, "brands": [{"id": BID, "name": "Brood & Co", "url": "broodenco.example", "lang": "en", "tz": "Europe/Amsterdam",
                                       "status": "active", "plan": "starter", "currency": "EUR", "countries": ["NL"],
                                       "members": ["demo@broodenco.example"], "approvals": "email", "comms_lang": "en",
                                       "copy_auto": False, "otto_since": "2026-07-01", "pillars": ["Craft", "Behind the oven", "Offers", "Tips"]}],
        "posts": posts, "campaigns": campaigns,
        "recommendations": [{"id": "rec-001", "priority": "P1", "title": "Approve the 2026-11 paid plan: 4 campaigns, ≈€600",
                             "why": "20 ads across 4 angles for November.", "impact": "", "cta": "Approve plan", "status": "proposed",
                             "created_at": now, "brand": BID, "source": "otto_ads", "action": "approve_plan", "plan": "2026-11"},
                            {"id": "rec-002", "priority": "P1", "title": "Double down on Behind the oven",
                             "why": "Your behind-the-oven posts got the most saves this month.", "impact": "", "cta": "Plan more",
                             "status": "proposed", "created_at": now, "brand": BID, "source": "otto_insights"}],
        "connections": [{"id": f"meta-{BID}", "service": "Instagram + Facebook", "brand": "Brood & Co", "status": "connected"}],
        "ads": {BID: {"connections": {"meta": True, "google": False}, "targets": {"cpl": 8}, "daily": daily}},
        "metrics": {BID: {"reach": 0, "followers": 1840, "daily": acct, "account": {"pulled_at": "2026-10-02T05:07:00Z",
                                                                                    "ig": {"followers": 1840}}}},
        "users": [], "trial_ledger": [], "seq": {}}
(WS / "data.json").write_text(json.dumps(data, indent=1))
plans = json.loads((PLATFORM / "plans.json").read_text())
(WS / "plans.json").write_text(json.dumps(plans, indent=1))
print(f"seeded {WS}: {len(posts)} posts, {len(campaigns)} campaigns, {len(daily)} ads days")


# the walkthrough itself, on this workspace and its own port
os.environ.update(OTTO_WALK_HOME=str(HOME), OTTO_WALK_PORT="8792")
os.execv(sys.executable, [sys.executable, str(PLATFORM / "tools" / "walkthrough.py")])
