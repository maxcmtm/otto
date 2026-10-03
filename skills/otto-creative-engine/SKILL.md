---
name: otto-creative-engine
description: "Otto's creative engine — merged from CreativeGod (ad-creative-prompting) and Facebook Ads Master. Auto-builds a Strategic Profile per brand from their website (no interview), extracts visual identity (colors/logo/style) so every creative matches THEIR brand, then generates on-brand visuals + copy. Use when onboarding a new Otto customer, generating posts/ads for any Otto brand, or refreshing a brand profile."
---

# Otto Creative Engine

**The core rule:** the customer never fills a questionnaire. They give a URL (+ socials if they have them). Otto scans, fills the Strategic Profile FOR them, and only asks about genuine gaps — max 3-4 questions, ever. Design style always comes from THEIR brand, never from a generic Otto look.

## Pipeline: URL → Strategic Profile → On-brand creatives

### Step 1 — Scan (automatic)
Given the customer's website (from onboarding):
1. Fetch homepage + key pages (about, products/services, testimonials/reviews, pricing).
2. **Visual identity extraction:**
   - Colors: `curl -sL <url> | grep -oE '#[0-9a-fA-F]{6}' | sort | uniq -c | sort -rn | head -12` + check `theme-color` meta. Top non-neutral hits = brand palette.
   - Logo: og:image, `<img>` with "logo" in src/alt/class. Download to `brands/<slug>/logo.png`.
   - Fonts + vibe: heading font, photography style (real people / product shots / illustration), light vs dark.
3. **Voice + market extraction:** language(s), tone (clinical/warm/street/premium), review quotes verbatim (customer language = copy gold), trust anchors (certs, lab tests, guarantees), price points.
4. If they gave FB/IG pages: pull recent posts + (if available) past ads for winning-angle analysis (see cmtm/terapia-winning-ads-analysis.md as the reference format — rank by CPL/engagement, extract WHY each won).

### Step 2 — Fill the Strategic Profile (automatic draft)
Fill `brands/BRAND-PROFILE-TEMPLATE.md` → save as `brands/<slug>/brand-profile.md`. Every section gets filled by inference from the scan — avatars, pains, triggers, objections, angles included. Mark inferred-but-unverified items with `(?)`.

### Step 3 — Confirm gaps only (customer touch, ≤4 questions)
Send the customer a short summary + only the questions the scan couldn't answer (typically: price if hidden, best-performing past angle, top objection they hear on calls, proof assets they have offline). Their answers overwrite the `(?)` items. Profile approved → locked as creative source of truth.

### Step 4 — Generate creatives (on-brand, always)
Every visual/copy generation MUST read `brands/<slug>/brand-profile.md` first and obey:
- **Palette:** only brand colors from VISUAL IDENTITY (+ neutrals). Never Otto default colors.
- **Logo:** placement per brand guide (upload as Leonardo image reference — flow below).
- **Copy voice:** the brand's tone + real customer language quotes from the profile.
- **Angles:** pick from WINNING ANGLES, one angle per creative, hook first.
- **Compliance:** obey the profile's compliance section (CBD/mental-health/etc. — Meta restricted categories).

## Leonardo generation (GPT Image 2) — used by `platform/genvisuals.py`
- `POST https://cloud.leonardo.ai/api/rest/v2/generations`, Bearer key (see otto-secrets).
- Body: `{"model":"gpt-image-2","parameters":{"width":W,"height":H,"prompt":"...","quality":"HIGH","quantity":1,"prompt_enhance":"OFF"},"public":false}`
- Ratios: feed 4:5 = 848×1264 (best FB/IG), square 1024², stories 9:16 = 768×1376.
- No style_ids/seed/guidance — style lives entirely in the prompt: always include brand hex colors, visual motifs, and "leave clear space bottom-right for logo" (or per brand guide).
- Logo/reference images: `POST /api/rest/v1/init-image` → S3 upload → use id in `guidances.image_reference` (max 6, used as-is).
- Poll `GET /api/rest/v1/generations/{id}` every 15-20s until COMPLETE. ~$0.20/image HIGH.
- Download result with a browser User-Agent (403 otherwise).

## Prompt recipe for on-brand ad visuals
```
[FORMAT] ad creative for [BRAND], [industry].
Brand palette: [hex list — mandatory, dominant].
Visual style: [from profile: premium/warm/clinical/... + motifs, e.g. "neural glow paths, cosmic dark background"].
Scene: [angle-specific — the avatar's moment: pain, dream outcome, or proof].
Text on image: "[hook ≤6 words, brand language]" in [font vibe], high contrast.
[Logo band/space instruction per brand guide]. No generic stock look, no watermarks.
```

## Ad matrix — every Meta campaign, angles × styles (Quill fills it)
**Automatic since Oct 2026:** `platform/otto_copy.py ads --brand <slug>` (the copywriter on the Claude API) writes this
month's copy by these rules — `angles.json` when missing, every concept's headlines / primaries / description / cta, every
cell's `data` (video beats included), creator briefs on plans that have them — right after `otto_ads.py plan`, after a
trial's first week and in the daily `copy` job. Fill or fix by hand only what it held (owner card "Ad copy held for review",
the draft in the item's `"copy"."draft"`); never overwrite copy a person wrote (its `"copy".by` is not `otto_copy`).
**Rule (Max, 2026-09-29):** paid Facebook never runs one editorial static per angle. It runs many angles × many executions,
image *and* video, the way Grüns does (`research/GRUNS-AD-LIBRARY-2026-09.md`: 823 ads, 32 angles, 59 styles; every serious
angle in ~9.5 styles, 63 % video, 1-2 headlines reused over many visuals). The unit is `brands/<slug>/ads-<YYYY-MM>.json`
(format + rules: `platform/otto_styles.py` docstring).

**The standard** (`otto_styles.LAUNCH_RULES`, checked by `--check`):
- **6 angles, one per angle family:** pain (the problem in the customer's words) · identity (one specific person / life
  stage) · enemy (what they use today and why it fails) · experience (taste, ease, format) · offer (price, bundle,
  guarantee) · moment (season, drop, collab; month 1 may use a second identity angle). ≥1 comes from competitor research.
- **6 styles per angle in ≥4 style families**, one per slot: ① UGC talking-head video by a **real creator** (format
  `creator`) ② faceless video (ad kit: text-overlay POV, or reel: voiceover b-roll) ③ product static (product_hero /
  macro_hero / ingredients) ④ comparison static (before_after / us_vs_them) ⑤ native screenshot static (notes_app /
  text_message / search / social_post) ⑥ proof or humor static (review_cards / quote / big_number / meme-style editorial).
  Plus a **price card** (`offer`) on the offer angle and on every hot-stage angle.
- **≥50 % video**: one of slots ③-⑥ per angle runs as its motion version (us_vs_them → versus kit, big_number → big, …);
  keep ≥2 statics per angle. Story 9:16 on ≥50 % of cells.
- **Micro floor** (evergreen under ~€36/day): 4 angles (pain, identity, enemy, offer) × 5 styles (slots ①-⑤), never
  fewer than 4 style families. `otto_ads.py plan` picks it from the budget.
- **Refresh after launch:** +2 new creatives per angle per week (set `"added": "YYYY-MM-DD"` on the cell), re-cut a
  winner first, at least one on a style the angle has not run. `--check` reports it.

1. **Skeleton.** `otto_ads.py plan <slug> <YYYY-MM>` writes it (or `python3 platform/otto_creative.py matrix <slug>
   <YYYY-MM> --plan [--preset micro | --budget <daily>]`): angles assigned to families, styles picked per slot by fit and
   by what the brand can back up (no review styles without verbatim reviews, no product styles without a product image,
   no price card without a real offer). Every cell carries a `brief` — read it, it names the proof ids to use.
2. **The catalogue.** `python3 platform/otto_styles.py list` prints every style: template, family, sizes, video kit, the
   data fields (`*` = required), what the brand needs for it, and the slots.
3. **Write the copy per angle, not per cell:** `headlines` (1-2, ≤40 chars, reused on all the angle's visuals — the test is
   about the visual), `primaries` (2-3, compliant benefit copy; the edgy line lives in the creative), `description`, `cta`
   (a Meta button type such as `SHOP_NOW`, or empty = the campaign's). A cell may override one only when it must.
4. **Fill every cell's `data`** with the style's render fields. Image cells render feed 4:5 **and** story 9:16 where the
   size list says so. **Video cells** (`"format": "video"`): write the ad-kit data JSON at the cell's `video.data` path
   (relative to `brands/<slug>/`; format = `motion/ad-kit/examples/<brand>/ads/<kit>.json`); otto_motion renders it.
   **Creator cells** (`"format": "creator"`): write `creator.hook` (first 2 s), `creator.script` (20-40 s, in a real
   person's words, no results claims), `creator.shot_list`, and the disclosure (Paid partnership + #ad). The cell stays
   `planned` until the real creator's footage arrives: then set `file` (the video), `poster` (optional), `creator.name`
   and `creator.consent: true`. **Never an AI-generated person presented as a customer** (FTC / Meta deception) — `--check`
   refuses it; a video without a real person is the faceless slot.
5. You may swap a cell's style, add cells or park one (`"status": "dropped"`) — the slots and counts above still hold.
6. `python3 platform/otto_creative.py matrix <slug> <YYYY-MM> --check` must exit 0 before launch day (coverage gaps, copy
   gaps, unwritten / invalid cells, compliance violations; `planned` creator cells are fine). `--render /tmp/<slug>`
   renders every ready cell to look at.

**Write each style natively** — it must look like a person made it, not the brand:
- **notes_app** — a phone Notes list in the customer's voice, built from the persona's `words` and the pains ("Things I
  stopped buying: ~~greens powder~~, ~~the shaker~~…"). Lowercase is fine. No brand-speak, no claim the proof bank can't back.
- **search** — the query people really type ("greens that actually taste good", lowercase, as typed), suggestions people
  would really see, or a results page with the brand's own listing (title / snippet from the site; rating only from
  proof_bank). Never a search engine's logo or colours.
- **text_message** — two friends, one asks, the other recommends it in plain words. It is a dramatisation: no invented
  results or health outcomes, and a customer quoted in it is verbatim from proof_bank. Or clearly the brand replying.
- **social_post** — the brand's own post, or a real customer's post verbatim, with consent. **ugc_caption** — a real
  photo of a person (never a packshot, never generated), 1-3 short first-person captions, no results claims.
- **Reviews verbatim only** (quote, review_cards): word for word from `strategy.json` proof_bank (`rv*`) or the scanned
  quotes; shorten only with "…". `--check` refuses anything else. Names as in the source (first name + initial).
- **us_vs_them / comparison / before_after** — the brand against a *generic category* ("Greens powders", "A shelf of
  bottles"), never a competitor's name, logo or look-alike pack: any name from `competitors.json` anywhere in the ad blocks
  the cell. Rows must be true; ties shown as ties. before_after is a routine or a chore, never bodies or symptoms.
- **Numbers** (big_number, rating lines, search ratings) and **offers** only from proof_bank / `strategy.json` offers,
  with the recurring price next to any intro price.
- Every cell's texts — a creator's script included — go through `brands/<slug>/compliance.json`: a violating cell is
  skipped and reported, never rendered.

**How it runs:** `otto_ads.py launch` puts the matrix on Meta as one campaign with campaign budget optimisation and **one
ad set per angle**, each style an ad (the 9:16 render placed on Stories / Reels), so Meta tests styles inside a concept
and concepts against each other. Rules change per matrix only through its `"preset"` / `"rules"` fields and only with
Max's OK (e.g. `{"slots": [...without "product"], "min_product": 0}` for a service business with nothing to photograph).

## From Facebook Ads Master (metapublish) — adopted practices
- **Landing/copy alignment:** every claim in a creative must exist on the customer's site or proof assets — never invent numbers, certs, or guarantees. If a claim isn't verifiable in the profile, cut it.
- **Creative intake:** customer-supplied assets (logos, photos, ZIPs via Drive) get verified (open, inspect, confirm contents) before use; store under `brands/<slug>/assets/`.
- **Restricted categories:** CBD, mental health, employment, finance → check profile compliance section before building paid creatives; organic-first when Meta restricts.

## Winning-ads memory (per brand)
After real performance data exists (M2+), maintain `brands/<slug>/winning-ads-analysis.md`: rank by CPL/CTR, note message + why it won. New creatives iterate on winners, don't start from zero. Reference example: `brands/cmtm/terapia-winning-ads-analysis.md`.
