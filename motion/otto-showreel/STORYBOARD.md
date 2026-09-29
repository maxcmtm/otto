---
compositionId: bgm
duration_s: 60.0
canvas: { w: 1920, h: 1080, fps: 30 }
style:
  font: "Inter Tight 600–650 display / Inter 400–600 UI"
  palette: ["#F5F5F7", "#FFFFFF", "#1D1D1F", "#2447F0", "#0B0B0D", "#1B7F4B"]
assets: "assets/img/*.jpg (20 real post photos), assets/hg-reel.mp4 (Happy Garden reel, 1080×1920, 57s), assets/kit.css, assets/fonts/*"
build_notes: ["one paused timeline per frame", "no remote assets", "fonts from ../../assets/fonts", "every state change on a listed anchor"]
avoid: ["HUD chrome, corner labels, timecode", "tiny UI in a void — UI fills ≥70% of its zone", "new palette per scene", "glitch / strobe / particles / neon", "text in the outer 6%"]
---

# Otto — brand film (60 s, 16:9, music only)

## Video direction

**Message.** Otto is a marketing department in your pocket: it reads your business, plans the month, makes
every post, asks you before anything goes out, then works day and night — publishing, running ads, reporting,
watching competitors — and every month you see what grew. You approve; Otto does the work.

**The one governing device — the Otto square.** A cobalt `#2447F0` rounded square with a white inner outline
(`.ok-mark`: radius 30% of its size, inner outline inset 25%, stroke 6% of size, inner radius 12%). It is the
protagonist and it never disappears between frames: it is the seed that multiplies into the chores (F1), the
logo (F2), the caret in the website field (F2), the scan line's origin (F3), the calendar's "today" tile (F4),
the bullet of every verb in the chorus (F7–F8), the source of the growth bars (F9) and the logo again (F10).
Canonical standalone size **120px at the canvas centre (960, 540)**.

**Grounds.** Light `#F5F5F7` for F1–F5, F9–F10. Night `#0B0B0D` for F7–F8 (the drop): the same system
inverted — "Otto keeps working while the shop is closed". F6 carries the switch: a circle wipe from the
Approve button, landing exactly on the drop at 26.0 s.

**Headline zone.** Top-centred headline at y ≈ 110–190 (baseline area), Inter Tight 600, 64px, ink, one
cobalt word allowed. Content zone below: x 160–1760, y 230–990. UI fills its zone (≥70%).

**Grid.** 120 BPM: beat = 0.5 s, bar = 2 s. Every anchor below is a track second on that grid. The score's
sections: intro 0–8 · build 8–24 (claps from 16) · lift 24–26 (snare roll + riser, no kick) · drop 26–42
(crashes 26, 34) · breakdown 42–50 (no kick) · final 50–58 (crash 50) · end impact 58, tail to 60.

**Content (real).** Brand used in the product scenes: **Happy Garden**, an EU CBD shop — industry "CBD
wellness · online shop · Germany, Austria, UK"; colours #FFBC00 #0E252C #31856C #FFFFFF; tone "Educational
and trust-first. Lab results over hype."; competitors "Nordic Oil · Naturecan · CBD Vital · Hempamed";
audience "Petra, 52 — “I haven’t slept well in years.”" Photos in `assets/img/` (hg-*, coffee-*, surf-*,
bakery, dental, florist, salon, pilates, interior-*, skincare, cm-*). Other businesses in the montage are
invented and generic: "Kiln Coffee", "Salt Line Surf", "Studio Nord Dental", "Rue Florist".

**Motion rules.** Continuous morphs; the only hard cuts are the frame seams (which are designed as
match-cuts — see each frame's `handoff_in/out`) and the chorus in F7–F8. Entrances expo.out, moves
power3.inOut, exits power2.in. Nothing enters before its anchor; every frame ends on a held, readable state
unless its handoff says it is mid-move.

## Frame 1 — 01-chores

- src: compositions/frames/01-chores.html
- duration: 8.0s
- span_sec: [0.0, 8.0]
- pacing: phrase_flow
- mood: [anticipation]
- feel: filtered pad and clock ticks, a riser into an impact at 8.0
- handoff_out: { element: "Otto square", x: 960, y: 540, size: 120, opacity: 1, rotation: 0, ground: "#F5F5F7", motion: "arrives at rest exactly at 8.0 after the collapse" }

### Groups

- **g1** — free_design
  - span_sec: [0.0, 4.0]
  - free_design: { dominant_system: "the Otto square alone, then one headline line", primitives: ["scale-in", "word-rise"], density_topology: "sparse" }
  - anchors: [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
  - copy: "Every week, your business needs"
  - notes: "0.0–0.5 the square scales 0→1 at (960,540), 120px. 1.0 it glides up to (960,330) (power3.inOut 0.8s). The headline (Inter Tight 600, 72px, ink, centred at y≈520) rises word-by-word from masks on 1.5 / 2.0 / 2.5 / 3.0 (“Every week,” · “your business” · “needs” — last word lands at 3.0). The square pulses 1→1.06→1 on each downbeat (0, 2) like a heartbeat."
- **g2** — free_design
  - span_sec: [4.0, 8.0]
  - free_design: { dominant_system: "the square multiplies into chore chips that pile up", primitives: ["spawn-from-origin", "accumulate", "collapse-to-point"], density_topology: "accumulate then implode" }
  - anchors: [4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5, 5.75, 6.0, 6.25, 6.5, 6.75, 7.0, 7.25, 7.5, 8.0]
  - copy: ["3 posts", "5 stories", "1 reel", "Meta ads", "Google ads", "Captions", "Replies", "Visuals", "Carousels", "Best posting times", "A weekly report", "Competitor check", "Budget", "Hashtags"]
  - notes: "Headline stays (it now reads as a sentence the chips complete). From 4.0, one chip per anchor (4.0 … 7.25) springs out of the square's position and flies to its own slot, filling the frame in a loose, deliberate 5×3-ish scatter (avoid the headline box and the outer 6%); chip = white pill, 64px tall, Inter 500 30px ink, a 22px cobalt square icon at left, card shadow, rotation from a fixed list (−4°…+4°, derived from index, not random). As chips accumulate the whole stage pushes in 1.0→1.05 (overwhelm). 7.5: the headline exits (power2.in 0.25s) and every chip accelerates back into (960,540) (power3.in, 0.5s, staggered 0.02s) shrinking to 0 — the square (which returned to the centre at 7.5) swallows them and lands at rest at 8.0, scale 1."

## Frame 2 — 02-otto

- src: compositions/frames/02-otto.html
- duration: 4.0s
- span_sec: [8.0, 12.0]
- pacing: phrase_flow
- mood: [reveal]
- feel: impact on 8.0, four-on-the-floor starts, bass enters
- handoff_in: { element: "Otto square", x: 960, y: 540, size: 120, opacity: 1, ground: "#F5F5F7" }
- handoff_out: { element: "website field", rect: "x 510→1410, y 485→595 (900×110), radius 55, white, card shadow", square: "56px at (575, 540)", text: "happygardeneu.com, Inter 500 44px ink, left edge x=625, fully typed", button: "cobalt pill 'Read' 150×70 at right end, centre (1330, 540), just pressed (scale 1)", headline: "“It starts with your website.” gone by 12.0" }

### Groups

- **g1** — free_design
  - span_sec: [8.0, 10.0]
  - free_design: { dominant_system: "logo lockup stamp", primitives: ["impact-stamp", "mask-wipe"], density_topology: "single hero" }
  - anchors: [8.0, 8.5, 9.0, 9.5]
  - copy: ["Otto", "Your marketing department,", "in your pocket."]
  - notes: "8.0 impact: the square stamps (scale 1.18→1, expo.out 0.6s) while it slides left to centre (777,500); the wordmark “Otto” (Inter Tight 650, 150px, −0.045em, ink) wipes in from a mask to its right (left edge x=873, baseline aligned to the square's centre). Tagline (Inter Tight 600, 52px, muted #6E6E73 with “in your pocket.” in ink) rises centred at y≈690: “Your marketing department,” on 8.5, “in your pocket.” on 9.5."
- **g2** — free_design
  - span_sec: [10.0, 12.0]
  - free_design: { dominant_system: "the square becomes the caret of a website field", primitives: ["morph-rect", "typewriter"], density_topology: "single hero" }
  - anchors: [10.0, 10.25, 10.5, 11.5]
  - copy: ["It starts with your website.", "happygardeneu.com", "Read"]
  - notes: "10.0: wordmark and tagline exit up (power2.in 0.3s); the square shrinks to 56px and travels to (575,540) as a white pill field grows out of it to the right (x 510→1410, 110 tall, radius 55). 10.25 headline “It starts with your website.” (Inter Tight 600, 64px, centred, y≈380). 10.5→11.4 the URL types one character per 1/16 note (0.0625s steps) “happygardeneu.com”. 11.5 the cobalt “Read” button (Inter 600 30px white) presses: scale 0.94 then back to 1 by 11.75. 11.75–12.0 the headline exits up; field stays exactly at the handoff geometry."

## Frame 3 — 03-reads

- src: compositions/frames/03-reads.html
- duration: 4.0s
- span_sec: [12.0, 16.0]
- pacing: beat_cut
- mood: [discovery]
- feel: pluck arpeggio enters, steady kick; information lands on each beat
- handoff_in: { element: "website field", same geometry as 02 handoff_out }
- handoff_out: { element: "brand profile card", rect: "centred at (960, 560), 640×720, radius 24, white, card shadow", content: "all five rows visible and settled", other: "browser gone, headline gone" }

### Groups

- **g1** — free_design
  - span_sec: [12.0, 16.0]
  - free_design: { dominant_system: "a browser reading the site; findings fly into a profile card", primitives: ["morph-rect", "scan-line", "highlight-box", "fly-to-slot", "row-reveal"], density_topology: "two panels" }
  - anchors: [12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5]
  - copy:
    - headline: "Otto reads your business."
    - page: { nav: "Happy Garden · Shop · Lab reports · About", hero: "Know exactly what’s in your bottle.", sub: "Third-party lab tested. Every batch.", reviews: "★★★★★ 4.8 · 1,240 reviews", products: ["Full spectrum 10%", "Broad spectrum 5%", "Isolate 20%"] }
    - card_title: "Brand profile"
    - card_note: "Filled in by Otto"
    - rows: [["Industry", "CBD wellness · online shop · Germany, Austria, UK"], ["Colours", "swatches #FFBC00 #0E252C #31856C #FFFFFF"], ["Tone", "Educational and trust-first. Lab results over hype."], ["Competitors", "Nordic Oil · Naturecan · CBD Vital · Hempamed"], ["Audience", "Petra, 52 — “I haven’t slept well in years.”"]]
  - notes: "12.0–12.5: the field morphs into the URL bar of a browser window (x 160→1060, y 230→980) whose page draws in: nav, hero photo `assets/img/hg-yellow.jpg` with the hero line in #0E252C, review strip, three product tiles (`hg-spectrum.jpg`, `hg-lab.jpg`, `hg-evening.jpg`). The square becomes the site's favicon slot in the URL bar (28px). Headline at top (y≈150). 12.5: the brand-profile card (x 1120→1760, y 250→970) appears empty with its title. 12.5→14.5: a cobalt scan line (2px + soft 12px tint band) sweeps the page top→bottom, reaching the bottom at 14.5. On each anchor 13.0/13.5/14.0/14.5/15.0 one page element gets a cobalt highlight box and a small chip copy of it flies to the card, landing as the next row (Industry ← nav, Colours ← hero, Tone ← hero line, Competitors ← (a chip labelled ‘4 competitors found’ flies in from the right edge of the page), Audience ← reviews). 15.5→16.0: the browser exits left (power2.in) and the card glides to the handoff rect at centre (power3.inOut)."

## Frame 4 — 04-plans

- src: compositions/frames/04-plans.html
- duration: 4.0s
- span_sec: [16.0, 20.0]
- pacing: beat_cut
- mood: [momentum]
- feel: claps join on beats 2 and 4 (16.5, 17.5, 18.5, 19.5); arpeggio in 16ths
- handoff_in: { element: "brand profile card", rect: "centred at (960, 560), 640×720" }
- handoff_out: { element: "post image", image: "assets/img/hg-spectrum.jpg", rect: "400×500 centred at (960, 560), radius 12, no chrome", ground: "#F5F5F7", other: "everything else gone" }

### Groups

- **g1** — free_design
  - span_sec: [16.0, 20.0]
  - free_design: { dominant_system: "the profile card becomes the month; tiles fill in waves", primitives: ["morph-rect", "grid-fill-wave", "counter-roll", "push-in"], density_topology: "grid" }
  - anchors: [16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5]
  - copy:
    - headline: "It plans your whole month."
    - month: "October 2026"
    - counter_final: "50 posts · 12 stories · 4 reels"
    - formats: ["Post", "Carousel", "Reel", "Story", "Ad"]
  - notes: "16.0–16.4: card content fades, the card morphs into a calendar panel (x 180→1740, y 240→990, radius 28). Headline top. Panel header: “October 2026” (Inter Tight 600, 40px) left; a counter right that rolls (tabular numbers) with the fill: “0 posts” → final “50 posts · 12 stories · 4 reels” at 19.0. Weekday row Mon…Sun (Inter 500 20px muted). 35 cells (7×5; Oct 1 2026 is a Thursday, so the first three cells are empty and greyed), day numbers top-left. Fill: one row per anchor 16.5 / 17.0 / 17.5 / 18.0 / 18.5, each row's tiles flipping in left→right 0.05s apart, each tile showing a photo from assets/img (cycle through all 20, fixed order) plus a tiny format label top-right in cobalt (cycle Post, Carousel, Reel, Story, Post, Ad…). Oct 7 (Wednesday, row 2) is the Happy Garden tile `hg-spectrum.jpg` labelled Reel. 19.0: all tiles settled, counter final. 19.5→20.0: push-in on Oct 7 — every other tile, the panel and the headline fade out while the Oct 7 photo grows to the handoff rect (400×500 at centre), losing its label and number."

## Frame 5 — 05-makes

- src: compositions/frames/05-makes.html
- duration: 4.0s
- span_sec: [20.0, 24.0]
- pacing: beat_cut
- mood: [craft]
- feel: claps on 20.5, 21.5, 22.5, 23.5; full build groove
- handoff_in: { element: "post image hg-spectrum.jpg", rect: "400×500 centred at (960, 560)" }
- handoff_out: { element: "phone", rect: "ok-phone 414×868 at scale 1.0, centre (1180, 560), screen shows a chat with Otto: the approval card for hg-spectrum (image, caption, meta, Approve/Skip/Edit)", ground: "#F5F5F7", other: "post/carousel/reel cards gone; nothing else on stage" }

### Groups

- **g1** — free_design
  - span_sec: [20.0, 23.5]
  - free_design: { dominant_system: "one post becomes three formats", primitives: ["chrome-grow", "fan-out", "video-in-card"], density_topology: "three cards" }
  - anchors: [20.0, 20.5, 21.5, 22.5]
  - copy:
    - headline: "It writes and designs every post."
    - post: { handle: "happygardeneu", caption: "Full, broad or isolate? Same plant, three products. 60 seconds to know what’s in your bottle." }
    - labels: ["Post", "Carousel", "Reel"]
  - notes: "20.0: Instagram post chrome grows around the image (ok-post, scaled so the card is ~500px wide) and slides to x-centre 520. Headline top. 20.5 label “Post” under it (Inter 500 26px muted). 21.5: a carousel appears in the middle column (centre x 960): three 4:5 slides (hg-spectrum, hg-lab, hg-yellow) fanned with slight perspective (rotateY −8°, 0°, 8°), dot indicator below; label “Carousel”. 22.5: a vertical reel card (9:16, 320×569, radius 20) slides in at centre x 1400 playing `assets/hg-reel.mp4` (muted <video> as a direct child of #stage, data-start at frame-local 2.4, media starting at 6.0s of the file); label “Reel”."
- **g2** — free_design
  - span_sec: [23.5, 24.0]
  - free_design: { dominant_system: "cards file into the phone", primitives: ["fly-to-slot"], density_topology: "single hero" }
  - anchors: [23.5, 24.0]
  - notes: "23.5: the three cards scale down and fly into a phone rising from below to the handoff rect (centre 1180,560), becoming the approval card on its screen; headline exits. Phone content per `.ok-phone/.ok-screen`: status bar 18:42, a Telegram-style chat header “Otto”, the approval bubble (image hg-spectrum, caption shortened, “Instagram · Tue 18:00”, buttons Approve (cobalt) · Skip · Edit)."

## Frame 6 — 06-approve

- src: compositions/frames/06-approve.html
- duration: 2.0s
- span_sec: [24.0, 26.0]
- pacing: phrase_flow
- mood: [tension]
- feel: kick drops out, snare roll and riser, reverse cymbal into the drop at 26.0
- handoff_in: { element: "phone", rect: "centre (1180, 560), 414×868, approval card on screen" }
- handoff_out: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#0B0B0D (night) fully covering", other: "phone gone" }

### Groups

- **g1** — free_design
  - span_sec: [24.0, 26.0]
  - free_design: { dominant_system: "one tap on Approve, circle wipe into night", primitives: ["headline-rise", "touch-press", "check-draw", "circle-wipe"], density_topology: "phone + headline" }
  - anchors: [24.0, 24.5, 25.0, 25.5, 25.75, 26.0]
  - copy: ["Nothing goes out", "until you tap."]
  - notes: "24.0: headline on the left column (x 200→860, vertically centred), Inter Tight 650, 96px, two lines, “until you tap.” with “tap.” in cobalt; lines rise on 24.0 and 24.5. A touch indicator (54px circle, rgba(29,29,31,.18), 2px white ring) glides from below the phone to the Approve button 24.6→25.4 (power3.inOut). 25.5 press: indicator scales 0.8, button darkens; 25.75 the button turns success green and a white check draws in it; at 25.75 a night-ground circle (#0B0B0D) starts expanding from the Approve button centre and covers the whole frame by 26.0 (power2.in). While the circle expands, the cobalt square (120px) appears at (960,540) on top of the night ground, landing at rest at 26.0."

## Frame 7 — 07-works

- src: compositions/frames/07-works.html
- duration: 8.0s
- span_sec: [26.0, 34.0]
- pacing: beat_cut
- mood: [peak energy]
- feel: the drop — kick every beat, stabs on the offbeats, crash at 26; chorus changes on each bar (26, 28, 30, 32) and details on each beat
- handoff_in: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#0B0B0D" }
- handoff_out: { element: "chorus layout", verb_slot: "left column, verb baseline y≈560, square bullet 64px at (200, 530)", ground: "#0B0B0D", right_panel: "empty at 34.0 (the alert card has exited by 33.9)" }

### Groups

- **g1** — free_design
  - span_sec: [26.0, 34.0]
  - free_design: { dominant_system: "verb chorus: one huge verb per bar on the left, real UI proof on the right, one change per beat", primitives: ["square-becomes-bullet", "verb-swap-on-bar", "feed-step", "counter-roll", "toast"], density_topology: "two columns" }
  - anchors: [26.0, 26.5, 27.0, 27.5, 28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0, 31.5, 32.0, 32.5, 33.0, 33.5]
  - copy:
    - verbs: ["Publishes.", "Runs your ads.", "Reports.", "Watches."]
    - publishes: { posts: [["Kiln Coffee", "coffee-pour.jpg"], ["Salt Line Surf", "surf-boards.jpg"], ["Rue Florist", "florist.jpg"], ["Happy Garden", "hg-spectrum.jpg"]], toast: "Published · 18:00" }
    - ads: { meta: { page: "Salt Line Surf", img: "surf-lesson.jpg", headline: "Surf lessons in Lisbon, from €35", cta: "Book now" }, google: { dom: "saltlinesurf.pt", title: "Surf Lessons Lisbon — Beginners Welcome", desc: "Small groups, boards and wetsuits included. Book online in 2 minutes." }, budget: "€20 a day", live: "Campaign live" }
    - reports: { time: "07:35", title: "Good morning. Here is yesterday.", rows: [["Spent", "€18.40"], ["Leads", "7"], ["Cost per lead", "€2.63"], ["Best ad", "Surf lessons in Lisbon"]] }
    - watches: { alert: "Reach dropped 18% on Tuesday.", fix: "The fix is drafted.", button: "Approve fix" }
  - notes: "Night ground throughout (on-night text #F5F5F7, muted #A1A1A6, accent text #5B75FF). 26.0 (crash): the square travels from centre to the bullet slot (200,530) shrinking to 64px (power3.inOut 0.45s); verb 1 “Publishes.” (Inter Tight 650, 168px, −0.045em, on-night) wipes in beside it (left edge x=300). Right panel (x 1000→1760, y 200→940): a feed column of four Instagram posts (white ok-post cards, ~380px wide) that steps up one post per beat 26.5/27.0/27.5 with a green ‘Published · 18:00’ toast on the newest. 28.0 verb swaps (old verb exits up 0.2s, new rises) → “Runs your ads.” (136px so it fits) — right panel: Meta ad card on 28.0, Google ad on 28.5, a budget slider pill filling to “€20 a day” on 29.0, a green “Campaign live” pill on 29.5. 30.0 → “Reports.” — right: briefing message (ok-brief, white on night) arriving as a notification at 30.0, its four rows landing on 30.5/31.0/31.5/32.0? (keep last row on 31.5). 32.0 → “Watches.” — right: an alert card: a small line chart (8 points) drawn on 32.0 with a dip, the text rows on 32.5, the ‘Approve fix’ button on 33.0, the dip line redrawing upward on 33.5; 33.75→34.0 the right panel content exits (power2.in). The square bullet pulses 1→1.12→1 on every downbeat (26, 28, 30, 32)."

## Frame 8 — 08-nightshift

- src: compositions/frames/08-nightshift.html
- duration: 8.0s
- span_sec: [34.0, 42.0]
- pacing: beat_cut
- mood: [peak energy → resolve]
- feel: second half of the drop, crash at 34; 42.0 the kick stops (breakdown)
- handoff_in: { element: "chorus layout", verb_slot: "square bullet 64px at (200, 530), verb left edge x=300", ground: "#0B0B0D" }
- handoff_out: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#F5F5F7 fully covering", other: "everything else gone" }

### Groups

- **g1** — free_design
  - span_sec: [34.0, 38.0]
  - free_design: { dominant_system: "verb chorus continues: competitor dossier", primitives: ["verb-swap-on-bar", "card-grid-reveal", "finding-chip"], density_topology: "two columns" }
  - anchors: [34.0, 34.5, 35.0, 35.5, 36.0, 36.5, 37.0, 37.5]
  - copy:
    - verb: "Studies your competitors."
    - competitors: [["Nordic Oil", "Posting reels 3× a week"], ["Naturecan", "New offer: 20% off bundles"], ["CBD Vital", "Same ad running for 41 days"], ["Hempamed", "Quiet on Instagram since July"]]
    - result: "3 new ideas added to next week"
  - notes: "34.0 (crash): verb swaps to “Studies your competitors.” (two lines, 120px). Right panel: 2×2 dossier cards (night-2 #17171B surfaces, 1px hairline rgba(255,255,255,.08), radius 20) each with a name (Inter 600 28px) and an empty finding line; on 34.5/35.0/35.5/36.0 one card lights (hairline turns #5B75FF) and its finding types in (Inter 400 22px). 37.0: a green pill “3 new ideas added to next week” slides up under the grid."
- **g2** — free_design
  - span_sec: [38.0, 42.0]
  - free_design: { dominant_system: "night shift: a lock screen filling with Otto notifications", primitives: ["phone-in", "notification-stack", "clock", "circle-wipe-to-light"], density_topology: "phone + verb" }
  - anchors: [38.0, 38.5, 39.0, 39.5, 40.0, 40.5, 41.0, 41.5, 42.0]
  - copy:
    - verb: "While you sleep."
    - clock: "07:35"
    - date: "Tuesday 14 October"
    - notifications: [["Otto", "Post published · Kiln Coffee · 18:00"], ["Otto", "3 new leads from Meta"], ["Otto", "Paused one ad: cost per lead too high"], ["Otto", "Your morning report is ready"]]
  - notes: "38.0: verb swaps to “While you sleep.”; the dossier exits; a phone (ok-phone, dark lock screen: very dark blue-black wallpaper, big clock “07:35” Inter Tight 600 96px, date line) rises into the right column (centre x 1320). Notifications (ok-notif, 330px wide inside the phone, scaled to fit the screen) drop in one per anchor 38.5/39.0/39.5/40.0, stacking. 41.0: the verb and bullet exit; 41.5→42.0 the lock screen brightens and a light-ground circle (#F5F5F7) expands from the phone's centre to cover the frame exactly at 42.0 (power2.in), while the cobalt square (120px) appears at (960,540) on top, at rest at 42.0."

## Frame 9 — 09-grows

- src: compositions/frames/09-grows.html
- duration: 8.0s
- span_sec: [42.0, 50.0]
- pacing: phrase_flow
- mood: [calm confidence]
- feel: breakdown — pads and a soft pluck, no kick; riser in the last bar (48–50)
- handoff_in: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#F5F5F7" }
- handoff_out: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#F5F5F7", other: "everything else gone" }

### Groups

- **g1** — free_design
  - span_sec: [42.0, 46.0]
  - free_design: { dominant_system: "the square becomes the chart", primitives: ["split-into-bars", "bar-rise", "counter-roll"], density_topology: "chart + metrics" }
  - anchors: [42.0, 43.0, 44.0, 45.0]
  - copy:
    - headline: "Every month, you see what grew."
    - bars: [["Aug", 0.46], ["Sep", 0.63], ["Oct", 0.81], ["Nov", 1.0]]
    - metrics: [["Reach", "+22%"], ["Followers", "+180"], ["Leads", "31"]]
    - footnote: "Example month"
  - notes: "42.0: headline top. The square moves to the chart baseline and splits into four bars (x 360→1060 zone, baseline y 860, max height 520, bar 120 wide, radius 14/14/4/4; past months #D9DEF9, current Nov #2447F0), rising one per anchor 42.0/43.0/44.0/45.0 (expo.out 0.8s), month labels under each. Right column (x 1200→1700): three metrics (ok-metric: value Inter Tight 650 96px, label Inter 500 24px muted, a green delta pill) counting up on 43.0/44.0/45.0. Footnote “Example month” (Inter 400 20px faint) under the chart."
- **g2** — free_design
  - span_sec: [46.0, 50.0]
  - free_design: { dominant_system: "the costs pile up, get struck through and fold into one Otto card", primitives: ["stack-in", "strike-through-draw", "fold-collapse", "collapse-to-point"], density_topology: "stack → single" }
  - anchors: [46.0, 46.5, 47.0, 47.5, 48.0, 48.5, 49.0, 49.5, 50.0]
  - copy:
    - headline: "What it replaces."
    - costs: [["An agency", "€1,500–5,000 a month"], ["An in-house hire", "€4,000–6,000 a month"], ["Tools and your evenings", "€60–100 a month + 8–10 hours a week"]]
    - otto: ["Otto", "You approve. Otto does the work."]
  - notes: "46.0: chart and metrics exit (power2.in 0.3s); headline swaps. Three cost cards (white, 1000×120, radius 22, label left Inter 600 36px, price right Inter 500 32px muted) stack centred at y 400/540/680 on 46.0/46.5/47.0. 48.0: a 4px cobalt strike-through line draws across all three (0.4s, staggered 0.08s). 48.5: the cards fold into one (they slide together and compress, power3.inOut 0.5s) becoming the Otto card (1000×220: square 72px left, “Otto” Inter Tight 650 64px, line 2 Inter 500 32px muted) settled at 49.0. 49.5→50.0: the Otto card collapses into the square at centre (power3.in), headline exits; square at rest at 50.0."

## Frame 10 — 10-finale

- src: compositions/frames/10-finale.html
- duration: 10.0s
- span_sec: [50.0, 60.0]
- pacing: beat_cut
- mood: [triumph → settle]
- feel: final drop with the lead motif (crash + impact at 50), impact at 58, tail to 60
- handoff_in: { element: "Otto square", x: 960, y: 540, size: 120, ground: "#F5F5F7" }

### Groups

- **g1** — free_design
  - span_sec: [50.0, 52.5]
  - free_design: { dominant_system: "a wall of the month's real posts bursts from the square and collapses back", primitives: ["burst-to-grid", "tile-flip-on-beat", "collapse-to-point"], density_topology: "full wall" }
  - anchors: [50.0, 50.5, 51.0, 51.5, 52.0, 52.5]
  - notes: "50.0 (crash): 24 photo tiles (from assets/img, 4:5, 180×225, radius 12) burst out of the square into a 8×3 wall filling the content zone (power3.out 0.5s, stagger by distance from centre). On 50.5/51.0/51.5 a third of the tiles flip to another photo (rotateY). 52.0→52.5 every tile collapses back into the square at centre (power3.in); the square at rest at 52.5."
- **g2** — free_design
  - span_sec: [52.5, 60.0]
  - free_design: { dominant_system: "logo lockup, promise, call to action, still ending", primitives: ["impact-stamp", "mask-wipe", "fact-row", "button-in", "hold"], density_topology: "end card" }
  - anchors: [52.5, 53.0, 54.0, 54.5, 55.0, 56.0, 58.0]
  - copy:
    - wordmark: "Otto"
    - tagline: "Your marketing department, in your pocket."
    - facts: ["Set up from your website", "Live in 24 hours", "You approve every post"]
    - cta: "Scan your site"
    - offer: "Founding pilot · €197"
    - legal: "Figures shown are illustrative."
  - notes: "Same lockup geometry as frame 2 (square centre (777,470), wordmark left edge 873, 150px) so the film rhymes. 52.5 stamp + wordmark wipe; 53.0 tagline (Inter Tight 600, 52px, centred, y≈620). 54.0/54.5/55.0 the three facts (Inter 500 28px muted, separated by 6px cobalt dots, centred y≈720). 56.0: CTA pill (cobalt, 72px tall, Inter 600 30px white “Scan your site”) at y≈830 with the offer line under it (Inter 500 22px muted). 58.0 (impact): the lockup does one final stamp (scale 1.03→1) and the square's inner outline re-draws; from 58.5 nothing moves. Legal line (Inter 400 16px faint) at y≈990 appears at 56.0."
