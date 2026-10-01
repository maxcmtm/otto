#!/usr/bin/env python3
"""Otto's own ad measurement (otto_track → Meta Conversions API) and the landing's consent banner (assets/consent.js).

The rule under test: an event reaches Meta only when $OTTO_SECRETS/meta-capi.json has a pixel id and a token AND the
visitor pressed Accept (cookie otto_consent=v1.granted) AND the browser sends no DNT / GPC signal — and then only the
allowlisted, hashed fields, never the scanned domain. Meta is a fake Graph endpoint on 127.0.0.1; nothing leaves the box.

  cd platform && python3 -m unittest discover -s tests -p test_capi.py
"""
import hashlib, http.server, json, os, re, sys, tempfile, threading, time, unittest, urllib.parse
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM))
import otto_track  # noqa: E402

ORIGIN = "https://otto.example"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
FBC = "fb.1.1790000000000.IwAR0abcdefghijklmnopqrstuvwxyz"
PIXEL, TOKEN = "123456789012345", "EAAtest" + "x" * 40


class FakeGraph:
    """A stand-in for graph.facebook.com that records every POST."""

    def __init__(self, status=200):
        self.calls, self.status = [], status
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.calls.append({"path": self.path, "body": self.rfile.read(n).decode(), "ctype": self.headers.get("Content-Type")})
                out = json.dumps({"events_received": 1} if outer.status == 200 else
                                 {"error": {"message": "Invalid OAuth access token", "code": 190}}).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v25.0"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def forms(self):
        return [urllib.parse.parse_qs(c["body"]) for c in self.calls]


def beacon(*events, anon=False):
    body = {"p": "/", "s": "abc12345", "ev": list(events) or [{"e": "view"}]}
    if anon:
        body["anon"] = 1
    return json.dumps(body).encode()


SCAN = ({"e": "view"}, {"e": "scroll", "d": 50}, {"e": "scan_start", "domain": "https://www.bakkerij-jansen.nl/"},
        {"e": "scan_result", "domain": "bakkerij-jansen.nl", "ok": True}, {"e": "cta", "id": "get_started@pricing"})


class CapiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="otto-capi-test-"))
        self.env = {k: os.environ.get(k) for k in ("OTTO_SECRETS", "OTTO_EVENTS", "OTTO_EVENTS_MAX_MB")}
        os.environ["OTTO_SECRETS"] = str(self.tmp / "secrets")
        os.environ["OTTO_EVENTS"] = str(self.tmp / "events.jsonl")
        os.environ.pop("OTTO_EVENTS_MAX_MB", None)
        (self.tmp / "secrets").mkdir()
        otto_track._buckets.clear()
        otto_track._global[:] = [float(otto_track.GLOBAL_PER_MIN), time.time()]
        otto_track._salt.update(day=None, salt=None)
        otto_track._capi_cache.update(key=None, cfg=None)
        self.graph = FakeGraph()
        self.orig_graph = otto_track.CAPI_GRAPH
        otto_track.CAPI_GRAPH = self.graph.url

    def tearDown(self):
        otto_track.capi_join()
        otto_track.CAPI_GRAPH = self.orig_graph
        self.graph.close()
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def config(self, **over):
        cfg = dict({"pixel_id": PIXEL, "access_token": TOKEN, "test_event_code": "TEST12345"}, **over)
        (self.tmp / "secrets" / "meta-capi.json").write_text(json.dumps(cfg))
        otto_track._capi_cache.update(key=None, cfg=None)

    def send(self, body, cookie=None, **extra):
        h = {"User-Agent": UA, "Origin": ORIGIN, "X-Country": "NL"}
        if cookie is not None:
            h["Cookie"] = cookie
        h.update(extra)
        code, _ = otto_track.ingest(body, "203.0.113.7", h)
        otto_track.capi_join()
        return code

    # ---- no call unless configured AND consented ----

    def test_no_config_file_no_call(self):
        self.assertIsNone(otto_track.capi_config())
        self.assertEqual(self.send(beacon(*SCAN), "otto_consent=v1.granted"), 204)
        self.assertEqual(self.graph.calls, [])

    def test_empty_pixel_id_is_off(self):
        self.config(pixel_id="")
        self.assertIsNone(otto_track.capi_config())
        self.send(beacon(*SCAN), "otto_consent=v1.granted")
        self.config(pixel_id="12345; DROP", access_token=TOKEN)          # malformed: off, never a request to a made-up path
        self.assertIsNone(otto_track.capi_config())
        self.config(access_token="")
        self.assertIsNone(otto_track.capi_config())
        self.send(beacon(*SCAN), "otto_consent=v1.granted")
        (self.tmp / "secrets" / "meta-capi.json").write_text("{not json")
        otto_track._capi_cache.update(key=None, cfg=None)
        self.assertIsNone(otto_track.capi_config())
        self.send(beacon(*SCAN), "otto_consent=v1.granted")
        self.assertEqual(self.graph.calls, [])

    def test_no_consent_no_call(self):
        self.config()
        for cookie in (None, "", "otto_consent=v1.denied", "otto_consent=granted", "otto_consent=v2.granted",
                       "other=1; otto_consent=v1.granted-ish", "xotto_consent=v1.granted"):
            self.assertEqual(self.send(beacon(*SCAN), cookie), 204, cookie)
        self.assertEqual(self.graph.calls, [])
        self.assertTrue(otto_track.read_events())                    # first-party statistics are stored as before

    def test_dnt_and_gpc_win_over_consent(self):
        self.config()
        self.send(beacon(*SCAN), "otto_consent=v1.granted", DNT="1")
        self.send(beacon(*SCAN), "otto_consent=v1.granted", **{"Sec-GPC": "1"})
        self.send(beacon(*SCAN, anon=True), "otto_consent=v1.granted")
        self.assertEqual(self.graph.calls, [])

    def test_only_mapped_events_are_forwarded(self):
        self.config()
        self.send(beacon({"e": "view"}, {"e": "scroll", "d": 25}, {"e": "section", "id": "pricing"}, {"e": "faq_open", "q": "price"},
                         {"e": "cta", "id": "scan_first@hero"}, {"e": "scan_result", "domain": "example.com", "ok": False}),
                  "otto_consent=v1.granted")
        self.assertEqual(self.graph.calls, [])

    # ---- what is sent ----

    def test_consented_events_reach_meta_with_allowed_fields_only(self):
        self.config()
        self.assertEqual(self.send(beacon(*SCAN), f"theme=dark; otto_consent=v1.granted; otto_fbc={FBC}"), 204)
        self.assertEqual(len(self.graph.calls), 1)
        call = self.graph.calls[0]
        self.assertEqual(call["path"], f"/v25.0/{PIXEL}/events")
        self.assertNotIn(TOKEN, call["path"])                        # the token travels in the body, never in the URL
        self.assertEqual(call["ctype"], "application/x-www-form-urlencoded")
        form = self.graph.forms()[0]
        self.assertEqual(form["access_token"], [TOKEN])
        self.assertEqual(form["test_event_code"], ["TEST12345"])
        data = json.loads(form["data"][0])
        self.assertEqual([e["event_name"] for e in data], ["ViewContent", "Lead", "InitiateCheckout"])
        raw = form["data"][0]
        for secret in ("bakkerij", "jansen", "pricing", "abc12345"):
            self.assertNotIn(secret, raw, "the scanned domain / ids never go to Meta")
        for e in data:
            self.assertEqual(set(e), {"event_name", "event_time", "action_source", "event_id", "event_source_url", "user_data",
                                      "custom_data"})
            self.assertEqual(e["action_source"], "website")
            self.assertEqual(e["event_source_url"], ORIGIN + "/")
            self.assertRegex(e["event_id"], r"^[0-9a-f]{32}$")
            self.assertLessEqual(abs(e["event_time"] - time.time()), 60)
            u = e["user_data"]
            self.assertLessEqual(set(u), {"client_ip_address", "client_user_agent", "fbc", "external_id", "country"})
            self.assertEqual(u["client_ip_address"], "203.0.113.7")
            self.assertEqual(u["client_user_agent"], UA)
            self.assertEqual(u["fbc"], FBC)
            self.assertEqual(u["country"], [hashlib.sha256(b"nl").hexdigest()])
            self.assertRegex(u["external_id"][0], r"^[0-9a-f]{64}$")
            self.assertLessEqual(set(e["custom_data"]), {"content_name", "content_category"})
        self.assertEqual(len({e["event_id"] for e in data}), 3)

    def test_bad_or_unconsented_click_id_is_not_sent(self):
        self.config(test_event_code="")
        self.send(beacon({"e": "scan_start", "domain": "example.com"}), "otto_consent=v1.granted; otto_fbc=fb.1.x.<script>")
        form = self.graph.forms()[0]
        self.assertNotIn("test_event_code", form)
        self.assertNotIn("fbc", json.loads(form["data"][0])[0]["user_data"])
        self.assertEqual(otto_track.capi_consent({"Cookie": f"otto_fbc={FBC}"}), (False, None))

    def test_site_url_when_no_origin_and_nothing_without_either(self):
        self.config()
        h = {"User-Agent": UA, "Cookie": "otto_consent=v1.granted"}
        otto_track.ingest(beacon({"e": "scan_start", "domain": "example.com"}), "203.0.113.8", h)
        otto_track.capi_join()
        self.assertEqual(self.graph.calls, [])                      # no page URL: Meta would reject it, so nothing is sent
        self.config(site_url="https://otto.example/")
        otto_track.ingest(beacon({"e": "scan_start", "domain": "example.com"}), "203.0.113.8", h)
        otto_track.capi_join()
        self.assertEqual(json.loads(self.graph.forms()[0]["data"][0])[0]["event_source_url"], "https://otto.example/")

    def test_trial_and_signup_ctas_are_initiate_checkout(self):
        """The CTA may become 'Start free trial' (Google sign-in): any get_started / start_trial / signup kind maps the same."""
        self.config()
        self.send(beacon({"e": "cta", "id": "start_trial@hero"}, {"e": "cta", "id": "signup@pricing"}, {"e": "cta", "id": "login@nav"}),
                  "otto_consent=v1.granted")
        data = json.loads(self.graph.forms()[0]["data"][0])
        self.assertEqual([e["event_name"] for e in data], ["InitiateCheckout", "InitiateCheckout"])
        self.assertEqual(data[0]["custom_data"]["content_name"], "start trial")

    def test_server_confirmed_signup_and_trial(self):
        self.config()
        h = {"User-Agent": UA, "Origin": ORIGIN, "X-Country": "IE", "Cookie": "otto_consent=v1.granted"}
        self.assertEqual(otto_track.capi_track("signup", "198.51.100.4", h, path="/start", ref="acct-42", method="google", wait=True), 1)
        self.assertEqual(otto_track.capi_track("trial_start", "198.51.100.4", h, ref="acct-42", value=0, currency="eur", wait=True), 1)
        a, b = (json.loads(f["data"][0])[0] for f in self.graph.forms())
        self.assertEqual((a["event_name"], a["custom_data"]["content_category"]), ("CompleteRegistration", "google"))
        self.assertEqual(a["event_source_url"], ORIGIN + "/start")
        self.assertEqual((b["event_name"], b["custom_data"]["currency"], b["custom_data"]["value"]), ("StartTrial", "EUR", 0.0))
        self.assertEqual(b["user_data"]["country"], [hashlib.sha256(b"ie").hexdigest()])
        self.assertNotIn("acct-42", "".join(c["body"] for c in self.graph.calls))     # the account id never goes to Meta
        n = len(self.graph.calls)
        self.assertEqual(otto_track.capi_track("signup", "198.51.100.4", dict(h, Cookie="otto_consent=v1.denied"), wait=True), 0)
        self.assertEqual(otto_track.capi_track("signup", "198.51.100.4", dict(h, **{"Sec-GPC": "1"}), wait=True), 0)
        self.assertEqual(otto_track.capi_track("purchase", "198.51.100.4", h, wait=True), 0)
        self.assertEqual(len(self.graph.calls), n)

    def test_signup_cannot_be_spoofed_through_the_public_beacon(self):
        self.config()
        code = self.send(beacon({"e": "signup", "method": "google"}, {"e": "trial_start"}), "otto_consent=v1.granted")
        self.assertEqual(code, 400)
        self.send(beacon({"e": "view"}, {"e": "cta", "id": "get_started@pricing", "_server": True}), "otto_consent=v1.granted")
        self.assertEqual([e["event_name"] for e in json.loads(self.graph.forms()[0]["data"][0])], ["InitiateCheckout"])

    def test_meta_errors_never_break_the_beacon(self):
        self.graph.status = 400
        self.config()
        self.assertEqual(self.send(beacon(*SCAN), "otto_consent=v1.granted"), 204)
        self.assertEqual(len(self.graph.calls), 1)
        otto_track.CAPI_GRAPH = "http://127.0.0.1:9/v25.0"             # nothing listens: a connection error, swallowed
        self.assertEqual(self.send(beacon(*SCAN), "otto_consent=v1.granted"), 204)


class ConsentBannerTest(unittest.TestCase):
    """Static checks on the banner: loaded by the landing, no network of its own, the two answers equal."""

    def setUp(self):
        self.js = (PLATFORM / "assets" / "consent.js").read_text()
        self.css = (PLATFORM / "assets" / "consent.css").read_text()
        self.landing = (PLATFORM / "landing.html").read_text()

    def test_landing_loads_it_and_links_privacy_choices(self):
        head = self.landing[:self.landing.index("</head>")]
        self.assertIn('<link rel="stylesheet" href="assets/consent.css"><script src="assets/consent.js" defer></script>', head)
        foot = re.search(r"<footer>.*?</footer>", self.landing, re.S).group(0)
        self.assertRegex(foot, r'<a href="legal/cookies\.html#your-choices" data-privacy-choices>Privacy choices</a>')
        csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', self.landing).group(1)
        self.assertNotRegex(csp, r"facebook|fbcdn|connect\.facebook")    # no browser pixel: the CSP stays same-origin

    def test_no_network_and_no_third_parties(self):
        for bad in ("fetch(", "XMLHttpRequest", "sendBeacon", "new Image", "importScripts", "facebook", "fbq", "http://", "https://"):
            self.assertNotIn(bad, self.js, bad)
        self.assertNotRegex(self.css, r"url\(|@import")

    def test_reject_is_as_easy_as_accept(self):
        self.assertIn("ui.reject = el('button', 'oc-btn', L.reject)", self.js)
        self.assertIn("ui.accept = el('button', 'oc-btn', L.accept)", self.js)
        self.assertNotRegex(self.css, r"\[data-choice=|\.oc-btn\.(?:accept|reject|primary)")   # no style for one answer only
        for lang in ("en", "nl"):
            block = re.search(lang + r": \{(.*?)\n    \}", self.js, re.S).group(1)
            for key in ("title", "body", "reject", "accept", "footer", "gpc"):
                self.assertRegex(block, r"\b" + key + r": '", f"{lang} lacks {key}")
        self.assertIn("reject: 'Weigeren', accept: 'Accepteren'", self.js)
        self.assertIn("'v1.granted'", self.js.replace("VERSION + '.granted'", "'v1.granted'"))
        self.assertEqual(otto_track.CONSENT_GRANTED, "v1.granted")
        self.assertIn(f"KEY = '{otto_track.CONSENT_COOKIE}'", self.js)
        self.assertIn(f"FBC = '{otto_track.FBC_COOKIE}'", self.js)


if __name__ == "__main__":
    unittest.main()
