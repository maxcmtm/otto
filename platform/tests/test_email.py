#!/usr/bin/env python3
"""E-mail approvals (otto_email + its routes in otto_api, jobs in otto_cron, fields in otto_admin): digest selection and the
claim that keeps two runs from sending twice, tokens (sign / verify / expiry / replay / wrong brand / removed recipient),
GET never acting, POST applying the decision through ap.decide with via="email" under the transition table and the tenant
rules, recommendations + the paid-plan card, the outbox fallback, SMTP against a local fake server (STARTTLS required, no
credentials in the clear), Postmark / Resend against a local HTTP stub (tracking off), rendering sanity (both parts, absolute
links, no tracking pixel, no script, no web font), cron gating by approvals channel and plan, the Settings action and the owner
console fields. Stdlib unittest; the only network is 127.0.0.1 servers started here; nothing outside a throwaway workspace.

  cd platform && python3 tests/test_email.py
  cd platform && python3 -m unittest discover -s tests          # with the other suites
"""
import base64, contextlib, email, email.policy, http.server, io, json, os, re, shutil, socketserver, ssl, subprocess, sys
import tempfile, threading, time, unittest, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="otto-email-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public_assets"),
       "OTTO_PUBLIC_BASE": "https://otto.example/", "OTTO_EVENTS": str(TMP / "events.jsonl"),
       "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_LEADS": str(TMP / "leads.json")}
CLEAR = ("OTTO_DOMAIN", "OTTO_APP_URL", "OTTO_EMAIL_BASE", "OTTO_OUTBOX", "OTTO_EMAIL_STATE", "OTTO_ADMIN_USERS",
         "OTTO_SINGLE_TENANT", "OTTO_PROXY_KEY", "OTTO_FALLBACK", "TELEGRAM_BOT_TOKEN", "OTTO_OWNER_CHAT_ID", "OTTO_PLANS")
NOW = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)          # 08:00 in Amsterdam
SECRET = "a" * 16 + "email-link-secret-for-tests-only" + "b" * 16
BASE_CFG = {"link_secret": SECRET, "app_url": "https://app.otto.example/", "action_base": "https://otto.example"}
ANNA, BRAM = "anna@noord.example", "bram@noord.example"


def seed():
    post = lambda pid, brand, status, slot, **kw: dict({"id": pid, "brand": brand, "pillar": "Bread", "platform": "ig",
                                                         "hook": f"Hook {pid}", "status": status, "slot": slot}, **kw)
    return {
        "brands": [
            {"id": "noord", "name": "Noordzee Bakery", "url": "noord.example", "tz": "Europe/Amsterdam", "status": "active",
             "plan": "starter", "approvals": "email", "members": [ANNA, "@noord.example", "Bram@Noord.example"]},
            {"id": "old", "name": "Old Mill", "url": "oldmill.example", "tz": "Europe/Dublin", "status": "active",
             "plan": "starter", "members": ["olga@oldmill.example"]},                                   # no field: Telegram
            {"id": "appy", "name": "Appy Cafe", "url": "appy.example", "tz": "Europe/Dublin", "status": "active",
             "plan": "starter", "approvals": "app", "members": ["ada@appy.example"]},
            {"id": "lapsed", "name": "Lapsed Co", "url": "lapsed.example", "tz": "Europe/Dublin", "status": "active",
             "plan": "none", "approvals": "email", "members": ["lee@lapsed.example"]},
            {"id": "domainonly", "name": "Domain Only", "url": "domainonly.example", "tz": "Europe/Dublin", "status": "active",
             "plan": "starter", "approvals": "email", "members": ["@domainonly.example"]}],
        "posts": [
            post("nb-001", "noord", "pending_approval", "2026-10-02T18:00", image="https://otto.example/assets/posts/nb-001.jpg",
                 caption="Thirty-six hours, flour, water, salt. 🍞\nThat's the whole recipe.", why="Sourdough posts get the most saves"),
            post("nb-002", "noord", "pending_approval", "2026-10-03T07:00:00+00:00", platform="fb", format="reel",
                 image="assets/posts/nb-002.jpg", hook="Behind the oven door"),
            post("nb-003", "noord", "pending_approval", "2026-10-06T09:00"),                     # beyond 72 h
            post("nb-004", "noord", "pending_approval", "2026-09-30T10:00"),                     # slot passed
            post("nb-005", "noord", "approved", "2026-10-02T12:00"),
            post("nb-006", "noord", "pending_approval", "2026-10-02T09:00", caption="A miracle loaf"),   # compliance
            post("nb-007", "noord", "published", "2026-09-29T10:00"),
            post("nb-100", "noord", "pending_approval", "2031-05-01T10:00"),                     # HTTP tests (real clock)
            post("nb-101", "noord", "published", "2031-05-01T11:00"),
            post("ol-001", "old", "pending_approval", "2026-10-02T10:00"),
            post("ap-001", "appy", "pending_approval", "2026-10-02T10:00"),
            post("la-001", "lapsed", "pending_approval", "2026-10-02T10:00"),
            post("do-001", "domainonly", "pending_approval", "2026-10-02T10:00")],
        "recommendations": [
            {"id": "rec-001", "priority": "P1", "title": "Approve the 2026-11 paid plan: 2 campaigns, ≈€900", "why": "Evergreen on Meta.",
             "impact": "Paid runs on the same calendar", "cta": "Approve plan", "status": "proposed", "brand": "noord",
             "source": "otto_ads", "action": "approve_plan", "plan": "2026-11"},
            {"id": "rec-002", "priority": "P0", "title": "Share the bake-off results", "why": "Your followers voted.", "impact": "Reach",
             "cta": "Do it", "status": "proposed", "brand": "noord"},
            {"id": "rec-003", "priority": "P2", "title": "Low priority", "why": "w", "impact": "i", "cta": "c", "status": "proposed", "brand": "noord"},
            {"id": "rec-004", "priority": "P1", "title": "Owner only", "why": "w", "impact": "i", "cta": "c", "status": "proposed",
             "brand": "noord", "audience": "owner"},
            {"id": "rec-005", "priority": "P1", "title": "Console card", "why": "w", "impact": "i", "cta": "c", "status": "proposed",
             "brand": "noord", "source": "otto_admin"},
            {"id": "rec-006", "priority": "P1", "title": "Old mill idea", "why": "w", "impact": "i", "cta": "c", "status": "proposed", "brand": "old"}],
        "campaigns": [
            {"id": "cp-001", "brand": "noord", "plan": "2026-11", "status": "draft", "network": "meta", "name": "Evergreen · bread",
             "daily_budget": 15, "start": "2026-11-01", "end": "2026-11-30", "currency": "€", "currency_code": "EUR"},
            {"id": "cp-002", "brand": "noord", "plan": "2026-11", "status": "draft", "network": "meta", "name": "Boost · sourdough",
             "daily_budget": 10, "start": "2026-11-03", "end": "2026-11-07", "currency": "€", "currency_code": "EUR"}],
        "connections": [], "taste_log": []}


def write_cfg(cfg):
    (TMP / "secrets" / "email.json").write_text(json.dumps(cfg))


def reset(cfg=None):
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    for d in ("brands", "secrets", "outbox", "public_assets"):
        shutil.rmtree(TMP / d, ignore_errors=True)
    (TMP / "brands" / "noord").mkdir(parents=True)
    (TMP / "brands" / "noord" / "compliance.json").write_text(json.dumps({"banned": ["miracle"]}))
    (TMP / "secrets").mkdir()
    (TMP / "public_assets" / "posts").mkdir(parents=True)
    (TMP / "public_assets" / "posts" / "nb-002.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    (TMP / "data.json").write_text(json.dumps(seed(), ensure_ascii=False, indent=1))
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    write_cfg(BASE_CFG if cfg is None else cfg)
    otto_email._rl.clear()
    otto_email._rl_global[:] = [0, 0]


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def outbox():
    d = TMP / "outbox"
    return sorted(d.glob("*.eml")) if d.is_dir() else []


def parse(f):
    return email.message_from_bytes(Path(f).read_bytes(), policy=email.policy.default)


def parts(msg):
    return msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()


def link(text, label):
    m = re.search(rf"^{label}:\s+(\S+)", text, re.M)
    return m.group(1) if m else None


def token_of(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["t"][0]


_SAVED = {}


def setUpModule():
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    global ap, otto_email, otto_api, otto_cron, otto_admin, otto_telegram
    import ap, otto_email, otto_api, otto_cron, otto_admin, otto_telegram     # noqa: E401
    _SAVED["paths"] = (ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG)
    ap.DATA, ap.HTML, ap.BRANDS = TMP / "data.json", TMP / "index.html", TMP / "brands"
    otto_api.LOG = TMP / "actions.log"
    reset()


def tearDownModule():
    ap.DATA, ap.HTML, ap.BRANDS, otto_api.LOG = _SAVED["paths"]
    for k, v in _SAVED["env"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


# ============================================================================================
# tokens
# ============================================================================================

class TokenTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_sign_and_verify(self):
        t = otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW)
        p, secret = otto_email.read_token(t, NOW + timedelta(hours=1))
        self.assertEqual((p["b"], p["k"], p["i"], p["a"]), ("noord", "post", "nb-001", "approve"))
        self.assertEqual(p["e"], int((NOW + timedelta(hours=72)).timestamp()))
        self.assertEqual(secret, SECRET.encode())
        body = base64.urlsafe_b64decode(t.split(".")[0] + "==").decode()
        self.assertNotIn("anna", body, "the address is never in the link, only a keyed hash")
        self.assertEqual(p["r"], otto_email.rcpt_hash(ANNA, SECRET.encode()))
        self.assertNotEqual(otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW), t, "every link has its own nonce")

    def test_tampering_and_garbage_are_invalid(self):
        t = otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW)
        body, sig = t.split(".")
        forged = json.loads(base64.urlsafe_b64decode(body + "=="))
        forged["i"] = "nb-005"
        fb = base64.urlsafe_b64encode(json.dumps(forged, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode()
        for bad in (fb + "." + sig, body + "." + sig[:-2] + ("AA" if not sig.endswith("AA") else "BB"), "", "x" * 50, "a.b",
                    t + "x", body + "." + sig + "." + sig, None):
            with self.assertRaises(otto_email.TokenError, msg=str(bad)[:40]) as cm:
                otto_email.read_token(bad, NOW)
            self.assertEqual(cm.exception.code, "invalid")
        other = otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW, secret=b"z" * 40)
        with self.assertRaises(otto_email.TokenError):
            otto_email.read_token(other, NOW)

    def test_expiry_and_rotation(self):
        t = otto_email.make_token("noord", "post", "nb-001", "skip", ANNA, now=NOW)
        otto_email.read_token(t, NOW + timedelta(hours=71, minutes=59))
        with self.assertRaises(otto_email.TokenError) as cm:
            otto_email.read_token(t, NOW + timedelta(hours=72, seconds=1))
        self.assertEqual(cm.exception.code, "expired")
        write_cfg(dict(BASE_CFG, link_secret="n" * 64, previous_link_secrets=[SECRET]))       # rotated: old links still work
        p, secret = otto_email.read_token(t, NOW)
        self.assertEqual(secret, SECRET.encode())
        write_cfg(dict(BASE_CFG, link_secret="n" * 64))                                         # previous dropped: dead
        with self.assertRaises(otto_email.TokenError):
            otto_email.read_token(t, NOW)

    def test_weak_or_missing_secret(self):
        write_cfg(dict(BASE_CFG, link_secret="short"))
        with self.assertRaises(otto_email.ConfigError):
            otto_email.link_secrets()
        write_cfg({"app_url": "https://app.otto.example/"})                                   # no link_secret: generated once, 600
        k1 = otto_email.link_secrets()[0]
        self.assertEqual(otto_email.link_secrets()[0], k1)
        f = TMP / ".email-link-secret"
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len(k1), 64)

    def test_form_nonce(self):
        t = otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW)
        p, s = otto_email.read_token(t, NOW)
        f = otto_email.form_nonce(p, s, NOW)
        self.assertTrue(otto_email.form_ok(f, p, s, NOW + timedelta(minutes=5)))
        self.assertFalse(otto_email.form_ok(f, p, s, NOW + timedelta(hours=2)), "a page left open for hours asks again")
        p2, _ = otto_email.read_token(otto_email.make_token("noord", "post", "nb-001", "approve", ANNA, now=NOW), NOW)
        self.assertFalse(otto_email.form_ok(f, p2, s, NOW), "bound to its own link")
        self.assertFalse(otto_email.form_ok("", p, s, NOW))
        self.assertFalse(otto_email.form_ok(f.replace(f[-1], "0" if f[-1] != "0" else "1"), p, s, NOW))


# ============================================================================================
# the digest: selection, claim, no double send, rendering
# ============================================================================================

class DigestTest(unittest.TestCase):
    def setUp(self):
        reset()

    def send(self, **kw):
        return quiet(otto_email.send_cards, now=NOW, **kw)

    def test_selection_claim_and_marks(self):
        t = self.send(bid="noord")
        self.assertEqual((t["posts"], t["emails"], t["blocked"], t["failed"]), (2, 2, 1, 0))
        files = outbox()
        self.assertEqual(len(files), 2, "one e-mail per approver; the @domain entry is not mailed")
        self.assertEqual(sorted(parse(f)["To"] for f in files), [ANNA, BRAM])
        d = ap.load()
        for pid in ("nb-001", "nb-002"):
            p = ap.post(d, pid)
            self.assertTrue(p.get("email_sent_at") and p.get("email_digest"), pid)
            self.assertNotIn("email_claim", p)
            self.assertEqual(p["status"], "pending_approval", "sending never decides anything")
        for pid in ("nb-003", "nb-004", "nb-005", "nb-007", "nb-100"):
            self.assertNotIn("email_sent_at", ap.post(d, pid), pid)
        held = ap.post(d, "nb-006")
        self.assertNotIn("email_sent_at", held)
        self.assertEqual(held["compliance_block"]["rules"], ["miracle"])
        self.assertTrue(any(r["title"].startswith("Compliance hold: nb-006") and r["source"] == "otto_email" for r in d["recommendations"]))
        text, _ = parts(parse(files[0]))
        self.assertIn("nb-001", text)
        self.assertIn("nb-002", text)
        self.assertNotIn("nb-006", text)
        st = otto_email.read_state()["brands"]["noord"]["digest"]
        self.assertEqual((st["posts"], st["emails"], st["transport"]), (2, 2, "outbox"))
        # the next run finds nothing new
        t2 = self.send(bid="noord")
        self.assertEqual((t2["posts"], t2["emails"]), (0, 0))
        self.assertEqual(len(outbox()), 2)

    def test_the_claim_is_taken_before_sending(self):
        real, seen = otto_email.deliver, []

        def spy(*a, **kw):
            d = ap.load()
            seen.append({pid: bool(ap.post(d, pid).get("email_claim")) for pid in ("nb-001", "nb-002")})
            return real(*a, **kw)
        otto_email.deliver = spy
        try:
            self.send(bid="noord")
        finally:
            otto_email.deliver = real
        self.assertEqual(seen, [{"nb-001": True, "nb-002": True}] * 2)

    def test_two_runs_at_once_send_each_post_once(self):
        real = otto_email.deliver

        def slow(*a, **kw):
            time.sleep(0.3)
            return real(*a, **kw)
        otto_email.deliver = slow
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                ts = [threading.Thread(target=otto_email.send_cards, kwargs={"bid": "noord", "now": NOW}) for _ in range(2)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join(30)
        finally:
            otto_email.deliver = real
        self.assertEqual(len(outbox()), 2, out.getvalue())
        d = ap.load()
        self.assertEqual(len({ap.post(d, p)["email_digest"] for p in ("nb-001", "nb-002")}), 1)

    def test_a_fresh_claim_blocks_a_stale_one_does_not(self):
        with ap.transaction() as d:
            ap.post(d, "nb-001")["email_claim"] = ap.now_iso()
            ap.post(d, "nb-002")["email_claim"] = "2020-01-01T00:00:00Z"
        self.send(bid="noord")
        text, _ = parts(parse(outbox()[0]))
        self.assertNotIn("nb-001", text)
        self.assertIn("nb-002", text)
        self.assertNotIn("email_sent_at", ap.post(ap.load(), "nb-001"))

    def test_resend_and_ids(self):
        self.send(bid="noord")
        self.send(bid="noord", resend=True, ids={"nb-001"})
        self.assertEqual(len(outbox()), 4)

    def test_channel_plan_and_recipient_rules(self):
        t = self.send()                                                    # every brand: only e-mail brands with a plan
        tos = {parse(f)["To"] for f in outbox()}
        self.assertEqual(tos, {ANNA, BRAM})
        self.assertEqual(t["failed"], 1, "domainonly has nobody to mail")
        self.assertIn("nobody to send to", otto_email.read_state()["brands"]["domainonly"]["error"]["why"])
        d = ap.load()
        for pid in ("ol-001", "ap-001", "la-001", "do-001"):
            self.assertNotIn("email_sent_at", ap.post(d, pid), pid)
            self.assertNotIn("email_claim", ap.post(d, pid), pid)

    def test_approvers_list_and_suppression(self):
        with ap.transaction() as d:
            ap.brand(d, "noord")["approvers"] = ["chef@noord.example", ANNA]
        otto_email.record_bounce(ANNA, "hard", "mailbox unavailable", "postmark", ["noord"])
        self.send(bid="noord")
        self.assertEqual([parse(f)["To"] for f in outbox()], ["chef@noord.example"])
        quiet(otto_email.main, ["unsuppress", ANNA])
        self.assertFalse(otto_email.suppressed(ANNA))

    def test_dry_run_writes_nothing(self):
        before = (TMP / "data.json").read_text()
        self.send(bid="noord", dry=True)
        self.assertEqual(outbox(), [])
        self.assertEqual((TMP / "data.json").read_text(), before)

    def test_logs_mask_addresses(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            otto_email.send_cards(bid="noord", now=NOW)
        self.assertNotIn(ANNA, out.getvalue())
        self.assertIn("a•••@noord.example", out.getvalue())


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset()
        quiet(otto_email.send_cards, bid="noord", now=NOW)
        cls.msg = parse(next(f for f in outbox() if parse(f)["To"] == ANNA))
        cls.text, cls.html = parts(cls.msg)

    def test_both_parts_and_headers(self):
        self.assertEqual(self.msg.get_content_type(), "multipart/alternative")
        self.assertEqual(self.msg["Auto-Submitted"], "auto-generated")
        self.assertIn("Noordzee Bakery", self.msg["Subject"])
        self.assertIn("2 posts to approve", self.msg["Subject"])
        self.assertTrue(self.msg["Message-ID"])
        self.assertIn("Approve:", self.text)
        self.assertIn("Review all in the app: https://app.otto.example/#review", self.text)

    def test_links_are_absolute_and_tokens_are_per_button(self):
        hrefs = re.findall(r'href="([^"]+)"', self.html)
        self.assertTrue(hrefs)
        for h in hrefs:
            self.assertTrue(h.startswith("https://"), h)
        acts = [h for h in hrefs if "/otto-email/act?t=" in h]
        self.assertEqual(len(acts), 4, "Approve + Skip for each of two posts")
        self.assertEqual(len(set(acts)), 4)
        self.assertIn("https://app.otto.example/#change=nb-001", hrefs)
        self.assertIn("https://app.otto.example/#review", hrefs)
        self.assertIn("https://app.otto.example/#settings", hrefs)
        self.assertEqual(link(self.text, "Change"), "https://app.otto.example/#change=nb-001")
        tok = token_of(link(self.text, "Approve"))
        p, _ = otto_email.read_token(tok, NOW)
        self.assertEqual((p["i"], p["a"]), ("nb-001", "approve"))

    def test_no_tracking_no_script_no_web_fonts(self):
        imgs = re.findall(r"<img\b[^>]*>", self.html)
        srcs = [re.search(r'src="([^"]+)"', i).group(1) for i in imgs]
        self.assertEqual(sorted(srcs), ["https://otto.example/assets/posts/nb-001.jpg", "https://otto.example/assets/posts/nb-002.jpg"],
                         "only the posts' own hosted images — the same URL for every reader, no pixel")
        for i in imgs:
            self.assertNotRegex(i, r'width="1"|height="1"')
        low = self.html.lower()
        for bad in ("<script", "<link", "@import", "fonts.googleapis", "@font-face", "cid:", "data:image"):
            self.assertNotIn(bad, low)
        self.assertEqual(self.msg.get_content_maintype(), "multipart")
        self.assertFalse(any(p.get_content_disposition() == "attachment" for p in self.msg.walk()), "no attachments")

    def test_layout_works_across_clients(self):
        self.assertIn('role="presentation"', self.html)
        self.assertIn("prefers-color-scheme:dark", self.html)
        self.assertIn('<meta name="color-scheme" content="light dark">', self.html)
        self.assertIn("[data-ogsc]", self.html, "Outlook.com dark mode")
        self.assertIn("<!--[if mso]>", self.html)
        self.assertLess(len(self.html.encode()), 102_000, "Gmail clips messages over ~102 KB")

    def test_slot_in_brand_local_time_and_escaping(self):
        self.assertIn("Fri 2 Oct · 18:00", self.html)                   # naive slot = Amsterdam time
        self.assertIn("Sat 3 Oct · 09:00", self.html)                   # 07:00Z shown as Amsterdam 09:00
        self.assertIn("Amsterdam time", self.html)
        self.assertIn("That&#x27;s the whole recipe.", self.html)
        self.assertIn("Instagram", self.html)
        self.assertIn("Facebook · Reel", self.html)
        self.assertIn("Why this post: Sourdough posts get the most saves", self.html)

    def test_recs_and_plan_render(self):
        b = ap.brand(ap.load(), "noord")
        r = ap.rec(ap.load(), "rec-001")
        subj, h, t = otto_email.render_plan(b, r, [c for c in ap.load()["campaigns"]], [("Approve plan", "https://otto.example/otto-email/act?t=x", True, 60)])
        self.assertEqual(subj, "Approve the November paid plan · Noordzee Bakery")
        self.assertIn("Evergreen · bread", h)
        self.assertIn("€15/day", h)
        self.assertIn("Approve plan: https://otto.example/otto-email/act?t=x", t)


# ============================================================================================
# the one-tap page: GET never acts, POST decides
# ============================================================================================

class ActTest(unittest.TestCase):
    def setUp(self):
        reset()

    def tok(self, item="nb-100", action="approve", who=ANNA, brand="noord", kind="post", now=NOW):
        return otto_email.make_token(brand, kind, item, action, who, now=now)

    def get(self, t, now=None, ip="10.0.0.1"):
        return otto_email.http_act("GET", t, None, ip, True, now or NOW + timedelta(hours=1))

    def post(self, t, form=None, now=None, ip="10.0.0.1", origin_ok=True):
        now = now or NOW + timedelta(hours=1)
        if form is None:
            code, h, _, _ = self.get(t, now, ip)
            m = re.search(r'name="f" value="([^"]+)"', h)
            form = m.group(1) if m else ""
        return otto_email.http_act("POST", t, form, ip, origin_ok, now)

    def test_get_never_acts(self):
        t = self.tok()
        before = (TMP / "data.json").read_text()
        for _ in range(3):                                                  # a mail scanner prefetching the link
            code, h, csp, line = self.get(t)
            self.assertEqual(code, 200)
            self.assertIsNone(line)
        self.assertEqual((TMP / "data.json").read_text(), before)
        self.assertEqual(otto_email.read_state().get("used") or {}, {})
        self.assertIn('<form method="post">', h)
        self.assertIn(">Approve post</button>", h)
        self.assertIn("Hook nb-100", h)
        self.assertNotIn("<script", h.lower())
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("script-src", csp)
        self.assertIn('http-equiv="Content-Security-Policy"', h)

    def test_post_applies_through_decide_with_via_email(self):
        t = self.tok()
        code, h, _, line = self.post(t)
        self.assertEqual(code, 200, h)
        self.assertIn("Approved", h)
        self.assertEqual(line, "email post nb-100 -> approve by a•••@noord.example (noord)")
        d = ap.load()
        p = ap.post(d, "nb-100")
        self.assertEqual((p["status"], p["approved_via"]), ("approved", "email"))
        self.assertEqual(d["taste_log"][-1], dict(d["taste_log"][-1], post="nb-100", decision="approve", via="email", brand="noord"))
        used = otto_email.read_state()["used"]
        self.assertEqual(len(used), 1)
        # replay: the same link, POST or GET, is spent
        code, h, _, line = self.post(t, form=otto_email.form_nonce(otto_email.read_token(t, NOW)[0], SECRET.encode(), NOW + timedelta(hours=1)))
        self.assertEqual(code, 409)
        self.assertIn("already used", h)
        self.assertIsNone(line)
        self.assertEqual(self.get(t)[0], 409)
        self.assertEqual(len(ap.load()["taste_log"]), 1)

    def test_skip_and_transitions(self):
        code, h, _, _ = self.post(self.tok(action="skip"))
        self.assertEqual(code, 200)
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "skipped")
        t = self.tok(action="approve")                                      # the Approve button of the same e-mail, later
        code, h, _, _ = self.get(t)
        self.assertEqual(code, 409)
        self.assertIn("already skipped", h)
        self.assertNotIn("<form", h)
        f = otto_email.form_nonce(otto_email.read_token(t, NOW)[0], SECRET.encode(), NOW + timedelta(hours=1))
        code, h, _, _ = self.post(t, form=f)                                # even a hand-made POST
        self.assertEqual(code, 409)
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "skipped")
        code, h, _, _ = self.get(self.tok(item="nb-101"))                  # published: never touched from an e-mail
        self.assertEqual(code, 409)
        self.assertIn("already published", h)
        code, _, _, _ = otto_email.http_act("POST", self.tok(item="nb-101"),
                                            otto_email.form_nonce(otto_email.read_token(self.tok(item="nb-101"), NOW)[0], SECRET.encode(), NOW),
                                            "10.0.0.2", True, NOW)
        self.assertEqual(ap.post(ap.load(), "nb-101")["status"], "published")

    def test_post_needs_the_form_nonce_and_our_origin(self):
        t = self.tok()
        for form in ("", "123.abc", "9999999999." + "0" * 32):
            code, h, _, _ = self.post(t, form=form)
            self.assertEqual(code, 400, form)
        code, _, _, _ = self.post(t, origin_ok=False)
        self.assertEqual(code, 403)
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "pending_approval")
        self.assertEqual(otto_email.read_state().get("used") or {}, {})

    def test_expired_invalid_and_calm_pages(self):
        t = self.tok()
        code, h, _, _ = self.get(t, now=NOW + timedelta(hours=73))
        self.assertEqual(code, 410)
        self.assertIn("This link has expired", h)
        self.assertIn('href="https://app.otto.example/#review"', h)
        code, h, _, _ = self.get("not-a-token")
        self.assertEqual(code, 400)
        self.assertIn("doesn&#x27;t work", h)
        code, h, _, _ = self.post(t, form="x", now=NOW + timedelta(hours=73))
        self.assertEqual(code, 410)

    def test_wrong_brand_and_removed_recipient(self):
        forged = self.tok(item="ol-001")                                    # noord's link naming another brand's post
        self.assertEqual(self.get(forged)[0], 403)
        self.assertEqual(self.post(forged, form="1.2")[0], 400)
        cross = otto_email.make_token("old", "post", "nb-100", "approve", "olga@oldmill.example", now=NOW)
        self.assertEqual(self.get(cross)[0], 403)
        t = self.tok()
        with ap.transaction() as d:
            ap.brand(d, "noord")["members"] = [BRAM]
        code, h, _, _ = self.get(t)
        self.assertEqual(code, 403)
        self.assertIn("can&#x27;t be used any more", h)
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "pending_approval")
        stranger = self.tok(who="eve@evil.example")
        self.assertEqual(self.get(stranger)[0], 403)

    def test_digest_link_end_to_end(self):
        quiet(otto_email.send_cards, bid="noord", now=NOW)
        text, _ = parts(parse(next(f for f in outbox() if parse(f)["To"] == BRAM)))
        code, h, _, line = self.post(token_of(link(text, "Approve")))
        self.assertEqual(code, 200, h)
        self.assertIn("It goes out Fri 2 Oct · 18:00", h)
        self.assertIn("b•••@noord.example", line)
        self.assertEqual(ap.post(ap.load(), "nb-001")["approved_via"], "email")

    def test_paid_plan_card_runs_the_same_action_as_telegram(self):
        t = self.tok(item="rec-001", kind="rec")
        code, h, _, _ = self.get(t)
        self.assertEqual(code, 200)
        self.assertIn("Nothing spends until you approve", h)
        code, h, _, line = quiet(self.post, t)
        self.assertEqual(code, 200, h)
        d = ap.load()
        r = ap.rec(d, "rec-001")
        self.assertEqual((r["status"], r["approved_via"]), ("done", "email"))
        self.assertIn("2 campaign(s) approved for November", r["action_result"])
        self.assertEqual({(c["status"], c["approved_via"]) for c in d["campaigns"]}, {("approved", "email")})
        self.assertIn("campaign(s) approved", line)

    def test_rec_dismiss_and_visibility(self):
        code, _, _, _ = self.post(self.tok(item="rec-002", kind="rec", action="dismiss"))
        self.assertEqual(code, 200)
        r = ap.rec(ap.load(), "rec-002")
        self.assertEqual((r["status"], r["approved_via"]), ("dismissed", "email"))
        self.assertEqual(self.get(self.tok(item="rec-004", kind="rec"))[0], 403, "an owner-only card is not the client's")
        self.assertEqual(self.get(self.tok(item="rec-005", kind="rec"))[0], 403)
        with self.assertRaises(otto_email.TokenError):
            otto_email.read_token(self.tok(item="rec-002", kind="rec", action="skip"), NOW)   # posts' actions only on posts

    def test_rate_limit(self):
        t = self.tok()
        codes = [self.get(t, ip="10.9.9.9")[0] for _ in range(otto_email.RATE_PER_MIN + 2)]
        self.assertEqual(codes[:otto_email.RATE_PER_MIN], [200] * otto_email.RATE_PER_MIN)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.get(t, ip="10.9.9.10")[0], 200, "per client")


class HttpRouteTest(unittest.TestCase):
    """The routes in otto_api, over a real socket (tokens on the real clock here)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), otto_api.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        reset()

    def req(self, path, method="GET", body=None, headers=None):
        r = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=15) as x:
                return x.status, dict(x.headers), x.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def test_get_then_post(self):
        t = otto_email.make_token("noord", "post", "nb-100", "approve", ANNA)
        code, hdrs, h = self.req("/otto-email/act?t=" + t)
        self.assertEqual(code, 200)
        self.assertTrue(hdrs["Content-Type"].startswith("text/html"))
        self.assertEqual(hdrs["Cache-Control"], "no-store")
        self.assertEqual(hdrs["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", hdrs["Content-Security-Policy"])
        self.assertIn("noindex", hdrs["X-Robots-Tag"])
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "pending_approval")
        f = re.search(r'name="f" value="([^"]+)"', h).group(1)
        form = urllib.parse.urlencode({"t": t, "f": f}).encode()
        code, _, _ = self.req("/otto-email/act", "POST", form, {"Content-Type": "application/json", "Origin": "https://otto.example"})
        self.assertEqual(code, 415)
        code, _, _ = self.req("/otto-email/act", "POST", form, {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(ap.post(ap.load(), "nb-100")["status"], "pending_approval")
        code, _, h = self.req("/otto-email/act?t=" + t, "POST", form, {"Content-Type": "application/x-www-form-urlencoded",
                                                                        "Origin": "https://otto.example"})
        self.assertEqual(code, 200, h)
        self.assertEqual(ap.post(ap.load(), "nb-100")["approved_via"], "email")
        self.assertIn("email post nb-100 -> approve by a•••@noord.example", (TMP / "actions.log").read_text())
        code, _, _ = self.req("/otto-email/act", "POST", form, {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://otto.example"})
        self.assertEqual(code, 409)

    def test_bad_requests(self):
        self.assertEqual(self.req("/otto-email/act")[0], 400)
        self.assertEqual(self.req("/otto-email/act?t=abc")[0], 400)
        code, _, _ = self.req("/otto-email/act", "POST", b"t=" + b"x" * 5000, {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 413)

    def test_settings_action_is_tenant_scoped(self):
        origin = sorted(otto_api.ALLOWED_ORIGINS)[0]
        client = {"Content-Type": "application/json", "Origin": origin, "X-Real-IP": "203.0.113.9", "X-Otto-User": ANNA}
        body = lambda **kw: json.dumps(dict({"kind": "brand"}, **kw)).encode()
        code, _, out = self.req("/otto-api/action", "POST", body(id="noord", approvals="telegram"), client)
        self.assertEqual(code, 200, out)
        j = json.loads(out)
        self.assertEqual([b["approvals"] for b in j["data"]["brands"]], ["telegram"])
        self.assertNotIn("members", j["data"]["brands"][0])
        self.assertEqual(ap.brand(ap.load(), "noord")["approvals_set"]["via"], "dashboard")
        self.assertIn("dashboard brand noord approvals email -> telegram", (TMP / "actions.log").read_text())
        self.assertEqual(self.req("/otto-api/action", "POST", body(id="old", approvals="email"), client)[0], 404)
        self.assertNotIn("approvals", ap.brand(ap.load(), "old"))
        for bad in ("fax", ["email", "app"], [], 7, None):
            self.assertEqual(self.req("/otto-api/action", "POST", body(id="noord", approvals=bad), client)[0], 400, bad)
        code, _, _ = self.req("/otto-api/action", "POST", body(id="noord", approvals=["telegram", "email"]), client)
        self.assertEqual(code, 200)
        self.assertEqual(ap.brand(ap.load(), "noord")["approvals"], ["email", "telegram"])
        code, _, _ = self.req("/otto-api/action", "POST", body(id="noord", approvals="app"), dict(client, Origin="https://evil.example"))
        self.assertEqual(code, 403)


# ============================================================================================
# recommendations by e-mail
# ============================================================================================

class RecsTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_plan_card_and_recs(self):
        t = quiet(otto_email.send_recs, bid="noord", now=NOW)
        self.assertEqual((t["recs"], t["emails"]), (2, 4), "a plan e-mail + a recommendations e-mail, to each of two approvers")
        subjects = sorted({parse(f)["Subject"] for f in outbox()})
        self.assertEqual(subjects, ["Approve the November paid plan · Noordzee Bakery", "Otto recommends: Share the bake-off results"])
        d = ap.load()
        for rid in ("rec-001", "rec-002"):
            self.assertTrue(ap.rec(d, rid).get("email_sent_at"), rid)
        for rid in ("rec-003", "rec-004", "rec-005", "rec-006"):
            self.assertNotIn("email_sent_at", ap.rec(d, rid), rid)
        plan = parse(next(f for f in outbox() if "paid plan" in parse(f)["Subject"] and parse(f)["To"] == ANNA))
        text, h = parts(plan)
        p, _ = otto_email.read_token(token_of(link(text, "Approve plan")), NOW)
        self.assertEqual((p["k"], p["i"], p["a"]), ("rec", "rec-001", "approve"))
        p, _ = otto_email.read_token(token_of(link(text, "Not now")), NOW)
        self.assertEqual(p["a"], "dismiss")
        self.assertIn("Boost · sourdough", h)
        self.assertEqual(quiet(otto_email.send_recs, bid="noord", now=NOW)["emails"], 0, "sent once")

    def test_onboarding_steps_open_the_app(self):
        with ap.transaction() as d:
            ap.rec(d, "rec-002")["onboard_step"] = "meta"
        quiet(otto_email.send_recs, bid="noord", now=NOW)
        text, _ = parts(parse(next(f for f in outbox() if "recommends" in parse(f)["Subject"])))
        self.assertIn("Open Otto: https://app.otto.example/#settings", text)
        self.assertIsNone(link(text, "Approve"))


# ============================================================================================
# transports
# ============================================================================================

class _SMTPHandler(socketserver.BaseRequestHandler):
    sock = None

    def handle(self):
        try:
            self._handle()
        finally:
            if self.sock is not self.request:
                self.sock.close()

    def _handle(self):
        srv, self.sock = self.server, self.request
        f, tls, data_mode, buf = self.sock.makefile("rb"), False, False, []
        self.say("220 fake.local ESMTP")
        while True:
            line = f.readline()
            if not line:
                return
            if data_mode:
                if line in (b".\r\n", b".\n"):
                    srv.messages.append({"tls": tls, "data": b"".join(buf)})
                    data_mode, buf = False, []
                    self.say("250 queued")
                else:
                    buf.append(line[1:] if line.startswith(b"..") else line)
                continue
            cmd = line.decode(errors="replace").strip()
            up = cmd.upper()
            srv.log.append((tls, up.split()[0] if up else ""))
            if up.startswith(("EHLO", "HELO")):
                ext = ["fake.local"] + (["STARTTLS"] if srv.tls_ctx and not tls else []) + ["AUTH PLAIN LOGIN", "SIZE 1000000"]
                for i, e in enumerate(ext):
                    self.say(("250 " if i == len(ext) - 1 else "250-") + e)
            elif up == "STARTTLS" and srv.tls_ctx:
                self.say("220 go ahead")
                self.sock = srv.tls_ctx.wrap_socket(self.sock, server_side=True)
                f, tls = self.sock.makefile("rb"), True
            elif up.startswith("AUTH PLAIN"):
                srv.auth.append({"tls": tls, "cred": base64.b64decode(cmd.split()[2]).split(b"\0")})
                self.say("235 ok")
            elif up.startswith("MAIL FROM"):
                self.say("250 ok")
            elif up.startswith("RCPT TO"):
                self.say("550 no such user" if "refuse" in cmd else "250 ok")
            elif up == "DATA":
                data_mode = True
                self.say("354 go")
            elif up == "QUIT":
                self.say("221 bye")
                return
            else:
                self.say("250 ok" if up == "RSET" or up == "NOOP" else "502 no")

    def say(self, s):
        self.sock.sendall((s + "\r\n").encode())


class FakeSMTP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, tls_ctx=None):
        super().__init__(("127.0.0.1", 0), _SMTPHandler)
        self.tls_ctx, self.log, self.auth, self.messages = tls_ctx, [], [], []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


class TransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certs = TMP.parent / (TMP.name + "-certs")
        cls.certs.mkdir(exist_ok=True)
        try:
            r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cls.certs / "key.pem"),
                                "-out", str(cls.certs / "cert.pem"), "-days", "2", "-subj", "/CN=127.0.0.1",
                                "-addext", "subjectAltName=IP:127.0.0.1"], capture_output=True, timeout=60)
            cls.have_tls = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            cls.have_tls = False

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.certs, ignore_errors=True)

    def setUp(self):
        reset()

    def smtp_cfg(self, srv, **kw):
        return dict(BASE_CFG, host="127.0.0.1", port=srv.server_address[1], user="otto", **{"pass": "LEAKCHECK-pass"},
                    **{"from": "Otto <approvals@otto.example>"}, **kw)

    def test_outbox_when_nothing_is_configured(self):
        write_cfg(BASE_CFG)
        self.assertEqual(otto_email.transport(), "outbox")
        out = otto_email.deliver(ANNA, "Hi", "<p>hi</p>", "hi", "digest", "noord")
        f = Path(out["path"])
        self.assertEqual(f.parent, TMP / "outbox")
        self.assertEqual(f.stat().st_mode & 0o777, 0o600, "the file holds working links")
        self.assertEqual(f.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(parse(f)["To"], ANNA)
        h = otto_email.health()
        self.assertEqual((h["transport"], h["outbox"]["files"]), ("outbox", 1))

    def test_smtp_starttls_is_used_before_the_login(self):
        if not self.have_tls:
            self.skipTest("openssl not available to make a throwaway certificate")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.certs / "cert.pem"), str(self.certs / "key.pem"))
        srv = FakeSMTP(ctx)
        self.addCleanup(srv.stop)
        write_cfg(self.smtp_cfg(srv, ca_file=str(self.certs / "cert.pem")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            t = otto_email.send_cards(bid="noord", now=NOW)
        self.assertEqual(t["emails"], 2, out.getvalue())
        self.assertEqual(len(srv.messages), 2)
        self.assertTrue(all(m["tls"] for m in srv.messages))
        self.assertEqual([a["tls"] for a in srv.auth], [True, True], "credentials only after STARTTLS")
        self.assertEqual(srv.auth[0]["cred"][1:], [b"otto", b"LEAKCHECK-pass"])
        msg = email.message_from_bytes(srv.messages[0]["data"], policy=email.policy.default)
        text, h = parts(msg)
        self.assertIn("/otto-email/act?t=", text)
        self.assertIn("<!doctype html>", h)
        self.assertNotIn("LEAKCHECK", out.getvalue())
        self.assertNotIn(ANNA, out.getvalue())
        self.assertEqual(outbox(), [])

    def test_smtp_without_starttls_is_refused(self):
        srv = FakeSMTP(None)
        self.addCleanup(srv.stop)
        cfg = self.smtp_cfg(srv)
        with self.assertRaises(otto_email.SendError) as cm:
            otto_email.deliver(ANNA, "Hi", "<p>hi</p>", "hi", "digest", "noord", cfg)
        self.assertIn("STARTTLS", str(cm.exception))
        self.assertEqual(srv.auth, [])
        self.assertEqual(srv.messages, [])
        self.assertNotIn("AUTH", [c for _, c in srv.log])
        write_cfg(cfg)
        t = quiet(otto_email.send_cards, bid="noord", now=NOW)
        self.assertEqual((t["emails"], t["failed"]), (0, 1))
        d = ap.load()
        self.assertNotIn("email_sent_at", ap.post(d, "nb-001"))
        self.assertNotIn("email_claim", ap.post(d, "nb-001"), "a failed send gives the claim back")
        self.assertIn("STARTTLS", otto_email.read_state()["brands"]["noord"]["error"]["why"])
        self.assertEqual(quiet(otto_email.main, ["send-cards", "--brand", "noord"]), 1, "the cron job fails, so it alerts")

    def test_smtp_refused_recipient_is_a_bounce(self):
        if not self.have_tls:
            self.skipTest("openssl not available")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.certs / "cert.pem"), str(self.certs / "key.pem"))
        srv = FakeSMTP(ctx)
        self.addCleanup(srv.stop)
        cfg = self.smtp_cfg(srv, ca_file=str(self.certs / "cert.pem"))
        with ap.transaction() as d:
            ap.brand(d, "noord")["members"] = ["refuse@noord.example", ANNA]
        write_cfg(cfg)
        t = quiet(otto_email.send_cards, bid="noord", now=NOW)
        self.assertEqual((t["emails"], t["failed"]), (1, 0), "a bounce is not an outage")
        self.assertTrue(otto_email.suppressed("refuse@noord.example"))
        b = otto_email.health()["bounces"][0]
        self.assertEqual((b["to"], b["type"]), ("r•••@noord.example", "hard"))

    def test_http_providers_turn_tracking_off(self):
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, dict(self.headers), body))
                out = {"MessageID": "pm-1", "ErrorCode": 0} if self.path == "/email" else {"id": "rs-1"}
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                out = ({"TotalCount": 1, "Bounces": [{"Email": BRAM, "Type": "HardBounce", "Inactive": True, "Description": "gone"}]}
                       if self.path.startswith("/bounces") else {"last_event": "bounced"})
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        api = f"http://127.0.0.1:{srv.server_address[1]}"
        pm = dict(BASE_CFG, provider="postmark", api_key="pm-LEAKCHECK", api_base=api, **{"from": "Otto <approvals@otto.example>"})
        out = otto_email.deliver(ANNA, "Hi", "<p>hi</p>", "hi", "digest", "noord", pm)
        self.assertEqual((out["transport"], out["id"]), ("postmark", "pm-1"))
        path, hdrs, body = seen[-1]
        self.assertEqual(path, "/email")
        self.assertEqual(hdrs["X-Postmark-Server-Token"], "pm-LEAKCHECK")
        self.assertEqual((body["TrackOpens"], body["TrackLinks"], body["To"]), (False, "None", ANNA))
        self.assertEqual((body["HtmlBody"], body["TextBody"]), ("<p>hi</p>", "hi"))
        write_cfg(pm)
        self.assertEqual(otto_email.sync_bounces(), 1)
        self.assertTrue(otto_email.suppressed(BRAM))
        rs = dict(BASE_CFG, provider="resend", api_key="re-LEAKCHECK", api_base=api, **{"from": "Otto <approvals@otto.example>"})
        write_cfg(rs)
        out = quiet(otto_email.deliver, ANNA, "Hi", "<p>hi</p>", "hi", "digest", "noord")
        self.assertEqual((out["transport"], out["id"]), ("resend", "rs-1"))
        self.assertEqual(seen[-1][1]["Authorization"], "Bearer re-LEAKCHECK")
        self.assertEqual(seen[-1][2]["to"], [ANNA])

    def test_config_errors(self):
        for cfg, why in (({"provider": "postmark", "from": "a@b.example"}, "api_key"), ({"provider": "pigeon"}, "unknown provider"),
                         ({"host": "smtp.example", "from": "a@b.example", "tls": "none"}, "plain SMTP"),
                         ({"host": "smtp.example"}, "from"), ({"provider": "smtp"}, "host")):
            with self.assertRaises(otto_email.ConfigError, msg=cfg) as cm:
                otto_email.transport(cfg)
            self.assertIn(why, str(cm.exception))
        (TMP / "secrets" / "email.json").write_text("{not json")
        with self.assertRaises(otto_email.ConfigError):
            otto_email.config()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(quiet(otto_email.main, ["send-cards"]), 2)


# ============================================================================================
# cron, Telegram, console, channel values
# ============================================================================================

class ChannelTest(unittest.TestCase):
    def test_channel_values(self):
        C = otto_email.approval_channels
        self.assertEqual(C({}), ["telegram"], "a brand from before e-mail approvals keeps Telegram")
        self.assertEqual(C({"approvals": "email"}), ["email"])
        self.assertEqual(C({"approvals": "app"}), [])
        self.assertEqual(C({"approvals": ["telegram", "email", "email"]}), ["email", "telegram"])
        self.assertEqual(C({"approvals": "fax"}), [])
        N = otto_email.normalize_approvals
        self.assertEqual((N("Email"), N(["email"]), N(["telegram", "email"]), N("email,telegram")),
                         ("email", "email", ["email", "telegram"], ["email", "telegram"]))
        for bad in ("fax", ["email", "app"], [], None, 3, {"a": 1}):
            with self.assertRaises(ValueError, msg=bad):
                N(bad)
        self.assertEqual(otto_email.recipients({"members": ["A@X.example", "@x.example", "bad", "a@x.example"]}), ["a@x.example"])
        self.assertEqual(otto_email.recipients({"members": ["a@x.example"], "approvers": []}), [])


class CronTest(unittest.TestCase):
    def setUp(self):
        reset()

    def plan(self, job):
        return {t.brand: t for t in otto_cron.plan(job, ap.load(), NOW, TMP / "brands", force=True)[0]}

    def test_gating_by_channel_and_plan(self):
        e = self.plan("email-cards")
        self.assertEqual([Path(e["noord"].argv[1]).name] + e["noord"].argv[2:], ["otto_email.py", "send-cards", "--brand", "noord"])
        self.assertEqual(e["old"].skip, "approvals by telegram (brands[].approvals)")
        self.assertEqual(e["appy"].skip, "approvals in the app only (brands[].approvals)")
        self.assertEqual(e["lapsed"].skip, "no active plan (membership ended)")
        r = self.plan("email-recs")
        self.assertEqual(r["noord"].argv[2:], ["send-recs", "--brand", "noord"])
        self.assertEqual(r["old"].skip, "approvals by telegram (brands[].approvals)")
        c = self.plan("cards")
        self.assertIsNone(c["old"].skip, "Telegram cards unchanged for a brand without the field")
        self.assertEqual(c["noord"].skip, "approvals by email (brands[].approvals)")
        self.assertEqual(c["appy"].skip, "approvals in the app only (brands[].approvals)")

    def test_local_clock(self):
        todo, not_due = otto_cron.plan("email-cards", ap.load(), NOW, TMP / "brands")          # 08:00 Amsterdam, 07:00 Dublin
        self.assertIn("noord", {t.brand for t in todo})
        self.assertIn("later today", not_due["old"])
        todo, not_due = otto_cron.plan("email-recs", ap.load(), NOW.replace(hour=16, minute=30), TMP / "brands")
        self.assertIn("noord", {t.brand for t in todo})

    def test_telegram_send_cards_skips_email_brands(self):
        import datetime as dtmod

        class Fixed(dtmod.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW if tz else NOW.replace(tzinfo=None)
        saved = otto_telegram.datetime
        otto_telegram.datetime = Fixed
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                otto_telegram.send_cards(dry=True)
        finally:
            otto_telegram.datetime = saved
        self.assertIn("WOULD SEND ol-001", out.getvalue())
        for pid in ("nb-001", "ap-001", "do-001"):
            self.assertNotIn(pid, out.getvalue())


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_snapshot_fields(self):
        write_cfg(dict(BASE_CFG, **{"pass": "LEAKCHECK"}))
        quiet(otto_email.send_cards, bid="noord", now=NOW)
        otto_email.record_bounce(BRAM, "hard", "gone", "postmark", ["noord"])
        s = otto_admin.snapshot()
        blob = json.dumps(s, ensure_ascii=False)
        self.assertNotIn("LEAKCHECK", blob)
        self.assertNotIn(SECRET, blob)
        B = {b["id"]: b for b in s["brands"]}
        a = B["noord"]["approvals"]
        self.assertEqual((a["label"], a["channels"], a["recipients"]), ("Email", ["email"], 2))
        self.assertEqual(a["to"], ["a•••@noord.example", "b•••@noord.example"])
        self.assertEqual((a["last_digest"]["posts"], a["last_digest"]["emails"]), (2, 2))
        self.assertEqual((a["outbox"]["files"], a["bounces"][0]["to"]), (2, "b•••@noord.example"))
        self.assertNotIn(ANNA, json.dumps(a))
        self.assertTrue(any("outbox" in i for i in B["noord"]["issues"]))
        self.assertTrue(any("bounced" in i for i in B["noord"]["issues"]))
        self.assertEqual(B["old"]["approvals"]["label"], "Telegram")
        self.assertFalse(B["old"]["approvals"]["set"])
        self.assertEqual(B["appy"]["approvals"]["label"], "App only")
        self.assertTrue(any("nobody to send to" in i for i in B["domainonly"]["issues"]))
        setup = next(x for x in s["setup"] if x["key"] == "email")
        self.assertEqual(setup["status"], "missing")
        self.assertIn("outbox (2 waiting)", setup["detail"])

    def test_admin_page_shows_the_block(self):
        html = (PLATFORM / "admin.html").read_text()
        for needle in ("function approvalsH(b)", "${approvalsH(b)}", "function apprChip(b)"):
            self.assertIn(needle, html)
        app = (PLATFORM / "index.html").read_text()
        for needle in ('kind: "brand", id: bid, approvals: v', "function approvalsGroup(B)", "#(post|change)="):
            self.assertIn(needle, app)


if __name__ == "__main__":
    unittest.main()
