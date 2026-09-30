#!/usr/bin/env python3
"""Telegram alert for a failed Otto unit. systemd runs it through OnFailure=otto-alert@%N.service:

  otto_alert.py <unit>          # e.g. otto-job@publish, otto-api, otto-backup
  otto_alert.py --test          # send a test message (checks the bot config end to end)

Bot: $OTTO_SECRETS/telegram.json {"bot_token", "owner_chat_id"} (the same file the approval loop uses), or env
TELEGRAM_BOT_TOKEN / OTTO_OWNER_CHAT_ID; "alert_chat_id" in that file (or OTTO_ALERT_CHAT_ID) sends alerts to a separate ops chat.
No bot config → it says so and exits 0 (the failure is still in `systemctl --failed` and the owner console).
Message: host, unit, and for an engine job (otto-job@<job>) its heartbeat — which brands failed and their last output line —
otherwise the unit's last journal lines. The same unit alerts at most once per OTTO_ALERT_QUIET_MIN minutes (default 180;
state in .alert-state.json next to data.json), so a publisher failing every 15 minutes is one message, not twelve.
The token only ever goes into the HTTPS request to api.telegram.org — never printed, never on a command line.
Stdlib only. bootstrap.sh installs a root-owned copy at /usr/local/lib/otto/otto_alert.py, so alerts work even when a release
breaks the checkout.
"""
import json, os, socket, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("OTTO_DATA") or "/var/lib/otto/data.json").parent
SECRETS = Path(os.environ.get("OTTO_SECRETS") or "/etc/otto/secrets")
HEARTBEATS = Path(os.environ.get("OTTO_HEARTBEATS") or DATA_DIR / "heartbeats.json")
STATE = DATA_DIR / ".alert-state.json"
QUIET_MIN = float(os.environ.get("OTTO_ALERT_QUIET_MIN") or 180)
MAX_TEXT = 3500


def bot():
    try:
        c = json.loads((SECRETS / "telegram.json").read_text())
    except (OSError, ValueError):
        c = {}
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or c.get("bot_token")
    chat = os.environ.get("OTTO_ALERT_CHAT_ID") or c.get("alert_chat_id") or os.environ.get("OTTO_OWNER_CHAT_ID") or c.get("owner_chat_id")
    return (str(tok).strip() if tok else None), (str(chat).strip() if chat else None)


def send(text):
    tok, chat = bot()
    if not tok or not chat:
        print("otto-alert: no Telegram bot config (telegram.json bot_token + owner_chat_id) — not sent")
        return None
    body = json.dumps({"chat_id": chat, "text": text[:MAX_TEXT], "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = json.loads(r.read() or b"{}").get("ok")
    except Exception as e:                                   # the exception text never contains the token (it is in the path)
        print(f"otto-alert: Telegram send failed: {type(e).__name__}")
        return False
    print("otto-alert: sent" if ok else "otto-alert: Telegram refused the message")
    return bool(ok)


def quiet(unit):
    """True when this unit already alerted within QUIET_MIN; otherwise records now."""
    try:
        st = json.loads(STATE.read_text())
    except (OSError, ValueError):
        st = {}
    now = time.time()
    if now - float(st.get(unit) or 0) < QUIET_MIN * 60:
        return True
    st = {k: v for k, v in st.items() if now - float(v or 0) < 7 * 86400}
    st[unit] = now
    try:
        tmp = STATE.with_name(STATE.name + ".tmp")
        tmp.write_text(json.dumps(st))
        os.replace(tmp, STATE)
    except OSError:
        pass
    return False


def job_lines(job):
    try:
        h = (json.loads(HEARTBEATS.read_text()).get("jobs") or {}).get(job) or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = [f"{job}: {h.get('summary') or h.get('status') or 'no heartbeat'}"]
    for bid, r in (h.get("brands") or {}).items():
        if isinstance(r, dict) and r.get("status") == "failed":
            last = (r.get("tail") or ["(no output)"])[-1]
            out.append(f"· {bid}: exit {r.get('exit')} — {last[:240]}")
    if int(h.get("fails_in_row") or 0) > 1:
        out.append(f"Failed {h['fails_in_row']} runs in a row.")
    return out


def journal(unit, n=12):
    try:
        r = subprocess.run(["journalctl", "-u", unit + ".service", "-n", str(n), "--no-pager", "-o", "cat"],
                           capture_output=True, text=True, timeout=20)
        return [l[:300] for l in r.stdout.splitlines() if l.strip()][-n:]
    except (OSError, subprocess.SubprocessError):
        return []


def main(a):
    host = socket.gethostname()
    if a[:1] == ["--test"]:
        r = send(f"Otto alert test from {host} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC — alerts reach this chat.")
        return 0 if r else 1
    if not a:
        print(__doc__)
        return 2
    unit = a[0][:-len(".service")] if a[0].endswith(".service") else a[0]
    if quiet(unit):
        print(f"otto-alert: {unit} already alerted in the last {QUIET_MIN:.0f} min — not sent again")
        return 0
    lines = [f"Otto alert · {unit} failed on {host} · {datetime.now(timezone.utc):%d %b %H:%M} UTC"]
    if unit.startswith("otto-job@"):
        job = unit.split("@", 1)[1]
        lines += job_lines(job) or journal(unit)
        lines.append(f"Logs: journalctl -u {unit} · otto logs {job}")
    else:
        lines += journal(unit)
        lines.append(f"Logs: journalctl -u {unit}")
    return 0 if send("\n".join(lines)) is not False else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
