#!/usr/bin/env python3
"""Otto × Whop — LEGACY. Whop sold the €197 founding seats until 1 Oct 2026; every new customer pays with Stripe
(otto_stripe, through the provider-agnostic otto_billing). This module only keeps the existing Whop memberships readable and
in sync: no Whop checkout is offered anywhere any more (app, landing, e-mails).

  otto_whop.py status                  # what is configured and when Whop last talked to us (never prints a secret)
  otto_whop.py backfill [--dry]        # pull every membership + payment from the Whop API (needs api_key + company_id)
  otto_whop.py customers [--json]      # the legacy Whop customers (e-mails masked unless --json)
  otto_whop.py link <mem_id> <brand>   # tie a legacy membership to a brand in data.json ("" unlinks) — otto_billing.link
  otto_whop.py replay <body.json>      # run a saved webhook body through the handler (support; no signature check)

Webhook: POST /otto-api/whop (Caddy: https://<apex>/hooks/whop) stays for the legacy memberships (a refund, a dispute, a
founder's status), signed by Whop with the Standard Webhooks scheme: headers webhook-id / webhook-timestamp /
webhook-signature ("v1,<base64>", several may be listed), signature = base64(HMAC-SHA256(key, "<webhook-id>.<webhook-
timestamp>.<raw body>")). Whop's key is the ws_… secret itself (no prefix stripping, no base64 decoding); a vanilla
"whsec_<base64>" secret is also accepted. Timestamps more than 5 minutes off are refused, and each webhook id is processed
once (Whop retries). No secret configured → 503 "not connected".
Events used: membership.activated / .deactivated / .cancel_at_period_end_changed / .trial_ending_soon,
payment.succeeded / .failed / .pending / .created / .canceled …, refund.created / .updated, dispute.created / .updated.

Secrets — $OTTO_SECRETS/whop.json (only these keys are used here):
  {"api_key": "…", "company_id": "biz_…", "otto_webhook_secret": "ws_…"}
  "otto_webhook_secret" is the secret of the webhook that points at /otto-api/whop; "webhook_secret" is accepted too
  (any configured secret that verifies is enough). Env WHOP_API_KEY / WHOP_WEBHOOK_SECRET / WHOP_COMPANY_ID override.
State — billing.json (otto_billing: storage, lock, the provider-agnostic customer model). A Whop customer record is keyed by
the membership id: {id, provider "whop" (records from before the field have none and are read as Whop), email, name,
plan_id, status, whop_status, started, renews, canceled_at, cancel_at_period_end, currency, website, brand_id, updated_at,
source}; payments {id, membership, status, amount, currency, amount_eur, refunded_eur, at, email, plan_id, reason}; plans
{plan_id: {name, type one_time|renewal, price, currency, period_days}}.
Customer status: active · trialing · past_due · canceled (Whop "completed" = a paid one-time purchase → active;
"canceling" → active until the period ends; "expired" → canceled; "unresolved" → past_due; "drafted" = an unfinished
checkout — kept, never counted as a customer).
Plans: a linked membership gives its brand the plan plans.json whop_plan_ids maps (founding ← plan_joHl1qsZoiJc9) while it
runs, plans.json defaults.ended once it ended — otto_billing.sync_plan, the same entitlement rules as Stripe. A legacy
membership whose e-mail equals a signed-in user's verified Google e-mail links itself to that user's trial brand on arrival
(otto_trial.autolink — kept only for these legacy memberships; Stripe links by our signed checkout reference instead).
"""
import base64, hashlib, hmac, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

import ap
import otto_billing as billing
from otto_billing import FX_EUR, billing_path, email_domain, empty, load, mask_email, to_eur, transaction  # noqa: F401

HERE = Path(__file__).parent
API_BASE = "https://api.whop.com/api/v1"
TOLERANCE = 300
KEEP_EVENTS, KEEP_SEEN = 500, 5000
# Plans Otto sells (Whop plan id → what it is). Add the monthly plans here when they open on Whop; the API backfill also
# caches plan prices it can read into billing.json → plans.
PLANS = {"plan_joHl1qsZoiJc9": {"name": "Founding pilot", "type": "one_time", "price": 197, "currency": "EUR"}}
STATUS = {"active": "active", "trialing": "trialing", "past_due": "past_due", "completed": "active", "canceling": "active",
          "canceled": "canceled", "cancelled": "canceled", "expired": "canceled", "unresolved": "past_due", "drafted": "drafted"}
PAID_EVENTS = {"payment.succeeded": "paid", "payment.failed": "failed", "payment.pending": "pending", "payment.created": "pending",
               "payment.authorized": "pending", "payment.requires_action": "pending", "payment.canceled": "canceled"}


# background runs (the console's pattern): the tests replace it
SPAWN = lambda args: subprocess.Popen(args, cwd=str(HERE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      stdin=subprocess.DEVNULL, start_new_session=True)


class NotConnected(Exception):
    pass


# ---------------- config (never logged, never returned to the UI) ----------------

def secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")


def config():
    raw = {}
    f = secrets_dir() / "whop.json"
    try:
        raw = json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}

    def pick(*keys):
        for k in keys:
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    secrets_ = [os.environ.get("WHOP_WEBHOOK_SECRET"), pick("otto_webhook_secret"), pick("webhook_secret", "webhookSecret")]
    secrets_ += [s for s in (raw.get("webhook_secrets") or []) if isinstance(s, str)]
    plans = dict(PLANS)
    if isinstance(raw.get("plans"), dict):
        plans.update({k: v for k, v in raw["plans"].items() if isinstance(v, dict)})
    return {"api_key": os.environ.get("WHOP_API_KEY") or pick("api_key", "apiKey"), "checkout_base": pick("checkout_base"),
            "company_id": os.environ.get("WHOP_COMPANY_ID") or pick("company_id", "account_id", "companyId"),
            "webhook_secrets": [s.strip() for s in secrets_ if s and s.strip()],
            "api_base": (pick("api_base") or API_BASE).rstrip("/"), "plans": plans, "file": f.exists()}


# ---------------- signature ----------------

def _hdr(headers, name):
    v = headers.get(name) if hasattr(headers, "get") else None
    if v is None and isinstance(headers, dict):
        v = next((val for k, val in headers.items() if k.lower() == name.lower()), None)
    return (v or "").strip()


def _keys(secret):
    keys = [secret.encode()]
    if secret.startswith("whsec_"):
        try:
            keys.append(base64.b64decode(secret[6:]))
        except Exception:
            pass
    return keys


def sign(secret, wid, ts, body):
    """The signature Whop sends (used by the tests and to check a setup by hand)."""
    msg = f"{wid}.{ts}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(_keys(secret)[0], msg, hashlib.sha256).digest()).decode()


def verify(body, headers, secrets_list, now=None):
    """(True, "ok") when one configured secret signed exactly these bytes within the last 5 minutes."""
    wid, wts, sig = _hdr(headers, "webhook-id"), _hdr(headers, "webhook-timestamp"), _hdr(headers, "webhook-signature")
    if not (wid and wts and sig):
        return False, "missing webhook-id / webhook-timestamp / webhook-signature"
    if not re.fullmatch(r"\d{9,11}", wts):
        return False, "bad webhook-timestamp"
    if abs((now or time.time()) - int(wts)) > TOLERANCE:
        return False, "webhook-timestamp is more than 5 minutes off"
    given = [p.split(",", 1)[1] for p in sig.split() if p.startswith("v1,")]
    msg = f"{wid}.{wts}.".encode() + body
    for s in secrets_list:
        for key in _keys(s):
            want = base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()
            if any(hmac.compare_digest(want, g) for g in given):
                return True, "ok"
    return False, "signature does not match"


# ---------------- normalizing ----------------

def iso(v):
    """Whop timestamps (ISO strings or unix seconds) → 'YYYY-MM-DDTHH:MM:SSZ' (UTC) or None."""
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{9,13}", v)):
            n = float(v)
            n = n / 1000 if n > 1e12 else n
            return datetime.fromtimestamp(n, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dt = ap.parse_iso(v)
        if dt is None:
            return None
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def _id(v):
    if isinstance(v, dict):
        v = v.get("id")
    return v if isinstance(v, str) and v.strip() else None


def _num(v):
    n = ap.num(v)
    return float(n) if n is not None else None


def _website(meta):
    if not isinstance(meta, dict):
        return None
    for k in ("website", "url", "domain", "site", "Website"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
    return None


def upsert_membership(b, m, etype="", source="webhook"):
    mid = _id(m)
    if not mid:
        return None
    now = ap.now_iso()
    c = b["customers"].setdefault(mid, {"id": mid, "provider": "whop", "first_seen": now})
    upd = iso(m.get("updated_at"))
    if upd and c.get("updated_at") and upd < c["updated_at"] and source == "webhook":
        return c                                              # an older delivery arriving late: keep the newer state
    st = str(m.get("status") or "").lower()
    if not st:
        st = {"membership.activated": "active", "membership.deactivated": "canceled"}.get(etype, "")
    if st:
        c["whop_status"] = st
        c["status"] = STATUS.get(st, c.get("status") or "active")
    user = m.get("user") if isinstance(m.get("user"), dict) else {}
    for k_in, k_out in (("email", "email"), ("name", "name"), ("username", "username")):
        if user.get(k_in):
            c[k_out] = str(user[k_in])[:200]
    if m.get("email") and not c.get("email"):
        c["email"] = str(m["email"])[:200]
    plan = _id(m.get("plan")) or (m.get("plan_id") if isinstance(m.get("plan_id"), str) else None)
    if plan:
        c["plan_id"] = plan
    started = iso(m.get("created_at")) or iso(m.get("joined_at"))
    if started and (not c.get("started") or started < c["started"]):
        c["started"] = started
    if "cancel_at_period_end" in m:
        c["cancel_at_period_end"] = bool(m.get("cancel_at_period_end"))
    c["renews"] = iso(m.get("renewal_period_end")) if c.get("status") in ("active", "trialing", "past_due") else None
    if c.get("status") == "canceled":
        c["canceled_at"] = iso(m.get("canceled_at")) or c.get("canceled_at") or iso(m.get("updated_at")) or now
    elif c.get("canceled_at") and st in ("active", "trialing"):
        c.pop("canceled_at", None)                            # came back
    if m.get("currency"):
        c["currency"] = str(m["currency"]).upper()[:3]
    site = _website(m.get("metadata"))
    if site:
        c["website"] = site
    c["updated_at"] = upd or now
    c["source"] = source
    return c


def upsert_payment(b, p, etype="", source="webhook"):
    pid = _id(p)
    if not pid:
        return None
    rec = b["payments"].setdefault(pid, {"id": pid, "provider": "whop"})
    status = PAID_EVENTS.get(etype)
    if not status:
        st, sub = str(p.get("status") or "").lower(), str(p.get("substatus") or "").lower()
        status = ("paid" if st == "paid" or sub == "succeeded" else "failed" if st in ("uncollectible", "void") or sub == "failed"
                  else "canceled" if sub == "canceled" else "pending")
    if rec.get("status") == "paid" and status == "pending":
        status = "paid"                                       # a late "created" after "succeeded" never downgrades
    if rec.get("status") == "refunded" and status in ("paid", "pending"):
        status = "refunded"                                   # nor does a late "succeeded" undo a refund (LTV, revenue)
    rec["status"] = status
    amount = next((x for x in (_num(p.get(k)) for k in ("total", "final_amount", "subtotal", "amount")) if x is not None), None)
    if amount is not None:
        rec["amount"] = amount
    cur = str(p.get("currency") or rec.get("currency") or "EUR").upper()[:3]
    rec["currency"] = cur
    rec["amount_eur"] = to_eur(rec.get("amount"), cur, _num(p.get("usd_total")))
    refunded = _num(p.get("refunded_amount"))
    if refunded:
        rec["refunded_eur"] = to_eur(refunded, cur)
        if refunded >= (rec.get("amount") or 0) > 0:
            rec["status"] = "refunded"
    mem = _id(p.get("membership")) or (p.get("membership_id") if isinstance(p.get("membership_id"), str) else None)
    if mem:
        rec["membership"] = mem
    user = p.get("user") if isinstance(p.get("user"), dict) else {}
    if user.get("email"):
        rec["email"] = str(user["email"])[:200]
    plan = _id(p.get("plan"))
    if plan:
        rec["plan_id"] = plan
    rec["at"] = iso(p.get("paid_at")) or iso(p.get("created_at")) or rec.get("at") or ap.now_iso()
    if p.get("billing_reason"):
        rec["reason"] = str(p["billing_reason"])[:40]
    if isinstance(p.get("membership"), dict) and p["membership"].get("status"):
        c = b["customers"].get(mem)
        if c is not None:
            c["whop_status"] = str(p["membership"]["status"]).lower()
            c["status"] = STATUS.get(c["whop_status"], c.get("status"))
    if mem and rec["status"] == "paid" and (b["customers"].get(mem) or {}).get("status") == "drafted":
        b["customers"][mem]["status"] = "active"             # the checkout went through before the membership event arrived
    if mem and mem not in b["customers"] and rec["status"] == "paid":
        # a one-time purchase can arrive as a payment only: the payer is a customer from this moment
        b["customers"][mem] = {"id": mem, "provider": "whop", "first_seen": ap.now_iso(), "status": "active", "whop_status": "paid",
                               "email": rec.get("email"), "plan_id": rec.get("plan_id"), "started": rec["at"],
                               "currency": cur, "updated_at": rec["at"], "source": source}
    return rec


def apply_refund(b, r):
    pay = _id(r.get("payment")) or r.get("payment_id")
    if not isinstance(pay, str) or pay not in b["payments"]:
        return None
    rec = b["payments"][pay]
    amt = _num(r.get("amount")) or _num(r.get("total"))
    st = str(r.get("status") or "").lower()
    if st in ("failed", "canceled"):
        return rec
    rec["refunded_eur"] = to_eur(amt, r.get("currency") or rec.get("currency")) if amt is not None else rec.get("amount_eur")
    if amt is None or amt >= (rec.get("amount") or 0):
        rec["status"] = "refunded"
    return rec


def handle_event(evt, event_id=None, source="webhook"):
    """One Whop event (webhook body or a replayed one) → billing.json. Returns a short summary."""
    if not isinstance(evt, dict):
        raise ValueError("JSON object expected")
    etype = str(evt.get("type") or evt.get("action") or evt.get("event") or "")[:80]
    data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
    eid = str(event_id or evt.get("id") or "")[:120]
    linked = cust = None
    with transaction() as b:
        if eid and eid in b["seen"]:
            return {"duplicate": True, "type": etype}
        ref = None
        if etype.startswith("membership."):
            c = upsert_membership(b, data, etype, source)
            ref = c and c["id"]
            linked = c
        elif etype.startswith("payment."):
            p = upsert_payment(b, data, etype, source)
            ref = p and p["id"]
            linked = b["customers"].get((p or {}).get("membership"))
        elif etype.startswith("refund."):
            p = apply_refund(b, data)
            ref = p and p["id"]
        elif etype.startswith("dispute."):
            ref = _id(data.get("payment")) or _id(data)
        billing.record_event(b, "whop", eid, etype, ref, source)
        cust = dict(linked) if linked else None
        linked = dict(linked) if linked and linked.get("brand_id") else None
    out = {"type": etype, "ref": ref}
    if cust and not linked:                                   # a trial user paid with their verified Google e-mail
        try:
            import otto_trial
            res = otto_trial.autolink(cust)
        except Exception as e:                                # noqa: BLE001 — the event is stored; the owner can link by hand
            print(f"trial auto-link failed: {type(e).__name__}: {e}", file=sys.stderr)
            res = None
        if res and res.get("brand_id"):
            out["auto_linked"] = res["brand_id"]
            ps = res.get("plan_sync") or {}
            if ps.get("changed"):
                out["plan"] = {"brand": ps["brand"], "from": ps["from"], "to": ps["to"]}
    if linked:                                                # outside the billing lock: data.json has its own
        res = sync_plan(linked, by="whop")
        if res and res.get("changed"):
            out["plan"] = {"brand": res["brand"], "from": res["from"], "to": res["to"]}
            after_plan_change([res])
    return out


def webhook(body, headers):
    """POST /otto-api/whop → (status, obj). Signature first; nothing is parsed or stored before it verifies."""
    cfg = config()
    if not cfg["webhook_secrets"]:
        return 503, {"error": "Whop is not connected yet (no webhook secret in otto-secrets/whop.json)"}
    ok, why = verify(body, headers, cfg["webhook_secrets"])
    if not ok:
        return 401, {"error": why}
    try:
        evt = json.loads(body)
    except Exception:
        return 400, {"error": "bad json"}
    return 200, dict(handle_event(evt, _hdr(headers, "webhook-id") or None), ok=True)


# ---------------- API backfill ----------------

def _http_get(url, key, timeout=30):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                               "User-Agent": "Otto/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Whop API {e.code} on {urllib.parse.urlsplit(url).path}") from None


def backfill(fetch=None, dry=False, max_pages=200):
    """Every membership + payment of the company through the Whop API (legacy founders) (cursor pages of 100), then the plan prices it can
    read. Network happens outside the billing lock; each page is merged in its own short transaction."""
    cfg = config()
    if not cfg["api_key"]:
        raise NotConnected("no Whop API key — add api_key to otto-secrets/whop.json")
    if not cfg["company_id"]:
        raise NotConnected("no Whop company id — add company_id (biz_…) to otto-secrets/whop.json")
    fetch = fetch or _http_get
    counts = {"memberships": 0, "payments": 0, "plans": 0}
    for kind in ("memberships", "payments"):
        after = None
        for _ in range(max_pages):
            q = {"account_id": cfg["company_id"], "first": 100}
            if after:
                q["after"] = after
            url = f"{cfg['api_base']}/{kind}?{urllib.parse.urlencode(q)}"
            if dry:
                print("GET", url)
                break
            res = fetch(url, cfg["api_key"])
            rows = [r for r in (res.get("data") or []) if isinstance(r, dict)]
            with transaction() as b:
                for r in rows:
                    (upsert_membership if kind == "memberships" else upsert_payment)(b, r, "", "backfill")
            counts[kind] += len(rows)
            pi = res.get("page_info") or {}
            after = pi.get("end_cursor") if pi.get("has_next_page") else None
            if not after:
                break
    if dry:
        return counts
    b = load()
    unknown = sorted({c.get("plan_id") for c in b["customers"].values() if c.get("plan_id")} - set(cfg["plans"]) - set(b["plans"]))
    found = {}
    for pid in unknown[:50]:
        try:
            p = fetch(f"{cfg['api_base']}/plans/{urllib.parse.quote(pid)}", cfg["api_key"])
        except Exception:
            continue
        price = _num(p.get("renewal_price")) or _num(p.get("initial_price"))
        typ = "one_time" if str(p.get("plan_type") or "").lower() == "one_time" else "renewal"
        found[pid] = {"name": str(p.get("title") or p.get("internal_notes") or pid)[:60], "type": typ, "price": price,
                      "currency": str(p.get("currency") or "EUR").upper()[:3], "period_days": int(_num(p.get("billing_period")) or 30)}
    with transaction() as b:
        b["plans"].update(found)
        b["last_backfill_at"] = ap.now_iso()
    counts["plans"] = len(found)
    changes = [r for r in (sync_plan(c, by="whop") for c in load()["customers"].values() if c.get("brand_id")) if r and r.get("changed")]
    after_plan_change(changes)
    if changes:
        counts["plan_changes"] = len(changes)
    return counts


# ---------------- reading ----------------

def plan_info(b, plan_id, cfg=None):
    plans = dict((cfg or config())["plans"])
    plans.update(b.get("plans") or {})
    return plans.get(plan_id) or {}


def customer_rows(b=None, cfg=None):
    """The legacy Whop customers (otto_billing.customer_rows, Whop rows only) with plan, MRR, lifetime value, payments."""
    return [c for c in billing.customer_rows(b, (cfg or config())["plans"]) if c["provider"] == "whop"]


def link(customer_id, brand_id, by="cli"):
    """Tie a legacy membership to a brand ("" unlinks): otto_billing.link (member + plan)."""
    return billing.link(customer_id, brand_id, by=by, spawn=SPAWN)


# ---------------- plans: membership → brands[].plan (otto_billing: the same rules for every provider) ----------------

def plan_for(c):
    return billing.plan_for(dict(c or {}, provider="whop"))


def sync_plan(c, by="whop"):
    return billing.sync_plan(dict(c or {}, provider="whop"), by=by)


def after_plan_change(results):
    billing.after_plan_change(results, spawn=SPAWN)


def status():
    cfg, b = config(), load()
    lw = b.get("last_webhook") or {}
    mine = [c for c in b["customers"].values() if isinstance(c, dict) and billing.provider_of(c) == "whop"]
    return {"file": cfg["file"], "api_key": bool(cfg["api_key"]), "company_id": bool(cfg["company_id"]),
            "webhook_secret": bool(cfg["webhook_secrets"]), "customers": len(mine),
            "payments": sum(1 for p in b["payments"].values() if isinstance(p, dict) and billing.provider_of(p) == "whop"),
            "last_webhook_at": lw.get("whop") or (None if lw else b.get("last_webhook_at")),
            "last_backfill_at": b.get("last_backfill_at")}


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "status":
        print(json.dumps(status(), indent=1))
    elif cmd == "backfill":
        try:
            print(json.dumps(backfill(dry="--dry" in a)))
        except NotConnected as e:
            sys.exit(f"not connected: {e}")
    elif cmd == "customers":
        rows = customer_rows()
        if "--json" in a:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for c in rows:
                print(f"{c['id']:22} {c.get('status', ''):9} {c['plan'][:18]:18} €{c['mrr_eur']:>7.2f}/mo  €{c['ltv_eur']:>8.2f}  "
                      f"{mask_email(c.get('email')) or '—':28} {c.get('brand_id') or ''}")
            print(f"-- {len(rows)} customers")
    elif cmd == "link":
        c = link(a[1], a[2] if len(a) > 2 else "")
        ps = c.get("plan_sync") or {}
        print(f"{c['id']} → {c.get('brand_id') or 'unlinked'}"
              + (f" · plan {ps['from']} → {ps['to']}" if ps.get("changed") else f" · plan unchanged ({ps['why']})" if ps else ""))
    elif cmd == "replay":
        print(json.dumps(handle_event(json.loads(Path(a[1]).read_text()), source="replay")))
    else:
        print(__doc__)
