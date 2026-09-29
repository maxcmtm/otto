#!/usr/bin/env python3
"""Otto platform state CLI. All writes to data.json go through here — either via the
CLI or via the helper functions below, which the engine scripts import.

Usage:
  ap.py list [brand] | pending
  ap.py add <brand> <pillar> <platform> <slot ISO> <hook...>
  ap.py status <post-id> <draft|pending_approval|approved|scheduled|publishing|published|skipped|failed>   # admin: no transition check
  ap.py decide <post-id> <approve|skip|later> [--via telegram|dashboard|auto]
  ap.py set <post-id> '<json-object>'          # merge fields into a post (hook, caption, image, format, brief…)
  ap.py brand-add <id> <name> <url> <lang> [pillar,pillar,...] [--tz Europe/Berlin] [--countries DE,AT] [--currency EUR]
                                                 # tz/countries default from the url's country TLD, then the language
  ap.py recs | rec <rec-id> <proposed|approved|dismissed|done>
  ap.py rec-add <P0|P1|P2> <title> | <why> | <impact> | <cta>
  ap.py taste [brand]                            # what the owner's decisions taught us
  ap.py sync-fallback                            # re-embed data.json into index.html fallback block

Concurrency: every writer uses `with ap.transaction() as d:` — an exclusive flock on data.json.lock,
a fresh load, the change, then an atomic write (temp file + os.replace). Long network work (Meta,
Google, Leonardo, Telegram) happens OUTSIDE the lock; only the per-id patch runs inside it.

Env: OTTO_DATA (default ./data.json), OTTO_HTML (default ./index.html), OTTO_BRANDS (default ../brands),
     OTTO_TZ (default brand timezone when brands[].tz is not set; default Asia/Jerusalem)
"""
import fcntl, json, os, re, sys, tempfile, threading, urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
DATA = Path(os.environ.get("OTTO_DATA") or HERE / "data.json")
HTML = Path(os.environ.get("OTTO_HTML") or HERE / "index.html")
BRANDS = Path(os.environ.get("OTTO_BRANDS") or HERE.parent / "brands")
STATUSES = {"draft", "pending_approval", "approved", "scheduled", "publishing", "published", "skipped", "failed"}
REC_STATUSES = {"proposed", "approved", "dismissed", "done"}
PLATFORMS = {"fb", "ig", "li"}
FORMATS = {"post", "carousel", "reel", "story", "video"}
DEFAULT_TZ = "Asia/Jerusalem"

# What the owner-facing surfaces (dashboard API, Telegram) may do to a post. The publisher and the
# admin CLI (`ap.py status`) move posts to publishing/published/failed themselves; nothing owner-facing
# can put a published/publishing/failed post back to approved (that is how double posts happen).
POST_TRANSITIONS = {
    "draft": {"pending_approval", "approved", "skipped"},
    "pending_approval": {"draft", "approved", "skipped"},
    "approved": {"pending_approval", "draft", "skipped", "scheduled"},
    "scheduled": {"approved", "pending_approval", "draft", "skipped"},
    "skipped": {"draft", "pending_approval"},
    "failed": {"draft", "pending_approval", "skipped"},     # re-review first; never straight back to approved
    "publishing": set(),                                    # may already be live — a human checks Meta first
    "published": set(),
}
REC_TRANSITIONS = {
    "proposed": {"approved", "dismissed", "done"},
    "approved": {"done", "dismissed"},
    "dismissed": {"proposed"},
    "done": set(),
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- storage: lock + atomic write ----------

_tx = threading.local()


def lock_path():
    return DATA.with_name(DATA.name + ".lock")


@contextmanager
def locked():
    """Exclusive flock on data.json.lock (re-entrant within one thread)."""
    if getattr(_tx, "depth", 0):
        _tx.depth += 1
        try:
            yield
        finally:
            _tx.depth -= 1
        return
    lp = lock_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        _tx.depth = 1
        try:
            yield
        finally:
            _tx.depth = 0
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextmanager
def transaction(sync=True):
    """with ap.transaction() as d: … — lock, fresh load, yield, atomic save. An exception inside the
    block discards the change (nothing is written). Nested blocks in the same thread share the outer d."""
    if getattr(_tx, "d", None) is not None:
        yield _tx.d
        return
    with locked():
        d = load()
        _tx.d = d
        try:
            yield d
        finally:
            _tx.d = None
        _write(d, sync)


def load():
    return json.loads(DATA.read_text())


def _atomic_write(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _write(d, sync=True):
    d["generated"] = now_iso()
    _atomic_write(DATA, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    if sync:
        sync_fallback(d)


def save(d, sync=True):
    """Legacy whole-document save (atomic, under the lock). Prefer transaction(): a load() … save()
    pair around slow work can still overwrite someone else's change. Inside a transaction this is a no-op
    (the transaction writes on exit)."""
    if getattr(_tx, "d", None) is not None:
        return
    with locked():
        _write(d, sync)


def embed_json(d):
    """JSON safe to embed in <script type=application/json>: no '</' (closes the tag) and no '<!--'."""
    return json.dumps(d, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "\\u003c!--")


def sync_fallback(d=None):
    d = d or load()
    if not HTML.exists():
        return
    html = HTML.read_text()
    blob = embed_json(d)
    new = re.sub(r'(<script id="fallback-data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    if new != html:
        _atomic_write(HTML, new)
    print("fallback synced")


# ---------- helpers used by the engine scripts ----------

def brand(d, bid):
    return next((b for b in d.get("brands", []) if b["id"] == bid), None)


def post(d, pid):
    return next((p for p in d.get("posts", []) if p["id"] == pid), None)


def rec(d, rid):
    return next((r for r in d.get("recommendations", []) if r["id"] == rid), None)


def campaign(d, cid):
    return next((c for c in d.get("campaigns", []) if c["id"] == cid), None)


def _num_suffix(ident, prefix):
    if not ident.startswith(prefix + "-"):
        return 0
    tail = ident[len(prefix) + 1:]
    return int(tail) if tail.isdigit() else 0


def next_seq(d, key, floor=0):
    """Persistent counter in d["seq"] — ids are never reused, even after posts are deleted (--replace)."""
    seq = d.setdefault("seq", {})
    n = max(int(seq.get(key, 0) or 0), int(floor or 0)) + 1
    seq[key] = n
    return n


def next_id(d, prefix, items):
    floor = max([_num_suffix(x.get("id", ""), prefix) for x in items] or [0])
    return f"{prefix}-{next_seq(d, 'id:' + prefix, floor):03d}"


def id_prefix(d, bid):
    b = brand(d, bid) or {}
    if b.get("prefix"):
        return b["prefix"]
    seq = d.setdefault("seq", {})
    if seq.get("prefix:" + bid):
        return seq["prefix:" + bid]
    seen = [p["id"].split("-")[0] for p in d.get("posts", []) if p.get("brand") == bid and "-" in p["id"]]
    prefix = max(set(seen), key=seen.count) if seen else bid[:2]
    seq["prefix:" + bid] = prefix
    return prefix


def new_post_id(d, bid):
    return next_id(d, id_prefix(d, bid), d.get("posts", []))


def add_post(d, bid, pillar, platform, slot, hook="", **fields):
    assert brand(d, bid), f"unknown brand {bid}"
    assert platform in PLATFORMS, f"bad platform {platform}"
    p = {"id": new_post_id(d, bid), "brand": bid, "pillar": pillar, "platform": platform,
         "hook": hook, "status": "draft", "slot": slot, "created_at": now_iso()}
    p.update({k: v for k, v in fields.items() if v is not None})
    d.setdefault("posts", []).append(p)
    return p


def add_rec(d, prio, title, why, impact, cta, **fields):
    assert prio in {"P0", "P1", "P2"}, f"bad priority {prio}"
    r = {"id": next_id(d, "rec", d.get("recommendations", [])), "priority": prio, "title": title, "why": why,
         "impact": impact, "cta": cta, "status": "proposed", "created_at": now_iso()}
    r.update(fields)
    d.setdefault("recommendations", []).append(r)
    return r


def add_rec_once(d, prio, title, why, impact, cta, **fields):
    """add_rec, unless a proposed recommendation with the same title for the same brand already exists
    (re-running a cron must not stack duplicate cards)."""
    for r in d.get("recommendations", []):
        if r.get("status") == "proposed" and r.get("title") == title and r.get("brand") == fields.get("brand"):
            return r
    return add_rec(d, prio, title, why, impact, cta, **fields)


def can_transition(kind, cur, new):
    table = POST_TRANSITIONS if kind == "post" else REC_TRANSITIONS
    if new == cur:
        return cur not in ("publishing",)
    return new in table.get(cur, set())


def check_transition(kind, cur, new):
    if not can_transition(kind, cur, new):
        raise ValueError(f"{kind} is {cur} — cannot move it to {new}")


DECISIONS = {"approve": "approved", "skip": "skipped", "later": "pending_approval"}


def decide(d, pid, decision, via="dashboard", enforce=True):
    """Owner decision on a post. Writes status + taste log (what the agency learns)."""
    p = post(d, pid)
    if p is None:
        raise KeyError(pid)
    if decision not in DECISIONS:
        raise ValueError(f"bad decision {decision}")
    if enforce:
        check_transition("post", p.get("status"), DECISIONS[decision])
    p["status"] = DECISIONS[decision]
    p["approved_via"] = via
    p["decided_at"] = now_iso()
    d.setdefault("taste_log", []).append({"post": pid, "brand": p["brand"], "pillar": p.get("pillar"),
                                          "platform": p.get("platform"), "decision": decision,
                                          "via": via, "ts": p["decided_at"]})
    return p


def taste(d, bid=None):
    """Per-pillar approve/skip counts — the visible 'what the agency learned'."""
    out = {}
    for t in d.get("taste_log", []):
        if bid and t["brand"] != bid:
            continue
        k = (t["brand"], t.get("pillar") or "?")
        out.setdefault(k, {"approve": 0, "skip": 0, "later": 0})
        out[k][t["decision"]] = out[k].get(t["decision"], 0) + 1
    return out


# ---------- brand helpers: timezone, language, currency ----------

def brand_tz(b):
    name = (b or {}).get("tz") or os.environ.get("OTTO_TZ") or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def slot_dt(p, b=None):
    """The post's slot as an aware datetime. A naive slot ("2026-10-01T09:00") is brand-local time
    (brands[].tz, default Asia/Jerusalem); an explicit offset is respected. None if unparsable."""
    dt = parse_iso((p or {}).get("slot"))
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=brand_tz(b))


LANGS = {"en", "de", "he", "fr", "es", "it", "nl", "pt", "pl", "ar", "ru", "hu", "ro"}


def scan_of(bid):
    f = BRANDS / bid / "scan.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        return {}


def brand_lang(b):
    """Primary content language: first language code in brands[].lang ("HE · shown in English" → he,
    "EN/DE" → en), else the site scan's first language, else en."""
    b = b or {}
    for tok in re.findall(r"[A-Za-z]+", b.get("lang") or ""):
        if len(tok) == 2 and tok.lower() in LANGS:
            return tok.lower()
    langs = (scan_of(b["id"]).get("languages") or []) if b.get("id") else []
    return langs[0] if langs else "en"


CURRENCY_SYMBOLS = {"EUR": "€", "ILS": "₪", "USD": "$", "GBP": "£", "CHF": "CHF ", "HUF": "Ft ", "PLN": "zł ",
                    "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "CZK": "Kč ", "RON": "lei ", "JPY": "¥"}
_SYMBOL_TO_CODE = {"€": "EUR", "₪": "ILS", "$": "USD", "£": "GBP", "NIS": "ILS", "¥": "JPY"}


def currency_code(x):
    """'€' / 'eur' / 'EUR' → 'EUR'. None for unknown / ambiguous ('NOK/SEK/DKK')."""
    if not x:
        return None
    x = str(x).strip()
    if x in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[x]
    if re.fullmatch(r"[A-Za-z]{3}", x):
        return _SYMBOL_TO_CODE.get(x.upper(), x.upper())
    return None


def currency_symbol(code):
    code = currency_code(code) or "EUR"
    return CURRENCY_SYMBOLS.get(code, code + " ")


def brand_currency(d, bid):
    """ISO code: brands[].currency → site scan commerce.currency → the brand's first country → EUR."""
    b = brand(d, bid) or {}
    return (currency_code(b.get("currency")) or currency_code((scan_of(bid).get("commerce") or {}).get("currency"))
            or COUNTRY_CURRENCY.get(((b.get("countries") or [None])[0] or "").upper()) or "EUR")


# Where a new brand lives, before anything is scanned: the url's country TLD, then the language (brand-add).
COUNTRY_TZ = {"DE": "Europe/Berlin", "AT": "Europe/Vienna", "CH": "Europe/Zurich", "PT": "Europe/Lisbon", "NL": "Europe/Amsterdam",
              "BE": "Europe/Brussels", "LU": "Europe/Luxembourg", "IT": "Europe/Rome", "FR": "Europe/Paris", "ES": "Europe/Madrid",
              "IL": "Asia/Jerusalem", "GB": "Europe/London", "IE": "Europe/Dublin", "PL": "Europe/Warsaw", "HU": "Europe/Budapest",
              "RO": "Europe/Bucharest", "DK": "Europe/Copenhagen", "SE": "Europe/Stockholm", "NO": "Europe/Oslo", "FI": "Europe/Helsinki",
              "CZ": "Europe/Prague", "GR": "Europe/Athens", "US": "America/New_York"}
COUNTRY_CURRENCY = {"IL": "ILS", "GB": "GBP", "CH": "CHF", "PL": "PLN", "HU": "HUF", "RO": "RON", "DK": "DKK", "SE": "SEK",
                    "NO": "NOK", "CZ": "CZK", "US": "USD"}
LANG_COUNTRY = {"de": "DE", "he": "IL", "pt": "PT", "nl": "NL", "it": "IT", "fr": "FR", "es": "ES", "pl": "PL", "hu": "HU", "ro": "RO"}


def guess_country(url="", lang=""):
    """ISO country from the url's TLD (.de, .co.il, .co.uk …), else from the first language code; None when unknown."""
    url = str(url or "").strip()
    host = (urllib.parse.urlsplit(url if "//" in url else "//" + url).hostname or "").rstrip(".")
    tld = host.rsplit(".", 1)[-1].upper() if "." in host else ""
    tld = "GB" if tld == "UK" else tld
    if tld in COUNTRY_TZ:
        return tld
    for tok in re.findall(r"[A-Za-z]+", lang or ""):
        if tok.lower() in LANG_COUNTRY:
            return LANG_COUNTRY[tok.lower()]
    return None


def brand_countries(b, langs=()):
    """Ad / research market: brands[].countries → the url's TLD → the site languages (he → IL, de → DACH, pt → PT …) → DE."""
    b = b or {}
    if b.get("countries"):
        return list(b["countries"])
    cc = guess_country(b.get("url") or "")
    if cc:
        return [cc]
    langs = list(langs) or [brand_lang(b)]
    if "he" in langs:
        return ["IL"]
    if "de" in langs:
        return ["DE", "AT", "CH"]
    for l in langs:
        if l in LANG_COUNTRY:
            return [LANG_COUNTRY[l]]
    return ["DE"]


def money(v, code, digits=0):
    if v is None:
        return "—"
    return f"{currency_symbol(code)}{v:,.{digits}f}"


def num(v):
    """Metric value if it is a real number, else None (Graph sometimes returns dicts/strings/None)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return None
    return None


# ---------- CLI ----------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("list", "pending"):
        d = load()
        posts = d["posts"]
        if args and args[0] == "pending":
            posts = [p for p in posts if p["status"] == "pending_approval"]
        elif len(args) > 1:
            posts = [p for p in posts if p["brand"] == args[1]]
        for p in posts:
            print(f'{p["id"]:8} {p["brand"]:12} {p["status"]:17} {p["slot"]:17} {p.get("hook","")}')
        print(f'-- {len(posts)} posts')
    elif args[0] == "add":
        bid, pillar, platform, slot = args[1:5]
        with transaction() as d:
            p = add_post(d, bid, pillar, platform, slot, " ".join(args[5:]))
        print(f"added {p['id']}")
    elif args[0] == "status":
        pid, st = args[1], args[2]
        assert st in STATUSES, f"bad status {st}"
        with transaction() as d:
            p = post(d, pid)
            assert p, f"unknown post {pid}"
            p["status"] = st
        print(f'{pid} -> {st}')
    elif args[0] == "decide":
        pid, decision = args[1], args[2]
        via = args[args.index("--via") + 1] if "--via" in args else "dashboard"
        with transaction() as d:
            p = decide(d, pid, decision, via)
        print(f'{pid} -> {p["status"]} (via {via})')
    elif args[0] == "set":
        pid, fields = args[1], json.loads(" ".join(args[2:]))
        with transaction() as d:
            p = post(d, pid)
            assert p, f"unknown post {pid}"
            if "status" in fields:
                assert fields["status"] in STATUSES, f"bad status {fields['status']}"
            p.update(fields)
        print(f'{pid} updated: {", ".join(fields)}')
    elif args[0] == "brand-add":
        opts = {}
        for k in ("--tz", "--countries", "--currency"):
            if k in args:
                i = args.index(k)
                opts[k] = args[i + 1]
                del args[i:i + 2]
        bid, name, url, lang = args[1:5]
        pillars = [s.strip() for s in args[5].split(",")] if len(args) > 5 else []
        country = guess_country(url, lang)
        countries = [c.strip().upper() for c in opts["--countries"].split(",")] if "--countries" in opts else ([country] if country else [])
        tz = opts.get("--tz") or COUNTRY_TZ.get((countries or [None])[0], DEFAULT_TZ)
        ZoneInfo(tz)                                     # a typo fails here, not at publish time
        b = {"id": bid, "name": name, "url": url, "lang": lang, "tz": tz, "status": "onboarding", "pillars": pillars, "compliance": ""}
        if countries:
            b["countries"] = countries
        if "--currency" in opts:
            b["currency"] = currency_code(opts["--currency"])
        with transaction() as d:
            assert not brand(d, bid), f"brand {bid} exists"
            d.setdefault("brands", []).append(b)
        print(f"added brand {bid} · tz {tz} · countries {','.join(countries) or '—'}")
    elif args[0] == "recs":
        for r in load().get("recommendations", []):
            print(f'{r["id"]:8} {r["priority"]:3} {r["status"]:10} {r["title"]}')
    elif args[0] == "rec":
        rid, st = args[1], args[2]
        assert st in REC_STATUSES, f"bad status {st}"
        with transaction() as d:
            r = rec(d, rid)
            assert r, f"unknown recommendation {rid}"
            r["status"] = st
        print(f'{rid} -> {st}')
    elif args[0] == "rec-add":
        prio = args[1]
        title, why, impact, cta = [s.strip() for s in " ".join(args[2:]).split("|")]
        with transaction() as d:
            r = add_rec(d, prio, title, why, impact, cta)
        print(f"added {r['id']}")
    elif args[0] == "taste":
        d = load()
        for (b, pillar), c in sorted(taste(d, args[1] if len(args) > 1 else None).items()):
            print(f'{b:12} {pillar:22} ✓{c["approve"]:2}  ✗{c["skip"]:2}  ↷{c["later"]:2}')
    elif args[0] == "sync-fallback":
        with locked():
            sync_fallback(load())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
