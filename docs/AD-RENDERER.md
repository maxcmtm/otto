# Otto ad renderer (`platform/otto_render.py`)

HTML templates shot by headless Chrome replace the ffmpeg text band, which remains the no-browser fallback. Stdlib Python; JPEG via `ffmpeg -q:v 2`.

## Templates (`platform/templates/ads/`)

| Template | Tuned sizes |
|---|---|
| `editorial` (photo + headline, auto overlay/split) | feed, story, square |
| `big_number`, `quote`, `offer`, `event` | feed, story (photo fills the Reels band) |
| `myth_fact`, `checklist`, `comparison`, `before_after`, `founder_note` | feed, square |
| `carousel_cover`, `carousel_inner`, `carousel_cta` | feed, square |

Feed 1080×1350, story 1080×1920, square 1080×1080. Each file's header lists its data fields; `*word*` marks the accent.

## API and CLI

```python
otto_render.render(template, data, out_path, size=(1080, 1350), brand="cmtm")
otto_render.render_set(post_or_campaign, brand_id, out_dir)
otto_render.fit_report(template, data, size, brand)           # {"fitted", "overflow"}
```

```
python3 otto_render.py demo <brand> <out_dir>
python3 otto_render.py one <template> '<json>' <out.jpg> --brand <id> [--size story]
python3 otto_render.py check <template> '<json>' --brand <id>   # exit 3: too long
python3 otto_render.py sheet <out.jpg> <dir>...
```

## Rules the renderer enforces

- **Brand tokens** come from the profile's VISUAL IDENTITY section plus `scan.json`. The CTA-labelled colour is the accent (CMTM: turquoise on navy, not purple); "UI only" colours are skipped; contrast is checked; a light accent (Happy Garden yellow) becomes a highlighter band. `brands/<id>/render.json` overrides tokens; `brands/<id>/logo.svg` replaces the wordmark.
- **Hebrew**: `dir="rtl"`, Heebo/Assistant/Frank Ruhl Libre, logical order; numbers are bidi-isolated so `10,000+` never flips.
- **Safe zones**: story keeps text out of the top 14 % and bottom 35 %.
- **Photos**: layout "auto" measures brightness; bright photos get a split layout, not a muddy scrim.
- **Copy hygiene**: `**`, arrows, placeholders, `(?)` and emoji are stripped; fields carrying CPL, ROAS, budget or lead counts are dropped with a warning. Copy shrinks to fit.
- **Compliance**: `demo` checks copy against `brands/<id>/compliance.json`.

## Server (Ubuntu)

```
sudo apt-get update && sudo apt-get install -y ffmpeg fonts-noto-core wget && wget -qO /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo apt-get install -y /tmp/chrome.deb
```

Browser lookup: `OTTO_CHROME`, `google-chrome`, `chromium(-browser)`, macOS Chrome, HyperFrames `chrome-headless-shell`. Snap Chromium can't read `/tmp`: set `OTTO_RENDER_TMP=$HOME/.cache/otto/tmp`. Fonts are fetched once into `~/.cache/otto/fonts`.

## Wiring patch for `platform/otto_creative.py`

Applies cleanly; `test_engine.py` passes 56/56 with it. Same file names and data. `OTTO_RENDERER=ffmpeg` forces the old overlay.

```diff
--- a/platform/otto_creative.py
+++ b/platform/otto_creative.py
@@ -24,2 +24,7 @@
 
+try:
+    import otto_render                    # studio templates via headless Chrome
+except Exception:
+    otto_render = None
+
 HERE = Path(__file__).parent
@@ -182,2 +187,12 @@
 
+def render_card(template, data, src, dst, text, color, bid, **overlay_kw):
+    """otto_render template; the ffmpeg band when no headless Chrome (or OTTO_RENDERER=ffmpeg)."""
+    if otto_render is not None and os.environ.get("OTTO_RENDERER", "html") != "ffmpeg":
+        try:
+            return otto_render.render(template, dict(data, photo=str(src)), dst, brand=bid)
+        except otto_render.RenderError as e:
+            print(f"otto_render fallback: {str(e)[:160]}", file=sys.stderr)
+    return overlay_text(src, dst, text, color, **overlay_kw)
+
+
 # ---------------- angle bank ----------------
@@ -298,3 +313,4 @@
                 try:
-                    overlay_text(paths.local_path(img_post["image"]), dst, hook, pal)
+                    render_card("editorial", {"headline": hook, "sub": proof.strip("“”")}, paths.local_path(img_post["image"]),
+                                dst, hook, pal, bid)
                     paths.publish(dst)
@@ -305,2 +321,5 @@
             cards = []
+            card_data = [("carousel_cover", {"headline": hook}),
+                         ("carousel_inner", {"title": trim(proof or a["angle"], 140)}),
+                         ("carousel_cta", {"headline": hook, "cta": cta_card})]
             for j, txt in enumerate([hook, trim(proof or a["angle"], 40), cta_card], 1):
@@ -312,3 +331,5 @@
                     try:
-                        overlay_text(paths.local_path(ip["image"]), dst, txt, pal, pos="bottom", size=52)
+                        tpl, data = card_data[j - 1]
+                        render_card(tpl, dict(data, n=j, total=3), paths.local_path(ip["image"]), dst, txt, pal, bid,
+                                    pos="bottom", size=52)
                         paths.publish(dst)
```

## Tests and demo

`python3 platform/tests/test_render.py`: 35 tests; 5 integration renders skip without a browser. Demos: `demo/ads-v2/`.
