#!/usr/bin/env python3
"""Otto e-mail approvals — the Telegram approval loop, by e-mail (launch markets NL / IE, where Telegram is a minority app).

  otto_email.py send-cards [--brand B] [--ids hg-001,hg-002] [--hours 72] [--resend] [--dry]
  otto_email.py send-recs  [--brand B] [--dry]
  otto_email.py preview    --brand B [--kind digest|recs|plan] [--out file.html] [--text]   # render only: nothing is claimed or sent
  otto_email.py channel    <brand> email|telegram|app|email,telegram                      # brands[].approvals, by hand
  otto_email.py bounces                                                                    # pull bounces from Postmark / Resend now
  otto_email.py unsuppress <address>                                                       # send to a bounced address again
  otto_email.py status [--json]                                                            # transport, outbox, per-brand health

send-cards  One approval digest per brand, same selection rules as otto_telegram send-cards: every post in pending_approval whose
            slot is within --hours (72) and has not passed, not e-mailed yet (email_sent_at), compliance-checked first (a violating
            post is not sent: compliance_block + a "Compliance hold" recommendation, as in Telegram). Every selected post is
            claimed (email_claim) in data.json before anything is sent, so two runs at the same time never send it twice; a failed
            send releases the claim. The digest goes to each approver separately (every button carries a token for that person):
            the post's image (hosted URL, never an attachment), platform, slot in brand-local time, hook, caption, and three
            one-tap buttons — Approve · Skip (signed links) · Change (opens the app on that post) — plus "Review all in the app".
send-recs   Per brand: the monthly paid-plan card ("Approve the October paid plan", otto_ads) as its own e-mail, and every other
            client-visible P0 / P1 recommendation in one e-mail, each with Approve · Not now (same tokens). Claimed the same way.
Recipients  brands[].approvers when the brand has that list, else brands[].members; only real addresses ("@domain" entries let
            a whole company sign in to the app, but there is nobody to send to). An address with a hard bounce or a complaint is
            skipped until `unsuppress`.
Channel     brands[].approvals = "email" | "telegram" | "app" | ["email", "telegram"]. Missing = "telegram" (brands from before
            e-mail approvals are unchanged); onboarding writes "email"; the client changes it in the app's Settings
            (POST /otto-api/action {"kind":"brand","id":…,"approvals":…}). "app" = nothing is pushed, everything waits in Review.

One-tap links (/otto-email/act?t=<token>, public, wired in otto_api): token = base64url(payload) "." base64url(HMAC-SHA256)
over {brand, kind post|rec, item id, action, recipient (a keyed hash, never the address), expiry (72 h), nonce}. GET only shows
a confirmation page (mail scanners prefetch links — nothing ever acts on GET); its one button POSTs the token + a form nonce
(HMAC, 1 h) back. The POST checks signature, expiry, the nonce against the used-nonce store (single use), that the recipient is
still an approver of that brand and the item belongs to it, then applies the decision through the same path as the dashboard and
Telegram: ap.decide(via="email") (status transition + taste log) for posts — only while the post is draft / pending_approval, as
in Telegram; for a recommendation the REC_TRANSITIONS table, approved_via "email", and on approval the same code Telegram runs
(the paid plan → otto_ads.approve(via="email"), otto_ads pause cards → otto_ads.rec_action). Pages carry a strict CSP (no script,
hashed style, images from the media host only), no-store, noindex, frame-ancestors 'none'.

Transport ($OTTO_SECRETS/email.json, never logged):
  {"link_secret": "<≥ 32 chars, e.g. secrets.token_hex(32)>", "previous_link_secrets": [],   # old links keep working after rotation
   "from": "Otto <approvals@otto.example>", "reply_to": optional,
   "host": "smtp.example.com", "port": 587, "user": "…", "pass": "…",       # SMTP: STARTTLS required (or "tls": "ssl" on 465)
   "provider": "postmark" | "resend", "api_key": "…",                       # HTTP API instead of SMTP (open / link tracking off)
   "app_url": "https://app.otto.example/", "action_base": "https://otto.example"}   # optional; default from OTTO_DOMAIN
No transport configured → every e-mail is written as an .eml file to $OTTO_OUTBOX (default outbox/ next to data.json, mode 700,
files 600 — they hold working links), so everything is testable and the owner console shows the count. No link_secret → a
random one is generated once into .email-link-secret next to data.json (600).
State: .email-state.json next to data.json ($OTTO_EMAIL_STATE; flock + atomic replace): used nonces (until expiry), per-brand
last digest / recommendations / error, bounces (masked address + a hash), recent provider message ids (Resend bounce checks).
Logs print masked addresses only (a•••@example.com). Stdlib only; every data.json write goes through ap.transaction().
"""
import base64, contextlib, fcntl, hashlib, hmac, html, json, os, re, secrets, smtplib, ssl, sys, threading, time
import urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import format_datetime, formataddr, parseaddr
from pathlib import Path

import ap
import otto_paths as paths

HERE = Path(__file__).parent
HOURS = 72
TOKEN_TTL = timedelta(hours=72)
CLAIM_TTL = timedelta(minutes=10)
FORM_TTL = 3600                                  # seconds a confirmation page's button stays valid
EDITABLE = ("draft", "pending_approval")         # same as otto_telegram: only these take a decision from a message
POST_ACTIONS = ("approve", "skip")
REC_ACTIONS = {"approve": "approved", "dismiss": "dismissed"}
CHANNELS = ("email", "telegram")
CHOICES = ("email", "telegram", "app")
PLAT = {"fb": "Facebook", "ig": "Instagram", "li": "LinkedIn"}
FORMAT = {"reel": "Reel", "story": "Story", "carousel": "Carousel", "video": "Video"}
MAX_DIGEST = 12                                  # posts per e-mail; the rest wait in the app
MAX_TOKEN = 900
RATE_PER_MIN, RATE_GLOBAL_PER_MIN = 30, 1200
BOUNCE_SYNC_EVERY = timedelta(hours=1)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,800}\.[A-Za-z0-9_-]{43}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
PLAN_RE = re.compile(r"Approve the (\d{4}-\d{2}) paid plan")


class ConfigError(Exception):
    """email.json cannot be used as written (the message never contains a secret)."""


class SendError(Exception):
    def __init__(self, why, permanent=False):
        super().__init__(why)
        self.permanent = permanent


class TokenError(Exception):
    """code: invalid | expired"""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Denied(Exception):
    pass


class Skip(Exception):
    pass


# ============================================================================================
# paths + config (read at call time: tests and the server point OTTO_* elsewhere after import)
# ============================================================================================

def secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")


def state_path():
    return Path(os.environ.get("OTTO_EMAIL_STATE") or ap.DATA.parent / ".email-state.json")


def outbox_dir():
    return Path(os.environ.get("OTTO_OUTBOX") or ap.DATA.parent / "outbox")


def local_secret_path():
    return ap.DATA.parent / ".email-link-secret"


def config():
    f = secrets_dir() / "email.json"
    if not f.exists():
        return {}
    try:
        c = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        raise ConfigError(f"email.json cannot be read ({type(e).__name__})")
    if not isinstance(c, dict):
        raise ConfigError("email.json must be a JSON object")
    return c


def safe_config():
    try:
        return config()
    except ConfigError:
        return {}


def sender(cfg):
    v = str(cfg.get("from") or "").strip()
    if v:
        name, addr = parseaddr(v)
        if not ap.EMAIL.fullmatch(addr or ""):
            raise ConfigError("email.json \"from\" is not an e-mail address")
        return formataddr((name or "Otto", addr))
    dom = (os.environ.get("OTTO_DOMAIN") or "").strip() or "otto.invalid"
    return formataddr(("Otto", f"approvals@{dom}"))


def transport(cfg=None):
    """"smtp" | "postmark" | "resend" | "outbox" (nothing configured). Raises ConfigError on a half-written config."""
    cfg = config() if cfg is None else cfg
    prov = str(cfg.get("provider") or "").strip().lower()
    if prov in ("postmark", "resend"):
        if not str(cfg.get("api_key") or "").strip():
            raise ConfigError(f"provider {prov} needs \"api_key\" in email.json")
        if not str(cfg.get("from") or "").strip():
            raise ConfigError("email.json needs \"from\" (a sender your provider has verified)")
        sender(cfg)
        return prov
    if prov not in ("", "smtp"):
        raise ConfigError(f"unknown provider {prov!r}: smtp, postmark or resend")
    if str(cfg.get("host") or "").strip():
        if not str(cfg.get("from") or "").strip():
            raise ConfigError("email.json needs \"from\"")
        sender(cfg)
        tls = str(cfg.get("tls") or "").strip().lower()
        if tls and tls not in ("starttls", "ssl"):
            raise ConfigError("\"tls\" must be starttls or ssl — plain SMTP is refused")
        return "smtp"
    if prov == "smtp":
        raise ConfigError("provider smtp needs \"host\"")
    return "outbox"


def _origin(u):
    s = urllib.parse.urlsplit(str(u or ""))
    return f"{s.scheme}://{s.netloc}" if s.scheme and s.netloc else ""


def action_base(cfg=None):
    """Where the one-tap links point (public, no login): the apex on the new server, the old box's host otherwise."""
    cfg = safe_config() if cfg is None else cfg
    v = str(cfg.get("action_base") or os.environ.get("OTTO_EMAIL_BASE") or "").strip()
    if not v and (os.environ.get("OTTO_DOMAIN") or "").strip():
        v = "https://" + os.environ["OTTO_DOMAIN"].strip()
    return (v or _origin(os.environ.get("OTTO_PUBLIC_BASE") or paths.BASE)).rstrip("/")


def app_url(cfg=None):
    """The client app (behind the sign-in): app.<domain>/ on the new server, the old box's /otto/ otherwise."""
    cfg = safe_config() if cfg is None else cfg
    v = str(cfg.get("app_url") or os.environ.get("OTTO_APP_URL") or "").strip()
    if not v and (os.environ.get("OTTO_DOMAIN") or "").strip():
        v = f"https://app.{os.environ['OTTO_DOMAIN'].strip()}/"
    v = v or (os.environ.get("OTTO_PUBLIC_BASE") or paths.BASE)
    return v if v.endswith("/") else v + "/"


def act_url(token, cfg=None):
    return f"{action_base(cfg)}/otto-email/act?t={token}"


def app_link(frag, cfg=None):
    return app_url(cfg) + "#" + frag


# ============================================================================================
# channel + recipients
# ============================================================================================

def approval_channels(b):
    """The push channels this brand's approvals go out on: a sub-list of ("email", "telegram"); [] = the app only.
    A brand without brands[].approvals is a brand from before e-mail approvals: Telegram, unchanged. An unknown value
    pushes nothing (the console shows it)."""
    raw = (b or {}).get("approvals")
    if raw is None:
        raw = "telegram"
    out = []
    for x in raw if isinstance(raw, list) else [raw]:
        x = str(x or "").strip().lower()
        if x in CHANNELS and x not in out:
            out.append(x)
    return [c for c in CHANNELS if c in out]


def normalize_approvals(v):
    """A value for brands[].approvals from a client / the CLI: "email" | "telegram" | "app" | ["email", "telegram"]. ValueError
    otherwise. A list of one is stored as that string; "app" cannot be combined."""
    if isinstance(v, str) and "," in v:
        v = [x for x in v.split(",") if x.strip()]
    if isinstance(v, str):
        v = v.strip().lower()
        if v in CHOICES:
            return v
        raise ValueError("approvals must be email, telegram or app")
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v) and len(v) <= 3:
        got = []
        for x in v:
            x = x.strip().lower()
            if x not in CHANNELS:
                raise ValueError("approvals can combine email and telegram only")
            if x not in got:
                got.append(x)
        got = [c for c in CHANNELS if c in got]
        return got[0] if len(got) == 1 else got
    raise ValueError("approvals must be email, telegram or app")


def approvals_label(b):
    ch = approval_channels(b)
    if not ch:
        return "App only"
    return " and ".join({"email": "Email", "telegram": "Telegram"}[c] for c in ch)


def recipients(b):
    """Lower-case addresses approval e-mails go to: brands[].approvers if the brand has that list, else brands[].members.
    "@domain" entries are skipped (a domain can sign in, but cannot be mailed)."""
    b = b or {}
    src = b["approvers"] if isinstance(b.get("approvers"), list) else b.get("members") or []
    out = []
    for m in src if isinstance(src, list) else []:
        e = ap.norm_member(m)
        if e and not e.startswith("@") and e not in out:
            out.append(e)
    return out


def mask(e):
    e = str(e or "")
    if "@" not in e:
        return "•••"
    user, dom = e.split("@", 1)
    return (user[:1] or "•") + "•••@" + dom


def masks(xs, n=3):
    xs = list(xs)
    return ", ".join(mask(x) for x in xs[:n]) + (f" (+{len(xs) - n} more)" if len(xs) > n else "")


def addr_key(e):
    """Stable, secret-free lookup key for an address (bounces / suppression)."""
    return hashlib.sha256(str(e or "").strip().lower().encode()).hexdigest()[:24]


# ============================================================================================
# link secret, tokens, form nonces
# ============================================================================================

def _local_secret():
    f = local_secret_path()
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


def link_secrets(cfg=None):
    """[current, previous…] as bytes. email.json link_secret (+ previous_link_secrets), else the generated local one."""
    cfg = safe_config() if cfg is None else cfg
    cur = cfg.get("link_secret")
    out = []
    if cur is not None:
        if not isinstance(cur, str) or len(cur.strip()) < 32:
            raise ConfigError("link_secret must be at least 32 characters (python3 -c 'import secrets; print(secrets.token_hex(32))')")
        out.append(cur.strip())
    else:
        out.append(_local_secret())
    for old in cfg.get("previous_link_secrets") or []:
        if isinstance(old, str) and len(old.strip()) >= 32:
            out.append(old.strip())
    return [s.encode() for s in out]


def link_secret_source(cfg=None):
    cfg = safe_config() if cfg is None else cfg
    return "email.json" if cfg.get("link_secret") else "generated" if local_secret_path().exists() else "none yet"


def _derive(secret, label):
    return hmac.new(secret, b"otto-email/" + label.encode(), hashlib.sha256).digest()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def rcpt_hash(email_addr, secret):
    return hmac.new(_derive(secret, "recipient"), str(email_addr).strip().lower().encode(), hashlib.sha256).hexdigest()[:20]


def make_token(brand, kind, item, action, recipient, now=None, ttl=TOKEN_TTL, secret=None):
    secret = secret or link_secrets()[0]
    now = now or datetime.now(timezone.utc)
    payload = {"v": 1, "b": brand, "k": kind, "i": item, "a": action, "r": rcpt_hash(recipient, secret),
               "e": int((now + ttl).timestamp()), "n": secrets.token_urlsafe(12)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_derive(secret, "token"), b"v1." + body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def read_token(token, now=None, keys=None):
    """→ (payload, the secret that signed it). TokenError("invalid" | "expired")."""
    token = str(token or "").strip()
    if len(token) > MAX_TOKEN or not TOKEN_RE.match(token):
        raise TokenError("invalid")
    body, sig = token.split(".")
    keys = keys or link_secrets()
    secret = None
    for k in keys:
        want = _b64(hmac.new(_derive(k, "token"), b"v1." + body.encode(), hashlib.sha256).digest())
        if hmac.compare_digest(want.encode(), sig.encode()):
            secret = k
            break
    if secret is None:
        raise TokenError("invalid")
    try:
        p = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        raise TokenError("invalid")
    if not (isinstance(p, dict) and p.get("v") == 1 and p.get("k") in ("post", "rec") and isinstance(p.get("e"), int)
            and all(isinstance(p.get(x), str) and p.get(x) for x in ("b", "i", "a", "r", "n"))
            and ID_RE.match(p["b"]) and ID_RE.match(p["i"])
            and p["a"] in (POST_ACTIONS if p["k"] == "post" else tuple(REC_ACTIONS))):
        raise TokenError("invalid")
    t = (now or datetime.now(timezone.utc)).timestamp()
    if t > p["e"]:
        raise TokenError("expired")
    if p["e"] > t + TOKEN_TTL.total_seconds() + 86400:
        raise TokenError("invalid")                      # an expiry no link of ours ever had
    return p, secret


def form_nonce(payload, secret, now=None):
    ts = int((now or datetime.now(timezone.utc)).timestamp())
    mac = hmac.new(_derive(secret, "form"), f"{payload['n']}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{mac}"


def form_ok(value, payload, secret, now=None):
    m = re.fullmatch(r"(\d{9,11})\.([0-9a-f]{32})", str(value or ""))
    if not m:
        return False
    ts, t = int(m.group(1)), (now or datetime.now(timezone.utc)).timestamp()
    if not (-60 <= t - ts <= FORM_TTL):
        return False
    want = hmac.new(_derive(secret, "form"), f"{payload['n']}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(want, m.group(2))


# ============================================================================================
# state: used nonces, per-brand health, bounces (flock + atomic replace, mode 600)
# ============================================================================================

def read_state():
    try:
        st = json.loads(state_path().read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def state():
    """with state() as st: … — exclusive lock, fresh read, saved when the block ends without an exception."""
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_name(p.name + ".lock"), "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            st = read_state()
            yield st
            if not p.exists():
                os.close(os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o600))
            ap._atomic_write(p, json.dumps(st, ensure_ascii=False, indent=1) + "\n")
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _prune(st, now):
    used = st.get("used") if isinstance(st.get("used"), dict) else {}
    cut = now.timestamp() - 86400
    st["used"] = {k: v for k, v in used.items() if isinstance(v, dict) and (v.get("exp") or 0) > cut}
    sent = st.get("sent_ids") if isinstance(st.get("sent_ids"), list) else []
    st["sent_ids"] = sent[-200:]


def note_brand(bid, kind, info=None, error=None):
    """Remember the latest send (kind digest | recs | plan) or error for the owner console."""
    with state() as st:
        b = st.setdefault("brands", {}).setdefault(bid, {})
        if error:
            b["error"] = {"at": ap.now_iso(), "kind": kind, "why": str(error)[:300]}
        if info is not None:
            b[kind] = dict(info, at=ap.now_iso())
            b["sent"] = int(b.get("sent") or 0) + int(info.get("emails") or 0)
            if not error:
                b.pop("error", None)


def suppressed(e, st=None):
    st = read_state() if st is None else st
    rec = (st.get("bounces") or {}).get(addr_key(e))
    return bool(isinstance(rec, dict) and rec.get("type") in ("hard", "complaint") and not rec.get("cleared"))


def record_bounce(e, kind, why, source, brands=(), st=None):
    def put(s):
        bs = s.setdefault("bounces", {})
        k = addr_key(e)
        prev = bs.get(k) if isinstance(bs.get(k), dict) else {}
        bs[k] = {"to": mask(e), "type": kind, "why": str(why or "")[:160], "source": source, "at": ap.now_iso(),
                 "brands": sorted(set(prev.get("brands") or []) | set(brands)), "count": int(prev.get("count") or 0) + 1}
    if st is not None:
        put(st)
    else:
        with state() as s:
            put(s)


# ============================================================================================
# rendering: shared pieces
# ============================================================================================

FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
L = {"bg": "#F5F7FB", "card": "#FFFFFF", "ink": "#10182B", "ink2": "#5B6478", "ink3": "#7A8397", "line": "#E4E8F1",
     "accent": "#2447F0", "sec": "#EEF1F6", "green": "#0B7A4B", "amber": "#B45309", "red": "#B4231F"}
E = html.escape


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def fstyle(size, lh, weight=400, color=None, extra=""):
    return (f"font-family:{FONT};font-size:{size}px;line-height:{lh}px;font-weight:{weight};"
            + (f"color:{color};" if color else "") + extra)


def short(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut if len(cut) > n * 0.6 else s[:n]).rstrip(" ,.;:—-") + "…"


def para(s):
    """Plain text → escaped HTML with line breaks kept (captions have them)."""
    return "<br>".join(esc(x) for x in str(s or "").strip().splitlines())


def slot_label(p, b, with_day=True):
    dt = ap.slot_dt(p, b)
    if not dt:
        return str(p.get("slot") or "")
    loc = dt.astimezone(ap.brand_tz(b))
    return f"{loc:%a} {loc.day} {loc:%b} · {loc:%H:%M}" if with_day else f"{loc:%H:%M}"


def tz_note(b):
    name = getattr(ap.brand_tz(b), "key", "") or ""
    city = name.rsplit("/", 1)[-1].replace("_", " ") if "/" in name else name
    return f"{city} time" if city else ""


def month_label(ym):
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%B")
    except (TypeError, ValueError):
        return str(ym or "")


def image_url(p, verify=True, base=None):
    """The post's picture as a public https URL (never an attachment), or None. A reel shows its cover image."""
    ref = p.get("image") or next((x for x in p.get("images") or [] if x), None) or p.get("poster")
    if not ref or re.search(r"\.(mp4|mov|webm)$", str(ref), re.I):
        return None
    try:
        return paths.media_url(ref, base or (os.environ.get("OTTO_PUBLIC_BASE") or paths.BASE), verify=verify)
    except Exception:
        return None


def button(label, url, primary=False, full=True):
    bg, fg, cls = (L["accent"], "#FFFFFF", "o-pri") if primary else (L["sec"], L["ink"], "o-sec")
    width = 'width="100%" ' if full else ""
    return (f'<table role="presentation" {width}cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="{cls}" align="center" bgcolor="{bg}" style="background:{bg};border-radius:10px;mso-padding-alt:12px 18px;">'
            f'<a href="{esc(url)}" target="_blank" style="display:block;padding:12px 18px;border-radius:10px;text-decoration:none;'
            f'{fstyle(15, 20, 600, fg)}">{esc(label)}</a></td></tr></table>')


EMAIL_CSS = (":root{color-scheme:light dark;supported-color-schemes:light dark}"
             "body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}"
             "table,td{mso-table-lspace:0pt;mso-table-rspace:0pt}"
             "img{-ms-interpolation-mode:bicubic;border:0;outline:none;text-decoration:none}"
             "a{text-decoration:none}"
             "@media (max-width:620px){.o-shell{width:100%!important}.o-px{padding-left:16px!important;padding-right:16px!important}"
             ".o-thumb{width:84px!important}.o-thumb img{width:84px!important}.o-h1{font-size:24px!important;line-height:30px!important}"
             ".o-in{padding:14px!important}}"
             "@media (prefers-color-scheme:dark){.o-bg{background:#0C0D0F!important}"
             ".o-card{background:#16171A!important;border-color:#2A2C31!important}"
             ".o-ink{color:#F2F3F5!important}.o-ink2{color:#A3A8B3!important}.o-ink3{color:#8D95A5!important}"
             ".o-line{border-color:#2A2C31!important}.o-pri{background:#4461F5!important}.o-pri a{color:#FFFFFF!important}"
             ".o-sec{background:#24262B!important}.o-sec a{color:#F2F3F5!important}.o-link{color:#8EA2FF!important}"
             ".o-tag{background:#1B2240!important;color:#AFBDFF!important}.o-warn{background:rgba(245,165,36,.14)!important;color:#F5A524!important}}"
             "[data-ogsc] .o-ink{color:#F2F3F5!important}[data-ogsc] .o-ink2{color:#A3A8B3!important}"
             "[data-ogsc] .o-ink3{color:#8D95A5!important}[data-ogsc] .o-link{color:#8EA2FF!important}"
             "[data-ogsb] .o-bg{background:#0C0D0F!important}[data-ogsb] .o-card{background:#16171A!important}"
             "[data-ogsb] .o-sec{background:#24262B!important}[data-ogsb] .o-pri{background:#4461F5!important}")


def layout(subject, preheader, brand_name, title, lead, blocks, foot_html):
    """The shared e-mail shell: table-based (Gmail / Outlook / Apple Mail), system fonts only, light + dark, no pixels."""
    pad = "&#847;&zwnj;&nbsp;" * 40
    return f"""<!doctype html>
<html lang="en" dir="ltr" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no,date=no,address=no,email=no,url=no">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{esc(subject)}</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>{EMAIL_CSS}</style>
</head>
<body class="o-bg" style="margin:0;padding:0;width:100%;background:{L['bg']};">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{esc(preheader)}{pad}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="o-bg" style="background:{L['bg']};">
<tr><td align="center" style="padding:28px 12px 44px;">
<!--[if mso]><table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" class="o-shell" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;">
<tr><td class="o-px" style="padding:0 24px 22px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td class="o-ink" style="{fstyle(17, 22, 700, L['ink'], 'letter-spacing:-0.02em;')}">Otto</td>
<td class="o-ink3" align="right" dir="auto" style="{fstyle(13, 18, 500, L['ink3'])}">{esc(brand_name)}</td>
</tr></table></td></tr>
<tr><td class="o-px" style="padding:0 24px 8px;"><h1 class="o-ink o-h1" dir="auto" style="margin:0;{fstyle(28, 34, 700, L['ink'], 'letter-spacing:-0.025em;')}">{esc(title)}</h1></td></tr>
<tr><td class="o-px o-ink2" style="padding:0 24px 24px;{fstyle(15, 22, 400, L['ink2'])}">{lead}</td></tr>
{''.join(blocks)}
<tr><td class="o-px o-ink3" style="padding:26px 24px 0;{fstyle(12, 18, 400, L['ink3'])}">{foot_html}</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body>
</html>
"""


def card(inner):
    return (f'<tr><td class="o-px" style="padding:0 24px 14px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="o-card" '
            f'style="background:{L["card"]};border:1px solid {L["line"]};border-radius:16px;border-collapse:separate;">'
            f'<tr><td class="o-in" style="padding:16px;">{inner}</td></tr></table></td></tr>')


def buttons_row(btns):
    """btns = [(label, url, primary, width%)] in one row."""
    cells = []
    for i, (label, url, primary, w) in enumerate(btns):
        padl = "0" if i == 0 else "4px"
        padr = "0" if i == len(btns) - 1 else "4px"
        cells.append(f'<td width="{w}%" valign="top" style="padding:0 {padr} 0 {padl};">{button(label, url, primary)}</td>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">'
            f'<tr>{"".join(cells)}</tr></table>')


def footer(b, extra=""):
    return (f"You get this because you approve posts for {esc(b.get('name') or b['id'])} in Otto. "
            f'Choose how approvals reach you in <a class="o-link" href="{esc(app_link("settings"))}" style="color:{L["accent"]};">Settings</a>. '
            "Each button works once and expires after 72 hours; nothing publishes without your OK." + extra)


# ============================================================================================
# the approval digest
# ============================================================================================

def digest_item(b, p, recipient, cfg, now, secret, verify=True):
    tok = lambda a: make_token(b["id"], "post", p["id"], a, recipient, now=now, secret=secret)
    return {"post": p, "approve": act_url(tok("approve"), cfg), "skip": act_url(tok("skip"), cfg),
            "change": app_link("change=" + urllib.parse.quote(p["id"]), cfg), "open": app_link("post=" + urllib.parse.quote(p["id"]), cfg),
            "image": image_url(p, verify=verify), "slot": slot_label(p, b),
            "where": " · ".join(x for x in (PLAT.get(p.get("platform"), p.get("platform") or ""), FORMAT.get(p.get("format") or "")) if x)}


def _why(p):
    brief = p.get("brief") or ""
    return p.get("why") or ("" if "TBD" in brief else brief)


def render_digest(b, items, waiting=0):
    """→ (subject, html, text). items from digest_item(); waiting = other posts already sent and still waiting."""
    name = b.get("name") or b["id"]
    n = len(items)
    first = ap.slot_dt(items[0]["post"], b) if items else None
    day = f"{first.astimezone(ap.brand_tz(b)):%a} {first.astimezone(ap.brand_tz(b)).day} {first.astimezone(ap.brand_tz(b)):%b}" if first else ""
    subject = f"{n} post{'s' * (n != 1)} to approve for {name}" + (f" · from {day}" if day else "")
    title = f"{n} post{'s' * (n != 1)} need{'s' * (n == 1)} your OK"
    tzn = tz_note(b)
    lead = ("Tap <b>Approve</b> and it goes out at its time. <b>Skip</b> and Otto fills the slot. "
            "<b>Change</b> opens the post in the app." + (f" Times are {esc(tzn)}." if tzn else ""))
    blocks = []
    for it in items:
        p = it["post"]
        hook = (p.get("hook") or "").strip() or short((p.get("caption") or "").split("\n")[0], 90)
        cap = (p.get("caption") or "").strip()
        cap = "" if cap.strip() == hook.strip() else short(cap, 280)
        why = _why(p)
        img = (f'<td class="o-thumb" width="112" valign="top" style="width:112px;padding:0 14px 0 0;">'
               f'<a href="{esc(it["open"])}" target="_blank"><img src="{esc(it["image"])}" width="112" alt="{esc(short("Image: " + hook, 90))}" '
               f'style="display:block;width:112px;max-width:112px;height:auto;border-radius:10px;border:0;"></a></td>') if it["image"] else ""
        text = (f'<td valign="top">'
                f'<div class="o-ink3" style="{fstyle(12, 16, 600, L["ink3"], "letter-spacing:0.02em;text-transform:uppercase;")}">{esc(it["where"])}</div>'
                f'<div class="o-ink2" style="{fstyle(13, 18, 500, L["ink2"], "padding-top:2px;")}">{esc(it["slot"])}</div>'
                f'<div class="o-ink" dir="auto" style="{fstyle(16, 22, 600, L["ink"], "padding-top:8px;letter-spacing:-0.01em;")}">{esc(hook)}</div>'
                + (f'<div class="o-ink2" dir="auto" style="{fstyle(14, 20, 400, L["ink2"], "padding-top:6px;")}">{para(cap)}</div>' if cap else "")
                + (f'<div class="o-ink3" dir="auto" style="{fstyle(12, 17, 400, L["ink3"], "padding-top:8px;")}">Why this post: {esc(short(why, 160))}</div>' if why else "")
                + '</td>')
        inner = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{img}{text}</tr></table>'
                 + buttons_row([("Approve", it["approve"], True, 50), ("Skip", it["skip"], False, 25), ("Change", it["change"], False, 25)]))
        blocks.append(card(inner))
    more = f"{waiting} more post{'s' * (waiting != 1)} {'are' if waiting != 1 else 'is'} waiting in the app." if waiting else ""
    blocks.append(f'<tr><td class="o-px" align="center" style="padding:10px 24px 0;">'
                  f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;"><tr><td>'
                  f'{button("Review all in the app", app_link("review"), False, full=False)}</td></tr></table>'
                  + (f'<div class="o-ink3" style="{fstyle(13, 18, 400, L["ink3"], "padding-top:10px;")}">{esc(more)}</div>' if more else "")
                  + '</td></tr>')
    preheader = short(" · ".join((it["post"].get("hook") or "") for it in items), 110)
    body = layout(subject, preheader, name, title, lead, blocks, footer(b))
    lines = [f"{name} — {title}", "", "Approve and it goes out at its time. Skip and Otto fills the slot. Change opens the post in the app."
             + (f" Times are {tzn}." if tzn else ""), ""]
    for i, it in enumerate(items, 1):
        p = it["post"]
        lines += [f"{i}. {it['where']} · {it['slot']}", (p.get("hook") or "").strip()]
        cap = (p.get("caption") or "").strip()
        if cap and cap != (p.get("hook") or "").strip():
            lines.append(short(cap, 280))
        if it["image"]:
            lines.append(f"Image: {it['image']}")
        lines += [f"Approve: {it['approve']}", f"Skip:    {it['skip']}", f"Change:  {it['change']}", ""]
    if more:
        lines.append(more)
    lines += [f"Review all in the app: {app_link('review')}", "",
              f"You get this because you approve posts for {name} in Otto. Choose how approvals reach you: {app_link('settings')}",
              "Each link works once and expires after 72 hours; nothing publishes without your OK."]
    return subject, body, "\n".join(lines) + "\n"


# ============================================================================================
# recommendations + the monthly paid plan
# ============================================================================================

def is_plan_card(r):
    return r.get("source") == "otto_ads" and (r.get("action") == "approve_plan" or bool(PLAN_RE.match(r.get("title") or "")))


def plan_month(r):
    m = PLAN_RE.match(r.get("title") or "")
    return r.get("plan") or (m.group(1) if m else None)


def rec_links(b, r, recipient, cfg, now, secret):
    if r.get("onboard_step"):                       # a set-up step ("Connect Instagram"): done in the app, not approved here
        return [("Open Otto", app_link("settings", cfg), True, 100)]
    tok = lambda a: make_token(b["id"], "rec", r["id"], a, recipient, now=now, secret=secret)
    return [("Approve", act_url(tok("approve"), cfg), True, 60), ("Not now", act_url(tok("dismiss"), cfg), False, 40)]


PRIO = {"P0": ("Urgent", "o-warn", "#FFF4E2", "#B45309"), "P1": ("Recommended", "o-tag", "#EDF1FF", "#2447F0")}


def render_recs(b, rows):
    """rows = [(rec, links)] → (subject, html, text)."""
    name = b.get("name") or b["id"]
    n = len(rows)
    subject = (f"Otto recommends: {short(rows[0][0].get('title'), 70)}" if n == 1 else f"{n} recommendations for {name}")
    title = "Otto recommends" if n == 1 else f"{n} things to decide"
    lead = "Your agency's suggestions for this week. Approve one and Otto gets on with it; Not now puts it away."
    blocks, lines = [], [f"{name} — {title}", "", lead, ""]
    for r, links in rows:
        tag, cls, bg, fg = PRIO.get(r.get("priority"), PRIO["P1"])
        inner = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td class="{cls}" '
                 f'style="background:{bg};border-radius:6px;padding:3px 8px;{fstyle(11, 14, 600, fg, "letter-spacing:0.03em;text-transform:uppercase;")}">{tag}</td></tr></table>'
                 f'<div class="o-ink" dir="auto" style="{fstyle(17, 23, 600, L["ink"], "padding-top:10px;letter-spacing:-0.01em;")}">{esc(r.get("title"))}</div>'
                 + (f'<div class="o-ink2" dir="auto" style="{fstyle(14, 21, 400, L["ink2"], "padding-top:6px;")}">{esc(short(r.get("why"), 420))}</div>' if r.get("why") else "")
                 + (f'<div class="o-ink3" dir="auto" style="{fstyle(13, 18, 500, L["ink3"], "padding-top:8px;")}">↗ {esc(r.get("impact"))}</div>' if r.get("impact") else "")
                 + buttons_row(links))
        blocks.append(card(inner))
        lines += [f"[{tag}] {r.get('title')}"] + ([short(r.get("why"), 420)] if r.get("why") else []) + \
                 ([f"Impact: {r['impact']}"] if r.get("impact") else []) + [f"{lab}: {url}" for lab, url, _, _ in links] + [""]
    blocks.append(f'<tr><td class="o-px" align="center" style="padding:10px 24px 0;"><table role="presentation" cellpadding="0" cellspacing="0" '
                  f'border="0" style="margin:0 auto;"><tr><td>{button("Open Otto", app_link("today"), False, full=False)}</td></tr></table></td></tr>')
    lines += [f"Open Otto: {app_link('today')}", "", f"Choose how approvals reach you: {app_link('settings')}"]
    body = layout(subject, short(rows[0][0].get("why") or rows[0][0].get("title"), 110), name, title, lead, blocks, footer(b))
    return subject, body, "\n".join(lines) + "\n"


def render_plan(b, r, campaigns, links):
    """The monthly paid-plan approval card as an e-mail → (subject, html, text)."""
    name = b.get("name") or b["id"]
    ym = plan_month(r)
    mon = month_label(ym)
    subject = f"Approve the {mon} paid plan · {name}"
    title = f"Approve the {mon} paid plan"
    m = re.search(r"paid plan:\s*(.+)$", r.get("title") or "")
    lead = (esc(m.group(1)) + ". " if m else "") + "Nothing spends until you approve, and every campaign has a daily ceiling."
    rows = []
    for c in campaigns[:8]:
        cur = ap.currency_symbol(c.get("currency_code") or c.get("currency"))
        rows.append(f'<tr><td class="o-ink o-line" dir="auto" style="padding:10px 0;border-top:1px solid {L["line"]};{fstyle(14, 19, 500, L["ink"])}">'
                    f'{esc(short(c.get("name"), 60))}<div class="o-ink3" style="{fstyle(12, 17, 400, L["ink3"], "padding-top:2px;")}">'
                    f'{esc({"meta": "Meta", "google": "Google"}.get(c.get("network"), c.get("network") or ""))} · {esc(c.get("start") or "")} to {esc(c.get("end") or "")}'
                    + (" · on hold for a copy review" if c.get("compliance_hold") else "") + '</div></td>'
                    f'<td class="o-ink2 o-line" align="right" valign="top" style="padding:10px 0 10px 12px;border-top:1px solid {L["line"]};white-space:nowrap;{fstyle(14, 19, 500, L["ink2"])}">'
                    f'{esc(cur)}{ap.num(c.get("daily_budget")) or 0:,.0f}/day</td></tr>')
    more = len(campaigns) - 8
    inner = ((f'<div class="o-ink2" dir="auto" style="{fstyle(14, 21, 400, L["ink2"])}">{esc(short(r.get("why"), 700))}</div>' if r.get("why") else "")
             + (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">{"".join(rows)}</table>' if rows else "")
             + (f'<div class="o-ink3" style="{fstyle(12, 17, 400, L["ink3"], "padding-top:6px;")}">and {more} more in the app</div>' if more > 0 else "")
             + buttons_row(links))
    blocks = [card(inner), f'<tr><td class="o-px" align="center" style="padding:10px 24px 0;"><table role="presentation" cellpadding="0" '
                           f'cellspacing="0" border="0" style="margin:0 auto;"><tr><td>{button("See it in the app", app_link("settings"), False, full=False)}'
                           f'</td></tr></table></td></tr>']
    body = layout(subject, short(r.get("title"), 110), name, title, lead, blocks, footer(b))
    lines = [f"{name} — {title}", "", re.sub(r"<[^>]+>", "", lead), "", short(r.get("why"), 700), ""]
    for c in campaigns[:8]:
        lines.append(f"- {c.get('name')} · {c.get('network')} · {c.get('start')} to {c.get('end')} · "
                     f"{ap.currency_symbol(c.get('currency_code') or c.get('currency'))}{ap.num(c.get('daily_budget')) or 0:,.0f}/day")
    lines += [""] + [f"{lab}: {url}" for lab, url, _, _ in links] + ["", f"See it in the app: {app_link('settings')}"]
    return subject, body, "\n".join(lines) + "\n"


# ============================================================================================
# transport
# ============================================================================================

def build_message(to, subject, html_body, text_body, cfg, kind, bid):
    msg = EmailMessage(policy=SMTP_POLICY)
    frm = sender(cfg)
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    dom = parseaddr(frm)[1].split("@")[-1] or "otto.invalid"
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@{dom}>"
    if cfg.get("reply_to"):
        msg["Reply-To"] = str(cfg["reply_to"])
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
    msg["X-Otto-Kind"] = kind
    msg.set_content(text_body, subtype="plain", charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")
    return msg


def _extra_headers(msg):
    return {k: msg[k] for k in ("Auto-Submitted", "X-Auto-Response-Suppress", "X-Otto-Kind") if msg[k]}


def _http_json(url, body, headers, timeout=30):
    """POST body as JSON (GET when body is None) → (status, parsed JSON). Network errors → SendError (never the key)."""
    hdrs = dict({"Accept": "application/json", "User-Agent": "Otto/1.0"}, **headers)
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SendError(f"{type(e).__name__}: {str(e)[:120]}")


def _smtp(msg, cfg):
    host, port = str(cfg["host"]).strip(), int(cfg.get("port") or 587)
    tls = str(cfg.get("tls") or ("ssl" if port == 465 else "starttls")).strip().lower()
    ctx = ssl.create_default_context(cafile=cfg.get("ca_file") or None)
    timeout = float(cfg.get("timeout") or 30)
    try:
        s = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) if tls == "ssl" else smtplib.SMTP(host, port, timeout=timeout)
    except (OSError, smtplib.SMTPException) as e:
        raise SendError(f"cannot reach the SMTP server: {type(e).__name__}")
    try:
        s.ehlo()
        if tls == "starttls":
            if not s.has_extn("starttls"):
                raise SendError("the SMTP server does not offer STARTTLS — refusing to send in the clear")
            s.starttls(context=ctx)
            s.ehlo()
        if cfg.get("user"):
            s.login(str(cfg["user"]), str(cfg.get("pass") or cfg.get("password") or ""))
        refused = s.send_message(msg)
        if refused:
            raise SendError(f"recipient refused: {next(iter(refused.values()))}", permanent=True)
        return {"id": msg["Message-ID"]}
    except smtplib.SMTPRecipientsRefused as e:
        code, why = next(iter(e.recipients.values()), (550, b""))
        raise SendError(f"recipient refused ({code})", permanent=500 <= int(code) < 600)
    except smtplib.SMTPAuthenticationError:
        raise SendError("SMTP login refused (check user / pass)")
    except smtplib.SMTPResponseException as e:
        raise SendError(f"SMTP {e.smtp_code}", permanent=False)
    except (ssl.SSLError, ssl.CertificateError) as e:
        raise SendError(f"TLS failed: {type(e).__name__}")
    except (OSError, smtplib.SMTPException) as e:
        if isinstance(e, SendError):
            raise
        raise SendError(f"SMTP: {type(e).__name__}")
    finally:
        try:
            s.quit()
        except Exception:
            try:
                s.close()
            except Exception:
                pass


def _postmark(msg, to, html_body, text_body, cfg):
    body = {"From": msg["From"], "To": to, "Subject": msg["Subject"], "HtmlBody": html_body, "TextBody": text_body,
            "MessageStream": cfg.get("message_stream") or "outbound", "TrackOpens": False, "TrackLinks": "None",
            "Headers": [{"Name": k, "Value": v} for k, v in _extra_headers(msg).items()]}
    if msg["Reply-To"]:
        body["ReplyTo"] = msg["Reply-To"]
    code, out = _http_json((cfg.get("api_base") or "https://api.postmarkapp.com").rstrip("/") + "/email", body,
                           {"X-Postmark-Server-Token": str(cfg["api_key"])})
    if code == 200 and not out.get("ErrorCode"):
        return {"id": out.get("MessageID")}
    ec = out.get("ErrorCode")
    raise SendError(f"Postmark {code}/{ec}: {str(out.get('Message') or '')[:120]}", permanent=ec in (300, 406))


def _resend(msg, to, html_body, text_body, cfg):
    body = {"from": msg["From"], "to": [to], "subject": msg["Subject"], "html": html_body, "text": text_body,
            "headers": _extra_headers(msg)}
    if msg["Reply-To"]:
        body["reply_to"] = msg["Reply-To"]
    code, out = _http_json((cfg.get("api_base") or "https://api.resend.com").rstrip("/") + "/emails", body,
                           {"Authorization": f"Bearer {cfg['api_key']}"})
    if code in (200, 201) and out.get("id"):
        return {"id": out["id"]}
    raise SendError(f"Resend {code}: {str(out.get('message') or out.get('name') or '')[:120]}", permanent=code == 422)


def _outbox(msg, to, kind, bid):
    d = outbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{re.sub(r'[^a-z0-9-]', '', bid)[:40]}-{kind}-{addr_key(to)[:8]}-{secrets.token_hex(2)}.eml"
    f = d / name
    fd = os.open(str(f), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(msg.as_bytes())
    return {"id": msg["Message-ID"], "path": str(f)}


def deliver(to, subject, html_body, text_body, kind, bid, cfg=None):
    """Send one e-mail to one address → {"transport", "id", "path"?}. Raises SendError / ConfigError."""
    cfg = config() if cfg is None else cfg
    tr = transport(cfg)
    msg = build_message(to, subject, html_body, text_body, cfg, kind, bid)
    if tr == "smtp":
        out = _smtp(msg, cfg)
    elif tr == "postmark":
        out = _postmark(msg, to, html_body, text_body, cfg)
    elif tr == "resend":
        out = _resend(msg, to, html_body, text_body, cfg)
    else:
        out = _outbox(msg, to, kind, bid)
    out["transport"] = tr
    return out


def send_to_all(b, rcpts, render, kind, cfg, dry=False):
    """render(recipient) → (subject, html, text). One e-mail per recipient. → (sent addresses, errors)."""
    sent, errors = [], []
    st = read_state()
    for to in rcpts:
        if suppressed(to, st):
            print(f"  {mask(to)}: skipped (bounced earlier — otto_email.py unsuppress <address>)")
            continue
        subject, body, text = render(to)
        if dry:
            print(f"  WOULD SEND {kind} → {mask(to)} · “{subject}”")
            continue
        try:
            out = deliver(to, subject, body, text, kind, b["id"], cfg)
        except SendError as e:
            if e.permanent:
                record_bounce(to, "hard", str(e), "send", [b["id"]])
                print(f"  {mask(to)}: bounced ({e})")
            else:
                errors.append(f"{mask(to)}: {e}")
                print(f"  {mask(to)}: FAILED ({e})")
            continue
        sent.append(to)
        if out.get("id") and out["transport"] == "resend":
            with state() as s:
                s.setdefault("sent_ids", []).append({"id": out["id"], "to": addr_key(to), "masked": mask(to), "brand": b["id"],
                                                     "at": ap.now_iso()})
        print(f"  SENT {kind} → {mask(to)} via {out['transport']}" + (f" ({Path(out['path']).name})" if out.get("path") else ""))
    return sent, errors


# ============================================================================================
# claims (data.json): select → claim → send → mark
# ============================================================================================

def _claim(ids, kind, field, resend=False):
    """Claim posts / recs in one transaction. → the ids this run owns (another run's fresh claim, a sent item, a changed
    status → not ours)."""
    mine = []
    now = datetime.now(timezone.utc)
    with ap.transaction() as d:
        for i in ids:
            q = ap.post(d, i) if kind == "post" else ap.rec(d, i)
            if q is None:
                continue
            claim = ap.parse_iso(q.get("email_claim"))
            busy = ((q.get("status") != ("pending_approval" if kind == "post" else "proposed"))
                    or (q.get(field) and not resend) or bool(claim and claim.tzinfo and now - claim < CLAIM_TTL))
            if not busy:
                q["email_claim"] = ap.now_iso()
                mine.append(i)
    return mine


def _finish(ids, kind, ok, digest=None):
    with ap.transaction() as d:
        for i in ids:
            q = ap.post(d, i) if kind == "post" else ap.rec(d, i)
            if q is None:
                continue
            q.pop("email_claim", None)
            if ok:
                q["email_sent_at"] = ap.now_iso()
                if digest:
                    q["email_digest"] = digest
                q.pop("compliance_block", None)


def email_brands(d, bid=None):
    out = []
    for b in d.get("brands", []):
        if not isinstance(b, dict) or not b.get("id") or (bid and b["id"] != bid):
            continue
        if "email" not in approval_channels(b):
            if bid:
                print(f"{b['id']}: approvals are {approvals_label(b).lower()} — no e-mail (brands[].approvals)")
            continue
        if ap.plan_ended(d, b["id"]):
            print(f"{b['id']}: no active plan — no e-mail")
            continue
        out.append(b)
    if bid and not any(isinstance(b, dict) and b.get("id") == bid for b in d.get("brands", [])):
        print(f"unknown brand {bid}")
    return out


def maybe_sync_bounces(cfg):
    try:
        tr = transport(cfg)
    except ConfigError:
        return
    if tr not in ("postmark", "resend"):
        return
    last = ap.parse_iso((read_state().get("bounce_sync") or {}).get("at"))
    if last and datetime.now(timezone.utc) - last < BOUNCE_SYNC_EVERY:
        return
    try:
        sync_bounces(cfg)
    except Exception as e:                                    # bounces are health info: never stop a send over them
        print(f"bounce check failed: {type(e).__name__}: {str(e)[:120]}")


def send_cards(bid=None, hours=HOURS, resend=False, dry=False, ids=None, now=None, verify_media=True):
    """The daily approval digest. → {"emails", "posts", "blocked", "failed"} (for tests / the CLI exit code)."""
    import otto_compliance as comp
    now = now or datetime.now(timezone.utc)
    cfg = config()
    tr = transport(cfg)
    secret = link_secrets(cfg)[0]
    maybe_sync_bounces(cfg)
    d = ap.load()
    total = {"emails": 0, "posts": 0, "blocked": 0, "failed": 0}
    for b in email_brands(d, bid):
        rcpts = recipients(b)
        todo, blocked = [], 0
        for p in sorted(d.get("posts", []), key=lambda x: str(x.get("slot") or "")):
            if not isinstance(p, dict) or p.get("brand") != b["id"] or (ids and p.get("id") not in ids):
                continue
            if p.get("status") != "pending_approval" or (p.get("email_sent_at") and not resend):
                continue
            slot = ap.slot_dt(p, b)
            if slot is None or (not ids and slot > now + timedelta(hours=hours)):
                continue
            if not ids and slot <= now:
                print(f"PAST    {p['id']} {slot_label(p, b)} — slot already passed, not e-mailed (needs a new slot)")
                continue
            v = comp.check_post(p)
            if v:
                blocked += 1
                print(f"BLOCKED {p['id']} {slot_label(p, b)} — compliance: {comp.describe(v)}")
                if not dry:
                    with ap.transaction() as d2:
                        q = ap.post(d2, p["id"])
                        if q is not None:
                            q["compliance_block"] = {"rules": [x["rule"] for x in v][:6], "at": ap.now_iso()}
                            comp.file_block(d2, b["id"], f"{p['id']} “{p.get('hook', '')[:50]}”", v, "otto_email", post=p["id"])
                continue
            todo.append(p)
        total["blocked"] += blocked
        if not todo:
            print(f"{b['id']}: nothing new to approve" + (f" ({blocked} blocked by compliance)" if blocked else ""))
            continue
        if not rcpts:
            why = "nobody to send to: no member e-mail (\"@domain\" entries cannot be mailed) — add one in the console"
            print(f"{b['id']}: {why}")
            if not dry:
                note_brand(b["id"], "digest", error=why)
            total["failed"] += 1
            continue
        todo = todo[:MAX_DIGEST]
        if dry:
            print(f"{b['id']}: WOULD SEND {len(todo)} post(s) to {len(rcpts)} approver(s) via {tr}: "
                  + ", ".join(p["id"] for p in todo))
            continue
        mine = _claim([p["id"] for p in todo], "post", "email_sent_at", resend)
        if not mine:
            print(f"{b['id']}: already e-mailed or being sent by another run — skipped")
            continue
        fresh = ap.load()
        posts = [ap.post(fresh, i) for i in mine]
        waiting = sum(1 for p in fresh.get("posts", []) if isinstance(p, dict) and p.get("brand") == b["id"]
                      and p.get("status") == "pending_approval" and p.get("id") not in mine and p.get("email_sent_at"))
        digest = f"dg-{b['id'][:24]}-{now:%Y%m%d%H%M}-{secrets.token_hex(2)}"
        print(f"SEND    {b['id']} digest {digest}: {len(posts)} post(s) → {masks(rcpts)}")
        render = lambda to: render_digest(b, [digest_item(b, p, to, cfg, now, secret, verify_media) for p in posts], waiting)
        try:
            sent, errors = send_to_all(b, rcpts, render, "digest", cfg)
        except Exception:
            _finish(mine, "post", False)
            raise
        _finish(mine, "post", bool(sent), digest)
        info = {"posts": len(posts), "emails": len(sent), "to": len(sent), "transport": tr, "id": digest}
        note_brand(b["id"], "digest", info if sent else None, error="; ".join(errors) if errors else
                   (None if sent else "every recipient bounced or is suppressed"))
        total["emails"] += len(sent)
        total["posts"] += len(posts) if sent else 0
        total["failed"] += 1 if errors and not sent else 0
    print(f"-- {total['posts']} post(s) in {total['emails']} e-mail(s)" + (f" · {total['blocked']} blocked by compliance" if total["blocked"] else ""))
    return total


def _rec_visible(r, bid):
    import otto_api                                       # one rule for what a client may see / decide (lazy: otto_api imports us)
    return otto_api.rec_visible(r, {bid})


def send_recs(bid=None, dry=False, now=None):
    """P0 / P1 recommendations (one e-mail per brand) + the monthly paid-plan card (its own e-mail)."""
    now = now or datetime.now(timezone.utc)
    cfg = config()
    tr = transport(cfg)
    secret = link_secrets(cfg)[0]
    maybe_sync_bounces(cfg)
    d = ap.load()
    total = {"emails": 0, "recs": 0, "failed": 0}
    for b in email_brands(d, bid):
        recs = [r for r in d.get("recommendations", []) if isinstance(r, dict) and r.get("brand") == b["id"]
                and r.get("status") == "proposed" and r.get("priority") in ("P0", "P1") and not r.get("email_sent_at")
                and _rec_visible(r, b["id"])]
        if not recs:
            print(f"{b['id']}: no new recommendation")
            continue
        rcpts = recipients(b)
        if not rcpts:
            why = "nobody to send to: no member e-mail"
            print(f"{b['id']}: {why}")
            if not dry:
                note_brand(b["id"], "recs", error=why)
            total["failed"] += 1
            continue
        plans = [r for r in recs if is_plan_card(r)]
        others = [r for r in recs if not is_plan_card(r)]
        groups = [("plan", [r]) for r in plans] + ([("recs", others)] if others else [])
        for kind, group in groups:
            if dry:
                print(f"{b['id']}: WOULD SEND {kind} ({', '.join(r['id'] for r in group)}) to {len(rcpts)} approver(s) via {tr}")
                continue
            mine = _claim([r["id"] for r in group], "rec", "email_sent_at")
            if not mine:
                continue
            fresh = ap.load()
            rows = [ap.rec(fresh, i) for i in mine]
            print(f"SEND    {b['id']} {kind}: {', '.join(mine)} → {masks(rcpts)}")
            if kind == "plan":
                r = rows[0]
                camps = [c for c in fresh.get("campaigns", []) if isinstance(c, dict) and c.get("brand") == b["id"]
                         and c.get("plan") == plan_month(r)]
                render = lambda to, r=r, camps=camps: render_plan(b, r, camps, [
                    ("Approve plan", act_url(make_token(b["id"], "rec", r["id"], "approve", to, now=now, secret=secret), cfg), True, 60),
                    ("Not now", act_url(make_token(b["id"], "rec", r["id"], "dismiss", to, now=now, secret=secret), cfg), False, 40)])
            else:
                render = lambda to, rows=rows: render_recs(b, [(r, rec_links(b, r, to, cfg, now, secret)) for r in rows])
            try:
                sent, errors = send_to_all(b, rcpts, render, kind, cfg)
            except Exception:
                _finish(mine, "rec", False)
                raise
            _finish(mine, "rec", bool(sent))
            info = {"recs": len(mine), "emails": len(sent), "transport": tr}
            if kind == "plan":
                info["plan"] = plan_month(rows[0])
            note_brand(b["id"], kind, info if sent else None, error="; ".join(errors) if errors else
                       (None if sent else "every recipient bounced or is suppressed"))
            total["emails"] += len(sent)
            total["recs"] += len(mine) if sent else 0
            total["failed"] += 1 if errors and not sent else 0
    print(f"-- {total['recs']} recommendation(s) in {total['emails']} e-mail(s)")
    return total


# ============================================================================================
# bounces (provider reports) — health for the console, suppression for sending
# ============================================================================================

def sync_bounces(cfg=None):
    cfg = config() if cfg is None else cfg
    tr = transport(cfg)
    d = ap.load()
    by_addr = {}
    for b in d.get("brands", []):
        if isinstance(b, dict) and b.get("id"):
            for e in recipients(b):
                by_addr.setdefault(addr_key(e), (e, []))[1].append(b["id"])
    found = 0
    if tr == "postmark":
        since = ((read_state().get("bounce_sync") or {}).get("at") or "")[:10]
        q = urllib.parse.urlencode(dict({"count": 100, "offset": 0}, **({"fromdate": since} if since else {})))
        code, out = _http_json((cfg.get("api_base") or "https://api.postmarkapp.com").rstrip("/") + "/bounces?" + q, None,
                               {"X-Postmark-Server-Token": str(cfg["api_key"])})
        if code != 200:
            raise SendError(f"Postmark bounces: HTTP {code}")
        with state() as st:
            for x in out.get("Bounces") or []:
                hit = by_addr.get(addr_key(x.get("Email")))
                if not hit:
                    continue
                t = str(x.get("Type") or "")
                kind = "complaint" if "Spam" in t else "hard" if t in ("HardBounce", "BadEmailAddress", "ManuallyDeactivated") or x.get("Inactive") else "soft"
                record_bounce(hit[0], kind, x.get("Description") or t, "postmark", hit[1], st=st)
                found += 1
            st["bounce_sync"] = {"at": ap.now_iso(), "found": found, "transport": tr}
    elif tr == "resend":
        st0 = read_state()
        recent = [x for x in st0.get("sent_ids") or [] if isinstance(x, dict) and not x.get("final")][-30:]
        finals = {}
        for x in recent:
            code, out = _http_json((cfg.get("api_base") or "https://api.resend.com").rstrip("/") + "/emails/" + urllib.parse.quote(str(x["id"])),
                                   None, {"Authorization": f"Bearer {cfg['api_key']}"})
            if code == 200:
                finals[x["id"]] = str(out.get("last_event") or "")
        with state() as st:
            for x in st.get("sent_ids") or []:
                ev = finals.get(x.get("id"))
                if not ev:
                    continue
                if ev in ("bounced", "complained"):
                    hit = by_addr.get(x.get("to"))
                    if hit:
                        record_bounce(hit[0], "hard" if ev == "bounced" else "complaint", ev, "resend", hit[1], st=st)
                        found += 1
                if ev in ("delivered", "bounced", "complained"):
                    x["final"] = ev
            st["bounce_sync"] = {"at": ap.now_iso(), "found": found, "transport": tr}
    return found


# ============================================================================================
# the one-tap page: GET confirms, POST acts
# ============================================================================================

_rl_lock = threading.Lock()
_rl = {}
_rl_global = [0, 0]


def rate_ok(key, now=None):
    t = int((now or time.time()) // 60)
    with _rl_lock:
        if _rl_global[1] != t:
            _rl_global[:] = [0, t]
        _rl_global[0] += 1
        if _rl_global[0] > RATE_GLOBAL_PER_MIN:
            return False
        c = _rl.get(key)
        if not c or c[1] != t:
            c = [0, t]
            if len(_rl) > 5000:
                for k in [k for k, v in _rl.items() if v[1] != t]:
                    _rl.pop(k, None)
        c[0] += 1
        _rl[key] = c
        return c[0] <= RATE_PER_MIN


PAGE_CSS = ("*{box-sizing:border-box;margin:0;padding:0}"
            ":root{color-scheme:light dark;--bg:#F5F7FB;--card:#FFFFFF;--ink:#10182B;--ink2:#5B6478;--ink3:#7A8397;--line:#E4E8F1;"
            "--acc:#2447F0;--accp:#1631B8;--sec:#EEF1F6;--ok:#0B7A4B;--okt:#E5F6EE;--warn:#B45309;--warnt:#FFF4E2}"
            "@media (prefers-color-scheme:dark){:root{--bg:#0C0D0F;--card:#16171A;--ink:#F2F3F5;--ink2:#A3A8B3;--ink3:#8D95A5;"
            "--line:#2A2C31;--acc:#4461F5;--accp:#3551E0;--sec:#24262B;--ok:#34C77B;--okt:rgba(52,199,123,.14);--warn:#F5A524;"
            "--warnt:rgba(245,165,36,.14)}}"
            "html{background:var(--bg)}body{font:400 16px/1.45 -apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,system-ui,sans-serif;"
            "letter-spacing:-.01em;color:var(--ink);-webkit-font-smoothing:antialiased;min-height:100vh;display:flex;justify-content:center;"
            "padding:max(28px,env(safe-area-inset-top)) 18px 40px}"
            "main{width:100%;max-width:440px}"
            ".top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:26px}"
            ".top b{font-size:17px;font-weight:700;letter-spacing:-.02em}.top span{font-size:13px;color:var(--ink3);font-weight:500}"
            "h1{font-size:26px;line-height:32px;font-weight:700;letter-spacing:-.025em;margin-bottom:8px;text-wrap:balance}"
            ".lead{color:var(--ink2);font-size:15px;line-height:22px;margin-bottom:22px;text-wrap:pretty}"
            ".card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;display:flex;gap:14px;margin-bottom:18px}"
            ".card img{width:96px;height:auto;border-radius:10px;flex:none;align-self:flex-start}"
            ".meta{font-size:12px;line-height:16px;font-weight:600;letter-spacing:.02em;text-transform:uppercase;color:var(--ink3)}"
            ".when{font-size:13px;color:var(--ink2);font-weight:500;margin-top:2px}"
            ".hook{font-size:16px;line-height:22px;font-weight:600;margin-top:8px}"
            ".cap{font-size:14px;line-height:20px;color:var(--ink2);margin-top:6px;overflow-wrap:anywhere}"
            "button,.btn{display:block;width:100%;height:50px;border:0;border-radius:12px;font-family:inherit;font-size:17px;font-weight:600;line-height:50px;"
            "letter-spacing:-.01em;text-align:center;text-decoration:none;cursor:pointer;-webkit-tap-highlight-color:transparent}"
            "button{background:var(--acc);color:#fff}button:active{background:var(--accp)}"
            ".btn{background:var(--sec);color:var(--ink);margin-top:10px}"
            ".note{font-size:13px;line-height:18px;color:var(--ink3);margin-top:16px;text-align:center;text-wrap:pretty}"
            ".st{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin-bottom:18px;"
            "background:var(--okt);color:var(--ok)}.st.w{background:var(--warnt);color:var(--warn)}"
            ".st svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}")
PAGE_CSS_HASH = "'sha256-" + base64.b64encode(hashlib.sha256(PAGE_CSS.encode()).digest()).decode() + "'"
ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
ICON_INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v.01M12 11v5"/></svg>'


def page_csp(img_origin=None):
    return ("default-src 'none'; style-src " + PAGE_CSS_HASH + "; img-src " + (img_origin or "'none'")
            + "; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def page(title, body, img_origin=None):
    """A whole page → (html, csp). No script at all; the style is allowed by its hash; images only from the media host."""
    csp = page_csp(img_origin)
    meta_csp = csp.replace("; frame-ancestors 'none'", "")               # frame-ancestors only works as a header
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark"><meta name="referrer" content="same-origin">'
            f'<meta name="robots" content="noindex,nofollow">'
            f'<meta http-equiv="Content-Security-Policy" content="{esc(meta_csp)}">'
            f'<title>{esc(title)} · Otto</title><style>{PAGE_CSS}</style></head>'
            f'<body><main>{body}</main></body></html>\n'), csp


def _top(brand_name):
    return f'<div class="top"><b>Otto</b><span dir="auto">{esc(brand_name or "")}</span></div>'


def message_page(title, text, brand_name="", ok=False, link=True):
    body = (_top(brand_name) + f'<div class="st{"" if ok else " w"}">{ICON_OK if ok else ICON_INFO}</div>'
            f'<h1>{esc(title)}</h1><p class="lead">{text}</p>'
            + (f'<a class="btn" href="{esc(app_link("review"))}">Open Otto</a>' if link else ""))
    return page(title, body)


TOKEN_PAGES = {
    "invalid": ("This link doesn't work", "It may have been cut short when it was copied. Open the e-mail again and tap the "
                                          "button, or review the post in the app."),
    "expired": ("This link has expired", "Buttons in approval e-mails work for 72 hours. The post is still waiting for you in "
                                         "the app."),
    "used": ("This link was already used", "Each button works once. {result}"),
    "denied": ("This link can't be used any more", "It was sent to someone who no longer approves for this brand, or the item "
                                                   "has moved. Open the app to see what's waiting."),
    "form": ("Please tap the button again", "This page was open for a while, so Otto asks once more. Open the link from your "
                                            "e-mail again."),
    "origin": ("That didn't come from Otto's page", "For your safety, decisions are only taken from Otto's own confirmation "
                                                    "page. Open the link from your e-mail again."),
    "rate": ("Too many taps", "Please wait a minute and try again."),
    "config": ("Otto can't check this link right now", "Please try again in a few minutes, or review the post in the app."),
}


def token_page(code, result=""):
    title, text = TOKEN_PAGES[code]
    return message_page(title, esc(text.format(result=result)).replace("  ", " "))


def _context(d, p, secret):
    """(brand, recipient, item) for a verified payload, or Denied — the tenant check: the brand exists, the item is that
    brand's (a recommendation also client-visible), and the link's recipient is still one of its approvers."""
    b = ap.brand(d, p["b"])
    if not b:
        raise Denied("unknown brand")
    who = next((e for e in recipients(b) if hmac.compare_digest(rcpt_hash(e, secret), p["r"])), None)
    if not who:
        raise Denied("not an approver of this brand any more")
    if p["k"] == "post":
        item = ap.post(d, p["i"])
        if not item or item.get("brand") != b["id"]:
            raise Denied("post not of this brand")
    else:
        item = ap.rec(d, p["i"])
        if not item or item.get("brand") != b["id"] or not _rec_visible(item, b["id"]):
            raise Denied("recommendation not of this brand")
    return b, who, item


VERB = {("post", "approve"): ("Approve this post?", "Approve post"), ("post", "skip"): ("Skip this post?", "Skip post"),
        ("rec", "approve"): ("Approve this?", "Approve"), ("rec", "dismiss"): ("Put this away for now?", "Not now")}


def _post_card(b, item, img):
    hook = (item.get("hook") or "").strip() or short(item.get("caption"), 90)
    cap = (item.get("caption") or "").strip()
    cap = "" if cap == hook else short(cap, 240)
    where = " · ".join(x for x in (PLAT.get(item.get("platform"), item.get("platform") or ""), FORMAT.get(item.get("format") or "")) if x)
    return (f'<div class="card">' + (f'<img src="{esc(img)}" alt="">' if img else "")
            + f'<div><p class="meta">{esc(where)}</p><p class="when">{esc(slot_label(item, b))}</p>'
            f'<p class="hook" dir="auto">{esc(hook)}</p>' + (f'<p class="cap" dir="auto">{esc(cap)}</p>' if cap else "") + '</div></div>')


def _state_for(p, item):
    """Why this item cannot take the decision any more (a short sentence), or None."""
    if p["k"] == "post":
        st = item.get("status")
        if st not in EDITABLE or not ap.can_transition("post", st, ap.DECISIONS[p["a"]]):
            word = {"approved": "approved", "scheduled": "scheduled", "skipped": "skipped", "published": "published",
                    "publishing": "being published", "failed": "waiting for a new slot"}.get(st, st)
            return f"This post is already {word}."
        return None
    st = item.get("status")
    if not ap.can_transition("rec", st, REC_ACTIONS[p["a"]]) or st != "proposed":
        return f"This was already {'handled' if st == 'done' else st}."
    return None


def http_act(method, token, form=None, ip="", origin_ok=True, now=None):
    """The body of GET / POST /otto-email/act → (status, html, csp, log line or None). GET never changes anything."""
    now = now or datetime.now(timezone.utc)
    if not rate_ok("email:" + str(ip or "?")):
        h, c = token_page("rate")
        return 429, h, c, None
    try:
        p, secret = read_token(token, now)
    except TokenError as e:
        h, c = token_page(e.code)
        return (410 if e.code == "expired" else 400), h, c, None
    except ConfigError:
        h, c = token_page("config")
        return 503, h, c, None
    if method == "POST":
        if not origin_ok:
            h, c = token_page("origin")
            return 403, h, c, None
        if not form_ok(form, p, secret, now):
            h, c = token_page("form")
            return 400, h, c, None
        return _act(p, secret, now)
    used = (read_state().get("used") or {}).get(p["n"])
    if used:
        h, c = token_page("used", used.get("result") or "")
        return 409, h, c, None
    d = ap.load()
    try:
        b, who, item = _context(d, p, secret)
    except Denied:
        h, c = token_page("denied")
        return 403, h, c, None
    name = b.get("name") or b["id"]
    late = _state_for(p, item)
    if late:
        h, c = message_page("Nothing to do here", esc(late) + " You can change it in the app.", name)
        return 409, h, c, None
    title, label = VERB[(p["k"], p["a"])]
    img = None
    if p["k"] == "post":
        img = image_url(item, verify=False)
        what = _post_card(b, item, img)
        lead = ("It goes out at its time on " + esc(PLAT.get(item.get("platform"), "the page")) + "." if p["a"] == "approve"
                else "Otto fills the slot with something else.")
    else:
        what = (f'<div class="card"><div><p class="meta">{esc({"P0": "Urgent", "P1": "Recommended"}.get(item.get("priority"), "Recommended"))}</p>'
                f'<p class="hook" dir="auto">{esc(item.get("title"))}</p>'
                + (f'<p class="cap" dir="auto">{esc(short(item.get("why"), 360))}</p>' if item.get("why") else "") + '</div></div>')
        lead = ("Nothing spends until you approve; every campaign keeps its daily ceiling." if is_plan_card(item) and p["a"] == "approve"
                else "Otto gets on with it." if p["a"] == "approve" else "Otto puts it away. You can bring it back in the app.")
    exp = datetime.fromtimestamp(p["e"], timezone.utc).astimezone(ap.brand_tz(b))
    body = (_top(name) + f'<h1 dir="auto">{esc(title)}</h1><p class="lead">{lead}</p>' + what
            + f'<form method="post"><input type="hidden" name="t" value="{esc(token)}">'
            f'<input type="hidden" name="f" value="{esc(form_nonce(p, secret, now))}"><button type="submit">{esc(label)}</button></form>'
            + f'<a class="btn" href="{esc(app_link(("post=" + urllib.parse.quote(item["id"])) if p["k"] == "post" else "today"))}">Open in the app instead</a>'
            + f'<p class="note">This button works once. The link expires {exp:%a} {exp.day} {exp:%b}, {exp:%H:%M}.</p>')
    h, c = page(title, body, _origin(img) if img else None)
    return 200, h, c, None


def _act(p, secret, now):
    """POST: single use (the nonce is burned under the state lock before the decision), tenant, transitions, the decision."""
    run_action = None
    with state() as st:
        _prune(st, now)
        used = st.setdefault("used", {})
        if p["n"] in used:
            h, c = token_page("used", used[p["n"]].get("result") or "")
            return 409, h, c, None
        try:
            with ap.transaction() as d:
                b, who, item = _context(d, p, secret)
                late = _state_for(p, item)
                if late:
                    raise Skip(late)
                if p["k"] == "post":
                    ap.decide(d, p["i"], p["a"], via="email")             # status + taste log, POST_TRANSITIONS enforced
                    snap = dict(item)
                else:
                    item["status"] = REC_ACTIONS[p["a"]]
                    item["approved_via"] = "email"
                    item["decided_at"] = ap.now_iso()
                    snap = dict(item)
                name = b.get("name") or b["id"]
                bsnap = dict(b)
        except Denied:
            h, c = token_page("denied")
            return 403, h, c, None
        except Skip as e:
            h, c = message_page("Nothing to do here", esc(str(e)) + " You can change it in the app.", "")
            return 409, h, c, None
        if p["k"] == "post":
            result = ({"approve": f"Approved on {datetime.now(ap.brand_tz(bsnap)):%a %d %b, %H:%M}.",
                       "skip": f"Skipped on {datetime.now(ap.brand_tz(bsnap)):%a %d %b, %H:%M}."})[p["a"]]
        else:
            result = f"{'Approved' if p['a'] == 'approve' else 'Put away'} on {datetime.now(ap.brand_tz(bsnap)):%a %d %b, %H:%M}."
            run_action = p["k"] == "rec" and p["a"] == "approve"
        used[p["n"]] = {"at": ap.now_iso(), "exp": p["e"], "brand": p["b"], "item": p["i"], "action": p["a"], "result": result}
    line = f"email {p['k']} {p['i']} -> {p['a']} by {mask(who)} ({p['b']})"
    if p["k"] == "post":
        if p["a"] == "approve":
            slot = ap.slot_dt(snap, bsnap)
            text = (f"It goes out {slot_label(snap, bsnap)}." if slot and slot > now
                    else "Its time has passed, so Otto will offer a new slot.")
            h, c = message_page("Approved", esc(text), name, ok=True)
        else:
            h, c = message_page("Skipped", "Otto fills the slot with something else.", name, ok=True)
        return 200, h, c, line
    if not run_action:
        h, c = message_page("Put away for now", "You can bring it back in the app whenever you like.", name, ok=True)
        return 200, h, c, line
    out = None
    try:
        out = run_rec_action(snap)
    except Exception as e:
        print(f"rec action {snap['id']} failed: {type(e).__name__}: {e}")
        with ap.transaction() as d:
            q = ap.rec(d, snap["id"])
            if q is not None:
                q["action_error"] = str(e)[:300]
    if out:
        with ap.transaction() as d:
            q = ap.rec(d, snap["id"])
            if q is not None:
                q["action_result"] = out
                q["status"] = "done"
        line += f" · {out}"
    text = (f"{out[:1].upper() + out[1:]}. Each campaign starts on its date with its daily ceiling." if out and is_plan_card(snap)
            else f"Done: {out}." if out else "Otto gets on with it.")
    h, c = message_page("Approved", esc(text), name, ok=True)
    return 200, h, c, line


def run_rec_action(r):
    """What approving a recommendation does in code — the same as otto_telegram.run_rec_action, recorded as via e-mail."""
    if r.get("source") != "otto_ads":
        return None
    import otto_ads
    if is_plan_card(r):
        ym = plan_month(r)
        if not (ym and r.get("brand")):
            return None
        n = otto_ads.approve(r["brand"], ym, via="email")
        return f"{n} campaign(s) approved for {month_label(ym)}"
    return otto_ads.rec_action(r)


# ============================================================================================
# console health
# ============================================================================================

def health():
    """Owner-console view (no secret, no full address): transport, outbox, link secret source, per-brand last sends,
    errors and bounces."""
    try:
        cfg = config()
        tr, err = transport(cfg), None
    except ConfigError as e:
        cfg, tr, err = {}, "error", str(e)
    st = read_state()
    ob = outbox_dir()
    files = sorted(ob.glob("*.eml")) if ob.is_dir() else []
    bounces = [dict(v) for v in (st.get("bounces") or {}).values() if isinstance(v, dict)]
    return {"transport": tr, "config_error": err, "link_secret": link_secret_source(cfg),
            "outbox": {"files": len(files), "kb": round(sum(f.stat().st_size for f in files) / 1024, 1),
                       "latest": datetime.fromtimestamp(files[-1].stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if files else None,
                       "dir": str(ob)} if files or tr == "outbox" else None,
            "brands": {k: v for k, v in (st.get("brands") or {}).items() if isinstance(v, dict)},
            "bounces": sorted(bounces, key=lambda x: x.get("at") or "", reverse=True)[:50],
            "bounce_sync": st.get("bounce_sync")}


def brand_health(b, h):
    """The per-brand block the console's drill-down shows."""
    rc = recipients(b)
    bh = (h.get("brands") or {}).get(b.get("id")) or {}
    bounced = [x for x in h.get("bounces") or [] if b.get("id") in (x.get("brands") or []) and not x.get("cleared")]
    ch = approval_channels(b)
    return {"channels": ch, "label": approvals_label(b), "set": b.get("approvals") is not None,
            "changed": b.get("approvals_set"), "recipients": len(rc), "to": [mask(e) for e in rc[:6]],
            "source": "approvers" if isinstance(b.get("approvers"), list) else "members",
            "transport": h.get("transport"), "last_digest": bh.get("digest"), "last_recs": bh.get("recs"),
            "last_plan": bh.get("plan"), "error": bh.get("error"), "sent": int(bh.get("sent") or 0),
            "bounces": [{k: x.get(k) for k in ("to", "type", "at", "why", "source")} for x in bounced][:8],
            "outbox": h.get("outbox") if "email" in ch else None}


# ============================================================================================
# CLI
# ============================================================================================

def _opt(a, k, default=None):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else default


def preview(bid, kind="digest", out=None, text=False):
    d = ap.load()
    b = ap.brand(d, bid)
    if not b:
        raise SystemExit(f"unknown brand {bid}")
    cfg, now, to = safe_config(), datetime.now(timezone.utc), "preview@example.invalid"
    secret = link_secrets(cfg)[0]
    if kind == "digest":
        posts = sorted([p for p in d.get("posts", []) if p.get("brand") == bid and p.get("status") == "pending_approval"],
                       key=lambda x: str(x.get("slot") or ""))[:MAX_DIGEST]
        if not posts:
            raise SystemExit(f"{bid}: nothing pending to preview")
        s, h, t = render_digest(b, [digest_item(b, p, to, cfg, now, secret, verify=False) for p in posts], 0)
    else:
        recs = [r for r in d.get("recommendations", []) if r.get("brand") == bid and r.get("status") == "proposed"
                and (is_plan_card(r) if kind == "plan" else not is_plan_card(r))]
        if not recs:
            raise SystemExit(f"{bid}: no proposed {'paid-plan card' if kind == 'plan' else 'recommendation'} to preview")
        if kind == "plan":
            r = recs[0]
            camps = [c for c in d.get("campaigns", []) if c.get("brand") == bid and c.get("plan") == plan_month(r)]
            s, h, t = render_plan(b, r, camps, [("Approve plan", act_url(make_token(bid, "rec", r["id"], "approve", to, secret=secret), cfg), True, 60),
                                                 ("Not now", act_url(make_token(bid, "rec", r["id"], "dismiss", to, secret=secret), cfg), False, 40)])
        else:
            s, h, t = render_recs(b, [(r, rec_links(b, r, to, cfg, now, secret)) for r in recs[:6]])
    body = t if text else h
    if out:
        Path(out).write_text(body)
        print(f"{s} → {out}")
    else:
        print(body)


def set_channel(bid, value):
    v = normalize_approvals(value)
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            raise SystemExit(f"unknown brand {bid}")
        b["approvals"] = v
        b["approvals_set"] = {"at": ap.now_iso(), "via": "cli"}
        label = approvals_label(b)
    print(f"{bid}: approvals by {label.lower()}")


def main(a):
    cmd = a[0] if a else ""
    try:
        if cmd == "send-cards":
            ids = set(_opt(a, "--ids").split(",")) if _opt(a, "--ids") else None
            t = send_cards(bid=_opt(a, "--brand"), hours=int(_opt(a, "--hours", HOURS)), resend="--resend" in a, dry="--dry" in a, ids=ids)
            return 1 if t["failed"] else 0
        if cmd == "send-recs":
            t = send_recs(bid=_opt(a, "--brand"), dry="--dry" in a)
            return 1 if t["failed"] else 0
        if cmd == "preview" and _opt(a, "--brand"):
            preview(_opt(a, "--brand"), _opt(a, "--kind", "digest"), _opt(a, "--out"), "--text" in a)
            return 0
        if cmd == "channel" and len(a) > 2:
            set_channel(a[1], a[2])
            return 0
        if cmd == "bounces":
            print(f"{sync_bounces()} bounce(s) recorded")
            return 0
        if cmd == "unsuppress" and len(a) > 1:
            with state() as st:
                rec = (st.get("bounces") or {}).get(addr_key(a[1]))
                if rec:
                    rec["cleared"] = ap.now_iso()
            print(f"{mask(a[1])}: {'will be mailed again' if rec else 'was not suppressed'}")
            return 0
        if cmd == "status":
            h = health()
            if "--json" in a:
                print(json.dumps(h, ensure_ascii=False, indent=1))
                return 0
            print(f"transport {h['transport']}" + (f" ({h['config_error']})" if h["config_error"] else "")
                  + f" · link secret {h['link_secret']}" + (f" · outbox {h['outbox']['files']} file(s) in {h['outbox']['dir']}" if h["outbox"] else ""))
            d = ap.load()
            for b in d.get("brands", []):
                bh = brand_health(b, h)
                dg = bh["last_digest"] or {}
                print(f"  {b['id']:16} {bh['label']:20} {bh['recipients']} approver(s)  last digest {dg.get('at') or '—'}"
                      + (f"  ERROR {bh['error']['why']}" if bh["error"] else "") + (f"  {len(bh['bounces'])} bounced" if bh["bounces"] else ""))
            return 0
    except ConfigError as e:
        print(f"email.json: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
