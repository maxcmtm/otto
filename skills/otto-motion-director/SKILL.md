---
name: otto-motion-director
description: "Otto's reel director — turns one post (or a campaign concept) into a 30–60 s motion-design explainer reel that looks studio-made: a business-specific script, a beat-by-beat storyboard with on-screen copy, a brand design system, voice-over, music, and HyperFrames compositions rendered to MP4. Use for every reel in the monthly plan, for video ad variants, and whenever a post's format is reel/video. Never produce slideshow reels (stills + zoom + captions)."
---

# Otto Motion Director

**Standard:** every reel must look like a small motion studio made it for this one business. Kinetic
type, a diagram or visual system that *is* the explanation, brand colours and fonts, voice-over timed to
the word, music under it, and nothing a competitor could reuse unchanged. The reference build is
`motion/happygarden-spectrum-guide/` (STORYBOARD.md, SCRIPT.md, frame.md, compositions/) — open it
before your first reel and match its level. **Read `references/motion-playbook.md` first** — the rules distilled
from a scored review of 223 Opus 5.5 motion videos (one governing object, one accent, real UI at ≥70% of frame,
motion on the beat, no HUD chrome, always a soundtrack) and the ban list every frame worker must receive.

**Engine:** HyperFrames (HTML compositions → MP4), workflow `/faceless-explainer`, run in
**autonomous mode** (`flow: automation`, `storyboard: no`). `platform/otto_motion.py prepare <post-id>`
creates the project, `BRIEF.md`, the capture package and the design system; you write the story; the
frame workers build; `otto_motion.py finish <post-id>` renders, checks and attaches the MP4 to the post.
The old `otto_video.py` (ffmpeg stills) is a fallback only when HyperFrames cannot run.

## 1. Inputs you must read first (never script from the hook alone)

From `brands/<slug>/`: `brand-profile.md` (avatars, pains in the customer's words, objections, proof,
positioning, compliance, VISUAL IDENTITY), any `*brand-guide*.md` (it wins over everything visual),
`strategy.json` when present (persona, awareness stage, offer, proof bank with sources, CTA per stage),
`angles.json` (competitor longevity winners), `winning-posts.md`. From the post: `hook`, `caption`,
`pillar`, `format`, `brief`, `slot`. Missing proof or offer? Script around what exists — never invent
numbers, certificates, guarantees or results.

## 2. Choose the reel's job (one per reel)

| Job | When | Structure (`arc`) |
|---|---|---|
| Teach one idea | education pillar, myth-busting | concept-explainer: hook → name the idea → 2–4 layers → takeaway → CTA |
| Compare / choose | product lines, plans, "which one is for me" | listicle with one shared visual system that changes per item (the Happy Garden chip stack is the model) |
| How it works | services, onboarding, "what happens when you book" | how-to-process: 3–5 steps on one consistent stage |
| Proof / story | alumni, customer, before→after | story-explainer: setup → tension → turn → result (real, sourced) → CTA |
| Myth vs fact | objections | hook (the myth, in the customer's words) → why people believe it → the fact with proof → CTA |

## 3. The script (SCRIPT.md) — rules that make it work

- **30–60 s, 70–130 words.** Fewer words beat faster voice. One idea per line; one line per frame.
- **Line 1 is the hook and the cover**: the customer's own question or the surprising claim, ≤ 12 words,
  outcome language. Never open with the brand name or "Did you know".
- **Value by the second line** (story-spine: value before evidence).
- **Every claim traceable** to `brand-profile.md` / `strategy.json` / the site scan. Numbers only from the
  proof bank. Restricted categories (CBD, health, therapy, finance, employment): no cure/treat/heal, no
  personal-attribute questions ("Do you suffer from…", "Is your child…"), no before/after bodies; run the
  brand's `compliance.json` check on the script before voicing it.
- **Last line = one CTA** that matches the landing page for this funnel stage ("Link in bio", "Book the free
  call", "Find yours"). No double CTA.
- **Language register** from the profile (du/Sie, Hebrew gendered forms, UK/US English). Voice pace
  145–155 wpm; write pauses as full stops, not ellipses.

## 4. The storyboard (STORYBOARD.md) — what makes it motion design

- **One visual system per reel**, invented from the subject (a stack of compounds that loses members, a
  path with stations, a scale that tips, a calendar that fills, a bottle that fills with layers). The
  system persists across frames and *changes* — that change is the explanation. Write its exact geometry
  once in `## Video direction` (positions, sizes, order, colours) so every frame worker reproduces it.
- **Frames = spoken lines** (4–8 frames). Each frame: `type`, `persuasion` (named technique), `beat`,
  `blueprint` (Adapt), `focal`, `roles`, then **Scene lines timed to the real word cues** (run
  `otto_motion.py words <post-id>` after the voice exists and write the cue seconds into the Scene lines).
- **On-screen copy is short**: labels, the coined term, a number, a 2–6 word headline. Captions carry the
  sentences. Headline ≤ 7 words.
- **Pacing:** something meaningful changes every 1.5–2.5 s; nothing enters before its word; end each frame
  on a held read; only the last frame has an exit.
- **Brand:** palette roles from `frame.md` (ground / surface / accent / text), brand fonts when the scan
  found them (Source Serif 4 + Inter otherwise), logo only on the end card, a quiet topbar with the brand
  name. No stock photos as the main layer, no AI glow/bokeh, no emoji, no uppercase mono chrome, no
  bouncy easing, no infinite loops.
- **Caption band:** bottom 17% stays clear. Instagram UI safe area: keep hero content inside x 60–1020,
  y 250–1590.

## 5. Voice, music, captions

- Voice: ElevenLabs via Higgsfield (`generate_audio`, `model: text2speech_v2`, `variant: elevenlabs`,
  `voice_type: preset`). House voices: calm female **Nora** `d081b915-6623-4a44-bacf-80d0f1c90a03`,
  male **Gideon** `1ad38ba4-9cc4-4f2f-9fde-b0fefdf67ae5` (handles Hebrew). One call per line.
- `otto_motion.py voice <post-id> <dir-with-mp3s>` converts, tightens dead air (caps pauses at 0.3 s),
  pads the last line for the end card, transcribes words (faster-whisper) and writes `audio_meta.json`.
- Music: local MusicGen through the HyperFrames media engine (`--bgm-mode generate`), prompt from the
  brand's mood (e.g. "soft organic acoustic, 88 bpm, no vocals"); ducked under the voice by the assembler.
- Captions: on (the preset's caption skin, brand-tinted).

## 6. Build and ship

1. `python3 platform/otto_motion.py prepare <post-id>` → `motion/<brand>-<post-id>/` with BRIEF.md,
   `capture/extracted/*`, `frame.md` (preset + brand colours), empty STORYBOARD/SCRIPT templates.
2. Write SCRIPT.md + STORYBOARD.md (sections 3–4). Voice the lines, then `otto_motion.py voice …`.
3. `node <faceless-explainer>/scripts/audio.mjs sync-durations …` then re-time the Scene lines to the cues.
4. `node <faceless-explainer>/scripts/frame-packets.mjs …`, dispatch one frame worker per frame (in
   parallel), wait for `compositions/frames/*.html`. **The packet builder does not copy `## Video direction`
   into the packets** — paste that whole block (palette roles, the shared stage geometry with exact px values,
   chip/label typography sizes, chrome decision) into every worker's dispatch context, and state the frame's
   exact start state when it continues the previous frame. Decide chrome once (topbar on every frame, or none)
   and say it in every dispatch — mixed chrome across frames is the most common inconsistency.
   After the workers return, compare the last frame of N with the first frame of N+1 (render both with
   `npx hyperframes snapshot --at`) and fix any jump before rendering.
5. `python3 platform/otto_motion.py finish <post-id>` → captions, assemble, transitions, lint, check,
   snapshot contact sheet, render `renders/video.mp4`, copy to `platform/assets/reels/<post-id>.mp4`,
   publish it to the public assets dir, set `post.video` + `post.format = reel`, and move the post to
   `pending_approval` so the owner gets the card.
   `finish` also keeps crossfades solid (the outgoing frame stays opaque, only the incoming one dissolves —
   otherwise the page background washes through mid-fade) and refuses to render when `check` fails.
   Known traps from the reference build:
   - A frame that toggles a child with `visibility` must set `"inherit"`, never `"visible"` — a child set
     to visible escapes the hidden parent clip and lingers (occluded) until the end of the film.
   - `data-layout-allow-overlap` goes on the **element** (`<span … data-layout-allow-overlap>`), never inside
     a CSS selector or a class string — a broken selector drops the whole rule and leaves unstyled text.
   - Every frame must create the registry before registering: `window.__timelines = window.__timelines || {};`
     then `window.__timelines["<id>"] = tl;`. Frames load in parallel; a frame that assumes a sibling already
     created the object freezes in its raw CSS state whenever it happens to run first.
   - A frame's script must not depend on finding its own root by id: the runtime renames the duplicate
     `id="stage"` roots when it mounts the frames, so `document.querySelector('#stage[...]')` returns null in
     the assembled film (it works in a standalone harness, which hides the bug). Use
     `document.querySelector(...) || document` with frame-prefixed ids, or look elements up by their unique ids.
   - Whisper splits hyphenated and contracted words ("third" + "-party"); `voice` glues them back
     (`join_fragments`) so captions never show "third -party".
6. Look at the contact sheet before calling it done: squint (one hero per frame), no text in the caption
   band, no frame frozen for > 3 s, the brand colour visible in every frame.

**Deliverables per reel:** 9:16 master (always). For ad use also a 4:5 cut and three alternative first-3-second
hooks (`finish --variants`) so `otto_ads` can test hooks.
