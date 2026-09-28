---
format: 1080x1920
duration: 57s
message: "Full, broad, isolate: same plant, three different products — know exactly what is in your bottle."
arc: listicle with concept-explainer (hook → name the team → full → broad → isolate → how to choose → proof + CTA)
audience: EU adults 25–60 curious about CBD but confused by labels; many want zero THC
mode: autonomous
music: soft organic acoustic underscore, warm, minimal, gentle pulse, 88 bpm, no vocals
brand: Happy Garden (happygardeneu.com)
---

## Video direction

- **Palette system (frame.md, Happy Garden mapping):** gravity ground = deep teal `green` #0E252C (frames 2–5, 7); reading ground = warm white `cream` #FFFDF6 (frames 1, 6). Accent = brand yellow `pink` #FFBC00, used for ONE thing per frame (the CBD chip, the spectrum label, the answer pill, the CTA). Hemp green `green-lite` #31856C only on the terpenes chip and the "0% THC" stamp. Chips on teal are `cream` fills with teal ink; never yellow text on white; two surface tones per frame max.
- **Type:** Source Serif 4 weight 500 for every headline and spectrum label (display ramp scaled to the 1080 short edge); Inter 600 sentence case for chips, labels, topbar. No mono, no uppercase chrome.
- **The stage (frames 2–5 share it exactly — continuity is the explanation):** a vertical stack of five pill chips, centred horizontally, each ~720×128 px, pill radius 64px, 28px gap, stack top at y≈560, top→bottom: `CBD` (yellow fill, teal ink, the hero) · `CBG` (cream) · `CBN` (cream) · `Terpenes` (hemp green fill, cream ink) · `THC · trace` (transparent, 2px dashed cream outline, cream ink). Each chip has a small leading glyph: a hexagon (cannabinoid) for CBD/CBG/CBN/THC, a simple leaf outline for terpenes (inline SVG, 36px, 2px stroke). Spectrum label zone above the stack, top of label at y≈300. Right-edge bracket zone x≈930–960 for the yellow set bracket.
- **Motion grammar:** smooth long-tail settles (`power3`, `expo.out` on fast arrivals), never bouncy. Reveal every element on its spoken cue (VO-paced), nothing front-loaded; the stage continuing across frames 2→5 is continuity, not front-loading. Seams inside a frame are velocity-matched cuts (`cut-catalog.md`). Removals are the signature move of frames 4–5: a chip lifts (y −24px, opacity → 0, blur 6px) and the stack re-centres on a 0.6s `power3` glide.
- **Rhythm / held beats:** frame 1 is fast and percussive; frames 3 and 5 end on a deliberate held read (≥0.8s still); frame 6 is brisk; frame 7 lands and holds still for the last 1.2s. Only sanctioned aliveness during holds: subtle jitter (`sine-wave-loop`, low amplitude) on the one hero element.
- **Chrome:** a quiet topbar on every frame — "Happy Garden" (Inter 600) left, "CBD, explained" (Inter 500, 70% opacity) right, 64px from the top, 2px hairline below it in the frame's accent. No footline, no page numbers.
- **Captions:** on; the caption band is the bottom 17% (y ≥ 1594) — nothing load-bearing below y≈1560.
- **Negative list:** no stock photos, no leaf/weed clip-art, no glow/bokeh/purple "AI" gradients, no box-shadows (flat paper depth), no medical words on screen (treat, cure, heal, relief, anxiety, pain), no marijuana imagery, no emoji, no slideshow (front-load then freeze), no screensaver (independent floating), no infinite loops, no Math.random.


## Frame 1 — Three labels, one plant

- type: hook
- duration: 6.35s
- transition_in: cut
- persuasion: Rhetorical question + frame-then-fill (show the three confusing labels, then the question they raise)
- beat: Recognition + curiosity
- scene: The three label words stack in, then collapse under one question
- voiceover: "Full spectrum. Broad spectrum. Isolate. Same plant — so what's actually in your bottle?"
- status: animated
- src: compositions/frames/01-hook.html
- blueprint: kinetic-type-beats (Adapt)
- focal: the three label words, then the question "What's actually in your bottle?"
- roles: label words = foreground subject · cream ground with a faint 2px hairline grid at 6% opacity = background · topbar = supporting
- sfx: none

Adapt: keep the kinetic-type-beats signature (a statement built across beats onto a payoff line); the three spectrum words stack as three beats, then compress to make room for the payoff question.
Scene 1 (0.00–1.15s): cream ground; "Full spectrum." enters alone at y≈520, Source Serif display ~118px teal, left-aligned at x=96, per-word staggered reveal on the VO's "Full spectrum" (`dynamic-content-sequencing`), smooth `power3` settle.
Scene 2 (1.15–2.20s): on "broad spectrum" (1.19s) "Broad spectrum." lands directly beneath at y≈660, same size and alignment; the first line dims to 45%.
Scene 3 (2.20–2.95s): on "isolate" (2.24s) "Isolate." lands beneath at y≈800; the second line dims to 45%.
Scene 4 (2.95–4.10s): on "same plant" (2.99s) the three lines compress upward together (scale 0.62, y −220) in one `power3` glide while a 4px yellow rule draws in left→right beneath them (a scaleX wipe from the left edge, `power3`); "Same plant." (Inter 600, 44px, teal 70%) appears under the rule.
Scene 5 (4.10–end): the payoff question reveals per word on the VO — "What's actually in your bottle?" — Source Serif display ~104px teal, two lines centred on y≈1060; at "your bottle" (5.40s) a yellow highlight sweeps behind those two words (`css-marker-patterns`). Hold still to the end.

narrativeRole: Opens the gap every CBD buyer has felt at the shelf: three labels that sound alike.
keyMessage: These three words mean three different products, and you are about to know which is which.

## Frame 2 — Hemp is a team

- type: product_intro
- duration: 12.46s
- transition_in: crossfade
- persuasion: Analogy (the plant's compounds as a team) + progressive disclosure (one member at a time)
- beat: Orientation + clarity
- scene: Five labelled molecule chips assemble into one row — the team
- voiceover: "Hemp makes more than CBD. Think of it as a team: CBD, the minor cannabinoids CBG and CBN, terpenes — and a trace of THC."
- status: animated
- src: compositions/frames/02-team.html
- blueprint: grid-card-assemble (Adapt)
- focal: the chip stack assembling — the team
- roles: chip stack = foreground subject · teal ground = background · headline = supporting
- sfx: none

Adapt: keep the staggered self-assembly into a vertical list; each chip arrives on its spoken name, not as one cascade.
Scene 1 (0.00–2.40s): teal ground; headline "Hemp makes more than CBD." (Source Serif ~84px, cream) per-word reveal at y≈300 on the VO; on "CBD" (1.56s) the yellow `CBD` chip spring-pops into its stage slot (top of stack, y≈560) with a smooth settle (`spring-pop-entrance`, no overshoot).
Scene 2 (2.40–4.20s): on "Think of it as a team" (2.41s) the headline swaps in place to "Think of it as a team." (`discrete-text-sequence`, velocity-matched cut).
Scene 3 (4.20–5.90s): on "CBD" (4.22s) the CBD chip gets a brief 2px cream outline tick; on "the minor cannabinoids" (4.65s) a small Inter 500 label "minor cannabinoids" (cream 70%, 30px) fades in left-aligned above where the next two chips will land.
Scene 4 (5.90–9.10s): on "CBG" (5.93s) the `CBG` chip slides up into its slot (40px → 0, opacity 0 → 1, `power3`); on "CBN" (7.73s) the `CBN` chip lands beneath it the same way; the "minor cannabinoids" label settles at 50%.
Scene 5 (9.10–10.30s): on "terpenes" (9.14s) the hemp-green `Terpenes` chip lands in the fourth slot with its leaf glyph drawing on (`svg-path-draw`).
Scene 6 (10.30–end): on "and a trace of THC" (10.49s) the dashed `THC · trace` outline draws itself round the fifth slot (`svg-path-draw`) and its label fades in; the full five-chip stack holds still — a clean held read to the end.

narrativeRole: Names the idea the whole video runs on — the product is defined by which team members stay.
keyMessage: A CBD product is a set of compounds; the spectrum tells you which ones are in the set.

## Frame 3 — Full spectrum keeps everyone

- type: feature_showcase
- duration: 9.04s
- transition_in: crossfade
- persuasion: Concretization (the full row, all lit) + coined term ("entourage effect" named on screen)
- beat: Comprehension
- scene: All five chips lit on the stage, the label "Full spectrum" lands above, a bracket spans the whole row
- voiceover: "Full spectrum keeps the whole team, trace THC included, within the legal limit. People call it the entourage effect."
- status: animated
- src: compositions/frames/03-full.html
- blueprint: kinetic-type-beats (Adapt)
- focal: the spectrum label "Full spectrum" + the yellow bracket enclosing all five chips
- roles: chip stack (all five, already in their slots at t=0 — continuity from frame 2) = foreground subject · label = focal type · bracket + "entourage effect" card = supporting · teal ground = background
- sfx: none

Adapt: the "words carry the shot" signature lives in the label and the coined term; the stack stays put.
Scene 1 (0.00–0.80s): the five-chip stack sits exactly as frame 2 ended (continuity); the label "Full spectrum" reveals per word above it (Source Serif display ~112px, yellow) with its top at y≈300.
Scene 2 (0.80–2.70s): on "keeps the whole team" (0.82–1.86s) a 4px yellow bracket self-draws down the right edge from the CBD chip to the THC chip (`svg-path-draw`) while the five chips brighten 10% in one sweep top→bottom.
Scene 3 (2.70–4.50s): on "trace THC included" (2.71s) the THC chip's dashed outline warms to yellow for a beat and settles back to cream.
Scene 4 (4.50–6.10s): on "within the legal limit" (4.50s) a small cream note "within the legal limit" (Inter 500, 30px, 80%) fades in right-aligned under the THC chip.
Scene 5 (6.10–end): on "the entourage effect" (7.31s) a coined-term card rises into the space below the stack (y≈1390, cream fill, teal ink, Source Serif 60px "the entourage effect", 8px radius) and settles; from 8.1s the frame holds still.

narrativeRole: First item of three — the baseline everything else subtracts from.
keyMessage: Full spectrum = everything the plant makes, including a legal trace of THC.

## Frame 4 — Broad spectrum removes THC

- type: feature_showcase
- duration: 6.79s
- transition_in: cut
- persuasion: Subtractive framing (define broad by the one member that leaves) + before/after on the same stage
- beat: "Aha" + relief
- scene: Same stage; the THC chip lifts out and dissolves, the gap closes, label swaps to "Broad spectrum · 0% THC"
- voiceover: "Broad spectrum: the same team, minus the THC. Whole plant, zero THC."
- status: animated
- src: compositions/frames/04-broad.html
- blueprint: kinetic-type-beats (Adapt)
- focal: the THC chip leaving + the label token swap "Full" → "Broad"
- roles: chip stack = foreground subject · label = focal type · "0% THC" stamp = supporting · teal ground = background
- sfx: none

Adapt: in-place token cycle on the label (Full → Broad) is the kinetic-type signature; the subtraction is the payoff.
Scene 1 (0.00–1.30s): stack + bracket as frame 3 ended (the entourage card and legal note are gone); on "Broad" (0.00s) the label's first word swaps in place "Full" → "Broad" (`discrete-text-sequence`, hard in-place swap), "spectrum" stays.
Scene 2 (1.30–2.70s): on "the same team" (1.33s) the five chips brighten in one quick top→bottom sweep.
Scene 3 (2.70–4.20s): on "minus the THC" (2.72s) the dashed THC chip lifts away (y −24px, blur 6px, opacity → 0, `power3`), the bracket retracts to end at Terpenes, and the four remaining chips glide down 78px to re-centre the stack (0.6s `power3`).
Scene 4 (4.20–end): on "zero THC" (5.28s) a hemp-green pill stamp "0% THC" (Inter 600, cream text) settles in beside the label (smooth settle, no overshoot); hold still.

narrativeRole: Second item — the answer for everyone who wants the plant without THC.
keyMessage: Broad spectrum = the whole plant with the THC taken out.

## Frame 5 — Isolate is CBD alone

- type: feature_showcase
- duration: 3.86s
- transition_in: cut
- persuasion: Subtractive framing, taken to the end + distillation (one chip left, grown to hero)
- beat: Clarity + satisfaction
- scene: Same stage; every chip except CBD slides away, CBD grows to the centre, label "Isolate · pure CBD"
- voiceover: "Isolate is pure CBD. Nothing else."
- status: animated
- src: compositions/frames/05-isolate.html
- blueprint: kinetic-type-beats (Adapt)
- focal: the CBD chip growing into the hero
- roles: CBD chip = foreground subject · label = focal type · leaving chips = supporting · teal ground = background
- sfx: none

Adapt: the label token swaps "Broad spectrum" → "Isolate"; the distillation of the stack to one chip is the payoff.
Scene 1 (0.00–1.00s): stack of four + stamp as frame 4 ended; on "Isolate" (0.00s) the label swaps in place to "Isolate" (`discrete-text-sequence`) and the stamp fades.
Scene 2 (1.00–2.50s): on "pure CBD" (1.02s) `Terpenes`, `CBN`, `CBG` lift away bottom→top, 120ms apart (same lift as frame 4), the bracket retracts to nothing; then the yellow `CBD` chip glides to the stage centre (y≈806) and scales to 1.7× (`scale-swap-transition` feel, `power3`).
Scene 3 (2.50–end): on "nothing else" (2.55s) the cream line "Pure CBD. Nothing else." reveals per word under the chip; hold still to the end.

narrativeRole: Third item — the simplest product, defined by what is left.
keyMessage: Isolate = CBD only; no other cannabinoids, no terpenes, no THC.

## Frame 6 — How to choose

- type: benefit_highlight
- duration: 7.24s
- transition_in: push-slide UP
- persuasion: Question→answer pairing + rule of three (three questions, three answers)
- beat: Mastery + confidence
- scene: Three decision rows build down the screen — a question on the left, the matching spectrum pill on the right
- voiceover: "So: want the whole plant? Full. Whole plant, zero THC? Broad. Only CBD? Isolate."
- status: animated
- src: compositions/frames/06-choose.html
- blueprint: grid-card-assemble (Adapt)
- focal: the three question→answer rows
- roles: rows = foreground subject · answer pills = focal accents · cream ground with 2px hairline row rules = background · headline = supporting
- sfx: none

Adapt: the staggered list assembly stays; each row arrives as a question→answer pair on its VO cue (question first, pill on the answer word).
Scene 1 (0.00–0.65s): cream ground; the headline "Pick yours in one question." (Source Serif ~88px, teal) reveals per word at y≈300 and a 2px teal rule draws beneath it (`svg-path-draw`).
Scene 2 (0.65–2.60s): on "want the whole plant" (0.65s) row 1 "Want the whole plant?" (Source Serif 60px, teal) slides up into y≈620; on "Full" (1.94s) a yellow pill "Full spectrum" settles in on the right of the row.
Scene 3 (2.60–5.30s): on "whole plant, zero THC" (2.61s) row 2 "Whole plant, zero THC?" slides in at y≈860; on "broad" (4.63s) a hemp-green pill "Broad spectrum" (cream text) settles in.
Scene 4 (5.30–end): on "only CBD" (5.34s) row 3 "Only CBD?" slides in at y≈1100; on "isolate" (6.53s) a teal pill "Isolate" (cream text) settles in; rows are separated by 2px hairlines; hold still.

narrativeRole: Turns understanding into a decision the viewer can make today.
keyMessage: One question picks your spectrum.

## Frame 7 — Lab tested, every batch

- type: cta
- duration: 11.51s
- transition_in: crossfade
- persuasion: Callback (the three chips return as a small seal) + evidence (lab testing, published report)
- beat: Trust + resolve
- scene: The three spectrum pills fold into a seal beside the Happy Garden wordmark; proof line and "Link in bio" settle below
- voiceover: "Whichever you choose, every Happy Garden batch is third-party lab tested, and the report is published. Find yours — link in bio."
- status: animated
- src: compositions/frames/07-cta.html
- blueprint: logo-assemble-lockup (Adapt)
- focal: the Happy Garden wordmark lockup with the three-segment seal
- roles: wordmark + seal = foreground subject · proof lines = supporting · CTA pill = accent · teal ground = background
- sfx: none

Adapt: keep the "mark comes to exist from parts" signature — the three spectrum pills become the three segments of a round seal that assembles, then the wordmark resolves beneath it.
Scene 1 (0.00–1.70s): teal ground; during "Whichever you choose" three arcs (yellow / hemp green / cream) sweep in from the edges and join into a 180px ring seal centred at y≈560 (`svg-path-draw` on three arc paths, `power3`).
Scene 2 (1.70–3.90s): on "Happy Garden" (2.05s) the wordmark "Happy Garden" (Source Serif 500, ~110px, cream) resolves beneath the seal at y≈760 by letter groups.
Scene 3 (3.90–7.90s): on "third-party lab tested" (3.93s) the proof line "Every batch third-party lab tested" (Inter 600, 40px, cream) reveals under a 2px yellow rule at y≈900; on "the report is published" (6.41s) a second line "Lab report published for every batch" fades in beneath at 75%.
Scene 4 (7.90–end): on "Find yours" (7.96s) a yellow CTA pill "Find your spectrum · link in bio" (Inter 600, teal ink, fully rounded) rises into y≈1180 and settles; the lockup holds still for ≥1.5s, and the last 0.6s fades everything to the teal ground (the only exit in the film).

narrativeRole: Lands the brand as the trustworthy guide and gives the one next step.
keyMessage: Happy Garden shows you exactly what is in the bottle — go pick yours.
