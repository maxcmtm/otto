#!/usr/bin/env python3
"""Otto visuals — an on-brand image for every post that needs one (Leonardo GPT Image 2).

  genvisuals.py [--brand <id>] [--ids hg-001,hg-002] [--limit 6] [--status draft,pending_approval] [--dry]

Reads data.json, picks posts without an image (or the given ids), builds a prompt from the brand's
visual identity (palette from brands/<slug>/scan.json or brand-profile.md, style hint, industry) plus
the post's visual_brief / pillar / hook, fires the generations, polls, saves assets/posts/<id>.png and
writes image + visual_prompt back through ap.py. Sizes by format: story 9:16, feed/carousel 4:5, else 1:1.
Rules: no text rendered in-image (Hebrew gets mangled; the caption carries the copy), no watermark,
clear space bottom-right for the logo, only the brand's palette. --dry prints the prompts and stops.
Key: env LEONARDO_API_KEY or platform/.leonardo_key (chmod 600). ~$0.20 per image (HIGH).
"""
import json, os, re, sys, time, urllib.request
from pathlib import Path

import ap

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
BASE = "https://cloud.leonardo.ai/api/rest"
OUT = HERE / "assets" / "posts"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
SIZES = {"story": (768, 1376), "feed": (848, 1264), "carousel": (848, 1264), "square": (1024, 1024)}
STYLE_HINT = {"cbd": "premium wellness editorial, botanical, natural light, calm",
              "restaurant": "warm appetizing food photography, natural light, inviting",
              "clinic": "clean clinical-warm, soft light, trust and calm",
              "education": "warm human documentary, hopeful, real people, soft golden light",
              "e-commerce": "bright clean product photography, studio light",
              "real estate": "architectural, wide, golden hour, aspirational",
              "saas": "modern abstract 3D, glass and light, minimal",
              "fitness": "energetic, high contrast, motion",
              "beauty": "soft luxurious skin-tone editorial",
              "hotel": "cinematic travel, warm, wide",
              "coaching": "confident portrait editorial, warm",
              "marketing": "modern editorial, bold color blocks"}


def key():
    k = os.environ.get("LEONARDO_API_KEY")
    if k:
        return k.strip()
    f = HERE / ".leonardo_key"
    if f.exists():
        return f.read_text().strip()
    sys.exit("no Leonardo key (LEONARDO_API_KEY or platform/.leonardo_key)")


def brand_visual(bid):
    """Palette + style from scan.json, else from the profile's VISUAL IDENTITY line."""
    pal, industry, style = [], "", ""
    prof = BRANDS / bid / "brand-profile.md"
    sj = BRANDS / bid / "scan.json"
    if sj.exists():
        s = json.loads(sj.read_text())
        industry = s.get("industry", "")
    if prof.exists():
        t = prof.read_text()
        m = re.search(r"VISUAL IDENTITY.*?(?=\n## |\Z)", t, re.S)
        if m:
            # the curated profile palette wins; the raw scan is the fallback
            pal = list(dict.fromkeys(re.findall(r"#[0-9A-Fa-f]{6}", m.group(0))))[:4]
            sm = re.search(r"Style:\s*(.+)", m.group(0))
            if sm and "(" not in sm.group(1)[:3]:
                style = sm.group(1).strip()[:160]
        if not industry:
            im = re.search(r"Industry:\*?\*?\s*(.+)", t)
            industry = im.group(1).strip()[:80] if im else ""
    if not pal and sj.exists():
        pal = [x["hex"] for x in json.loads(sj.read_text()).get("visual", {}).get("palette", [])[:4]]
    hint = next((v for k, v in STYLE_HINT.items() if k in industry.lower()), "premium editorial, natural light")
    return pal, industry, style or hint


def prompt_for(d, p):
    b = ap.brand(d, p["brand"]) or {}
    pal, industry, style = brand_visual(p["brand"])
    fmt = p.get("format", "post")
    shape = "vertical 9:16 story" if fmt == "story" else "vertical 4:5 feed" if fmt in ("feed", "carousel") else "square"
    scene = p.get("visual_brief") or p.get("brief") or f"{p.get('pillar','')} — the moment behind this idea (concept only, never render these words): “{p.get('hook','')}”"
    return (f"{shape} social visual for {b.get('name', p['brand'])}, {industry or 'brand'}. "
            f"Brand palette (mandatory, dominant): {', '.join(pal) or 'brand colors from the site'}. "
            f"Visual style: {style}. Scene: {scene}. "
            f"Photorealistic, premium, no text on image, no letters, no logos, no watermark, "
            f"leave clear space bottom-right for the brand logo.")


def post_json(u, body, k):
    r = urllib.request.Request(u, data=json.dumps(body).encode(),
                               headers={"authorization": f"Bearer {k}", "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=45) as x:
        return json.loads(x.read())


def run(bid=None, ids=None, limit=6, statuses=("draft", "pending_approval"), dry=False):
    d = ap.load()
    todo = [p for p in d["posts"] if (ids and p["id"] in ids) or
            (not ids and p["status"] in statuses and not p.get("image") and (not bid or p["brand"] == bid))]
    todo = todo[:limit]
    if not todo:
        print("nothing to generate"); return
    OUT.mkdir(parents=True, exist_ok=True)
    plans = [(p, prompt_for(d, p)) for p in todo]
    for p, pr in plans:
        print(f"{'WOULD FIRE' if dry else 'FIRE'} {p['id']} [{p.get('format','post')}]\n   {pr}\n")
    if dry:
        return
    k = key()
    jobs = []
    for p, pr in plans:
        w, h = SIZES.get(p.get("format", "post"), SIZES["square"])
        body = {"model": "gpt-image-2", "parameters": {"width": w, "height": h, "prompt": pr,
                "quality": "HIGH", "quantity": 1, "prompt_enhance": "OFF"}, "public": False}
        try:
            gid = post_json(f"{BASE}/v2/generations", body, k)["generate"]["generationId"]
            jobs.append((p, pr, gid)); print("fired", p["id"], gid)
        except Exception as e:
            print("ERR", p["id"], e)
        time.sleep(1)
    done, deadline = {}, time.time() + 480
    while len(done) < len(jobs) and time.time() < deadline:
        for p, pr, gid in jobs:
            if p["id"] in done:
                continue
            try:
                req = urllib.request.Request(f"{BASE}/v1/generations/{gid}", headers={"authorization": f"Bearer {k}"})
                with urllib.request.urlopen(req, timeout=30) as x:
                    g = json.loads(x.read()).get("generations_by_pk") or {}
            except Exception as e:
                print("poll err", p["id"], e); continue
            if g.get("status") == "COMPLETE":
                imgs = g.get("generated_images") or []
                if imgs:
                    q = urllib.request.Request(imgs[0]["url"], headers={"User-Agent": UA})
                    with urllib.request.urlopen(q, timeout=60) as x:
                        data = x.read()
                    path = OUT / f"{p['id']}.png"
                    path.write_bytes(data)
                    p["image"] = f"assets/posts/{p['id']}.png"; p["visual_prompt"] = pr; p["visual_at"] = ap.now_iso()
                    done[p["id"]] = str(path); print("SAVED", p["id"], len(data))
                else:
                    done[p["id"]] = None; print("EMPTY", p["id"])
            elif g.get("status") == "FAILED":
                done[p["id"]] = None; print("FAILED", p["id"])
        if len(done) < len(jobs):
            time.sleep(12)
    # carousels: 3 slides with the copy on them (hook / point / point), from the base image + 2 more
    try:
        import otto_creative as cre
        for p, pr, gid in jobs:
            if p.get("format") == "carousel" and p.get("image"):
                slides = p.get("slides") or carousel_slides(p)
                pal = brand_visual(p["brand"])[0]
                files = []
                for i, txt in enumerate(slides[:5], 1):
                    dst = OUT / f"{p['id']}-{i}.png"
                    try:
                        cre.overlay_text(HERE / p["image"], dst, txt, pal[0] if pal else "#2447F0", pos="bottom" if i > 1 else "center", size=58)
                        files.append(f"assets/posts/{dst.name}")
                    except Exception as e:
                        print("slide failed", p["id"], i, e)
                if len(files) >= 2:
                    p["images"] = files; p["slides"] = slides
    except Exception as e:
        print("carousel step skipped:", e)
    ap.save(d)
    print("DONE", json.dumps(done))


def carousel_slides(p):
    """Hook + up to 4 caption sentences → slide texts (Quill can pre-write post.slides for better ones)."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", p.get("caption") or "") if 15 <= len(s.strip()) <= 120 and not s.strip().startswith("#")]
    return [p.get("hook") or sents[0]] + [s for s in sents if s != p.get("hook")][:4]


if __name__ == "__main__":
    a = sys.argv[1:]
    run(bid=a[a.index("--brand") + 1] if "--brand" in a else None,
        ids=set(a[a.index("--ids") + 1].split(",")) if "--ids" in a else None,
        limit=int(a[a.index("--limit") + 1]) if "--limit" in a else 6,
        statuses=tuple(a[a.index("--status") + 1].split(",")) if "--status" in a else ("draft", "pending_approval"),
        dry="--dry" in a)
