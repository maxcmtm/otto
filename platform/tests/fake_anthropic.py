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
Stdlib only; no network beyond 127.0.0.1.
"""
import http.server, itertools, json, re, threading

KEY = "sk-ant-test-otto-fake-do-not-use"
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
                posts = r(body, slots, k) if callable(r) else [make(s, i + 7 * k) for i, s in enumerate(slots)]
                return self._answer(200, me.message(body, json.dumps({"posts": posts})))

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
