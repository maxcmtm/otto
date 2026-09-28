#!/usr/bin/env python3
"""Autopilot platform state CLI. All writes to data.json go through here.

Usage:
  ap.py list [brand]
  ap.py pending
  ap.py add <brand> <pillar> <platform> <slot ISO> <hook...>
  ap.py status <post-id> <draft|pending_approval|approved|scheduled|published|skipped>
  ap.py recs              # list recommendations
  ap.py rec <rec-id> <proposed|approved|dismissed|done>
  ap.py rec-add <P0|P1|P2> <title> | <why> | <impact> | <cta>
  ap.py sync-fallback     # re-embed data.json into index.html fallback block
"""
import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).parent
DATA = HERE / "data.json"
HTML = HERE / "index.html"
STATUSES = {"draft","pending_approval","approved","scheduled","published","skipped"}

def load(): return json.loads(DATA.read_text())
def save(d):
    d["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    sync_fallback(d)

def sync_fallback(d=None):
    d = d or load()
    html = HTML.read_text()
    blob = json.dumps(d, ensure_ascii=False)
    new = re.sub(r'(<script id="fallback-data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    HTML.write_text(new)
    print("fallback synced")

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("list","pending"):
        d = load()
        posts = d["posts"]
        if args and args[0] == "pending":
            posts = [p for p in posts if p["status"] == "pending_approval"]
        elif len(args) > 1:
            posts = [p for p in posts if p["brand"] == args[1]]
        for p in posts:
            print(f'{p["id"]:8} {p["brand"]:12} {p["status"]:17} {p["slot"]:17} {p["hook"]}')
        print(f'-- {len(posts)} posts')
    elif args[0] == "add":
        brand, pillar, platform, slot = args[1:5]
        hook = " ".join(args[5:])
        d = load()
        assert any(b["id"] == brand for b in d["brands"]), f"unknown brand {brand}"
        prefix = brand[:2]
        n = max([int(p["id"].split("-")[1]) for p in d["posts"] if p["id"].startswith(prefix)] or [0]) + 1
        pid = f"{prefix}-{n:03d}"
        d["posts"].append({"id": pid, "brand": brand, "pillar": pillar, "platform": platform,
                           "hook": hook, "status": "draft", "slot": slot})
        save(d)
        print(f"added {pid}")
    elif args[0] == "status":
        pid, st = args[1], args[2]
        assert st in STATUSES, f"bad status {st}"
        d = load()
        p = next(p for p in d["posts"] if p["id"] == pid)
        p["status"] = st
        save(d)
        print(f'{pid} -> {st}')
    elif args[0] == "recs":
        for r in load().get("recommendations", []):
            print(f'{r["id"]:8} {r["priority"]:3} {r["status"]:10} {r["title"]}')
    elif args[0] == "rec":
        rid, st = args[1], args[2]
        assert st in {"proposed","approved","dismissed","done"}, f"bad status {st}"
        d = load()
        r = next(r for r in d["recommendations"] if r["id"] == rid)
        r["status"] = st
        save(d)
        print(f'{rid} -> {st}')
    elif args[0] == "rec-add":
        prio = args[1]
        assert prio in {"P0","P1","P2"}, f"bad priority {prio}"
        title, why, impact, cta = [s.strip() for s in " ".join(args[2:]).split("|")]
        d = load()
        n = max([int(r["id"].split("-")[1]) for r in d.get("recommendations", [])] or [0]) + 1
        rid = f"rec-{n:03d}"
        d.setdefault("recommendations", []).append({"id": rid, "priority": prio, "title": title,
            "why": why, "impact": impact, "cta": cta, "status": "proposed"})
        save(d)
        print(f"added {rid}")
    elif args[0] == "sync-fallback":
        sync_fallback()
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
