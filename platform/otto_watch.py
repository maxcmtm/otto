#!/usr/bin/env python3
"""Otto proactive engine: daily performance report + drop/deadline alerts to Max's Telegram.

  otto_watch.py report   -> morning digest (cron 06:30 UTC) + append metrics history snapshot
  otto_watch.py watch    -> hourly guard: metric drops vs 7-day avg, missed publishes,
                            approvals about to miss their slot. Sends only when something is wrong.

State: metrics_history.jsonl (one snapshot/day), .watch-state.json (alert dedup, 1/day per key).
Sending goes through the OpenClaw CLI (same pattern as gateway_watchdog.sh).
"""
import json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data.json"
HIST = HERE / "metrics_history.jsonl"
STATE = HERE / ".watch-state.json"
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
    r = subprocess.run([OCLAW, "message", "send", "--channel", "telegram",
                        "--account", "maximus", "--target", TARGET, "--message", text],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:  # fall back to default account routing
        r = subprocess.run([OCLAW, "message", "send", "--channel", "telegram",
                            "--target", TARGET, "--message", text],
                           capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print("send failed:", r.stderr[-400:], file=sys.stderr)
    return r.returncode == 0


def fmt_slot(s):
    try:
        return datetime.fromisoformat(s).strftime("%d/%m %H:%M")
    except Exception:
        return s


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
    latest, prior = rows[-1]["metrics"], rows[-8:-1]
    for brand, m in latest.items():
        for k, v in m.items():
            vals = [r["metrics"].get(brand, {}).get(k, 0) for r in prior]
            base = sum(vals) / len(vals) if vals else 0
            if base >= MIN_BASE and v < base * (1 - DROP_PCT / 100):
                out.append((brand, k, v, base))
    return out


def report():
    d = load(DATA, {})
    rows = snapshot(d)
    now = datetime.now(timezone.utc)
    posts = d.get("posts", [])
    pending = [p for p in posts if p["status"] == "pending_approval"]
    next24 = [p for p in posts if p["status"] in ("approved", "scheduled")
              and 0 <= (datetime.fromisoformat(p["slot"]).replace(tzinfo=timezone.utc) - now).total_seconds() < 86400]
    yesterday = (now - timedelta(days=1)).date()
    pub_y = [p for p in posts if p["status"] == "published"
             and datetime.fromisoformat(p["slot"]).date() >= yesterday]
    p0 = [r for r in d.get("recommendations", []) if r.get("priority") == "P0" and r.get("status") == "proposed"]

    lines = [f"☀️ *דוח Otto יומי* · {now.strftime('%d/%m')}"]
    lines.append(f"\n✍️ ממתינים לאישור שלך: *{len(pending)}*" if pending else "\n✍️ תור האישורים נקי ✓")
    for p in pending[:4]:
        lines.append(f"  · {p['hook'][:60]} ({fmt_slot(p['slot'])})")
    if next24:
        lines.append(f"🗓 יוצאים ב-24ש הקרובות: *{len(next24)}*")
    if pub_y:
        lines.append(f"📤 פורסמו מאתמול: {len(pub_y)}")
    metr = d.get("metrics", {})
    live = {b: m for b, m in metr.items() if sum(m.values()) > 0}
    if live:
        lines.append("\n📊 *ביצועים:*")
        brand_names = {b["id"]: b["name"] for b in d.get("brands", [])}
        for b, m in live.items():
            lines.append(f"  {brand_names.get(b, b)}: reach {m.get('reach',0):,} · clicks {m.get('clicks',0):,} · leads {m.get('leads',0)}")
        for brand, k, v, base in drops(rows):
            lines.append(f"  ⚠️ {brand_names.get(brand, brand)}: {k} ירד ל-{v:,} (ממוצע שבועי {base:,.0f})")
    else:
        lines.append("📊 מדדים יופעלו עם השבוע המפורסם הראשון.")
    if p0:
        lines.append(f"\n🚧 חוסמים (P0): " + " · ".join(r["title"] for r in p0[:2]))
    lines.append(f"\n{DASH}")
    send("\n".join(lines))


def watch():
    d = load(DATA, {})
    state = load(STATE, {})
    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc)
    alerts = []

    for brand, k, v, base in drops(history()):
        key = f"drop:{brand}:{k}:{today}"
        if key not in state:
            state[key] = 1
            alerts.append(f"📉 ירידה ב-{brand}: {k} עומד על {v:,} — {DROP_PCT}%+ מתחת לממוצע השבועי ({base:,.0f}). שווה הצצה.")

    for p in d.get("posts", []):
        slot = datetime.fromisoformat(p["slot"]).replace(tzinfo=timezone.utc)
        hrs = (slot - now).total_seconds() / 3600
        if p["status"] == "pending_approval" and 0 < hrs <= 6:
            key = f"slot-soon:{p['id']}"
            if key not in state:
                state[key] = 1
                alerts.append(f"⏰ \"{p['hook'][:50]}\" מתוזמן ל-{fmt_slot(p['slot'])} ועדיין לא אושר — {hrs:.0f} שעות לאשר.")
        # missed-publish only makes sense once a publishing channel is actually connected
        connected = any(c.get("status") == "connected" for c in d.get("connections", []))
        if connected and p["status"] in ("approved", "scheduled") and hrs < -2:
            key = f"missed:{p['id']}"
            if key not in state:
                state[key] = 1
                alerts.append(f"🚨 \"{p['hook'][:50]}\" היה אמור לצאת ב-{fmt_slot(p['slot'])} ולא פורסם. בודק את הצנרת.")

    # prune old dedup keys (keep 14 days)
    cutoff = (now - timedelta(days=14)).date().isoformat()
    state = {k: v for k, v in state.items() if not k.split(":")[-1][:4].isdigit() or k.split(":")[-1] >= cutoff}
    STATE.write_text(json.dumps(state))
    if alerts:
        send("🔔 *Otto Alert*\n\n" + "\n\n".join(alerts) + f"\n\n{DASH}")
        print(f"sent {len(alerts)} alerts")
    else:
        print("all clear")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
    {"report": report, "watch": watch}[mode]()
