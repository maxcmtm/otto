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

## From Facebook Ads Master (metapublish) — adopted practices
- **Landing/copy alignment:** every claim in a creative must exist on the customer's site or proof assets — never invent numbers, certs, or guarantees. If a claim isn't verifiable in the profile, cut it.
- **Creative intake:** customer-supplied assets (logos, photos, ZIPs via Drive) get verified (open, inspect, confirm contents) before use; store under `brands/<slug>/assets/`.
- **Restricted categories:** CBD, mental health, employment, finance → check profile compliance section before building paid creatives; organic-first when Meta restricts.

## Winning-ads memory (per brand)
After real performance data exists (M2+), maintain `brands/<slug>/winning-ads-analysis.md`: rank by CPL/CTR, note message + why it won. New creatives iterate on winners, don't start from zero. Reference example: `brands/cmtm/terapia-winning-ads-analysis.md`.
