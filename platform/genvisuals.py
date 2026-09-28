#!/usr/bin/env python3
"""Otto visuals — an on-brand image for every post that needs one (Leonardo GPT Image 2).

  genvisuals.py [--brand <id>] [--ids hg-001,hg-002] [--limit 6] [--status draft,pending_approval] [--dry]

Reads data.json, picks posts without an image (or the given ids), builds a prompt from the brand's
visual identity plus the post's visual_brief / pillar / hook, fires the generations, polls, saves
assets/posts/<id>.jpg (named by the real type — Leonardo returns JPEG; anything else is converted,
Instagram only takes JPEG), copies it to the public assets dir (otto_paths.publish) and writes
image + visual_prompt back per post in a short ap.transaction. Sizes by format: story 9:16, feed/carousel 4:5, else 1:1.
Art direction — the brand guide always wins: the profile's VISUAL IDENTITY "Style:" line, else
brands/<slug>/*brand-guide*.md (its visual/style sections + don'ts), else the generic industry hint.
"Photorealistic" is only forced for the generic hint or a guide that asks for photography.
Rules: no text rendered in-image (Hebrew gets mangled; the caption carries the copy), no watermark,
clear space bottom-right for the logo, only the brand's palette. --dry prints the prompts and stops.
Key: env LEONARDO_API_KEY or platform/.leonardo_key (chmod 600). ~$0.20 per image (HIGH).
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

import ap
import otto_paths as paths

HERE = Path(__file__).parent
BRANDS = ap.BRANDS
BASE = "https://cloud.leonardo.ai/api/rest"
OUT = paths.ASSETS / "posts"
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


GUIDE_HEAD = re.compile(r"style|visual|art direction|imagery|photograph|motif|aesthetic|look and feel|"
                        r"סגנון|ויזואל|מוטיב|צילום|אסתטיק", re.I)
AVOID_HEAD = re.compile(r"don'?t|avoid|never|לא לעשות|להימנע|אסור", re.I)
NON_PHOTO = re.compile(r"illustrat|vector|flat design|cartoon|anime|\b3d\b|render|cgi|abstract|neon|glow|cosmic|collage|"
                       r"painting|watercolou?r|איור|גרפי|תלת|קוסמי|חלל|זוהר|נוירלי|אבסטרקט", re.I)
PHOTO = re.compile(r"photo|real people|product shot|צילום|אנשים אמיתיים|תמונות אמיתיות", re.I)


def _clean(line):
    return re.sub(r"\s+", " ", re.sub(r"\*\*|__|`|❌|✅|^[\s>\-\*•\d.]+", "", line)).strip()


def guide_direction(bid):
    """Art direction from brands/<slug>/*brand-guide*.md: bullet lines under visual/style/motif headings,
    plus the don'ts. '' when there is no guide or nothing usable in it."""
    files = sorted((BRANDS / bid).glob("*brand-guide*.md"))
    if not files:
        return ""
    keep, avoid, mode = [], [], None
    for ln in files[0].read_text().splitlines():
        if ln.startswith("#"):
            h = ln.lstrip("#").strip()
            mode = "avoid" if AVOID_HEAD.search(h) else "keep" if GUIDE_HEAD.search(h) else None
            continue
        if mode and ln.strip().startswith(("-", "*", "•")):
            item = _clean(ln)
            if 4 < len(item) < 200:
                (avoid if mode == "avoid" else keep).append(item)
    out = "; ".join(keep)[:420]
    if avoid:
        out += (". " if out else "") + "Avoid: " + "; ".join(avoid)[:240]
    return out


def art_direction(bid):
    """(style, source): profile Style line → brand guide → profile Motifs line → '' (caller uses the industry hint)."""
    prof = BRANDS / bid / "brand-profile.md"
    motifs = ""
    if prof.exists():
        m = re.search(r"VISUAL IDENTITY.*?(?=\n## |\Z)", prof.read_text(), re.S)
        if m:
            sm = re.search(r"Style:\s*(.+)", m.group(0))
            if sm and "(" not in sm.group(1)[:3] and "creative engine" not in sm.group(1).lower():
                return sm.group(1).strip()[:300], "profile"
            mm = re.search(r"Motifs?:\s*(.+)", m.group(0))
            motifs = _clean(mm.group(1))[:240] if mm else ""
    g = guide_direction(bid)
    if g:
        return (f"Motifs: {motifs}. {g}" if motifs else g)[:600], "guide"
    if motifs:
        return f"Motifs: {motifs}", "profile"
    return "", "industry"


def realism(style, source):
    """Only force photorealism where the art direction asks for photography (or there is no guide at all)."""
    if source == "industry" or not style:
        return "Photorealistic, premium"
    photo, other = bool(PHOTO.search(style)), bool(NON_PHOTO.search(style))
    if photo and not other:
        return "Photorealistic, premium"
    if other and not photo:
        return "Premium, rendered in the brand's own art direction (not photographic)"
    return "Premium, in the brand's own art direction (not generic stock photography)"


def brand_visual(bid):
    """(palette, industry, style). Palette: the profile's VISUAL IDENTITY hexes, else scan.json.
    Style: art_direction() (brand guide wins), else the industry hint."""
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
        if not industry:
            im = re.search(r"Industry:\*?\*?\s*(.+)", t)
            industry = im.group(1).strip()[:80] if im else ""
    if not pal and sj.exists():
        pal = [x["hex"] for x in json.loads(sj.read_text()).get("visual", {}).get("palette", [])[:4]]
    style, _ = art_direction(bid)
    hint = next((v for k, v in STYLE_HINT.items() if k in industry.lower()), "premium editorial, natural light")
    return pal, industry, style or hint


def prompt_for(d, p):
    b = ap.brand(d, p["brand"]) or {}
    pal, industry, style = brand_visual(p["brand"])
    _, source = art_direction(p["brand"])
    fmt = p.get("format", "post")
    shape = "vertical 9:16 story" if fmt == "story" else "vertical 4:5 feed" if fmt in ("feed", "carousel") else "square"
    scene = p.get("visual_brief") or p.get("brief") or f"{p.get('pillar','')} — the moment behind this idea (concept only, never render these words): “{p.get('hook','')}”"
    return (f"{shape} social visual for {b.get('name', p['brand'])}, {industry or 'brand'}. "
            f"Brand palette (mandatory, dominant): {', '.join(pal) or 'brand colors from the site'}. "
            f"Visual style: {style}. Scene: {scene}. "
            f"{realism(style, source)}, no text on image, no letters, no logos, no watermark, "
            f"leave clear space bottom-right for the brand logo.")


def post_json(u, body, k):
    r = urllib.request.Request(u, data=json.dumps(body).encode(),
                               headers={"authorization": f"Bearer {k}", "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=45) as x:
        return json.loads(x.read())


def save_image(pid, data):
    """Leonardo bytes → assets/posts/<id>.<real ext>; non-JPEG also gets a .jpg twin (Instagram). Returns the
    stored ref of the JPEG (or the original if conversion is impossible) after copying it to the public dir."""
    kind = paths.sniff(data) or "jpeg"
    path = OUT / f"{pid}{paths.EXT.get(kind, '.jpg')}"
    path.write_bytes(data)
    if kind != "jpeg":
        ff = shutil.which("ffmpeg")
        jpg = OUT / f"{pid}.jpg"
        if ff and subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(jpg)],
                                 capture_output=True).returncode == 0:
            path = jpg
        else:
            print("  warning: not JPEG and no ffmpeg — Instagram will refuse", path.name)
    paths.publish(path)
    return paths.rel_of(path)


def _patch(pid, fields, force=False):
    with ap.transaction() as d:
        q = ap.post(d, pid)
        if q is None:
            print("  gone while generating:", pid); return False
        if q.get("image") and not force and "image" in fields:
            print("  already has an image, kept:", pid); return False
        q.update(fields)
    return True


def run(bid=None, ids=None, limit=6, statuses=("draft", "pending_approval"), dry=False):
    d = ap.load()                                   # snapshot for selection; writes are per-post transactions
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
                    try:
                        q = urllib.request.Request(imgs[0]["url"], headers={"User-Agent": UA})
                        with urllib.request.urlopen(q, timeout=60) as x:
                            data = x.read()
                        ref = save_image(p["id"], data)
                        if _patch(p["id"], {"image": ref, "visual_prompt": pr, "visual_at": ap.now_iso()}, force=bool(ids)):
                            p["image"] = ref
                        done[p["id"]] = ref; print("SAVED", p["id"], ref, len(data))
                    except Exception as e:
                        done[p["id"]] = None; print("SAVE FAILED", p["id"], e)
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
            if p.get("format") == "carousel" and p.get("image") and done.get(p["id"]):
                slides = p.get("slides") or carousel_slides(p)
                pal = brand_visual(p["brand"])[0]
                files = []
                for i, txt in enumerate(slides[:5], 1):
                    dst = OUT / f"{p['id']}-{i}.jpg"
                    try:
                        cre.overlay_text(paths.local_path(p["image"]), dst, txt, pal[0] if pal else "#2447F0",
                                         pos="bottom" if i > 1 else "center", size=58)
                        paths.publish(dst)
                        files.append(paths.rel_of(dst))
                    except Exception as e:
                        print("slide failed", p["id"], i, e)
                if len(files) >= 2:
                    _patch(p["id"], {"images": files, "slides": slides})
    except Exception as e:
        print("carousel step skipped:", e)
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
