#!/usr/bin/env python3
"""Video ads (otto_advideo): the scripted faceless video cells of a brand's monthly ad matrix → mp4s in the brand's look.
A fake renderer stands in for the HyperFrames call (no network, no Chrome): the cell's kit JSON and the brand.json it gets
(copy verbatim, the brand's colours / font / pictures — never Otto's), scripted → rendered (file, poster, render.hash /
files / status), the plan's cap in concept order (a failed cell holds no slot), caching by the beats (new copy → stale →
rendered again under a new name, the old files dropped unless a campaign points at them), the beats changing mid-render,
failures (the cell stays scripted, retried after 6 h, one owner card after two failed runs, resolved once it renders),
size / length checks, unguessable public names, AI provenance only when a placed picture is AI-made, right-to-left brands,
the launch reading it (otto_creative.build_matrix: the 9:16 story + the 4:5 feed video; otto_ads: one video creative with
placement rules, the 9:16 alone when Meta refuses them), Meta's 9:16 safe-zone patches against the real kit templates,
ground contrast, the per-step time limit, the queue (spawn, run_queue's order, yielding to a kickoff, the budget), the
pins (HyperFrames in ship.mjs / build.mjs / bootstrap.sh) and the server prerequisites.

  cd platform && python3 tests/test_advideo.py
  OTTO_TEST_RENDER=1 python3 tests/test_advideo.py    # + one real render: npx hyperframes, headless Chrome, ffmpeg, network
                                                       # for GSAP's CDN (≈ 1 min); OTTO_TEST_RENDER_OUT=<dir> keeps the mp4,
                                                       # the poster and key frames
"""
import contextlib, io, json, os, shutil, struct, subprocess, sys, tempfile, time, unittest, zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
REPO = PLATFORM.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-advideo-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_PUBLIC_BASE": "https://otto.example/", "OTTO_LOCKS": str(TMP / "locks"), "OTTO_PLANS": str(TMP / "plans.json"),
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_FONT_CACHE": str(TMP / "fonts"), "OTTO_RENDER_TMP": str(TMP / "rtmp"),
       "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_COPY_LEDGER": str(TMP / "copy-usage.json")}
CLEAR = ("OTTO_COPY_QUEUE", "OTTO_VIDEO_TMP", "OTTO_VIDEO_KEEP", "OTTO_RENDER_FONTS", "OTTO_CRON_TIMEOUT_S", "OTTO_DOMAIN",
         "OTTO_VIDEO_RENDER_TIMEOUT_S", "ANTHROPIC_API_KEY", "OTTO_COPY")
MODS = ("ap", "otto_paths", "otto_styles", "otto_advideo", "otto_creative", "otto_ads", "otto_copy", "otto_render",
        "otto_provenance", "otto_publish")
PINS = [("ap", "DATA", "data.json"), ("ap", "HTML", "index.html"), ("ap", "BRANDS", "brands"), ("otto_paths", "ASSETS", "assets"),
        ("otto_render", "BRANDS", "brands"), ("otto_creative", "BRANDS", "brands"), ("otto_ads", "BRANDS", "brands"),
        ("otto_creative", "OUT", "assets/ads"), ("otto_render", "FONT_CACHE", "fonts")]
YM = "2026-10"
FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_SAVED, S = {}, {}


def tiny_png(w=8, h=8, rgb=(122, 59, 18), alpha=False):
    raw = b"".join(b"\x00" + (bytes(rgb) + (b"\x00" if alpha else b"")) * w for _ in range(h))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def bag_png(w=180, h=270):
    """A small transparent packshot: a brown bag with a cream label, clear around it (otto_render.is_cutout says yes)."""
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            if not (30 <= x < w - 30 and 30 <= y < h - 25):
                row += b"\x00\x00\x00\x00"
            elif 110 <= y < 190 and 55 <= x < w - 55:
                row += b"\xf3\xe9\xd8\xff"
            else:
                row += b"\x4a\x2a\x14\xff"
        rows.append(bytes(row))

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def fake_mp4(path, pad=0):
    mdat = b"\x00" * (64 + pad)
    Path(path).write_bytes(struct.pack(">I4s", 16, b"ftyp") + b"isom\x00\x00\x02\x00" + struct.pack(">I4s", 8 + len(mdat), b"mdat") + mdat)


def real_media(mp4, jpg):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x7A3B12:s=108x192:d=1", "-f", "lavfi",
                    "-i", "sine=frequency=330:duration=1", "-c:a", "aac", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x7A3B12:s=108x192", "-frames:v", "1",
                    str(jpg)], check=True)


EC = {"headline": "Coffee that tastes like it should.", "accent": "tastes like it should.", "sub": "Roasted in Utrecht since 2014.",
      "fine": "A bag costs € 12."}
BEATS = {
    "notes": ("notes_app", {"note": {"meta": "Sunday, 8:40", "title": "Why my coffee tasted flat",
                                     "struck": ["supermarket beans", "no roast date", "a year on the shelf"], "keep": "fresh beans"}}),
    "versus": ("us_vs_them", {"versus": {"vs": "vs", "left": {"label": "Supermarket coffee", "rows": ["No roast date", "Months old", "Big batches"]},
                                         "right": {"label": "Bean Bros", "rows": ["Roast date on it", "This month", "Small batches"]},
                                         "footer": "Taste the difference."}}),
    "big": ("big_number", {"big": {"phrases": [{"big": "Since 2014", "rest": "roasting in Utrecht."}, {"big": "Small", "rest": "batches."},
                                               {"big": "€ 12", "rest": "a bag."}]}}),
    "texts": ("text_message", {"thread": {"name": "Sam", "initial": "S", "stamp": "Today 9:14", "placeholder": "Message",
                                          "messages": [{"from": "them", "text": "your coffee was so good"}, {"from": "me", "text": "Bean Bros"},
                                                       {"from": "them", "text": "where do I get it?"}, {"from": "me", "text": "they ship it"}]}}),
    "search": ("search", {"search": {"placeholder": "Search", "query": "fresh coffee beans", "suggestions": ["fresh coffee beans",
                                     "fresh coffee beans utrecht"], "pick": 1, "result": {"site": "Bean Bros", "url": "beanbros.example",
                                                                                          "title": "Bean Bros | Coffee roasters",
                                                                                          "snippet": "Small-batch coffee, roasted in Utrecht."}}}),
    "reel": ("product_hero", {"vo": ["Every bag shows its roast date.", "Small batches, roasted in Utrecht."],
                              "lines": ["The roast date is on every bag", "Growth: 20%", "Small batches, roasted in Utrecht"]}),
}


def vcell(cid, kit):
    style, data = BEATS[kit]
    return {"id": cid, "style": style, "slot": "faceless", "format": "video", "size": "story",
            "video": {"kit": kit, "data": f"video/{YM}/{cid}.json"}, "data": dict(json.loads(json.dumps(data)), endcard=dict(EC)),
            "copy": {"by": "otto_copy", "state": "written"}}


def angle(aid, cells, family="pain"):
    return {"id": aid, "name": f"Concept {aid}", "family": family, "stage": "cold", "headlines": ["Fresh beans, every bag"],
            "primaries": ["Every bag shows its roast date.", "Small batches, roasted in Utrecht since 2014."],
            "description": "Roasted in Utrecht", "cta": "SHOP_NOW", "ads": cells}


def matrix(angles):
    return {"brand": "beans", "month": YM, "preset": "micro", "angles": angles}


def six():
    return matrix([angle("a1", [vcell("a1-notes", "notes"), vcell("a1-versus", "versus"), vcell("a1-big", "big"),
                                {"id": "a1-editorial", "style": "editorial", "size": "feed",
                                 "data": {"headline": "Fresh *beans*.", "photo": "roastery-photo.png"}}]),
                   angle("a2", [vcell("a2-texts", "texts"), vcell("a2-search", "search"), vcell("a2-reel", "reel")], "identity")])


def brand(**kw):
    b = {"id": "beans", "name": "Bean Bros", "url": "beanbros.example", "status": "active", "plan": "starter", "tz": "Europe/Amsterdam",
         "countries": ["NL"], "lang": "en", "members": ["kim@beans.example"]}
    b.update(kw)
    return b


SCAN = {"url": "https://beanbros.example", "final_url": "https://beanbros.example/", "identity": {"site_name": "Bean Bros"},
        "languages": ["en"], "visual": {"palette": [{"hex": "#7A3B12", "count": 30}, {"hex": "#E8A33D", "count": 12}],
                                        "neutrals": [{"hex": "#1E120A"}, {"hex": "#FBF6EE"}], "fonts": []},
        "commerce": {"currency": "EUR", "prices": ["€ 12"]}, "trust": ["Roasted in Utrecht since 2014"], "quotes": []}


def write_brand(scan=None, mx=None, **kw):
    f = TMP / "brands" / "beans"
    (f / "assets").mkdir(parents=True, exist_ok=True)
    (f / "scan.json").write_text(json.dumps(scan or SCAN))
    (f / "strategy.json").write_text(json.dumps({"proof_bank": [{"id": "pr1", "claim": "Roasted in Utrecht since 2014"}],
                                                 "offers": [{"id": "o1", "name": "Bag", "price": "€ 12"}]}))
    (f / "compliance.json").write_text(json.dumps({"banned": ["miracle"]}))
    (f / "brand-profile.md").write_text("# Bean Bros — brand profile\n")
    (f / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 80"><text x="0" y="60" fill="#3B1F0E">'
                                'Bean Bros</text></svg>')
    (f / "assets" / "bag-cutout.png").write_bytes(tiny_png(alpha=True))
    (f / "assets" / "roastery-photo.png").write_bytes(tiny_png(rgb=(200, 170, 140)))
    (f / f"ads-{YM}.json").write_text(json.dumps(mx or six(), indent=1))
    d = {"brands": [brand(**kw)], "posts": [], "campaigns": [], "recommendations": [], "connections": []}
    (TMP / "data.json").write_text(json.dumps(d, indent=1))


def data():
    return json.loads((TMP / "data.json").read_text())


def set_data(fn):
    d = data()
    fn(d)
    (TMP / "data.json").write_text(json.dumps(d, indent=1))


def mx():
    return json.loads((TMP / "brands" / "beans" / f"ads-{YM}.json").read_text())


def save_mx(m):
    (TMP / "brands" / "beans" / f"ads-{YM}.json").write_text(json.dumps(m, indent=1))


def cell(cid, m=None):
    return next(c for a in (m or mx())["angles"] for c in a["ads"] if c["id"] == cid)


def fake_renderer(job):
    ad = json.loads(Path(job["ad"]).read_text())
    S["jobs"].append({"fmt": job["fmt"], "kit": job["kit"], "name": job["name"], "ad": ad,
                      "brand": json.loads(Path(job["brand"]).read_text()),
                      "font": (Path(job["brand"]).parent / "assets" / "brand.woff2").read_bytes()})
    if S.get("during"):
        S["during"](job)
    if S.get("fail") and S["fail"](job):
        raise otto_advideo.RenderError("check failed — text_box_overflow “Roast date on the bag”")
    out = Path(job["proj"]) / "renders"
    out.mkdir(parents=True, exist_ok=True)
    mp4, jpg = out / f"{job['name']}.mp4", out / f"{job['name']}.jpg"
    if S.get("real_media"):
        real_media(mp4, jpg)
    else:
        fake_mp4(mp4, S.get("pad", 0))
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    return {"mp4": mp4, "poster": jpg, "sheet": None, "duration": S.get("duration", 12.0), "log": "fake"}


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **kw)
    S["out"] = buf.getvalue()
    return r


def setUpModule():
    for d in ("brands", "secrets", "assets", "public", "locks", "fonts", "rtmp"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(PLATFORM / "plans.json", TMP / "plans.json")
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    g = globals()
    for m in MODS:
        g[m] = __import__(m)
    _SAVED["pins"] = [(m, a, getattr(g[m], a)) for m, a, _ in PINS]
    for m, a, rel in PINS:
        setattr(g[m], a, TMP / rel)
    _SAVED["fns"] = (otto_advideo.RENDERER, otto_advideo.SPAWN, otto_advideo.toolchain, otto_advideo.is_cutout, otto_advideo.shrink)


def tearDownModule():
    g = globals()
    if "fns" in _SAVED:
        (otto_advideo.RENDERER, otto_advideo.SPAWN, otto_advideo.toolchain, otto_advideo.is_cutout, otto_advideo.shrink) = _SAVED["fns"]
    for m, a, v in _SAVED.get("pins", []):
        setattr(g[m], a, v)
    for k, v in (_SAVED.get("env") or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        for x in ("brands", "assets", "public", "locks", "fonts", "rtmp", "queue"):
            shutil.rmtree(TMP / x, ignore_errors=True)
            (TMP / x).mkdir()
        (TMP / "video.log").unlink(missing_ok=True)
        write_brand()
        S.clear()
        S.update(jobs=[], spawned=[])
        otto_advideo.RENDERER = fake_renderer
        otto_advideo.SPAWN = lambda args, log: S["spawned"].append(args)
        otto_advideo.toolchain = lambda: None
        otto_advideo.is_cutout = lambda p: "cutout" in Path(p).name
        otto_advideo.shrink = _SAVED["fns"][4]
        for k in CLEAR:
            os.environ.pop(k, None)

    def render(self, **kw):
        return quiet(otto_advideo.render_month, "beans", kw.pop("ym", YM), **kw)

    def statuses(self):
        return {r["id"]: r["status"] for r in otto_styles.check_matrix("beans", YM, mx())["cells"]}

    def age_failures(self, hours=7):
        m = mx()
        for a in m["angles"]:
            for c in a["ads"]:
                f = (c.get("render") or {}).get("failed")
                if f:
                    f["at"] = otto_advideo.iso(datetime.now(timezone.utc) - timedelta(hours=hours))
        save_mx(m)


VIDEO_IDS = ["a1-notes", "a1-versus", "a1-big", "a2-texts", "a2-search", "a2-reel"]


class RenderTest(Base):
    def test_scripted_cells_render_in_the_brands_look(self):
        self.assertEqual({k: v for k, v in self.statuses().items() if k in VIDEO_IDS}, {k: "scripted" for k in VIDEO_IDS})
        r = self.render()
        self.assertEqual(r["rendered"], VIDEO_IDS, S["out"])
        self.assertEqual(r["failed"], [])
        # 9:16 for every kit, 4:5 too for the kits with a tuned 4:5 layout
        self.assertEqual(sorted((j["kit"], j["fmt"]) for j in S["jobs"]),
                         sorted([("notes", "9x16"), ("notes", "4x5"), ("versus", "9x16"), ("big", "9x16"), ("texts", "9x16"),
                                 ("texts", "4x5"), ("search", "9x16"), ("reel", "9x16")]))
        m = mx()
        self.assertTrue(otto_paths.valid_token(m.get("media_token")), "the month's media token is kept on the matrix")
        for cid in VIDEO_IDS:
            c = cell(cid, m)
            self.assertEqual(c["status"], "rendered")
            self.assertEqual(c["render"]["hash"], otto_styles.video_hash(c))
            self.assertEqual(c["render"]["hf"], otto_advideo.HF_PKG)
            self.assertNotIn("failed", c["render"])
            h8 = c["render"]["hash"][:8]
            self.assertRegex(c["file"], rf"^assets/ads/beans-{YM}-{cid}-{h8}-9x16-[0-9a-f]{{32}}\.mp4$")
            self.assertRegex(c["poster"], rf"^assets/ads/beans-{YM}-{cid}-{h8}-9x16-poster-[0-9a-f]{{32}}\.jpg$")
            self.assertEqual(c["render"]["files"]["9x16"]["file"], c["file"])
            for f in c["render"]["files"].values():
                for ref in (f["file"], f["poster"]):
                    self.assertTrue(otto_paths.local_path(ref).is_file(), ref)
                    self.assertTrue((TMP / "public" / ref[len("assets/"):]).is_file(), f"{ref} is not public")
                self.assertTrue(9 <= f["duration"] <= 30)
                self.assertLessEqual(f["bytes"], otto_advideo.MAX_BYTES)
        self.assertEqual(sorted(cell("a1-notes", m)["render"]["files"]), ["4x5", "9x16"])
        self.assertEqual(sorted(cell("a1-big", m)["render"]["files"]), ["9x16"])
        st = self.statuses()
        self.assertEqual({k: st[k] for k in VIDEO_IDS}, {k: "ready" for k in VIDEO_IDS}, "a rendered video is ready to launch")
        self.assertEqual(st["a1-editorial"], "ready", "the statics are untouched")
        self.assertFalse((TMP / "brands" / "beans" / "video").exists(), "no kit JSON is written into the brand folder")

    def test_the_kit_gets_the_copy_verbatim_and_the_brands_look(self):
        self.render()
        jobs = {(j["kit"], j["fmt"]): j for j in S["jobs"]}
        b = jobs[("notes", "9x16")]["brand"]
        self.assertEqual(b["name"], "Bean Bros")
        self.assertEqual(b["colors"]["primary"], "#7A3B12", "the brand's colour, not Otto's")
        self.assertNotIn("#2447F0", json.dumps(b), "never Otto's look")
        self.assertEqual(set(b["assets"]), {"pack", "photo", "logo"})
        self.assertEqual(jobs[("notes", "9x16")]["font"],
                         (REPO / "motion" / "otto-kit" / "fonts" / "InterTight-var-latin.woff2").read_bytes(),
                         "no site font found: the statics' default display face (Inter Tight)")
        notes = jobs[("notes", "9x16")]["ad"]
        self.assertEqual(notes["note"], BEATS["notes"][1]["note"], "the copy is copied verbatim")
        self.assertEqual({k: notes["endcard"][k] for k in EC}, EC)
        self.assertEqual(notes["formats"], ["9x16", "4x5"])
        self.assertEqual(notes["endcard"]["products"], ["pack"])
        self.assertEqual(notes["endcard"]["logo"], "logo", "a dark logo on a light end card")
        self.assertNotIn(notes["endcard"]["ground"], otto_advideo.DARK, "a dark-only logo keeps the end cards light")
        self.assertEqual(jobs[("big", "9x16")]["ad"]["big"]["hero"], "pack")
        self.assertEqual(jobs[("versus", "9x16")]["ad"]["versus"]["right"]["image"], "pack")
        self.assertEqual(jobs[("search", "9x16")]["ad"]["search"]["result"]["image"], "pack")
        reel = jobs[("reel", "9x16")]["ad"]["reel"]
        self.assertEqual(reel["lines"], BEATS["reel"][1]["lines"])
        self.assertEqual(reel["vo"], BEATS["reel"][1]["vo"], "the voice lines are kept (a silent reel: no clip, no voice)")
        self.assertTrue(all("clip" not in c for c in reel["cues"]))
        self.assertTrue(reel["cues"][-1]["endcard"])
        self.assertTrue(reel["cues"][1].get("stat"), "“Growth: 20%” counts up as a stat card")
        self.assertTrue(all(2.0 <= c["dur"] <= 4.0 for c in reel["cues"][:-1]))
        self.assertTrue(any(c.get("shot") for c in reel["cues"]))
        # the brand's own Google sans, once it is cached (fetched once on the server)
        (TMP / "fonts" / "adkit-dm-sans-latin.woff2").write_bytes(b"wOF2" + b"\x00" * 2000)
        write_brand(scan=dict(SCAN, visual=dict(SCAN["visual"], fonts=["DM Sans"])))
        S["jobs"].clear()
        self.render()
        self.assertEqual(S["jobs"][0]["font"][:4], b"wOF2")
        self.assertIn("DM Sans", S["out"])

    def test_a_white_logo_gets_a_dark_end_card(self):
        (TMP / "brands" / "beans" / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 2">'
                                                           '<path fill="#FFFFFF" d="M0 0h10v2H0z"/></svg>')
        self.render()
        ad = next(j for j in S["jobs"] if j["kit"] == "notes")
        self.assertEqual(ad["ad"]["endcard"]["logo"], "logo_white")
        self.assertIn(ad["ad"]["endcard"]["ground"], otto_advideo.DARK)

    def test_cached_until_the_beats_change(self):
        self.render()
        first = cell("a1-notes")
        n = len(S["jobs"])
        r = self.render()
        self.assertEqual(len(S["jobs"]), n, "nothing renders twice")
        self.assertEqual(sorted(r["cached"]), sorted(VIDEO_IDS))
        # a person edits the beats: the old video is stale — never launched with the old copy — and renders again
        m = mx()
        cell("a1-notes", m)["data"]["note"]["title"] = "Why my coffee tasted like cardboard"
        save_mx(m)
        self.assertEqual(self.statuses()["a1-notes"], "scripted")
        cr = otto_creative.build_matrix(data(), {"id": "cp-1", "brand": "beans", "plan": YM, "objective": "sales"}, mx(), dry=True)
        self.assertIn("a1-notes", [v["id"] for v in cr["matrix"]["scripted_videos"]])
        self.assertNotIn("a1-notes", [ad["id"] for con in cr["concepts"] for ad in con["ads"]])
        r = self.render()
        self.assertEqual(r["rendered"], ["a1-notes"])
        new = cell("a1-notes")
        self.assertNotEqual(new["file"], first["file"], "new beats, new names")
        for ref in (first["file"], first["poster"], first["render"]["files"]["4x5"]["file"]):
            self.assertFalse(otto_paths.local_path(ref).exists(), f"{ref}: the stale render is removed")
            self.assertFalse((TMP / "public" / ref[len("assets/"):]).exists())
        # unless a campaign still points at it (a launched flight's creatives)
        m = mx()
        cell("a1-notes", m)["data"]["note"]["keep"] = "beans from Utrecht"
        save_mx(m)
        set_data(lambda d: d["campaigns"].append({"id": "cp-live", "brand": "beans", "creatives": {"videos": [{"file": new["file"]}]}}))
        self.render()
        self.assertTrue(otto_paths.local_path(new["file"]).exists())
        self.assertNotEqual(cell("a1-notes")["file"], new["file"])
        # --force renders a cached cell again
        S["jobs"].clear()
        self.render(force=True, only={"a1-big"})
        self.assertEqual([j["kit"] for j in S["jobs"]], ["big"])

    def test_beats_changed_while_rendering_drops_the_result(self):
        def edit(job):
            if job["kit"] == "versus":
                m = mx()
                cell("a1-versus", m)["data"]["versus"]["footer"] = "Taste it."
                save_mx(m)
        S["during"] = edit
        r = self.render(only={"a1-versus"})
        self.assertEqual(r["rendered"], [])
        c = cell("a1-versus")
        self.assertNotIn("file", c)
        self.assertEqual(list((TMP / "assets" / "ads").glob("*a1-versus*")), [], "the dropped render leaves no files")
        S["during"] = None
        self.assertEqual(self.render(only={"a1-versus"})["rendered"], ["a1-versus"])

    def test_failure_leaves_the_cell_scripted_retries_and_files_one_card(self):
        S["fail"] = lambda job: job["kit"] == "versus"
        r = self.render()
        self.assertEqual([x[0] for x in r["failed"]], ["a1-versus"])
        self.assertEqual(len(r["rendered"]), 5, "one failure never stops the others")
        c = cell("a1-versus")
        self.assertNotIn("file", c)
        self.assertNotIn("status", c)
        self.assertEqual(c["render"]["failed"]["attempts"], 1)
        self.assertIn("text_box_overflow", c["render"]["failed"]["error"])
        self.assertEqual(self.statuses()["a1-versus"], "scripted")
        self.assertFalse(data()["recommendations"], "one failed run is not a card yet")
        # the statics and every other video still launch
        cr = otto_creative.build_matrix(data(), {"id": "cp-1", "brand": "beans", "plan": YM, "objective": "sales"}, mx(), dry=True)
        ids = {ad["id"] for con in cr["concepts"] for ad in con["ads"]}
        self.assertIn("a1-editorial", ids)
        self.assertEqual(ids & set(VIDEO_IDS), set(VIDEO_IDS) - {"a1-versus"})
        # a failure is not retried for 6 hours (same beats)
        S["jobs"].clear()
        r = self.render()
        self.assertEqual(S["jobs"], [])
        self.assertIn("failed recently", S["out"])
        # later: retried, fails again → the owner card (one, updated by later runs)
        self.age_failures()
        r = self.render()
        self.assertEqual(cell("a1-versus")["render"]["failed"]["attempts"], 2)
        cards = [x for x in data()["recommendations"] if x["title"] == "Video ads not rendering: Bean Bros"]
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["status"], cards[0]["audience"], cards[0]["brand"]), ("proposed", "owner", "beans"))
        self.assertIn("a1-versus", cards[0]["why"])
        self.age_failures()
        self.render()
        self.assertEqual(len([x for x in data()["recommendations"] if x["title"].startswith("Video ads not rendering")]), 1)
        # fixed: it renders, the failure is gone and the card is resolved
        S["fail"] = None
        self.age_failures()
        r = self.render()
        self.assertEqual(r["rendered"], ["a1-versus"])
        self.assertNotIn("failed", cell("a1-versus")["render"])
        self.assertEqual(data()["recommendations"][0]["status"], "done")

    def test_new_beats_retry_a_failed_cell_at_once(self):
        S["fail"] = lambda job: job["kit"] == "versus"
        self.render()
        S["fail"] = None
        m = mx()
        cell("a1-versus", m)["data"]["versus"]["right"]["rows"][0] = "Dated bags"
        save_mx(m)
        self.assertEqual(self.render()["rendered"], ["a1-versus"], "the copy was fixed: no 6-hour wait")

    def test_size_and_length_checks(self):
        S["duration"] = 8.0
        r = self.render(only={"a1-big"})
        self.assertIn("outside 9–30", r["failed"][0][1])
        S["duration"] = 31.0
        self.age_failures()
        self.assertIn("outside 9–30", self.render(only={"a1-big"})["failed"][0][1])
        S["duration"], S["pad"] = 12.0, otto_advideo.MAX_BYTES + 1
        otto_advideo.shrink = lambda p, limit=otto_advideo.MAX_BYTES: False
        self.age_failures()
        self.assertIn("does not shrink under 10 MB", self.render(only={"a1-big"})["failed"][0][1])

        def shrink(p, limit=otto_advideo.MAX_BYTES):
            fake_mp4(p)
            return True
        otto_advideo.shrink = shrink
        self.age_failures()
        self.assertEqual(self.render(only={"a1-big"})["rendered"], ["a1-big"])
        self.assertLess(cell("a1-big")["render"]["files"]["9x16"]["bytes"], otto_advideo.MAX_BYTES)

    def test_right_to_left_brand_is_not_rendered(self):
        write_brand(scan=dict(SCAN, languages=["he"]), lang="he")
        (TMP / "brands" / "beans" / "render.json").write_text(json.dumps({"lang": "he"}))
        r = self.render()
        self.assertEqual(r["rendered"], [])
        self.assertIn("right to left", r["error"])
        self.assertEqual(S["jobs"], [])
        self.assertNotIn("render", cell("a1-notes"), "no cell is touched")
        self.assertEqual([x["title"] for x in data()["recommendations"]], ["Video ads not rendering: Bean Bros"])

    def test_skips(self):
        set_data(lambda d: d["brands"][0].update(paused=True))
        self.assertEqual(self.render()["skipped"], "paused")
        set_data(lambda d: d["brands"][0].update(paused=False, plan="content"))
        self.assertIn("no paid ads", self.render()["skipped"])
        set_data(lambda d: d["brands"][0].update(plan="starter"))
        self.assertEqual(self.render(ym="2026-11")["skipped"], "no matrix")
        self.assertEqual(quiet(otto_advideo.render_month, "nobody", YM)["skipped"], "unknown brand")
        otto_advideo.toolchain = lambda: "not installed: node, npx"
        r = self.render()
        self.assertIn("node", r["error"])
        self.assertEqual(r["rendered"], [])
        self.assertEqual(quiet(otto_advideo.daily, "beans"), 1, "the nightly job fails loudly when it cannot render")
        r = self.render(dry=True)
        self.assertEqual(r["skipped"], "dry")
        self.assertIn("WOULD RENDER a1-notes", S["out"])
        self.assertEqual(S["jobs"], [])


class CapTest(Base):
    def twelve(self):
        kits = ["notes", "versus", "big", "texts", "search", "reel"]
        return matrix([angle(f"a{i}", [vcell(f"a{i}-v{j}", kits[(i + j) % 6]) for j in range(4)]) for i in range(1, 4)])

    def test_the_plans_cap_in_concept_order(self):
        write_brand(mx=self.twelve())
        r = self.render()
        order = [c["id"] for a in mx()["angles"] for c in a["ads"]]
        self.assertEqual(r["rendered"], order[:10], "Starter: 10 video ads a month, in concept order")
        self.assertEqual(r["over_cap"], order[10:])
        self.assertEqual(self.render()["over_cap"], order[10:])
        cr = otto_creative.build(data(), {"id": "cp-1", "brand": "beans", "plan": YM, "objective": "sales"}, dry=True)
        self.assertEqual(len(cr["videos"]), 10)

    def test_a_failed_cell_holds_no_slot(self):
        write_brand(mx=self.twelve())
        S["fail"] = lambda job: "a1-v1-" in job["name"]
        r = self.render()
        order = [c["id"] for a in mx()["angles"] for c in a["ads"]]
        self.assertEqual(r["rendered"], [x for x in order[:11] if x != "a1-v1"], "the next cell takes the failed one's slot")
        self.assertEqual(r["over_cap"], order[11:])
        self.assertEqual(self.render()["over_cap"], order[11:], "a recent failure holds no slot in the next run either")

    def test_trial_and_plans_without_video(self):
        write_brand(mx=self.twelve(), plan="trial")
        self.assertEqual(len(self.render()["rendered"]), 3, "the trial previews 3")
        set_data(lambda d: d["brands"][0].update(plan="growth"))
        self.assertEqual(len(self.render()["rendered"]), 9, "Growth: the rest (31 a month)")


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class ProvenanceTest(Base):
    def test_only_ai_pictures_mark_the_video(self):
        S["real_media"] = True
        self.render(only={"a1-big"})
        c = cell("a1-big")
        self.assertNotIn("media_ai", c["render"], "the client's real pictures + synthesized music: not AI media")
        self.assertFalse(otto_provenance.inspect(otto_paths.local_path(c["file"]))["generated"])
        # the product cut-out came out of an image model: the ad contains a generated element
        otto_provenance.mark(TMP / "brands" / "beans" / "assets" / "bag-cutout.png", ["image"], "Leonardo.ai gpt-image-2")
        self.render(only={"a1-big"}, force=True)
        c = cell("a1-big")
        for ref in (c["file"], c["poster"]):
            info = otto_provenance.inspect(otto_paths.local_path(ref))
            self.assertTrue(info["generated"], ref)
            self.assertEqual(c["render"]["media_ai"][ref]["source_type"], "compositeSynthetic")
            self.assertEqual(c["render"]["media_ai"][ref]["tool"], "Leonardo.ai gpt-image-2")
        side = otto_provenance.sidecar_path(otto_paths.local_path(c["file"]))
        self.assertTrue(side.is_file())
        self.assertTrue((TMP / "public" / "ads" / side.name).is_file(), "the sidecar is published with the video")


class LaunchTest(Base):
    def test_build_matrix_and_the_meta_creative(self):
        self.render()
        c = {"id": "cp-1", "brand": "beans", "plan": YM, "objective": "sales", "media_token": otto_paths.new_token()}
        cr = otto_creative.build_matrix(data(), c, mx(), dry=True)
        ads = {ad["id"]: ad for con in cr["concepts"] for ad in con["ads"]}
        notes, big = ads["a1-notes"], ads["a1-big"]
        self.assertEqual([(f["size"], f["kind"]) for f in notes["files"]], [("story", "video"), ("feed", "video")])
        self.assertEqual(notes["files"][0]["file"], cell("a1-notes")["file"], "inside assets/: kept as it is")
        self.assertEqual(notes["files"][0]["poster"], cell("a1-notes")["poster"])
        self.assertEqual(notes["files"][1]["file"], cell("a1-notes")["render"]["files"]["4x5"]["file"])
        self.assertEqual([f["size"] for f in big["files"]], ["story"])
        # otto_ads: both videos uploaded once, one creative with placement rules (9:16 Stories / Reels, 4:5 elsewhere)
        up, posts = [], []
        saved = (otto_ads.upload_video, otto_ads.upload_image_bytes, otto_publish.graph)
        otto_ads.upload_video = lambda ref, m, base: up.append(ref) or f"v{len(up)}"
        otto_ads.upload_image_bytes = lambda ref, m: f"h-{Path(ref).name[:12]}"
        try:
            media = otto_ads._ad_media(notes, {}, "https://otto.example/", {}, {}, lambda: None)
            self.assertEqual((media["video"], media["video_feed"]), ("v1", "v2"))
            self.assertEqual(len(up), 2)

            def graph(method, path, tok, **params):
                posts.append(params)
                if "asset_feed_spec" in params and S.get("refuse"):
                    raise otto_publish.GraphError("(#100) Invalid parameter")
                return {"id": f"cr{len(posts)}"}
            otto_publish.graph = graph
            otto_ads._concept_creative("act_1", "tok", "page", {"name": "Flight"}, notes, media, "https://beanbros.example", None,
                                       "LEARN_MORE")
            spec = json.loads(posts[-1]["asset_feed_spec"])
            self.assertEqual([v["video_id"] for v in spec["videos"]], ["v1", "v2"])
            self.assertEqual(spec["ad_formats"], ["SINGLE_VIDEO"])
            self.assertEqual([r["video_label"]["name"] for r in spec["asset_customization_rules"]], ["a1-notes-story", "a1-notes-feed"])
            S["refuse"] = True
            with contextlib.redirect_stdout(io.StringIO()):
                otto_ads._concept_creative("act_1", "tok", "page", {"name": "Flight"}, notes, media, "https://beanbros.example", None,
                                           "LEARN_MORE")
            vd = json.loads(posts[-1]["object_story_spec"])["video_data"]
            self.assertEqual(vd["video_id"], "v1", "refused: the 9:16 video everywhere")
            one = otto_ads._ad_media(big, {}, "https://otto.example/", {}, {}, lambda: None)
            self.assertNotIn("video_feed", one)
        finally:
            otto_ads.upload_video, otto_ads.upload_image_bytes, otto_publish.graph = saved


class KitTest(Base):
    def test_safe_zone_patches_match_the_kit_templates(self):
        proj = TMP / "rtmp" / "proj"
        (proj / "compositions").mkdir(parents=True)
        tpl = REPO / "motion" / "ad-kit" / "templates"
        for f in list((tpl / "styles").glob("*.html")) + [tpl / "endcard.html"]:
            shutil.copy(f, proj / "compositions" / f.name)
        self.assertEqual(otto_advideo.safe_zone_patch(proj), [], "every SAFE_916 line is in the kit's templates")
        self.assertEqual(otto_advideo.safe_zone_patch(proj, otto_advideo.BUILD_PATCHES), [])
        self.assertIn("lineTop: 290", (proj / "compositions" / "reel.html").read_text())
        self.assertIn("top: 272px;", (proj / "compositions" / "texts.html").read_text())
        self.assertIn("data-layout-allow-overflow", (proj / "compositions" / "search.html").read_text())
        # a template that changed fails the cell instead of drifting into the safe zone
        self.assertTrue(otto_advideo.safe_zone_patch(proj), "patched once, the old lines are gone: reported")
        self.assertEqual(sorted(otto_advideo.SAFE_916), sorted(["endcard.html", "versus.html", "big.html", "search.html", "reel.html",
                                                               "texts.html"]))

    def test_grounds_keep_contrast_for_any_palette(self):
        import otto_render as orr
        for pal in ("#FFD400", "#0B1F4B", "#2E8B57", "#F4F4F4", "#E4002B", "#7A3B12"):
            tok = dict(orr.brand_tokens(None), primary=pal, accent=pal, accent_on_dark=pal)
            c = otto_advideo.kit_colors(tok)
            for kit, (scene, end) in otto_advideo.GROUNDS.items():
                for g in (otto_advideo.pick_ground(c, scene), otto_advideo.pick_ground(c, end)):
                    self.assertGreaterEqual(orr.contrast(otto_advideo.text_on(c, g), c[g]), 4.5, (pal, kit, g))
            self.assertGreaterEqual(orr.contrast(c["onPrimary"], c["primary"]), 3.0, pal)

    def test_lengthen_and_reel_cues(self):
        ad = {"style": "notes", "endcard": {"headline": "x"}}
        self.assertEqual(otto_advideo.lengthen(ad, 1.0)["endcard"]["duration"], 4.35)
        self.assertEqual(otto_advideo.lengthen({"style": "reel", "endcard": {}}, 0.5)["timing"]["tail"], 2.15)
        cues = otto_advideo.reel_cues(["One line", "Stat: 4.8", "A much longer line that goes on and on for a while"], set())
        self.assertEqual([("stat" in c, "shot" in c) for c in cues[:3]], [(False, False), (True, False), (False, False)])
        self.assertEqual(cues[2]["dur"], 4.0)
        self.assertTrue(cues[-1]["endcard"])

    def test_a_step_over_its_time_limit_is_killed(self):
        t0 = time.time()
        with self.assertRaises(otto_advideo.RenderError) as e:
            otto_advideo.run([sys.executable, "-c", "import time; time.sleep(30)"], TMP, dict(os.environ), 1)
        self.assertIn("timed out", str(e.exception))
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(otto_advideo._CHILDREN, [])

    def test_kit_env_has_a_writable_npm_cache_and_no_telemetry(self):
        saved = os.environ.pop("npm_config_cache", None)
        os.environ["OTTO_NPM_CACHE"] = str(TMP / "npm")
        try:
            env = otto_advideo.kit_env()
        finally:
            os.environ.pop("OTTO_NPM_CACHE", None)
            if saved is not None:
                os.environ["npm_config_cache"] = saved
        self.assertEqual(env["npm_config_cache"], str(TMP / "npm"))
        self.assertTrue((TMP / "npm").is_dir())
        self.assertEqual((env["HYPERFRAMES_NO_TELEMETRY"], env["DO_NOT_TRACK"], env["HYPERFRAMES_NO_UPDATE_CHECK"]), ("1", "1", "1"))
        self.assertEqual(env["HF_CLI"], f"npx --yes {otto_advideo.HF_PKG}")

    def test_pins_and_server_prerequisites(self):
        pin = otto_advideo.HF_PKG
        kit = REPO / "motion" / "ad-kit"
        self.assertIn(f'"npx --yes {pin}"', (kit / "ship.mjs").read_text())
        self.assertIn(f"npx --yes {pin} check", (kit / "build.mjs").read_text())
        boot = (REPO / "infra" / "bootstrap.sh").read_text()
        self.assertIn(f"HF_PKG={pin}", boot)
        self.assertIn("NODE_MAJOR=22", boot)
        self.assertIn("node_${NODE_MAJOR}.x", boot)
        self.assertNotIn("node_20.x", boot)
        self.assertIn("python3-numpy python3-scipy", boot)
        self.assertIn("/var/cache/otto/npm", boot)
        self.assertIn("env_default npm_config_cache /var/cache/otto/npm", boot)
        self.assertIn("env_default HYPERFRAMES_NO_TELEMETRY 1", boot)
        self.assertIn("browser ensure", boot)
        self.assertIn("if (!c.clip) return c.dur || 2.0;", (kit / "build.mjs").read_text(), "silent reel cues keep their length")
        svc = (REPO / "infra" / "systemd" / "otto-copy-queue.service").read_text()
        self.assertIn("TimeoutStartSec=2h", svc)
        self.assertGreater(2 * 3600, otto_copy.QUEUE_VIDEO_BUDGET_S + otto_advideo.render_timeout() + 15 * 60)


class TriggerTest(Base):
    def test_spawn_locally_or_queue_on_the_server(self):
        self.assertTrue(otto_advideo.spawn("beans", YM))
        self.assertEqual(Path(S["spawned"][0][1]).name, "otto_advideo.py")
        self.assertEqual(S["spawned"][0][2:], ["render", "--brand", "beans", "--month", YM])
        self.assertIn(f"render --brand beans --month {YM}", (TMP / "video.log").read_text())
        self.assertFalse(otto_advideo.spawn("../etc", YM))
        self.assertFalse(otto_advideo.spawn("beans", "2026-13"))
        self.assertFalse(otto_advideo.spawn("beans", "2026-11"), "no matrix: nothing to render")
        otto_advideo.toolchain = lambda: "not installed: node"
        self.assertFalse(otto_advideo.spawn("beans", YM), "locally without node nothing starts")
        q = TMP / "queue" / "copy"
        os.environ["OTTO_COPY_QUEUE"] = str(q)
        try:
            S["spawned"].clear()
            self.assertTrue(otto_advideo.spawn("beans", YM), "the server queues it whatever this process has")
            self.assertEqual(S["spawned"], [])
            self.assertEqual([f.name for f in q.iterdir()], [f"beans.{YM}.videos"])
            self.assertEqual(json.loads((q / f"beans.{YM}.videos").read_text())["kind"], "videos")
        finally:
            os.environ.pop("OTTO_COPY_QUEUE", None)
        otto_advideo.toolchain = lambda: None
        quiet(otto_advideo.render_month, "beans", YM)
        S["spawned"].clear()
        self.assertFalse(otto_advideo.spawn("beans", YM), "everything rendered: nothing to start")
        set_data(lambda d: d["brands"][0].update(plan="content"))
        self.assertFalse(otto_advideo.spawn("beans", YM))

    def test_queue_runs_kickoffs_first_and_a_render_steps_aside(self):
        q = TMP / "queue" / "copy"
        q.mkdir(parents=True)
        os.environ["OTTO_COPY_QUEUE"] = str(q)
        order = []
        saved = (otto_copy.write_week, otto_copy.render_pending, otto_copy.write_ads)
        otto_copy.write_week = lambda bid, *a, **k: order.append(("week", bid))
        otto_copy.render_pending = lambda bid, out=print: None
        otto_copy.write_ads = lambda bid, ym=None, **k: order.append(("ads", bid))
        try:
            (q / f"beans.{YM}.videos").write_text(json.dumps({"brand": "beans", "month": YM, "kind": "videos"}))
            time.sleep(0.01)
            (q / "other.week").write_text(json.dumps({"brand": "other", "days": 7}))

            def kickoff_arrives(job):                   # a new trial signs up while the first video renders
                if not (q / "late.week").exists() and not any(o[1] == "late" for o in order):
                    (q / "late.week").write_text(json.dumps({"brand": "late", "days": 7}))
                order.append(("render", job["kit"], job["fmt"]))
            S["during"] = kickoff_arrives
            n = quiet(otto_copy.run_queue)
            kinds = [o[0] for o in order]
            self.assertEqual(order[0], ("week", "other"), "the kickoff queued before it runs first")
            self.assertEqual(kinds[1], "render")
            self.assertEqual(order[2:4], [("render", "notes", "4x5"), ("week", "late")],
                             "the render finishes the cell in hand, then steps aside for the new kickoff")
            self.assertEqual(sorted(cell(x).get("status") for x in VIDEO_IDS), ["rendered"] * 6, "then the rest renders")
            self.assertEqual(list(q.iterdir()), [], "nothing left in the queue")
            self.assertGreaterEqual(n, 3)
            # out of budget: the job goes back to the queue untouched (the path unit starts the next run)
            (q / f"beans.{YM}.videos").write_text(json.dumps({"brand": "beans", "month": YM, "kind": "videos"}))
            S["jobs"].clear()
            quiet(otto_copy.run_queue, video_budget_s=0)
            self.assertEqual([f.name for f in q.iterdir()], [f"beans.{YM}.videos"])
            self.assertEqual(S["jobs"], [])
            # a claim a killed run left behind goes back into the queue after 3 hours
            (q / f"beans.{YM}.videos").rename(q / f"beans.{YM}.videos.work")
            old = time.time() - 4 * 3600
            os.utime(q / f"beans.{YM}.videos.work", (old, old))
            quiet(otto_copy.run_queue, video_budget_s=0)
            self.assertEqual([f.name for f in q.iterdir()], [f"beans.{YM}.videos"])
        finally:
            otto_copy.write_week, otto_copy.render_pending, otto_copy.write_ads = saved
            os.environ.pop("OTTO_COPY_QUEUE", None)

    def test_daily_renders_this_month_and_next_once_planned(self):
        now = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
        nov = six()
        nov["month"] = "2026-11"
        (TMP / "brands" / "beans" / "ads-2026-11.json").write_text(json.dumps(nov))
        self.assertEqual(quiet(otto_advideo.daily, "beans", now=now), 0)
        self.assertIn("beans 2026-10: 6 rendered", S["out"])
        self.assertIn("beans 2026-11: 6 rendered", S["out"])

    def test_status_rows(self):
        self.render(only={"a1-notes"})
        rows = quiet(otto_advideo.status_rows, "beans", now=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        row = next(r for r in rows if r["month"] == YM)
        self.assertEqual((row["rendered"], row["todo"], row["cap"]), (1, 5, 10))


class CronTest(unittest.TestCase):
    def test_the_nightly_job_and_its_timer(self):
        import otto_cron
        j = otto_cron.JOBS["ad-videos"]
        self.assertEqual((j.local, j.scope, j.kill, j.log), ("19:15", otto_cron.BRAND, False, "video.log"))
        self.assertGreater(j.timeout * 60, otto_advideo.DAILY_BUDGET_S + otto_advideo.render_timeout(),
                           "the run ends itself (budget + one render) before otto_cron's limit")
        d = {"brands": [{"id": "x", "status": "active", "plan": "starter"}, {"id": "y", "status": "active", "plan": "content"},
                        {"id": "z", "status": "active", "plan": "trial", "plan_until": "2099-01-01"}], "posts": [], "campaigns": []}
        tasks = {t.brand: t for t in otto_cron.tasks("ad-videos", d)}
        self.assertEqual([Path(tasks["x"].argv[1]).name] + tasks["x"].argv[2:], ["otto_advideo.py", "daily", "--brand", "x"])
        self.assertIn("no video ads", tasks["y"].skip)
        self.assertIsNone(tasks["z"].skip, "a trial previews its video ads too")
        f = REPO / "infra" / "systemd" / "otto-job-ad-videos.timer"
        self.assertEqual(f.read_text(), otto_cron.timer_text("ad-videos"))
        self.assertIn("OnCalendar=*-*-* *:15:00 UTC", f.read_text())
        self.assertIn("`ad-videos`", (PLATFORM / "crons.md").read_text())


@unittest.skipUnless(os.environ.get("OTTO_TEST_RENDER") == "1", "real HyperFrames render: OTTO_TEST_RENDER=1")
class RealRenderTest(Base):
    """One real render through npx hyperframes + headless Chrome + ffmpeg: the search kit (9:16 only, ≈ 10 s of video)."""

    def test_one_real_video(self):
        otto_advideo.RENDERER, otto_advideo.toolchain = _SAVED["fns"][0], _SAVED["fns"][2]
        otto_advideo.is_cutout = _SAVED["fns"][3]
        why = otto_advideo.toolchain()
        if why:
            self.skipTest(why)
        (TMP / "brands" / "beans" / "assets" / "bag-cutout.png").write_bytes(bag_png())
        t0 = time.time()
        r = self.render(only={"a2-search"})
        took = time.time() - t0
        self.assertEqual(r["rendered"], ["a2-search"], S["out"])
        c = cell("a2-search")
        mp4 = otto_paths.local_path(c["file"])
        info = otto_advideo.probe(mp4)
        self.assertEqual((info["width"], info["height"], info["video"], info["audio"]), (1080, 1920, "h264", "aac"))
        self.assertTrue(9 <= info["duration"] <= 30, info)
        self.assertLessEqual(mp4.stat().st_size, otto_advideo.MAX_BYTES)
        self.assertTrue(otto_paths.local_path(c["poster"]).read_bytes()[:3] == b"\xff\xd8\xff")
        print(f"\n  real render: {info['duration']:.1f}s video, {mp4.stat().st_size / 1048576:.2f} MB, rendered in {took:.0f}s")
        out = os.environ.get("OTTO_TEST_RENDER_OUT")
        if out:
            o = Path(out)
            o.mkdir(parents=True, exist_ok=True)
            shutil.copy(mp4, o / "search-9x16.mp4")
            shutil.copy(otto_paths.local_path(c["poster"]), o / "search-9x16-poster.jpg")
            for t in (1.0, info["duration"] * 0.45, info["duration"] * 0.7, info["duration"] - 0.4):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1",
                                str(o / f"frame-{t:05.2f}.png")], check=True)


if __name__ == "__main__":
    unittest.main()
