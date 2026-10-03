#!/usr/bin/env python3
"""Otto images through the Higgsfield Cloud API (otto_imagegen) against a fake Higgsfield (tests/fake_higgsfield.py,
127.0.0.1 — no network, no real key): the config (file, HIGGSFIELD_KEY, the 127.0.0.1-only base override, model aliases),
the request shapes (Authorization: Key id:secret, Idempotency-Key, the GPT Image 2 body, the key never sent to the CDN, the
upload URL or a foreign status URL), submit → poll → complete / failed / nsfw / timeout (a queued request is canceled),
429 / concurrency / 5xx backoff with Retry-After and the same Idempotency-Key, the download check, reference uploads,
the daily caps and the usage ledger, no secret or prompt in any output, the CLI, and the provider order in genvisuals (post
visuals) and otto_video (reel scenes): Higgsfield first, Leonardo as the fallback, then the post's own picture.

  cd platform && python3 tests/test_imagegen.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, os, re, shutil, sys, tempfile, threading, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_higgsfield as FH                                                    # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="otto-imagegen-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_IMAGEGEN_LEDGER": str(TMP / "imagegen-usage.json")}
CLEAR = ("HIGGSFIELD_KEY", "OTTO_IMAGEGEN", "OTTO_HIGGSFIELD_API_BASE", "LEONARDO_API_KEY")
SECRET_PROMPT = "Bakkerij Geheim at Prinsengracht 12 — the owner's new sourdough"
_SAVED, S = {}, {}


def quiet(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            return fn(*a, **kw)
        finally:
            quiet.out = out.getvalue()


def set_cfg(**extra):
    cfg = {"key_id": FH.KEY_ID, "key_secret": FH.KEY_SECRET, "image_model": "gpt-image-2", "scene_model": "gpt-image-2"}
    cfg.update(extra)
    (TMP / "secrets" / "higgsfield.json").write_text(json.dumps(cfg))


def no_cfg():
    f = TMP / "secrets" / "higgsfield.json"
    if f.exists():
        f.unlink()


def ledger():
    f = TMP / "imagegen-usage.json"
    return json.loads(f.read_text()) if f.exists() else {}


def today(brand=None):
    days = ledger().get("days") or {}
    day = days[sorted(days)[-1]] if days else {}
    return (day.get("brands") or {}).get(brand, {}) if brand else day


def add_post(**fields):
    with ap.transaction(sync=False) as d:
        p = dict({"brand": "alpha", "pillar": "A", "platform": "ig", "hook": "h", "status": "draft",
                  "slot": "2031-01-01T09:00"}, **fields)
        d["posts"] = [x for x in d["posts"] if x["id"] != p["id"]] + [p]
    return p


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, ig, prov, otto_paths, genvisuals, otto_video, otto_admin
    import ap, otto_imagegen as ig, otto_provenance as prov, otto_paths, genvisuals, otto_video, otto_admin   # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, genvisuals.OUT, genvisuals.BRANDS, otto_video.REELS,
                       otto_video.SECRETS, otto_video.BRANDS)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_paths.ASSETS = TMP / "assets"
    genvisuals.OUT, genvisuals.BRANDS = TMP / "assets" / "posts", TMP / "brands"
    otto_video.REELS, otto_video.SECRETS, otto_video.BRANDS = TMP / "assets" / "reels", TMP / "secrets", TMP / "brands"
    for d in ("brands/alpha", "secrets", "assets/posts", "assets/reels", "public", "work"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    (TMP / "data.json").write_text(json.dumps({"brands": [{"id": "alpha", "name": "Alpha", "url": "alpha.nl", "status": "active",
                                                           "countries": ["NL"], "pillars": ["A"]}],
                                               "posts": [], "recommendations": [], "campaigns": []}))
    S["fake"] = FH.FakeHiggsfield()
    os.environ["OTTO_HIGGSFIELD_API_BASE"] = S["fake"].base


def tearDownModule():
    S["fake"].close()
    (ap.DATA, ap.HTML, ap.BRANDS, otto_paths.ASSETS, genvisuals.OUT, genvisuals.BRANDS, otto_video.REELS,
     otto_video.SECRETS, otto_video.BRANDS) = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = S["fake"]
        self.fake.reset()
        os.environ["OTTO_HIGGSFIELD_API_BASE"] = self.fake.base
        for k in ("HIGGSFIELD_KEY", "OTTO_IMAGEGEN", "LEONARDO_API_KEY"):
            os.environ.pop(k, None)
        set_cfg()
        f = TMP / "imagegen-usage.json"
        if f.exists():
            f.unlink()
        # a fake clock: no test waits for real backoff or polling
        self.t, self.sleeps, lock = [1000.0], [], threading.Lock()

        def sleep(s):
            with lock:
                self.sleeps.append(round(s, 2))
                self.t[0] += s
        self._real = (ig.SLEEP, ig.CLOCK)
        ig.SLEEP, ig.CLOCK = sleep, (lambda: self.t[0])

    def tearDown(self):
        ig.SLEEP, ig.CLOCK = self._real

    def submits(self):
        return self.fake.submissions()


class ConfigTest(Base):
    def test_file_env_and_aliases(self):
        cfg = ig.config()
        self.assertTrue(ig.ready(cfg))
        self.assertEqual((cfg["key_source"], cfg["image_model"], cfg["scene_model"]), ("file", "marketing-studio/image", "marketing-studio/image"))
        self.assertEqual((cfg["quality"], cfg["scene_quality"], cfg["cli_quality"], cfg["resolution"]), ("medium", "medium", "high", "2k"))
        self.assertEqual(ig.tool_name(cfg["image_model"]), "Higgsfield gpt-image-2")
        self.assertNotIn(FH.KEY_SECRET, json.dumps(ig.public(cfg)))
        self.assertNotIn(FH.KEY_ID, json.dumps(ig.public(cfg)))
        os.environ["HIGGSFIELD_KEY"] = "envid:envsecret"
        try:
            cfg = ig.config()
            self.assertEqual((cfg["key_id"], cfg["key_secret"], cfg["key_source"]), ("envid", "envsecret", "env"))
            os.environ["HIGGSFIELD_KEY"] = "no-colon-here"                    # malformed: the file's key stays
            self.assertEqual(ig.config()["key_source"], "file")
        finally:
            os.environ.pop("HIGGSFIELD_KEY")
        set_cfg(image_model="dall-e-9", scene_model="z-image-turbo")
        cfg = ig.config()
        self.assertEqual((cfg["image_model"], cfg["scene_model"]), ("marketing-studio/image", "z-image/turbo"))
        self.assertTrue(any("dall-e-9" in w for w in cfg["warnings"]))

    def test_not_ready_without_a_whole_key_or_when_off(self):
        set_cfg(key_secret="")
        cfg = ig.config()
        self.assertFalse(ig.ready(cfg))
        self.assertIn("key_id and key_secret", cfg["error"])
        set_cfg(key_id=None, key_secret=None, key=f"{FH.KEY_ID}:{FH.KEY_SECRET}")       # {"key": "id:secret"} works too
        self.assertTrue(ig.ready())
        set_cfg(enabled=False)
        self.assertFalse(ig.ready())
        set_cfg()
        os.environ["OTTO_IMAGEGEN"] = "off"
        try:
            self.assertFalse(ig.ready())
            with self.assertRaises(ig.NotConfigured):
                quiet(ig.render, "a cat", cfg=ig.config())
        finally:
            os.environ.pop("OTTO_IMAGEGEN")
        (TMP / "secrets" / "higgsfield.json").write_text("{not json")
        self.assertEqual(ig.config()["error"], "higgsfield.json is not valid JSON")
        no_cfg()
        self.assertFalse(ig.ready())

    def test_the_base_override_is_only_honoured_for_127_0_0_1(self):
        for bad in ("https://evil.example", "http://localhost:8080", "http://127.0.0.1", "http://127.0.0.1:80/x",
                    "https://api.higgsfield.ai.evil.example"):
            os.environ["OTTO_HIGGSFIELD_API_BASE"] = bad
            self.assertEqual(ig.config()["api_base"], ig.API_BASE, bad)
        os.environ["OTTO_HIGGSFIELD_API_BASE"] = "http://127.0.0.1:8123/"
        self.assertEqual(ig.config()["api_base"], "http://127.0.0.1:8123")

    def test_only_higgsfield_hosts_get_the_key(self):
        real = dict(ig.config(), api_base=ig.API_BASE)
        for ok in ("https://api.higgsfield.ai/requests/x/status", "https://platform.higgsfield.ai/requests/x/status"):
            self.assertTrue(ig._trusted(ok, real), ok)
        for bad in ("http://platform.higgsfield.ai/requests/x", "https://higgsfield.ai.evil.example/x", "https://evil.example/x",
                    "https://d3u0tzju9qaucj.cloudfront.net/a.png", f"{self.fake.base}/requests/x/status"):
            self.assertFalse(ig._trusted(bad, real), bad)

    def test_aspects_and_bodies(self):
        self.assertEqual(ig.aspect_for("gpt-image-2", "4:5"), "3:4")              # GPT Image 2's nearest to Instagram's 4:5
        self.assertEqual(ig.aspect_for("gpt-image-2", "story"), "9:16")
        self.assertEqual(ig.aspect_for("gpt-image-2", (1080, 1920)), "9:16")
        self.assertEqual(ig.aspect_for("gpt-image-2", "1080x1350"), "3:4")
        self.assertEqual(ig.aspect_for("z-image/turbo", "4:5"), "7:9")
        with self.assertRaises(ig.InvalidRequest):
            ig.aspect_for("gpt-image-2", "tall")
        b = ig.build_body("gpt-image-2", "a cat", "9:16", "medium", "2k")
        self.assertEqual(b, {"prompt": "a cat", "aspect_ratio": "9:16", "resolution": "2k", "quality": "medium", "enhance_prompt": False})
        with self.assertRaises(ig.InvalidRequest):
            ig.build_body("z-image/turbo", "a cat", "1:1", None, "1k", ["https://x.example/a.png"])     # no references
        with self.assertRaises(ig.InvalidRequest):
            ig.build_body("gpt-image-2", "x" * 5001, "1:1", "low", "1k")
        with self.assertRaises(ig.InvalidRequest):
            ig.build_body("gpt-image-2", "a cat", "1:1", "ultra", "1k")
        self.assertEqual(ig.price_guess("gpt-image-2", "3:4", "medium", "2k"), 0.076)
        self.assertEqual(ig.price_guess("gpt-image-2", "1:1", "low", "1k"), 0.014)


class FlowTest(Base):
    def test_submit_poll_download_with_the_right_headers(self):
        res = quiet(ig.render, "a red ceramic cup", "1:1", brand="alpha", purpose="post")
        self.assertEqual(res["images"][0], (self.fake.image, "png"))
        self.assertEqual((res["label"], res["tool"], res["aspect"], res["quality"], res["resolution"], res["usd"]),
                         ("gpt-image-2", "Higgsfield gpt-image-2", "1:1", "medium", "2k", 0.076))
        sub, = self.submits()
        self.assertEqual(sub["path"], "/marketing-studio/image")
        self.assertEqual(sub["headers"]["authorization"], f"Key {FH.KEY_ID}:{FH.KEY_SECRET}")
        self.assertRegex(sub["headers"]["idempotency-key"], r"^[0-9a-f-]{36}$")
        self.assertEqual(sub["headers"]["content-type"], "application/json")
        self.assertEqual(sub["body"], {"prompt": "a red ceramic cup", "aspect_ratio": "1:1", "resolution": "2k", "quality": "medium",
                                       "enhance_prompt": False})
        est, = self.fake.calls("/estimate/marketing-studio/image")
        self.assertEqual(est["body"], sub["body"], "the estimate prices exactly what is submitted")
        polls = self.fake.calls("/requests/", "GET")
        self.assertEqual(len(polls), 3)                                           # queued → in_progress → completed
        self.assertTrue(all(p["headers"]["authorization"].startswith("Key ") for p in polls))
        cdn, = self.fake.calls("/cdn/")
        self.assertNotIn("authorization", cdn["headers"], "the key never goes to the CDN")
        self.assertEqual(self.sleeps[:3], sorted(self.sleeps[:3]), "polling backs off")
        self.assertTrue(2.0 <= self.sleeps[0] <= 2.5)
        day = today()
        self.assertEqual((day["images"], day["usd"], day["errors"]), (1, 0.076, 0))
        self.assertEqual(today("alpha")["images"], 1)
        self.assertEqual(day["models"]["gpt-image-2"]["images"], 1)
        last = ledger()["last"]["alpha"]
        self.assertEqual((last["outcome"], last["purpose"], last["request_id"]), ("ok", "post", res["request_id"]))

    def test_failed_and_nsfw_are_refunded_in_the_ledger(self):
        self.fake.script = ["in_progress", "failed"]
        with self.assertRaises(ig.GenerationFailed) as c:
            quiet(ig.render, "a cup", brand="alpha")
        self.assertIn("not charged", str(c.exception))
        self.assertTrue(c.exception.request_id)
        self.assertEqual((today()["images"], today()["usd"], today()["errors"]), (0, 0.0, 1))
        self.fake.script = ["nsfw"]
        with self.assertRaises(ig.ContentRejected):
            quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual((today()["images"], today()["nsfw"]), (0, 1))

    def test_a_request_still_queued_at_the_deadline_is_canceled(self):
        set_cfg(timeout_s=30)
        self.fake.script = ["queued"] * 500
        with self.assertRaises(ig.GenerationTimeout) as c:
            quiet(ig.render, "a cup", brand="alpha")
        self.assertIn("canceled, not charged", str(c.exception))
        self.assertEqual(len(self.fake.calls("/requests/", "POST")), 1, "one cancel call")
        self.assertEqual(today()["images"], 0)

    def test_a_request_in_progress_at_the_deadline_keeps_its_claim(self):
        set_cfg(timeout_s=30)
        self.fake.script = ["in_progress"] * 500
        with self.assertRaises(ig.GenerationTimeout) as c:
            quiet(ig.render, "a cup", brand="alpha")
        self.assertIn("may still finish", str(c.exception))
        self.assertFalse(self.fake.calls("/requests/", "POST"), "an in-progress request cannot be canceled")
        self.assertEqual((today()["images"], today()["errors"]), (1, 1), "it may still be billed")
        self.assertLessEqual(max(self.sleeps), 10.6, "polling caps at 10 s (+ jitter)")

    def test_429_honours_retry_after_and_reuses_the_idempotency_key(self):
        self.fake.replies = [("error", 429, "Too many requests", {"Retry-After": "7"}), ("concurrency",)]
        res = quiet(ig.render, "a cup", brand="alpha")
        subs = self.submits()
        self.assertEqual(len(subs), 3)
        self.assertEqual(len({s["headers"]["idempotency-key"] for s in subs}), 1, "one generation intent, one key")
        self.assertEqual(len(self.fake.requests), 1, "and one request on Higgsfield's side")
        self.assertEqual(self.sleeps[0], 7.0, "Retry-After honoured")
        self.assertGreaterEqual(self.sleeps[1], 4.0, "the concurrency 400 waits for a slot")
        self.assertEqual(res["images"][0][1], "png")

    def test_5xx_is_retried_then_given_up(self):
        self.fake.replies = [("error", 502, "bad gateway")] * 2
        quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual(len(self.submits()), 3)
        self.fake.reset()
        self.fake.replies = [("error", 500, "boom")] * 9
        with self.assertRaises(ig.ServerError):
            quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual(len(self.submits()), 5, "retries (4) + 1")
        self.assertEqual(today()["images"], 1, "the failed one was never accepted: given back")
        self.fake.reset()
        self.fake.replies = [("error", 503, "Model is not ready")] * 9
        with self.assertRaises(ig.ModelUnavailable):
            quiet(ig.render, "a cup", brand="alpha")

    def test_errors_that_are_not_retried(self):
        self.fake.replies = [("error", 403, "Not enough credits")]
        with self.assertRaises(ig.CreditsError):
            quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual(len(self.submits()), 1)
        self.fake.replies = [("error", 422, "Idempotency-Key was already used with different request parameters")]
        with self.assertRaises(ig.InvalidRequest):
            quiet(ig.render, "a cup", brand="alpha")
        set_cfg(key_secret="wrong-secret-value")
        self.fake.reset()
        with self.assertRaises(ig.AuthError) as c:
            quiet(ig.render, "a cup", brand="alpha")
        self.assertIn("key was refused", str(c.exception))
        self.assertNotIn("wrong-secret-value", str(c.exception))
        self.assertEqual(len(self.fake.log), 1, "a refused key stops at the (free) estimate: nothing is submitted")
        self.assertEqual(today()["images"], 0)

    def test_status_poll_errors_are_transient(self):
        self.fake.status_errors = [(500, "boom"), (502, "bad gateway")]
        res = quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual(res["images"][0][1], "png")

    def test_a_foreign_status_url_never_gets_the_key(self):
        self.fake.status_url_origin = "http://127.0.0.1:9"                         # not the configured base
        res = quiet(ig.render, "a cup", brand="alpha")
        self.assertEqual(res["images"][0][1], "png", "polled the base's own /requests/<id>/status instead")
        self.assertTrue(self.fake.calls(f"/requests/{res['request_id']}/status", "GET"))

    def test_download_is_checked(self):
        self.fake.image = b"<html>not an image</html>"
        with self.assertRaises(ig.DownloadError) as c:
            quiet(ig.render, "a cup", brand="alpha")
        self.assertTrue(c.exception.request_id)
        self.assertEqual((today()["images"], today()["errors"]), (1, 1), "accepted and billed: the claim stays")

    def test_the_estimate_falls_back_to_the_price_table(self):
        self.fake.estimate_replies = [("error", 500, "x"), ("error", 500, "x")]
        res = quiet(ig.render, "a cup", "9:16", brand="alpha", purpose="scene")
        self.assertEqual(res["usd"], 0.060)
        self.fake.estimate_replies = [("description",)]
        res = quiet(ig.render, "a cup", "3:4", brand="alpha", quality="high")
        self.assertEqual(res["usd"], 0.277)


class RefsTest(Base):
    def test_local_refs_are_uploaded_and_urls_pass_through(self):
        ref = TMP / "work" / "logo.png"
        ref.write_bytes(FH.tiny_png(4, 4, (255, 0, 0)))
        quiet(ig.render, "the product on a table", "1:1", refs=[ref, "https://cdn.example/ref.jpg"], brand="otto", purpose="cli")
        gen, = self.fake.calls("/files/generate-upload-url")
        self.assertEqual(gen["body"], {"content_type": "image/png"})
        put, = self.fake.calls("/put/", "PUT")
        self.assertEqual(put["headers"]["x-amz-tagging"], "retention=temporary")
        self.assertEqual(put["headers"]["content-type"], "image/png")
        self.assertNotIn("authorization", put["headers"], "never the key to the presigned upload URL")
        uid = put["path"].split("/")[2].split("?")[0]
        self.assertEqual(self.fake.uploads[uid]["data"], ref.read_bytes())
        sub, = self.submits()
        self.assertEqual(sub["body"]["image_urls"], [f"{self.fake.base}/uploads/{uid}", "https://cdn.example/ref.jpg"])
        self.assertEqual(sub["body"]["quality"], "high", "the CLI's quality")

    def test_bad_refs_are_refused_before_anything_is_spent(self):
        txt = TMP / "work" / "notes.txt"
        txt.write_text("hello")
        with self.assertRaises(ig.InvalidRequest):
            quiet(ig.render, "a cup", refs=[txt])
        with self.assertRaises(ig.InvalidRequest):
            quiet(ig.render, "a cup", refs=[TMP / "work" / "missing.png"])
        with self.assertRaises(ig.InvalidRequest):
            quiet(ig.render, "a cup", refs=["https://cdn.example/a.png"] * 17)
        with self.assertRaises(ig.InvalidRequest):
            quiet(ig.render, "a cup", refs=["https://cdn.example/a.png"], model="z-image-turbo")
        self.assertFalse(self.submits())
        self.assertEqual(today().get("images", 0), 0)


class CapsTest(Base):
    def test_daily_caps(self):
        set_cfg(max_images_day=2)
        quiet(ig.render, "a", brand="alpha")
        quiet(ig.render, "b", brand="beta")
        with self.assertRaises(ig.CapReached) as c:
            quiet(ig.render, "c", brand="alpha")
        self.assertIn("daily cap of 2 images", str(c.exception))
        self.assertEqual(len(self.submits()), 2)

    def test_per_brand_and_spend_caps(self):
        set_cfg(max_images_per_brand_day=1)
        quiet(ig.render, "a", brand="alpha")
        with self.assertRaises(ig.CapReached):
            quiet(ig.render, "b", brand="alpha")
        quiet(ig.render, "c", brand="beta")
        set_cfg(max_usd_day=0.5)
        self.fake.price = "0.3"
        (TMP / "imagegen-usage.json").unlink()
        quiet(ig.render, "d", brand="alpha")
        with self.assertRaises(ig.CapReached) as c:
            quiet(ig.render, "e", brand="beta")
        self.assertIn("daily spend cap of $0.5", str(c.exception))

    def test_generate_many_stops_at_a_cap(self):
        set_cfg(max_images_day=1, parallel=2)
        res = quiet(ig.generate_many, [{"prompt": f"p{i}", "brand": "alpha"} for i in range(3)])
        self.assertEqual(sum(1 for r in res if isinstance(r, dict)), 1)
        self.assertEqual(sum(1 for r in res if isinstance(r, ig.CapReached)), 2)


class SecretsTest(Base):
    def test_no_secret_and_no_prompt_in_any_output(self):
        out = []
        quiet(ig.render, SECRET_PROMPT, brand="alpha"); out.append(quiet.out)
        self.fake.script = ["failed"]
        try:
            quiet(ig.render, SECRET_PROMPT, brand="alpha")
        except ig.ImageGenError as e:
            out.append(quiet.out + str(e) + repr(e))
        self.fake.reset()
        self.fake.replies = [("error", 400, f"bad prompt: {FH.KEY_SECRET}")]       # even an API echoing the key back
        try:
            quiet(ig.render, SECRET_PROMPT, brand="alpha")
        except ig.ImageGenError as e:
            out.append(quiet.out + str(e))
        quiet(ig.main, ["status"]); out.append(quiet.out)
        quiet(ig.main, ["status", "--json"]); out.append(quiet.out)
        quiet(ig.main, ["test"]); out.append(quiet.out)
        out.append(json.dumps(ig.console_row()))
        out.append((TMP / "imagegen-usage.json").read_text())
        blob = "\n".join(out)
        self.assertIn("higgsfield gpt-image-2", blob)
        for s in (FH.KEY_SECRET, FH.KEY_ID, "Prinsengracht", "sourdough"):
            self.assertNotIn(s, blob)
        self.assertRegex(blob, r"prompt \d+ chars #[0-9a-f]{8}")


class CliTest(Base):
    def test_gen_writes_a_marked_file_and_test_checks_the_key(self):
        out = TMP / "work" / "hero.png"
        self.assertEqual(quiet(ig.main, ["gen", "--prompt", "a bright studio scene, no text", "--aspect", "9:16", "--out", str(out)]), 0)
        self.assertEqual(quiet.out.strip().splitlines()[-1], str(out))
        self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        info = prov.inspect(out)
        self.assertEqual((info["generated"], info["tool"]), (True, "Higgsfield gpt-image-2"))
        sub, = self.submits()
        self.assertEqual((sub["body"]["aspect_ratio"], sub["body"]["quality"]), ("9:16", "high"))
        jpg = TMP / "work" / "hero.jpg"
        self.assertEqual(quiet(ig.main, ["gen", "--prompt", "x y", "--out", str(jpg), "--quality", "low", "--resolution", "1k"]), 0)
        got = Path(quiet.out.strip().splitlines()[-1])
        self.assertIn(got.suffix, (".jpg", ".png"), "converted when ffmpeg is there, else the real type")
        self.assertEqual(self.submits()[-1]["body"]["resolution"], "1k")
        d = TMP / "work" / "outdir"
        d.mkdir()
        self.assertEqual(quiet(ig.main, ["gen", "--prompt", "x y", "--out", str(d)]), 0)
        self.assertRegex(Path(quiet.out.strip().splitlines()[-1]).name, r"^hf-[0-9a-f-]{8}\.png$")
        self.assertEqual(quiet(ig.main, ["test"]), 0)
        self.assertIn("key OK (file)", quiet.out)
        self.assertEqual(len(self.submits()), 3, "test without --live makes no image")
        no_cfg()
        self.assertEqual(quiet(ig.main, ["test"]), 1)
        self.assertIn("not configured", quiet.out)

    def test_console_row(self):
        quiet(ig.render, "a", brand="alpha")
        row = ig.console_row()
        self.assertEqual((row["key"], row["status"]), ("imagegen", "connected"))
        self.assertIn("today 1 image(s), ≈ $0.08", row["detail"])
        self.assertIn("alpha 1", row["detail"])
        self.assertIn("higgsfield.json", row["how"])
        snap = otto_admin.setup_items({"brands": []}, {"secrets": {}}, {}, {})
        self.assertIn("imagegen", [x["key"] for x in snap])
        no_cfg()
        self.assertEqual(ig.console_row()["status"], "missing")


class GenvisualsTest(Base):
    def setUp(self):
        super().setUp()
        self._gv = (genvisuals.key, genvisuals.post_json, genvisuals.time.sleep, genvisuals.urllib.request.urlopen)

    def tearDown(self):
        genvisuals.key, genvisuals.post_json, genvisuals.time.sleep, genvisuals.urllib.request.urlopen = self._gv
        super().tearDown()

    def test_higgsfield_first(self):
        add_post(id="al-101", format="story", hook="Een nieuwe week")
        add_post(id="al-102", format="feed", hook="Twee")
        add_post(id="al-103", format="post", hook="Drie")
        genvisuals.post_json = lambda *a, **kw: self.fail("Leonardo must not be called when Higgsfield made the image")
        res = quiet(genvisuals.run, ids={"al-101", "al-102", "al-103"})
        self.assertEqual(res, {"todo": 3, "fired": 3, "saved": 3})
        self.assertEqual(sorted(s["body"]["aspect_ratio"] for s in self.submits()), ["1:1", "3:4", "9:16"])
        self.assertTrue(all(s["body"]["quality"] == "medium" and s["body"]["resolution"] == "2k" for s in self.submits()))
        for pid in ("al-101", "al-102", "al-103"):
            p = ap.post(ap.load(), pid)
            self.assertRegex(p["image"], rf"^assets/posts/{pid}-[0-9a-f]{{32}}\.(jpg|png)$")    # unguessable (otto_paths)
            rec = p["media_ai"][p["image"]]
            self.assertEqual((rec["generated"], rec["tool"], rec["marked"]), (True, "Higgsfield gpt-image-2", "xmp"))
            self.assertTrue(prov.inspect(TMP / "public" / "posts" / p["image"].rsplit("/", 1)[1])["generated"],
                            "the public copy carries the mark")
            self.assertTrue(p["visual_prompt"])
        self.assertIn("FIRE al-101 [story] prompt ", quiet.out)
        self.assertNotIn("Een nieuwe week", quiet.out, "a real run logs no prompt (client data): its length and hash only")
        self.assertEqual(today("alpha")["images"], 3)

    def test_leonardo_is_the_fallback(self):
        add_post(id="al-111", format="post", hook="Vier")
        self.fake.script = ["nsfw"]
        real_urlopen = genvisuals.urllib.request.urlopen
        fired = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.startswith(self.fake.base):
                return real_urlopen(req, timeout=timeout)
            if "/v1/generations/" in url:
                return Resp(json.dumps({"generations_by_pk": {"status": "COMPLETE",
                                        "generated_images": [{"url": "https://cdn.example/leo.jpg"}]}}).encode())
            if url == "https://cdn.example/leo.jpg":
                return Resp(FH.tiny_png())
            raise AssertionError(f"unexpected fetch {url}")
        genvisuals.key = lambda: "leo-test-key"
        genvisuals.post_json = lambda u, body, k: fired.append(body) or {"generate": {"generationId": "g1"}}
        genvisuals.time.sleep = lambda s: None
        genvisuals.urllib.request.urlopen = fake_urlopen
        try:
            res = quiet(genvisuals.run, ids={"al-111"})
        finally:
            genvisuals.urllib.request.urlopen = real_urlopen
        self.assertEqual(res["saved"], 1)
        self.assertEqual(len(fired), 1, "Leonardo made the one Higgsfield refused")
        self.assertIn("HIGGSFIELD FAILED al-111 ContentRejected", quiet.out)
        p = ap.post(ap.load(), "al-111")
        self.assertEqual(p["media_ai"][p["image"]]["tool"], "Leonardo.ai gpt-image-2")
        self.assertEqual(today()["nsfw"], 1)

    def test_without_higgsfield_leonardo_runs_as_before(self):
        no_cfg()
        add_post(id="al-121", format="post", hook="Vijf")
        genvisuals.key = lambda: "leo-test-key"
        genvisuals.post_json = lambda *a, **kw: (_ for _ in ()).throw(OSError("HTTP Error 401: Unauthorized"))
        genvisuals.time.sleep = lambda s: None
        self.assertEqual(quiet(genvisuals.main, ["--ids", "al-121"]), 1)
        self.assertIn("ERR al-121", quiet.out)
        self.assertFalse(self.submits())

    def test_higgsfield_failing_without_leonardo_exits_non_zero(self):
        add_post(id="al-131", format="post", hook="Zes")
        self.fake.script = ["failed"]
        self.assertEqual(quiet(genvisuals.main, ["--ids", "al-131"]), 1)
        self.assertIn("HIGGSFIELD FAILED al-131 GenerationFailed", quiet.out)
        self.assertIn("1 generation(s) started, none saved", quiet.out)
        self.assertNotIn("image", ap.post(ap.load(), "al-131"))


class VideoScenesTest(Base):
    SCRIPT = [{"text": "Eerste tip", "seconds": 5, "visual": "a bakery counter"},
              {"text": "Tweede tip", "seconds": 5, "visual": "bread on a board"},
              {"text": "Derde tip", "seconds": 5, "visual": "a happy customer"}]

    def setUp(self):
        super().setUp()
        self._v = (otto_video._leonardo_scene, genvisuals.key)
        shutil.rmtree(TMP / "assets" / "reels", ignore_errors=True)
        (TMP / "assets" / "reels").mkdir(parents=True)

    def tearDown(self):
        otto_video._leonardo_scene, genvisuals.key = self._v
        super().tearDown()

    def test_scenes_come_from_higgsfield_and_are_cached(self):
        p = add_post(id="al-201", format="reel", hook="Drie tips")
        imgs = quiet(otto_video.scene_images, p, self.SCRIPT, False)
        self.assertEqual(len(self.submits()), 3)
        self.assertTrue(all(s["body"]["aspect_ratio"] == "9:16" and s["body"]["quality"] == "medium" for s in self.submits()))
        for f in imgs:
            self.assertRegex(f.name, r"^s-[0-9a-f]{12}\.png$")
            self.assertEqual(prov.inspect(f)["tool"], "Higgsfield gpt-image-2")
            self.assertTrue(otto_video.scene_is_ai(f))
        self.assertEqual(otto_video.scene_tools(imgs), ["Higgsfield gpt-image-2"])
        again = quiet(otto_video.scene_images, p, self.SCRIPT, False)
        self.assertEqual(again, imgs)
        self.assertEqual(len(self.submits()), 3, "cached: no new image")
        self.assertEqual(today("alpha")["images"], 3)

    def test_leonardo_fills_what_higgsfield_could_not_make(self):
        set_cfg(parallel=1)
        p = add_post(id="al-202", format="reel", hook="Drie tips")
        self.fake.replies = [("error", 422, "prompt rejected")]                  # the first scene only
        calls = []

        def leo(gv, key, prompt, d, stem):
            calls.append(stem)
            f = d / (stem + ".jpg")
            f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
            return f
        otto_video._leonardo_scene = leo
        genvisuals.key = lambda: "leo-test-key"
        imgs = quiet(otto_video.scene_images, p, self.SCRIPT, False)
        self.assertEqual(calls, [imgs[0].stem])
        self.assertEqual([f.suffix for f in imgs], [".jpg", ".png", ".png"])
        self.assertIn("scene 1 image (Higgsfield) failed: InvalidRequest", quiet.out)

    def test_no_keys_reuse_the_post_picture_and_dry_makes_nothing(self):
        no_cfg()
        pic = TMP / "assets" / "posts" / otto_paths.token_name("al-203", ".jpg")
        pic.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        p = add_post(id="al-203", format="reel", hook="Drie tips", image=otto_paths.rel_of(pic))
        otto_video._leonardo_scene = lambda *a: self.fail("no Leonardo key: Leonardo is not called")
        imgs = quiet(otto_video.scene_images, p, self.SCRIPT, False)
        self.assertTrue(all(f.stem.endswith("-fb") for f in imgs), "fallbacks are not cached under the scene key")
        self.assertFalse(any(otto_video.scene_is_ai(f) for f in imgs))
        set_cfg()
        shutil.rmtree(TMP / "assets" / "reels" / "al-203")
        quiet(otto_video.scene_images, p, self.SCRIPT, True)
        self.assertFalse(self.submits(), "a dry render generates nothing")


if __name__ == "__main__":
    unittest.main()
