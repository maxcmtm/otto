#!/usr/bin/env python3
"""Unguessable media names (otto_paths): token_name / record_token / media_token, the publish guard (a generated file under
assets/posts|ads|reels is never made public under a guessable name), producers naming with the record's token (genvisuals,
otto_creative), stored legacy refs that still resolve, and the one-off `otto_paths.py migrate-names` (dry by default; files
renamed locally and publicly with their twins and sidecars, data.json and brands/<id>/*.json updated through ap.transaction,
idempotent). Stdlib unittest, no network, nothing outside a throwaway workspace.

  cd platform && python3 tests/test_media_names.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, os, re, shutil, sys, tempfile, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-media-names-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public")}
BASE = "https://otto.example/"
HEX = re.compile(r"-[0-9a-f]{32}\.")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
_SAVED = {}


def quiet(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        res = fn(*a, **kw)
    quiet.out = out.getvalue()
    return res


def write(p, data=b"x"):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p


def seed():
    return {"brands": [{"id": "hg", "name": "Happy", "url": "happy.example", "status": "active", "plan": "starter"}],
            "posts": [{"id": "hg-001", "brand": "hg", "status": "draft", "image": "assets/posts/hg-001.jpg",
                       "images": ["assets/posts/hg-001-1.jpg", "assets/posts/hg-001-2.jpg"], "video": "assets/reels/hg-001.mp4",
                       "media_ai": {"assets/posts/hg-001.jpg": {"generated": True}, "assets/reels/hg-001.mp4": {"generated": True}}},
                      {"id": "hg-002", "brand": "hg", "status": "published", "image": BASE + "assets/posts/hg-002.jpg"},
                      {"id": "hg-003", "brand": "hg", "status": "draft", "image": "assets/posts/hg-003.jpg"},     # no file anywhere
                      {"id": "hg-004", "brand": "hg", "status": "draft", "video": "assets/reels/hg-spectrum-guide.mp4"}],  # landing's
            "campaigns": [{"id": "cp-001", "brand": "hg", "status": "live",
                           "creatives": {"images": [{"file": "assets/ads/cp-001-1-static.jpg"}],
                                         "remote": {"url": BASE + "assets/ads/cp-001-1-static.jpg"}}}],
            "recommendations": [], "connections": []}


def reset():
    for x in list(TMP.iterdir()):
        shutil.rmtree(x) if x.is_dir() else x.unlink()
    (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    for rel in ("posts/hg-001.jpg", "posts/hg-001.png", "posts/hg-001-1.jpg", "posts/hg-001-2.jpg", "reels/hg-001.mp4",
                "reels/hg-001.mp4.provenance.json", "ads/cp-001-1-static.jpg", "reels/hg-spectrum-guide.mp4"):
        write(TMP / "assets" / rel, rel)
        write(TMP / "public" / rel, rel)
    write(TMP / "public" / "posts" / "hg-002.jpg", "published only")          # public copy only (no local file)
    write(TMP / "public" / "posts" / "orphan.jpg", "nobody names it")
    write(TMP / "brands" / "hg" / "ads-2026-10.json", json.dumps({"angles": [{"ads": [{"id": "a1", "file": "assets/ads/cp-001-1-static.jpg"}]}]}))


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_paths, genvisuals, otto_creative
    import ap, otto_paths, genvisuals, otto_creative   # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, otto_paths.BASE, genvisuals.OUT)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_paths.ASSETS, otto_paths.BASE, genvisuals.OUT = TMP / "assets", BASE, TMP / "assets" / "posts"
    reset()


def tearDownModule():
    (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, otto_paths.BASE, genvisuals.OUT) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def post(pid):
    return ap.post(ap.load(), pid)


class NamingTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_token_name(self):
        t = otto_paths.new_token()
        self.assertRegex(t, r"^[0-9a-f]{32}$")
        self.assertNotEqual(t, otto_paths.new_token())
        n = otto_paths.token_name("hg-001", ".jpg", t)
        self.assertRegex(n, r"^hg-001-[0-9a-f]{32}\.jpg$")
        self.assertNotIn(t, n, "the record token itself is never in a file name")
        self.assertEqual(n, otto_paths.token_name("hg-001", ".jpg", t))                 # a re-render keeps its name
        self.assertEqual(n[:-4], otto_paths.token_name("hg-001", ".png", t)[:-4])       # twins share the stem
        self.assertNotEqual(n[7:], otto_paths.token_name("hg-001-1", ".jpg", t)[9:])    # siblings are unrelated
        self.assertNotEqual(n, otto_paths.token_name("hg-001", ".jpg", otto_paths.new_token()))
        self.assertEqual(otto_paths.token_name(n[:-4] + "-poster", ".jpg", t), n[:-4] + "-poster.jpg")
        self.assertRegex(otto_paths.token_name("x", ".jpg"), r"^x-[0-9a-f]{32}\.jpg$")   # no record: a random one
        self.assertTrue(otto_paths.guessable("assets/posts/hg-001.jpg"))
        self.assertFalse(otto_paths.guessable("assets/posts/" + n))
        self.assertFalse(otto_paths.guessable("assets/reels/" + n[:-4] + ".mp4.provenance.json"))
        self.assertFalse(otto_paths.guessable("assets/site/hg/logo.png"))
        self.assertFalse(otto_paths.guessable("assets/landing/hg-001-640.webp"))

    def test_record_and_media_token(self):
        rec = {"id": "x"}
        t = otto_paths.record_token(rec)
        self.assertEqual((rec["media_token"], otto_paths.record_token(rec)), (t, t))
        fb = otto_paths.new_token()
        self.assertEqual(otto_paths.record_token({}, fb), fb)
        t1 = quiet(otto_paths.media_token, "post", "hg-001")
        self.assertEqual(post("hg-001")["media_token"], t1)
        self.assertEqual(quiet(otto_paths.media_token, "post", "hg-001"), t1)
        tc = quiet(otto_paths.media_token, "campaign", "cp-001")
        self.assertEqual(ap.campaign(ap.load(), "cp-001")["media_token"], tc)
        self.assertRegex(quiet(otto_paths.media_token, "post", "nope"), r"^[0-9a-f]{32}$")

    def test_publish_refuses_a_guessable_name(self):
        write(TMP / "assets" / "posts" / "new.jpg")
        with self.assertRaises(otto_paths.AssetError):
            otto_paths.publish(TMP / "assets" / "posts" / "new.jpg")
        self.assertFalse((TMP / "public" / "posts" / "new.jpg").exists())
        saved = os.environ["OTTO_PUBLIC_ASSETS"]
        os.environ["OTTO_PUBLIC_ASSETS"] = ""                   # no public dir (local dev): still refused
        try:
            with self.assertRaises(otto_paths.AssetError):
                otto_paths.publish("assets/ads/new.jpg")
        finally:
            os.environ["OTTO_PUBLIC_ASSETS"] = saved
        good = write(TMP / "assets" / "posts" / otto_paths.token_name("new", ".jpg"))
        self.assertTrue(otto_paths.publish(good).exists())
        self.assertTrue(otto_paths.publish("assets/posts/new.jpg", legacy=True).exists())   # a stored legacy ref
        write(TMP / "assets" / "site" / "hg" / "logo.png")
        self.assertTrue(otto_paths.publish("assets/site/hg/logo.png").exists())

    def test_old_refs_still_resolve_and_new_ones_are_public(self):
        (TMP / "public" / "posts" / "hg-001.jpg").unlink()
        url = otto_paths.media_url("assets/posts/hg-001.jpg", base=BASE)                            # legacy: copied on demand
        self.assertEqual(url, BASE + "assets/posts/hg-001.jpg")
        self.assertTrue((TMP / "public" / "posts" / "hg-001.jpg").exists())
        ref = quiet(genvisuals.save_image, "hg-005", JPEG)
        self.assertRegex(ref, r"^assets/posts/hg-005-[0-9a-f]{32}\.jpg$")
        self.assertEqual(otto_paths.media_url(ref, base=BASE), BASE + ref)                            # what Meta fetches
        self.assertTrue((TMP / "public" / ref[len("assets/"):]).exists())
        self.assertFalse((TMP / "public" / "posts" / "hg-005.jpg").exists())
        self.assertEqual(quiet(genvisuals.save_image, "hg-001", JPEG), quiet(genvisuals.save_image, "hg-001", JPEG))

    def test_genvisuals_failing_everything_exits_non_zero(self):
        # regression (integration review): every Leonardo call failing (revoked key, outage) printed "ERR" and exited 0, so the
        # scheduler's heartbeat said ok and no alert went out
        with ap.transaction(sync=False) as d:
            ap.add_post(d, "hg", "A", "ig", "2031-01-01T09:00", "needs a picture")
        real = (genvisuals.post_json, genvisuals.key, genvisuals.time.sleep)
        genvisuals.post_json = lambda *a, **kw: (_ for _ in ()).throw(OSError("HTTP Error 401: Unauthorized"))
        genvisuals.key, genvisuals.time.sleep = (lambda: "k"), (lambda s: None)
        try:
            self.assertEqual(quiet(genvisuals.main, ["--brand", "hg", "--limit", "1"]), 1)
            self.assertEqual(quiet(genvisuals.main, ["--brand", "hg", "--limit", "1", "--dry"]), 0)
            self.assertEqual(quiet(genvisuals.main, ["--brand", "nobody"]), 0, "nothing to generate is not a failure")
        finally:
            genvisuals.post_json, genvisuals.key, genvisuals.time.sleep = real

    def test_campaign_files_share_one_recorded_token(self):
        c = {"id": "cp-009", "brand": "hg"}
        nm = otto_creative._namer(c)
        a, b = nm("cp-009-1-static", ".jpg"), nm("cp-009-1-c1", ".jpg")
        self.assertRegex(a, r"^cp-009-1-static-[0-9a-f]{32}\.jpg$")
        self.assertEqual(otto_creative._namer({"id": "cp-009", "creatives": {"media_token": c["media_token"]}})("cp-009-1-static", ".jpg"), a)
        self.assertEqual(otto_creative._namer(c)("cp-009-1-c1", ".jpg"), b)            # the launch names what the dry plan named


class MigrationTest(unittest.TestCase):
    def setUp(self):
        reset()

    def listing(self):
        return {r: sorted(str(p.relative_to(TMP / r)) for p in (TMP / r).rglob("*") if p.is_file()) for r in ("assets", "public")}

    def test_dry_run_changes_nothing(self):
        before, data = self.listing(), (TMP / "data.json").read_text()
        plan = quiet(otto_paths.migrate)
        self.assertEqual((self.listing(), (TMP / "data.json").read_text()), (before, data))
        refs = {r["ref"] for r in plan["renames"]}
        self.assertEqual(refs, {"assets/posts/hg-001.jpg", "assets/posts/hg-001-1.jpg", "assets/posts/hg-001-2.jpg",
                                "assets/reels/hg-001.mp4", "assets/posts/hg-002.jpg", "assets/ads/cp-001-1-static.jpg"})
        self.assertEqual({s["ref"]: s["why"] for s in plan["skipped"]},
                         {"assets/posts/hg-003.jpg": "no local or public copy",
                          "assets/reels/hg-spectrum-guide.mp4": "used by a page shipped with the release"})
        self.assertEqual(plan["unreferenced"], ["assets/posts/orphan.jpg"])
        self.assertIn("would rename assets/posts/hg-001.jpg", quiet.out)

    def test_apply_renames_files_and_refs(self):
        plan = quiet(otto_paths.migrate, apply=True)
        p1, p2 = post("hg-001"), post("hg-002")
        tok = p1["media_token"]
        self.assertEqual(p1["image"], "assets/posts/" + otto_paths.token_name("hg-001", ".jpg", tok))
        self.assertEqual(p1["images"], ["assets/posts/" + otto_paths.token_name(f"hg-001-{i}", ".jpg", tok) for i in (1, 2)])
        self.assertEqual(p1["video"], "assets/reels/" + otto_paths.token_name("hg-001", ".mp4", tok))
        self.assertEqual(sorted(p1["media_ai"]), sorted([p1["image"], p1["video"]]))        # keys follow
        self.assertRegex(p2["image"], r"^https://otto\.example/assets/posts/hg-002-[0-9a-f]{32}\.jpg$")   # full URLs follow
        self.assertEqual(post("hg-003")["image"], "assets/posts/hg-003.jpg")
        self.assertEqual(post("hg-004")["video"], "assets/reels/hg-spectrum-guide.mp4")
        c = ap.campaign(ap.load(), "cp-001")
        new_ad = c["creatives"]["images"][0]["file"]
        self.assertEqual(new_ad, "assets/ads/" + otto_paths.token_name("cp-001-1-static", ".jpg", c["media_token"]))
        self.assertEqual(c["creatives"]["remote"]["url"], BASE + new_ad)
        mx = json.loads((TMP / "brands" / "hg" / "ads-2026-10.json").read_text())
        self.assertEqual(mx["angles"][0]["ads"][0]["file"], new_ad)
        after = self.listing()
        for root in ("assets", "public"):
            names = after[root]
            self.assertFalse([n for n in names if n in ("posts/hg-001.jpg", "posts/hg-001.png", "posts/hg-001-1.jpg",
                                                        "reels/hg-001.mp4", "reels/hg-001.mp4.provenance.json", "ads/cp-001-1-static.jpg")],
                             f"{root}: an old name is still there")
            self.assertIn(p1["image"][len("assets/"):], names)
            self.assertIn(p1["image"][len("assets/"):-4] + ".png", names)                     # the twin, same new stem
            self.assertIn(p1["video"][len("assets/"):] + ".provenance.json", names)           # the sidecar follows
            self.assertIn("reels/hg-spectrum-guide.mp4", names)
        self.assertIn("posts/" + p2["image"].rsplit("/", 1)[1], after["public"])
        self.assertIn("posts/orphan.jpg", after["public"])
        self.assertEqual((TMP / "public" / p1["image"][len("assets/"):]).read_text(), "posts/hg-001.jpg")   # same bytes
        self.assertEqual(otto_paths.media_url(p1["image"], base=BASE), BASE + p1["image"])
        self.assertIn("paths migrate-names 6 refs", (TMP / "actions.log").read_text())
        # the producers name the same file the same way from now on
        self.assertEqual(quiet(genvisuals.save_image, "hg-001", JPEG), p1["image"])
        # idempotent
        again = quiet(otto_paths.migrate, apply=True)
        self.assertEqual((again["renames"], again["moves"]), ([], []))
        self.assertEqual(len(plan["renames"]), 6)


if __name__ == "__main__":
    unittest.main()
