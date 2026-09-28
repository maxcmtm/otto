#!/usr/bin/env python3
"""Otto month planner — "Otto builds your month".

  otto_plan.py build <brand> <YYYY-MM> [--per-week 12] [--platforms fb,ig] [--no-stories] [--dry] [--replace]
  otto_plan.py fill  <brand> <YYYY-MM> <copy.json> [--pending]
  otto_plan.py show  <brand> <YYYY-MM>

build: turns the brand's pillars + posting slots into a full month of draft posts in
       data.json (one per slot, pillar rotation, platform alternation, format per pillar)
       and writes brands/<slug>/content-plan-YYYY-MM.md — a skeleton the content agent
       (Quill / otto-copy-engine) fills with hooks + captions.
fill:  imports that copy back — a JSON list of {"id","hook","caption","visual_brief","hashtags"}.
       --pending moves filled posts to pending_approval (i.e. straight to the owner's deck).
show:  prints the month grid.

Slots come from brands[].slots in data.json (weekday -> ["HH:MM", ...]); defaults below.
Stories: an Instagram story slot on brands[].story_days (default mon/wed/fri) at story_time (12:00),
on top of the weekly feed quota. `--no-stories` turns them off.
Pure stdlib. Writes through ap.py so the dashboard fallback stays in sync.
"""
import calendar, json, sys
from datetime import date
from pathlib import Path

import ap

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"

DEFAULT_SLOTS = {"mon": ["09:00", "18:00"], "tue": ["09:00", "18:00"], "wed": ["09:00", "18:00"],
                 "thu": ["09:00", "18:00"], "fri": ["09:00", "18:00"], "sat": ["10:00"], "sun": ["09:00"]}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# pillar -> default format (the creative engine may override per post)
FORMAT_FOR = {"education": "carousel", "proof": "post", "trust": "post", "use": "post",
              "product": "post", "engagement": "story", "story": "post", "myth": "post",
              "community": "post", "behind": "reel", "career": "post"}


MIX_BY_INDUSTRY = [("education", {"post": .4, "carousel": .4, "reel": .2}), ("coaching", {"post": .4, "carousel": .4, "reel": .2}),
                   ("legal", {"post": .5, "carousel": .35, "reel": .15}), ("saas", {"post": .4, "carousel": .4, "reel": .2}),
                   ("restaurant", {"post": .4, "carousel": .15, "reel": .45}), ("hotel", {"post": .4, "carousel": .15, "reel": .45}),
                   ("fitness", {"post": .35, "carousel": .2, "reel": .45}), ("beauty", {"post": .4, "carousel": .2, "reel": .4}),
                   ("real estate", {"post": .4, "carousel": .3, "reel": .3}), ("e-commerce", {"post": .45, "carousel": .3, "reel": .25}),
                   ("cbd", {"post": .45, "carousel": .35, "reel": .2})]
DEFAULT_MIX = {"post": .5, "carousel": .3, "reel": .2}


def format_mix(b):
    """brands[].format_mix wins; else competitors' observed formats blended with the industry default."""
    if b.get("format_mix"):
        return b["format_mix"]
    base = DEFAULT_MIX
    industry = ""
    sj = BRANDS / b["id"] / "scan.json"
    if sj.exists():
        industry = json.loads(sj.read_text()).get("industry", "").lower()
    for k, mix in MIX_BY_INDUSTRY:
        if k in industry:
            base = mix; break
    cj = BRANDS / b["id"] / "competitors.json"
    if cj.exists():
        seen = {}
        for it in json.loads(cj.read_text()):
            for f, n in (it.get("formats") or {}).items():
                seen[f] = seen.get(f, 0) + n
        tot = sum(seen.values())
        if tot >= 10:                                  # enough observed competitor posts to matter
            obs = {f: seen.get(f, 0) / tot for f in ("post", "carousel", "reel")}
            base = {f: round(0.5 * base.get(f, 0) + 0.5 * obs.get(f, 0), 2) for f in base}
    return base


def mix_pattern(mix, n=10):
    """Deterministic interleaving of formats for n slots (largest remainder, then spread out)."""
    counts = {f: int(round(mix.get(f, 0) * n)) for f in ("post", "carousel", "reel")}
    while sum(counts.values()) < n: counts["post"] += 1
    while sum(counts.values()) > n: counts[max(counts, key=counts.get)] -= 1
    seq, acc = [], {f: 0.0 for f in counts}
    for _ in range(n):
        for f in counts:
            acc[f] += counts[f] / n
        f = max(acc, key=acc.get); acc[f] -= 1; seq.append(f)
    return seq


def fmt_for(pillar, idx, pattern=None):
    if pattern:
        return pattern[idx % len(pattern)]
    key = pillar.lower()
    for k, v in FORMAT_FOR.items():
        if k in key:
            return v
    return "reel" if idx % 6 == 5 else "post"


def month_days(ym):
    y, m = [int(x) for x in ym.split("-")]
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def build(bid, ym, per_week=12, platforms=("fb", "ig"), dry=False, replace=False, stories=True):
    d = ap.load()
    b = ap.brand(d, bid)
    assert b, f"unknown brand {bid}"
    pillars = b.get("pillars") or ["Education", "Trust & proof", "Use-case", "Product", "Engagement"]
    slots = b.get("slots") or DEFAULT_SLOTS
    existing = [p for p in d["posts"] if p["brand"] == bid and p.get("plan") == ym]
    if existing and not replace:
        sys.exit(f"{bid} already has {len(existing)} posts planned for {ym} — use --replace to rebuild drafts")
    if replace:
        d["posts"] = [p for p in d["posts"] if not (p["brand"] == bid and p.get("plan") == ym and p["status"] == "draft")]

    plan, week_count, idx = [], {}, 0
    pattern = mix_pattern(format_mix(b))
    story_days = b.get("story_days") if b.get("story_days") is not None else ["mon", "wed", "fri"]
    story_time = b.get("story_time") or "12:00"
    for day in month_days(ym):
        wk = day.isocalendar()[1]
        if stories and DAYS[day.weekday()] in story_days and "ig" in platforms:
            plan.append({"pillar": pillars[(idx + 2) % len(pillars)], "platform": "ig", "format": "story",
                         "slot": f"{day.isoformat()}T{story_time}"})     # stories don't count against the weekly quota
        for t in slots.get(DAYS[day.weekday()], []):
            if week_count.get(wk, 0) >= per_week:
                break
            pillar = pillars[idx % len(pillars)]
            platform = platforms[idx % len(platforms)]
            fmt = fmt_for(pillar, idx, pattern)
            if fmt == "story":
                fmt = "post"          # feed slots never become stories; stories have their own daily slot
            if fmt in ("reel", "carousel") and "ig" in platforms:
                platform = "ig"          # stories/reels/carousels live on Instagram
            plan.append({"pillar": pillar, "platform": platform, "format": fmt,
                         "slot": f"{day.isoformat()}T{t}"})
            week_count[wk] = week_count.get(wk, 0) + 1
            idx += 1

    # the base package promises four explainer reels a month — top up if the mix fell short
    reels = [x for x in plan if x["format"] == "reel"]
    if len(reels) < 4:
        for x in [x for x in plan if x["format"] == "post" and x["platform"] == "ig"][:4 - len(reels)]:
            x["format"] = "reel"
    if dry:
        for p in plan:
            print(f'{p["slot"]}  {p["platform"]:2}  {p["format"]:8}  {p["pillar"]}')
        counts = {}
        for x in plan: counts[x["format"]] = counts.get(x["format"], 0) + 1
        print(f"-- {len(plan)} posts for {bid} · {ym} (dry run) · mix {format_mix(b)} · {counts}")
        return plan

    created = []
    for p in plan:
        created.append(ap.add_post(d, bid, p["pillar"], p["platform"], p["slot"], "",
                                   format=p["format"], plan=ym,
                                   brief=f'{p["pillar"]} · {p["format"]} · angle TBD by Quill · visual on-brand per brand-profile.md'))
    ap.save(d)
    write_plan_md(b, ym, created)
    print(f"planned {len(created)} draft posts for {bid} · {ym} → {plan_path(bid, ym)}")
    return created


def plan_path(bid, ym):
    return BRANDS / bid / f"content-plan-{ym}.md"


def write_plan_md(b, ym, posts):
    path = plan_path(b["id"], ym)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Content plan — {b['name']} · {ym}",
             f"Generated by otto_plan.py · {len(posts)} slots · pillars: {', '.join(b.get('pillars', []))}",
             "Fill the hook + caption per row (otto-copy-engine), then `otto_plan.py fill <brand> <month> copy.json --pending`.",
             "", "| id | slot | platform | format | pillar | hook |", "|---|---|---|---|---|---|"]
    for p in posts:
        lines.append(f"| {p['id']} | {p['slot'].replace('T', ' ')} | {p['platform']} | {p.get('format', 'post')} | {p['pillar']} | {p.get('hook') or '_TBD_'} |")
    path.write_text("\n".join(lines) + "\n")


def fill(bid, ym, copy_file, pending=False):
    d = ap.load()
    items = json.loads(Path(copy_file).read_text())
    n = 0
    for it in items:
        p = ap.post(d, it["id"])
        if not p or p["brand"] != bid:
            sys.exit(f"unknown post {it.get('id')} for {bid}")
        for k in ("hook", "caption", "visual_brief", "hashtags", "image", "format"):
            if k in it:
                p[k] = it[k]
        if pending and p.get("hook") and p.get("caption"):
            p["status"] = "pending_approval"
        n += 1
    ap.save(d)
    b = ap.brand(d, bid)
    write_plan_md(b, ym, [p for p in d["posts"] if p["brand"] == bid and p.get("plan") == ym])
    print(f"filled {n} posts for {bid} · {ym}" + (" → pending_approval" if pending else ""))


def show(bid, ym):
    d = ap.load()
    posts = sorted([p for p in d["posts"] if p["brand"] == bid and p.get("plan") == ym], key=lambda p: p["slot"])
    for p in posts:
        print(f'{p["id"]:8} {p["slot"]:16} {p["platform"]:2} {p.get("format", "post"):8} {p["status"]:16} {p["pillar"]:18} {p.get("hook", "")[:60]}')
    print(f"-- {len(posts)} posts")


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        print(__doc__); return
    cmd, bid, ym = a[0], a[1], a[2]
    if cmd == "build":
        pw = int(a[a.index("--per-week") + 1]) if "--per-week" in a else 12
        pl = tuple(a[a.index("--platforms") + 1].split(",")) if "--platforms" in a else ("fb", "ig")
        build(bid, ym, pw, pl, dry="--dry" in a, replace="--replace" in a, stories="--no-stories" not in a)
    elif cmd == "fill":
        fill(bid, ym, a[3], pending="--pending" in a)
    elif cmd == "show":
        show(bid, ym)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
