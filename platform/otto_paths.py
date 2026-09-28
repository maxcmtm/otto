#!/usr/bin/env python3
"""Otto media paths — where generated files live locally and where Meta/Telegram fetch them.

Local:  platform/assets/... (OTTO_ASSETS overrides the assets dir). data.json stores repo-relative
        paths ("assets/posts/hg-001.jpg").
Public: nginx serves /srv/pulse/otto/ as https://dash.monyflow.work/otto/ and cannot read the workspace,
        so every generated file is copied into the public assets dir right after it is written:
        OTTO_PUBLIC_ASSETS (env; empty string disables), default /srv/pulse/otto/assets when it exists.
media_url() is the only way the publisher / ads code turns a stored path into a URL: it returns a URL
only for a file that is actually public (copying it there first if needed) and raises AssetError
otherwise — never a relative path, never a URL that 404s at Meta.
"""
import os, shutil, subprocess, tempfile, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = Path(os.environ.get("OTTO_ASSETS") or HERE / "assets")
BASE = os.environ.get("OTTO_PUBLIC_BASE") or "https://dash.monyflow.work/otto/"
DEFAULT_PUBLIC = Path("/srv/pulse/otto/assets")
_http_ok = {}


class AssetError(Exception):
    pass


def public_dir():
    v = os.environ.get("OTTO_PUBLIC_ASSETS")
    if v is not None:
        return Path(v) if v.strip() else None
    return DEFAULT_PUBLIC if DEFAULT_PUBLIC.is_dir() else None


def rel_of(path):
    """Local file → "assets/…" path as stored in data.json."""
    path = Path(path).resolve()
    try:
        return "assets/" + path.relative_to(ASSETS.resolve()).as_posix()
    except ValueError:
        return path.relative_to(HERE.resolve()).as_posix()


def clean_rel(ref):
    rel = str(ref or "").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise AssetError(f"{ref!r} is not a repo-relative asset path")
    if not rel.startswith("assets/"):
        raise AssetError(f"{ref} is outside assets/ — only /otto/assets/ is public")
    return rel


def local_path(ref):
    rel = clean_rel(ref)
    return ASSETS / rel[len("assets/"):]


def _copy_atomic(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + dst.name + ".", dir=str(dst.parent))
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)                         # nginx never serves a half-written file
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def publish(path_or_rel):
    """Copy a generated file into the public assets dir (creating parents). Returns the public path,
    or None when this machine has no public dir (local dev)."""
    pd = public_dir()
    if pd is None:
        return None
    p = Path(path_or_rel)
    rel = rel_of(p) if p.is_absolute() else clean_rel(path_or_rel)
    src = local_path(rel)
    if not src.exists():
        raise AssetError(f"{rel} does not exist locally")
    dst = pd / rel[len("assets/"):]
    _copy_atomic(src, dst)
    return dst


def _http_exists(url, timeout=10):
    if url in _http_ok:
        return _http_ok[url]
    ok = False
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Otto/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = 200 <= r.status < 300
    except Exception:
        ok = False
    _http_ok[url] = ok
    return ok


def media_url(ref, base=BASE, verify=True):
    """Stored media reference → public https URL that Meta / Telegram can fetch.
    http(s) refs pass through. Relative refs must live under assets/ and be public: with a public dir on
    this machine the file must exist there (it is copied from the workspace if missing); without one the
    URL is checked with a HEAD request. verify=False (dry runs) only builds the URL."""
    if not ref:
        raise AssetError("no media")
    ref = str(ref).strip()
    if ref.startswith(("http://", "https://")):
        return ref
    rel = clean_rel(ref)
    url = base.rstrip("/") + "/" + rel
    if not verify:
        return url
    pd = public_dir()
    if pd is not None:
        pub = pd / rel[len("assets/"):]
        if not pub.exists() and local_path(rel).exists():
            publish(rel)
        if not pub.exists():
            raise AssetError(f"{rel} is not on the public host ({pub} missing and no local copy)")
        return url
    if not _http_exists(url):
        raise AssetError(f"{url} is not reachable — run deploy.sh or set OTTO_PUBLIC_ASSETS")
    return url


def sniff(data_or_path):
    """Real image/video type from magic bytes: jpeg | png | webp | gif | mp4 | None."""
    if isinstance(data_or_path, (bytes, bytearray)):
        head = bytes(data_or_path[:16])
    else:
        with open(data_or_path, "rb") as f:
            head = f.read(16)
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp":
        return "mp4"
    return None


EXT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif", "mp4": ".mp4"}


def ensure_jpeg(ref):
    """Instagram only takes JPEG. Returns a stored ref to a real .jpg (http refs pass through):
    a .png that is really JPEG bytes is copied to .jpg; anything else is re-encoded with ffmpeg."""
    if not ref or str(ref).startswith(("http://", "https://")):
        return ref
    src = local_path(ref)
    if src.suffix.lower() in (".jpg", ".jpeg") and src.exists() and sniff(src) == "jpeg":
        return clean_rel(ref)
    if not src.exists():
        if src.suffix.lower() in (".jpg", ".jpeg"):
            return clean_rel(ref)            # not local (already public only) — trust the name
        raise AssetError(f"{ref} is not JPEG and there is no local copy to convert")
    dst = src.with_suffix(".jpg")
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        if sniff(src) == "jpeg":
            shutil.copyfile(src, dst)
        else:
            ff = shutil.which("ffmpeg")
            if not ff:
                raise AssetError(f"{ref} is {sniff(src) or 'unknown'}; Instagram needs JPEG and ffmpeg is missing")
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise AssetError(f"JPEG conversion failed for {ref}: {r.stderr[-200:]}")
    rel = rel_of(dst)
    publish(rel)
    return rel
