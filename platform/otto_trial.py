#!/usr/bin/env python3
"""Otto free trial — 7 days, no card, one per Google account and per website domain; after it, a card (Billing page, Stripe).

  otto_trial.py run [--now ISO] [--dry]      # the hourly job (otto_cron "trials"): ends trials, sends the reminder e-mails
  otto_trial.py status [--json]              # every trial: who (masked), brand, ends, days left, reminders, converted
  otto_trial.py offers <email>               # the "add a card" offers (each opens the plan on the Billing page)

Sign-up (otto_auth, first Google login): start_for_new_user gives the user trial_started_at = now, trial_ends_at = now +
trial_days (plans.json: the plan named by defaults.trial, "trial", trial_days 7) and status "trial" — unless that e-mail had a
trial before (the ledger, below): then status "none" and no trial. Users: data.json users[] {id, email, name, google_sub, hd,
created_at, last_login_at, trial_started_at, trial_ends_at, status trial | active | expired | none, brands (ids it created),
trial_reminders {day5, day7, day8}, paid_at}.
First brand (signed-in onboarding, otto_onboard.create → brand_on_signup): with the trial running and the site's domain never
trialled, the brand starts on the trial plan with plan_until = the trial's last day (brand-local; the fallback — this job ends
it on the hour), status "active" (its jobs run during the trial), the user as member, brands[].trial = {user, started_at,
ends_at}. Otherwise — trial over, e-mail or domain already trialled, a second brand, trials switched off — the brand starts on
the ended plan ("none") with brands[].trial.denied = why, and the app shows the "add a card" screen. The ledger (data.json
trial_ledger[]: "e:" / "d:" + SHA-256 of the lower-case e-mail / site host) outlives deleted users and brands, so a trial is
given once per Google account e-mail and once per website domain.
During the trial: the trial plan inherits Starter; paid ads are planned and rendered for preview, never launched
(features.ads_launch false → ap.no_launch_why).
The job (hourly): a brand whose trial ended without a paid plan moves to the ended plan ("none": publishing and ads pause;
ap.set_plan with effective = the trial's end, so otto_retention's 90 days count from the trial's end) with one owner card; the
user becomes "expired". Reminder e-mails to the user (otto_email.deliver: its transport, or the outbox): day5 "2 days left"
(48 hours before the end), day7 "ends today / tomorrow" (24 hours before), day8 "paused, your work is kept for 90 days — add
a card to continue" (after the end) — each once (claimed in data.json before sending; a failed send is retried next hour;
a reminder whose window has passed is never sent late, and day8 not more than 7 days late). Each reminder speaks the
language the user's brand chose for e-mails (brands[].comms_lang, otto_i18n: en by default, nl, de), dates and prices in
its locale. A trial's first week that is still unwritten 15 minutes after its kickoff
(the copywriter otto_copy normally starts in the background at onboarding) is written inline here (copy_catchup; only with
an Anthropic key). Users without any brand, whose
trial is over and who have not signed in for 90 days, are removed (their sessions end); the ledger keeps the hashes only,
for LEDGER_DAYS (3 years), then drops them.
Paying (Stripe, otto_stripe; Whop is legacy): the "add a card" screen offers plans.json trial.checkout_plans (Starter,
Growth); each opens Otto's own Billing page (app.<domain>/billing.html?plan=…), where the payment form is Stripe's embedded
Checkout for that plan's stripe_price_ids. A plan with no price yet is "not on sale yet"; without Stripe keys every offer
says "Payments aren't set up yet". A user who pays while their trial still runs is charged only when it ends (the
subscription starts at the trial's end). The Checkout Session carries our signed reference (brand + user, HMAC), so the
webhook links the subscription to exactly that brand: autolink() → otto_billing.link (member, plan from
stripe_price_ids, plan_until cleared, trial converted, user active) — no e-mail matching for Stripe. Bought before the
brand existed (the founding seat from the landing): link_pending() links it at onboarding, by the user id in the
reference. Idempotent: a linked customer is never linked again. The legacy Whop memberships still link by the verified
e-mail (autolink with provider "whop"). Everything else stays the owner's manual link (console → Customers → link).
The reminder e-mails' "Add a card" button opens the Billing page (billing.html).
Stdlib only; every data.json write goes through ap.transaction().
"""
import hashlib, html, json, math, os, re, sys, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import ap

DEFAULT_DAYS = 7
RETENTION_DAYS = 90
USER_IDLE_DAYS = 90
LEDGER_DAYS = 3 * 365          # the "one trial per e-mail / domain" hashes (Privacy Policy: [3 YEARS] — Max decides)
DAY8_LATE = timedelta(days=7)
REMINDERS = (("day8", timedelta(0)), ("day7", timedelta(days=1)), ("day5", timedelta(days=2)))   # sent when this much is left
RUNNING = ("active", "trialing", "past_due")


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(v):
    dt = ap.parse_iso(v)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) if dt else None


def trial_plan():
    """(plan id, resolved plan) of the free trial, or (None, None) when plans.json has no defaults.trial."""
    pid = ap.trial_plan_id()
    return (pid, ap.plans_config()["plans"][pid]) if pid else (None, None)


def trial_days():
    _, p = trial_plan()
    return int((p or {}).get("trial_days") or DEFAULT_DAYS)


def ended_plan():
    return ap.plans_config()["defaults"]["ended"]


def owner_tz():
    for name in (os.environ.get("OTTO_OWNER_TZ"), os.environ.get("OTTO_TZ"), ap.DEFAULT_TZ):
        try:
            if name:
                return ZoneInfo(name)
        except Exception:
            continue
    return ZoneInfo(ap.DEFAULT_TZ)


def users(d):
    return [u for u in d.get("users") or [] if isinstance(u, dict) and u.get("id")]


def user_by_email(d, email):
    e = str(email or "").strip().lower()
    return next((u for u in users(d) if str(u.get("email") or "").lower() == e), None) if e else None


def mask(e):
    e = str(e or "")
    if "@" not in e:
        return "•••"
    a, dom = e.split("@", 1)
    return (a[:1] or "•") + "•••@" + dom


# ------------------------------------------------------------------------------------------------------------ the ledger

def ledger_key(kind, value):
    return f"{kind}:" + hashlib.sha256(str(value or "").strip().lower().encode()).hexdigest()


def ledger_has(d, kind, value):
    k = ledger_key(kind, value)
    return any(isinstance(x, dict) and x.get("k") == k for x in d.get("trial_ledger") or [])


def ledger_add(d, kind, value, now=None):
    if value and not ledger_has(d, kind, value):
        d.setdefault("trial_ledger", []).append({"k": ledger_key(kind, value), "at": iso(now or utcnow())})


# ------------------------------------------------------------------------------------------------------------ sign-up + first brand

def start_for_new_user(d, u, now=None):
    """A first Google login (inside otto_auth's transaction): the trial clock starts now, once per e-mail."""
    now = now or utcnow()
    u.setdefault("brands", [])
    if trial_plan()[0] is None:
        u.update(status="none", trial_denied="off")
    elif ledger_has(d, "e", u["email"]):
        u.update(status="none", trial_denied="email")
    else:
        u.update(status="trial", trial_started_at=iso(now), trial_ends_at=iso(now + timedelta(days=trial_days())))
        ledger_add(d, "e", u["email"], now)
    return u


DENIED = {"off": "Free trials are not available right now.",
          "email": "This Google account already had its free trial.",
          "domain": "This website already had a free trial.",
          "ended": "Your free trial has ended.",
          "one_brand": "The free trial covers one business."}


def brand_on_signup(d, b, uid, host, now=None):
    """A brand a signed-in user just created (inside otto_onboard's transaction): the trial plan while the user's trial runs
    and the domain never had one; the ended plan otherwise. → {"granted": bool, "ends_at"?, "why"?, "message"}."""
    now = now or utcnow()
    u = next((x for x in users(d) if x.get("id") == uid), None)
    tp, ended = trial_plan()[0], ended_plan()
    b.pop("plan_billing", None)
    b["status"] = "active"
    why = None
    ends = _dt((u or {}).get("trial_ends_at"))
    if tp is None:
        why = "off"
    elif u is None or u.get("status") != "trial" or ends is None:
        why = (u or {}).get("trial_denied") or ("ended" if ends else "email")
    elif now >= ends:
        why = "ended"
    elif any(isinstance(x, dict) and x.get("id") != b["id"] and (x.get("trial") or {}).get("user") == uid
             and not (x.get("trial") or {}).get("denied") for x in d.get("brands") or []):
        why = "one_brand"
    elif ledger_has(d, "d", host):
        why = "domain"
    if u is not None and b["id"] not in (u.get("brands") or []):
        u["brands"] = list(u.get("brands") or []) + [b["id"]]
    if why is None:
        b["plan"] = tp
        b["plan_until"] = ends.astimezone(ap.brand_tz(b)).date().isoformat()
        b["trial"] = {"user": uid, "started_at": u["trial_started_at"], "ends_at": u["trial_ends_at"]}
        ledger_add(d, "d", host, now)
        return {"granted": True, "ends_at": u["trial_ends_at"], "days": trial_days(),
                "message": f"Your free trial runs until {when_text(ends, ap.brand_tz(b))}. No card needed until then."}
    b["plan"] = ended
    b.pop("plan_until", None)
    b["trial"] = {"user": uid, "denied": why, "at": iso(now)}
    b["plan_history"] = (b.get("plan_history") or [])[-19:] + [{"at": iso(now), "by": "trial", "via": "trial", "from": None,
                                                                "to": ended, "until": None, "note": f"no free trial ({why})"}]
    return {"granted": False, "why": why, "message": DENIED.get(why, DENIED["ended"]) + " Add a card to start."}


def when_day(dt, tz):
    loc = dt.astimezone(tz)
    return f"{loc:%a} {loc.day} {loc:%b}"


def when_text(dt, tz):
    loc = dt.astimezone(tz)
    return f"{loc:%a} {loc.day} {loc:%b}, {loc:%H:%M}"


# ------------------------------------------------------------------------------------------------------------ the app's view

def plan_lines(p, t=None):
    """A plan in three short lines for the "add a card" screen (English, the app's language) or a reminder e-mail (t)."""
    import otto_i18n
    t = t or otto_i18n.Tr()
    f, L = p["features"], p["limits"]
    out = []
    if L.get("posts_per_month"):
        out.append(t("trial.line.posts", posts=t.num(L["posts_per_month"]), reels=t.num(L.get("reels_per_month") or 0)))
    nets = t.join([n for n, k in (("Meta", "ads_meta"), ("Google", "ads_google")) if f.get(k)])
    if nets:
        cap = L.get("ad_spend_managed_eur_month")
        out.append(t("trial.line.paid", nets=nets) + (t("trial.line.cap", cap=t.money(cap, "EUR")) if cap else ""))
    if f.get("ad_matrix") and ap.PRESET_TEXT.get(L.get("ad_matrix_preset")):
        out.append(t("trial.line.matrix", preset=t("preset." + L["ad_matrix_preset"])))
    return out


def billing_page(plan=None, interval=None):
    """Otto's own Billing page on app.<domain> (otto_stripe.billing_url), optionally opened on one plan's checkout."""
    try:
        import otto_stripe
        return otto_stripe.billing_url(plan=plan, interval=interval)
    except Exception:                                        # noqa: BLE001 — a link, never a reason to fail a page
        import otto_paths
        return otto_paths.app_url() + "billing.html" + (f"?plan={urllib.parse.quote(plan)}" if plan else "")


def payments_ready():
    try:
        import otto_stripe
        return otto_stripe.ready()
    except Exception:                                        # noqa: BLE001
        return False


def checkout_offers(email=None, t=None):
    """[{plan, label, monthly_eur, yearly_eur, draft, lines, on_sale, month, year, checkout_url, why}] — plans.json
    trial.checkout_plans (default Starter and Growth). checkout_url opens the plan on Otto's Billing page; it is None while
    the plan has no Stripe price (why "not_on_sale") or payments are not set up (why "not_configured"). t = the language of
    the lines; email is kept for the callers' signature (the Billing page knows the signed-in user)."""
    cfg = ap.plans_config()
    _, tp = trial_plan()
    ids = (tp or {}).get("checkout_plans") or [x for x in ("starter", "growth") if x in cfg["plans"]]
    live, out = payments_ready(), []
    for pid in ids:
        p = cfg["plans"].get(pid)
        if not p:
            continue
        month, year = bool(ap.price_for(pid, "month")), bool(ap.price_for(pid, "year"))   # no yearly where yearly_eur is null
        on_sale = month or year
        why = None if live and on_sale else "not_configured" if not live else "not_on_sale"
        out.append({"plan": pid, "label": p["label"], "monthly_eur": p.get("monthly_eur"), "yearly_eur": p.get("yearly_eur"),
                    "draft": p.get("status") == "draft", "lines": plan_lines(p, t), "on_sale": on_sale,
                    "month": month, "year": year, "why": why,
                    "checkout_url": billing_page(pid) if why is None else None})
    return out


def trial_state(u, now=None):
    """{state running | ended | converted | none, started_at, ends_at, days_left, hours_left, denied}."""
    now = now or utcnow()
    ends = _dt(u.get("trial_ends_at"))
    st = u.get("status")
    out = {"started_at": u.get("trial_started_at"), "ends_at": u.get("trial_ends_at"), "denied": u.get("trial_denied")}
    if st == "active" and u.get("paid_at"):
        out["state"] = "converted"
    elif ends is None:
        out["state"] = "none"
    elif now < ends:
        left = (ends - now).total_seconds()
        out.update(state="running", days_left=max(1, math.ceil(left / 86400)), hours_left=max(1, math.ceil(left / 3600)))
    else:
        out["state"] = "ended"
    return out


def account_view(d, u, now=None):
    """GET /auth/me for a signed-in user: who, the trial, their brands, the "add a card" offers while they need one."""
    now = now or utcnow()
    tr = trial_state(u, now)
    bids = sorted(ap.member_brands(d, u["email"], domains=domain_ok(u)))
    brands = [{"id": b["id"], "name": b.get("name") or b["id"], "plan": ap.plan_of(d, b["id"])["id"],
               "trial_ended": ap.trial_ended(d, b["id"])} for b in d.get("brands") or [] if isinstance(b, dict) and b.get("id") in bids]
    needs_card = tr["state"] != "converted" and (tr["state"] in ("running", "ended", "none") or any(x["trial_ended"] for x in brands))
    try:
        import otto_billing
        bill = otto_billing.user_summary(d, u)
    except Exception:                                        # noqa: BLE001 — the account works without billing.json
        bill = []
    return {"signed_in": True, "email": u["email"], "name": u.get("name") or "", "status": u.get("status") or "none",
            "trial": tr, "brands": brands, "checkout": checkout_offers(u["email"]) if needs_card else [],
            "billing_email": u["email"], "billing": bill, "payments": payments_ready(), "billing_url": billing_page()}


def domain_ok(u):
    """A Google sign-in counts for "@domain" members only when it is a Google Workspace account of that domain (hd)."""
    e = str(u.get("email") or "")
    return bool(u.get("hd")) and "@" in e and e.rsplit("@", 1)[1].lower() == str(u.get("hd")).lower()


def paywall(d, bids, u=None, now=None):
    """The 402 answer when every brand the caller belongs to came from a trial that ended without a card (else None)."""
    bids = set(bids or ())
    if not bids or not all(ap.trial_ended(d, bid) for bid in bids):
        return None
    now = now or utcnow()
    rows, ended_at, why = [], None, None
    for bid in sorted(bids):
        b = ap.brand(d, bid) or {}
        tr = b.get("trial") or {}
        why = why or tr.get("denied")
        e = _dt(tr.get("ended_at") or tr.get("ends_at"))
        ended_at = max(ended_at, e) if ended_at and e else (e or ended_at)
        rows.append({"id": bid, "name": b.get("name") or bid})
    email = (u or {}).get("email")
    return {"error": "trial ended" if not why else "no free trial", "code": "trial_ended" if not why else "no_trial",
            "why": why, "message": (f"Your free trial ended on {when_day(ended_at, owner_tz())}. Your work is kept: add a "
                                    "card to continue where you left off." if ended_at and not why else
                                    DENIED.get(why, DENIED["ended"]) + " Add a card to start."),
            "ended_at": iso(ended_at) if ended_at else None,
            "kept_until": iso(ended_at + timedelta(days=RETENTION_DAYS)) if ended_at else None,
            "brands": rows, "checkout": checkout_offers(email), "billing_email": email, "payments": payments_ready(),
            "billing_url": billing_page()}


# ------------------------------------------------------------------------------------------------------------ paid → linked

def _brand_for(d, u, billing):
    """The user's brand a new subscription belongs to when our reference names no brand (bought before onboarding): a trial
    brand of theirs (ended first, then running) that no running subscription is linked to yet."""
    taken = {c.get("brand_id") for c in (billing.get("customers") or {}).values()
             if isinstance(c, dict) and c.get("brand_id") and c.get("status") in RUNNING}
    mine = [b for b in d.get("brands") or [] if isinstance(b, dict) and b.get("id") in (u.get("brands") or [])
            and (b.get("trial") or {}).get("user") == u["id"] and b["id"] not in taken]
    mine.sort(key=lambda b: (not ap.trial_ended(d, b["id"]), b.get("plan") != ap.trial_plan_id()))
    return mine[0]["id"] if mine else None


def autolink(c, by=None):
    """A running customer that is not linked yet → otto_billing.link to its brand. Stripe: the brand + user of our signed
    checkout reference (c["ref"], verified by otto_stripe) — the user must still exist and belong to that brand; a reference
    without a brand (paid before onboarding) takes the user's own trial brand, if any (else link_pending at onboarding).
    Legacy Whop: the membership's e-mail equals a signed-in user's verified Google e-mail and the Whop plan is mapped.
    Never a customer that is linked already. → the linked customer (otto_billing.link's answer) or None."""
    import otto_billing
    if not c or c.get("brand_id") or c.get("status") not in RUNNING:
        return None
    fresh = (otto_billing.load().get("customers") or {}).get(c.get("id")) or {}
    if fresh.get("brand_id"):
        return None                                            # linked meanwhile (a retry of the same event, the console)
    d = ap.load()
    if otto_billing.provider_of(c) == "stripe":
        ref = c.get("ref") if isinstance(c.get("ref"), dict) else None
        u = next((x for x in users(d) if ref and x.get("id") == ref.get("user")), None)
        if u is None:
            return None
        bid = ref.get("brand")
        if bid:
            if ap.brand(d, bid) is None or bid not in (ap.member_brands(d, u["email"], domains=domain_ok(u)) | set(u.get("brands") or [])):
                return None                                    # the brand is gone, or no longer theirs: the owner decides
        else:
            bid = _brand_for(d, u, otto_billing.load())
            if not bid:
                return None
        return otto_billing.link(c["id"], bid, by=by or "auto: signed checkout reference")
    email = str(c.get("email") or "").strip().lower()                    # legacy Whop: the verified Google e-mail
    if not email or not ap.plan_for_whop(c.get("plan_id")):
        return None
    u = user_by_email(d, email)
    if u is None or not u.get("google_sub"):
        return None
    bid = _brand_for(d, u, otto_billing.load())
    if not bid:
        return None
    import otto_whop
    return otto_whop.link(c["id"], bid, by=by or "auto: verified Google e-mail")


def link_pending(u):
    """At onboarding: a subscription / seat this user paid for before the brand existed is linked now (Stripe: by the user id
    in our signed reference; legacy Whop: by the verified e-mail). → the linked customer or None."""
    import otto_billing
    email = str((u or {}).get("email") or "").lower()
    for c in (otto_billing.load().get("customers") or {}).values():
        if not isinstance(c, dict) or c.get("brand_id"):
            continue
        mine = ((c.get("ref") or {}).get("user") == (u or {}).get("id")) if otto_billing.provider_of(c) == "stripe" \
            else str(c.get("email") or "").lower() == email
        if mine:
            out = autolink(c)
            if out:
                return out
    return None


# ------------------------------------------------------------------------------------------------------------ reminder e-mails

def _tz_for(d, u):
    for b in d.get("brands") or []:
        if isinstance(b, dict) and b.get("id") in (u.get("brands") or []):
            return ap.brand_tz(b), b.get("name") or b["id"], b["id"]
    return owner_tz(), "", "account"


def _tr_for(d, u):
    """The reminder's language: the comms_lang of the user's first brand (otto_i18n), else English."""
    import otto_i18n
    for b in d.get("brands") or []:
        if isinstance(b, dict) and b.get("id") in (u.get("brands") or []):
            return otto_i18n.Tr.for_brand(b)
    return otto_i18n.Tr()


def due_reminder(u, now):
    """The reminder this user is due now, or None (the latest window only; each once)."""
    if u.get("status") not in ("trial", "expired") or u.get("paid_at"):
        return None
    ends = _dt(u.get("trial_ends_at"))
    if ends is None:
        return None
    left = ends - now
    sent = u.get("trial_reminders") if isinstance(u.get("trial_reminders"), dict) else {}
    for key, window in REMINDERS:
        if left <= window:
            if key in sent or (key == "day8" and now - ends > DAY8_LATE):
                return None
            return key
    return None


def render(key, u, d, now):
    """→ (subject, html, text) of one reminder, in the comms_lang of the user's brand (English by default)."""
    import otto_email as em
    tz, name, _ = _tz_for(d, u)
    t = _tr_for(d, u)
    ends = _dt(u["trial_ends_at"])
    loc_end, loc_now = ends.astimezone(tz), now.astimezone(tz)
    when = t.day_at(loc_end)
    link = em.app_url() + "billing.html"                         # Otto's Billing page: choose a plan, add a card
    who = name or t("trial.your_business")
    kept = (ends + timedelta(days=RETENTION_DAYS)).astimezone(tz)
    offers = checkout_offers(u["email"], t)
    monthly = [o for o in offers if o.get("monthly_eur") is not None]
    price = t("trial.price", price=t.money(min(o["monthly_eur"] for o in monthly), "EUR")) if monthly else ""
    if key == "day5":
        subject, title = t("trial.day5.subject"), t("trial.day5.title")
        lead = t("trial.day5.lead", when=when, who=who, price=price)
        cta = t("trial.cta")
    elif key == "day7":
        w = "today" if loc_end.date() == loc_now.date() else "tomorrow"
        subject, title = t(f"trial.day7.subject_{w}"), t(f"trial.day7.title_{w}")
        lead = t("trial.day7.lead", time=t.time(loc_end), day=t.day(loc_end), who=who, price=price)
        cta = t("trial.cta")
    else:
        subject = t("trial.day8.subject_named", who=who) if name else t("trial.day8.subject")
        title = t("trial.day8.title")
        lead = t("trial.day8.lead_named", who=who, kept=t.day(kept)) if name else t("trial.day8.lead")
        cta = t("trial.cta_continue")
    E = em.esc
    btn = em.button(cta, link, primary=True)
    per = lambda o: (" · " + t("trial.a_month", price=t.money(o["monthly_eur"], "EUR"))) if o.get("monthly_eur") is not None else ""
    lines = "".join(f'<p style="{em.fstyle(14, 20, 400, em.L["ink2"])}">{E(o["label"])}{E(per(o))}'
                    f'{" — " + E("; ".join(o["lines"][:2])) if o["lines"] else ""}</p>' for o in offers)
    blocks = [em.card(lines + '<div style="margin-top:14px;">' + btn + "</div>") if lines else em.card(btn)]
    foot = E(t("trial.why", email=u["email"])) + " " + E(t("trial.terms"))
    html_body = em.layout(subject, lead[:120], name, title, E(lead), blocks, foot, lang=t.lang)
    text = f"{title}\n\n{lead}\n\n{cta}: {link}\n\n" + "".join(f"- {o['label']}{per(o)}\n" for o in offers) + \
        f"\n{t('trial.why', email=u['email'])} {t('trial.terms')}\n"
    return subject, html_body, text


# ------------------------------------------------------------------------------------------------------------ the job

def _trial_end(b):
    """When this trial brand's trial ends: brands[].trial.ends_at, else (a trial set by hand) the day after plan_until."""
    tr = b.get("trial") if isinstance(b.get("trial"), dict) else {}
    end = _dt(tr.get("ends_at"))
    if end is None:
        until = ap._plan_date(b.get("plan_until"))
        end = datetime.combine(until + timedelta(days=1), datetime.min.time(), ap.brand_tz(b)) if until else None
    return end


def _expire_due(d, now):
    tp = ap.trial_plan_id()
    due = [b for b in d.get("brands") or [] if isinstance(b, dict) and tp and b.get("plan") == tp
           and not (b.get("trial") or {}).get("converted_at") and _trial_end(b) and now >= _trial_end(b)]
    return due or [u for u in users(d) if u.get("status") == "trial" and _dt(u.get("trial_ends_at")) and now >= _dt(u["trial_ends_at"])]


def expire(now=None, out=print):
    """Trials past their end: brands → the ended plan (effective = the trial's end), users → expired. → brand ids ended."""
    now = now or utcnow()
    tp, ended = ap.trial_plan_id(), ended_plan()
    done = []
    if not _expire_due(ap.load(), now):                          # the usual hour: nothing to end, nothing written
        return done
    with ap.transaction() as d:
        for b in d.get("brands") or []:
            if not isinstance(b, dict) or not b.get("id") or b.get("plan") != tp or tp is None:
                continue
            tr = b.get("trial") if isinstance(b.get("trial"), dict) else {}
            end = _trial_end(b)                                # a trial brand made by hand: the day after its plan_until
            if end is None or now < end or tr.get("converted_at"):
                continue
            ap.set_plan(d, b["id"], ended, until=None, by="trial", via="trial", note="the free trial ended without a card",
                        effective=iso(end))
            tr["ended_at"] = iso(end)
            b["trial"] = tr
            name = b.get("name") or b["id"]
            u = next((x for x in users(d) if x.get("id") == tr.get("user")), None)
            ap.add_rec(d, "P2", f"{name}: free trial ended without a card",
                       f"The 7-day trial of {name}" + (f" ({mask(u.get('email'))})" if u else "") + f" ended on {iso(end)[:10]}. "
                       "Publishing and ads are paused and the client got the “add a card” e-mail. Nothing was deleted: the data "
                       "is kept 90 days (otto_retention). A subscription (Billing page) or a plan set in the console resumes it.",
                       "A trial that did not convert", "Follow up if it was a good fit", brand=b["id"], source="trials",
                       audience="owner", action="trial")
            done.append(b["id"])
        for u in users(d):
            end = _dt(u.get("trial_ends_at"))
            if u.get("status") == "trial" and end and now >= end:
                u["status"] = "expired"
    for bid in done:
        out(f"{bid}: trial ended — plan {ended}, publishing and ads paused")
    return done


def send_reminders(now=None, out=print, dry=False):
    import otto_email as em
    now = now or utcnow()
    sent, failed = [], []
    for u in users(ap.load()):
        key = due_reminder(u, now)
        if not key:
            continue
        if dry:
            out(f"{mask(u.get('email'))}: would send {key}")
            continue
        if em.suppressed(u["email"]):
            out(f"{mask(u['email'])}: {key} skipped (the address bounced earlier)")
            continue
        with ap.transaction() as d:                              # claim: two runs never send the same reminder twice
            cur = next((x for x in users(d) if x.get("id") == u["id"]), None)
            if cur is None or due_reminder(cur, now) != key:
                continue
            cur.setdefault("trial_reminders", {})[key] = {"claimed": iso(now)}
            snap = json.loads(json.dumps(cur))
            subject, body, text = render(key, snap, d, now)
            bid = _tz_for(d, snap)[2]
        try:
            res = em.deliver(snap["email"], subject, body, text, "trial", bid)
        except Exception as e:                                   # noqa: BLE001 — retried next hour
            with ap.transaction() as d:
                cur = next((x for x in users(d) if x.get("id") == u["id"]), None)
                if cur is not None:
                    (cur.get("trial_reminders") or {}).pop(key, None)
            failed.append(u["id"])
            out(f"{mask(u['email'])}: {key} FAILED ({type(e).__name__}: {str(e)[:120]}) — retried next hour")
            continue
        with ap.transaction() as d:
            cur = next((x for x in users(d) if x.get("id") == u["id"]), None)
            if cur is not None:
                cur.setdefault("trial_reminders", {})[key] = {"sent": iso(now), "via": res.get("transport")}
        sent.append((u["id"], key))
        out(f"{mask(u['email'])}: {key} sent via {res.get('transport')}")
    return sent, failed


def prune_users(now=None, out=print):
    """Users with no brand, no trial running and no sign-in for USER_IDLE_DAYS days are removed (the ledger keeps hashes)."""
    now = now or utcnow()
    gone = []

    def idle(d, u, live):
        last = _dt(u.get("last_login_at")) or _dt(u.get("created_at"))
        owns = [x for x in u.get("brands") or [] if x in live] or ap.member_brands(d, u.get("email"))
        return not owns and u.get("status") != "trial" and last and now - last > timedelta(days=USER_IDLE_DAYS)

    snap = ap.load()
    live0 = {b.get("id") for b in snap.get("brands") or [] if isinstance(b, dict)}
    old_ledger = any(isinstance(x, dict) and (_dt(x.get("at")) or now) <= now - timedelta(days=LEDGER_DAYS)
                     for x in snap.get("trial_ledger") or [])
    if not old_ledger and not any(idle(snap, u, live0) for u in users(snap)):
        return gone
    with ap.transaction() as d:
        keep = []
        live = {b.get("id") for b in d.get("brands") or [] if isinstance(b, dict)}
        for u in d.get("users") or []:
            if not isinstance(u, dict):
                continue
            if u.get("id") and idle(d, u, live):
                gone.append(u["id"])
                continue
            keep.append(u)
        if gone:
            d["users"] = keep
        led = d.get("trial_ledger") or []
        fresh = [x for x in led if isinstance(x, dict) and (_dt(x.get("at")) or now) > now - timedelta(days=LEDGER_DAYS)]
        if len(fresh) != len(led):
            d["trial_ledger"] = fresh
    if gone:
        try:
            import otto_auth
            otto_auth.delete_user_sessions(gone)
        except Exception:                                        # noqa: BLE001
            pass
        out(f"removed {len(gone)} idle account(s) without a brand")
    return gone


def _months(start, end):
    """Every YYYY-MM from start's month to end's month (both dates)."""
    y, m, out = start.year, start.month, []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def kickoff(bid, now=None, out=print, spawn=True):
    """A trial is worth nothing if its seven days are empty: the monthly plan only runs on the 25th for the next month.
    Plan every month the trial overlaps (future slots only — otto_plan skips past ones) right away, and flag the brand
    for the copywriter (kickoff.copy_needed). With an Anthropic key the copywriter (otto_copy) starts in the background
    right away (spawn=True: the onboarding request never waits) and writes the first 7 days with their cards into the
    client's approvals; the hourly job (spawn=False here) catches up inline (copy_catchup). Without a key the owner card
    stays the human fallback (skills/otto-autopilot 0b). The planning itself is local and cheap (no network). Idempotent: a
    done kickoff is never redone. → months planned."""
    import otto_plan
    now = now or utcnow()
    d = ap.load()
    b = ap.brand(d, bid)
    if not b or (b.get("kickoff") or {}).get("done"):
        return []
    tz = ap.brand_tz(b)
    end = _dt((b.get("trial") or {}).get("ends_at")) or (now + timedelta(days=trial_days()))
    months, planned = _months(now.astimezone(tz).date(), end.astimezone(tz).date()), []
    for ym in months:
        if any(p.get("brand") == bid and p.get("plan") == ym for p in d.get("posts") or []):
            continue                                       # already planned (the 25th ran, or a hand build)
        try:
            otto_plan.build(bid, ym)
            planned.append(ym)
        except SystemExit as e:                            # otto_plan refuses (exists / plan has no organic): say why, go on
            out(f"{bid} {ym}: {e}")
    with ap.transaction() as d2:
        b2 = ap.brand(d2, bid)
        if b2 is None:
            return planned
        b2["kickoff"] = {"done": True, "at": iso(now), "months": months, "planned": planned, "copy_needed": True}
        ap.add_rec_once(d2, "P1", f"New trial: write the first week for {b2.get('name') or bid}",
                        f"{b2.get('name') or bid} started a {trial_days()}-day free trial. The posts are planned ({', '.join(months)}); "
                        "write the copy for the next 7 days first, then the visuals, so the trial shows real work on day one.",
                        "A trial with an empty app does not convert", "Write copy", brand=bid, source="otto_trial",
                        audience="owner")
    out(f"{bid}: trial kickoff planned {', '.join(planned) or 'nothing new'} (months {', '.join(months)})")
    if spawn:
        try:
            import otto_copy
            if otto_copy.spawn_week(bid):
                out(f"{bid}: the copywriter is writing the first week in the background (copy.log)")
            else:
                out(f"{bid}: no Anthropic key — the first week waits for a person (owner card)")
        except Exception as e:                             # noqa: BLE001 — the hourly job catches up
            out(f"{bid}: copywriter not started ({type(e).__name__}: {e}) — the trials job catches up")
    return planned


COPY_CATCHUP = timedelta(minutes=15)       # a trial's first week still unwritten this long after its kickoff → the job writes it
COPY_RETRY = timedelta(minutes=50)         # not again while a run (the spawned one, or the last catch-up) may still be busy
COPY_MAX_PER_RUN = 3


def copy_catchup(now=None, out=print):
    """The hourly safety net for the trial kickoff's background copywriter (a crash, a restart of the API, the API down):
    every trial brand still kickoff.copy_needed 15 minutes after its kickoff gets its first week written inline (at most
    three brands an hour; not again within 50 minutes of the last try). Nothing without an Anthropic key. → brand ids run."""
    now = now or utcnow()
    try:
        import otto_copy
    except Exception as e:                                 # noqa: BLE001
        out(f"copy catch-up unavailable: {type(e).__name__}: {e}")
        return []
    try:
        otto_copy.render_pending(out=out)                  # cards the kickoff's background run (no Chrome in the API) left
    except Exception as e:                                 # noqa: BLE001
        out(f"pending cards not rendered: {type(e).__name__}: {e}")
    if not otto_copy.ready():
        return []
    due = []
    d = ap.load()
    for b in d.get("brands") or []:
        k = (b.get("kickoff") or {}) if isinstance(b, dict) else {}
        if not k.get("copy_needed") or not b.get("id") or ap.plan_ended(d, b["id"]):
            continue
        at, tried = _dt(k.get("at")), _dt(k.get("copy_try_at"))
        if (at and now - at < COPY_CATCHUP) or (tried and now - tried < COPY_RETRY):
            continue
        due.append(b["id"])
    done = []
    for bid in due[:COPY_MAX_PER_RUN]:
        try:
            otto_copy.write_week(bid, out=out, job="trial catch-up")
            done.append(bid)
        except Exception as e:                             # noqa: BLE001 — one brand never stops the job
            out(f"{bid}: copy catch-up failed: {type(e).__name__}: {e}")
    return done


def copy_done(bid):
    """The first week has copy (otto_copy.finish_trial calls this when every post of it is written or held for review; a person
    can run `otto_trial.py copy-done <slug>`): clears kickoff.copy_needed."""
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        assert b, f"unknown brand {bid}"
        (b.setdefault("kickoff", {}))["copy_needed"] = False


def run(now=None, out=print, dry=False):
    """The hourly job. → exit code (1 when a reminder could not be sent: it is retried next hour)."""
    now = now or utcnow()
    if ap.plans_config().get("error"):
        out(f"plans.json is unreadable ({ap.plans_config()['error'][:120]}) — no trial is ended today")
        return 1
    if dry:
        d = ap.load()
        tp = ap.trial_plan_id()
        for b in d.get("brands") or []:
            end = _dt((b.get("trial") or {}).get("ends_at")) if isinstance(b, dict) else None
            if b.get("plan") == tp and end and now >= end:
                out(f"{b['id']}: would end its trial")
        send_reminders(now, out, dry=True)
        return 0
    for b in list(ap.load().get("brands") or []):          # catch-up: a kickoff the onboarding request could not finish
        if isinstance(b, dict) and b.get("trial") and not (b.get("trial") or {}).get("denied") \
                and not (b.get("kickoff") or {}).get("done") and b.get("plan") == ap.trial_plan_id():
            try:
                kickoff(b["id"], now, out, spawn=False)    # a systemd oneshot kills what it spawns: copy_catchup writes inline
            except Exception as e:                         # noqa: BLE001 — one brand never stops the job
                out(f"{b['id']}: kickoff failed: {type(e).__name__}: {e}")
    expire(now, out)
    _, failed = send_reminders(now, out)
    prune_users(now, out)
    copy_catchup(None, out)                                # last: it calls the Claude API (minutes, not seconds)
    return 1 if failed else 0


def status_rows(d=None, now=None):
    d = d if d is not None else ap.load()
    now = now or utcnow()
    rows = []
    for u in users(d):
        if not u.get("trial_started_at") and u.get("status") == "none":
            continue
        tr = trial_state(u, now)
        rows.append({"user": u["id"], "email": mask(u.get("email")), "status": u.get("status"), "state": tr["state"],
                     "started_at": u.get("trial_started_at"), "ends_at": u.get("trial_ends_at"), "days_left": tr.get("days_left"),
                     "brands": list(u.get("brands") or []), "reminders": sorted((u.get("trial_reminders") or {}).keys()),
                     "paid_at": u.get("paid_at")})
    return rows


def main(a):
    cmd = a[0] if a else ""
    now = None
    if "--now" in a and a.index("--now") + 1 < len(a):
        now = _dt(a[a.index("--now") + 1])
    if cmd == "run":
        return run(now, dry="--dry" in a)
    if cmd == "status":
        rows = status_rows(now=now)
        if "--json" in a:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print(f"{r['email']:28} {r['state']:9} ends {str(r['ends_at'])[:16]:16} left {r['days_left'] or '—':>2}  "
                      f"{','.join(r['brands']) or '—':20} reminders {','.join(r['reminders']) or '—'}")
            print(f"-- {len(rows)} trial account(s)")
        return 0
    if cmd == "kickoff" and len(a) > 1:
        kickoff(a[1], now)
        return 0
    if cmd == "copy-done" and len(a) > 1:
        copy_done(a[1])
        print(f"{a[1]}: first-week copy marked done")
        return 0
    if cmd == "offers" and len(a) > 1:
        print(json.dumps(checkout_offers(a[1]), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
