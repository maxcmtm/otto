#!/usr/bin/env python3
"""Otto sign-in with Google: OpenID Connect, authorization-code flow with PKCE (S256), state and nonce. Stdlib only.

Routes (otto_api wires them; Caddy sends /auth/* on app.<domain> to the API):
  GET  /auth/google/start?next=/onboarding.html?site=x   302 to Google. A fresh state, nonce and PKCE verifier are kept
                                                          server-side for 10 minutes (PENDING, in memory: a restart only
                                                          means "click again"); a short-lived HttpOnly login cookie holding
                                                          the state binds the round trip to this browser (login CSRF).
  GET  /auth/google/callback?code=…&state=…               the state must match the login cookie and a pending login (single
                                                          use); the code is exchanged at Google's token endpoint over TLS,
                                                          server to server (client secret + code_verifier); the ID token that
                                                          comes back is verified — RS256 signature against Google's JWKS
                                                          (pure-Python PKCS#1 v1.5, keys cached per Cache-Control), iss, aud
                                                          (= our client id; azp when aud is a list), exp / iat (60 s skew),
                                                          nonce, email_verified true, sub — then the user is created or
                                                          updated (first login = sign-up: otto_trial starts the free trial),
                                                          a session is opened and the browser goes to `next` (303).
  POST /auth/logout                                       deletes the session, clears the cookie (Origin checked in otto_api)
  GET  /auth/me                                           who is signed in + trial + "add a card" offers (otto_trial)
Nothing from Google is stored but the verified e-mail, the name, the Google account id (sub) and, for Google Workspace
accounts, the hosted domain (hd). No access or refresh token is kept, no profile picture.

Config: $OTTO_SECRETS/google-oauth.json {"client_id": "…apps.googleusercontent.com", "client_secret": "…"} (Google's downloaded
client file {"web": {…}} works too). Redirect URI: OTTO_GOOGLE_REDIRECT_URI (local development, e.g.
http://localhost:8790/auth/google/callback), else "redirect_uri" in the file, else https://app.<OTTO_DOMAIN>/auth/google/callback.
Missing any of the three → every route answers 503 "Google sign-in isn't set up yet" and /auth/me says google: false (the UI
hides the button). The Google endpoints can be pointed elsewhere in the file (auth_url, token_url, jwks_url) only over https,
or http to 127.0.0.1 / localhost (tests).

Sessions: a random 256-bit id in the cookie (__Host-otto_sid: HttpOnly, Secure, SameSite=Lax, Path=/, no Domain — so the
browser sends it to app.<domain> only; on http://localhost it is otto_sid without Secure). The server keeps only its SHA-256
in sessions.json next to data.json ($OTTO_SESSIONS; own flock, atomic replace, mode 600): {user, created, seen, expires}.
Sliding expiry: SESSION_DAYS after the last use, written (and the cookie re-sent) at most once an hour. Logout deletes it; a
deleted user's sessions stop working; at most MAX_SESSIONS per user (the oldest go). Why not data.json: every job writes
data.json (a login would wait on their lock), it is shown whole to the owner and copied into exports, and a session id is
a credential — here the file holds only hashes and nothing else reads it.
Users live in data.json users[] (otto_trial: trial dates, status trial | active | expired | none, brands they created).
Rate limit: RATE_MAX sign-in starts / callbacks per client (an IPv6 /64 counts as one) per RATE_WINDOW seconds → 429.
Env: OTTO_SESSIONS, OTTO_SECRETS, OTTO_DOMAIN, OTTO_GOOGLE_REDIRECT_URI. Paths are read when used (tests point them elsewhere).
"""
import base64, fcntl, hashlib, hmac, json, os, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request
from collections import deque, namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ap

HERE = Path(__file__).parent
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"
SESSION_DAYS = 30
SLIDE_EVERY = 3600                 # seconds between two writes of one session's sliding expiry
MAX_SESSIONS = 20                  # per user
LOGIN_TTL = 600                    # seconds a started sign-in may take
MAX_PENDING = 10000
SKEW = 60                          # seconds of clock skew allowed on exp / iat
RATE_MAX, RATE_WINDOW = 20, 600
NOT_SET_UP = "Google sign-in isn't set up yet"
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# headers: [(name, value)]; body: bytes; log: actions.log line; event: (otto_track server event, ref) for Meta measurement
Reply = namedtuple("Reply", "code headers body ctype log event", defaults=(None,))


class AuthError(Exception):
    """The sign-in cannot be accepted. str(e) is for the error log; the page shows a fixed sentence."""


# ------------------------------------------------------------------------------------------------------------ config

def secrets_dir():
    return Path(os.environ.get("OTTO_SECRETS") or HERE.parent.parent / "otto-secrets")


def sessions_path():
    return Path(os.environ.get("OTTO_SESSIONS") or ap.DATA.parent / "sessions.json")


def _allowed_endpoint(u):
    s = urllib.parse.urlsplit(str(u or ""))
    return s.scheme == "https" and bool(s.netloc) or (s.scheme == "http" and s.hostname in ("127.0.0.1", "localhost"))


def config():
    """{client_id, client_secret, redirect_uri, secure, auth_url, token_url, jwks_url} or None when sign-in is not set up.
    Never logged, never returned to a client."""
    try:
        raw = json.loads((secrets_dir() / "google-oauth.json").read_text())
    except (OSError, ValueError):
        return None
    if isinstance(raw, dict) and isinstance(raw.get("web"), dict):
        raw = dict(raw["web"], **{k: v for k, v in raw.items() if k != "web"})
    if not isinstance(raw, dict):
        return None
    cid, sec = str(raw.get("client_id") or "").strip(), str(raw.get("client_secret") or "").strip()
    dom = (os.environ.get("OTTO_DOMAIN") or "").strip().strip("/")
    redirect = ((os.environ.get("OTTO_GOOGLE_REDIRECT_URI") or "").strip() or str(raw.get("redirect_uri") or "").strip()
                or (f"https://app.{dom}/auth/google/callback" if dom else ""))
    if not (cid and sec and redirect) or not _allowed_endpoint(redirect):
        return None
    out = {"client_id": cid, "client_secret": sec, "redirect_uri": redirect, "secure": redirect.startswith("https://")}
    for k, dflt in (("auth_url", AUTH_URL), ("token_url", TOKEN_URL), ("jwks_url", JWKS_URL)):
        v = str(raw.get(k) or "").strip()
        out[k] = v if v and _allowed_endpoint(v) else dflt
    return out


def configured():
    return config() is not None


# ------------------------------------------------------------------------------------------------------------ helpers

def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64url_decode(s):
    if not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", s):
        raise AuthError("not base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_next(v):
    """A same-origin path to land on after sign-in ("/", "/onboarding.html?site=acme.com"); anything else → "/"."""
    v = str(v or "").strip()
    if not v or len(v) > 500 or not v.startswith("/") or v.startswith("//") or "\\" in v or re.search(r"[\x00-\x20\x7f]", v):
        return "/"
    s = urllib.parse.urlsplit(v)
    if s.scheme or s.netloc:
        return "/"
    return v


def parse_cookies(header):
    out = {}
    for part in str(header or "").split(";"):
        k, sep, v = part.strip().partition("=")
        if sep and k and k not in out:
            out[k] = v.strip().strip('"')
    return out


def cookie_names(secure):
    return ("__Host-otto_sid", "__Host-otto_login") if secure else ("otto_sid", "otto_login")


def set_cookie(name, value, max_age, secure):
    """Host-only (no Domain), Path=/, HttpOnly, SameSite=Lax; Secure on https (the __Host- prefix requires it)."""
    return ("Set-Cookie", f"{name}={value}; Path=/; Max-Age={int(max_age)}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else ""))


def clear_cookies():
    """Set-Cookie headers that remove both cookie spellings (whatever the config says now)."""
    return [set_cookie(n, "", 0, n.startswith("__Host-")) for n in ("__Host-otto_sid", "otto_sid", "__Host-otto_login", "otto_login")]


def session_token_from(cookie_header):
    c = parse_cookies(cookie_header)
    for name in ("__Host-otto_sid", "otto_sid"):
        v = c.get(name)
        if v and TOKEN_RE.fullmatch(v):
            return v
    return None


def mask(e):
    e = str(e or "")
    if "@" not in e:
        return "•••"
    user, dom = e.split("@", 1)
    return (user[:1] or "•") + "•••@" + dom


# ------------------------------------------------------------------------------------------------------------ rate limit

_rl_lock = threading.Lock()
_rl = {}                           # client key → deque of timestamps


def rate_ok(key, now=None):
    now = now or time.time()
    with _rl_lock:
        q = _rl.setdefault(key, deque())
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_MAX:
            return False
        q.append(now)
        if len(_rl) > 20000:
            for k in [k for k, v in _rl.items() if not v or now - v[-1] > RATE_WINDOW][:10000]:
                _rl.pop(k, None)
        return True


# ------------------------------------------------------------------------------------------------------------ RS256 / JWKS

def rsa_verify(n, e, message, signature):
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017 §8.2.2): s^e mod n must be exactly 00 01 FF…FF 00 DigestInfo(SHA-256) H.
    Keys under 2048 bits are refused."""
    if not (isinstance(n, int) and isinstance(e, int)) or n.bit_length() < 2048 or e < 3 or e % 2 == 0 or e >= n:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    ps = k - len(t) - 3
    if ps < 8:
        return False
    return hmac.compare_digest(em, b"\x00\x01" + b"\xff" * ps + b"\x00" + t)


_jwks_lock = threading.Lock()
_jwks = {"url": None, "keys": {}, "exp": 0.0, "fetched": 0.0}


def _http(method, url, data=None, headers=None, timeout=10):
    """(status, headers, body bytes) — TLS verified by the default context; HTTP errors are answers, not exceptions."""
    req = urllib.request.Request(url, data=data, method=method, headers=dict({"User-Agent": "Otto/1.0", "Accept": "application/json"},
                                                                             **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(100_000)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AuthError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {type(e).__name__}")


def _max_age(headers):
    m = re.search(r"max-age=(\d+)", str({k.lower(): v for k, v in (headers or {}).items()}.get("cache-control") or ""))
    return min(86400, max(300, int(m.group(1)))) if m else 3600


def _fetch_jwks(url):
    code, hdrs, body = _http("GET", url)
    if code != 200:
        raise AuthError(f"JWKS answered HTTP {code}")
    try:
        doc = json.loads(body)
    except ValueError:
        raise AuthError("JWKS is not JSON")
    keys = {}
    for k in doc.get("keys") or [] if isinstance(doc, dict) else []:
        if not isinstance(k, dict) or k.get("kty") != "RSA" or k.get("use", "sig") != "sig" or k.get("alg", "RS256") != "RS256":
            continue
        try:
            n = int.from_bytes(b64url_decode(k["n"]), "big")
            e = int.from_bytes(b64url_decode(k["e"]), "big")
        except (KeyError, AuthError, ValueError, TypeError):
            continue
        if isinstance(k.get("kid"), str) and k["kid"]:
            keys[k["kid"]] = (n, e)
    if not keys:
        raise AuthError("JWKS has no RS256 key")
    return keys, _max_age(hdrs)


def signing_key(kid, url):
    """(n, e) for this key id from Google's JWKS, cached; an unknown kid refetches at most once a minute (key rotation)."""
    now = time.time()
    with _jwks_lock:
        fresh = _jwks["url"] == url and now < _jwks["exp"]
        if fresh and kid in _jwks["keys"]:
            return _jwks["keys"][kid]
        if fresh and now - _jwks["fetched"] < 60:
            raise AuthError(f"unknown signing key {str(kid)[:40]}")
        keys, age = _fetch_jwks(url)
        _jwks.update(url=url, keys=keys, exp=now + age, fetched=now)
        if kid not in keys:
            raise AuthError(f"unknown signing key {str(kid)[:40]}")
        return keys[kid]


def verify_id_token(token, cfg, nonce, now=None):
    """The ID token's claims once every check passes (signature, iss, aud / azp, exp, iat, nonce, email_verified, sub,
    email); AuthError otherwise."""
    now = now or time.time()
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise AuthError("malformed ID token")
    try:
        header, claims = json.loads(b64url_decode(parts[0])), json.loads(b64url_decode(parts[1]))
        sig = b64url_decode(parts[2])
    except (ValueError, AuthError):
        raise AuthError("malformed ID token")
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("malformed ID token")
    if header.get("alg") != "RS256":
        raise AuthError(f"unexpected alg {str(header.get('alg'))[:20]}")
    n, e = signing_key(header.get("kid"), cfg["jwks_url"])
    if not rsa_verify(n, e, (parts[0] + "." + parts[1]).encode("ascii"), sig):
        raise AuthError("bad signature")
    if claims.get("iss") not in ISSUERS:
        raise AuthError("wrong issuer")
    aud = claims.get("aud")
    if isinstance(aud, list):
        if cfg["client_id"] not in aud or claims.get("azp") != cfg["client_id"]:
            raise AuthError("wrong audience")
    elif aud != cfg["client_id"]:
        raise AuthError("wrong audience")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or now > exp + SKEW:
        raise AuthError("expired ID token")
    if not isinstance(iat, (int, float)) or isinstance(iat, bool) or iat > now + SKEW:
        raise AuthError("ID token issued in the future")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"].encode(), str(nonce or "").encode()):
        raise AuthError("nonce mismatch")
    if claims.get("email_verified") not in (True, "true"):
        raise AuthError("e-mail not verified by Google")
    email = str(claims.get("email") or "").strip().lower()
    if not ap.EMAIL.fullmatch(email) or len(email) > 200:
        raise AuthError("no usable e-mail")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", sub):
        raise AuthError("no subject")
    return dict(claims, email=email)


# ------------------------------------------------------------------------------------------------------------ pending logins

_pending_lock = threading.Lock()
PENDING = {}                       # state → {nonce, verifier, next, at}


def _new_pending(nxt, now=None):
    now = now or time.time()
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    with _pending_lock:
        for k in [k for k, v in PENDING.items() if now - v["at"] > LOGIN_TTL]:
            PENDING.pop(k, None)
        while len(PENDING) >= MAX_PENDING:
            PENDING.pop(next(iter(PENDING)))
        PENDING[state] = {"nonce": nonce, "verifier": verifier, "next": nxt, "at": now}
    return state, nonce, verifier


def _take_pending(state, now=None):
    now = now or time.time()
    with _pending_lock:
        p = PENDING.pop(state, None)
    return p if p and now - p["at"] <= LOGIN_TTL else None


# ------------------------------------------------------------------------------------------------------------ sessions

def _read_sessions():
    try:
        doc = json.loads(sessions_path().read_text())
        return doc if isinstance(doc, dict) and isinstance(doc.get("sessions"), dict) else {"sessions": {}}
    except (OSError, ValueError):
        return {"sessions": {}}


class _store:
    """with _store() as s: … — flock on sessions.json.lock, fresh read, atomic write (mode 600) on a clean exit."""

    def __enter__(self):
        f = sessions_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        self.lf = open(f.with_name(f.name + ".lock"), "a+")
        fcntl.flock(self.lf.fileno(), fcntl.LOCK_EX)
        self.doc = _read_sessions()
        return self.doc

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                f = sessions_path()
                ap._atomic_write(f, json.dumps(self.doc, indent=1) + "\n")
                os.chmod(f, 0o600)
        finally:
            fcntl.flock(self.lf.fileno(), fcntl.LOCK_UN)
            self.lf.close()
        return False


def _hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(uid, now=None):
    """A new session for this user → the token (the cookie value). Expired sessions are dropped on the way."""
    now = now or utcnow()
    token = secrets.token_urlsafe(32)
    with _store() as s:
        ss = s["sessions"]
        for k in [k for k, v in ss.items() if not isinstance(v, dict) or (ap.parse_iso(v.get("expires")) or now) <= now]:
            ss.pop(k, None)
        mine = sorted((k for k, v in ss.items() if v.get("user") == uid), key=lambda k: ss[k].get("seen") or "")
        for k in mine[:max(0, len(mine) - MAX_SESSIONS + 1)]:
            ss.pop(k, None)
        ss[_hash(token)] = {"user": uid, "created": iso(now), "seen": iso(now), "expires": iso(now + timedelta(days=SESSION_DAYS))}
    return token


def lookup(token, now=None):
    """(session, refreshed) for a live session; (None, False) when missing or expired. Sliding expiry: SESSION_DAYS from
    the last use, written at most once every SLIDE_EVERY seconds (refreshed = True then: re-send the cookie)."""
    if not token or not TOKEN_RE.fullmatch(token):
        return None, False
    now = now or utcnow()
    h = _hash(token)
    s = _read_sessions()["sessions"].get(h)
    if not isinstance(s, dict):
        return None, False
    exp, seen = ap.parse_iso(s.get("expires")), ap.parse_iso(s.get("seen"))
    if exp is None or exp <= now:
        with _store() as st:
            st["sessions"].pop(h, None)
        return None, False
    if seen is None or (now - seen).total_seconds() >= SLIDE_EVERY:
        with _store() as st:
            cur = st["sessions"].get(h)
            if not isinstance(cur, dict):
                return None, False
            cur.update(seen=iso(now), expires=iso(now + timedelta(days=SESSION_DAYS)))
            s = dict(cur)
        return s, True
    return s, False


def delete_session(token):
    if token and TOKEN_RE.fullmatch(token):
        with _store() as s:
            return s["sessions"].pop(_hash(token), None) is not None
    return False


def delete_user_sessions(uids):
    uids = set(uids)
    if not uids:
        return 0
    with _store() as s:
        gone = [k for k, v in s["sessions"].items() if isinstance(v, dict) and v.get("user") in uids]
        for k in gone:
            s["sessions"].pop(k, None)
    return len(gone)


def find_user(d, uid):
    return next((u for u in d.get("users") or [] if isinstance(u, dict) and u.get("id") == uid), None) if uid else None


def current(cookie_header, now=None, d=None):
    """The signed-in user of a request: {"user": users[] record, "token", "refresh"} or None."""
    token = session_token_from(cookie_header)
    if not token:
        return None
    s, refreshed = lookup(token, now)
    if s is None:
        return None
    u = find_user(d if d is not None else ap.load(), s.get("user"))
    if u is None or not u.get("email"):
        delete_session(token)                                  # the user is gone (deleted): so is the session
        return None
    return {"user": u, "token": token, "refresh": refreshed}


# ------------------------------------------------------------------------------------------------------------ users

def upsert_user(claims, now=None):
    """The users[] record for a verified Google identity (by Google account id, else by e-mail) → (user copy, created).
    A first login is a sign-up: otto_trial.start_for_new_user gives it the free trial (or says why not)."""
    import otto_trial
    now = now or utcnow()
    email, sub = claims["email"], claims["sub"]
    name = re.sub(r"[\x00-\x1f\x7f<>]", "", str(claims.get("name") or ""))[:120].strip()
    hd = str(claims.get("hd") or "").strip().lower()[:120] or None
    with ap.transaction() as d:
        users = d.setdefault("users", [])
        u = next((x for x in users if isinstance(x, dict) and x.get("google_sub") == sub), None) or \
            next((x for x in users if isinstance(x, dict) and str(x.get("email") or "").lower() == email), None)
        created = u is None
        if created:
            u = {"id": "u-" + secrets.token_hex(8), "email": email, "name": name, "google_sub": sub, "created_at": iso(now),
                 "brands": []}
            otto_trial.start_for_new_user(d, u, now)
            users.append(u)
        else:
            old = str(u.get("email") or "").lower()
            if old and old != email:                            # the Google account's address changed: its own brands follow
                for b in d.get("brands") or []:
                    if isinstance(b, dict) and b.get("id") in (u.get("brands") or []) and old in (b.get("members") or []):
                        b["members"] = [email if m == old else m for m in b["members"]]
            u.update(email=email, google_sub=sub)
            if name:
                u["name"] = name
        u["hd"] = hd
        u["last_login_at"] = iso(now)
        out = json.loads(json.dumps(u))
    return out, created


# ------------------------------------------------------------------------------------------------------------ pages

def page(code, title, text, retry=True, log=None):
    import otto_email
    E = otto_email.esc
    body = (otto_email._top("") + f'<div class="st w">{otto_email.ICON_INFO}</div><h1>{E(title)}</h1><p class="lead">{E(text)}</p>'
            + ('<a class="btn" href="/auth/google/start">Try again</a>' if retry else "") + '<a class="btn" href="/">Back to Otto</a>')
    html, csp = otto_email.page(title, body)
    return Reply(code, [("Content-Security-Policy", csp)], html.encode(), "text/html; charset=utf-8", log)


def json_reply(code, obj, headers=(), log=None):
    return Reply(code, list(headers), json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", log)


# ------------------------------------------------------------------------------------------------------------ flows

def start(query, client_key):
    """GET /auth/google/start → 302 to Google (or a page saying why not)."""
    cfg = config()
    if cfg is None:
        return page(503, NOT_SET_UP, "Otto's team has not switched Google sign-in on for this site yet.", retry=False)
    if not rate_ok("start:" + client_key):
        return page(429, "Too many sign-in attempts", "Please wait a few minutes and try again.", retry=False)
    q = urllib.parse.parse_qs(query or "", max_num_fields=8)
    nxt = safe_next((q.get("next") or ["/"])[0])
    state, nonce, verifier = _new_pending(nxt)
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"], "response_type": "code", "scope": SCOPES,
              "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
              "prompt": "select_account", "access_type": "online"}
    _, login = cookie_names(cfg["secure"])
    return Reply(302, [("Location", cfg["auth_url"] + "?" + urllib.parse.urlencode(params)),
                       set_cookie(login, state, LOGIN_TTL, cfg["secure"])], b"", "text/plain; charset=utf-8", None)


def exchange_code(cfg, code, verifier):
    """The authorization code → the ID token, at Google's token endpoint (server to server, TLS)."""
    body = urllib.parse.urlencode({"code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                   "redirect_uri": cfg["redirect_uri"], "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    status, _, raw = _http("POST", cfg["token_url"], body, {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        doc = json.loads(raw or b"{}")
    except ValueError:
        doc = {}
    if status != 200:
        raise AuthError(f"token endpoint HTTP {status} {str((doc or {}).get('error') or '')[:40]}")
    tok = doc.get("id_token") if isinstance(doc, dict) else None
    if not isinstance(tok, str) or len(tok) > 16384:
        raise AuthError("no ID token in the token response")
    return tok


def callback(query, cookie_header, client_key, now=None):
    """GET /auth/google/callback → 303 to `next` with a session cookie, or a page saying why not."""
    cfg = config()
    if cfg is None:
        return page(503, NOT_SET_UP, "Otto's team has not switched Google sign-in on for this site yet.", retry=False)
    sid_name, login_name = cookie_names(cfg["secure"])
    clear_login = set_cookie(login_name, "", 0, cfg["secure"])
    if not rate_ok("cb:" + client_key):
        return page(429, "Too many sign-in attempts", "Please wait a few minutes and try again.", retry=False)
    q = urllib.parse.parse_qs(query or "", max_num_fields=12)
    state = (q.get("state") or [""])[0]
    bound = parse_cookies(cookie_header).get(login_name) or ""
    if not state or not bound or not hmac.compare_digest(state.encode(), bound.encode()):
        if state:
            _take_pending(state)                               # burn it: a state is tried once
        r = page(400, "This sign-in expired", "It took too long, or it was started in another browser or tab. Please start again.",
                 log="auth callback refused (state does not match this browser)")
        return r._replace(headers=r.headers + [clear_login])
    pending = _take_pending(state)
    if pending is None:
        r = page(400, "This sign-in expired", "It took too long, or it was already used. Please start again.",
                 log="auth callback refused (no pending sign-in for this state)")
        return r._replace(headers=r.headers + [clear_login])
    if q.get("error"):
        r = page(400, "Sign-in cancelled", "Google didn't sign you in, so nothing changed.",
                 log=f"auth callback: Google said {str(q['error'][0])[:40]}")
        return r._replace(headers=r.headers + [clear_login])
    code = (q.get("code") or [""])[0]
    if not code or len(code) > 2048:
        r = page(400, "Sign-in didn't complete", "Google sent Otto back without a sign-in code. Please start again.")
        return r._replace(headers=r.headers + [clear_login])
    try:
        claims = verify_id_token(exchange_code(cfg, code, pending["verifier"]), cfg, pending["nonce"],
                                 now=(now.timestamp() if now else None))
    except AuthError as e:
        r = page(401, "Google didn't confirm your sign-in", "Otto could not verify the answer from Google, so you are not "
                 "signed in. Please try again in a minute.", log=f"auth callback refused: {e}")
        return r._replace(headers=r.headers + [clear_login])
    u, created = upsert_user(claims, now)
    token = create_session(u["id"], now)
    nxt = pending["next"]
    if nxt == "/" and not ap.member_brands(ap.load(), u["email"]):
        nxt = "/onboarding.html"                               # a new account has nothing to show yet: set up the first brand
    return Reply(303, [("Location", nxt), set_cookie(sid_name, token, SESSION_DAYS * 86400, cfg["secure"]), clear_login],
                 b"", "text/plain; charset=utf-8",
                 f"auth login {mask(u['email'])} {'sign-up' if created else 'returning'} ({u.get('status')})",
                 ("signup", u["id"]) if created else None)


def logout(cookie_header):
    token = session_token_from(cookie_header)
    gone = delete_session(token) if token else False
    return json_reply(200, {"ok": True, "signed_out": gone}, clear_cookies(), log="auth logout" if gone else None)


def refresh_cookie(token):
    """The Set-Cookie that extends a slid session in the browser too."""
    cfg = config()
    secure = cfg["secure"] if cfg else True
    return set_cookie(cookie_names(secure)[0], token, SESSION_DAYS * 86400, secure)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "status":
        c = config()
        n = len(_read_sessions()["sessions"])
        print(json.dumps({"configured": bool(c), "redirect_uri": c and c["redirect_uri"], "sessions": n}, indent=1))
    elif cmd == "logout-user" and len(sys.argv) > 2:
        d = ap.load()
        uids = [u["id"] for u in d.get("users") or [] if isinstance(u, dict) and (u.get("id") == sys.argv[2]
                                                                                   or u.get("email") == sys.argv[2].lower())]
        print(f"{delete_user_sessions(uids)} session(s) ended")
    else:
        print(__doc__)
