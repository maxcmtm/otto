# Cookie and tracking notice

> **Draft — must be reviewed by a qualified lawyer in the EU before publishing.**
>
> Words in [SQUARE BRACKETS] are placeholders to fill in. Notes marked Review, Decision, Verify or Engineering are for the reviewing lawyer and for Max; remove every one of them before publishing.

Version: Draft 0.2 · 30 September 2026 · In force from [EFFECTIVE DATE]

This notice covers Otto's website at [DOMAIN] (the landing page, setup and these legal pages) and the Otto app at app.[DOMAIN]. It lists everything our pages store in your browser and every other website your browser contacts because of our pages. How we use the data is in our [Privacy Policy](privacy.html).

## The short version

- Our pages run **no third-party analytics or advertising tags**: no Google Analytics, and no Meta pixel script in your browser.
- We count visits with our own cookieless tool. It never stores your IP address, and it respects Do Not Track and Global Privacy Control.
- The landing page asks one question: may we measure our own ads with Meta? **Reject** and **Accept** are equal buttons, side by side, and the page works the same whichever you press. If you accept, our server (not your browser) tells Meta when you scan a website, see the scan result, or start signing up or checking out. If you reject, nothing is sent to Meta.
- We set one cookie to remember your answer, and, only if you accept and arrived from a Meta ad, one more cookie for that ad's click ID.
- You can change your answer at any time with **Privacy choices** at the bottom of the landing page.

## Cookies

| Cookie | Set by | When | Purpose | Lasts |
|---|---|---|---|---|
| `otto_consent` | Otto (first party) | When you answer the question on the landing page | Remembers your answer (`v1.granted` or `v1.denied`), so we do not ask again and our server knows whether it may send anything to Meta. Strictly necessary for your choice. | 180 days |
| `otto_fbc` | Otto (first party) | Only after you press Accept, and only if you reached our page from a Meta ad link (the link carries a `fbclid` click ID) | Holds that click ID so Meta can tell which of our ads brought the visit. Deleted when you reject or withdraw consent. | 90 days |
| `__cf_bm` | Cloudflare | Only if Cloudflare's bot protection needs to tell people from automated traffic [VERIFY: whether bot protection is on for our zone] | Security | 30 minutes |
| `cf_clearance` | Cloudflare | Only after you pass a Cloudflare security check | Security | [VERIFY: the challenge passage time set in Cloudflare] |
| `__Host-otto_sid` | Otto (first party, app.[DOMAIN] only) | When you sign in to the Otto app with Google | Keeps you signed in: a random code whose one-way hash our server keeps. Strictly necessary. Deleted when you sign out. | 30 days after your last visit |
| `__Host-otto_login` | Otto (first party, app.[DOMAIN] only) | While you are on Google's sign-in page | Ties Google's answer to the browser that asked for it (protection against forged sign-ins). Strictly necessary. | 10 minutes, deleted when you come back |
| `CF_Authorization` | Cloudflare Access | Only for Otto's team, when signing in to the owner console (admin.[DOMAIN]) | Keeps our team signed in | [VERIFY: the session length set in Cloudflare Access] |

The Cloudflare cookies are set by Cloudflare, which protects and delivers our site; all three are strictly necessary.

## What our pages keep in your browser tab

- **The website scan.** When you scan a website on our landing page, the page keeps the address you typed and the result (`otto.site`, `otto.peek`) in your browser's session storage, so that setup can continue from it.
- **Setup.** The setup page keeps your answers (`otto.onboarding`) in session storage, so that a refresh does not lose them.

Session storage belongs to the browser tab and is deleted when you close it. Nothing in it is sent to us until you finish setup. It is used only for the service you asked for.

## Visit statistics without cookies

Our pages send short messages to our own server (`/otto-track`): the page, the referring site's domain, campaign tags in the link, the type of device, and what you do on the page (scroll depth, sections seen, main buttons clicked, questions opened, films played, a scan started). Nothing is stored on your device for these statistics. Our server replaces your IP address with a code that changes every day and never writes the IP address down. With Do Not Track or Global Privacy Control switched on, the page sends one anonymous page view and nothing else. Your answer to the ad-measurement question is counted in these statistics too (how many visitors accept and reject), without anything that identifies you. The details are in the [Privacy Policy](privacy.html#our-website-statistics-in-detail).

## Ad measurement with Meta (only with your consent)

We advertise Otto on Facebook and Instagram. To learn which of our ads bring people who are really interested, and to let Meta show our ads to similar businesses, we can tell Meta about these moments:

| Moment on our page | Name Meta uses |
|---|---|
| You start a website scan | ViewContent |
| Otto shows you the scan result | Lead |
| You press a button that starts checkout, sign-up or a trial ("Get started", "Start free trial") | InitiateCheckout |
| Only once sign-up opens on our site: you complete sign-up, or your trial starts (our server confirms it; your browser cannot report it) | CompleteRegistration, StartTrial |

This happens **only if you pressed Accept**. It is done by our server through Meta's Conversions API; no Meta code runs in your browser and your browser makes no request to Meta because of our page. With each moment our server sends: its name and time, a random event number, the page address, your IP address and browser type (Meta needs them to match the moment to an ad; we still do not store your IP address), the Meta click ID from the `otto_fbc` cookie if there is one, and one-way hashes of our daily visitor code and of your country code. We never send the website address you scanned, anything you typed, the referring site or campaign tags.

Your answer is ignored in one direction only: if your browser sends Do Not Track or Global Privacy Control, nothing is sent to Meta even if you pressed Accept. More about Meta's role, and how long Meta keeps the data, is in the [Privacy Policy](privacy.html#ad-measurement-with-meta).

[ENGINEERING: forwarding switches on only when the server holds the Meta dataset settings (`meta-capi.json` in the secrets folder). Until then nothing is sent to Meta, even after Accept. Keep this section published either way: the question on the page must describe what would happen.]

## Other websites your browser contacts

| Page | Host | What and why | What that host sees |
|---|---|---|---|
| Landing page and setup | The website you scan | Your browser loads that website's logo directly from it, to show it in the preview. No referrer is sent. | Your IP address and browser type |
| Sign-in (app.[DOMAIN]) | accounts.google.com | Only when you choose Continue with Google: your browser goes to Google's sign-in page and comes back. No Google code runs on our pages. | What any visit to Google's sign-in sees, under Google's privacy policy |
| All other pages | None | Fonts, animation code and the privacy question are served from our own server | — |
| Legal pages (this page) | None | Everything comes from our own server | — |

Links to other websites, such as Meta or Google, are not loaded until you click them. Those websites have their own cookie and privacy notices.

The Billing page in the app (where you pay) loads the payment form of our payment service provider, Stripe, from js.stripe.com. Stripe may set its own cookies in that form to prevent fraud; they are strictly necessary for the payment and are covered by Stripe's cookie policy. No other page of Otto loads anything from Stripe. [REVIEW: list Stripe's cookies (for example __stripe_mid, __stripe_sid) by name if the cookie table needs them.]

## Your choices

- Use **Privacy choices** at the bottom of our landing page to see your answer and change it. Withdrawing is as easy as giving consent, and takes effect at once: nothing more is sent to Meta, and the `otto_fbc` cookie is deleted.
- Delete the `otto_consent` cookie in your browser and we ask again on your next visit.
- Switch on Global Privacy Control or Do Not Track in your browser: we then record one anonymous page view and nothing else, and send nothing to Meta.
- Close the tab to clear what the landing page and setup kept in session storage.

Questions: [PRIVACY EMAIL].
