#!/usr/bin/env python3
"""Otto paid layer — Facebook (Meta) + Google Ads on the same rails as organic.

  otto_ads.py report  [--brand <id>] [--days 7] [--dry] [--no-send]   # daily paid report → data.json + Telegram (07:35)
  otto_ads.py plan    <brand> <YYYY-MM> [--budget 20] [--dry]          # month of campaign flights (the paid Gantt) → campaigns[] drafts + ads-plan md + one rec
  otto_ads.py approve <brand> <YYYY-MM>                                # owner said yes → drafts become approved
  otto_ads.py launch  [--brand <id>] [--dry]                           # approved flights that start today → created on Meta / Google (cron 06:00)
  otto_ads.py guard   [--dry]                                          # CPL rules, ended flights → pause + P0 recommendation (cron daily);
                                                                       # plan downgrades / expiries → live campaigns paused (plan_guard)
  otto_ads.py pause   <campaign-id>                                    # manual pause (remote + state)
  otto_ads.py resume  <campaign-id>                                    # paused → live again (remote + state); an ended flight → ended
  otto_ads.py release <campaign-id>                                    # clear a compliance hold once the copy passes otto_compliance
  otto_ads.py retry   <campaign-id>                                    # failed → approved; the next launch resumes from campaign.remote

Credentials (per brand, in $OTTO_SECRETS):
  meta-<brand>.json   {"access_token","page_id","ig_user_id","ad_account_id":"act_123","pixel_id":"...","lead_form_id":"..."}
  google-<brand>.json {"client_id","client_secret","refresh_token","developer_token","customer_id":"1234567890","login_customer_id":"..."}
Brand settings (data.json brands[]): currency (ISO; default scan commerce.currency, else EUR), countries, special_ad_categories
  (Meta list, e.g. ["EMPLOYMENT"]), landing (url or {"cold","warm","hot"}), keywords ({"brand":[…],"generic":[…]} — Google
  only ever uses this explicit list, never site nav/headings; brands/<slug>/keywords.json works too), tz.
State (data.json, via ap.transaction): ads[brand] = {connections, targets:{cpl}, daily:{date:{meta:{…},google:{…}}}}
                              campaigns[] = {id, brand, network, name, objective, start, end, daily_budget, currency, currency_code,
                                             audience, creative, landing_url, status, remote, compliance_hold}
Campaign status: draft → approved → live → paused/ended · failed · skipped (a boost whose post is not live on Facebook).
paused_by says who paused it ("kill_switch", "brand", "manual" …): the owner console's kill switch resumes only the
campaigns it paused itself. While the kill switch is on or the brand is paused, nothing launches — checked again inside
each campaign's claim, and a campaign that went live while the switch was flipped is paused straight away.
Nothing spends without `approved`. Compliance: every launch runs otto_compliance on the copy first; a violation puts the
campaign on compliance hold and files a recommendation (`release` clears it once the copy is fixed).
Free trial (plans.json features.ads_launch false): the month is planned and its creatives rendered for preview as usual, but
launch / resume refuse every campaign of the brand (ap.no_launch_why) until a paid plan replaces the trial.
Plans (plans.json via ap.plan_of): plan refuses a brand whose plan has no paid ads, plans only the networks the plan has
(ads_meta / ads_google), takes the Meta ad-matrix preset from the plan (micro still wins under ~€36/day) and treats
limits.ad_spend_managed_eur_month as a soft cap (ap.ad_band): the first month above it is planned in full and the card says
so; the second month in a row above it every flight is scaled down to the cap and the card offers the next plan; a plan
with overage (scale) is planned in full and the card shows the fee on the spend above it (never billed by Otto). The month's
decision is kept on brands[].ad_band. launch / resume refuse a campaign whose network the plan does not cover. guard (daily) also files
the one owner card for an expired plan and pauses, through pause() (paused_by "plan"), every live campaign the brand's plan
no longer covers — a downgrade, an expiry or an ended membership — with a card that says so. A broken plans.json pauses
nothing: paid work is refused until it is fixed, and the owner gets one P0 card.
Meta launch is resumable: every created object id is saved into campaign.remote the moment it exists, and a re-run
continues from there (no duplicate campaigns / ad sets). Reporting counts Meta results per campaign objective (leads,
purchases, engagements, landing-page views) and reports link clicks separately — clicks are never "results".
Meta Marketing API v25 + Google Ads REST v21 (GAQL searchStream / googleAds:mutate). Pure stdlib. --dry never calls out.
"""
import base64, calendar, json, math, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_paths as paths
import otto_publish as pub

HERE = Path(__file__).parent
BRANDS = ap.BRANDS
SECRETS = pub.SECRETS
GADS = "https://googleads.googleapis.com/v21"
# categories where paid needs a human first (Meta special/restricted categories, policy-sensitive verticals)
RESTRICTED = re.compile(r"cbd|hemp|cannab|weight loss|crypto|bitcoin|forex|gambling|casino|betting|pharma|prescription|"
                        r"therap|mental health|psychotherap|psycholog|counsel+ing|employment|job (ad|opening|offer)s?|"
                        r"recruit|hiring|vacanc|housing|rental|mortgage|\bcredit\b|\bloans?\b|lending|"
                        r"טיפול רגשי|בריאות נפשית|פסיכותרפ|תרפי", re.I)
# Meta results by campaign objective, first match wins (the lists overlap, never sum them)
OBJECTIVE_RESULTS = {
    "OUTCOME_LEADS": ["lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "complete_registration"],
    "OUTCOME_SALES": ["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"],
    "OUTCOME_ENGAGEMENT": ["post_engagement", "onsite_conversion.messaging_conversation_started_7d"],
    "OUTCOME_TRAFFIC": ["landing_page_view", "link_click"],
    "OUTCOME_AWARENESS": [],
}
LEGACY_OBJECTIVE = {"LEAD_GENERATION": "OUTCOME_LEADS", "CONVERSIONS": "OUTCOME_SALES", "LINK_CLICKS": "OUTCOME_TRAFFIC",
                    "POST_ENGAGEMENT": "OUTCOME_ENGAGEMENT", "MESSAGES": "OUTCOME_ENGAGEMENT", "REACH": "OUTCOME_AWARENESS",
                    "BRAND_AWARENESS": "OUTCOME_AWARENESS", "PRODUCT_CATALOG_SALES": "OUTCOME_SALES"}
CONVERSION_OBJECTIVES = {"OUTCOME_LEADS", "OUTCOME_SALES"}
RESULT_LABEL = {"OUTCOME_LEADS": "leads", "OUTCOME_SALES": "purchases", "OUTCOME_ENGAGEMENT": "engagements",
                "OUTCOME_TRAFFIC": "landing-page views", "OUTCOME_AWARENESS": "reach"}
# Meta budgets are in the account currency's minor units ("offset" 100) except these (offset 1). The HUF entry
# follows Meta's currency table as we understand it — verify against act?fields=currency on the first HUF account.
ZERO_DECIMAL = {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}
# Google Ads geo target constants (country criterion id = 2000 + ISO 3166 numeric) and language constants
GEO = {"DE": 2276, "AT": 2040, "CH": 2756, "IL": 2376, "FR": 2250, "IT": 2380, "ES": 2724, "NL": 2528, "BE": 2056,
       "LU": 2442, "PL": 2616, "PT": 2620, "IE": 2372, "DK": 2208, "SE": 2752, "NO": 2578, "FI": 2246, "CZ": 2203,
       "SK": 2703, "HU": 2348, "RO": 2642, "BG": 2100, "GR": 2300, "HR": 2191, "SI": 2705, "EE": 2233, "LV": 2428,
       "LT": 2440, "GB": 2826, "US": 2840}
LANG_CONST = {"en": 1000, "de": 1001, "fr": 1002, "es": 1003, "it": 1004, "nl": 1010, "pt": 1014, "ar": 1019, "hu": 1024,
              "he": 1027, "pl": 1030, "ru": 1031, "ro": 1032}
FALLBACK_HEADLINES = {"en": ["Official Site", "Learn More Today", "Get in Touch"],
                      "de": ["Offizielle Website", "Jetzt mehr erfahren", "Kontakt aufnehmen"],
                      "he": ["האתר הרשמי", "לפרטים נוספים", "דברו איתנו היום"],
                      "pt": ["Site oficial", "Saiba mais hoje", "Fale connosco"],
                      "nl": ["Officiële website", "Meer informatie", "Neem contact op"],
                      "it": ["Sito ufficiale", "Scopri di più", "Contattaci oggi"],
                      "fr": ["Site officiel", "En savoir plus", "Contactez-nous"],
                      "es": ["Sitio oficial", "Más información", "Contáctanos hoy"]}
# a shop's Search ad sells: "Get in Touch" / "Talk to our team" are lead-gen lines
SHOP_HEADLINES = {"en": ["Official Store", "Shop Online Today", "Order Online"],
                  "de": ["Offizieller Shop", "Jetzt online bestellen", "Online bestellen"],
                  "he": ["החנות הרשמית", "הזמינו אונליין", "קנו עכשיו באתר"],
                  "pt": ["Loja oficial", "Compre online hoje", "Encomende online"],
                  "nl": ["Officiële webshop", "Bestel vandaag online", "Online bestellen"],
                  "it": ["Negozio ufficiale", "Acquista online oggi", "Ordina online"],
                  "fr": ["Boutique officielle", "Commandez en ligne", "Achetez en ligne"],
                  "es": ["Tienda oficial", "Compra online hoy", "Pide online"]}
SHOP_DESCRIPTIONS = {"en": ["Order online from the official store.", "See the full range on the official site."],
                     "de": ["Jetzt im offiziellen Shop bestellen.", "Das ganze Sortiment auf der offiziellen Website."],
                     "he": ["הזמינו אונליין מהחנות הרשמית.", "כל המוצרים באתר הרשמי."],
                     "pt": ["Encomende online na loja oficial.", "Veja toda a gama no site oficial."],
                     "nl": ["Bestel online in de officiële webshop.", "Bekijk het hele assortiment op de officiële site."],
                     "it": ["Ordina online dal negozio ufficiale.", "Scopri tutta la gamma sul sito ufficiale."],
                     "fr": ["Commandez sur la boutique officielle.", "Toute la gamme sur le site officiel."],
                     "es": ["Pide online en la tienda oficial.", "Descubre toda la gama en el sitio oficial."]}
FALLBACK_DESCRIPTIONS = {"en": ["Find out more on our official site.", "Talk to our team today."],
                         "de": ["Mehr erfahren auf unserer offiziellen Website.", "Sprechen Sie noch heute mit uns."],
                         "he": ["כל הפרטים באתר הרשמי.", "השאירו פרטים ונחזור אליכם."],
                         "pt": ["Saiba mais no nosso site oficial.", "Fale hoje com a nossa equipa."],
                         "nl": ["Lees meer op onze officiële website.", "Neem vandaag contact op met ons team."],
                         "it": ["Scopri di più sul nostro sito ufficiale.", "Parla oggi con il nostro team."],
                         "fr": ["Découvrez-en plus sur notre site officiel.", "Parlez à notre équipe dès aujourd'hui."],
                         "es": ["Descubre más en nuestro sitio oficial.", "Habla hoy con nuestro equipo."]}


class LaunchError(Exception):
    pass


class Skipped(Exception):
    pass


def today(b=None):
    """The brand's local calendar date (flights are brand-local dates; the server's own date is a day off around
    midnight). Without a brand: UTC."""
    return datetime.now(ap.brand_tz(b) if b else timezone.utc).date().isoformat()


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
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        hint = " — the refresh token was revoked or expired: reconnect Google Ads" if "invalid_grant" in body else ""
        raise pub.GraphError(f"Google OAuth HTTP {e.code}: {body}{hint}")
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise pub.GraphError(f"Google OAuth failed: {e}")


def google_call(g, path, body):
    headers = {"Authorization": "Bearer " + google_token(g), "Content-Type": "application/json"}
    if g.get("developer_token"):
        headers["developer-token"] = g["developer_token"]
    if g.get("login_customer_id"):
        headers["login-customer-id"] = str(g["login_customer_id"]).replace("-", "")
    cust = str(g["customer_id"]).replace("-", "")
    req = urllib.request.Request(f"{GADS}/customers/{cust}/{path}", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise pub.GraphError(f"Google Ads HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")


def gaql(g, query):
    out = google_call(g, "googleAds:searchStream", {"query": query})
    rows = []
    for chunk in (out if isinstance(out, list) else [out]):
        rows.extend(chunk.get("results", []))
    return rows


_acct = {}


def meta_account_currency(m):
    """ISO currency the ad account bills in (act?fields=currency)."""
    act = m["ad_account_id"]
    if act not in _acct:
        r = pub.graph("GET", act, m["access_token"], fields="currency")
        _acct[act] = (r.get("currency") or "").upper() or None
    return _acct[act]


def minor_units(amount, currency):
    return int(round(float(amount) * (1 if (currency or "").upper() in ZERO_DECIMAL else 100)))


# ---------------- reporting ----------------

def _objective(o):
    o = (o or "").upper()
    return LEGACY_OBJECTIVE.get(o, o)


def meta_insights(c, preset):
    r = pub.graph("GET", f"{c['ad_account_id']}/insights", c["access_token"], level="campaign", date_preset=preset,
                  fields="campaign_id,campaign_name,objective,spend,impressions,reach,clicks,inline_link_clicks,ctr,cpc,actions,purchase_roas",
                  limit="100")
    rows = []
    for x in r.get("data", []):
        acts = {}
        for a in x.get("actions", []) or []:
            v = ap.num(a.get("value"))
            if v is not None:
                acts[a["action_type"]] = float(v)
        obj = _objective(x.get("objective"))
        rtype = next((k for k in OBJECTIVE_RESULTS.get(obj, []) if k in acts), None)
        results = acts.get(rtype, 0.0) if rtype else 0.0
        spend = float(ap.num(x.get("spend")) or 0)
        link_clicks = int(ap.num(x.get("inline_link_clicks")) or acts.get("link_click", 0))
        conv = obj in CONVERSION_OBJECTIVES
        roas = x.get("purchase_roas")
        rows.append({"id": x["campaign_id"], "name": x["campaign_name"], "objective": obj, "result_type": RESULT_LABEL.get(obj),
                     "conversion": conv, "spend": spend, "impressions": int(ap.num(x.get("impressions")) or 0),
                     "reach": int(ap.num(x.get("reach")) or 0), "clicks": int(ap.num(x.get("clicks")) or 0),
                     "link_clicks": link_clicks, "ctr": float(ap.num(x.get("ctr")) or 0), "results": results,
                     "cost_per_result": round(spend / results, 2) if results else None,
                     "cpl": round(spend / results, 2) if (conv and results) else None,
                     "roas": float(ap.num(roas[0].get("value")) or 0) if roas else None})
    return rows


def google_insights(g, during):
    rows = gaql(g, f"SELECT campaign.id, campaign.name, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.ctr, "
                   f"metrics.conversions, metrics.conversions_value FROM campaign WHERE segments.date DURING {during} "
                   f"AND campaign.status != 'REMOVED'")
    out = []
    for r in rows:
        m, camp = r.get("metrics", {}), r.get("campaign", {})
        spend = int(m.get("costMicros", 0)) / 1e6
        conv = float(ap.num(m.get("conversions")) or 0)
        out.append({"id": str(camp.get("id")), "name": camp.get("name"), "objective": "SEARCH", "result_type": "conversions",
                    "conversion": True, "spend": round(spend, 2), "impressions": int(m.get("impressions", 0)),
                    "clicks": int(m.get("clicks", 0)), "link_clicks": int(m.get("clicks", 0)), "ctr": float(ap.num(m.get("ctr")) or 0),
                    "results": conv, "cost_per_result": round(spend / conv, 2) if conv else None, "cpl": round(spend / conv, 2) if conv else None})
    return out


def google_terms(g):
    try:
        rows = gaql(g, "SELECT search_term_view.search_term, metrics.clicks, metrics.conversions FROM search_term_view "
                       "WHERE segments.date DURING LAST_7_DAYS ORDER BY metrics.clicks DESC LIMIT 5")
        return [(r["searchTermView"]["searchTerm"], int(r["metrics"].get("clicks", 0))) for r in rows]
    except Exception:
        return []


def totals(rows):
    """results = conversions only (leads / purchases on Meta, conversions on Google); clicks separate;
    results_by_type keeps every objective's own result count, labelled."""
    spend = sum(r["spend"] for r in rows)
    conv_rows = [r for r in rows if r.get("conversion")]
    res = sum(r["results"] for r in conv_rows)
    conv_spend = sum(r["spend"] for r in conv_rows)
    clicks = sum(r["clicks"] for r in rows)
    link = sum(r.get("link_clicks", 0) for r in rows)
    imps = sum(r["impressions"] for r in rows)
    by_type = {}
    for r in rows:
        if r.get("result_type") and r["results"]:
            by_type[r["result_type"]] = by_type.get(r["result_type"], 0) + r["results"]
    return {"spend": round(spend, 2), "results": res, "results_by_type": by_type, "clicks": clicks, "link_clicks": link,
            "impressions": imps, "cpl": round(conv_spend / res, 2) if res else None,
            "ctr": round(100 * clicks / imps, 2) if imps else 0}


def report(bid=None, days=7, dry=False, send=True):
    snap = ap.load()
    per_brand, lines_all = {}, []
    for b in snap["brands"]:
        if bid and b["id"] != bid:
            continue
        cur = ap.brand_currency(snap, b["id"])
        m, g = meta_creds(b["id"]), google_creds(b["id"])
        if dry or (not m and not g):
            print(f"{b['id']}: {'dry' if dry else 'no ad credentials'} — meta {bool(m)} google {bool(g)}")
            if not dry:
                per_brand[b["id"]] = {"connections": {"meta": bool(m), "google": bool(g)}}
                continue
        day = {"meta": None, "google": None}
        block = [f"💸 Paid · {b['name']} · {date.today().strftime('%a %d %b')}"]
        issues = []
        if m and not dry:
            try:
                mcur = meta_account_currency(m) or cur
                y, w = meta_insights(m, "yesterday"), meta_insights(m, "last_7d")
                ty, tw = totals(y), totals(w)
                day["meta"] = {"yesterday": ty, "week": tw, "campaigns": y, "currency": mcur}
                conv = [r for r in y if r["cpl"]]
                best = min(conv, key=lambda r: r["cpl"], default=None)
                worst = max(conv, key=lambda r: r["cpl"], default=None)
                other = " · ".join(f"{v:.0f} {k}" for k, v in ty["results_by_type"].items() if k not in ("leads", "purchases"))
                block.append(f"Meta: spent {ap.money(ty['spend'], mcur)} yesterday (7d {ap.money(tw['spend'], mcur)}) · "
                             f"{ty['results']:.0f} leads/purchases · CPL {ap.money(ty['cpl'], mcur)} (7d {ap.money(tw['cpl'], mcur)}) · "
                             f"{ty['link_clicks']} link clicks · CTR {ty['ctr']}%" + (f" · {other}" if other else ""))
                if best:
                    block.append(f"  ▲ best: “{best['name'][:40]}” CPL {ap.money(best['cpl'], mcur)}")
                if worst and worst is not best:
                    block.append(f"  ▼ watch: “{worst['name'][:40]}” CPL {ap.money(worst['cpl'], mcur)}")
            except Exception as e:
                block.append(f"Meta: error — {str(e)[:200]}")
        if g and not dry:
            try:
                y, w = google_insights(g, "YESTERDAY"), google_insights(g, "LAST_7_DAYS")
                ty, tw = totals(y), totals(w)
                terms = google_terms(g)
                # currency: the brand's (Google reports in the customer's currency — keep them the same account-side)
                day["google"] = {"yesterday": ty, "week": tw, "campaigns": y, "terms": terms, "currency": cur}
                block.append(f"Google: spent {ap.money(ty['spend'], cur)} · {ty['clicks']} clicks · {ty['results']:.0f} conversions · "
                             f"CPA {ap.money(ty['cpl'], cur)}" + (f" · top term “{terms[0][0]}”" if terms else ""))
            except Exception as e:
                block.append(f"Google: error — {str(e)[:200]}")
                if "invalid_grant" in str(e) or "OAuth" in str(e):
                    issues.append(str(e))
        if dry:
            block.append("(dry run — no API calls)")
        per_brand[b["id"]] = {"connections": {"meta": bool(m), "google": bool(g)}, "day": day, "block": block, "cur": cur, "issues": issues}
    if dry:
        text = "\n\n".join("\n".join(v["block"]) for v in per_brand.values() if v.get("block")) or "No paid accounts connected yet."
        print(text)
        return text
    with ap.transaction() as d:
        for b_id, v in per_brand.items():
            adsb = d.setdefault("ads", {}).setdefault(b_id, {"connections": {}, "targets": {"cpl": None}, "daily": {}})
            adsb.setdefault("targets", {}).setdefault("cpl", None)
            adsb.setdefault("daily", {})
            adsb["connections"] = v["connections"]
            if "day" not in v:
                continue
            adsb["daily"][today()] = v["day"]
            for k in sorted(adsb["daily"])[:-90]:           # keep 90 days
                adsb["daily"].pop(k, None)
            v["block"].append(suggest(d, b_id, adsb, (v["day"].get("meta") or {}).get("currency") or v["cur"]))
            for msg in v["issues"]:
                ap.add_rec_once(d, "P0", f"Reconnect Google Ads for {(ap.brand(d, b_id) or {}).get('name', b_id)}", msg[:300],
                                "Google reporting and launches are blocked until then", "Reconnect", brand=b_id, source="otto_ads")
            lines_all.append("\n".join(x for x in v["block"] if x))
    text = "\n\n".join(lines_all) or "No paid accounts connected yet."
    print(text)
    if send and lines_all:
        notify(text)
    return text


def suggest(d, bid, adsb, cur):
    """One concrete action from the last 3 days: file it as a recommendation (→ Telegram card / deck).
    The card carries campaign_id so approving it pauses exactly that campaign."""
    days = sorted(adsb["daily"])[-3:]
    metas = [adsb["daily"][k].get("meta") for k in days if adsb["daily"][k].get("meta")]
    if len(metas) < 3:
        return ""
    target = adsb.get("targets", {}).get("cpl") or ((metas[-1].get("week") or {}).get("cpl") or 0) * 1.5
    if not target:
        return ""
    bad, names = {}, {}
    for m in metas:
        for c in m.get("campaigns", []):
            if c.get("cpl") and c["cpl"] > target:
                bad[c["id"]] = bad.get(c["id"], 0) + 1; names[c["id"]] = c["name"]
    over = [rid for rid, k in bad.items() if k >= 3]
    if not over:
        return ""
    rid = over[0]
    ours = next((c for c in d.get("campaigns", []) if str((c.get("remote") or {}).get("campaign_id")) == str(rid)), None)
    title = f"Pause “{names[rid][:40]}” — CPL above target 3 days running"
    ap.add_rec_once(d, "P1", title, f"Target CPL {ap.money(target, cur)}; this campaign has been above it three days in a row. "
                    "Pausing moves the budget to the best performer.", "Stops the bleed the same day", "Pause it", brand=bid,
                    source="otto_ads", action="pause_campaign", campaign_id=ours["id"] if ours else None, remote_campaign_id=rid)
    return f"Suggested: pause “{names[rid][:40]}” (3 days above target CPL) — card sent."


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

def profile_bits(bid, b=None):
    prof = BRANDS / bid / "brand-profile.md"
    t = prof.read_text() if prof.exists() else ""
    s = ap.scan_of(bid)
    im = re.search(r"Industry:\*?\*?\s*(.+)", t)
    industry = s.get("industry", "") or (im.group(1) if im else "")
    langs = s.get("languages") or []
    countries = ap.brand_countries(b or {"id": bid}, langs)       # brands[].countries → url TLD → site language
    # restricted = what the business IS (scan industry, the profile's explicit Industry line, declared Meta special
    # categories) — never any word anywhere in the profile ("referral credit", "no weight-loss claims" are not a category)
    basis = " ".join([industry, im.group(1) if im else "", " ".join((b or {}).get("special_ad_categories") or [])])
    return {"industry": industry, "countries": countries, "restricted": bool(RESTRICTED.search(basis)),
            "shop": is_shop(s, industry),
            "url": clean_landing(s.get("final_url") or ""), "description": s.get("identity", {}).get("description", ""),
            "lang": ap.brand_lang(b or {"id": bid})}


SHOP_PLATFORMS = re.compile(r"shopify|woocommerce|magento|bigcommerce|shopware|prestashop|wix stores|squarespace commerce", re.I)
SHOP_INDUSTRIES = re.compile(r"e-commerce|retail|supplement|nutrition|cbd|beauty products|fashion|apparel", re.I)


def is_shop(scan, industry):
    """An online shop sells at checkout: its paid objective is purchases (pixel PURCHASE), not leads."""
    plat = str((scan or {}).get("platform") or "")
    has_prices = bool(((scan or {}).get("commerce") or {}).get("prices"))
    return bool(SHOP_PLATFORMS.search(plat) or (SHOP_INDUSTRIES.search(industry or "") and has_prices))


def clean_landing(u):
    """Scan URLs carry cache-busters (?v=…): ads get the bare page."""
    if not u:
        return ""
    p = urllib.parse.urlsplit(u.strip())
    return urllib.parse.urlunsplit((p.scheme or "https", p.netloc, p.path or "/", "", ""))


def landing_for(b, stage, bits):
    """brands[].landing: a url, or {"cold","warm","hot"} per funnel stage; else the cleaned scan URL."""
    lp = (b or {}).get("landing")
    if isinstance(lp, dict):
        u = lp.get(stage) or lp.get("cold") or next((v for v in lp.values() if v), "")
        if u:
            return clean_landing(u) if "?" in u and "utm_" not in u else u
    elif isinstance(lp, str) and lp:
        return lp
    return bits["url"] or ("https://" + (b or {}).get("url", "").strip("/") if (b or {}).get("url") else "")


def explicit_keywords(b):
    """{"brand": [...], "generic": [...]} from brands[].keywords or brands/<slug>/keywords.json — never from the site."""
    kw = (b or {}).get("keywords")
    f = BRANDS / b["id"] / "keywords.json"
    if not kw and f.exists():
        try:
            kw = json.loads(f.read_text())
        except Exception:
            kw = None
    out = {"brand": [b["name"].lower()], "generic": []}
    if isinstance(kw, dict):
        out["brand"] += [k for k in kw.get("brand") or [] if isinstance(k, str)]
        out["generic"] += [k for k in kw.get("generic") or [] if isinstance(k, str)]
    elif isinstance(kw, list):
        out["generic"] += [k for k in kw if isinstance(k, str)]
    norm = lambda xs: list(dict.fromkeys(re.sub(r"\s+", " ", k.strip().lower())[:80] for k in xs if k and k.strip()))
    return {"brand": norm(out["brand"]), "generic": [k for k in norm(out["generic"]) if k not in norm(out["brand"])]}


def best_creative_posts(d, bid, n=3):
    """Boost candidates: posts already live on Facebook first (a boost needs the organic post), then by reach/saves."""
    posts = [p for p in d["posts"] if p["brand"] == bid and p.get("image")]
    def key(p):
        m = p.get("metrics") or {}
        live_fb = p.get("status") == "published" and p.get("platform") == "fb" and p.get("remote_id")
        return (0 if live_fb else 1, -((ap.num(m.get("reach")) or 0) + 10 * (ap.num(m.get("saves")) or 0)))
    return sorted(posts, key=key)[:n]


def new_campaign_id(d):
    return ap.next_id(d, "cp", d.get("campaigns", []))


def angle_ads(bid):
    """Ad copy written per angle (angles.json → angles[].ad = {headline, primary, description, proof}), best angle first."""
    f = BRANDS / bid / "angles.json"
    try:
        angles = json.loads(f.read_text()).get("angles", []) if f.exists() else []
    except (OSError, ValueError):
        return []
    return [a["ad"] for a in angles if isinstance(a, dict) and isinstance(a.get("ad"), dict)]


def _sentences_fit(text, n):
    """The longest run of whole leading sentences that fits n chars ('' when even the first does not)."""
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        cand = (out + " " + sent).strip()
        if len(cand) > n:
            break
        out = cand
    return out


def plan_flights(d, b, ym, budget, bits):
    y, m = [int(x) for x in ym.split("-")]
    last = calendar.monthrange(y, m)[1]
    import otto_compliance as comp
    creatives = best_creative_posts(d, b["id"])
    # Google headlines come from post hooks: never a hook that is compliance-blocked or trips the brand's rules (one bad hook
    # would put the whole Search campaign on hold at launch)
    hooks = []
    for p in d["posts"]:
        if len(hooks) >= 8:
            break
        if p["brand"] == b["id"] and p.get("hook") and not p.get("compliance_block") and not comp.check_texts(b["id"], [p["hook"]], "hooks"):
            hooks.append(p["hook"])
    # the angles' written ad copy (angles.json "ad") is the best Search copy there is: headlines that fit 30 chars,
    # descriptions cut at a sentence to 90 — each line checked against the brand's rules, like the hooks
    search_heads, search_descs = [], []
    for ad in angle_ads(b["id"]):
        for k in ("headline", "proof", "description"):
            t = _sentences_fit(ad.get(k) or "", 30).rstrip(".")      # "6 grams of fiber. One snack pack." → "6 grams of fiber"
            if t:
                search_heads.append(t)
        t = _sentences_fit(ad.get("primary") or "", 90)
        if t:
            search_descs.append(t)
    search_heads = [h for h in dict.fromkeys(search_heads) if not comp.check_texts(b["id"], [h], "ads")]
    search_descs = [t for t in dict.fromkeys(search_descs) if not comp.check_texts(b["id"], [t], "ads")]
    site_desc = bits["description"] if bits["description"] and not comp.check_texts(b["id"], [bits["description"]], "ads") else ""
    langs = [bits["lang"]]
    flights = []
    # 1. always-on leads/traffic on Meta, whole month
    goal = "traffic" if bits["restricted"] else ("sales" if bits.get("shop") else "leads")
    flights.append({"network": "meta", "name": f"{b['name']} · Evergreen {goal} · {ym}",
                    "objective": goal, "stage": "cold", "start": f"{ym}-01", "end": f"{ym}-{last:02d}",
                    "daily_budget": budget, "audience": {"countries": bits["countries"], "age": [25, 60], "interests": b.get("pillars", [])[:4],
                                                         "languages": langs},
                    "creative": {"post": creatives[0]["id"]} if creatives else {"post": None}, "compliance_hold": bits["restricted"]})
    # 2. two boosts of the best organic posts, weeks 2 and 4 (5-day flights) — only posts live on Facebook can be boosted
    live_fb = [p for p in best_creative_posts(d, b["id"], n=6)
               if p.get("status") == "published" and p.get("platform") == "fb" and p.get("remote_id")]
    for i, (s_day, e_day) in enumerate([(8, 12), (22, 26)]):
        if live_fb:
            src = live_fb[min(i, len(live_fb) - 1)]
        else:
            src = creatives[min(i + 1, len(creatives) - 1)] if creatives else None
        flights.append({"network": "meta", "name": f"{b['name']} · Boost “{(src or {}).get('hook', 'best post')[:30]}” · w{2 + 2 * i}",
                        "objective": "engagement", "stage": "warm", "start": f"{ym}-{s_day:02d}", "end": f"{ym}-{min(e_day, last):02d}",
                        "daily_budget": round(budget / 2, 2), "audience": {"countries": bits["countries"], "age": [25, 60], "interests": [],
                                                                           "languages": langs},
                        "creative": {"post": (src or {}).get("id")}, "compliance_hold": bits["restricted"]})
    # 3. Google Search — brand + category intent from the explicit keyword list, whole month (skipped for restricted categories)
    if not bits["restricted"]:
        kw = explicit_keywords(b)
        flights.append({"network": "google", "name": f"{b['name']} · Search · {ym}", "objective": "sales" if bits.get("shop") else "leads", "stage": "hot",
                        "start": f"{ym}-01", "end": f"{ym}-{last:02d}",
                        "daily_budget": round(budget / 2, 2), "audience": {"countries": bits["countries"], "languages": langs},
                        # never the scan's English industry label ("Clinic & medical", "Unknown (?)") as ad copy
                        "creative": {"headlines": [b["name"]] + search_heads[:9] + [h for h in hooks[:5]],
                                     "descriptions": search_descs[:3] + ([site_desc] if site_desc else []),
                                     "keywords": kw}, "compliance_hold": False})
        if not kw["generic"]:
            print(f"note: {b['id']} has no generic keyword list (brands[].keywords or brands/{b['id']}/keywords.json) — "
                  "Google Search runs on the brand name only")
    else:
        print(f"note: {bits['industry']} is a restricted category — Google Search skipped, Meta flights created on compliance hold (needs a compliant lander)")
    for f in flights:
        f["landing_url"] = landing_for(b, f["stage"], bits)
    return flights


def _month_total(flights):
    return sum(f["daily_budget"] * ((date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days + 1) for f in flights)


def plan(bid, ym, budget=20.0, dry=False):
    snap = ap.load()
    b = ap.brand(snap, bid)
    assert b, f"unknown brand {bid}"
    why = ap.no_ads_why(snap, bid)
    if why:                                            # defence in depth: otto_cron already skips such a brand
        print(f"REFUSED {bid} · {ym}: {why} — nothing planned (paid campaigns need a plan with paid ads)")
        return []
    existing = [c for c in snap.get("campaigns", []) if c["brand"] == bid and c.get("plan") == ym]
    if existing:
        sys.exit(f"{bid} already has {len(existing)} campaigns planned for {ym}")
    pl = ap.plan_of(snap, bid)
    bits = profile_bits(bid, b)
    code = ap.brand_currency(snap, bid)
    sym = ap.currency_symbol(code)
    flights = plan_flights(snap, b, ym, budget, bits)
    off = sorted({f["network"] for f in flights if ap.no_ads_why(snap, bid, f["network"])})
    if off:
        print(f"note: plan {pl['id']} has no {' / '.join('Meta' if n == 'meta' else 'Google' for n in off)} ads — "
              f"{sum(1 for f in flights if f['network'] in off)} flight(s) not planned")
        flights = [f for f in flights if f["network"] not in off]
    total = _month_total(flights)
    # the plan's ad-spend band (EUR), a soft cap: the first month above it is planned in full, the second month in a row at
    # the cap with the next plan offered; a plan with overage is planned in full and shows its fee (ap.ad_band)
    asked = total
    total_eur = ap.to_eur(total, code)
    band = ap.ad_band(snap, bid, ym, total_eur if total_eur is not None else 0.0)
    if band["mode"] == "capped" and total_eur:
        k = band["cap_eur"] / total_eur
        for f in flights:
            f["daily_budget"] = math.floor(f["daily_budget"] * k * 100) / 100
        total = _month_total(flights)
    band.update(asked=round(asked, 2), planned=round(total, 2))
    if band["mode"] == "grace":
        print(f"note: ≈{sym}{asked:,.0f} is above plan {pl['id']}'s €{band['cap_eur']:,.0f}/month band — first month above it: "
              "planned in full, the card says so")
    elif band["mode"] == "capped":
        print(f"note: ≈{sym}{asked:,.0f} is above plan {pl['id']}'s €{band['cap_eur']:,.0f}/month band for the second month in a "
              f"row — planned at ≈{sym}{total:,.0f}, the card offers {band['upgrade_label'] or 'a bigger plan'}")
    elif band["mode"] == "overage":
        print(f"note: ≈{sym}{asked:,.0f} planned in full on plan {pl['id']}; {band['overage_pct']:g}% of the spend above "
              f"€{band['overage_above_eur']:,.0f} ≈ €{band['overage_eur']:,.0f} (shown, not billed automatically)")
    evergreen = next((f["daily_budget"] for f in flights if f["network"] == "meta" and f.get("stage") == "cold"), None)
    if evergreen is None:                              # no Meta flight → no Meta ad matrix
        mx, mx_new, mx_line, gaps = None, False, f"none — plan {pl['id']} has no Meta ads", []
    else:
        mx, mx_new, mx_line, gaps = plan_matrix_for(bid, ym, snap, evergreen, code)
    if not flights:
        print(f"{bid} · {ym}: nothing to plan on the networks plan {pl['id']} covers")
        return []
    if dry:
        for f in flights:
            print(f'{f["network"]:6} {f["start"]} → {f["end"]}  {sym}{f["daily_budget"]}/day  {f["objective"]:10} {f["name"]}  → {f["landing_url"]}')
        print(f"-- {len(flights)} flights · ≈{sym}{total:,.0f} for {ym} (dry) · Meta ad matrix: {mx_line}"
              + (" (skeleton, not written)" if mx_new else ""))
        return flights
    import otto_creative as cre
    import otto_styles as sty
    if mx_new:
        sty.save_matrix(bid, ym, mx)                   # the skeleton the copywriter fills (otto-creative-engine skill)
    created = []
    with ap.transaction() as d:
        if any(c["brand"] == bid and c.get("plan") == ym for c in d.get("campaigns", [])):
            sys.exit(f"{bid} already has campaigns planned for {ym}")
        for f in flights:
            c = dict(f, id=new_campaign_id(d), brand=bid, plan=ym, currency=sym, currency_code=code, status="draft",
                     remote={}, created_at=ap.now_iso())
            try:
                cre.build(d, c, dry=True)               # plan the variants now (angles × formats); files render at launch
            except Exception as e:
                c["creatives"] = {"error": str(e)[:120]}
            d.setdefault("campaigns", []).append(c); created.append(c)
        held = [c for c in created if c.get("compliance_hold")]
        ap.add_rec_once(d, "P1", f"Approve the {ym} paid plan: {len(created)} campaigns, ≈{sym}{total:,.0f}",
                        "Evergreen on Meta all month" +
                        (f" as {sty.size_text(mx)}: one ad set per concept, Meta moves the budget to the concepts that sell"
                         + (" (creator videos go live as real creators' footage arrives)"
                            if any(sty.fmt(x) == "creator" for a in sty.live_angles(mx) for x in sty.live_cells(a)) else "")
                         if mx else "") +
                        ", two 5-day boosts of your best organic posts" + (", one Google Search campaign on brand + category intent" if not bits["restricted"] else "") +
                        ". Nothing spends until you approve; every campaign has a daily ceiling and a CPL guard." +
                        (f" Matrix gap{'s' if len(gaps) > 1 else ''} to close before launch: {gaps[0]}" +
                         (f" (+{len(gaps) - 1} more)" if len(gaps) > 1 else "") + "." if gaps else "") +
                        (f" {len(held)} of them are on compliance hold (restricted category): approving does not start them — they run only "
                         "after a review and `otto_ads.py release <id>`." if held else "") +
                        band_text(pl, band, sym),
                        "Paid runs on the same calendar as organic", "Approve plan", brand=bid, source="otto_ads",
                        action="approve_plan", plan=ym, **({"band": band} if band["mode"] != "within" else {}))
        ap.record_band(d, bid, ym, band)
    write_plan_md(b, ym, created, sym, total, mx, gaps)
    print(f"planned {len(created)} campaigns for {bid} · {ym} (≈{sym}{total:,.0f}) → drafts + recommendation · Meta ad matrix: {mx_line}")
    return created


def band_text(pl, band, sym):
    """The plan card's sentence about the plan's ad-spend band ("" inside it)."""
    cap = band.get("cap_eur") or 0
    if band["mode"] == "grace":
        return (f" This month's ≈{sym}{band['asked']:,.0f} is above your {pl['label']} plan's €{cap:,.0f} a month: Otto plans it in "
                f"full this once. If next month is above it too, Otto plans €{cap:,.0f}"
                + (f" and suggests {band['upgrade_label']}" + (f" (up to €{band['upgrade_cap_eur']:,.0f} a month)" if band.get("upgrade_cap_eur") else "")
                   if band.get("upgrade_label") else "") + ".")
    if band["mode"] == "capped":
        return (f" Your {pl['label']} plan covers €{cap:,.0f} of ad spend a month and this is the second month in a row above it, "
                f"so the ≈{sym}{band['asked']:,.0f} is planned at ≈{sym}{band['planned']:,.0f}."
                + (f" {band['upgrade_label']} runs the full budget" + (f" (up to €{band['upgrade_cap_eur']:,.0f} a month)."
                                                                       if band.get("upgrade_cap_eur") else ".")
                   if band.get("upgrade_label") else " Talk to us about a bigger plan."))
    if band["mode"] == "overage":
        return (f" Above €{band['overage_above_eur']:,.0f} a month your {pl['label']} plan adds {band['overage_pct']:g}% of the excess: "
                f"≈ €{band['overage_eur']:,.0f} for this month's plan. Nothing is charged automatically.")
    return ""


def plan_matrix_for(bid, ym, snap, budget=None, currency="EUR"):
    """The month's Meta ad matrix: brands/<id>/ads-<ym>.json when it exists, else a fresh skeleton (otto_styles.plan_matrix,
    written by plan()) that the copywriter fills — the launch standard (6 angles × 6 styles), or the micro floor (4 × 5) when
    the evergreen's daily budget is under otto_styles.MICRO_BELOW_DAILY_EUR. → (matrix | None, is_new, summary, coverage gaps)."""
    try:
        import otto_styles as sty
        mx = sty.load_matrix(bid, ym)
        new = mx is None
        if new:                                        # the plan's preset; the micro floor still wins under ~€36/day
            preset = ap.matrix_preset(snap, bid, sty.preset_for_budget(budget, currency) if budget is not None else None)
            if preset == "none":
                return None, False, f"none — plan {ap.plan_of(snap, bid)['id']} has no ad matrix", []
            per = sty.PRESETS[preset]["min_styles_per_angle"] if preset == "scale" else None   # scale: more styles than slots
            mx = sty.plan_matrix(bid, ym=ym, d=snap, preset=preset, n_per_angle=per)
            refresh = ap.limit(snap, bid, "refresh_per_angle_week")
            if refresh is not None and refresh != sty.rules_for(mx).get("refresh_per_angle_week"):
                mx["rules"] = dict(mx.get("rules") or {}, refresh_per_angle_week=refresh)     # the plan's weekly refresh
        if not mx.get("angles"):
            return None, False, "none — no angles to build one from yet (strategy.json / competitor research)", []
        rep = sty.check_matrix(bid, ym, mx)
        ready = sum(1 for r in rep["cells"] if r["status"] == "ready")
        return mx, new, f"{mx.get('preset') or 'launch'} · {rep['size']}, {ready} ready", rep["gaps"]
    except Exception as e:                              # a broken matrix never blocks the plan; it is named
        return None, False, f"unavailable — {str(e)[:120]}", []


def write_plan_md(b, ym, camps, cur, total, mx=None, gaps=()):
    path = BRANDS / b["id"] / f"ads-plan-{ym}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Paid plan — {b['name']} · {ym} · ≈{cur}{total:,.0f}", "", "| id | network | flight | daily | objective | creative | landing | status |",
             "|---|---|---|---|---|---|---|---|"]
    for c in camps:
        kw = c["creative"].get("keywords")
        kws = (kw.get("brand", []) + kw.get("generic", [])) if isinstance(kw, dict) else (kw or [])
        cr = c["creative"].get("post") or (", ".join(kws[:3]) + "…")
        lines.append(f"| {c['id']} | {c['network']} | {c['start']} → {c['end']} | {cur}{c['daily_budget']} | {c['objective']} | {cr} | "
                     f"{c.get('landing_url') or '—'} | {c['status']}{' · compliance hold' if c.get('compliance_hold') else ''} |")
    if mx:
        import otto_styles as sty
        lines += ["", f"## Meta ad matrix — {sty.size_text(mx)} (brands/{b['id']}/ads-{ym}.json)", "",
                  "One ad set per concept (campaign budget optimisation); the styles are its ads. Creator videos run once a real "
                  "creator's footage arrives.", "",
                  "| concept (ad set) | family | stage | source | styles |", "|---|---|---|---|---|"]
        for a in sty.live_angles(mx):
            styles = ", ".join(f"{x.get('style')}{({'video': ' (video)', 'creator': ' (creator)'}).get(sty.fmt(x), '')}"
                               for x in sty.live_cells(a))
            lines.append(f"| {a.get('ad_set') or a.get('id')} | {a.get('family') or '—'} | {a.get('stage') or '—'} | "
                         f"{a.get('source') or '—'} | {styles} |")
        lines += [""] + [f"- gap: {g}" for g in gaps]
    path.write_text("\n".join(lines) + "\n")


def approve(bid, ym, via="cli"):
    n = 0
    with ap.transaction() as d:
        for c in d.get("campaigns", []):
            if c["brand"] == bid and c.get("plan") == ym and c["status"] == "draft" and not c.get("compliance_hold"):
                c["status"] = "approved"; c["approved_via"] = via; c["decided_at"] = ap.now_iso(); n += 1
    print(f"{n} campaign(s) approved for {bid} · {ym} (compliance-hold flights stay draft)")
    return n


def rec_action(r):
    """Code behind a recommendation card from this module (called by otto_telegram on ✅). Returns a short
    result when an action ran, None when the card is informational."""
    m = re.match(r"Approve the (\d{4}-\d{2}) paid plan", r.get("title") or "")
    if r.get("action") == "approve_plan" or m:
        ym = r.get("plan") or (m.group(1) if m else None)
        if not (ym and r.get("brand")):
            return None
        n = approve(r["brand"], ym, via="telegram")
        return f"{n} campaign(s) approved for {ym}"
    if r.get("action") == "pause_campaign" and r.get("campaign_id"):
        pause(r["campaign_id"])
        return f"{r['campaign_id']} paused"
    return None


def release(cid):
    import otto_compliance as comp
    snap = ap.load()
    c = ap.campaign(snap, cid)
    assert c, f"unknown campaign {cid}"
    v = comp.check_campaign(c, _boost_texts(snap, c))
    if v:
        sys.exit(f"{cid} still violates compliance: {comp.describe(v)}")
    with ap.transaction() as d:
        c2 = ap.campaign(d, cid)
        c2["compliance_hold"] = False; c2.pop("compliance", None); c2["released_at"] = ap.now_iso()
    print(f"{cid} released from compliance hold (status {c['status']})")


def retry(cid):
    with ap.transaction() as d:
        c = ap.campaign(d, cid)
        assert c, f"unknown campaign {cid}"
        assert c["status"] == "failed", f"{cid} is {c['status']}, not failed"
        c["status"] = "approved"; c["retried_at"] = ap.now_iso()
    print(f"{cid} → approved; next launch resumes from {len(c.get('remote') or {})} saved remote field(s)")


# ---------------- launch ----------------

def _boost_texts(d, c):
    p = ap.post(d, (c.get("creative") or {}).get("post") or "")
    if c.get("objective") == "engagement" and p:
        import otto_compliance as comp
        return comp.post_texts(p)
    return []


def meta_mode(d, c, m):
    """How this flight is built on Meta (pure — also printed by --dry).
    leads + lead form → OUTCOME_LEADS / LEAD_GENERATION / ON_AD with the form on the CTA;
    leads + pixel → OUTCOME_LEADS / OFFSITE_CONVERSIONS (pixel LEAD); leads without either → OUTCOME_TRAFFIC / LINK_CLICKS.
    Never LEAD_GENERATION without a form."""
    obj = c.get("objective")
    if obj == "engagement" and (c.get("creative") or {}).get("post"):
        p = ap.post(d, c["creative"]["post"]) or {}
        if p.get("status") != "published" or p.get("platform") != "fb" or not p.get("remote_id"):
            return {"skip": f"boost skipped: {p.get('id') or c['creative']['post']} is not live on Facebook "
                            f"({p.get('platform')}/{p.get('status')}) — a boost needs the published organic post"}
        rid = str(p["remote_id"])
        story = rid if "_" in rid else f"{m['page_id']}_{rid}"
        return {"objective": "OUTCOME_ENGAGEMENT", "optimization_goal": "POST_ENGAGEMENT", "boost": story}
    if obj == "leads":
        if m.get("lead_form_id"):
            return {"objective": "OUTCOME_LEADS", "optimization_goal": "LEAD_GENERATION", "destination_type": "ON_AD",
                    "promoted_object": {"page_id": m["page_id"]}, "lead_form": m["lead_form_id"]}
        if m.get("pixel_id"):
            return {"objective": "OUTCOME_LEADS", "optimization_goal": "OFFSITE_CONVERSIONS",
                    "promoted_object": {"pixel_id": m["pixel_id"], "custom_event_type": "LEAD"}}
        return {"objective": "OUTCOME_TRAFFIC", "optimization_goal": "LINK_CLICKS", "note": "no lead form or pixel — traffic instead"}
    if obj == "sales":
        if m.get("pixel_id"):
            return {"objective": "OUTCOME_SALES", "optimization_goal": "OFFSITE_CONVERSIONS",
                    "promoted_object": {"pixel_id": m["pixel_id"], "custom_event_type": "PURCHASE"}}
        return {"objective": "OUTCOME_TRAFFIC", "optimization_goal": "LINK_CLICKS", "note": "no pixel — traffic instead"}
    if obj == "awareness":
        return {"objective": "OUTCOME_AWARENESS", "optimization_goal": "REACH"}
    if obj == "engagement":
        return {"objective": "OUTCOME_ENGAGEMENT", "optimization_goal": "POST_ENGAGEMENT", "skip": "engagement flight without a post to boost"}
    return {"objective": "OUTCOME_TRAFFIC", "optimization_goal": "LINK_CLICKS"}


def upload_image_bytes(ref, m):
    """Local file → ad image hash (adimages bytes=<base64>) — no public URL involved."""
    lp = paths.local_path(ref)
    if not lp.exists():
        raise LaunchError(f"ad image {ref} is missing locally")
    r = pub.graph("POST", f"{m['ad_account_id']}/adimages", m["access_token"],
                  bytes=base64.b64encode(lp.read_bytes()).decode(), name=lp.name)
    img = next(iter((r.get("images") or {}).values()), {})
    if not img.get("hash"):
        raise LaunchError(f"no hash for {ref}")
    return img["hash"]


def upload_video(ref, m, base, timeout=600):
    """Public mp4 → advideos, then wait for status.video_status == ready (an unprocessed video fails the ad)."""
    url = paths.media_url(ref, base)
    vid = pub.graph("POST", f"{m['ad_account_id']}/advideos", m["access_token"], file_url=url)["id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = (pub.graph("GET", vid, m["access_token"], fields="status").get("status") or {})
        if st.get("video_status") == "ready":
            return vid
        if st.get("video_status") == "error":
            raise LaunchError(f"video {ref} failed processing")
        time.sleep(10)
    raise LaunchError(f"video {ref} still processing after {timeout}s")


def _adset_params(c, mode, special, countries, campaign_id, name):
    """Ad set basics shared by both structures (no budget: ABO adds it, CBO keeps it on the campaign)."""
    age = c["audience"].get("age", [25, 60])
    targeting = {"geo_locations": {"countries": countries}}
    if special:
        targeting.update({"age_min": 18, "age_max": 65})          # special ad categories: no age narrowing
    else:
        targeting.update({"age_min": age[0], "age_max": age[1]})
        if age[1] and age[1] < 65:
            targeting["targeting_automation"] = {"advantage_audience": 0}   # v25: honour age_max as a hard limit
    start = max(datetime.fromisoformat(c["start"] + "T06:00:00+00:00"), datetime.now(timezone.utc) + timedelta(minutes=10))
    params = {"name": name[:200], "campaign_id": campaign_id, "billing_event": "IMPRESSIONS",
              "optimization_goal": mode["optimization_goal"], "status": "PAUSED", "targeting": json.dumps(targeting),
              "start_time": start.strftime("%Y-%m-%dT%H:%M:%S+0000"), "end_time": c["end"] + "T23:59:00+0000"}
    if mode.get("destination_type"):
        params["destination_type"] = mode["destination_type"]
    if mode.get("promoted_object"):
        params["promoted_object"] = json.dumps(mode["promoted_object"])
    return params


MAX_CONCEPTS, MAX_ADS_PER_SET = 10, 6          # ad sets per campaign · ads per ad set (Meta tests ~3-6 creatives per set well)
META_CTA = re.compile(r"^[A-Z][A-Z_]{2,30}$")
# placement asset customisation: the 9:16 render serves Stories / Reels, the 4:5 (or square) render everything else.
# Field names follow Meta's asset_feed_spec docs; unverified live — a refusal falls back to one image for all placements.
PLACEMENT_RULES = [
    ({"publisher_platforms": ["facebook", "instagram", "messenger"], "facebook_positions": ["story", "facebook_reels"],
      "instagram_positions": ["story", "reels"], "messenger_positions": ["story"]}, "story"),
    ({"publisher_platforms": ["facebook", "instagram", "audience_network", "messenger"]}, "feed"),
]


def _concepts(cr):
    """Matrix creatives (otto_creative.build_matrix) → what can launch: ≤MAX_CONCEPTS angles, each with its first
    ≤MAX_ADS_PER_SET ads that have rendered (not planned) files. [] for angle-bank creatives."""
    out = []
    for con in (cr or {}).get("concepts") or []:
        ads = [a for a in con.get("ads") or [] if a.get("files") and not any(f.get("planned") for f in a["files"])]
        if ads:
            out.append(dict(con, ads=ads[:MAX_ADS_PER_SET]))
    return out[:MAX_CONCEPTS]


def _ad_media(ad, m, base, hashes, vids, save):
    """Upload one ad's files (each file once: hashes / vids map file → Meta id across all concepts and re-runs)."""
    def h(ref):
        if ref not in hashes:
            hashes[ref] = upload_image_bytes(ref, m)
            save()
        return hashes[ref]
    out = {}
    for f in ad.get("files") or []:
        if f.get("kind") == "video":
            if not f.get("poster"):
                raise LaunchError("video without a poster frame")
            if f["file"] not in vids:
                vids[f["file"]] = upload_video(f["file"], m, base)
                save()
            out.update(video=vids[f["file"]], poster=h(f["poster"]))
        elif f.get("cards"):
            if "cards" not in out or f.get("size") == "feed":
                out["cards"] = [h(k["file"]) for k in f["cards"]]
                out["card_texts"] = [k.get("text") or "" for k in f["cards"]]
        else:
            out[f.get("size") or "feed"] = h(f["file"])
    if not any(out.get(k) for k in ("video", "cards", "feed", "square", "story")):
        raise LaunchError("no file to upload")
    return out


def _concept_creative(act, tok, page, c, ad, media, link, lead_form, cta_default):
    """One style = one creative: a video (video_data), a carousel (child_attachments) or a single image — with the 9:16
    render placed on Stories / Reels when the cell has one (not with an instant form: unverified there)."""
    cta_type = ad.get("cta") if META_CTA.match(str(ad.get("cta") or "")) else cta_default
    cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": lead_form}} if lead_form else {"type": cta_type, "value": {"link": link}}
    msg, title, desc = (ad.get("primary") or "")[:1000], (ad.get("headline") or "")[:255], (ad.get("description") or "").strip()
    name = f"{c['name']} · {ad['id']}"[:200]

    def post(spec):
        return pub.graph("POST", f"{act}/adcreatives", tok, name=name, **{k: json.dumps(v) for k, v in spec.items()})["id"]

    if media.get("video"):
        vd = {"video_id": media["video"], "message": msg, "title": title, "call_to_action": cta, "image_hash": media["poster"]}
        if desc:
            vd["link_description"] = desc
        return post({"object_story_spec": {"page_id": page, "video_data": vd}})
    if media.get("cards"):
        kids = [{"link": link, "image_hash": hh, "name": (t or title)[:255]} for hh, t in zip(media["cards"], media["card_texts"])]
        return post({"object_story_spec": {"page_id": page, "link_data": {"link": link, "message": msg, "child_attachments": kids,
                                                                            "call_to_action": cta, "multi_share_optimized": False,
                                                                            "multi_share_end_card": False}}})
    main = media.get("feed") or media.get("square") or media.get("story")
    ld = {"link": link, "message": msg, "name": title, "image_hash": main, "call_to_action": cta}
    if desc:
        ld["description"] = desc
    if media.get("story") and media["story"] != main and not lead_form:
        imgs = {"feed": main, "story": media["story"]}
        spec = {"images": [{"hash": hh, "adlabels": [{"name": f"{ad['id']}-{k}"}]} for k, hh in imgs.items()],
                "bodies": [{"text": msg}], "titles": [{"text": title}], "link_urls": [{"website_url": link}],
                "call_to_action_types": [cta_type], "ad_formats": ["SINGLE_IMAGE"],
                "asset_customization_rules": [{"customization_spec": cs, "image_label": {"name": f"{ad['id']}-{k}"}, "priority": i}
                                              for i, (cs, k) in enumerate(PLACEMENT_RULES, 1)]}
        if desc:
            spec["descriptions"] = [{"text": desc}]
        try:
            return post({"object_story_spec": {"page_id": page}, "asset_feed_spec": spec})
        except pub.GraphError as e:
            print(f"  {ad['id']}: placement customisation refused, one image everywhere — {str(e)[:120]}")
    return post({"object_story_spec": {"page_id": page, "link_data": ld}})


def _launch_concepts(c, m, cr, mode, remote, save, acct_cur, special, countries, b, base):
    """The concept-structured flight: one ad set per angle of the month's matrix, that angle's styles as separate ads,
    so Meta tests executions inside a concept and concepts against each other.
    Budget: campaign budget optimisation (CBO) — the flight's daily budget is set on the campaign and Meta moves it to
    the ad sets that convert. The flights Otto plans are small (€20/day): split evenly over 6+ ad sets (ABO), each would
    sit below what an ad set needs to leave learning, and the split would be ours, not the auction's. Resumable like the
    one-set flight: every id is saved in remote (campaign_id, hashes, concepts[<angle>] = {adset_id, ads{cell: ids}})."""
    tok, act, page = m["access_token"], m["ad_account_id"], m["page_id"]
    concepts = _concepts(cr)
    if not concepts:
        raise LaunchError("the ad matrix has no rendered ad to launch")
    remote["structure"] = "concepts"
    if not remote.get("campaign_id"):
        params = {"name": c["name"], "objective": mode["objective"], "status": "PAUSED", "buying_type": "AUCTION",
                  "special_ad_categories": json.dumps(special), "daily_budget": minor_units(c["daily_budget"], acct_cur),
                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}       # CBO: the budget lives on the campaign
        if special:
            params["special_ad_category_country"] = json.dumps(countries)
        remote["campaign_id"] = pub.graph("POST", f"{act}/campaigns", tok, **params)["id"]
    save()
    link = c.get("landing_url") or ("https://" + b.get("url", "").strip("/") if b.get("url") else "")
    lead_form, cta_default = mode.get("lead_form"), cr.get("cta", "LEARN_MORE")
    hashes, vids, done = remote.setdefault("hashes", {}), remote.setdefault("video_map", {}), remote.setdefault("concepts", {})
    for con in concepts:
        st = done.setdefault(str(con["angle"]), {})
        st.setdefault("ads", {})
        todo = []
        for ad in con["ads"]:
            if (st["ads"].get(ad["id"]) or {}).get("ad_id"):
                continue                                   # created in an earlier run
            try:
                todo.append((ad, _ad_media(ad, m, base, hashes, vids, save)))
            except Exception as e:                          # one bad file drops that ad, not the concept
                print(f"  {ad['id']}: not uploaded — {str(e)[:160]}")
        if todo and not st.get("adset_id"):
            params = _adset_params(c, mode, special, countries, remote["campaign_id"], f"{c['name']} · {con['ad_set']}")
            st["adset_id"] = pub.graph("POST", f"{act}/adsets", tok, **params)["id"]
            save()
        for ad, media in todo:
            a_st = st["ads"].setdefault(ad["id"], {"style": ad.get("style")})
            if not a_st.get("creative_id"):
                a_st["creative_id"] = _concept_creative(act, tok, page, c, ad, media, link, lead_form, cta_default)
                save()
            a_st["ad_id"] = pub.graph("POST", f"{act}/ads", tok, name=f"{c['name']} · {ad['id']}"[:200], adset_id=st["adset_id"],
                                      creative=json.dumps({"creative_id": a_st["creative_id"]}), status="ACTIVE")["id"]
            save()
        if st.get("adset_id") and not st.get("active") and any(x.get("ad_id") for x in st["ads"].values()):
            pub.graph("POST", st["adset_id"], tok, status="ACTIVE")
            st["active"] = True
            save()
    live = [k for k, v in done.items() if v.get("active")]
    if not live:
        raise LaunchError("no ad of the matrix could be uploaded")
    if not remote.get("campaign_active"):
        pub.graph("POST", remote["campaign_id"], tok, status="ACTIVE")
        remote["campaign_active"] = True
    remote.update({"done": True, "mode": {k: v for k, v in mode.items() if k != "promoted_object"}, "ad_sets": len(live),
                   "ads": sum(1 for k in live for x in done[k]["ads"].values() if x.get("ad_id")),
                   "images": len(hashes), "videos": len(vids)})
    save()
    return remote


def launch_meta(d, c, m, base, persist=lambda **kw: None):
    """Resumable: c["remote"] is persisted after every created object; a re-run continues from it. A flight whose creatives
    come from the month's ad matrix is concept-structured (_launch_concepts: CBO, one ad set per angle); otherwise one
    ad set with its own budget and Meta dynamic creative (or one ad per static with an instant form)."""
    remote = dict(c.get("remote") or {})
    tok, act, page = m["access_token"], m["ad_account_id"], m["page_id"]
    b = ap.brand(d, c["brand"]) or {}

    def save(**extra):
        persist(remote=dict(remote), **extra)

    mode = meta_mode(d, c, m)
    if mode.get("skip"):
        raise Skipped(mode["skip"])
    acct_cur = remote.get("account_currency") or meta_account_currency(m)
    plan_cur = c.get("currency_code") or ap.currency_code(c.get("currency"))
    if acct_cur and plan_cur and acct_cur != plan_cur:
        raise LaunchError(f"budget is planned in {plan_cur} but the ad account bills in {acct_cur} — re-plan in {acct_cur}")
    remote["account_currency"] = acct_cur
    special = [s for s in (b.get("special_ad_categories") or []) if s and s != "NONE"]
    countries = c["audience"].get("countries", ["DE"])
    boost = mode.get("boost")

    cr = c.get("creatives") or {}
    if not boost and not remote.get("creatives_built"):
        import otto_creative as cre
        cr = cre.build(d, c, dry=False, base=base)         # render statics/carousels with copy now
        remote["creatives_built"] = ap.now_iso()
        save(creatives=cr)
    # the month's ad matrix was built → concept structure (one ad set per angle); a campaign already created as one
    # ad set stays that way on resume
    if not boost and (remote.get("structure") == "concepts" or (not remote.get("campaign_id") and _concepts(cr))):
        return _launch_concepts(c, m, cr, mode, remote, save, acct_cur, special, countries, b, base)

    if not remote.get("campaign_id"):
        params = {"name": c["name"], "objective": mode["objective"], "status": "PAUSED", "buying_type": "AUCTION",
                  "special_ad_categories": json.dumps(special),
                  "is_adset_budget_sharing_enabled": "false"}          # budgets live on the ad set (no CBO)
        if special:
            params["special_ad_category_country"] = json.dumps(countries)
        remote["campaign_id"] = pub.graph("POST", f"{act}/campaigns", tok, **params)["id"]
        save()

    hashes, videos = remote.get("image_hashes"), remote.get("video_ids")
    if not boost and hashes is None:
        refs = list(dict.fromkeys([i["file"] for i in cr.get("images", []) if i.get("file")] +
                                  [k["file"] for car in cr.get("carousels", []) for k in car.get("cards", []) if k.get("file")]))
        hashes = []
        for ref in refs[:10]:
            try:
                hashes.append(upload_image_bytes(ref, m))
            except Exception as e:
                print("  image upload failed:", ref, e)
        remote["image_hashes"] = hashes
        save()
    if not boost and videos is None:
        videos = []
        for v in cr.get("videos", [])[:3]:
            try:
                videos.append(upload_video(v["file"], m, base))
            except Exception as e:
                print("  video upload failed:", v.get("file"), e)
        remote["video_ids"] = videos
        save()
    hashes, videos = hashes or [], videos or []

    lead_form = mode.get("lead_form")
    dynamic = not boost and not lead_form and (len(hashes) >= 2 or len(cr.get("titles", [])) >= 2)
    if not remote.get("adset_id"):
        params = _adset_params(c, mode, special, countries, remote["campaign_id"], c["name"] + " · set A")
        params["daily_budget"] = minor_units(c["daily_budget"], acct_cur)
        if dynamic:
            params["is_dynamic_creative"] = "true"
        remote["adset_id"] = pub.graph("POST", f"{act}/adsets", tok, **params)["id"]
        remote["dynamic"] = dynamic
        save()
    dynamic = remote.get("dynamic", dynamic)

    post = ap.post(d, (c.get("creative") or {}).get("post") or "") or {}
    link = c.get("landing_url") or ("https://" + b.get("url", "").strip("/") if b.get("url") else "")
    remote.setdefault("creative_ids", []); remote.setdefault("ad_ids", [])
    specs = []
    if boost:
        specs.append({"name": c["name"] + " · boost", "object_story_id": boost})
    elif dynamic:
        spec = {"images": [{"hash": h} for h in hashes[:10]], "bodies": [{"text": t} for t in cr.get("bodies", [])[:5] if t],
                "titles": [{"text": t} for t in cr.get("titles", [])[:5] if t],
                "ad_formats": ["AUTOMATIC_FORMAT"] if videos else ["SINGLE_IMAGE"],
                "call_to_action_types": [cr.get("cta", "LEARN_MORE")], "link_urls": [{"website_url": link}]}
        descs = [{"text": t} for t in cr.get("descriptions", [])[:2] if t and t.strip()]
        if descs:
            spec["descriptions"] = descs                 # omitted when empty (an empty text is rejected)
        if videos:
            spec["videos"] = [{"video_id": v} for v in videos[:3]]
        specs.append({"name": c["name"] + " · dynamic", "object_story_spec": {"page_id": page}, "asset_feed_spec": spec})
    else:
        # single image per ad; with a lead form, one ad per image (dynamic creative + instant forms is not used —
        # asset_feed_spec support for lead_gen_form_id is unverified)
        msg = (post.get("caption") or post.get("hook") or (cr.get("bodies") or [c["name"]])[0])[:1000]
        title = ((cr.get("titles") or [None])[0] or post.get("hook") or c["name"])[:40]
        cta = {"type": "SIGN_UP", "value": {"lead_gen_form_id": lead_form}} if lead_form else \
              {"type": cr.get("cta", "LEARN_MORE"), "value": {"link": link}}
        imgs = hashes[:3] if lead_form else hashes[:1]
        for i, h in enumerate(imgs or [None], 1):
            ld = {"link": link, "message": msg, "name": title, "call_to_action": cta}
            if h:
                ld["image_hash"] = h
            elif post.get("image"):
                ld["picture"] = pub.image_url(post, base)
            specs.append({"name": f"{c['name']} · creative {i}", "object_story_spec": {"page_id": page, "link_data": ld}})
    for i, sp in enumerate(specs):
        if i < len(remote["ad_ids"]):
            continue                                  # created in an earlier run
        if i < len(remote["creative_ids"]):
            cid = remote["creative_ids"][i]
        else:
            params = {"name": sp["name"]}
            for k in ("object_story_id", "object_story_spec", "asset_feed_spec"):
                if k in sp:
                    params[k] = sp[k] if isinstance(sp[k], str) else json.dumps(sp[k])
            cid = pub.graph("POST", f"{act}/adcreatives", tok, **params)["id"]
            remote["creative_ids"].append(cid); save()
        ad = pub.graph("POST", f"{act}/ads", tok, name=f"{c['name']} · ad {i + 1}", adset_id=remote["adset_id"],
                       creative=json.dumps({"creative_id": cid}), status="ACTIVE")["id"]
        remote["ad_ids"].append(ad); save()
    if not remote.get("adset_active"):
        pub.graph("POST", remote["adset_id"], tok, status="ACTIVE")
        remote["adset_active"] = True; save()
    if not remote.get("campaign_active"):
        pub.graph("POST", remote["campaign_id"], tok, status="ACTIVE")
        remote["campaign_active"] = True
    remote.update({"done": True, "mode": {k: v for k, v in mode.items() if k != "promoted_object"}, "images": len(hashes), "videos": len(videos)})
    save()
    return remote


def _clean_ad_text(t, n):
    t = re.sub(r"\s+", " ", str(t or "").replace("!", "")).strip(" -—–·|")
    t = re.sub(r"[*_`#>]", "", t)
    if len(t) > n:
        cut = t[:n]
        t = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return t.strip(" -—–·|,.:;")


def _fit(t, n):
    """Ad text that fits n chars without a broken phrase: the text itself, else its leading whole sentences, else its first
    clause (before ':', ' — ', '?', '. '); '' when nothing clean fits (a hook cut to "Surf camp: uma semana que" is dropped)."""
    t = _clean_ad_text(t, 10 ** 6)
    if len(t) <= n:
        return t
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", t):
        if len((out + " " + s).strip()) > n:
            break
        out = (out + " " + s).strip()
    if len(out) >= min(15, n // 2):
        return out.strip(" -—–·|,.:;")
    clause = re.split(r"\s*(?::|—|–|\||\?|!|\.\s)\s*", t, maxsplit=1)[0].strip(" -—–·|,.:;")
    return clause if 3 <= len(clause) <= n else ""


def uniq_trunc(cands, n, limit):
    """Fit first, then dedupe (two hooks that share a first clause are ONE headline)."""
    out, seen = [], set()
    for c in cands:
        t = _fit(c, n)
        if t and t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    return out[:limit]


def _g_text(t):
    """Google Ads editorial: no decorative symbols ('4.8★' is disapproved as non-standard use of symbols)."""
    t = re.sub(r"\s*★\s*", " stars ", str(t or ""))
    t = re.sub(r"[☆✓✔✨•→←]+", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def rsa_assets(c, b, lang):
    cr = c.get("creative") or {}
    shop = c.get("objective") == "sales"
    fh = (SHOP_HEADLINES if shop else FALLBACK_HEADLINES)
    fd = (SHOP_DESCRIPTIONS if shop else FALLBACK_DESCRIPTIONS)
    heads = uniq_trunc([_g_text(t) for t in list(cr.get("headlines") or []) + [b.get("name", "")] + fh.get(lang, fh["en"])], 30, 15)
    descs = uniq_trunc([_g_text(t) for t in list(cr.get("descriptions") or []) + fd.get(lang, fd["en"])], 90, 4)
    if len(heads) < 3:
        raise LaunchError(f"responsive search ad needs 3+ unique headlines, have {len(heads)}")
    if len(descs) < 2:
        raise LaunchError(f"responsive search ad needs 2+ unique descriptions, have {len(descs)}")
    return heads, descs


def split_keywords(c, b):
    kw = (c.get("creative") or {}).get("keywords")
    if isinstance(kw, dict):
        return list(dict.fromkeys(kw.get("brand") or [])), list(dict.fromkeys(kw.get("generic") or []))
    # legacy plans stored site nav/headings here: only the brand-name terms are trusted
    name = (b.get("name") or "").lower()
    brand = [k for k in (kw or []) if isinstance(k, str) and name and name.split()[0] in k.lower()]
    if kw and len(brand) < len(kw):
        print(f"  note: {len(kw) - len(brand)} legacy keyword(s) from the site scan dropped — set brands[].keywords")
    return brand or ([name] if name else []), []


def google_ops(c, g, b, bidding="maximizeConversions"):
    """All mutate operations for one Search campaign (pure). Raises LaunchError when it cannot be built safely."""
    cust = str(g["customer_id"]).replace("-", "")
    lang = (c["audience"].get("languages") or [ap.brand_lang(b)])[0]
    heads, descs = rsa_assets(c, b, lang)
    countries = c["audience"].get("countries") or []
    unknown = [cc for cc in countries if cc.upper() not in GEO]
    if not countries or unknown:
        raise LaunchError(f"no Google geo target for {unknown or 'empty country list'} — add it to GEO or fix audience.countries")
    brand_kw, generic_kw = split_keywords(c, b)
    if not brand_kw and not generic_kw:
        raise LaunchError("no explicit keyword list (brands[].keywords)")
    camp_rn, budget_rn = f"customers/{cust}/campaigns/-2", f"customers/{cust}/campaignBudgets/-1"
    ops = [
        {"campaignBudgetOperation": {"create": {"resourceName": budget_rn, "name": c["name"] + " budget",
                                                "amountMicros": str(int(round(float(c["daily_budget"]) * 1e6))),
                                                "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        # startDate/endDate (YYYYMMDD): newer API versions may expect startDateTime/endDateTime instead — unverified for v21;
        # if Google rejects these fields, switch to "startDateTime": "YYYY-MM-DD 00:00:00".
        {"campaignOperation": {"create": {"resourceName": camp_rn, "name": c["name"], "status": "ENABLED",
                                          "advertisingChannelType": "SEARCH", "campaignBudget": budget_rn,
                                          bidding: {}, "startDate": c["start"].replace("-", ""), "endDate": c["end"].replace("-", ""),
                                          "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": False, "targetContentNetwork": False},
                                          "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
    ]
    for cc in countries:
        ops.append({"campaignCriterionOperation": {"create": {"campaign": camp_rn,
                                                              "location": {"geoTargetConstant": f"geoTargetConstants/{GEO[cc.upper()]}"}}}})
    langs = [l for l in (c["audience"].get("languages") or [lang]) if l]
    for l in langs:
        if l in LANG_CONST:
            ops.append({"campaignCriterionOperation": {"create": {"campaign": camp_rn,
                                                                  "language": {"languageConstant": f"languageConstants/{LANG_CONST[l]}"}}}})
        else:
            print(f"  note: no Google language constant for '{l}' — campaign runs without that language criterion")
    for tmp, label, kws in ((-3, "brand", brand_kw), (-4, "generic", generic_kw)):
        if not kws:
            continue
        ag = f"customers/{cust}/adGroups/{tmp}"
        ops.append({"adGroupOperation": {"create": {"resourceName": ag, "name": f"{c['name']} · {label}", "campaign": camp_rn,
                                                    "status": "ENABLED", "type": "SEARCH_STANDARD"}}})
        ops.append({"adGroupAdOperation": {"create": {"adGroup": ag, "status": "ENABLED",
                                                      "ad": {"finalUrls": [c.get("landing_url") or ""],
                                                             "responsiveSearchAd": {"headlines": [{"text": h} for h in heads],
                                                                                    "descriptions": [{"text": t} for t in descs]}}}}})
        for k in list(dict.fromkeys(kws))[:20]:
            ops.append({"adGroupCriterionOperation": {"create": {"adGroup": ag, "status": "ENABLED",
                                                                 "keyword": {"text": k[:80], "matchType": "PHRASE"}}}})
    if not c.get("landing_url"):
        raise LaunchError("no landing URL")
    return ops


def google_bidding(g):
    """maximizeConversions only when the account has an enabled conversion action; else Maximize clicks (targetSpend)."""
    rows = gaql(g, "SELECT conversion_action.id, conversion_action.status FROM conversion_action "
                   "WHERE conversion_action.status = 'ENABLED' LIMIT 1")
    if rows:
        return "maximizeConversions", None
    return "targetSpend", "no enabled conversion action in Google Ads — bidding Maximize clicks until conversion tracking exists"


def launch_google(d, c, g, dry=False):
    b = ap.brand(d, c["brand"]) or {"name": c["brand"], "id": c["brand"]}
    if dry:
        ops = google_ops(c, g, b)
        return {"ops": ops, "warning": "preflight (conversion action check) skipped in dry run"}
    bidding, warning = google_bidding(g)
    if warning:
        print("  warning:", warning)
    ops = google_ops(c, g, b, bidding)
    res = google_call(g, "googleAds:mutate", {"mutateOperations": ops})
    names = [r.get(k, {}).get("resourceName") for r in res.get("mutateOperationResponses", []) for k in r]
    return {"campaign": next((n for n in names if n and "/campaigns/" in n), None), "all": names, "bidding": bidding,
            "warning": warning, "done": True}


LAUNCH_CLAIM_MIN = 60


def _live_fb(p):
    return bool(p) and p.get("status") == "published" and p.get("platform") == "fb" and bool(p.get("remote_id"))


def boost_post(d, c):
    """The post a boost promotes: the planned one if it is live on Facebook, else the brand's best live Facebook post (plans
    are made before the month, when a new brand has nothing live yet). None when nothing is live."""
    p = ap.post(d, (c.get("creative") or {}).get("post") or "")
    if _live_fb(p):
        return p["id"]
    alt = next((q for q in best_creative_posts(d, c["brand"], n=10) if _live_fb(q)), None)
    return alt["id"] if alt else None


def _claim(cid):
    """Mark a campaign as being launched by this run. None when another run holds a fresh claim (two launch runs at once
    would each create a Meta campaign = double spend) or the campaign changed meanwhile. A stale claim (a crashed run) is
    taken over — launch_meta resumes from the ids saved in campaign.remote. Returns the fresh campaign."""
    with ap.transaction() as d:
        c = ap.campaign(d, cid)
        if c is None or c.get("status") != "approved" or c.get("compliance_hold") or (c.get("remote") or {}).get("done"):
            return None
        if ap.paused(d, c.get("brand")):              # the kill switch / a brand pause flipped while this run was working
            return None
        if ap.no_launch_why(d, c.get("brand"), c.get("network")):   # the plan changed while this run was working
            return None
        held = ap.parse_iso(c.get("launching_at"))
        if held and held.tzinfo and datetime.now(timezone.utc) - held < timedelta(minutes=LAUNCH_CLAIM_MIN):
            return None
        c["launching_at"] = ap.now_iso()
        return json.loads(json.dumps(c))


def _persist(cid, **fields):
    with ap.transaction() as d:
        c = ap.campaign(d, cid)
        if c is not None:
            c.update(fields)


def launch(bid=None, dry=False, base=pub.BASE):
    import otto_compliance as comp
    snap = ap.load()                                  # snapshot; every change is a short per-campaign transaction
    if ap.paused(snap):                               # owner console kill switch (otto_admin): nothing launches
        print(f"PAUSED  {ap.paused(snap)} — nothing launches"); return
    snap["campaigns"] = [c for c in snap.get("campaigns", []) if not ap.paused(snap, c["brand"])]   # paused brands launch nothing
    for c in snap.get("campaigns", []):
        t = today(ap.brand(snap, c["brand"]))
        if c["status"] != "approved" or (bid and c["brand"] != bid) or not (c["start"] <= t <= c["end"]):
            continue
        if c.get("compliance_hold") or (c.get("remote") or {}).get("done"):
            continue
        tag = f'{c["id"]} {c["network"]} {c["name"]} ({c["start"]}→{c["end"]}, {c.get("currency", "")}{c["daily_budget"]}/day)'
        why = ap.no_launch_why(snap, c["brand"], c["network"])     # no paid ads, or a trial (planned + previewed, never launched)
        if why:                                       # defence in depth: otto_cron skips the brand already
            print(f"SKIPPED {tag} — {why}")
            continue
        try:
            if c.get("objective") == "engagement" and (c.get("creative") or {}).get("post"):
                src = boost_post(snap, c)
                if src and src != c["creative"]["post"]:
                    print(f"  boost source {c['creative']['post']} is not live on Facebook — boosting {src} instead")
                    c = dict(c, creative=dict(c["creative"], post=src))
                    if not dry:
                        _persist(c["id"], creative=c["creative"])
            v = comp.check_campaign(c, _boost_texts(snap, c))
            if v:
                print(f"{'WOULD BLOCK' if dry else 'BLOCKED'} {tag} — compliance: {comp.describe(v)}")
                if not dry:
                    with ap.transaction() as d:
                        c2 = ap.campaign(d, c["id"])
                        c2["compliance_hold"] = True; c2["compliance"] = [x["rule"] for x in v][:6]
                        comp.file_block(d, c["brand"], f"campaign {c['id']} “{c['name'][:40]}”", v, "otto_ads", campaign_id=c["id"])
                continue
            creds = meta_creds(c["brand"]) if c["network"] == "meta" else google_creds(c["brand"])
            if not creds:
                print(f"NO-CREDS {tag}")
                if not dry:                          # the owner approved spend that can never start — say so once
                    net = "Meta ads" if c["network"] == "meta" else "Google Ads"
                    what = f"meta-{c['brand']}.json with an ad_account_id" if c["network"] == "meta" else f"google-{c['brand']}.json"
                    with ap.transaction() as d:
                        ap.add_rec_once(d, "P1", f"Connect {net} for {(ap.brand(d, c['brand']) or {}).get('name', c['brand'])} — approved flights are waiting",
                                        f"{c['id']} “{c['name'][:50]}” is approved and due since {c['start']}, but Otto has no {what}, so nothing launches.",
                                        "The approved budget starts working", "Connect", brand=c["brand"], source="otto_ads", campaign_id=c["id"])
                continue
            if not dry:
                fresh = _claim(c["id"])
                if fresh is None:
                    print(f"  skipped: {c['id']} is being launched by another run (or changed since the snapshot)"); continue
                c = fresh
            resume = " (resuming)" if c.get("remote") else ""
            print(f"{'WOULD LAUNCH' if dry else 'LAUNCH'} {tag}{resume}")
            if dry:
                if c["network"] == "google":
                    out = launch_google(snap, c, creds, dry=True)
                    print(json.dumps(out["ops"][:3], indent=1, ensure_ascii=False)[:700] + f" … ({len(out['ops'])} ops; {out['warning']})")
                else:
                    print("  " + json.dumps(meta_mode(snap, c, creds), ensure_ascii=False))
                continue
            if c["network"] == "meta":
                remote = launch_meta(snap, c, creds, base, persist=lambda **kw: _persist(c["id"], **kw))
            else:
                remote = launch_google(snap, c, creds)
            _persist(c["id"], remote=remote, status="live", launched_at=ap.now_iso(), error=None, launching_at=None)
            print(f"  live: {c['id']}")
            why = ap.paused(ap.load(), c["brand"])
            if why:                                   # switched off while the launch was in flight: stop the spend now
                print(f"  {why} — pausing {c['id']} right away")
                try:
                    pause(c["id"], by="kill_switch" if "kill switch" in why else "brand")
                except Exception as e:
                    with ap.transaction() as d:
                        ap.add_rec_once(d, "P0", f"Pause campaign {c['id']} by hand", f"It went live while publishing was paused, "
                                        f"and pausing it failed: {str(e)[:200]}", "It may still be spending", "Pause in Ads Manager",
                                        brand=c["brand"], source="otto_admin", campaign_id=c["id"])
        except Skipped as e:
            print(f"  skipped: {e}")
            if not dry:
                _persist(c["id"], status="skipped", error=str(e), launching_at=None)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}" if not isinstance(e, (pub.GraphError, LaunchError)) else str(e)
            print(f"  failed: {msg}")
            if dry:
                continue
            with ap.transaction() as d:
                c2 = ap.campaign(d, c["id"])
                if c2 is not None:
                    c2["status"] = "failed"; c2["error"] = msg[:500]; c2.pop("launching_at", None)
                    ap.add_rec_once(d, "P0", f"Campaign launch failed: {c['name'][:50]}", msg[:300] +
                                    (f" — objects already created are saved; `otto_ads.py retry {c['id']}` resumes." if c2.get("remote") else ""),
                                    "Budget is not spending", "Open campaign", brand=c["brand"], source="otto_ads", campaign_id=c["id"])


def set_meta_status(c, m, status):
    if not m:
        raise LaunchError(f"no Meta credentials for {c['brand']}")
    if (c.get("remote") or {}).get("campaign_id"):
        pub.graph("POST", c["remote"]["campaign_id"], m["access_token"], status=status)


def set_google_status(c, g, status):
    rn = (c.get("remote") or {}).get("campaign")
    if rn:
        if not g:
            raise LaunchError(f"no Google credentials for {c['brand']}")
        google_call(g, "campaigns:mutate", {"operations": [{"update": {"resourceName": rn, "status": status}, "updateMask": "status"}]})


def _remote_pause(c):
    if c["network"] == "meta":
        set_meta_status(c, meta_creds(c["brand"]), "PAUSED")
    else:
        set_google_status(c, google_creds(c["brand"]), "PAUSED")


def _remote_resume(c):
    if c["network"] == "meta":
        set_meta_status(c, meta_creds(c["brand"]), "ACTIVE")
    else:
        set_google_status(c, google_creds(c["brand"]), "ENABLED")


def pause(cid, dry=False, by="manual"):
    """Pause a campaign: remote first (raises → the state is NOT changed), then status paused + who paused it."""
    snap = ap.load()
    c = ap.campaign(snap, cid)
    assert c, f"unknown campaign {cid}"
    if not dry and c["status"] == "live":
        _remote_pause(c)                               # raises → state is NOT changed
    if dry:
        print(f"{cid} would be paused"); return
    _persist(cid, status="paused", paused_at=ap.now_iso(), paused_by=by)
    print(f"{cid} paused")


def resume(cid, dry=False):
    """paused → live (remote first; raises → the state is NOT changed). A flight whose end date has passed is marked
    ended instead of spending again; a paused brand or the kill switch refuses. Returns the new status."""
    snap = ap.load()
    c = ap.campaign(snap, cid)
    assert c, f"unknown campaign {cid}"
    if c.get("status") != "paused":
        raise LaunchError(f"{cid} is {c.get('status')}, not paused")
    why = ap.paused(snap, c.get("brand")) or ap.no_launch_why(snap, c.get("brand"), c.get("network"))
    if why:
        raise LaunchError(f"{cid} stays paused: {why}")
    if str(c.get("end") or "9999") < today(ap.brand(snap, c.get("brand"))):
        if not dry:
            _persist(cid, status="ended", ended_at=ap.now_iso(), paused_by=None)
        print(f"{cid} ended while paused — not resumed")
        return "ended"
    if dry:
        print(f"{cid} would be resumed"); return "live"
    _remote_resume(c)
    _persist(cid, status="live", resumed_at=ap.now_iso(), paused_by=None)
    print(f"{cid} resumed")
    return "live"


def guard(dry=False):
    snap = ap.load()
    for c in snap.get("campaigns", []):
        if c["status"] == "live" and c["end"] < today(ap.brand(snap, c["brand"])):
            print(f"ENDED {c['id']} {c['name']}")
            if dry:
                continue
            try:
                _remote_pause(c)
            except Exception as e:
                print("  pause failed — stays live, retried tomorrow:", e)
                with ap.transaction() as d:
                    ap.add_rec_once(d, "P0", f"Could not pause ended campaign: {c['name'][:50]}", str(e)[:300],
                                    "It may still be spending", "Pause by hand", brand=c["brand"], source="otto_ads", campaign_id=c["id"])
                continue
            _persist(c["id"], status="ended", ended_at=ap.now_iso())
    # CPL rule → recommendations come from report() (suggest); nothing auto-pauses unless ads[brand].auto_pause
    for bid, adsb in snap.get("ads", {}).items():
        if adsb.get("auto_pause"):
            for r in snap.get("recommendations", []):
                if r.get("source") == "otto_ads" and r["status"] == "proposed" and r.get("action") == "pause_campaign":
                    print(f"auto_pause on for {bid}: would act on {r['id']} ({r.get('campaign_id') or 'no campaign id'})")
    plan_guard(dry=dry)


def plan_guard(dry=False, bids=None):
    """What plans.json says after a downgrade, an expiry or an ended membership (runs inside guard, daily, whatever the
    kill switch): the one owner card per expired plan (ap.plan_expiry_notices), then every live campaign whose brand's plan
    no longer covers its network is paused through pause() (remote first, paused_by "plan"), with one owner card per brand
    that says so. A campaign that cannot be paused stays live and becomes a P0 "pause it by hand" card (retried tomorrow).
    A broken plans.json pauses nothing. bids = only these brands. → ids paused."""
    snap = ap.load()
    cfg = ap.plans_config()
    if cfg.get("error"):
        print(f"plans.json cannot be used ({cfg['error'][:200]}) — no campaign is paused because of plans")
        if not dry:
            with ap.transaction() as d:
                ap.add_rec_once(d, "P0", "Fix plans.json", f"{cfg['error'][:300]}. Until it is fixed every brand runs organic "
                                "only: no paid campaign is planned or launched (live ones are left alone).",
                                "Paid work is on hold for every client", "Fix plans.json", source="otto_admin", audience="owner")
        return []
    expired = []
    for b in snap.get("brands", []):
        p = ap.plan_of(snap, b["id"]) if isinstance(b, dict) and b.get("id") else None
        if p and p["expired"] and b.get("plan_notice") != f"expired:{p['requested']}:{p['until']}":
            expired.append(b["id"])
    if expired and not dry:
        with ap.transaction() as d:
            for bid in ap.plan_expiry_notices(d):
                print(f"PLAN {bid}: plan ended — owner card filed")
    paused_ids, by_brand = [], {}
    for c in snap.get("campaigns", []):
        if not isinstance(c, dict) or c.get("status") != "live" or (bids and c.get("brand") not in bids):
            continue
        why = ap.no_launch_why(snap, c.get("brand"), c.get("network"))
        if not why:
            continue
        print(f"{'WOULD PAUSE' if dry else 'PAUSE'} {c['id']} {c.get('name', '')} — {why}")
        if dry:
            continue
        try:
            pause(c["id"], by="plan")
        except Exception as e:                        # stays live; the card says so, tomorrow's guard retries
            print("  pause failed — stays live, retried tomorrow:", e)
            with ap.transaction() as d:
                ap.add_rec_once(d, "P0", f"Pause campaign {c['id']} by hand", f"{why}, but pausing the live campaign failed: "
                                f"{str(e)[:200]}", "It may still be spending", "Pause in Ads Manager",
                                brand=c.get("brand"), source="otto_admin", campaign_id=c["id"])
            continue
        paused_ids.append(c["id"])
        by_brand.setdefault(c.get("brand"), (why, []))[1].append(c["id"])
    for bid, (why, ids) in by_brand.items():
        with ap.transaction() as d:
            name = (ap.brand(d, bid) or {}).get("name") or bid
            ap.add_rec(d, "P1", f"{name}: {len(ids)} live campaign{'s' * (len(ids) != 1)} paused — not covered by the plan",
                       f"{', '.join(ids)} {'were' if len(ids) != 1 else 'was'} paused on Meta / Google because {why}. Nothing was "
                       "deleted: after an upgrade they can be resumed from the console.", "No spend the plan does not cover",
                       "Change the plan", brand=bid, source="plans", audience="owner", campaign_ids=ids)
    return paused_ids


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
    elif cmd == "resume":
        resume(a[1], dry="--dry" in a)
    elif cmd == "release":
        release(a[1])
    elif cmd == "retry":
        retry(a[1])
    else:
        print(__doc__)
