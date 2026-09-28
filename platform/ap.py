#!/usr/bin/env python3
"""Otto platform state CLI. All writes to data.json go through here — either via the
CLI or via the helper functions below, which the engine scripts import.

Usage:
  ap.py list [brand] | pending
  ap.py add <brand> <pillar> <platform> <slot ISO> <hook...>
  ap.py status <post-id> <draft|pending_approval|approved|scheduled|published|skipped|failed>
  ap.py decide <post-id> <approve|skip|later> [--via telegram|dashboard|auto]
  ap.py set <post-id> '<json-object>'          # merge fields into a post (hook, caption, image, format, brief…)
  ap.py brand-add <id> <name> <url> <lang> [pillar,pillar,...]
  ap.py recs | rec <rec-id> <proposed|approved|dismissed|done>
  ap.py rec-add <P0|P1|P2> <title> | <why> | <impact> | <cta>
  ap.py taste [brand]                            # what the owner's decisions taught us
  ap.py sync-fallback                            # re-embed data.json into index.html fallback block

Env: OTTO_DATA (default ./data.json), OTTO_HTML (default ./index.html)
"""
import json, os, re, sys
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).parent
DATA = Path(os.environ.get("OTTO_DATA") or HERE / "data.json")
HTML = Path(os.environ.get("OTTO_HTML") or HERE / "index.html")
STATUSES = {"draft", "pending_approval", "approved", "scheduled", "published", "skipped", "failed"}
REC_STATUSES = {"proposed", "approved", "dismissed", "done"}
PLATFORMS = {"fb", "ig", "li"}
FORMATS = {"post", "carousel", "reel", "story", "video"}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    return json.loads(DATA.read_text())


def save(d, sync=True):
    d["generated"] = now_iso()
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    if sync:
        sync_fallback(d)


def sync_fallback(d=None):
    d = d or load()
    if not HTML.exists():
        return
    html = HTML.read_text()
    blob = json.dumps(d, ensure_ascii=False)
    new = re.sub(r'(<script id="fallback-data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    HTML.write_text(new)
    print("fallback synced")


# ---------- helpers used by the engine scripts ----------

def brand(d, bid):
    return next((b for b in d.get("brands", []) if b["id"] == bid), None)


def post(d, pid):
    return next((p for p in d.get("posts", []) if p["id"] == pid), None)


def id_prefix(d, bid):
    b = brand(d, bid) or {}
    if b.get("prefix"):
        return b["prefix"]
    seen = [p["id"].split("-")[0] for p in d.get("posts", []) if p.get("brand") == bid and "-" in p["id"]]
    return max(set(seen), key=seen.count) if seen else bid[:2]


def new_post_id(d, bid):
    prefix = id_prefix(d, bid)
    n = max([int(p["id"].split("-")[1]) for p in d.get("posts", [])
             if p["id"].startswith(prefix + "-") and p["id"].split("-")[1].isdigit()] or [0]) + 1
    return f"{prefix}-{n:03d}"


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
    n = max([int(r["id"].split("-")[1]) for r in d.get("recommendations", [])] or [0]) + 1
    r = {"id": f"rec-{n:03d}", "priority": prio, "title": title, "why": why, "impact": impact,
         "cta": cta, "status": "proposed", "created_at": now_iso()}
    r.update(fields)
    d.setdefault("recommendations", []).append(r)
    return r


def decide(d, pid, decision, via="dashboard"):
    """Owner decision on a post. Writes status + taste log (what the agency learns)."""
    p = post(d, pid)
    if p is None:
        raise KeyError(pid)
    mapping = {"approve": "approved", "skip": "skipped", "later": "pending_approval"}
    assert decision in mapping, f"bad decision {decision}"
    p["status"] = mapping[decision]
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
        d = load()
        p = add_post(d, bid, pillar, platform, slot, " ".join(args[5:]))
        save(d)
        print(f"added {p['id']}")
    elif args[0] == "status":
        pid, st = args[1], args[2]
        assert st in STATUSES, f"bad status {st}"
        d = load()
        p = post(d, pid)
        assert p, f"unknown post {pid}"
        p["status"] = st
        save(d)
        print(f'{pid} -> {st}')
    elif args[0] == "decide":
        pid, decision = args[1], args[2]
        via = args[args.index("--via") + 1] if "--via" in args else "dashboard"
        d = load()
        p = decide(d, pid, decision, via)
        save(d)
        print(f'{pid} -> {p["status"]} (via {via})')
    elif args[0] == "set":
        pid, fields = args[1], json.loads(" ".join(args[2:]))
        d = load()
        p = post(d, pid)
        assert p, f"unknown post {pid}"
        if "status" in fields:
            assert fields["status"] in STATUSES, f"bad status {fields['status']}"
        p.update(fields)
        save(d)
        print(f'{pid} updated: {", ".join(fields)}')
    elif args[0] == "brand-add":
        bid, name, url, lang = args[1:5]
        pillars = [s.strip() for s in args[5].split(",")] if len(args) > 5 else []
        d = load()
        assert not brand(d, bid), f"brand {bid} exists"
        d.setdefault("brands", []).append({"id": bid, "name": name, "url": url, "lang": lang,
                                           "status": "onboarding", "pillars": pillars, "compliance": ""})
        save(d)
        print(f"added brand {bid}")
    elif args[0] == "recs":
        for r in load().get("recommendations", []):
            print(f'{r["id"]:8} {r["priority"]:3} {r["status"]:10} {r["title"]}')
    elif args[0] == "rec":
        rid, st = args[1], args[2]
        assert st in REC_STATUSES, f"bad status {st}"
        d = load()
        r = next(r for r in d["recommendations"] if r["id"] == rid)
        r["status"] = st
        save(d)
        print(f'{rid} -> {st}')
    elif args[0] == "rec-add":
        prio = args[1]
        title, why, impact, cta = [s.strip() for s in " ".join(args[2:]).split("|")]
        d = load()
        r = add_rec(d, prio, title, why, impact, cta)
        save(d)
        print(f"added {r['id']}")
    elif args[0] == "taste":
        d = load()
        for (b, pillar), c in sorted(taste(d, args[1] if len(args) > 1 else None).items()):
            print(f'{b:12} {pillar:22} ✓{c["approve"]:2}  ✗{c["skip"]:2}  ↷{c["later"]:2}')
    elif args[0] == "sync-fallback":
        sync_fallback()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
