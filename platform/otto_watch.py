#!/usr/bin/env python3
"""Otto proactive engine: the morning metrics snapshot, the Telegram morning report, and drop / deadline alerts.

  otto_watch.py snapshot              -> append today's metrics history snapshot (otto_cron watch-report, 07:30 owner time)
  otto_watch.py report [--brand B]    -> the Telegram morning report (otto_report: the same content as the 07:35 e-mail, in
                                         the brand's comms_lang) for every brand whose approvals include Telegram, + snapshot.
                                         The scheduled 07:35 brand-time send is otto_cron morning-report (otto_report.py send);
                                         this command sends now, by hand, and never twice the same local day.
  otto_watch.py watch                 -> hourly guard: metric drops vs 7-day avg, missed publishes, approvals about to miss
                                         their slot. Sends only when something is wrong — each alert in its brand's comms_lang.

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
import otto_i18n as i18n
import otto_paths
import otto_publish

HERE = Path(__file__).parent
HIST = ap.DATA.parent / "metrics_history.jsonl"      # next to data.json (OTTO_DATA), like publish.log
STATE = ap.DATA.parent / ".watch-state.json"
OCLAW = "/home/ubuntu/.npm-global/bin/openclaw"
TARGET = "590113904"
DASH = otto_paths.app_url()          # the client app: app.<OTTO_DOMAIN>/ on the new server (OTTO_PUBLIC_BASE is the landing there)
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


def fmt_slot(s, t=None):
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return s
    return t.day_time(dt) if t else dt.strftime("%d/%m %H:%M")


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


def report(bid=None, force=False):
    """The Telegram morning report, now: the snapshot, then otto_report's message for each brand whose approvals include
    Telegram (or just `bid`). The 07:35 brand-time send is the otto_cron morning-report job."""
    import otto_email, otto_report
    d = load_data()
    snapshot(d)
    sent = 0
    for b in d.get("brands", []):
        if not isinstance(b, dict) or not b.get("id") or (bid and b["id"] != bid):
            continue
        if "telegram" not in otto_email.approval_channels(b) or otto_report.skip_reason(d, b):
            continue
        r = otto_report.send_telegram(b["id"], force=force)
        sent += 1 if r.get("sent") else 0
    print(f"-- {sent} Telegram report(s) sent")
    return sent


def watch():
    d = load_data()
    state = load(STATE, {})
    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc)
    alerts = []
    with_creds = {b["id"] for b in d.get("brands", []) if otto_publish.creds(b["id"])}

    brands = {b["id"]: b for b in d.get("brands", []) if isinstance(b, dict) and b.get("id")}
    tr = lambda bid: i18n.Tr.for_brand(brands[bid]) if bid in brands else i18n.Tr()
    hook = lambda p: (p.get("hook_en") if tr(p.get("brand")).lang == "en" else None) or p.get("hook", "")[:50]
    for brand, k, v, base in drops(history()):
        key = f"drop:{brand}:{k}:{today}"
        if key not in state:
            state[key] = 1
            t = tr(brand)
            alerts.append((t, t("alert.drop", brand=(brands.get(brand) or {}).get("name") or brand,
                                metric=t("metric." + k) if t.has("metric." + k) else k, value=t.num(v), pct=DROP_PCT, avg=t.num(base))))

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
                t = tr(p.get("brand"))
                alerts.append((t, t("alert.stuck", hook=hook(p))))
        if p["status"] == "pending_approval" and 0 < hrs <= 6:
            key = f"slot-soon:{p['id']}"
            if key not in state:
                state[key] = 1
                t = tr(p.get("brand"))
                alerts.append((t, t("alert.slot_soon", n=max(1, round(hrs)), hook=hook(p),
                                    when=fmt_slot(p['slot'], t) if not slot else t.day_time(slot.astimezone(ap.brand_tz(brands.get(p.get("brand"))))))))
        # missed-publish only makes sense once a publishing channel is actually connected: the dashboard's
        # connections[] list, or the brand's Meta credentials (brand-add never adds a connections[] entry)
        connected = any(c.get("status") == "connected" for c in d.get("connections", [])) or p.get("brand") in with_creds
        if connected and p["status"] in ("approved", "scheduled") and hrs < -2:
            key = f"missed:{p['id']}"
            if key not in state:
                state[key] = 1
                t = tr(p.get("brand"))
                alerts.append((t, t("alert.missed", hook=hook(p), when=t.day_time(slot.astimezone(ap.brand_tz(brands.get(p.get("brand"))))))))

    # prune old dedup keys (keep 14 days)
    cutoff = (now - timedelta(days=14)).date().isoformat()
    state = {k: v for k, v in state.items() if not k.split(":")[-1][:4].isdigit() or k.split(":")[-1] >= cutoff}
    STATE.write_text(json.dumps(state))
    if alerts:
        by_lang = {}
        for t, text in alerts:
            by_lang.setdefault(t.lang, (t, []))[1].append(text)
        for t, texts in by_lang.values():              # one message per language (a per-client instance has one)
            send(f"*{t('alert.head')}*\n\n" + "\n\n".join(texts) + f"\n\n{DASH}")
        print(f"sent {len(alerts)} alerts")
    else:
        print("all clear")


def snapshot_cmd():
    rows = snapshot(load_data())
    print(f"metrics snapshot: {rows[-1].get('date') if rows else '—'} ({len(rows)} day(s) in {HIST.name})")


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = a[0] if a else "watch"
    if mode == "report":
        report(a[a.index("--brand") + 1] if "--brand" in a and a.index("--brand") + 1 < len(a) else None, force="--force" in a)
    else:
        {"snapshot": snapshot_cmd, "watch": watch}[mode]()
