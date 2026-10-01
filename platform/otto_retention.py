#!/usr/bin/env python3
"""Otto data retention — a client brand's data is deleted 90 days after its plan ended (Terms 17.3, DPA 9.2, Privacy Policy
"How long we keep data"), and scanned-domain leads after OTTO_LEAD_RETENTION_DAYS without activity.

  otto_retention.py plan [--json] [--today YYYY-MM-DD]   # dry: every brand whose plan ended — its timeline, the notices, and
                                                          # what would be deleted and when; exports and leads due for pruning
  otto_retention.py run [--today YYYY-MM-DD]             # the daily job (otto_cron "retention", 04:40 owner time)
  otto_retention.py hold <brand> [--note "…"]            # brands[].retention_hold = true: never deleted while it is set
  otto_retention.py release <brand> [--note "…"]         # clears it; both notices go out again before any deletion
  otto_retention.py export <brand>                       # the brand's content as a zip in OTTO_EXPORTS now (Terms 17.2)
  otto_retention.py restore <zip> [--apply]              # put an exported brand back (a returning client); dry by default

Timeline. A plan ends when the brand moves to plans.json defaults.ended ("none": a canceled / unpaid subscription, the
owner console, or a free trial that ended without a card): the date of that brands[].plan_history entry (UTC) — its
"effective" date when it names one (otto_trial: the trial's end, whenever the hourly job got to it). A brand found on
"none" without such an entry counts from the day this job first saw it (brands[].retention.source "first_seen"). delete_on = ended + 90 days. Owner notices 14 and 3
days before: an owner recommendation (never shown to the client), a Telegram message to the owner chat (otto_telegram) and an
e-mail to OTTO_OWNER_EMAIL, else the OTTO_ADMIN_USERS addresses (otto_email: its transport, or the outbox) — each when
configured. A deletion never comes sooner than 3 days after the 3-day notice (a brand already past its date when this job
first sees it gets the notice and is deleted 3 days later). A plan that starts again (a subscription, the console) stops it and clears
the state. brands[].retention_hold (truthy, e.g. a legal dispute) stops the notices and the deletion; `release` restarts the
notices. brands[].retention = {ended, source, delete_on, notices: {"14": day, "3": day}} is the job's memory.

Deletion of one brand. First an export: otto-export-<id>-<UTC stamp>.zip in OTTO_EXPORTS (default exports/ next to data.json,
dir 700, file 600): manifest.json, data.json (the brand record and every record of it), brand/ (brands/<id>/), media/ (its
images, ad statics, reels, scanned site images). No secrets, no billing. Kept 30 days, then this job removes it (infra/backup.sh
leaves exports/ out of the backups). Then, in one data.json transaction that first checks the plan is still ended and not held,
the records go and the list of files to remove is written to .retention-journal.json next to data.json; the files follow and
the journal entry is dropped (a crash resumes from the journal on the next run):
- data.json: the brand and every record of it — posts, campaigns, recommendations, taste_log, edit_requests, connections
  (meta-<id>, tg-<id>, … and legacy ones by the brand's name), the brand's key in metrics / ads / competitors / growth (any
  top-level object keyed by brand id), every other top-level list's entries with "brand": <id>, seq prefix:<id>; and the
  Google sign-in account (users[], otto_auth) that created it once it has no other brand (its sessions stop working; the
  trial ledger keeps only hashes);
- files: brands/<id>/; its media in OTTO_ASSETS and in the public dir (with .jpg / .png twins and .provenance.json sidecars,
  and every file named after one of its posts or campaigns) unless another brand's record or a page shipped with the release
  names the same file; reels/<post>/ scene caches; assets/site/<id>/; motion projects <id>-<post>; its per-brand secrets
  (<service>-<id>.json in OTTO_SECRETS: meta-, google-, …; never Otto's own google-oauth.json); its e-mails in the outbox;
- its lead: the brand's own domain in leads.json, and in the scan events of events.jsonl (the event stays, without the domain);
  its per-brand entries in .email-state.json, .report-state.json and heartbeats.json; its figures in metrics_history.jsonl;
- actions.log keeps every line (who did what, when) with its content stripped (note=…, ip=…).
Kept: billing.json (tax law: the Privacy Policy's billing period), the audit lines, the export for 30 days; backups roll over.
Every deletion appends "retention delete <id> …" to actions.log and files an owner recommendation.

Leads. A scanned domain (leads.json "d:<domain>" and the domain in the scan events) or a clicked-through visitor ("v:…") with
no activity — a scan, or the owner's status / note — for OTTO_LEAD_RETENTION_DAYS (default 730: the Privacy Policy's 24 months)
is removed from leads.json, and the domain is stripped from its scan events.

Paths are read when used: OTTO_DATA, OTTO_BRANDS, OTTO_ASSETS / OTTO_PUBLIC_ASSETS (otto_paths), OTTO_SECRETS, OTTO_EXPORTS,
OTTO_EVENTS, OTTO_LEADS, OTTO_HEARTBEATS, OTTO_OUTBOX, OTTO_EMAIL_STATE, OTTO_REPORT_STATE, OTTO_MOTION_ROOT. Exit: 0 ok · 1 something failed
(an unreadable plans.json deletes nothing and sends nothing) · 2 usage. Stdlib only; every data.json write goes through
ap.transaction().
"""
import copy, fcntl, html, json, os, re, shutil, sys, tempfile, zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_paths as paths

HERE = Path(__file__).resolve().parent
RETENTION_DAYS = 90
NOTICES = ("14", "3")                          # days before delete_on
EXPORT_KEEP_DAYS = 30
LEAD_DAYS_DEFAULT = 730
FORMAT = "otto-brand-export/1"
EXPORT_RE = re.compile(r"^otto-export-[A-Za-z0-9_.-]+-(\d{8})T\d{6}Z\.zip$")
ASSET_REF = re.compile(r"^assets/[A-Za-z0-9_@%.+/-]+$")
STRIP = re.compile(r' (note|ip)=("(?:[^"\\]|\\.)*"|\S+)')
SYSTEM_SECRETS = {"google-oauth.json"}         # Otto's own Google sign-in client, never a brand's token file (brand "oauth")


# ---------------------------------------------------------------- paths (read when used: tests and the server set them)

def _env_path(name, default):
    return Path(os.environ.get(name) or default)


def exports_dir():
    return _env_path("OTTO_EXPORTS", ap.DATA.parent / "exports")


def secrets_dir():
    return _env_path("OTTO_SECRETS", HERE.parent.parent / "otto-secrets")


def leads_path():
    return _env_path("OTTO_LEADS", ap.DATA.parent / "leads.json")


def events_path():
    return _env_path("OTTO_EVENTS", ap.DATA.parent / "events.jsonl")


def heartbeats_path():
    return _env_path("OTTO_HEARTBEATS", ap.DATA.parent / "heartbeats.json")


def outbox_dir():
    return _env_path("OTTO_OUTBOX", ap.DATA.parent / "outbox")


def email_state_path():
    return _env_path("OTTO_EMAIL_STATE", ap.DATA.parent / ".email-state.json")


def report_state_path():
    return _env_path("OTTO_REPORT_STATE", ap.DATA.parent / ".report-state.json")


def motion_root():
    return _env_path("OTTO_MOTION_ROOT", HERE.parent / "motion")


def actions_log():
    return ap.DATA.parent / "actions.log"


def journal_path():
    return ap.DATA.parent / ".retention-journal.json"


def history_path():
    return ap.DATA.parent / "metrics_history.jsonl"


def lead_days():
    try:
        n = int(os.environ.get("OTTO_LEAD_RETENTION_DAYS") or LEAD_DAYS_DEFAULT)
    except ValueError:
        n = LEAD_DAYS_DEFAULT
    return n if n > 0 else LEAD_DAYS_DEFAULT


def utcnow():
    return datetime.now(timezone.utc)


@contextmanager
def _flock(path):
    """Exclusive flock on <path>.lock — the lock the file's owner uses (leads.json, heartbeats.json)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _read_json(path, default):
    try:
        x = json.loads(Path(path).read_text())
        return x if isinstance(x, type(default)) else default
    except (OSError, ValueError):
        return default


def audit(line):
    """One actions.log line (never raises: the change it records has happened)."""
    try:
        actions_log().parent.mkdir(parents=True, exist_ok=True)
        with actions_log().open("a") as f:
            f.write(f"{ap.now_iso()} retention {line}\n")
    except OSError as e:
        print(f"retention: actions.log not written ({type(e).__name__})", file=sys.stderr)


# ---------------------------------------------------------------- timeline

def _day(v):
    """An ISO date / datetime → a date (UTC), else None."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    dt = ap.parse_iso(v) if isinstance(v, str) else None
    if dt is not None:
        return (dt.astimezone(timezone.utc) if dt.tzinfo else dt).date()
    return None


def ended_plan():
    return ap.plans_config()["defaults"]["ended"]


def on_ended_plan(b, ended):
    raw = (b or {}).get("plan")
    return isinstance(raw, str) and raw.strip() == ended


def ended_on(b, ended):
    """(date the plan ended, source): the latest plan_history entry when it is the move to the ended plan, else the day this
    job first saw the brand there (brands[].retention.ended), else (None, "first_seen") — the caller uses today."""
    hist = [h for h in (b.get("plan_history") or []) if isinstance(h, dict)]
    if hist and hist[-1].get("to") == ended:
        day = _day(hist[-1].get("effective")) or _day(hist[-1].get("at"))
        if day:
            return day, "plan_history"
    st = b.get("retention") if isinstance(b.get("retention"), dict) else {}
    day = _day(st.get("ended")) if st.get("source") == "first_seen" else None
    return day, "first_seen"


def timeline(b, today, ended=None):
    """Where one brand stands. state: "active" (its plan runs: nothing happens) · "held" (retention_hold) · "counting" ·
    due: None | "notice-14" | "notice-3" | "delete". effective = the day it is deleted (delete_on, or 3 days after a late
    3-day notice)."""
    ended = ended or ended_plan()
    out = {"brand": b.get("id"), "name": b.get("name") or b.get("id"), "held": bool(b.get("retention_hold"))}
    if not on_ended_plan(b, ended):
        out.update(state="active", due=None)
        return out
    day, source = ended_on(b, ended)
    if day is None:
        day = today
    delete_on = day + timedelta(days=RETENTION_DAYS)
    st = b.get("retention") if isinstance(b.get("retention"), dict) else {}
    sent = {k: _day(v) for k, v in (st.get("notices") or {}).items() if k in NOTICES and _day(v)}
    if st.get("ended") and st.get("ended") != day.isoformat():
        sent = {}                                        # notices of an earlier end (renewed and ended again): not this one
    n3 = sent.get("3")
    effective = max(delete_on, (n3 or today) + timedelta(days=3))
    due = None
    if not out["held"]:
        if n3 and today >= effective:
            due = "delete"
        elif not n3 and today >= delete_on - timedelta(days=3):
            due = "notice-3"
        elif not n3 and "14" not in sent and today >= delete_on - timedelta(days=14):
            due = "notice-14"
    out.update(state="held" if out["held"] else "counting", due=due, ended=day.isoformat(), source=source,
               delete_on=delete_on.isoformat(), effective=effective.isoformat(),
               notice_14=(delete_on - timedelta(days=14)).isoformat(), notice_3=(delete_on - timedelta(days=3)).isoformat(),
               sent={k: v.isoformat() for k, v in sent.items()}, days_left=(effective - today).days)
    return out


# ---------------------------------------------------------------- what belongs to a brand

def _conn_of(c, bid, names, all_ids):
    """A connection record of this brand: "meta-<id>", "tg-<id>" …, or a legacy one named after the brand (otto_api.client_view)."""
    own = str(c.get("id") or "").split("-", 1)[-1]
    return own == bid or (own not in all_ids and str(c.get("brand") or "").strip().lower() in names)


def brand_slice(d, bid):
    """Every record of one brand in data.json (references into d, not copies): {"brand", "lists": {key: [records]},
    "keyed": {key: value}, "seq": {key: value}}. None when the brand does not exist."""
    b = ap.brand(d, bid)
    if b is None:
        return None
    names = {str(b.get("name") or "").strip().lower()} - {""}
    all_ids = {x.get("id") for x in d.get("brands") or [] if isinstance(x, dict)}
    post_ids = {p.get("id") for p in d.get("posts") or [] if isinstance(p, dict) and p.get("brand") == bid and p.get("id")}
    lists, keyed = {}, {}
    for k, v in d.items():
        if k == "brands":
            continue
        if isinstance(v, list):
            if k == "connections":
                sel = [c for c in v if isinstance(c, dict) and _conn_of(c, bid, names, all_ids)]
            elif k == "edit_requests":
                sel = [e for e in v if isinstance(e, dict) and (e.get("brand") == bid or e.get("post") in post_ids)]
            else:
                sel = [x for x in v if isinstance(x, dict) and x.get("brand") == bid]
            if sel:
                lists[k] = sel
        elif isinstance(v, dict) and k != "seq" and bid in v:
            keyed[k] = v[bid]
    seq = {k: v for k, v in (d.get("seq") or {}).items() if k == f"prefix:{bid}"}
    return {"brand": b, "lists": lists, "keyed": keyed, "seq": seq}


def purge_records(d, bid):
    """Remove one brand and every record of it from d (in place). → {collection: n removed}."""
    sl = brand_slice(d, bid)
    if sl is None:
        return {}
    counts = {"brands": 1}
    d["brands"] = [x for x in d.get("brands") or [] if x is not sl["brand"]]
    for k, recs in sl["lists"].items():
        ids = {id(x) for x in recs}
        d[k] = [x for x in d[k] if id(x) not in ids]
        counts[k] = len(recs)
    for k in sl["keyed"]:
        d[k].pop(bid, None)
        counts[k] = counts.get(k, 0) + 1
    for k in sl["seq"]:
        d["seq"].pop(k, None)
    live = {x.get("id") for x in d.get("brands") or [] if isinstance(x, dict)}
    users, gone = [], 0
    for u in d.get("users") or []:                  # the sign-in account that created it (otto_trial), once it has no brand left
        if isinstance(u, dict) and bid in (u.get("brands") or []):
            u["brands"] = [x for x in u["brands"] if x != bid]
            if not [x for x in u["brands"] if x in live] and not ap.member_brands(d, u.get("email")):
                gone += 1
                continue
        users.append(u)
    if gone:
        d["users"] = users
        counts["users"] = gone
    return counts


def _refs(doc, base):
    """assets/… refs named anywhere in a JSON document (relative, or a URL on our public base)."""
    out = set()
    for s in paths._strings(doc):
        if base and s.startswith(base):
            s = s[len(base):]
        if ASSET_REF.match(s) and ".." not in s.split("/"):
            out.add(s)
    return out


def _item_ids(sl):
    ids = set()
    for recs in sl["lists"].values():
        ids.update(x.get("id") for x in recs if isinstance(x.get("id"), str) and x.get("id"))
    return ids


def brand_domains(b):
    """The brand's own site domain(s) — its lead."""
    try:
        import otto_admin
        dom = otto_admin.base_domain(otto_admin.host_of(b.get("url")))
    except Exception:
        dom = None
    return sorted({dom} - {None, ""})


def inventory(d, bid):
    """What deleting `bid` removes, from data.json d and the disk: {"slice", "counts", "files", "dirs", "secrets", "outbox",
    "domains", "item_ids", "kept_shared"}. Files another brand's record or a shipped page names are kept (kept_shared)."""
    sl = brand_slice(d, bid)
    if sl is None:
        return None
    base = paths.BASE
    rest = copy.deepcopy(d)
    purge_records(rest, bid)
    other = _refs(rest, base) | paths._static_refs()
    mine = _refs(sl, base)
    pd = paths.public_dir()
    roots = [r for r in (paths.ASSETS, pd) if r is not None]
    post_ids = sorted(x["id"] for x in sl["lists"].get("posts", []) if isinstance(x.get("id"), str))
    camp_ids = sorted(x["id"] for x in sl["lists"].get("campaigns", []) if isinstance(x.get("id"), str))
    other_heads = {(Path(r).parent.as_posix(), Path(r).name.partition(".")[0]) for r in other}
    files, kept = set(), sorted(mine & other)
    heads = {(Path(r).parent.as_posix(), Path(r).name.partition(".")[0]) for r in mine - other}
    own_name = [re.compile(rf"^{re.escape(p)}(-\d+)?(-[0-9a-f]{{32}})?$") for p in post_ids] + \
               [re.compile(rf"^{re.escape(c)}-") for c in camp_ids]
    for r in roots:
        for sub in paths.MEDIA_DIRS:
            folder = r / sub
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if not f.is_file():
                    continue
                head = f.name.partition(".")[0]
                key = (f"assets/{sub}", head)
                if key in other_heads:
                    continue
                if key in heads or any(rx.match(head) for rx in own_name):
                    files.add(f)
        for ref in mine - other:                       # anything else it names under assets/ (site images, …)
            rel = ref[len("assets/"):]
            if rel.split("/", 1)[0] in paths.MEDIA_DIRS:
                continue
            f = r / rel
            if f.is_file():
                files.add(f)
    dirs = set()
    for r in roots:
        dirs.update(r / "reels" / pid for pid in post_ids if (r / "reels" / pid).is_dir())
        if (r / "site" / bid).is_dir():
            dirs.add(r / "site" / bid)
    dirs.update(motion_root() / f"{bid}-{pid}" for pid in post_ids if (motion_root() / f"{bid}-{pid}").is_dir())
    if (Path(ap.BRANDS) / bid).is_dir():
        dirs.add(Path(ap.BRANDS) / bid)
    files = {f for f in files if not any(f.is_relative_to(x) for x in dirs)}
    sd = secrets_dir()
    secret_re = re.compile(rf"^[a-z]+-{re.escape(bid)}\.json$")
    secrets_ = sorted(f for f in sd.iterdir() if f.is_file() and secret_re.match(f.name) and f.name not in SYSTEM_SECRETS) \
        if sd.is_dir() else []
    ob = outbox_dir()
    ob_re = re.compile(rf"^\d{{8}}T\d{{6}}-{re.escape(re.sub(r'[^a-z0-9-]', '', bid)[:40])}-[a-z]+-[0-9a-f]{{8}}-[0-9a-f]{{4}}\.eml$")
    outbox = sorted(f for f in ob.iterdir() if f.is_file() and ob_re.match(f.name)) if ob.is_dir() else []
    counts = {"records": {k: len(v) for k, v in sl["lists"].items()}, "keyed": sorted(sl["keyed"])}
    return {"slice": sl, "counts": counts, "files": sorted(files), "dirs": sorted(dirs), "secrets": secrets_, "outbox": outbox,
            "domains": brand_domains(sl["brand"]), "item_ids": sorted(_item_ids(sl)), "kept_shared": kept}


# ---------------------------------------------------------------- export / restore

def _stamp(now=None):
    return (now or utcnow()).strftime("%Y%m%dT%H%M%SZ")


def export(bid, d=None, reason="request", now=None):
    """The brand's content as a zip in OTTO_EXPORTS (dir 700, file 600) → its Path. Media are read from the local assets
    dir, else the public copy. Raises KeyError for an unknown brand."""
    d = ap.load() if d is None else d
    inv = inventory(d, bid)
    if inv is None:
        raise KeyError(bid)
    sl = inv["slice"]
    out_dir = exports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass
    now = now or utcnow()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", bid) or "brand"
    dst = out_dir / f"otto-export-{safe}-{_stamp(now)}.zip"
    media = []
    pd = paths.public_dir()
    for ref in sorted(_refs(sl, paths.BASE)):
        try:
            src = paths.local_path(ref)
        except paths.AssetError:
            continue
        if not src.is_file() and pd is not None:
            src = pd / ref[len("assets/"):]
        if src.is_file():
            media.append((ref, src))
    for r in [x for x in (paths.ASSETS, pd) if x is not None]:
        site = r / "site" / bid
        if site.is_dir():
            media += [(f"assets/site/{bid}/{f.relative_to(site).as_posix()}", f) for f in sorted(site.rglob("*")) if f.is_file()]
    seen = set()
    media = [m for m in media if not (m[0] in seen or seen.add(m[0]))]
    brand_dir = Path(ap.BRANDS) / bid
    brand_files = sorted(f for f in brand_dir.rglob("*") if f.is_file()) if brand_dir.is_dir() else []
    data = {"brand": sl["brand"], "lists": sl["lists"], "keyed": sl["keyed"], "seq": sl["seq"]}
    manifest = {"format": FORMAT, "brand": bid, "name": sl["brand"].get("name"), "reason": reason,
                "exported_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "plan": sl["brand"].get("plan"),
                "records": {k: len(v) for k, v in sl["lists"].items()}, "keyed": sorted(sl["keyed"]),
                "brand_files": [f.relative_to(brand_dir).as_posix() for f in brand_files], "media": [m[0] for m in media],
                "not_included": "secrets (access tokens: a returning client connects Meta / Google again), billing records "
                                "(kept separately), motion project sources, reel scene caches, logs",
                "restore": f"python3 otto_retention.py restore {dst.name} --apply"}
    fd, tmp = tempfile.mkstemp(prefix=".otto-export-", suffix=".zip", dir=str(out_dir))
    os.close(fd)
    try:
        os.chmod(tmp, 0o600)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            z.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=1))
            for f in brand_files:
                z.write(f, "brand/" + f.relative_to(brand_dir).as_posix())
            for ref, src in media:
                z.write(src, "media/" + ref, compress_type=zipfile.ZIP_STORED)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dst


def _safe_member(name):
    parts = Path(name).parts
    return bool(parts) and not Path(name).is_absolute() and ".." not in parts and "\\" not in name


def restore(zpath, apply=False, out=print):
    """An export → back into data.json, brands/<id>/ and the assets (published again). Refuses when the brand exists; records
    whose id is taken meanwhile are skipped and listed. Dry by default. → summary dict."""
    zpath = Path(zpath)
    if not zpath.is_file() and (exports_dir() / zpath.name).is_file():
        zpath = exports_dir() / zpath.name
    with zipfile.ZipFile(zpath) as z:
        man = json.loads(z.read("manifest.json"))
        if man.get("format") != FORMAT:
            raise ValueError(f"{zpath.name} is not an Otto brand export ({man.get('format')!r})")
        sl = json.loads(z.read("data.json"))
        bid = man["brand"]
        names = [n for n in z.namelist() if not n.endswith("/")]
        bad = [n for n in names if not _safe_member(n)]
        if bad:
            raise ValueError(f"unsafe paths in the zip: {bad[:3]}")
        d = ap.load()
        if ap.brand(d, bid) is not None:
            raise ValueError(f"{bid} exists in data.json — nothing restored (rename or delete it first)")
        taken = {k: sorted(x.get("id") for x in recs if x.get("id") and any(
            isinstance(y, dict) and y.get("id") == x.get("id") for y in d.get(k) or [])) for k, recs in sl["lists"].items()}
        summary = {"brand": bid, "records": {k: len(v) for k, v in sl["lists"].items()}, "taken": {k: v for k, v in taken.items() if v},
                   "brand_files": sum(1 for n in names if n.startswith("brand/")), "media": sum(1 for n in names if n.startswith("media/"))}
        out(f"{'RESTORE' if apply else 'would restore'} {bid} from {zpath.name}: " +
            ", ".join(f"{v} {k}" for k, v in summary["records"].items()) + f", {summary['brand_files']} brand files, "
            f"{summary['media']} media" + (f" · skipped (id taken): {summary['taken']}" if summary["taken"] else ""))
        if not apply:
            return summary
        media = []
        for n in names:
            if n.startswith("brand/"):
                root, rel = Path(ap.BRANDS) / bid, n[len("brand/"):]
            elif n.startswith("media/assets/"):
                paths.clean_rel(n[len("media/"):])
                root, rel = paths.ASSETS, n[len("media/assets/"):]
                media.append(n[len("media/"):])
            else:
                continue
            dst = root / rel
            if not dst.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"{n} leaves {root}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(n))
    with ap.transaction() as d:
        if ap.brand(d, bid) is not None:
            raise ValueError(f"{bid} appeared in data.json meanwhile — data not restored (the files are back)")
        b = dict(sl["brand"])
        b.pop("retention", None)
        b["plan_history"] = (b.get("plan_history") or [])[-19:] + [{
            "at": ap.now_iso(), "by": "retention", "via": "restore", "from": b.get("plan"), "to": b.get("plan"),
            "until": b.get("plan_until"), "note": f"restored from {zpath.name}"}]
        d.setdefault("brands", []).append(b)
        for k, recs in sl["lists"].items():
            have = {y.get("id") for y in d.get(k) or [] if isinstance(y, dict)}
            d.setdefault(k, []).extend(x for x in recs if not x.get("id") or x.get("id") not in have)
        for k, v in sl["keyed"].items():
            if isinstance(d.get(k, {}), dict):
                d.setdefault(k, {}).setdefault(bid, v)
        for k, v in (sl.get("seq") or {}).items():
            d.setdefault("seq", {}).setdefault(k, v)
    for ref in media:
        if ref.split("/")[1] in paths.MEDIA_DIRS:
            try:
                paths.publish(ref, legacy=True)
            except paths.AssetError as e:
                out(f"  not public: {e}")
    audit(f"restore {bid} from {zpath.name}")
    return summary


def prune_exports(today, apply=True):
    """Exports older than EXPORT_KEEP_DAYS (by the stamp in the name) → removed. → names."""
    out, d = [], exports_dir()
    if not d.is_dir():
        return out
    cut = today - timedelta(days=EXPORT_KEEP_DAYS)
    for f in sorted(d.iterdir()):
        m = EXPORT_RE.match(f.name)
        if f.is_file() and m and datetime.strptime(m.group(1), "%Y%m%d").date() < cut:
            out.append(f.name)
            if apply:
                f.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------- notices

def owner_emails():
    raw = os.environ.get("OTTO_OWNER_EMAIL") or os.environ.get("OTTO_ADMIN_USERS") or ""
    return [e for e in (x.strip().lower() for x in raw.split(",")) if ap.EMAIL.fullmatch(e)]


def notify_owner(subject, text, bid):
    """Telegram (the owner chat) and e-mail (owner addresses) when configured. Never raises. → channels used."""
    used = []
    try:
        import otto_telegram
        tok, chat = otto_telegram.config()
        if tok and chat:
            otto_telegram.send(f"{subject}\n\n{text}")
            used.append("telegram")
    except Exception as e:                                      # noqa: BLE001 — a notice never stops the job
        print(f"  telegram notice failed: {type(e).__name__}", file=sys.stderr)
    try:
        rcpts = owner_emails()
        if rcpts:
            import otto_email
            body = "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"
            for to in rcpts:
                otto_email.deliver(to, subject, body, text, "retention", bid)
            used.append("email")
    except Exception as e:                                      # noqa: BLE001
        print(f"  e-mail notice failed: {type(e).__name__}", file=sys.stderr)
    return used


def _notice_text(t, days):
    name, bid = t["name"], t["brand"]
    return (f"{name}: data deleted in {days} day{'s' if days != 1 else ''} ({t['effective']}) unless a plan starts again",
            f"The plan of {name} ({bid}) ended on {t['ended']}. {RETENTION_DAYS} days after a plan ends Otto deletes the brand's "
            f"data from its live systems (Terms 17.3, DPA 9.2): brand profile, posts, campaigns, media, connections and access "
            f"tokens — in {days} day{'s' if days != 1 else ''}, on {t['effective']}. A zip export is made first and kept "
            f"{EXPORT_KEEP_DAYS} days. To keep the data: start a plan again (a new subscription on the Billing page, or the owner console), or hold it for a "
            f"legal reason: otto_retention.py hold {bid}.")


def send_notice(bid, which, today, ended, out=print):
    """File the 14- or 3-day notice (once: brands[].retention.notices) and tell the owner. → True when sent now."""
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            return False
        t = timeline(b, today, ended)
        if t["due"] != f"notice-{which}":
            return False
        st = b.setdefault("retention", {})
        if st.get("ended") != t["ended"]:
            st["notices"] = {}
        st.update(ended=t["ended"], source=t["source"], delete_on=t["delete_on"])
        st.setdefault("notices", {})[which] = today.isoformat()
        t = timeline(b, today, ended)
        title, why = _notice_text(t, t["days_left"])
        ap.add_rec_once(d, "P0" if which == "3" else "P1", title, why, "Keeps the promise in the Terms and the DPA (deletion "
                        "90 days after the plan ends) without surprising anyone", "Renew, export or hold",
                        brand=bid, source="retention", audience="owner", action="retention", delete_on=t["effective"])
    used = notify_owner(title, why, bid)
    audit(f"notice-{which} {bid} delete_on={t['effective']}" + (f" via={','.join(used)}" if used else ""))
    out(f"{bid}: {which}-day notice (deletion {t['effective']})" + (f" · sent by {', '.join(used)}" if used else ""))
    return True


def _record_state(bid, today, ended):
    """Keep brands[].retention in step with the timeline (first_seen day, delete_on); nothing is written when it already is."""
    d = ap.load()
    b = ap.brand(d, bid)
    if b is None:
        return
    t = timeline(b, today, ended)
    st = b.get("retention") if isinstance(b.get("retention"), dict) else {}
    want = {"ended": t["ended"], "source": t["source"], "delete_on": t["delete_on"]}
    if all(st.get(k) == v for k, v in want.items()):
        return
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is not None and on_ended_plan(b, ended):
            t = timeline(b, today, ended)
            st = b.setdefault("retention", {})
            if st.get("ended") not in (None, t["ended"]):
                st.pop("notices", None)                    # an earlier end's notices never count for this one
            st.update(ended=t["ended"], source=t["source"], delete_on=t["delete_on"])


def _clear_state(bid, why):
    """A brand whose plan runs again: forget the countdown and close its open retention cards."""
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None or not b.get("retention"):
            return False
        b.pop("retention", None)
        for r in d.get("recommendations") or []:
            if isinstance(r, dict) and r.get("brand") == bid and r.get("source") == "retention" and r.get("status") == "proposed":
                r["status"] = "dismissed"
                r["dismissed_at"] = ap.now_iso()
    audit(f"clear {bid} ({why})")
    return True


# ---------------------------------------------------------------- deletion

def _journal():
    return _read_json(journal_path(), {})


def _journal_write(j):
    ap._atomic_write(journal_path(), json.dumps(j, ensure_ascii=False, indent=1) + "\n")


def _allowed_roots(bid):
    pd = paths.public_dir()
    return [Path(x).resolve() for x in (paths.ASSETS, pd, ap.BRANDS, secrets_dir(), motion_root(), outbox_dir()) if x is not None]


def _remove(p, roots):
    """Delete one listed file / dir, only inside the roots it may be in. → True when something was removed."""
    p = Path(p)
    try:
        rp = p.resolve()
    except OSError:
        return False
    if not any(rp.is_relative_to(r) and rp != r for r in roots):
        print(f"  refused to delete {p}: outside the data dirs", file=sys.stderr)
        return False
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
            return True
        if p.exists() or p.is_symlink():
            p.unlink(missing_ok=True)
            return True
    except OSError as e:                                        # e.g. /etc/otto/secrets read-only for the job
        print(f"  could not delete {p}: {type(e).__name__}", file=sys.stderr)
    return False


def _base(host):
    try:
        import otto_admin
        return otto_admin.base_domain(host)
    except Exception:
        return host


def _strip_events(domains):
    """Drop "domain" from the scan events of these domains (the event stays for the statistics). → events changed."""
    f = events_path()
    if not domains or not f.exists():
        return 0
    base = _base
    try:
        import otto_track
        lock = otto_track._lock
    except Exception:
        import threading
        lock = threading.Lock()
    n = 0
    with lock:
        lines = f.read_bytes().splitlines(keepends=True)
        out = []
        for line in lines:
            if b'"domain"' in line:
                try:
                    e = json.loads(line)
                except ValueError:
                    e = None
                if isinstance(e, dict) and e.get("domain") and (e["domain"] in domains or base(e["domain"]) in domains):
                    e.pop("domain")
                    line = (json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                    n += 1
            out.append(line)
        if n:
            ap._atomic_write(f, b"".join(out).decode("utf-8", "replace"))
    return n


def _drop_leads(pred):
    """Remove leads.json rows for which pred(id, row) is true (under its lock). → ids removed."""
    f = leads_path()
    if not f.exists():
        return []
    with _flock(f):
        cur = _read_json(f, {})
        leads = cur.get("leads") if isinstance(cur.get("leads"), dict) else {}
        gone = [k for k, v in leads.items() if pred(k, v if isinstance(v, dict) else {})]
        if gone:
            for k in gone:
                leads.pop(k, None)
            ap._atomic_write(f, json.dumps(cur, ensure_ascii=False, indent=1) + "\n")
            os.chmod(f, 0o600)
    return gone


def _strip_state_files(bid):
    """The brand's entries in .email-state.json, .report-state.json (the morning report's ledger), heartbeats.json and
    metrics_history.jsonl."""
    f = report_state_path()
    if f.exists():
        with _flock(f):
            st = _read_json(f, {})
            if isinstance(st.get("brands"), dict) and st["brands"].pop(bid, None) is not None:
                ap._atomic_write(f, json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    f = email_state_path()
    if f.exists():
        with _flock(f):
            st = _read_json(f, {})
            changed = (st.get("brands") or {}).pop(bid, None) is not None if isinstance(st.get("brands"), dict) else False
            for rec in (st.get("bounces") or {}).values() if isinstance(st.get("bounces"), dict) else []:
                if isinstance(rec, dict) and bid in (rec.get("brands") or []):
                    rec["brands"] = [x for x in rec["brands"] if x != bid]
                    changed = True
            if isinstance(st.get("bounces"), dict):
                empty = [k for k, rec in st["bounces"].items() if isinstance(rec, dict) and "brands" in rec and not rec["brands"]]
                for k in empty:
                    st["bounces"].pop(k)
                changed = changed or bool(empty)
            if isinstance(st.get("sent_ids"), list):
                keep = [x for x in st["sent_ids"] if not (isinstance(x, dict) and x.get("brand") == bid)]
                changed = changed or len(keep) != len(st["sent_ids"])
                st["sent_ids"] = keep
            if changed:
                ap._atomic_write(f, json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    f = heartbeats_path()
    if f.exists():
        with _flock(f):
            hb = _read_json(f, {})
            changed = False
            for rec in (hb.get("jobs") or {}).values() if isinstance(hb.get("jobs"), dict) else []:
                if isinstance(rec, dict) and isinstance(rec.get("brands"), dict) and bid in rec["brands"]:
                    rec["brands"].pop(bid)
                    changed = True
            if changed:
                ap._atomic_write(f, json.dumps(hb, ensure_ascii=False, indent=1) + "\n")
    f = history_path()
    if f.exists():
        rows, changed = [], False
        for line in f.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                rows.append(line)
                continue
            if isinstance(row, dict) and isinstance(row.get("metrics"), dict) and bid in row["metrics"]:
                row["metrics"].pop(bid)
                changed = True
            rows.append(json.dumps(row, ensure_ascii=False))
        if changed:
            ap._atomic_write(f, "".join(r + "\n" for r in rows))


def _strip_actions_log(bid, item_ids, lead_ids):
    """actions.log keeps every line; lines about this brand (its id, its posts / campaigns / recs, its lead) lose their
    content (note=…, ip=…). → lines changed."""
    f = actions_log()
    if not f.exists():
        return 0
    words = {bid} | set(item_ids) | set(lead_ids)
    rx = re.compile(r"(?<![A-Za-z0-9_.:-])(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?![A-Za-z0-9_-])")
    n, out = 0, []
    for line in f.read_text(errors="replace").splitlines(keepends=True):
        if rx.search(line):
            new = STRIP.sub(lambda m: f" {m.group(1)}=[deleted]", line)
            n += new != line
            line = new
        out.append(line)
    if n:
        ap._atomic_write(f, "".join(out))
    return n


def _finish_journal(bid, entry, out=print):
    """Remove what the journal lists for a brand that is gone from data.json, then drop the entry."""
    roots = _allowed_roots(bid)
    removed = sum(_remove(p, roots) for p in entry.get("files", []) + entry.get("dirs", []) + entry.get("secrets", [])
                  + entry.get("outbox", []))
    doms = set(entry.get("domains") or [])
    ev = _strip_events(doms)
    leads = _drop_leads(lambda k, v: k.startswith("d:") and (k[2:] in doms or _base(k[2:]) in doms))
    _strip_state_files(bid)
    lines = _strip_actions_log(bid, entry.get("item_ids") or [], [f"d:{x}" for x in doms])
    left = [p for p in entry.get("files", []) + entry.get("dirs", []) + entry.get("secrets", []) + entry.get("outbox", [])
            if Path(p).exists()]
    audit(f"delete {bid} (plan ended {entry.get('ended')}; export {entry.get('export')}; records "
          + ",".join(f"{k}={v}" for k, v in sorted((entry.get("counts") or {}).items())) +
          f"; files {removed}; secrets {len(entry.get('secrets') or [])}; lead {len(leads)}; events {ev}; log lines stripped {lines}"
          + (f"; NOT removed {len(left)}" if left else "") + ")")
    if left:                                                    # never loop on it: the owner removes the rest by hand
        with ap.transaction() as d:
            ap.add_rec(d, "P0", f"{bid}: {len(left)} file(s) of a deleted client could not be removed",
                       "The retention job has no write access there (a token in /etc/otto/secrets needs the "
                       "otto-job@retention drop-in from bootstrap.sh). Remove them by hand: " + " ".join(left)[:900],
                       "Deletion as promised in the Terms (17.3) and the DPA (9.2)", "Remove by hand",
                       source="retention", audience="owner", action="retention", deleted=bid)
        out(f"{bid}: {len(left)} file(s) could not be removed — owner card filed")
    j = _journal()
    j.get("pending", {}).pop(bid, None)
    _journal_write(j)
    return {"removed": removed, "events": ev, "leads": leads, "log_lines": lines, "left": left}


def resume_journal(out=print):
    """Finish deletions a crash interrupted; drop entries whose brand is (still / again) in data.json."""
    j = _journal()
    pending = j.get("pending") if isinstance(j.get("pending"), dict) else {}
    if not pending:
        return []
    d = ap.load()
    done = []
    for bid, entry in list(pending.items()):
        if ap.brand(d, bid) is not None:
            out(f"{bid}: a deletion was interrupted before its records went — dropped from the journal, nothing removed")
            j2 = _journal()
            j2.get("pending", {}).pop(bid, None)
            _journal_write(j2)
            continue
        _finish_journal(bid, entry, out)
        done.append(bid)
        out(f"{bid}: interrupted deletion finished")
    return done


def delete_brand(bid, today, ended, out=print):
    """Export, then delete one brand (see the module doc). → result dict, or None when it no longer qualifies."""
    d = ap.load()
    b = ap.brand(d, bid)
    if b is None or timeline(b, today, ended)["due"] != "delete":
        return None
    t = timeline(b, today, ended)
    zp = export(bid, d, reason="retention")
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None or timeline(b, today, ended)["due"] != "delete":   # renewed or held meanwhile: keep everything
            zp.unlink(missing_ok=True)
            return None
        inv = inventory(d, bid)
        entry = {"at": ap.now_iso(), "ended": t["ended"], "export": zp.name, "counts": {},
                 "files": [str(p) for p in inv["files"]], "dirs": [str(p) for p in inv["dirs"]],
                 "secrets": [str(p) for p in inv["secrets"]], "outbox": [str(p) for p in inv["outbox"]],
                 "domains": inv["domains"], "item_ids": inv["item_ids"]}
        entry["counts"] = purge_records(d, bid)
        j = _journal()
        j.setdefault("pending", {})[bid] = entry
        _journal_write(j)                              # before data.json is written: a crash after it resumes from here
    res = _finish_journal(bid, entry, out)
    with ap.transaction() as d:
        ap.add_rec(d, "P2", f"{bid}: client data deleted ({RETENTION_DAYS} days after the plan ended)",
                   f"The plan ended on {t['ended']}; the brand, its records, media, connections and tokens are gone from Otto's "
                   f"live systems. Billing records and the audit log stay. The export {zp.name} is kept {EXPORT_KEEP_DAYS} days "
                   f"(otto_retention.py restore {zp.name} --apply brings the brand back); backups roll over within about 8 weeks.",
                   "Deletion as promised in the Terms (17.3) and the DPA (9.2)", "Nothing to do",
                   source="retention", audience="owner", action="retention", deleted=bid, export=zp.name)
    notify_owner(f"{bid}: client data deleted", f"The data of {bid} was deleted today ({RETENTION_DAYS} days after its plan "
                 f"ended on {t['ended']}). Export kept {EXPORT_KEEP_DAYS} days: {zp.name}.", bid)
    out(f"{bid}: DELETED · export {zp.name} · " + ", ".join(f"{v} {k}" for k, v in sorted(entry["counts"].items()))
        + f" · {res['removed']} files/dirs")
    return dict(res, export=zp.name, counts=entry["counts"])


# ---------------------------------------------------------------- leads

def lead_plan(today):
    """Leads with no activity for lead_days(): {"leads": [ids], "domains": [domains whose events lose the domain]}."""
    cut = (today - timedelta(days=lead_days())).isoformat()
    last = {}
    f = events_path()
    if f.exists():
        for line in f.read_bytes().splitlines():
            if b'"domain"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("domain") and isinstance(e.get("ts"), str):
                last[e["domain"]] = max(last.get(e["domain"], ""), e["ts"][:10])
    leads = (_read_json(leads_path(), {}).get("leads") or {}) if leads_path().exists() else {}
    leads = leads if isinstance(leads, dict) else {}
    upd = {k: str((v or {}).get("updated") or "")[:10] for k, v in leads.items() if isinstance(v, dict)}
    domains = sorted(dom for dom, day in last.items() if max(day, upd.get(f"d:{dom}", "")) < cut)
    gone = []
    for k in leads:
        if k.startswith("d:"):
            act = max(last.get(k[2:], ""), upd.get(k, ""))
        elif k.startswith("v:"):
            act = max(k[2:12], upd.get(k, ""))
        else:
            continue
        if act < cut:
            gone.append(k)
    return {"cutoff": cut, "leads": sorted(gone), "domains": domains}


def prune_leads(today, out=print):
    lp = lead_plan(today)
    ev = _strip_events(set(lp["domains"]))
    due = set(lp["leads"])
    gone = _drop_leads(lambda k, v: k in due and str(v.get("updated") or "")[:10] < lp["cutoff"])
    if ev or gone:
        audit(f"leads pruned {len(gone)} (no activity since {lp['cutoff']}), scan events stripped {ev}")
        out(f"leads: {len(gone)} removed, {ev} scan events lost their domain (no activity since {lp['cutoff']})")
    return {"leads": gone, "events": ev}


# ---------------------------------------------------------------- plan / run / hold

def plan(today=None, d=None):
    """Dry: the timeline of every brand whose plan ended, what deleting it would remove, exports and leads due."""
    today = today or utcnow().date()
    d = ap.load() if d is None else d
    cfg = ap.plans_config()
    rows = []
    if not cfg.get("error"):
        ended = cfg["defaults"]["ended"]
        for b in d.get("brands") or []:
            if not (isinstance(b, dict) and b.get("id")):
                continue
            t = timeline(b, today, ended)
            if t["state"] == "active":
                if b.get("retention"):
                    rows.append(dict(t, note="plan runs again: the countdown is cleared on the next run"))
                continue
            inv = inventory(d, b["id"])
            t["would_delete"] = {"records": inv["counts"]["records"], "keyed": inv["counts"]["keyed"],
                                 "files": [str(p) for p in inv["files"]], "dirs": [str(p) for p in inv["dirs"]],
                                 "secrets": [p.name for p in inv["secrets"]], "outbox": len(inv["outbox"]),
                                 "lead_domains": inv["domains"], "kept_shared": inv["kept_shared"]}
            rows.append(t)
    return {"today": today.isoformat(), "config_error": cfg.get("error"), "brands": rows,
            "exports_due": prune_exports(today, apply=False), "leads": lead_plan(today)}


def print_plan(p, out=print):
    if p["config_error"]:
        out(f"plans.json is unreadable ({p['config_error'][:120]}) — nothing is deleted until it is fixed")
    if not p["brands"]:
        out("no brand is on the ended plan")
    for t in p["brands"]:
        if t["state"] == "active":
            out(f"{t['brand']}: {t['note']}")
            continue
        head = f"{t['brand']}: plan ended {t['ended']} ({t['source']}) · deletion {t['effective']}"
        if t["state"] == "held":
            head += " · ON HOLD (retention_hold): nothing is deleted"
        else:
            head += f" (in {t['days_left']} days) · notices {t['notice_14']} / {t['notice_3']}" + \
                    (f" · sent {t['sent']}" if t["sent"] else "") + (f" · due now: {t['due']}" if t["due"] else "")
        out(head)
        w = t["would_delete"]
        out(f"   records: {', '.join(f'{v} {k}' for k, v in w['records'].items()) or 'none'}"
            + (f" · keyed: {', '.join(w['keyed'])}" if w["keyed"] else ""))
        out(f"   files: {len(w['files'])} · dirs: {len(w['dirs'])} · secrets: {', '.join(w['secrets']) or 'none'}"
            f" · outbox e-mails: {w['outbox']} · lead: {', '.join(w['lead_domains']) or 'none'}")
        for f in w["files"] + w["dirs"]:
            out(f"     {f}")
        if w["kept_shared"]:
            out(f"   kept (another brand or a shipped page uses them): {', '.join(w['kept_shared'])}")
    if p["exports_due"]:
        out(f"exports older than {EXPORT_KEEP_DAYS} days: {', '.join(p['exports_due'])}")
    lp = p["leads"]
    out(f"leads with no activity since {lp['cutoff']}: {len(lp['leads'])}" + (f" ({', '.join(lp['leads'][:10])})" if lp["leads"] else "")
        + (f" · scan events to strip for {len(lp['domains'])} domains" if lp["domains"] else ""))


def run(today=None, out=print):
    """The daily job. → exit code."""
    today = today or utcnow().date()
    failed = False
    try:
        resume_journal(out)
    except Exception as e:                                      # noqa: BLE001
        out(f"journal: {type(e).__name__}: {e}")
        failed = True
    try:                                # before the deletions: an export made below is never pruned by this same run (its
        gone = prune_exports(today)     # stamp is the wall clock, `today` may be a --today well ahead of it)
        if gone:
            audit(f"exports removed {len(gone)} (older than {EXPORT_KEEP_DAYS} days)")
            out(f"exports removed: {', '.join(gone)}")
    except Exception as e:                                      # noqa: BLE001
        out(f"prune: FAILED {type(e).__name__}: {str(e)[:200]}")
        failed = True
    cfg = ap.plans_config()
    if cfg.get("error"):
        out(f"plans.json is unreadable ({cfg['error'][:120]}) — no notice, no deletion today")
        failed = True
    else:
        ended = cfg["defaults"]["ended"]
        for b in list(ap.load().get("brands") or []):
            bid = b.get("id") if isinstance(b, dict) else None
            if not bid:
                continue
            try:
                t = timeline(b, today, ended)
                if t["state"] == "active":
                    if b.get("retention") and _clear_state(bid, f"plan {b.get('plan') or 'legacy'} runs"):
                        out(f"{bid}: plan runs again — countdown cleared")
                    continue
                _record_state(bid, today, ended)
                if t["state"] == "held":
                    out(f"{bid}: on hold — deletion date {t['effective']} does not apply while retention_hold is set")
                elif t["due"] in ("notice-14", "notice-3"):
                    send_notice(bid, t["due"].split("-")[1], today, ended, out)
                elif t["due"] == "delete":
                    delete_brand(bid, today, ended, out)
                else:
                    out(f"{bid}: deletion {t['effective']} (in {t['days_left']} days)")
            except Exception as e:                              # noqa: BLE001 — one brand never stops the others
                out(f"{bid}: FAILED {type(e).__name__}: {str(e)[:200]}")
                failed = True
    try:
        prune_leads(today, out)
    except Exception as e:                                      # noqa: BLE001
        out(f"prune: FAILED {type(e).__name__}: {str(e)[:200]}")
        failed = True
    return 1 if failed else 0


def set_hold(bid, on, note="", who="cli"):
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            raise KeyError(bid)
        if on:
            b["retention_hold"] = True
        else:
            b.pop("retention_hold", None)
            if isinstance(b.get("retention"), dict):
                b["retention"].pop("notices", None)            # both notices again before any deletion
    audit(f"{'hold' if on else 'release'} {bid} by={who}" + (f" note={json.dumps(note, ensure_ascii=False)}" if note else ""))


def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def main(a):
    cmd = a[0] if a else ""
    today = _day(_opt(a, "--today")) if _opt(a, "--today") else None
    if cmd == "plan":
        p = plan(today)
        if "--json" in a:
            print(json.dumps(p, ensure_ascii=False, indent=1, default=str))
        else:
            print_plan(p)
        return 0
    if cmd == "run":
        return run(today)
    if cmd in ("hold", "release") and len(a) > 1:
        set_hold(a[1], cmd == "hold", _opt(a, "--note") or "")
        print(f"{a[1]}: {'on hold — nothing is deleted while it is set' if cmd == 'hold' else 'hold released'}")
        return 0
    if cmd == "export" and len(a) > 1:
        zp = export(a[1])
        audit(f"export {a[1]} {zp.name}")
        print(zp)
        return 0
    if cmd == "restore" and len(a) > 1:
        restore(a[1], apply="--apply" in a)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
