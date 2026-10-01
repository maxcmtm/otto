#!/usr/bin/env python3
"""Otto Telegram loop — the approval surface, in code (no agent in the loop).

  otto_telegram.py send-cards [--brand <id>] [--ids hg-001,hg-002] [--hours 72] [--resend] [--dry]
  otto_telegram.py send-recs  [--dry]
  otto_telegram.py poll [--once] [--timeout 50]
  otto_telegram.py send "<text>"

send-cards: every post in pending_approval whose slot is within --hours and that has no card yet, of a brand whose approvals
            go to Telegram (brands[].approvals; a brand without the field does — e-mail approvals are otto_email.py)
            → photo (the visual) + caption + inline buttons  ✅ Approve · ❌ Skip · ✏️ Edit · ↷ Later
            Each card is checked against brands/<slug>/compliance.json first (otto_compliance): a violating
            card is NOT sent and a "Compliance hold" recommendation is filed instead. Photo by public URL,
            else uploaded from the local file, else the card goes out as text. Each card is saved on its own.
            A post whose slot already passed gets no card (approving it could only produce a "missed" publish).
            Each post is claimed (tg_claim) in data.json before it is sent, so a second send-cards running at the
            same time skips it instead of sending a duplicate card.
send-recs:  every proposed recommendation without a card → message + ✅ Approve · Not now
poll:       long-polls Bot API updates. Button taps → ap.decide / rec status (taste log, approved_via=telegram),
            the card is edited in place ("✅ Approved · publishes Sat 18:00") so the phone shows the state.
            ↷ Later clears the card id, so tomorrow's send-cards sends it again.
            ✏️ Edit → the owner REPLIES to the prompt within 2 h → stored as an edit request (edit_requests[],
            post back to draft) for Quill to rewrite and re-send. Only posts in draft/pending_approval take edits.
            Approving "Approve the <month> paid plan" runs otto_ads.approve(brand, month); approving an otto_ads
            "Pause …" card runs otto_ads.pause(<campaign_id stored on the card>). "On it" is only said when an
            action actually ran.
Language: cards, buttons, answers and edit prompts speak the brand's brands[].comms_lang (otto_i18n: en by default, nl, de;
German Sie / du);
an owner-only recommendation card stays English. The 07:35 morning report (otto_report) sends this brand's cards right after
itself; the 08:00 send-cards run is the catch-up.
Only the owner may decide: callback_query.from.id must be owner_user_id (default: owner_chat_id).
Config: $OTTO_SECRETS/telegram.json {"bot_token": "...", "owner_chat_id": "590113904", "owner_user_id": optional}
or env TELEGRAM_BOT_TOKEN / OTTO_OWNER_CHAT_ID.
State: .telegram-state.json next to data.json (update offset, pending edit prompts). Public image base for photos: --base.
Pure stdlib. Writes through ap.transaction().
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap
import otto_email
import otto_i18n as i18n
import otto_paths as paths

HERE = Path(__file__).parent
SECRETS = Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")
STATE = ap.DATA.parent / ".telegram-state.json"     # next to data.json (the workspace platform dir on the server)
BASE = paths.BASE
PLAT = {"fb": "Facebook", "ig": "Instagram", "li": "LinkedIn"}
EDIT_TTL = timedelta(hours=2)
CLAIM_TTL = timedelta(minutes=10)
EDITABLE = ("draft", "pending_approval")


def _conf():
    f = SECRETS / "telegram.json"
    return json.loads(f.read_text()) if f.exists() else {}


def config():
    c = _conf()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or c.get("bot_token")
    chat = os.environ.get("OTTO_OWNER_CHAT_ID") or c.get("owner_chat_id")
    return tok, str(chat) if chat else None


def owner_user():
    c = _conf()
    u = os.environ.get("OTTO_OWNER_USER_ID") or c.get("owner_user_id") or config()[1]
    return str(u) if u else None


def _multipart(fields, files):
    boundary = "otto" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode() + str(v).encode() + b"\r\n")
    for k, (name, data, ctype) in files.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n"
                   f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def api(method, files=None, **params):
    tok, _ = config()
    if not tok:
        raise RuntimeError("no bot token (otto-secrets/telegram.json or TELEGRAM_BOT_TOKEN)")
    fields = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
    if files:
        data, ctype = _multipart(fields, files)
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=data, headers={"Content-Type": ctype})
    else:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            out = json.loads(e.read().decode())
        except Exception:
            raise RuntimeError(f"{method}: HTTP {e.code}")
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out.get('description')}")
    return out["result"]


def slot_str(p, b=None, t=None):
    """The slot in the brand's own time and language ("Fri 2 Oct · 18:00" / "vr 2 okt · 18:00")."""
    dt = ap.slot_dt(p, b)
    if not dt:
        return p.get("slot", "")
    t = t or (i18n.Tr.for_brand(b) if b else i18n.Tr())
    return t.day_time(dt.astimezone(ap.brand_tz(b)))


def tr_for(d=None, brand_id=None):
    """The translator for the brand a card / tap belongs to (English when it cannot be told)."""
    try:
        b = ap.brand(d if d is not None else ap.load(), brand_id) if brand_id else None
    except Exception:                                          # noqa: BLE001
        b = None
    return i18n.Tr.for_brand(b) if b else i18n.Tr()


def card_caption(d, p):
    b = ap.brand(d, p["brand"]) or {}
    t = i18n.Tr.for_brand(b) if b else i18n.Tr()
    brief = p.get("brief") or ""
    why = p.get("why") or ("" if "TBD" in brief else brief)    # the planner's placeholder brief is not a reason
    cap = (p.get("caption") or p.get("hook") or "").strip()
    head = f"{b.get('name', p['brand'])} · {PLAT.get(p['platform'], p['platform'])} · {slot_str(p, b or None, t)} · {p.get('pillar', '')}"
    text = f"{head}\n\n{cap}"
    if why:
        text += "\n\n— " + t("digest.why", why=why[:200])
    return text[:1000]


def post_keyboard(pid, t=None):
    t = t or i18n.Tr()
    return {"inline_keyboard": [[{"text": t("tg.approve"), "callback_data": f"otto:{pid}:approve"},
                                 {"text": t("tg.skip"), "callback_data": f"otto:{pid}:skip"}],
                                [{"text": t("tg.edit"), "callback_data": f"otto:{pid}:edit"},
                                 {"text": t("tg.later"), "callback_data": f"otto:{pid}:later"}]]}


def rec_keyboard(rid, t=None):
    t = t or i18n.Tr()
    return {"inline_keyboard": [[{"text": t("tg.approve"), "callback_data": f"otto:rec:{rid}:approve"},
                                 {"text": t("tg.not_now"), "callback_data": f"otto:rec:{rid}:dismiss"}]]}


def send_card(chat, p, cap, base, t=None):
    """Photo by public URL → photo uploaded from the local file → plain text. Returns (message, kind)."""
    kb = post_keyboard(p["id"], t)
    img = p.get("image")
    if img:
        try:
            url = paths.media_url(img, base)
            return api("sendPhoto", chat_id=chat, photo=url, caption=cap, reply_markup=kb), "photo"
        except Exception as e:
            print(f"  photo by url failed ({str(e)[:100]}) — trying upload")
        try:
            lp = paths.local_path(img) if not str(img).startswith("http") else None
            if lp and lp.exists():
                ctype = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(paths.sniff(lp) or "", "application/octet-stream")
                return api("sendPhoto", files={"photo": (lp.name, lp.read_bytes(), ctype)}, chat_id=chat, caption=cap,
                           reply_markup=kb), "photo"
        except Exception as e:
            print(f"  photo upload failed ({str(e)[:100]}) — sending text")
    return api("sendMessage", chat_id=chat, text=cap, reply_markup=kb), "text"


def send_cards(bid=None, hours=72, resend=False, dry=False, base=BASE, ids=None, now=None):
    import otto_compliance as comp
    d = ap.load()                                   # snapshot; every card is saved in its own transaction
    _, chat = config()
    now = now or datetime.now(timezone.utc)
    sent = blocked = 0
    for p in sorted(d["posts"], key=lambda x: x.get("slot", "")):
        if ids and p["id"] not in ids:
            continue
        if p["status"] != "pending_approval" or (bid and p["brand"] != bid):
            continue
        if not ids and "telegram" not in otto_email.approval_channels(ap.brand(d, p["brand"])):
            continue                                # this brand approves by e-mail / in the app (brands[].approvals)
        if p.get("tg_message_id") and not resend:
            continue
        slot = ap.slot_dt(p, ap.brand(d, p["brand"]))
        if slot is None or (not ids and slot > now + timedelta(hours=hours)):
            continue
        if not ids and slot <= now:
            print(f"PAST    {p['id']} {slot_str(p)} — slot already passed, no card (needs a new slot)")
            continue
        try:
            v = comp.check_post(p)
            if v:
                blocked += 1
                print(f"BLOCKED {p['id']} {slot_str(p)} — compliance: {comp.describe(v)}")
                if not dry:
                    with ap.transaction() as d2:
                        q = ap.post(d2, p["id"])
                        if q is not None:
                            q["compliance_block"] = {"rules": [x["rule"] for x in v][:6], "at": ap.now_iso()}
                            comp.file_block(d2, p["brand"], f"{p['id']} “{p.get('hook', '')[:50]}”", v, "otto_telegram", post=p["id"])
                continue
            cap = card_caption(d, p)
            print(f"{'WOULD SEND' if dry else 'SEND'} {p['id']} {slot_str(p)} {'photo' if p.get('image') else 'text'} — {p.get('hook','')[:50]}")
            if dry:
                continue
            with ap.transaction() as d2:                # claim first: a parallel run skips a post that is being sent
                q = ap.post(d2, p["id"])
                claim = ap.parse_iso((q or {}).get("tg_claim"))
                busy = (q is None or q.get("status") != "pending_approval" or (q.get("tg_message_id") and not resend)
                        or bool(claim and claim.tzinfo and datetime.now(timezone.utc) - claim < CLAIM_TTL))
                if not busy:
                    q["tg_claim"] = ap.now_iso()
            if busy:
                print(f"  {p['id']}: already carded or being sent by another run — skipped")
                continue
            try:
                m, kind = send_card(chat, p, cap, base, tr_for(d, p["brand"]))
            except Exception:
                with ap.transaction() as d2:
                    q = ap.post(d2, p["id"])
                    if q is not None:
                        q.pop("tg_claim", None)
                raise
            with ap.transaction() as d2:
                q = ap.post(d2, p["id"])
                if q is not None:
                    q["tg_message_id"] = m["message_id"]; q["tg_sent_at"] = ap.now_iso(); q["tg_kind"] = kind
                    q.pop("compliance_block", None); q.pop("tg_claim", None)
            sent += 1
        except Exception as e:
            print(f"  card {p['id']} failed: {type(e).__name__}: {e}")
    print(f"-- {sent} card(s) sent" + (f" · {blocked} blocked by compliance" if blocked else ""))


def send_recs(dry=False):
    d = ap.load()
    _, chat = config()
    sent = 0
    for r in d.get("recommendations", []):
        if r.get("status") != "proposed" or r.get("tg_message_id"):
            continue
        owner = r.get("audience") == "owner" or r.get("internal") or r.get("source") == "otto_admin"
        t = i18n.Tr() if owner else tr_for(d, r.get("brand"))       # an owner-only card stays in the owner's English
        import otto_report
        title, why, impact = (r["title"], r.get("why", ""), r.get("impact", "")) if owner else \
            ((otto_report.plan_title(t, r), r.get("why", "") if t.lang == "en" else "", r.get("impact", "") if t.lang == "en" else "")
             if otto_email.is_plan_card(r) else tuple(otto_report.rec_text(t, r, f) for f in ("title", "why", "impact")))
        text = f"{t('tg.rec_head', prio=r['priority'])}\n\n{title}" + (f"\n\n{why}" if why else "") + (f"\n\n↗ {impact}" if impact else "")
        print(f"{'WOULD SEND' if dry else 'SEND'} {r['id']} — {r['title'][:60]}")
        if dry:
            continue
        try:
            m = api("sendMessage", chat_id=chat, text=text[:4000], reply_markup=rec_keyboard(r["id"], t))
            with ap.transaction() as d2:
                q = ap.rec(d2, r["id"])
                if q is not None:
                    q["tg_message_id"] = m["message_id"]
            sent += 1
        except Exception as e:
            print(f"  rec {r['id']} failed: {type(e).__name__}: {e}")
    print(f"-- {sent} recommendation card(s) sent")


def send(text):
    _, chat = config()
    return api("sendMessage", chat_id=chat, text=text[:4000])


def edit_card(chat, message, p, note):
    """Freeze a decided card: drop the buttons and append the outcome. Photo vs text is decided by the
    ORIGINAL message (a photo card is edited with editMessageCaption even if the post changed since)."""
    msg = message["message_id"]
    try:
        api("editMessageReplyMarkup", chat_id=chat, message_id=msg, reply_markup={"inline_keyboard": []})
        base = message.get("caption") if "photo" in message else message.get("text")
        if not base:
            base = card_caption(ap.load(), p)
        new = f"{base}\n\n{note}"
        if "photo" in message:
            api("editMessageCaption", chat_id=chat, message_id=msg, caption=new[:1024])
        else:
            api("editMessageText", chat_id=chat, message_id=msg, text=new[:4000])
    except RuntimeError as e:
        print("edit failed:", e)


def _state():
    try:
        return json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        return {}


def _save_state(state):
    ap._atomic_write(STATE, json.dumps(state))


def _is_owner(user_id, chat_id=None):
    _, owner_chat = config()
    if str(user_id) != owner_user():
        return False
    return chat_id is None or str(chat_id) == owner_chat


class Skip(Exception):
    """Raised inside a transaction to abort it without saving; the message goes back to the owner."""


def run_rec_action(r):
    """What approving a recommendation does in code. Returns a result string when an action ran, else None."""
    if r.get("source") != "otto_ads":
        return None
    import otto_ads
    return otto_ads.rec_action(r)


def _already(t, status):
    return t("tg.already", state=t("status." + status) if t.has("status." + str(status)) else status)


def handle_rec(cq, rid, action):
    chat = str(cq["message"]["chat"]["id"])
    new = "approved" if action == "approve" else "dismissed"
    t = i18n.Tr()
    try:
        with ap.transaction() as d:
            r = ap.rec(d, rid)
            if r is None:
                raise Skip(t("tg.unknown_rec"))
            if not (r.get("audience") == "owner" or r.get("source") == "otto_admin"):
                t = tr_for(d, r.get("brand"))
            if not ap.can_transition("rec", r["status"], new):
                raise Skip(_already(t, r["status"]))
            r["status"] = new; r["approved_via"] = "telegram"; r["decided_at"] = ap.now_iso()
            snapshot = dict(r)
    except Skip as e:
        api("answerCallbackQuery", callback_query_id=cq["id"], text=str(e)); return
    result = failed = None
    if new == "approved":
        try:
            result = run_rec_action(snapshot)
        except Exception as e:
            result, failed = None, f"{type(e).__name__}: {e}"
            print(f"rec action {rid} failed: {e}")
            with ap.transaction() as d:
                ap.rec_action_failed(d, snapshot, failed, "in Telegram")
        if result:
            with ap.transaction() as d:
                q = ap.rec(d, rid)
                if q is not None:
                    q["action_result"] = result; q["status"] = "done"
    if new == "approved":
        answer = t("tg.rec.on_it") if result else t("tg.rec.failed") if failed else t("tg.rec.approved")
    else:
        answer = t("tg.rec.dismissed")
    api("answerCallbackQuery", callback_query_id=cq["id"], text=answer)
    api("editMessageReplyMarkup", chat_id=chat, message_id=cq["message"]["message_id"], reply_markup={"inline_keyboard": []})
    tail = ("\n\n" + (t("tg.rec.tail_done", result=result) if result else t("tg.rec.tail_failed") if failed else t("tg.rec.approved"))) \
        if new == "approved" else "\n\n" + t("tg.rec.tail_dismissed")
    api("editMessageText", chat_id=chat, message_id=cq["message"]["message_id"], text=(cq["message"].get("text", "") + tail)[:4000])


def handle_callback(cq):
    msg_obj = cq.get("message") or {}
    chat = str((msg_obj.get("chat") or {}).get("id"))
    data = cq.get("data", "")
    if not _is_owner((cq.get("from") or {}).get("id"), chat):
        parts0 = str(data).split(":")
        q0 = ap.post(ap.load(), parts0[1]) if len(parts0) == 3 else None
        api("answerCallbackQuery", callback_query_id=cq["id"], text=tr_for(None, (q0 or {}).get("brand"))("tg.not_yours")); return
    parts = str(data).split(":")
    if len(parts) == 4 and parts[0] == "otto" and parts[1] == "rec":
        if parts[3] not in ("approve", "dismiss"):            # callback data comes from the client: only our two buttons
            api("answerCallbackQuery", callback_query_id=cq["id"], text="?"); return
        return handle_rec(cq, parts[2], parts[3])
    if len(parts) != 3 or parts[0] != "otto":
        api("answerCallbackQuery", callback_query_id=cq["id"], text="?"); return
    _, pid, action = parts
    if action == "edit":
        d = ap.load()
        p = ap.post(d, pid)
        t = tr_for(d, (p or {}).get("brand"))
        if not p:
            api("answerCallbackQuery", callback_query_id=cq["id"], text=t("tg.unknown_post")); return
        if p["status"] not in EDITABLE:
            api("answerCallbackQuery", callback_query_id=cq["id"], text=_already(t, p["status"])); return
        api("answerCallbackQuery", callback_query_id=cq["id"], text=t("tg.edit.answer"))
        prompt = api("sendMessage", chat_id=chat, text=t("tg.edit.prompt", pid=pid),
                     reply_markup={"force_reply": True, "selective": True})
        state = _state()
        edits = state.setdefault("pending_edits", {})
        edits[str(prompt["message_id"])] = {"post": pid, "card": msg_obj.get("message_id"), "ts": ap.now_iso()}
        cutoff = datetime.now(timezone.utc) - EDIT_TTL
        state["pending_edits"] = {k: v for k, v in edits.items() if (ap.parse_iso(v.get("ts")) or cutoff) >= cutoff}
        state.pop("pending_edit", None)
        _save_state(state)
        with ap.transaction() as d2:
            q = ap.post(d2, pid)
            if q is not None:
                q["edit_requested_at"] = ap.now_iso()
        return
    if action not in ap.DECISIONS:
        api("answerCallbackQuery", callback_query_id=cq["id"], text="?"); return
    t = i18n.Tr()
    try:
        with ap.transaction() as d:
            p = ap.post(d, pid)
            if not p:
                raise Skip(t("tg.unknown_post"))
            t = tr_for(d, p.get("brand"))
            if p["status"] not in EDITABLE:
                raise Skip(_already(t, p["status"]))
            ap.decide(d, pid, action, via="telegram")
            if action == "later":
                p.pop("tg_message_id", None)        # tomorrow's send-cards sends it again
            p_after = dict(p)
            b = ap.brand(d, p["brand"])
    except Skip as e:
        api("answerCallbackQuery", callback_query_id=cq["id"], text=str(e)); return
    note = {"approve": t("tg.note.approve", when=slot_str(p_after, b, t)), "skip": t("tg.note.skip"),
            "later": t("tg.note.later")}[action]
    api("answerCallbackQuery", callback_query_id=cq["id"], text=note.split(" — ")[0])
    edit_card(chat, msg_obj, p_after, note)


def handle_message(m):
    _, owner_chat = config()
    if not _is_owner((m.get("from") or {}).get("id"), (m.get("chat") or {}).get("id")) or not m.get("text"):
        return
    reply_to = (m.get("reply_to_message") or {}).get("message_id")
    if not reply_to:
        return                                     # only a reply to the edit prompt counts as an edit
    state = _state()
    edits = state.get("pending_edits") or {}
    pe = edits.pop(str(reply_to), None)
    if not pe:
        return
    _save_state(state)
    ts = ap.parse_iso(pe.get("ts"))
    t = tr_for(None, (ap.post(ap.load(), pe["post"]) or {}).get("brand"))
    if ts is None or datetime.now(timezone.utc) - ts > EDIT_TTL:
        api("sendMessage", chat_id=owner_chat, text=t("tg.edit.expired", pid=pe["post"]))
        return
    note = m["text"].strip()
    with ap.transaction() as d:
        p = ap.post(d, pe["post"])
        if p is None or p["status"] not in EDITABLE:
            status = p["status"] if p else "gone"
            ok = False
        else:
            p["edit_note"] = note; p["status"] = "draft"; p.pop("tg_message_id", None)
            d.setdefault("edit_requests", []).append({"post": p["id"], "note": note, "ts": ap.now_iso(), "via": "telegram"})
            ok = True
    if ok:
        api("sendMessage", chat_id=owner_chat, text=t("tg.edit.got_it", pid=pe["post"], note=note[:120]))
    else:
        api("sendMessage", chat_id=owner_chat, text=t("tg.edit.too_late", pid=pe["post"],
                                                      state=t("status." + status) if t.has("status." + str(status)) else status))


def poll(once=False, timeout=50):
    state = _state()
    while True:
        updates = api("getUpdates", offset=state.get("offset", 0), timeout=0 if once else timeout,
                      allowed_updates=["callback_query", "message"])
        for u in updates:
            try:
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
            except Exception as e:
                print("update error:", e)
            state = _state()                       # handlers may have written pending edits
            state["offset"] = u["update_id"] + 1
            _save_state(state)
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
                   resend="--resend" in a, dry="--dry" in a, base=a[a.index("--base") + 1] if "--base" in a else BASE,
                   ids=set(a[a.index("--ids") + 1].split(",")) if "--ids" in a else None)
    elif cmd == "send-recs":
        send_recs(dry="--dry" in a)
    elif cmd == "poll":
        poll(once="--once" in a, timeout=int(a[a.index("--timeout") + 1]) if "--timeout" in a else 50)
    elif cmd == "send":
        send(" ".join(a[1:]))
    else:
        print(__doc__)
