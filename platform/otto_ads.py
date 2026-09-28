#!/usr/bin/env python3
"""Otto paid layer — Facebook (Meta) + Google Ads on the same rails as organic.

  otto_ads.py report  [--brand <id>] [--days 7] [--dry] [--no-send]   # daily paid report → data.json + Telegram (07:35)
  otto_ads.py plan    <brand> <YYYY-MM> [--budget 20] [--dry]          # month of campaign flights (the paid Gantt) → campaigns[] drafts + ads-plan md + one rec
  otto_ads.py approve <brand> <YYYY-MM>                                # owner said yes → drafts become approved
  otto_ads.py launch  [--brand <id>] [--dry]                           # approved flights that start today → created on Meta / Google (cron 06:00)
  otto_ads.py guard   [--dry]                                          # CPL rules, ended flights → pause + P0 recommendation (cron daily)
  otto_ads.py pause   <campaign-id>                                    # manual pause (remote + state)

Credentials (per brand, in $OTTO_SECRETS):
  meta-<brand>.json   {"access_token","page_id","ig_user_id","ad_account_id":"act_123","pixel_id":"...","lead_form_id":"..."}
  google-<brand>.json {"client_id","client_secret","refresh_token","developer_token","customer_id":"1234567890","login_customer_id":"..."}
State (data.json, via ap.py): ads[brand] = {connections, targets:{cpl,currency}, daily:{date:{meta:{…},google:{…}}}}
                              campaigns[] = {id, brand, network, name, objective, start, end, daily_budget, currency,
                                             audience, creative, landing_url, status, remote, compliance_hold}
Campaign status: draft → approved → live → paused/ended · failed.  Nothing spends without `approved`.
Meta Marketing API v25 + Google Ads REST v21 (GAQL searchStream / googleAds:mutate). Pure stdlib. --dry never calls out.
"""
import calendar, json, os, re, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import ap
import otto_publish as pub

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
SECRETS = pub.SECRETS
GADS = "https://googleads.googleapis.com/v21"
RESTRICTED = re.compile(r"cbd|hemp|cannab|weight loss|crypto|forex|gambling|casino|pharma|supplement", re.I)
RESULT_ACTIONS = ["lead", "onsite_conversion.lead_grouped", "purchase", "omni_purchase", "complete_registration",
                  "onsite_conversion.messaging_conversation_started_7d", "link_click"]


def today():
    return date.today().isoformat()


# ---------------- credentials ----------------

def meta_creds(bid):
    c = pub.creds(bid)
    return c if c and c.get("ad_account_id") else None


def google_creds(bid):
    f = SECRETS / f"google-{bid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def google_token(g):
    data = urllib.parse.urlencode({"client_id": g["client_id"], "client_secret": g["client_secret"],
                                   "refresh_token": g["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def google_call(g, path, body):
    headers = {"Authorization": "Bearer " + google_token(g), "Content-Type": "application/json"}
    if g.get("developer_token"):
        headers["developer-token"] = g["developer_token"]
    if g.get("login_customer_id"):
        headers["login-customer-id"] = str(g["login_customer_id"])
    req = urllib.request.Request(f"{GADS}/customers/{g['customer_id']}/{path}", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise pub.GraphError(f"Google Ads HTTP {e.code}: {e.read().decode()[:300]}")


def gaql(g, query):
    out = google_call(g, "googleAds:searchStream", {"query": query})
    rows = []
    for chunk in (out if isinstance(out, list) else [out]):
        rows.extend(chunk.get("results", []))
    return rows


# ---------------- reporting ----------------

def meta_insights(c, preset):
    r = pub.graph("GET", f"{c['ad_account_id']}/insights", c["access_token"], level="campaign", date_preset=preset,
                  fields="campaign_id,campaign_name,spend,impressions,reach,clicks,ctr,cpc,actions,cost_per_action_type,purchase_roas",
                  limit="100")
    rows = []
    for x in r.get("data", []):
        acts = {a["action_type"]: float(a["value"]) for a in x.get("actions", [])}
        results = next((acts[k] for k in RESULT_ACTIONS if k in acts), 0.0)
        spend = float(x.get("spend", 0))
        rows.append({"id": x["campaign_id"], "name": x["campaign_name"], "spend": spend, "impressions": int(x.get("impressions", 0)),
                     "reach": int(x.get("reach", 0)), "clicks": int(x.get("clicks", 0)), "ctr": float(x.get("ctr", 0)),
                     "results": results, "cpl": round(spend / results, 2) if results else None,
                     "roas": float(x["purchase_roas"][0]["value"]) if x.get("purchase_roas") else None})
    return rows


def google_insights(g, during):
    rows = gaql(g, f"SELECT campaign.id, campaign.name, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.ctr, "
                   f"metrics.conversions, metrics.conversions_value FROM campaign WHERE segments.date DURING {during} "
                   f"AND campaign.status != 'REMOVED'")
    out = []
    for r in rows:
        m, camp = r.get("metrics", {}), r.get("campaign", {})
        spend = int(m.get("costMicros", 0)) / 1e6
        conv = float(m.get("conversions", 0))
        out.append({"id": str(camp.get("id")), "name": camp.get("name"), "spend": round(spend, 2), "impressions": int(m.get("impressions", 0)),
                    "clicks": int(m.get("clicks", 0)), "ctr": float(m.get("ctr", 0)), "results": conv,
                    "cpl": round(spend / conv, 2) if conv else None})
    return out


def google_terms(g):
    try:
        rows = gaql(g, "SELECT search_term_view.search_term, metrics.clicks, metrics.conversions FROM search_term_view "
                       "WHERE segments.date DURING LAST_7_DAYS ORDER BY metrics.clicks DESC LIMIT 5")
        return [(r["searchTermView"]["searchTerm"], int(r["metrics"].get("clicks", 0))) for r in rows]
    except Exception:
        return []


def totals(rows):
    spend = sum(r["spend"] for r in rows); res = sum(r["results"] for r in rows); clicks = sum(r["clicks"] for r in rows)
    imps = sum(r["impressions"] for r in rows)
    return {"spend": round(spend, 2), "results": res, "clicks": clicks, "impressions": imps,
            "cpl": round(spend / res, 2) if res else None, "ctr": round(100 * clicks / imps, 2) if imps else 0}


def fmt_money(v, cur):
    return f"{cur}{v:,.0f}" if v is not None else "—"


def report(bid=None, days=7, dry=False, send=True):
    d = ap.load()
    lines_all = []
    for b in d["brands"]:
        if bid and b["id"] != bid:
            continue
        adsb = d.setdefault("ads", {}).setdefault(b["id"], {"connections": {}, "targets": {"cpl": None, "currency": "€"}, "daily": {}})
        cur = adsb["targets"].get("currency") or "€"
        m, g = meta_creds(b["id"]), google_creds(b["id"])
        adsb["connections"] = {"meta": bool(m), "google": bool(g)}
        if dry or (not m and not g):
            print(f"{b['id']}: {'dry' if dry else 'no ad credentials'} — meta {bool(m)} google {bool(g)}")
            if not dry:
                continue
        day = {"meta": None, "google": None}
        block = [f"💸 Paid · {b['name']} · {date.today().strftime('%a %d %b')}"]
        if m and not dry:
            try:
                y, w = meta_insights(m, "yesterday"), meta_insights(m, "last_7d")
                ty, tw = totals(y), totals(w)
                day["meta"] = {"yesterday": ty, "week": tw, "campaigns": y}
                best = min([r for r in y if r["cpl"]], key=lambda r: r["cpl"], default=None)
                worst = max([r for r in y if r["cpl"]], key=lambda r: r["cpl"], default=None)
                block.append(f"Meta: spent {fmt_money(ty['spend'], cur)} yesterday (7d {fmt_money(tw['spend'], cur)}) · {ty['results']:.0f} results · "
                             f"CPL {fmt_money(ty['cpl'], cur)} (7d {fmt_money(tw['cpl'], cur)}) · CTR {ty['ctr']}%")
                if best:
                    block.append(f"  ▲ best: “{best['name'][:40]}” CPL {fmt_money(best['cpl'], cur)}")
                if worst and worst is not best:
                    block.append(f"  ▼ watch: “{worst['name'][:40]}” CPL {fmt_money(worst['cpl'], cur)}")
            except pub.GraphError as e:
                block.append(f"Meta: error — {e}")
        if g and not dry:
            try:
                y, w = google_insights(g, "YESTERDAY"), google_insights(g, "LAST_7_DAYS")
                ty, tw = totals(y), totals(w)
                terms = google_terms(g)
                day["google"] = {"yesterday": ty, "week": tw, "campaigns": y, "terms": terms}
                block.append(f"Google: spent {fmt_money(ty['spend'], cur)} · {ty['clicks']} clicks · {ty['results']:.0f} conv · CPA {fmt_money(ty['cpl'], cur)}"
                             + (f" · top term “{terms[0][0]}”" if terms else ""))
            except pub.GraphError as e:
                block.append(f"Google: error — {e}")
        if dry:
            block.append("(dry run — no API calls)")
        adsb["daily"][today()] = day
        # keep 90 days
        for k in sorted(adsb["daily"])[:-90]:
            adsb["daily"].pop(k, None)
        block.append(suggest(d, b["id"], adsb, cur))
        lines_all.append("\n".join(x for x in block if x))
    if not dry:
        ap.save(d)
    text = "\n\n".join(lines_all) or "No paid accounts connected yet."
    print(text)
    if send and not dry and lines_all:
        notify(text)
    return text


def suggest(d, bid, adsb, cur):
    """One concrete action from the last 3 days: file it as a recommendation (→ Telegram card / deck)."""
    days = sorted(adsb["daily"])[-3:]
    metas = [adsb["daily"][k].get("meta") for k in days if adsb["daily"][k].get("meta")]
    if len(metas) < 3:
        return ""
    target = adsb["targets"].get("cpl") or (metas[-1]["week"]["cpl"] or 0) * 1.5
    if not target:
        return ""
    bad = {}
    for m in metas:
        for c in m["campaigns"]:
            if c["cpl"] and c["cpl"] > target:
                bad[c["name"]] = bad.get(c["name"], 0) + 1
    over = [n for n, k in bad.items() if k >= 3]
    if not over:
        return ""
    title = f"Pause “{over[0][:40]}” — CPL above target 3 days running"
    if not any(r["title"] == title and r["status"] == "proposed" for r in d.get("recommendations", [])):
        ap.add_rec(d, "P1", title, f"Target CPL {fmt_money(target, cur)}; this campaign has been above it three days in a row. "
                   "Pausing moves the budget to the best performer.", "Stops the bleed the same day", "Pause it", brand=bid, source="otto_ads")
    return f"Suggested: pause “{over[0][:40]}” (3 days above target CPL) — card sent."


def notify(text):
    try:
        import otto_telegram as tg
        tok, chat = tg.config()
        if tok and chat:
            tg.send(text); return True
    except Exception as e:
        print("telegram send failed:", e)
    try:
        import otto_watch
        return otto_watch.send(text)
    except Exception as e:
        print("openclaw send failed:", e)
    return False


# ---------------- monthly campaign plan (the paid Gantt) ----------------

def profile_bits(bid):
    prof = BRANDS / bid / "brand-profile.md"
    t = prof.read_text() if prof.exists() else ""
    sj = BRANDS / bid / "scan.json"
    s = json.loads(sj.read_text()) if sj.exists() else {}
    industry = s.get("industry", "") or (re.search(r"Industry:\*?\*?\s*(.+)", t).group(1) if re.search(r"Industry:\*?\*?\s*(.+)", t) else "")
    langs = s.get("languages") or []
    countries = ["IL"] if "he" in langs else ["DE", "AT", "CH"] if "de" in langs else ["DE"]
    kws = [h for h in s.get("headings", [])[:6]] + [n for n in s.get("nav", [])[:6]]
    return {"industry": industry, "countries": countries, "restricted": bool(RESTRICTED.search(industry + " " + t[:3000])),
            "url": s.get("final_url") or "", "description": s.get("identity", {}).get("description", ""), "keywords": kws}


def best_creative_posts(d, bid, n=3):
    posts = [p for p in d["posts"] if p["brand"] == bid and p.get("image")]
    scored = sorted(posts, key=lambda p: -((p.get("metrics") or {}).get("reach", 0) + 10 * (p.get("metrics") or {}).get("saves", 0)))
    return scored[:n] if scored else posts[:n]


def new_campaign_id(d):
    n = max([int(c["id"].split("-")[1]) for c in d.get("campaigns", []) if c["id"].startswith("cp-")] or [0]) + 1
    return f"cp-{n:03d}"


def plan(bid, ym, budget=20.0, dry=False):
    d = ap.load()
    b = ap.brand(d, bid)
    assert b, f"unknown brand {bid}"
    existing = [c for c in d.get("campaigns", []) if c["brand"] == bid and c.get("plan") == ym]
    if existing:
        sys.exit(f"{bid} already has {len(existing)} campaigns planned for {ym}")
    y, m = [int(x) for x in ym.split("-")]
    last = calendar.monthrange(y, m)[1]
    bits = profile_bits(bid)
    cur = d.get("ads", {}).get(bid, {}).get("targets", {}).get("currency") or "€"
    creatives = best_creative_posts(d, bid)
    hooks = [p.get("hook", "") for p in d["posts"] if p["brand"] == bid and p.get("hook")][:8]
    flights = []
    # 1. always-on leads/traffic on Meta, whole month
    flights.append({"network": "meta", "name": f"{b['name']} · Evergreen {'leads' if not bits['restricted'] else 'traffic'} · {ym}",
                    "objective": "traffic" if bits["restricted"] else "leads", "start": f"{ym}-01", "end": f"{ym}-{last:02d}",
                    "daily_budget": budget, "audience": {"countries": bits["countries"], "age": [25, 60], "interests": b.get("pillars", [])[:4]},
                    "creative": {"post": creatives[0]["id"]} if creatives else {"post": None}, "compliance_hold": bits["restricted"]})
    # 2. two boosts of the best organic posts, weeks 2 and 4 (5-day flights)
    for i, (s_day, e_day) in enumerate([(8, 12), (22, 26)]):
        src = creatives[min(i + 1, len(creatives) - 1)] if creatives else None
        flights.append({"network": "meta", "name": f"{b['name']} · Boost “{(src or {}).get('hook', 'best post')[:30]}” · w{2 + 2 * i}",
                        "objective": "engagement", "start": f"{ym}-{s_day:02d}", "end": f"{ym}-{min(e_day, last):02d}",
                        "daily_budget": round(budget / 2, 2), "audience": {"countries": bits["countries"], "age": [25, 60], "interests": []},
                        "creative": {"post": (src or {}).get("id")}, "compliance_hold": bits["restricted"]})
    # 3. Google Search — brand + category intent, whole month (skipped for restricted categories)
    if not bits["restricted"]:
        flights.append({"network": "google", "name": f"{b['name']} · Search · {ym}", "objective": "leads", "start": f"{ym}-01", "end": f"{ym}-{last:02d}",
                        "daily_budget": round(budget / 2, 2), "audience": {"countries": bits["countries"]},
                        "creative": {"headlines": [b["name"]] + [h[:30] for h in hooks[:5]] + [bits["industry"][:30]],
                                     "descriptions": [bits["description"][:90]] if bits["description"] else [f"{b['name']} — {bits['industry']}"],
                                     "keywords": [b["name"].lower()] + [k.lower()[:40] for k in bits["keywords"][:8]]}, "compliance_hold": False})
    else:
        print(f"note: {bits['industry']} is a restricted category — Google Search skipped, Meta flights created on compliance hold (needs a compliant lander)")
    total = sum(f["daily_budget"] * ((date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days + 1) for f in flights)
    if dry:
        for f in flights:
            print(f'{f["network"]:6} {f["start"]} → {f["end"]}  {cur}{f["daily_budget"]}/day  {f["objective"]:10} {f["name"]}')
        print(f"-- {len(flights)} flights · ≈{cur}{total:,.0f} for {ym} (dry)")
        return flights
    created = []
    for f in flights:
        c = dict(f, id=new_campaign_id(d), brand=bid, plan=ym, currency=cur, landing_url=bits["url"], status="draft", remote={}, created_at=ap.now_iso())
        d.setdefault("campaigns", []).append(c); created.append(c)
    ap.add_rec(d, "P1", f"Approve the {ym} paid plan: {len(created)} campaigns, ≈{cur}{total:,.0f}",
               "Evergreen on Meta all month, two 5-day boosts of your best organic posts" + (", one Google Search campaign on brand + category intent" if not bits["restricted"] else "") +
               ". Nothing spends until you approve; every campaign has a daily ceiling and a CPL guard.",
               "Paid runs on the same calendar as organic", "Approve plan", brand=bid, source="otto_ads")
    ap.save(d)
    write_plan_md(b, ym, created, cur, total)
    print(f"planned {len(created)} campaigns for {bid} · {ym} (≈{cur}{total:,.0f}) → drafts + recommendation")
    return created


def write_plan_md(b, ym, camps, cur, total):
    path = BRANDS / b["id"] / f"ads-plan-{ym}.md"
    lines = [f"# Paid plan — {b['name']} · {ym} · ≈{cur}{total:,.0f}", "", "| id | network | flight | daily | objective | creative | status |", "|---|---|---|---|---|---|---|"]
    for c in camps:
        cr = c["creative"].get("post") or (", ".join(c["creative"].get("keywords", [])[:3]) + "…")
        lines.append(f"| {c['id']} | {c['network']} | {c['start']} → {c['end']} | {cur}{c['daily_budget']} | {c['objective']} | {cr} | {c['status']}{' · compliance hold' if c.get('compliance_hold') else ''} |")
    path.write_text("\n".join(lines) + "\n")


def approve(bid, ym):
    d = ap.load()
    n = 0
    for c in d.get("campaigns", []):
        if c["brand"] == bid and c.get("plan") == ym and c["status"] == "draft" and not c.get("compliance_hold"):
            c["status"] = "approved"; c["approved_via"] = "cli"; c["decided_at"] = ap.now_iso(); n += 1
    ap.save(d)
    print(f"{n} campaign(s) approved for {bid} · {ym} (compliance-hold flights stay draft)")


# ---------------- launch ----------------

OBJ = {"leads": ("OUTCOME_LEADS", "LEAD_GENERATION"), "traffic": ("OUTCOME_TRAFFIC", "LINK_CLICKS"),
       "sales": ("OUTCOME_SALES", "OFFSITE_CONVERSIONS"), "engagement": ("OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT"),
       "awareness": ("OUTCOME_AWARENESS", "REACH")}


def launch_meta(d, c, m, base):
    objective, opt = OBJ.get(c["objective"], OBJ["traffic"])
    tok, act = m["access_token"], m["ad_account_id"]
    camp = pub.graph("POST", f"{act}/campaigns", tok, name=c["name"], objective=objective, status="PAUSED",
                     special_ad_categories="[]", buying_type="AUCTION")["id"]
    targeting = {"geo_locations": {"countries": c["audience"].get("countries", ["DE"])},
                 "age_min": c["audience"].get("age", [25, 60])[0], "age_max": c["audience"].get("age", [25, 60])[1]}
    adset_params = {"name": c["name"] + " · set A", "campaign_id": camp, "daily_budget": int(round(c["daily_budget"] * 100)),
                    "billing_event": "IMPRESSIONS", "optimization_goal": opt, "status": "PAUSED",
                    "targeting": json.dumps(targeting), "start_time": c["start"] + "T06:00:00+0000", "end_time": c["end"] + "T23:59:00+0000"}
    if c["objective"] == "leads" and m.get("lead_form_id"):
        adset_params["promoted_object"] = json.dumps({"page_id": m["page_id"]})
    elif c["objective"] == "sales" and m.get("pixel_id"):
        adset_params["promoted_object"] = json.dumps({"pixel_id": m["pixel_id"], "custom_event_type": "PURCHASE"})
    adset = pub.graph("POST", f"{act}/adsets", tok, **adset_params)["id"]
    post = ap.post(d, c["creative"].get("post") or "") or {}
    link_data = {"link": c.get("landing_url") or "https://" + (post.get("brand") or ""), "message": (post.get("caption") or post.get("hook") or c["name"])[:1000],
                 "name": (post.get("hook") or c["name"])[:40], "call_to_action": {"type": "LEARN_MORE", "value": {"link": c.get("landing_url") or ""}}}
    if post.get("image"):
        link_data["picture"] = pub.image_url(post, base)
    creative = pub.graph("POST", f"{act}/adcreatives", tok, name=c["name"] + " · creative",
                         object_story_spec=json.dumps({"page_id": m["page_id"], "link_data": link_data}))["id"]
    ad = pub.graph("POST", f"{act}/ads", tok, name=c["name"] + " · ad", adset_id=adset, creative=json.dumps({"creative_id": creative}), status="ACTIVE")["id"]
    pub.graph("POST", adset, tok, status="ACTIVE")
    pub.graph("POST", camp, tok, status="ACTIVE")
    return {"campaign_id": camp, "adset_id": adset, "creative_id": creative, "ad_id": ad}


def launch_google(c, g):
    cr = c["creative"]
    ops = [
        {"campaignBudgetOperation": {"create": {"resourceName": f"customers/{g['customer_id']}/campaignBudgets/-1", "name": c["name"] + " budget",
                                                "amountMicros": str(int(c["daily_budget"] * 1e6)), "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        {"campaignOperation": {"create": {"resourceName": f"customers/{g['customer_id']}/campaigns/-2", "name": c["name"], "status": "ENABLED",
                                          "advertisingChannelType": "SEARCH", "campaignBudget": f"customers/{g['customer_id']}/campaignBudgets/-1",
                                          "maximizeConversions": {}, "startDate": c["start"].replace("-", ""), "endDate": c["end"].replace("-", ""),
                                          "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": False, "targetContentNetwork": False},
                                          "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
        {"adGroupOperation": {"create": {"resourceName": f"customers/{g['customer_id']}/adGroups/-3", "name": c["name"] + " · group A",
                                         "campaign": f"customers/{g['customer_id']}/campaigns/-2", "status": "ENABLED", "type": "SEARCH_STANDARD"}}},
        {"adGroupAdOperation": {"create": {"adGroup": f"customers/{g['customer_id']}/adGroups/-3", "status": "ENABLED",
                                           "ad": {"finalUrls": [c.get("landing_url") or ""],
                                                  "responsiveSearchAd": {"headlines": [{"text": h[:30]} for h in dict.fromkeys(cr.get("headlines", []))[:15] if h],
                                                                         "descriptions": [{"text": t[:90]} for t in dict.fromkeys(cr.get("descriptions", []))[:4] if t]}}}}},
    ]
    for k in dict.fromkeys(cr.get("keywords", []))[:20]:
        if k:
            ops.append({"adGroupCriterionOperation": {"create": {"adGroup": f"customers/{g['customer_id']}/adGroups/-3", "status": "ENABLED",
                                                                   "keyword": {"text": k, "matchType": "PHRASE"}}}})
    return ops


def launch(bid=None, dry=False, base=pub.BASE):
    d = ap.load()
    t = today()
    changed = False
    for c in d.get("campaigns", []):
        if c["status"] != "approved" or (bid and c["brand"] != bid) or c.get("remote") or not (c["start"] <= t <= c["end"]):
            continue
        creds = meta_creds(c["brand"]) if c["network"] == "meta" else google_creds(c["brand"])
        tag = f'{c["id"]} {c["network"]} {c["name"]} ({c["start"]}→{c["end"]}, {c["currency"]}{c["daily_budget"]}/day)'
        if not creds:
            print(f"NO-CREDS {tag}"); continue
        print(f"{'WOULD LAUNCH' if dry else 'LAUNCH'} {tag}")
        if dry:
            if c["network"] == "google":
                print(json.dumps(launch_google(c, creds)[:2], indent=1)[:600] + " …")
            continue
        try:
            if c["network"] == "meta":
                c["remote"] = launch_meta(d, c, creds, base)
            else:
                ops = launch_google(c, creds)
                res = google_call(creds, "googleAds:mutate", {"mutateOperations": ops})
                names = [r.get(k, {}).get("resourceName") for r in res.get("mutateOperationResponses", []) for k in r]
                c["remote"] = {"campaign": next((n for n in names if n and "/campaigns/" in n), None), "all": names}
            c["status"] = "live"; c["launched_at"] = ap.now_iso(); changed = True
        except pub.GraphError as e:
            c["status"] = "failed"; c["error"] = str(e); changed = True
            ap.add_rec(d, "P0", f"Campaign launch failed: {c['name'][:50]}", str(e)[:300], "Budget is not spending", "Open campaign", brand=c["brand"], source="otto_ads")
    if changed:
        ap.save(d)


def set_meta_status(c, m, status):
    if c.get("remote", {}).get("campaign_id"):
        pub.graph("POST", c["remote"]["campaign_id"], m["access_token"], status=status)


def set_google_status(c, g, status):
    rn = c.get("remote", {}).get("campaign")
    if rn:
        google_call(g, "campaigns:mutate", {"operations": [{"update": {"resourceName": rn, "status": status}, "updateMask": "status"}]})


def pause(cid, dry=False):
    d = ap.load()
    c = next((x for x in d.get("campaigns", []) if x["id"] == cid), None)
    assert c, f"unknown campaign {cid}"
    if not dry and c["status"] == "live":
        if c["network"] == "meta":
            set_meta_status(c, meta_creds(c["brand"]), "PAUSED")
        else:
            set_google_status(c, google_creds(c["brand"]), "PAUSED")
    c["status"] = "paused"; c["paused_at"] = ap.now_iso()
    if not dry:
        ap.save(d)
    print(f"{cid} paused")


def guard(dry=False):
    d = ap.load()
    t = today(); changed = False
    for c in d.get("campaigns", []):
        if c["status"] == "live" and c["end"] < t:
            print(f"ENDED {c['id']} {c['name']}")
            if not dry:
                try:
                    (set_meta_status(c, meta_creds(c["brand"]), "PAUSED") if c["network"] == "meta" else set_google_status(c, google_creds(c["brand"]), "PAUSED"))
                except pub.GraphError as e:
                    print("  pause failed:", e)
                c["status"] = "ended"; changed = True
    if changed:
        ap.save(d)
    # CPL rule → recommendations come from report() (suggest); nothing auto-pauses unless ads[brand].auto_pause
    for bid, adsb in d.get("ads", {}).items():
        if adsb.get("auto_pause"):
            for r in d.get("recommendations", []):
                if r.get("source") == "otto_ads" and r["status"] == "proposed" and r["title"].startswith("Pause"):
                    print(f"auto_pause on for {bid}: would act on {r['id']} (implement per campaign id when live)")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "report":
        report(bid=a[a.index("--brand") + 1] if "--brand" in a else None, days=int(a[a.index("--days") + 1]) if "--days" in a else 7,
               dry="--dry" in a, send="--no-send" not in a)
    elif cmd == "plan":
        plan(a[1], a[2], budget=float(a[a.index("--budget") + 1]) if "--budget" in a else 20.0, dry="--dry" in a)
    elif cmd == "approve":
        approve(a[1], a[2])
    elif cmd == "launch":
        launch(bid=a[a.index("--brand") + 1] if "--brand" in a else None, dry="--dry" in a)
    elif cmd == "guard":
        guard(dry="--dry" in a)
    elif cmd == "pause":
        pause(a[1], dry="--dry" in a)
    else:
        print(__doc__)
