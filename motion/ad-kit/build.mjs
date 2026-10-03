#!/usr/bin/env node
// Otto ad-kit — brand tokens + one ad data file → a ready HyperFrames project (+ its synthesized soundtrack).
//
//   node build.mjs --brand <brand.json> --ad <ad.json> --out <project-dir> [--format 9x16|4x5|1x1] [--no-audio]
//
// The project it writes is a normal HyperFrames project: index.html (root: scene + end card + soundtrack),
// compositions/<style>.html and compositions/endcard.html (the kit templates with the brand tokens and the
// ad's data/timing baked in), assets/ (fonts, product images, soundtrack.wav). Then:
//   npx hyperframes lint <dir> && npx hyperframes check <dir> && npx hyperframes render <dir>
// or run ship.mjs, which does all of that plus the poster and the web copy.

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { schedule } from "./lib/schedule.mjs";

const KIT = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_UI_FONT = path.join(KIT, "..", "otto-kit", "fonts", "Inter-var-latin.woff2");
const FORMATS = { "9x16": { w: 1080, h: 1920 }, "4x5": { w: 1080, h: 1350 }, "1x1": { w: 1080, h: 1080 } };
const GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js";

const TOKEN_KEYS = ["bg", "surface", "ink", "muted", "line", "primary", "primaryDeep", "onPrimary", "accent", "onAccent", "night", "neutral", "wash"];

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
}
const flag = (name) => process.argv.includes(`--${name}`);
const readJSON = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

function imageSize(file) {
  const b = fs.readFileSync(file);
  if (b.slice(1, 4).toString() === "PNG") return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
  if (b[0] === 0xff && b[1] === 0xd8) {
    let i = 2;
    while (i < b.length) {
      const m = b[i + 1];
      const len = b.readUInt16BE(i + 2);
      if (m >= 0xc0 && m <= 0xc3) return { w: b.readUInt16BE(i + 7), h: b.readUInt16BE(i + 5) };
      i += 2 + len;
    }
  }
  const s = b.toString("utf8", 0, 2000);
  const vb = s.match(/viewBox="([\d.\s-]+)"/);
  if (vb) {
    const [, , w, h] = vb[1].trim().split(/\s+/).map(Number);
    return { w, h };
  }
  return { w: 1, h: 1 };
}

// WCAG contrast of two #rrggbb colours
function contrast(a, b) {
  const lum = (hex) => {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return null;
    const v = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  const la = lum(a);
  const lb = lum(b);
  if (la == null || lb == null) return 21;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// ground token → the colour for text and for the one highlight on that ground (the highlight must keep 3:1 —
// large-text AA — or it falls back to the text colour and the build says so)
function groundVars(name, c) {
  const dark = ["primary", "primaryDeep", "night"].includes(name);
  const on = dark ? "onPrimary" : name === "accent" ? "onAccent" : "ink";
  let hi = dark ? "accent" : name === "accent" ? "primaryDeep" : "primary";
  const sub = dark ? "onPrimary" : name === "accent" ? "onAccent" : "muted";
  if (c && contrast(c[hi], c[name]) < 3) {
    console.warn(`ad-kit: highlight ${hi} on ground ${name} is ${contrast(c[hi], c[name]).toFixed(2)}:1 (<3:1) — using ${on}; pick a darker/lighter ground for a coloured accent`);
    hi = on;
  }
  return { ground: name, on, hi, sub };
}

function tokensCSS(brand, ground) {
  const c = brand.colors;
  const lines = TOKEN_KEYS.filter((k) => c[k]).map((k) => `--c-${k}: ${c[k]};`);
  const g = groundVars(ground, c);
  lines.push(
    `--ad-ground: var(--c-${g.ground});`,
    `--ad-on: var(--c-${g.on});`,
    `--ad-hi: var(--c-${g.hi});`,
    `--ad-sub: var(--c-${g.sub});`,
    `--brand-track: ${(brand.fonts.brand && brand.fonts.brand.tracking) || "-0.03em"};`,
  );
  return lines.join("\n      ");
}

// STORYBOARD.md: the beat sheet this project was generated from (read-only record; edit the ad JSON, not this)
function storyboard(ad, sch, brand, fmtName) {
  const S = sch.S;
  const f = (t) => Number(t).toFixed(2);
  const beats = [];
  if (ad.style === "notes") {
    beats.push(`${f(S.title.times[0])}s title types: "${S.title.text}"`);
    S.rows.forEach((r) => beats.push(`${f(r.start)}s types "${r.text}" · struck ${f(r.strikeAt)}s`));
    beats.push(`${f(S.keep.start)}s types "${S.keep.text}" · marker ${f(S.keep.markAt)}s`);
  } else if (ad.style === "search") {
    beats.push(`${f(S.query.times[0])}s query types: "${S.query.text}"`, `${f(S.dropAt)}s autocomplete drops`);
    S.steps.forEach((st) => beats.push(`${f(st.t)}s highlight → "${ad.search.suggestions[st.i]}"`));
    beats.push(`${f(S.chooseAt)}s chosen · ${f(S.resultAt)}s result card · ${f(S.starsAt)}s stars fill`);
  } else if (ad.style === "texts") {
    S.messages.forEach((m) => beats.push(`${f(m.at)}s ${m.from}: ${m.photo ? "[photo]" : `"${m.text}"`}${m.dotsAt != null ? ` (dots ${f(m.dotsAt)}s)` : ""}${m.typeAt != null ? ` (typed from ${f(m.typeAt)}s)` : ""}`));
  } else if (ad.style === "versus") {
    beats.push(`${f(S.labelsAt[0])}s "${ad.versus.left.label}" · ${f(S.labelsAt[1])}s "${ad.versus.right.label}" · ${f(S.vsAt)}s vs`);
    S.rows.forEach((r, i) => beats.push(`${f(r.left)}s ✕ ${ad.versus.left.rows[i]} · ${f(r.right)}s ✓ ${ad.versus.right.rows[i]}`));
    if (ad.versus.footer) beats.push(`${f(S.footerAt)}s footer: "${ad.versus.footer}"`);
  } else if (ad.style === "reel") {
    S.cues.forEach((c) => beats.push(`${f(c.at)}s ${c.endcard ? "end card" : c.stat ? "stat" : c.shot ? c.shot.kind + " " + c.shot.asset : "type"}${c.line != null ? `: "${ad.reel.lines[c.line]}"` : ""} · voice ${f(c.dur)}s`));
  } else if (ad.style === "big") {
    beats.push(`0.00s macro pull-back on the hero`);
    S.phrases.forEach((p) => beats.push(`${f(p.at)}s "${p.big}"${p.rest ? ` · ${f(p.restAt)}s "${p.rest}"` : ""}${p.product ? " · product swings in" : ""}`));
  }
  const e = ad.endcard || {};
  beats.push(`${f(sch.endAt)}s end card (${e.ground || "bg"}): "${e.headline || ""}" · ${e.sub || ""}${e.fine ? " · " + e.fine : ""}`);
  return `---
format: ${fmtName}
duration: ${sch.duration}s
style: ${ad.style}
brand: ${brand.name}
angle: ${ad.angle || ""}
music: synthesized ${(ad.music && ad.music.mood) || "calm"} bed, ${sch.bpm} BPM, −14 LUFS (audio/score.py)
generated: by motion/ad-kit/build.mjs from the ad JSON; edit the JSON and rebuild, not this file
---

## Beats (seconds, beat-locked)

${beats.map((b) => "- " + b).join("\n")}
- ${sch.duration}s end
`;
}

function frameMd(brand, ad) {
  const c = brand.colors;
  return `---
name: ${ad.id}
colors:
${Object.entries(c).map(([k, v]) => `  ${k}: "${v}"`).join("\n")}
fonts:
  display: "AdKit Brand = ${brand.fonts.brand.file} (assets/fonts/brand.woff2)"
  ui: "AdKit UI = ${(brand.fonts.ui && brand.fonts.ui.file) || "Inter (kit default)"} (assets/fonts/ui.woff2)"
---

# ${brand.name} · ${ad.style} ad (Otto ad-kit)

Tokens arrive as CSS variables on each composition root (\`--c-<token>\`, plus \`--ad-ground/on/hi/sub\` for the
composition's ground). Scene ground: \`${(ad.scene && ad.scene.ground) || "bg"}\`; end card ground:
\`${(ad.endcard && ad.endcard.ground) || "bg"}\`. One accent per frame, generic UI, no HUD, no fake buttons,
motion on the beat. See motion/ad-kit/README.md.
`;
}

function fill(tpl, map) {
  let out = tpl;
  for (const [k, v] of Object.entries(map)) out = out.split(k).join(v);
  return out;
}

function main() {
  const brandPath = arg("brand");
  const adPath = arg("ad");
  const outDir = arg("out");
  if (!brandPath || !adPath || !outDir) {
    console.error("usage: node build.mjs --brand <brand.json> --ad <ad.json> --out <dir> [--format 9x16|4x5|1x1] [--no-audio]");
    process.exit(2);
  }
  const brand = readJSON(brandPath);
  const ad = readJSON(adPath);
  const fmtName = arg("format", (ad.formats && ad.formats[0]) || "9x16");
  const fmt = FORMATS[fmtName];
  if (!fmt) throw new Error(`unknown format ${fmtName}`);
  const assetRoot = path.resolve(path.dirname(brandPath), brand.assetRoot || ".");
  // reel: voice clips (paths relative to the ad file) → measured lengths for the scheduler
  const clips = [];
  if (ad.style === "reel") {
    ad.__clipDur = ad.reel.cues.map((c) => {
      if (!c.clip) return c.dur || 2.0; // a silent cue (no voice clip): its own length, else 2 s
      const src = path.resolve(path.dirname(adPath), c.clip);
      const dur = parseFloat(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], { encoding: "utf8" }));
      clips.push({ src, clip: c.clip });
      return Math.round(dur * 1000) / 1000;
    });
  }
  const sch = schedule(ad);

  const dir = path.resolve(outDir);
  for (const d of ["compositions", "assets/img", "assets/fonts", "assets/audio"]) fs.mkdirSync(path.join(dir, d), { recursive: true });

  // fonts: brand display face + neutral UI face (kit default Inter)
  const bf = brand.fonts.brand;
  fs.copyFileSync(path.resolve(assetRoot, bf.file), path.join(dir, "assets/fonts/brand.woff2"));
  const uiFont = brand.fonts.ui && brand.fonts.ui.file ? path.resolve(assetRoot, brand.fonts.ui.file) : DEFAULT_UI_FONT;
  fs.copyFileSync(uiFont, path.join(dir, "assets/fonts/ui.woff2"));

  // assets: every role the ad references, copied as assets/img/<role>.<ext>
  const roles = new Set();
  ((ad.endcard && ad.endcard.products) || []).forEach((r) => roles.add(r));
  if (ad.endcard && ad.endcard.logo) roles.add(ad.endcard.logo);
  if (ad.style === "search" && ad.search.result.image) roles.add(ad.search.result.image);
  if (ad.style === "texts") ad.thread.messages.forEach((m) => m.photo && roles.add(m.photo));
  if (ad.style === "versus" && ad.versus.right.image) roles.add(ad.versus.right.image);
  if (ad.style === "versus" && ad.versus.left.image) roles.add(ad.versus.left.image);
  if (ad.style === "reel") ad.reel.cues.forEach((c) => c.shot && c.shot.asset && roles.add(c.shot.asset));
  if (ad.style === "big") {
    roles.add(ad.big.hero);
    ad.big.phrases.forEach((p) => p.product && roles.add(p.product));
  }
  const assets = {};
  for (const role of roles) {
    const rel = brand.assets[role];
    if (!rel) throw new Error(`brand has no asset for role "${role}"`);
    const src = path.resolve(assetRoot, rel);
    const ext = path.extname(src).toLowerCase();
    const dest = `assets/img/${role}${ext}`;
    fs.copyFileSync(src, path.join(dir, dest));
    assets[role] = { src: dest, ...imageSize(src) };
  }

  const base = {
    id: ad.id,
    style: ad.style,
    fmt: { name: fmtName, w: fmt.w, h: fmt.h },
    bpm: sch.bpm,
    beat: sch.beat,
    duration: sch.duration,
    endAt: sch.endAt,
    c: brand.colors,
    brand: { name: brand.name, site: brand.site },
    assets,
  };
  // voice clips → assets/audio/vo-NN.wav (the soundtrack mixes them; the composition never plays audio itself)
  const voPlaced = (sch.vo || []).map((v, i) => {
    const c = clips.find((x) => x.clip === v.clip);
    const dest = path.join(dir, "assets/audio", `vo-${String(i).padStart(2, "0")}${path.extname(c.src)}`);
    fs.copyFileSync(c.src, dest);
    return { file: dest, t: v.t };
  });
  const sceneData = { ...base, scene: ad.scene || {}, content: ad[{ notes: "note", search: "search", texts: "thread", versus: "versus", big: "big", reel: "reel" }[ad.style]], S: sch.S };
  const endGround = (ad.endcard && ad.endcard.ground) || "bg";
  const endData = { ...base, duration: sch.endDur, endcard: { ...ad.endcard, legal: ad.endcard && ad.endcard.legal ? brand.legal[ad.endcard.legal] || ad.endcard.legal : "" } };

  const common = { __W__: String(fmt.w), __H__: String(fmt.h), __GSAP__: GSAP };
  const styleTpl = fs.readFileSync(path.join(KIT, "templates/styles", `${ad.style}.html`), "utf8");
  fs.writeFileSync(
    path.join(dir, "compositions", `${ad.style}.html`),
    fill(styleTpl, { ...common, __DUR__: String(sch.duration), "/*@TOKENS*/": tokensCSS(brand, (ad.scene && ad.scene.ground) || "bg"), "/*@DATA*/null": JSON.stringify(sceneData) }),
  );
  const endTpl = fs.readFileSync(path.join(KIT, "templates/endcard.html"), "utf8");
  fs.writeFileSync(
    path.join(dir, "compositions", "endcard.html"),
    fill(endTpl, { ...common, __DUR__: String(sch.endDur), "/*@TOKENS*/": tokensCSS(brand, endGround), "/*@DATA*/null": JSON.stringify(endData) }),
  );
  const sceneGround = brand.colors[(ad.scene && ad.scene.ground) || "bg"];
  const idx = fs.readFileSync(path.join(KIT, "templates/index.html"), "utf8");
  fs.writeFileSync(
    path.join(dir, "index.html"),
    fill(idx, {
      ...common,
      __DUR__: String(sch.duration),
      __STYLE__: ad.style,
      __END__: String(sch.endAt),
      __ENDDUR__: String(sch.endDur),
      __BG__: sceneGround,
      __TITLE__: `${brand.name} — ${ad.id} (${fmtName})`,
    }),
  );

  const name = `${ad.id}-${fmtName}`;
  fs.writeFileSync(
    path.join(dir, "hyperframes.json"),
    JSON.stringify({ $schema: "https://hyperframes.heygen.com/schema/hyperframes.json", registry: "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry", paths: { blocks: "compositions", components: "compositions/components", assets: "assets" }, media: { autoProxy: true } }, null, 2) + "\n",
  );
  fs.writeFileSync(path.join(dir, "package.json"), JSON.stringify({ name, private: true, type: "module", scripts: { check: "npx --yes hyperframes@0.8.91 check", render: "npx --yes hyperframes@0.8.91 render" } }, null, 2) + "\n");
  fs.writeFileSync(path.join(dir, "meta.json"), JSON.stringify({ id: name, name, createdAt: "generated by otto ad-kit" }, null, 2) + "\n");
  fs.writeFileSync(path.join(dir, "STORYBOARD.md"), storyboard(ad, sch, brand, fmtName));
  fs.writeFileSync(path.join(dir, "frame.md"), frameMd(brand, ad));
  const sound = { bpm: sch.bpm, duration: sch.duration, endAt: sch.endAt, mood: (ad.music && ad.music.mood) || "calm", key: (ad.music && ad.music.key) || "F", events: sch.events, vo: voPlaced };
  fs.writeFileSync(path.join(dir, "sound.json"), JSON.stringify(sound, null, 1) + "\n");
  fs.writeFileSync(
    path.join(dir, "schedule.json"),
    JSON.stringify({ id: ad.id, style: ad.style, format: fmtName, duration: sch.duration, endAt: sch.endAt, hookAt: sch.hookAt, posterAt: sch.posterAt, bpm: sch.bpm, S: sch.S }, null, 1) + "\n",
  );

  if (!flag("no-audio")) {
    execFileSync("python3", [path.join(KIT, "audio/score.py"), "--sound", path.join(dir, "sound.json"), "--out", path.join(dir, "assets/audio/soundtrack.wav")], { stdio: "inherit" });
  }
  console.log(`built ${name}: ${sch.duration}s (end card at ${sch.endAt}s, poster ${sch.posterAt}s) → ${dir}`);
}

main();
