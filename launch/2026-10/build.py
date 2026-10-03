#!/usr/bin/env python3
"""Otto launch kit, October 2026 — write the Meta Ads Manager bulk-import files once the domain (and the Meta ids) are known.

  python3 build.py                                                # placeholder build: links carry {DOMAIN}
  python3 build.py --domain otto.example                          # the minimum to import: every link gets the domain
  python3 build.py --domain otto.example --page-id 1234 --instagram-id 5678 --pixel-id 9012 \
                   [--exclude "2385…:Otto · signed up · 180 days"] [--campaign-id nl=1201…,ie=1202…] [--status PAUSED|ACTIVE]

Reads campaign.json (the spec), brands/otto/ads-2026-10-{nl,ie}.json (the copy) and creatives/<market>/manifest.json (the
rendered files, written by render.py). Writes import/:
  otto-<market>-part1.xlsx (+ .csv)   the campaign, ad sets a1-a3 and their ads (statics + 9 videos)
  otto-<market>-part2.xlsx (+ .csv)   ad sets a4-a6 and their ads (statics + 9 videos), added to the part-1 campaign: needs
                                      that campaign's id (--campaign-id), otherwise the Campaign ID cell says {NL_CAMPAIGN_ID}
                                      and Ads Manager refuses the file instead of creating a second campaign
  media/<market>-part<n>/             exactly the images and videos that part references (select the folder in the dialog)
  meta-bulk-import.xlsx               every row of both markets on one sheet (review copy), plus the media list and the
                                      manual steps (carousels, placement customisation)
Why two parts per market: the import dialog takes at most 10 videos (≤ 10 MB each) per import (Meta help 261309361378237);
each market has 18. Images and videos are attached in the import dialog under the exact file names in the sheet
(creatives/<market>/static/*-4x5.jpg, creatives/<market>/premium/*-1x1.jpg, creatives/<market>/video/*-9x16.mp4).

Without --page-id / --instagram-id / --pixel-id the cells carry {PAGE_ID} / {INSTAGRAM_ID} / {PIXEL_ID} so nothing is
imported with a wrong identity. Python 3.9 stdlib + openpyxl (optional: without it only the .csv files are written).
"""
import argparse, csv, json, os, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "import"
FIRST_PART = {"a1", "a2", "a3"}

COLUMNS = ["Campaign ID", "Campaign Name", "Campaign Status", "Special Ad Categories", "Campaign Objective", "Buying Type",
           "Campaign Daily Budget", "Campaign Bid Strategy", "Campaign Start Time",
           "Ad Set Name", "Ad Set Run Status", "Ad Set Time Start", "Ad Set Daily Budget", "Ad Set Minimum Spend Limit",
           "Destination Type", "Link Object ID", "Optimized Conversion Tracking Pixels", "Optimized Event", "Link",
           "Countries", "Gender", "Age Min", "Age Max", "Excluded Custom Audiences", "Publisher Platforms", "Device Platforms",
           "Optimization Goal", "Attribution Spec", "Billing Event", "Use Accelerated Delivery",
           "Ad Name", "Ad Status", "Title", "Body", "Display Link", "Link Description", "Optimize text per person",
           "Conversion Tracking Pixels", "Optimized Ad Creative", "Image File Name", "Creative Type", "URL Tags",
           "Video File Name", "Instagram Account ID", "Call to Action", "Additional Custom Tracking Specs", "Use Page as Actor"]


def meta_time(day):
    y, m, d = day.split("-")
    return f"{m}/{d}/{y} 12:00:00 am"                  # Ads Manager's export format, in the ad account's time zone


def ad_copy(angle, cell, i):
    """The engine's rule (otto_styles.ad_copy): the cell's override, else the angle's headlines / primaries rotated."""
    hs, ps = angle.get("headlines") or [], angle.get("primaries") or []
    return {"primary": cell.get("primary") or (ps[i % len(ps)] if ps else ""),
            "headline": cell.get("headline") or (hs[i % len(hs)] if hs else ""),
            "description": cell.get("description") or angle.get("description") or "",
            "cta": (cell.get("cta") or angle.get("cta") or "LEARN_MORE").upper()}


def rows_for(mk, spec, a):
    m = spec["markets"][mk]
    mx = json.loads((REPO / m["matrix"]).read_text())
    man_p = HERE / "creatives" / mk / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {}
    ob, bud, aud = spec["objective"], spec["budget"], spec["audience"]
    dom = a.domain if a.domain == "{DOMAIN}" else a.domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    page = f"o:{a.page_id}" if a.page_id else "o:{PAGE_ID}"
    ig = f"x:{a.instagram_id}" if a.instagram_id else "x:{INSTAGRAM_ID}"
    px = f"tp:{a.pixel_id}" if a.pixel_id else "tp:{PIXEL_ID}"
    cids = dict(x.split("=", 1) for x in (a.campaign_id or "").split(",") if "=" in x)
    rows, manual, media, warn = {1: [], 2: []}, [], [], []
    for angle in mx["angles"]:
        part = 1 if angle["id"] in FIRST_PART else 2
        for i, cell in enumerate(angle["ads"]):
            if cell.get("status") in ("dropped", "hold"):
                continue
            cp = ad_copy(angle, cell, i)
            cid = cell["id"]
            fmt = cell.get("format") or "image"
            st = (man.get("statics") or {}).get(cid) if fmt == "image" else None
            vd = (man.get("videos") or {}).get(cid) if fmt == "video" else None
            files = (st or vd or {}).get("files") or []
            by = {f["ratio"]: f for f in files if not f.get("card")}
            cards = sorted([f for f in files if f.get("card")], key=lambda f: (f["ratio"], f["card"]))
            media.append({"market": mk.upper(), "ad": cid, "concept": angle["id"], "style": cell["style"], "format": fmt,
                          "feed_4x5": (by.get("4x5") or {}).get("file", ""), "story_9x16": (by.get("9x16") or {}).get("file", ""),
                          "square_1x1": (by.get("1x1") or {}).get("file", ""),
                          "poster": (by.get("9x16") or {}).get("poster", ""),
                          "cards": ", ".join(Path(f["file"]).name for f in cards if f["ratio"] == "4x5")})
            if cell["style"] == "carousel":
                manual.append({"market": mk.upper(), "ad": cid, "ad_set": angle["ad_set"], "what": "carousel (create by hand)",
                               "files": ", ".join(Path(f["file"]).name for f in cards if f["ratio"] == "4x5"),
                               "headline": cp["headline"], "primary": cp["primary"], "cta": cp["cta"]})
                continue
            # the import row's image: the 4:5 render; a premium cell (a finished 1:1 + 9:16 ad, render.py premium) imports
            # its 1:1 (Meta's feed placements take 1:1; the 9:16 is in the media list for placement customisation)
            img = by.get("4x5") or (by.get("1x1") if (st or {}).get("premium") else None)
            if fmt == "image" and not img:
                warn.append(f"{cid}: no rendered {'1:1' if (st or {}).get('premium') else '4:5'} image in the manifest — "
                            f"run render.py {'premium' if (st or {}).get('premium') else 'statics'}")
                continue
            if fmt == "video" and "9x16" not in by:
                warn.append(f"{cid}: no rendered 9:16 video in the manifest — run render.py videos (left out of the import)")
                continue
            r = dict.fromkeys(COLUMNS, "")
            r.update({
                "Campaign ID": "" if part == 1 else cids.get(mk) or "{" + mk.upper() + "_CAMPAIGN_ID}",
                "Campaign Name": m["campaign"],
                "Ad Set Name": angle["ad_set"], "Ad Set Run Status": "ACTIVE", "Ad Set Time Start": meta_time(spec["start"]),
                "Ad Set Minimum Spend Limit": bud["ad_set_min_daily_days_1_7"], "Destination Type": "WEBSITE",
                "Link Object ID": page, "Optimized Conversion Tracking Pixels": px, "Optimized Event": ob["event"],
                "Link": f"https://{dom}/", "Countries": m["country"], "Age Min": aud["age_min"], "Age Max": aud["age_max"],
                "Excluded Custom Audiences": a.exclude or "", "Device Platforms": "mobile, desktop",
                "Optimization Goal": ob["optimization_goal"], "Attribution Spec": ob["attribution_spec"],
                "Billing Event": ob["billing_event"], "Use Accelerated Delivery": "No",
                "Ad Name": cid, "Ad Status": "ACTIVE", "Title": cp["headline"], "Body": cp["primary"], "Display Link": dom,
                "Link Description": cp["description"], "Optimize text per person": "No", "Conversion Tracking Pixels": px,
                "Optimized Ad Creative": "No",
                "URL Tags": spec["utm"].format(market=mk, ad_id=cid), "Instagram Account ID": ig, "Call to Action": cp["cta"],
                "Additional Custom Tracking Specs": "[]", "Use Page as Actor": "No"})
            if part == 1:                                  # the campaign is created once, by part 1
                r.update({"Campaign Status": a.status, "Campaign Objective": ob["campaign_objective"], "Buying Type": "AUCTION",
                          "Campaign Daily Budget": bud["campaign_daily"], "Campaign Bid Strategy": ob["bid_strategy"],
                          "Campaign Start Time": meta_time(spec["start"])})
            if fmt == "video":
                r.update({"Video File Name": Path(by["9x16"]["file"]).name, "Creative Type": "Video Page Post Ad"})
            else:
                r.update({"Image File Name": Path(img["file"]).name, "Creative Type": "Link Page Post Ad"})
            rows[part].append(r)
    return rows, manual, media, warn


def media_dir(mk, part, rows):
    """import/media/<market>-part<n>/: exactly the files this import references (hard links, so no extra disk), so the owner
    can select the whole folder in the import dialog."""
    d = OUT / "media" / f"{mk}-part{part}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for r in rows:
        for col, subs in (("Image File Name", ("static", "premium")), ("Video File Name", ("video",))):
            if r[col]:
                src = next((HERE / "creatives" / mk / sub / r[col] for sub in subs
                            if (HERE / "creatives" / mk / sub / r[col]).is_file()), HERE / "creatives" / mk / subs[0] / r[col])
                try:
                    os.link(src, d / r[col])
                except OSError:
                    shutil.copyfile(src, d / r[col])
    return d


def write_csv(path, rows):
    """UTF-16, tab-separated: the format Ads Manager itself exports (and so always re-imports)."""
    with open(path, "w", encoding="utf-16", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def write_xlsx(path, sheets):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for title, cols, rows in sheets:
        ws = wb.create_sheet(title[:31])
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([r.get(c, "") for c in cols])
        for i, c in enumerate(cols, 1):
            width = max([len(str(c))] + [len(str(r.get(c, ""))) for r in rows[:60]])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max(10, width + 2))
        ws.freeze_panes = "A2"
    wb.save(path)
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--domain", default="{DOMAIN}", help="the landing's domain, e.g. otto.example (no https://); "
                   "left out, every link carries the {DOMAIN} placeholder (not importable)")
    p.add_argument("--page-id", default="", help="Otto's Facebook Page id (Link Object ID)")
    p.add_argument("--instagram-id", default="", help="Otto's Instagram professional account id")
    p.add_argument("--pixel-id", default="", help="the dataset (pixel) id from Events Manager")
    p.add_argument("--exclude", default="", help="excluded custom audiences, 'id:name, id:name'")
    p.add_argument("--campaign-id", default="", help="part 2 only: 'nl=<id>,ie=<id>' (the campaigns part 1 created)")
    p.add_argument("--status", default="PAUSED", choices=["PAUSED", "ACTIVE"], help="campaign status on import (default PAUSED)")
    a = p.parse_args()
    if a.domain != "{DOMAIN}" and not re.fullmatch(r"(?:https?://)?[a-z0-9.-]+\.[a-z]{2,}/?", a.domain.strip().lower()):
        sys.exit(f"--domain {a.domain!r} does not look like a domain (example: otto.example)")
    spec = json.loads((HERE / "campaign.json").read_text())
    OUT.mkdir(exist_ok=True)
    allrows, manual, media, warns = [], [], [], []
    for mk in ("nl", "ie"):
        rows, man, med, warn = rows_for(mk, spec, a)
        manual += man
        media += med
        warns += warn
        for part in (1, 2):
            base = OUT / f"otto-{mk}-part{part}"
            write_csv(base.with_suffix(".csv"), rows[part])
            write_xlsx(base.with_suffix(".xlsx"), [(f"otto-{mk}-part{part}", COLUMNS, rows[part])])
            media_dir(mk, part, rows[part])
            vids = sum(1 for r in rows[part] if r["Video File Name"])
            print(f"{base.name}: {len(rows[part])} ads ({len(rows[part]) - vids} image, {vids} video)")
            allrows += [dict(r, Market=mk.upper(), Part=part) for r in rows[part]]
    ok = write_xlsx(HERE / "meta-bulk-import.xlsx", [
        ("all ads (review)", ["Market", "Part"] + COLUMNS, allrows),
        ("media", ["market", "ad", "concept", "style", "format", "feed_4x5", "story_9x16", "square_1x1", "poster", "cards"], media),
        ("manual steps", ["market", "ad", "ad_set", "what", "files", "headline", "primary", "cta"], manual)])
    print(("wrote meta-bulk-import.xlsx" if ok else "openpyxl missing: only the .csv files were written")
          + f" · {len(allrows)} ads in the import files, {len(manual)} by hand (carousels)")
    if a.domain == "{DOMAIN}":
        print("  note: no --domain: every Link / Display Link carries {DOMAIN}; rebuild with --domain <domain> before importing")
    for k, label in (("page_id", "--page-id"), ("instagram_id", "--instagram-id"), ("pixel_id", "--pixel-id")):
        if not getattr(a, k):
            print(f"  note: {label} not given — its cells carry a {{…}} placeholder; rebuild before importing")
    if not a.campaign_id:
        print("  note: part 2 files carry {NL_CAMPAIGN_ID} / {IE_CAMPAIGN_ID}: import part 1, copy the campaign ids, rebuild "
              "with --campaign-id nl=…,ie=…")
    for w in warns:
        print("  WARNING " + w)
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
