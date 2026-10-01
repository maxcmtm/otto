"""A stand-in for Google's OpenID Connect endpoints, for tests/test_auth.py and tests/test_trial.py (not a test module itself).

FakeGoogle runs a 127.0.0.1 HTTP server with Google's token endpoint (POST /token: checks client id + secret, redirect URI,
grant type, the single-use code and the PKCE verifier against the challenge the sign-in started with) and its JWKS
(GET /certs, Cache-Control max-age). ID tokens are RS256 JWTs signed here with a pure-Python RSA key (a deterministic
2048-bit key generated once per process). sign_in() drives a whole sign-in against an otto_api server the way a browser
does: /auth/google/start → (Google) → /auth/google/callback, cookies carried by hand, redirects not followed.
Stdlib only.
"""
import base64, hashlib, http.client, http.server, json, random, secrets, threading, time, urllib.parse

CLIENT_ID = "otto-test.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-secret-do-not-use"
REDIRECT = "http://localhost:8790/auth/google/callback"
DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
SMALL = [p for p in range(3, 2000) if all(p % q for q in range(2, int(p ** 0.5) + 1))]


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _probable_prime(n, rng, rounds=24):
    if any(n % p == 0 for p in SMALL):
        return n in SMALL
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits, rng):
    while True:
        c = rng.getrandbits(bits) | (1 << bits - 1) | (1 << bits - 2) | 1
        if _probable_prime(c, rng):
            return c


_KEYS = {}


def rsa_key(bits=2048, seed=1):
    """(n, e, d) — deterministic per (bits, seed), cached for the process."""
    if (bits, seed) not in _KEYS:
        rng = random.Random(seed)
        e = 65537
        while True:
            p, q = _prime(bits // 2, rng), _prime(bits // 2, rng)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e and (p * q).bit_length() == bits:
                break
        _KEYS[(bits, seed)] = (p * q, e, pow(e, -1, phi))
    return _KEYS[(bits, seed)]


def rs256(key, msg):
    n, _, d = key
    k = (n.bit_length() + 7) // 8
    t = DIGEST_INFO + hashlib.sha256(msg).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def jwt(claims, key, kid="k1", header=None):
    h = b64url(json.dumps(header or {"alg": "RS256", "kid": kid, "typ": "JWT"}).encode())
    p = b64url(json.dumps(claims).encode())
    return f"{h}.{p}." + b64url(rs256(key, f"{h}.{p}".encode()))


def jwk(key, kid):
    n, e, _ = key
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid,
            "n": b64url(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": b64url(e.to_bytes(3, "big"))}


def claims_for(email, sub, nonce, **over):
    now = int(time.time())
    c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "azp": CLIENT_ID, "sub": sub, "email": email,
         "email_verified": True, "name": email.split("@")[0].title(), "iat": now, "exp": now + 3600, "nonce": nonce}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


class FakeGoogle:
    def __init__(self):
        self.key = rsa_key()
        self.keys = [("k1", self.key)]
        self.codes = {}
        self.jwks_fetches = 0
        self.token_calls = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj, headers=()):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/certs"):
                    me.jwks_fetches += 1
                    return self._json(200, {"keys": [jwk(k, kid) for kid, k in me.keys]},
                                      [("Cache-Control", "public, max-age=3600, must-revalidate")])
                self._json(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                form = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
                me.token_calls.append(form)
                ent = me.codes.pop(form.get("code"), None)
                challenge = b64url(hashlib.sha256((form.get("code_verifier") or "").encode()).digest())
                if (ent is None or form.get("grant_type") != "authorization_code" or form.get("client_id") != CLIENT_ID
                        or form.get("client_secret") != CLIENT_SECRET or form.get("redirect_uri") != REDIRECT
                        or challenge != ent["challenge"]):
                    return self._json(400, {"error": "invalid_grant"})
                self._json(200, {"access_token": "ya29.fake", "expires_in": 3599, "token_type": "Bearer",
                                 "scope": "openid email profile", "id_token": ent["token"]})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def config(self, **over):
        c = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "redirect_uri": REDIRECT,
             "token_url": self.base + "/token", "jwks_url": self.base + "/certs"}
        c.update(over)
        return c

    def issue(self, challenge, token):
        code = "4/0A" + secrets.token_urlsafe(24)
        self.codes[code] = {"challenge": challenge, "token": token}
        return code


def request(base, method, path, headers=None, body=None):
    """(status, headers message, body bytes) — no redirect is followed."""
    u = urllib.parse.urlsplit(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=20)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, r.msg, r.read()
    finally:
        c.close()


def cookies_of(msg):
    """{name: (value, attributes lower-case)} from Set-Cookie headers."""
    out = {}
    for sc in msg.get_all("Set-Cookie") or []:
        first, _, attrs = sc.partition(";")
        k, _, v = first.partition("=")
        out[k.strip()] = (v.strip(), attrs.lower())
    return out


def start(api_base, nxt="/", headers=None):
    q = "?" + urllib.parse.urlencode({"next": nxt}) if nxt else ""
    st, msg, body = request(api_base, "GET", "/auth/google/start" + q, headers)
    loc = msg.get("Location") or ""
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))
    return st, msg, params


def sign_in(api_base, fake, email, sub, nxt="/", headers=None, token_fn=None, **claim_over):
    """A whole sign-in. → (status, response headers, session cookie value or None, callback body). token_fn(nonce) makes a
    custom ID token; else a valid one for (email, sub) with claim_over applied."""
    st, msg, params = start(api_base, nxt, headers)
    assert st == 302, (st, msg)
    login = {k: v for k, (v, _) in cookies_of(msg).items() if k.endswith("otto_login")}
    name, state = next(iter(login.items()))
    token = token_fn(params["nonce"]) if token_fn else jwt(claims_for(email, sub, params["nonce"], **claim_over), fake.key)
    code = fake.issue(params["code_challenge"], token)
    h = dict(headers or {}, Cookie=f"{name}={state}")
    st, msg, body = request(api_base, "GET", "/auth/google/callback?" + urllib.parse.urlencode({"code": code, "state": state}), h)
    sid = next((v for k, (v, _) in cookies_of(msg).items() if k.endswith("otto_sid") and v), None)
    return st, msg, sid, body
