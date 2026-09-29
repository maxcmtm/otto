#!/usr/bin/env python3
"""Otto motion reels — the HyperFrames pipeline around skills/otto-motion-director.

  otto_motion.py prepare <post-id> [--length 45] [--preset <name>]   # project + BRIEF + capture + frame.md + templates
  otto_motion.py voice   <post-id> <dir-with-NN.mp3>                 # wav, tighten pauses, words, audio_meta, start music
  otto_motion.py words   <post-id>                                   # print word cues per frame (to time the Scene lines)
  otto_motion.py finish  <post-id> [--no-render]                     # captions → assemble → transitions → lint/check/snapshot → render → attach

The creative work in between (SCRIPT.md, STORYBOARD.md, dispatching one frame worker per frame) is done
by the agent following skills/otto-motion-director/SKILL.md. Reference build: motion/happygarden-spectrum-guide/.
Requires: node + npx (HyperFrames CLI), ffmpeg/ffprobe, python faster-whisper (word timings).
Env: OTTO_MOTION_ROOT (default <repo>/motion), HF_SKILLS (default ~/.claude/skills), npm_config_cache (optional).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ap
import otto_paths as paths

HERE = Path(__file__).parent
REPO = HERE.parent
BRANDS = ap.BRANDS                                   # OTTO_BRANDS
MOTION = Path(os.environ.get("OTTO_MOTION_ROOT") or REPO / "motion")
SKILLS = Path(os.environ.get("HF_SKILLS") or Path.home() / ".claude" / "skills")
FE = SKILLS / "faceless-explainer" / "scripts"
MEDIA = SKILLS / "media-use" / "audio" / "scripts" / "audio.mjs"
REELS = paths.ASSETS / "reels"                       # OTTO_ASSETS — the publisher resolves post.video there

PRESET_BY_INDUSTRY = [("cbd", "editorial-forest"), ("wellness", "editorial-forest"), ("restaurant", "bold-poster"),
                      ("food", "bold-poster"), ("clinic", "cartesian"), ("medical", "cartesian"), ("legal", "cartesian"),
                      ("real estate", "cartesian"), ("education", "biennale-yellow"), ("coaching", "biennale-yellow"),
                      ("saas", "blue-professional"), ("software", "blue-professional"), ("finance", "blue-professional"),
                      ("marketing", "blue-professional"), ("beauty", "capsule"), ("fitness", "broadside"),
                      ("hotel", "code-editorial"), ("e-commerce", "editorial-forest")]
ARC_BY_PILLAR = [("educat", "concept"), ("myth", "concept"), ("how", "how-to"), ("proof", "story"), ("stor", "story"),
                 ("alumni", "story"), ("review", "story"), ("product", "listicle"), ("compar", "listicle"), ("use", "concept")]
VOICES = {"female": "d081b915-6623-4a44-bacf-80d0f1c90a03", "male": "1ad38ba4-9cc4-4f2f-9fde-b0fefdf67ae5"}


def sh(cmd, cwd=None, check=True, both=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))}… failed:\n{(r.stderr or r.stdout)[-800:]}")
    return r.stdout + (r.stderr or "") if both else r.stdout


def project_dir(d, p):
    return MOTION / f"{p['brand']}-{p['id']}"


def scan_of(bid):
    f = BRANDS / bid / "scan.json"
    return json.loads(f.read_text()) if f.exists() else {}


def profile_text(bid):
    f = BRANDS / bid / "brand-profile.md"
    return f.read_text() if f.exists() else ""


def section(md, *names):
    out = []
    for n in names:
        m = re.search(r"^##[^\n]*" + re.escape(n) + r"[^\n]*\n(.*?)(?=^## |\Z)", md, re.S | re.M | re.I)
        if m:
            out.append(m.group(0).strip())
    return "\n\n".join(out)


def brand_colors(bid):
    md = profile_text(bid)
    vis = section(md, "VISUAL IDENTITY")
    hexes = list(dict.fromkeys(re.findall(r"#[0-9A-Fa-f]{6}", vis)))
    if not hexes:
        hexes = [c["hex"] for c in scan_of(bid).get("visual", {}).get("palette", [])]
    return [h.upper() for h in hexes[:5]]


def pick(table, text, default):
    t = (text or "").lower()
    return next((v for k, v in table if k in t), default)


# ---------------- prepare ----------------

def prepare(pid, length=45, preset=None):
    d = ap.load()
    p = ap.post(d, pid)
    assert p, f"unknown post {pid}"
    b = ap.brand(d, p["brand"]) or {"id": p["brand"], "name": p["brand"]}
    s = scan_of(b["id"])
    industry = s.get("industry") or ""
    preset = preset or pick(PRESET_BY_INDUSTRY, industry + " " + " ".join(b.get("pillars", [])), "editorial-forest")
    angle = pick(ARC_BY_PILLAR, p.get("pillar", ""), "concept")
    lang = ap.brand_lang(b)                          # "PT/EN" → pt, "IT" → it (was: he/de, else English)
    pdir = project_dir(d, p)
    if not (pdir / "hyperframes.json").exists():
        pdir.parent.mkdir(parents=True, exist_ok=True)
        sh(["npx", "-y", "hyperframes@latest", "init", str(pdir), "--non-interactive", "--example=blank", "--skill=faceless-explainer"])
    hook = p.get("hook_en") or p.get("hook") or ""
    (pdir / "BRIEF.md").write_text(f"""---
workflow: faceless-explainer
flow: automation
storyboard: no
message: "{hook.replace('"', "'")}"
destination: instagram-reels
aspect: 1080x1920
language: {lang}
audience: "{b.get('name')} customers — see brand-profile avatars"
length: {length}s
angle: {angle}
---

## Intent

Otto reel for {b.get('name')} ({b.get('url', '')}), post {p['id']} · pillar {p.get('pillar', '')}. A {length}-second,
motion-design-led vertical explainer that looks studio-made for this business. Follow
skills/otto-motion-director/SKILL.md and match the reference build motion/happygarden-spectrum-guide/.

## Notes

- Compliance: {b.get('compliance', 'see brand-profile.md')}
- Every claim must trace to brand-profile.md / strategy.json / scan.json. Never invent numbers or proof.
""")
    cap = pdir / "capture" / "extracted"
    cap.mkdir(parents=True, exist_ok=True)
    md = profile_text(b["id"])
    visible = [f"Brand: {b.get('name')} — {b.get('url', '')}. Industry: {industry}.",
               f"Post hook: {hook}", f"Post caption: {p.get('caption_en') or p.get('caption') or ''}",
               f"Brief: {p.get('brief', '')}", section(md, "Business snapshot", "Identity"),
               section(md, "Avatars", "Pain", "Objections", "Customer language", "Proof", "Compliance", "Winning angles")]
    (cap / "visible-text.txt").write_text("\n\n".join(x for x in visible if x)[:12000])
    (cap / "tokens.json").write_text(json.dumps({"title": hook, "description": p.get("brief", ""),
                                                 "colors": brand_colors(b["id"]), "fonts": []}, ensure_ascii=False))
    if not (pdir / "frame.md").exists():
        sh(["node", str(FE / "build-frame.mjs"), "--preset", preset, "--hyperframes", "."], cwd=pdir)
    if not (pdir / "STORYBOARD.md").exists():
        (pdir / "STORYBOARD.md").write_text(f"""---
format: 1080x1920
duration: {length}s
message: "{hook.replace('"', "'")}"
arc: {angle}
audience: see BRIEF.md
mode: autonomous
music: <mood from the brand, e.g. soft organic acoustic, 88 bpm, no vocals>
brand: {b.get('name')}
---

## Video direction

<palette roles from frame.md · the ONE visual system with exact geometry · motion grammar · held beats · chrome · caption band · negative list>

## Frame 1 — <title>

- type: hook
- duration: <synced from the voice>
- transition_in: cut
- persuasion: <named technique>
- beat: <feeling>
- scene: <one line>
- voiceover: "<line 1 of SCRIPT.md>"
- status: outline
- src: compositions/frames/01-hook.html
- blueprint: <id> (Adapt)
- focal: <hero element>
- roles: <element = role · …>
- sfx: none

Scene 1 (0.00–…s): <what enters on which word cue, where, which move (rule id)>

narrativeRole: <job of the frame>
keyMessage: <one sentence>
""")
    if not (pdir / "SCRIPT.md").exists():
        (pdir / "SCRIPT.md").write_text(f"# SCRIPT — {pdir.name}\n\n**Voice:** ElevenLabs via Higgsfield — Nora ({VOICES['female']}) or Gideon ({VOICES['male']})\n**Voice direction:** <from the brand's tone>\n\n---\n\n## Line 1 — Hook (Frame 1)\n\n**Delivery:** <note>\n\n    <spoken line>\n")
    with_tx(lambda dd: ap.post(dd, pid).__setitem__("motion", {"project": str(pdir), "status": "prepared", "preset": preset}))
    print(f"prepared {pdir}\n  preset {preset} · angle {angle} · colours {brand_colors(b['id'])}\n  next: write SCRIPT.md + STORYBOARD.md per skills/otto-motion-director")
    return pdir


def with_tx(fn):
    """Apply fn(d) inside ap.transaction() when available (atomic), else load/save."""
    tx = getattr(ap, "transaction", None)
    if tx:
        with tx() as d:
            fn(d)
    else:
        d = ap.load(); fn(d); ap.save(d)


# ---------------- voice ----------------

def _dur(f):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).strip())


def tighten(src, dst, words, cap=0.30, head=0.05, tail=0.16, sil=0.12, pad_end=0.25):
    segs, cur = [], [words[0]]
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > cap:
            segs.append(cur)
            cur = [b]
        else:
            cur.append(b)
    segs.append(cur)
    total = _dur(src)
    parts, t_new, remap = [], 0.0, []
    for i, s in enumerate(segs):
        s0, s1 = max(0.0, s[0]["start"] - head), min(total, s[-1]["end"] + tail)
        parts.append((s0, s1))
        remap += [{"text": w["text"], "start": round(w["start"] - s0 + t_new, 3), "end": round(w["end"] - s0 + t_new, 3)} for w in s]
        t_new += (s1 - s0) + (sil if i < len(segs) - 1 else 0)
    fc, labels = [], []
    for i, (a, b) in enumerate(parts):
        fc.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[s{i}]"); labels.append(f"[s{i}]")
        if i < len(parts) - 1:
            fc.append(f"anullsrc=r=44100:cl=mono,atrim=0:{sil}[z{i}]"); labels.append(f"[z{i}]")
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1,apad=pad_dur={pad_end}[out]")
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", ";".join(fc), "-map", "[out]", "-ar", "44100", "-ac", "1", str(dst)])
    return remap


def whisper_model(lang):
    """small.en only understands English; any other voice-over needs the multilingual model."""
    return os.environ.get("WHISPER_MODEL") or ("small.en" if lang == "en" else "small")


def transcribe(files, lang="en"):
    from faster_whisper import WhisperModel
    m = WhisperModel(whisper_model(lang), device="cpu", compute_type="int8")
    out = {}
    for f in files:
        segs, info = m.transcribe(str(f), word_timestamps=True, vad_filter=False, language=lang)
        out[f.name] = join_fragments([{"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                                      for s in segs for w in s.words])
    return out


def join_fragments(words):
    """Whisper splits "third-party" into "third" + "-party" and "it's" into "it" + "'s"; captions must show one word.
    Tokens that start with a hyphen/apostrophe or are pure punctuation are glued onto the previous word."""
    out = []
    for w in words:
        t = w["text"]
        if out and t and (t[0] in "-'’" or not any(ch.isalnum() for ch in t)):
            out[-1] = {**out[-1], "text": out[-1]["text"] + t, "end": w["end"]}
        else:
            out.append(dict(w))
    return out


def voice(pid, mp3_dir):
    d = ap.load(); p = ap.post(d, pid); pdir = project_dir(d, p)
    adir = pdir / "assets" / "audio"; adir.mkdir(parents=True, exist_ok=True)
    mp3s = sorted(Path(mp3_dir).glob("*.mp3"))
    assert mp3s, f"no .mp3 files in {mp3_dir} (name them 01.mp3, 02.mp3 … one per frame)"
    raw = []
    for i, f in enumerate(mp3s, 1):
        w = adir / f"vo-{i:02d}.wav"
        sh(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-ar", "44100", "-ac", "1", str(w)]); raw.append(w)
    words = transcribe(raw, ap.brand_lang(ap.brand(d, p["brand"]) or {"id": p["brand"]}))
    voices = []
    for i, w in enumerate(raw, 1):
        final = adir / f"vo-{i:02d}-final.wav"
        remap = tighten(w, final, words[w.name], pad_end=1.6 if i == len(raw) else 0.25)
        voices.append({"id": f"{i:02d}", "path": f"assets/audio/{final.name}", "duration_s": round(_dur(final), 3),
                       "words": [{"id": f"w{i:02d}_{j:02d}", **x} for j, x in enumerate(remap)]})
    total = round(sum(v["duration_s"] for v in voices), 3)
    (pdir / "audio_engine_meta.json").write_text(json.dumps({"bgm": None, "bgm_pending": False, "voices": voices, "sfx": [], "total_duration_s": total}, indent=1))
    (pdir / "audio_meta.json").write_text(json.dumps({"bgm": None, "bgm_pending": False, "sfx": [],
        "voices": [{"frame": int(v["id"]), "path": v["path"], "duration_s": v["duration_s"], "words": v["words"]} for v in voices]}, indent=1))
    sb = (pdir / "STORYBOARD.md").read_text()
    mood = (re.search(r"^music:\s*(.+)$", sb, re.M) or [None, "calm minimal underscore, no vocals"])[1]
    (pdir / "audio_request.json").write_text(json.dumps({"provider": "auto", "lines": [], "bgm": {"mode": "generate", "prompt": mood, "query": mood, "blob": mood}}))
    sh(["node", str(MEDIA), "--request", "./audio_request.json", "--hyperframes", ".", "--out", "./audio_engine_meta.json", "--only", "bgm", "--bgm-mode", "generate"], cwd=pdir, check=False)
    sh(["node", str(FE / "audio.mjs"), "sync-durations", "--audio-meta", "./audio_meta.json", "--storyboard", "./STORYBOARD.md"], cwd=pdir, check=False)
    print(f"voice: {len(voices)} lines · {total}s total · music generating")
    words_cmd(pid)


def words_cmd(pid):
    d = ap.load(); p = ap.post(d, pid); pdir = project_dir(d, p)
    meta = json.loads((pdir / "audio_meta.json").read_text())
    for v in meta["voices"]:
        print(f"F{v['frame']} {v['duration_s']:.2f}s: " + " ".join(f"{w['text']}@{w['start']:.2f}" for w in v["words"]))


# ---------------- finish ----------------

def bgm_ready(pdir):
    """Fold a finished detached MusicGen track into both audio metas; False while it is still rendering."""
    meta = json.loads((pdir / "audio_engine_meta.json").read_text())
    if not meta.get("bgm_pending"):
        return True
    track = pdir / ((meta.get("bgm") or {}).get("path") or "assets/bgm/track.wav")
    logs = sorted((pdir / "assets" / "bgm").glob("bgm-*.log"))
    done = logs and "wrote" in logs[-1].read_text()
    if not (track.exists() and done):
        return False
    bgm = {"path": str(track.relative_to(pdir)), "volume": (meta.get("bgm") or {}).get("volume", 0.12),
           "query": (meta.get("bgm") or {}).get("query"), "duration_s": round(_dur(track), 2)}
    for f in ("audio_engine_meta.json", "audio_meta.json"):
        m = json.loads((pdir / f).read_text()); m["bgm"] = bgm; m["bgm_pending"] = False
        (pdir / f).write_text(json.dumps(m, indent=1))
    return True


CROSSFADE_OUT = re.compile(r'tl\.to\("(#el-[\w-]+)", \{ opacity: 0, duration: ([\d.]+), ease: "[^"]+" \}, ([\d.]+)\);\n(\s*)tl\.fromTo\("(#el-[\w-]+)", \{ opacity: 0 \}, \{ opacity: 1')


def solid_crossfades(index_path):
    """transitions.mjs fades the outgoing frame out while the incoming fades in; at the midpoint both are
    semi-transparent and the root background washes through (a grey/cream flash between two dark frames).
    Keep the outgoing frame opaque underneath and dissolve only the incoming frame (later in the DOM = on top)."""
    path = Path(index_path); html = path.read_text()
    fixed, n = CROSSFADE_OUT.subn(lambda m: f'tl.set("{m.group(1)}", {{ opacity: 1 }}, {m.group(3)});\n{m.group(4)}'
                                            f'tl.fromTo("{m.group(5)}", {{ opacity: 0 }}, {{ opacity: 1', html)
    if n:
        path.write_text(fixed)
    return n


def finish(pid, render=True):
    d = ap.load(); p = ap.post(d, pid); pdir = project_dir(d, p)
    frames = sorted((pdir / "compositions" / "frames").glob("*.html"))
    assert frames, "no compositions/frames/*.html — dispatch the frame workers first"
    if not bgm_ready(pdir):
        print("music still generating — finishing without it would ship a silent bed; retry in a minute"); return
    steps = [["node", str(FE / "captions.mjs"), "build", "--storyboard", "./STORYBOARD.md", "--audio-meta", "./audio_meta.json", "--hyperframes", ".", "--out", "./caption_groups.json"],
             ["node", str(FE / "assemble-index.mjs"), "--storyboard", "./STORYBOARD.md", "--hyperframes", "."],
             ["node", str(FE / "transitions.mjs"), "inject", "--storyboard", "./STORYBOARD.md", "--hyperframes", "."],
             ["node", str(FE / "transitions.mjs"), "verify", "--storyboard", "./STORYBOARD.md", "--index", "./index.html"],
             ["npx", "hyperframes", "lint"], ["npx", "hyperframes", "check"]]
    for c in steps:
        print("·", " ".join(c[:3])); out = sh(c, cwd=pdir, both=True); print(out[-600:])
        if "inject" in c:
            n = solid_crossfades(pdir / "index.html")
            if n:
                print(f"  crossfades kept solid underneath: {n}")
        if c[-1] == "check" and "Check failed" in out:
            raise SystemExit("hyperframes check failed — fix the findings above before rendering (nothing was rendered)")
    if not render:
        return
    sh(["npx", "hyperframes", "render", "--skill=faceless-explainer", "--quality", "high", "--output", "renders/video.mp4"], cwd=pdir)
    REELS.mkdir(parents=True, exist_ok=True)
    out = REELS / f"{pid}.mp4"
    shutil.copy(pdir / "renders" / "video.mp4", out)
    paths.publish(out)                               # public before post.video points at it (ap has no publish_asset)
    secs = round(_dur(out), 1)

    def attach(dd):
        pp = ap.post(dd, pid)
        pp["video"] = f"assets/reels/{pid}.mp4"; pp["video_seconds"] = secs; pp["format"] = "reel"
        pp.setdefault("motion", {})["status"] = "rendered"
        if pp.get("status") == "draft":
            pp["status"] = "pending_approval"
    with_tx(attach)
    print(f"rendered {out} · {secs}s → post {pid} is waiting for approval")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "prepare":
        prepare(a[1], int(a[a.index("--length") + 1]) if "--length" in a else 45, a[a.index("--preset") + 1] if "--preset" in a else None)
    elif cmd == "voice":
        voice(a[1], a[2])
    elif cmd == "words":
        words_cmd(a[1])
    elif cmd == "finish":
        finish(a[1], render="--no-render" not in a)
    else:
        print(__doc__)
