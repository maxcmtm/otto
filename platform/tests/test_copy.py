#!/usr/bin/env python3
"""The AI copywriter (otto_copy) against a fake Claude API (tests/fake_anthropic.py, 127.0.0.1 — no network): the request
shape (headers, model, adaptive thinking, effort, strict JSON schema, refusal fallbacks, the cached brand block), the posts it
writes (exactly the fields the app, the 07:35 report, the approval e-mails and the publisher read) and their cards (token
names, published), pending_approval for what passes, the JSON repair, compliance rejection → one rewrite → held as a draft
with an owner card, banned words, the no-invention guard (numbers, prices, quotes, attributions, personas, claims), a person's
edit never overwritten, the trial (spawn on kickoff, copy_done + the owner card resolved, the hourly catch-up), no key → no-op,
the caps and the usage ledger, retries, the auth error, refusals, cut-off answers, the daily job and its timer, disclaimers,
English twins, cards deferred from a process without Chrome. Every OTTO_* path points into a temp workspace.

  cd platform && python3 tests/test_copy.py
  OTTO_TEST_RENDER=1 python3 tests/test_copy.py        # also one real render through headless Chrome (fonts may be fetched)
"""
import contextlib, io, json, os, shutil, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PLATFORM = Path(__file__).resolve().parent.parent
REPO = PLATFORM.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_anthropic as FA                                                     # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="otto-copy-test-"))
ENV = {"OTTO_DATA": str(TMP / "data.json"), "OTTO_HTML": str(TMP / "index.html"), "OTTO_BRANDS": str(TMP / "brands"),
       "OTTO_SECRETS": str(TMP / "secrets"), "OTTO_ASSETS": str(TMP / "assets"), "OTTO_PUBLIC_ASSETS": str(TMP / "public"),
       "OTTO_PUBLIC_BASE": "https://otto.example/", "OTTO_COPY_LEDGER": str(TMP / "copy-usage.json"), "OTTO_LOCKS": str(TMP / "locks"),
       "OTTO_PLANS": str(TMP / "plans.json"), "OTTO_OUTBOX": str(TMP / "outbox"), "OTTO_EMAIL_STATE": str(TMP / ".email-state.json"),
       "OTTO_HEARTBEATS": str(TMP / "heartbeats.json"), "OTTO_BILLING": str(TMP / "billing.json"), "OTTO_EVENTS": str(TMP / "events.jsonl"),
       "OTTO_SESSIONS": str(TMP / "sessions.json"), "OTTO_APP_URL": "https://app.otto.example/"}
CLEAR = ("ANTHROPIC_API_KEY", "OTTO_COPY_MODEL", "OTTO_COPY", "OTTO_COPY_RENDER", "OTTO_ANTHROPIC_API_BASE", "OTTO_TZ", "OTTO_DOMAIN")
MODS = ("ap", "otto_copy", "otto_trial", "otto_plan", "otto_paths", "otto_render", "otto_cron", "otto_admin", "otto_compliance")
PINS = [("ap", "DATA", "data.json"), ("ap", "HTML", "index.html"), ("ap", "BRANDS", "brands"), ("otto_paths", "ASSETS", "assets"),
        ("otto_plan", "BRANDS", "brands"), ("otto_render", "BRANDS", "brands")]
TZ = ZoneInfo("Europe/Amsterdam")
_SAVED, S = {}, {}

SCAN = {"url": "https://beanbros.example", "final_url": "https://beanbros.example/", "scanned_at": "2026-10-01T10:00:00Z",
        "pages": ["https://beanbros.example/"],
        "identity": {"title": "Bean Bros | Specialty coffee roasters", "description": "Small-batch coffee, roasted in Utrecht.",
                     "site_name": "Bean Bros", "og_title": "", "og_image": None},
        "industry": "E-commerce & retail", "industry_candidates": [], "languages": ["en"], "platform": "Shopify",
        "visual": {"palette": [{"hex": "#7A3B12", "count": 30}], "neutrals": [], "logo": None, "fonts": [], "theme_color": None},
        "socials": {"instagram": "https://instagram.com/beanbros"}, "contact": {"emails": [], "phones": []},
        "commerce": {"currency": "EUR", "prices": ["€ 12", "€ 79"], "promos": []},
        "trust": ["Roasted in Utrecht since 2014"], "quotes": ["“Best beans in town, every single time.” — Kim"],
        "headings": ["Fresh roasted coffee", "Our beans", "Subscriptions"], "nav": ["Shop", "Subscriptions", "About"],
        "text_sample": "Bean Bros roasts small batches in Utrecht since 2014. Every bag shows its roast date. "
                       "A bag costs € 12; the yearly subscription € 79."}
STRATEGY = {"brand": "beans", "personas": [{"id": "p1", "label": "Petra, 41, home barista", "situation": "brews every morning",
                                            "awareness": "problem", "words": ["my coffee tastes flat"]}],
            "pains": [{"text": "coffee tastes flat at home", "persona": "p1", "source": "site"}],
            "objections": [{"text": "Is specialty coffee worth it?", "answer": "the roast date", "proof_id": "(?)"}],
            "offers": [{"id": "o1", "name": "Yearly subscription", "price": "€ 79", "terms": "(?)", "deadline": None, "stage": "hot"}],
            "proof_bank": [{"id": "pr1", "claim": "Roasted in Utrecht since 2014", "source": "site"}],
            "cta_by_stage": {"cold": "Shop beans", "warm": "Try a bag", "hot": "Subscribe"},
            "angles": [{"id": "a1", "angle": "Freshness you can read on the bag", "persona": "p1", "stage": "cold", "status": "idea"}]}
PROFILE = "# Bean Bros — brand profile\n\n## VOICE\nWarm, plain, a little nerdy about coffee. Addresses the reader as 'you'.\n"


def local_slot(days, hhmm="09:00"):
    d = (datetime.now(TZ) + timedelta(days=days)).date()
    return f"{d.isoformat()}T{hhmm}"


def brand(bid="beans", **kw):
    b = {"id": bid, "name": "Bean Bros" if bid == "beans" else bid.title(), "url": f"{bid}.example", "lang": "EN",
         "tz": "Europe/Amsterdam", "status": "active", "plan": "starter", "countries": ["NL"], "members": [f"kim@{bid}.example"],
         "approvals": "email", "comms_lang": "en", "pillars": ["Education", "Product", "Proof"], "copy_auto": True}
    b.update(kw)
    return b


def post(pid, bid, days, fmt="post", platform="ig", status="draft", hook="", **kw):
    p = {"id": pid, "brand": bid, "pillar": "Education", "platform": platform, "hook": hook, "status": status,
         "slot": local_slot(days), "created_at": "2026-10-01T10:00:00Z", "format": fmt, "plan": "2026-10",
         "brief": f"Education · {fmt} · angle TBD by Quill · visual on-brand per brand-profile.md"}
    p.update(kw)
    return p


def seed():
    posts = [post("bb-001", "beans", 1, "post", "fb"), post("bb-002", "beans", 2, "carousel"), post("bb-003", "beans", 3, "story"),
             post("bb-004", "beans", 4, "reel"), post("bb-005", "beans", 5, "post"), post("bb-006", "beans", 6, "post", "fb"),
             post("bb-090", "beans", -1, "post"),                                  # past: never written
             post("bb-091", "beans", 10, "post"),                                  # outside the 7 days
             post("bb-092", "beans", 2, "post", hook="A person wrote this one"),   # a person's draft
             post("bb-093", "beans", 3, "post", status="pending_approval", hook="Already waiting", caption="Waiting.")]
    return {"brands": [brand()], "posts": posts, "recommendations": [], "connections": [], "campaigns": [], "users": []}


def write_brand_files(bid="beans", scan=None, strategy=None, compliance=None):
    f = TMP / "brands" / bid
    f.mkdir(parents=True, exist_ok=True)
    (f / "scan.json").write_text(json.dumps(scan or SCAN))
    (f / "strategy.json").write_text(json.dumps(strategy or STRATEGY))
    (f / "brand-profile.md").write_text(PROFILE)
    (f / "compliance.json").write_text(json.dumps(compliance or {"banned": ["miracle", "re:\\bcheap\\b"], "required_disclaimer": None}))


def set_key(**extra):
    cfg = {"api_key": FA.KEY, "parallel": 1, "batch": 4}
    cfg.update(extra)
    (TMP / "secrets" / "anthropic.json").write_text(json.dumps(cfg))


def data():
    return json.loads((TMP / "data.json").read_text())


def P(pid, d=None):
    return next(p for p in (d or data())["posts"] if p["id"] == pid)


def fake_render(template, d, out_path, size, tok):
    S["renders"].append({"template": template, "data": dict(d), "size": tuple(size)})
    Path(out_path).write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 2048)
    return str(out_path)


def setUpModule():
    for d in ("brands", "secrets", "assets", "public", "locks"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(PLATFORM / "plans.json", TMP / "plans.json")
    (TMP / "index.html").write_text('<html><script id="fallback-data" type="application/json">{}</script></html>')
    _SAVED["env"] = {k: os.environ.get(k) for k in list(ENV) + list(CLEAR)}
    os.environ.update(ENV)
    for k in CLEAR:
        os.environ.pop(k, None)
    sys.path.insert(0, str(PLATFORM))
    g = globals()
    for m in MODS:
        g[m] = __import__(m)
    _SAVED["pins"] = [(m, a, getattr(g[m], a)) for m, a, _ in PINS]
    for m, a, rel in PINS:
        setattr(g[m], a, TMP / rel)
    S["fake"] = FA.FakeAnthropic()
    os.environ["OTTO_ANTHROPIC_API_BASE"] = S["fake"].base
    _SAVED["fns"] = (otto_copy.render_card, otto_copy.tokens, otto_copy.SPAWN, otto_copy.SLEEP, otto_copy.fetch_og,
                     otto_copy.can_render)
    otto_copy.tokens = lambda bid: {"lang": "en", "name": bid}
    otto_copy.fetch_og = lambda bid, scan: None
    otto_copy.can_render = lambda: True


def tearDownModule():
    if "fake" in S:
        S["fake"].close()
    if "fns" in _SAVED:
        (otto_copy.render_card, otto_copy.tokens, otto_copy.SPAWN, otto_copy.SLEEP, otto_copy.fetch_og,
         otto_copy.can_render) = _SAVED["fns"]
    g = globals()
    for m, a, v in _SAVED.get("pins", []):
        setattr(g[m], a, v)
    for k, v in (_SAVED.get("env") or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        (TMP / "data.json").write_text(json.dumps(seed(), indent=1))
        for x in (TMP / "brands").iterdir():
            shutil.rmtree(x, ignore_errors=True)
        for x in ("assets", "public"):
            shutil.rmtree(TMP / x, ignore_errors=True)
            (TMP / x).mkdir()
        for f in ("copy-usage.json", "copy.log"):
            (TMP / f).unlink(missing_ok=True)
        (TMP / "secrets" / "anthropic.json").unlink(missing_ok=True)
        write_brand_files()
        set_key()
        S["fake"].reset()
        S["renders"] = []
        S["sleeps"] = []
        S["spawned"] = []
        otto_copy.render_card = fake_render
        otto_copy.SLEEP = lambda s: S["sleeps"].append(s)
        otto_copy.SPAWN = lambda args, log: S["spawned"].append(args)
        otto_copy.can_render = lambda: True
        otto_copy._no_fallback.clear()
        for k in ("ANTHROPIC_API_KEY", "OTTO_COPY", "OTTO_COPY_MODEL", "OTTO_COPY_QUEUE"):
            os.environ.pop(k, None)
        os.environ["OTTO_ANTHROPIC_API_BASE"] = S["fake"].base

    def run_week(self, bid="beans", **kw):
        lines = []
        r = otto_copy.write_week(bid, out=lines.append, **kw)
        return r, lines


def walk_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from walk_objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from walk_objects(v)


class RequestAndWrite(Base):
    def test_request_shape_and_posts_written(self):
        r, lines = self.run_week()
        self.assertEqual(sorted(r["written"]), ["bb-001", "bb-002", "bb-003", "bb-004", "bb-005", "bb-006"], lines)
        reqs = S["fake"].requests()
        self.assertEqual(len(reqs), 2, "6 posts in batches of 4 → 2 requests")
        h, body = reqs[0]["headers"], reqs[0]["body"]
        self.assertEqual(h["x-api-key"], FA.KEY)
        self.assertEqual(h["anthropic-version"], "2023-06-01")
        self.assertEqual(h["anthropic-beta"], otto_copy.FALLBACK_BETA)
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["output_config"]["effort"], "medium")
        fmt = body["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        for obj in walk_objects(fmt["schema"]):
            self.assertIs(obj.get("additionalProperties"), False, obj)
            self.assertEqual(sorted(obj["required"]), sorted(obj["properties"]), "structured outputs: every field required")
        self.assertNotIn("temperature", body)
        sysb = body["system"]
        self.assertEqual(len(sysb), 2)
        self.assertNotIn("cache_control", sysb[0])
        self.assertEqual(sysb[1]["cache_control"], {"type": "ephemeral"})
        self.assertIn("You are Quill", sysb[0]["text"])
        self.assertIn("checklist", sysb[0]["text"], "the hook bank is in the system prompt")
        brand_txt = sysb[1]["text"]
        for s in ("Bean Bros", "CONTENT LANGUAGE: English (en)", "Roasted in Utrecht since 2014", "€ 12", "miracle",
                  "Best beans in town", "Petra, 41"):
            self.assertIn(s, brand_txt)
        self.assertEqual([s["id"] for s in reqs[0]["slots"]], ["bb-001", "bb-002", "bb-003", "bb-004"])
        self.assertEqual(reqs[0]["slots"][1]["format"], "carousel")
        self.assertEqual(reqs[0]["slots"][0]["network"], "Facebook")
        self.assertEqual(sysb, reqs[1]["body"]["system"], "the second batch reuses the cached prefix byte for byte")
        self.assertIn("bb-005", reqs[1]["body"]["messages"][0]["content"])
        self.assertIn("The rest of this week", reqs[0]["body"]["messages"][0]["content"])
        d = data()
        for pid in r["written"]:
            p = P(pid, d)
            self.assertEqual(p["status"], "pending_approval", pid)
            self.assertTrue(p["hook"] and p["caption"] and p["why"], pid)
            self.assertTrue(isinstance(p["hashtags"], list) and all(t.startswith("#") for t in p["hashtags"]), pid)
            self.assertTrue(p["image"].startswith("assets/posts/"), p["image"])
            import otto_paths
            self.assertTrue(otto_paths.has_token(p["image"]), "unguessable media names")
            self.assertTrue((TMP / "assets" / p["image"][len("assets/"):]).is_file())
            self.assertTrue((TMP / "public" / p["image"][len("assets/"):]).is_file(), "published")
            self.assertTrue(otto_paths.valid_token(p.get("media_token")))
            self.assertEqual(p["copy"]["by"], "otto_copy")
            self.assertEqual(p["copy"]["state"], "written")
            self.assertEqual(p["copy"]["model"], "claude-opus-5-5")
            self.assertNotIn("_render", p)
            self.assertNotIn("hook_en", p, "English content: no English twin")
        car = P("bb-002", d)
        self.assertGreaterEqual(len(car["images"]), 4)
        self.assertEqual(car["image"], car["images"][0])
        self.assertTrue(all(isinstance(s, dict) and s["title"] for s in car["slides"]))
        self.assertEqual(len(set(car["images"])), len(car["images"]))
        reel = P("bb-004", d)
        self.assertGreaterEqual(len(reel["script"]), 4)
        self.assertTrue(all({"text", "seconds", "visual"} <= set(x) for x in reel["script"]))
        tpls = [x["template"] for x in S["renders"]]
        self.assertIn("carousel_cover", tpls)
        self.assertIn("carousel_cta", tpls)
        story = [x for x in S["renders"] if x["size"] == (1080, 1920)]
        self.assertEqual(len(story), 2, "the story and the reel cover are 9:16")
        self.assertTrue(any("*" in x["data"].get("headline", "") for x in S["renders"]), "the accent word is marked")
        # untouched
        self.assertEqual(P("bb-090", d)["status"], "draft")
        self.assertEqual(P("bb-090", d)["hook"], "")
        self.assertEqual(P("bb-091", d)["hook"], "")
        self.assertEqual(P("bb-092", d)["hook"], "A person wrote this one")
        self.assertNotIn("copy", P("bb-092", d))
        self.assertEqual(P("bb-093", d)["caption"], "Waiting.")
        out = "\n".join(lines)
        self.assertNotIn(FA.KEY, out)
        self.assertNotIn(FA.KEY, json.dumps(d))
        self.assertNotIn(FA.KEY, (TMP / "copy-usage.json").read_text())
        led = json.loads((TMP / "copy-usage.json").read_text())
        day = next(iter(led["days"].values()))
        self.assertEqual(day["calls"], 2)
        self.assertEqual(day["input_tokens"], 3000)
        self.assertEqual(day["output_tokens"], 1800)
        self.assertAlmostEqual(day["usd"], 2 * (1500 * 4 + 900 * 20 + 400 * 5) / 1e6, places=4)
        self.assertEqual(day["brands"]["beans"]["calls"], 2)
        self.assertEqual(led["brands"]["beans"]["written"], 6)
        # what the approval flow picks up
        import otto_email
        due, blocked = otto_email.due_posts(d, ap.brand(d, "beans"), datetime.now(timezone.utc), hours=96, dry=True)
        self.assertIn("bb-001", [p["id"] for p in due])
        self.assertEqual(blocked, 0)
        # a second run has nothing left to write
        r2, _ = self.run_week()
        self.assertEqual(r2["skipped"], "nothing to write")
        self.assertEqual(len(S["fake"].requests()), 2)

    def test_parallel_batches(self):
        set_key(parallel=3, batch=2)
        r, lines = self.run_week()
        self.assertEqual(len(r["written"]), 6, lines)
        self.assertEqual(sorted(len(x["slots"]) for x in S["fake"].requests()), [2, 2, 2])
        self.assertEqual(len({p["image"] for p in data()["posts"] if p.get("image")}), 6, "one card set per written post")

    def test_dry_run_sends_nothing(self):
        r, lines = self.run_week(dry=True)
        self.assertEqual(r["skipped"], "dry")
        self.assertEqual(S["fake"].requests(), [])
        self.assertTrue(any("WOULD WRITE bb-001" in x for x in lines))
        self.assertEqual(P("bb-001")["hook"], "")

    def test_model_effort_and_fallbacks_are_configurable(self):
        set_key(model="claude-sonnet-5", effort="low", fallbacks=False)
        self.run_week()
        body, h = S["fake"].requests()[0]["body"], S["fake"].requests()[0]["headers"]
        self.assertEqual(body["model"], "claude-sonnet-5")
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertNotIn("fallbacks", body)
        self.assertNotIn("anthropic-beta", h)
        self.assertEqual(P("bb-001")["copy"]["model"], "claude-sonnet-5")

    def test_api_base_only_local(self):
        for v, want in (("https://evil.example", otto_copy.API_BASE), ("http://localhost:9", otto_copy.API_BASE),
                        ("http://127.0.0.1:8080", "http://127.0.0.1:8080")):
            os.environ["OTTO_ANTHROPIC_API_BASE"] = v
            self.assertEqual(otto_copy.config()["api_base"], want, v)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-from-env"
        self.assertEqual(otto_copy.config()["api_key"], "sk-ant-from-env")
        self.assertEqual(otto_copy.config()["key_source"], "env")


class NoKey(Base):
    def test_no_key_is_a_no_op(self):
        (TMP / "secrets" / "anthropic.json").unlink()
        before = (TMP / "data.json").read_text()
        r, lines = self.run_week()
        self.assertEqual(r["skipped"], "no_key")
        self.assertEqual(S["fake"].requests(), [])
        self.assertEqual((TMP / "data.json").read_text(), before)
        self.assertFalse(otto_copy.spawn_week("beans"))
        self.assertEqual(S["spawned"], [])
        self.assertEqual(otto_copy.daily(out=lines.append), [])
        row = otto_admin._copy_setup()
        self.assertEqual(row["key"], "copywriter")
        self.assertEqual(row["status"], "missing")
        self.assertIn("anthropic.json", row["how"])
        self.assertNotIn(FA.KEY, json.dumps(row))
        (TMP / "secrets" / "anthropic.json").write_text("{not json")
        self.assertFalse(otto_copy.ready())
        self.assertIn("not valid JSON", otto_admin._copy_setup()["detail"])

    def test_switched_off(self):
        os.environ["OTTO_COPY"] = "off"
        r, _ = self.run_week()
        self.assertEqual(r["skipped"], "off")
        self.assertEqual(S["fake"].requests(), [])

    def test_setup_row_with_key(self):
        self.run_week()
        row = otto_admin._copy_setup()
        self.assertEqual(row["status"], "connected")
        self.assertIn("claude-opus-5-5", row["detail"])
        self.assertIn("2 call(s)", row["detail"])
        self.assertNotIn(FA.KEY, json.dumps(row))
        info = otto_copy.status(out=lambda *a: None)
        self.assertTrue(info["ready"])
        self.assertEqual(info["today"]["calls"], 2)
        self.assertNotIn(FA.KEY, json.dumps(info))


class Validation(Base):
    def test_bad_json_is_asked_again(self):
        S["fake"].replies = [("text", "Sure! Here are your posts.")]   # the rewrite request gets the default answer
        r, lines = self.run_week()
        self.assertIn("bb-001", r["written"], lines)
        reqs = S["fake"].requests()
        self.assertIn("<rejected>", reqs[1]["body"]["messages"][0]["content"])
        self.assertIn("no draft came back", reqs[1]["body"]["messages"][0]["content"])
        self.assertEqual(P("bb-001")["copy"]["attempts"], 2)

    def test_json_inside_prose_is_repaired_without_a_new_call(self):
        slots = [{"id": "bb-001", "format": "post"}, {"id": "bb-002", "format": "carousel"}, {"id": "bb-003", "format": "story"},
                 {"id": "bb-004", "format": "reel"}]
        S["fake"].replies = [("text", "Here you go:\n" + json.dumps({"posts": [FA.make(x, i) for i, x in enumerate(slots)]})
                              + "\nEnjoy!")]
        r, _ = self.run_week()
        self.assertEqual(len(S["fake"].requests()), 2, "batch 1 repaired from prose, batch 2 normal")
        self.assertIn("bb-004", r["written"])
        self.assertEqual(P("bb-001")["copy"]["attempts"], 1)

    def test_hashtags_moved_out_of_caption_and_normalised(self):
        def reply(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            out[0]["caption"] += "\n\n#beans #Coffee Time"
            out[0]["hashtags"] = ["specialty coffee", "#beans"]
            out[0]["hook"] = "☕ Fresh beans show their roast date"
            return out
        S["fake"].replies = [reply]
        self.run_week()
        p = P("bb-001")
        self.assertNotIn("#beans", p["caption"])
        self.assertEqual(p["hashtags"][:2], ["#specialtycoffee", "#beans"])
        self.assertNotIn("☕", p["hook"])


class Compliance(Base):
    def test_violation_is_rewritten_once(self):
        def bad(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            out[0]["caption"] = "This little miracle in a bag changes your mornings. Order in the webshop."
            return out
        S["fake"].replies = [bad]
        r, lines = self.run_week()
        reqs = S["fake"].requests()
        self.assertEqual(len(reqs), 3, "batch 1, its rewrite, batch 2")
        msg = reqs[1]["body"]["messages"][0]["content"]
        self.assertIn("<rejected>", msg)
        self.assertIn("miracle", msg)
        self.assertEqual([s["id"] for s in reqs[1]["slots"]], ["bb-001"], "only the failing post is rewritten")
        self.assertIn("bb-001", r["written"])
        p = P("bb-001")
        self.assertNotIn("miracle", p["caption"])
        self.assertEqual(p["copy"]["attempts"], 2)
        self.assertEqual(P("bb-002")["copy"]["attempts"], 1)

    def test_still_violating_is_held_for_the_owner(self):
        def bad(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            out[0]["caption"] = "Cheap coffee, a miracle every morning. Order in the webshop."
            return out
        S["fake"].replies = [bad, bad]
        r, lines = self.run_week()
        self.assertIn("bb-001", r["held"])
        p = P("bb-001")
        self.assertEqual(p["status"], "draft", "never shown to the client")
        self.assertEqual(p["copy"]["state"], "held")
        self.assertEqual(p["copy"]["held_for"], ["compliance"])
        self.assertIn("miracle", p["caption"], "the draft is kept for a person to fix")
        self.assertNotIn("image", p, "no card for a held post")
        recs = [x for x in data()["recommendations"] if x["title"] == "Copy held for review: Bean Bros"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["audience"], "owner")
        self.assertIn("bb-001", recs[0]["why"])
        self.assertIn("miracle", recs[0]["why"])
        self.assertEqual(recs[0]["posts"], ["bb-001"])
        import otto_api
        self.assertNotIn(recs[0]["id"], [x["id"] for x in otto_api.client_view(data(), {"beans"})["recommendations"]])
        r2, _ = self.run_week()                                     # a held post is left for a person
        self.assertEqual(r2["skipped"], "nothing to write")

    def test_disclaimers_are_added_by_code(self):
        write_brand_files(compliance={"banned": [], "required_disclaimer": "Prices include VAT."})
        self.run_week()
        self.assertTrue(P("bb-001")["caption"].endswith("Prices include VAT."))
        # a US supplement brand: the DSHEA line
        d = data()
        d["brands"].append(brand("greens", countries=["US"], currency="USD"))
        d["posts"].append(post("gr-001", "greens", 2))
        (TMP / "data.json").write_text(json.dumps(d))
        scan = dict(SCAN, industry="Supplements & nutrition")
        write_brand_files("greens", scan=scan, compliance={"banned": [], "required_disclaimer": None, "countries": ["US"],
                                                           "industries": ["supplements"]})
        self.run_week("greens")
        cap = P("gr-001")["caption"]
        self.assertIn("not been evaluated by the Food and Drug Administration", cap)
        self.assertEqual(cap.count("Food and Drug Administration"), 1)


class Claims(Base):
    def ctx(self):
        d = data()
        return otto_copy.context(d, ap.brand(d, "beans"))

    def test_guard(self):
        c = self.ctx()
        cp = lambda t: otto_copy.claims_problems([t], c)
        self.assertEqual(cp("3 things to check before you buy beans. A bag costs €12."), [])
        self.assertEqual(cp("Roasting in Utrecht since 2014. Open at 18:00."), [])
        self.assertEqual(cp("The yearly subscription is € 79 — that is €6.58 a month."), [], "price maths from a real price")
        self.assertEqual(cp("“Best beans in town, every single time.” — Kim"), [], "a verbatim review")
        self.assertEqual(cp("- Fresh beans\n- Roast date on every bag"), [], "a bullet list is not an attribution")
        self.assertTrue(any("number “12,000”" in x for x in cp("Loved by 12,000 coffee fans.")))
        self.assertTrue(any("price “15”" in x for x in cp("Now only €15 a bag.")))
        self.assertTrue(any("percentage “20%”" in x for x in cp("Save 20% today.")))
        self.assertTrue(any("quotation" in x for x in cp("“These beans changed my mornings forever,” says a fan.")))
        self.assertTrue(any("— Anna" in x for x in cp("“Lovely.”\n— Anna K.")))
        self.assertTrue(any("persona" in x for x in cp("Petra brews every morning before work.")))
        self.assertTrue(any("an award" in x for x in cp("Award-winning roasters from Utrecht.")))
        self.assertTrue(any("a guarantee" in x for x in cp("Money-back guarantee on every bag.")))
        self.assertTrue(any("free shipping" in x for x in cp("Free shipping on every order.")))
        self.assertTrue(any("a rating" in x for x in cp("Rated 4.9 stars by our fans.")))

    def test_invented_claims_are_rewritten(self):
        def bad(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            out[0]["caption"] = "Over 12,000 happy customers can't be wrong. “Best coffee I ever had” — Sarah M.\n\nOrder today."
            return out
        S["fake"].replies = [bad]
        r, _ = self.run_week()
        msg = S["fake"].requests()[1]["body"]["messages"][0]["content"]
        self.assertIn("12,000", msg)
        self.assertIn("Sarah", msg)
        self.assertIn("bb-001", r["written"])
        self.assertNotIn("12,000", P("bb-001")["caption"])

    def test_filler_words_earn_one_rewrite_but_never_hold(self):
        def filler(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            out[0]["hook"] = "Unlock a seamless morning ritual"
            return out
        S["fake"].replies = [filler, filler]
        r, _ = self.run_week()
        self.assertIn("filler", S["fake"].requests()[1]["body"]["messages"][0]["content"])
        self.assertIn("bb-001", r["written"], "style never holds a post")
        self.assertEqual(P("bb-001")["status"], "pending_approval")


class Statuses(Base):
    def test_a_persons_edit_is_never_overwritten(self):
        def meddle(body, slots, n):
            d = data()
            P("bb-002", d)["hook"] = "Max wrote this while Otto was thinking"
            P("bb-003", d)["status"] = "skipped"
            (TMP / "data.json").write_text(json.dumps(d))
            return [FA.make(s, i) for i, s in enumerate(slots)]
        S["fake"].replies = [meddle]
        r, _ = self.run_week()
        d = data()
        self.assertEqual(P("bb-002", d)["hook"], "Max wrote this while Otto was thinking")
        self.assertEqual(P("bb-002", d)["status"], "draft")
        self.assertNotIn("copy", P("bb-002", d))
        self.assertEqual(P("bb-003", d)["status"], "skipped")
        self.assertNotIn("bb-002", r["written"])
        self.assertEqual(P("bb-001", d)["status"], "pending_approval")

    def test_plan_gates(self):
        d = data()
        b = ap.brand(d, "beans")
        b["plan"] = "none"
        (TMP / "data.json").write_text(json.dumps(d))
        r, _ = self.run_week()
        self.assertIn("ended plan", r["skipped"])
        b["plan"], b["paused"] = "starter", True
        (TMP / "data.json").write_text(json.dumps(d))
        self.assertEqual(self.run_week()[0]["skipped"], "paused")
        self.assertEqual(S["fake"].requests(), [])

    def test_formats_outside_the_plan_are_skipped(self):
        plans = json.loads((TMP / "plans.json").read_text())
        plans["plans"]["slim"] = {"label": "Slim", "inherits": "content", "public": False,
                                  "features": {"reels": False, "stories": False}}
        plans["order"] = plans.get("order", []) + ["slim"]
        (TMP / "plans.json").write_text(json.dumps(plans))
        try:
            d = data()
            ap.brand(d, "beans")["plan"] = "slim"
            (TMP / "data.json").write_text(json.dumps(d))
            r, _ = self.run_week()
            self.assertNotIn("bb-003", r["written"])
            self.assertNotIn("bb-004", r["written"])
            self.assertIn("bb-001", r["written"])
        finally:
            shutil.copy(PLATFORM / "plans.json", TMP / "plans.json")


class Trial(Base):
    def trial_seed(self, minutes_ago=30):
        d = data()
        b = ap.brand(d, "beans")
        b.update(plan="trial", trial={"user": "u1", "started_at": "2026-10-02T08:00:00Z", "ends_at": "2026-10-09T08:00:00Z"},
                 kickoff={"done": True, "at": otto_copy.iso(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)),
                          "months": ["2026-10"], "planned": ["2026-10"], "copy_needed": True})
        ap.add_rec(d, "P1", "New trial: write the first week for Bean Bros", "…", "…", "Write copy", brand="beans",
                   source="otto_trial", audience="owner")
        (TMP / "data.json").write_text(json.dumps(d))

    def test_copy_done_and_card_resolved(self):
        self.trial_seed()
        r, lines = self.run_week()
        self.assertEqual(len(r["written"]), 6)
        d = data()
        self.assertFalse(ap.brand(d, "beans")["kickoff"]["copy_needed"])
        self.assertTrue(ap.brand(d, "beans")["kickoff"].get("copy_try_at"))
        rec = next(x for x in d["recommendations"] if x["title"].startswith("New trial: write the first week"))
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["done_by"], "otto_copy")

    def test_failed_week_stays_needed(self):
        self.trial_seed()
        S["fake"].replies = [("error", 500, "api_error", "Internal server error")] * 20
        r, lines = self.run_week()
        self.assertEqual(r["written"], [])
        self.assertEqual(len(r["failed"]), 6)
        d = data()
        self.assertTrue(ap.brand(d, "beans")["kickoff"]["copy_needed"])
        self.assertEqual(P("bb-001", d)["copy"]["state"], "failed")
        self.assertEqual(P("bb-001", d)["status"], "draft")
        note = next(x for x in d["recommendations"] if x["title"] == "Copy not written yet: Bean Bros")
        self.assertEqual(note["audience"], "owner")
        self.assertIn("500", note["why"])
        self.assertNotIn(FA.KEY, "\n".join(lines) + json.dumps(d))
        self.assertEqual(len(S["sleeps"]), 3 * 2, "4 tries per request (3 backoffs) for each of the two batches")
        # a failed post is retried only after a pause
        S["fake"].reset()
        r2, _ = self.run_week()
        self.assertEqual(r2["skipped"], "nothing to write")

    def test_spawn_on_kickoff(self):
        d = data()
        b = ap.brand(d, "beans")
        b.update(plan="trial", trial={"user": "u1", "started_at": "2026-10-02T08:00:00Z",
                                      "ends_at": otto_copy.iso(datetime.now(timezone.utc) + timedelta(days=7))})
        d["posts"] = []
        (TMP / "data.json").write_text(json.dumps(d))
        lines = []
        otto_trial.kickoff("beans", out=lines.append)
        self.assertEqual(len(S["spawned"]), 1, lines)
        args = S["spawned"][0]
        self.assertEqual(Path(args[1]).name, "otto_copy.py")
        self.assertEqual(args[2:], ["week", "--brand", "beans", "--days", "7"])
        self.assertIn("week --brand beans", (TMP / "copy.log").read_text())
        self.assertTrue(ap.brand(data(), "beans")["kickoff"]["copy_needed"])
        # without a key: nothing is spawned, the owner card is the fallback
        d = data()
        ap.brand(d, "beans").pop("kickoff")
        (TMP / "data.json").write_text(json.dumps(d))
        (TMP / "secrets" / "anthropic.json").unlink()
        otto_trial.kickoff("beans", out=lines.append)
        self.assertEqual(len(S["spawned"]), 1)
        self.assertTrue(any("no Anthropic key" in x for x in lines))
        self.assertTrue(any(x["title"].startswith("New trial: write the first week") for x in data()["recommendations"]))

    def test_hourly_catch_up(self):
        self.trial_seed(minutes_ago=5)
        lines = []
        self.assertEqual(otto_trial.copy_catchup(out=lines.append), [], "too soon: the background run may still be busy")
        self.trial_seed(minutes_ago=30)
        d = data()
        ap.brand(d, "beans")["kickoff"]["copy_try_at"] = otto_copy.iso(datetime.now(timezone.utc) - timedelta(minutes=10))
        (TMP / "data.json").write_text(json.dumps(d))
        self.assertEqual(otto_trial.copy_catchup(out=lines.append), [], "tried 10 minutes ago")
        d = data()
        ap.brand(d, "beans")["kickoff"].pop("copy_try_at")
        (TMP / "data.json").write_text(json.dumps(d))
        self.assertEqual(otto_trial.copy_catchup(out=lines.append), ["beans"])
        self.assertFalse(ap.brand(data(), "beans")["kickoff"]["copy_needed"])
        self.assertEqual(P("bb-001")["status"], "pending_approval")
        self.assertEqual(S["spawned"], [], "inline in the job, never spawned (systemd would kill it)")


class Caps(Base):
    def test_brand_cap(self):
        set_key(max_calls_per_brand_day=1)
        r, lines = self.run_week()
        self.assertEqual(len(S["fake"].requests()), 1)
        self.assertEqual(sorted(r["written"]), ["bb-001", "bb-002", "bb-003", "bb-004"])
        self.assertEqual(sorted(r["failed"]), ["bb-005", "bb-006"])
        self.assertIn("daily cap of 1", r["stop"])
        note = next(x for x in data()["recommendations"] if x["title"] == "Copy not written yet: Bean Bros")
        self.assertIn("cap", note["why"])

    def test_global_and_spend_caps(self):
        set_key(max_calls_day=1)
        self.run_week()
        self.assertEqual(len(S["fake"].requests()), 1)
        S["fake"].reset()
        set_key()
        (TMP / "data.json").write_text(json.dumps(seed()))
        led = json.loads((TMP / "copy-usage.json").read_text())
        next(iter(led["days"].values()))["usd"] = 999.0
        (TMP / "copy-usage.json").write_text(json.dumps(led))
        r, _ = self.run_week()
        self.assertEqual(S["fake"].requests(), [])
        self.assertIn("spend cap", r["stop"])

    def test_cost_estimate(self):
        self.assertAlmostEqual(otto_copy.cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}), 6.0)
        self.assertEqual(otto_copy.price_of("claude-new-model-9"), otto_copy.UNKNOWN_PRICE, "unknown models are never under-priced")


class Errors(Base):
    def test_overloaded_and_rate_limited_are_retried(self):
        S["fake"].replies = [("error", 529, "overloaded_error", "Overloaded"),
                             ("error", 429, "rate_limit_error", "Slow down", {"retry-after": "2"})]
        r, _ = self.run_week()
        self.assertEqual(len(r["written"]), 6)
        self.assertEqual(len(S["sleeps"]), 2)
        self.assertEqual(S["sleeps"][1], 2.0, "retry-after is honoured")

    def test_fallbacks_parameter_refused_once(self):
        S["fake"].replies = [("error", 400, "invalid_request_error", "fallbacks: Extra inputs are not permitted")]
        r, _ = self.run_week()
        reqs = S["fake"].requests()
        self.assertIn("fallbacks", reqs[0]["body"])
        self.assertNotIn("fallbacks", reqs[1]["body"])
        self.assertNotIn("anthropic-beta", reqs[1]["headers"])
        self.assertNotIn("fallbacks", reqs[2]["body"], "remembered for the rest of the run")
        self.assertEqual(len(r["written"]), 6)

    def test_auth_error_stops_the_run(self):
        set_key(api_key="sk-ant-wrong-key")
        r, lines = self.run_week()
        self.assertEqual(len(S["fake"].requests()), 1, "no retry on 401, no second batch")
        self.assertEqual(len(r["failed"]), 6)
        self.assertIn("refused", r["stop"])
        self.assertNotIn("sk-ant-wrong-key", "\n".join(lines) + json.dumps(data()) + (TMP / "copy-usage.json").read_text())
        note = next(x for x in data()["recommendations"] if x["title"] == "Copy not written yet: Bean Bros")
        self.assertEqual(note["priority"], "P1")

    def test_refusal(self):
        S["fake"].replies = [("refusal", "cyber")]
        r, _ = self.run_week()
        self.assertEqual(sorted(r["failed"]), ["bb-001", "bb-002", "bb-003", "bb-004"])
        self.assertEqual(sorted(r["written"]), ["bb-005", "bb-006"])
        day = next(iter(json.loads((TMP / "copy-usage.json").read_text())["days"].values()))
        self.assertEqual(day["refused"], 1)

    def test_cut_off_answer_is_split(self):
        S["fake"].replies = [("max_tokens",)]
        r, _ = self.run_week()
        self.assertEqual(len(r["written"]), 6)
        self.assertEqual([len(x["slots"]) for x in S["fake"].requests()], [4, 1, 1, 1, 1, 2])

    def test_concurrent_run_is_refused(self):
        with otto_copy.brand_lock("beans") as got:
            self.assertTrue(got)
            r, _ = self.run_week()
        self.assertIn("another copy run", r["skipped"])
        self.assertEqual(S["fake"].requests(), [])


class Languages(Base):
    def test_english_twin_when_the_owner_reads_english(self):
        d = data()
        ap.brand(d, "beans")["lang"] = "NL"
        (TMP / "data.json").write_text(json.dumps(d))

        def nl(body, slots, n):
            out = [FA.make(s, i) for i, s in enumerate(slots)]
            for x in out:
                x["hook_en"], x["caption_en"] = "English hook", "English caption"
            return out
        S["fake"].replies = [nl, nl]
        self.run_week()
        body = S["fake"].requests()[0]["body"]
        self.assertIn("CONTENT LANGUAGE: Dutch (nl)", body["system"][1]["text"])
        self.assertIn("OWNER LANGUAGE: English (en)", body["system"][1]["text"])
        self.assertIn("write the English translation", body["messages"][0]["content"])
        self.assertEqual(P("bb-001")["hook_en"], "English hook")
        # a Dutch owner reads Dutch: no twin
        S["fake"].reset()
        (TMP / "data.json").write_text(json.dumps(seed()))
        d = data()
        ap.brand(d, "beans").update(lang="NL", comms_lang="nl")
        (TMP / "data.json").write_text(json.dumps(d))
        S["fake"].replies = [nl, nl]
        self.run_week()
        self.assertIn("(not needed)", S["fake"].requests()[0]["body"]["messages"][0]["content"])
        self.assertNotIn("hook_en", P("bb-001"))


class Visuals(Base):
    def test_cards_deferred_without_chrome(self):
        otto_copy.can_render = lambda: False
        r, lines = self.run_week()
        self.assertEqual(len(r["written"]), 6)
        p = P("bb-001")
        self.assertEqual(p["status"], "pending_approval", "the copy does not wait for its card")
        self.assertNotIn("image", p)
        self.assertEqual(p["copy"]["render"], "pending")
        self.assertEqual(S["renders"], [])
        otto_copy.can_render = lambda: True
        lines = []
        self.assertEqual(otto_copy.render_pending(out=lines.append), 6)
        p = P("bb-002")
        self.assertTrue(p["image"] and len(p["images"]) >= 4)
        self.assertNotIn("render", p["copy"])
        self.assertEqual(otto_copy.render_pending(out=lines.append), 0)

    def test_render_failure_keeps_the_copy(self):
        def boom(*a, **k):
            raise RuntimeError("chrome crashed")
        otto_copy.render_card = boom
        r, _ = self.run_week()
        self.assertEqual(len(r["written"]), 6)
        p = P("bb-001")
        self.assertEqual(p["status"], "pending_approval")
        self.assertNotIn("image", p)
        self.assertEqual(p["copy"]["render"], "failed")
        note = next(x for x in data()["recommendations"] if x["title"] == "Post images not rendered: Bean Bros")
        self.assertIn("chrome crashed", note["why"])
        self.assertEqual(list((TMP / "assets" / "posts").glob("*.jpg")), [], "no half sets")

    def test_site_photo_and_provenance(self):
        import otto_provenance
        photos = TMP / "brands" / "beans" / "assets"
        photos.mkdir(parents=True)
        (photos / "shop.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20000)       # the renderer is faked here
        saved = otto_provenance.propagate
        otto_provenance.propagate = lambda src, dst, **kw: {"generated": True, "marked": "xmp", "kind": "image"}
        try:
            self.run_week()
        finally:
            otto_provenance.propagate = saved
        used = [x["data"].get("photo") for x in S["renders"] if x["data"].get("photo")]
        self.assertTrue(used and all(u.endswith("shop.png") for u in used))
        p = P("bb-001")
        self.assertIn(p["image"], p["media_ai"], "an AI-marked source photo carries its mark to the card")

    @unittest.skipUnless(os.environ.get("OTTO_TEST_RENDER") == "1", "real headless-Chrome render: OTTO_TEST_RENDER=1")
    def test_real_render(self):
        otto_copy.render_card = _SAVED["fns"][0]
        otto_copy.tokens = _SAVED["fns"][1]
        try:
            d = data()
            d["posts"] = [post("bb-001", "beans", 1, "post"), post("bb-002", "beans", 2, "carousel")]
            (TMP / "data.json").write_text(json.dumps(d))
            r, lines = self.run_week()
            self.assertEqual(sorted(r["written"]), ["bb-001", "bb-002"], lines)
            p = P("bb-002")
            for ref in p["images"]:
                f = TMP / "assets" / ref[len("assets/"):]
                self.assertEqual(f.read_bytes()[:3], b"\xff\xd8\xff")
        finally:
            otto_copy.tokens = lambda bid: {"lang": "en", "name": bid}


class Jobs(Base):
    def test_daily(self):
        d = data()
        d["brands"] += [brand("ended", plan="none"), brand("newbie", status="onboarding"), brand("legacy", copy_auto=None)]
        d["posts"] += [post("en-001", "ended", 1), post("nw-001", "newbie", 1), post("lg-001", "legacy", 1)]
        (TMP / "data.json").write_text(json.dumps(d))
        for bid in ("ended", "newbie", "legacy"):
            write_brand_files(bid)
        lines = []
        rs = otto_copy.daily(out=lines.append)
        by = {r["brand"]: r for r in rs}
        self.assertEqual(len(by["beans"]["written"]), 6)
        self.assertIn("ended plan", by["ended"]["skipped"])
        self.assertNotIn("newbie", by)
        self.assertNotIn("legacy", by, "a hand-written brand (no copy_auto) is never written by the daily run")
        self.assertTrue(any("legacy" in x and "by hand" in x for x in lines), lines)
        self.assertEqual(P("lg-001")["hook"], "")
        self.assertEqual(P("en-001")["hook"], "")
        self.assertEqual(otto_copy.main(["daily", "--brand", "beans"]), 0)

    def test_cron_job_and_timer(self):
        self.assertIn("copy", otto_cron.JOBS)
        j = otto_cron.JOBS["copy"]
        self.assertEqual((j.local, j.scope, j.kill), ("05:30", otto_cron.BRAND, False))
        d = {"brands": [{"id": "x", "status": "active", "copy_auto": True}, {"id": "y", "status": "active", "plan": "none", "copy_auto": True},
                        {"id": "z", "status": "active"}], "posts": [], "campaigns": []}
        ts = {t.brand: t for t in otto_cron.tasks("copy", d)}
        self.assertIn("written by hand", ts["z"].skip)
        self.assertEqual([Path(a).name if i == 1 else a for i, a in enumerate(ts["x"].argv)][1:], ["otto_copy.py", "daily", "--brand", "x"])
        self.assertIsNone(ts["x"].skip)
        self.assertIn("no active plan", ts["y"].skip)
        timer = REPO / "infra" / "systemd" / "otto-job-copy.timer"
        self.assertEqual(timer.read_text(), otto_cron.timer_text("copy"))

    def test_cli(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(otto_copy.main(["week", "--brand", "beans", "--dry"]), 0)
            self.assertEqual(otto_copy.main(["status"]), 0)
            self.assertEqual(otto_copy.main(["nonsense"]), 2)
        out = buf.getvalue()
        self.assertIn("WOULD WRITE", out)
        self.assertIn("model claude-opus-5-5", out)
        self.assertNotIn(FA.KEY, out)


class Queue(Base):
    """On the server the API cannot start Chrome: the kickoff queues the brand and otto-copy-queue.service writes and renders it."""

    def setUp(self):
        super().setUp()
        self.q = TMP / "queue" / "copy"
        shutil.rmtree(TMP / "queue", ignore_errors=True)
        os.environ["OTTO_COPY_QUEUE"] = str(self.q)

    def tearDown(self):
        os.environ.pop("OTTO_COPY_QUEUE", None)

    def test_kickoff_queues_instead_of_spawning(self):
        self.assertTrue(otto_copy.spawn_week("beans"))
        self.assertEqual(S["spawned"], [])
        self.assertEqual([f.name for f in self.q.iterdir()], ["beans.week"])
        self.assertFalse(otto_copy.spawn_week("../etc"))

    def test_queue_run_writes_and_renders_then_empties(self):
        otto_copy.spawn_week("beans")
        lines = []
        self.assertEqual(otto_copy.run_queue(out=lines.append), 1)
        self.assertEqual(list(self.q.iterdir()), [])
        self.assertEqual(P("bb-001")["status"], "pending_approval")
        self.assertTrue(S["renders"], "images rendered in the same run")
        self.assertEqual(otto_copy.run_queue(out=lines.append), 0)

    def test_without_a_queue_dir_nothing_runs(self):
        os.environ.pop("OTTO_COPY_QUEUE", None)
        self.assertEqual(otto_copy.run_queue(), 0)


class SelfServeFlag(unittest.TestCase):
    def test_onboarding_marks_new_brands_for_the_copywriter(self):
        src = (REPO / "platform" / "otto_onboard.py").read_text()
        self.assertIn('"copy_auto": True', src)


if __name__ == "__main__":
    unittest.main()
