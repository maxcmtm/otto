#!/usr/bin/env python3
"""Otto reels — 30–60 s explainer videos for every brand, in the base package.

  otto_video.py plan   <post-id> [--seconds 45]         # scene script from the post (Quill may write post.script first)
  otto_video.py render <post-id> [--dry] [--no-voice]    # scenes → images → voice-over → ffmpeg → assets/reels/<id>.mp4 → post.video
  otto_video.py demo   <out.mp4> [--voice]               # render a sample reel from existing post images (local check)

A reel = 4–7 scenes. Each scene: one on-brand vertical image (Leonardo, brand palette), a slow
Ken Burns move, a caption in the brand band (ffmpeg drawtext, same typography as the ad statics),
optional voice-over (ElevenLabs, $OTTO_SECRETS/elevenlabs.json {api_key, voice_id}) and a music bed
from assets/music/*.mp3 (royalty-free, optional). 1080×1920, 30 fps, H.264 + AAC, capped at 60 s.
post.script = [{"text","seconds","visual"}] — if missing, `plan` derives it from hook + caption.
Needs ffmpeg + ffprobe on PATH and a TTF font (OTTO_FONT or the defaults in otto_creative.py).
"""
import json, os, re, shutil, subprocess, sys, tempfile, textwrap, urllib.request
from pathlib import Path

import ap
import otto_creative as cre

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
REELS = HERE / "assets" / "reels"
MUSIC = HERE / "assets" / "music"
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

def plan_script(p, b, seconds=45):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", (p.get("caption") or "")) if 12 <= len(s.strip()) <= 140]
    sents = [s for s in sents if not s.startswith("#")]
    hook = p.get("hook") or (sents[0] if sents else b.get("name", ""))
    body = [s for s in sents if s != hook][:4]
    lines = [hook] + body + [f"{b.get('name', '')}. Link in bio."]
    per = max(5, min(9, seconds // len(lines)))
    return [{"text": t, "seconds": per, "visual": f"{p.get('pillar', '')} — {t}"} for t in lines][:7]


# ---------------- assets ----------------

def scene_images(p, script, dry):
    """One 9:16 image per scene via Leonardo (skips existing). Dry/no key → reuse the post image."""
    d = REELS / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    out = []
    try:
        import genvisuals as gv
        key = None if dry else gv.key()
    except SystemExit:
        key = None
    for i, sc in enumerate(script, 1):
        f = d / f"s{i}.png"
        if f.exists():
            out.append(f); continue
        if key:
            pal, industry, style = gv.brand_visual(p["brand"])
            prompt = (f"vertical 9:16 social video frame, {industry or 'brand'}. Brand palette (dominant): {', '.join(pal) or 'brand colors'}. "
                      f"Visual style: {style}. Scene: {sc.get('visual') or sc['text']} (concept only, never render words). "
                      f"Cinematic, premium, no text, no logos, no watermark, clear space in the lower third for a caption.")
            try:
                gid = gv.post_json(f"{gv.BASE}/v2/generations", {"model": "gpt-image-2", "parameters": {"width": 768, "height": 1376, "prompt": prompt,
                                   "quality": "HIGH", "quantity": 1, "prompt_enhance": "OFF"}, "public": False}, key)["generate"]["generationId"]
                import time
                for _ in range(40):
                    time.sleep(12)
                    req = urllib.request.Request(f"{gv.BASE}/v1/generations/{gid}", headers={"authorization": f"Bearer {key}"})
                    with urllib.request.urlopen(req, timeout=30) as x:
                        g = json.loads(x.read()).get("generations_by_pk") or {}
                    if g.get("status") == "COMPLETE" and g.get("generated_images"):
                        q = urllib.request.Request(g["generated_images"][0]["url"], headers={"User-Agent": gv.UA})
                        with urllib.request.urlopen(q, timeout=60) as x:
                            f.write_bytes(x.read())
                        break
                    if g.get("status") == "FAILED":
                        break
            except Exception as e:
                print("scene image failed:", e)
        if not f.exists():
            src = HERE / p["image"] if p.get("image") else None
            if src and src.exists():
                shutil.copy(src, f)
            else:
                cre_font = cre.font_path()
                sh([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={brand_color(p['brand'])}:s={W}x{H}:d=1", "-frames:v", "1", str(f)])
        out.append(f)
    return out


def brand_color(bid):
    sj = BRANDS / bid / "scan.json"
    if sj.exists():
        pl = json.loads(sj.read_text()).get("visual", {}).get("palette") or []
        if pl:
            return pl[0]["hex"]
    return "#2447F0"


def voice_over(script, out_dir, voice=True):
    f = SECRETS / "elevenlabs.json"
    if not voice or not f.exists():
        return [None] * len(script)
    c = json.loads(f.read_text())
    outs = []
    for i, sc in enumerate(script, 1):
        mp3 = out_dir / f"v{i}.mp3"
        if not mp3.exists():
            req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{c['voice_id']}",
                                         data=json.dumps({"text": sc["text"], "model_id": c.get("model_id", "eleven_multilingual_v2")}).encode(),
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
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(lines)); tfile = tf.name
    size = 62 if len(lines) <= 2 else 54
    band = size * len(lines) + 130
    fc = cre.text_color_for(color if cre.hex_ok(color) else "#2447F0")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
          f"drawbox=x=0:y=ih-{band}-120:w=iw:h={band}:color={color}@0.92:t=fill,"
          f"drawtext=fontfile='{font}':textfile='{tfile}':fontcolor={fc}:fontsize={size}:line_spacing=12:x=64:y=h-{band}-120+64,"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, secs - 0.4)}:d=0.4,format=yuv420p")
    sh([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-loop", "1", "-i", str(img), "-t", str(secs), "-vf", vf,
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(out)])
    os.unlink(tfile)
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


def render(pid, dry=False, voice=True):
    d = ap.load()
    p = ap.post(d, pid)
    assert p, f"unknown post {pid}"
    b = ap.brand(d, p["brand"]) or {}
    script = p.get("script") or plan_script(p, b)
    p["script"] = script
    if dry:
        for i, sc in enumerate(script, 1):
            print(f"scene {i} · {sc.get('seconds', 6)}s · {sc['text']}")
        print(f"-- {len(script)} scenes ≈ {sum(int(s.get('seconds', 6)) for s in script)}s (dry: no images, no render)")
        ap.save(d); return
    imgs = scene_images(p, script, dry=False)
    work = REELS / p["id"]
    vos = voice_over(script, work, voice)
    REELS.mkdir(parents=True, exist_ok=True)
    out = REELS / f"{p['id']}.mp4"
    _, total = assemble(list(zip(imgs, script)), vos, out, brand_color(p["brand"]), work)
    p["video"] = f"assets/reels/{p['id']}.mp4"; p["video_seconds"] = round(total, 1); p["format"] = p.get("format") or "reel"
    ap.save(d)
    print(f"rendered {out} · {total:.0f}s · {len(imgs)} scenes · voice {'yes' if any(vos) else 'no'}")


def demo(out, voice=False):
    imgs = sorted((HERE / "assets" / "posts").glob("*.png"))[:5]
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
        d = ap.load(); p = ap.post(d, a[1]); b = ap.brand(d, p["brand"]) or {}
        secs = int(a[a.index("--seconds") + 1]) if "--seconds" in a else 45
        p["script"] = plan_script(p, b, secs); ap.save(d)
        for i, sc in enumerate(p["script"], 1):
            print(f"scene {i} · {sc['seconds']}s · {sc['text']}")
    elif cmd == "render":
        render(a[1], dry="--dry" in a, voice="--no-voice" not in a)
    elif cmd == "demo":
        demo(a[1], voice="--voice" in a)
    else:
        print(__doc__)
