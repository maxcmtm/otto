#!/usr/bin/env python3
"""Otto competitor sweep — the automated half of otto-competitor-research (M6, weekly).

  otto_competitors.py list  <brand>
  otto_competitors.py add   <brand> <name> [site] [--type direct|aspirational|adjacent] [--fb url] [--ig handle] [--tiktok handle]
  otto_competitors.py sweep <brand> [--country DE] [--dry]
  otto_competitors.py formats <brand> <name> post=3,carousel=5,reel=8      # what they post (from the IG grid browse)
  otto_competitors.py angles <brand>                                      # research md + formats → angles.json (planner + ad creative read it)

What the script automates every week, per competitor:
  1. Reads their site (home + promo/news/collection pages) and fingerprints it: headlines,
     prices, promotions, socials. Diffs against last week's snapshot → "what changed".
  2. Builds the ad-intelligence checklist links (Meta Ad Library, Google Ads Transparency,
     TikTok Creative Center) that the agent opens with the browser tool to record
     longevity winners (the manual half — the skill describes what to capture).
  3. Appends a dated "Weekly sweep" section to brands/<slug>/competitor-research.md and,
     when something changed, files a recommendation in data.json so the owner sees it
     in Mission Control / Telegram ("Competitor sweep: 3 changes — review").

Competitor list: brands/<slug>/competitors.json (created from brand-profile.md's competitors
section on first run; sites without a URL are resolved via a DuckDuckGo lookup, best effort).
"""
import json, os, re, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import otto_scan as sc

HERE = Path(__file__).parent
BRANDS = Path(os.environ.get("OTTO_BRANDS") or HERE.parent / "brands")
PROMO_PAGES = ["sale", "offer", "deal", "promo", "new", "blog", "news", "collection", "product", "shop", "menu", "pricing"]
DROP_TOKENS = {"and", "etc", "others", "the", "all", "heavy", "on", "leaders", "gap", "most", "post", "generic"}


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cfile(bid):
    return BRANDS / bid / "competitors.json"


def load_list(bid):
    f = cfile(bid)
    if f.exists():
        return json.loads(f.read_text())
    return seed_from_profile(bid)


def save_list(bid, items):
    cfile(bid).parent.mkdir(parents=True, exist_ok=True)
    cfile(bid).write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")


def seed_from_profile(bid):
    """Best-effort: pull competitor names out of brand-profile.md's competitors section."""
    prof = BRANDS / bid / "brand-profile.md"
    if not prof.exists():
        return []
    lines = prof.read_text().splitlines()
    names, grab = [], False
    for ln in lines:
        if ln.startswith("#"):
            grab = "competitor" in ln.lower() or "מתחר" in ln
            continue
        if grab and ln.strip():
            body = re.sub(r"\(.*?\)", "", ln)
            body = body.split("—")[0].split(" - ")[0].split(":")[-1] if ":" in body.split("—")[0] else body.split("—")[0]
            for tok in re.split(r"[,·/|]| and ", body):
                tok = tok.strip(" -*•.").strip()
                if 2 < len(tok) < 40 and tok.lower() not in DROP_TOKENS and not tok.lower().startswith(("gap", "most", "all ")):
                    names.append(tok)
    items = [{"name": n, "site": "", "type": "direct", "fb": "", "ig": "", "tiktok": ""} for n in dict.fromkeys(names)][:8]
    if items:
        save_list(bid, items)
    return items


def guess_site(name, tlds=("com", "de", "eu", "co.uk", "co.il", "no")):
    """Try name-derived domains first (nordicoil.com, hempamed.de…): cheap, deterministic."""
    forms = [re.sub(r"[^a-z0-9]+", "", name.lower()), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")]
    for base in dict.fromkeys(f for f in forms if f):
      for tld in tlds:
        u = f"https://www.{base}.{tld}"
        final, html, ct = sc.fetch(u, limit=200_000, timeout=8)
        if html and "text/html" in ct and name.lower().split()[0] in html.lower()[:20000]:
            return "https://" + sc.host_of(final)
    return ""


def find_site(name):
    """Domain guesses, then a DuckDuckGo HTML lookup → first non-social result. '' on failure."""
    g = guess_site(name)
    if g:
        return g
    q = urllib.parse.quote_plus(name + " official site")
    _, html, _ = sc.fetch("https://duckduckgo.com/html/?q=" + q, limit=400_000)
    for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', html):
        u = urllib.parse.unquote(re.search(r"uddg=([^&]+)", href).group(1)) if "uddg=" in href else href
        host = sc.host_of(u)
        if host and not re.search(r"wikipedia|facebook|instagram|linkedin|amazon|youtube|tiktok|duckduckgo|trustpilot", host):
            return "https://" + host
    return ""


def ad_links(name, site, country):
    host = sc.host_of(site) if site else ""
    q = urllib.parse.quote_plus(name)
    return {
        "meta_ad_library": f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={country}&q={q}&search_type=keyword_unordered&media_type=all",
        "google_ads_transparency": f"https://adstransparency.google.com/?region={country}&domain={host}" if host else f"https://adstransparency.google.com/?region={country}&q={q}",
        "tiktok_creative_center": f"https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en?region={country}&period=30&search={q}",
    }


def fingerprint(site):
    """Fetch home + up to 3 promo/news pages → compact fingerprint for diffing."""
    url = sc.normalize_url(site)
    final, html, ctype = sc.fetch(url, limit=900_000)
    if not html:
        return {"error": ctype, "url": url}
    home = sc.parse(html)
    pages = [(final, home)]
    seen = set()
    for href, _, rel, _ in home.links:
        if rel != "a":
            continue
        u = sc.absolute(final, href).split("#")[0]
        path = urllib.parse.urlsplit(u).path.lower()
        if sc.host_of(u) == sc.host_of(final) and any(k in path for k in PROMO_PAGES) and u not in seen and u != final:
            seen.add(u)
            _, h, ct = sc.fetch(u, limit=600_000)
            if h and "text/html" in ct:
                pages.append((u, sc.parse(h)))
        if len(pages) >= 4:
            break
    text = " ".join(t for _, p in pages for t in p.texts)
    heads = list(dict.fromkeys(h for _, p in pages for _, h in p.headings))[:40]
    cur, prices = sc.prices_from(text)
    promos = list(dict.fromkeys(m.strip().lower() for m in sc.PROMO_RE.findall(text)))[:12]
    hrefs = [sc.absolute(final, href) for _, p in pages for href, _, _, _ in p.links]
    return {"url": final, "title": home.title.strip()[:160], "description": (home.metas.get("description") or "")[:300],
            "headings": heads, "prices": prices[:20], "currency": cur, "promos": promos,
            "socials": sc.socials_from(hrefs), "pages": [u for u, _ in pages], "platform": sc.detect_platform(html),
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def diff(old, new):
    if not old or "error" in old or "error" in new:
        return []
    ch = []
    if old.get("title") != new.get("title"):
        ch.append(f"title changed: “{old.get('title')}” → “{new.get('title')}”")
    for h in [h for h in new["headings"] if h not in old.get("headings", [])][:6]:
        ch.append(f"new headline: “{h}”")
    for h in [h for h in old.get("headings", []) if h not in new["headings"]][:3]:
        ch.append(f"removed headline: “{h}”")
    for p in [p for p in new["promos"] if p not in old.get("promos", [])]:
        ch.append(f"new promotion: {p}")
    for p in [p for p in old.get("promos", []) if p not in new["promos"]]:
        ch.append(f"promotion ended: {p}")
    if set(new["prices"][:8]) != set(old.get("prices", [])[:8]) and old.get("prices"):
        ch.append(f"price points moved: {', '.join(old['prices'][:4])} → {', '.join(new['prices'][:4])}")
    return ch


def sweep(bid, country=None, dry=False):
    items = load_list(bid)
    if not items:
        sys.exit(f"no competitors for {bid} — add with: otto_competitors.py add {bid} <name> <site>")
    country = country or guess_country(bid)
    snapdir = BRANDS / bid / "competitors"
    snapdir.mkdir(parents=True, exist_ok=True)
    report, total_changes = [], 0
    for it in items:
        if not it.get("site"):
            it["site"] = find_site(it["name"])
        key = re.sub(r"[^a-z0-9]+", "-", it["name"].lower()).strip("-")
        snap = snapdir / f"{key}.json"
        old = json.loads(snap.read_text()) if snap.exists() else None
        new = fingerprint(it["site"]) if it.get("site") else {"error": "no site", "url": ""}
        changes = diff(old, new)
        total_changes += len(changes)
        if not dry and "error" not in new:
            snap.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n")
        report.append((it, old, new, changes, ad_links(it["name"], it.get("site", ""), country)))
    if not dry:
        save_list(bid, items)
        append_report(bid, country, report, total_changes)
        file_recommendation(bid, report, total_changes, country)
    print_report(bid, country, report, total_changes, dry)
    return report


def guess_country(bid):
    try:
        import ap
        b = ap.brand(ap.load(), bid) or {}
        lang = (b.get("lang") or "").upper()
        return "IL" if "HE" in lang else "DE" if "DE" in lang else "US" if "US" in lang else "DE"
    except Exception:
        return "DE"


def print_report(bid, country, report, total, dry):
    print(f"Competitor sweep · {bid} · {today()} · country {country}{' · DRY' if dry else ''}")
    for it, old, new, changes, links in report:
        status = new.get("error") or ("first snapshot" if not old else f"{len(changes)} change(s)")
        print(f"- {it['name']} ({it.get('site') or 'no site'}) — {status}")
        for c in changes:
            print(f"    · {c}")
        if new.get("promos"):
            print(f"    live promos: {', '.join(new['promos'][:5])}")
    print(f"-- {total} changes across {len(report)} competitors")


def append_report(bid, country, report, total):
    path = BRANDS / bid / "competitor-research.md"
    head = "" if path.exists() else f"# Competitor Research — {bid}\n\n"
    lines = [f"\n## Weekly sweep {today()} · country {country} · {total} change(s)\n"]
    for it, old, new, changes, links in report:
        lines.append(f"### {it['name']} · {it.get('type', 'direct')} · {it.get('site') or 'site unknown'}")
        if new.get("error"):
            lines.append(f"- site fetch failed: {new['error']}")
        else:
            lines.append(f"- title: {new.get('title')}")
            lines.append("- changes since last sweep: " + ("; ".join(changes) if changes else ("first snapshot" if not old else "none visible")))
            if new.get("promos"):
                lines.append(f"- live promotions: {', '.join(new['promos'][:6])}")
            if new.get("prices"):
                lines.append(f"- price points: {', '.join(new['prices'][:6])}")
            if new.get("socials"):
                lines.append("- socials: " + ", ".join(f"{k} {v}" for k, v in new["socials"].items()))
        lines.append(f"- ads sweep (open with browser tool, record longevity winners 30+ days): "
                     f"[Meta Ad Library]({links['meta_ad_library']}) · [Google Ads]({links['google_ads_transparency']}) · [TikTok top ads]({links['tiktok_creative_center']})")
        lines.append("- longevity winners / hooks / offers: _(agent fills)_\n")
    lines.append("### Synthesis → content plan\n- steal-and-improve angles: _(agent fills)_\n- gaps nobody runs: _(agent fills)_\n- briefs for otto-creative-engine: _(agent fills, 3-5)_\n")
    with path.open("a") as f:
        f.write(head + "\n".join(lines))


def file_recommendation(bid, report, total, country="DE"):
    """Summary card for Mission Control (competitors[brand]) + a recommendation when something moved.
    Runs after all the fetching, in one short ap.transaction; a re-run does not stack a duplicate card."""
    import ap
    if not ap.DATA.exists():
        print("(no data.json here — summary/recommendation not filed; run on the server)"); return
    with ap.transaction() as d:
        d.setdefault("competitors", {})[bid] = {
            "last_sweep": today(), "country": country, "changes": total,
            "items": [{"name": it["name"], "site": it.get("site", ""), "type": it.get("type", "direct"),
                       "promos": (new.get("promos") or [])[:4], "changes": ch[:3], "error": new.get("error")}
                      for it, _, new, ch, _ in report]}
        if total:
            names = [it["name"] for it, _, _, ch, _ in report if ch][:3]
            r = ap.add_rec_once(d, "P2", f"Competitor sweep: {total} change(s) at {', '.join(names)}",
                                "Weekly automated sweep found new headlines, promotions or price moves on competitor sites. "
                                "Nova turns them into steal-and-improve briefs once you confirm which matter.",
                                "Fresh angles for next week's plan", "Review sweep", brand=bid, source="otto_competitors")
            print(f"filed {r['id']} in data.json")


def angles(bid):
    """competitor-research.md (longevity winners, synthesis, briefs) + competitors[].formats → brands/<slug>/angles.json.
    The agent fills those sections after the ad-library browse; this turns them into data the planner and the ad
    creative engine read. Placeholders '(agent fills)' are ignored."""
    path = BRANDS / bid / "competitor-research.md"
    out, formats, grab = [], {}, False
    if path.exists():
        for ln in path.read_text().splitlines():
            if ln.startswith("#"):
                grab = any(k in ln.lower() for k in ("longevity", "steal", "synthesis", "gaps", "briefs", "winners"))
                continue
            t = ln.strip()
            if grab and t.startswith(("-", "*", "|")) and "agent fills" not in t and "_(" not in t:
                t = t.lstrip("-*| ").strip()
                if 12 < len(t) < 200 and not t.startswith("longevity winners") and not t.lower().startswith(("id |", "steal-and-improve angles:", "gaps nobody runs:", "briefs for")):
                    out.append({"angle": t, "source": "competitor-research"})
    for it in load_list(bid):
        for f, n in (it.get("formats") or {}).items():
            formats[f] = formats.get(f, 0) + n
    data = {"angles": out[:12], "formats": formats, "updated": today()}
    (BRANDS / bid).mkdir(parents=True, exist_ok=True)
    (BRANDS / bid / "angles.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"{bid}: {len(out)} angle(s), formats {formats or '—'} → angles.json")
    return data


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__); return
    cmd, bid = a[0], a[1]
    if cmd == "list":
        for it in load_list(bid):
            print(f"{it['name']:28} {it.get('type', 'direct'):12} {it.get('site') or '—'}")
    elif cmd == "add":
        items = load_list(bid)
        it = {"name": a[2], "site": a[3] if len(a) > 3 and not a[3].startswith("--") else "", "type": "direct", "fb": "", "ig": "", "tiktok": ""}
        for k in ("type", "fb", "ig", "tiktok"):
            if f"--{k}" in a:
                it[k] = a[a.index(f"--{k}") + 1]
        items = [x for x in items if x["name"].lower() != it["name"].lower()] + [it]
        save_list(bid, items)
        print(f"{bid}: {len(items)} competitors")
    elif cmd == "sweep":
        country = a[a.index("--country") + 1] if "--country" in a else None
        sweep(bid, country, dry="--dry" in a)
        if "--dry" not in a:
            angles(bid)
    elif cmd == "angles":
        angles(bid)
    elif cmd == "formats":                       # otto_competitors.py formats <brand> <name> post=3,carousel=5,reel=8  (from the IG grid browse)
        items = load_list(bid)
        it = next((x for x in items if x["name"].lower() == a[2].lower()), None)
        assert it, f"unknown competitor {a[2]}"
        it["formats"] = {k: int(v) for k, v in (kv.split("=") for kv in a[3].split(","))}
        save_list(bid, items); print(f"{it['name']}: formats {it['formats']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
