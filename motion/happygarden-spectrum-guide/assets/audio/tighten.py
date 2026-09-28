"""Cap dead air between phrases: split each line at gaps > CAP, keep speech, re-join with GAP_KEEP of silence.
Writes vo-NN-tight.wav + words-tight.json (word times remapped)."""
import json, subprocess, os
HERE = os.path.dirname(__file__)
CAP, HEAD, TAIL, SIL = 0.30, 0.05, 0.16, 0.12
W = json.load(open(os.path.join(HERE, "words.json")))
out = {}
for name, d in W.items():
    words = d["words"]
    segs = []
    cur = [words[0]]
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > CAP:
            segs.append(cur); cur = [b]
        else:
            cur.append(b)
    segs.append(cur)
    parts, t_new, remap = [], 0.0, []
    for i, s in enumerate(segs):
        s0 = max(0.0, s[0]["start"] - HEAD)
        s1 = min(d["duration"], s[-1]["end"] + TAIL)
        parts.append((s0, s1))
        for w in s:
            remap.append({"text": w["text"], "start": round(w["start"] - s0 + t_new, 3), "end": round(w["end"] - s0 + t_new, 3)})
        t_new += (s1 - s0) + (SIL if i < len(segs) - 1 else 0)
    src = os.path.join(HERE, name)
    dst = os.path.join(HERE, name.replace(".wav", "-tight.wav"))
    fc, labels = [], []
    for i, (a, b) in enumerate(parts):
        fc.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[s{i}]"); labels.append(f"[s{i}]")
        if i < len(parts) - 1:
            fc.append(f"anullsrc=r=44100:cl=mono,atrim=0:{SIL}[z{i}]"); labels.append(f"[z{i}]")
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", ";".join(fc), "-map", "[out]", "-ar", "44100", "-ac", "1", dst], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", dst], capture_output=True, text=True).stdout)
    out[name.replace(".wav", "-tight.wav")] = {"duration": round(dur, 3), "words": remap}
    print(f"{name}: {d['duration']:.2f}s -> {dur:.2f}s ({len(parts)} phrases)")
json.dump(out, open(os.path.join(HERE, "words-tight.json"), "w"), indent=1)
print("total", round(sum(v["duration"] for v in out.values()), 2))
