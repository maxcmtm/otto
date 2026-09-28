#!/usr/bin/env python3
"""Generate post visuals via Leonardo (GPT Image 2) into assets/posts/<post-id>.png.
Fire + poll in one run. Hebrew text is never rendered in-image (models mangle it) —
the caption carries the copy; visuals stay text-free or English-minimal.
"""
import json, time, os, urllib.request
def _load_key():
    k = os.environ.get("LEONARDO_API_KEY")
    if k:
        return k.strip()
    p = os.path.join(os.path.dirname(__file__), ".leonardo_key")
    with open(p) as f:
        return f.read().strip()

KEY = _load_key()
BASE = "https://cloud.leonardo.ai/api/rest"
OUT = os.path.join(os.path.dirname(__file__), "assets", "posts")
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

POSTS = [
 ("hg-001",
  "Premium wellness editorial flat-lay photograph, square format. Three elegant amber glass dropper bottles side by side on warm off-white linen, subtly labeled in small clean sans-serif: 'FULL SPECTRUM', 'BROAD SPECTRUM', 'ISOLATE'. Fresh green hemp leaves and soft botanical shadows, morning window light, calm natural palette of sage green, amber and cream. Sophisticated Instagram wellness-brand aesthetic, photorealistic, no watermark."),
 ("cm-001",
  "Conceptual therapeutic illustration-photograph hybrid, square format, no text. A luminous young tree seen in cross-section: warm golden light in the branches above ground, and deep intricate glowing roots below the soil line, symbolizing healing from the root rather than the surface. Warm earthy palette — terracotta, deep teal, soft gold. Calm, hopeful, premium editorial feel for a therapy school. Photorealistic render, no watermark, no text."),
 ("cm-002",
  "Authentic documentary photograph, square format, no text. An Israeli woman around 43 with warm confident smile standing in her own small bright therapy clinic she just opened: soft armchair, plants, morning light through the window, notebook in hand. Candid, unposed, shallow depth of field, warm natural tones. Real human story feel, photorealistic, no watermark, no text."),
 ("cm-007",
  "Bold minimal conceptual photograph, square format, no text. Split composition: left side a stiff dark formal framed diploma on a cold grey academic wall; right side a warm inviting therapy room corner with two comfortable chairs facing each other, soft golden light, a plant. The warm side clearly wins the frame. Editorial myth-vs-reality visual metaphor, premium, photorealistic, no watermark, no text."),
]

def post(u, b):
    r = urllib.request.Request(u, data=json.dumps(b).encode(),
        headers={"authorization": f"Bearer {KEY}", "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=45) as x:
        return json.loads(x.read())

jobs = []
for name, prompt in POSTS:
    if os.path.exists(f"{OUT}/{name}.png"):
        print("SKIP (exists)", name); continue
    body = {"model": "gpt-image-2", "parameters": {"width": 1024, "height": 1024, "prompt": prompt,
            "quality": "HIGH", "quantity": 1, "prompt_enhance": "OFF"}, "public": False}
    try:
        r = post(f"{BASE}/v2/generations", body)
        gid = r["generate"]["generationId"]; jobs.append((name, gid)); print("FIRED", name, gid)
    except Exception as e:
        print("ERR", name, e)
    time.sleep(1)

done = {}
deadline = time.time() + 480
while len(done) < len(jobs) and time.time() < deadline:
    for name, gid in jobs:
        if name in done: continue
        r = urllib.request.Request(f"{BASE}/v1/generations/{gid}", headers={"authorization": f"Bearer {KEY}"})
        try:
            with urllib.request.urlopen(r, timeout=30) as x:
                d = json.loads(x.read())
        except Exception as e:
            print("poll err", name, e); continue
        g = d.get("generations_by_pk") or {}
        if g.get("status") == "COMPLETE":
            imgs = g.get("generated_images") or []
            if imgs:
                q = urllib.request.Request(imgs[0]["url"], headers={"User-Agent": UA})
                with urllib.request.urlopen(q, timeout=60) as x:
                    data = x.read()
                p = f"{OUT}/{name}.png"
                open(p, "wb").write(data); done[name] = p; print("SAVED", name, len(data))
            else:
                done[name] = None; print("EMPTY", name)
        elif g.get("status") == "FAILED":
            done[name] = None; print("FAILED", name)
    if len(done) < len(jobs): time.sleep(12)
print("DONE", json.dumps(done))
