#!/usr/bin/env python3
"""Otto video ads — every faceless video cell the copywriter scripted in a brand's monthly ad matrix becomes a finished,
checked mp4 in the BRAND's look, so the paid flight launches videos next to its statics without a person in between.

  otto_advideo.py render --brand B [--month YYYY-MM] [--only id,id] [--force] [--dry]
                                            # B's month (default: this month, brand time): render what is scripted, under
                                            # the plan's cap; --force re-renders cached cells too; --dry lists, renders nothing
  otto_advideo.py daily  --brand B [--dry]  # otto_cron "ad-videos" (19:15 brand time): this month + next month's matrix
  otto_advideo.py status [--brand B] [--json]   # per brand and month: rendered, to render, failed, over the plan's cap
  otto_advideo.py check                     # the toolchain here: node, npx, ffmpeg, numpy + scipy, the kit, the HyperFrames pin
  (the same render: otto_creative.py videos --brand B [--month M] [--dry])

What renders: brands/<id>/ads-<YYYY-MM>.json cells with "format": "video" whose otto_styles.check_matrix status is
"scripted" — the copywriter (otto_copy.write_ads) wrote their beats + end card into the cell's "data", they passed
compliance, and no kit JSON exists — on the HyperFrames ad kit (motion/ad-kit: notes, search, texts, versus, big, reel).
A cell with a hand-made kit JSON (video.data on disk, e.g. Otto's own launch kit) or a delivered "file" is a person's:
never touched. Plan (plans.json): features.video_ads, and limits.video_ads_per_month caps the finished faceless videos
of the month in concept order (the order otto_creative.plan_video launches them) — Starter: 10. A cell that failed in
the last 6 hours does not hold a slot, so the next scripted cell takes it.

The brand's look (brand_kit): otto_render.brand_tokens (the profile's VISUAL IDENTITY, else the scan's palette; the
same tokens the statics use) mapped onto the kit's fixed colour vocabulary, the grounds per style chosen so text keeps
4.5:1; the display face = the brand's own Google sans from the scan (latin woff2, fetched once into OTTO_FONT_CACHE;
offline → the kit's Inter Tight, the statics' default face); the logo (brands/<id>/logo.*, logo-white.* for dark end
cards; a white-only logo forces a dark end card); a transparent product cut-out (otto_styles.brand_assets) as the end
card's pack and the big style's hero, a real site / product photo for the reel's photo cards, the search result and the
versus side (else the logo). Never Otto's own look. Right-to-left brands (he / ar / fa / ur) are not rendered yet: the kit
has no RTL layout — the cells stay scripted and the owner gets one card.

Per cell (render_cell): the cell's copy → one kit JSON (motion/ad-kit/from_matrix.py's shape, copy verbatim; the reel's
cues are made here: one line per cue, timed by its length — no voice, so nothing is synthetic) → for 9:16 and, for the
kits with a tuned 4:5 layout (notes, texts), 4:5: build.mjs (project + synthesized score) → length 9–30 s (a short ad's
end card is held longer; a longer one fails) → 9:16 only: the layout is moved into Meta's safe zone (SAFE_916: no text in
the top 14 % / bottom 20 %) and `hyperframes check --caption-zone` must find no text element in either band at the
ad's key moments → ship.mjs (lint, check, render, −14 LUFS, poster, contact sheet) → ffprobe (size, codecs, length)
→ ≤ 10 MB (re-encoded at a higher CRF when bigger, else it fails) → assets/ads/<otto_paths.token_name> (unguessable,
the matrix's own media token + the beats hash in the stem, so new beats get new names) + the poster jpg → AI provenance:
when a placed picture carries an AI mark (otto_provenance.inspect, e.g. a genvisuals image) the mp4 and its poster are
marked compositeSynthetic with a sidecar, like every other render path; the kit's music is procedural, there is no voice
→ otto_paths.publish (public before anything points at it) → the cell, re-read under the brand's file lock
(locks/adfiles-<id>.lock, the copywriter's): "file" (the 9:16 mp4), "poster", "status": "rendered" and
"render" {by, at, hash (otto_styles.video_hash of the beats), kit, hf, files {9x16, 4x5: {file, poster, duration, bytes}},
media_ai}. otto_creative.build_matrix takes "file" + "poster" as the story video and render.files["4x5"] as the feed
video; otto_ads launches them (one video ad, the 9:16 on Stories / Reels, the 4:5 elsewhere). The beats changed while it
rendered → the result is dropped (the next run renders the new beats).

Caching: a cell whose render.hash equals its beats and whose files are on disk is not rendered again; new beats make it
"scripted" again (otto_styles.validate_cell: a stale video never launches with old copy) and it re-renders.
Failures: logged (video.log / the job log), the cell stays scripted (its statics and every other cell still launch), the
reason in render.failed {hash, at, error, attempts}; retried after 6 hours or when the beats change. A cell that failed in
two runs (or a brand that cannot render at all) → one owner card "Video ads not rendering: <Brand>" (audience owner),
updated while it is open and resolved once the brand's videos render.

Triggers: otto_copy.write_ads ends by calling spawn(bid, month) when the month has something to render — on the server
(OTTO_COPY_QUEUE) it drops <id>.<month>.videos into the copywriter's queue and otto-copy-queue.service renders it in the
jobs' sandbox (Chrome works there; the queue runs trial kickoffs and ad copy first and a render steps aside for them —
run_queued(yield_to)); locally it starts `otto_advideo.py render` in the background (video.log next to data.json). The
nightly otto_cron "ad-videos" job (19:15 brand time: rendered overnight, long before the next 06:00 launch) catches up
whatever the trigger missed: failures due for a retry, copy a person fixed, stale videos, hand-written months.
Guards: one render at a time per server (flock locks/video-render.lock, held per cell, waited for within the run's
budget) so one big brand never starves the box; one run per brand (locks/advideo-<id>.lock); a time limit per step
(build 3 min, safe-zone check 4 min, ship OTTO_VIDEO_RENDER_TIMEOUT_S = 15 min: the process group is killed) and a
budget per run (queue 40 min, nightly 100 min; what is left waits for the next run). SIGTERM (otto_cron's limit) kills the
render in flight.
Needs: node ≥ 22 + npx (HyperFrames HF_PKG — the version ship.mjs pins; infra/bootstrap.sh installs it and warms the
cache), ffmpeg + ffprobe, python3-numpy + python3-scipy (the kit's score), headless Chrome (HyperFrames' managed
chrome-headless-shell, `npx hyperframes browser ensure`). npx always gets a writable cache (npm_config_cache, else
OTTO_NPM_CACHE, else <tmp>/otto-npm-cache — never a root-owned ~/.npm); HyperFrames telemetry and update checks are off.
"""
import contextlib, copy, fcntl, json, os, re, shutil, signal, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_paths as paths
import otto_provenance as prov

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
KIT = Path(os.environ.get("OTTO_ADKIT") or REPO / "motion" / "ad-kit")
KIT_FONTS = REPO / "motion" / "otto-kit" / "fonts"
HF_PKG = "hyperframes@0.8.91"                       # = motion/ad-kit/ship.mjs + build.mjs; infra/bootstrap.sh pins the same
CONTENT_KEY = {"notes": "note", "search": "search", "texts": "thread", "versus": "versus", "big": "big", "reel": "reel"}
TUNED_45 = ("notes", "texts")                       # the kits with an art-directed 4:5 layout (motion/ad-kit/README, Formats)
DIMS = {"9x16": (1080, 1920), "4x5": (1080, 1350)}
MAX_BYTES = 10 * 1024 * 1024
MIN_S, MAX_S = 9.0, 30.0
SAFE_TOP, SAFE_BOTTOM = 0.14, 0.20                  # Meta's Stories / Reels UI: no text in the top 14 % / bottom 20 %
RETRY_AFTER = timedelta(hours=6)
CARD_AFTER = 2                                      # failed runs of one cell before the owner card
BUILD_TIMEOUT_S, CHECK_TIMEOUT_S = 180, 240
QUEUE_BUDGET_S, DAILY_BUDGET_S = 40 * 60, 100 * 60
RTL_LANGS = ("he", "ar", "fa", "ur")
CARD_TITLE = "Video ads not rendering: {name}"
ENDCARD_COPY = ("headline", "accent", "sub", "fine", "legal")
DARK = ("primary", "primaryDeep", "night")
# per kit: (scene grounds, end card grounds) in order of preference — the first whose text keeps 4.5:1 wins
GROUNDS = {"notes": (("primary", "primaryDeep", "bg"), ("bg",)),
           "texts": (("wash", "bg"), ("primary", "primaryDeep", "night", "bg")),
           "versus": (("bg",), ("night", "primaryDeep", "primary", "bg")),
           "big": (("primary", "primaryDeep", "night", "bg"), ("bg",)),
           "search": (("bg",), ("primary", "primaryDeep", "bg")),
           "reel": (("bg",), ("primary", "primaryDeep", "bg"))}
MUSIC = {"notes": ("calm", "F"), "texts": ("calm", "C"), "versus": ("calm", "F"), "big": ("punchy", "C"), "search": ("calm", "F"),
         "reel": ("calm", "F")}
# Meta's 9:16 safe zone. The kit's templates aim at y 200–1560 (motion/ad-kit/README), so five of them put text into the
# bands: the end card's headline / sub / fine print, the versus labels and footer, the big phrases, the search pill and the
# reel's line zone and stat cards, the chat's header and composer. The kit stays as it is (the launch kit renders from it
# too); the BUILT 9:16 project is moved here before ship.mjs checks it — a template that no longer has the expected line
# fails the cell (no silent drift). (launch/2026-10/render.py's table, plus the reel and the chat.)
SAFE_916 = {
    "endcard.html": [("? { head: 252, headSize: 124, packH: 700, packCy: 1000, unitH: 420, sub: 1452, subSize: 42, fineSize: 27 }",
                      "? { head: 290, headSize: 118, packH: 580, packCy: 930, unitH: 350, sub: 1280, subSize: 42, fineSize: 27 }")],
    "versus.html": [("label: Math.round(226 * k)", "label: Math.round(290 * k)"), ("badge: Math.round(418 * k)", "badge: Math.round(462 * k)"),
                    ("illoTop: Math.round(572 * k)", "illoTop: Math.round(600 * k)"), ("illoH: Math.round(420 * k)", "illoH: Math.round(390 * k)"),
                    ("rows: Math.round(1052 * k)", "rows: Math.round(1010 * k)"), ("rowGap: Math.round(130 * k)", "rowGap: Math.round(112 * k)"),
                    ("footer: Math.round(1462 * k)", "footer: Math.round(1330 * k)")],
    "big.html": [("var TOP = tall ? 210 : 80;", "var TOP = tall ? 290 : 80;")],
    "search.html": [("var PILL_Y1 = tall ? 200 : 60;", "var PILL_Y1 = tall ? 290 : 60;")],
    "texts.html": [("      top: 200px;\n      height: 1440px;", "      top: 272px;\n      height: 1230px;")],
    "reel.html": [("{ lineTop: 214, lineSize: 100, visTop: 640, visBot: 1590, heroMid: 900, heroSize: 128 }",
                   "{ lineTop: 290, lineSize: 96, visTop: 700, visBot: 1500, heroMid: 900, heroSize: 124 }")],
}
# every format: the search field clips its text and fades both edges like a real input (the completion scrolls), so its
# characters may run past the field — by design, not an overflow for `hyperframes check` to fail
BUILD_PATCHES = {
    "search.html": [('el("span", "sr-ch", ch);', 'el("span", "sr-ch", ch);\n          s.setAttribute("data-layout-allow-overflow", "");')],
}
STAT_LINE = re.compile(r"^[^:\n]{2,40}:\s+[+\-−]?[€$£]?\d[\d.,]*\s?(?:%|x|×|k|K|M|\+)?$")
# a background render (local: no queue) — tests replace it; its output goes to video.log next to data.json
SPAWN = lambda args, log: subprocess.Popen(args, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           start_new_session=True)
_CHILDREN = []                                      # render processes in flight (killed on SIGTERM)


class RenderError(Exception):
    """One cell could not be rendered (the reason is kept on the cell and in the log)."""


class Unsupported(RenderError):
    """Nothing of this brand can render (right-to-left text): no cell is touched, the owner gets the card."""


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utcnow()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sty():
    import otto_styles
    return otto_styles


def _safe(bid):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(bid))


def _plain_id(bid):
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", str(bid or "")))


def _plain_month(ym):
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(ym or "")))


def month_of(b, now=None):
    return (now or utcnow()).astimezone(ap.brand_tz(b)).strftime("%Y-%m")


def next_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


# ============================================================================================ environment

def locks_dir():
    folder = Path(os.environ.get("OTTO_LOCKS") or ap.DATA.parent / "locks")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextlib.contextmanager
def flock(name, wait=False, deadline=None):
    """locks/<name>.lock: non-blocking (yields False when held), blocking (wait=True), or polled until `deadline`."""
    with open(locks_dir() / f"{name}.lock", "a+") as lf:
        got = False
        while True:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX | (0 if wait and deadline is None else fcntl.LOCK_NB))
                got = True
                break
            except OSError:
                if not wait or deadline is None or time.time() >= deadline:
                    break
                time.sleep(2)
        try:
            yield got
        finally:
            if got:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def npm_cache():
    v = os.environ.get("npm_config_cache") or os.environ.get("OTTO_NPM_CACHE")
    return Path(v) if v else Path(tempfile.gettempdir()) / "otto-npm-cache"


def kit_env():
    """The environment every kit command runs in: a writable npx cache, HyperFrames pinned, no telemetry / update checks."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1",
               HYPERFRAMES_NO_UPDATE_CHECK="1", HYPERFRAMES_NO_AUTO_INSTALL="1", HF_CLI=f"npx --yes {HF_PKG}",
               OTTO_PROVENANCE=str(HERE / "otto_provenance.py"))
    cache = npm_cache()
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    env["npm_config_cache"] = str(cache)
    return env


def toolchain():
    """Why this machine cannot render the kit (None = it can): node, npx, ffmpeg, ffprobe, python3 and the kit's files."""
    miss = [t for t in ("node", "npx", "ffmpeg", "ffprobe", "python3") if not shutil.which(t)]
    if miss:
        return "not installed: " + ", ".join(miss)
    gone = [f for f in ("build.mjs", "ship.mjs", "lib/schedule.mjs", "audio/score.py", "templates/endcard.html") if not (KIT / f).is_file()]
    if gone:
        return f"the ad kit is incomplete ({KIT}: {', '.join(gone)})"
    if _SCORE_OK.get("ok") is None:                     # the kit's music (audio/score.py) needs numpy + scipy
        try:
            r = subprocess.run(["python3", "-c", "import numpy, scipy"], capture_output=True, timeout=60)
            _SCORE_OK["ok"] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _SCORE_OK["ok"] = False
    if not _SCORE_OK["ok"]:
        return "python3-numpy / python3-scipy missing (the ad kit's music)"
    return None


_SCORE_OK = {}


def tmp_root():
    v = os.environ.get("OTTO_VIDEO_TMP") or os.environ.get("OTTO_RENDER_TMP")
    root = Path(v) if v else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return root


def queue_dir():
    v = (os.environ.get("OTTO_COPY_QUEUE") or "").strip()
    return Path(v) if v else None


def render_timeout():
    try:
        return max(60.0, float(os.environ.get("OTTO_VIDEO_RENDER_TIMEOUT_S") or 900))
    except ValueError:
        return 900.0


def _killpg(p):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(10)
            return
        except subprocess.TimeoutExpired:
            continue


def run(cmd, cwd, env, timeout, merge=True):
    """One kit command in its own process group (Chrome children die with it). → (exit, stdout, stderr). Raises RenderError
    on the time limit."""
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if merge else subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                         errors="replace", start_new_session=True)
    _CHILDREN.append(p)
    try:
        out, err = p.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        _killpg(p)
        raise RenderError(f"{Path(str(cmd[1] if len(cmd) > 1 else cmd[0])).name} {cmd[2] if len(cmd) > 2 else ''}".strip()
                          + f" timed out after {timeout:.0f}s")
    finally:
        if p in _CHILDREN:
            _CHILDREN.remove(p)
    return p.returncode, out or "", err or ""


def _on_term(signum, frame):
    for p in list(_CHILDREN):
        _killpg(p)
    sys.exit(128 + signum)


def _tail(text, n=600):
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(text or "")).strip()
    return text[-n:]


# ============================================================================================ which cells

def kit_of(cell):
    sty = _sty()
    st = sty.resolve(cell.get("style"))
    return (cell.get("video") or {}).get("kit") or ((sty.STYLES.get(st) or {}).get("video") if st else None)


def skip_why(d, b):
    """Why this brand renders no video ads now, or None."""
    bid = b["id"]
    if b.get("paused") or str(b.get("status") or "active").lower() == "paused":
        return "paused"
    if ap.plan_ended(d, bid):
        return "no active plan (the ended plan)"
    why = ap.no_ads_why(d, bid)
    if why:
        return why
    p = ap.plan_of(d, bid)
    if not p["features"].get("video_ads"):
        return f"plan {p['id']} has no video ads"
    return None


def _recent_fail(cell, h, now):
    f = (cell.get("render") or {}).get("failed") if isinstance(cell.get("render"), dict) else None
    if not isinstance(f, dict) or f.get("hash") != h:
        return None
    at = ap.parse_iso(f.get("at"))
    return f if at and at.tzinfo and now - at < RETRY_AFTER else None


def candidates(bid, ym, mx, d, force=False, only=None, now=None):
    """The month's faceless video cells in concept order → {"cap", "rendered", "todo", "over_cap", "waiting", "failed"}.
    rendered = finished videos (ours, or a person's "file"); todo = scripted cells to render now, as many as the plan's
    video_ads_per_month leaves; a cell that failed within RETRY_AFTER (same beats) waits and holds no slot."""
    sty = _sty()
    now = now or utcnow()
    p = ap.plan_of(d, bid)
    cap = p["limits"].get("video_ads_per_month") if p["features"].get("video_ads") else 0
    rep = sty.check_matrix(bid, ym, mx)
    status = {(r["angle"], r["id"]): r for r in rep["cells"]}
    out = {"cap": cap, "rendered": [], "todo": [], "over_cap": [], "spare": [], "waiting": [], "failed": []}
    for a in sty.live_angles(mx):
        for i, c in enumerate(sty.live_cells(a)):
            if sty.fmt(c) != "video":
                continue
            cid = str(c.get("id") or "")
            row = status.get((a.get("id"), c.get("id"))) or {}
            st, kit = row.get("status"), kit_of(c)
            ours = isinstance(c.get("render"), dict) and c["render"].get("hash")
            if st == "ready" and c.get("file"):
                if force and ours and (not only or cid in only):
                    pass                                        # --force: a cached cell of ours renders again
                else:
                    out["rendered"].append(cid)
                    continue
            elif st == "ready":
                out["waiting"].append((cid, "kit JSON written by hand — rendered by whoever wrote it"))
                continue
            elif st != "scripted":
                continue                                        # unwritten / invalid / violation: the copywriter's, not ours
            if kit not in CONTENT_KEY:
                out["waiting"].append((cid, f"kit {kit!r} is not an ad-kit style"))
                continue
            if only and cid not in only:
                continue
            h = sty.video_hash(c)
            f = None if force else _recent_fail(c, h, now)
            if f:
                out["failed"].append((cid, str(f.get("error") or "")[:160]))
                continue
            item = {"id": cid, "angle": a.get("id"), "i": i, "kit": kit, "hash": h, "cell": c}
            if cap is not None and len(out["rendered"]) + len(out["todo"]) >= cap:
                out["over_cap"].append(cid)
                out["spare"].append(item)                       # takes the slot of a cell that fails in this run
                continue
            out["todo"].append(item)
    return out


# ============================================================================================ the brand's look

def _light(h):
    from otto_render import _hsl
    return _hsl(h)[1]


def _rgba(h, a):
    h = h.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {a})"


def kit_colors(tok):
    """otto_render.brand_tokens → the kit's fixed colour vocabulary (motion/ad-kit/README, brand token file)."""
    from otto_render import contrast, mix
    W = "#FFFFFF"
    ink = tok.get("ink") or "#161616"
    primary = tok.get("primary") or "#2B2B2B"
    on_primary = W if contrast(W, primary) >= contrast(ink, primary) else ink
    deep = tok.get("deep") or ink
    if deep == ink or contrast(W, deep) < 4.5:
        deep, t = primary, 0.0
        while contrast(W, deep) < 7 and t < 0.8:
            t += 0.1
            deep = mix(primary, "#000000", t)
    night = ink if contrast(W, ink) >= 7 else "#151515"
    accent = tok.get("accent_on_dark") or tok.get("accent") or primary
    on_accent = W if contrast(W, accent) >= contrast(ink, accent) else ink
    return {"bg": tok.get("surface") or "#F6F3ED", "surface": W, "ink": ink, "muted": tok.get("mut_light") or mix(ink, W, 0.35),
            "line": _rgba(ink, 0.12), "primary": primary, "primaryDeep": deep, "onPrimary": on_primary, "accent": accent,
            "onAccent": on_accent, "night": night, "neutral": tok.get("surface2") or mix(W, ink, 0.07),
            "wash": mix(primary, W, 0.86)}


def text_on(colors, ground):
    return colors["onPrimary"] if ground in DARK else colors["onAccent"] if ground == "accent" else colors["ink"]


def ground_ok(colors, ground):
    from otto_render import contrast
    return ground in colors and contrast(text_on(colors, ground), colors[ground]) >= 4.5


def pick_ground(colors, prefs, dark=None):
    """The first preferred ground whose text keeps 4.5:1 (dark=True / False: only dark / light grounds)."""
    ok = [g for g in prefs if ground_ok(colors, g) and (dark is None or (g in DARK) == dark)]
    if ok:
        return ok[0]
    if dark:
        return next((g for g in DARK if ground_ok(colors, g)), "bg")
    return "bg"


def _font_slug(family):
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def display_font(family, log=print):
    """The brand's display face as one latin woff2 → (path, family). Inter Tight (the statics' default display face) ships
    with the kit; another Google family is fetched once into OTTO_FONT_CACHE. Offline / refused → Inter Tight."""
    fallback = (KIT_FONTS / "InterTight-var-latin.woff2", "Inter Tight")
    if not family or family == "Inter Tight":
        return fallback
    if family == "Inter":
        return KIT_FONTS / "Inter-var-latin.woff2", "Inter"
    import otto_render as orr
    cached = orr.FONT_CACHE / f"adkit-{_font_slug(family)}-latin.woff2"
    if cached.is_file() and cached.stat().st_size > 1000:
        return cached, family
    if os.environ.get("OTTO_RENDER_FONTS") == "system":
        return fallback
    try:
        css = orr._fetch(orr._google_url([family])).decode("utf-8")
        best = None
        for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*{[^}]*})", css):
            if subset != "latin" or re.search(r"font-style:\s*italic", block):
                continue
            ws = [int(x) for x in re.search(r"font-weight:\s*([\d ]+);", block).group(1).split()]
            src = re.search(r"url\((https://[^)]+)\)", block).group(1)
            lo, hi = min(ws), max(ws)
            score = 0 if lo <= 800 <= hi else abs(800 - hi)          # a variable font covering 800, else the heaviest
            if best is None or score < best[0]:
                best = (score, src)
        if not best:
            raise ValueError("no latin face in the Google CSS")
        data = orr._fetch(best[1])
        if data[:4] != b"wOF2":
            raise ValueError("not a woff2 file")
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_name(cached.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cached)
        return cached, family
    except Exception as e:                                             # noqa: BLE001 — the kit's face is a fine fallback
        log(f"  font {family} not fetched ({type(e).__name__}: {str(e)[:80]}) — Inter Tight instead")
        return fallback


def _local_file(ref):
    if not ref:
        return None
    ref = str(ref)
    if ref.startswith("file:"):
        from urllib.parse import unquote, urlparse
        p = Path(unquote(urlparse(ref).path))
        return p if p.is_file() else None
    try:
        p = paths.local_path(ref) if ref.startswith("assets/") else Path(ref).expanduser()
    except Exception:                                                  # noqa: BLE001
        return None
    if not p.is_absolute():
        p = HERE / p
    return p if p.is_file() else None


def is_cutout(path):
    import otto_render as orr
    try:
        return orr.is_cutout(Path(path).resolve().as_uri())
    except Exception:                                                  # noqa: BLE001
        return False


def _image_size(path):
    """(w, h) of a PNG / JPEG, None otherwise."""
    try:
        with open(path, "rb") as f:
            b = f.read(65536)
    except OSError:
        return None
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            m, ln = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
            if 0xC0 <= m <= 0xC3:
                return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + ln
    return None


def light_logo(path):
    """True when a logo is (nearly) all white — it only reads on a dark end card. SVG: every colour it names is light;
    PNG / WebP: the visible pixels' mean luminance (ffmpeg). Unknown → False."""
    p = Path(path)
    try:
        if p.suffix.lower() == ".svg":
            t = p.read_text(errors="ignore")
            cols = re.findall(r"(?:fill|stop-color|color)\s*[:=]\s*[\"']?\s*(#[0-9A-Fa-f]{3,6}\b|white|black|currentColor)", t)
            if not cols:
                return False
            def lum(c):
                if c == "white":
                    return 1.0
                if c in ("black", "currentColor"):
                    return 0.0
                c = c.lstrip("#")
                c = "".join(x * 2 for x in c) if len(c) == 3 else c
                return _light("#" + c)
            return all(lum(c) > 0.85 for c in cols)
        ff = shutil.which("ffmpeg")
        if not ff:
            return False
        r = subprocess.run([ff, "-v", "error", "-i", str(p), "-vf", "scale=24:24,format=rgba", "-frames:v", "1", "-f", "rawvideo", "-"],
                           capture_output=True, timeout=30)
        px = r.stdout
        if r.returncode or len(px) != 24 * 24 * 4:
            return False
        vis = [(px[i], px[i + 1], px[i + 2]) for i in range(0, len(px), 4) if px[i + 3] > 128]
        if len(vis) < 8:
            return False
        mean = sum(0.2126 * r_ + 0.7152 * g + 0.0722 * b for r_, g, b in vis) / len(vis) / 255
        return mean > 0.85
    except Exception:                                                  # noqa: BLE001
        return False


def place(src, dest_dir, role, log=print):
    """A brand picture → <dest_dir>/<role>.<ext> the kit can measure (PNG / JPEG / SVG; WebP converted, anything over
    1600 px scaled down — ffmpeg). → file name, or None."""
    src = Path(src)
    ext = src.suffix.lower()
    if ext == ".svg":
        shutil.copyfile(src, dest_dir / f"{role}.svg")
        return f"{role}.svg"
    size = _image_size(src)
    if ext in (".png", ".jpg", ".jpeg") and size and max(size) <= 1600:
        name = f"{role}{'.png' if ext == '.png' else '.jpg'}"
        shutil.copyfile(src, dest_dir / name)
        return name
    ff = shutil.which("ffmpeg")
    if not ff:
        log(f"  {role}: {src.name} needs ffmpeg to convert — left out")
        return None
    alpha = ext in (".png", ".webp")
    name = f"{role}{'.png' if alpha else '.jpg'}"
    r = subprocess.run([ff, "-y", "-v", "error", "-i", str(src), "-vf", "scale='min(1600,iw)':'min(1600,ih)':force_original_aspect_ratio=decrease",
                        "-frames:v", "1"] + ([] if alpha else ["-q:v", "3"]) + [str(dest_dir / name)], capture_output=True, timeout=60)
    if r.returncode or not (dest_dir / name).is_file():
        log(f"  {role}: {src.name} could not be converted — left out")
        return None
    return name


def brand_kit(bid, work, d=None, log=print):
    """The brand's look for the kit, written into <work>/brand/ (brand.json + assets/). → {"path", "brand", "colors",
    "roles", "sources" (role → the original file, for provenance), "font", "lang", "grounds", "end_logo"}.
    Raises Unsupported for a right-to-left brand."""
    import otto_render as orr
    sty = _sty()
    tok = orr.brand_tokens(bid)
    lang = str(tok.get("lang") or "en")[:2]
    if lang in RTL_LANGS or tok.get("dir") == "rtl":
        raise Unsupported(f"the brand writes {lang.upper()} (right to left) and the video kit has no right-to-left layout yet")
    root = Path(work) / "brand"
    (root / "assets").mkdir(parents=True, exist_ok=True)
    colors = kit_colors(tok)
    font, family = display_font(tok.get("font_display"), log)
    shutil.copyfile(font, root / "assets" / "brand.woff2")
    assets, sources = {}, {}

    def put(role, src):
        f = _local_file(src)
        if f and role not in assets:
            name = place(f, root / "assets", role, log)
            if name:
                assets[role], sources[role] = name, str(f)

    try:
        ba = sty.brand_assets(bid, d=d)
    except Exception as e:                                             # noqa: BLE001 — no pictures: text-only ads still render
        log(f"  brand assets unreadable ({type(e).__name__}: {e}) — rendering without pictures")
        ba = {"product": [], "photos": [], "people": []}
    product = list(dict.fromkeys(ba.get("product") or []))
    photos = [x for x in dict.fromkeys(ba.get("photos") or [])]
    cut = next((r for r in product + photos if str(r).lower().endswith((".png", ".webp")) and _local_file(r)
                and is_cutout(_local_file(r))), None)
    if cut:
        put("pack", cut)
    posts = {p.get("image") for p in (d or {}).get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid}
    # a real site / product photo first; a post image (possibly generated) only when there is nothing else
    photo = next((r for r in product + photos if r != cut and r not in posts and _local_file(r)), None) or \
        next((r for r in photos if r != cut and _local_file(r)), None)
    if photo:
        put("photo", photo)
    logo = tok.get("logo") or ""
    white = next((p for ext in ("svg", "png", "webp") for p in [ap.BRANDS / bid / f"logo-white.{ext}"] if p.is_file()), None)
    if logo and Path(logo).is_file() and Path(logo) != white:
        if light_logo(logo):
            put("logo_white", logo)
        else:
            put("logo", logo)
    if white:
        put("logo_white", white)
    # grounds per kit (the logo has to read on its end card: a dark-only logo keeps end cards light and vice versa)
    grounds = {}
    for kit, (scene, end) in GROUNDS.items():
        if "logo" in assets and "logo_white" not in assets:
            eg = pick_ground(colors, end, dark=False)
        elif "logo_white" in assets and "logo" not in assets:
            eg = pick_ground(colors, end, dark=True)
        else:
            eg = pick_ground(colors, end)
        grounds[kit] = (pick_ground(colors, scene), eg)
    end_logo = lambda g: ("logo_white" if "logo_white" in assets else None) if g in DARK else ("logo" if "logo" in assets else None)
    brand = {"name": tok.get("name") or bid, "slug": bid, "site": tok.get("host") or "", "assetRoot": "assets",
             "fonts": {"brand": {"file": "brand.woff2", "weight": "100 900", "tracking": "-0.03em"}, "ui": None},
             "colors": colors, "assets": assets, "legal": {}}
    (root / "brand.json").write_text(json.dumps(brand, ensure_ascii=False, indent=1) + "\n")
    return {"path": root / "brand.json", "brand": brand, "colors": colors, "roles": set(assets), "sources": sources,
            "font": family, "lang": lang, "grounds": grounds, "end_logo": end_logo}


# ============================================================================================ one cell → kit JSON

def _line_dur(text):
    return round(max(2.0, min(4.0, 1.2 + 0.3 * len(str(text).split()))), 2)


def reel_cues(lines, roles):
    """Silent reel: one cue per on-screen line, timed by its length (build.mjs reads "dur" when a cue has no voice clip);
    a "Label: 20%" line counts up as a stat card; the brand's pictures alternate as shots; the end card closes it."""
    shots = []
    if "pack" in roles:
        shots += [{"asset": "pack", "kind": "cutout", "move": "turn"}, {"asset": "pack", "kind": "cutout", "move": "rise"}]
    if "photo" in roles:
        shots.insert(1 if shots else 0, {"asset": "photo", "kind": "photo"})
    cues, k = [], 0
    for i, line in enumerate(lines):
        c = {"line": i, "dur": _line_dur(line)}
        if STAT_LINE.match(str(line).strip()):
            c["stat"] = True
        elif shots and i % 2 == 0:
            c["shot"] = dict(shots[k % len(shots)])
            k += 1
        cues.append(c)
    cues.append({"endcard": True, "dur": 1.7})
    return cues


def kit_ad(cell, kit, bk):
    """The cell's copy (verbatim) + the brand's presentation → the ad-kit JSON build.mjs reads (from_matrix.py's shape)."""
    src = cell.get("data") if isinstance(cell.get("data"), dict) else {}
    roles = bk["roles"]
    scene, end = bk["grounds"][kit]
    mood, key = MUSIC[kit]
    out = {"id": str(cell.get("id")), "style": kit, "formats": ["9x16"] + (["4x5"] if kit in TUNED_45 else []),
           "music": {"bpm": 120, "mood": mood, "key": key}, "scene": {"ground": scene}}
    if kit == "reel":
        lines = [str(x).strip() for x in src.get("lines") or [] if str(x).strip()] or \
                [str(x).strip() for x in src.get("vo") or [] if str(x).strip()]
        if not lines:
            raise RenderError("the reel has no lines")
        out["reel"] = {"vo": [str(x) for x in src.get("vo") or []], "lines": lines, "cues": reel_cues(lines, roles)}
    else:
        content = copy.deepcopy(src.get(CONTENT_KEY[kit]))
        if not isinstance(content, dict) or not content:
            raise RenderError(f"no {CONTENT_KEY[kit]} beats in the cell")
        visual = "pack" if "pack" in roles else "photo" if "photo" in roles else None
        if kit == "big":
            hero = "pack" if "pack" in roles else "logo" if "logo" in roles else "logo_white" if "logo_white" in roles else \
                "photo" if "photo" in roles else None
            if not hero:
                raise RenderError("the big style needs a picture (a product cut-out, a logo or a photo) — add a transparent "
                                  f"product PNG to brands/{bk['brand']['slug']}/assets/")
            content["hero"] = hero
            for ph in content.get("phrases") or []:
                if isinstance(ph, dict) and ph.get("product") not in roles:
                    ph.pop("product", None)
        elif kit == "versus":
            for side in ("left", "right"):
                s = content.get(side)
                if isinstance(s, dict):
                    if s.get("image") not in roles:
                        s.pop("image", None)
                    if s.get("illo") not in ("tub", "plate"):
                        s.pop("illo", None)
            if visual and isinstance(content.get("right"), dict) and not content["right"].get("image"):
                content["right"]["image"] = visual
        elif kit == "search":
            r = content.get("result")
            if isinstance(r, dict):
                if r.get("image") not in roles:
                    r.pop("image", None)
                if visual:
                    r["image"] = visual
                if not r.get("site"):
                    r["site"] = bk["brand"]["name"]
        elif kit == "texts":
            for m in content.get("messages") or []:
                if isinstance(m, dict) and m.get("photo") and m["photo"] not in roles:
                    m.pop("photo", None)
        out[CONTENT_KEY[kit]] = content
    ec = src.get("endcard") if isinstance(src.get("endcard"), dict) else {}
    ec = {k: str(ec[k]) for k in ENDCARD_COPY if isinstance(ec.get(k), str) and ec[k].strip()}
    if not ec.get("headline"):
        raise RenderError("no end card headline in the cell")
    ec["ground"] = end
    ec["products"] = ["pack"] if "pack" in roles else []
    lg = bk["end_logo"](end)
    if lg:
        ec["logo"] = lg
    out["endcard"] = ec
    return out


def lengthen(ad, deficit):
    """A video under MIN_S: the end card holds longer (the reel: its tail)."""
    ad = copy.deepcopy(ad)
    extra = round(deficit + 0.15, 2)
    if ad.get("style") == "reel":
        t = ad.setdefault("timing", {})
        t["tail"] = round(float(t.get("tail", 1.5)) + extra, 2)
    else:
        ad["endcard"]["duration"] = round(float(ad["endcard"].get("duration") or 3.2) + extra, 2)
    return ad


# ============================================================================================ the real renderer

def safe_zone_patch(proj, table=None):
    """Move a built 9:16 project into Meta's safe zone (SAFE_916; or apply another table). → [] or the problems (a template
    changed)."""
    bad = []
    for name, subs in (SAFE_916 if table is None else table).items():
        f = Path(proj) / "compositions" / name
        if not f.exists():
            continue
        t = f.read_text()
        for old, new in subs:
            if old not in t:
                bad.append(f"{name}: expected layout line not found ({old[:40]}…) — the kit's template changed, update SAFE_916")
            t = t.replace(old, new)
        f.write_text(t)
    return bad


def seek_fractions(sched):
    """The ad's settled moments as fractions of its length: the hook, the idea mid-way, the full scene, the end card."""
    dur = float(sched["duration"])
    hook, end, poster = float(sched.get("hookAt") or 1.0), float(sched.get("endAt") or dur - 3.2), float(sched.get("posterAt") or dur / 2)
    ts = [hook + 0.15, (hook + end) / 2, poster, end + 1.3, dur - 0.3]     # settled frames, not the camera moves between
    return ",".join(f"{max(0.02, min(0.98, t / dur)):.3f}" for t in ts)


def zone_check(proj, sched, env, deadline):
    """`hyperframes check --caption-zone` for the top 14 % and the bottom 20 % of a 9:16 project. → ["top: “text” at 3.1s", …]."""
    hits = []
    seeks = seek_fractions(sched)
    for band, (y0, y1) in (("top", (0.0, SAFE_TOP)), ("bottom", (1.0 - SAFE_BOTTOM, 1.0))):
        zone = f"x0=0;y0={y0:.2f};x1=1;y1={y1:.2f};severity=error;seek={seeks}"
        code, out, err = run(["npx", "--yes", HF_PKG, "check", str(proj), "--json", "--no-contrast", f"--caption-zone={zone}"],
                             proj, env, min(CHECK_TIMEOUT_S, max(30.0, deadline - time.time())), merge=False)
        try:
            rep = json.loads(out[out.index("{"):]) if "{" in out else {}
        except ValueError:
            rep = {}
        if not rep:
            raise RenderError(f"safe-zone check did not run (exit {code}): {_tail(err or out, 300)}")
        for f in (rep.get("layout") or {}).get("findings") or []:
            if f.get("code") == "caption_zone_collision":
                hits.append(f"{band}: “{str(f.get('text') or '')[:30]}” at {f.get('time')}s")
    return list(dict.fromkeys(hits))


def probe(mp4):
    """ffprobe → {"duration", "width", "height", "video", "audio"}."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
                        "-of", "json", str(mp4)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RenderError(f"ffprobe could not read {Path(mp4).name}: {_tail(r.stderr, 200)}")
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams") or [] if s.get("codec_type") == "video"), {})
    a = next((s for s in j.get("streams") or [] if s.get("codec_type") == "audio"), {})
    return {"duration": float((j.get("format") or {}).get("duration") or 0), "width": v.get("width"), "height": v.get("height"),
            "video": v.get("codec_name"), "audio": a.get("codec_name")}


def check_errors(proj, env, deadline):
    """After a failed ship: what `hyperframes check` objects to, in words (" — text_box_overflow “Roast date on the bag”")."""
    try:
        code, out, _ = run(["npx", "--yes", HF_PKG, "check", str(proj), "--json"], proj, env,
                           min(CHECK_TIMEOUT_S, max(30.0, deadline - time.time())), merge=False)
        rep = json.loads(out[out.index("{"):]) if "{" in out else {}
    except (RenderError, ValueError):
        return ""
    errs = []
    for sec in ("lint", "runtime", "layout", "motion", "contrast"):
        s = rep.get(sec) if isinstance(rep.get(sec), dict) else {}
        for f in s.get("findings") or s.get("issues") or []:
            if isinstance(f, dict) and f.get("severity") == "error":
                errs.append(f"{f.get('code')} “{str(f.get('text') or '')[:40]}”" + (f" at {f.get('time')}s" if f.get("time") is not None else ""))
    return (" — " + "; ".join(list(dict.fromkeys(errs))[:3])) if errs else ""


def ship_error(out):
    """ship.mjs's failure in a line or two: the check's summary and its first errors, or the thrown message — no stack."""
    lines = [l.strip() for l in re.sub(r"\x1b\[[0-9;]*m", "", out or "").splitlines() if l.strip()]
    lines = [l for l in lines if not re.match(r"^(at |node:|\^|file:///)", l) and not l.startswith("[")
             and not re.search(r"\bthrow\b|\bif \(|=>|;\s*$", l)]
    keep = [l for l in lines if re.search(r"error\(s\)|✗|failed|Error:", l, re.I)]
    return " · ".join(dict.fromkeys(keep or lines[-3:]))[-500:]


def render_project(job):
    """The HyperFrames call for one cell and format (tests replace RENDERER). job = {"ad", "brand", "fmt", "proj", "name",
    "env", "deadline"} → {"mp4", "poster", "sheet", "duration", "log"}. Raises RenderError."""
    ad_path, proj, fmt, env = Path(job["ad"]), Path(job["proj"]), job["fmt"], job["env"]
    left = lambda cap: min(cap, max(10.0, job["deadline"] - time.time()))
    log = []
    for attempt in range(3):
        if proj.exists():
            shutil.rmtree(proj)
        code, out, _ = run(["node", KIT / "build.mjs", "--brand", job["brand"], "--ad", ad_path, "--out", proj, "--format", fmt],
                           KIT, env, left(BUILD_TIMEOUT_S))
        log.append(_tail(out, 400))
        if code:
            raise RenderError(f"build failed: {_tail(out, 300)}")
        sched = json.loads((proj / "schedule.json").read_text())
        dur = float(sched["duration"])
        if dur > MAX_S:
            raise RenderError(f"the video runs {dur:.1f}s (Meta's limit here is {MAX_S:.0f}s): the beats are too long for one ad")
        if dur >= MIN_S:
            break
        ad_path.write_text(json.dumps(lengthen(json.loads(ad_path.read_text()), MIN_S - dur), ensure_ascii=False))
    else:
        raise RenderError(f"the video stays under {MIN_S:.0f}s")
    bad = safe_zone_patch(proj, BUILD_PATCHES)
    if bad:
        raise RenderError("; ".join(bad))
    if fmt == "9x16":
        bad = safe_zone_patch(proj)
        if bad:
            raise RenderError("; ".join(bad))
        hits = zone_check(proj, sched, env, job["deadline"])
        if hits:
            raise RenderError("text in Meta's 9:16 safe zone (top 14 % / bottom 20 %): " + "; ".join(hits[:4]))
    code, out, _ = run(["node", KIT / "ship.mjs", proj, "--name", job["name"]], KIT, env, left(render_timeout()))
    log.append(_tail(out, 600))
    if code:
        raise RenderError(f"render failed: {ship_error(out)}" + check_errors(proj, env, job["deadline"]))
    mp4, poster = proj / "renders" / f"{job['name']}.mp4", proj / "renders" / f"{job['name']}.jpg"
    if not mp4.is_file() or not poster.is_file():
        raise RenderError("the render left no mp4 / poster")
    info = probe(mp4)
    if (info["width"], info["height"]) != DIMS[fmt]:
        raise RenderError(f"rendered {info['width']}×{info['height']}, expected {DIMS[fmt][0]}×{DIMS[fmt][1]}")
    if info["video"] != "h264" or info["audio"] != "aac":
        raise RenderError(f"codecs {info['video']}/{info['audio']} (Meta wants h264 + aac)")
    sheet = proj / "renders" / f"{job['name']}-sheet.jpg"
    return {"mp4": mp4, "poster": poster, "sheet": sheet if sheet.is_file() else None, "duration": info["duration"] or dur,
            "log": "\n".join(log)}


RENDERER = render_project


def shrink(mp4, limit=MAX_BYTES):
    """Re-encode an mp4 over `limit` at rising CRF until it fits (1080 wide kept, faststart). → True when it fits."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    for crf in (20, 23, 26, 29):
        tmp = Path(str(mp4) + f".crf{crf}.mp4")
        r = subprocess.run([ff, "-y", "-v", "error", "-i", str(mp4), "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(tmp)], capture_output=True, timeout=600)
        if r.returncode == 0 and tmp.is_file() and tmp.stat().st_size <= limit:
            os.replace(tmp, mp4)
            return True
        tmp.unlink(missing_ok=True)
    return False


# ============================================================================================ one cell, start to finish

def _ai_sources(bk, ad):
    """The placed pictures this ad shows that carry an AI mark → (kinds, tool) or None."""
    used = set(ad.get("endcard", {}).get("products") or []) | {ad.get("endcard", {}).get("logo")}
    blob = json.dumps(ad)
    used |= {r for r in bk["sources"] if f'"{r}"' in blob}
    tools = []
    for role in sorted(r for r in used if r in bk["sources"]):
        try:
            info = prov.inspect(bk["sources"][role])
        except Exception:                                              # noqa: BLE001
            continue
        if info.get("generated"):
            tools.append(info.get("tool") or info.get("ai_system") or "")
    if not tools:
        return None
    return ["image"], " + ".join(t for t in dict.fromkeys(tools) if t)


def matrix_token(bid, ym):
    """The month matrix's media token (created and saved on first use) — every video file of the month is named from it."""
    sty = _sty()
    with flock(f"adfiles-{_safe(bid)}", wait=True):
        mx = sty.load_matrix(bid, ym)
        if mx is None:
            raise RenderError("the matrix disappeared")
        if paths.valid_token(mx.get("media_token")):
            return mx["media_token"]
        tok = paths.record_token(mx)
        ap._atomic_write(sty.matrix_path(bid, ym), json.dumps(mx, ensure_ascii=False, indent=1) + "\n")
        return tok


def render_cell(bid, ym, item, bk, work, env, deadline, token, out=print):
    """One scripted cell → its finished, public files. → {"files": {fmt: {...}}, "media_ai": {...}}. Raises RenderError."""
    sty = _sty()
    cell, kit, cid = item["cell"], item["kit"], item["id"]
    safe = re.sub(r"[^A-Za-z0-9_-]", "", cid)
    ad = kit_ad(cell, kit, bk)
    ai = _ai_sources(bk, ad)
    texts = sty.data_texts({k: v for k, v in ad.items() if k not in ("id", "style", "formats", "music", "scene")})
    if not texts:
        raise RenderError("no text in the beats")
    d = Path(work) / safe
    d.mkdir(parents=True, exist_ok=True)
    done, made = {}, []
    try:
        for fmt in ad["formats"]:
            ad_path = d / f"ad-{fmt}.json"
            ad_path.write_text(json.dumps(ad, ensure_ascii=False, indent=1))
            res = RENDERER({"ad": ad_path, "brand": bk["path"], "fmt": fmt, "proj": d / fmt, "name": f"{safe}-{fmt}", "env": env,
                            "deadline": deadline, "kit": kit})
            mp4, poster = Path(res["mp4"]), Path(res["poster"])
            dur = float(res.get("duration") or 0)
            if not MIN_S - 0.05 <= dur <= MAX_S + 0.05:
                raise RenderError(f"{fmt}: {dur:.1f}s is outside {MIN_S:.0f}–{MAX_S:.0f}s")
            if mp4.stat().st_size > MAX_BYTES and not shrink(mp4):
                raise RenderError(f"{fmt}: {mp4.stat().st_size / 1048576:.1f} MB and it does not shrink under 10 MB")
            stem = f"{bid}-{ym}-{safe}-{item['hash'][:8]}-{fmt}"
            dst = paths.ASSETS / "ads" / paths.token_name(stem, ".mp4", token)
            pdst = paths.ASSETS / "ads" / paths.token_name(f"{stem}-poster", ".jpg", token)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mp4, dst)
            shutil.copyfile(poster, pdst)
            made += [dst, pdst]
            rec = {}
            if ai:
                rec[paths.rel_of(dst)] = prov.record(prov.mark_safely(dst, ai[0], ai[1], composite=True, log=out))
                rec[paths.rel_of(pdst)] = prov.record(prov.mark_safely(pdst, ai[0], ai[1], composite=True, log=out))
            for f in (dst, pdst):                                     # public before anything points at it
                paths.publish(f)
            if prov.sidecar_path(dst).exists():
                made.append(prov.sidecar_path(dst))
                paths.publish(prov.sidecar_path(dst))
            done[fmt] = {"file": paths.rel_of(dst), "poster": paths.rel_of(pdst), "duration": round(dur, 2),
                         "bytes": dst.stat().st_size, "media_ai": rec}
    except BaseException:
        for f in made:
            _remove(paths.rel_of(f))
        raise
    return {"files": done, "made": [paths.rel_of(f) for f in made]}


def _remove(ref):
    """A file of ours (local + public copy)."""
    try:
        lp = paths.local_path(ref)
    except Exception:                                                  # noqa: BLE001
        return
    for p in [lp] + ([paths.public_dir() / ref[len("assets/"):]] if paths.public_dir() else []):
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


def _find_cell(mx, cid):
    for a in (mx or {}).get("angles") or []:
        for c in (a.get("ads") or []) if isinstance(a, dict) else []:
            if isinstance(c, dict) and str(c.get("id")) == cid:
                return c
    return None


def _update_cell(bid, ym, cid, fn):
    """fn(matrix, cell) under the brand's file lock on a fresh read; a False result writes nothing. → fn's result."""
    sty = _sty()
    with flock(f"adfiles-{_safe(bid)}", wait=True):
        try:
            mx = sty.load_matrix(bid, ym)
        except ValueError:
            return None
        c = _find_cell(mx, cid)
        if c is None:
            return None
        r = fn(mx, c)
        if r is not False:
            ap._atomic_write(sty.matrix_path(bid, ym), json.dumps(mx, ensure_ascii=False, indent=1) + "\n")
        return r


def save_rendered(bid, ym, item, res, kit):
    """The finished files onto the cell (only when its beats are still the ones rendered). → "saved" | "changed" | "gone"."""
    sty = _sty()
    old, state = [], ["gone"]

    def fn(mx, c):
        if sty.video_hash(c) != item["hash"]:
            state[0] = "changed"
            return False
        prev = c.get("render") if isinstance(c.get("render"), dict) else {}
        old.extend(f[k] for f in (prev.get("files") or {}).values() if isinstance(f, dict) for k in ("file", "poster") if f.get(k))
        files = res["files"]
        story = files["9x16"]
        c["file"], c["poster"], c["status"] = story["file"], story["poster"], "rendered"
        media_ai = {}
        for f in files.values():
            media_ai.update(f.pop("media_ai", None) or {})
        c["render"] = {"by": "otto_advideo", "at": iso(), "hash": item["hash"], "kit": kit, "hf": HF_PKG, "files": files}
        if media_ai:
            c["render"]["media_ai"] = media_ai
        state[0] = "saved"
        return True

    _update_cell(bid, ym, item["id"], fn)
    r = state[0]
    if r != "saved":
        for f in res.get("made") or []:
            _remove(f)
        return r
    new = {f for x in res["files"].values() for f in (x["file"], x["poster"])}
    _drop_old([f for f in old if f not in new])
    return r


def _drop_old(refs):
    """Earlier renders of a cell whose beats changed: deleted unless a campaign in data.json still points at them."""
    if not refs:
        return
    try:
        blob = json.dumps(ap.load().get("campaigns") or [])
    except Exception:                                                  # noqa: BLE001 — unsure: keep them
        return
    for ref in refs:
        if ref not in blob:
            _remove(ref)
            _remove(ref + ".provenance.json")


def save_failed(bid, ym, item, err):
    """The reason onto the cell (render.failed); the cell stays scripted. → attempts so far."""
    sty = _sty()

    def fn(mx, c):
        r = c.get("render") if isinstance(c.get("render"), dict) else {}
        prev = r.get("failed") if isinstance(r.get("failed"), dict) else {}
        h = sty.video_hash(c)
        n = (int(prev.get("attempts") or 0) + 1) if prev.get("hash") == h else 1
        r["failed"] = {"hash": h, "at": iso(), "error": str(err)[:400], "attempts": n}
        r.setdefault("by", "otto_advideo")
        c["render"] = r
        if c.get("status") == "rendered" and sty.video_stale(c):
            c.pop("status", None)                                      # its old video is stale: not "rendered" any more
        return n

    return _update_cell(bid, ym, item["id"], fn) or 0


def clear_failed(bid, ym, cid):
    def fn(mx, c):
        r = c.get("render") if isinstance(c.get("render"), dict) else {}
        if "failed" not in r:
            return False
        r.pop("failed")
        return True
    _update_cell(bid, ym, cid, fn)


# ============================================================================================ a brand's month

def render_month(bid, ym=None, dry=False, force=False, only=None, out=print, deadline=None, yield_to=None, now=None, job="render"):
    """Render every scripted faceless video cell of the brand's month under the plan's cap. → {"brand", "month", "skipped",
    "rendered", "failed", "cached", "over_cap", "waiting", "stop", "error"}. stop: None (all done) | "budget" (out of time:
    the rest waits) | "yield" (a higher-priority queue job arrived) | "busy" (another run renders this brand)."""
    sty = _sty()
    now = now or utcnow()
    res = {"brand": bid, "month": ym, "skipped": None, "rendered": [], "failed": [], "cached": [], "over_cap": [], "waiting": [],
           "stop": None, "error": None, "todo": []}
    d = ap.load()
    b = ap.brand(d, bid)
    if b is None:
        res["skipped"] = "unknown brand"
        out(f"{bid}: unknown brand")
        return res
    why = skip_why(d, b)
    if why:
        res["skipped"] = why
        out(f"{bid}: video ads skipped — {why}")
        return res
    ym = ym or month_of(b, now)
    res["month"] = ym
    if not _plain_month(ym):
        res["skipped"] = f"month must be YYYY-MM, got {ym}"
        out(f"{bid}: {res['skipped']}")
        return res
    try:
        mx = sty.load_matrix(bid, ym)
    except ValueError as e:
        res["skipped"] = str(e)
        out(f"{bid}: {e} — no video rendered")
        return res
    if mx is None:
        res["skipped"] = "no matrix"
        out(f"{bid} {ym}: no ad matrix — nothing to render")
        return res
    plan = candidates(bid, ym, mx, d, force, only, now)
    res.update(cached=plan["rendered"], over_cap=plan["over_cap"], waiting=plan["waiting"],
               todo=[x["id"] for x in plan["todo"]])
    head = (f"{bid} {ym}: {len(plan['rendered'])} rendered, {len(plan['todo'])} to render"
            + (f", {len(plan['over_cap'])} over the plan's {plan['cap']:g} a month" if plan["over_cap"] else "")
            + (f", {len(plan['failed'])} failed recently (retried after {RETRY_AFTER.seconds // 3600} h)" if plan["failed"] else ""))
    if dry:
        out(head + " (dry)")
        for x in plan["todo"]:
            fm = ["9x16"] + (["4x5"] if x["kit"] in TUNED_45 else [])
            out(f"  WOULD RENDER {x['id']:28} {x['kit']:7} {' + '.join(fm)} · beats {x['hash'][:8]}")
        for cid, why in plan["waiting"] + plan["failed"]:
            out(f"  waiting      {cid:28} {why}")
        for cid in plan["over_cap"]:
            out(f"  over the cap {cid}")
        res["skipped"] = "dry"
        return res
    if not plan["todo"]:
        out(head)
        if not plan["failed"]:
            _resolve_card(bid, ym, b)
        return res
    tc = toolchain()
    if tc:
        res["skipped"] = res["error"] = f"cannot render here — {tc}"
        out(f"{bid} {ym}: {len(plan['todo'])} video(s) to render but {res['error']}")
        return res
    deadline = deadline or (time.time() + DAILY_BUDGET_S)
    out(head)
    with flock(f"advideo-{_safe(bid)}") as got:
        if not got:
            res["stop"] = "busy"
            out(f"{bid}: another video run is rendering this brand — left to it")
            return res
        work = Path(tempfile.mkdtemp(prefix=f"otto-advideo-{_safe(bid)}-", dir=str(tmp_root())))
        env = kit_env()
        try:
            try:
                bk = brand_kit(bid, work, d, out)
            except Unsupported as e:
                res["error"] = str(e)
                out(f"{bid}: {e} — {len(plan['todo'])} video(s) stay scripted")
                _card(bid, b, ym, [], str(e))
                return res
            out(f"  look: {bk['font']} · primary {bk['colors']['primary']} · pictures: {', '.join(sorted(bk['roles'])) or 'none'}")
            token = matrix_token(bid, ym)
            queue, spare = list(plan["todo"]), list(plan["spare"])
            while queue:
                item = queue.pop(0)
                if time.time() >= deadline:
                    res["stop"] = "budget"
                    break
                if yield_to and yield_to():
                    res["stop"] = "yield"
                    break
                with flock("video-render", wait=True, deadline=deadline) as lock:
                    if not lock:
                        res["stop"] = "budget"
                        out(f"  the server's render slot stayed busy until this run's budget ran out — {item['id']} and the rest wait")
                        break
                    t0 = time.time()
                    try:
                        r = render_cell(bid, ym, item, bk, work, env, deadline, token, out)
                        st = save_rendered(bid, ym, item, r, item["kit"])
                        if st == "saved":
                            res["rendered"].append(item["id"])
                            fl = r["files"]
                            out(f"  rendered {item['id']} ({item['kit']}) in {time.time() - t0:.0f}s: "
                                + " · ".join(f"{k} {v['duration']:.1f}s {v['bytes'] / 1048576:.1f} MB" for k, v in fl.items()))
                        else:
                            out(f"  {item['id']}: {'its beats changed while it rendered — the next run renders the new ones' if st == 'changed' else 'the cell is gone'}")
                    except Exception as e:                       # noqa: BLE001 — one cell never stops the others
                        why = str(e) if isinstance(e, RenderError) else f"{type(e).__name__}: {e}"
                        n = save_failed(bid, ym, item, why)
                        res["failed"].append((item["id"], why[:300], n))
                        out(f"  FAILED {item['id']} ({item['kit']}, attempt {n}): {why[:400]}")
                        if spare:                                # the plan's promise: the next scripted cell takes the slot
                            nxt = spare.pop(0)
                            queue.append(nxt)
                            res["over_cap"] = [x for x in res["over_cap"] if x != nxt["id"]]
        finally:
            if os.environ.get("OTTO_VIDEO_KEEP") == "1":
                out(f"  work dir kept (OTTO_VIDEO_KEEP=1): {work}")
            else:
                shutil.rmtree(work, ignore_errors=True)
    # the owner card: a cell that failed in CARD_AFTER runs (its own attempts), resolved once nothing is failing
    try:
        mx2 = sty.load_matrix(bid, ym) or {}
    except ValueError:
        mx2 = {}
    failing = []
    for a in sty.live_angles(mx2):
        for c in sty.live_cells(a):
            f = (c.get("render") or {}).get("failed") if isinstance(c.get("render"), dict) else None
            if isinstance(f, dict) and f.get("hash") == sty.video_hash(c):
                failing.append((str(c.get("id")), str(f.get("error") or ""), int(f.get("attempts") or 0)))
    if any(n >= CARD_AFTER for _, _, n in failing):
        _card(bid, b, ym, [(cid, why) for cid, why, n in failing])
    elif not failing:
        _resolve_card(bid, ym, b)
    out(f"{bid} {ym}: {len(res['rendered'])} rendered, {len(res['failed'])} failed"
        + (f" · stopped: {res['stop']} ({len(plan['todo']) - len(res['rendered']) - len(res['failed'])} left for the next run)" if res["stop"] else ""))
    return res


def _card(bid, b, ym, items, reason=None):
    """One owner card per brand while it is open (updated, never stacked)."""
    name = (b or {}).get("name") or bid
    title = CARD_TITLE.format(name=name)
    what = reason or "; ".join(f"{cid}: {str(why)[:200]}" for cid, why in items[:6])
    why = (f"Otto could not render {f'{len(items)} of the' if items else 'the'} faceless video ads of {ym} for {name} "
           f"({what}). Their statics and every other ad still launch; the videos stay scripted in brands/{bid}/ads-{ym}.json and "
           f"Otto retries every night (otto_cron ad-videos). `otto_advideo.py render --brand {bid} --month {ym}` renders them now; "
           "the full log is in video.log / the ad-videos job log.")
    try:
        with ap.transaction() as d:
            r = next((x for x in d.get("recommendations") or [] if isinstance(x, dict) and x.get("status") == "proposed"
                      and x.get("title") == title and x.get("brand") == bid), None)
            if r is None:
                ap.add_rec(d, "P2", title, why[:1800], "The month runs fewer video ads than the plan promises", "Check",
                           brand=bid, source="otto_advideo", audience="owner")
            else:
                r["why"] = why[:1800]
                r["updated_at"] = ap.now_iso()
    except Exception:                                                  # noqa: BLE001 — the log still says it
        pass


def _resolve_card(bid, ym, b):
    title = CARD_TITLE.format(name=(b or {}).get("name") or bid)
    try:
        d0 = ap.load()
        if not any(isinstance(x, dict) and x.get("status") == "proposed" and x.get("title") == title and x.get("brand") == bid
                   for x in d0.get("recommendations") or []):
            return
        with ap.transaction() as d:
            for x in d.get("recommendations") or []:
                if isinstance(x, dict) and x.get("status") == "proposed" and x.get("title") == title and x.get("brand") == bid:
                    x.update(status="done", done_at=ap.now_iso(), done_by="otto_advideo")
    except Exception:                                                  # noqa: BLE001
        pass


# ============================================================================================ triggers

def spawn(bid, ym, out=None):
    """After otto_copy.write_ads wrote a month: render its scripted videos without waiting for the nightly job. On the
    server (OTTO_COPY_QUEUE) the month is queued as <id>.<ym>.videos for otto-copy-queue.service (the jobs' sandbox, where
    Chrome runs); locally `otto_advideo.py render` starts in the background (video.log). → True when queued / started;
    False when there is nothing to render, the plan has no video ads, the ids are not plain, or (locally) no toolchain."""
    if not _plain_id(bid) or not _plain_month(ym):
        return False
    try:
        d = ap.load()
        b = ap.brand(d, bid)
        if not b or skip_why(d, b):
            return False
        mx = _sty().load_matrix(bid, ym)
        if mx is None or not candidates(bid, ym, mx, d)["todo"]:
            return False
    except Exception:                                                  # noqa: BLE001 — the nightly job will say what is wrong
        return False
    q = queue_dir()
    if q:
        q.mkdir(parents=True, exist_ok=True)
        tmp = q / f".{bid}.{ym}.videos.tmp"
        tmp.write_text(json.dumps({"brand": bid, "month": ym, "kind": "videos", "at": iso()}))
        os.replace(tmp, q / f"{bid}.{ym}.videos")
        return True
    why = toolchain()
    if why:
        if out:
            out(f"{bid} {ym}: video ads not started here — {why} (the nightly ad-videos job renders them where it can)")
        return False
    log = ap.DATA.parent / "video.log"
    with open(log, "a") as lf:
        lf.write(f"== {iso()} render --brand {bid} --month {ym} (ad copy written)\n")
        lf.flush()
        SPAWN([sys.executable, str(HERE / "otto_advideo.py"), "render", "--brand", bid, "--month", ym], lf)
    return True


def run_queued(job, out=print, yield_to=None, deadline=None):
    """One queued <id>.<ym>.videos job (otto_copy.run_queue). → "done" | "yield" | "budget" (the queue keeps it)."""
    bid = str(job.get("brand") or "")
    ym = job.get("month") or None
    if not _plain_id(bid) or (ym and not _plain_month(ym)):
        out(f"queued video job ignored: {job!r}")
        return "done"
    r = render_month(bid, ym, out=out, yield_to=yield_to, deadline=deadline or time.time() + QUEUE_BUDGET_S, job="queue")
    return r["stop"] if r["stop"] in ("yield", "budget") else "done"


def daily(bid, now=None, dry=False, out=print, budget_s=None):
    """otto_cron "ad-videos": this month and, once the 25th planned it, next month. → exit code: 1 when the brand had videos
    to render and none could be (no toolchain, or every attempt failed), else 0."""
    now = now or utcnow()
    d = ap.load()
    b = ap.brand(d, bid)
    if b is None:
        out(f"{bid}: unknown brand")
        return 1
    cur = month_of(b, now)
    months = [cur] + [m for m in (next_month(cur),) if _sty().matrix_path(bid, m).exists()]
    deadline = time.time() + (budget_s or _budget_from_env())
    worst = 0
    for ym in months:
        r = render_month(bid, ym, dry=dry, out=out, deadline=deadline, now=now, job="daily")
        if r.get("error") or (r["failed"] and not r["rendered"]):
            worst = 1
    return worst


def _budget_from_env():
    """A nightly run ends its own work before otto_cron's per-brand limit (OTTO_CRON_TIMEOUT_S) would kill it."""
    try:
        lim = float(os.environ.get("OTTO_CRON_TIMEOUT_S") or 0)
    except ValueError:
        lim = 0
    return max(60.0, lim - 15 * 60) if lim else DAILY_BUDGET_S


# ============================================================================================ status

def status_rows(bid=None, now=None):
    now = now or utcnow()
    d = ap.load()
    rows = []
    for b in d.get("brands") or []:
        if not isinstance(b, dict) or (bid and b.get("id") != bid):
            continue
        why = skip_why(d, b)
        cur = month_of(b, now)
        for ym in (cur, next_month(cur)):
            try:
                mx = _sty().load_matrix(b["id"], ym)
            except ValueError as e:
                rows.append({"brand": b["id"], "month": ym, "error": str(e)[:200]})
                continue
            if mx is None:
                continue
            c = candidates(b["id"], ym, mx, d, now=now)
            rows.append({"brand": b["id"], "month": ym, "skip": why, "cap": c["cap"], "rendered": len(c["rendered"]),
                         "todo": len(c["todo"]), "failed": len(c["failed"]), "over_cap": len(c["over_cap"]),
                         "waiting": len(c["waiting"])})
    return rows


# ============================================================================================ CLI

def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def main(argv):
    cmd = argv[0] if argv else ""
    signal.signal(signal.SIGTERM, _on_term)
    if cmd in ("render", "daily"):
        bid = _opt(argv, "--brand")
        if not bid:
            print("--brand B is required")
            return 2
        if cmd == "daily":
            return daily(bid, dry="--dry" in argv)
        only = set((_opt(argv, "--only") or "").split(",")) - {""}
        r = render_month(bid, _opt(argv, "--month"), dry="--dry" in argv, force="--force" in argv, only=only or None)
        return 1 if r.get("error") or (r["failed"] and not r["rendered"]) else 0
    if cmd == "status":
        rows = status_rows(_opt(argv, "--brand"))
        if "--json" in argv:
            print(json.dumps(rows, indent=1))
        for r in rows if "--json" not in argv else []:
            print(f"{r['brand']:16} {r['month']}  " + (r.get("error") or
                  f"{r['rendered']} rendered · {r['todo']} to render · {r['failed']} failed · {r['over_cap']} over the cap "
                  f"({r['cap']} a month)" + (f" · skipped: {r['skip']}" if r.get("skip") else "")))
        return 0
    if cmd == "check":
        why = toolchain()
        print(f"kit {KIT} · HyperFrames {HF_PKG} · npm cache {npm_cache()}")
        print("toolchain: " + (why or "ok"))
        if not why:
            r = subprocess.run(["npx", "--yes", HF_PKG, "--version"], cwd=str(KIT), env=kit_env(), capture_output=True, text=True,
                               timeout=300)
            print(f"npx {HF_PKG}: " + ((r.stdout or "").strip() or _tail(r.stderr, 200)))
        return 1 if why else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
