#!/usr/bin/env python3
"""Otto Telegram loop — the approval surface, in code (no agent in the loop).

  otto_telegram.py send-cards [--brand <id>] [--hours 72] [--resend] [--dry]
  otto_telegram.py send-recs  [--dry]
  otto_telegram.py poll [--once] [--timeout 50]
  otto_telegram.py send "<text>"

send-cards: every post in pending_approval whose slot is within --hours and that has no card yet
            → photo (the visual) + caption + inline buttons  ✅ Approve · ❌ Skip · ✏️ Edit · ↷ Later
send-recs:  every proposed recommendation without a card → message + ✅ Approve · Not now
poll:       long-polls Bot API updates. Button taps → ap.decide / ap.rec (taste log, approved_via=telegram),
            the card is edited in place ("✅ Approved · publishes Sat 18:00") so the phone shows the state.
            ✏️ Edit → the owner replies in plain words → stored as an edit request (edit_requests[] in
            data.json, post back to draft) for Quill to rewrite and re-send.
Only the owner chat may decide (owner_chat_id). Config: $OTTO_SECRETS/telegram.json
{"bot_token": "...", "owner_chat_id": "590113904"} or env TELEGRAM_BOT_TOKEN / OTTO_OWNER_CHAT_ID.
State: .telegram-state.json (update offset). Public image base for photos: --base (dash.monyflow.work/otto/).
Pure stdlib. Writes through ap.py.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import ap

HERE = Path(__file__).parent
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
STATE = HERE / ".telegram-state.json"
BASE = "https://dash.monyflow.work/otto/"
TZ = ZoneInfo(os.environ.get("OTTO_TZ", "Asia/Jerusalem"))
PLAT = {"fb": "Facebook", "ig": "Instagram", "li": "LinkedIn"}


def config():
    f = SECRETS / "telegram.json"
    c = json.loads(f.read_text()) if f.exists() else {}
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or c.get("bot_token")
    chat = os.environ.get("OTTO_OWNER_CHAT_ID") or c.get("owner_chat_id")
    return tok, str(chat) if chat else None


def api(method, **params):
    tok, _ = config()
    if not tok:
        raise RuntimeError("no bot token (otto-secrets/telegram.json or TELEGRAM_BOT_TOKEN)")
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        out = json.loads(e.read().decode())
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out.get('description')}")
    return out["result"]


def slot_str(p):
    try:
        return datetime.fromisoformat(p["slot"]).strftime("%a %d %b %H:%M")
    except Exception:
        return p.get("slot", "")


def card_caption(d, p):
    b = ap.brand(d, p["brand"]) or {}
    why = p.get("why") or p.get("brief") or ""
    cap = (p.get("caption") or p.get("hook") or "").strip()
    head = f"{b.get('name', p['brand'])} · {PLAT.get(p['platform'], p['platform'])} · {slot_str(p)} · {p.get('pillar', '')}"
    text = f"{head}\n\n{cap}"
    if why:
        text += f"\n\n— Why this post: {why[:200]}"
    return text[:1000]


def post_keyboard(pid):
    return {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"otto:{pid}:approve"},
                                 {"text": "❌ Skip", "callback_data": f"otto:{pid}:skip"}],
                                [{"text": "✏️ Edit", "callback_data": f"otto:{pid}:edit"},
                                 {"text": "↷ Later", "callback_data": f"otto:{pid}:later"}]]}


def rec_keyboard(rid):
    return {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"otto:rec:{rid}:approve"},
                                 {"text": "Not now", "callback_data": f"otto:rec:{rid}:dismiss"}]]}


def send_cards(bid=None, hours=72, resend=False, dry=False, base=BASE):
    d = ap.load()
    _, chat = config()
    now = datetime.now(TZ)
    sent = 0
    for p in sorted(d["posts"], key=lambda x: x["slot"]):
        if p["status"] != "pending_approval" or (bid and p["brand"] != bid):
            continue
        if p.get("tg_message_id") and not resend:
            continue
        try:
            slot = datetime.fromisoformat(p["slot"]).replace(tzinfo=TZ)
        except Exception:
            continue
        if slot > now + timedelta(hours=hours):
            continue
        cap = card_caption(d, p)
        img = p.get("image")
        url = img if (img or "").startswith("http") else (base.rstrip("/") + "/" + img.lstrip("/") if img else None)
        print(f"{'WOULD SEND' if dry else 'SEND'} {p['id']} {slot_str(p)} {'photo' if url else 'text'} — {p.get('hook','')[:50]}")
        if dry:
            continue
        if url:
            r = api("sendPhoto", chat_id=chat, photo=url, caption=cap, reply_markup=post_keyboard(p["id"]))
        else:
            r = api("sendMessage", chat_id=chat, text=cap, reply_markup=post_keyboard(p["id"]))
        p["tg_message_id"] = r["message_id"]; p["tg_sent_at"] = ap.now_iso(); sent += 1
    if sent:
        ap.save(d)
    print(f"-- {sent} card(s) sent")


def send_recs(dry=False):
    d = ap.load()
    _, chat = config()
    sent = 0
    for r in d.get("recommendations", []):
        if r.get("status") != "proposed" or r.get("tg_message_id"):
            continue
        text = f"💡 Your agency recommends · {r['priority']}\n\n{r['title']}\n\n{r.get('why','')}\n\n↗ {r.get('impact','')}"
        print(f"{'WOULD SEND' if dry else 'SEND'} {r['id']} — {r['title'][:60]}")
        if dry:
            continue
        m = api("sendMessage", chat_id=chat, text=text[:4000], reply_markup=rec_keyboard(r["id"]))
        r["tg_message_id"] = m["message_id"]; sent += 1
    if sent:
        ap.save(d)
    print(f"-- {sent} recommendation card(s) sent")


def send(text):
    _, chat = config()
    return api("sendMessage", chat_id=chat, text=text[:4000])


def edit_card(chat, msg, p, note):
    """Freeze a decided card: drop the buttons and append the outcome."""
    try:
        api("editMessageReplyMarkup", chat_id=chat, message_id=msg, reply_markup={"inline_keyboard": []})
        d = ap.load()
        new = card_caption(d, p) + f"\n\n{note}"
        if p.get("image"):
            api("editMessageCaption", chat_id=chat, message_id=msg, caption=new[:1000])
        else:
            api("editMessageText", chat_id=chat, message_id=msg, text=new[:4000])
    except RuntimeError as e:
        print("edit failed:", e)


def handle_callback(cq):
    _, owner = config()
    chat = str(cq["message"]["chat"]["id"]); msg = cq["message"]["message_id"]
    data = cq.get("data", "")
    if chat != owner:
        api("answerCallbackQuery", callback_query_id=cq["id"], text="Not your Otto."); return
    parts = data.split(":")
    if len(parts) == 4 and parts[1] == "rec":
        _, _, rid, action = parts
        d = ap.load()
        r = next((x for x in d.get("recommendations", []) if x["id"] == rid), None)
        if not r:
            api("answerCallbackQuery", callback_query_id=cq["id"], text="Unknown recommendation"); return
        r["status"] = "approved" if action == "approve" else "dismissed"; r["approved_via"] = "telegram"; r["decided_at"] = ap.now_iso()
        ap.save(d)
        api("answerCallbackQuery", callback_query_id=cq["id"], text="✅ Approved — Orion is on it" if action == "approve" else "Dismissed")
        api("editMessageReplyMarkup", chat_id=chat, message_id=msg, reply_markup={"inline_keyboard": []})
        api("editMessageText", chat_id=chat, message_id=msg, text=cq["message"].get("text", "") + ("\n\n✅ Approved" if action == "approve" else "\n\n— Not now"))
        return
    if len(parts) != 3 or parts[0] != "otto":
        api("answerCallbackQuery", callback_query_id=cq["id"], text="?"); return
    _, pid, action = parts
    d = ap.load()
    p = ap.post(d, pid)
    if not p:
        api("answerCallbackQuery", callback_query_id=cq["id"], text="Unknown post"); return
    if action == "edit":
        p["edit_requested_at"] = ap.now_iso()
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        state["pending_edit"] = {"post": pid, "message_id": msg, "ts": ap.now_iso()}
        STATE.write_text(json.dumps(state))
        ap.save(d)
        api("answerCallbackQuery", callback_query_id=cq["id"], text="Reply with the change you want")
        api("sendMessage", chat_id=chat, text=f"✏️ {pid} — reply to this message with what to change (e.g. “shorter, mention the lab tests”). Quill rewrites and sends a new card.",
            reply_markup={"force_reply": True, "selective": True})
        return
    if p["status"] not in ("pending_approval", "draft"):
        api("answerCallbackQuery", callback_query_id=cq["id"], text=f"Already {p['status']}"); return
    ap.decide(d, pid, action, via="telegram")
    ap.save(d)
    note = {"approve": f"✅ Approved · publishes {slot_str(p)}", "skip": "❌ Skipped — Otto refills the slot",
            "later": "↷ Later — you'll get it again tomorrow morning"}[action]
    api("answerCallbackQuery", callback_query_id=cq["id"], text=note.split(" — ")[0])
    if action != "later":
        edit_card(chat, msg, p, note)


def handle_message(m):
    _, owner = config()
    if str(m["chat"]["id"]) != owner or not m.get("text"):
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    pe = state.get("pending_edit")
    if not pe:
        return
    d = ap.load()
    p = ap.post(d, pe["post"])
    if p:
        p["edit_note"] = m["text"].strip(); p["status"] = "draft"
        d.setdefault("edit_requests", []).append({"post": p["id"], "note": p["edit_note"], "ts": ap.now_iso(), "via": "telegram"})
        ap.save(d)
        api("sendMessage", chat_id=owner, text=f"Got it — Quill is rewriting {p['id']}: “{p['edit_note'][:120]}”. New card shortly.")
    state.pop("pending_edit", None); STATE.write_text(json.dumps(state))


def poll(once=False, timeout=50):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    while True:
        updates = api("getUpdates", offset=state.get("offset", 0), timeout=0 if once else timeout,
                      allowed_updates=["callback_query", "message"])
        for u in updates:
            state["offset"] = u["update_id"] + 1
            try:
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
            except Exception as e:
                print("update error:", e)
            STATE.write_text(json.dumps(state))
        if once:
            print(f"processed {len(updates)} update(s)"); return
        if not updates:
            time.sleep(1)


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "send-cards":
        send_cards(bid=a[a.index("--brand") + 1] if "--brand" in a else None,
                   hours=int(a[a.index("--hours") + 1]) if "--hours" in a else 72,
                   resend="--resend" in a, dry="--dry" in a, base=a[a.index("--base") + 1] if "--base" in a else BASE)
    elif cmd == "send-recs":
        send_recs(dry="--dry" in a)
    elif cmd == "poll":
        poll(once="--once" in a, timeout=int(a[a.index("--timeout") + 1]) if "--timeout" in a else 50)
    elif cmd == "send":
        send(" ".join(a[1:]))
    else:
        print(__doc__)
