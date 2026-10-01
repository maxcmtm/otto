#!/usr/bin/env python3
"""Otto billing — the provider-agnostic layer: customers, subscriptions and payments of every payment provider in one file
(billing.json), what a subscription entitles a brand to, and the numbers the owner console shows. Never in data.json (the
client app and its embedded fallback expose that file).

  otto_billing.py customers [--json]     # every customer, all providers (e-mails masked unless --json)
  otto_billing.py link <id> <brand>      # tie a customer (a Stripe subscription / one-time purchase, a legacy Whop membership)
                                         # to a brand ("" unlinks): member + plan, like the console's manual link

Providers: "stripe" (otto_stripe — every new customer: subscriptions and the optional one-time founding seat) and "whop"
(otto_whop — the legacy founding seats bought before 1 Oct 2026; read-only here, no new Whop checkout is offered anywhere).
Records written before the provider field existed are Whop memberships: readers treat a record without "provider" as
"whop" (provider_of) and nothing rewrites them.

State — $OTTO_BILLING (default billing.json next to data.json; git-ignored; chmod 600; its own flock):
  {"customers": {id: {id, provider, kind subscription | one_time, email, name, status, provider_status, plan (Otto plan id),
                      plan_id (the provider's price / plan id), interval month | year | one_time, amount, currency, started,
                      renews (next charge), period_end, trial_end, cancel_at_period_end, canceled_at, pending {plan, interval,
                      price, at} (a downgrade at period end), schedule, customer (Stripe cus_…), checkout_session, ref {brand,
                      user} (from our signed checkout reference only), brand_id, user_id, brand_link {by, at}, event_at,
                      updated_at, first_seen, source}},
   "payments": {id: {id, provider, membership (the customer id above), customer, status paid | failed | pending | refunded |
                     canceled, amount, currency, amount_eur, refunded_eur, at, email, plan_id, reason, number,
                     hosted_invoice_url, invoice_pdf, payment_intent, charge}},
   "accounts": {brand id: {provider, customer, email, at, payment_method {type, brand, last4}}},
   "plans": {Whop plan cache}, "events": [last 500], "seen": [processed event ids, any provider],
   "last_webhook_at" (any provider), "last_webhook": {provider: at}, "last_backfill_at" (Whop)}
  Stripe customers are keyed by the subscription id (sub_…), a one-time purchase by its Checkout Session (cs_…); Whop ones
  by the membership id (mem_…). Provider statuses are mapped to: active · trialing · past_due · canceled · incomplete
  (checkout not paid yet) · expired (never paid) · drafted (Whop: an unfinished checkout).

Entitlement (sync_plan, idempotent): a customer linked to a brand gives the brand its plan — Stripe: the plan whose
plans.json stripe_price_ids holds the subscription's price; Whop: whop_plan_ids — while it runs (active / trialing /
past_due), via ap.set_plan (clears plan_until and plan_billing, converts a free trial, the user becomes "active" with
paid_at; an "onboarding" brand becomes "active" so its jobs run). canceled / unpaid / paused → plans.json defaults.ended
("none": publishing and ads pause, otto_retention deletes the data 90 days later unless a plan starts again) with one owner
card, and the paying user goes back to status "none" (the app offers the plans again). incomplete / expired never change a
plan (a first payment that failed must not end a running free trial). The payer becomes a member of the brand.
Metrics (MRR, ARPU, churn, LTV) are in EUR: a monthly subscription adds its amount, a yearly one amount / 12, a one-time
seat 0; trialing customers are not counted as paying.
Stdlib only.
"""
import fcntl, json, os, subprocess, sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap

HERE = Path(__file__).parent
KEEP_EVENTS, KEEP_SEEN = 500, 5000
RUNNING = ("active", "trialing", "past_due")
ENDS = ("canceled",)                       # statuses that move a linked brand to the ended plan
PROVIDERS = ("stripe", "whop")
# approximate, fixed FX for the console's EUR figures (payments in other currencies; Whop backfills)
FX_EUR = {"EUR": 1.0, "USD": 0.86, "GBP": 1.16, "CHF": 1.07, "ILS": 0.26, "PLN": 0.235, "SEK": 0.091, "NOK": 0.085,
          "DKK": 0.134, "CZK": 0.041, "HUF": 0.0026, "RON": 0.20, "CAD": 0.62, "AUD": 0.57}

# background runs (the console's pattern): the tests replace it
SPAWN = lambda args: subprocess.Popen(args, cwd=str(HERE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      stdin=subprocess.DEVNULL, start_new_session=True)


# ---------------- storage ----------------

def billing_path():
    return Path(os.environ.get("OTTO_BILLING") or ap.DATA.parent / "billing.json")


def empty():
    return {"customers": {}, "payments": {}, "accounts": {}, "plans": {}, "events": [], "seen": [], "last_webhook_at": None,
            "last_webhook": {}, "last_backfill_at": None}


def load():
    f = billing_path()
    try:
        b = json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        b = {}
    out = empty()
    out.update(b if isinstance(b, dict) else {})
    for k in ("customers", "payments", "accounts", "plans", "last_webhook"):
        if not isinstance(out.get(k), dict):
            out[k] = {}
    for k in ("events", "seen"):
        if not isinstance(out.get(k), list):
            out[k] = []
    return out


@contextmanager
def transaction():
    """Lock billing.json.lock, fresh load, yield, atomic write (chmod 600). An exception discards the change."""
    f = billing_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f.with_name(f.name + ".lock"), "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            b = load()
            yield b
            ap._atomic_write(f, json.dumps(b, ensure_ascii=False, indent=1) + "\n")
            os.chmod(f, 0o600)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


# ---------------- small helpers ----------------

def provider_of(c):
    """A record's provider; records from before the field existed are Whop memberships (read-only migration)."""
    p = (c or {}).get("provider")
    return p if p in PROVIDERS else "whop"


def iso_ts(v):
    """Unix seconds (Stripe) → 'YYYY-MM-DDTHH:MM:SSZ', or None."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n / 1000 if n > 1e12 else n, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def to_eur(amount, currency, usd=None):
    if amount is None:
        return None
    cur = (currency or "EUR").upper()
    if cur in FX_EUR:
        return round(amount * FX_EUR[cur], 2)
    if usd is not None:
        return round(usd * FX_EUR["USD"], 2)
    return None


def mask_email(e):
    if not e or "@" not in str(e):
        return None
    user, dom = str(e).split("@", 1)
    return (user[:1] or "•") + "•••@" + dom


def email_domain(e):
    return str(e).split("@", 1)[1].lower().strip() if e and "@" in str(e) else None


def seen(eid):
    return bool(eid) and eid in load()["seen"]


def record_event(b, provider, eid, etype, ref, source="webhook"):
    """Inside a billing transaction: the event in the short log and (with an id) in the processed list, so a retry of the
    same event is a duplicate from now on."""
    now = ap.now_iso()
    b["events"].append({"id": eid or None, "type": etype, "ref": ref, "at": now, "source": source, "provider": provider})
    del b["events"][:-KEEP_EVENTS]
    if eid and eid not in b["seen"]:
        b["seen"].append(eid)
        del b["seen"][:-KEEP_SEEN]
    if source == "webhook":
        b["last_webhook_at"] = now
        b.setdefault("last_webhook", {})[provider] = now


# ---------------- reading: customers, metrics ----------------

def _whop_plans():
    try:
        import otto_whop
        return otto_whop.config()["plans"]
    except Exception:                                         # noqa: BLE001 — the console works without whop.json
        return {}


def plan_info(b, c, whop_plans=None):
    """{name, type renewal | one_time, price, currency, period_days} of a customer's plan (None values when unknown)."""
    if provider_of(c) == "stripe":
        p = ap.plans_config()["plans"].get(c.get("plan") or "") or {}
        label = p.get("label") or c.get("plan") or c.get("plan_id")
        iv = c.get("interval")
        if label and iv in ("month", "year"):
            label = f"{label} ({'yearly' if iv == 'year' else 'monthly'})"
        return {"name": label, "type": "one_time" if c.get("kind") == "one_time" else "renewal", "price": c.get("amount"),
                "currency": c.get("currency") or "EUR", "period_days": 365 if iv == "year" else 30}
    plans = dict(whop_plans if whop_plans is not None else _whop_plans())
    plans.update(b.get("plans") or {})
    return plans.get(c.get("plan_id")) or {}


def customer_rows(b=None, whop_plans=None):
    """Customers of every provider with plan, MRR (EUR), lifetime value and payments counted. Drafted / unpaid checkouts
    (Whop "drafted", Stripe incomplete / expired) are left out."""
    b = load() if b is None else b
    pays = {}
    for p in (b.get("payments") or {}).values():
        if isinstance(p, dict) and p.get("membership"):
            pays.setdefault(p["membership"], []).append(p)
    out = []
    for c in (b.get("customers") or {}).values():
        if not isinstance(c, dict) or not c.get("id") or c.get("status") in ("drafted", "incomplete", "expired"):
            continue
        prov = provider_of(c)
        pl = plan_info(b, c, whop_plans)
        mine = pays.get(c["id"], [])
        ltv = round(sum((p.get("amount_eur") or 0) - (p.get("refunded_eur") or 0) for p in mine if p.get("status") in ("paid", "refunded")), 2)
        mrr, est = 0.0, False
        if c.get("status") in ("active", "past_due"):
            if pl.get("type") == "renewal" and pl.get("price") is not None:
                mrr = (to_eur(pl["price"], pl.get("currency")) or 0) * 30 / max(1, int(pl.get("period_days") or 30))
                if prov == "stripe" and c.get("interval") == "year":
                    mrr = (to_eur(pl["price"], pl.get("currency")) or 0) / 12
            elif not pl and prov == "whop":
                subs = sorted([p for p in mine if p.get("status") == "paid" and str(p.get("reason", "")).startswith("subscription")],
                              key=lambda p: p.get("at") or "")
                if subs:
                    mrr, est = subs[-1].get("amount_eur") or 0, True
        out.append(dict(c, provider=prov, plan=pl.get("name") or c.get("plan") or c.get("plan_id") or "—", otto_plan=c.get("plan"),
                        plan_type=pl.get("type") or ("renewal" if est else None), mrr_eur=round(mrr, 2), mrr_estimated=est,
                        ltv_eur=ltv, payments=len(mine), failed_payments=sum(1 for p in mine if p.get("status") == "failed")))
    return sorted(out, key=lambda c: c.get("started") or "", reverse=True)


def metrics(customers, payments, now=None):
    """The console's billing numbers from customer_rows() and the payments: MRR / ARR / ARPU / churn / LTV / revenue (EUR)."""
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    month_start = month + "-01"
    cut30 = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pays = [p for p in (payments.values() if isinstance(payments, dict) else payments or []) if isinstance(p, dict)]
    rev30 = sum((p.get("amount_eur") or 0) - (p.get("refunded_eur") or 0) for p in pays
                if p.get("status") in ("paid", "refunded") and (p.get("at") or "") >= cut30)
    live = [c for c in customers if c.get("status") in ("active", "past_due")]
    subs = [c for c in live if c.get("mrr_eur")]
    mrr = round(sum(c.get("mrr_eur") or 0 for c in live), 2)
    start_active = [c for c in customers if (c.get("started") or "") < month_start and not ((c.get("canceled_at") or "9999") < month_start)]
    churned = [c for c in customers if (c.get("canceled_at") or "").startswith(month)]
    ltvs = [c["ltv_eur"] for c in customers if c.get("ltv_eur")]
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    return {"mrr_eur": mrr, "arr_eur": round(mrr * 12, 2), "paying": len(live),
            "active": sum(1 for c in customers if c.get("status") == "active"),
            "trialing": sum(1 for c in customers if c.get("status") == "trialing"),
            "past_due": sum(1 for c in customers if c.get("status") == "past_due"),
            "canceled": sum(1 for c in customers if c.get("status") == "canceled"),
            "canceling": sum(1 for c in customers if c.get("cancel_at_period_end") and c.get("status") in RUNNING),
            "new_this_month": sum(1 for c in customers if (c.get("started") or "").startswith(month)),
            "churned_this_month": len(churned), "churn_rate_month": pct(len(churned), len(start_active)),
            "arpu_eur": round(mrr / len(subs), 2) if subs else None,
            "avg_ltv_eur": round(sum(ltvs) / len(ltvs), 2) if ltvs else None,
            "revenue_30d_eur": round(rev30, 2), "lifetime_revenue_eur": round(sum(ltvs), 2),
            "by_provider": {p: sum(1 for c in live if c.get("provider") == p) for p in PROVIDERS}}


def running_for_brand(bid, b=None, provider=None):
    """The brand's running customer (newest first), or None."""
    b = load() if b is None else b
    rows = [c for c in (b.get("customers") or {}).values() if isinstance(c, dict) and c.get("brand_id") == bid
            and c.get("status") in RUNNING and (provider is None or provider_of(c) == provider)]
    rows.sort(key=lambda c: (c.get("kind") != "one_time", c.get("started") or ""), reverse=True)
    return rows[0] if rows else None


def latest_for_brand(bid, b=None):
    b = load() if b is None else b
    rows = [c for c in (b.get("customers") or {}).values() if isinstance(c, dict) and c.get("brand_id") == bid
            and c.get("status") not in ("drafted", "incomplete", "expired")]
    rows.sort(key=lambda c: (c.get("status") in RUNNING, c.get("updated_at") or c.get("started") or ""), reverse=True)
    return rows[0] if rows else None


def brand_summary(bid, b=None):
    """What the app shows about a brand's billing: {provider, status, plan, label, interval, amount, currency, renews,
    period_end, trial_end, cancel_at_period_end, pending, past_due} or None (never billed)."""
    c = latest_for_brand(bid, b)
    if not c:
        return None
    cfg = ap.plans_config()["plans"]
    pend = c.get("pending") if isinstance(c.get("pending"), dict) else None
    return {"provider": provider_of(c), "status": c.get("status"), "kind": c.get("kind") or ("one_time" if provider_of(c) == "whop" else "subscription"),
            "plan": c.get("plan") or (ap.plan_for_whop(c.get("plan_id")) if provider_of(c) == "whop" else None),
            "label": (cfg.get(c.get("plan") or "") or {}).get("label"), "interval": c.get("interval"), "amount": c.get("amount"),
            "currency": c.get("currency"), "renews": c.get("renews"), "period_end": c.get("period_end"),
            "trial_end": c.get("trial_end"), "cancel_at_period_end": bool(c.get("cancel_at_period_end")),
            "pending": ({"plan": pend.get("plan"), "label": (cfg.get(pend.get("plan") or "") or {}).get("label"),
                         "interval": pend.get("interval"), "at": pend.get("at")} if pend else None),
            "past_due": c.get("status") == "past_due"}


# ---------------- linking + entitlement ----------------

def plan_for(c):
    """(Otto plan id or None, why) for a customer: its plan while it runs, plans.json defaults.ended once it ended, None
    (unchanged) for an unmapped price / plan, an unpaid checkout or an unknown status."""
    st = (c or {}).get("status")
    cfg = ap.plans_config()
    if cfg.get("error"):
        return None, f"plans.json is unreadable ({cfg['error'][:120]})"
    prov = provider_of(c)
    what = "membership" if prov == "whop" else "subscription" if (c or {}).get("kind") != "one_time" else "purchase"
    if st in ENDS:
        return cfg["defaults"]["ended"], f"the {what} ended"
    if st in RUNNING:
        if prov == "whop":
            pid = ap.plan_for_whop(c.get("plan_id"))
            if pid:
                return pid, f"Whop plan {c.get('plan_id')}"
            return None, f"Whop plan {c.get('plan_id') or '(none)'} is not mapped in plans.json whop_plan_ids — plan unchanged"
        pid = c.get("plan") if c.get("plan") in cfg["plans"] else (ap.plan_for_price(c.get("plan_id")) or (None, None))[0]
        if pid:
            return pid, f"Stripe price {c.get('plan_id')}"
        return None, f"Stripe price {c.get('plan_id') or '(none)'} is not in plans.json stripe_price_ids — plan unchanged"
    return None, f"{what} is {st or 'unknown'} — plan unchanged"


def _users_of(d, c):
    """The users[] records a customer pays for: the one our signed checkout reference names, else the brand's trial user."""
    out = []
    uid = c.get("user_id") or (c.get("ref") or {}).get("user")
    b = ap.brand(d, c.get("brand_id")) if c.get("brand_id") else None
    tuid = ((b or {}).get("trial") or {}).get("user")
    for u in d.get("users") or []:
        if isinstance(u, dict) and u.get("id") and u["id"] in (uid, tuid):
            out.append(u)
    return out


def sync_plan(c, by=None, spawn=None):
    """Give the brand a linked customer belongs to the plan the customer says (plan_for). One data.json transaction; a move
    to the ended plan files one owner card. → {brand, changed, from, to, why, live, ...} or None (no brand / unknown brand)."""
    bid = (c or {}).get("brand_id")
    if not bid:
        return None
    prov = provider_of(c)
    by = by or prov
    target, why = plan_for(c)
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            return None
        cur = ap.plan_of(d, bid)
        res = {"brand": bid, "changed": False, "from": cur["id"], "to": cur["id"], "why": why, "live": []}
        ended = ap.plans_config()["defaults"]["ended"]
        if target is not None and target != ended:
            if b.get("plan_billing"):
                b.pop("plan_billing", None)                    # a running subscription pays for it now: billed
                res["billed"] = True
            if b.get("status") == "onboarding":                # paid and linked: otto_cron runs "active" brands only
                b["status"] = "active"
                res["activated"] = True
            for u in _users_of(d, c):                          # the payer: paid, the app stops offering the plans
                if u.get("status") != "active":
                    u["status"] = "active"
                u.setdefault("paid_at", ap.now_iso())
        elif target == ended:
            others = [x for x in load()["customers"].values() if isinstance(x, dict) and x.get("id") != c.get("id")
                      and x.get("status") in RUNNING and (x.get("user_id") or (x.get("ref") or {}).get("user"))]
            busy = {x.get("user_id") or (x.get("ref") or {}).get("user") for x in others}
            for u in _users_of(d, c):
                if u.get("status") == "active" and u["id"] not in busy:
                    u["status"] = "none"                       # nothing running for them: the app offers the plans again
        if target is None or b.get("plan") == target:        # the same plan: nothing to do (an owner-set plan_until stays)
            return res
        keep = cur["requested"] == target                    # a legacy record made explicit keeps its pilot end date
        extra = {"membership": c.get("id"), "whop_plan": c.get("plan_id")} if prov == "whop" else \
            {"subscription": c.get("id"), "price": c.get("plan_id")}
        _, after = ap.set_plan(d, bid, target, until=ap.KEEP if keep else None, by=by, via=prov, note=why, **extra)
        res.update(changed=True, to=after["id"])
        res["live"] = [x["id"] for x in d.get("campaigns", []) if isinstance(x, dict) and x.get("brand") == bid
                       and x.get("status") == "live" and ap.no_ads_why(d, bid, x.get("network"))]
        name = b.get("name") or bid
        if target == ended:
            what = "membership" if prov == "whop" else "subscription"
            src = "Whop membership" if prov == "whop" else "Stripe subscription" if c.get("kind") != "one_time" else "Stripe purchase"
            ap.add_rec(d, "P1", f"{name}: {what} ended — publishing paused",
                       f"The {src} {c.get('id')} was canceled or expired, so {name} is on “{after['label']}”: no post "
                       "publishes and no ad launches" + (f", and its {len(res['live'])} live campaign"
                                                         f"{'s are' if len(res['live']) != 1 else ' is'} being paused" if res["live"] else "")
                       + ". Nothing was deleted; a new subscription or choosing a plan in the console resumes it. "
                       "Without a plan its data is deleted 90 days from now (owner notices 14 and 3 days before; "
                       "otto_retention.py hold keeps it).",
                       "No work the client does not pay for", "Check with the client", brand=bid, source="plans",
                       audience="owner", action="plan", membership=c.get("id"))
    return res


def after_plan_change(results, spawn=None):
    """Live campaigns a plan change no longer covers are paused now: `otto_ads.py guard` in the background (plan_guard
    pauses them through the normal pause path and says so). The daily guard would catch them anyway."""
    if any(r and r.get("live") for r in results or []):
        try:
            (spawn or SPAWN)([sys.executable, str(HERE / "otto_ads.py"), "guard"])
        except OSError as e:
            print(f"could not start otto_ads.py guard ({e}) — the daily guard pauses them", file=sys.stderr)


def link(customer_id, brand_id, by="cli", spawn=None):
    """Tie a customer to a brand ("" unlinks), make the payer a member of it (brands[].members) and give the brand the
    customer's plan (sync_plan). Unlinking leaves the brand's plan and members as they are. A Stripe customer also becomes
    the brand's billing account (accounts[brand]: the app's Billing page manages it). → the customer, with "plan_sync" and
    "member_added" when a brand was linked."""
    with transaction() as b:
        c = b["customers"].get(customer_id)
        if c is None:
            raise KeyError(customer_id)
        if brand_id:
            c["brand_id"] = brand_id
            c["brand_link"] = {"by": by, "at": ap.now_iso()}
            if provider_of(c) == "stripe" and c.get("customer"):
                acct = b["accounts"].setdefault(brand_id, {})
                acct.update(provider="stripe", customer=c["customer"], email=c.get("email") or acct.get("email"),
                            at=acct.get("at") or ap.now_iso())
        else:
            c.pop("brand_id", None)
            c.pop("brand_link", None)
        c = dict(c)
    if brand_id:
        email = ap.norm_member(c.get("email"))
        with ap.transaction() as d:
            bb = ap.brand(d, brand_id)
            emails = [email] if email and not email.startswith("@") else []
            for u in _users_of(d, c):                          # the signed-in buyer (our reference) belongs to it too
                e = ap.norm_member(u.get("email"))
                if e and e not in emails:
                    emails.append(e)
                if brand_id not in (u.get("brands") or []) and c.get("user_id") == u.get("id"):
                    u["brands"] = list(u.get("brands") or []) + [brand_id]
            if bb is not None:
                for e in emails:
                    if e not in (bb.get("members") or []):
                        bb["members"] = list(bb.get("members") or []) + [e]
                        c.setdefault("member_added", e)
        res = sync_plan(c, by=by)
        c["plan_sync"] = res
        if res and res.get("changed"):
            after_plan_change([res], spawn)
    return c


def user_summary(d, u):
    """The billing lines of a signed-in user's brands for GET /auth/me: [{brand, name, …brand_summary}]."""
    b = load()
    bids = sorted(ap.member_brands(d, u.get("email"), domains=False))      # only brands they still belong to
    out = []
    for bid in bids:
        br = ap.brand(d, bid)
        s = brand_summary(bid, b) if br else None
        if s:
            out.append(dict(s, brand=bid, name=(br or {}).get("name") or bid))
    return out


def main(a):
    cmd = a[0] if a else ""
    if cmd == "customers":
        rows = customer_rows()
        if "--json" in a:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for c in rows:
                print(f"{c['provider']:6} {c['id']:24} {c.get('status', ''):9} {str(c['plan'])[:22]:22} €{c['mrr_eur']:>7.2f}/mo  "
                      f"€{c['ltv_eur']:>8.2f}  {mask_email(c.get('email')) or '—':28} {c.get('brand_id') or ''}")
            print(f"-- {len(rows)} customers")
        return 0
    if cmd == "link" and len(a) > 1:
        c = link(a[1], a[2] if len(a) > 2 else "")
        ps = c.get("plan_sync") or {}
        print(f"{c['id']} → {c.get('brand_id') or 'unlinked'}"
              + (f" · plan {ps['from']} → {ps['to']}" if ps.get("changed") else f" · plan unchanged ({ps['why']})" if ps else ""))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
