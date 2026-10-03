#!/usr/bin/env python3
"""Otto client dashboard — what the app's Today, Results and Review show, built only from what the engine already stores.

otto_api.with_dashboard adds to every answer of GET /otto-api/data (and to the data an action returns), per brand of that
answer:

  brands[].today      the 07:35 report's model (otto_report.model — the very function the e-mail and Telegram use), worded
                      in English (the app is English; the e-mail follows brands[].comms_lang, the numbers are the same):
                      {"day" (yesterday, brand-local), "line" (yesterday's sentence: otto_report.summary_parts), "summary"
                       (the opening as the report says it, without the greeting), "yesterday": {"posts", "with_numbers",
                       "reach", "reactions", "clicks", "failed"} (organic numbers only from posts that have them), "paid":
                       null (no paid ads in the plan) | {"state": trial | not_connected | pending | idle | ok, "next"?, and
                       when ok: "spend", "currency", "kind", "results", "cost", "budget", "within", "avg7", "link_clicks",
                       "messages", "month": {"spent", "planned"}?}}
  brands[].ledger     this month's work (brand-local month): {"month", "posts" | "stories" | "reels": {"planned", "made",
                      "out"}, "ads": null | {"designed", "angles", "styles", "live", "month", "state"}, "budget": null |
                      {"planned", "spent" (null until a report has a day of it), "currency"}, "connect": [{"id": site |
                      meta | ad_account | approvals, "label", "detail", "done", "state"?, "channel"?, "requested"?}]}
                      made = written and its picture (or, for a reel, its video) exists, or already published; out =
                      published; planned = this month's posts in the calendar that are not skipped.
  brands[].results    Results for 7 / 30 / 90 days ending yesterday, each against the period of the same length before it:
                      {"day", "started", "state": empty | ok, "connected", "paid_plan", "updated": {"ads_day",
                       "account_at"}, "series": {"start", "reach", "results", "spend"} (180 brand-local days, null where
                       there is no number: before Otto's first post, a day whose posts have no numbers yet, a day without
                       an ads report), "periods": {"7" | "30" | "90": {"days", "from", "to", "prev_from", "prev_to",
                       "numbers": {reach, engagement, followers, link_clicks, results, spend, cost: {"v", "prev", "state",
                       …}}, "posts", "waiting_numbers", "best_posts", "ads", "ads_days", "adsets", "adsets_level",
                       "summary": [sentences]}}}
                      A number is never invented: no source → "state" says why (not_connected | pending | none | trial |
                      idle | no_plan) and "v" is null; the previous period is compared only when it is fully covered
                      (organic: Otto's first post is on or before its first day; paid / account numbers: a report for every
                      day of it), else "prev" is null ("No earlier period yet" in the app).
                      Per-ad numbers (ads.daily[].meta.ads, otto_ads) are kept 14 days: "ads_days" says how many days of the
                      period they cover. adsets = Meta ad sets (one per angle of the matrix) from the per-ad rows, or per
                      campaign from the campaign rows when there are none ("adsets_level": "adset" | "campaign"), plus Google
                      campaigns. summary = 1-3 template sentences from these numbers only (no model call, no claim the numbers
                      do not make).
  brands[].ad_review  the month's ad matrix for Review (brands/<id>/ads-YYYY-MM.json, otto_styles), the month of the paid
                      plan waiting for approval, else this month's or next month's matrix: {"month", "plan_rec" (the plan
                      card's id: approving it is the one tap), "state": proposed | approved | live | draft, "trial",
                      "campaigns", "budget": {"total", "daily", "currency"}, "count", "angles": [{"id", "name", "family",
                      "headlines", "cells": [{"id", "style", "style_label", "format", "headline", "primary",
                      "description", "cta", "cta_label", "media": null | {"image"} | {"video", "poster"}}]}]}
                      Only the cells the plan runs (creator videos only with creator_briefs, video only with video_ads,
                      up to video_ads_per_month — as otto_creative.plan_video). media = the cell's rendered file once
                      otto_creative has made it (campaigns[].creatives, public assets/ paths only); before that the app
                      shows the cell's own words, never a stand-in picture.

Never in any of these: a cost of Otto's own (AI spend, tokens, model), a ledger or hold reason, a strategist note (an angle's
"angle", a cell's "brief", persona, source), a secret or a credential (only "is there an ad account" as a yes / no). Ad spend
is the client's own money and is shown. Everything is cut from the brand's own records: the tenant rule of client_view holds.
Read-only (never writes data.json); stdlib only; never fails the request — on any error a brand carries none of these.
"""
import json, os, re, threading, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap

PERIODS = (7, 30, 90)
SERIES_DAYS = 180
RESULT_KINDS = ("leads", "purchases", "conversions")
MADE_STATUSES = ("pending_approval", "approved", "scheduled", "publishing", "published")
CACHE_TTL = 20.0
_cache, _cache_lock = {}, threading.Lock()

STYLE_LABEL = {"before_after": "Before and after", "big_number": "Big number", "carousel": "Carousel", "checklist": "Checklist",
               "comparison": "Comparison", "editorial": "Editorial", "event": "Event", "founder_note": "Founder's note",
               "ingredients": "Ingredients", "macro_hero": "Close-up", "myth_fact": "Myth and fact", "notes_app": "Notes app",
               "offer": "Offer", "product_hero": "Product", "quote": "Customer quote", "review_cards": "Reviews",
               "search": "Search page", "social_post": "Social post", "text_message": "Text message",
               "ugc_caption": "Photo with captions", "ugc_talking_head": "Creator video", "us_vs_them": "Us vs. them"}
CTA_LABEL = {"SHOP_NOW": "Shop now", "LEARN_MORE": "Learn more", "SIGN_UP": "Sign up", "ORDER_NOW": "Order now",
             "BUY_NOW": "Buy now", "GET_OFFER": "Get offer", "SUBSCRIBE": "Subscribe", "BOOK_TRAVEL": "Book now",
             "CONTACT_US": "Contact us", "APPLY_NOW": "Apply now", "DOWNLOAD": "Download", "GET_QUOTE": "Get quote",
             "SEE_MORE": "See more", "WATCH_MORE": "Watch more", "SEND_MESSAGE": "Send message",
             "WHATSAPP_MESSAGE": "Send WhatsApp message", "BOOK_NOW": "Book now"}
KIND_WORD = {"leads": ("enquiry", "enquiries"), "purchases": ("sale", "sales"), "conversions": ("conversion", "conversions")}
BROKEN = re.compile(r"expired|error|disconnected|revoked|invalid", re.I)


# ============================================================================================
# small helpers
# ============================================================================================

def utcnow():
    return datetime.now(timezone.utc)


def _n(v):
    return ap.num(v) or 0


def _utc(s):
    dt = ap.parse_iso(s) if isinstance(s, str) and s else None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) if dt else None


def _date(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _r2(v):
    return None if v is None else round(float(v), 2)


def _written(p):
    return bool(str(p.get("hook") or "").strip() or str(p.get("caption") or "").strip())


def _pub_day(p, b, tz):
    dt = _utc(p.get("published_at")) or ap.slot_dt(p, b)
    return dt.astimezone(tz).date() if dt else None


def _group(p):
    f = p.get("format")
    return "stories" if f == "story" else "reels" if f == "reel" else "posts"


def _made(p):
    if p.get("status") == "published":
        return True
    if not _written(p):
        return False
    if p.get("format") == "reel":
        return bool(p.get("video"))
    return bool(p.get("image") or p.get("images") or p.get("video"))


def _public(ref):
    """Only a public media path the app can load (assets/…, as posts[].image) — never a file path of the server."""
    return ref if isinstance(ref, str) and ref.startswith("assets/") and ".." not in ref else None


def _secrets():
    return Path(os.environ.get("OTTO_SECRETS") or Path(__file__).resolve().parent.parent.parent / "otto-secrets")


def _ad_account(bid, adsb):
    """Is a Meta ad account linked (the ads report's own flag, or ad_account_id in meta-<brand>.json)? Only yes / no."""
    if ((adsb or {}).get("connections") or {}).get("meta"):
        return True
    try:
        c = json.loads((_secrets() / f"meta-{bid}.json").read_text())
        return bool(isinstance(c, dict) and c.get("ad_account_id"))
    except (OSError, ValueError):
        return False


def _net(e, net):
    """One network's part of an ads.daily entry, {} when it is not a dict."""
    x = e.get(net) if isinstance(e, dict) else None
    return x if isinstance(x, dict) else {}


def _conn(conns, cid):
    return next((c for c in conns or [] if isinstance(c, dict) and c.get("id") == cid), None)


def _conn_state(c):
    st = str((c or {}).get("status") or "not_connected")
    return "connected" if st == "connected" else "broken" if BROKEN.search(st) else "not_connected"


def _camp_month(c):
    return str(c.get("plan") or c.get("start") or "")[:7]


def _month_bounds(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    first = date(y, m, 1)
    last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return first, last


def _next_ym(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def _month_label(ym):
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%B")
    except (TypeError, ValueError):
        return str(ym or "")


def _tr():
    import otto_i18n
    return otto_i18n.Tr("en")


def _money(v, cur):
    return _tr().money(v, cur)


def _word(kind, n):
    one, many = KIND_WORD.get(kind, ("result", "results"))
    return one if round(n) == 1 else many


def _fmt_n(v):
    return f"{int(round(v)):,}"


def ad_status(c, active=True):
    """A campaign (or one of its ad sets) in plain words."""
    st = c.get("status")
    if c.get("compliance_hold") and st not in ("ended", "skipped"):
        return "On hold for a copy check"
    if st == "live":
        return "Live" if active else "Not live yet"
    if st == "paused":
        return "Paused: not in your plan" if c.get("paused_by") == "plan" else "Paused"
    if st == "ended":
        return "Ended"
    if st == "approved":
        s = _date(c.get("start"))
        return f"Starts {s.day} {s.strftime('%b')}" if s else "Approved"
    if st == "draft":
        return "Waiting for your approval"
    if st == "failed":
        return "Not live yet"
    if st == "skipped":
        return "Skipped"
    return str(st or "").replace("_", " ").capitalize()


# ============================================================================================
# Today: the 07:35 model
# ============================================================================================

def today_block(d, b, now):
    import otto_report as rep
    m = rep.model(d, dict(b, comms_lang="en"), now)            # English words, the report's own numbers
    s = rep.summary_parts(m)
    org = m.get("organic") or {}
    out = {"day": m["yesterday"].isoformat(), "line": s["yesterday"],
           "summary": " ".join(x for x in (s["yesterday"], s["waiting"]) if x),
           "yesterday": {"posts": len(m["yday"]), "with_numbers": int(org.get("posts") or 0),
                         "reach": org.get("reach") if org else None, "reactions": org.get("reactions") if org else None,
                         "clicks": org.get("clicks") if org else None, "failed": int(m.get("failed") or 0)},
           "paid": None}
    p = m.get("paid")
    if p:
        q = {"state": p.get("state")}
        if p.get("next"):
            q["next"] = p["next"].isoformat()
        if p.get("state") == "ok":
            budget = p.get("budget")
            q.update({"spend": _r2(p.get("spend")), "currency": p.get("currency"), "kind": p.get("kind"),
                      "results": sum(float(v) for v in (p.get("by") or {}).values()), "cost": _r2(p.get("cost")),
                      "budget": _r2(budget), "within": (p["spend"] <= budget * 1.005) if budget else None,
                      "avg7": p.get("avg7"), "link_clicks": int(p.get("link_clicks") or 0), "messages": int(p.get("messages") or 0)})
            if p.get("month"):
                q["month"] = {"spent": _r2(p["month"]["spent"]), "planned": _r2(p["month"]["planned"])}
        out["paid"] = q
    return out


# ============================================================================================
# Ledger: this month's work + the connect checklist
# ============================================================================================

def _live_ads(c):
    """How many ads of a live campaign run on Meta (concept flights: the cells with an ad id in an active ad set)."""
    r = c.get("remote") if isinstance(c.get("remote"), dict) else {}
    if isinstance(r.get("concepts"), dict):
        return sum(1 for st in r["concepts"].values() if isinstance(st, dict) and st.get("active")
                   for x in (st.get("ads") or {}).values() if isinstance(x, dict) and x.get("ad_id"))
    return len(r.get("ad_ids") or [])


def _matrix(bid, ym):
    try:
        import otto_styles
        return otto_styles.load_matrix(bid, ym)
    except Exception:                                          # noqa: BLE001 — unreadable: no matrix to show
        return None


def _plan_cells(d, bid, mx):
    """[(angle, cell, i)] of the live cells the brand's plan runs (otto_creative.plan_video's rules)."""
    import otto_styles
    p = ap.plan_of(d, bid)
    f, cap = p["features"], p["limits"].get("video_ads_per_month")
    out, n = [], 0
    for a in otto_styles.live_angles(mx):
        for i, cell in enumerate(otto_styles.live_cells(a)):
            fm = otto_styles.fmt(cell)
            if fm == "creator" and not f.get("creator_briefs"):
                continue
            if fm == "video":
                if not f.get("video_ads") or (cap is not None and n >= cap):
                    continue
                n += 1
            out.append((a, cell, i))
    return out


def _month_paid(d, bid, ym, today):
    """(planned budget of the month's approved / live / paused / ended flights, spent so far or None, currency)."""
    import otto_metrics
    cur = ap.brand_currency(d, bid)
    first, last = _month_bounds(ym)
    planned = 0.0
    for c in d.get("campaigns") or []:
        if not isinstance(c, dict) or c.get("brand") != bid or c.get("status") not in ("approved", "live", "paused", "ended"):
            continue
        s, e = _date(c.get("start")), _date(c.get("end"))
        if s and e:
            lo, hi = max(s, first), min(e, last)
            if lo <= hi:
                planned += _n(c.get("daily_budget")) * ((hi - lo).days + 1)
    adsb = (d.get("ads") or {}).get(bid) or {}
    daily = adsb.get("daily") if isinstance(adsb.get("daily"), dict) else {}
    entries = [e for k, e in daily.items() if isinstance(e, dict) and _date(k)
               and first <= _date(k) - timedelta(days=1) <= min(last, today)]
    spent = otto_metrics.paid_period(entries)["spend"] if entries else None
    return round(planned, 2), spent, cur


def ledger(d, b, conns, now):
    bid, tz = b["id"], ap.brand_tz(b)
    today = now.astimezone(tz).date()
    ym = today.strftime("%Y-%m")
    out = {"month": ym, "label": _month_label(ym)}
    month = [p for p in d.get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid
             and str(p.get("slot") or "").startswith(ym) and p.get("status") != "skipped"]
    for g in ("posts", "stories", "reels"):
        ps = [p for p in month if _group(p) == g]
        out[g] = {"planned": len(ps), "made": sum(1 for p in ps if _made(p)),
                  "out": sum(1 for p in ps if p.get("status") == "published")}
    adsb = (d.get("ads") or {}).get(bid) or {}
    paid_plan = ap.entitled(d, bid, "ads")
    out["ads"] = out["budget"] = None
    if paid_plan:
        mx = _matrix(bid, ym)
        cells = _plan_cells(d, bid, mx) if mx else []
        camps = [c for c in d.get("campaigns") or [] if isinstance(c, dict) and c.get("brand") == bid and _camp_month(c) == ym]
        live = sum(_live_ads(c) for c in camps if c.get("status") == "live")
        state = ("live" if any(c.get("status") == "live" for c in camps) else
                 "approved" if any(c.get("status") == "approved" for c in camps) else
                 "draft" if any(c.get("status") == "draft" for c in camps) else "none")
        out["ads"] = {"designed": len(cells), "angles": len({a.get("id") for a, _, _ in cells}),
                      "styles": len({c.get("style") for _, c, _ in cells}), "live": live, "state": state,
                      "trial": ap.plan_of(d, bid)["features"].get("ads_launch") is False}
        planned, spent, cur = _month_paid(d, bid, ym, today)
        out["budget"] = {"planned": planned, "spent": spent, "currency": cur}
    out["connect"] = connect_list(d, b, conns, adsb, paid_plan)
    return out


def connect_list(d, b, conns, adsb, paid_plan):
    bid = b["id"]
    site = (ap.BRANDS / bid / "scan.json").is_file() or (ap.BRANDS / bid / "brand-profile.md").is_file()
    meta = _conn(conns, f"meta-{bid}")
    mst = _conn_state(meta)
    help_ = b.get("connect_help") if isinstance(b.get("connect_help"), dict) else {}
    req = lambda k: (help_.get(k) or {}).get("at") if isinstance(help_.get(k), dict) else None
    items = [{"id": "site", "label": "Website read", "detail": "Your brand profile is ready" if site else "Otto reads your site again shortly",
              "done": bool(site)},
             {"id": "meta", "label": "Instagram and Facebook", "state": mst, "done": mst == "connected",
              "detail": ("Reconnect so Otto can publish again" if mst == "broken" else
                         "Otto publishes your approved posts and reads their numbers" if mst == "connected" else
                         "So Otto can publish your approved posts and measure them"),
              **({"requested": req("meta")} if req("meta") else {})}]
    if paid_plan:
        ok = _ad_account(bid, adsb)
        items.append({"id": "ad_account", "label": "Meta ad account", "done": ok, "state": "connected" if ok else "not_connected",
                      "detail": "Your ads run and report from it" if ok else "So your ads can run and report their results",
                      **({"requested": req("ad_account")} if req("ad_account") else {})})
    try:
        import otto_email
        chans = otto_email.approval_channels(b)
    except Exception:                                          # noqa: BLE001
        chans = ["telegram"] if b.get("approvals") in (None, "telegram") else []
    tg = _conn_state(_conn(conns, f"tg-{bid}")) == "connected"
    ch = "both" if len(chans) > 1 else chans[0] if chans else "app"
    done = "email" in chans or ch == "app" or tg
    items.append({"id": "approvals", "label": "Where approvals reach you", "channel": ch, "done": done,
                  "detail": {"email": "By e-mail, with the 07:35 report", "both": "By e-mail and in Telegram",
                             "app": "In the app only"}.get(ch, "In Telegram" if tg else "Telegram isn't paired yet")})
    return items


# ============================================================================================
# Results
# ============================================================================================

def _post_numbers(p):
    import otto_report
    return otto_report.post_numbers(p.get("metrics"))


def _score(n):
    return _n(n.get("reach")) + 10 * _n(n.get("saves")) + 5 * _n(n.get("clicks")) + 2 * _n(n.get("reactions"))


def _ad_map(d, bid):
    """Meta ad id → what Otto made for it: {campaign, angle (name), style, format, headline, media}; and ad set id → angle."""
    ads, sets = {}, {}
    for c in d.get("campaigns") or []:
        if not isinstance(c, dict) or c.get("brand") != bid:
            continue
        cr = c.get("creatives") if isinstance(c.get("creatives"), dict) else {}
        cells, names = {}, {}
        for con in cr.get("concepts") or []:
            if not isinstance(con, dict):
                continue
            names[str(con.get("angle"))] = con.get("name") or str(con.get("angle") or "")
            for ad in con.get("ads") or []:
                if isinstance(ad, dict) and ad.get("id"):
                    cells[str(ad["id"])] = (con, ad)
        r = c.get("remote") if isinstance(c.get("remote"), dict) else {}
        for ang, st in (r.get("concepts") or {}).items() if isinstance(r.get("concepts"), dict) else ():
            if not isinstance(st, dict):
                continue
            if st.get("adset_id"):
                sets[str(st["adset_id"])] = {"name": names.get(str(ang)) or str(ang), "campaign": c, "active": bool(st.get("active"))}
            for cell_id, x in (st.get("ads") or {}).items():
                if isinstance(x, dict) and x.get("ad_id"):
                    con, ad = cells.get(str(cell_id), ({}, {}))
                    ads[str(x["ad_id"])] = {"campaign": c, "angle": names.get(str(ang)) or str(ang), "cell": str(cell_id),
                                            "style": ad.get("style") or x.get("style"), "format": ad.get("format"),
                                            "headline": ad.get("headline") or "", "media": _ad_media(ad)}
        for i, aid in enumerate(r.get("ad_ids") or []):
            ads.setdefault(str(aid), {"campaign": c, "angle": c.get("name") or "", "cell": None, "style": None, "format": None,
                                      "headline": "", "media": None})
        if r.get("adset_id"):
            sets.setdefault(str(r["adset_id"]), {"name": c.get("name") or "", "campaign": c, "active": True})
    return ads, sets


def _ad_media(ad):
    """A creative's first public file: {"image"} or {"video", "poster"}; planned (not rendered) files are not media yet."""
    for f in (ad or {}).get("files") or []:
        if not isinstance(f, dict) or f.get("planned"):
            continue
        if f.get("kind") == "video":
            v = _public(f.get("file"))
            if v:
                return {"video": v, **({"poster": _public(f.get("poster"))} if _public(f.get("poster")) else {})}
        else:
            i = _public(f.get("file"))
            if i:
                return {"image": i}
    return None


def _sum_rows(rows, key):
    out = {}
    for r in rows:
        k = str(r.get(key) or "")
        if not k:
            continue
        x = out.setdefault(k, {"spend": 0.0, "results": 0.0, "link_clicks": 0, "conv": False, "name": "", "objective": None,
                               "campaign_id": None})
        x["spend"] += _n(r.get("spend"))
        x["link_clicks"] += int(_n(r.get("link_clicks")))
        if r.get("conversion"):
            x["conv"] = True
            x["results"] += _n(r.get("results"))
        x["name"] = r.get({"ad_id": "ad_name", "adset_id": "adset_name"}.get(key, "name")) or r.get("name") or x["name"]
        x["objective"] = r.get("objective") or x["objective"]
        x["campaign_id"] = r.get("campaign_id") or x["campaign_id"]
    return out


def _kind_of(rows_obj, by):
    import otto_metrics
    k = next((k for k in RESULT_KINDS if by.get(k)), None)
    if k:
        return k
    objs = {otto_metrics.KIND_OF_OBJECTIVE.get(otto_metrics.objective(o)) for o in rows_obj}
    return next((k for k in RESULT_KINDS if k in objs), "leads")


def results(d, b, conns, now):
    import otto_metrics
    bid, tz = b["id"], ap.brand_tz(b)
    today = now.astimezone(tz).date()
    yday = today - timedelta(days=1)
    start = yday - timedelta(days=SERIES_DAYS - 1)
    posts = [p for p in d.get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid]
    pub = [(p, _pub_day(p, b, tz)) for p in posts if p.get("status") == "published"]
    pub = [(p, day) for p, day in pub if day]
    started = min((day for _, day in pub), default=None)
    mb = (d.get("metrics") or {}).get(bid) or {}
    base = mb.get("baseline") if isinstance(mb.get("baseline"), dict) else {}
    since = _date(b.get("otto_since")) or _date(base.get("joined"))
    if since and (started is None or since < started):
        started = since
    nums = {p["id"]: _post_numbers(p) for p, _ in pub}
    adsb = (d.get("ads") or {}).get(bid) or {}
    daily = adsb.get("daily") if isinstance(adsb.get("daily"), dict) else {}
    entries = {}                                              # the day the numbers are for → the ads.daily entry
    for k, e in daily.items():
        dk = _date(k)
        if dk and isinstance(e, dict):
            entries[dk - timedelta(days=1)] = e
    paid_day = {k: otto_metrics.paid_day(e) for k, e in entries.items()}
    acct = {}
    for k, v in (mb.get("daily") or {}).items() if isinstance(mb.get("daily"), dict) else ():
        dk = _date(k)
        if dk and isinstance(v, dict):
            acct[dk] = v
    meta_state = _conn_state(_conn(conns, f"meta-{bid}"))
    connected = meta_state == "connected"
    paid_plan = ap.entitled(d, bid, "ads")
    plan = ap.plan_of(d, bid)
    trial_ads = paid_plan and plan["features"].get("ads_launch") is False
    has_account = _ad_account(bid, adsb) or bool(_conn(conns, f"gads-{bid}") and _conn_state(_conn(conns, f"gads-{bid}")) == "connected")
    cur_code = next((_net(e, net)["currency"] for e in daily.values() for net in ("meta", "google")
                     if isinstance(_net(e, net).get("currency"), str)), None) or ap.brand_currency(d, bid)
    ad_map, set_map = _ad_map(d, bid)

    # ---- the daily series (180 days): organic reach by the day a post went out, paid by the day the numbers are for
    reach_s, res_s, spend_s = [], [], []
    by_day = {}
    for p, day in pub:
        by_day.setdefault(day, []).append(p)
    for i in range(SERIES_DAYS):
        day = start + timedelta(days=i)
        if started is None or day < started:
            reach_s.append(None)
        else:
            ps = by_day.get(day) or []
            with_n = [nums[p["id"]] for p in ps if nums.get(p["id"]) and nums[p["id"]].get("reach") is not None]
            reach_s.append(sum(_n(x.get("reach")) for x in with_n) if (with_n or not ps) else None)
        pdx = paid_day.get(day)
        res_s.append(sum(pdx["by"].get(k, 0) for k in RESULT_KINDS) if pdx else None)
        spend_s.append(pdx["spend"] if pdx else None)

    out = {"day": yday.isoformat(), "started": started.isoformat() if started else None, "connected": connected,
           "meta": meta_state, "paid_plan": paid_plan, "trial_ads": bool(trial_ads), "currency": cur_code,
           "updated": {"ads_day": max(daily) if daily else None,
                       "account_at": ((mb.get("account") or {}).get("pulled_at") if isinstance(mb.get("account"), dict) else None)},
           "series": {"start": start.isoformat(), "reach": reach_s, "results": res_s, "spend": spend_s}, "periods": {}}
    out["before"] = before_otto(base)
    any_paid = any(x["spend"] > 0 or sum(x["by"].values()) > 0 for x in paid_day.values())
    out["state"] = "ok" if (pub or any_paid) else "empty"

    for N in PERIODS:
        cur = [yday - timedelta(days=i) for i in range(N)]
        prev = [yday - timedelta(days=N + i) for i in range(N)]
        lo, plo = cur[-1], prev[-1]
        out["periods"][str(N)] = _period(N, cur, prev, lo, plo, yday, pub, nums, started, entries, paid_day, acct, connected,
                                         paid_plan, trial_ads, has_account, cur_code, ad_map, set_map, d, bid)
    return out


def before_otto(base):
    """The 30 days before the brand joined Otto (metrics[brand].baseline, otto_insights) as Meta's own account numbers, or
    None: Instagram accounts reached (unique over the window), interactions, new followers (follows − unfollows, Instagram
    and Facebook) and profile link taps. Shown as context, never compared with the per-post sums above (another measure)."""
    if not isinstance(base, dict) or not (base.get("ig") or base.get("fb")):
        return None
    ig = base.get("ig") if isinstance(base.get("ig"), dict) else {}
    fb = base.get("fb") if isinstance(base.get("fb"), dict) else {}
    f = [ap.num(n.get("follows")) for n in (ig, fb) if ap.num(n.get("follows")) is not None]
    u = [ap.num(n.get("unfollows")) for n in (ig, fb) if ap.num(n.get("unfollows")) is not None]
    out = {"since": str(base.get("since") or "")[:10], "until": str(base.get("until") or "")[:10], "joined": str(base.get("joined") or "")[:10],
           "days": base.get("days"), "final": bool(base.get("final")), "reach": ap.num(ig.get("reach")),
           "interactions": ap.num(ig.get("interactions")), "followers": (sum(f) - sum(u)) if f else None,
           "link_taps": ap.num(ig.get("link_taps"))}
    return out if any(out[k] is not None for k in ("reach", "interactions", "followers", "link_taps")) else None


def _organic(pub, nums, days):
    ds = set(days)
    ps = [p for p, day in pub if day in ds]
    with_n = [nums[p["id"]] for p in ps if nums.get(p["id"])]
    return {"posts": len(ps), "with_numbers": len(with_n), "reach": sum(_n(x.get("reach")) for x in with_n),
            "engagement": sum(_n(x.get("reactions")) + _n(x.get("saves")) for x in with_n),
            "clicks": sum(_n(x.get("clicks")) for x in with_n), "ps": ps}


def _account(acct, days, key_ig, key_fb=None, diff=None):
    """Sum of an Instagram / Facebook account number over the days that have it → (value, days covered)."""
    v, cov = 0.0, 0
    for day in days:
        x = acct.get(day)
        if not x:
            continue
        ig, fb = x.get("ig") if isinstance(x.get("ig"), dict) else {}, x.get("fb") if isinstance(x.get("fb"), dict) else {}
        got = False
        if diff:
            for net in (ig, fb):
                if ap.num(net.get(diff[0])) is not None or ap.num(net.get(diff[1])) is not None:
                    v += _n(net.get(diff[0])) - _n(net.get(diff[1]))
                    got = True
        else:
            if ap.num(ig.get(key_ig)) is not None:
                v += _n(ig.get(key_ig)); got = True
            if key_fb and ap.num(fb.get(key_fb)) is not None:
                v += _n(fb.get(key_fb)); got = True
        cov += got
    return v, cov


def _period(N, cur, prev, lo, plo, yday, pub, nums, started, entries, paid_day, acct, connected, paid_plan, trial_ads,
            has_account, cur_code, ad_map, set_map, d, bid):
    import otto_metrics
    o, op = _organic(pub, nums, cur), _organic(pub, nums, prev)
    prev_ok = bool(started and started <= plo)
    numbers = {}
    if not o["posts"]:
        reach_st = "none"
    elif not o["with_numbers"]:
        reach_st = "pending"
    else:
        reach_st = "ok"
    pv = lambda k: op[k] if prev_ok and op["with_numbers"] else (0 if prev_ok and not op["posts"] else None)
    numbers["reach"] = {"v": o["reach"] if reach_st == "ok" else None, "prev": pv("reach"), "state": reach_st,
                        "posts": o["posts"], "with_numbers": o["with_numbers"]}
    numbers["engagement"] = {"v": o["engagement"] if reach_st == "ok" else None, "prev": pv("engagement"), "state": reach_st}
    # followers gained + link clicks: the Instagram / Facebook account numbers (otto_insights daily), + Facebook post clicks
    fv, fcov = _account(acct, cur, None, diff=("follows", "unfollows"))
    fpv, fpcov = _account(acct, prev, None, diff=("follows", "unfollows"))
    acc_state = "ok" if fcov else ("not_connected" if not connected else "pending")
    numbers["followers"] = {"v": fv if fcov else None, "prev": fpv if fpcov >= N else None, "state": acc_state, "days": fcov}
    lv, lcov = _account(acct, cur, "link_taps")
    lpv, lpcov = _account(acct, prev, "link_taps")
    post_clicks = o["clicks"] if o["with_numbers"] else 0
    lstate = "ok" if (lcov or post_clicks) else ("not_connected" if not connected else "pending")
    numbers["link_clicks"] = {"v": (lv + post_clicks) if lstate == "ok" else None,
                              "prev": (lpv + op["clicks"]) if (lpcov >= N and prev_ok) else None, "state": lstate, "days": lcov}
    # paid
    ce = [paid_day[x] for x in cur if x in paid_day]
    pe = [paid_day[x] for x in prev if x in paid_day]
    cp, pp = otto_metrics.paid_period(ce), otto_metrics.paid_period(pe)
    rows_obj = [r.get("objective") for x in cur if x in entries for r in (_net(entries[x], "meta").get("campaigns") or [])
                if isinstance(r, dict)]
    kind = _kind_of(rows_obj, dict(cp["by"], **{k: v for k, v in pp["by"].items() if not cp["by"].get(k)}))
    if not paid_plan:
        pst = "no_plan"
    elif trial_ads:
        pst = "trial"
    elif ce:
        pst = "ok"
    elif not has_account:
        pst = "not_connected"
    else:
        pst = "pending" if any(c.get("brand") == bid and c.get("status") in ("approved", "live") for c in d.get("campaigns") or []
                               if isinstance(c, dict)) else "idle"
    full_prev = len(pe) >= N
    res = cp["by"].get(kind, 0) if ce else None
    numbers["results"] = {"v": res, "prev": pp["by"].get(kind, 0) if full_prev else None, "state": pst, "kind": kind,
                          "days": len(ce)}
    numbers["spend"] = {"v": cp["spend"] if ce else None, "prev": pp["spend"] if full_prev else None, "state": pst,
                        "currency": cur_code}
    numbers["cost"] = {"v": cp["cost"].get(kind) if ce else None, "prev": pp["cost"].get(kind) if full_prev else None,
                       "state": pst if (not ce or cp["cost"].get(kind) is not None) else "no_results", "kind": kind,
                       "currency": cur_code}
    numbers["ad_clicks"] = {"v": cp["link_clicks"] if ce else None, "prev": pp["link_clicks"] if full_prev else None, "state": pst}

    # best posts (Otto's score: reach + 10×saves + 5×clicks + 2×reactions)
    scored = [(p, nums[p["id"]]) for p in o["ps"] if nums.get(p["id"])]
    scored.sort(key=lambda x: _score(x[1]), reverse=True)
    lead = {k: max((_n(n.get(k)) for _, n in scored), default=0) for k in ("reach", "saves", "clicks", "reactions")}
    best = []
    for p, n in scored[:3]:
        reason = next((w for k, w in (("reach", "Most reached"), ("saves", "Most saves"), ("clicks", "Most clicks"),
                                      ("reactions", "Most reactions")) if lead[k] and _n(n.get(k)) == lead[k]), "")
        best.append({"id": p["id"], "hook": str(p.get("hook_en") or p.get("hook") or "")[:140], "format": p.get("format"),
                     "platform": p.get("platform"), "image": _public(p.get("image")),
                     "reach": n.get("reach"), "saves": n.get("saves"), "clicks": n.get("clicks"), "reactions": n.get("reactions"),
                     "reason": reason})
    # per ad (≤ 14 days kept) and per ad set
    ad_rows, camp_rows, g_rows, ad_days = [], [], [], 0
    for x in cur:
        e = entries.get(x)
        if not e:
            continue
        m = _net(e, "meta")
        if isinstance(m.get("ads"), list):
            ad_days += 1
            ad_rows += [r for r in m["ads"] if isinstance(r, dict)]
        camp_rows += [r for r in m.get("campaigns") or [] if isinstance(r, dict)]
        g = _net(e, "google")
        g_rows += [r for r in g.get("campaigns") or [] if isinstance(r, dict)]
    camp_by_remote = {str((c.get("remote") or {}).get("campaign_id")): c for c in d.get("campaigns") or []
                      if isinstance(c, dict) and c.get("brand") == bid and (c.get("remote") or {}).get("campaign_id")}
    ads = []
    for aid, x in _sum_rows(ad_rows, "ad_id").items():
        info = ad_map.get(aid) or {}
        c = info.get("campaign") or camp_by_remote.get(str(x["campaign_id"])) or {}
        res_ = x["results"] if x["conv"] else None
        ads.append({"ad_id": aid, "name": x["name"], "angle": info.get("angle") or "", "cell": info.get("cell"),
                    "campaign": c.get("name") or "",
                    "style": info.get("style"), "style_label": STYLE_LABEL.get(info.get("style") or "", ""),
                    "format": info.get("format"), "headline": info.get("headline") or "", "media": info.get("media"),
                    "spend": _r2(x["spend"]), "results": res_, "cost": _r2(x["spend"] / res_) if res_ else None,
                    "link_clicks": x["link_clicks"], "status": ad_status(c) if c else "", "kind": kind})
    ads.sort(key=lambda a: (-(a["results"] or 0), a["cost"] if a["cost"] is not None else 1e12, -(a["spend"] or 0)))
    adsets, level = [], "adset"
    if ad_rows:
        for sid, x in _sum_rows(ad_rows, "adset_id").items():
            info = set_map.get(sid) or {}
            c = info.get("campaign") or camp_by_remote.get(str(x["campaign_id"])) or {}
            res_ = x["results"] if x["conv"] else None
            adsets.append({"name": info.get("name") or x["name"], "network": "Meta", "campaign": c.get("name") or "",
                           "spend": _r2(x["spend"]), "link_clicks": x["link_clicks"], "results": res_,
                           "cost": _r2(x["spend"] / res_) if res_ else None, "status": ad_status(c, info.get("active", True)) if c else ""})
    elif camp_rows:
        level = "campaign"
        for cid, x in _sum_rows(camp_rows, "id").items():
            c = camp_by_remote.get(cid) or {}
            res_ = x["results"] if x["conv"] else None
            adsets.append({"name": c.get("name") or x["name"], "network": "Meta", "campaign": "", "spend": _r2(x["spend"]),
                           "link_clicks": x["link_clicks"], "results": res_, "cost": _r2(x["spend"] / res_) if res_ else None,
                           "status": ad_status(c) if c else ""})
    for cid, x in _sum_rows(g_rows, "id").items():
        c = camp_by_remote.get(cid) or {}
        res_ = x["results"]
        adsets.append({"name": c.get("name") or x["name"], "network": "Google", "campaign": "", "spend": _r2(x["spend"]),
                       "link_clicks": x["link_clicks"], "results": res_, "cost": _r2(x["spend"] / res_) if res_ else None,
                       "status": ad_status(c) if c else ""})
    adsets.sort(key=lambda a: -(a["spend"] or 0))
    waiting = sum(1 for p in o["ps"] if not nums.get(p["id"]))
    per = {"days": N, "from": lo.isoformat(), "to": yday.isoformat(), "prev_from": plo.isoformat(), "prev_to": prev[0].isoformat(),
           "numbers": numbers, "posts": o["posts"], "waiting_numbers": waiting, "best_posts": best, "ads": ads[:40],
           "ads_days": ad_days, "adsets": adsets[:30], "adsets_level": level}
    per["summary"] = summary_lines(per, N, cur_code, scored)
    return per


def _change(v, p, N, unit_word=None):
    """", 6 more than the 7 days before" — only when the previous period is there."""
    if p is None or v is None:
        return ""
    before = f"the {N} days before"
    if unit_word:                                              # counts: "3 more" / "2 fewer" / "the same as"
        dv = int(round(v - p))
        if dv == 0:
            return f", as many as {before}"
        return f", {abs(dv)} {'more' if dv > 0 else 'fewer'} than {before}"
    if not p:
        return ""
    pct = (v - p) / p * 100
    if abs(pct) < 1:
        return f", about the same as {before}"
    return f", {'up' if pct > 0 else 'down'} {abs(pct):.0f}% on {before}"


def summary_lines(per, N, cur, scored):
    """What happened, in 1-3 sentences made from the numbers above (templates; nothing else)."""
    nb, out = per["numbers"], []
    r, sp, co = nb["results"], nb["spend"], nb["cost"]
    if r["state"] == "ok" and sp["v"] is not None:
        if r["v"]:
            s = f"You got {_fmt_n(r['v'])} {_word(r['kind'], r['v'])}"
            if co["v"] is not None:
                s += f" at {_money(co['v'], cur)} each"
            out.append(s + _change(r["v"], r["prev"], N, unit_word=True) + ".")
        elif sp["v"]:
            out.append(f"Your ads spent {_money(sp['v'], cur)} and brought no {_word(r['kind'], 2)} in these {N} days.")
    rc = nb["reach"]
    if rc["state"] == "ok":
        s = f"{_fmt_n(rc['posts'])} {'post' if rc['posts'] == 1 else 'posts'} went out"
        s += f" and reached {_fmt_n(rc['v'])} {'person' if rc['v'] == 1 else 'people'}" if rc["v"] else ""
        if rc["with_numbers"] < rc["posts"]:
            s += f" ({rc['with_numbers']} of them have numbers so far)"
        out.append(s + (_change(rc["v"], rc["prev"], N) if rc["with_numbers"] == rc["posts"] else "") + ".")
    elif rc["state"] == "pending":
        out.append(f"{_fmt_n(rc['posts'])} {'post' if rc['posts'] == 1 else 'posts'} went out; Meta reports their numbers "
                   f"24–48 hours after each post.")
    best = per["best_posts"]
    if best and len(scored) >= 2 and best[0]["hook"] and best[0]["reason"]:
        out.append(f"Your best post was “{best[0]['hook'][:80]}” ({best[0]['reason'].lower()}).")
    sets = [a for a in per["adsets"] if a.get("spend") and a.get("network") == "Meta"]
    if r["state"] == "ok" and r["v"] and len(sets) >= 2 and per["adsets_level"] == "adset" and per["ads_days"] >= N:
        top = max(sets, key=lambda a: a.get("results") or 0)
        out.append(f"The “{top['name'][:60]}” ads brought {_fmt_n(top['results'])} of the {_fmt_n(r['v'])} "
                   f"{_word(r['kind'], r['v'])}.")
    return out[:4]


# ============================================================================================
# Review: the month's ads
# ============================================================================================

def _plan_cards(d, bid):
    try:
        import otto_email
        is_plan, month_of = otto_email.is_plan_card, otto_email.plan_month
    except Exception:                                          # noqa: BLE001
        return []
    import otto_api
    return [(r, month_of(r)) for r in d.get("recommendations") or [] if isinstance(r, dict) and r.get("brand") == bid
            and r.get("status") == "proposed" and is_plan(r) and otto_api.rec_visible(r, {bid})]


def ad_review(d, b, now):
    import otto_styles
    bid = b["id"]
    if not ap.entitled(d, bid, "ads"):
        return None
    tz = ap.brand_tz(b)
    ym_now = now.astimezone(tz).date().strftime("%Y-%m")
    cards = _plan_cards(d, bid)
    card = next(((r, m) for r, m in cards if m), cards[0] if cards else None)
    ym = card[1] if card and card[1] else None
    mx = _matrix(bid, ym) if ym else None
    if ym is None:                                      # no plan waiting: next month once its plan is approved, else this month
        nxt = _next_ym(ym_now)
        ahead = any(isinstance(c, dict) and c.get("brand") == bid and _camp_month(c) == nxt and c.get("status") in ("approved", "live")
                    for c in d.get("campaigns") or [])
        for cand in ((nxt, ym_now) if ahead else (ym_now, nxt)):
            mx = _matrix(bid, cand)
            if mx:
                ym = cand
                break
    if ym is None:
        return None
    camps = [c for c in d.get("campaigns") or [] if isinstance(c, dict) and c.get("brand") == bid and _camp_month(c) == ym
             and c.get("status") != "skipped"]
    media = {}
    for c in camps:
        cr = c.get("creatives") if isinstance(c.get("creatives"), dict) else {}
        for con in cr.get("concepts") or []:
            for ad in (con or {}).get("ads") or []:
                if isinstance(ad, dict) and ad.get("id") and _ad_media(ad):
                    media.setdefault(str(ad["id"]), _ad_media(ad))
    angles = []
    for a, cell, i in (_plan_cells(d, bid, mx) if mx else []):
        if not angles or angles[-1]["id"] != a.get("id"):
            heads = [h for h in a.get("headlines") or [] if isinstance(h, str) and h.strip()]
            angles.append({"id": a.get("id"), "name": str(a.get("name") or (heads[0] if heads else f"Angle {len(angles) + 1}")),
                           "family": a.get("family"), "headlines": heads[:2], "cells": []})
        cp = otto_styles.ad_copy(a, cell, i)
        cta = str(cp.get("cta") or "").upper()
        style = otto_styles.resolve(cell.get("style")) or cell.get("style")
        angles[-1]["cells"].append({"id": cell.get("id"), "style": style,
                                    "style_label": STYLE_LABEL.get(style or "") or str(style or "").replace("_", " ").capitalize(),
                                    "format": otto_styles.fmt(cell), "headline": cp["headline"], "primary": cp["primary"],
                                    "description": cp["description"], "cta": cta, "cta_label": CTA_LABEL.get(cta, ""),
                                    "media": media.get(str(cell.get("id")))})
    angles = [a for a in angles if a["cells"]]
    first, last = _month_bounds(ym)
    total, daily_ = 0.0, 0.0
    for c in camps:
        s, e = _date(c.get("start")), _date(c.get("end"))
        if s and e:
            lo, hi = max(s, first), min(e, last)
            if lo <= hi:
                total += _n(c.get("daily_budget")) * ((hi - lo).days + 1)
                daily_ += _n(c.get("daily_budget"))
    st = ("proposed" if card else "live" if any(c.get("status") == "live" for c in camps) else
          "approved" if any(c.get("status") in ("approved", "paused", "ended") for c in camps) else "draft")
    return {"month": ym, "label": _month_label(ym), "plan_rec": card[0]["id"] if card else None, "state": st,
            "trial": ap.plan_of(d, bid)["features"].get("ads_launch") is False, "campaigns": len(camps),
            "budget": {"total": round(total, 2), "daily": round(daily_, 2), "currency": ap.brand_currency(d, bid)} if camps else None,
            "count": sum(len(a["cells"]) for a in angles), "angles": angles}


# ============================================================================================
# the hook otto_api calls
# ============================================================================================

def brand_blocks(d, b, conns, now):
    """{today, ledger, results, ad_review} for one brand (d = the whole data.json, b = its full record); a block that fails
    is left out, the others stay."""
    out, errs = {}, []
    for key, fn in (("today", lambda: today_block(d, b, now)), ("ledger", lambda: ledger(d, b, conns, now)),
                    ("results", lambda: results(d, b, conns, now)), ("ad_review", lambda: ad_review(d, b, now))):
        try:
            out[key] = fn()
        except Exception as e:                                 # noqa: BLE001 — the app works without it
            errs.append(f"{key}: {type(e).__name__}: {e}")
    return out, errs


def _stamp():
    try:
        return ap.DATA.stat().st_mtime_ns
    except OSError:
        return 0


def with_dashboard(view, full=None, now=None, on_error=None):
    """brands[].today / ledger / results / ad_review on an answer of /otto-api/data: a client_view (full = the whole
    data.json it was cut from) or the owner's whole data (full None). Only the answer's own brands are touched, from their
    own records; connections come from the answer (already overlaid with installed credentials). Never fails the request.
    A live answer (now None) is cached for CACHE_TTL seconds per brand and data.json version."""
    src = full if full is not None else view
    live = now is None
    now = now or utcnow()
    conns = view.get("connections") or []
    stamp = _stamp() if live else None
    for b in view.get("brands") or []:
        if not isinstance(b, dict) or not b.get("id"):
            continue
        full_b = ap.brand(src, b["id"]) or b
        key = (b["id"], stamp, json.dumps([c for c in conns if isinstance(c, dict) and str(c.get("id", "")).endswith("-" + b["id"])],
                                          sort_keys=True, default=str)) if live else None
        hit = None
        if key:
            with _cache_lock:
                hit = _cache.get(key)
                if hit and time.monotonic() - hit[0] > CACHE_TTL:
                    hit = None
        if hit:
            blocks, errs = hit[1], []
        else:
            blocks, errs = brand_blocks(src, full_b, conns, now)
            if key:
                with _cache_lock:
                    if len(_cache) > 256:
                        _cache.clear()
                    _cache[key] = (time.monotonic(), blocks)
        for e in errs:
            if on_error:
                on_error(f"dashboard {b['id']} {e}")
        b.update(json.loads(json.dumps(blocks, default=str)))      # a copy: the cache is never shared with an answer
    return view
