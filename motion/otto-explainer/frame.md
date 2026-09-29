---
name: otto
canvas: "#F5F5F7"
night: "#0B0B0D"
colors:
  canvas: "#F5F5F7"
  surface: "#FFFFFF"
  ink: "#1D1D1F"
  muted: "#6E6E73"
  faint: "#86868B"
  hair: "rgba(60,60,67,.16)"
  accent: "#2447F0"
  accent-night: "#5B75FF"
  accent-tint: "#EEF2FF"
  success: "#1B7F4B"
  success-night: "#34C77B"
  night: "#0B0B0D"
  night-2: "#17171B"
  on-night: "#F5F5F7"
  on-night-muted: "#A1A1A6"
fonts:
  display: "Inter Tight (assets/fonts/InterTight-var-latin.woff2), weight 600–650, letter-spacing −0.04em"
  ui: "Inter (assets/fonts/Inter-var-latin.woff2), weights 400/500/600"
---

# Otto — vertical explainer system (1080×1920)

**One accent on a neutral ground.** Light scenes: canvas `#F5F5F7`, white surfaces, ink `#1D1D1F`, muted
`#6E6E73`. The only saturated colour is Otto cobalt `#2447F0` (on the night ground use `#5B75FF` for text
accents; the cobalt square itself stays `#2447F0`). Content photos bring their own colour — nothing else does.
Success green `#1B7F4B` (night `#34C77B`) only for "approved / live / up".

**Type.** Display: Inter Tight 600–650, tight tracking (−0.04em at ≥100px, −0.03em at 60–90px, −0.02em
below). UI text: Inter 400/500/600, sentence case, never uppercase-tracked labels. Scale on 1080×1920 (viewed on a phone at ~0.36×): display L 104px · M 84px · S 64px; UI text never
below 36px (labels 30px minimum); cards 900–960px wide. One accent word per headline max, in cobalt.

**Depth.** White cards with `0 1px 2px rgba(0,0,0,.05), 0 18px 48px rgba(0,0,0,.10)`; floating objects (phone,
browser) `0 2px 6px rgba(0,0,0,.06), 0 40px 90px rgba(0,0,0,.18)`. Radii: cards 16–28px, pills 999px,
phone 68px. No glass blur soup, no glow, no gradients except photo content.

**Components.** Use `assets/kit.css` (classes `ok-*`): the Otto square (`.ok-mark`), phone, approval card,
Instagram post, browser, brand-profile card, calendar day tiles, metric + bars, briefing message, notification
banner, Meta and Google ad previews. Inline the rules you use into your frame's `<style>` (namespace them to
your frame) and load fonts with `@font-face` pointing at `assets/fonts/…` and images at `assets/img/…` — paths resolve from
the project root (the frame is injected into `index.html`).

**Motion.** GSAP: entrances `expo.out` 0.5–0.9s; moves `power3.inOut` 0.5–1.0s; exits `power2.in`
0.25–0.4s. No back / elastic / bounce, no infinite loops, no random jitter, no glitch, no strobe. State changes
land on the beat anchors given in the frame block.

**Banned (AI-slop kit).** Corner brackets / crop marks, timecode, "REEL 2026", BPM or fps readouts, "01/08"
counters, bouncing ball / easing graphs, particle spheres, isometric cube fields, chrome/iridescent blobs,
neon, mesh-gradient orbs, RGB-split glitch, emoji, any text in the outer 6% of the frame (x<115, x>1805,
y<65, y>1015) — for this vertical film: hero content inside x 60–1020, y 250–1560; the caption band
(y ≥ 1594) stays empty.
