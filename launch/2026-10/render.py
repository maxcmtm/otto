#!/usr/bin/env python3
"""Otto launch kit, October 2026 — render, check and sheet every creative of the two launch matrices.

  python3 render.py check                       # the engine's matrix --check for both markets (nothing rendered)
  python3 render.py statics [--market ie|nl]    # every ready image cell: 4:5, 9:16 and 1:1 where the template supports it
  python3 render.py videos  [--market ie|nl] [--only id,id] [--jobs 3]
                                                # every faceless video cell with motion/ad-kit (build.mjs → ship.mjs):
                                                # 9:16, plus 4:5 for the notes / texts kits (the tuned ones)
  python3 render.py sheets                      # contact sheets of everything rendered → sheets/
  python3 render.py compliance                  # every text of every cell through otto_compliance + Meta length rules
  python3 render.py all                         # check, statics, videos, sheets, compliance

Sources: brands/otto/ads-2026-10-{ie,nl}.json (copy + render data), brands/otto/video/2026-10-{ie,nl}/*.json (kit files,
written by motion/ad-kit/from_matrix.py), brands/otto/video/brand.json. Output: creatives/<market>/{static,video}/ with clean
names (<cell-id>-4x5.jpg, <cell-id>-9x16.mp4 …) and creatives/<market>/manifest.json, which build.py reads.

The engine reads one matrix per brand and month (brands/<id>/ads-YYYY-MM.json) and one language per brand, so each market
renders in a throwaway workspace (the GTM doc's recipe): the brand folder is copied, the market's matrix becomes
ads-2026-10.json, render.json lang = en (English ads in both markets) and compliance countries = the market only. Nothing is
written to the repo's brands/ or to platform/data.json. Engine code is used as it is (otto_creative.build_matrix → otto_render).
Needs: python3, headless Chrome, ffmpeg, node + npx (hyperframes@0.8.91 is fetched by ship.mjs; set npm_config_cache to a
writable folder if ~/.npm is not writable — this script does that for you).
"""
import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PLATFORM = REPO / "platform"
BRAND = REPO / "brands" / "otto"
KIT = REPO / "motion" / "ad-kit"
MONTH = "2026-10"
MARKETS = ("ie", "nl")
RATIO = {"feed": "4x5", "story": "9x16", "square": "1x1"}
OUT = HERE / "creatives"
SHEETS = HERE / "sheets"


def arg(name, default=None):
    a = sys.argv
    return a[a.index(f"--{name}") + 1] if f"--{name}" in a and a.index(f"--{name}") + 1 < len(a) else default


def markets():
    m = arg("market")
    return [m] if m else list(MARKETS)


def matrix(mk):
    return json.loads((BRAND / f"ads-{MONTH}-{mk}.json").read_text())


# ---------------------------------------------------------------- isolated workspace per market

def workspace(mk):
    """A throwaway engine workspace for one market (GTM doc, 'Rendering Otto's own ads'). Returns (dir, env)."""
    w = Path(tempfile.mkdtemp(prefix=f"otto-launch-{mk}-"))
    for sub in ("brands", "assets", "fonts", "secrets", "tmp"):
        (w / sub).mkdir(parents=True, exist_ok=True)
    b = w / "brands" / "otto"
    shutil.copytree(BRAND, b)
    shutil.copyfile(BRAND / f"ads-{MONTH}-{mk}.json", b / f"ads-{MONTH}.json")
    r = json.loads((b / "render.json").read_text())
    r["lang"] = "en"                                   # English ads in both markets (owner's rule)
    (b / "render.json").write_text(json.dumps(r))
    c = json.loads((b / "compliance.json").read_text())
    c["countries"] = [mk.upper()]
    (b / "compliance.json").write_text(json.dumps(c))
    (w / "data.json").write_text('{"brands": [], "posts": [], "campaigns": [], "recommendations": []}')
    # Mona Sans from the landing's own woff2 (weights 400-800), so the cards never depend on a Google fetch
    key = hashlib.sha1((json.dumps(["Mona Sans"]) + json.dumps(["latin", "latin-ext"])).encode()).hexdigest()[:16]
    woff = base64.b64encode((BRAND / "assets" / "mona-sans-latin.woff2").read_bytes()).decode()
    (w / "fonts" / f"{key}.css").write_text("@font-face{font-family:'Mona Sans';font-style:normal;font-weight:400 800;"
                                           f"font-display:block;src:url(data:font/woff2;base64,{woff}) format('woff2');}}")
    env = dict(os.environ, OTTO_DATA=str(w / "data.json"), OTTO_HTML=str(w / "index.html"), OTTO_BRANDS=str(w / "brands"),
               OTTO_ASSETS=str(w / "assets"), OTTO_PUBLIC_ASSETS="", OTTO_SECRETS=str(w / "secrets"),
               OTTO_EVENTS=str(w / "events.jsonl"), OTTO_FONT_CACHE=str(w / "fonts"), OTTO_RENDER_TMP=str(w / "tmp"))
    return w, env


def in_workspace(mk, step, *extra):
    """Re-run this script inside the market's workspace (the engine reads its paths from the environment at import)."""
    w, env = workspace(mk)
    try:
        r = subprocess.run([sys.executable, str(Path(__file__)), step, mk, str(w), *extra], env=env, cwd=str(PLATFORM))
        return r.returncode
    finally:
        shutil.rmtree(w, ignore_errors=True)


def _engine():
    sys.path.insert(0, str(PLATFORM))
    import ap, otto_creative, otto_render, otto_styles, otto_compliance   # noqa: E401
    return ap, otto_creative, otto_render, otto_styles, otto_compliance


# ---------------------------------------------------------------- check

def _check(mk, w):
    r = subprocess.run([sys.executable, "otto_creative.py", "matrix", "otto", MONTH, "--check"], cwd=str(PLATFORM),
                       capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    print(f"== {mk.upper()} ==\n{out}\n(exit {r.returncode})")
    (HERE / "qa").mkdir(exist_ok=True)
    (HERE / "qa" / f"check-{mk}.txt").write_text(out + f"\n(exit {r.returncode})\n")
    return r.returncode


# ---------------------------------------------------------------- statics

def _statics(mk, w):
    ap, oc, orr, ost, _ = _engine()
    mx = ost.load_matrix("otto", MONTH)
    d = ap.load()
    c = {"id": f"otto-{MONTH}-{mk}", "brand": "otto", "plan": MONTH, "objective": "traffic"}
    tmp = Path(w) / "out"
    tmp.mkdir(exist_ok=True)
    cr = oc.build_matrix(d, c, mx, dry=False, out=tmp, publish=False, jobs=4)
    dst = OUT / mk / "static"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    ads = {}
    for con in cr["concepts"]:
        for ad in con["ads"]:
            if ad["format"] != "image":
                continue
            files = []
            for f in ad["files"]:
                ratio = RATIO[f["size"]]
                if f.get("cards"):
                    for j, card in enumerate(f["cards"], 1):
                        name = f"{ad['id']}-c{j}-{ratio}.jpg"
                        shutil.copyfile(card["file"], dst / name)
                        files.append({"file": f"static/{name}", "ratio": ratio, "card": j})
                else:
                    name = f"{ad['id']}-{ratio}.jpg"
                    shutil.copyfile(f["file"], dst / name)
                    files.append({"file": f"static/{name}", "ratio": ratio})
            ads[ad["id"]] = {"angle": ad["angle"], "style": ad["style"], "format": "image", "files": files}
    # QA: the renderer's own fit report for every card (story UI zones, contrast, final font sizes)
    tok = orr.brand_tokens("otto")
    lang = tok.get("lang") or "en"
    jobs = []
    for a in ost.live_angles(mx):
        for i, cell in enumerate(ost.live_cells(a)):
            if ost.fmt(cell) != "image":
                continue
            st = ost.resolve(cell.get("style"))
            data = oc._resolve_assets("otto", cell.get("data") or {})
            if not str(data.get("cta") or "").strip():
                btn = ost.ad_copy(a, cell, i)["cta"].upper() or "LEARN_MORE"
                data = dict(data, cta=orr.cta_label(btn, lang))
            cards = oc._carousel_cards(data) if st == "carousel" else [(ost.STYLES[st]["template"], data)]
            for size in ost.cell_sizes(cell):
                for j, (tpl, cd) in enumerate(cards, 1):
                    jobs.append((cell["id"], j if st == "carousel" else None, RATIO[size], tpl, cd, ost.SIZES[size]))

    def fit(job):
        cid, card, ratio, tpl, cd, size = job
        try:
            rep = orr.fit_report(tpl, cd, size, tok)
        except Exception as e:                     # noqa: BLE001
            rep = {"error": str(e)[:200]}
        return {"id": cid, "card": card, "ratio": ratio, "template": tpl,
                **{k: rep.get(k) for k in ("overflow", "offcanvas", "unsafe", "low_contrast", "missing", "broken", "error") if rep.get(k)}}

    with ThreadPoolExecutor(max_workers=4) as ex:
        qa = list(ex.map(fit, jobs))
    man_p = OUT / mk / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {}
    man.update({"market": mk.upper(), "month": MONTH, "statics": ads,
                "skipped": cr["matrix"]["skipped"], "fit_qa": qa})
    man_p.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n")
    n = sum(len(v["files"]) for v in ads.values())
    print(f"{mk.upper()}: {len(ads)} static ads, {n} files → {dst}")
    for s in cr["matrix"]["skipped"]:
        print(f"  SKIPPED {s['id']}: {s['status']} — {s['reason'][:200]}")
    for q in qa:
        flags = {k: v for k, v in q.items() if k in ("overflow", "offcanvas", "unsafe", "low_contrast", "missing", "broken", "error")}
        if flags:
            print(f"  qa {q['id']}{'-c' + str(q['card']) if q['card'] else ''}-{q['ratio']}: {json.dumps(flags, ensure_ascii=False)[:260]}")
    return 1 if cr["matrix"]["skipped"] else 0


# ---------------------------------------------------------------- videos

def _npm_env():
    env = dict(os.environ)
    if not os.access(Path.home() / ".npm" / "_cacache", os.W_OK) or os.environ.get("OTTO_NPM_CACHE"):
        cache = Path(os.environ.get("OTTO_NPM_CACHE") or Path(tempfile.gettempdir()) / "otto-npm-cache")
        cache.mkdir(parents=True, exist_ok=True)
        env["npm_config_cache"] = str(cache)
    return env


def videos():
    only = set((arg("only") or "").split(",")) - {""}
    jobs = int(arg("jobs", "3"))
    work = Path(tempfile.mkdtemp(prefix="otto-launch-video-"))
    env = _npm_env()
    todo = []
    for mk in markets():
        for a in matrix(mk)["angles"]:
            for cell in a["ads"]:
                if cell.get("format") != "video" or (only and cell["id"] not in only):
                    continue
                kit = BRAND / cell["video"]["data"]
                kd = json.loads(kit.read_text())
                for fmt in kd.get("formats") or ["9x16"]:
                    todo.append((mk, cell["id"], kit, fmt))

    def one(t):
        mk, cid, kit, fmt = t
        name = f"{cid}-{fmt}"
        proj = work / name
        final = OUT / mk / "video"
        final.mkdir(parents=True, exist_ok=True)
        log = []
        for cmd in (["node", "build.mjs", "--brand", str(BRAND / "video" / "brand.json"), "--ad", str(kit), "--out", str(proj), "--format", fmt],
                    ["node", "ship.mjs", str(proj), "--name", name, "--final", str(final)]):
            r = subprocess.run(cmd, cwd=str(KIT), env=env, capture_output=True, text=True)
            log.append(r.stdout[-1500:] + r.stderr[-1500:])
            if r.returncode != 0:
                return {"id": cid, "market": mk, "format": fmt, "ok": False, "log": "\n".join(log)[-2500:]}
        sheet = proj / "renders" / f"{name}-sheet.jpg"
        (SHEETS / "video").mkdir(parents=True, exist_ok=True)
        if sheet.exists():
            shutil.copyfile(sheet, SHEETS / "video" / sheet.name)
        sched = json.loads((proj / "schedule.json").read_text())
        return {"id": cid, "market": mk, "format": fmt, "ok": True, "duration": sched.get("duration"),
                "file": f"video/{name}.mp4", "poster": f"video/{name}.jpg",
                "summary": [l for l in log[-1].splitlines() if l.startswith(("✓", "  loudness", "  Check", "  ✓"))][-3:]}

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        res = list(ex.map(one, todo))
    for mk in markets():
        man_p = OUT / mk / "manifest.json"
        man = json.loads(man_p.read_text()) if man_p.exists() else {"market": mk.upper(), "month": MONTH}
        vids = man.get("videos") or {}
        for r in [x for x in res if x["market"] == mk]:
            v = vids.setdefault(r["id"], {"format": "video", "files": [], "failed": []})
            v["files"] = [f for f in v["files"] if f["ratio"] != r["format"]]
            v["failed"] = [f for f in v.get("failed", []) if f != r["format"]]
            if r["ok"]:
                v["files"].append({"file": r["file"], "poster": r["poster"], "ratio": r["format"], "duration": r["duration"]})
            else:
                v["failed"].append(r["format"])
        man["videos"] = vids
        man_p.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n")
    for r in res:
        print(("ok   " if r["ok"] else "FAIL ") + f"{r['id']}-{r['format']}" + (f" {r['duration']}s" if r["ok"] else "\n" + r["log"]))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if all(r["ok"] for r in res) else 1


# ---------------------------------------------------------------- contact sheets

def _sheets(mk, w):
    _, _, orr, _, _ = _engine()
    SHEETS.mkdir(exist_ok=True)
    man = json.loads((OUT / mk / "manifest.json").read_text())
    order = [c["id"] for a in matrix(mk)["angles"] for c in a["ads"]]
    for ratio in ("4x5", "9x16", "1x1"):
        groups = []
        for a in matrix(mk)["angles"]:
            files = []
            for c in a["ads"]:
                st = man.get("statics", {}).get(c["id"])
                for f in (st or {}).get("files", []):
                    if f["ratio"] == ratio:
                        files.append((str(OUT / mk / f["file"]), Path(f["file"]).stem))
            if files:
                groups.append((f"{mk.upper()} · {a['id']} · {a['name']}  ({ratio})", files))
        if groups:
            out = SHEETS / f"{mk}-statics-{ratio}.jpg"
            orr.contact_sheet(groups, out, cols=6 if ratio != "9x16" else 7, thumb_w=360 if ratio != "9x16" else 300)
            print("sheet", out)
    vs = sorted((SHEETS / "video").glob(f"{mk}-*-sheet.jpg"), key=lambda p: (order.index(re.sub(r"-(9x16|4x5)-sheet$", "", p.stem))
                                                                          if re.sub(r"-(9x16|4x5)-sheet$", "", p.stem) in order else 99, p.stem))
    if vs:
        out = SHEETS / f"{mk}-videos.jpg"
        orr.contact_sheet([(f"{mk.upper()} · faceless videos (4 key frames each: hook, middle, full scene, end card)",
                            [(str(p), p.stem.replace("-sheet", "")) for p in vs])], out, cols=2, thumb_w=900)
        print("sheet", out)
    return 0


# ---------------------------------------------------------------- compliance + Meta limits

DUTCH = re.compile(r"\b(de|het|een|je|jouw|niet|voor|met|zijn|wij|onze|gratis|klaar|goedkeuren|maand|ochtend|vandaag|"
                   r"bericht|zonder|nodig|dagen|uur|wat|ook)\b", re.I)
PRICE = re.compile(r"[€$£]\s?\d|\d\s?(?:euro|EUR)\b", re.I)
LIMITS = {"primary": 125, "headline": 40, "description": 30}


def _compliance(mk, w):
    ap, oc, orr, ost, comp = _engine()
    mx = ost.load_matrix("otto", MONTH)
    rep = ost.check_matrix("otto", MONTH, mx)
    status = {r["id"]: r for r in rep["cells"]}
    rows, total = [], 0
    for a in ost.live_angles(mx):
        for i, cell in enumerate(ost.live_cells(a)):
            texts = ost.cell_texts("otto", cell, a, i)
            cp = ost.ad_copy(a, cell, i)
            v_all = comp.check_texts("otto", texts, "ads", countries=[mk.upper()])
            per = []
            for t in texts:
                v = comp.check_texts("otto", [t], "ads", countries=[mk.upper()])
                per.append({"text": t, "violations": [x.get("rule") for x in v]})
            total += len(texts)
            lim = {k: len(cp[k]) for k in LIMITS}
            over = [f"{k} {lim[k]}/{LIMITS[k]}" for k in LIMITS if lim[k] > LIMITS[k]]
            sample = any("sample" in t.lower() for t in texts)
            prices = [t for t in texts if PRICE.search(t)]
            dutch = [t for t in texts if len(DUTCH.findall(t)) >= 2]
            rows.append({"id": cell["id"], "angle": a["id"], "style": cell["style"], "format": ost.fmt(cell),
                         "engine_status": status.get(cell["id"], {}).get("status"),
                         "engine_reasons": status.get(cell["id"], {}).get("reasons"),
                         "copy": cp, "lengths": lim, "over_limit": over, "n_texts": len(texts),
                         "violations": [{k: x.get(k) for k in ("rule", "match", "excerpt", "severity", "id") if x.get(k)} for x in v_all],
                         "money_figures": [{"text": t, "labelled_sample": sample} for t in prices],
                         "possible_dutch": dutch, "texts": per})
    out = {"market": mk.upper(), "month": MONTH, "checked_texts": total, "cells": rows,
           "matrix_gaps": rep["gaps"], "copy_gaps": rep["copy"], "size": rep["size"],
           "rules": {k: v for k, v in comp.rules("otto").items() if k in ("countries", "industries", "baseline", "error")},
           "baselines": [x["id"] for x, _ in comp.applicable(comp.rules("otto"))]}
    (HERE / "qa").mkdir(exist_ok=True)
    (HERE / "qa" / f"compliance-{mk}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    bad = [r for r in rows if r["violations"] or r["over_limit"] or r["possible_dutch"]
           or (r["money_figures"] and not all(m["labelled_sample"] for m in r["money_figures"]))]
    print(f"{mk.upper()}: {len(rows)} cells, {total} texts checked, {sum(len(r['violations']) for r in rows)} violations, "
          f"{len(bad)} cells flagged")
    return 0


def compliance_report():
    """qa/compliance-{ie,nl}.json → compliance-report.md (human-readable, every text with its result)."""
    L = ["# Compliance report: October 2026 launch (NL + IE)", "",
         "Generated by `python3 render.py compliance` with the engine's own checks: `otto_compliance.check_texts(…, \"ads\")` "
         "(brands/otto/compliance.json + the country baselines in otto_baselines.py for the market) on every text a viewer "
         "reads (primary text, headline, description, every word on the image, every line of the video kit file), "
         "`otto_styles.check_matrix` (competitor and platform names, placeholders, internal data, verbatim reviews), "
         "plus Meta's length limits (primary text ≤ 125 characters so nothing hides behind \"…more\", headline ≤ 40, "
         "description ≤ 30), a money-figure scan (no prices in ads: the only figures allowed are sample report numbers "
         "labelled \"Sample\") and a Dutch-word scan (English ads only).", ""]
    for mk in MARKETS:
        p = HERE / "qa" / f"compliance-{mk}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        rows = d["cells"]
        nv = sum(len(r["violations"]) for r in rows)
        over = [r for r in rows if r["over_limit"]]
        dutch = [r for r in rows if r["possible_dutch"]]
        money = [m for r in rows for m in r["money_figures"]]
        L += [f"## {d['market']}: {d['size']}", "",
              f"- Texts checked: **{d['checked_texts']}** across {len(rows)} ads · compliance violations: **{nv}** · "
              f"over Meta length limits: **{len(over)}** · non-English text: **{len(dutch)}** · money figures: "
              f"**{len(money)}** ({sum(1 for m in money if m['labelled_sample'])} in sample-labelled report screens, "
              f"{sum(1 for m in money if not m['labelled_sample'])} unlabelled)",
              f"- Rules applied: brand rules (compliance.json: Native's phrases, guarantees, fake scarcity, price-versus-agency, "
              f"multipliers) + baselines {', '.join(d['baselines']) or '(none)'} for {', '.join(d['rules'].get('countries') or [])}, "
              f"industries {', '.join(d['rules'].get('industries') or [])}",
              f"- Engine matrix check: coverage gaps {len(d['matrix_gaps'])}, copy gaps {len(d['copy_gaps'])}"
              + (": " + "; ".join(d["matrix_gaps"] + d["copy_gaps"]) if d["matrix_gaps"] or d["copy_gaps"] else ""), "",
              "| Ad | Style | Engine | Violations | Primary / headline / description (chars) | Notes |", "|---|---|---|---|---|---|"]
        for r in rows:
            notes = []
            if r["over_limit"]:
                notes.append("over limit: " + ", ".join(r["over_limit"]))
            if r["money_figures"]:
                notes.append("figures: " + "; ".join(f"“{m['text'][:50]}”" + (" (Sample)" if m["labelled_sample"] else " (UNLABELLED)")
                                                      for m in r["money_figures"]))
            if r["possible_dutch"]:
                notes.append("Dutch?: " + "; ".join(f"“{t[:40]}”" for t in r["possible_dutch"]))
            vio = "; ".join(f"{v.get('rule')} “{v.get('match')}”" for v in r["violations"]) or "0"
            eng = r["engine_status"] + (f" (rendered in creatives/{mk}/video; the matrix cell has no \"file\" yet)"
                                        if r["engine_status"] == "ready" and r["format"] == "video" else "")
            L.append(f"| {r['id']} | {r['style']} ({r['format']}) | {eng} | {vio} | {r['lengths']['primary']} / "
                     f"{r['lengths']['headline']} / {r['lengths']['description']} | {' · '.join(notes) or '–'} |")
        L += ["", f"### Every text checked ({d['market']})", ""]
        for r in rows:
            L.append(f"**{r['id']}**")
            L.append("")
            for t in r["texts"]:
                res = "clean" if not t["violations"] else "VIOLATION: " + ", ".join(t["violations"])
                L.append(f"- {res} · {t['text']}".replace("\n", " "))
            L.append("")
    (HERE / "compliance-report.md").write_text("\n".join(L) + "\n")
    print("wrote", HERE / "compliance-report.md")


# ---------------------------------------------------------------- CLI

STEPS = {"_check": _check, "_statics": _statics, "_sheets": _sheets, "_compliance": _compliance}


def main():
    a = sys.argv[1:]
    if a and a[0] in STEPS:                          # inside a workspace (re-executed with its environment)
        sys.exit(STEPS[a[0]](a[1], a[2]))
    cmd = a[0] if a else ""
    rc = 0
    if cmd in ("check", "all"):
        rc |= max(in_workspace(mk, "_check") for mk in markets())
    if cmd in ("statics", "all"):
        rc |= max(in_workspace(mk, "_statics") for mk in markets())
    if cmd in ("videos", "all"):
        rc |= videos()
    if cmd in ("sheets", "all"):
        rc |= max(in_workspace(mk, "_sheets") for mk in markets())
    if cmd in ("compliance", "all"):
        rc |= max(in_workspace(mk, "_compliance") for mk in markets())
        compliance_report()
    if cmd not in ("check", "statics", "videos", "sheets", "compliance", "all"):
        print(__doc__)
        return
    sys.exit(rc)


if __name__ == "__main__":
    main()
