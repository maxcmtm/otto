"""A stand-in for the Claude Messages API, for tests/test_copy.py (not a test module itself).

FakeAnthropic runs a 127.0.0.1 HTTP server that speaks enough of api.anthropic.com for otto_copy: POST /v1/messages with
x-api-key + anthropic-version, the JSON body (model, system, messages, output_config, thinking, fallbacks) and Anthropic's
error shape. Every request is logged (path, headers, parsed body, the slots the user turn asked for) so a test can assert
the exact request. By default it answers every requested slot with a clean, valid post (structured-output JSON in a text
block after an empty thinking block); `replies` queues special answers for the next requests:
  callable(body, slots, n) → list of post dicts          the posts (use make(slot) for a valid default and edit it)
  ("error", status, type, message[, headers])            an API error
  ("text", "…")                                          a message whose text block is this (bad JSON, prose, …)
  ("refusal", category)                                  stop_reason refusal
  ("max_tokens",)                                        stop_reason max_tokens, half a JSON
A callable may also return a dict: it is sent as the whole JSON answer (the ad requests: {"angle", "cells"} / {"angles"}).
The ad copywriter's requests (otto_copy.write_ads — told apart by their JSON schema) get clean defaults too: make_angles
answers an angles.json build ({"angles": [...]}, one per <existing> id and per new id), make_ad a matrix concept
({"angle": {...}, "cells": [...]} for every cell in <cells>, data in the style's or the video kit's shape).
Stdlib only; no network beyond 127.0.0.1.
"""
import http.server, itertools, json, re, threading

KEY = "fake-anthropic-key-otto-tests-do-not-use"
HOOKS = ["Fresh beans show their roast date", "Grind just before you brew", "Why your coffee tastes flat at home",
         "The water matters more than you think", "A slower pour makes a sweeter cup", "Store beans away from the light",
         "What a medium roast really means", "Two spoons, one minute, better coffee", "The bag tells you how it was roasted",
         "Cold brew is not iced coffee", "Your grinder decides the taste", "Brewing for a crowd without the stress"]


def slots_of(body):
    text = ""
    for m in body.get("messages") or []:
        c = m.get("content")
        text += c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
    m = re.search(r"<slots>\s*(.*?)\s*</slots>", text, re.S)
    return json.loads(m.group(1)) if m else []


def make(slot, i=0):
    """A clean post for one requested slot (no numbers above ten, no quotes, no claims, no banned words)."""
    fmt = slot.get("format") or "post"
    hook = HOOKS[i % len(HOOKS)]
    p = {"id": slot["id"], "hook": hook, "accent": hook.split()[-1], "kicker": "Brew guide", "cta_text": "Shop beans",
         "caption": f"{hook}.\n\nMost bags hide it. Ours print it on the front, so you know what you are drinking.\n\n"
                    "Pick a bag in the webshop and taste the difference this week.",
         "hashtags": ["#specialtycoffee", "#coffeeathome", "#utrechtcoffee"], "card_sub": "Small batches, roasted in Utrecht.",
         "slides": [], "closing": "", "script": [], "why": "Shows first-time buyers what makes the beans different.",
         "visual_brief": "A bag of beans on a wooden counter, morning light.", "hook_type": "mistake", "angle_id": "",
         "persona_id": "", "stage": "cold", "facts_used": ["Roasted in Utrecht"], "hook_en": "", "caption_en": ""}
    if fmt == "carousel":
        p["slides"] = [{"title": hook, "body": ""}, {"title": "Check the roast date", "body": "Fresh beans taste brighter."},
                       {"title": "Grind at home", "body": "Ground coffee goes flat within days."},
                       {"title": "Use good water", "body": "Filtered water lets the beans speak."}]
        p["closing"] = "Ready for a better cup?"
    if fmt == "reel":
        p["script"] = [{"text": hook, "seconds": 6, "visual": "Close-up of a coffee bag label."},
                       {"text": "Look for the roast date on the front.", "seconds": 7, "visual": "A finger points at the date."},
                       {"text": "Grind just before you brew.", "seconds": 7, "visual": "A hand grinder turning."},
                       {"text": "Then taste the difference.", "seconds": 6, "visual": "A steaming cup on the counter."},
                       {"text": "Find our beans in the webshop.", "seconds": 6, "visual": "The bag next to the cup."}]
    return p


def user_text(body):
    text = ""
    for m in body.get("messages") or []:
        c = m.get("content")
        text += c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
    return text


def ad_kind(body):
    """"ad" (a matrix concept), "angles" (an angles.json build) or None (posts) — from the request's JSON schema."""
    props = ((((body.get("output_config") or {}).get("format") or {}).get("schema") or {}).get("properties") or {})
    return "ad" if "cells" in props else "angles" if "angles" in props else None


def block(body, tag):
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", user_text(body), re.S)
    return json.loads(m.group(1)) if m else None


AD_HEADLINES = ["Read the roast date first", "Fresh beans, dated bags", "Coffee that tells you its age", "Roasted in Utrecht"]
AD_PRIMARIES = ["Every bag shows its roast date, so you know how fresh your coffee is before you open it.",
                "Coffee tastes flat at home? Start with beans that show their roast date on the front.",
                "Small batches, roasted in Utrecht since 2014.\nPick a bag in the webshop."]
RSA = (["Fresh Coffee Beans", "Roasted in Utrecht", "Roast Date on Every Bag", "Small-Batch Coffee"],
       ["Every bag shows its roast date. Order fresh beans from the Utrecht roastery.",
        "Small batches, roasted in Utrecht since 2014."])
END = {"headline": "Fresh beans, dated bags.", "accent": "dated bags.", "sub": "Roasted in Utrecht.", "fine": "", "legal": ""}
AD_DATA = {
    "notes_app": {"title": "Before I buy coffee", "items": ["Check the roast date", "Smell the beans", "Grind at home"], "mode": "checklist",
                  "photo": "invented.png", "theme": "dark"},
    "search": {"query": "fresh coffee beans", "suggestions": ["fresh coffee beans utrecht", "fresh coffee beans roast date",
                                                              "fresh coffee beans subscription"], "headline": "Looking for *fresh beans*?"},
    "text_message": {"contact": "Bean Bros", "messages": [{"from": "me", "text": "Do your bags show the roast date?"},
                                                          {"from": "them", "text": "Every bag, right on the front."}]},
    "social_post": {"name": "Bean Bros", "text": "Every bag shows its roast date. Roasted in Utrecht."},
    "big_number": {"number": "2014", "label": "Roasting small batches in Utrecht since", "kicker": "Since"},
    "us_vs_them": {"headline": "Know *when* it was roasted", "us": {"name": "Bean Bros"}, "them": {"name": "Supermarket coffee"},
                   "rows": [{"label": "Roast date on the bag", "us": True, "them": False},
                            {"label": "Roasted in Utrecht", "us": True, "them": "Unknown"},
                            {"label": "Small batches", "us": True, "them": "Varies"}]},
    "comparison": {"title": "Supermarket or *fresh*?", "columns": [{"name": "Supermarket"}, {"name": "Bean Bros", "highlight": True}],
                   "rows": [{"label": "Roast date on the bag", "values": ["no", "yes"]}, {"label": "Small batches", "values": ["no", "yes"]},
                            {"label": "Roasted in Utrecht", "values": ["no", "yes"]}]},
    "before_after": {"before": "Flat coffee from an old bag", "after": "A fresh bag with its roast date", "kicker": "Mornings"},
    "offer": {"name": "Yearly subscription", "price": "€ 79", "cta": "Subscribe", "features": ["Fresh beans", "Roast date on every bag"]},
    "myth_fact": {"myth": "All coffee beans taste the same.", "fact": "Fresh beans show their roast date, and you can taste it.",
                  "source": "Roasted in Utrecht since 2014"},
    "checklist": {"title": "3 things to check before you buy beans", "items": ["The roast date", "Where it was roasted", "Whole beans"]},
    "carousel": {"cover": {"headline": "How to read a coffee bag"}, "slides": [{"title": "The roast date", "body": "Fresh beans taste brighter."},
                                                                               {"title": "Where it was roasted"}],
                 "end": {"headline": "Ready for a better cup?", "cta": "Shop beans"}},
    "editorial": {"headline": "Fresh beans, *dated* bags"},
    "product_hero": {"headline": "Fresh beans, *dated* bags", "callouts": ["Roast date on the front", "Roasted in Utrecht"]},
    "macro_hero": {"word": "*Fresh*", "sub": "Every bag shows its roast date"},
    "quote": {"quote": "Best beans in town, every single time.", "name": "Kim"},
    "review_cards": {"reviews": [{"text": "Best beans in town, every single time.", "name": "Kim"}]},
}
KIT_DATA = {
    "notes": {"note": {"meta": "Sunday, 9:40", "title": "Coffee rules", "struck": ["beans without a date", "pre-ground bags", "flat mornings"],
                       "keep": "the roast date on the front"}},
    "search": {"search": {"placeholder": "Search", "query": "fresh coffee beans", "suggestions": ["fresh coffee beans utrecht",
                                                                                                  "fresh coffee beans roast date"],
                          "pick": 1, "result": {"site": "Bean Bros", "url": "Specialty coffee roasters", "title": "Fresh roasted coffee",
                                                "snippet": "Every bag shows its roast date.", "image": "pack"}}},
    "texts": {"thread": {"name": "Bean Bros", "initial": "B", "stamp": "Today 9:14", "placeholder": "Message",
                         "messages": [{"from": "me", "text": "Do your bags show the roast date?"},
                                      {"from": "them", "text": "Every bag, right on the front."},
                                      {"from": "me", "text": "And where is it roasted?"},
                                      {"from": "them", "text": "In Utrecht, in small batches."}]}},
    "versus": {"versus": {"vs": "vs", "left": {"label": "Supermarket bag", "rows": ["No roast date", "Pre-ground", "Flat taste"], "illo": "tub"},
                          "right": {"label": "Bean Bros", "rows": ["Roast date on the front", "Whole beans", "Bright taste"]},
                          "footer": "Read the date."}},
    "big": {"big": {"hero": "pack", "phrases": [{"big": "Small", "rest": "batches."}, {"big": "Dated", "rest": "bags."},
                                                {"big": "Utrecht", "rest": "since 2014."}]}},
    "reel": {"vo": ["Every bag shows its roast date.", "Small batches, roasted in Utrecht.", "Pick a bag in the webshop."],
             "lines": ["Roast date on every bag", "Roasted in Utrecht", "In the webshop"]},
}
CREATOR = {"hook": "Show the roast date on the front of the bag", "script": ["Show the bag and point at the roast date",
                                                                             "Say in your own words how you brew your morning coffee",
                                                                             "Grind the beans on camera"],
           "shot_list": ["Close-up of the roast date", "Hands grinding the beans", "The cup on the counter"]}


def cell_data(c):
    if c.get("format") == "creator":
        return dict(CREATOR)
    if c.get("format") == "video":
        return dict(json.loads(json.dumps(KIT_DATA.get(c.get("kit"), KIT_DATA["notes"]))), endcard=dict(END))
    return json.loads(json.dumps(AD_DATA.get(c.get("style"), {"headline": "Fresh beans, dated bags"})))


def make_ad(body):
    """A clean answer to a matrix-concept request: the concept's copy + every cell in <cells>."""
    concept = block(body, "concept") or {}
    cells = block(body, "cells") or []
    rsa = "rsa_headlines (4-5)" in user_text(body)
    angle = {"id": concept.get("id", ""), "headlines": AD_HEADLINES[:2], "primaries": list(AD_PRIMARIES), "description": "Roasted in Utrecht",
             "cta": "SHOP_NOW", "rsa_headlines": RSA[0] if rsa else [], "rsa_descriptions": RSA[1] if rsa else [],
             "proof": "Roasted in Utrecht since 2014", "why": "Shows first-time buyers what makes the beans different.",
             "facts_used": ["Roasted in Utrecht since 2014"]}
    return {"angle": angle, "cells": [{"id": c["id"], "data_json": json.dumps(cell_data(c)), "why": "The roast date as proof.",
                                       "facts_used": []} for c in cells]}


NOTES = {"pain": "Coffee tastes flat at home: the beans were roasted long ago, and the bag never says when.",
         "identity": "For home baristas who brew every morning and want beans that show their roast date.",
         "enemy": "Supermarket bags without a roast date against dated small-batch bags from Utrecht.",
         "offer": "The yearly subscription (€ 79): fresh beans with the roast date on every bag.",
         "experience": "A morning with fresh beans: grind, brew and taste the difference.",
         "moment": "The new roast of the month."}


def make_angles(body):
    """A clean answer to an angles.json build: ad copy for every <existing> id, one concept per new "nK: family"."""
    text = user_text(body)
    rsa = "rsa_headlines (4-5" in text
    out = []
    ids = [(x["id"], x.get("family") or "pain", None) for x in block(body, "existing") or []]
    m = re.search(r"new concepts, one per family \(id: family\): ([^\n]*)", text)
    ids += [(k, fam, True) for k, fam in re.findall(r"(n\d+): (\w+)", m.group(1))] if m else []
    for i, (k, fam, new) in enumerate(ids):
        out.append({"id": k, "angle": NOTES.get(fam, NOTES["pain"]) if new else "", "family": fam if fam in NOTES else "pain",
                    "stage": "hot" if fam == "offer" else "cold", "persona": "p1" if fam == "identity" else "",
                    "from_competitors": fam == "enemy", "headline": AD_HEADLINES[i % len(AD_HEADLINES)],
                    "primary": AD_PRIMARIES[i % len(AD_PRIMARIES)], "description": "Roasted in Utrecht",
                    "proof": "Roasted in Utrecht since 2014", "rsa_headlines": RSA[0] if rsa else [],
                    "rsa_descriptions": RSA[1] if rsa else [], "why": "A concept the brand's data backs.", "facts_used": []})
    return {"angles": out}


class FakeAnthropic:
    def __init__(self):
        self.log, self.replies, self.n = [], [], itertools.count(1)
        self.usage = {"input_tokens": 1500, "output_tokens": 900, "cache_creation_input_tokens": 400, "cache_read_input_tokens": 0}
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, code, obj, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode("utf-8") if n else ""
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {}
                slots = slots_of(body)
                k = next(me.n)
                me.log.append({"path": self.path, "headers": {h.lower(): v for h, v in self.headers.items()}, "body": body,
                               "slots": slots, "n": k})
                if self.path != "/v1/messages":
                    return self._answer(404, {"type": "error", "error": {"type": "not_found_error", "message": "Not found"}})
                if self.headers.get("x-api-key") != KEY:
                    return self._answer(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
                if self.headers.get("anthropic-version") != "2023-06-01":
                    return self._answer(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "anthropic-version"}})
                r = me.replies.pop(0) if me.replies else None
                if isinstance(r, tuple) and r[0] == "error":
                    return self._answer(r[1], {"type": "error", "error": {"type": r[2], "message": r[3]}}, r[4] if len(r) > 4 else None)
                if isinstance(r, tuple) and r[0] == "text":
                    return self._answer(200, me.message(body, r[1]))
                if isinstance(r, tuple) and r[0] == "refusal":
                    m = me.message(body, "")
                    m.update(stop_reason="refusal", stop_details={"type": "refusal", "category": r[1], "explanation": "declined"})
                    return self._answer(200, m)
                if isinstance(r, tuple) and r[0] == "max_tokens":
                    m = me.message(body, '{"posts": [{"id": "')
                    m["stop_reason"] = "max_tokens"
                    return self._answer(200, m)
                kind = ad_kind(body)
                if callable(r):
                    posts = r(body, slots, k)
                elif kind == "ad":
                    posts = make_ad(body)
                elif kind == "angles":
                    posts = make_angles(body)
                else:
                    posts = [make(s, i + 7 * k) for i, s in enumerate(slots)]
                return self._answer(200, me.message(body, json.dumps(posts if isinstance(posts, dict) else {"posts": posts})))

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def message(self, body, text):
        return {"id": f"msg_fake_{len(self.log)}", "type": "message", "role": "assistant", "model": body.get("model") or "claude-x",
                "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}],
                "stop_reason": "end_turn", "stop_sequence": None, "stop_details": None, "usage": dict(self.usage)}

    def requests(self):
        return [x for x in self.log if x["path"] == "/v1/messages"]

    def reset(self):
        self.log.clear()
        self.replies.clear()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
