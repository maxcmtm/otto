#!/usr/bin/env python3
"""Otto ↔ Meta numbers: the metric map (Graph API v26.0, checked against developers.facebook.com on 02.10.2026) and the
helpers every numbers pull goes through — organic (otto_insights) and paid (otto_ads), read back by the 07:35 report
(otto_report), the owner console (otto_admin) and the app (otto_api client_view → metrics / ads).

  python3 otto_metrics.py map        # print the metric map below
  python3 otto_metrics.py refused    # metrics Meta refused lately (dropped from requests, retried after 30 days)

Version: otto_publish.GRAPH_VERSION (env GRAPH_API_VERSION, default v26.0) — publishing, insights, ads and CAPI ask the same one.

METRIC MAP (what Otto asks Meta for → where it lands)
Instagram account   GET {ig_user_id}/insights period=day metric_type=total_value since/until = one brand-local day (unix)
  reach → ig.reach · views → ig.views · accounts_engaged → ig.engaged · total_interactions → ig.interactions ·
  likes, comments, shares, saves, replies → same names · profile_links_taps → ig.link_taps
  follows_and_unfollows, breakdown=follow_type (own call): FOLLOWER → ig.follows, NON_FOLLOWER → ig.unfollows
  reach, metric_type=time_series (the baseline's daily curve: only reach has a time series)
  GET {ig_user_id}?fields=followers_count,media_count → account.ig.followers / media
  Retired: impressions (21.04.2025 → views); profile_views, website_clicks, email_contacts, phone_call_clicks,
  get_directions_clicks, text_message_clicks (v21, 08.01.2025 → profile_links_taps; website visits come from Otto's own
  UTM links, otto_track). follower_count / online_followers need 100+ followers and are not used. Data lags up to 48 h.
Instagram media     GET {media_id}/insights (lifetime)
  feed + carousel: reach, views, saved → saves, likes, comments, shares, total_interactions → interactions,
                   profile_visits, follows (feed only — carousel albums: the album itself; its children have no insights)
  reel:  reach, views, saved, likes, comments, shares, total_interactions, ig_reels_avg_watch_time → avg_watch_ms,
         ig_reels_video_view_total_time → watch_ms
  story: reach, views, replies, shares, total_interactions, follows, profile_visits — only for 24 h, so stories are pulled
         before they expire (otto_insights.stories, run by the publisher every 15 min). EU stories report replies = 0.
  Retired: impressions, plays, video_views, clips_replays_count, ig_reels_aggregated_all_plays_count → views.
Facebook Page       GET {page_id}/insights period=day since/until (dates; ≤ 90 days a query, 2 years back; Pages with 100+ likes)
  page_media_view → fb.views · page_total_media_view_unique → fb.viewers · page_post_engagements → fb.engagements ·
  page_total_actions → fb.actions · page_views_total → fb.page_views · page_follows → fb.followers (a level) ·
  page_daily_follows → fb.follows · page_daily_unfollows_unique → fb.unfollows
  period=week (weekly job): page_total_media_view_unique → metrics[brand].page_reach_week (was page_impressions_unique)
  GET {page_id}?fields=followers_count,fan_count → metrics[brand].followers
  Retired 15.11.2025 (an invalid-metric error since): page_impressions* → page_media_view / page_total_media_view_unique,
  page_fans* → page_follows, post_impressions* → post_media_view / post_total_media_view_unique.
Facebook post       GET {post_id}/insights: post_total_media_view_unique → reach, post_media_view → views, post_clicks → clicks
                    GET {post_id}?fields=shares,comments.summary(true),reactions.summary(true) → shares, comments, likes
Ads                 GET {act}/insights level=campaign (and level=ad for yesterday), date_preset yesterday | last_7d,
                    use_unified_attribution_setting=true: each ad set's own attribution, i.e. what Ads Manager shows — Meta's
                    default 7-day click + 1-day view (the 7d_view / 28d_view windows stopped returning data 12.01.2026).
  fields: spend, impressions, reach, frequency, cpm, clicks, inline_link_clicks, ctr, cpc, actions, cost_per_action_type,
          purchase_roas (+ ids/names of the level and the campaign objective)
  results by objective (first present action wins — the lists overlap, never sum them): leads `lead` → lead_grouped →
          fb_pixel_lead → complete_registration · sales omni_purchase → purchase → fb_pixel_purchase · engagement
          post_engagement → messaging conversations · traffic landing_page_view → link_click
  leads: `lead` is every lead (instant forms + website); onsite_conversion.lead_grouped (instant forms) and
         offsite_conversion.fb_pixel_lead (website) are its parts — kept as the split leads_form / leads_website, never
         added to `lead` or to each other.
  messaging: onsite_conversion.messaging_conversation_started_7d → messages (per ad and per campaign)
  cost per lead = spend / leads of the same rows; per kind (cost per lead never mixes in sales or Google conversions).

FALLBACK: insights() asks for every metric in one request. When Meta refuses a metric (Graph error 100 with an
invalid-metric message: "must be one of the following values", "valid insights metric", …) the refused metric(s) are
dropped and the rest asked again — named from Meta's message when it says which, else one by one. A refused metric is
logged once (one line in the job's log) and remembered for 30 days per API version in .graph-metrics.json next to
data.json (OTTO_GRAPH_STATE), so the next pulls do not ask for it at all. Error 10 on one metric (e.g. story replies
below 5 interactions) only loses that metric for that request. Anything else (token, permissions, rate limit) is raised to
the caller, which records it and goes on with the next brand / post — one metric never fails a whole pull.
Stdlib only.
"""
import json, os, re, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_publish as pub

REFUSED_TTL = timedelta(days=30)

# ---------------- organic ----------------
IG_ACCOUNT = {"reach": "reach", "views": "views", "accounts_engaged": "engaged", "total_interactions": "interactions",
              "likes": "likes", "comments": "comments", "shares": "shares", "saves": "saves", "replies": "replies",
              "profile_links_taps": "link_taps"}
IG_FOLLOWS = "follows_and_unfollows"                     # breakdown follow_type: FOLLOWER → follows, NON_FOLLOWER → unfollows
IG_FOLLOW_KEYS = {"FOLLOWER": "follows", "NON_FOLLOWER": "unfollows"}
IG_MEDIA = {
    "feed": ["reach", "views", "saved", "likes", "comments", "shares", "total_interactions", "profile_visits", "follows"],
    "carousel": ["reach", "views", "saved", "likes", "comments", "shares", "total_interactions"],
    "reel": ["reach", "views", "saved", "likes", "comments", "shares", "total_interactions", "ig_reels_avg_watch_time",
             "ig_reels_video_view_total_time"],
    "story": ["reach", "views", "replies", "shares", "total_interactions", "follows", "profile_visits"],
}
IG_MEDIA_NAMES = {"saved": "saves", "total_interactions": "interactions", "ig_reels_avg_watch_time": "avg_watch_ms",
                  "ig_reels_video_view_total_time": "watch_ms"}
FB_PAGE_DAY = {"page_media_view": "views", "page_total_media_view_unique": "viewers", "page_post_engagements": "engagements",
               "page_total_actions": "actions", "page_views_total": "page_views", "page_follows": "followers",
               "page_daily_follows": "follows", "page_daily_unfollows_unique": "unfollows"}
FB_PAGE_WEEK = {"page_total_media_view_unique": "page_reach_week", "page_post_engagements": "page_engagements_week"}
FB_LEVELS = {"followers"}                                # a level, not a count: a window keeps its last value, never a sum
FB_POST = {"post_total_media_view_unique": "reach", "post_media_view": "views", "post_clicks": "clicks"}
RETIRED = {                                              # old → new, for the docs, the tests and anyone grepping
    "page_impressions": "page_media_view", "page_impressions_unique": "page_total_media_view_unique",
    "page_fans": "page_follows", "page_fan_adds": "page_daily_follows", "page_fan_removes": "page_daily_unfollows_unique",
    "post_impressions": "post_media_view", "post_impressions_unique": "post_total_media_view_unique",
    "impressions": "views", "plays": "views", "video_views": "views", "profile_views": "profile_links_taps",
    "website_clicks": "otto_track UTM visits", "email_contacts": "profile_links_taps", "phone_call_clicks": "profile_links_taps",
    "get_directions_clicks": "profile_links_taps", "text_message_clicks": "profile_links_taps",
}

# ---------------- paid ----------------
LEAD_TYPES = ["lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"]   # first present wins
LEAD_FORM, LEAD_WEBSITE = "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"
MESSAGES = "onsite_conversion.messaging_conversation_started_7d"
ATTRIBUTION = "7d_click,1d_view"                          # Meta's default; asked through use_unified_attribution_setting
# Meta results by campaign objective, first match wins (the lists overlap, never sum them)
OBJECTIVE_RESULTS = {
    "OUTCOME_LEADS": LEAD_TYPES + ["complete_registration"],
    "OUTCOME_SALES": ["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"],
    "OUTCOME_ENGAGEMENT": ["post_engagement", MESSAGES],
    "OUTCOME_TRAFFIC": ["landing_page_view", "link_click"],
    "OUTCOME_AWARENESS": [],
}
LEGACY_OBJECTIVE = {"LEAD_GENERATION": "OUTCOME_LEADS", "CONVERSIONS": "OUTCOME_SALES", "LINK_CLICKS": "OUTCOME_TRAFFIC",
                    "POST_ENGAGEMENT": "OUTCOME_ENGAGEMENT", "MESSAGES": "OUTCOME_ENGAGEMENT", "REACH": "OUTCOME_AWARENESS",
                    "BRAND_AWARENESS": "OUTCOME_AWARENESS", "PRODUCT_CATALOG_SALES": "OUTCOME_SALES"}
CONVERSION_OBJECTIVES = {"OUTCOME_LEADS", "OUTCOME_SALES"}
RESULT_LABEL = {"OUTCOME_LEADS": "leads", "OUTCOME_SALES": "purchases", "OUTCOME_ENGAGEMENT": "engagements",
                "OUTCOME_TRAFFIC": "landing-page views", "OUTCOME_AWARENESS": "reach"}
RESULT_KINDS = ("leads", "purchases", "conversions")     # what the report counts as results (Google: conversions)
KIND_OF_OBJECTIVE = {"OUTCOME_LEADS": "leads", "OUTCOME_SALES": "purchases", "SEARCH": "conversions"}
AD_FIELDS_CORE = ["spend", "impressions", "reach", "clicks", "inline_link_clicks", "ctr", "cpc", "actions", "purchase_roas"]
AD_FIELDS_MORE = ["frequency", "cpm", "cost_per_action_type"]
LEVEL_FIELDS = {"campaign": ["campaign_id", "campaign_name", "objective"],
                "adset": ["adset_id", "adset_name", "campaign_id", "campaign_name", "objective"],
                "ad": ["ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name", "objective"]}


# ============================================================================================
# Graph errors and the refused-metric memo
# ============================================================================================

INVALID_RE = re.compile(r"must be one of the following values|valid insights metric|invalid metric|"
                        r"does not support the \S+ metric|metric\S* \S+ (?:is|has been) (?:deprecated|retired|removed)|"
                        r"(?:deprecated|retired|no longer (?:available|supported)).{0,40}metric", re.I)
VALID_LIST_RE = re.compile(r"must be one of the following values:\s*([A-Za-z0-9_,\s]+)", re.I)
INDEX_RE = re.compile(r"metric\[(\d+)\]")
_logged = set()                                           # (kind, metric) already logged by this process
_memo = {"mtime": None, "st": {}}


def code_of(e):
    """Meta's error code of a GraphError (100 = invalid parameter / metric, 10 = not enough data, 190 = token …)."""
    c = getattr(e, "code", None)
    if c is None:
        m = re.match(r"Graph (\d+):", str(e))
        c = m.group(1) if m else None
    try:
        return int(c)
    except (TypeError, ValueError):
        return None


def invalid_metric(e):
    """True when Meta refused a request because of a metric name: error 100 with an invalid-metric message."""
    return code_of(e) == 100 and bool(INVALID_RE.search(str(e)))


def state_path():
    return Path(os.environ.get("OTTO_GRAPH_STATE") or ap.DATA.parent / ".graph-metrics.json")


def _state():
    p = state_path()
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    if _memo["mtime"] != mt:
        try:
            st = json.loads(p.read_text())
            _memo.update(mtime=mt, st=st if isinstance(st, dict) else {})
        except (OSError, ValueError):
            _memo.update(mtime=mt, st={})
    return _memo["st"]


def refused(kind, metric, now=None):
    """True while `metric` is remembered as refused for `kind` on this API version (30 days)."""
    rec = (_state().get(pub.GRAPH_VERSION) or {}).get(f"{kind}:{metric}")
    at = ap.parse_iso(rec.get("at")) if isinstance(rec, dict) else None
    if at is None:
        return False
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - at < REFUSED_TTL


def refuse(kind, metric, why, remember=True):
    """Drop `metric` for `kind`: one log line per process, and (remember) 30 days in .graph-metrics.json so the next pulls
    do not ask for it at all — i.e. one line in the job log per retired metric. Never raises."""
    key = f"{kind}:{metric}"
    if key not in _logged:
        _logged.add(key)
        print(f"meta: Meta refused {kind} metric {metric} — dropped{' for 30 days' if remember else ' from this request'}"
              f" ({str(why)[:160]})")
    if not remember:
        return
    try:
        p = state_path()
        try:
            st = json.loads(p.read_text())
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        st.setdefault(pub.GRAPH_VERSION, {})[key] = {"at": ap.now_iso(), "why": str(why)[:240]}
        p.parent.mkdir(parents=True, exist_ok=True)
        ap._atomic_write(p, json.dumps(st, ensure_ascii=False, indent=1) + "\n")
        _memo["mtime"] = None
    except Exception as e:                                     # noqa: BLE001 — the memo is an optimisation
        print(f"meta: refused-metric memo not written ({type(e).__name__})", file=sys.stderr)


def culprits(e, want):
    """The metric(s) Meta's error names as the problem, or [] when it does not say."""
    msg = str(e)
    m = VALID_LIST_RE.search(msg)
    if m:
        valid = {x.strip().lower() for x in m.group(1).split(",") if x.strip()}
        bad = [w for w in want if w.lower() not in valid]
        if bad and (len(bad) < len(want) or len(want) == 1):    # all of them "invalid": a cut-off list, not proof
            return bad
    m = INDEX_RE.search(msg)
    if m and int(m.group(1)) < len(want):
        return [want[int(m.group(1))]]
    named = [w for w in want if re.search(rf"(?<![a-z_]){re.escape(w)}(?![a-z_])", msg)]
    return named if len(named) == 1 else []


def _data(r):
    return [x for x in (r.get("data") or []) if isinstance(x, dict)] if isinstance(r, dict) else []


def insights(obj, tok, metrics, kind, **params):
    """GET {obj}/insights?metric=<metrics> → Graph rows. Refused metrics are dropped (see FALLBACK above); kind names the
    edge for the memo ("ig_user", "fb_page:day", "ig_media:reel" …). Errors that are not about a metric are raised."""
    want = [m for m in dict.fromkeys(metrics) if m and not refused(kind, m)]
    while want:
        try:
            return _data(pub.graph("GET", f"{obj}/insights", tok, metric=",".join(want), **params))
        except pub.GraphError as e:
            if len(want) > 1 and code_of(e) == 10:
                return _one_by_one(obj, tok, want, kind, params)
            if not invalid_metric(e):
                raise
            bad = culprits(e, want) or (want[:] if len(want) == 1 else None)
            if bad is None:
                return _one_by_one(obj, tok, want, kind, params)
            for m in bad:
                refuse(kind, m, e)
            want = [m for m in want if m not in bad]
    return []


def _one_by_one(obj, tok, want, kind, params):
    rows = []
    for m in want:
        try:
            rows += _data(pub.graph("GET", f"{obj}/insights", tok, metric=m, **params))
        except pub.GraphError as e:
            if invalid_metric(e):
                refuse(kind, m, e)
            elif code_of(e) == 10:                             # not enough data for this metric (story replies < 5) — this time
                refuse(kind, m, e, remember=False)
            else:
                raise
    return rows


# ============================================================================================
# parsing
# ============================================================================================

def values(rows):
    """Graph insights rows → {name: number}: total_value.value, else the last of values[] (lifetime / one period).
    Non-numeric values (dicts, strings, None) are skipped."""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        tv = r.get("total_value")
        v = ap.num(tv.get("value")) if isinstance(tv, dict) else None
        if v is None:
            vals = [x for x in r.get("values") or [] if isinstance(x, dict)]
            v = ap.num(vals[-1].get("value")) if vals else None
        if v is not None:
            out[r["name"]] = v
    return out


def rename(vals, names):
    return {names.get(k, k): v for k, v in vals.items() if v is not None and k in names}


def breakdown(rows, name):
    """total_value.breakdowns of metric `name` → {dimension value: number} ("FOLLOWER": 12, "NON_FOLLOWER": 3)."""
    for r in rows or []:
        if not isinstance(r, dict) or r.get("name") != name:
            continue
        out = {}
        for b in ((r.get("total_value") or {}).get("breakdowns") or []):
            for res in (b.get("results") or []) if isinstance(b, dict) else []:
                key = "/".join(str(x) for x in (res.get("dimension_values") or []))
                v = ap.num(res.get("value"))
                if key and v is not None:
                    out[key] = out.get(key, 0) + v
        return out
    return {}


def day_of(end_time):
    """A period=day value's own day: Meta stamps it with the END of the day (end_time 2026-10-02T07:00:00+0000 = 1 Oct)."""
    try:
        return date.fromisoformat(str(end_time)[:10]) - timedelta(days=1)
    except ValueError:
        return None


def by_day(rows):
    """period=day / time_series rows → {name: {date: number}}."""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        for x in r.get("values") or []:
            day = day_of(x.get("end_time")) if isinstance(x, dict) else None
            v = ap.num(x.get("value")) if isinstance(x, dict) else None
            if day is not None and v is not None:
                out.setdefault(r["name"], {})[day] = v
    return out


def window_sums(days, levels=FB_LEVELS):
    """{date: {name: n}} → {name: total}: counts summed, levels (followers) = the last day's value."""
    out = {}
    for day in sorted(days):
        for k, v in (days[day] or {}).items():
            if ap.num(v) is None:
                continue
            out[k] = v if k in levels else out.get(k, 0) + v
    return out


def local_bounds(day, tz):
    """A brand-local day → (since, until) unix seconds: local midnight to the next local midnight."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + timedelta(days=1)
    return int(start.timestamp()), int(datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).timestamp())


# ============================================================================================
# paid
# ============================================================================================

def objective(o):
    o = (o or "").upper()
    return LEGACY_OBJECTIVE.get(o, o)


def ad_fields(level="campaign", core=False):
    return ",".join(LEVEL_FIELDS.get(level, LEVEL_FIELDS["campaign"]) + AD_FIELDS_CORE + ([] if core else AD_FIELDS_MORE))


def actions(x, key="actions"):
    """[{action_type, value}] → {action_type: float}."""
    out = {}
    for a in (x.get(key) or []) if isinstance(x, dict) else []:
        if isinstance(a, dict) and a.get("action_type"):
            v = ap.num(a.get("value"))
            if v is not None:
                out[a["action_type"]] = float(v)
    return out


def lead_count(acts):
    """Leads in one row: `lead` (all leads); without it the first present part. Never a sum of the overlapping types."""
    return next((acts[k] for k in LEAD_TYPES if k in acts), 0.0)


def _f(x, k):
    return float(ap.num(x.get(k)) or 0)


def paid_row(x, level="campaign"):
    """One Ads Insights row → Otto's row (same keys as before + leads, leads_form, leads_website, cost_per_lead, messages,
    cost_per_message, frequency, cpm; per ad also ad / ad set / campaign ids)."""
    acts = actions(x)
    obj = objective(x.get("objective"))
    rtype = next((k for k in OBJECTIVE_RESULTS.get(obj, []) if k in acts), None)
    results = acts.get(rtype, 0.0) if rtype else 0.0
    spend = _f(x, "spend")
    link_clicks = int(ap.num(x.get("inline_link_clicks")) or acts.get("link_click", 0))
    conv = obj in CONVERSION_OBJECTIVES
    roas = x.get("purchase_roas")
    leads, msgs = lead_count(acts), acts.get(MESSAGES, 0.0)
    rid = x.get({"ad": "ad_id", "adset": "adset_id"}.get(level, "campaign_id"))
    name = x.get({"ad": "ad_name", "adset": "adset_name"}.get(level, "campaign_name"))
    row = {"id": str(rid) if rid is not None else "", "name": name or "", "objective": obj,
           "result_type": RESULT_LABEL.get(obj), "conversion": conv, "spend": spend,
           "impressions": int(ap.num(x.get("impressions")) or 0), "reach": int(ap.num(x.get("reach")) or 0),
           "frequency": round(_f(x, "frequency"), 2), "cpm": round(_f(x, "cpm"), 2),
           "clicks": int(ap.num(x.get("clicks")) or 0), "link_clicks": link_clicks, "ctr": _f(x, "ctr"), "results": results,
           "cost_per_result": round(spend / results, 2) if results else None,
           "cpl": round(spend / results, 2) if (conv and results) else None,
           "roas": float(ap.num(roas[0].get("value")) or 0) if isinstance(roas, list) and roas and isinstance(roas[0], dict) else None,
           "leads": leads, "leads_form": acts.get(LEAD_FORM), "leads_website": acts.get(LEAD_WEBSITE),
           "cost_per_lead": round(spend / leads, 2) if leads else None,
           "messages": msgs, "cost_per_message": round(spend / msgs, 2) if msgs else None}
    if level in ("ad", "adset"):
        row.update({k: (str(x[k]) if k.endswith("_id") else x[k]) for k in LEVEL_FIELDS[level] if k.endswith(("_id", "_name"))
                    and x.get(k) is not None})
    return row


def paid_totals(rows):
    """Rows of one network and period → its totals. results = conversions only (leads / purchases on Meta, conversions on
    Google); clicks separate; results_by_type keeps every objective's own result count, labelled; cost_by_type is each
    kind's own spend / its own results; leads = the lead campaigns' results (`lead`), messages summed over every row."""
    spend = sum(r["spend"] for r in rows)
    conv_rows = [r for r in rows if r.get("conversion")]
    res = sum(r["results"] for r in conv_rows)
    conv_spend = sum(r["spend"] for r in conv_rows)
    clicks = sum(r["clicks"] for r in rows)
    link = sum(r.get("link_clicks", 0) for r in rows)
    imps = sum(r["impressions"] for r in rows)
    by_type, kind_spend = {}, {}
    for r in rows:
        if r.get("result_type") and r["results"]:
            by_type[r["result_type"]] = by_type.get(r["result_type"], 0) + r["results"]
        if r.get("conversion") and r.get("result_type"):
            kind_spend[r["result_type"]] = kind_spend.get(r["result_type"], 0) + r["spend"]
    leads = by_type.get("leads", 0)
    msgs = sum(float(ap.num(r.get("messages")) or 0) for r in rows)
    return {"spend": round(spend, 2), "results": res, "results_by_type": by_type, "clicks": clicks, "link_clicks": link,
            "impressions": imps, "cpl": round(conv_spend / res, 2) if res else None,
            "ctr": round(100 * clicks / imps, 2) if imps else 0,
            "cost_by_type": {k: round(kind_spend[k] / by_type[k], 2) for k in kind_spend if by_type.get(k)},
            "leads": leads, "cost_per_lead": round(kind_spend.get("leads", 0) / leads, 2) if leads and kind_spend.get("leads") else None,
            "leads_form": sum(float(ap.num(r.get("leads_form")) or 0) for r in rows if r.get("result_type") == "leads"),
            "leads_website": sum(float(ap.num(r.get("leads_website")) or 0) for r in rows if r.get("result_type") == "leads"),
            "messages": msgs}


def _n0(v):
    return float(ap.num(v) or 0)


def paid_day(entry):
    """One ads[brand].daily entry → the day's paid numbers exactly as every reader shows them (the 07:35 report, the owner
    console, tests): {"spend", "by": {kind: results}, "kind_spend": {kind: spend}, "cost": {kind: spend / results},
    "messages", "link_clicks", "networks"}. Works on entries written before cost_by_type existed (from the campaign rows)."""
    spend, by, kspend, msgs, link = 0.0, {}, {}, 0.0, 0.0
    nets = []
    for net in ("meta", "google"):
        e = (entry or {}).get(net) if isinstance(entry, dict) else None
        if not isinstance(e, dict):
            continue
        nets.append(net)
        y = e.get("yesterday") if isinstance(e.get("yesterday"), dict) else {}
        spend += _n0(y.get("spend"))
        if net == "meta":
            for k, v in (y.get("results_by_type") or {}).items():
                if k in RESULT_KINDS and ap.num(v):
                    by[k] = by.get(k, 0) + float(v)
            rows = [r for r in e.get("campaigns") or [] if isinstance(r, dict)]
            for r in rows:
                k = r.get("result_type") or KIND_OF_OBJECTIVE.get(objective(r.get("objective")))
                if r.get("conversion") and k in RESULT_KINDS:
                    kspend[k] = kspend.get(k, 0) + _n0(r.get("spend"))
            msgs += sum(_n0(r.get("messages")) for r in rows) if rows else _n0(y.get("messages"))
            link += _n0(y.get("link_clicks"))
        else:
            if ap.num(y.get("results")):
                by["conversions"] = by.get("conversions", 0) + float(y["results"])
                kspend["conversions"] = kspend.get("conversions", 0) + _n0(y.get("spend"))
            link += _n0(y.get("clicks"))
    return {"spend": round(spend, 2), "by": by, "kind_spend": {k: round(v, 2) for k, v in kspend.items()},
            "cost": {k: round(kspend[k] / by[k], 2) for k in by if kspend.get(k)}, "messages": msgs,
            "link_clicks": int(link), "networks": nets}


def paid_period(entries):
    """Several paid_day() results (or raw entries) → their sum, with each kind's cost recomputed from the sums."""
    spend, by, kspend, msgs, link = 0.0, {}, {}, 0.0, 0
    for x in entries:
        x = x if isinstance(x, dict) and "kind_spend" in x else paid_day(x)
        spend += x["spend"]
        msgs += x["messages"]
        link += x["link_clicks"]
        for k, v in x["by"].items():
            by[k] = by.get(k, 0) + v
        for k, v in x["kind_spend"].items():
            kspend[k] = kspend.get(k, 0) + v
    return {"spend": round(spend, 2), "by": by, "kind_spend": {k: round(v, 2) for k, v in kspend.items()},
            "cost": {k: round(kspend[k] / by[k], 2) for k in by if kspend.get(k)}, "messages": msgs, "link_clicks": link}


def console_view(daily, ym=None):
    """ads[brand].daily → what the owner console shows: yesterday (the latest entry) and the month so far, in the same
    numbers as the 07:35 report (paid_day): spend, leads, cost per lead, purchases, cost per sale, conversations."""
    def flat(x, day=None):
        return {"day": day, "spend": x["spend"], "leads": x["by"].get("leads", 0), "cost_per_lead": x["cost"].get("leads"),
                "purchases": x["by"].get("purchases", 0), "cost_per_purchase": x["cost"].get("purchases"),
                "conversions": x["by"].get("conversions", 0), "messages": x["messages"], "link_clicks": x["link_clicks"]}
    daily = daily if isinstance(daily, dict) else {}
    days = {}
    for k, e in daily.items():
        try:
            days[(date.fromisoformat(k) - timedelta(days=1)).isoformat()] = e   # filed the day after the numbers
        except ValueError:
            continue
    out = {"yesterday": None, "month": None}
    if days:
        last = max(days)
        out["yesterday"] = flat(paid_day(days[last]), last)
        ym = ym or last[:7]
        month = [paid_day(e) for k, e in days.items() if k.startswith(ym)]
        if month:
            out["month"] = dict(flat(paid_period(month)), day=None, month=ym, days=len(month))
    return out


def print_map():
    print(__doc__.split("METRIC MAP", 1)[1].split("FALLBACK:", 1)[0].strip())


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["map"]:
        print_map()
    elif a[:1] == ["refused"]:
        st = _state()
        for ver, recs in sorted(st.items()):
            for k, rec in sorted((recs or {}).items()):
                print(f"{ver} {k:48} {str((rec or {}).get('at'))[:16]} {str((rec or {}).get('why'))[:100]}")
        if not st:
            print("no refused metrics remembered")
    else:
        print(__doc__)
