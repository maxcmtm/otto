# Otto motion playbook — what separates studio-grade AI motion from AI slop

Source: a scored review of all **223 "Motion graphics" videos** people made with Claude Opus 5.5 and shared
publicly (skillry.dev, collected 29 Sept 2026). Every video was reviewed from an 8-frame contact sheet, its
prompt, its tech stack, its audio track and ffmpeg scene-cut timestamps; each got a 1–10 "would a top studio
sign this?" score. Mean ≈ 6.2; one 9; ~30 eights. Raw analysis: see the scratch archive noted in
`docs/OTTO-MASTER-PLAN.md` (not committed — third-party material).

## 1. The seven rules the 8s and the 9 all follow

1. **One governing device that never breaks.** One object carries the eye through the whole piece and
   *changes jobs*: a dot becomes a contact grid, then a chart point, then the "o" of the logo; one card morphs
   through ten UI states without a cut; one ring frames the phone and collapses into the logo. Samplers of
   unrelated scenes cap at 6–7, however polished each scene is.
2. **One accent on a neutral ground.** Two neutrals + one saturated accent (the 9 is literally one cobalt ink
   on paper). A new palette per scene is the most common reason for a ≤5.
3. **Real content at real scale.** Real UI, real copy, real numbers — and big: the UI fills ≥70% of the
   frame. Tiny UI floating in a void reads as a screen recording. Show the *outcome* (the shop rises in "near
   me" results; 90 quiet clients flip into 38 drafted follow-ups), not a feature list.
4. **Motion on the beat, not cuts on the beat.** Two pacing modes win: **continuous morph** (0–1.3 detected
   cuts per 10 s, a meaningful change on every beat) or a **beat-locked edit** (8–16 cuts per 10 s, every cut on
   the bar grid — 0.5 s at 120 BPM, 1.875 s bars at 128 BPM). The 4–6 cuts/10 s middle is mostly flash-frame
   noise. Strobe/glitch montages at the end inflate the cut count and lower the score.
5. **Copy with a turn.** Strike-through replacement ("Five apps for one client."), a before/after in one
   object, a counter that is part of the story ("0 → 38 follow-ups drafted") instead of a HUD readout.
6. **Sound is half the piece.** Every 8+ has audio; every silent video scored ≤7 (mean 5.7). The best ones
   make the sync visible (the kick drawn live as a chart; one state change per beat, SFX on the peaks).
7. **Short.** The best run 15–45 s. Runs of 60 s+ sag unless a story carries them.

## 2. The AI-slop kit — never use any of it

Viewfinder/corner brackets, "MOTION REEL 2026" labels, timecode, "60FPS · 120BPM" readouts, "01/07"
counters · a bouncing ball over a bezier graph editor, "TIMING / STRETCH / EASING" words · isometric cube
fields, particle spheres/tori/galaxies, chrome or iridescent blobs, neon tunnels, mesh-gradient orbs ·
RGB-split glitch and strobe endings · a new palette every scene · a "Claude."-style end card with a coloured
period · frozen scramble text · blur dissolves between slide layouts (headline left, card right, repeat) ·
emoji · generic "✨ AI" gradients · screen recordings with browser chrome · 60–110 s runtimes with no story.
The single clearest tell is **HUD chrome** (corner labels, timecode): present on nearly every video scoring ≤6,
on almost none of the 8s.

## 3. What in the brief moves the score

- **A real subject beats "go all out".** The stock "showreel for a résumé, go all out" prompt was used ~50
  times and converges on the same template (mean ≈ 6). The *same* prompt run inside a real product repo
  averaged 7.25–8. For Otto: always brief with the business's real site, offer, proof and numbers.
- **One hard constraint makes a piece coherent**: "one shape, never cut", "one ink on paper", "sound tells
  half the story", a named style ("risograph", "Apple-style", "main-title design"). Write it in `## Video
  direction`.
- **Ban lists work** — "no text or frames in the corners" produced the only HUD-free "showreel". Always
  include §2 as a ban list in the frame-worker dispatch.
- **Beat instructions are obeyed exactly**; **"the camera fills the frame" is ignored** unless you give
  explicit scale numbers ("the card is 1400 px wide").
- **Terse prompts with no audio instruction come out silent.** Always specify the score.
- **"Typical SaaS launch video" returns the typical template** (logo walls, headline-left/card-right).

## 4. Moves worth stealing for Otto (and where they are used)

| Move | Seen in | Otto use |
|---|---|---|
| One card, never cut, cursor/thumb-driven through every state | twoclipping, thegrootdev, dzhohola, annacher | The approval card: draft → approve → scheduled → live → result |
| The mark as protagonist that lands as the logo | zheke, leonkohli, mustaphafenzar | The Otto square becomes day tile → post → Approve button → chart bar → logo |
| Month as a grid that fills | lepadev, batch-5 steal list | 30 day tiles fill with real thumbnails on the 16th-note arpeggio; diegetic counter "0 → 50 posts" |
| Tool-sprawl collapse | bizibeast | Agency €1.5–5k/mo + freelancer + tools + evenings stack, strike through, fold into one Otto card |
| Show the outcome | dansushik, lepadev | The morning report at 07:35 with real spend/lead numbers; "fix already drafted" |
| Chart drawn on the kick | fionntobin (the 9) | Month-over-month bars rise on the downbeats |
| Night beat | batch-4 "shop closed" | "Shop closed. Otto still working." — the same system on the night ground |

## 5. Otto house spec for every reel/film

- Tokens and components: `motion/otto-kit/kit.css` (brand videos) or the client's `frame.md` (client reels).
- Canvas: light neutral (#F5F5F7 / paper) with ink #1D1D1F and one accent; a night variant only as a
  deliberate beat. Type: one display grotesk (Inter Tight 600–650, −0.04em) + Inter for UI; optionally one
  italic serif word per film.
- Protagonist object defined in `## Video direction` with exact geometry and its role in every frame.
- Pacing: continuous morph by default; a beat-locked chorus only in the energy peak. Every state change on a
  beat or a word cue. Entrances `expo.out` 0.5–0.9 s; moves `power3.inOut`; exits `power2.in` 0.25–0.4 s; no
  back/elastic/bounce.
- UI ≥70% of frame when UI is the subject. No text in the outer 6% of the frame except the end card's legal line.
- Audio always: the score for brand films (synthesized to the storyboard's bar grid, `motion/otto-showreel-score/`),
  voice + bed for explainers. Loudness −14 LUFS integrated.
- Length: 30–45 s for ads and reels; 60 s only for the brand showreel.
