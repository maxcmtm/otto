#!/usr/bin/env python3
"""Otto × Stripe — Stripe is only the payment processor: the customer pays and manages billing on Otto's own Billing page
(app.<domain>/billing.html) and never lands on a Stripe-branded page in the normal flow. Stdlib only (urllib, hmac).

  otto_stripe.py status             # what is configured (never prints a secret) and when Stripe last talked to us
  otto_stripe.py check              # read-only setup check against the Stripe API: account, Stripe Tax, every price in
                                    # plans.json, the webhook endpoint, branding → billing.json stripe_check (the console)
  otto_stripe.py replay <evt.json>  # run a saved event through the handler (support; no signature check)

Paying (POST /billing/checkout, signed-in, tenant-scoped): an Embedded Checkout Session (ui_mode embedded, mounted on our
billing page; "checkout_ui": "hosted" in stripe.json falls back to Stripe's hosted page) — mode subscription for a plan's
plans.json stripe_price_ids.monthly / .yearly, mode payment for the founding seat (stripe_price_ids.one_time; off while
null). The session carries: client_reference_id = our signed reference (brand + user, HMAC — the webhook links by it, never
by guessing from an e-mail), metadata (the same, also on the subscription / payment), the verified Google e-mail
(customer_email; once the brand has a Stripe customer, that customer, which locks the e-mail), payment methods card, SEPA
Direct Debit, iDEAL and Bancontact (iDEAL / Bancontact set up SEPA Direct Debit for the renewals), billing address required,
tax ID collection on, automatic tax on (Stripe Tax: reverse charge for an EU business with a valid VAT ID), a business-only
note above the button. No Stripe trial — except that a brand still inside Otto's own 7-day trial starts its subscription at
the trial's end (subscription_data.trial_end; under 48 hours left, trial_period_days rounded up), so nobody is charged early.
Managing (our own account management, not Stripe's Customer Portal): GET /billing/account (plan, next charge, payment
method, VAT ID, invoices with Stripe's hosted invoice / PDF links), POST /billing/change (upgrade or monthly → yearly: now,
prorated and invoiced at once, applied only once paid — payment_behavior pending_if_incomplete; downgrade or yearly →
monthly: at the end of the period, through a subscription schedule), /billing/cancel (at period end) and /billing/resume,
/billing/payment-method (a SetupIntent for the Payment Element on our page; the webhook makes the new method the default
and retries an open invoice), /billing/tax-id (replace the VAT ID). /billing/portal (Stripe's Customer Portal) exists only
as an optional fallback ("portal_fallback": true; off by default).
Webhook: POST /hooks/stripe (public through Caddy, server to server). Stripe-Signature "t=<unix>,v1=<hex>[,v1=…]": v1 =
HMAC-SHA256(endpoint secret, "<t>.<raw body>"); any configured secret (webhook_secrets: rotation) and any v1 may match;
more than 5 minutes off is refused (replay), and every event id is applied once (Stripe retries). Events:
checkout.session.completed / .async_payment_succeeded / .async_payment_failed, customer.subscription.created / .updated /
.deleted, invoice.paid, invoice.payment_failed, invoice.payment_action_required, charge.refunded, setup_intent.succeeded.
State only ever changes from a verified event or from a server-side Stripe API answer — never from a browser redirect.
past_due → banner in the app + an owner card; after Stripe's retries (Dashboard: cancel the subscription) →
customer.subscription.deleted → plan none (otto_billing.sync_plan). A full refund of the one-time founding seat ends it.

Config — $OTTO_SECRETS/stripe.json (chmod 600); test-mode keys welcome; without it every billing screen says "Payments
aren't set up yet" and every /billing/* route answers 503:
  {"secret_key": "sk_test_…" | "rk_…", "publishable_key": "pk_test_…", "webhook_secrets": ["whsec_…"],
   "checkout_ui": "embedded" | "hosted", "portal_fallback": false, "portal_configuration": "bpc_…" (optional),
   "payment_method_types": ["card", "sepa_debit", "ideal", "bancontact"] ([] = the methods enabled in the Dashboard),
   "require_tax_id": false, "ref_secret": "<≥ 32 chars>" (else generated once into .billing-ref-secret next to data.json),
   "previous_ref_secrets": [], "api_version": "2025-03-31.basil"}
Env OTTO_STRIPE_SECRET_KEY / OTTO_STRIPE_PUBLISHABLE_KEY / OTTO_STRIPE_WEBHOOK_SECRET override; OTTO_STRIPE_API_BASE points
the client at a fake Stripe (tests only).
"""
import base64, hashlib, hmac, json, math, os, re, secrets, sys, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

import ap
import otto_billing as billing

HERE = Path(__file__).parent
API_BASE = "https://api.stripe.com"
API_VERSION = "2025-03-31.basil"
TOLERANCE = 300
DEFAULT_PMT = ["card", "sepa_debit", "ideal", "bancontact"]
INTERVALS = ("month", "year", "one_time")
SUB_STATUS = {"active": "active", "trialing": "trialing", "past_due": "past_due", "canceled": "canceled", "unpaid": "canceled",
              "paused": "canceled", "incomplete": "incomplete", "incomplete_expired": "expired"}
NOT_SET_UP = "Payments aren't set up yet."
LIVE_TTL = 60
RL_WINDOW, RL_MAX = 600, 30                    # /billing/* writes per signed-in user per 10 minutes
_rl, _rl_lock = {}, threading.Lock()
_live, _live_lock = {}, threading.Lock()


class NotConfigured(Exception):
    pass


class StripeError(Exception):
    def __init__(self, status, message, code=None, kind=None):
        super().__init__(message)
        self.status, self.code, self.kind = status, code, kind


# ---------------- config (never logged, never returned to a browser except the publishable key) ----------------

def secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")


def config():
    f = secrets_dir() / "stripe.json"
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

    sk = (os.environ.get("OTTO_STRIPE_SECRET_KEY") or "").strip() or pick("secret_key", "api_key")
    pk = (os.environ.get("OTTO_STRIPE_PUBLISHABLE_KEY") or "").strip() or pick("publishable_key")
    whs = [os.environ.get("OTTO_STRIPE_WEBHOOK_SECRET"), pick("webhook_secret")]
    whs += [s for s in (raw.get("webhook_secrets") or []) if isinstance(s, str)]
    pmt = raw.get("payment_method_types")
    pmt = [x for x in pmt if isinstance(x, str) and re.fullmatch(r"[a-z_]{2,40}", x)] if isinstance(pmt, list) else list(DEFAULT_PMT)
    ui = pick("checkout_ui") if pick("checkout_ui") in ("embedded", "hosted") else "embedded"
    base = (os.environ.get("OTTO_STRIPE_API_BASE") or "").strip().rstrip("/")
    if not re.match(r"^http://127\.0\.0\.1:\d+$", base):
        base = API_BASE                                   # the secret key only ever goes to Stripe (or a local fake in tests)
    mode = "live" if sk and "_live_" in sk else "test" if sk else None
    return {"file": f.exists(), "secret_key": sk, "publishable_key": pk if pk and pk.startswith("pk_") else None,
            "webhook_secrets": [s.strip() for s in whs if s and s.strip()], "checkout_ui": ui,
            "portal_fallback": raw.get("portal_fallback") is True, "portal_configuration": pick("portal_configuration"),
            "payment_method_types": pmt, "require_tax_id": raw.get("require_tax_id") is True,
            "ref_secret": pick("ref_secret"), "previous_ref_secrets": [s for s in raw.get("previous_ref_secrets") or [] if isinstance(s, str)],
            "api_version": pick("api_version") or API_VERSION, "api_base": base, "mode": mode,
            "app_url": pick("app_url")}


def ready(cfg=None):
    """Can a customer pay? A secret key, and a publishable key for the embedded form (the hosted fallback needs none)."""
    cfg = cfg or config()
    return bool(cfg["secret_key"]) and (bool(cfg["publishable_key"]) or cfg["checkout_ui"] == "hosted")


def app_base(cfg=None):
    import otto_paths
    v = (cfg or config()).get("app_url") or otto_paths.app_url()
    return v if v.endswith("/") else v + "/"


def billing_url(cfg=None, **q):
    q = {k: v for k, v in q.items() if v}
    return app_base(cfg) + "billing.html" + ("?" + urllib.parse.urlencode(q) if q else "")


# ---------------- the Stripe API (form-encoded, Bearer key, pinned version) ----------------

def _flatten(params, prefix=""):
    out = []
    items = params.items() if isinstance(params, dict) else enumerate(params)
    for k, v in items:
        key = f"{prefix}[{k}]" if prefix else str(k)
        if v is None:
            continue
        if isinstance(v, dict):
            out += _flatten(v, key)
        elif isinstance(v, (list, tuple)):
            out += _flatten(list(v), key)
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        else:
            out.append((key, str(v)))
    return out


def request(method, path, params=None, cfg=None, idem=None, timeout=20):
    """One Stripe API call → the JSON answer. Raises NotConfigured / StripeError (status, Stripe's message, code)."""
    cfg = cfg or config()
    if not cfg["secret_key"]:
        raise NotConfigured(NOT_SET_UP)
    q = urllib.parse.urlencode(_flatten(params or {}))
    url, data = cfg["api_base"] + path, None
    if method in ("GET", "DELETE"):
        url += ("?" + q) if q else ""
    else:
        data = q.encode()
    headers = {"Authorization": "Bearer " + cfg["secret_key"], "Stripe-Version": cfg["api_version"], "Accept": "application/json",
               "User-Agent": "Otto/1.0 (+stdlib)"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Idempotency-Key"] = idem or ("otto-" + secrets.token_hex(16))
    for attempt in (1, 2):                                   # one retry on a dropped connection (same idempotency key)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                err = (json.loads(e.read().decode() or "{}") or {}).get("error") or {}
            except Exception:
                err = {}
            raise StripeError(e.code, str(err.get("message") or f"Stripe answered HTTP {e.code}")[:300], err.get("code"),
                              err.get("type")) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == 2:
                raise StripeError(0, f"Stripe could not be reached ({type(e).__name__})") from None
    raise StripeError(0, "Stripe could not be reached")


def _id(v):
    if isinstance(v, dict):
        v = v.get("id")
    return v if isinstance(v, str) and v.strip() else None


# ---------------- our signed reference (client_reference_id / metadata) ----------------

def _local_ref_secret():
    f = ap.DATA.parent / ".billing-ref-secret"
    try:
        return f.read_text().strip()
    except FileNotFoundError:
        pass
    f.parent.mkdir(parents=True, exist_ok=True)
    val = secrets.token_hex(32)
    try:
        fd = os.open(str(f), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return f.read_text().strip()
    with os.fdopen(fd, "w") as fh:
        fh.write(val + "\n")
    return val


def _ref_keys(cfg=None):
    cfg = cfg or config()
    cur = cfg.get("ref_secret") if cfg.get("ref_secret") and len(cfg["ref_secret"]) >= 32 else _local_ref_secret()
    return [k.encode() for k in [cur] + [s for s in cfg.get("previous_ref_secrets") or [] if len(s) >= 32]]


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_ref(bid, uid, cfg=None):
    """"o1" + 32 hex HMAC + base64url(["brand", "user"]) — letters, digits, - and _ only, at most 200 characters."""
    payload = _b64(json.dumps([bid or "", uid or ""], separators=(",", ":")).encode())
    sig = hmac.new(_ref_keys(cfg)[0], b"otto-billing/ref|" + payload.encode(), hashlib.sha256).hexdigest()[:32]
    ref = "o1" + sig + payload
    if len(ref) > 200:
        raise ValueError("reference too long")
    return ref


def read_ref(ref, cfg=None):
    """{"brand": id or None, "user": id} when the reference is ours and intact, else None."""
    if not isinstance(ref, str) or not re.fullmatch(r"o1[0-9a-f]{32}[A-Za-z0-9_-]{4,170}", ref):
        return None
    sig, payload = ref[2:34], ref[34:]
    for key in _ref_keys(cfg):
        want = hmac.new(key, b"otto-billing/ref|" + payload.encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(want, sig):
            try:
                bid, uid = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            except Exception:
                return None
            if isinstance(uid, str) and uid and isinstance(bid, str):
                return {"brand": bid or None, "user": uid}
            return None
    return None


# ---------------- webhook signature ----------------

def sign(secret, body, ts=None):
    """The Stripe-Signature header Stripe would send (tests, and checking a setup by hand)."""
    ts = int(ts if ts is not None else time.time())
    v1 = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def verify(body, header, secrets_list, now=None):
    """(True, "ok") when one configured endpoint secret signed exactly these bytes less than 5 minutes ago."""
    parts = {}
    for item in str(header or "").split(","):
        k, _, v = item.strip().partition("=")
        if k and v:
            parts.setdefault(k, []).append(v)
    ts = (parts.get("t") or [""])[0]
    sigs = parts.get("v1") or []
    if not ts or not sigs:
        return False, "missing Stripe-Signature (t=…, v1=…)"
    if not re.fullmatch(r"\d{9,11}", ts):
        return False, "bad Stripe-Signature timestamp"
    if abs((now or time.time()) - int(ts)) > TOLERANCE:
        return False, "Stripe-Signature timestamp is more than 5 minutes off"
    msg = ts.encode() + b"." + body
    for s in secrets_list:
        want = hmac.new(s.encode(), msg, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(want, g.strip()) for g in sigs):
            return True, "ok"
    return False, "signature does not match"


def webhook(body, headers):
    """POST /hooks/stripe → (status, obj). Nothing is parsed or stored before the signature verifies."""
    cfg = config()
    if not cfg["webhook_secrets"]:
        return 503, {"error": "Stripe is not connected yet (no webhook secret in otto-secrets/stripe.json)"}
    sig = headers.get("Stripe-Signature") if hasattr(headers, "get") else None
    ok, why = verify(body, sig, cfg["webhook_secrets"])
    if not ok:
        return 400, {"error": why}
    try:
        evt = json.loads(body)
    except Exception:
        return 400, {"error": "bad json"}
    if not (isinstance(evt, dict) and isinstance(evt.get("id"), str) and isinstance(evt.get("type"), str)):
        return 400, {"error": "not a Stripe event"}
    return 200, dict(handle_event(evt), ok=True)


# ---------------- normalizing Stripe objects into billing.json ----------------

def _money(cents):
    try:
        return round(int(cents) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _pm_summary(pm):
    """{type, brand, last4, exp} of a PaymentMethod object (nothing else is kept)."""
    if not isinstance(pm, dict):
        return None
    t = pm.get("type")
    if t == "card" and isinstance(pm.get("card"), dict):
        c = pm["card"]
        return {"type": "card", "brand": str(c.get("brand") or "card")[:20], "last4": str(c.get("last4") or "")[:4],
                "exp": f"{int(c.get('exp_month') or 0):02d}/{str(c.get('exp_year') or '')[-2:]}" if c.get("exp_month") else None}
    if t == "sepa_debit" and isinstance(pm.get("sepa_debit"), dict):
        return {"type": "sepa_debit", "brand": "SEPA Direct Debit", "last4": str(pm["sepa_debit"].get("last4") or "")[:4]}
    if t:
        return {"type": str(t)[:30], "brand": str(t).replace("_", " ").title()[:30], "last4": None}
    return None


def _base(cid, kind):
    return {"id": cid, "provider": "stripe", "kind": kind, "first_seen": ap.now_iso()}


def _set_ref(c, ref_str, cfg=None):
    ref = read_ref(ref_str, cfg)
    if ref:
        c["ref"] = ref
        c.setdefault("user_id", ref["user"])
    return ref


def apply_subscription(b, sub, created, source="webhook", cfg=None):
    """A Subscription object → the customer record (inside a billing transaction). An older event than the one already
    applied changes nothing (Stripe does not promise order)."""
    sid = _id(sub)
    if not sid:
        return None
    c = b["customers"].setdefault(sid, _base(sid, "subscription"))
    c.setdefault("provider", "stripe")
    c.setdefault("kind", "subscription")
    meta = sub.get("metadata") if isinstance(sub.get("metadata"), dict) else {}
    if not c.get("ref"):
        _set_ref(c, meta.get("otto_ref"), cfg)
    if c.get("event_at") and int(created or 0) < int(c["event_at"]):
        return c                                                # a late delivery: the record already holds a newer state
    raw = str(sub.get("status") or "").lower()
    if raw:
        c["provider_status"] = raw
        c["status"] = SUB_STATUS.get(raw, c.get("status") or "incomplete")
    c["subscription"] = sid
    c["customer"] = _id(sub.get("customer")) or c.get("customer")
    if isinstance(sub.get("customer"), dict) and sub["customer"].get("email"):
        c["email"] = str(sub["customer"]["email"])[:200]
    items = ((sub.get("items") or {}).get("data") or []) if isinstance(sub.get("items"), dict) else []
    item = items[0] if items and isinstance(items[0], dict) else {}
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    if price.get("id"):
        c["plan_id"] = price["id"]
        c["item"] = item.get("id")
        mapped = ap.plan_for_price(price["id"])
        c["plan"] = mapped[0] if mapped else None
        rec = price.get("recurring") if isinstance(price.get("recurring"), dict) else {}
        c["interval"] = rec.get("interval") if rec.get("interval") in ("month", "year") else (mapped[1] if mapped else None)
        amt = _money(price.get("unit_amount"))
        if amt is not None:
            c["amount"] = round(amt * int(item.get("quantity") or 1), 2)
        c["currency"] = str(price.get("currency") or sub.get("currency") or "eur").upper()[:3]
    started = billing.iso_ts(sub.get("start_date") or sub.get("created"))
    if started and (not c.get("started") or started < c["started"]):
        c["started"] = started
    pend = sub.get("current_period_end") or item.get("current_period_end")       # basil moved it onto the item
    c["period_end"] = billing.iso_ts(pend)
    c["cancel_at_period_end"] = bool(sub.get("cancel_at_period_end")) or bool(sub.get("cancel_at"))
    c["cancel_at"] = billing.iso_ts(sub.get("cancel_at"))
    c["trial_end"] = billing.iso_ts(sub.get("trial_end")) if c.get("status") == "trialing" else None
    c["renews"] = c["period_end"] if c.get("status") in billing.RUNNING and not c["cancel_at_period_end"] else None
    if c.get("status") == "canceled":
        c["canceled_at"] = billing.iso_ts(sub.get("ended_at") or sub.get("canceled_at")) or c.get("canceled_at") or ap.now_iso()
    elif c.get("canceled_at") and c.get("status") in ("active", "trialing"):
        c.pop("canceled_at", None)                              # came back
    c["schedule"] = _id(sub.get("schedule"))
    pd = c.get("pending")
    if isinstance(pd, dict) and (not c["schedule"] or pd.get("price") == c.get("plan_id")):
        c.pop("pending", None)                                  # released, or the change has happened
    pm = _pm_summary(sub.get("default_payment_method")) if isinstance(sub.get("default_payment_method"), dict) else None
    if pm:
        c["payment_method"] = pm
    c["event_at"] = int(created or time.time())
    c["updated_at"] = ap.now_iso()
    c["source"] = source
    return c


def apply_checkout(b, s, etype, created, cfg=None):
    """A Checkout Session (completed / async succeeded / async failed) → the customer record it creates or completes."""
    mode = s.get("mode")
    meta = s.get("metadata") if isinstance(s.get("metadata"), dict) else {}
    details = s.get("customer_details") if isinstance(s.get("customer_details"), dict) else {}
    email = details.get("email") or s.get("customer_email")
    if mode == "subscription":
        sid = _id(s.get("subscription"))
        if not sid:
            return None
        c = b["customers"].setdefault(sid, dict(_base(sid, "subscription"), status="incomplete"))
    elif mode == "payment":
        sid = s.get("id")
        c = b["customers"].setdefault(sid, dict(_base(sid, "one_time"), status="incomplete"))
        paid = s.get("payment_status") in ("paid", "no_payment_required")
        if etype == "checkout.session.async_payment_failed":
            c["status"], c["provider_status"] = "expired", "payment_failed"
        elif paid or etype == "checkout.session.async_payment_succeeded":
            if c.get("status") != "canceled":                     # a refunded seat never comes back from a late event
                c["status"], c["provider_status"] = "active", "paid"
        else:
            c["provider_status"] = "processing"                  # SEPA: the money arrives in a few days
        price = meta.get("otto_price")
        mapped = ap.plan_for_price(price) if price else None
        c["plan_id"] = price or c.get("plan_id")
        c["plan"] = mapped[0] if mapped else (meta.get("otto_plan") if meta.get("otto_plan") in ap.plans_config()["plans"] else None)
        c["interval"] = "one_time"
        c["amount"] = _money(s.get("amount_total"))
        c["currency"] = str(s.get("currency") or "eur").upper()[:3]
        c.setdefault("started", billing.iso_ts(s.get("created") or created))
        pi = _id(s.get("payment_intent"))
        if pi:
            c["payment_intent"] = pi
            p = b["payments"].setdefault(pi, {"id": pi, "provider": "stripe"})
            st = "failed" if c["status"] == "expired" else "paid" if c["status"] == "active" else "pending"
            if p.get("status") != "refunded":
                p["status"] = st
            p.update(membership=sid, customer=_id(s.get("customer")), amount=c["amount"], currency=c["currency"],
                     amount_eur=billing.to_eur(c["amount"], c["currency"]), at=billing.iso_ts(created) or ap.now_iso(),
                     email=email, plan_id=c.get("plan_id"), reason="one_time", payment_intent=pi)
            if _id(s.get("invoice")):
                p["invoice"] = _id(s.get("invoice"))
    else:
        return None
    c["checkout_session"] = s.get("id")
    c["customer"] = _id(s.get("customer")) or c.get("customer")
    if email:
        c["email"] = str(email)[:200]
    if details.get("name"):
        c["name"] = str(details["name"])[:200]
    ref = _set_ref(c, s.get("client_reference_id"), cfg) or _set_ref(c, meta.get("otto_ref"), cfg)
    if ref and ref.get("brand") and c.get("customer"):
        acct = b["accounts"].setdefault(ref["brand"], {})
        acct.update(provider="stripe", customer=c["customer"], email=c.get("email") or acct.get("email"), at=acct.get("at") or ap.now_iso())
    c["updated_at"] = ap.now_iso()
    c.setdefault("source", "webhook")
    return c


def _invoice_sub(inv):
    """The subscription an Invoice belongs to (pre-basil: invoice.subscription; basil: parent.subscription_details)."""
    sid = _id(inv.get("subscription"))
    if sid:
        return sid
    par = inv.get("parent") if isinstance(inv.get("parent"), dict) else {}
    sid = _id((par.get("subscription_details") or {}).get("subscription")) if isinstance(par.get("subscription_details"), dict) else None
    if sid:
        return sid
    for ln in ((inv.get("lines") or {}).get("data") or []) if isinstance(inv.get("lines"), dict) else []:
        p = ln.get("parent") if isinstance(ln, dict) and isinstance(ln.get("parent"), dict) else {}
        s = _id((p.get("subscription_item_details") or {}).get("subscription")) if isinstance(p.get("subscription_item_details"), dict) else None
        if s or _id(ln.get("subscription")):
            return s or _id(ln.get("subscription"))
    return None


def apply_invoice(b, inv, kind, created):
    """An Invoice (paid / failed / action required) → a payment record; a failed renewal marks a running customer past_due
    until Stripe's own subscription event says otherwise."""
    iid = _id(inv)
    if not iid:
        return None, None
    sid = _invoice_sub(inv)
    p = b["payments"].setdefault(iid, {"id": iid, "provider": "stripe"})
    st = {"paid": "paid", "failed": "failed", "action_required": "failed"}[kind]
    if p.get("status") == "refunded" and st == "paid":
        st = "refunded"
    if p.get("status") == "paid" and st == "failed":
        st = "paid"                                           # a late failure after the retry succeeded never downgrades
    p["status"] = st
    amt = _money(inv.get("amount_paid") if kind == "paid" else inv.get("amount_due"))
    if amt is not None:
        p["amount"] = amt
    p["currency"] = str(inv.get("currency") or p.get("currency") or "eur").upper()[:3]
    p["amount_eur"] = billing.to_eur(p.get("amount"), p["currency"])
    trans = inv.get("status_transitions") if isinstance(inv.get("status_transitions"), dict) else {}
    p["at"] = billing.iso_ts(trans.get("paid_at")) or billing.iso_ts(inv.get("created")) or p.get("at") or ap.now_iso()
    for k in ("number", "hosted_invoice_url", "invoice_pdf"):
        if isinstance(inv.get(k), str):
            p[k] = inv[k][:500]
    p["reason"] = str(inv.get("billing_reason") or p.get("reason") or "")[:40] or None
    p["customer"] = _id(inv.get("customer")) or p.get("customer")
    p["email"] = inv.get("customer_email") or p.get("email")
    for k in ("payment_intent", "charge"):
        if _id(inv.get(k)):
            p[k] = _id(inv.get(k))
    if sid:
        p["membership"] = sid
        c = b["customers"].get(sid)
        if c is not None:
            p["plan_id"] = c.get("plan_id")
            newer = int(created or 0) >= int(c.get("event_at") or 0)
            if kind in ("failed", "action_required") and c.get("status") == "active" and newer and p["reason"] != "subscription_create":
                c["status"], c["provider_status"] = "past_due", "past_due"
                c["event_at"] = int(created or 0)
            elif kind == "paid" and c.get("status") == "past_due" and newer:
                c["status"], c["provider_status"] = "active", "active"
                c["event_at"] = int(created or 0)
            if kind != "paid":
                c["payment_failed_at"] = billing.iso_ts(created) or ap.now_iso()
                c["action_required"] = kind == "action_required"
            else:
                c.pop("payment_failed_at", None)
                c.pop("action_required", None)
    return p, (b["customers"].get(sid) if sid else None)


def apply_refund(b, ch):
    """A Charge with refunds → its payment record (matched by payment intent / charge / invoice, else the customer's latest
    paid payment of the same amount). A full refund of a one-time seat ends it."""
    pi, cid, inv = _id(ch.get("payment_intent")), _id(ch), _id(ch.get("invoice"))
    pays = b["payments"]
    p = next((x for x in pays.values() if isinstance(x, dict) and ((pi and x.get("payment_intent") == pi) or
                                                                     (cid and x.get("charge") == cid) or x.get("id") in (pi, inv))), None)
    if p is None:
        amt, cus = _money(ch.get("amount")), _id(ch.get("customer"))
        cands = sorted([x for x in pays.values() if isinstance(x, dict) and x.get("status") == "paid" and cus and x.get("customer") == cus
                        and x.get("amount") == amt], key=lambda x: x.get("at") or "")
        p = cands[-1] if cands else None
    if p is None:
        return None, None
    refunded = _money(ch.get("amount_refunded")) or 0
    p["refunded_eur"] = billing.to_eur(refunded, p.get("currency"))
    if cid:
        p["charge"] = cid
    full = bool(ch.get("refunded")) or refunded >= (p.get("amount") or 0) > 0
    if full:
        p["status"] = "refunded"
    c = b["customers"].get(p.get("membership"))
    if full and c is not None and c.get("kind") == "one_time" and c.get("status") in billing.RUNNING:
        c.update(status="canceled", provider_status="refunded", canceled_at=ap.now_iso(), renews=None)
    return p, c


# ---------------- events ----------------

def _fetch_subscription(sid, cfg=None):
    return request("GET", f"/v1/subscriptions/{urllib.parse.quote(sid)}", {"expand": ["default_payment_method"]}, cfg)


def handle_event(evt, source="webhook"):
    """One Stripe event (a verified webhook body or a replayed one) → billing.json, then the brand's plan. Idempotent: an
    event id is applied once; everything it does is an upsert, so a retry after a failure half-way is safe too."""
    cfg = config()
    eid, etype = str(evt.get("id") or "")[:120], str(evt.get("type") or "")[:80]
    created = evt.get("created") or int(time.time())
    obj = ((evt.get("data") or {}).get("object")) if isinstance(evt.get("data"), dict) else None
    obj = obj if isinstance(obj, dict) else {}
    if eid and billing.seen(eid):
        return {"duplicate": True, "type": etype}
    out, cust, card = {"type": etype, "ref": None}, None, None
    fetch_sub = None
    with billing.transaction() as b:
        if etype.startswith("checkout.session."):
            if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed"):
                c = apply_checkout(b, obj, etype, created, cfg)
                cust = c and dict(c)
                if c and c.get("kind") == "subscription" and not c.get("provider_status"):
                    fetch_sub = c["id"]                       # the subscription event has not arrived yet: ask Stripe
        elif etype.startswith("customer.subscription."):
            c = apply_subscription(b, obj, created, source, cfg)
            cust = c and dict(c)
        elif etype in ("invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed", "invoice.payment_action_required"):
            kind = "paid" if etype in ("invoice.paid", "invoice.payment_succeeded") else \
                "action_required" if etype.endswith("action_required") else "failed"
            p, c = apply_invoice(b, obj, kind, created)
            cust = c and dict(c)
            out["ref"] = p and p["id"]
            if kind != "paid" and p:
                card = (p, cust)
        elif etype == "charge.refunded":
            p, c = apply_refund(b, obj)
            cust = c and dict(c)
            out["ref"] = p and p["id"]
        elif etype == "setup_intent.succeeded":
            out["ref"] = obj.get("id")
        out["ref"] = out["ref"] or (cust or {}).get("id")
    if fetch_sub and cfg["secret_key"]:
        try:
            sub = _fetch_subscription(fetch_sub, cfg)
            with billing.transaction() as b:
                c = apply_subscription(b, sub, int(time.time()), "api", cfg)
                cust = c and dict(c)
        except (StripeError, NotConfigured) as e:            # the customer.subscription.* events carry the same state
            print(f"stripe: could not read {fetch_sub} ({e}) — waiting for its subscription event", file=sys.stderr)
    if etype == "setup_intent.succeeded":
        out.update(_default_payment_method(obj, cfg))
    if cust:
        out.update(settle(cust))
    if card:
        _payment_failed_card(*card)
    with billing.transaction() as b:                          # applied: a retry of this event is a duplicate from now on
        billing.record_event(b, "stripe", eid, etype, out.get("ref"), source)
    return out


def settle(c):
    """After a customer record changed: link it to its brand by our signed reference (otto_trial.autolink), or bring the
    linked brand's plan in line (otto_billing.sync_plan; live campaigns the new plan does not cover are paused now)."""
    out = {}
    if c.get("brand_id"):
        res = billing.sync_plan(c, by="stripe")
        if res and res.get("changed"):
            out["plan"] = {"brand": res["brand"], "from": res["from"], "to": res["to"]}
            billing.after_plan_change([res])
        return out
    if c.get("ref") and c.get("status") in billing.RUNNING:
        try:
            import otto_trial
            res = otto_trial.autolink(c)
        except Exception as e:                                # noqa: BLE001 — stored; the owner can link by hand
            print(f"stripe auto-link failed: {type(e).__name__}: {e}", file=sys.stderr)
            res = None
        if res and res.get("brand_id"):
            out["auto_linked"] = res["brand_id"]
            ps = res.get("plan_sync") or {}
            if ps.get("changed"):
                out["plan"] = {"brand": ps["brand"], "from": ps["from"], "to": ps["to"]}
    return out


def _payment_failed_card(p, c):
    """One owner card per failed invoice: who, how much, that Stripe retries and what happens after the last retry."""
    bid = (c or {}).get("brand_id")
    d0 = ap.load()
    name = ((ap.brand(d0, bid) or {}).get("name") or bid) if bid else billing.mask_email(p.get("email")) or (c or {}).get("id") or "A customer"
    with ap.transaction() as d:
        ap.add_rec_once(d, "P1", f"{name}: payment failed",
                        f"Stripe could not collect {p.get('currency') or 'EUR'} {p.get('amount') or 0:,.2f} (invoice "
                        f"{p.get('number') or p['id']}). The client sees a banner in the app to update the payment method; Stripe "
                        "retries on its schedule. If every retry fails, Stripe cancels the subscription and the brand moves to "
                        "no plan (publishing pauses, nothing is deleted).", "Revenue at risk", "Check with the client",
                        brand=bid, source="billing", audience="owner", invoice=p["id"])


def _default_payment_method(si, cfg=None):
    """setup_intent.succeeded from our Billing page: the new method becomes the default of the customer and of its running
    subscriptions, and an open invoice of a past-due subscription is retried with it now."""
    meta = si.get("metadata") if isinstance(si.get("metadata"), dict) else {}
    cus, pm = _id(si.get("customer")), _id(si.get("payment_method"))
    if meta.get("otto_purpose") != "payment_method" or not (cus and pm) or si.get("status") not in (None, "succeeded"):
        return {}
    cfg = cfg or config()
    out = {"payment_method": "default"}
    try:
        request("POST", f"/v1/customers/{urllib.parse.quote(cus)}", {"invoice_settings": {"default_payment_method": pm}}, cfg,
                idem=f"otto-pm-cus-{si.get('id')}")
        b = billing.load()
        for c in [x for x in b["customers"].values() if isinstance(x, dict) and x.get("customer") == cus
                  and x.get("kind") == "subscription" and x.get("status") in billing.RUNNING]:
            sub = request("POST", f"/v1/subscriptions/{urllib.parse.quote(c['id'])}", {"default_payment_method": pm,
                          "expand": ["latest_invoice", "default_payment_method"]}, cfg, idem=f"otto-pm-sub-{si.get('id')}-{c['id']}")
            with billing.transaction() as bb:
                apply_subscription(bb, sub, int(time.time()), "api", cfg)
            inv = sub.get("latest_invoice") if isinstance(sub.get("latest_invoice"), dict) else {}
            if c.get("status") == "past_due" and inv.get("status") == "open" and inv.get("id"):
                try:
                    request("POST", f"/v1/invoices/{urllib.parse.quote(inv['id'])}/pay", {}, cfg, idem=f"otto-pay-{si.get('id')}-{inv['id']}")
                    out["retried"] = inv["id"]
                except StripeError as e:                       # the card was set; Stripe's own retry uses it next
                    out["retry_error"] = str(e)[:120]
        with billing.transaction() as bb:
            for bid, acct in bb["accounts"].items():
                if isinstance(acct, dict) and acct.get("customer") == cus:
                    acct["payment_method_updated_at"] = ap.now_iso()
    except (StripeError, NotConfigured) as e:
        out["error"] = str(e)[:160]
        print(f"stripe: default payment method for {cus} failed: {e}", file=sys.stderr)
    _live_drop(cus)
    return out


# ---------------- the app's Billing page ----------------

class Refused(Exception):
    """A request we answer with (status, {"error", "code"}) — never a 500."""

    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.code = status, code


def rate_ok(uid, now=None):
    now = now or time.time()
    with _rl_lock:
        q = [t for t in _rl.get(uid, []) if now - t < RL_WINDOW]
        if len(q) >= RL_MAX:
            _rl[uid] = q
            return False
        q.append(now)
        _rl[uid] = q
        if len(_rl) > 5000:
            for k in list(_rl)[:1000]:
                _rl.pop(k, None)
        return True


def _brand_for_request(d, u, bids, bid):
    """The brand a billing request is about: the one named (it must be the caller's), else the caller's only / first one."""
    mine = sorted(bids) if bids is not None else sorted(x["id"] for x in d.get("brands") or [] if isinstance(x, dict) and x.get("id"))
    if bid:
        if not isinstance(bid, str) or (bids is not None and bid not in bids) or ap.brand(d, bid) is None:
            raise Refused(404, f"unknown brand {str(bid)[:60]}", "unknown_brand")
        return bid
    own = [x for x in (u.get("brands") or []) if x in mine]
    return (own or mine or [None])[0]


def _trial_end(d, bid, now=None):
    """When the brand's Otto trial ends (it is still running and was never converted), else None."""
    b = ap.brand(d, bid) or {}
    tr = b.get("trial") if isinstance(b.get("trial"), dict) else {}
    if not tr or tr.get("converted_at") or tr.get("denied") or b.get("plan") != ap.trial_plan_id():
        return None
    end = ap.parse_iso(tr.get("ends_at"))
    if end is None:
        return None
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    return end if end > (now or datetime.now(timezone.utc)) else None


def offers(d=None, bid=None, current=None):
    """The plans the Billing page offers: plans.json trial.checkout_plans + every other public, priced plan, with what is on
    sale per interval (a price id in stripe_price_ids)."""
    cfg = ap.plans_config()
    tp = cfg["plans"].get(ap.trial_plan_id() or "") or {}
    ids = list(tp.get("checkout_plans") or [x for x in ("starter", "growth") if x in cfg["plans"]])
    ids += [pid for pid in cfg["order"] if pid not in ids and cfg["plans"][pid].get("public") and cfg["plans"][pid].get("monthly_eur") is not None]
    out = []
    for pid in ids:
        p = cfg["plans"].get(pid)
        if not p:
            continue
        spi = p.get("stripe_price_ids") or {}
        out.append({"plan": pid, "label": p["label"], "monthly_eur": p.get("monthly_eur"), "yearly_eur": p.get("yearly_eur"),
                    "draft": p.get("status") == "draft", "month": bool(spi.get("monthly")), "year": bool(spi.get("yearly")),
                    "current": bool(current and current.get("plan") == pid), "upgrade_to": p.get("upgrade_to")})
    return out


def founding_offer(cfg=None):
    p = ap.plans_config()["plans"].get("founding") or {}
    on = ready(cfg) and bool((p.get("stripe_price_ids") or {}).get("one_time"))
    return {"on": on, "price_eur": p.get("one_time_eur"), "label": p.get("label"), "url": billing_url(cfg, plan="founding") if on else None}


def public_offers():
    """GET /billing/offers (public, the landing): what can be bought right now. No secret, no price id."""
    cfg = config()
    return {"payments": ready(cfg), "founding": founding_offer(cfg),
            "plans": [{k: o[k] for k in ("plan", "label", "monthly_eur", "yearly_eur", "month", "year")} for o in offers()]}


B2B_NOTE = ("Otto is for businesses. Enter your company's VAT ID to apply the EU reverse charge; prices are shown "
            "without VAT and Stripe adds it where it is due. By paying you accept Otto's terms.")


def create_checkout(u, d, bids, req, now=None):
    """POST /billing/checkout {plan, interval, brand?} → {ui: embedded, client_secret, publishable_key} | {ui: hosted, url}."""
    cfg = config()
    if not ready(cfg):
        raise Refused(503, NOT_SET_UP, "not_configured")
    plan = str(req.get("plan") or "")
    pcfg = ap.plans_config()
    if plan not in pcfg["plans"]:
        raise Refused(400, "choose a plan", "bad_plan")
    interval = "one_time" if plan == "founding" else str(req.get("interval") or "month")
    if interval not in INTERVALS:
        raise Refused(400, "interval must be month or year", "bad_interval")
    price = ap.price_for(plan, interval)
    label = pcfg["plans"][plan]["label"]
    if not price:
        raise Refused(409, f"{label} is not on sale yet.", "not_on_sale")
    bid = _brand_for_request(d, u, bids, req.get("brand"))
    b0 = billing.load()
    if bid:
        rows = [c for c in b0["customers"].values() if isinstance(c, dict) and c.get("brand_id") == bid and c.get("status") in billing.RUNNING]
        subs = [c for c in rows if billing.provider_of(c) == "stripe" and c.get("kind") == "subscription"]
        if subs or (interval == "one_time" and rows):        # a founder (one-time seat) may still start a subscription
            raise Refused(409, "This business already has a plan: change it on the Billing page.", "subscribed")
    if not rate_ok(u["id"]):
        raise Refused(429, "Too many attempts. Wait a few minutes and try again.", "slow_down")
    ref = make_ref(bid, u["id"], cfg)
    meta = {"otto_ref": ref, "otto_brand": bid or "", "otto_user": u["id"], "otto_plan": plan, "otto_interval": interval,
            "otto_price": price}
    br = ap.brand(d, bid) if bid else None
    lang = str((br or {}).get("lang") or "").split("-")[0].lower()
    p = {"mode": "payment" if interval == "one_time" else "subscription", "line_items": [{"price": price, "quantity": 1}],
         "client_reference_id": ref, "metadata": meta, "billing_address_collection": "required",
         "tax_id_collection": dict({"enabled": True}, **({"required": "if_supported"} if cfg["require_tax_id"] else {})),
         "automatic_tax": {"enabled": True}, "locale": lang if lang in ("nl", "de", "en", "fr", "es", "it", "pt", "da", "sv", "fi", "pl") else "auto",
         "custom_text": {"submit": {"message": B2B_NOTE}}}
    if cfg["payment_method_types"]:
        p["payment_method_types"] = list(cfg["payment_method_types"])
    acct = (b0["accounts"].get(bid) or {}) if bid else {}
    if acct.get("customer"):
        p["customer"] = acct["customer"]                     # the e-mail is the customer's: locked
        p["customer_update"] = {"address": "auto", "name": "auto"}
    else:
        p["customer_email"] = u["email"]                     # the verified Google e-mail, prefilled and locked
        if interval == "one_time":
            p["customer_creation"] = "always"
    if interval == "one_time":
        p["payment_intent_data"] = {"metadata": meta, "description": f"Otto · {label}"}
        p["invoice_creation"] = {"enabled": True, "invoice_data": {"metadata": meta, "description": f"Otto · {label}"}}
    else:
        sd = {"metadata": meta, "description": f"Otto · {label}"}
        end = _trial_end(d, bid, now) if bid else None
        if end is not None:                                   # never charged before Otto's own trial is over
            left = (end - (now or datetime.now(timezone.utc))).total_seconds()
            if left >= 48 * 3600 + 120:
                sd["trial_end"] = int(end.timestamp())
            else:
                sd["trial_period_days"] = max(1, math.ceil(left / 86400))
        p["subscription_data"] = sd
        p["payment_method_collection"] = "always"
    if cfg["checkout_ui"] == "embedded":
        p["ui_mode"] = "embedded"
        p["return_url"] = billing_url(cfg) + ("&" if "?" in billing_url(cfg) else "?") + "session_id={CHECKOUT_SESSION_ID}"
    else:
        p["success_url"] = billing_url(cfg) + ("&" if "?" in billing_url(cfg) else "?") + "session_id={CHECKOUT_SESSION_ID}"
        p["cancel_url"] = billing_url(cfg, plan=plan, interval=interval if interval != "one_time" else None, brand=bid, canceled="1")
    s = request("POST", "/v1/checkout/sessions", p, cfg)
    out = {"session": s.get("id"), "plan": plan, "interval": interval, "brand": bid,
           "trial_end": billing.iso_ts((p.get("subscription_data") or {}).get("trial_end"))}
    if cfg["checkout_ui"] == "embedded":
        out.update(ui="embedded", client_secret=s.get("client_secret"), publishable_key=cfg["publishable_key"])
    else:
        out.update(ui="hosted", url=s.get("url"))
    return out


def checkout_status(u, session_id):
    """GET /billing/status?session_id= → {state: active | processing | open | expired, plan?} — for the page that waits for
    the webhook after a payment. Only ever the caller's own session (our reference names them)."""
    if not isinstance(session_id, str) or not re.fullmatch(r"cs_[A-Za-z0-9_]{6,200}", session_id):
        raise Refused(400, "bad session id", "bad_session")
    b = billing.load()
    c = next((x for x in b["customers"].values() if isinstance(x, dict) and x.get("checkout_session") == session_id), None)
    if c and (c.get("ref") or {}).get("user") == u["id"]:
        st = c.get("status")
        return {"state": "active" if st in billing.RUNNING else "processing" if st == "incomplete" else st,
                "plan": c.get("plan"), "brand": c.get("brand_id"), "trial_end": c.get("trial_end")}
    cfg = config()
    if not cfg["secret_key"]:
        raise Refused(503, NOT_SET_UP, "not_configured")
    s = request("GET", f"/v1/checkout/sessions/{urllib.parse.quote(session_id)}", None, cfg)
    ref = read_ref(s.get("client_reference_id"), cfg)
    if not ref or ref["user"] != u["id"]:
        raise Refused(404, "unknown checkout", "unknown_session")
    st = s.get("status")
    return {"state": "processing" if st == "complete" else st if st in ("open", "expired") else "processing",
            "plan": (s.get("metadata") or {}).get("otto_plan"), "brand": ref.get("brand")}


def _live_drop(cus):
    with _live_lock:
        _live.pop(cus, None)


def _live_view(cus, sub_id, cfg):
    """The customer's payment method, VAT IDs and invoices, fresh from Stripe (cached LIVE_TTL seconds)."""
    with _live_lock:
        hit = _live.get(cus)
        if hit and time.time() - hit[0] < LIVE_TTL and hit[2] == sub_id:
            return hit[1]
    cust = request("GET", f"/v1/customers/{urllib.parse.quote(cus)}",
                   {"expand": ["invoice_settings.default_payment_method", "tax_ids"]}, cfg)
    pm = _pm_summary((cust.get("invoice_settings") or {}).get("default_payment_method"))
    if sub_id and not pm:
        try:
            pm = _pm_summary(_fetch_subscription(sub_id, cfg).get("default_payment_method"))
        except StripeError:
            pm = None
    tax = [{"id": t.get("id"), "type": t.get("type"), "value": t.get("value"),
            "status": ((t.get("verification") or {}).get("status") if isinstance(t.get("verification"), dict) else None)}
           for t in ((cust.get("tax_ids") or {}).get("data") or []) if isinstance(t, dict)]
    inv = request("GET", "/v1/invoices", {"customer": cus, "limit": 12}, cfg)
    invoices = [{"id": i.get("id"), "number": i.get("number"), "at": billing.iso_ts(i.get("created")),
                 "amount": _money(i.get("total")), "currency": str(i.get("currency") or "eur").upper(), "status": i.get("status"),
                 "url": i.get("hosted_invoice_url"), "pdf": i.get("invoice_pdf")}
                for i in (inv.get("data") or []) if isinstance(i, dict) and i.get("status") != "draft"]
    addr = cust.get("address") if isinstance(cust.get("address"), dict) else {}
    view = {"payment_method": pm, "tax_ids": tax, "invoices": invoices, "name": cust.get("name"),
            "country": addr.get("country"), "email": cust.get("email")}
    with _live_lock:
        _live[cus] = (time.time(), view, sub_id)
    return view


def _https(u):
    return u if isinstance(u, str) and re.match(r"^https://[^\s\"'<>]+$", u) else None


def account(u, d, bids, bid=None):
    """GET /billing/account?brand= → everything the Billing page shows for one brand."""
    cfg = config()
    bid = _brand_for_request(d, u, bids, bid)
    b = billing.load()
    mine = sorted(bids) if bids is not None else sorted(x["id"] for x in d.get("brands") or [] if isinstance(x, dict) and x.get("id"))
    out = {"configured": ready(cfg), "mode": cfg["mode"], "email": u["email"], "portal": bool(cfg["portal_fallback"] and cfg["secret_key"]),
           "publishable_key": cfg["publishable_key"], "brand": None, "subscription": None, "legacy": None,
           "brands": [{"id": x, "name": (ap.brand(d, x) or {}).get("name") or x} for x in mine],
           "payment_method": None, "tax_ids": [], "invoices": [], "founding": founding_offer(cfg)}
    if not bid:
        out["offers"] = offers()
        return out
    br = ap.brand(d, bid) or {}
    out["brand"] = {"id": bid, "name": br.get("name") or bid, "plan": ap.plan_of(d, bid)["id"],
                    "plan_label": ap.plan_of(d, bid)["label"]}
    end = _trial_end(d, bid)
    out["trial"] = {"ends_at": end.strftime("%Y-%m-%dT%H:%M:%SZ")} if end else None
    run = billing.running_for_brand(bid, b) or billing.latest_for_brand(bid, b)
    if run and billing.provider_of(run) == "whop":
        out["legacy"] = {"provider": "whop", "status": run.get("status"), "plan": ap.plan_for_whop(run.get("plan_id"))}
    elif run:
        out["subscription"] = dict(billing.brand_summary(bid, b) or {}, id=run["id"])
    out["offers"] = offers(current=(out["subscription"] if out["subscription"] and out["subscription"]["status"] in billing.RUNNING else None))
    cus = (b["accounts"].get(bid) or {}).get("customer") or (run or {}).get("customer") if billing.provider_of(run or {"provider": "stripe"}) == "stripe" else None
    if cus and cfg["secret_key"]:
        try:
            live = _live_view(cus, (run or {}).get("subscription"), cfg)
            out.update(payment_method=live["payment_method"], tax_ids=live["tax_ids"],
                       invoices=[dict(i, url=_https(i["url"]), pdf=_https(i["pdf"])) for i in live["invoices"]])
        except (StripeError, NotConfigured) as e:
            out["stale"] = str(e)[:120]
    if not out["invoices"]:                                    # what the webhooks stored (Stripe unreachable / no key)
        ids = {c["id"] for c in b["customers"].values() if isinstance(c, dict) and c.get("brand_id") == bid}
        pays = sorted([p for p in b["payments"].values() if isinstance(p, dict) and p.get("membership") in ids
                       and billing.provider_of(p) == "stripe"], key=lambda p: p.get("at") or "", reverse=True)[:12]
        out["invoices"] = [{"id": p["id"], "number": p.get("number"), "at": p.get("at"), "amount": p.get("amount"),
                            "currency": p.get("currency"), "status": p.get("status"), "url": _https(p.get("hosted_invoice_url")),
                            "pdf": _https(p.get("invoice_pdf"))} for p in pays]
    if not out["payment_method"] and run and isinstance(run.get("payment_method"), dict):
        out["payment_method"] = run["payment_method"]
    out["has_customer"] = bool(cus)
    return out


def _stripe_sub(d, u, bids, req):
    """(brand id, the brand's running Stripe subscription record) or Refused."""
    if not ready():
        raise Refused(503, NOT_SET_UP, "not_configured")
    bid = _brand_for_request(d, u, bids, req.get("brand"))
    c = billing.running_for_brand(bid, provider="stripe") if bid else None
    if not c or c.get("kind") != "subscription":
        raise Refused(409, "This business has no subscription yet: choose a plan first.", "no_subscription")
    if not rate_ok(u["id"]):
        raise Refused(429, "Too many attempts. Wait a few minutes and try again.", "slow_down")
    return bid, c


def _apply_api_sub(sub, cfg):
    with billing.transaction() as b:
        c = apply_subscription(b, sub, int(time.time()), "api", cfg)
        snap = dict(c) if c else None
    if snap:
        settle(snap)
    return snap


def _release(c, cfg):
    if c.get("schedule"):
        request("POST", f"/v1/subscription_schedules/{urllib.parse.quote(c['schedule'])}/release", {}, cfg)
        with billing.transaction() as b:
            x = b["customers"].get(c["id"])
            if x is not None:
                x.pop("pending", None)
                x["schedule"] = None


def _tier(plan_id):
    p = ap.plans_config()["plans"].get(plan_id) or {}
    return p.get("monthly_eur") if p.get("monthly_eur") is not None else ((p.get("yearly_eur") or 0) / 12)


def change_plan(u, d, bids, req):
    """POST /billing/change {brand, plan, interval}: up (a higher plan, or monthly → yearly) now, prorated and invoiced at
    once (applied only once paid); down (a lower plan, or yearly → monthly) at the end of the period via a subscription
    schedule; the current plan again = keep it (a pending downgrade is dropped)."""
    cfg = config()
    bid, c = _stripe_sub(d, u, bids, req)
    plan, interval = str(req.get("plan") or ""), str(req.get("interval") or c.get("interval") or "month")
    if interval not in ("month", "year"):
        raise Refused(400, "interval must be month or year", "bad_interval")
    price = ap.price_for(plan, interval)
    if not price:
        raise Refused(409, f"{(ap.plans_config()['plans'].get(plan) or {}).get('label') or plan} is not on sale yet.", "not_on_sale")
    if price == c.get("plan_id"):
        if c.get("pending") or c.get("schedule"):
            _release(c, cfg)
            return {"ok": True, "message": "You stay on your current plan.", "when": "kept"}
        raise Refused(409, "You are on this plan already.", "same_plan")
    up = _tier(plan) > _tier(c.get("plan")) or (_tier(plan) == _tier(c.get("plan")) and not (c.get("interval") == "year" and interval == "month"))
    if not up and c.get("cancel_at_period_end"):
        raise Refused(409, "Your subscription is set to end. Keep it first, then choose the new plan.", "canceling")
    _release(c, cfg)
    label = ap.plans_config()["plans"][plan]["label"]
    if not c.get("item"):                                     # replace the item, never add a second one
        c = _apply_api_sub(_fetch_subscription(c["id"], cfg), cfg) or c
        if not c.get("item"):
            raise Refused(409, "Your subscription could not be read just now. Try again in a minute.", "no_item")
    if up:
        sub = request("POST", f"/v1/subscriptions/{urllib.parse.quote(c['id'])}",
                      {"items": [{"id": c.get("item"), "price": price}], "proration_behavior": "always_invoice",
                       "payment_behavior": "pending_if_incomplete"}, cfg)
        _apply_api_sub(sub, cfg)
        pend = sub.get("pending_update")
        return {"ok": True, "when": "now", "message": (f"Almost there: confirm the payment for {label} (see your invoices)."
                                                       if pend else f"You're on {label} now. The difference is invoiced today.")}
    sched = request("POST", "/v1/subscription_schedules", {"from_subscription": c["id"]}, cfg)
    ph = (sched.get("phases") or [{}])[0]
    cur_items = [{"price": _id(x.get("price")) or c.get("plan_id"), "quantity": int(x.get("quantity") or 1)} for x in ph.get("items") or []] \
        or [{"price": c.get("plan_id"), "quantity": 1}]
    first = {"items": cur_items, "start_date": ph.get("start_date"), "end_date": ph.get("end_date"), "automatic_tax": {"enabled": True}}
    if ph.get("trial_end"):
        first["trial_end"] = ph["trial_end"]                   # a subscription still in Otto's trial keeps its first charge date
    request("POST", f"/v1/subscription_schedules/{urllib.parse.quote(sched['id'])}",
            {"end_behavior": "release", "proration_behavior": "none",
             "phases": [first,
                        {"items": [{"price": price, "quantity": 1}], "iterations": 1, "automatic_tax": {"enabled": True},
                         "metadata": {"otto_plan": plan, "otto_interval": interval}}]}, cfg)
    at = billing.iso_ts(ph.get("end_date")) or c.get("period_end")
    with billing.transaction() as b:
        x = b["customers"].get(c["id"])
        if x is not None:
            x["schedule"] = sched["id"]
            x["pending"] = {"plan": plan, "interval": interval, "price": price, "at": at}
    return {"ok": True, "when": "period_end", "at": at, "message": f"You move to {label} at the end of this period. Until then nothing changes."}


def cancel(u, d, bids, req):
    """POST /billing/cancel {brand}: the subscription ends at the end of the paid period (Otto runs until then)."""
    cfg = config()
    _, c = _stripe_sub(d, u, bids, req)
    _release(c, cfg)
    sub = request("POST", f"/v1/subscriptions/{urllib.parse.quote(c['id'])}", {"cancel_at_period_end": True}, cfg)
    x = _apply_api_sub(sub, cfg) or {}
    return {"ok": True, "message": "Your subscription ends at the end of this period. Otto keeps working until then.",
            "ends_at": x.get("period_end")}


def resume(u, d, bids, req):
    """POST /billing/resume {brand}: undo a cancellation at period end."""
    cfg = config()
    _, c = _stripe_sub(d, u, bids, req)
    if not c.get("cancel_at_period_end"):
        raise Refused(409, "Your subscription is not set to end.", "not_canceling")
    sub = request("POST", f"/v1/subscriptions/{urllib.parse.quote(c['id'])}", {"cancel_at_period_end": False}, cfg)
    _apply_api_sub(sub, cfg)
    return {"ok": True, "message": "Your subscription continues."}


def setup_payment_method(u, d, bids, req):
    """POST /billing/payment-method {brand} → a SetupIntent's client secret for the Payment Element on our Billing page."""
    cfg = config()
    if not ready(cfg) or not cfg["publishable_key"]:
        raise Refused(503, NOT_SET_UP, "not_configured")
    bid = _brand_for_request(d, u, bids, req.get("brand"))
    cus = ((billing.load()["accounts"].get(bid) or {}).get("customer")) if bid else None
    if not cus:
        raise Refused(409, "This business has no payment method yet: choose a plan first.", "no_customer")
    if not rate_ok(u["id"]):
        raise Refused(429, "Too many attempts. Wait a few minutes and try again.", "slow_down")
    p = {"customer": cus, "usage": "off_session", "metadata": {"otto_purpose": "payment_method", "otto_brand": bid, "otto_user": u["id"]}}
    if cfg["payment_method_types"]:
        p["payment_method_types"] = list(cfg["payment_method_types"])
    else:
        p["automatic_payment_methods"] = {"enabled": True}
    si = request("POST", "/v1/setup_intents", p, cfg)
    return {"client_secret": si.get("client_secret"), "publishable_key": cfg["publishable_key"], "return_url": billing_url(cfg, brand=bid)}


VAT_RE = re.compile(r"^(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI|GB)[0-9A-Z+*]{2,13}$")


def update_tax_id(u, d, bids, req):
    """POST /billing/tax-id {brand, value}: the customer's VAT ID (replaces the one on file; "" removes it). Stripe Tax applies
    the reverse charge to the next invoices once it is on the customer."""
    cfg = config()
    if not ready(cfg):
        raise Refused(503, NOT_SET_UP, "not_configured")
    bid = _brand_for_request(d, u, bids, req.get("brand"))
    cus = ((billing.load()["accounts"].get(bid) or {}).get("customer")) if bid else None
    if not cus:
        raise Refused(409, "Choose a plan first: the VAT ID is asked at checkout.", "no_customer")
    v = re.sub(r"[\s.\-]", "", str(req.get("value") or "")).upper()
    if v and not VAT_RE.match(v):
        raise Refused(400, "That does not look like an EU VAT ID (for example NL123456789B01).", "bad_vat")
    if not rate_ok(u["id"]):
        raise Refused(429, "Too many attempts. Wait a few minutes and try again.", "slow_down")
    have = request("GET", f"/v1/customers/{urllib.parse.quote(cus)}/tax_ids", {"limit": 10}, cfg)
    for t in have.get("data") or []:
        if isinstance(t, dict) and t.get("id") and t.get("value") != v:
            request("DELETE", f"/v1/customers/{urllib.parse.quote(cus)}/tax_ids/{urllib.parse.quote(t['id'])}", None, cfg)
    if v and not any(isinstance(t, dict) and t.get("value") == v for t in have.get("data") or []):
        request("POST", f"/v1/customers/{urllib.parse.quote(cus)}/tax_ids", {"type": "gb_vat" if v.startswith("GB") else "eu_vat",
                                                                             "value": v}, cfg)
    _live_drop(cus)
    return {"ok": True, "message": "VAT ID saved. It applies to your next invoice." if v else "VAT ID removed."}


def portal(u, d, bids, req):
    """POST /billing/portal {brand}: Stripe's Customer Portal — an optional fallback, off unless stripe.json says
    "portal_fallback": true (the Billing page is the normal way)."""
    cfg = config()
    if not (cfg["portal_fallback"] and cfg["secret_key"]):
        raise Refused(404, "not enabled", "portal_off")
    bid = _brand_for_request(d, u, bids, req.get("brand"))
    cus = ((billing.load()["accounts"].get(bid) or {}).get("customer")) if bid else None
    if not cus:
        raise Refused(409, "This business has no subscription yet.", "no_customer")
    p = {"customer": cus, "return_url": billing_url(cfg, brand=bid)}
    if cfg["portal_configuration"]:
        p["configuration"] = cfg["portal_configuration"]
    s = request("POST", "/v1/billing_portal/sessions", p, cfg)
    return {"url": s.get("url")}


ROUTES = {"/billing/checkout": create_checkout, "/billing/change": change_plan, "/billing/cancel": cancel, "/billing/resume": resume,
          "/billing/payment-method": setup_payment_method, "/billing/tax-id": update_tax_id, "/billing/portal": portal}


def http(method, path, query, req, u, d, bids):
    """The /billing/* routes for otto_api (the caller is signed in; bids = their brands, None = all) → (status, obj)."""
    try:
        if method == "GET" and path == "/billing/account":
            return 200, account(u, d, bids, (query.get("brand") or [None])[0])
        if method == "GET" and path == "/billing/status":
            return 200, checkout_status(u, (query.get("session_id") or [""])[0])
        fn = ROUTES.get(path) if method == "POST" else None
        if fn is None:
            return 404, {"error": "not found"}
        return 200, fn(u, d, bids, req)
    except Refused as e:
        return e.status, {"error": str(e), "code": e.code}
    except NotConfigured:
        return 503, {"error": NOT_SET_UP, "code": "not_configured"}
    except StripeError as e:
        why = str(e) if e.status in (400, 402) and e.kind in ("card_error", "invalid_request_error") and e.code in (
            "tax_id_invalid", "card_declined", "expired_card") else None
        return 502, {"error": why or "The payment service did not answer as expected. Try again in a minute.", "code": "stripe",
                     "detail": f"{e.status} {e.code or ''} {str(e)[:160]}"}


# ---------------- setup check (read-only, for the owner console) ----------------

def check(cfg=None):
    """Read the Stripe setup and store what is missing in billing.json stripe_check (the console's Setup section)."""
    cfg = cfg or config()
    if not cfg["secret_key"]:
        raise NotConfigured("no secret_key in otto-secrets/stripe.json")
    res = {"at": ap.now_iso(), "mode": cfg["mode"], "problems": [], "prices": {}}
    try:
        acct = request("GET", "/v1/account", None, cfg)
        res["account"] = {"country": acct.get("country"), "currency": acct.get("default_currency"),
                          "name": (acct.get("business_profile") or {}).get("name") or (acct.get("settings") or {}).get("dashboard", {}).get("display_name")}
        br = ((acct.get("settings") or {}).get("branding") or {})
        res["branding"] = bool(br.get("icon") or br.get("logo")) and bool(br.get("primary_color"))
        if str(acct.get("default_currency") or "").lower() != "eur":
            res["problems"].append("the account's default currency is not EUR")
        if not res["branding"]:
            res["problems"].append("branding (icon / logo + colours) is not set: invoices and receipts look like Stripe's")
    except StripeError as e:
        res["problems"].append(f"account: {e}")
    try:
        tax = request("GET", "/v1/tax/settings", None, cfg)
        res["tax"] = tax.get("status")
        if tax.get("status") != "active":
            res["problems"].append("Stripe Tax is not active (head office address, preset tax code, registrations)")
    except StripeError as e:
        res["tax"] = None
        res["problems"].append(f"Stripe Tax: {e}")
    for pid, p in ap.plans_config()["plans"].items():
        for k, v in (p.get("stripe_price_ids") or {}).items():
            if not v:
                continue
            key = f"{pid}.{k}"
            try:
                pr = request("GET", f"/v1/prices/{urllib.parse.quote(v)}", None, cfg)
                want_iv = ap.STRIPE_INTERVALS[k]
                iv = ((pr.get("recurring") or {}).get("interval")) if isinstance(pr.get("recurring"), dict) else "one_time"
                bad = [w for w, ok in (("inactive", pr.get("active")), ("not EUR", str(pr.get("currency")).lower() == "eur"),
                                       (f"billed per {iv}, not {want_iv}", iv == want_iv),
                                       ("tax behaviour not set", pr.get("tax_behavior") in ("exclusive", "inclusive"))) if not ok]
                amt = _money(pr.get("unit_amount"))
                want = p.get({"monthly": "monthly_eur", "yearly": "yearly_eur", "one_time": "one_time_eur"}[k])
                if want is not None and amt is not None and abs(amt - want) > 0.005:
                    bad.append(f"€{amt:g} in Stripe, €{want:g} in plans.json")
                res["prices"][key] = "ok" if not bad else "; ".join(bad)
                if bad:
                    res["problems"].append(f"price {key}: " + "; ".join(bad))
            except StripeError as e:
                res["prices"][key] = str(e)[:120]
                res["problems"].append(f"price {key}: {e}")
    try:
        eps = request("GET", "/v1/webhook_endpoints", {"limit": 20}, cfg)
        mine = [e for e in eps.get("data") or [] if isinstance(e, dict) and str(e.get("url") or "").endswith("/hooks/stripe")]
        res["webhook"] = bool(mine) and mine[0].get("status") == "enabled"
        if mine:
            ev = set(mine[0].get("enabled_events") or [])
            missing = [x for x in EVENTS if "*" not in ev and x not in ev]
            if missing:
                res["problems"].append("the webhook misses " + ", ".join(missing))
        else:
            res["problems"].append("no webhook endpoint for /hooks/stripe")
    except StripeError as e:
        res["problems"].append(f"webhooks: {e}")
    with billing.transaction() as b:
        b["stripe_check"] = res
    return res


EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed",
          "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted", "invoice.paid",
          "invoice.payment_failed", "invoice.payment_action_required", "charge.refunded", "setup_intent.succeeded")


def status():
    cfg, b = config(), billing.load()
    return {"file": cfg["file"], "secret_key": bool(cfg["secret_key"]), "mode": cfg["mode"], "publishable_key": bool(cfg["publishable_key"]),
            "webhook_secret": bool(cfg["webhook_secrets"]), "checkout_ui": cfg["checkout_ui"], "portal_fallback": cfg["portal_fallback"],
            "ready": ready(cfg), "last_webhook_at": (b.get("last_webhook") or {}).get("stripe"),
            "customers": sum(1 for c in b["customers"].values() if isinstance(c, dict) and billing.provider_of(c) == "stripe"),
            "check": b.get("stripe_check")}


def main(a):
    cmd = a[0] if a else ""
    if cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "check":
        try:
            res = check()
        except NotConfigured as e:
            print(f"not connected: {e}")
            return 1
        print(json.dumps(res, indent=1))
        return 1 if res["problems"] else 0
    if cmd == "replay" and len(a) > 1:
        print(json.dumps(handle_event(json.loads(Path(a[1]).read_text()), source="replay")))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
