---
format: 1080x1920
duration: 40s
message: "You run the business; Otto runs the marketing."
arc: problem → product → how it works (read, plan, make) → control (approve) → result (report, growth) → CTA
audience: EU small-business owners with no time for marketing
mode: autonomous
music: Otto bed (synthesized, 120 BPM, A minor, soft pads + pluck, light kick)
brand: Otto
---

## Video direction

- **System:** `frame.md` (Otto, vertical). Light ground `#F5F5F7` everywhere; white cards with the card shadow;
  ink `#1D1D1F`; one accent, cobalt `#2447F0`; success green `#1B7F4B` only for approved / up. Display type Inter
  Tight 600–650; UI Inter. Component geometry from `assets/kit.css` (`ok-*`), scaled up for a phone-viewed video.
- **Readability rule (non-negotiable):** this film is watched on a phone at ~0.36× — UI text is **never below 36px**
  (small labels 30px), headline 84–104px, cards 900–960px wide. Do NOT put UI inside a phone mockup (it becomes
  unreadable); show the UI itself as big cards.
- **The one governing device — the Otto square:** cobalt rounded square with a white inner outline (`.ok-mark`).
  Canonical size **140px at (540, 900)**. It carries every seam: chips collapse into it (F1), it stamps the logo
  (F2), becomes the website field's caret (F2→F3), the calendar's today marker (F4), morphs into the approval
  card (F5), the chart's source (F7) and the logo again (F8).
- **Zones:** headline zone y 250–520 (top-centred, max 2 lines); content zone y 560–1560; caption band
  y ≥ 1594 stays empty; nothing load-bearing outside x 60–1020.
- **Motion grammar:** reveal every element on its spoken cue (cues below are frame-local seconds from the real
  voice); entrances expo.out 0.5–0.8s, moves power3.inOut, exits power2.in 0.25–0.35s; no back/elastic/bounce,
  no jitter, no glitch; each frame ends on a held, readable state unless its handoff says otherwise.
- **Seams:** every `transition_in` is `cut`; continuity is carried by the `handoff` geometry (match cuts).
- **Chrome:** none. No topbar, no corner labels, no timecode, no page numbers.
- **Negative list:** HUD chrome, emoji, stock-video feel, gradients/glow/glass, particles, a new palette per
  scene, tiny UI, text in the caption band, "paste your website", "autopilot".

## Frame 1 — Who runs the marketing

- type: hook
- duration: 3.26s
- transition_in: cut
- status: animated
- src: compositions/frames/01-hook.html
- voiceover: "You run the business. So who runs the marketing?"
- cues: You 0.00 · run 0.22 · business 0.66 · So 1.43 · who 1.69 · runs 1.91 · marketing 2.51
- handoff_out: { element: "Otto square", x: 540, y: 900, size: 140, ground: "#F5F5F7", other: "everything else gone, square at rest at 3.26" }

Scene 1 (0.00–1.40s): “You run the business.” (Inter Tight 650, 96px, ink, centred, y≈330) rises per word on You/run/business. At 0.30 the square scales in at (540, 900); from 0.66 chore chips spring out of it one every 0.12s into a loose stack filling the content zone (white pills 88px tall, Inter 500 38px, 28px cobalt square icon; copy: “3 posts”, “5 stories”, “1 reel”, “Meta ads”, “Google ads”, “Captions”, “Replies”, “Visuals”, “A report”, “Competitor check”; rotations from a fixed −3°…+3° list by index).
Scene 2 (1.40–2.90s): line 2 “So who runs the marketing?” (84px) rises under line 1 on So/who/runs; “marketing?” lands in cobalt on 2.51. Chips keep a slow push-in (1.00→1.04).
Scene 3 (2.90–3.26s): headline exits up (power2.in); every chip is pulled back into the square (power3.in, stagger 0.02s); square at rest at 3.26.

## Frame 2 — Meet Otto

- type: product_intro
- duration: 4.0s
- transition_in: cut
- status: animated
- src: compositions/frames/02-meet.html
- voiceover: "Meet Otto, your marketing department in your pocket."
- cues: Meet 0.00 · Otto 0.30 · your 1.13 · marketing 1.29 · department 1.73 · in 2.37 · your 3.01 · pocket 3.21
- handoff_in: { element: "Otto square", x: 540, y: 900, size: 140 }
- handoff_out: { element: "website field", rect: "x 90→990, y 700→830 (900×130), radius 65, white, card shadow", square: "72px at (170, 765)", text: "none yet (placeholder hidden)", other: "wordmark + tagline gone by 4.0" }

Scene 1 (0.00–1.10s): on “Otto” (0.30) the square stamps (1.2→1, expo.out) while sliding to lockup position (square centre (330, 820)); wordmark “Otto” (Inter Tight 650, 190px, −0.045em) wipes in to its right (left edge x≈430). Lockup centred as a unit.
Scene 2 (1.10–3.40s): tagline under the lockup, centred, Inter Tight 600 64px: “Your marketing department,” (muted) on 1.13 and “in your pocket.” (ink, “pocket.” cobalt) on 2.37. Hold.
Scene 3 (3.40–4.00s): wordmark and tagline exit (power2.in); the square shrinks to 72px and slides to (170, 765) while a white field grows out of it to the right (x 90→990, 130 tall, radius 65) — handoff geometry at 4.0.

## Frame 3 — Otto reads your business

- type: how_it_works
- duration: 6.05s
- transition_in: cut
- status: animated
- src: compositions/frames/03-reads.html
- voiceover: "Start with your website. Otto reads your colours, your tone, your customers, and your competitors."
- cues: Start 0.00 · website 0.60 · Otto 1.39 · reads 1.41 · colours 2.03 · tone 2.92 · customers 3.87 · competitors 5.18
- handoff_in: { element: "website field", same geometry as frame 2 handoff_out }
- handoff_out: { element: "brand profile card", rect: "x 90→990, y 600→1500, radius 32, white, card shadow", content: "title + 4 rows settled", other: "headline gone" }

Scene 1 (0.00–1.35s): headline “Start with your website.” (84px, y≈380) on 0.00; the URL “happygardeneu.com” types into the field (Inter 500 44px) 0.10→0.90; a cobalt “Read” pill button at the field's right end presses on 1.10.
Scene 2 (1.35–2.00s): on “Otto reads” the headline swaps to “Otto reads your business.”; the field lifts to the top of the content zone (y 560–690) and a white brand-profile card opens beneath it (x 90→990, y 720→1500) with title “Brand profile” (Inter Tight 600 48px) and note “Filled in by Otto” (Inter 500 30px muted). A cobalt scan line sweeps the field once.
Scene 3 (2.00–5.60s): rows land on their words, each row = label (Inter 500 30px muted) above value (Inter 500 40px ink), hairline between rows: “Colours” with four 56px swatches #FFBC00 #0E252C #31856C #FFFFFF on 2.03 · “Tone” “Educational, trust-first.” on 2.92 · “Customers” “Petra, 52: “I haven’t slept well in years.”” on 3.87 · “Competitors” chips “Nordic Oil · Naturecan · CBD Vital” on 5.18.
Scene 4 (5.60–6.05s): the field and headline exit up; the card glides to the handoff rect (y 600→1500).

## Frame 4 — It plans the whole month

- type: how_it_works
- duration: 6.81s
- transition_in: cut
- status: animated
- src: compositions/frames/04-plans.html
- voiceover: "Then it plans your whole month. Posts, stories, short reels, and ads on Meta and Google."
- cues: Then 0.00 · plans 0.44 · whole 1.06 · month 1.36 · Posts 2.15 · stories 2.78 · reels 3.73 · ads 4.76 · Meta 5.44 · Google 6.16
- handoff_in: { element: "brand profile card", rect: "x 90→990, y 600→1500" }
- handoff_out: { element: "Otto square", x: 540, y: 900, size: 140, other: "everything else gone, square at rest at 6.81" }

Scene 1 (0.00–1.90s): the card's rows fade and the card morphs into a calendar panel (x 60→1020, y 560→1080, radius 32); headline “It plans your whole month.” on 0.44 (84px). Panel header “October 2026” (Inter Tight 600 44px). 7×5 day tiles (≈124×80, radius 12) fill row by row 0.60→1.60, each tile a photo from `assets/img` (fixed cycle). The Otto square (40px) marks today (Oct 7).
Scene 2 (2.10–5.20s): below the calendar a 2×2 grid of format cards (each 440×210, white, radius 24; photo left 180 wide, label right Inter Tight 600 48px): “Posts” (hg-spectrum) on 2.15 · “Stories” (coffee-pour) on 2.78 · “Reels” (a muted `<video>` of `assets/hg-reel.mp4`, media from 6.0s) on 3.73 · “Ads” (surf-lesson) on 4.76.
Scene 3 (5.20–6.40s): two channel pills under the grid (Inter 600 40px, 96px tall, white with ink text): “Meta” lights (cobalt ring) on 5.44 and “Google” on 6.16.
Scene 4 (6.40–6.81s): everything collapses into the square at (540,900) (power3.in); square at rest at 6.81.

## Frame 5 — Nothing goes out until you approve it

- type: proof
- duration: 5.36s
- transition_in: cut
- status: animated
- src: compositions/frames/05-approve.html
- voiceover: "Nothing goes out until you approve it. One tap from your phone."
- cues: Nothing 0.00 · goes 0.42 · out 0.68 · until 1.14 · you 1.62 · approve 1.82 · One 3.13 · tap 3.39 · phone 4.63
- handoff_in: { element: "Otto square", x: 540, y: 900, size: 140 }
- handoff_out: { element: "approval card", rect: "x 90→990, y 560→1480, radius 32", state: "approved (green 'Approved · Tue 18:00' bar)", other: "headline 'One tap.' held" }

Scene 1 (0.00–0.50s): the square morphs (grows and opens) into the approval card (x 90→990, y 560→1480): a message header “Otto” with 48px square avatar (Inter 600 36px) · photo `hg-spectrum.jpg` 900×560 · caption “Full, broad or isolate? Same plant, three products.” (Inter 500 38px) · meta “Instagram · Tue 18:00” (Inter 400 30px muted) · a button row 120px tall: “Approve” (cobalt fill, white Inter 600 40px) · “Edit” (ink, Inter 600 40px).
Scene 2 (0.00–2.40s): headline “Nothing goes out until you approve it.” (84px, 2 lines) rises word-group by cue: Nothing goes out · until you · approve it (“approve” cobalt).
Scene 3 (2.40–4.20s): a touch indicator (80px circle, rgba(29,29,31,.18), 3px white ring) glides to Approve (2.40→3.10); headline swaps to “One tap.” (104px) on 3.13; press on 3.39 (indicator 0.85, button darkens) → button becomes a green bar “Approved · Tue 18:00” with a white check drawing in (3.50–3.90).
Scene 4 (4.20–5.36s): hold; on “phone” (4.63) the card gives one subtle settle (scale 1.01→1). Held state at the end.

## Frame 6 — The morning report

- type: proof
- duration: 6.51s
- transition_in: cut
- status: animated
- src: compositions/frames/06-report.html
- voiceover: "Every morning, a short report. If something drops, the fix is already drafted."
- cues: Every 0.00 · morning 0.48 · short 1.42 · report 1.72 · If 2.63 · something 2.81 · drops 3.17 · fix 4.22 · already 5.00 · drafted 5.54
- handoff_in: { element: "approval card", rect: "x 90→990, y 560→1480", state: "approved" }
- handoff_out: { element: "Otto square", x: 540, y: 900, size: 140, other: "everything else gone, square at rest at 6.51" }

Scene 1 (0.00–0.50s): the approval card slides down and out (power2.in); headline “Every morning, a short report.” (84px) rises on 0.00/0.48.
Scene 2 (0.50–2.50s): a notification banner (x 90→990, 150 tall, radius 40, Otto square 72px, “Otto · 07:35” Inter 600 36px, “Your morning report is ready” Inter 400 36px) drops in on 0.60; on “report” (1.72) it expands into the report card (x 90→990, y 560→1180): title “Yesterday” (Inter Tight 600 52px) and rows (label Inter 400 38px muted, value Inter 600 44px tabular): Spent €18.40 · Leads 7 · Cost per lead €2.63 — rows land 1.80 / 2.00 / 2.20.
Scene 3 (2.60–6.00s): headline swaps to “If something drops,” on 2.63; an alert card (x 90→990, y 1220→1540) appears: a 900×150 line chart that draws in, dipping on “drops” (3.17), text “Reach fell 18% on Tuesday.” (Inter 500 38px); on “fix” (4.22) the headline becomes “the fix is already drafted.” and a cobalt button “Approve fix” (100px tall) slides into the alert card on “drafted” (5.54).
Scene 4 (6.00–6.51s): everything collapses into the square at (540,900); at rest at 6.51.

## Frame 7 — Every month, you see what grew

- type: proof
- duration: 3.43s
- transition_in: cut
- status: animated
- src: compositions/frames/07-grew.html
- voiceover: "And every month, you see exactly what grew."
- cues: And 0.00 · every 0.22 · month 0.54 · you 1.26 · see 1.48 · exactly 1.76 · what 2.26 · grew 2.68
- handoff_in: { element: "Otto square", x: 540, y: 900, size: 140 }
- handoff_out: { element: "Otto square", x: 540, y: 900, size: 140, other: "everything else gone, square at rest at 3.43" }

Scene 1 (0.00–2.70s): headline “Every month, you see what grew.” (84px, 2 lines) builds on the cues. The square drops to the chart baseline (y 1400) and splits into four bars (180 wide, gap 40, radius 18/18/6/6, max height 700): Aug 0.46 · Sep 0.63 · Oct 0.81 (#D9DEF9) · Nov 1.0 (#2447F0), rising on 0.54 / 1.26 / 1.76 / 2.26; month labels (Inter 500 34px muted) below.
Scene 2 (2.68–3.10s): on “grew” a big metric lands above the Nov bar: “+22% reach” (Inter Tight 650 96px, cobalt) with “Example month” (Inter 400 30px faint) under the chart.
Scene 3 (3.10–3.43s): bars and text collapse into the square (power3.in); at rest at 3.43.

## Frame 8 — Scan your site

- type: cta
- duration: 4.45s
- transition_in: cut
- status: animated
- src: compositions/frames/08-cta.html
- voiceover: "Scan your site for free. Link in bio."
- cues: Scan 0.00 · site 0.64 · free 1.28 · Link 1.99 · bio 2.09
- handoff_in: { element: "Otto square", x: 540, y: 900, size: 140 }

Scene 1 (0.00–0.60s): the square stamps and the lockup forms (same geometry as frame 2: square centre (330,820), wordmark 190px), then the lockup rises to y≈640 by 0.60.
Scene 2 (0.60–1.90s): a white field (x 90→990, y 900→1030, radius 65) with placeholder “yourcompany.com” (Inter 500 44px faint) and a cobalt button “Scan my site” (Inter 600 40px, inside the field's right end) appears on “site” (0.64); line “Free. No signup.” (Inter 500 38px muted) on “free” (1.28), y≈1110.
Scene 3 (1.99–4.45s): “Link in bio” (Inter Tight 600 56px, cobalt) on 1.99, y≈1250; small legal “Figures shown are illustrative.” (Inter 400 26px faint) at y≈1500. From 2.60 nothing moves — a still end card.
