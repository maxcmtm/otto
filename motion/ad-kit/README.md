# Otto ad-kit: short video ads, re-skinnable per client

Six HyperFrames ad styles (10–15 s — reels follow their voice — 9:16 first, sound-off first) that Otto fills from a client's **brand
tokens** and **one data file per ad**, plus a synthesized music bed and UI sounds. They are for Meta campaigns
where every angle runs in several ad styles. Each style is one idea on one real-feeling surface, ending on a
shared end card (product, one line, the offer).

First client: Grüns (`examples/gruns/`). The renders live in `demo/gruns/video-ads/` (full resolution,
git-ignored) and `demo/gruns/page/video/` (web copies).

## The six styles, and when to use each

| Style | What happens | Use it for | Grüns length |
|---|---|---|---|
| `notes` | A phone note is typed ("Things I stopped buying"). Lines get struck through on the beat, and the last line is kept and highlighted. | Replace-the-stack, habit, or "what I quit" angles, told in the customer's own voice | 12.7 s |
| `search` | A generic search pill. The query types, autocomplete drops, a suggestion is chosen, and one result card rises (site, title, stars, snippet, product). | Problem-aware or solution-aware "I was looking for X" angles, and taste/quality claims backed by proof | 10.7 s |
| `texts` | A text thread between two friends: typing dots, a typed-and-sent reply (whoosh), a photo attachment. | Social proof and switcher stories: objection → answer in conversation | 13.7 s |
| `versus` | A split screen: the generic category (neutral) against the brand's way (brand colour). Rows reveal in pairs, cross against check, and a highlighted footer closes it. | Us-vs-the-category angles. **Never name a competitor.** | 10.2 s |
| `big` | The hero product huge: a macro pull-back, then kinetic type slams one fact per hit ("6 g" / "of fiber."), and the last phrase brings in the pack. | Number-led angles (fiber, vitamins, price per day). Fast and on the beat. | 10.2 s |
| `reel` | Short voiceover b-roll. The voice leads and on-screen lines carry it sound-off. One stage: a line zone above one visual zone that changes per cue (a product cut-out turning or rising, a photo card with a slow push, or stat cards that count up). A cue without a shot sets its line large. The last voice line plays over the end card. | Proof and study explainers, moments (seasonal), anything that needs a sentence of voice. Length follows the voice (≈ 15–25 s). | 17.9–23.0 s |

Every style ends on `endcard`: a sheet rises on a downbeat and carries the headline with one accent phrase, the
pack plus an optional single unit, an offer line, fine print, and an optional legal/FDA line. It has no buttons.
The platform's own CTA does the clicking.

## Quick start

```bash
cd motion/ad-kit
export npm_config_cache=/path/to/npm-cache           # only if your npx needs a writable cache

# 1. brand tokens + ad data → a HyperFrames project (+ assets/audio/soundtrack.wav, −14 LUFS)
node build.mjs --brand examples/gruns/brand.json --ad examples/gruns/ads/notes.json \
               --out /tmp/ads/notes-9x16 --format 9x16          # --format 4x5 | 1x1, --no-audio to skip the score

# 2. lint → check (must pass) → render → loudness verify → poster → web copy → contact sheet → copy out
node ship.mjs /tmp/ads/notes-9x16 --final ../../demo/<client>/video-ads --web ../../demo/<client>/page/video
```

`ship.mjs` writes to `<project>/renders/`: `<id>-<format>.mp4` (1080 wide, CRF 16), `.jpg` (poster),
`-web.mp4` (720 wide, ≤ 2.5 MB, faststart), `-web.jpg`, and `-sheet.jpg` (4 key frames: hook, middle, full
scene, end card). Look at the sheet before the ad goes anywhere.

## Layout

```
ad-kit/
  build.mjs              brand + ad → project (index.html, compositions/<style>.html, compositions/endcard.html, assets/)
  ship.mjs               lint/check/render/poster/web/sheet/copy   (--web-max <MB>, default 2.5)
  from_matrix.py         a month's ad matrix → one kit JSON per video cell (copy verbatim + a presentation file)
  lib/schedule.mjs       THE timing source: content → beat-locked times + the sound cue list (deterministic, seeded)
  audio/score.py         music bed (calm | punchy) on the ad's beat grid + UI sounds on the cues, mixed to −14 LUFS
  templates/index.html   root: scene (full length) + end card (from endAt) + one soundtrack
  templates/styles/*.html   the six styles (HyperFrames sub-compositions, <template>-wrapped)
  templates/endcard.html    the shared end card
  examples/gruns/        brand.json, ads/*.json, assets/ (PNG cut-outs are git-ignored: keep them locally)
```

The kit reuses `../otto-kit/fonts/Inter-var-latin.woff2` (neutral UI face) and the instruments in
`../otto-showreel-score/compose.py`.

## How it is driven

**(a) Brand tokens → CSS variables.** `build.mjs` writes the tokens onto each composition's `#root` as
`--c-<token>`. It also writes per-composition ground roles: `--ad-ground`, `--ad-on` (text), `--ad-hi` (the one
accent) and `--ad-sub`. Templates only ever use these variables, never a hex value. The brand display font is
copied to `assets/fonts/brand.woff2` (family `AdKit Brand`), and the UI font to `assets/fonts/ui.woff2`
(`AdKit UI`, Inter by default).

**(b) One JSON per ad → the `D` object.** The ad's content, asset roles and every time from `lib/schedule.mjs`
are baked into the composition. Templates build their DOM from `D` after the fonts load, measure it, and then
register one paused GSAP timeline. Nothing is timed by hand in a template. Change the words and the timing
follows: typing speed, strike, send and pop times, and the end card all snap to the beat grid (`music.bpm`,
120 by default).

### Brand token file (`brand.json`)

```jsonc
{
  "name": "Grüns", "site": "gruns.co",
  "assetRoot": "assets",                                  // relative to this file
  "fonts": { "brand": { "file": "DMSans-var-latin.woff2", "weight": "100 900", "tracking": "-0.04em" },
             "ui": null },                                // null = kit Inter
  "colors": {                                             // this vocabulary is fixed; the values are the brand's
    "bg": "#FFF8E6", "surface": "#FFFFFF", "ink": "#002613", "muted": "#5E6B63", "line": "rgba(0,38,19,.12)",
    "primary": "#007E40", "primaryDeep": "#00572C", "onPrimary": "#FFF8E6",
    "accent": "#E8B411", "onAccent": "#002613", "night": "#002613",
    "neutral": "#ECEBE6",                                 // versus category side, incoming bubbles
    "wash": "#DAECE3"                                     // tints: autocomplete highlight, image panels, avatar
  },
  "assets": { "pack": "pouch-hd.png", "unit": "sachet-front.png", "hero": "gummy.png",
              "photo": "hero-life.png", "logo": "logo.svg" },
  "legal": { "fda": "These statements have not been evaluated by the Food and Drug Administration. …" }
}
```

Grounds are chosen per composition by token name (`scene.ground`, `endcard.ground`). The build checks that the
accent on each ground reaches 3:1 (large-text AA). If it doesn't, the accent falls back to the text colour and
the build prints a warning. Pick a deeper ground instead: Grüns uses `primaryDeep` for green end cards, because
yellow on `#007E40` is 2.7:1.

### Required assets (per client)

| Role | What | Used by |
|---|---|---|
| `pack` | The retail pack (pouch, box, bottle): a **tight-cropped transparent PNG**, ≥ 700 px tall | end card, search result |
| `unit` | One serving or single unit (sachet, can, stick): transparent PNG | end card, versus (right), big (last phrase) |
| `hero` | The macro hero object (a gummy, a pill, a drop, a cookie): transparent PNG, ≥ 500 px tall | big |
| `photo` | A real lifestyle photo with the product (licensed or client-owned) | texts (photo attachment) |
| `logo` | Optional wordmark (SVG/PNG) for end cards where the pack doesn't read as the brand | endcard `logo` |
| brand font | `.woff2` of the display face (DM Sans for Grüns) | end card, versus, big |

Asset roles are optional per style. Only what an ad references is copied.

### Ad data (`ads/<style>.json`)

Common fields: `id`, `style`, `angle` (a note of which strategy angle it serves), `formats`,
`music: { bpm, mood: "calm"|"punchy", key: "F"|"C" }`, `scene: { ground }`, optional `timing: {…}`, and:

```jsonc
"endcard": { "ground": "bg", "headline": "See what's in one pack", "accent": "one pack",
             "sub": "60+ ingredients · 21 vitamins & minerals · 6 g fiber", "fine": "",
             "products": ["pack", "unit"], "logo": null, "legal": null /* or "fda" */, "duration": 3.2 }
```

| Style | Content block | Timing knobs (defaults) |
|---|---|---|
| notes | `note: { meta, title, struck: [..], keep }` | `cps` 19, `titleCps` 16, `startAt` 0.3, `hold` 0.95 |
| search | `search: { placeholder, query, suggestions: [..], pick, result: { site, url, favicon, title, rating?, ratingText?, snippet, image } }`. With no rating, the stars row is left out. A long query shrinks to fit (down to 44 px), and only the completion scrolls. | `cps` 17, `read` 2.7 |
| texts | `thread: { name, initial, stamp, placeholder, avatar?: "brand", messages: [{from:"them"\|"me", text} \| {from:"me", photo:"photo"}] }`. The first message (either side) is already on screen at the start. `avatar: "brand"` gives the brand a coloured avatar (for support threads). | `cps` 21, `dots` 0.7, `photoHold` 0.85, `hold` 1.25, `firstInstant` true |
| versus | `versus: { vs, left: { label, illo:"tub"\|"plate" \| image, rows }, right: { label, image, rows }, footer }`. Row words share one size that fits both columns. The footer is a marker that wraps to two lines. | `rowsAt` 1.5, `footerGap` 0.75, `hold` 2.0 |
| big | `big: { hero, phrases: [{ big, rest? }, …, { big, rest?, product }] }` (a long `rest` wraps to two lines; if the last `product` is the hero itself, the hero settles instead of doubling) | `firstAt` 1.5, `everyBeats` 3, `hold` 2.5 |
| reel | `reel: { vo: [..script..], lines: [..on-screen..], cues: [{ clip: "vo/x-00.wav", line: 0, shot: { asset, kind: "cutout"\|"photo", move: "turn"\|"rise" } }, { clip, line, stat: true }, { clip, line }, …, { clip, endcard: true }] }`. `clip` paths are relative to the ad JSON; a cue without a clip lasts its `dur` (default 2 s): a silent reel. A `stat` line "Label: +20.5%" becomes a count-up card (up to two stack). A cue with no shot and no stat sets its line large. | `startAt` 0.3, `gap` 0.14, `tail` 1.5 |

Durations are computed: `endAt` (always on a beat) + the end card (3.2 s). Keep copy short enough to land at
10–15 s: 3–4 struck lines, 4–7 messages, 3 row pairs, 3 phrases. `schedule.json` in the project shows the result.

## From the monthly ad matrix (`from_matrix.py`)

The copywriter's matrix (`brands/<id>/ads-YYYY-MM.json`) marks faceless video cells with `"format": "video"` and
`"video": { "kit": <style>, "data": "video/YYYY-MM/<cell-id>.json" }`, and the copy lives in the cell's
`data`. One command writes every kit file where the engine looks for it (`brands/<id>/` + that path):

```bash
python3 from_matrix.py --matrix $BRANDS/<id>/ads-2026-10.json --brand $BRANDS/<id>/video/brand.json \
                       --presentation $BRANDS/<id>/video/presentation-2026-10.json
cd ../../platform && python3 otto_creative.py matrix <id> 2026-10 --check     # video cells → ready
```

- **Copy is never rewritten.** It is copied verbatim from the cell, and the engine re-runs compliance on the kit
  file.
- **The presentation file holds only presentation:** per-kit defaults (grounds, music, timing), a role map
  (e.g. `"sachet": "unit"`), reel `cues`, per-cell `products` for end cards that name none, and whitelisted
  `set` switches (`left.illo`, `avatar`, `hero`, `image`, `product`).
- **Priced end cards show priced packs only.** With `brand.json` `"price_safe_products": ["pack"]`, an end card
  that shows a price keeps only those packs. For Grüns that is the Original pouch; the Sugar-Free sachet is
  dropped. Any other `brand.json` asset role (e.g. `kids`, `person`) can be referenced by name.
- **Voice for reels:** one clip per cue, using the house voice (ElevenLabs "Nora" via Higgsfield, see
  otto-motion-director §5). Pauses are capped at ~0.22 s and there is a gentle `atempo` of 1.12 or less. Write
  the brand name phonetically in the *audio prompt only* if TTS mispronounces it ("Greens" for Grüns).
- **Render names:** use `ship.mjs … --name <cell-id>-9x16`. Add a `4x5` build when the cell's sizes include
  `feed`.
- **Engine hookup:** the engine takes a video cell once the cell has a `file` (otto_creative `build_matrix`).
  For client brands that is automatic: `platform/otto_advideo.py` renders every cell the copywriter scripted (beats in
  the cell's `data`, no kit JSON) with this kit — the brand's look from its scan (colours, display font, logo, product
  cut-out / photos), 9:16 plus 4:5 for notes / texts, Meta's 9:16 safe zone checked (`hyperframes check --caption-zone`
  for the top 14 % / bottom 20 %), and sets the cell's `file`, `poster`, `status: "rendered"` and `render`
  (`render.files["4x5"]` is the feed version). A cell with a hand-made kit JSON (like Otto's own launch) is left to
  whoever wrote it: `--check` reports it `ready` with "video not rendered yet". A reel cue without a voice `clip` may
  carry its own `dur` (seconds; otto_advideo's silent reels time each line by its length). `VIDEO_KITS` in otto_styles
  maps `reel` to otto_motion, which is still right for 30–60 s explainer reels; short reel *ads* render here.

## How Otto fills it for a new client

1. **Tokens.** Copy the palette and fonts from `brands/<slug>/brand-profile.md` (VISUAL IDENTITY, or the brand
   guide, which wins) into `brand.json` using the fixed vocabulary above. Get the display font as `.woff2`.
2. **Assets.** Take pack, unit and hero cut-outs from the site scan, and remove backgrounds where needed
   (`hyperframes remove-background` or media-use). Crop tight. Use a lifestyle photo only if it is licensed.
3. **Angles → styles.** For each ranked angle in `angles.json`, pick 2–3 styles from the table above. Copy
   comes from the angle's approved `ad` fields and the proof bank. Numbers only from `strategy.json`, and
   reviews labelled as self-reported where the brand says so.
4. **Compliance.** Run the ad's visible text through the brand's `compliance.json`. Structure/function wording
   only. If any line says "supports digestion" (or similar), set `"legal": "fda"` on the end card.
5. **Build, ship, look.** `build.mjs`, then `ship.mjs`. Read the `-sheet.jpg` (one idea per frame, nothing in
   the corners, the brand colour in every frame, text clear of the bottom band). Only then attach it to the
   campaign.

## Formats

- **9:16 (1080×1920):** all six styles. Key text sits in y 200–1560, x ≥ 30, clear of the Reels/Stories UI.
- **4:5 (1080×1350):** `notes`, `texts` and `endcard` have tuned layouts (used for Grüns). `search`, `versus`
  `big` and `reel` scale their layout by canvas height, but they have not been art-directed at 4:5 yet.
- **1:1:** the end card has a layout. The styles are untested at 1:1.

## Sound

`audio/score.py` reads `sound.json` (written by the build: bpm, duration, `endAt`, mood, and the event list from
the scheduler) and synthesizes:

- **calm**: electric-piano I–vi–IV–V, an 8th-note pluck, a soft kick on 1 and 3 from bar 2, snaps on 2 and 4,
  a 16th shaker, and a sub. The end card resolves to the tonic.
- **punchy**: a riser into the first hit, four-on-the-floor, claps, offbeat bass, a chord stab on every `hit`,
  and an impact on `impact`.
- **UI sounds**: soft key ticks (seeded, varied), return, pen strike, marker swipe with a small chime, dropdown,
  select, enter, card, stars, incoming pop, send whoosh, cross or check, and the end-card sheet whoosh with a
  landing thump. They sit about 12 LU under the bed.

The mix is normalized to −14 LUFS integrated with a true peak of −1 dBTP or lower, measured with ffmpeg's EBU
R128 meter. `ship.mjs` re-measures the rendered MP4 and corrects it if it drifted. Pass `--stems` to write the
bed and UI stems separately. All sound is synthesized in code; there is no licensed or copyrighted music.

## Rules the templates enforce (keep them when you add a style)

- Generic UI only: no platform logos, wordmarks or signature colours (the search UI is not Google, and the chat
  is not iMessage or WhatsApp). The brand's colour replaces the platform's.
- No HUD, no emoji, no fake CTA buttons. Diegetic UI (a composer's send arrow) is fine.
- There is one idea per ad and the brand colour appears in every frame. Motion lands on the beat, with no
  bounce or elastic easing.
- Determinism: one paused timeline, registered with `window.__timelines = window.__timelines || {}` after the
  font-gated build. Every tween after t=0 is a `fromTo` with `immediateRender:false`, and starting states use
  `gsap.set`. There is no `Math.random` (jitter comes from the seeded scheduler) and no `repeat:-1`.
- Ids are prefixed per style (`nt-`, `sr-`, `tx-`, `vs-`, `bg-`, `ec-`) and looked up with `getElementById`.
  Never query `#root…`, because the runtime renames root ids. Toggle visibility with `opacity`, or use
  `"inherit"` and never `"visible"`.
- Once the end card fully covers the scene (`endAt + 0.75`), the scene's stage goes to opacity 0. This keeps
  `check` from grading text nobody can see.
- Text breaks are explicit and balanced, preferring a break after punctuation (notes lines, chat bubbles,
  end-card headline), so strikes, markers and bubbles always hug the real lines. Chrome's `text-wrap: balance`
  measures differently from what it paints, so the templates don't rely on it.
- `check` must pass before render (`ship.mjs` refuses otherwise). The remaining warnings are expected and cluster
  in the 0.6 s where the end card sheet slides over the scene.

## Reusable vs client-specific

- **Reusable (the kit):** all templates, the scheduler, the score, build/ship, the end card, the neutral tub
  illustration, the generic search, chat and notes UIs, and the layout rules.
- **Client-specific (data):** `brand.json` (colours, fonts, asset files, legal line), each `ads/*.json` (copy,
  suggestions, messages, rows, phrases, end-card lines, grounds, bpm/mood), and the cut-out PNGs and photo.
