# Frame-worker dispatch — Otto vertical explainer (1080×1920, voice-over, captions on)

PROJECT_DIR: /Users/maxsalkov/otto/motion/otto-explainer
Canvas: 1080×1920, 30 fps. Audio and captions live on the root; your frame is silent.

Read, in this order, before writing anything:
1. /Users/maxsalkov/.claude/skills/hyperframes/references/frame-worker-core.md — the worker contract and
   self-check codes (template transport, #root styling, one paused timeline, gsap_css_transform_conflict…).
2. /Users/maxsalkov/.claude/skills/faceless-explainer/sub-agents/frame-worker.md — this workflow's delta.
3. /Users/maxsalkov/.claude/skills/hyperframes-core/references/sub-compositions.md and
   /Users/maxsalkov/.claude/skills/hyperframes-core/references/determinism-rules.md.
4. PROJECT_DIR/STORYBOARD.md — `## Video direction` (the whole film's system) and **your** `## Frame N` block.
   Cues are frame-local seconds from the real voice. Honour `handoff_in` / `handoff_out` geometry exactly.
5. PROJECT_DIR/frame.md — palette, type, depth, motion, ban list.
6. PROJECT_DIR/assets/kit.css — component geometry (`ok-*`); inline what you use into your frame's `<style>`,
   namespaced to your frame, and **scale it up** — this film is watched on a phone.
7. /Users/maxsalkov/otto/skills/otto-motion-director/references/motion-playbook.md — §1 rules and §2 ban list.

Hard rules:
- Write exactly one file: PROJECT_DIR/compositions/frames/<frame_id>.html (frame_id = the `src` file stem).
- `<template>` wrapping the root with `data-composition-id="<frame_id>"`, `data-duration` = your frame's
  `duration`; everything (style, scripts, the gsap `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js">`)
  inside the template; exactly one paused GSAP timeline registered at `window.__timelines["<frame_id>"]`,
  built synchronously. Deterministic: no Math.random, no Date, no network besides the gsap script.
- Ids/classes: prefix with a letter (e.g. `e05-…`) so no selector starts with a digit.
- Full-bleed ground (#F5F5F7) is its own full-duration `class="clip"` layer inside the root.
- Fonts: `@font-face { font-family: "Inter Tight"; src: url("assets/fonts/InterTight-var-latin.woff2") format("woff2"); font-weight: 100 900; }`
  and "Inter" → `assets/fonts/Inter-var-latin.woff2`. Images `assets/img/<name>.jpg`. Paths resolve from the project root.
- Readability: UI text ≥ 36px (small labels ≥ 30px), headlines 84–104px, cards 900–960px wide. Content inside
  x 60–1020, y 250–1560. The caption band (y ≥ 1594) stays empty.
- Every element enters on its cue, not before. Entrances expo.out, moves power3.inOut, exits power2.in; no
  back/elastic/bounce, no jitter, no glitch, no infinite repeats. End on a held readable state unless the
  handoff says otherwise.
- No HUD chrome, no topbar, no emoji. Copy verbatim from your block (en-GB).
- A `<video>` must be `muted`, a direct child of the root, with `data-start`, `data-duration`,
  `data-track-index`, `data-media-start`, and `class="clip"`.

Do not run the `hyperframes` CLI on the project (the orchestrator runs lint/check after assembly). Reply with
the file path, the frame-local times of your key states, and anything in the plan you could not realise.
