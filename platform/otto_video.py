#!/usr/bin/env python3
"""Otto reels — 30–60 s explainer videos for every brand, in the base package.

  otto_video.py plan   <post-id> [--seconds 45]         # scene script from the post (Quill may write post.script first)
  otto_video.py render <post-id> [--dry] [--no-voice]    # scenes → images → voice-over → ffmpeg → assets/reels/<id>-<token>.mp4 → post.video
  otto_video.py demo   <out.mp4> [--voice]               # render a sample reel from existing post images (local check)
  otto_video.py missing [--brand <id>]                   # ids of reel posts (draft/pending_approval) that have no video yet and
                                                         # whose words are written (hook, caption or script) — the cron loop

A reel = 4–7 scenes. Each scene: one on-brand vertical 9:16 image (GPT Image 2 through the Higgsfield Cloud API when
otto_imagegen is configured — scene_model, 2k, quality "medium" ≈ $0.06 a scene, at most `parallel` at a time — else Leonardo;
without either key, or when both fail, the post's own picture / a brand-colour card), a slow Ken Burns move, a caption in
the brand band (ffmpeg drawtext, same typography as the ad statics),
optional voice-over (ElevenLabs, $OTTO_SECRETS/elevenlabs.json {api_key, voice_id}) and a music bed
from assets/music/*.mp3 (royalty-free, optional). 1080×1920, 30 fps, H.264 + AAC, capped at 60 s.
post.script = [{"text","seconds","visual"}] — if missing, `plan` derives it from hook + caption.
A reel whose words are not written yet (no hook, no caption, no script: the copywriter has not reached it) is never rendered:
`missing` leaves it out and `render` refuses it — a video made from the brand name alone would reach the client's Review.
Scene images and voice clips are cached per scene under assets/reels/<post-id>/ keyed by a hash of the
scene text (+ visual / voice), so editing one line of the script re-renders only that scene.
The finished mp4 is copied to the public assets dir (otto_paths.publish) before post.video is set.
Provenance (EU AI Act Art. 50(2), otto_provenance): generated scene images are marked when they are saved; a reel that
contains a generated scene or a synthetic voice is marked as compositeSynthetic (MP4 comment/description
tags + XMP uuid box + <mp4>.provenance.json) before it is made public, and post.media_ai[<ref>] records what is synthetic.
Needs ffmpeg + ffprobe on PATH and a TTF font (OTTO_FONT or the defaults in otto_creative.py).
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path

import ap
import otto_creative as cre
import otto_paths as paths
import otto_provenance as prov

HERE = Path(__file__).parent
BRANDS = ap.BRANDS
REELS = paths.ASSETS / "reels"
MUSIC = paths.ASSETS / "music"
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
W, H, FPS = 1080, 1920, 30


def sh(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])
    return r.stdout


def duration(path):
    out = sh([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip() or 0)


# ---------------- script ----------------

LINK_IN_BIO = {"en": "Link in bio.", "he": "הקישור בביו.", "de": "Link in der Bio.", "pt": "Link na bio.", "nl": "Link in de bio.",
               "it": "Trovi il link nella bio.", "fr": "Lien en bio.", "es": "Enlace en la bio."}


def plan_script(p, b, seconds=45):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", (p.get("caption") or "")) if 12 <= len(s.strip()) <= 140]
    sents = [s for s in sents if not s.startswith("#")]
    hook = p.get("hook") or (sents[0] if sents else b.get("name", ""))
    body = [s for s in sents if s != hook][:4]
    lines = [hook] + body + [f"{b.get('name', '')}. {LINK_IN_BIO.get(ap.brand_lang(b), LINK_IN_BIO['en'])}"]
    per = max(5, min(9, seconds // len(lines)))
    return [{"text": t, "seconds": per, "visual": f"{p.get('pillar', '')} — {t}"} for t in lines][:7]


# ---------------- assets ----------------

def scene_key(*parts):
    return hashlib.sha1("\x1f".join(str(x or "") for x in parts).encode("utf-8")).hexdigest()[:12]


def _cached(d, stem):
    hits = sorted(d.glob(stem + ".*"))
    return hits[0] if hits else None


def scene_prompt(p, sc, gv):
    pal, industry, style = gv.brand_visual(p["brand"])
    return (f"vertical 9:16 social video frame, {industry or 'brand'}. Brand palette (dominant): {', '.join(pal) or 'brand colors'}. "
            f"Visual style: {style}. Scene: {sc.get('visual') or sc['text']} (concept only, never render words). "
            f"Cinematic, premium, no text, no logos, no watermark, clear space in the lower third for a caption.")


def _higgsfield_scenes(p, d, stems, prompts, out):
    """Missing scenes through Higgsfield (otto_imagegen, scene_model, 9:16) → fills out[i]; quiet when it is not configured."""
    try:
        import otto_imagegen as ig
        if not ig.ready():
            return
    except Exception as e:                                   # noqa: BLE001 — Leonardo / the fallback still run
        print("scene images: Higgsfield config unreadable:", type(e).__name__); return
    todo = sorted(prompts)
    res = ig.generate_many([{"prompt": prompts[i], "aspect": "9:16", "brand": p["brand"], "purpose": "scene"} for i in todo])
    for i, r in zip(todo, res):
        if isinstance(r, Exception):
            print(f"scene {i + 1} image (Higgsfield) failed: {type(r).__name__}: {r}"); continue
        data, kind = r["images"][0]
        f = d / (stems[i] + paths.EXT.get(kind, ".png"))   # named by real type; cached under the scene key
        f.write_bytes(data)
        prov.mark_safely(f, ["image"], r["tool"])
        out[i] = f


def _leonardo_scene(gv, key, prompt, d, stem):
    """One scene through Leonardo → the saved file or None."""
    import time
    try:
        gid = gv.post_json(f"{gv.BASE}/v2/generations", {"model": "gpt-image-2", "parameters": {"width": 768, "height": 1376, "prompt": prompt,
                           "quality": "HIGH", "quantity": 1, "prompt_enhance": "OFF"}, "public": False}, key)["generate"]["generationId"]
        for _ in range(40):
            time.sleep(12)
            req = urllib.request.Request(f"{gv.BASE}/v1/generations/{gid}", headers={"authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as x:
                g = json.loads(x.read()).get("generations_by_pk") or {}
            if g.get("status") == "COMPLETE" and g.get("generated_images"):
                q = urllib.request.Request(g["generated_images"][0]["url"], headers={"User-Agent": gv.UA})
                with urllib.request.urlopen(q, timeout=60) as x:
                    data = x.read()
                f = d / (stem + paths.EXT.get(paths.sniff(data) or "", ".jpg"))   # named by real type
                f.write_bytes(data)
                prov.mark_safely(f, ["image"], gv.TOOL)
                return f
            if g.get("status") == "FAILED":
                return None
    except Exception as e:
        print("scene image failed:", e)
    return None


def scene_images(p, script, dry):
    """One 9:16 image per scene, cached by a hash of the scene (brand + visual + text): Higgsfield first when configured,
    then Leonardo for what is still missing, then the fallback. Dry / no key → reuse the post image."""
    d = REELS / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    stems = ["s-" + scene_key(p["brand"], sc.get("visual"), sc.get("text")) for sc in script]
    out = [_cached(d, stem) for stem in stems]
    if not dry and any(f is None for f in out):
        import genvisuals as gv
        prompts = {i: scene_prompt(p, sc, gv) for i, sc in enumerate(script) if out[i] is None}
        _higgsfield_scenes(p, d, stems, prompts, out)
        rest = [i for i in prompts if out[i] is None]
        if rest:
            try:
                key = gv.key()
            except SystemExit:
                key = None
            for i in rest if key else []:
                out[i] = _leonardo_scene(gv, key, prompts[i], d, stems[i])
    for i, f in enumerate(out):
        if f is None or not f.exists():
            stem = stems[i]
            src = paths.local_path(p["image"]) if p.get("image") else None
            # fallbacks are not cached under the scene key, so the next render with a key retries the generators
            if src and src.exists():
                f = d / (stem + "-fb" + paths.EXT.get(paths.sniff(src) or "", src.suffix or ".jpg"))
                shutil.copy(src, f)
            else:
                f = d / (stem + "-fb.jpg")
                sh([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={brand_color(p['brand'])}:s={W}x{H}:d=1",
                    "-frames:v", "1", "-q:v", "2", str(f)])
            out[i] = f
    return out


def brand_color(bid):
    sj = BRANDS / bid / "scan.json"
    if sj.exists():
        pl = json.loads(sj.read_text()).get("visual", {}).get("palette") or []
        if pl:
            return pl[0]["hex"]
    return "#2447F0"


def scene_is_ai(img):
    """A scene image is generated when it carries an AI mark (XMP / C2PA), or when it is a generated scene from the
    cache (Higgsfield or Leonardo: s-<hash>.<ext>; fallbacks are named s-<hash>-fb.*: the post image, which counts only if
    it is marked itself, or a solid brand-colour card)."""
    img = Path(img)
    return prov.is_generated(img) or (img.name.startswith("s-") and "-fb" not in img.stem)


def voice_tool():
    f = SECRETS / "elevenlabs.json"
    try:
        model = json.loads(f.read_text()).get("model_id") if f.exists() else None
    except ValueError:
        model = None
    return f"ElevenLabs {model or 'eleven_multilingual_v2'}"


def mark_reel(out, imgs, vos):
    """→ the post.media_ai record for the finished reel, or None when nothing in it is synthetic."""
    kinds, tools = [], []
    if any(scene_is_ai(i) for i in imgs):
        kinds.append("image"); tools.extend(scene_tools(imgs))
    if any(vos):
        kinds.append("voice"); tools.append(voice_tool())
    if not kinds:
        return None
    return prov.record(prov.mark_safely(out, kinds, " + ".join(tools), composite=True))


def scene_tools(imgs):
    """The AI systems the reel's generated scenes name in their own marks (e.g. "Higgsfield gpt-image-2"), in order;
    a generated scene whose mark names none (an upstream C2PA file, an old cached scene) counts as Leonardo's."""
    tools = []
    for i in imgs:
        if not scene_is_ai(i):
            continue
        try:
            t = prov.inspect(i).get("tool")
        except Exception:                                    # noqa: BLE001
            t = None
        t = t or genvisuals_tool()
        if t not in tools:
            tools.append(t)
    return tools or [genvisuals_tool()]


def genvisuals_tool():
    try:
        import genvisuals as gv
        return gv.TOOL
    except Exception:                                    # noqa: BLE001
        return "Leonardo.ai"


def voice_over(script, out_dir, voice=True):
    f = SECRETS / "elevenlabs.json"
    if not voice or not f.exists():
        return [None] * len(script)
    c = json.loads(f.read_text())
    model = c.get("model_id", "eleven_multilingual_v2")
    outs = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, sc in enumerate(script, 1):
        mp3 = out_dir / f"v-{scene_key(c.get('voice_id'), model, sc['text'])}.mp3"
        if not mp3.exists():
            req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{c['voice_id']}",
                                         data=json.dumps({"text": sc["text"], "model_id": model}).encode(),
                                         headers={"xi-api-key": c["api_key"], "Content-Type": "application/json", "Accept": "audio/mpeg"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    mp3.write_bytes(r.read())
            except Exception as e:
                print("voice failed:", e); outs.append(None); continue
        outs.append(mp3)
    return outs


# ---------------- assembly ----------------

def render_scene(img, text, secs, out, color, font):
    frames = int(secs * FPS)
    lines = cre.prep_lines(text, 24)
    size = 62 if len(lines) <= 2 else 54
    spacing = 12
    band = size * len(lines) + spacing * max(0, len(lines) - 1) + 130
    fc = cre.text_color_for(color if cre.hex_ok(color) else "#2447F0")
    chain, files = cre.drawtext_chain(lines, font, fc, size, f"h-{band}-120+64", bool(cre.RTL.search(text or "")),
                                      margin=64, spacing=spacing)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
          f"drawbox=x=0:y=ih-{band}-120:w=iw:h={band}:color={color}@0.92:t=fill,"
          + (chain + "," if chain else "") +
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, secs - 0.4)}:d=0.4,format=yuv420p")
    try:
        sh([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-loop", "1", "-i", str(img), "-t", str(secs), "-vf", vf,
            "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(out)])
    finally:
        for f in files:
            os.unlink(f)
    return out


def assemble(scenes, vos, out_mp4, color, workdir):
    font = cre.font_path()
    ff = shutil.which("ffmpeg")
    if not ff or not font:
        raise RuntimeError("ffmpeg or a TTF font is missing")
    clips, total = [], 0.0
    for i, (img, sc, vo) in enumerate(zip([s[0] for s in scenes], [s[1] for s in scenes], vos), 1):
        secs = float(sc.get("seconds", 6))
        if vo:
            secs = max(secs, duration(vo) + 0.6)
        if total + secs > 60:
            secs = max(3.0, 60 - total)
        if secs < 3:
            break
        clip = workdir / f"c{i}.mp4"
        render_scene(img, sc["text"], secs, clip, color, font)
        clips.append((clip, secs, vo)); total += secs
    lst = workdir / "list.txt"
    lst.write_text("".join(f"file '{c[0]}'\n" for c in clips))
    video = workdir / "video.mp4"
    sh([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    # audio: voice segments padded to scene lengths, plus an optional music bed
    inputs, filters, idx = [], [], 1                 # input 0 is the silent video; audio inputs start at 1
    for c, secs, vo in clips:
        if vo:
            inputs += ["-i", str(vo)]; filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={secs:.2f},atrim=0:{secs:.2f}[a{idx}]"); idx += 1
        else:
            inputs += ["-f", "lavfi", "-t", f"{secs:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]; filters.append(f"[{idx}:a]atrim=0:{secs:.2f}[a{idx}]"); idx += 1
    n = idx - 1
    concat = "".join(f"[a{i}]" for i in range(1, idx)) + f"concat=n={n}:v=0:a=1[voice]"
    music = sorted(MUSIC.glob("*.mp3")) if MUSIC.exists() else []
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music[0])]
        fc = ";".join(filters + [concat, f"[{idx}:a]volume=0.12,atrim=0:{total:.2f}[bed]", "[voice][bed]amix=inputs=2:duration=first:dropout_transition=2[mix]"])
        amap = "[mix]"
    else:
        fc = ";".join(filters + [concat]); amap = "[voice]"
    sh([ff, "-y", "-loglevel", "error", "-i", str(video)] + inputs + ["-filter_complex", fc, "-map", "0:v", "-map", amap,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out_mp4)])
    return out_mp4, total


REEL_STATUSES = ("draft", "pending_approval")


def written(p):
    """The reel's words exist: a hook, a caption or a script with text (otto_progress counts the same as "written")."""
    script = p.get("script")
    has_script = isinstance(script, list) and any(isinstance(x, dict) and str(x.get("text") or "").strip() for x in script)
    return bool(str(p.get("hook") or "").strip() or str(p.get("caption") or "").strip() or has_script)


def missing(d, bid=None):
    """Reel posts the 18:30 job renders: no video yet, still draft / pending approval, and written."""
    return [p["id"] for p in d.get("posts", []) if isinstance(p, dict) and p.get("format") == "reel" and not p.get("video")
            and p.get("status") in REEL_STATUSES and (not bid or p.get("brand") == bid) and written(p)]


def _save_script(pid, script):
    with ap.transaction() as d:
        q = ap.post(d, pid)
        if q is not None and not q.get("script"):
            q["script"] = script


def render(pid, dry=False, voice=True):
    d = ap.load()                                   # snapshot: all slow work happens outside the lock
    p = ap.post(d, pid)
    assert p, f"unknown post {pid}"
    b = ap.brand(d, p["brand"]) or {}
    if not written(p):
        print(f"{pid}: not written yet (no hook, caption or script) — no reel is rendered until the copywriter has written it")
        return None
    script = p.get("script") or plan_script(p, b)
    if dry:
        for i, sc in enumerate(script, 1):
            print(f"scene {i} · {sc.get('seconds', 6)}s · {sc['text']}")
        print(f"-- {len(script)} scenes ≈ {sum(int(s.get('seconds', 6)) for s in script)}s (dry: no images, no render)")
        _save_script(pid, script); return
    imgs = scene_images(p, script, dry=False)
    work = REELS / p["id"]
    vos = voice_over(script, work, voice)
    REELS.mkdir(parents=True, exist_ok=True)
    out = REELS / paths.token_name(p["id"], ".mp4", paths.media_token("post", p["id"]))   # unguessable public name
    _, total = assemble(list(zip(imgs, script)), vos, out, brand_color(p["brand"]), work)
    ai = mark_reel(out, imgs, vos)                  # marked before it is public: the public copy carries the mark
    paths.publish(out)                              # public before anything points at it
    if prov.sidecar_path(out).exists():
        paths.publish(prov.sidecar_path(out))
    ref = paths.rel_of(out)
    with ap.transaction() as d2:
        q = ap.post(d2, pid)
        if q is None:
            print(f"{pid} disappeared while rendering — video kept at {out}"); return
        q["script"] = q.get("script") or script
        q["video"] = ref; q["video_seconds"] = round(total, 1); q["format"] = q.get("format") or "reel"
        media_ai = dict(q.get("media_ai") if isinstance(q.get("media_ai"), dict) else {})
        media_ai.pop(ref, None)
        if ai:
            media_ai[ref] = ai
        if media_ai or "media_ai" in q:
            q["media_ai"] = media_ai
    print(f"rendered {out} · {total:.0f}s · {len(imgs)} scenes · voice {'yes' if any(vos) else 'no'}"
          f"{' · AI-marked (' + ','.join(ai['kinds']) + ')' if ai and ai.get('marked') else ' · NOT marked: ' + ai['error'] if ai else ''}")


def demo(out, voice=False):
    imgs = sorted(p for p in (paths.ASSETS / "posts").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:5]
    assert imgs, "no post images to demo with"
    script = [{"text": "Full spectrum, broad spectrum, isolate. Same plant, three products.", "seconds": 6},
              {"text": "Full: every compound working together.", "seconds": 5},
              {"text": "Broad: the same team, minus THC.", "seconds": 5},
              {"text": "Isolate: pure CBD, nothing else.", "seconds": 5},
              {"text": "Every batch third-party lab tested. Link in bio.", "seconds": 6}]
    work = Path(tempfile.mkdtemp(prefix="otto-reel-"))
    vos = voice_over(script, work, voice)
    _, total = assemble(list(zip([imgs[i % len(imgs)] for i in range(len(script))], script)), vos, Path(out), "#FFBC00", work)
    print(f"demo rendered {out} · {total:.0f}s")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "plan":
        secs = int(a[a.index("--seconds") + 1]) if "--seconds" in a else 45
        with ap.transaction() as d:
            p = ap.post(d, a[1]); assert p, f"unknown post {a[1]}"
            b = ap.brand(d, p["brand"]) or {}
            p["script"] = plan_script(p, b, secs)
        for i, sc in enumerate(p["script"], 1):
            print(f"scene {i} · {sc['seconds']}s · {sc['text']}")
    elif cmd == "render":
        render(a[1], dry="--dry" in a, voice="--no-voice" not in a)
    elif cmd == "demo":
        demo(a[1], voice="--voice" in a)
    elif cmd == "missing":
        bid = a[a.index("--brand") + 1] if "--brand" in a else None
        for pid in missing(ap.load(), bid):
            print(pid)
    else:
        print(__doc__)
