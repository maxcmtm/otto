# Frame-worker dispatch — Otto brand film

PROJECT_DIR: /Users/maxsalkov/otto/motion/otto-showreel
Canvas: 1920×1080, 30 fps. Audio lives on the root; your frame is silent.

Read, in this order, before writing anything:
1. /Users/maxsalkov/.claude/skills/music-to-video/sub-agents/frame-worker.md — your role and self-check.
2. /Users/maxsalkov/.claude/skills/hyperframes-core/references/sub-compositions.md and
   /Users/maxsalkov/.claude/skills/hyperframes-core/references/determinism-rules.md — the composition contract.
3. PROJECT_DIR/STORYBOARD.md — the `## Video direction` section (the whole film's system; the Otto square is the
   one governing device) and **your** `## Frame N — <frame_id>` block (anchors are TRACK seconds; subtract your
   frame's span start to get frame-local time). Honour `handoff_in` / `handoff_out` geometry exactly — your
   first and last frames must match the neighbouring frames pixel for pixel.
4. PROJECT_DIR/frame.md — palette, type, depth, motion, ban list.
5. PROJECT_DIR/assets/kit.css — the component geometry (`ok-*`). Inline the rules you use into your frame's
   `<style>`, prefixed/namespaced to your frame id so they cannot clash with sibling frames.
6. /Users/maxsalkov/otto/skills/otto-motion-director/references/motion-playbook.md — §1 rules and §2 ban list.

Hard rules:
- Write exactly one file: PROJECT_DIR/compositions/frames/<frame_id>.html. Do not edit any other file.
- `<template>` wrapping `#stage` with `data-composition-id="<frame_id>"`, `data-duration` = your frame length;
  one paused GSAP timeline registered at `window.__timelines["<frame_id>"]`, built synchronously, ending in
  `tl.seek(0)`. Use the host's global `gsap` (no gsap `<script>` tag). Deterministic: no Math.random, no Date,
  no network. Ids and classes that start with a digit must be selected with attribute selectors
  (`[id="07-works-x"]`, `[class~="07-works-y"]`) — or prefix them with a letter (e.g. `f07-…`), which is simpler.
- A full-bleed background must be its own full-duration layer inside #stage (not a background on #stage /
  the root). Light ground #F5F5F7, night ground #0B0B0D as the storyboard says.
- Fonts: `@font-face { font-family: "Inter Tight"; src: url("assets/fonts/InterTight-var-latin.woff2") }` and
  `"Inter"` → `assets/fonts/Inter-var-latin.woff2` (weight range 100 900). Images: `assets/img/<name>.jpg`.
  Paths resolve from the project root.
- UI must be big: when UI is the subject it fills ≥70% of its zone. Hero text readable, nothing in the outer
  6% of the frame (x<115, x>1805, y<65, y>1015) except what the storyboard places there.
- Every state change lands on an anchor from your block. Nothing enters before its anchor. Entrances
  expo.out, moves power3.inOut, exits power2.in; no back/elastic/bounce, no jitter, no glitch, no strobe, no
  infinite repeats.
- No HUD chrome of any kind: no corner labels, crop marks, timecode, frame counters, BPM/fps text.
- Use the real copy from your block verbatim (sentence case, en-GB spelling). No emoji.
- If your block includes a `<video>`, it must be `muted`, a direct child of `#stage`, with `data-start`,
  `data-duration`, `data-track-index`, and `data-media-start` for the in-point.

Finish by running your self-check (frame-worker.md). You may render a quick visual check of your own frame by
writing a temporary harness HTML in /private/tmp/claude-501/-Users-maxsalkov/8b0d32a7-0c91-40d0-a2e1-749ffd613bfb/scratchpad/
if you want, but do not run the `hyperframes` CLI on the project (the orchestrator runs lint/check after
assembly). Reply with the file path, the frame-local times of your key states, and anything in the plan you
could not realise.
