"""A stand-in for the Stripe API, for tests/test_stripe.py and tests/test_journey.py (not a test module itself).

FakeStripe runs a 127.0.0.1 HTTP server that speaks enough of api.stripe.com for otto_stripe: form-encoded requests with a
Bearer key and a pinned Stripe-Version, JSON answers, Stripe's error shape. It keeps Checkout Sessions, Customers (tax IDs,
default payment method), Subscriptions (items, schedules, cancel at period end), SetupIntents, Invoices and the read-only
objects of the setup check (account, tax settings, prices, webhook endpoints). Every request is logged (method, path, the
flat form params, headers) so a test can assert the exact request shape. complete() plays the customer finishing a
Checkout Session: it creates the Customer and the Subscription (or the paid one-time payment) the way Stripe would and
returns the objects a webhook would carry; event() wraps an object into a Stripe event.
Stdlib only; no network beyond 127.0.0.1.
"""
import http.server, itertools, json, threading, time, urllib.parse

KEY = "sk_test_otto_fake_do_not_use"
PRICES = {"price_starter_m": (7900, "month"), "price_starter_y": (79000, "year"), "price_growth_m": (24900, "month"),
          "price_growth_y": (249000, "year"), "price_founding": (19700, None)}


class FakeStripe:
    def __init__(self):
        self.log, self.n = [], itertools.count(1)
        self.sessions, self.customers, self.subs, self.schedules, self.setups, self.invoices = {}, {}, {}, {}, {}, {}
        self.tax_ids = {}                     # customer → [tax id objects]
        self.fail_next = None                 # (status, message, code): the next request answers this error
        self.tax_status, self.branding = "active", True
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _go(self, method):
                u = urllib.parse.urlsplit(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode() if n else (u.query or "")
                params = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
                me.log.append({"method": method, "path": u.path, "params": params, "headers": dict(self.headers)})
                if self.headers.get("Authorization") != f"Bearer {KEY}":
                    return self._answer(401, {"error": {"type": "invalid_request_error", "message": "Invalid API Key provided"}})
                if me.fail_next:
                    st, msg, code = me.fail_next
                    me.fail_next = None
                    return self._answer(st, {"error": {"type": "invalid_request_error", "message": msg, "code": code}})
                try:
                    code, obj = me.route(method, u.path, params)
                except KeyError as e:
                    code, obj = 404, {"error": {"type": "invalid_request_error", "code": "resource_missing",
                                                "message": f"No such object: '{e.args[0]}'"}}
                self._answer(code, obj)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

            def do_DELETE(self):
                self._go("DELETE")

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    # ---------------- helpers for the tests ----------------

    def id(self, prefix):
        return f"{prefix}_{next(self.n):04d}"

    def calls(self, method=None, path=None):
        return [c for c in self.log if (method is None or c["method"] == method) and (path is None or c["path"].startswith(path))]

    def last(self, method, path):
        x = self.calls(method, path)
        return x[-1] if x else None

    @staticmethod
    def sub_params(params, prefix):
        """{"a[b]": v} → the part under prefix as a flat dict without it."""
        return {k[len(prefix):]: v for k, v in params.items() if k.startswith(prefix)}

    def customer(self, email, pm="card"):
        cid = self.id("cus")
        pmo = {"id": self.id("pm"), "type": "card", "card": {"brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030}} if pm == "card" \
            else {"id": self.id("pm"), "type": "sepa_debit", "sepa_debit": {"last4": "3000"}}
        self.customers[cid] = {"id": cid, "object": "customer", "email": email, "name": "Koffie Zon B.V.",
                               "address": {"country": "NL"}, "invoice_settings": {"default_payment_method": None}, "_pm": pmo}
        self.tax_ids[cid] = [{"id": self.id("txi"), "type": "eu_vat", "value": "NL123456789B01", "verification": {"status": "verified"}}]
        return cid

    def complete(self, session_id, status=None, pm="card"):
        """The customer pays a Checkout Session. → (session object, subscription object or None)."""
        s = self.sessions[session_id]
        p = s["_params"]
        cus = p.get("customer") or self.customer(p.get("customer_email"), pm)
        s.update(status="complete", customer=cus, customer_details={"email": self.customers[cus]["email"], "name": "Koffie Zon B.V."})
        price = p["line_items[0][price]"]
        amount, interval = PRICES[price]
        now = int(time.time())
        if p["mode"] == "payment":
            s.update(payment_status="paid" if pm == "card" else "unpaid", payment_intent=self.id("pi"), amount_total=amount, currency="eur",
                     invoice=self.id("in"))
            return dict(s), None
        sid = self.id("sub")
        trial_end = int(p["subscription_data[trial_end]"]) if p.get("subscription_data[trial_end]") else (
            now + 86400 * int(p["subscription_data[trial_period_days]"]) if p.get("subscription_data[trial_period_days]") else None)
        meta = self.sub_params(p, "subscription_data[metadata][")
        meta = {k.rstrip("]"): v for k, v in meta.items()}
        sub = {"id": sid, "object": "subscription", "status": status or ("trialing" if trial_end else "active"), "customer": cus,
               "start_date": now, "created": now, "trial_end": trial_end, "cancel_at_period_end": False, "cancel_at": None,
               "canceled_at": None, "ended_at": None, "metadata": meta, "schedule": None, "currency": "eur", "latest_invoice": None,
               "default_payment_method": self.customers[cus]["_pm"],
               "items": {"object": "list", "data": [{"id": self.id("si"), "quantity": 1, "current_period_end": (trial_end or now) + 30 * 86400,
                                                      "price": self._price(price)}]}}
        self.subs[sid] = sub
        s.update(subscription=sid, payment_status="paid" if not trial_end else "no_payment_required")
        return dict(s), json.loads(json.dumps(sub))

    def _price(self, price):
        amount, interval = PRICES[price]
        return {"id": price, "object": "price", "unit_amount": amount, "currency": "eur", "active": True, "tax_behavior": "exclusive",
                "recurring": {"interval": interval} if interval else None, "type": "recurring" if interval else "one_time"}

    def invoice(self, sub_id, status="paid", reason="subscription_cycle"):
        sub = self.subs[sub_id]
        iid = self.id("in")
        it = sub["items"]["data"][0]
        inv = {"id": iid, "object": "invoice", "customer": sub["customer"], "status": status, "billing_reason": reason,
               "amount_paid": it["price"]["unit_amount"] if status == "paid" else 0, "amount_due": it["price"]["unit_amount"],
               "total": it["price"]["unit_amount"], "currency": "eur", "number": f"OTTO-{iid[-4:]}", "created": int(time.time()),
               "hosted_invoice_url": f"https://invoice.stripe.com/i/{iid}", "invoice_pdf": f"https://pay.stripe.com/invoice/{iid}/pdf",
               "status_transitions": {"paid_at": int(time.time()) if status == "paid" else None},
               "parent": {"type": "subscription_details", "subscription_details": {"subscription": sub_id}},
               "customer_email": self.customers[sub["customer"]]["email"]}
        self.invoices[iid] = inv
        sub["latest_invoice"] = iid
        return dict(inv)

    def event(self, etype, obj, created=None):
        return {"id": self.id("evt"), "object": "event", "type": etype, "created": int(created or time.time()), "livemode": False,
                "api_version": "2025-03-31.basil", "data": {"object": obj}}

    # ---------------- the API ----------------

    def route(self, method, path, p):
        parts = path.strip("/").split("/")[1:]                # drop "v1"
        if parts == ["checkout", "sessions"] and method == "POST":
            sid = self.id("cs_test")
            s = {"id": sid, "object": "checkout.session", "mode": p.get("mode"), "status": "open", "client_reference_id": p.get("client_reference_id"),
                 "metadata": {k[len("metadata["):-1]: v for k, v in p.items() if k.startswith("metadata[")}, "customer": p.get("customer"),
                 "customer_email": p.get("customer_email"), "created": int(time.time()), "_params": p,
                 "client_secret": f"{sid}_secret_fake" if p.get("ui_mode") == "embedded" else None,
                 "url": None if p.get("ui_mode") == "embedded" else f"https://checkout.stripe.com/c/pay/{sid}"}
            self.sessions[sid] = s
            return 200, {k: v for k, v in s.items() if not k.startswith("_")}
        if parts[:2] == ["checkout", "sessions"] and len(parts) == 3:
            s = self.sessions[parts[2]]
            return 200, {k: v for k, v in s.items() if not k.startswith("_")}
        if parts[:1] == ["subscriptions"] and len(parts) == 2:
            sub = self.subs[parts[1]]
            if method == "POST":
                if p.get("items[0][price]"):
                    if p.get("items[0][id]") != sub["items"]["data"][0]["id"]:
                        return 400, {"error": {"type": "invalid_request_error", "message": "a second item would be added"}}
                    sub["items"]["data"][0]["price"] = self._price(p["items[0][price]"])
                if "cancel_at_period_end" in p:
                    if sub.get("schedule"):
                        return 400, {"error": {"type": "invalid_request_error", "message": "managed by a subscription schedule"}}
                    sub["cancel_at_period_end"] = p["cancel_at_period_end"] == "true"
                if p.get("default_payment_method"):
                    sub["default_payment_method"] = {"id": p["default_payment_method"], "type": "card",
                                                     "card": {"brand": "mastercard", "last4": "4444", "exp_month": 1, "exp_year": 2031}}
            out = json.loads(json.dumps(sub))
            if p.get("expand[0]") == "latest_invoice" and sub.get("latest_invoice"):
                out["latest_invoice"] = dict(self.invoices[sub["latest_invoice"]])
            return 200, out
        if parts == ["subscription_schedules"] and method == "POST":
            sub = self.subs[p["from_subscription"]]
            sc = {"id": self.id("sub_sched"), "object": "subscription_schedule", "subscription": sub["id"],
                  "phases": [{"start_date": sub["start_date"], "end_date": sub["items"]["data"][0]["current_period_end"],
                              "trial_end": sub["trial_end"], "items": [{"price": sub["items"]["data"][0]["price"]["id"], "quantity": 1}]}]}
            self.schedules[sc["id"]] = sc
            sub["schedule"] = sc["id"]
            return 200, sc
        if parts[:1] == ["subscription_schedules"] and len(parts) == 3 and parts[2] == "release":
            sc = self.schedules[parts[1]]
            self.subs[sc["subscription"]]["schedule"] = None
            sc["status"] = "released"
            return 200, sc
        if parts[:1] == ["subscription_schedules"] and len(parts) == 2:
            sc = self.schedules[parts[1]]
            sc["_update"] = p
            return 200, sc
        if parts == ["setup_intents"] and method == "POST":
            si = {"id": self.id("seti"), "object": "setup_intent", "customer": p.get("customer"), "status": "requires_payment_method",
                  "metadata": {k[len("metadata["):-1]: v for k, v in p.items() if k.startswith("metadata[")}}
            si["client_secret"] = si["id"] + "_secret_fake"
            self.setups[si["id"]] = si
            return 200, si
        if parts[:1] == ["customers"] and len(parts) == 2:
            c = self.customers[parts[1]]
            if method == "POST" and p.get("invoice_settings[default_payment_method]"):
                c["invoice_settings"]["default_payment_method"] = p["invoice_settings[default_payment_method]"]
            out = {k: v for k, v in c.items() if not k.startswith("_")}
            if p.get("expand[0]") == "invoice_settings.default_payment_method" and c["invoice_settings"]["default_payment_method"]:
                out["invoice_settings"] = {"default_payment_method": dict(c["_pm"], id=c["invoice_settings"]["default_payment_method"])}
            out["tax_ids"] = {"object": "list", "data": list(self.tax_ids.get(c["id"], []))}
            return 200, out
        if parts[:1] == ["customers"] and len(parts) >= 3 and parts[2] == "tax_ids":
            lst = self.tax_ids.setdefault(parts[1], [])
            if method == "GET":
                return 200, {"object": "list", "data": list(lst)}
            if method == "POST":
                t = {"id": self.id("txi"), "type": p["type"], "value": p["value"], "verification": {"status": "pending"}}
                lst.append(t)
                return 200, t
            if method == "DELETE":
                self.tax_ids[parts[1]] = [t for t in lst if t["id"] != parts[3]]
                return 200, {"id": parts[3], "deleted": True}
        if parts == ["invoices"] and method == "GET":
            data = sorted([i for i in self.invoices.values() if i["customer"] == p.get("customer")], key=lambda i: -i["created"])
            return 200, {"object": "list", "data": data[:int(p.get("limit") or 10)]}
        if parts[:1] == ["invoices"] and len(parts) == 3 and parts[2] == "pay":
            inv = self.invoices[parts[1]]
            inv.update(status="paid", amount_paid=inv["amount_due"])
            return 200, inv
        if parts == ["billing_portal", "sessions"]:
            return 200, {"id": self.id("bps"), "url": f"https://billing.stripe.com/p/session/{self.id('x')}", "customer": p.get("customer")}
        if parts == ["account"]:
            return 200, {"id": "acct_fake", "country": "NL", "default_currency": "eur", "business_profile": {"name": "Otto"},
                         "settings": {"branding": {"icon": "file_1", "logo": "file_2", "primary_color": "#2447F0"} if self.branding else {}}}
        if parts == ["tax", "settings"]:
            return 200, {"object": "tax.settings", "status": self.tax_status}
        if parts[:1] == ["prices"] and len(parts) == 2:
            return 200, self._price(parts[1]) if parts[1] in PRICES else (_ for _ in ()).throw(KeyError(parts[1]))
        if parts == ["webhook_endpoints"]:
            return 200, {"object": "list", "data": [{"id": "we_1", "url": "https://otto.example/hooks/stripe", "status": "enabled",
                                                     "enabled_events": ["*"]}]}
        raise KeyError(path)
