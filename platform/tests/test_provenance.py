#!/usr/bin/env python3
"""AI provenance marks (otto_provenance, EU AI Act Art. 50(2)): mark → inspect round trips for JPEG / PNG / MP4, the upstream
C2PA case, failure modes, the CLI, and the generation points that call it (genvisuals, otto_video, otto_motion,
otto_paths.ensure_jpeg). Stdlib unittest; MP4 tests need ffmpeg and are skipped without it. No network: Leonardo and
ElevenLabs are faked.

  cd platform && python3 tests/test_provenance.py

Under discover, earlier suites have imported the modules with their own OTTO_* paths, so setUpModule pins every
module-level path this suite touches to its own workspace and tearDownModule puts them back.
"""
import contextlib, io, json, os, shutil, struct, subprocess, sys, tempfile, unittest, zlib
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-provenance-test-"))
FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
# a 16×16 baseline JPEG (APP0 JFIF + COM, no XMP, no C2PA), made with ffmpeg; hex, so no long base64 run can look like a token
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010200000100010000fffe000f4c61766336302e332e31303000ffdb004300080a0a0b0a0b"
    "0d0d0d0d0d0d100f10101010101010101010101212121515151212121010121214141515171717151515151717191919"
    "1e1e1c1c2323242b2b33ffc4004c00010100000000000000000000000000000006010101000000000000000000000000"
    "00000507100100000000000000000000000000000000110100000000000000000000000000000000ffc0001108001000"
    "1003012200021100031100ffda000c03010002110311003f008f015a00ffd9")
# a real Leonardo gpt-image-2 output: JPEG bytes with OpenAI's signed C2PA manifest (trainedAlgorithmicMedia)
C2PA_JPEG = PLATFORM / "assets" / "posts" / "hg-001.png"
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_MOTION_ROOT": str(TMP / "motion")}
_SAVED = {}


def tiny_png(w=4, h=4, rgb=(36, 71, 240)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_chunks(data):
    i, out = 8, []
    while i < len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        t, body, crc = data[i + 4:i + 8], data[i + 8:i + 8 + ln], struct.unpack(">I", data[i + 8 + ln:i + 12 + ln])[0]
        out.append((t, body, crc == zlib.crc32(t + body) & 0xFFFFFFFF))
        i += 12 + ln
    return out


def make_mp4(path, seconds=1, audio=True):
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x2447F0:s=160x284:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)
    return path


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    sys.path.insert(0, str(PLATFORM))
    global ap, prov, otto_paths, genvisuals, otto_video, otto_motion
    import ap, otto_provenance as prov, otto_paths, genvisuals, otto_video, otto_motion   # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, genvisuals.OUT, genvisuals.BRANDS, otto_video.REELS,
                       otto_video.SECRETS, otto_video.BRANDS, otto_motion.REELS, otto_motion.MOTION, otto_motion.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_paths.ASSETS = TMP / "assets"
    genvisuals.OUT, genvisuals.BRANDS = TMP / "assets" / "posts", TMP / "brands"
    otto_video.REELS, otto_video.SECRETS, otto_video.BRANDS = TMP / "assets" / "reels", TMP / "secrets", TMP / "brands"
    otto_motion.REELS, otto_motion.MOTION, otto_motion.BRANDS = TMP / "assets" / "reels", TMP / "motion", TMP / "brands"
    for d in ("brands/alpha", "secrets", "assets/posts", "assets/reels", "public", "motion", "work"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    (TMP / "data.json").write_text(json.dumps({"brands": [{"id": "alpha", "name": "Alpha", "url": "alpha.nl", "status": "active",
                                                           "countries": ["NL"], "pillars": ["A"]}],
                                               "posts": [], "recommendations": [], "campaigns": []}))


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, genvisuals.OUT, genvisuals.BRANDS, otto_video.REELS,
     otto_video.SECRETS, otto_video.BRANDS, otto_motion.REELS, otto_motion.MOTION, otto_motion.BRANDS) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def add_post(**fields):
    with ap.transaction(sync=False) as d:
        p = dict({"brand": "alpha", "pillar": "A", "platform": "ig", "hook": "h", "status": "draft",
                  "slot": "2031-01-01T09:00"}, **fields)
        d["posts"] = [x for x in d["posts"] if x["id"] != p["id"]] + [p]
    return p


class JpegTest(unittest.TestCase):
    def setUp(self):
        self.f = TMP / "work" / "a.jpg"
        self.f.write_bytes(TINY_JPEG)

    def test_mark_then_inspect_round_trip(self):
        info = prov.mark(self.f, ["image"], "Leonardo.ai gpt-image-2")
        self.assertEqual((info["generated"], info["kind"], info["source_type"], info["marked"]),
                         (True, "image", "trainedAlgorithmicMedia", "xmp"))
        got = prov.inspect(self.f)
        self.assertTrue(got["generated"])
        self.assertEqual(got["digital_source_type"], "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia")
        self.assertEqual((got["ai_system"], got["kinds"], got["tool"]), ("Leonardo.ai gpt-image-2", ["image"], "Leonardo.ai gpt-image-2"))

    def test_image_data_untouched_and_segment_order(self):
        prov.mark(self.f, ["image"], "x")
        data = self.f.read_bytes()
        segs, sos = prov._jpeg_segments(data)
        self.assertEqual(data[sos:], TINY_JPEG[prov._jpeg_segments(TINY_JPEG)[1]:], "scan data changed")
        self.assertEqual([m for s, e, m, p in segs][:2], [0xE0, 0xE1], "XMP APP1 goes right after APP0 (JFIF)")
        self.assertTrue(data[segs[1][3]:].startswith(prov.JPEG_XMP))
        if FFMPEG:
            r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.f), "-f", "null", "-"], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_remark_replaces_and_keeps_foreign_xmp(self):
        foreign = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
                   '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
                   'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture">'
                   '<dc:creator><rdf:Seq><rdf:li>Studio Alpha</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF>'
                   '</x:xmpmeta><?xpacket end="w"?>').encode()
        seg = b"\xff\xe1" + struct.pack(">H", 2 + len(prov.JPEG_XMP) + len(foreign)) + prov.JPEG_XMP + foreign
        self.f.write_bytes(TINY_JPEG[:20] + seg + TINY_JPEG[20:])       # after SOI + APP0 (18 bytes)
        prov.mark(self.f, ["image"], "first")
        prov.mark(self.f, ["image"], "second", composite=True)
        data = self.f.read_bytes()
        self.assertEqual(data.count(prov.JPEG_XMP), 1, "one XMP segment, replaced in place")
        self.assertEqual(data.count(b"DigitalSourceType"), 2, "one element (open + close tag), the old attribute is gone")
        self.assertIn(b"Studio Alpha", data)
        got = prov.inspect(self.f)
        self.assertEqual((got["digital_source_type"].rsplit("/", 1)[1], got["tool"]), ("compositeSynthetic", "second"))

    def test_upstream_c2pa_is_kept_byte_for_byte(self):
        self.assertTrue(C2PA_JPEG.exists())
        f = TMP / "work" / "leo.jpg"
        shutil.copyfile(C2PA_JPEG, f)
        before = f.read_bytes()
        info = prov.mark(f, ["image"], "Leonardo.ai gpt-image-2")
        self.assertEqual(f.read_bytes(), before, "an XMP insert would break the manifest's hash binding")
        self.assertEqual((info["marked"], info["source_type"]), ("c2pa-upstream", "trainedAlgorithmicMedia"))
        got = prov.inspect(f)
        self.assertEqual((got["generated"], got["c2pa"], got["xmp"]), (True, True, False))

    def test_c2pa_without_ai_declaration_is_refused(self):
        jumbf = b"JP\x00\x01" + b"jumb....c2pa manifest without a source type"
        seg = b"\xff\xeb" + struct.pack(">H", 2 + len(jumbf)) + jumbf
        self.f.write_bytes(TINY_JPEG[:20] + seg + TINY_JPEG[20:])
        before = self.f.read_bytes()
        with self.assertRaises(prov.ProvenanceError):
            prov.mark(self.f, ["image"], "x")
        self.assertEqual(self.f.read_bytes(), before)
        self.assertFalse(prov.inspect(self.f)["generated"])

    def test_unmarked_file_is_not_generated(self):
        got = prov.inspect(self.f)
        self.assertEqual((got["generated"], got["xmp"], got["digital_source_type"]), (False, False, None))


class PngTest(unittest.TestCase):
    def test_round_trip_crc_and_position(self):
        f = TMP / "work" / "b.png"
        f.write_bytes(tiny_png())
        idat = [b for t, b, ok in png_chunks(tiny_png()) if t == b"IDAT"]
        prov.mark(f, "image", "Leonardo.ai gpt-image-2", composite=True)
        prov.mark(f, "image", "Leonardo.ai gpt-image-2", composite=True)          # idempotent
        chunks = png_chunks(f.read_bytes())
        self.assertTrue(all(ok for t, b, ok in chunks), "a chunk CRC is wrong")
        types = [t for t, b, ok in chunks]
        self.assertEqual(types, [b"IHDR", b"iTXt", b"IDAT", b"IEND"])
        self.assertEqual([b for t, b, ok in chunks if t == b"IDAT"], idat, "pixel data changed")
        self.assertTrue(chunks[1][1].startswith(b"XML:com.adobe.xmp\x00\x00\x00"))
        got = prov.inspect(f)
        self.assertEqual((got["generated"], got["digital_source_type"].rsplit("/", 1)[1]),
                         (True, "compositeSynthetic"))

    def test_compressed_foreign_xmp_is_read_and_replaced(self):
        f = TMP / "work" / "c.png"
        xmp = prov.xmp_packet(prov.TRAINED, ["image"], "old tool").encode()
        body = b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + zlib.compress(xmp)
        png = tiny_png()
        itxt = struct.pack(">I", len(body)) + b"iTXt" + body + struct.pack(">I", zlib.crc32(b"iTXt" + body) & 0xFFFFFFFF)
        f.write_bytes(png[:33] + itxt + png[33:])                                  # after IHDR
        self.assertEqual(prov.inspect(f)["tool"], "old tool")
        prov.mark(f, "image", "new tool")
        self.assertEqual(sum(1 for t, b, ok in png_chunks(f.read_bytes()) if t == b"iTXt"), 1)
        self.assertEqual(prov.inspect(f)["tool"], "new tool")


class FailureModesTest(unittest.TestCase):
    def test_unsupported_and_broken_files(self):
        for name, data in (("x.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "), ("x.txt", b"hello"), ("x.jpg", b"\xff\xd8\xff\xe0\x00"),
                           ("fake.mp4", b"\x00\x00\x00\x18ftypmp42 fake")):
            f = TMP / "work" / name
            f.write_bytes(data)
            with self.assertRaises(prov.ProvenanceError, msg=name):
                prov.mark(f, ["image"], "x")
            self.assertEqual(f.read_bytes(), data, f"{name} was modified")
            rec = prov.mark_safely(f, ["image"], "x", log=None)
            self.assertEqual((rec["generated"], rec["marked"]), (True, False))
            self.assertTrue(rec["error"])
        with self.assertRaises(prov.ProvenanceError):
            prov.mark(TMP / "work" / "missing.jpg", ["image"])
        with self.assertRaises(prov.ProvenanceError):
            prov.mark(TMP / "work" / "x.txt", ["hologram"])

    def test_real_photo_is_never_marked_by_propagation(self):
        """Template cards on the client's real photo (otto_render / otto_creative) are not AI media: propagate() only
        marks a derived file when its source carries an AI mark."""
        src, dst = TMP / "work" / "real.jpg", TMP / "work" / "card.jpg"
        src.write_bytes(TINY_JPEG); dst.write_bytes(TINY_JPEG)
        self.assertIsNone(prov.propagate(src, dst, log=None))
        self.assertFalse(prov.inspect(dst)["generated"])
        prov.mark(src, ["image"], "Leonardo.ai gpt-image-2")
        rec = prov.propagate(src, dst, log=None)
        self.assertEqual(rec["source_type"], "compositeSynthetic")
        self.assertEqual(prov.inspect(dst)["tool"], "Leonardo.ai gpt-image-2")


class Mp4StructureTest(unittest.TestCase):
    def test_xmp_uuid_box_appended_and_replaced(self):
        mdat = b"\x00" * 64
        data = (struct.pack(">I4s", 16, b"ftyp") + b"isom\x00\x00\x02\x00" + struct.pack(">I4s", 8 + len(mdat), b"mdat") + mdat)
        once = prov._mp4_write(data, lambda old: prov.xmp_packet(prov.COMPOSITE, ["voice"], "ElevenLabs", existing=old))
        self.assertEqual(once[:len(data)], data, "appending must not move a byte of the original boxes")
        twice = prov._mp4_write(once, lambda old: prov.xmp_packet(prov.COMPOSITE, ["voice"], "v2", existing=old))
        boxes = prov._mp4_boxes(twice)
        self.assertEqual([b[0] for b in boxes], [b"ftyp", b"mdat", b"uuid"])
        self.assertEqual(twice.count(prov.MP4_XMP_UUID), 1)
        self.assertEqual(prov.parse_xmp(prov._mp4_xmp(twice, boxes)[1])["tool"], "v2")


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
class Mp4Test(unittest.TestCase):
    def test_mark_voice_video_round_trip(self):
        f = make_mp4(TMP / "work" / "reel.mp4")
        info = prov.mark(f, ["voice"], "ElevenLabs eleven_multilingual_v2", composite=True)
        self.assertEqual(info["marked"], "xmp+mp4-tags+sidecar")
        got = prov.inspect(f)
        self.assertTrue(got["generated"])
        self.assertEqual((got["kinds"], got["digital_source_type"].rsplit("/", 1)[1]), (["voice"], "compositeSynthetic"))
        self.assertIn("compositeSynthetic", got["mp4_tags"]["comment"])
        self.assertIn("AI-generated voice", got["mp4_tags"]["description"])
        self.assertTrue(got["sidecar"]["sha256_ok"])
        side = json.loads(prov.sidecar_path(f).read_text())
        self.assertEqual((side["file"], side["kind"], side["law"]), ("reel.mp4", "voice", "EU AI Act Art. 50(2)"))
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, ""), "the marked file must still decode")
        prov.mark(f, ["voice", "image"], "again", composite=True)
        self.assertEqual(f.read_bytes().count(prov.MP4_XMP_UUID), 1)
        self.assertEqual(prov.inspect(f)["kinds"], ["voice", "image"])

    def test_cli_mark_and_inspect(self):
        f = make_mp4(TMP / "work" / "cli.mp4", audio=False)
        cli = [sys.executable, str(PLATFORM / "otto_provenance.py")]
        r = subprocess.run(cli + ["mark", str(f), "--kind", "voice,music", "--tool", "ElevenLabs + MusicGen", "--composite", "--json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["kinds"], ["voice", "music"])
        r = subprocess.run(cli + ["inspect", str(f), "--json"], capture_output=True, text=True)
        self.assertEqual((r.returncode, json.loads(r.stdout)["generated"]), (0, True))
        plain = TMP / "work" / "plain.jpg"
        plain.write_bytes(TINY_JPEG)
        self.assertEqual(subprocess.run(cli + ["inspect", str(plain)], capture_output=True).returncode, 1)
        self.assertEqual(subprocess.run(cli + ["mark", str(plain), "--kind", "nope"], capture_output=True).returncode, 2)

    def test_jpeg_conversion_for_instagram_keeps_the_mark(self):
        src = TMP / "assets" / "posts" / "conv.png"
        src.write_bytes(tiny_png(32, 32))
        prov.mark(src, ["image"], "Leonardo.ai gpt-image-2")
        ref = otto_paths.ensure_jpeg("assets/posts/conv.png")
        got = prov.inspect(otto_paths.local_path(ref))
        self.assertEqual((ref, got["generated"], got["digital_source_type"].rsplit("/", 1)[1]),
                         ("assets/posts/conv.jpg", True, "trainedAlgorithmicMedia"))


class GenvisualsTest(unittest.TestCase):
    def test_saved_image_is_marked_before_it_is_public_and_recorded(self):
        ai = {}
        ref = quiet(genvisuals.save_image, "al-001", TINY_JPEG, ai)
        self.assertRegex(ref, r"^assets/posts/al-001-[0-9a-f]{32}\.jpg$")                 # unguessable name (otto_paths.token_name)
        self.assertTrue(prov.inspect(TMP / "public" / "posts" / ref.rsplit("/", 1)[1])["generated"], "the public copy lacks the mark")
        self.assertEqual({k: ai[ref][k] for k in ("generated", "kind", "tool", "source_type", "marked")},
                         {"generated": True, "kind": "image", "tool": genvisuals.TOOL, "source_type": "trainedAlgorithmicMedia",
                          "marked": "xmp"})

    def test_run_records_media_ai_on_the_post(self):
        """The whole generation loop with Leonardo faked: fire → poll → download → save → patch."""
        add_post(id="al-002", format="post", hook="Een nieuwe week", status="draft")
        real_urlopen = urllib_request().urlopen

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/v1/generations/" in url:
                return Resp(json.dumps({"generations_by_pk": {"status": "COMPLETE",
                                        "generated_images": [{"url": "https://cdn.example/leo.jpg"}]}}).encode())
            if url == "https://cdn.example/leo.jpg":
                return Resp(TINY_JPEG)
            raise AssertionError(f"unexpected fetch {url}")
        saved = (genvisuals.key, genvisuals.post_json, genvisuals.time.sleep)
        genvisuals.key = lambda: "k"
        genvisuals.post_json = lambda u, body, k: {"generate": {"generationId": "g1"}}
        genvisuals.time.sleep = lambda s: None
        genvisuals.urllib.request.urlopen = fake_urlopen
        try:
            quiet(genvisuals.run, ids={"al-002"})
        finally:
            genvisuals.key, genvisuals.post_json, genvisuals.time.sleep = saved
            genvisuals.urllib.request.urlopen = real_urlopen
        p = ap.post(ap.load(), "al-002")
        self.assertRegex(p["image"], r"^assets/posts/al-002-[0-9a-f]{32}\.jpg$")
        rec = p["media_ai"][p["image"]]
        self.assertEqual((rec["generated"], rec["kind"], rec["tool"]), (True, "image", "Leonardo.ai gpt-image-2"))
        self.assertTrue(prov.inspect(otto_paths.local_path(p["image"]))["generated"])


def urllib_request():
    import urllib.request
    return urllib.request


class VideoTest(unittest.TestCase):
    def test_what_counts_as_synthetic_in_a_reel(self):
        d = TMP / "assets" / "reels" / "vx"
        d.mkdir(parents=True, exist_ok=True)
        leo, solid, photo = d / "s-aaa.jpg", d / "s-bbb-fb.jpg", d / "s-ccc-fb.jpg"
        for f in (leo, solid, photo):
            f.write_bytes(TINY_JPEG)
        self.assertTrue(otto_video.scene_is_ai(leo), "a Leonardo scene from the cache (even from before marking existed)")
        self.assertFalse(otto_video.scene_is_ai(solid), "a solid brand-colour fallback card")
        prov.mark(photo, ["image"], "Leonardo.ai gpt-image-2")
        self.assertTrue(otto_video.scene_is_ai(photo), "a fallback copy of an AI-marked post image")
        out = d / "none.mp4"
        out.write_bytes(b"")
        self.assertIsNone(otto_video.mark_reel(out, [solid], [None, None]), "nothing synthetic: no mark")

    @unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
    def test_render_marks_the_reel_and_records_it(self):
        add_post(id="al-003", format="reel", hook="Drie tips", caption="Eerste tip hier. Tweede tip hier.", status="draft")
        (TMP / "secrets" / "elevenlabs.json").write_text(json.dumps({"api_key": "x", "voice_id": "v", "model_id": "eleven_v3"}))
        scene = TMP / "assets" / "reels" / "al-003" / "s-abc.jpg"
        scene.parent.mkdir(parents=True, exist_ok=True)
        scene.write_bytes(TINY_JPEG)
        prov.mark(scene, ["image"], "Leonardo.ai gpt-image-2")
        vo = TMP / "assets" / "reels" / "al-003" / "v-1.mp3"
        vo.write_bytes(b"ID3")
        saved = (otto_video.scene_images, otto_video.voice_over, otto_video.assemble)
        otto_video.scene_images = lambda p, script, dry: [scene] * len(script)
        otto_video.voice_over = lambda script, out_dir, voice=True: [vo] + [None] * (len(script) - 1)
        otto_video.assemble = lambda scenes, vos, out, color, work: (make_mp4(out), 3.0)
        try:
            quiet(otto_video.render, "al-003")
        finally:
            otto_video.scene_images, otto_video.voice_over, otto_video.assemble = saved
        p = ap.post(ap.load(), "al-003")
        self.assertRegex(p["video"], r"^assets/reels/al-003-[0-9a-f]{32}\.mp4$")         # unguessable name (otto_paths.token_name)
        rec = p["media_ai"][p["video"]]
        self.assertEqual((rec["kind"], rec["kinds"], rec["source_type"]), ("voice", ["image", "voice"], "compositeSynthetic"))
        self.assertEqual(rec["tool"], "Leonardo.ai gpt-image-2 + ElevenLabs eleven_v3")
        pub = TMP / "public" / "reels" / p["video"].rsplit("/", 1)[1]
        self.assertTrue(prov.inspect(pub)["generated"], "the public copy lacks the mark")
        self.assertTrue(pub.with_name(pub.name + ".provenance.json").exists())


class MotionTest(unittest.TestCase):
    def _project(self, pid, meta, voice=None):
        add_post(id=pid, format="reel", status="draft", **({"motion": {"voice": voice}} if voice else {}))
        pdir = otto_motion.project_dir(ap.load(), ap.post(ap.load(), pid))
        (pdir / "compositions" / "frames").mkdir(parents=True, exist_ok=True)
        (pdir / "compositions" / "frames" / "01.html").write_text("<div></div>")
        (pdir / "index.html").write_text("<html></html>")
        (pdir / "audio_engine_meta.json").write_text(json.dumps(meta))
        (pdir / "renders").mkdir(exist_ok=True)
        return pdir

    def test_synthetic_parts(self):
        meta = {"bgm_pending": False, "voices": [{"id": "01"}], "bgm": {"path": "assets/bgm/track.wav"}}
        pdir = self._project("al-010", meta)
        self.assertEqual(otto_motion.synthetic_parts(ap.post(ap.load(), "al-010"), pdir),
                         (["voice", "music"], "ElevenLabs via Higgsfield + MusicGen"))
        pdir = self._project("al-011", meta, voice="human")
        self.assertEqual(otto_motion.synthetic_parts(ap.post(ap.load(), "al-011"), pdir), (["music"], "MusicGen"))
        pdir = self._project("al-012", {"bgm_pending": False})
        self.assertEqual(otto_motion.synthetic_parts(ap.post(ap.load(), "al-012"), pdir), ([], ""))

    @unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
    def test_finish_marks_before_publishing(self):
        pdir = self._project("al-013", {"bgm_pending": False, "voices": [{"id": "01"}], "bgm": {"path": "x.wav"}})
        make_mp4(pdir / "renders" / "video.mp4")
        saved = (otto_motion.sh, otto_motion._dur)
        otto_motion.sh = lambda cmd, cwd=None, check=True, both=False: ""       # node / npx HyperFrames stubbed
        otto_motion._dur = lambda f: 1.0
        try:
            quiet(otto_motion.finish, "al-013")
        finally:
            otto_motion.sh, otto_motion._dur = saved
        p = ap.post(ap.load(), "al-013")
        self.assertRegex(p["video"], r"^assets/reels/al-013-[0-9a-f]{32}\.mp4$")
        rec = p["media_ai"][p["video"]]
        self.assertEqual((p["status"], rec["kind"], rec["kinds"], bool(rec["marked"])), ("pending_approval", "voice", ["voice", "music"], True))
        self.assertTrue(prov.inspect(TMP / "public" / "reels" / p["video"].rsplit("/", 1)[1])["generated"])

    def test_unmarkable_render_still_attaches_and_says_so(self):
        """A broken file never stops the pipeline; the record says marked=false so the console can flag it."""
        pdir = self._project("al-014", {"bgm_pending": False, "voices": [{"id": "01"}]})
        (pdir / "renders" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
        saved = (otto_motion.sh, otto_motion._dur)
        otto_motion.sh = lambda cmd, cwd=None, check=True, both=False: ""
        otto_motion._dur = lambda f: 12.0
        try:
            quiet(otto_motion.finish, "al-014")
        finally:
            otto_motion.sh, otto_motion._dur = saved
        p = ap.post(ap.load(), "al-014")
        self.assertRegex(p["video"], r"^assets/reels/al-014-[0-9a-f]{32}\.mp4$")
        rec = p["media_ai"][p["video"]]
        self.assertEqual((rec["generated"], rec["marked"]), (True, False))


if __name__ == "__main__":
    unittest.main()
