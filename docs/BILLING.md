# Billing — Stripe as the payment processor, everything else Otto's own

Decision 1 Oct 2026 (Max): clients are not sent to Whop. Otto sells its plans itself; **Stripe only processes the
payments**. The client never leaves Otto's site in the normal flow: they pay inside Otto's own Billing page
(`app.<domain>/billing.html`), manage their plan there, and only receipts / invoices come from Stripe (branded as Otto).
Whop stays only for the founding seats already bought on it (legacy, read-only).

## How it works

| Piece | What it does |
|---|---|
| `platform/otto_billing.py` | Provider-agnostic layer. `billing.json` (customers / subscriptions, payments, accounts brand → Stripe customer, the processed-event list). Entitlement: a running subscription (active / trialing / past_due) gives its brand the plan whose `stripe_price_ids` holds the price (`ap.set_plan`: clears `plan_until` and "not billed yet", converts the free trial, the payer becomes a member and the user "active"); canceled / unpaid → plan `none` + an owner card; incomplete / expired never touch a plan. MRR / ARPU / churn / LTV for the console. Records from before the `provider` field are read as Whop (nothing rewrites them). |
| `platform/otto_stripe.py` | The Stripe integration (stdlib: urllib + hmac). Checkout Sessions, the webhook, our own account management, the setup check. |
| `platform/billing.html` | The Billing page: choose a plan, pay (Stripe Embedded Checkout mounted in the page), confirm, then manage — plan and next charge, change plan, cancel / resume, payment method (Stripe Payment Element + SetupIntent), VAT ID, invoices. The only page that loads Stripe.js; its CSP allows exactly `js.stripe.com`, Stripe's frames and `api.stripe.com`. |
| `platform/otto_whop.py` | LEGACY: keeps the Whop founders readable and in sync (their webhook at `/hooks/whop`). No Whop checkout is offered anywhere. |

**Why Embedded Checkout (and the Payment Element only for "update payment method").** Both keep Otto at PCI SAQ A
(card data is entered in Stripe iframes and never touches our server). Embedded Checkout gives, with no custom code:
SCA / 3-D Secure, SEPA Direct Debit mandates, iDEAL and Bancontact for subscriptions (they set up SEPA Direct Debit for the
renewals), Stripe Tax, the VAT ID field with validation, the billing address, the trial start date and the one-time
founding payment. The Payment Element + Subscriptions API route would need us to build the address form, the VAT ID
handling and validation, the tax preview before the subscription exists, and the "incomplete" subscription states — more
code on our side for the same result. Saving a new payment method needs neither tax nor an address, so there the
SetupIntent + Payment Element is the smallest piece. `"checkout_ui": "hosted"` in stripe.json falls back to Stripe's hosted
page (a redirect) if the embedded form ever cannot be used.

### Paying (`POST /billing/checkout {plan, interval, brand}`, signed in with Google)

- Subscription mode for `plans.json` `<plan>.stripe_price_ids.monthly` / `.yearly`; payment mode for the founding seat
  (`founding.stripe_price_ids.one_time`, off while null: the landing hides its line, `GET /billing/offers` says so).
- `client_reference_id` (and metadata on the session, the subscription, the payment) = our **signed reference**
  (HMAC of brand + user). The webhook links the payment to exactly that brand — no e-mail guessing. Paid before the brand
  existed (founding seat from the landing): linked at onboarding by the user id in the reference.
- `customer_email` = the verified Google e-mail (locked); once the brand has a Stripe customer, that customer is passed
  (`customer_update` address + name = auto).
- `payment_method_types` card, sepa_debit, ideal, bancontact (`"payment_method_types": []` in stripe.json = whatever is on
  in the Dashboard). `billing_address_collection` required, `tax_id_collection` on (optionally required:
  `"require_tax_id": true`), `automatic_tax` on, a business-only note above the pay button.
- No Stripe trial — but a brand still inside Otto's 7-day trial starts its subscription **at the trial's end**
  (`subscription_data.trial_end`; under 48 hours left, Stripe's minimum, `trial_period_days` rounded up). Nobody is ever
  charged early; cancelling before the trial ends costs nothing.
- `return_url` = `billing.html?session_id={CHECKOUT_SESSION_ID}`: the page polls `GET /billing/status` until **the webhook**
  has switched the plan on. A browser redirect never changes any state.

### Webhook (`POST /hooks/stripe`, public on the apex only)

`Stripe-Signature: t=…,v1=…` = HMAC-SHA256(endpoint secret, `t.raw body`); any secret in `webhook_secrets` (rotation) and any
`v1` may match; more than 5 minutes off is refused; each event id is applied once; everything is an upsert, so a retry
after a failure half-way is safe; an older event never overwrites a newer state (Stripe does not promise order).

| Event | Effect |
|---|---|
| `checkout.session.completed` | Records the customer / subscription and the brand → customer account; reads the subscription from Stripe if its own event has not arrived yet; links by the signed reference. One-time seat: active when paid. |
| `checkout.session.async_payment_succeeded` / `_failed` | One-time seat paid by SEPA: active / never started. |
| `customer.subscription.created` / `.updated` / `.deleted` | Status, price → plan, interval, amount, next charge, trial end, cancel at period end, pending change → the brand's plan (`otto_billing.sync_plan`). |
| `invoice.paid` | Payment record with number, hosted invoice and PDF links; a past-due subscription is active again. |
| `invoice.payment_failed`, `invoice.payment_action_required` | Payment failed → past_due: a red banner in the app (Account + top line) and on the Billing page, one owner card per invoice. Publishing continues while Stripe retries. After the last retry Stripe cancels → `customer.subscription.deleted` → plan `none` (publishing pauses, data kept 90 days). |
| `charge.refunded` | Refund recorded (LTV / revenue); a full refund of the one-time founding seat ends it. |
| `setup_intent.succeeded` | The new payment method from the Billing page becomes the default (customer + subscription); an open invoice of a past-due subscription is retried at once. |

### Managing (Otto's own pages, not Stripe's Customer Portal)

`GET /billing/account?brand=` (plan, next charge, pending change, payment method, VAT ID, invoices live from Stripe with a
60-second cache, the plans on sale), `POST /billing/change` (a higher plan or monthly → yearly: now, prorated and invoiced at
once, applied only once paid — `payment_behavior=pending_if_incomplete`; a lower plan or yearly → monthly: at the end of the
period through a subscription schedule; the current plan again = keep it), `/billing/cancel` (at period end) and
`/billing/resume`, `/billing/payment-method` (SetupIntent), `/billing/tax-id` (replace the VAT ID), `/billing/portal`
(Stripe's Customer Portal: only with `"portal_fallback": true`, off by default). All `/billing/*`: a Google session only,
the caller's own brands only (404 otherwise), JSON + an allowed Origin for POSTs, 30 writes per 10 minutes per user,
503 "Payments aren't set up yet" without `stripe.json`.

## What Max sets up in Stripe

0. **Which company sells Otto.** A Stripe account belongs to a business established in a
   [Stripe-supported country](https://stripe.com/global). **Israel is not supported**, so the seller has to be an entity in a
   supported country (for example a Dutch B.V., an Irish Ltd, an Estonian OÜ or a US LLC). That choice also decides the VAT
   set-up below, the company details on the invoices and the legal pages ([COMPANY LEGAL NAME] etc.). [DECISION: Max, with the
   accountant.]
1. **Account**: business details, default currency **EUR**, payout bank account in EUR, statement descriptor `OTTO`
   (Settings → Business → Public details: name "Otto", support e-mail, website).
2. **Branding** (Settings → Business → Branding): icon + logo, brand colour `#2447F0`, accent `#10182B`. This styles the
   embedded form, receipts and invoices. Settings → Customer emails: successful payments and refunds **on** (receipts come
   from Stripe in Otto's branding). Optional: Settings → Custom domains (e.g. `pay.<domain>`) so invoice links show our domain.
3. **Payment methods** (Settings → Payments → Payment methods): **Cards** (Apple Pay / Google Pay come with them), **SEPA
   Direct Debit**, **iDEAL**, **Bancontact**. Leave buy-now-pay-later off (B2B subscriptions).
4. **Stripe Tax** (Settings → Tax): head office address of the selling entity; preset product tax code *Software as a
   service (SaaS) – business use*; tax behaviour **exclusive** (prices are without VAT); add the registration(s) the
   accountant confirms (for an EU entity: its home country; OSS is not needed for B2B only). Stripe Tax then charges home-
   country VAT to customers in that country and applies the **reverse charge** (0 %, with the reverse-charge note on the
   invoice) to EU businesses with a valid VAT ID. For a non-EU seller selling only B2B, EU customers self-account; confirm
   with the accountant whether any registration is needed. [VERIFY: the invoice wording for reverse charge.]
5. **Invoices** (Settings → Billing → Invoices): invoice number prefix (e.g. `OTTO`), the company's legal details, VAT
   number and address in the footer, payment terms. Subscriptions create invoices automatically; the one-time founding seat
   creates one through Checkout (`invoice_creation`).
6. **Products and prices** (Product catalog), EUR, recurring, tax behaviour exclusive — from `plans.json` (draft prices,
   status "draft" until Max approves them; yearly = 10 × monthly):

   | Product | Monthly | Yearly | plans.json |
   |---|---|---|---|
   | Otto Starter | €99 | €990 | `starter.stripe_price_ids.monthly` / `.yearly` |
   | Otto Growth | €249 | €2,490 | `growth.stripe_price_ids…` |
   | Otto Scale | €499 | €4,990 | `scale.stripe_price_ids…` |
   | Otto Agency (5 workspaces) | €499 | €4,990 | `agency.stripe_price_ids…` |
   | Otto Founding pilot (optional) | €197 one-time | — | `founding.stripe_price_ids.one_time` (null = off) |

   Copy each price id (`price_…`) into `platform/plans.json` (re-read on save; a plan without a price shows "Not on sale
   yet"). The founding bridge prices (€179 Growth / €79 Starter for 12 months) are Stripe coupons or separate prices — add
   them when the bridge opens. [DECISION]
7. **Retries** (Settings → Billing → Subscriptions and emails): Smart Retries over up to 2 weeks; after the last attempt
   **cancel the subscription** (Otto then moves the brand to no plan). Turn on Stripe's e-mails for failed payments only if
   wanted — Otto's app already shows the banner.
8. **Webhook** (Developers → Webhooks → Add endpoint): URL `https://<domain>/hooks/stripe` (the apex; the console's Setup
   section shows the exact URL with a Copy button), API version: the account's current one is fine (Otto reads both the
   pre-2025 and the 2025 "basil" shapes), events:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`,
   `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`,
   `invoice.payment_failed`, `invoice.payment_action_required`, `charge.refunded`, `setup_intent.succeeded`.
   Copy the signing secret (`whsec_…`).
9. **Keys**: Developers → API keys. Create a **restricted key** with write access to Checkout Sessions, Customers,
   Subscriptions, Subscription Schedules, SetupIntents, Invoices, Billing Portal, and read access to Prices, Tax settings,
   Webhook endpoints, Account (or use the secret key while testing). On the server:

   ```
   /etc/otto/secrets/stripe.json   (chmod 600, owner = the otto-api user)
   {"secret_key": "rk_test_…", "publishable_key": "pk_test_…", "webhook_secrets": ["whsec_…"]}
   ```
   then `systemctl restart otto-api`. Optional keys: `"checkout_ui": "hosted"`, `"portal_fallback": true`
   (+ `"portal_configuration": "bpc_…"`), `"require_tax_id": true`, `"payment_method_types": […]`, `"ref_secret"` (≥ 32
   characters; otherwise one is generated once into `.billing-ref-secret` next to data.json). Rolling the webhook secret:
   put the new one first and keep the old one in the list until Stripe stops signing with it.
10. **Customer Portal**: not needed (clients manage everything on Otto's Billing page). Only for the optional fallback.
11. **Check**: owner console → Controls → *Check Stripe setup* (or `python3 otto_stripe.py check`): reads the account,
    Stripe Tax, every price in plans.json (active, EUR, interval, tax behaviour, amount = plans.json) and the webhook; the
    result is in Setup.

## Test-mode run-through (before switching to live keys)

1. Test keys + a test webhook endpoint (or `stripe listen --forward-to https://<domain>/hooks/stripe` while trying on a test
   box), test prices in plans.json.
2. Sign up with a Google account → onboarding → the trial runs. Settings → Account → *Billing and plans* → Growth monthly.
   The page says "You won't be charged before" the trial's end. Pay with `4242 4242 4242 4242` (any future date, any CVC),
   a Dutch address and a VAT ID (Stripe's Tax ID docs list test values that verify and that fail). Back on the page: "Growth is on. Your first charge is
   on …". In Stripe: the subscription is *trialing* until that date; in the console: Customers shows it, the brand is on
   Growth.
3. SEPA: IBAN `NL39RABO0300065264`; iDEAL / Bancontact: the test bank page → *Authorize*. 3-D Secure: card
   `4000 0027 6000 3184`.
4. Change plan to Starter (at period end: a pending change shows) and back (*Stay on Growth*); to Growth yearly (now,
   invoiced at once). Cancel → "Ends on …" → *Keep my subscription*.
5. Failed renewal: in Stripe, attach `4000 0000 0000 0341` (attaches, then fails) as the default and use a test clock to
   reach the renewal → the app shows "Your last payment didn't go through", the console has the owner card; *Update* on the
   Billing page with `4242…` → the open invoice is paid at once. Let the test clock run past the last retry → the
   subscription is canceled → the brand is on no plan.
6. Refund the founding seat in the Dashboard (with `founding.stripe_price_ids.one_time` set) → the seat ends.
7. Remove `stripe.json` → every billing screen says "Payments aren't set up yet", nothing breaks.

## Fees: Stripe against Whop (per payment, EUR prices, EUR customers)

Stripe (stripe.com/en-nl/pricing, checked 1 Oct 2026): standard EEA cards 1.5 % + €0.25, premium EEA cards (many business
cards) 2.8 % + €0.25, UK cards 2.5 % + €0.25, other international cards 3.15 % + €0.25 (+2 % only if a currency is
converted); SEPA Direct Debit €0.35; iDEAL €0.29; Bancontact €0.35; plus **Stripe Billing 0.7 %** of subscription volume and
**Stripe Tax 0.5 %** per transaction; one-off invoices (founding seat) 0.4 %. Disputes €20. Embedded Checkout itself is free.
Whop (research §5.1, [W1]): 2.7 % + $0.30, +1.5 % international cards, +1 % currency conversion, +2 % when Whop collects tax —
about **7.2 % + €0.26** conservatively, about 4.7 % + €0.26 for a domestic EU card.

| Payment | Stripe, EEA card | Stripe, SEPA / iDEAL | Stripe, premium card | Whop (≈7.2 % + €0.26) |
|---|---|---|---|---|
| Starter €99 / month | €2.92 (2.9 %) | €1.54 (1.6 %) | €4.21 (4.3 %) | €7.39 (7.5 %) |
| Growth €249 / month | €6.97 (2.8 %) | €3.34 (1.3 %) | €10.21 (4.1 %) | €18.19 (7.3 %) |
| Growth €2,490 / year | €67.48 (2.7 %) | €30.23 (1.2 %) | €99.85 (4.0 %) | €179.54 (7.2 %) |
| €20,000 MRR (about 80 payments) | ≈ €560 / month | ≈ €270 | ≈ €820 | ≈ €1,460 |

Trade-off: Whop was merchant of record for VAT (it collected and remitted EU / UK VAT); with Stripe, Otto is the seller and
must handle VAT itself (Stripe Tax computes and reports it; the filing is Otto's / the accountant's). For B2B with reverse
charge that is little work, and the saving is roughly 3–6 points of revenue.
