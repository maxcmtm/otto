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
Unguessable names: generated media (assets/posts, assets/ads, assets/reels) are public so that Meta can fetch them, so their
names must not be guessable — a draft's image must not be visible to someone who counts post ids. Every producer names its
file with token_name(): "<stem>-<32 hex>.<ext>", the hex derived from the owning record's random 128-bit media token
(posts[].media_token / campaigns[].media_token, media_token() / record_token() create and keep it) and the stem, so each file
of a record has its own unguessable name that stays the same when it is re-rendered. publish() refuses a guessable name in
those dirs (legacy=True lets media_url() / ensure_jpeg() serve refs that data.json already holds, until
`otto_paths.py migrate-names --apply` renames them).

  otto_paths.py migrate-names [--apply]    # rename existing guessable media (local + public copies, sidecars) and update
                                           # data.json (ap.transaction) and brands/<id>/*.json; dry run by default
"""
import hashlib, json, os, re, secrets, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = Path(os.environ.get("OTTO_ASSETS") or HERE / "assets")
BASE = os.environ.get("OTTO_PUBLIC_BASE") or "https://dash.monyflow.work/otto/"
DEFAULT_PUBLIC = Path("/srv/pulse/otto/assets")
_http_ok = {}


class AssetError(Exception):
    pass


# ---------- unguessable names ----------

MEDIA_DIRS = ("posts", "ads", "reels")                      # generated media: never public under a guessable name
TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


def new_token():
    """128 random bits (hex)."""
    return secrets.token_hex(16)


def valid_token(t):
    return isinstance(t, str) and re.fullmatch(r"[0-9a-f]{32}", t) is not None


def has_token(name):
    """True when a file name carries a 128-bit hex token (token_name, or a name derived from one: a .jpg twin, a sidecar)."""
    return bool(TOKEN_RE.search(Path(str(name)).name))


def token_name(stem, ext, token=None):
    """The file name a generated file is written and published under: "<stem>-<32 hex><ext>". The hex is
    sha256(token:stem)[:32] of the owning record's media token, so a re-render of the same file keeps its name and one known
    URL says nothing about the record's other files. token=None → a fresh random token (a file with no record to keep it).
    A stem that already carries a token (a poster named after its video) is kept as it is."""
    stem = str(stem)
    if has_token(stem):
        return f"{stem}{ext}"
    token = token if valid_token(token) else new_token()
    return f"{stem}-{hashlib.sha256(f'{token}:{stem}'.encode()).hexdigest()[:32]}{ext}"


def record_token(rec, fallback=None):
    """The record's media token (rec["media_token"]), else `fallback` (a token kept elsewhere, e.g. in the record's
    creatives), else a new one — set on rec, which the caller saves."""
    t = rec.get("media_token") if isinstance(rec, dict) else None
    if not valid_token(t):
        t = fallback if valid_token(fallback) else new_token()
        if isinstance(rec, dict):
            rec["media_token"] = t
    return t


def media_token(kind, ident):
    """posts[ident] / campaigns[ident] (kind "post" | "campaign") media token, created and saved in data.json on first use
    (one short ap.transaction). A record that does not exist gets a fresh token that is not stored."""
    import ap
    find = ap.post if kind == "post" else ap.campaign
    try:
        rec = find(ap.load(), ident)
    except (OSError, ValueError):                    # no data.json (a demo render): unguessable, just not kept
        return new_token()
    if rec is None:
        return new_token()
    if valid_token(rec.get("media_token")):
        return rec["media_token"]
    with ap.transaction() as d:
        rec = find(d, ident)
        return record_token(rec) if rec is not None else new_token()


def guessable(rel):
    """True for a generated-media path (assets/posts|ads|reels/…) whose name has no token."""
    parts = Path(rel).parts
    return len(parts) >= 3 and parts[0] == "assets" and parts[1] in MEDIA_DIRS and not has_token(parts[-1])


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


def publish(path_or_rel, legacy=False):
    """Copy a generated file into the public assets dir (creating parents). Returns the public path,
    or None when this machine has no public dir (local dev). The single publish point: a file under assets/posts, ads or
    reels must carry a token in its name (token_name) — AssetError otherwise, on every machine. legacy=True serves a
    ref data.json already holds (media_url / ensure_jpeg) until migrate-names renames it."""
    pd = public_dir()
    p = Path(path_or_rel)
    try:
        rel = rel_of(p) if p.is_absolute() else clean_rel(path_or_rel)
    except (ValueError, AssetError):
        if pd is None:                               # local dev: nothing is made public, as before
            return None
        raise
    if not legacy and guessable(rel):
        raise AssetError(f"{rel}: a generated file is never made public under a guessable name — name it with "
                         "otto_paths.token_name()")
    if pd is None:
        return None
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
            publish(rel, legacy=True)                # a stored ref: served as it is until migrate-names renames it
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
            try:                                     # re-encoding drops metadata: an AI-marked source stays marked
                import otto_provenance
                otto_provenance.propagate(src, dst, composite=None)
            except Exception:                        # noqa: BLE001 — never block a publish on the provenance helper
                pass
    rel = rel_of(dst)
    publish(rel, legacy=True)                        # the .jpg twin of a stored ref keeps its (tokenized) stem
    return rel


# ---------- one-off: rename media published under guessable names (before token_name existed) ----------

REF_RE = re.compile(r"^assets/(?:posts|ads|reels)/[^/]+$")
STATIC_REF = re.compile(r"assets/[A-Za-z0-9_@%./-]+")


def _strings(x):
    """Every string in a JSON document, dict keys included."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _remap(x, m):
    """A copy of a JSON document with every string (and dict key) that is a key of m replaced by its value."""
    if isinstance(x, str):
        return m.get(x, x)
    if isinstance(x, dict):
        return {(m.get(k, k) if isinstance(k, str) else k): _remap(v, m) for k, v in x.items()}
    if isinstance(x, list):
        return [_remap(v, m) for v in x]
    return x


def _static_refs():
    """assets/… paths the pages shipped with the release use (the landing's demo reel, …): never renamed."""
    out = set()
    for f in HERE.glob("*.html"):
        try:
            out.update(STATIC_REF.findall(f.read_text(errors="replace")))
        except OSError:
            pass
    return out


def _as_ref(s, base):
    """A stored string → the generated-media ref it names (relative, or a URL on our public base), else None."""
    if base and s.startswith(base):
        s = s[len(base):]
    return s if REF_RE.match(s) else None


def migration_plan(d=None, base=None):
    """What migrate-names would do. Every guessable ref in data.json is grouped with the files that share its name up to the
    first dot (the file, its .jpg / .png twin, its .provenance.json sidecar) in the local and the public dir; the group gets
    token_name(<that head>) with the owning post's / campaign's media token (a new one is recorded when it has none), which
    is the name the producers would give the same file now. → {"renames": [{ref, to, owner}], "moves": [(old, new)],
    "tokens": {(kind, id): token}, "skipped": [{ref, why}], "unreferenced": [public guessable files no data.json ref names]}"""
    import ap
    d = ap.load() if d is None else d
    base = BASE if base is None else base
    pd = public_dir()
    static = _static_refs()
    owners, tokens = {}, {}
    for kind, key in (("post", "posts"), ("campaign", "campaigns")):
        for rec in d.get(key) or []:
            if not (isinstance(rec, dict) and isinstance(rec.get("id"), str)):
                continue
            if valid_token(rec.get("media_token")):
                tokens[(kind, rec["id"])] = rec["media_token"]
            for s in _strings(rec):
                r = _as_ref(s, base)
                if r:
                    owners.setdefault(r, (kind, rec["id"]))
    refs = sorted({r for r in (_as_ref(s, base) for s in _strings(d)) if r and guessable(r)})
    heads, renames, skipped, moves = {}, [], [], {}
    roots = [x for x in (ASSETS, pd) if x is not None]
    for ref in refs:
        if ref in static:
            skipped.append({"ref": ref, "why": "used by a page shipped with the release"})
            continue
        folder_rel = Path(ref).parent.relative_to("assets")
        head, dot, tail = Path(ref).name.partition(".")
        group = (folder_rel.as_posix(), head)
        if group not in heads:
            present = [r / folder_rel / f.name for r in roots if (r / folder_rel).is_dir()
                       for f in (r / folder_rel).iterdir() if f.is_file() and f.name.partition(".")[0] == head]
            if not present:
                skipped.append({"ref": ref, "why": "no local or public copy"})
                continue
            owner = owners.get(ref)
            tok = tokens.setdefault(owner, new_token()) if owner else new_token()
            heads[group] = new_head = token_name(head, "", tok)
            for f in present:
                moves.setdefault(f, f.with_name(new_head + f.name[len(head):]))
        renames.append({"ref": ref, "to": (Path("assets") / folder_rel / (heads[group] + dot + tail)).as_posix(),
                        "owner": list(owners[ref]) if ref in owners else None})
    named = {r for r in (_as_ref(s, base) for s in _strings(d)) if r}
    unref = []
    if pd is not None:
        for sub in MEDIA_DIRS:
            if (pd / sub).is_dir():
                unref += [f"assets/{sub}/{f.name}" for f in sorted((pd / sub).iterdir()) if f.is_file() and not has_token(f.name)
                          and f"assets/{sub}/{f.name}" not in named and f"assets/{sub}/{f.name}" not in static
                          and Path(f) not in moves]
    used = {tuple(r["owner"]) for r in renames if r["owner"]}
    return {"renames": renames, "moves": sorted(moves.items()), "skipped": skipped, "unreferenced": unref,
            "tokens": {k: v for k, v in tokens.items() if k in used}}


def migrate(apply=False, base=None, out=print):
    """migrate-names: dry by default (prints the plan). --apply: new names are linked next to the old ones (local and
    public), data.json refs (relative and full public URLs, dict keys included — post.media_ai) and missing media tokens are
    written in one ap.transaction, brands/<id>/*.json that name an old ref are rewritten, then the old names are removed.
    A reader never finds a ref without its file. Safe to re-run: nothing guessable left means nothing to do."""
    import ap
    base = BASE if base is None else base
    plan = migration_plan(base=base)
    for r in plan["renames"]:                     # a dry run names the token <token>: --apply draws the real one
        to = r["to"] if apply else TOKEN_RE.sub("<token>", r["to"])
        out(f"{'RENAME' if apply else 'would rename'} {r['ref']} → {to}" + (f"  ({r['owner'][0]} {r['owner'][1]})" if r["owner"] else ""))
    for s in plan["skipped"]:
        out(f"  kept {s['ref']}: {s['why']}")
    for u in plan["unreferenced"]:
        out(f"  not referenced by data.json, left as it is (remove it by hand if nothing uses it): {u}")
    out(f"-- {len(plan['renames'])} refs, {len(plan['moves'])} files" + ("" if apply else " (dry run: --apply renames them)"))
    if not apply or not plan["renames"]:
        return plan
    for old, new in plan["moves"]:
        if not new.exists():
            try:
                os.link(old, new)
            except OSError:
                shutil.copy2(old, new)
    mapping = {}
    for r in plan["renames"]:
        mapping[r["ref"]] = r["to"]
        if base:
            mapping[base + r["ref"]] = base + r["to"]
    with ap.transaction() as d:
        for (kind, ident), tok in plan["tokens"].items():
            rec = (ap.post if kind == "post" else ap.campaign)(d, ident)
            if rec is not None and not valid_token(rec.get("media_token")):
                rec["media_token"] = tok
        new = _remap(d, mapping)
        d.clear()
        d.update(new)
    for f in sorted(Path(ap.BRANDS).glob("*/*.json")):
        try:
            doc = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if any(s in mapping for s in _strings(doc)):
            ap._atomic_write(f, json.dumps(_remap(doc, mapping), ensure_ascii=False, indent=2) + "\n")
            out(f"  updated {f}")
    for old, new in plan["moves"]:
        if new.exists() and old.exists():
            old.unlink()
    try:
        with (ap.DATA.parent / "actions.log").open("a") as f:
            f.write(f"{ap.now_iso()} paths migrate-names {len(plan['renames'])} refs {len(plan['moves'])} files\n")
    except OSError:
        pass
    return plan


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["migrate-names"]:
        migrate(apply="--apply" in a)
    else:
        print(__doc__)
