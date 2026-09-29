#!/usr/bin/env python3
"""Otto proactive engine: daily performance report + drop/deadline alerts to Max's Telegram.

  otto_watch.py report   -> morning digest (cron 06:30 UTC) + append metrics history snapshot
  otto_watch.py watch    -> hourly guard: metric drops vs 7-day avg, missed publishes,
                            approvals about to miss their slot. Sends only when something is wrong.

State: metrics_history.jsonl (one snapshot/day), .watch-state.json (alert dedup, 1/day per key) — both next to data.json.
Reads data.json through ap (OTTO_DATA respected); slot times are brand-local (ap.slot_dt, brands[].tz).
Only numeric metric values are compared / summed (Graph can hand back None, dicts or strings).
Sending: the brand owner's Telegram bot ($OTTO_SECRETS/telegram.json, same as the approval cards — on a per-client instance
that is the client, not Max); only without a bot config does it fall back to the OpenClaw CLI (Max's chat).
"""
import json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_publish

HERE = Path(__file__).parent
HIST = ap.DATA.parent / "metrics_history.jsonl"      # next to data.json (OTTO_DATA), like publish.log
STATE = ap.DATA.parent / ".watch-state.json"
OCLAW = "/home/ubuntu/.npm-global/bin/openclaw"
TARGET = "590113904"
DASH = "https://dash.monyflow.work/otto/"
DROP_PCT = 30          # alert when a metric falls >=30% vs 7-day average
MIN_BASE = 50          # ...only if the 7-day average is at least this (avoid zero-noise)


def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def send(text):
    try:
        import otto_telegram as tg
        tok, chat = tg.config()
        if tok and chat:
            tg.send(text.replace("*", ""))      # plain text: a Markdown parse error would drop the whole report
            return True
    except Exception as e:
        print("telegram send failed:", e, file=sys.stderr)
    try:
        r = subprocess.run([OCLAW, "message", "send", "--channel", "telegram",
                            "--account", "maximus", "--target", TARGET, "--message", text],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:  # fall back to default account routing
            r = subprocess.run([OCLAW, "message", "send", "--channel", "telegram",
                                "--target", TARGET, "--message", text],
                               capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print("send failed (no Telegram bot config, no OpenClaw CLI):", e, file=sys.stderr)
        return False
    if r.returncode != 0:
        print("send failed:", r.stderr[-400:], file=sys.stderr)
    return r.returncode == 0


def fmt_slot(s):
    try:
        return datetime.fromisoformat(s).strftime("%d/%m %H:%M")
    except Exception:
        return s


def load_data():
    try:
        return ap.load()
    except Exception:
        return {}


def slot_of(d, p):
    return ap.slot_dt(p, ap.brand(d, p.get("brand")))


def numeric(m):
    return {k: v for k, v in (m or {}).items() if ap.num(v) is not None}


def history():
    rows = []
    if HIST.exists():
        for line in HIST.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def snapshot(d):
    today = datetime.now(timezone.utc).date().isoformat()
    rows = history()
    if rows and rows[-1].get("date") == today:
        return rows
    rows.append({"date": today, "metrics": d.get("metrics", {})})
    with HIST.open("a") as f:
        f.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
    return rows


def drops(rows):
    """Compare latest snapshot vs mean of up to 7 prior days."""
    out = []
    if len(rows) < 4:
        return out
    latest, prior = rows[-1].get("metrics") or {}, rows[-8:-1]
    for brand, m in latest.items():
        for k, v in numeric(m).items():
            v = ap.num(v)
            vals = [ap.num(((r.get("metrics") or {}).get(brand) or {}).get(k)) for r in prior]
            vals = [x for x in vals if x is not None]
            base = sum(vals) / len(vals) if vals else 0
            if base >= MIN_BASE and v < base * (1 - DROP_PCT / 100):
                out.append((brand, k, v, base))
    return out


def report():
    d = load_data()
    rows = snapshot(d)
    now = datetime.now(timezone.utc)
    posts = d.get("posts", [])
    pending = [p for p in posts if p["status"] == "pending_approval"]
    next24 = [p for p in posts if p["status"] in ("approved", "scheduled") and slot_of(d, p)
              and 0 <= (slot_of(d, p) - now).total_seconds() < 86400]
    yesterday = (now - timedelta(days=1)).date()
    pub_y = [p for p in posts if p["status"] == "published" and slot_of(d, p)
             and slot_of(d, p).astimezone(timezone.utc).date() >= yesterday]
    p0 = [r for r in d.get("recommendations", []) if r.get("priority") == "P0" and r.get("status") == "proposed"]

    lines = [f"*Otto daily* · {now.strftime('%a %d %b')}"]
    lines.append(f"\nWaiting for you: *{len(pending)}*" if pending else "\nNothing is waiting for you.")
    for p in pending[:4]:
        lines.append(f"  · {p.get('hook', '')[:60]} ({fmt_slot(p['slot'])})")
    if next24:
        lines.append(f"Publishing in the next 24 h: *{len(next24)}*")
    if pub_y:
        lines.append(f"Published since yesterday: {len(pub_y)}")
    metr = d.get("metrics", {})
    live = {b: numeric(m) for b, m in metr.items() if sum(ap.num(v) for v in numeric(m).values()) > 0}
    if live:
        lines.append("\n*Performance*")
        brand_names = {b["id"]: b["name"] for b in d.get("brands", [])}
        for b, m in live.items():
            lines.append(f"  {brand_names.get(b, b)}: reach {m.get('reach',0):,} · clicks {m.get('clicks',0):,} · leads {m.get('leads',0)}")
        for brand, k, v, base in drops(rows):
            lines.append(f"  Watch: {brand_names.get(brand, brand)} {k} is down to {v:,} (7-day average {base:,.0f})")
    else:
        lines.append("Metrics start with the first published week.")
    if p0:
        lines.append(f"\nNeeds you: " + " · ".join(r["title"] for r in p0[:2]))
    lines.append(f"\n{DASH}")
    send("\n".join(lines))


def watch():
    d = load_data()
    state = load(STATE, {})
    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc)
    alerts = []
    with_creds = {b["id"] for b in d.get("brands", []) if otto_publish.creds(b["id"])}

    for brand, k, v, base in drops(history()):
        key = f"drop:{brand}:{k}:{today}"
        if key not in state:
            state[key] = 1
            alerts.append(f"Drop at {brand}: {k} is at {v:,}, {DROP_PCT}%+ below the 7-day average ({base:,.0f}). Worth a look.")

    for p in d.get("posts", []):
        slot = slot_of(d, p)
        if slot is None:
            continue
        hrs = (slot - now).total_seconds() / 3600
        if p["status"] == "publishing":
            key = f"stuck:{p['id']}"
            since = ap.parse_iso(p.get("publishing_at"))
            if key not in state and (since is None or since.tzinfo is None or now - since > timedelta(minutes=30)):
                state[key] = 1
                alerts.append(f"“{p.get('hook_en') or p.get('hook', '')[:50]}” was sent to Meta but never confirmed. Otto will not retry it — check the page.")
        if p["status"] == "pending_approval" and 0 < hrs <= 6:
            key = f"slot-soon:{p['id']}"
            if key not in state:
                state[key] = 1
                alerts.append(f"“{p.get('hook_en') or p.get('hook', '')[:50]}” is slotted for {fmt_slot(p['slot'])} and still not approved. {hrs:.0f} hours left.")
        # missed-publish only makes sense once a publishing channel is actually connected: the dashboard's
        # connections[] list, or the brand's Meta credentials (brand-add never adds a connections[] entry)
        connected = any(c.get("status") == "connected" for c in d.get("connections", [])) or p.get("brand") in with_creds
        if connected and p["status"] in ("approved", "scheduled") and hrs < -2:
            key = f"missed:{p['id']}"
            if key not in state:
                state[key] = 1
                alerts.append(f"“{p.get('hook_en') or p.get('hook', '')[:50]}” was due {fmt_slot(p['slot'])} and did not publish. Checking the pipeline.")

    # prune old dedup keys (keep 14 days)
    cutoff = (now - timedelta(days=14)).date().isoformat()
    state = {k: v for k, v in state.items() if not k.split(":")[-1][:4].isdigit() or k.split(":")[-1] >= cutoff}
    STATE.write_text(json.dumps(state))
    if alerts:
        send("*Otto alert*\n\n" + "\n\n".join(alerts) + f"\n\n{DASH}")
        print(f"sent {len(alerts)} alerts")
    else:
        print("all clear")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
    {"report": report, "watch": watch}[mode]()
