#!/usr/bin/env python3
"""Otto morning report — "the 7:35 message": every morning at 07:35 brand-local time the client gets ONE message with what
went out yesterday, what it brought (reach, clicks, enquiries / sales), what paid ads cost against their budget, what is
scheduled today and what is waiting for a decision — in English, or in Dutch / German when the client chose
that (brands[].comms_lang, otto_i18n; never inferred from the language the brand's posts are written in).

  otto_report.py send    --brand B [--channel email|telegram] [--force] [--dry] [--now ISO] [--no-refresh]
  otto_report.py preview --brand B [--channel email|telegram] [--out file] [--text] [--now ISO]   # renders, sends nothing
  otto_report.py status  [--json]                                                                 # last report per brand

Channels follow brands[].approvals (otto_email.approval_channels): "email" → one e-mail per approver (otto_email.send_report:
the report AND the approvals in it — the 07:35 e-mail carries the same signed one-tap links the digest does, and claims the
posts it carries, so the 08:00 `email-cards` run finds nothing left and stays a catch-up); "telegram" → the report as one
Telegram message (otto_watch.send) followed straight away by that brand's approval cards (otto_telegram.send_cards; the
08:00 `cards` run is the catch-up); both → both; "app" → nothing is pushed. Telegram also needs a plan with Telegram.
Plan: the report needs plans.json features.reports; the paid section shows only for a plan with paid ads (a free trial says
its ads are planned for preview and nothing is spent). A brand on the ended plan gets nothing.
Once per brand per local day per channel: claimed in the ledger (.report-state.json next to data.json, OTTO_REPORT_STATE;
flock + atomic replace) before anything is sent — a second run the same local day, or one started while the first is still
sending, sends nothing; a failed send releases the claim so `otto run morning-report --brand B` repeats it; --force sends
again the same day (a fresh claim of another run still wins).
Fresh numbers first (skipped with --no-refresh / --dry): when today's paid numbers are not in data.json yet (the
`ads-report` job pulls them at 07:15) the report pulls them itself (otto_ads.report --no-send), and yesterday's published posts
get their per-post numbers pulled from the Graph API (otto_insights.pull_post). Nothing is invented: a post without numbers
says they follow tomorrow, a brand without an ad account is asked to connect one, an empty day says so in one line.
The job: otto_cron `morning-report` (07:35 brand time, per brand). Stdlib only; data.json writes go through ap.transaction().
"""
import contextlib, fcntl, json, os, re, secrets, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_i18n as i18n

WINDOW_H = 72                     # approvals: posts due within 72 h (the digest's window)
MAX_POSTS = 12                    # posts with buttons per report; the rest wait in the app
CLAIM_TTL = timedelta(minutes=15)
CHANNELS = ("email", "telegram")
LIVE_STATUSES = ("live", "paused", "ended")
TODAY_STATUSES = ("approved", "scheduled", "publishing", "published")
RESULT_KINDS = ("leads", "purchases", "conversions")
OBJ_KIND = {"OUTCOME_LEADS": "leads", "OUTCOME_SALES": "purchases", "SEARCH": "conversions"}


def utcnow():
    return datetime.now(timezone.utc)


def _utc(s):
    dt = ap.parse_iso(s)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) if dt is not None else None


def n0(v):
    return ap.num(v) or 0


# ============================================================================================
# the ledger: once per brand per local day per channel
# ============================================================================================

def state_path():
    return Path(os.environ.get("OTTO_REPORT_STATE") or ap.DATA.parent / ".report-state.json")


def read_state():
    try:
        st = json.loads(state_path().read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def ledger():
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_name(p.name + ".lock"), "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            st = read_state()
            yield st
            if not p.exists():
                os.close(os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o600))
            ap._atomic_write(p, json.dumps(st, ensure_ascii=False, indent=1) + "\n")
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def claim(bid, channel, day, force=False, now=None):
    """→ (True, None) when this run may send `channel` for `day`, else (False, why)."""
    now = now or utcnow()
    with ledger() as st:
        rec = st.setdefault("brands", {}).setdefault(bid, {}).setdefault(channel, {})
        c = _utc(rec.get("claim"))
        if c and now - c < CLAIM_TTL:
            return False, "being sent by another run"
        if rec.get("day") == day and not force:
            return False, f"already sent today ({day})"
        rec["claim"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return True, None


def done(bid, channel, day, info=None):
    with ledger() as st:
        rec = st.setdefault("brands", {}).setdefault(bid, {}).setdefault(channel, {})
        rec.pop("claim", None)
        rec.update(day=day, at=ap.now_iso(), **(info or {}))
        rec["count"] = int(rec.get("count") or 0) + 1


def release(bid, channel):
    with ledger() as st:
        ((st.get("brands") or {}).get(bid) or {}).get(channel, {}).pop("claim", None)


def last(bid, channel=None):
    rec = (read_state().get("brands") or {}).get(bid) or {}
    return rec.get(channel) if channel else rec


# ============================================================================================
# the model: one dict both channels render
# ============================================================================================

def _local(dt, tz):
    return dt.astimezone(tz) if dt else None


def _post_day(p, b):
    """The local day a published post went out: published_at, else its slot."""
    tz = ap.brand_tz(b)
    dt = _utc(p.get("published_at")) or ap.slot_dt(p, b)
    return dt.astimezone(tz).date() if dt else None


def post_numbers(m):
    """posts[].metrics → {reach, clicks, reactions, saves} with only real numbers (None when there is nothing)."""
    if not isinstance(m, dict) or m.get("error") and len([k for k in m if ap.num(m.get(k)) is not None]) == 0:
        return None
    reach, clicks, saves = ap.num(m.get("reach")), ap.num(m.get("clicks")), ap.num(m.get("saves"))
    react = [ap.num(m.get(k)) for k in ("likes", "comments", "shares", "replies")]
    react = [x for x in react if x is not None]
    out = {"reach": reach, "clicks": clicks, "reactions": sum(react) if react else None, "saves": saves}
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _score(n):
    return n0(n.get("reach")) + 10 * n0(n.get("saves")) + 5 * n0(n.get("clicks")) + 2 * n0(n.get("reactions"))


def _creds(bid):
    try:
        import otto_email
        sd = otto_email.secrets_dir()
    except Exception:                                          # noqa: BLE001
        sd = Path(os.environ.get("OTTO_SECRETS") or "")
    return (sd / f"meta-{bid}.json").exists() or (sd / f"google-{bid}.json").exists()


def _flight(c):
    try:
        return (datetime.strptime(str(c.get("start"))[:10], "%Y-%m-%d").date(),
                datetime.strptime(str(c.get("end"))[:10], "%Y-%m-%d").date())
    except (TypeError, ValueError):
        return None, None


def _day_entry(daily, data_day):
    """The ads.daily entry holding `data_day`'s numbers: otto_ads files them under the day the report ran (the day after)."""
    e = daily.get((data_day + timedelta(days=1)).isoformat())
    return e if isinstance(e, dict) else None


def _day_numbers(e):
    """(spend, {kind: results}) for one ads.daily entry."""
    spend, by = 0.0, {}
    for net in ("meta", "google"):
        y = ((e or {}).get(net) or {}).get("yesterday") or {}
        spend += float(n0(y.get("spend")))
        if net == "meta":
            for k, v in (y.get("results_by_type") or {}).items():
                if ap.num(v):
                    by[k] = by.get(k, 0) + float(v)
        elif ap.num(y.get("results")):
            by["conversions"] = by.get("conversions", 0) + float(y["results"])
    return spend, by


def paid(d, b, today, yday, now):
    """The paid section, or None when the brand's plan has no paid ads. state: trial | not_connected | pending | idle | ok."""
    bid = b["id"]
    if not ap.entitled(d, bid, "ads"):
        return None
    if ap.plan_of(d, bid)["features"].get("ads_launch") is False:
        return {"state": "trial"}
    adsb = (d.get("ads") or {}).get(bid) or {}
    daily = adsb.get("daily") if isinstance(adsb.get("daily"), dict) else {}
    camps = [c for c in d.get("campaigns") or [] if isinstance(c, dict) and c.get("brand") == bid]
    upcoming = sorted(s for s, _ in (_flight(c) for c in camps if c.get("status") in ("approved", "live")) if s and s > yday)
    nxt = upcoming[0] if upcoming else None
    entry = daily.get(today.isoformat()) or daily.get(now.astimezone(timezone.utc).date().isoformat())
    conns = adsb.get("connections") or {}
    connected = bool(conns.get("meta") or conns.get("google")) or _creds(bid)
    if not isinstance(entry, dict):
        return {"state": "pending" if connected else "not_connected", "next": nxt}
    ym, yg = entry.get("meta") or {}, entry.get("google") or {}
    tm, tg = ym.get("yesterday") or {}, yg.get("yesterday") or {}
    spend, by = _day_numbers(entry)
    cur = ym.get("currency") or yg.get("currency") or ap.brand_currency(d, bid)
    conv = {k: by[k] for k in RESULT_KINDS if by.get(k)}
    results = sum(conv.values())
    rows = [r for r in ym.get("campaigns") or [] if isinstance(r, dict)]
    conv_spend = sum(float(n0(r.get("spend"))) for r in rows if r.get("conversion")) + float(n0(tg.get("spend")))
    if spend <= 0 and not results:
        return {"state": "idle", "next": nxt}
    kind = next((k for k in RESULT_KINDS if conv.get(k)), None)
    if kind is None:
        objs = {OBJ_KIND.get(r.get("objective")) for r in rows} | ({"conversions"} if tg else set())
        kind = next((k for k in RESULT_KINDS if k in objs), "results")
    budget = 0.0
    for c in camps:
        s, e = _flight(c)
        launched = c.get("status") in LIVE_STATUSES and ((c.get("remote") or {}).get("campaign_id") or c.get("launched_at")
                                                         or c.get("status") == "live")
        if launched and s and e and s <= yday <= e:
            budget += float(n0(c.get("daily_budget")))
    names = {str((c.get("remote") or {}).get("campaign_id")): c.get("name") for c in camps if (c.get("remote") or {}).get("campaign_id")}
    scored = [r for r in rows if r.get("results") and r.get("cost_per_result") is not None and r.get("conversion")]
    best = min(scored, key=lambda r: r["cost_per_result"], default=None)
    best_out = ({"name": names.get(str(best.get("id"))) or best.get("name") or "", "cost": best["cost_per_result"],
                 "kind": OBJ_KIND.get(best.get("objective"), kind)} if best and len(rows) > 1 else None)
    chart = []
    for i in range(6, -1, -1):
        day = yday - timedelta(days=i)
        e = _day_entry(daily, day) if i else entry
        if e is None:
            chart.append({"day": day, "spend": None, "results": None})
        else:
            s_, b_ = _day_numbers(e)
            chart.append({"day": day, "spend": s_, "results": sum(b_.get(k, 0) for k in RESULT_KINDS)})
    prior = [_day_entry(daily, yday - timedelta(days=i)) for i in range(1, 8)]
    prior = [sum(_day_numbers(e)[1].get(k, 0) for k in RESULT_KINDS) for e in prior if e is not None]
    avg7 = round(sum(prior) / len(prior), 1) if len(prior) >= 3 else None
    m_start = yday.replace(day=1)
    starts = [s for s, _ in (_flight(c) for c in camps if c.get("status") in LIVE_STATUSES) if s]
    first = max(m_start, min(starts)) if starts else m_start
    days = [first + timedelta(days=i) for i in range((yday - first).days + 1)]
    month = None
    if days and all(_day_entry(daily, x) is not None or x == yday for x in days):
        spent = sum(_day_numbers(_day_entry(daily, x) if x != yday else entry)[0] for x in days)
        m_end = (m_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        planned = 0.0
        for c in camps:
            s, e = _flight(c)
            if c.get("status") in ("approved",) + LIVE_STATUSES and s and e:
                lo, hi = max(s, m_start), min(e, m_end)
                if lo <= hi:
                    planned += float(n0(c.get("daily_budget"))) * ((hi - lo).days + 1)
        month = {"spent": spent, "planned": planned} if planned > 0 else None
    return {"state": "ok", "spend": spend, "currency": cur, "results": results, "by": conv, "kind": kind,
            "cost": round(conv_spend / results, 2) if results and conv_spend else None,
            "link_clicks": int(n0(tm.get("link_clicks")) + n0(tg.get("clicks"))), "budget": budget or None,
            "best": best_out, "chart": chart if sum(1 for x in chart if x["spend"] is not None) >= 3 else None,
            "avg7": avg7, "month": month, "networks": [n for n in ("meta", "google") if entry.get(n)], "next": nxt}


def _rec_visible(r, bid):
    try:
        import otto_api
        return otto_api.rec_visible(r, {bid})
    except Exception:                                          # noqa: BLE001 — never show an owner card by accident
        return isinstance(r, dict) and r.get("brand") == bid and r.get("audience") != "owner" and r.get("source") != "otto_admin"


def is_plan_card(r):
    import otto_email
    return otto_email.is_plan_card(r)


def decisions(d, b, now):
    """What waits for the client: pending posts due within WINDOW_H that pass compliance (sorted by slot), the paid-plan
    card(s) and the other client-visible P0 / P1 recommendations."""
    import otto_compliance as comp
    bid = b["id"]
    due, later = [], 0
    for p in sorted((p for p in d.get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid
                     and p.get("status") == "pending_approval"), key=lambda x: str(x.get("slot") or "")):
        slot = ap.slot_dt(p, b)
        if slot is None or slot <= now:
            continue
        if slot > now + timedelta(hours=WINDOW_H):
            later += 1
            continue
        try:
            if comp.check_post(p):
                continue                                   # held for compliance: a card explains it, no button here
        except Exception:                                  # noqa: BLE001 — an unreadable rule file holds the post too
            continue
        due.append(p)
    recs = [r for r in d.get("recommendations") or [] if isinstance(r, dict) and r.get("brand") == bid
            and r.get("status") == "proposed" and r.get("priority") in ("P0", "P1") and _rec_visible(r, bid)]
    recs.sort(key=lambda r: (r.get("priority") != "P0", str(r.get("id"))))
    return {"posts": due[:MAX_POSTS], "more": max(0, len(due) - MAX_POSTS) + later,
            "plans": [r for r in recs if is_plan_card(r)], "recs": [r for r in recs if not is_plan_card(r)][:6]}


def drops_for(bid):
    try:
        import otto_watch
        return [(k, v, base) for brand, k, v, base in otto_watch.drops(otto_watch.history()) if brand == bid]
    except Exception:                                          # noqa: BLE001 — a heads-up line never stops the report
        return []


def model(d, b, now=None):
    now = now or utcnow()
    t = i18n.Tr.for_brand(b)
    tz = ap.brand_tz(b)
    loc = now.astimezone(tz)
    today, yday = loc.date(), loc.date() - timedelta(days=1)
    bid = b["id"]
    posts = [p for p in d.get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid]
    out_y = [p for p in posts if p.get("status") == "published" and _post_day(p, b) == yday]
    out_y.sort(key=lambda p: str(_local(_utc(p.get("published_at")) or ap.slot_dt(p, b), tz) or ""))
    rows = [{"post": p, "numbers": post_numbers(p.get("metrics")), "best": False} for p in out_y]
    with_n = [r for r in rows if r["numbers"]]
    if len(with_n) >= 2:
        max(with_n, key=lambda r: _score(r["numbers"]))["best"] = True
    organic = None
    if with_n:
        organic = {"posts": len(with_n), "reach": sum(n0(r["numbers"].get("reach")) for r in with_n),
                   "clicks": sum(n0(r["numbers"].get("clicks")) for r in with_n),
                   "reactions": sum(n0(r["numbers"].get("reactions")) for r in with_n)}
    failed = sum(1 for p in posts if p.get("status") == "failed" and (ap.slot_dt(p, b) or now).astimezone(tz).date() == yday)
    ever = any(p.get("status") == "published" for p in posts)
    today_posts = sorted((p for p in posts if (p.get("status") in TODAY_STATUSES or (p.get("status") == "pending_approval"
                                                                                     and (ap.slot_dt(p, b) or now) > now))
                          and ap.slot_dt(p, b) and ap.slot_dt(p, b).astimezone(tz).date() == today), key=lambda p: ap.slot_dt(p, b))
    upcoming = sorted((p for p in posts if p.get("status") in ("approved", "scheduled", "pending_approval")
                       and ap.slot_dt(p, b) and ap.slot_dt(p, b) > now),
                      key=lambda p: (ap.slot_dt(p, b)))
    m = {"brand": b, "name": b.get("name") or bid, "t": t, "now": now, "loc": loc, "today": today, "yesterday": yday,
         "yday": rows, "organic": organic, "failed": failed, "ever": ever, "today_posts": today_posts,
         "first": upcoming[0] if (not ever and upcoming) else None,
         "paid": paid(d, b, today, yday, now), "decisions": decisions(d, b, now), "drops": drops_for(bid)}
    m["summary"] = summary(m)
    return m


# ============================================================================================
# words shared by both channels
# ============================================================================================

def where(t, p):
    import otto_email
    fmt = p.get("format") or ""
    return " · ".join(x for x in (otto_email.PLAT.get(p.get("platform"), p.get("platform") or ""),
                                  t("fmt." + fmt) if t.has("fmt." + fmt) else "") if x)


def hook_of(p, n=90):
    import otto_email
    return (p.get("hook") or "").strip() or otto_email.short((p.get("caption") or "").split("\n")[0], n)


def results_phrase(t, by):
    parts = [t("res." + k, n=int(round(by[k]))) for k in RESULT_KINDS if by.get(k)]
    return t.join(parts) if parts else t("report.sum.no_results")


def n_waiting(m):
    dc = m["decisions"]
    return len(dc["posts"]), len(dc["plans"]) + len(dc["recs"])


def summary(m):
    """The opening lines — the ad's "Goedemorgen. Gisteren: € 18 aan advertenties, 4 aanvragen. 3 posts wachten op je."."""
    t, p = m["t"], m["paid"]
    parts = [t("report.greeting")]
    if p and p.get("state") == "ok":
        parts.append(t("report.sum.paid", spend=t.money(p["spend"], p["currency"]), results=results_phrase(t, p["by"])))
    if m["yday"] and not (p and p.get("state") == "ok"):
        if m["organic"] and m["organic"]["reach"]:
            parts.append(t("report.sum.organic_reach", n=len(m["yday"]), reach=t.num(m["organic"]["reach"])))
        else:
            parts.append(t("report.sum.organic", n=len(m["yday"])))
    elif not m["yday"] and not (p and p.get("state") == "ok"):
        parts.append(t("report.sum.starting") if not m["ever"] else t("report.sum.quiet"))
    posts, other = n_waiting(m)
    if posts and other:
        parts.append(t("report.sum.both", posts=t("noun.post", n=posts), decisions=t("noun.decision", n=other)))
    elif posts:
        parts.append(t("report.sum.waiting", n=posts))
    elif other:
        parts.append(t("report.sum.decisions", n=other))
    else:
        parts.append(t("report.sum.clear"))
    return " ".join(parts)


def subject(m):
    t = m["t"]
    posts, other = n_waiting(m)
    tail = t("report.subject_waiting", n=posts + other) if posts + other else t("report.subject_clear")
    return t("report.subject", day=t.day(m["loc"]), name=m["name"]) + " · " + tail


def numbers_line(t, n):
    """"1.240 bereikt · 32 klikken · 18 reacties" — only the numbers that exist."""
    if not n:
        return ""
    bits = []
    if n.get("reach") is not None:
        bits.append(t("m.reach", n=n["reach"]))
    if n.get("clicks"):
        bits.append(t("m.clicks", n=n["clicks"]))
    if n.get("reactions"):
        bits.append(t("m.reactions", n=n["reactions"]))
    if n.get("saves"):
        bits.append(t("m.saves", n=n["saves"]))
    return " · ".join(bits)


def first_line(t, b, f):
    """A client with nothing published yet: when the first post goes out (or that it waits for their OK)."""
    if not f:
        return t("report.first_none")
    loc = ap.slot_dt(f, b).astimezone(ap.brand_tz(b))
    return t("report.first_pending" if f.get("status") == "pending_approval" else "report.first_post", day=t.day(loc), time=t.time(loc))


def cost_line(t, kind, amount, cur):
    return t(("report.cost_line." + kind) if t.has("report.cost_line." + kind) else "report.cost_line.results", cost=t.money(amount, cur, 2))


def today_suffix(t, q):
    st = q.get("status")
    return f" ({t('report.today_done')})" if st == "published" else f" ({t('report.today_waiting')})" if st == "pending_approval" else ""


def kind_label(t, kind):
    return t("kpi." + kind) if t.has("kpi." + kind) else t("kpi.results")


def cost_phrase(t, kind, amount, cur):
    return t(("cost." + kind) if t.has("cost." + kind) else "cost.results", cost=t.money(amount, cur, 2))


def budget_line(t, p):
    if not p.get("budget"):
        return ""
    b = t.money(p["budget"], p["currency"])
    return t("kpi.within_budget", budget=b) if p["spend"] <= p["budget"] * 1.005 else t("kpi.over_budget", budget=b)


def paid_lines(t, p):
    """The paid section as plain lines (the e-mail renders the same facts as tiles)."""
    st = p.get("state")
    if st == "trial":
        return [t("report.paid.trial")]
    if st == "not_connected":
        return [t("report.paid.not_connected")]
    if st == "pending":
        return [t("report.paid.pending")]
    if st == "idle":
        return [t("report.paid.idle")] + ([t("report.paid.next", day=t.day(p["next"]))] if p.get("next") else [])
    lines = [" · ".join(x for x in (f"{t('kpi.spent')} {t.money(p['spend'], p['currency'])}", budget_line(t, p)) if x)]
    res = [results_phrase(t, p["by"])]
    if p.get("cost"):
        res.append(cost_phrase(t, p["kind"], p["cost"], p["currency"]))
    if p.get("avg7") is not None:
        res.append(t("kpi.avg7", avg=t.num(p["avg7"], 0 if float(p["avg7"]).is_integer() else 1)))
    lines.append(" · ".join(res))
    if p.get("best"):
        lines.append(t("report.best_ad", name=p["best"]["name"], cost=cost_phrase(t, p["best"]["kind"], p["best"]["cost"], p["currency"])))
    if p.get("month"):
        lines.append(t("report.month", spent=t.money(p["month"]["spent"], p["currency"]), planned=t.money(p["month"]["planned"], p["currency"])))
    return lines


def rec_text(t, r, field):
    """A recommendation's title / why / impact in the brand's language when the engine filed it with an i18n key."""
    spec = r.get("i18n") if isinstance(r.get("i18n"), dict) else None
    if spec and spec.get("key") and t.has(f"{spec['key']}.{field}"):
        try:
            args = {k: (t.num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
                    for k, v in (spec.get("args") or {}).items()}
            return t(f"{spec['key']}.{field}", **args)
        except (KeyError, IndexError, ValueError):
            pass
    return r.get(field) or ""


def plan_title(t, r):
    import otto_email
    return t("plan.title", month=t.month(otto_email.plan_month(r)))


def plan_campaigns(d, b, r):
    import otto_email
    return [c for c in d.get("campaigns") or [] if isinstance(c, dict) and c.get("brand") == b["id"]
            and c.get("plan") == otto_email.plan_month(r)]


def plan_summary(t, camps, cur):
    """"2 campagnes, ca. € 900 · max. € 25 per dag · 1 nov t/m 30 nov" from the campaigns themselves."""
    if not camps:
        return ""
    total, per_day, starts, ends = 0.0, 0.0, [], []
    for c in camps:
        s, e = _flight(c)
        daily = float(n0(c.get("daily_budget")))
        per_day += daily
        if s and e:
            total += daily * ((e - s).days + 1)
            starts.append(s)
            ends.append(e)
    bits = [t("plan.summary", n=len(camps), total=t.money(round(total), cur))]
    if per_day:
        bits.append(t("plan.max_day", amount=t.money(per_day, cur)))
    if starts:
        bits.append(t("plan.dates", start=t.day_month(min(starts)), end=t.day_month(max(ends))))
    return " · ".join(bits)


# ============================================================================================
# Telegram
# ============================================================================================

def telegram_text(m, app=None):
    """The report as one plain-text Telegram message (no Markdown: a parse error would drop it)."""
    t, b, tz = m["t"], m["brand"], ap.brand_tz(m["brand"])
    if app is None:
        import otto_email
        app = otto_email.app_url()
    L = [f"{t('report.title')} · {m['name']}", f"{t.long_day(m['loc'])} · {t.time(m['loc'])}", "", m["summary"]]
    p = m["paid"]
    y = []
    if p:
        y += paid_lines(t, p)
    for r in m["yday"]:
        q = r["post"]
        when = _local(_utc(q.get("published_at")) or ap.slot_dt(q, b), tz)
        line = f"· {t.time(when) if when else ''} {where(t, q)}: {hook_of(q, 70)}"
        nl = numbers_line(t, r["numbers"])
        line += f" — {nl}" if nl else f" — {t('m.pending')}"
        if r["best"]:
            line += f" ({t('report.best_post')})"
        y.append(line)
    if m["failed"]:
        y.append(t("report.failed", n=m["failed"]))
    for k, v, base in m["drops"][:2]:
        y.append(t("report.drop", metric=t("metric." + k) if t.has("metric." + k) else k, value=t.num(v), avg=t.num(base)))
    if not m["yday"] and not m["ever"]:
        y.append(first_line(t, b, m["first"]))
    if y:
        L += ["", t("report.yesterday")] + y
    dc = m["decisions"]
    w = []
    if dc["posts"]:
        w.append("· " + t("tg.cards", n=len(dc["posts"])))
    for r in dc["plans"]:
        w.append("· " + plan_title(t, r))
    for r in dc["recs"]:
        w.append("· " + rec_text(t, r, "title"))
    if w:
        L += ["", t("report.waiting")] + w
    if m["today_posts"]:
        L += ["", t("report.today")]
        for q in m["today_posts"][:8]:
            when = ap.slot_dt(q, b).astimezone(tz)
            L.append(f"· {t.time(when)} {where(t, q)}: {hook_of(q, 70)}" + today_suffix(t, q))
    L += ["", t("tg.open", url=app)]
    return "\n".join(L)[:4000]


def send_telegram(bid, now=None, dry=False, force=False):
    """The Telegram report for one brand, then its approval cards. → {"sent": bool, "skipped": why | None, "failed": bool}."""
    import otto_email
    now = now or utcnow()
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        return {"sent": False, "skipped": "unknown brand", "failed": True}
    if "telegram" not in otto_email.approval_channels(b):
        return {"sent": False, "skipped": "approvals are not in Telegram", "failed": False}
    if not ap.plan_of(d, bid)["features"].get("telegram"):
        return {"sent": False, "skipped": f"plan {ap.plan_of(d, bid)['id']} has no Telegram", "failed": False}
    day = now.astimezone(ap.brand_tz(b)).date().isoformat()
    m = model(d, b, now)
    text = telegram_text(m)
    if dry:
        print(f"{bid}: WOULD SEND telegram report ({len(text)} chars)\n{text}")
        return {"sent": False, "skipped": "dry", "failed": False}
    ok, why = claim(bid, "telegram", day, force, now)
    if not ok:
        print(f"{bid}: telegram report — {why}")
        return {"sent": False, "skipped": why, "failed": False}
    try:
        import otto_watch
        sent = otto_watch.send(text)
    except Exception:
        release(bid, "telegram")
        raise
    if not sent:
        release(bid, "telegram")
        print(f"{bid}: telegram report FAILED (no bot reached)")
        return {"sent": False, "skipped": None, "failed": True}
    done(bid, "telegram", day, {"chars": len(text), "lang": m["t"].lang})
    print(f"SENT    {bid} telegram report")
    if m["decisions"]["posts"]:
        try:                                               # the cards follow the report: one morning moment
            import otto_telegram
            otto_telegram.send_cards(bid=bid, now=now)
        except Exception as e:                             # noqa: BLE001 — the 08:00 `cards` run catches up
            print(f"  cards after the report failed: {type(e).__name__}: {str(e)[:160]}")
    return {"sent": True, "skipped": None, "failed": False}


# ============================================================================================
# fresh numbers
# ============================================================================================

def refresh(bid, now=None):
    """Pull what the report needs and is not in data.json yet: yesterday's paid numbers (when the 07:15 ads-report has
    not landed) and the per-post numbers of yesterday's posts. Network errors are printed, never raised."""
    now = now or utcnow()
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        return
    tz = ap.brand_tz(b)
    today = now.astimezone(tz).date()
    p = paid(d, b, today, today - timedelta(days=1), now)
    if p and p.get("state") == "pending":
        try:
            import otto_ads
            if otto_ads.meta_creds(bid) or otto_ads.google_creds(bid):
                otto_ads.report(bid=bid, send=False)
        except Exception as e:                                 # noqa: BLE001
            print(f"  paid numbers not pulled: {type(e).__name__}: {str(e)[:160]}")
    try:
        import otto_insights, otto_publish
        c = otto_publish.creds(bid)
    except Exception as e:                                     # noqa: BLE001
        print(f"  post numbers not pulled: {type(e).__name__}")
        return
    if not c:
        return
    yday = today - timedelta(days=1)
    got = {}
    for q in d.get("posts") or []:
        if not (isinstance(q, dict) and q.get("brand") == bid and q.get("status") == "published" and q.get("remote_id")
                and _post_day(q, b) in (yday, today)):
            continue
        pulled = _utc((q.get("metrics") or {}).get("pulled_at"))
        if pulled and now - pulled < timedelta(hours=3):
            continue
        try:
            mm = otto_insights.pull_post(q, c)
        except Exception as e:                                 # noqa: BLE001
            print(f"  {q['id']}: numbers not pulled ({type(e).__name__})")
            continue
        if mm:
            mm["pulled_at"] = ap.now_iso()
            got[q["id"]] = mm
    if got:
        with ap.transaction() as d2:
            for pid, mm in got.items():
                q = ap.post(d2, pid)
                if q is not None:
                    merged = {k: v for k, v in (q.get("metrics") or {}).items() if k != "error"}
                    merged.update(mm)
                    q["metrics"] = merged
        print(f"  {len(got)} post(s): numbers pulled")


# ============================================================================================
# orchestration (the cron job)
# ============================================================================================

def skip_reason(d, b):
    """Why this brand gets no morning report at all, or None."""
    import otto_email
    bid = b["id"]
    if ap.plan_ended(d, bid):
        return "no active plan (membership ended)"
    plan = ap.plan_of(d, bid)
    if not plan["features"].get("reports"):
        return f"plan {plan['id']} has no reports"
    if not otto_email.approval_channels(b):
        return "approvals in the app only (brands[].approvals)"
    return None


def send(bid, now=None, dry=False, force=False, channels=None, refresh_numbers=True, verify_media=True):
    """The 07:35 report for one brand on each of its channels. → {"email": …, "telegram": …, "failed": bool}."""
    import otto_email
    now = now or utcnow()
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        print(f"unknown brand {bid}")
        return {"failed": True}
    why = skip_reason(d, b)
    if why:
        print(f"{bid}: no morning report — {why}")
        return {"failed": False, "skipped": why}
    chans = [c for c in otto_email.approval_channels(b) if channels is None or c in channels]
    if refresh_numbers and not dry:
        refresh(bid, now)
        try:
            import otto_watch
            otto_watch.snapshot(ap.load())
        except Exception as e:                                 # noqa: BLE001
            print(f"  metrics snapshot failed: {type(e).__name__}")
    out = {"failed": False}
    if "email" in chans:
        r = otto_email.send_report(bid, now=now, dry=dry, force=force, verify_media=verify_media)
        out["email"] = r
        out["failed"] |= bool(r.get("failed"))
    if "telegram" in chans:
        r = send_telegram(bid, now=now, dry=dry, force=force)
        out["telegram"] = r
        out["failed"] |= bool(r.get("failed"))
    return out


def preview(bid, channel="email", out=None, text=False, now=None):
    import otto_email
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        raise SystemExit(f"unknown brand {bid}")
    now = now or utcnow()
    m = model(d, b, now)
    if channel == "telegram":
        body, subj = telegram_text(m), "(telegram)"
    else:
        cfg = otto_email.safe_config()
        subj, h, tx = otto_email.render_report(b, m, "preview@example.invalid", cfg, now, otto_email.link_secrets(cfg)[0], verify=False)
        body = tx if text else h
    if out:
        Path(out).write_text(body)
        print(f"{subj} → {out}")
    else:
        print(body)


def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def main(a):
    cmd = a[0] if a else ""
    now = _utc(_opt(a, "--now")) if _opt(a, "--now") else None
    if cmd == "send" and _opt(a, "--brand"):
        ch = _opt(a, "--channel")
        r = send(_opt(a, "--brand"), now=now, dry="--dry" in a, force="--force" in a, channels=[ch] if ch else None,
                 refresh_numbers="--no-refresh" not in a)
        return 1 if r.get("failed") else 0
    if cmd == "preview" and _opt(a, "--brand"):
        preview(_opt(a, "--brand"), _opt(a, "--channel", "email"), _opt(a, "--out"), "--text" in a, now)
        return 0
    if cmd == "status":
        st = read_state().get("brands") or {}
        if "--json" in a:
            print(json.dumps(st, ensure_ascii=False, indent=1))
            return 0
        for bid, rec in sorted(st.items()):
            print(f"  {bid:16} " + "  ".join(f"{ch} {((rec.get(ch) or {}).get('day') or '—')}" for ch in CHANNELS))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
