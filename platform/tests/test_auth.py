#!/usr/bin/env python3
"""Google sign-in (otto_auth) through the real API server: the OIDC authorization-code flow with PKCE, state and nonce
against a fake Google (token endpoint + JWKS, tests/fake_google.py), every ID-token check that must refuse a sign-in, the
pure-Python RS256 verifier (including an OpenSSL-made known-answer vector), sessions (cookie flags, sliding expiry, expiry,
logout, a deleted user), the per-client rate limit, "never an admin from a session unless listed", tenant scoping by
session, and the 503 answer without a Google client.

  cd platform && python3 tests/test_auth.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import contextlib, io, json, os, shutil, sys, tempfile, threading, time, unittest, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_google as G                                                        # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="otto-auth-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_SESSIONS": str(TMP / "sessions.json"), "OTTO_BILLING": str(TMP / "billing.json"),
       "OTTO_EVENTS": str(TMP / "events.jsonl"), "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"),
       "OTTO_PLANS": str(PLATFORM / "plans.json")}
CLEAR = ("OTTO_ADMIN_USERS", "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_DOMAIN", "OTTO_GOOGLE_REDIRECT_URI", "OTTO_FALLBACK")
PROXIED = {"X-Real-IP": "203.0.113.7"}
# OpenSSL-made known answer (openssl genrsa 2048; openssl dgst -sha256 -sign): the message is a JWS signing input
KAT_MSG = b"eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJvdHRvLWthdCJ9"
KAT_N = int(
    "c44b52e18c42163ec49129b55df3c18efc3432545b28a9c12e6d1719ed190494b61177a0d3d880d3af0735b508f7bf93f59e"
    "11bb36add83549f7c545abf8d7fea89121a8f10211af010bd9b3c44aabbfdcd609d165cf09c188cdcba123f29706e50fb11b"
    "7175400d174f4c5a4493b315a4175d254b150267dc7671b4f22e7c8d1b5bac700b25eee981c6fc57dcd63427947a2e20e922"
    "a13b75cc267bddf8f46e3191447e2cbf373aa3fdba8a5fc3835a1d1d64e50cc19fc2033a4d9e8912fccbbcd8c04b9c058cd6"
    "612cb0baaf6d4b8eb18f95514747cc882565605c493b05e118aa269875af3c9aeb4de437cbaa7391aff0ccf057282e36ba2d"
    "ac0778795c19", 16)
KAT_SIG = bytes.fromhex(
    "a49302a63c257e028c95bb5fe011154ea9f35acfb44baf32f06bfdcf34382a38d0f91ab157bdd8da56114cf34ed319c8edaa"
    "9c12d2a65e96ccbd9f63b6b9e62b2ba0b2e7633c48a7189c34e9b5f0e3ee04c29113d863ee91527e5382d0bdd44a646feff1"
    "b14d8fb009b8ee4a39f8779bbc511b0875bb561895b881c7c335d3a7a0c4d9a43b9ed4f5a089e82d453c0a08bf3563e21ab9"
    "a9f50b8522c42bee11611543fb4ae1fda7c7a13d5ef9e2a6b9af26bd7308bfe3d436b1dd6721839f94a3345e50fb1425abac"
    "daf4c02c4796b1f1407e7e026b00f100b87a03028f2f9dd2eb0222b8746c9ab730aedbb65bf085ad02be802708c1275d2db9"
    "f030ef2cfee3")


def seed():
    return {"brands": [{"id": "alpha", "name": "Alpha Dental", "url": "alpha-dental.example", "tz": "UTC", "status": "active",
                        "plan": "starter", "members": ["ann@alpha-dental.example"], "pillars": ["A"], "compliance": ""},
                       {"id": "beta", "name": "Beta Cafe", "url": "beta-cafe.example", "tz": "UTC", "status": "active",
                        "plan": "starter", "members": ["@beta-cafe.example"], "pillars": ["A"], "compliance": ""}],
            "posts": [{"id": "al-001", "brand": "alpha", "platform": "fb", "status": "pending_approval", "slot": "2031-01-01T09:00"},
                      {"id": "be-001", "brand": "beta", "platform": "fb", "status": "pending_approval", "slot": "2031-01-01T09:00"}],
            "recommendations": [], "connections": [], "campaigns": [], "users": []}


_SAVED, S = {}, {}


def write_config(**over):
    (TMP / "secrets").mkdir(exist_ok=True)
    (TMP / "secrets" / "google-oauth.json").write_text(json.dumps(S["google"].config(**over)))


def reset():
    (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
    for f in ("sessions.json", "billing.json"):
        (TMP / f).unlink(missing_ok=True)
    write_config()
    otto_auth._rl.clear()
    otto_auth.PENDING.clear()
    otto_auth._jwks.update(url=None, keys={}, exp=0.0, fetched=0.0)
    for k in CLEAR:
        os.environ.pop(k, None)


def setUpModule():
    (TMP / "brands").mkdir(parents=True, exist_ok=True)
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_api, otto_auth, otto_trial
    import ap, otto_api, otto_auth, otto_trial                                     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG)
    ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = TMP / "data.json", TMP / "index.html", TMP / "brands", TMP / "actions.log"
    S["google"] = G.FakeGoogle()
    S["srv"] = otto_api.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
    threading.Thread(target=S["srv"].serve_forever, daemon=True).start()
    S["base"] = f"http://127.0.0.1:{S['srv'].server_address[1]}"
    S["origin"] = sorted(otto_api.ALLOWED_ORIGINS)[0]
    reset()


def tearDownModule():
    for k in ("srv",):
        if k in S:
            S[k].shutdown(); S[k].server_close()
    if "google" in S:
        S["google"].close()
    if "paths" in _SAVED:
        ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = _SAVED["paths"]
    for k, v in _SAVED.get("env", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


def req(method, path, headers=None, body=None, sid=None):
    h = dict(headers or {})
    if sid:
        h["Cookie"] = (h.get("Cookie", "") + "; " if h.get("Cookie") else "") + f"otto_sid={sid}"
    st, msg, raw = G.request(S["base"], method, path, h, body)
    try:
        obj = json.loads(raw) if raw and "json" in (msg.get("Content-Type") or "") else raw.decode(errors="replace")
    except ValueError:
        obj = raw.decode(errors="replace")
    return st, msg, obj


def login(email="eva@koffie.example", sub="1001", **kw):
    st, msg, sid, body = G.sign_in(S["base"], S["google"], email, sub, headers=kw.pop("headers", PROXIED), **kw)
    return st, msg, sid, body


def users():
    return ap.load().get("users") or []


class FlowTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_start_redirects_to_google_with_pkce_state_and_nonce(self):
        st, msg, p = G.start(S["base"], "/onboarding.html?site=koffie.example", PROXIED)
        self.assertEqual(st, 302)
        self.assertTrue(msg["Location"].startswith(otto_auth.AUTH_URL + "?"), "the real Google authorize endpoint")
        self.assertEqual((p["response_type"], p["scope"], p["code_challenge_method"], p["client_id"], p["redirect_uri"]),
                         ("code", "openid email profile", "S256", G.CLIENT_ID, G.REDIRECT))
        self.assertGreaterEqual(len(p["state"]), 40)
        self.assertGreaterEqual(len(p["nonce"]), 40)
        self.assertNotEqual(p["state"], p["nonce"])
        pend = otto_auth.PENDING[p["state"]]
        self.assertEqual(p["code_challenge"], otto_auth.b64url(__import__("hashlib").sha256(pend["verifier"].encode()).digest()))
        self.assertNotIn(pend["verifier"], msg["Location"], "the verifier never leaves the server")
        self.assertEqual(pend["next"], "/onboarding.html?site=koffie.example")
        c = G.cookies_of(msg)["otto_login"]
        self.assertEqual(c[0], p["state"])
        for flag in ("httponly", "samesite=lax", "path=/", "max-age=600"):
            self.assertIn(flag, c[1])
        self.assertNotIn("secure", c[1], "http://localhost has no Secure cookie")
        self.assertEqual(msg["Cache-Control"], "no-store")

    def test_happy_path_signs_up_starts_the_trial_and_opens_a_session(self):
        st, msg, sid, _ = login(nxt="/onboarding.html?site=koffie.example")
        self.assertEqual(st, 303)
        self.assertEqual(msg["Location"], "/onboarding.html?site=koffie.example")
        c = G.cookies_of(msg)
        self.assertIn("httponly", c["otto_sid"][1])
        self.assertIn("samesite=lax", c["otto_sid"][1])
        self.assertIn(f"max-age={30 * 86400}", c["otto_sid"][1])
        self.assertEqual(c["otto_login"][0], "", "the login cookie is cleared")
        self.assertEqual(msg["Referrer-Policy"], "no-referrer")
        u = users()[0]
        self.assertEqual((u["email"], u["google_sub"], u["status"]), ("eva@koffie.example", "1001", "trial"))
        start, end = ap.parse_iso(u["trial_started_at"]), ap.parse_iso(u["trial_ends_at"])
        self.assertEqual(end - start, timedelta(days=7))
        self.assertNotIn("picture", u)
        store = (TMP / "sessions.json").read_text()
        self.assertNotIn(sid, store, "only the SHA-256 of the session id is stored")
        self.assertEqual(oct(os.stat(TMP / "sessions.json").st_mode & 0o777), "0o600")
        st, _, me = req("GET", "/auth/me", PROXIED, sid=sid)
        self.assertEqual((st, me["signed_in"], me["email"], me["trial"]["state"], me["trial"]["days_left"]),
                         (200, True, "eva@koffie.example", "running", 7))
        self.assertTrue(me["google"])
        st, _, out = req("GET", "/otto-api/data", PROXIED, sid=sid)
        self.assertEqual((st, out.get("code")), (403, "no_brand"), "signed in, no brand yet → set up the first one")
        self.assertIn("auth login e•••@koffie.example sign-up (trial)", (TMP / "actions.log").read_text())
        # a second login is the same account, never a second trial
        st, msg, sid2, _ = login(nxt="/")
        self.assertEqual((st, msg["Location"]), (303, "/onboarding.html"), "nothing to show yet: onboarding")
        self.assertEqual(len(users()), 1)
        self.assertEqual(users()[0]["trial_started_at"], u["trial_started_at"])

    def test_next_is_always_a_same_origin_path(self):
        for bad in ("https://evil.example/x", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/a\nb", ""):
            self.assertEqual(otto_auth.safe_next(bad), "/", bad)
        self.assertEqual(otto_auth.safe_next("/onboarding.html?site=a.com"), "/onboarding.html?site=a.com")

    def test_state_must_match_this_browser_and_is_single_use(self):
        st, msg, p = G.start(S["base"], "/", PROXIED)
        code = S["google"].issue(p["code_challenge"], G.jwt(G.claims_for("x@y.example", "9", p["nonce"]), S["google"].key))
        q = "/auth/google/callback?" + urllib.parse.urlencode({"code": code, "state": p["state"]})
        st, _, body = req("GET", q, dict(PROXIED, Cookie="otto_login=someone-elses-state"))
        self.assertEqual(st, 400)
        self.assertIn("This sign-in expired", body)
        st, _, _ = req("GET", q, dict(PROXIED, Cookie=f"otto_login={p['state']}"))
        self.assertEqual(st, 400, "a state that was tried once is burnt")
        st, _, _ = req("GET", q, PROXIED)
        self.assertEqual(st, 400, "no login cookie at all")
        self.assertEqual(users(), [])
        self.assertFalse(S["google"].token_calls and S["google"].token_calls[-1].get("code") == code, "never exchanged")

    def test_google_error_and_missing_code(self):
        st, msg, p = G.start(S["base"], "/", PROXIED)
        st, _, body = req("GET", "/auth/google/callback?" + urllib.parse.urlencode({"error": "access_denied", "state": p["state"]}),
                          dict(PROXIED, Cookie=f"otto_login={p['state']}"))
        self.assertEqual(st, 400)
        self.assertIn("Sign-in cancelled", body)
        self.assertIn("default-src 'none'", _["Content-Security-Policy"], "error pages: no script, strict CSP")
        self.assertEqual(users(), [])
        st, msg, p = G.start(S["base"], "/", PROXIED)
        st, _, body = req("GET", "/auth/google/callback?" + urllib.parse.urlencode({"state": p["state"]}),
                          dict(PROXIED, Cookie=f"otto_login={p['state']}"))
        self.assertEqual(st, 400)
        self.assertIn("without a sign-in code", body.replace("&#x27;", "'"))

    def test_pkce_verifier_must_match(self):
        st, msg, p = G.start(S["base"], "/", PROXIED)
        code = S["google"].issue("not-the-challenge", G.jwt(G.claims_for("x@y.example", "9", p["nonce"]), S["google"].key))
        st, _, body = req("GET", "/auth/google/callback?" + urllib.parse.urlencode({"code": code, "state": p["state"]}),
                          dict(PROXIED, Cookie=f"otto_login={p['state']}"))
        self.assertEqual(st, 401)
        self.assertIn("didn&#x27;t confirm", body)
        self.assertGreaterEqual(len(S["google"].token_calls[-1]["code_verifier"]), 43, "the verifier went to Google, server to server")
        self.assertIn("token endpoint HTTP 400", (TMP / "actions.log").read_text())
        self.assertEqual(users(), [])

    def test_every_id_token_check_refuses(self):
        other = G.rsa_key(seed=2)
        now = int(time.time())
        cases = {
            "nonce mismatch": dict(nonce="not-the-nonce"),
            "wrong issuer": dict(iss="https://evil.example"),
            "wrong audience": dict(aud="someone-else.apps.googleusercontent.com"),
            "list audience without azp": dict(aud=[G.CLIENT_ID, "other"], azp="other"),
            "expired": dict(exp=now - 600, iat=now - 4200),
            "issued in the future": dict(iat=now + 3600, exp=now + 7200),
            "unverified e-mail": dict(email_verified=False),
            "unverified e-mail (string)": dict(email_verified="false"),
            "no subject": dict(sub=None),
            "bad e-mail": dict(email="not-an-email"),
        }
        def token(over):
            return lambda nonce: G.jwt({k: v for k, v in dict(G.claims_for("mallory@example.com", "666", nonce), **over).items()
                                        if v is not None}, S["google"].key)
        for why, over in cases.items():
            with self.subTest(why):
                st, _, sid, body = login(email="mallory@example.com", sub="666", token_fn=token(over))
                self.assertEqual((st, sid), (401, None), why)
        tokens = {
            "signed by another key": lambda nonce: G.jwt(G.claims_for("m@x.example", "7", nonce), other),
            "alg none": lambda nonce: G.b64url(json.dumps({"alg": "none", "kid": "k1"}).encode()) + "." +
                                      G.b64url(json.dumps(G.claims_for("m@x.example", "7", nonce)).encode()) + ".",
            "HS256": lambda nonce: G.jwt(G.claims_for("m@x.example", "7", nonce), S["google"].key,
                                         header={"alg": "HS256", "kid": "k1"}),
            "unknown key id": lambda nonce: G.jwt(G.claims_for("m@x.example", "7", nonce), S["google"].key, kid="k9"),
            "tampered payload": lambda nonce: (lambda t: t.split(".")[0] + "." + G.b64url(json.dumps(
                G.claims_for("admin@otto.example", "1", nonce)).encode()) + "." + t.split(".")[2])(
                G.jwt(G.claims_for("m@x.example", "7", nonce), S["google"].key)),
            "garbage": lambda nonce: "a.b",
        }
        for why, fn in tokens.items():
            with self.subTest(why):
                st, _, sid, _ = login(email="m@x.example", sub="7", token_fn=fn)
                self.assertEqual((st, sid), (401, None), why)
        self.assertEqual(users(), [], "no refused sign-in created an account")
        self.assertEqual(json.loads((TMP / "sessions.json").read_text() if (TMP / "sessions.json").exists() else '{"sessions":{}}')["sessions"], {})
        self.assertLessEqual(S["google"].jwks_fetches, 3, "the JWKS is cached (an unknown kid refetches at most once a minute)")

    def test_rs256_verifier(self):
        self.assertTrue(otto_auth.rsa_verify(KAT_N, 65537, KAT_MSG, KAT_SIG), "OpenSSL's own PKCS#1 v1.5 signature verifies")
        self.assertFalse(otto_auth.rsa_verify(KAT_N, 65537, KAT_MSG + b"x", KAT_SIG))
        self.assertFalse(otto_auth.rsa_verify(KAT_N, 65537, KAT_MSG, KAT_SIG[:-1] + bytes([KAT_SIG[-1] ^ 1])))
        self.assertFalse(otto_auth.rsa_verify(KAT_N, 65537, KAT_MSG, KAT_SIG[1:]), "wrong length")
        self.assertFalse(otto_auth.rsa_verify(KAT_N, 3, KAT_MSG, KAT_SIG), "wrong exponent")
        small = G.rsa_key(bits=1024, seed=3)
        self.assertFalse(otto_auth.rsa_verify(small[0], small[1], b"m", G.rs256(small, b"m")), "keys under 2048 bits are refused")
        key = S["google"].key
        self.assertTrue(otto_auth.rsa_verify(key[0], key[1], b"m", G.rs256(key, b"m")))

    def test_jwks_rotation_refetches_once_a_minute_at_most(self):
        cfg = otto_auth.config()
        login()
        n0 = S["google"].jwks_fetches
        S["google"].keys.append(("k2", G.rsa_key(seed=2)))
        with self.assertRaises(otto_auth.AuthError):
            otto_auth.signing_key("k2", cfg["jwks_url"])                          # fetched < 60 s ago: no refetch
        self.assertEqual(S["google"].jwks_fetches, n0)
        otto_auth._jwks["fetched"] -= 120
        self.assertEqual(otto_auth.signing_key("k2", cfg["jwks_url"])[1], 65537, "a rotated key is found on the refetch")
        self.assertEqual(S["google"].jwks_fetches, n0 + 1)
        S["google"].keys.pop()


class SessionTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_sliding_expiry_expiry_and_logout(self):
        st, _, sid, _ = login()
        now = datetime.now(timezone.utc)
        s, refreshed = otto_auth.lookup(sid, now + timedelta(minutes=5))
        self.assertFalse(refreshed, "within the hour: nothing written")
        s, refreshed = otto_auth.lookup(sid, now + timedelta(days=20))
        self.assertTrue(refreshed)
        self.assertGreater(ap.parse_iso(s["expires"]), now + timedelta(days=49), "30 days from the last use")
        self.assertIsNotNone(otto_auth.lookup(sid, now + timedelta(days=45))[0], "still inside the slid window")
        self.assertIsNone(otto_auth.lookup(sid, now + timedelta(days=90))[0], "30 days unused: gone")
        self.assertEqual(json.loads((TMP / "sessions.json").read_text())["sessions"], {}, "an expired session is deleted")
        st, _, sid, _ = login()
        # the API re-sends the cookie when it slides the session
        with open(TMP / "sessions.json") as f:
            doc = json.load(f)
        for v in doc["sessions"].values():
            v["seen"] = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (TMP / "sessions.json").write_text(json.dumps(doc))
        st, msg, _ = req("GET", "/auth/me", PROXIED, sid=sid)
        self.assertIn("otto_sid", G.cookies_of(msg), "a slid session refreshes its cookie")
        # logout: Origin checked, the session gone, both cookies cleared
        st, _, _ = req("POST", "/auth/logout", dict(PROXIED, Origin="https://evil.example"), sid=sid)
        self.assertEqual(st, 403)
        st, msg, out = req("POST", "/auth/logout", dict(PROXIED, Origin=S["origin"]), sid=sid)
        self.assertEqual((st, out["signed_out"]), (200, True))
        self.assertIn("max-age=0", G.cookies_of(msg)["otto_sid"][1])
        st, _, me = req("GET", "/auth/me", PROXIED, sid=sid)
        self.assertFalse(me["signed_in"])
        self.assertIn("auth logout", (TMP / "actions.log").read_text())

    def test_a_deleted_user_is_signed_out(self):
        st, _, sid, _ = login()
        with ap.transaction(sync=False) as d:
            d["users"] = []
        st, _, me = req("GET", "/auth/me", PROXIED, sid=sid)
        self.assertFalse(me["signed_in"])
        self.assertEqual(json.loads((TMP / "sessions.json").read_text())["sessions"], {})

    def test_https_redirect_gives_host_prefixed_secure_cookies(self):
        write_config(redirect_uri="https://app.otto.example/auth/google/callback")
        st, msg, p = G.start(S["base"], "/", PROXIED)
        c = G.cookies_of(msg)
        self.assertIn("__Host-otto_login", c)
        self.assertIn("secure", c["__Host-otto_login"][1])
        self.assertNotIn("domain=", c["__Host-otto_login"][1], "host-only: never sent to admin. or the apex")
        self.assertEqual(p["redirect_uri"], "https://app.otto.example/auth/google/callback")
        os.environ["OTTO_DOMAIN"] = "otto.example"
        (TMP / "secrets" / "google-oauth.json").write_text(json.dumps({"web": {"client_id": "c", "client_secret": "s"}}))
        self.assertEqual(otto_auth.config()["redirect_uri"], "https://app.otto.example/auth/google/callback",
                         "Google's downloaded client file + OTTO_DOMAIN")
        os.environ["OTTO_GOOGLE_REDIRECT_URI"] = "http://localhost:8790/auth/google/callback"
        self.assertFalse(otto_auth.config()["secure"], "local development override")

    def test_not_set_up_answers_503_and_the_ui_hides_the_button(self):
        (TMP / "secrets" / "google-oauth.json").unlink()
        st, msg, body = req("GET", "/auth/google/start", PROXIED)
        self.assertEqual(st, 503)
        self.assertIn("Google sign-in isn&#x27;t set up yet", body)
        self.assertEqual(req("GET", "/auth/google/callback?code=x&state=y", PROXIED)[0], 503)
        st, _, me = req("GET", "/auth/me", PROXIED)
        self.assertEqual((st, me["signed_in"], me["google"]), (200, False, False))
        st, _, out = req("GET", "/otto-api/data", PROXIED)
        self.assertEqual((st, out["google"]), (401, False))

    def test_rate_limit_per_client(self):
        old = otto_auth.RATE_MAX
        otto_auth.RATE_MAX = 3
        try:
            codes = [G.start(S["base"], "/", {"X-Real-IP": "198.51.100.9"})[0] for _ in range(4)]
            self.assertEqual(codes, [302, 302, 302, 429])
            self.assertEqual(G.start(S["base"], "/", {"X-Real-IP": "198.51.100.10"})[0], 302, "another client is not limited")
        finally:
            otto_auth.RATE_MAX = old


class ScopeTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_tenant_scoping_by_session(self):
        _, _, ann, _ = login("ann@alpha-dental.example", "2001")
        st, _, d = req("GET", "/otto-api/data", PROXIED, sid=ann)
        self.assertEqual(st, 200)
        self.assertEqual([b["id"] for b in d["brands"]], ["alpha"])
        self.assertEqual([p["id"] for p in d["posts"]], ["al-001"])
        self.assertNotIn("users", d)
        # another brand's post is not there for her
        st, _, out = req("POST", "/otto-api/action", dict(PROXIED, Origin=S["origin"], **{"Content-Type": "application/json"}),
                         json.dumps({"kind": "post", "id": "be-001", "status": "approved"}).encode(), sid=ann)
        self.assertEqual(st, 404)
        # "@beta-cafe.example": a plain Google account with that address is not the company; its Workspace account is
        _, _, bob, _ = login("bob@beta-cafe.example", "2002")
        self.assertEqual(req("GET", "/otto-api/data", PROXIED, sid=bob)[0], 403)
        _, _, bob, _ = login("bob@beta-cafe.example", "2002", hd="beta-cafe.example")
        st, _, d = req("GET", "/otto-api/data", PROXIED, sid=bob)
        self.assertEqual([b["id"] for b in d["brands"]], ["beta"])

    def test_a_session_scopes_even_on_a_single_tenant_box_and_locally(self):
        _, _, ann, _ = login("ann@alpha-dental.example", "2001")
        os.environ["OTTO_SINGLE_TENANT"] = "1"
        st, _, d = req("GET", "/otto-api/data", PROXIED, sid=ann)
        self.assertEqual([b["id"] for b in d["brands"]], ["alpha"])
        st, _, d = req("GET", "/otto-api/data", {}, sid=ann)                    # a direct local call with a cookie
        self.assertEqual([b["id"] for b in d["brands"]], ["alpha"])

    def test_never_admin_from_a_session_unless_listed(self):
        _, _, eve, _ = login("eve@evil.example", "3001")
        os.environ["OTTO_ADMIN_USERS"] = "*"
        st, _, out = req("GET", "/otto-api/data", PROXIED, sid=eve)
        self.assertEqual(st, 403, "“*” means anyone Cloudflare Access let in — never a Google sign-up")
        self.assertEqual(req("GET", "/otto-api/admin/snapshot", PROXIED, sid=eve)[0], 403)
        st, _, _ = req("POST", "/otto-api/admin", dict(PROXIED, Origin=S["origin"], **{"Content-Type": "application/json"}),
                       json.dumps({"action": "kill_switch", "state": "on"}).encode(), sid=eve)
        self.assertEqual(st, 403)
        self.assertFalse((ap.load().get("controls") or {}).get("publishing_paused"))
        # listed by exact address: sees every brand in the app, but the console API still needs the proxy (Access)
        _, _, max_, _ = login("max@otto.example", "3002")
        os.environ["OTTO_ADMIN_USERS"] = "max@otto.example"
        st, _, d = req("GET", "/otto-api/data", PROXIED, sid=max_)
        self.assertEqual(sorted(b["id"] for b in d["brands"]), ["alpha", "beta"])
        self.assertEqual(req("GET", "/otto-api/admin/snapshot", PROXIED, sid=max_)[0], 403)
        self.assertEqual(req("GET", "/otto-api/admin/snapshot", dict(PROXIED, **{"X-Otto-User": "max@otto.example"}))[0], 200)

    def test_session_and_a_different_proxy_user_is_refused(self):
        _, _, ann, _ = login("ann@alpha-dental.example", "2001")
        st, _, out = req("GET", "/otto-api/data", dict(PROXIED, **{"X-Otto-User": "bob@beta-cafe.example"}), sid=ann)
        self.assertEqual(st, 401)
        self.assertIn("two different sign-ins", out["error"])
        st, _, d = req("GET", "/otto-api/data", dict(PROXIED, **{"X-Otto-User": "ann@alpha-dental.example"}), sid=ann)
        self.assertEqual(st, 200, "the same person twice is fine")

    def test_proxy_key_rule_still_holds_without_a_session(self):
        os.environ["OTTO_PROXY_KEY"] = "k" * 32
        st, _, _ = req("GET", "/otto-api/data", dict(PROXIED, **{"X-Otto-User": "ann@alpha-dental.example"}))
        self.assertEqual(st, 401)
        st, _, d = req("GET", "/otto-api/data", dict(PROXIED, **{"X-Otto-User": "ann@alpha-dental.example", "X-Otto-Proxy-Key": "k" * 32}))
        self.assertEqual([b["id"] for b in d["brands"]], ["alpha"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
