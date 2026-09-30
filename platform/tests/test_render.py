#!/usr/bin/env python3
"""otto_render tests. Stdlib unittest; the unit tests need no browser, the integration tests render real JPEGs
and are skipped when no headless Chrome (or ffmpeg) is available.

  cd platform && python3 tests/test_render.py
  OTTO_CHROME=/path/to/chrome-headless-shell python3 tests/test_render.py      # pick the browser
"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM))
import otto_render as R  # noqa: E402

ROOT = PLATFORM.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-render-test-"))
DARK = "motion/otto-kit/img/hg-evening.jpg"
BRIGHT = "motion/otto-kit/img/hg-yellow.jpg"


def browser():
    try:
        return R.find_browser()
    except R.BrowserNotFound:
        return None


HAVE_BROWSER = bool(browser()) and bool(shutil.which("ffmpeg"))
SPEC = json.loads((R.TEMPLATES / "_demo.json").read_text())


def setUpModule():
    """These tests read the real brands/ (happygarden, cmtm). When run under discover after test_engine, OTTO_BRANDS
    points at that suite's temp fixture — pin both lookups back to the repo for the duration."""
    import ap
    global _SAVED
    _SAVED = (R.BRANDS, ap.BRANDS)
    R.BRANDS = ap.BRANDS = ROOT / "brands"


def tearDownModule():
    import ap
    R.BRANDS, ap.BRANDS = _SAVED


def quiet(*_a, **_k):
    pass


def visible_text(page):
    """What a viewer can read: no styles, scripts, comments or tags."""
    page = re.sub(r"<style>.*?</style>|<script>.*?</script>|<!--.*?-->", " ", page, flags=re.S)
    return re.sub(r"<[^>]+>", " ", page)


class TemplateLanguageTest(unittest.TestCase):
    def test_vars_escape_and_raw(self):
        self.assertEqual(R.fill("<b>{{x}}</b>", {"x": "<i>&"}), "<b>&lt;i&gt;&amp;</b>")
        self.assertEqual(R.fill("{{&x}}", {"x": "<i>"}), "<i>")

    def test_missing_key_renders_nothing(self):
        self.assertEqual(R.fill("[{{nope}}][{{a.b.c}}]", {}), "[][]")

    def test_each_if_unless_else(self):
        out = R.fill("{{#each xs}}{{@n}}:{{.}}{{#unless @last}},{{/unless}}{{/each}}", {"xs": ["a", "b", "c"]})
        self.assertEqual(out, "1:a,2:b,3:c")
        self.assertEqual(R.fill("{{#if a}}Y{{else}}N{{/if}}", {"a": ""}), "N")
        self.assertEqual(R.fill("{{#each xs}}x{{else}}empty{{/each}}", {"xs": []}), "empty")
        self.assertEqual(R.fill("{{#each rows}}{{name}}{{/each}}", {"rows": [{"name": "r1"}, {"name": "r2"}]}), "r1r2")

    def test_unbalanced_raises(self):
        with self.assertRaises(R.RenderError):
            R.fill("{{#if a}}x", {})
        with self.assertRaises(R.RenderError):
            R.fill("x{{/if}}", {})

    def test_attribute_values_get_no_markup(self):
        out = R.fill('<img style="object-position:{{pos}}" alt="{{t}}">{{pos}}', {"pos": "50% 30%", "t": "*a* 10+"})
        self.assertTrue(out.startswith('<img style="object-position:50% 30%" alt="*a* 10+">'), out)
        self.assertIn('<bdi class="n">50%</bdi>', out)                 # text context still isolates numbers

    def test_partials_inline(self):
        out = R.fill("{{> tick}}", {})
        self.assertIn("<svg", out)


class CopyTest(unittest.TestCase):
    def test_emphasis_breaks_paragraphs(self):
        self.assertEqual(R.fmt_text("a *b* c"), "a <em>b</em> c")
        self.assertEqual(R.fmt_text("a\nb"), "a<br>b")
        self.assertIn('class="pb"', R.fmt_text("a\n\nb"))

    def test_numbers_are_bidi_isolated(self):
        out = R.fmt_text("מעל 10,000+ בוגרים")
        self.assertIn('<bdi class="n">10,000+</bdi>', out)
        self.assertIn("מעל", out)
        self.assertIn('<bdi class="n">19:00</bdi>, ok', R.fmt_text("19:00, ok"))   # trailing comma stays outside

    def test_urls_untouched(self):
        u = "file:///x/hg-001.jpg"
        self.assertEqual(R.fmt_text(u), u)

    def test_clean_copy(self):
        self.assertEqual(R.clean_copy("**Bold** → next"), "Bold next")
        self.assertEqual(R.clean_copy("Hi {first_name} [TBD] (?)"), "Hi")
        self.assertEqual(R.clean_copy("Sleep better \U0001F634"), "Sleep better")
        self.assertEqual(R.clean_copy("Keep *this*"), "Keep *this*")

    def test_sanitize_drops_internal_data(self):
        warned = []
        d = R.sanitize({"headline": "Good copy", "sub": "CPL ₪44, 355 leads", "photo": "assets/x → y.jpg",
                        "items": ["ok", "budget €20/day"]}, warned.append)
        self.assertEqual(d["headline"], "Good copy")
        self.assertNotIn("sub", d)
        self.assertEqual(d["items"], ["ok"])
        self.assertEqual(d["photo"], "assets/x → y.jpg")       # asset paths are never rewritten
        self.assertEqual(len(warned), 2)

    def test_placeholders_fail_loudly_and_real_copy_survives(self):
        """"Costume: TBD" is a headline, not a placeholder: it renders whole. Real placeholders and internal data stop the
        render (CopyError), never vanish silently."""
        tok = R.brand_tokens("happygarden")
        for ok in ("Costume: TBD", "Launch date TBD", "It leads to calmer evenings.", "CBD on a budget", "Lead the way",
                   "Budget-friendly, lab tested", "XXL bottle", "30 ml · €45"):
            page = R.render_html("editorial", {"headline": ok}, brand=tok, warn=quiet)
            self.assertIn(R.fmt_text(ok).split("<")[0][:12], page, ok)
        for bad in ("Big [TBD] sale", "Hi {{first_name}}", "Hi {first_name}", "TBD", "tbd.", "TODO: headline",
                    "6 g of fiber (?)", "Save XX% today", "Lorem ipsum dolor", "[Brand Name] oil", "[insert price]"):
            with self.assertRaises(R.CopyError, msg=bad) as cm:
                R.render_html("editorial", {"headline": "ok", "sub": bad}, brand=tok)
            self.assertTrue(cm.exception.issues[0].startswith("sub: placeholder"), cm.exception.issues)
        for bad in ("CPL ₪44", "355 leads this week", "daily budget €20", "budget €20/day", "עלות לליד 40 ₪", "ROAS 3.1"):
            with self.assertRaises(R.CopyError, msg=bad):
                R.render_html("editorial", {"headline": bad}, brand=tok)
        # nested copy is checked too; asset paths, urls and layout switches are not copy
        with self.assertRaises(R.CopyError):
            R.render_html("checklist", {"title": "x", "items": ["fine", {"text": "[TBD]"}]}, brand=tok)
        R.render_html("editorial", {"headline": "x", "photo": "assets/[TBD].png", "url": "https://x/{id}"}, brand=tok, warn=quiet)

    def test_check_and_render_set_refuse_placeholders(self):
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = R.main(["check", "editorial", json.dumps({"headline": "Big [TBD] sale"}), "--brand", "happygarden"])
        self.assertEqual(code, 4)
        self.assertIn("placeholder", err.getvalue())
        with self.assertRaises(R.CopyError) as cm:                     # nothing rendered, no browser needed
            R.render_set({"id": "p-tbd", "format": "feed", "hook": "Hi {first_name}, meet CBD"}, "happygarden", TMP / "set-tbd")
        self.assertIn("p-tbd-ad.jpg", str(cm.exception))
        self.assertFalse((TMP / "set-tbd" / "p-tbd-ad.jpg").exists())

    def test_strict_render_refuses_a_missing_required_field(self):
        out = TMP / "ph-noproduct.jpg"
        with self.assertRaises(R.FitError) as cm:                  # before any browser: nothing to shoot
            R.render("product_hero", {"headline": "Clean CBD"}, out, brand="happygarden")
        self.assertIn("photo", str(cm.exception))
        self.assertFalse(out.exists())
        self.assertIsInstance(cm.exception, R.CopyError)          # otto_creative never falls back to a text band

    def test_cta_labels_follow_the_meta_button(self):
        self.assertEqual(R.cta_label("SHOP_NOW", "en"), "Shop now")
        self.assertEqual(R.cta_label("shop_now", "he"), "לרכישה")
        self.assertEqual(R.cta_label("LEARN_MORE", "he"), R.LABELS["he"]["cta"])
        self.assertEqual(R.cta_label("SIGN_UP", "ro"), "Înscrie-te")
        self.assertEqual(R.cta_label("BOOK_NOW", "xx"), "Book now")
        self.assertEqual(R.cta_label(None), "")

    def test_hebrew_stays_in_logical_order(self):
        he = "תוך שנה הפכתי למטפלת טובה"
        page = R.render_html("quote", {"quote": he, "name": "רות"}, brand=R.brand_tokens("cmtm"), warn=quiet)
        self.assertIn(he, page)
        self.assertNotIn(he[::-1], page)


class TokenTest(unittest.TestCase):
    def test_happygarden(self):
        t = R.brand_tokens("happygarden")
        self.assertEqual(t["accent"], "#FFBC00")
        self.assertEqual(t["lang"], "en")
        self.assertEqual(t["dir"], "ltr")
        self.assertEqual(t["em_light"], "marker")               # yellow is too light for text on paper
        self.assertNotEqual(t["accent"], "#25D366")             # "UI only" WhatsApp green never becomes the accent
        self.assertEqual(t["host"], "happygardeneu.com")

    def test_cmtm_rtl_cta_accent_navy(self):
        t = R.brand_tokens("cmtm")
        self.assertEqual(t["dir"], "rtl")
        self.assertEqual(t["accent"], "#00A5B5")                # the profile's CTA colour, not the purple
        self.assertEqual(t["deep"], "#0A1530")
        self.assertEqual(t["font_display"], "Heebo")

    def test_contrast_guarantees(self):
        for bid in ("happygarden", "cmtm", None):
            t = R.brand_tokens(bid)
            self.assertGreaterEqual(R.contrast(t["accent_on_dark"], t["deep"]), 4.5, bid)
            if t["em_light"] == "color":
                self.assertGreaterEqual(R.contrast(t["accent_text"], t["surface"]), 3.0, bid)
            self.assertGreaterEqual(R.contrast(t["accent"], t["accent_ink"]), 3.0, bid)

    def test_muted_text_keeps_body_contrast_on_every_ground(self):
        """Secondary text (subs, sources, hosts, fine print) is as quiet as each brand's colours allow while small text keeps
        4.5:1 — a fixed 64 % ink fell to 3.3:1 on Grüns' green paper, 74 % white to 3.6:1 on its accent."""
        palettes = {"t-green": ["#007E40", "#E8B411", "#00572C"], "t-orange": ["#FF6B00", "#1E1E1E"], "t-teal": ["#00B3C7", "#06262B"],
                    "t-purple": ["#6B3FA0", "#1B1030"], "t-lime": ["#B6E300", "#14210A"]}
        root = TMP / "brands-mut"
        for bid, cols in palettes.items():
            (root / bid).mkdir(parents=True, exist_ok=True)
            (root / bid / "scan.json").write_text(json.dumps({"visual": {"palette": [{"hex": h} for h in cols]}, "languages": ["en"]}))
        saved = R.BRANDS
        R.BRANDS = root
        try:
            toks = [R.brand_tokens(b) for b in palettes] + [R.brand_tokens("happygarden"), R.brand_tokens("cmtm")]
        finally:
            R.BRANDS = saved
        for t in toks + [R.brand_tokens(None)]:
            for paper in (t["surface"], t["surface2"]):
                self.assertGreaterEqual(R.contrast(t["mut_light"], paper), 4.5, t["id"])
                self.assertGreaterEqual(R.contrast(t["mut_large_light"], paper), 3.0, t["id"])
            self.assertGreaterEqual(R.contrast(t["mut_dark"], t["deep"]), 4.5, t["id"])
            self.assertGreaterEqual(R.contrast(t["mut_accent"], t["accent"]), min(4.5, R.contrast(t["accent_ink"], t["accent"])), t["id"])
            self.assertGreaterEqual(R.contrast(t["marker_ink"], t["marker"]), 3.0, t["id"])
            self.assertIn("--mut-light:" + t["mut_light"], R.tokens_css(t))

    def test_unknown_brand_defaults(self):
        t = R.brand_tokens("no-such-brand-xyz")
        self.assertEqual(t["lang"], "en")
        self.assertTrue(t["accent"].startswith("#"))

    def test_logo_replaces_wordmark(self):
        logo = TMP / "logo.svg"
        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40"><rect width="200" height="40"/></svg>')
        tok = R.brand_tokens("happygarden", logo=str(logo))
        self.assertEqual(tok["logo_ratio"], 5.0)
        page = R.render_html("editorial", {"headline": "x"}, brand=tok)       # mono: a mask in the ground's colour
        self.assertIn('class="logo-m"', page)
        self.assertIn("data:image/svg+xml;base64,", page)
        self.assertNotIn(">happygarden<", page.lower())
        page = R.render_html("editorial", {"headline": "x"}, brand=dict(tok, logo_mode="color"))
        self.assertIn(logo.resolve().as_uri(), page)

    def test_overrides(self):
        self.assertEqual(R.brand_tokens("cmtm", accent="#123456")["accent"], "#123456")

    def test_palette_labels(self):
        got = dict(R.palette_labels("- Palette: #111111 (text) · #00A5B5 CTA · #25D366 WhatsApp — UI only"))
        self.assertIn("CTA", got["#00A5B5"])
        self.assertIn("UI only", got["#25D366"])

    def test_two_colour_brand_with_its_own_font(self):
        """Found on gruns.co: green + yellow, DM Sans. Their face carries emphasis, yellow is the accent on forest
        green and the highlighter on paper; brands without a web font keep the house serif."""
        bdir = TMP / "brands-gr" / "t-green"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "scan.json").write_text(json.dumps({"visual": {
            "palette": [{"hex": h} for h in ("#007E40", "#E8B411", "#00572C", "#002613")],
            "neutrals": [{"hex": "#FFFFFF"}], "fonts": ["DMSans", "Work Sans"]}, "languages": ["en"]}))
        saved = R.BRANDS
        R.BRANDS = TMP / "brands-gr"
        try:
            t = R.brand_tokens("t-green")
        finally:
            R.BRANDS = saved
        self.assertEqual((t["font_display"], t["font_text"], t["em_style"]), ("DM Sans", "DM Sans", "brand"))
        self.assertEqual(t["accent_on_dark"], "#E8B411")
        self.assertEqual((t["em_light"], t["marker"]), ("marker", "#E8B411"))
        self.assertIn("ems-brand", R.render_html("editorial", {"headline": "x"}, brand=t))
        self.assertEqual(R.brand_tokens("happygarden")["em_style"], "serif")
        self.assertEqual(R.brand_tokens("happygarden")["marker"], R.brand_tokens("happygarden")["accent"])
        self.assertIsNone(R.brand_font({"visual": {"fonts": ["Olipop Display"]}}))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_cutout_detection(self):
        cut, photo = TMP / "cut.png", TMP / "photo.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=64x64,format=rgba",
                        "-vf", "drawbox=x=16:y=16:w=32:h=32:color=green@1:t=fill", "-frames:v", "1", str(cut)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=64x64", "-frames:v", "1",
                        str(photo)], check=True)
        self.assertTrue(R.is_cutout(cut.resolve().as_uri()))
        self.assertFalse(R.is_cutout(photo.resolve().as_uri()))
        page = R.render_html("editorial", {"headline": "x", "photo": str(cut)}, brand=R.brand_tokens("cmtm"))
        self.assertIn("has-cutout", page)
        self.assertIn('class="ad split', page)


class ContextTest(unittest.TestCase):
    def test_dates(self):
        en = R.date_parts("2026-10-15", "en")
        self.assertEqual((en["date_day"], en["date_mon"], en["date_weekday"]), ("15", "Oct", "Thursday"))
        he = R.date_parts("2026-10-14", "he")
        self.assertEqual((he["date_month"], he["date_weekday"]), ("אוקטובר", "יום רביעי"))
        self.assertEqual(R.date_parts("Every Tuesday")["date_label"], "Every Tuesday")

    def test_table_cells(self):
        ctx = {"columns": ["A", {"name": "B", "highlight": True}], "rows": [{"label": "x", "values": ["yes", "no"]}]}
        R.table_cells(ctx)
        cells = ctx["rows"][0]["_cells"]
        self.assertEqual(ctx["_ncols"], 2)
        self.assertTrue(cells[0]["yes"] and cells[1]["no"] and cells[1]["hi"])

    def test_carousel_counter(self):
        ctx = R.build_context({"headline": "x", "n": 2, "total": 5}, (1080, 1350), R.brand_tokens("happygarden"))
        self.assertEqual(ctx["counter"], "02 / 05")
        self.assertEqual(sum(1 for s in ctx["_segments"] if s["on"]), 2)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
    def test_auto_layout_by_photo_brightness(self):
        tok = R.brand_tokens("happygarden")
        self.assertTrue(R.build_context({"photo": BRIGHT}, (1080, 1350), tok).get("split"))
        self.assertTrue(R.build_context({"photo": DARK}, (1080, 1350), tok).get("overlay"))
        self.assertTrue(R.build_context({"photo": DARK, "layout": "split"}, (1080, 1350), tok).get("split"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
    def test_brand_bar_turns_ink_over_a_bright_photo_top(self):
        tok = R.brand_tokens("happygarden")
        self.assertIn("photo-top-light", R.build_context({"photo": BRIGHT}, (1080, 1350), tok)["html_class"])
        self.assertNotIn("photo-top-light", R.build_context({"photo": DARK}, (1080, 1350), tok)["html_class"])
        page = R.render_html("offer", {"name": "x", "cta": "Shop now", "photo": BRIGHT}, brand=tok)
        self.assertIn("html.photo-top-light body .top-on-photo", page)

    def test_formats(self):
        self.assertEqual(R.fmt_of((1080, 1920)), "story")
        self.assertEqual(R.fmt_of((1080, 1080)), "square")
        self.assertEqual(R.fmt_of((1080, 1350)), "feed")


class TemplateSetTest(unittest.TestCase):
    REQUIRED = {"editorial", "big_number", "quote", "before_after", "myth_fact", "checklist", "offer", "comparison",
                "carousel_cover", "carousel_inner", "carousel_cta", "founder_note", "event"}

    def test_catalogue(self):
        have = set(R.list_templates())
        self.assertTrue(self.REQUIRED <= have, self.REQUIRED - have)
        self.assertGreaterEqual(len(have), 10)
        with self.assertRaises(R.RenderError):
            R.template_path("nope")

    def test_every_demo_spec_renders_clean_html(self):
        for bid in ("happygarden", "cmtm"):
            tok = R.brand_tokens(bid)
            for s in SPEC[bid]:
                size = R.SIZES[s.get("size", "feed")]
                page = R.render_html(s["template"], s["data"], size, tok, warn=quiet)
                label = f"{bid}/{s['name']}"
                self.assertNotIn("{{", page, label)
                self.assertIn(f'dir="{tok["dir"]}"', page, label)
                self.assertIn(f"f-{R.fmt_of(size)}", page, label)
                self.assertIn("data-fit", page, label)
                text = visible_text(page)
                for bad in ("**", "→", "->", "=>", "TBD", "placeholder", "CPL", "undefined", "alt=", "50%"):
                    self.assertNotIn(bad, text, f"{label}: {bad!r}")

    def test_every_template_survives_empty_data(self):
        for t in R.list_templates():
            page = R.render_html(t, {}, (1080, 1350), R.brand_tokens("happygarden"), warn=quiet)
            self.assertTrue(page.lstrip().lower().startswith("<!doctype html>"), t)
            self.assertNotIn("{{", page, t)

    def test_demo_copy_passes_brand_compliance(self):
        for bid in ("happygarden", "cmtm"):
            issues = R.compliance_issues(bid, R._texts([s["data"] for s in SPEC[bid]]))
            self.assertEqual(issues, [], f"{bid}: {issues}")

    def test_compliance_gate_catches_banned_copy(self):
        self.assertTrue(R.compliance_issues("happygarden", ["CBD may heal your joints"]))
        self.assertTrue(R.compliance_issues("cmtm", ["האם הילד שלך מתמודד עם חרדה?"]))


class BrowserLookupTest(unittest.TestCase):
    def test_bad_env_is_a_clear_error(self):
        old = os.environ.get("OTTO_CHROME")
        os.environ["OTTO_CHROME"] = "/nonexistent/chrome-xyz"
        try:
            with self.assertRaises(R.BrowserNotFound) as cm:
                R.find_browser()
            self.assertIn("OTTO_CHROME", str(cm.exception))
        finally:
            if old is None:
                os.environ.pop("OTTO_CHROME", None)
            else:
                os.environ["OTTO_CHROME"] = old


@unittest.skipUnless(HAVE_BROWSER, "no headless Chrome / ffmpeg: set OTTO_CHROME to run the integration renders")
class IntegrationTest(unittest.TestCase):
    def _jpeg_size(self, path):
        data = Path(path).read_bytes()
        self.assertEqual(data[:2], b"\xff\xd8", "not a JPEG")
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        return None

    def test_render_hebrew_feed_and_story(self):
        s = next(x for x in SPEC["cmtm"] if x["name"] == "02-editorial-split")
        out = R.render("editorial", s["data"], TMP / "he.jpg", brand="cmtm")
        self.assertEqual(self._jpeg_size(out), (1080, 1350))
        self.assertGreater(Path(out).stat().st_size, 40_000)
        out = R.render("big_number", {"number": "10,000+", "label": "בוגרים"}, TMP / "he-story.jpg", size=(1080, 1920),
                       brand="cmtm")
        self.assertEqual(self._jpeg_size(out), (1080, 1920))

    def test_png_out(self):
        out = R.render("myth_fact", {"myth": "All CBD contains THC.", "fact": "Our isolate is *THC-free*."},
                       TMP / "mf.png", size=(1080, 1080), brand="happygarden")
        self.assertEqual(R._png_size(out), (1080, 1080))

    def test_strict_render_never_writes_clipped_copy(self):
        long = {"headline": " ".join(["Extraordinarily"] * 60)}
        out = TMP / "clipped.jpg"
        with self.assertRaises(R.FitError) as cm:
            R.render("editorial", long, out, brand="happygarden")
        self.assertIn("does not fit", str(cm.exception))
        self.assertFalse(out.exists())
        self.assertTrue(Path(R.render("editorial", long, out, brand="happygarden", strict=False)).exists())   # drafts
        with self.assertRaises(R.FitError):
            R.render("editorial", {"headline": "x", "photo": "assets/nope/missing.jpg"}, TMP / "nophoto.jpg", brand="happygarden")

    def test_copy_fits_or_is_flagged(self):
        ok = R.fit_report("editorial", {"headline": "Clean CBD, *checked twice*."}, brand="happygarden")
        self.assertTrue(ok["fitted"])
        self.assertFalse(ok["overflow"])
        long = R.fit_report("editorial", {"headline": " ".join(["Extraordinarily"] * 60)}, brand="happygarden")
        self.assertTrue(long["overflow"])

    def test_render_set_post_carousel(self):
        post = {"id": "t-1", "format": "carousel", "hook": "Full vs broad vs isolate?", "image": BRIGHT,
                "caption": "Confused by labels? Full is the whole plant. Broad is everything minus THC. "
                           "Isolate is pure CBD. Our spectrum guide makes it simple."}
        out = R.render_set(post, "happygarden", TMP / "set")
        self.assertEqual([o["template"] for o in out],
                         ["carousel_cover"] + ["carousel_inner"] * 4 + ["carousel_cta"])
        self.assertEqual(out[-1]["text"], "Our spectrum guide makes it simple.")
        for o in out:
            self.assertTrue(Path(o["file"]).exists(), o["file"])

    def test_fit_report_flags_missing_and_broken_images(self):
        bad = TMP / "broken.jpg"
        bad.write_bytes(b"not an image at all" * 50)
        rep = R.fit_report("editorial", {"headline": "Clean CBD", "photo": "assets/nope/missing.jpg"}, brand="happygarden")
        self.assertEqual(rep["missing"], ["assets/nope/missing.jpg"])
        self.assertTrue(rep["fitted"])
        rep = R.fit_report("quote", {"quote": "Lovely.", "name": "A.", "portrait": str(bad)}, brand="happygarden")
        self.assertEqual(rep["broken"], ["broken.jpg"])
        self.assertEqual(rep["offcanvas"], [])

    def test_offer_takes_a_cutout_in_every_format(self):
        """A transparent packshot on the offer card: whole, on the theme's ground (no light band), the brand bar in the
        ground's text colour, the story card inside the safe zone."""
        cut = TMP / "offer-cut.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=400x600,format=rgba",
                        "-vf", "drawbox=x=80:y=60:w=240:h=480:color=green@1:t=fill", "-frames:v", "1", str(cut)], check=True)
        data = {"name": "Subscribe & Save", "price": "€45", "price_note": "30 ml", "features": ["Lab tested", "THC-free"],
                "cta": "Shop now", "terms": "Renews monthly.", "photo": str(cut), "theme": "dark"}
        page = R.render_html("offer", data, (1080, 1920), R.brand_tokens("happygarden"))
        self.assertIn("has-cutout", page)
        self.assertIn("html:not(.has-cutout) .top-on-photo{color:#fff}", page)
        for size in ((1080, 1350), (1080, 1080), (1080, 1920)):
            rep = R.fit_report("offer", data, size, brand="happygarden")
            self.assertFalse(rep["overflow"], size)
            self.assertEqual((rep["offcanvas"], rep["unsafe"]), ([], []), size)

    def test_native_screenshot_fills_its_room(self):
        """A short thread is zoomed in (up to 1.4x the iOS size) instead of a small phone in an empty frame; a long one
        still fits or scrolls; every story keeps its copy inside Meta's unified safe zone."""
        short = {"contact": "Happy Garden", "messages": [{"from": "me", "text": "Which oils have no THC?"},
                                                         {"from": "them", "text": "Broad Spectrum and Isolate."}]}
        rep = R.fit_report("text_message", short, (1080, 1350), brand="happygarden")
        size = next(v for k, v in rep["sizes"].items() if k.startswith("in#"))
        self.assertGreater(size, 17 * 2.3 + 4)
        self.assertLessEqual(size, 17 * 2.3 * 1.4 + 1)
        self.assertFalse(rep["overflow"])
        for t, d in (("text_message", dict(short, headline="The two questions *everyone asks*.")),
                     ("notes_app", {"title": "Before I buy CBD", "items": ["Find the lab report", "Check the spectrum"],
                                    "headline": "Your CBD checklist, *before checkout*."}),
                     ("search", {"query": "cbd oil without", "suggestions": ["cbd oil without thc", "cbd oil without the guesswork"]})):
            rep = R.fit_report(t, d, (1080, 1920), brand="happygarden")
            self.assertEqual((rep["overflow"], rep["unsafe"], rep["offcanvas"]), (False, [], []), t)

    def test_render_set_campaign_names(self):
        camp = {"id": "cp-t", "objective": "leads", "creatives": {"titles": ["Clean CBD"], "bodies": ["Lab tested."],
                                                                  "images": [{"src": DARK}]}}
        out = R.render_set(camp, "happygarden", TMP / "camp")
        self.assertEqual(sorted(Path(o["file"]).name for o in out),
                         ["cp-t-1-c1.jpg", "cp-t-1-c2.jpg", "cp-t-1-c3.jpg", "cp-t-1-static.jpg"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
