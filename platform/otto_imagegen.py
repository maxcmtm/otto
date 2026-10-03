#!/usr/bin/env python3
"""Otto images — the Higgsfield Cloud API (pay per use, https://api.higgsfield.ai): Otto's image generator.

  otto_imagegen.py test [--live]                      # config + key + model check: one free cost estimate (no image);
                                                      # --live also makes ONE real 1k / low-quality square (≈ $0.014)
  otto_imagegen.py gen --prompt "…" [--prompt-file f] [--aspect 1:1] [--out file.png | dir/] [--ref img.jpg …]
                       [--quality low|medium|high] [--resolution 1k|2k|4k] [--model gpt-image-2] [--brand otto] [--no-mark]
                                                      # one image (our own creative work: Otto's ads, showcase images)
  otto_imagegen.py estimate [--aspect 9:16] [--quality …] [--resolution …] [--model …] [--refs N]   # what one costs (free)
  otto_imagegen.py status [--json]                    # config (never the key) + today's usage against the caps

The model: GPT Image 2 (Max, 3 Oct 2026) — Higgsfield's endpoint `marketing-studio/image` ("Marketing Studio Image 2.0
Alpha", system name gpt_image_2): photoreal, accurate English text, up to 16 reference images, aspect ratios 1:1 3:2 2:3 4:3
3:4 16:9 9:16 21:9, resolution tiers 1k / 2k / 4k, quality low / medium / high. Post visuals AND reel scenes use it
(image_model = scene_model; a 9:16 scene is a native GPT Image 2 size). Verified prices (POST /estimate, 3 Oct 2026, with
Higgsfield's current 15 % discount; PRICE_GPT2 below): 1k low square $0.014 · 2k medium 3:4 $0.076 · 2k medium 9:16 $0.060 ·
2k high 3:4 $0.277 · 2k high square $0.373 · 4k high square $0.614. The engine's defaults: 2k, quality "medium" for post
visuals and reel scenes (no text in those images), "high" for `gen` (ad creatives with words in them). Other catalogue
models (MODELS: GPT Image 2.5 Flare / Sunburst, Z-Image Turbo, Grok Image 2.0) can be named in the config or with --model.

The request flow (docs.higgsfield.ai, verified end to end 3 Oct 2026):
  POST {base}/{model}  JSON body + Authorization: Key KEY_ID:KEY_SECRET + Idempotency-Key (one uuid per intended image,
       reused on every retry of that submission) → 200 {"status": "queued", "request_id", "status_url", "cancel_url"}
       (status_url / cancel_url point at platform.higgsfield.ai; only *.higgsfield.ai over https ever gets the key)
  GET  status_url (2 s, ×1.5 up to 10 s, + jitter) → queued → in_progress → completed {"images": [{"url"}]} | failed {error}
       | nsfw | canceled (failed / nsfw / canceled are not charged). A 1k square took ~10 s, a PNG of ~1.3 MB.
  GET  the image URL at once (CDN, no key; outputs are kept "at least 7 days"), checked by magic bytes (PNG / JPEG / WebP).
  References: POST {base}/files/generate-upload-url {"content_type"} → {"public_url", "upload_url", "upload_headers"};
       PUT the bytes to upload_url with exactly upload_headers (never the key); public_url goes into the model's image_urls.
  Price: POST {base}/estimate/{model} with the same body (free) → {"credits", "usd"}; claimed against the daily caps before
       the submission and refunded in the ledger when the request ends failed / nsfw / canceled.
Errors map to ImageGenError subclasses (AuthError 401, CreditsError 403, NotFoundError 404, InvalidRequest 400 / 422,
ModelUnavailable 423 / 503, RateLimited 429 or "maximum number of concurrent requests" after the retries, ServerError 5xx /
network after the retries, GenerationFailed, ContentRejected (nsfw), Canceled, GenerationTimeout, DownloadError,
CapReached, NotConfigured). 429 / 5xx / dropped connections / the concurrency 400 are retried with exponential backoff and
jitter (Retry-After honoured when sent; Higgsfield does not send it today); a submission is retried with the same
Idempotency-Key, so a lost answer never creates (or bills) a second image. Messages carry the HTTP status, the API's detail,
the request id and X-Correlation-ID — never the key, never the prompt (logs say its length and a short hash).

Config: <OTTO_SECRETS>/higgsfield.json (owner otto, chmod 600; push_secrets.py writes it from higgsfield-api.txt):
  {"key_id": "…", "key_secret": "…", "image_model": "gpt-image-2", "scene_model": "gpt-image-2",
   "quality": "medium", "scene_quality": "medium", "resolution": "2k", "scene_resolution": "2k",
   "max_images_day": 200, "max_usd_day": 25, "max_images_per_brand_day": 40, "parallel": 2, "timeout_s": 300, "enabled": true}
Only key_id + key_secret are needed. Env HIGGSFIELD_KEY="KEY_ID:KEY_SECRET" overrides the key, OTTO_IMAGEGEN=off switches
it off; OTTO_HIGGSFIELD_API_BASE is honoured only for http://127.0.0.1:<port> (the tests' fake), never anything else.
Usage ledger: imagegen-usage.json next to data.json (OTTO_IMAGEGEN_LEDGER; flock + atomic replace, 45 days kept): per UTC day
images, estimated USD, errors, nsfw, per brand and per model; the owner console's "AI images" Setup row shows today's.
Who calls it: genvisuals.py (post visuals) and otto_video.py scene_images (reel scenes) — Higgsfield first when configured,
Leonardo as the fallback, then the no-key fallback (the post's own picture). Our own creative work (Otto's ads, showcase
images) goes through `otto_imagegen.py gen`, never through the Higgsfield MCP / subscription credits.
Provenance: `gen` marks what it writes as AI-generated (otto_provenance, XMP DigitalSourceType; Higgsfield's PNGs carry no
C2PA manifest); the engine paths mark their own files exactly like the Leonardo ones. Stdlib only (urllib).
"""
import contextlib, fcntl, hashlib, http.client, json, math, os, random, re, socket, sys, tempfile, threading, time, uuid
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_BASE = "https://api.higgsfield.ai"
TRUSTED_HOST = re.compile(r"(?:[a-z0-9-]+\.)*higgsfield\.ai")       # api. and platform. (status / cancel URLs)
DEFAULT_MODEL = "marketing-studio/image"                             # GPT Image 2 (gpt_image_2) — Max, 3 Oct 2026
TERMINAL = ("completed", "failed", "nsfw", "canceled")
LEDGER_DAYS = 45
MAX_IMAGE_BYTES = 60 * 1024 * 1024
MAX_REF_BYTES = 25 * 1024 * 1024
UA = "otto-imagegen/1 (+https://github.com/maxcmtm/otto)"
MIME = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
EXT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}
# name: (default, lowest, highest)
LIMITS = {"timeout_s": (300, 30, 1800), "retries": (4, 1, 8), "parallel": (2, 1, 4), "max_images_day": (200, 1, 5000),
          "max_usd_day": (25.0, 0.5, 1000.0), "max_images_per_brand_day": (40, 1, 1000)}
_GPT_ASPECTS = ("1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9")
_GPT_BASE = {"aspects": _GPT_ASPECTS, "resolutions": ("1k", "2k", "4k"), "refs": 16, "ref_field": "image_urls",
             "prompt_max": 5000, "kind": "gpt"}
MODELS = {
    "marketing-studio/image": dict(_GPT_BASE, label="gpt-image-2", name="GPT Image 2 (Marketing Studio Image 2.0 Alpha)",
                                   qualities=("low", "medium", "high"), price=None),
    "marketing-studio/image/flare": dict(_GPT_BASE, label="gpt-image-2.5-flare", name="GPT Image 2.5 Flare (Marketing Studio 2.5)",
                                         qualities=("low", "medium", "high", "xhigh", "max"), price=0.45),
    "marketing-studio/image/sunburst": dict(_GPT_BASE, label="gpt-image-2.5-sunburst", name="Marketing Studio Image 2.5 Sunburst",
                                            qualities=("low", "medium", "high", "xhigh", "max"), price=0.45),
    "z-image/turbo": {"label": "z-image-turbo", "name": "Z-Image Turbo", "kind": "zimage", "qualities": (), "refs": 0,
                      "aspects": ("1:1", "2:3", "3:2", "3:4", "4:3", "7:9", "9:7", "9:16", "16:9", "21:9"),
                      "resolutions": ("1k", "2k"), "prompt_max": 800, "ref_field": None, "price": 0.03},
    "xai/grok-imagine-image-2.0": {"label": "grok-imagine-image-2.0", "name": "Grok Image 2.0", "kind": "grok",
                                   "qualities": ("low", "medium"), "refs": 10, "ref_field": "image_urls",
                                   "aspects": ("1:1", "1:2", "2:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"),
                                   "resolutions": ("1k", "2k"), "prompt_max": 5000, "price": 0.12},
}
ALIASES = {"gpt-image-2": "marketing-studio/image", "gpt_image_2": "marketing-studio/image", "gpt-image": "marketing-studio/image",
           "marketing-studio-image": "marketing-studio/image", "gpt-image-2.5-flare": "marketing-studio/image/flare",
           "flare": "marketing-studio/image/flare", "sunburst": "marketing-studio/image/sunburst",
           "z-image-turbo": "z-image/turbo", "grok-image-2": "xai/grok-imagine-image-2.0"}
# GPT Image 2 per image in USD, from POST /estimate on 3 Oct 2026 (Higgsfield's 15 % discount included): the fallback when
# the free estimate call fails. (resolution, quality) → {aspect class: usd}; 3:2 / 2:3 / 4:3 count as 3:4, 16:9 / 21:9 as 9:16.
PRICE_GPT2 = {("1k", "low"): {"1:1": 0.014, "3:4": 0.013, "9:16": 0.012}, ("1k", "medium"): {"1:1": 0.054, "3:4": 0.043, "9:16": 0.034},
              ("1k", "high"): {"1:1": 0.188, "3:4": 0.143, "9:16": 0.109}, ("2k", "low"): {"1:1": 0.019, "3:4": 0.017, "9:16": 0.015},
              ("2k", "medium"): {"1:1": 0.100, "3:4": 0.076, "9:16": 0.060}, ("2k", "high"): {"1:1": 0.373, "3:4": 0.277, "9:16": 0.210},
              ("4k", "low"): {"1:1": 0.026, "3:4": 0.022, "9:16": 0.019}, ("4k", "medium"): {"1:1": 0.160, "3:4": 0.122, "9:16": 0.094},
              ("4k", "high"): {"1:1": 0.614, "3:4": 0.459, "9:16": 0.349}}
REF_SURCHARGE = 0.015                       # per call with references (input tokens: 1 ref ≈ +$0.011, 3 refs ≈ +$0.033 at 2k high)
DEFAULTS = {"quality": "medium", "scene_quality": "medium", "cli_quality": "high", "resolution": "2k", "scene_resolution": "2k"}
NAMED_ASPECTS = {"story": "9:16", "reel": "9:16", "scene": "9:16", "vertical": "9:16", "feed": "4:5", "carousel": "4:5",
                 "portrait": "4:5", "square": "1:1", "post": "1:1", "landscape": "16:9"}
SLEEP = time.sleep                          # tests replace SLEEP / CLOCK with a fake clock
CLOCK = time.monotonic


# ============================================================================================ errors

class ImageGenError(Exception):
    """Base: a clear, secret-free message plus what support needs (status, request id, correlation id)."""
    fallback = True                         # worth trying the next provider

    def __init__(self, msg, status=None, request_id=None, correlation_id=None):
        super().__init__(msg)
        self.status, self.request_id, self.correlation_id = status, request_id, correlation_id

    def __str__(self):
        extra = [f"HTTP {self.status}" if self.status else "", f"request {self.request_id}" if self.request_id else "",
                 f"correlation {self.correlation_id}" if self.correlation_id else ""]
        extra = [x for x in extra if x]
        return super().__str__() + (f" ({', '.join(extra)})" if extra else "")


class NotConfigured(ImageGenError):
    pass


class CapReached(ImageGenError):
    pass


class AuthError(ImageGenError):
    pass


class CreditsError(ImageGenError):
    pass


class NotFoundError(ImageGenError):
    pass


class InvalidRequest(ImageGenError):
    pass


class ModelUnavailable(ImageGenError):
    pass


class RateLimited(ImageGenError):
    pass


class ServerError(ImageGenError):
    pass


class GenerationFailed(ImageGenError):
    pass


class ContentRejected(ImageGenError):
    pass


class Canceled(ImageGenError):
    pass


class GenerationTimeout(ImageGenError):
    pass


class DownloadError(ImageGenError):
    pass


# ============================================================================================ config

def secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")


def _bounded(v, default, lo, hi):
    cast = float if isinstance(default, float) else int
    try:
        x = cast(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def canonical_model(name):
    """'gpt-image-2' / 'marketing-studio/image' → the endpoint id in MODELS, else None."""
    n = str(name or "").strip().strip("/").lower()
    n = ALIASES.get(n, n)
    return n if n in MODELS else None


def _split_key(v):
    kid, sep, sec = str(v or "").strip().partition(":")
    return (kid.strip(), sec.strip()) if sep and kid.strip() and sec.strip() else (None, None)


def config():
    """higgsfield.json + env → the settings. The key is in it: never print, log or return it to a browser (public())."""
    f = secrets_dir() / "higgsfield.json"
    raw, err, warn = {}, None, []
    if f.exists():
        try:
            raw = json.loads(f.read_text())
        except Exception:                                     # noqa: BLE001 — a broken file is "not set up", said once
            raw, err = {}, "higgsfield.json is not valid JSON"
        if not isinstance(raw, dict):
            raw, err = {}, "higgsfield.json is not a JSON object"
    env_id, env_secret = _split_key(os.environ.get("HIGGSFIELD_KEY"))
    file_id = raw.get("key_id").strip() if isinstance(raw.get("key_id"), str) else ""
    file_secret = raw.get("key_secret").strip() if isinstance(raw.get("key_secret"), str) else ""
    if not (file_id and file_secret) and isinstance(raw.get("key"), str):           # {"key": "id:secret"} works too
        file_id, file_secret = (x or "" for x in _split_key(raw["key"]))
    key_id, key_secret = (env_id, env_secret) if env_id else (file_id or None, file_secret or None)
    if bool(key_id) != bool(key_secret):
        key_id = key_secret = None
        err = err or "higgsfield.json needs both key_id and key_secret"
    image_model = canonical_model(raw.get("image_model")) or DEFAULT_MODEL
    if raw.get("image_model") and not canonical_model(raw.get("image_model")):
        warn.append(f"unknown image_model {str(raw.get('image_model'))[:60]!r}: using {MODELS[DEFAULT_MODEL]['label']}")
    scene_model = canonical_model(raw.get("scene_model")) or image_model
    if raw.get("scene_model") and not canonical_model(raw.get("scene_model")):
        warn.append(f"unknown scene_model {str(raw.get('scene_model'))[:60]!r}: using {MODELS[image_model]['label']}")
    base = (os.environ.get("OTTO_HIGGSFIELD_API_BASE") or "").strip().rstrip("/")
    if not re.fullmatch(r"http://127\.0\.0\.1:\d{1,5}", base):
        base = API_BASE                                       # the key only ever goes to Higgsfield (or the tests' local fake)
    off = (os.environ.get("OTTO_IMAGEGEN") or "").strip().lower() in ("off", "0", "false", "no") or raw.get("enabled") is False
    cfg = {"file": f.exists(), "error": err, "warnings": warn, "key_id": key_id, "key_secret": key_secret,
           "key_source": ("env" if env_id else "file") if key_id else None, "image_model": image_model,
           "scene_model": scene_model, "api_base": base, "enabled": not off}
    for k, dflt in DEFAULTS.items():
        cfg[k] = str(raw.get(k) or dflt).strip().lower()
    for k, (dflt, lo, hi) in LIMITS.items():
        cfg[k] = _bounded(raw.get(k), dflt, lo, hi)
    return cfg


def ready(cfg=None):
    """Can Otto make images through Higgsfield? A key, and not switched off."""
    cfg = cfg or config()
    return bool(cfg["key_id"] and cfg["key_secret"]) and cfg["enabled"]


def public(cfg):
    """The config without the key (status --json, the owner console)."""
    return {k: v for k, v in cfg.items() if k not in ("key_id", "key_secret")}


def tool_name(model):
    """What the provenance mark names as the AI system, e.g. "Higgsfield gpt-image-2"."""
    m = canonical_model(model) or DEFAULT_MODEL
    return f"Higgsfield {MODELS[m]['label']}"


# ============================================================================================ small helpers

def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sniff(data):
    head = bytes(data[:16])
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def prompt_tag(prompt):
    """What a log may say about a prompt: its length and a short hash (never the words: they carry client data)."""
    p = str(prompt or "")
    return f"prompt {len(p)} chars #{hashlib.sha1(p.encode('utf-8')).hexdigest()[:8]}"


def _scrub(text, cfg=None):
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()
    for s in ((cfg or {}).get("key_secret"), (cfg or {}).get("key_id")):
        if s:
            t = t.replace(s, "[key]")
    t = re.sub(r"(?i)(authorization|key)\s*[:=]\s*\S+", r"\1: [redacted]", t)
    return t[:300]


def _ratio(size):
    """'9:16' / '1080x1920' / (1080, 1920) / 'story' → width / height (float)."""
    if isinstance(size, (tuple, list)) and len(size) == 2:
        w, h = float(size[0]), float(size[1])
    else:
        s = NAMED_ASPECTS.get(str(size or "1:1").strip().lower(), str(size or "1:1").strip().lower())
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[:x×/]\s*(\d+(?:\.\d+)?)", s)
        if not m:
            raise InvalidRequest(f"aspect {str(size)[:20]!r} is not W:H, WxH or one of {', '.join(sorted(NAMED_ASPECTS))}")
        w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0:
        raise InvalidRequest("aspect sides must be positive")
    return w / h


def aspect_for(model, size):
    """The model's supported aspect ratio nearest to `size` (exact when it is supported; 4:5 → 3:4 on GPT Image 2)."""
    spec = MODELS[canonical_model(model) or DEFAULT_MODEL]
    if isinstance(size, str) and size.strip() in spec["aspects"]:
        return size.strip()
    r = _ratio(size)
    return min(spec["aspects"], key=lambda a: abs(math.log(r) - math.log(_ratio(a))))


def _aspect_class(aspect):
    r = _ratio(aspect)
    return "1:1" if abs(math.log(r)) < 0.05 else "9:16" if abs(math.log(r)) > 0.45 else "3:4"


def price_guess(model, aspect, quality, resolution, refs=0):
    """USD for one image when the estimate endpoint cannot be reached (PRICE_GPT2; other models: their table price)."""
    m = canonical_model(model) or DEFAULT_MODEL
    if m == DEFAULT_MODEL:
        row = PRICE_GPT2.get((resolution, quality)) or PRICE_GPT2[("4k", "high")]
        usd = row[_aspect_class(aspect)]
    else:
        usd = MODELS[m]["price"] or 0.5
    return round(usd + (REF_SURCHARGE if refs else 0), 4)


def build_body(model, prompt, aspect, quality=None, resolution=None, ref_urls=None):
    """The model's JSON body (its documented schema). Raises InvalidRequest for what the model cannot take."""
    m = canonical_model(model)
    if not m:
        raise InvalidRequest(f"unknown model {str(model)[:60]!r} (known: {', '.join(sorted(MODELS))})")
    spec = MODELS[m]
    prompt = str(prompt or "").strip()
    if not prompt:
        raise InvalidRequest("the prompt is empty")
    if len(prompt) > spec["prompt_max"]:
        raise InvalidRequest(f"the prompt has {len(prompt)} characters; {spec['label']} takes at most {spec['prompt_max']}")
    if aspect not in spec["aspects"]:
        raise InvalidRequest(f"{spec['label']} has no aspect {aspect} ({', '.join(spec['aspects'])})")
    body = {"prompt": prompt, "aspect_ratio": aspect}
    if spec["resolutions"]:
        r = resolution or "2k"
        if r not in spec["resolutions"]:
            r = spec["resolutions"][-1] if r == "4k" else spec["resolutions"][0]
        body["resolution"] = r
    if spec["qualities"]:
        q = quality or "medium"
        if q not in spec["qualities"]:
            raise InvalidRequest(f"{spec['label']} has no quality {q!r} ({', '.join(spec['qualities'])})")
        body["quality"] = q
    if spec["kind"] == "gpt":
        body["enhance_prompt"] = False                       # our prompt as written: no preset rewrite (+10 %)
    elif spec["kind"] == "zimage":
        body["prompt_extend"] = False
    refs = list(ref_urls or [])
    if refs:
        if not spec["refs"]:
            raise InvalidRequest(f"{spec['label']} takes no reference images")
        if len(refs) > spec["refs"]:
            raise InvalidRequest(f"{spec['label']} takes at most {spec['refs']} reference images, got {len(refs)}")
        body[spec["ref_field"]] = refs
    return body


# ============================================================================================ HTTP

def _origin(url):
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}".lower()


def _trusted(url, cfg):
    """May this URL get the key? The configured base's origin, or https *.higgsfield.ai when the base is the real API."""
    try:
        u = urllib.parse.urlsplit(str(url))
    except ValueError:
        return False
    if _origin(url) == _origin(cfg["api_base"]):
        return True
    return cfg["api_base"] == API_BASE and u.scheme == "https" and bool(TRUSTED_HOST.fullmatch((u.hostname or "").lower()))


def _fetchable(url, cfg):
    """May we download from / upload to this URL (no key sent)? https anywhere; plain http only to the tests' local base."""
    u = urllib.parse.urlsplit(str(url))
    return u.scheme == "https" or (u.scheme == "http" and cfg["api_base"] != API_BASE and _origin(url) == _origin(cfg["api_base"]))


def _retry_after(headers, default):
    v = (headers or {}).get("Retry-After") if headers is not None else None
    if not v:
        return default
    try:
        return max(0.0, min(120.0, float(v)))
    except ValueError:
        try:
            return max(0.0, min(120.0, (parsedate_to_datetime(v) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return default


def _backoff(attempt, base=1.0, cap=30.0):
    return min(cap, base * (2 ** attempt)) + random.uniform(0, 0.5)


def _detail(raw):
    try:
        j = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw[:200].decode("utf-8", "replace")
    d = j.get("detail") if isinstance(j, dict) else j
    if isinstance(d, list):                                  # FastAPI validation errors
        d = "; ".join(f"{'.'.join(str(x) for x in (e.get('loc') or [])[1:])}: {e.get('msg')}" if isinstance(e, dict) else str(e)
                      for e in d[:4])
    return str(d if d is not None else j)


ERRORS = {401: AuthError, 403: CreditsError, 404: NotFoundError, 422: InvalidRequest, 423: ModelUnavailable}
WHAT = {401: "the Higgsfield key was refused (check key_id / key_secret)", 403: "the Higgsfield account has no credits left",
        404: "not found for this account (model or request)", 422: "the request was rejected", 423: "the model is temporarily blocked",
        503: "the model is disabled or not ready"}


def _call(cfg, method, url, payload=None, idem=None, retries=None, timeout=60, what="request"):
    """One JSON call to Higgsfield with retries → the parsed JSON (dict). Raises an ImageGenError subclass."""
    if not _trusted(url, cfg):
        raise ImageGenError(f"refusing to send the Higgsfield key to {urllib.parse.urlsplit(url).hostname or '?'}")
    tries = (cfg["retries"] if retries is None else retries) + 1
    data = json.dumps(payload).encode() if payload is not None else None
    last = None
    for attempt in range(tries):
        h = {"Authorization": f"Key {cfg['key_id']}:{cfg['key_secret']}", "Accept": "application/json", "User-Agent": UA}
        if data is not None:
            h["Content-Type"] = "application/json"
        if idem:
            h["Idempotency-Key"] = idem
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        wait = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            try:
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except ValueError:
                raise ServerError(f"Higgsfield {what}: the answer is not JSON")
        except urllib.error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            detail = _scrub(_detail(raw or b""), cfg)
            corr = e.headers.get("X-Correlation-ID") if e.headers is not None else None
            code = e.code
            if code == 429:
                last = RateLimited(f"Higgsfield {what}: rate limited — {detail}", code, correlation_id=corr)
                wait = _retry_after(e.headers, _backoff(attempt, 2.0, 60.0))
            elif code == 400 and re.search(r"concurren", detail, re.I):
                last = RateLimited(f"Higgsfield {what}: {detail}", code, correlation_id=corr)
                wait = _retry_after(e.headers, _backoff(attempt, 4.0, 60.0))
            elif code >= 500:
                cls = ModelUnavailable if code == 503 else ServerError
                last = cls(f"Higgsfield {what}: {WHAT.get(code, 'server error')} — {detail}", code, correlation_id=corr)
                wait = _retry_after(e.headers, _backoff(attempt, 1.0, 30.0))
            else:
                cls = ERRORS.get(code, InvalidRequest)
                raise cls(f"Higgsfield {what}: {WHAT.get(code, 'the request was rejected')} — {detail}", code, correlation_id=corr)
        except (urllib.error.URLError, socket.timeout, ConnectionError, http.client.HTTPException, OSError) as e:
            reason = getattr(e, "reason", e)
            last = ServerError(f"Higgsfield {what}: network — {type(e).__name__}: {_scrub(reason, cfg)}")
            wait = _backoff(attempt, 1.0, 30.0)
        if attempt + 1 < tries:
            SLEEP(wait)
    raise last


def _get_bytes(cfg, url, limit, what="download", tries=3):
    if not _fetchable(url, cfg):
        raise DownloadError(f"Higgsfield {what}: refusing a non-https URL")
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read(limit + 1)
            if len(data) > limit:
                raise DownloadError(f"Higgsfield {what}: the file is larger than {limit // (1024 * 1024)} MB")
            return data
        except urllib.error.HTTPError as e:
            last = DownloadError(f"Higgsfield {what}: HTTP {e.code}", e.code)
            if e.code < 500 and e.code != 429:
                raise last
        except (urllib.error.URLError, socket.timeout, ConnectionError, http.client.HTTPException, OSError) as e:
            last = DownloadError(f"Higgsfield {what}: network — {type(e).__name__}")
        if attempt + 1 < tries:
            SLEEP(_backoff(attempt, 1.0, 10.0))
    raise last


def upload_ref(cfg, ref):
    """A reference image → a public URL the model can read: an https URL passes through; a local file goes through
    Higgsfield's upload flow (generate-upload-url → PUT with exactly the returned headers, no key → public_url)."""
    if isinstance(ref, str) and ref.startswith("https://"):
        return ref
    p = Path(ref)
    if not p.is_file():
        raise InvalidRequest(f"reference image {p.name} does not exist")
    data = p.read_bytes()
    if len(data) > MAX_REF_BYTES:
        raise InvalidRequest(f"reference image {p.name} is larger than {MAX_REF_BYTES // (1024 * 1024)} MB")
    kind = sniff(data)
    if kind not in MIME:
        raise InvalidRequest(f"reference image {p.name} must be JPEG, PNG, WebP or GIF")
    j = _call(cfg, "POST", f"{cfg['api_base']}/files/generate-upload-url", {"content_type": MIME[kind]}, what="upload URL")
    up, pub = j.get("upload_url"), j.get("public_url")
    if not up or not pub or not _fetchable(up, cfg) or not _fetchable(pub, cfg):
        raise ServerError("Higgsfield upload URL: the answer has no usable upload_url / public_url")
    hdr = {str(k): str(v) for k, v in (j.get("upload_headers") or {"Content-Type": MIME[kind]}).items()}
    if not any(k.lower() == "content-type" for k in hdr):
        hdr["Content-Type"] = MIME[kind]
    last = None
    for attempt in range(3):
        req = urllib.request.Request(up, data=data, method="PUT", headers=hdr)      # never the Higgsfield key here
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
            return pub
        except urllib.error.HTTPError as e:
            last = ServerError(f"Higgsfield upload: HTTP {e.code}", e.code)
            if e.code < 500:
                raise last
        except (urllib.error.URLError, socket.timeout, ConnectionError, http.client.HTTPException, OSError) as e:
            last = ServerError(f"Higgsfield upload: network — {type(e).__name__}")
        if attempt < 2:
            SLEEP(_backoff(attempt, 1.0, 10.0))
    raise last


def estimate(cfg, model, body):
    """USD for one request from POST /estimate/{model} (free, no image), or None when it gives no number."""
    m = canonical_model(model) or model
    try:
        j = _call(cfg, "POST", f"{cfg['api_base']}/estimate/{m}", body, retries=1, timeout=30, what="estimate")
    except (AuthError, CreditsError, NotFoundError):
        raise                                                # the generation would fail the same way
    except ImageGenError:
        return None
    try:
        return float(j.get("usd")) if isinstance(j, dict) and j.get("usd") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _status_url(cfg, j, rid):
    u = j.get("status_url")
    return u if u and _trusted(u, cfg) else f"{cfg['api_base']}/requests/{rid}/status"


def _cancel(cfg, j, rid):
    u = j.get("cancel_url")
    u = u if u and _trusted(u, cfg) else f"{cfg['api_base']}/requests/{rid}/cancel"
    try:
        _call(cfg, "POST", u, None, retries=1, timeout=20, what="cancel")
        return True
    except ImageGenError:
        return False


def _wait(cfg, sub, rid, deadline):
    """Poll until a terminal status (backoff 2 s ×1.5 → 10 s + jitter) → the completed JSON. Raises on failed / nsfw /
    canceled / the deadline (a request still queued then is canceled: not charged)."""
    url, delay, last = _status_url(cfg, sub, rid), 2.0, sub.get("status") or "queued"
    while True:
        if CLOCK() >= deadline:
            if last == "queued" and _cancel(cfg, sub, rid):
                raise GenerationTimeout(f"Higgsfield: still queued after {cfg['timeout_s']} s — canceled, not charged", request_id=rid)
            raise GenerationTimeout(f"Higgsfield: no result after {cfg['timeout_s']} s (last status {last}; it may still finish "
                                    "and be charged)", request_id=rid)
        SLEEP(max(0.0, min(delay, deadline - CLOCK())) + random.uniform(0, 0.5))
        delay = min(delay * 1.5, 10.0)
        try:
            st = _call(cfg, "GET", url, retries=2, timeout=30, what="status")
        except (ServerError, RateLimited, ModelUnavailable):
            continue                                         # transient: keep polling until the deadline
        s = str(st.get("status") or "")
        last = s or last
        if s == "completed":
            return st
        if s == "failed":
            raise GenerationFailed(f"Higgsfield: generation failed — {_scrub(st.get('error') or 'no reason given', cfg)} "
                                   "(not charged)", request_id=rid)
        if s == "nsfw":
            raise ContentRejected("Higgsfield: rejected by content moderation (not charged)", request_id=rid)
        if s == "canceled":
            raise Canceled("Higgsfield: the request was canceled (not charged)", request_id=rid)


# ============================================================================================ usage ledger + caps

def ledger_path():
    if os.environ.get("OTTO_IMAGEGEN_LEDGER"):
        return Path(os.environ["OTTO_IMAGEGEN_LEDGER"])
    try:
        import ap
        return ap.DATA.parent / "imagegen-usage.json"
    except Exception:                                         # noqa: BLE001 — the CLI works without the engine's state
        return HERE / "imagegen-usage.json"


def _atomic(path, text):
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _ledger():
    """flock + load + yield + atomic save (only when the block finished without an exception)."""
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p) + ".lock", "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            try:
                led = json.loads(p.read_text()) if p.exists() else {}
            except (OSError, ValueError):
                led = {}
            led = led if isinstance(led, dict) else {}
            led["days"] = led.get("days") if isinstance(led.get("days"), dict) else {}
            led["last"] = led.get("last") if isinstance(led.get("last"), dict) else {}
            yield led
            led["days"] = {k: led["days"][k] for k in sorted(led["days"])[-LEDGER_DAYS:]}
            _atomic(p, json.dumps(led, ensure_ascii=False, indent=1))
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _blank():
    return {"images": 0, "usd": 0.0, "errors": 0, "nsfw": 0}


def _today(led, now=None):
    day = led["days"].setdefault((now or utcnow()).astimezone(timezone.utc).date().isoformat(), dict(_blank(), brands={}, models={}))
    day.setdefault("brands", {})
    day.setdefault("models", {})
    return day


def reserve(cfg, bid, usd, model, now=None):
    """Claim one image (and its estimated USD) against today's caps (UTC day). → None to go ahead, else why not."""
    with _ledger() as led:
        day = _today(led, now)
        br = day["brands"].setdefault(bid, _blank())
        if day["images"] >= cfg["max_images_day"]:
            return f"the daily cap of {cfg['max_images_day']} images is reached"
        if day["usd"] + usd > cfg["max_usd_day"]:
            return f"the daily spend cap of ${cfg['max_usd_day']:g} is reached (${day['usd']:.2f} used today)"
        if br["images"] >= cfg["max_images_per_brand_day"]:
            return f"{bid} reached its daily cap of {cfg['max_images_per_brand_day']} images"
        mo = day["models"].setdefault(MODELS[model]["label"], _blank())
        for t in (day, br, mo):
            t["images"] += 1
            t["usd"] = round(t["usd"] + usd, 4)
    return None


def settle(bid, usd, model, outcome, info=None, now=None):
    """After a reserved request: outcome "ok" keeps the claim; "failed" / "nsfw" / "canceled" / "error" (never billed by
    Higgsfield) gives the image and its USD back; "timeout" keeps it (an in-progress request may still be billed)."""
    with _ledger() as led:
        day = _today(led, now)
        br = day["brands"].setdefault(bid, _blank())
        mo = day["models"].setdefault(MODELS[model]["label"], _blank())
        for t in (day, br, mo):
            if outcome in ("failed", "nsfw", "canceled", "error"):
                t["images"] = max(0, t["images"] - 1)
                t["usd"] = round(max(0.0, t["usd"] - usd), 4)
            if outcome == "nsfw":
                t["nsfw"] += 1
            elif outcome != "ok":
                t["errors"] += 1
        if info:
            led["last"][bid] = dict(info, at=iso(now or utcnow()), outcome=outcome)


def usage_today(now=None):
    p = ledger_path()
    try:
        led = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        led = {}
    day = ((led.get("days") or {}).get((now or utcnow()).astimezone(timezone.utc).date().isoformat())) or dict(_blank(), brands={}, models={})
    return day, (led.get("last") or {})


# ============================================================================================ generation

_proc_lock = threading.Lock()
_proc_sem = {}


def _slot(cfg):
    """A process-wide semaphore of cfg["parallel"]: at most that many requests queued / in progress from this process."""
    with _proc_lock:
        n = cfg["parallel"]
        if n not in _proc_sem:
            _proc_sem[n] = threading.BoundedSemaphore(n)
        return _proc_sem[n]


def render(prompt, aspect="1:1", refs=None, model=None, quality=None, resolution=None, brand="otto", purpose="image", cfg=None,
           log=print):
    """One image through Higgsfield → {"images": [(bytes, kind)], "request_id", "model", "label", "tool", "aspect",
    "resolution", "quality", "usd", "seconds"}. `purpose` "scene" uses scene_model / scene_quality / scene_resolution,
    "cli" the CLI's quality; anything else image_model / quality / resolution. Raises an ImageGenError subclass."""
    cfg = cfg or config()
    if not ready(cfg):
        raise NotConfigured("Higgsfield is not configured" + (f": {cfg['error']}" if cfg.get("error") else "")
                            if cfg["enabled"] else "Higgsfield is switched off (OTTO_IMAGEGEN=off or \"enabled\": false)")
    scene = purpose == "scene"
    m = canonical_model(model) if model else (cfg["scene_model"] if scene else cfg["image_model"])
    if not m:
        raise InvalidRequest(f"unknown model {str(model)[:60]!r} (known: {', '.join(sorted(MODELS))})")
    spec = MODELS[m]
    q = quality or (cfg["scene_quality"] if scene else cfg["cli_quality"] if purpose == "cli" else cfg["quality"])
    if spec["qualities"] and q not in spec["qualities"]:
        q = "medium" if "medium" in spec["qualities"] else spec["qualities"][-1]
    res = resolution or (cfg["scene_resolution"] if scene else cfg["resolution"])
    asp = aspect_for(m, aspect)
    refs = list(refs or [])
    if len(refs) > spec["refs"]:
        raise InvalidRequest(f"{spec['label']} takes at most {spec['refs']} reference images, got {len(refs)}")
    body = build_body(m, prompt, asp, q, res, ["https://placeholder.invalid/ref.png"] * len(refs) if refs else None)
    bid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(brand or "otto"))[:60] or "otto"
    with _slot(cfg):
        t0 = CLOCK()                                         # the deadline starts once this request has its slot
        ref_urls = [upload_ref(cfg, r) for r in refs]
        body = build_body(m, prompt, asp, body.get("quality"), body.get("resolution"), ref_urls or None)
        usd = estimate(cfg, m, body)
        usd = usd if usd is not None else price_guess(m, asp, body.get("quality"), body.get("resolution"), len(refs))
        why = reserve(cfg, bid, usd, m)
        if why:
            raise CapReached(f"Higgsfield: {why}")
        idem, rid, info = str(uuid.uuid4()), None, {"purpose": purpose, "model": spec["label"], "aspect": asp}
        try:
            sub = _call(cfg, "POST", f"{cfg['api_base']}/{m}", body, idem=idem, what="submit")
            rid = str(sub.get("request_id") or "")
            if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", rid):
                raise ServerError("Higgsfield submit: no request_id in the answer")
            log(f"  higgsfield {spec['label']} {asp} {body.get('resolution', '')} {body.get('quality', '')} · {prompt_tag(prompt)} "
                f"· ≈${usd:.3f} · request {rid}")
            done = _wait(cfg, sub, rid, t0 + cfg["timeout_s"])
            urls = [x.get("url") for x in (done.get("images") or []) if isinstance(x, dict) and x.get("url")]
            if not urls:
                raise GenerationFailed("Higgsfield: completed without an image", request_id=rid)
            images = []
            for u in urls:                                   # download now: outputs expire (≥ 7 days)
                data = _get_bytes(cfg, u, MAX_IMAGE_BYTES)
                kind = sniff(data)
                if kind not in ("png", "jpeg", "webp"):
                    raise DownloadError("Higgsfield download: not an image (PNG / JPEG / WebP)", request_id=rid)
                images.append((data, kind))
        except ContentRejected:
            settle(bid, usd, m, "nsfw", dict(info, request_id=rid))
            raise
        except (GenerationFailed, Canceled) as e:
            settle(bid, usd, m, "failed" if isinstance(e, GenerationFailed) else "canceled", dict(info, request_id=rid))
            raise
        except GenerationTimeout as e:
            settle(bid, usd, m, "canceled" if "canceled" in str(e) else "timeout", dict(info, request_id=rid))
            raise
        except ImageGenError as e:
            # never accepted (no rid) → never billed; accepted but the download failed → billed, keep the claim
            settle(bid, usd, m, "error" if not rid else "download", dict(info, request_id=rid, error=type(e).__name__))
            if rid and not e.request_id:
                e.request_id = rid
            raise
        except Exception:
            settle(bid, usd, m, "error" if not rid else "download", dict(info, request_id=rid))
            raise
    secs = round(CLOCK() - t0, 1)
    settle(bid, usd, m, "ok", dict(info, request_id=rid, seconds=secs, usd=usd))
    return {"images": images, "request_id": rid, "model": m, "label": spec["label"], "tool": tool_name(m), "aspect": asp,
            "resolution": body.get("resolution"), "quality": body.get("quality"), "usd": usd, "seconds": secs}


def generate_many(jobs, cfg=None, log=print):
    """Several render() calls, cfg["parallel"] at a time → one entry per job, in order: the result dict or the exception.
    jobs: dicts of render() keyword arguments. A cap or a refused key stops the rest (they come back as that error)."""
    cfg = cfg or config()
    if not jobs:
        return []
    stop = {}

    def one(kw):
        if stop.get("err"):
            return stop["err"]
        try:
            return render(cfg=cfg, log=log, **kw)
        except (CapReached, AuthError, CreditsError, NotConfigured) as e:
            stop["err"] = e
            return e
        except ImageGenError as e:
            return e
        except Exception as e:                               # noqa: BLE001 — one job never kills the batch
            return ImageGenError(f"Higgsfield: {type(e).__name__}: {_scrub(e, cfg)}")
    with ThreadPoolExecutor(max_workers=cfg["parallel"]) as ex:
        return list(ex.map(one, jobs))


def _write(path, data, kind):
    """Bytes → path; the suffix follows the real type unless the caller asked for .jpg and ffmpeg can convert."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    want = path.suffix.lower()
    real = EXT.get(kind, ".png")
    if want in (".jpg", ".jpeg") and kind != "jpeg":
        import shutil, subprocess
        ff = shutil.which("ffmpeg")
        if ff:
            tmp = path.with_suffix(real)
            tmp.write_bytes(data)
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1", "-q:v", "2", str(path)],
                               capture_output=True)
            if r.returncode == 0:
                tmp.unlink()
                return path
            tmp.unlink()
        path = path.with_suffix(real)
    elif want != real and not (want == ".jpeg" and kind == "jpeg"):
        path = path.with_suffix(real)
    path.write_bytes(data)
    return path


def generate(prompt, aspect="1:1", refs=None, model=None, out=None, quality=None, resolution=None, brand="otto", purpose="cli",
             mark=True, cfg=None, log=print):
    """One generation, saved → [local file paths]. `out`: a file path (its suffix follows the real image type, .jpg is
    converted with ffmpeg), a directory (ends with "/" or exists: <dir>/hf-<request>.<ext>), or None (a temp dir).
    Every file is marked as AI-generated (otto_provenance) unless mark=False."""
    res = render(prompt, aspect, refs, model, quality, resolution, brand, purpose, cfg, log)
    paths = []
    o = Path(out) if out else Path(tempfile.mkdtemp(prefix="otto-imagegen-"))
    as_dir = out is None or str(out).endswith(("/", os.sep)) or o.is_dir()
    for i, (data, kind) in enumerate(res["images"], 1):
        if as_dir:
            dst = o / f"hf-{res['request_id'][:8]}{'-' + str(i) if len(res['images']) > 1 else ''}{EXT.get(kind, '.png')}"
        else:
            dst = o if len(res["images"]) == 1 else o.with_name(f"{o.stem}-{i}{o.suffix}")
        p = _write(dst, data, kind)
        if mark:
            try:
                import otto_provenance as prov
                prov.mark_safely(p, ["image"], res["tool"], log=log)
            except ImportError:
                log("  provenance: otto_provenance not found — file not marked")
        paths.append(p)
    return paths


# ============================================================================================ status (CLI + owner console)

def console_row():
    """The owner console's Setup row (otto_admin.setup_items): key, model, today's images / spend against the caps."""
    cfg = config()
    day, last = usage_today()
    at = max((str(v.get("at") or "") for v in last.values() if isinstance(v, dict)), default="") or None
    use = (f"today {day.get('images', 0)} image(s), ≈ ${day.get('usd', 0):.2f}"
           + (f", {day.get('errors', 0)} error(s)" if day.get("errors") else "") + (f", {day.get('nsfw', 0)} rejected" if day.get("nsfw") else "")
           + f" (caps: {cfg['max_images_day']} images, ${cfg['max_usd_day']:g} a day, {cfg['max_images_per_brand_day']} per brand)")
    top = sorted(((b, v) for b, v in (day.get("brands") or {}).items() if isinstance(v, dict) and v.get("images")),
                 key=lambda x: -x[1].get("usd", 0))[:4]
    if top:
        use += " · " + ", ".join(f"{b} {v['images']} (${v.get('usd', 0):.2f})" for b, v in top)
    label = MODELS[cfg["image_model"]]["label"] + (f" / scenes {MODELS[cfg['scene_model']]['label']}"
                                                   if cfg["scene_model"] != cfg["image_model"] else "")
    if ready(cfg):
        status, detail = "connected", (f"Post visuals and reel scenes ({label}, {cfg['resolution']} {cfg['quality']}; Leonardo is the "
                                       f"fallback) · {use}")
    elif cfg["key_id"]:
        status, detail = "waiting", "Switched off (OTTO_IMAGEGEN=off or \"enabled\": false): visuals use Leonardo when its key is set"
    else:
        status = "missing"
        detail = (f"Cannot be used: {cfg['error']}" if cfg["error"] else "No Higgsfield API key") + \
            " — post visuals and reel scenes use Leonardo when its key is set, else a reel reuses the post's own picture"
    if cfg.get("warnings"):
        detail += " · " + "; ".join(cfg["warnings"])
    return {"key": "imagegen", "label": "AI images (Higgsfield Cloud API)", "status": status, "detail": detail, "at": at,
            "how": "console.higgsfield.ai → API keys → create a key (pay per use; top up the balance). Put "
                   "{\"key_id\": \"…\", \"key_secret\": \"…\", \"image_model\": \"gpt-image-2\", \"scene_model\": \"gpt-image-2\"} into "
                   "/etc/otto/secrets/higgsfield.json (owner otto, chmod 600) — or run ~/otto-launch-keys/push_secrets.py with "
                   "higgsfield-api.txt. Optional: \"quality\", \"scene_quality\", \"resolution\", \"max_images_day\", \"max_usd_day\", "
                   "\"max_images_per_brand_day\". Test: python3 otto_imagegen.py test (free), then test --live (one image, ≈ $0.014)."}


def status(as_json=False, out=print):
    cfg = config()
    day, last = usage_today()
    info = {"ready": ready(cfg), **{k: v for k, v in public(cfg).items()}, "today": day, "last": last,
            "ledger": str(ledger_path())}
    if as_json:
        out(json.dumps(info, ensure_ascii=False, indent=1))
        return info
    out(f"key: {'set (' + cfg['key_source'] + ')' if cfg['key_source'] else 'MISSING — ' + (cfg['error'] or 'no higgsfield.json')}"
        f" · {'on' if cfg['enabled'] else 'OFF'} · base {cfg['api_base']}")
    out(f"models: images {MODELS[cfg['image_model']]['label']} ({cfg['image_model']}, {cfg['resolution']} {cfg['quality']}) · "
        f"scenes {MODELS[cfg['scene_model']]['label']} ({cfg['scene_resolution']} {cfg['scene_quality']}) · gen {cfg['cli_quality']}")
    for w in cfg.get("warnings") or []:
        out("warning: " + w)
    out(f"today (UTC): {day.get('images', 0)} image(s), ≈ ${day.get('usd', 0):.2f}, {day.get('errors', 0)} error(s), "
        f"{day.get('nsfw', 0)} rejected · caps {cfg['max_images_day']} images / ${cfg['max_usd_day']:g} a day, "
        f"{cfg['max_images_per_brand_day']} per brand · parallel {cfg['parallel']}")
    for b, v in sorted((day.get("brands") or {}).items()):
        out(f"  {b:20} {v.get('images', 0):>3} image(s)  ≈ ${v.get('usd', 0):.2f}" + (f"  {v.get('errors')} error(s)" if v.get("errors") else ""))
    return info


# ============================================================================================ CLI

def _opt(a, name, default=None):
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def _opts(a, name):
    return [a[i + 1] for i, x in enumerate(a) if x == name and i + 1 < len(a)]


def main(argv):
    a = list(argv)
    cmd = a[0] if a else ""
    if cmd == "status":
        status("--json" in a)
        return 0
    cfg = config()
    if cmd in ("test", "gen", "estimate") and not ready(cfg):
        print("Higgsfield is not configured: " + (cfg["error"] or ("switched off" if cfg["key_id"] else
              f"no key (HIGGSFIELD_KEY or {secrets_dir() / 'higgsfield.json'})")))
        return 1
    try:
        if cmd == "test":
            m = canonical_model(_opt(a, "--model")) or cfg["image_model"]
            body = build_body(m, "A plain light-grey studio background, soft daylight, minimal still life", "1:1", "low", "1k")
            usd = estimate(cfg, m, body)
            print(f"key OK ({cfg['key_source']}) · {MODELS[m]['label']} ({m}) reachable · one 1k low square ≈ "
                  f"${usd if usd is not None else price_guess(m, '1:1', 'low', '1k'):.3f}"
                  + ("" if usd is not None else " (table price: the estimate gave no number)"))
            for q, r, asp in (("medium", cfg["resolution"], "3:4"), ("medium", cfg["scene_resolution"], "9:16"), ("high", "2k", "1:1")):
                if MODELS[m]["qualities"] and q in MODELS[m]["qualities"]:
                    try:
                        e = estimate(cfg, m, build_body(m, "x x", aspect_for(m, asp), q, r))
                    except ImageGenError:
                        e = None
                    print(f"  {r} {q} {asp}: ≈ ${e:.3f}" if e is not None else f"  {r} {q} {asp}: no estimate")
            if "--live" in a:
                t = time.time()
                paths = generate("A smooth matte ceramic sphere on a plain light-grey studio background, soft even daylight, "
                                 "minimal still life, no text", "1:1", model=m, quality="low", resolution="1k", brand="_test",
                                 purpose="test", cfg=cfg)
                for p in paths:
                    print(f"live OK · {p} · {p.stat().st_size:,} bytes · {round(time.time() - t, 1)} s")
            return 0
        if cmd == "gen":
            prompt = _opt(a, "--prompt") or (Path(_opt(a, "--prompt-file")).read_text() if _opt(a, "--prompt-file") else "")
            if not prompt.strip():
                print("gen needs --prompt \"…\" or --prompt-file <file>")
                return 2
            paths = generate(prompt, _opt(a, "--aspect", "1:1"), _opts(a, "--ref") or None, _opt(a, "--model"), _opt(a, "--out"),
                             _opt(a, "--quality"), _opt(a, "--resolution"), _opt(a, "--brand", "otto"), "cli", "--no-mark" not in a, cfg)
            for p in paths:
                print(p)
            return 0
        if cmd == "estimate":
            m = canonical_model(_opt(a, "--model")) or cfg["image_model"]
            n = int(_opt(a, "--refs", "0") or 0)
            asp = aspect_for(m, _opt(a, "--aspect", "1:1"))
            q = _opt(a, "--quality", "medium" if "medium" in MODELS[m]["qualities"] else None)
            body = build_body(m, "x x", asp, q, _opt(a, "--resolution", cfg["resolution"]),
                              ["https://cdn.higgsfield.ai/ref.png"] * n if n else None)
            usd = estimate(cfg, m, body)
            print(f"{MODELS[m]['label']} {asp} {body.get('resolution', '')} {body.get('quality', '')}"
                  f"{f' + {n} ref(s)' if n else ''}: ≈ ${usd if usd is not None else price_guess(m, asp, q, body.get('resolution'), n):.3f}"
                  + ("" if usd is not None else " (table price)"))
            return 0
    except ImageGenError as e:
        print(f"{type(e).__name__}: {e}")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
