// Ad-kit scheduler — turns an ad's content into beat-locked times.
//
// One function per style. Each returns { S, events, endAt, posterAt, hookAt }:
//   S       — everything the composition needs to animate (per-character type times, strike/pop/send times …)
//   events  — the sound cue list for audio/score.py ({ t, type, gain? })
//   endAt   — when the shared end card starts (always on a beat)
// Everything is deterministic: typing jitter comes from a PRNG seeded with the ad id.

const r3 = (x) => Math.round(x * 1000) / 1000;

export function grid(bpm) {
  const beat = 60 / bpm;
  // next(t, div): the first grid point >= t, on 1/div of a beat (div 1 = beats, 2 = 8ths)
  const next = (t, div = 1) => {
    const s = beat / div;
    return r3(Math.ceil(t / s - 1e-6) * s);
  };
  return { bpm, beat, bar: beat * 4, next };
}

export function prng(seedText) {
  let h = 2166136261;
  for (const c of String(seedText)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  let a = h >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Human-ish typing: one time per character, jittered, a little faster on spaces, a pause after punctuation.
export function typeText(text, t0, cps, rand) {
  const times = [];
  let t = t0;
  for (const ch of Array.from(text)) {
    times.push(r3(t));
    let dt = (1 / cps) * (0.72 + 0.56 * rand());
    if (ch === " ") dt *= 0.75;
    if (",.?!".includes(ch)) dt += 0.1;
    t += dt;
  }
  return { times, end: r3(t) };
}

function keyEvents(events, text, times, gain = 1) {
  Array.from(text).forEach((ch, i) => {
    events.push({ t: times[i], type: ch === " " ? "space" : "key", gain });
  });
}

// ── 1. notes ─────────────────────────────────────────────────────────────────────────────────────────
function notes(ad, g, rand) {
  const n = ad.note;
  const T = ad.timing || {};
  const cps = T.cps || 19;
  const E = [];
  let t = T.startAt ?? 0.3;
  const title = typeText(n.title, t, T.titleCps || 16, rand);
  keyEvents(E, n.title, title.times);
  t = g.next(title.end + 0.28, 2);
  const rows = [];
  for (const text of n.struck) {
    E.push({ t, type: "return" });
    const ty = typeText(text, r3(t + 0.08), cps, rand);
    keyEvents(E, text, ty.times);
    const strikeAt = g.next(ty.end + 0.18, 1);
    E.push({ t: strikeAt, type: "strike" });
    rows.push({ text, start: t, times: ty.times, strikeAt });
    t = g.next(strikeAt + 0.3, 2);
  }
  E.push({ t, type: "return" });
  const ky = typeText(n.keep, r3(t + 0.08), cps, rand);
  keyEvents(E, n.keep, ky.times);
  const markAt = g.next(ky.end + 0.2, 2);
  E.push({ t: markAt, type: "mark" });
  const endAt = g.next(markAt + (T.hold ?? 0.95), 1);
  return {
    S: { title: { text: n.title, times: title.times }, rows, keep: { text: n.keep, start: t, times: ky.times, markAt } },
    events: E,
    endAt,
    hookAt: title.end,
    posterAt: r3(endAt - 0.1),
  };
}

// ── 2. search ────────────────────────────────────────────────────────────────────────────────────────
function search(ad, g, rand) {
  const s = ad.search;
  const T = ad.timing || {};
  const E = [];
  const q = typeText(s.query, T.startAt ?? 0.35, T.cps || 17, rand);
  keyEvents(E, s.query, q.times);
  const dropAt = g.next(q.end + 0.12, 2);
  E.push({ t: dropAt, type: "drop" });
  const steps = [];
  let h = g.next(dropAt + 0.45, 1);
  for (let i = 0; i <= s.pick; i++) {
    steps.push({ i, t: h });
    E.push({ t: h, type: "select" });
    h = r3(h + g.beat / 2);
  }
  const chooseAt = g.next(steps[steps.length - 1].t + 0.4, 2);
  E.push({ t: chooseAt, type: "enter" });
  const resultAt = g.next(chooseAt + 0.45, 1);
  E.push({ t: resultAt, type: "card" });
  const starsAt = r3(resultAt + 0.45);
  const rated = s.result && (s.result.rating != null || s.result.ratingText);
  if (rated) for (let i = 0; i < 5; i++) E.push({ t: r3(starsAt + i * 0.07), type: "star", gain: 0.8 });
  const endAt = g.next(resultAt + (T.read ?? 2.7), 1);
  return {
    S: { query: { text: s.query, times: q.times }, dropAt, steps, chooseAt, resultAt, starsAt },
    events: E,
    endAt,
    hookAt: q.end,
    posterAt: r3(endAt - 0.1),
  };
}

// ── 3. texts ─────────────────────────────────────────────────────────────────────────────────────────
function texts(ad, g, rand) {
  const T = ad.timing || {};
  const cps = T.cps || 21;
  const dots = T.dots ?? 0.7;
  const E = [];
  let t = T.startAt ?? 0.25;
  const msgs = [];
  ad.thread.messages.forEach((m, i) => {
    if (i === 0 && m.from === "me" && T.firstInstant !== false && !m.photo) {
      // the thread opens on a message already sent (the hook is on screen from the first frame)
      E.push({ t, type: "pop", gain: 0.8 });
      msgs.push({ ...m, instant: true, at: t });
      t = r3(t + 0.35 + 0.07 * m.text.split(/\s+/).length);
      return;
    }
    if (m.from === "them") {
      let dotsAt = null;
      let popAt = t;
      if (!(i === 0 && T.firstInstant !== false)) {
        dotsAt = t;
        popAt = g.next(t + dots, 2);
        E.push({ t: dotsAt, type: "dots", gain: 0.7 });
      }
      E.push({ t: popAt, type: "pop" });
      msgs.push({ ...m, dotsAt, at: popAt });
      const words = (m.text || "").split(/\s+/).length;
      t = r3(popAt + 0.3 + 0.07 * words);
    } else if (m.photo) {
      const sendAt = g.next(t + 0.05, 2);
      E.push({ t: sendAt, type: "send" });
      msgs.push({ ...m, at: sendAt });
      t = r3(sendAt + (T.photoHold ?? 0.85));
    } else {
      const ty = typeText(m.text, t, cps, rand);
      keyEvents(E, m.text, ty.times, 0.9);
      const sendAt = g.next(ty.end + 0.18, 2);
      E.push({ t: sendAt, type: "send" });
      msgs.push({ ...m, typeAt: t, times: ty.times, at: sendAt });
      t = r3(sendAt + 0.4);
    }
  });
  const last = msgs[msgs.length - 1];
  const endAt = g.next(last.at + (T.hold ?? 1.25), 1);
  return { S: { messages: msgs }, events: E, endAt, hookAt: msgs[0].at + 0.5, posterAt: r3(endAt - 0.1) };
}

// ── 4. versus ────────────────────────────────────────────────────────────────────────────────────────
function versus(ad, g) {
  const T = ad.timing || {};
  const v = ad.versus;
  const E = [];
  const labelsAt = [0.12, 0.42];
  const vsAt = g.next(0.6, 2);
  E.push({ t: labelsAt[0], type: "swish", gain: 0.7 }, { t: labelsAt[1], type: "swish", gain: 0.7 }, { t: vsAt, type: "tick" });
  const illoAt = [g.next(0.75, 2), g.next(1.0, 2)];
  E.push({ t: illoAt[1], type: "land", gain: 0.7 });
  let t = g.next(T.rowsAt ?? 1.5, 1);
  const rows = v.left.rows.map((_, i) => {
    const r = { left: t, right: r3(t + g.beat) };
    E.push({ t: r.left, type: "cross" }, { t: r.right, type: "check" });
    t = r3(t + 2 * g.beat);
    return r;
  });
  const footerAt = g.next(rows[rows.length - 1].right + (T.footerGap ?? 0.75), 1);
  E.push({ t: footerAt, type: "mark" });
  const endAt = g.next(footerAt + (T.hold ?? 2.0), 1);
  return { S: { labelsAt, vsAt, illoAt, rows, footerAt }, events: E, endAt, hookAt: 1.0, posterAt: r3(endAt - 0.1) };
}

// ── 5. big ───────────────────────────────────────────────────────────────────────────────────────────
function big(ad, g) {
  const T = ad.timing || {};
  const E = [];
  const firstAt = g.next(T.firstAt ?? 1.5, 1);
  E.push({ t: 0, type: "riser", len: firstAt });
  const every = (T.everyBeats ?? 3) * g.beat;
  let t = firstAt;
  const phrases = ad.big.phrases.map((p, i) => {
    const out = { ...p, at: t, restAt: p.rest ? r3(t + g.beat / 2) : null };
    E.push({ t, type: i === ad.big.phrases.length - 1 ? "impact" : "hit" });
    if (out.restAt) E.push({ t: out.restAt, type: "tick", gain: 0.8 });
    t = r3(t + every);
    return out;
  });
  const last = phrases[phrases.length - 1];
  const endAt = g.next(last.at + (T.hold ?? 2.5), 1);
  return { S: { firstAt, phrases }, events: E, endAt, hookAt: firstAt, posterAt: r3(last.at + 0.9) };
}

// ── 6. reel (voiceover b-roll) ───────────────────────────────────────────────────────────────────────
// Timed by the voice, not the bar grid: each cue starts when the previous voice clip ends (+ a small gap).
// build.mjs measures the clips and passes their lengths as ad.__clipDur (same order as reel.cues).
function reel(ad) {
  const R = ad.reel;
  const T = ad.timing || {};
  const gap = T.gap ?? 0.14;
  const E = [];
  let t = T.startAt ?? 0.3;
  let prevShot = null;
  const cues = R.cues.map((c, i) => {
    const dur = (ad.__clipDur || [])[i] || 2.0;
    const out = { ...c, at: r3(t), dur: r3(dur) };
    const shotKey = c.stat ? "stat" : JSON.stringify(c.shot || null);
    if (i > 0 && !c.endcard && shotKey !== prevShot) E.push({ t: out.at, type: c.stat ? "card" : "swish", gain: 0.55 });
    if (c.stat) E.push({ t: r3(out.at + 0.95), type: "tick", gain: 0.8 });
    prevShot = shotKey;
    t = r3(t + dur + gap);
    return out;
  });
  const endCue = cues.find((c) => c.endcard);
  const endAt = endCue ? endCue.at : r3(t + 0.2);
  const endDur = r3(endCue ? Math.max(3.0, endCue.dur + (T.tail ?? 1.5)) : 3.2);
  const vo = cues.filter((c) => c.clip).map((c) => ({ clip: c.clip, t: c.at }));
  const lastScene = cues.filter((c) => !c.endcard).pop();
  return { S: { cues }, events: E, endAt, endDur, vo, hookAt: r3(cues[0].at + 0.9), posterAt: r3(lastScene ? Math.min(endAt - 0.1, lastScene.at + 1.2) : endAt - 0.1) };
}

const STYLES = { notes, search, texts, versus, big, reel };

export function schedule(ad) {
  const fn = STYLES[ad.style];
  if (!fn) throw new Error(`unknown style "${ad.style}" (expected one of ${Object.keys(STYLES).join(", ")})`);
  const bpm = (ad.music && ad.music.bpm) || 120;
  const g = grid(bpm);
  const out = fn(ad, g, prng(ad.id || ad.style));
  const endDur = out.endDur || (ad.endcard && ad.endcard.duration) || 3.2;
  const duration = r3(out.endAt + endDur);
  out.events.push({ t: out.endAt, type: "sheet" }, { t: r3(out.endAt + 0.38), type: "land" });
  out.events.sort((a, b) => a.t - b.t);
  return { ...out, bpm, beat: g.beat, duration, endDur };
}
