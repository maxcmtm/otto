# Cookie and tracking notice

> **Draft — must be reviewed by a qualified lawyer in the EU before publishing.**
>
> Words in [SQUARE BRACKETS] are placeholders to fill in. Notes marked Review, Decision, Verify or Engineering are for the reviewing lawyer and for Max; remove every one of them before publishing.

Version: Draft 0.1 · 30 September 2026 · In force from [EFFECTIVE DATE]

This notice covers Otto's website at [DOMAIN] (the landing page, setup and these legal pages) and the Otto app at app.[DOMAIN]. It lists everything our pages store in your browser and every other website your browser contacts because of our pages. How we use the data is in our [Privacy Policy](privacy.html).

## The short version

- Our pages set **no cookies** and use **no third-party analytics or advertising tags** (no Google Analytics, no Meta pixel).
- We count visits with our own cookieless tool. It never stores your IP address, and it respects Do Not Track and Global Privacy Control.
- That is why you see no cookie banner. [REVIEW: confirm that no consent is needed for the items below (see the note in the Privacy Policy on EDPB Guidelines 2/2023). If a banner is needed after all, rejecting must be as easy as accepting.]

## Cookies

Our own pages set none. The cookies below can still appear. All are set by Cloudflare, which protects and delivers our site, and all are strictly necessary:

| Cookie | Set by | When | Purpose | Lasts |
|---|---|---|---|---|
| `__cf_bm` | Cloudflare | Only if Cloudflare's bot protection needs to tell people from automated traffic [VERIFY: whether bot protection is on for our zone] | Security | 30 minutes |
| `cf_clearance` | Cloudflare | Only after you pass a Cloudflare security check | Security | [VERIFY: the challenge passage time set in Cloudflare] |
| `CF_Authorization` | Cloudflare Access | When you sign in to the Otto app (app.[DOMAIN]) | Keeps you signed in | [VERIFY: the session length set in Cloudflare Access] |

## What our pages keep in your browser tab

- **The website scan.** When you scan a website on our landing page, the page keeps the address you typed and the result (`otto.site`, `otto.peek`) in your browser's session storage, so that setup can continue from it.
- **Setup.** The setup page keeps your answers (`otto.onboarding`) in session storage, so that a refresh does not lose them.

Session storage belongs to the browser tab and is deleted when you close it. Nothing in it is sent to us until you finish setup. It is used only for the service you asked for.

## Visit statistics without cookies

Our pages send short messages to our own server (`/otto-track`): the page, the referring site's domain, campaign tags in the link, the type of device, and what you do on the page (scroll depth, sections seen, main buttons clicked, questions opened, films played, a scan started). Nothing is stored on your device. Our server replaces your IP address with a code that changes every day and never writes the IP address down. With Do Not Track or Global Privacy Control switched on, the page sends one anonymous page view and nothing else. The details are in the [Privacy Policy](privacy.html#our-website-statistics-in-detail).

## Other websites your browser contacts

| Page | Host | What and why | What that host sees |
|---|---|---|---|
| Landing page and setup | The website you scan | Your browser loads that website's logo directly from it, to show it in the preview. No referrer is sent. | Your IP address and browser type |
| All other pages | None | Fonts and animation code are served from our own server | — |
| Legal pages (this page) | None | Everything comes from our own server | — |

Links to other websites, such as the Whop checkout, Meta or Google, are not loaded until you click them. Those websites have their own cookie and privacy notices.

## Your choices

- Switch on Global Privacy Control or Do Not Track in your browser: we then record one anonymous page view and nothing else.
- Close the tab to clear what the landing page and setup kept in session storage.

Questions: [PRIVACY EMAIL].
