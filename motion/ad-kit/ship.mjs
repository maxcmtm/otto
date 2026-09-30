#!/usr/bin/env node
// Otto ad-kit — take a built project (build.mjs) to finished files:
//   lint → check (must pass) → render MP4 → verify loudness (−14 LUFS ± 0.5, fixes if needed) → AI provenance mark
//   → poster JPG → web MP4 (720 wide, ≤ 2.5 MB, faststart) → contact sheet (4 key frames) → copy to the given folders.
//
//   node ship.mjs <project-dir> [--name <basename>] [--final <dir>] [--web <dir>] [--web-max <MB, default 2.5>]
//                 [--skip-render] [--force]
//
// Uses `npx --yes hyperframes@0.8.91` (override with HF_CLI="…"); set npm_config_cache if your npx needs it.
// Provenance (EU AI Act Art. 50(2)): an ad with voice clips (sound.json "vo"; the house voice is ElevenLabs "Nora" via
// Higgsfield — set "voice": "human" in sound.json for a real recording) or with a placed image that carries an AI mark
// (assets/img/*, checked with otto_provenance.py inspect) gets its final + web MP4 marked as
// compositeSynthetic by platform/otto_provenance.py (MP4 tags + XMP + <file>.provenance.json); the
// posters too when an image is generated. A failed mark stops the ship (--force ships unmarked, with a warning).
// OTTO_PROVENANCE overrides the script path. The kit's own synthesized music bed (audio/score.py) is procedural, not AI.

import fs from "node:fs";
import path from "node:path";
import { execSync, spawnSync } from "node:child_process";

const HF = process.env.HF_CLI || "npx --yes hyperframes@0.8.91";
const PROV = process.env.OTTO_PROVENANCE || path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../platform/otto_provenance.py");

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > -1 ? process.argv[i + 1] : d;
};
const flag = (n) => process.argv.includes(`--${n}`);
const sh = (cmd, opts = {}) => execSync(cmd, { stdio: "pipe", encoding: "utf8", maxBuffer: 64 << 20, ...opts });
const q = (p) => `"${p}"`;

function loudness(file) {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-nostats", "-i", file, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"], { encoding: "utf8" });
  const log = r.stderr.slice(r.stderr.lastIndexOf("Summary:"));
  const i = parseFloat((log.match(/I:\s+(-?[\d.]+) LUFS/) || [])[1]);
  const tp = parseFloat((log.match(/Peak:\s+(-?[\d.]+) dBFS/) || [])[1]);
  return { i, tp };
}

// what in this ad is AI-generated → { kinds: ["voice", "image"], tool: "ElevenLabs via Higgsfield + …" }
function synthetic(dir) {
  const kinds = [];
  const tools = [];
  const imageTools = [];
  let sound = {};
  try {
    sound = JSON.parse(fs.readFileSync(path.join(dir, "sound.json"), "utf8"));
  } catch {}
  if ((sound.vo || []).length && sound.voice !== "human") {
    kinds.push("voice");
    tools.push(sound.voiceTool || "ElevenLabs via Higgsfield");
  }
  const imgDir = path.join(dir, "assets/img");
  const imgs = fs.existsSync(imgDir) ? fs.readdirSync(imgDir).filter((f) => /\.(jpe?g|png)$/i.test(f)).map((f) => path.join(imgDir, f)) : [];
  if (imgs.length) {
    const r = spawnSync("python3", [PROV, "inspect", "--json", ...imgs], { encoding: "utf8" });
    let rows = [];
    try {
      rows = [].concat(JSON.parse(r.stdout || "[]"));
    } catch {
      console.warn(`  provenance: could not inspect the ad's images (${(r.stderr || "").trim().slice(-160)})`);
    }
    const ai = rows.filter((x) => x.generated);
    if (ai.length) {
      kinds.push("image");
      ai.forEach((x) => (x.tool || x.ai_system) && imageTools.push(x.tool || x.ai_system));
      tools.push(...imageTools);
    }
  }
  return { kinds, tool: [...new Set(tools)].join(" + "), imageTool: [...new Set(imageTools)].join(" + ") };
}

function markAI(file, ai, kinds = ai.kinds) {
  const tool = kinds.includes("voice") ? ai.tool : ai.imageTool || "";
  const r = spawnSync("python3", [PROV, "mark", file, "--kind", kinds.join(","), "--tool", tool, "--composite"], { encoding: "utf8" });
  if (r.status !== 0) {
    const why = `AI provenance mark failed for ${path.basename(file)}: ${(r.stderr || r.stdout || "").trim().slice(-200)}`;
    if (!flag("force")) throw new Error(why + " (fix it, or pass --force to ship unmarked)");
    console.warn("  WARNING " + why);
    return;
  }
  console.log("  " + r.stdout.trim());
}

function main() {
  const dir = path.resolve(process.argv[2] || ".");
  const sched = JSON.parse(fs.readFileSync(path.join(dir, "schedule.json"), "utf8"));
  const name = arg("name", `${sched.id}-${sched.format}`);
  const out = path.join(dir, "renders");
  fs.mkdirSync(out, { recursive: true });
  const mp4 = path.join(out, `${name}.mp4`);

  if (!flag("skip-render")) {
    console.log(`▸ lint + check ${name}`);
    sh(`${HF} lint ${q(dir)}`);
    const chk = spawnSync(`${HF} check ${q(dir)}`, { shell: true, encoding: "utf8" });
    const summary = (chk.stdout + chk.stderr).replace(/\x1b\[[0-9;]*m/g, "").split("\n").filter((l) => /error\(s\)|Check (passed|failed)/.test(l));
    summary.forEach((l) => console.log("  " + l.trim()));
    if (chk.status !== 0 && !flag("force")) throw new Error(`check failed for ${name} — fix it (or pass --force)`);
    console.log(`▸ render ${name}`);
    sh(`${HF} render ${q(dir)} -o ${q(mp4)} --quiet`, { stdio: "inherit" });
  }

  // loudness: the soundtrack is mastered to −14 LUFS; confirm it survived the render, correct if not
  let L = loudness(mp4);
  if (Math.abs(L.i + 14) > 0.5) {
    const tmp = mp4.replace(/\.mp4$/, ".fix.mp4");
    const gain = (-14 - L.i).toFixed(2);
    sh(`ffmpeg -y -hide_banner -loglevel error -i ${q(mp4)} -c:v copy -af "volume=${gain}dB,alimiter=limit=0.89" -c:a aac -b:a 192k ${q(tmp)}`);
    fs.renameSync(tmp, mp4);
    L = loudness(mp4);
  }
  console.log(`  loudness ${L.i} LUFS, true peak ${L.tp} dBFS`);

  // provenance: the final MP4 carries the AI mark before anything is copied out (the web copy and posters below too)
  const ai = synthetic(dir);
  if (ai.kinds.length) markAI(mp4, ai);
  else console.log("  provenance: no synthetic voice or generated image in this ad — not marked");

  // poster: the fullest frame of the scene (just before the end card)
  const poster = path.join(out, `${name}.jpg`);
  sh(`ffmpeg -y -hide_banner -loglevel error -ss ${sched.posterAt} -i ${q(mp4)} -frames:v 1 -q:v 2 ${q(poster)}`);

  // web copy: 720 wide, faststart, ≤ --web-max MB (crf steps up until it fits)
  const WEB_MAX = parseFloat(arg("web-max", "2.5")) * 1024 * 1024;
  const web = path.join(out, `${name}-web.mp4`);
  for (const crf of [26, 28, 30, 32, 34]) {
    sh(
      `ffmpeg -y -hide_banner -loglevel error -i ${q(mp4)} -vf "scale=720:-2:flags=lanczos" -c:v libx264 -preset slow -crf ${crf} -profile:v high -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart ${q(web)}`,
    );
    if (fs.statSync(web).size <= WEB_MAX) break;
  }
  const webPoster = path.join(out, `${name}-web.jpg`);
  sh(`ffmpeg -y -hide_banner -loglevel error -i ${q(poster)} -vf scale=720:-2 -q:v 4 ${q(webPoster)}`);
  if (ai.kinds.length) markAI(web, ai);
  if (ai.kinds.includes("image")) [poster, webPoster].forEach((f) => markAI(f, ai, ["image"]));

  // contact sheet: hook, the idea mid-way, the full scene, the end card
  const times = [sched.hookAt, (sched.hookAt + sched.endAt) / 2, sched.posterAt, sched.duration - 0.25].map((t) => Math.max(0.05, Math.min(sched.duration - 0.05, t)).toFixed(2));
  const tiles = times.map((t, i) => {
    const f = path.join(out, `.sheet-${i}.png`);
    sh(`ffmpeg -y -hide_banner -loglevel error -ss ${t} -i ${q(mp4)} -frames:v 1 -vf "scale=360:-2,drawtext=text='${t}s':x=12:y=12:fontsize=20:fontcolor=white:box=1:boxcolor=0x000000AA:boxborderw=6" ${q(f)}`);
    return f;
  });
  const sheet = path.join(out, `${name}-sheet.jpg`);
  sh(`ffmpeg -y -hide_banner -loglevel error ${tiles.map((t) => `-i ${q(t)}`).join(" ")} -filter_complex "hstack=inputs=${tiles.length}" -q:v 3 ${q(sheet)}`);
  tiles.forEach((t) => fs.unlinkSync(t));

  const copyTo = (dest, files) => {
    if (!dest) return;
    fs.mkdirSync(dest, { recursive: true });
    files.forEach(([src, as]) => fs.copyFileSync(src, path.join(dest, as || path.basename(src))));
  };
  const side = (f, as) => (fs.existsSync(f + ".provenance.json") ? [[f + ".provenance.json", as && as + ".provenance.json"]] : []);
  copyTo(arg("final"), [[mp4], [poster], ...side(mp4)]);
  copyTo(arg("web"), [
    [web, `${name}.mp4`],
    [webPoster, `${name}.jpg`],
    ...side(web, `${name}.mp4`),
  ]);
  const mb = (f) => (fs.statSync(f).size / 1048576).toFixed(2) + " MB";
  console.log(`✓ ${name}: ${sched.duration}s · final ${mb(mp4)} · web ${mb(web)} · sheet ${sheet}`);
}

main();
