# Sub-processors

> **Draft — must be reviewed by a qualified lawyer in the EU before publishing.**
>
> Words in [SQUARE BRACKETS] are placeholders to fill in. Notes marked Review, Decision, Verify or Engineering are for the reviewing lawyer and for Max; remove every one of them before publishing.

Version: Draft 0.1 · 30 September 2026 · In force from [EFFECTIVE DATE]

These are the companies that process personal data for Otto when we work for our clients. Each one has signed data processing terms with us that give at least the protection of our [Data Processing Agreement](dpa.html). This list is Annex III of that agreement.

## Current list

<!-- subprocessors:start — keep this table identical to the one in dpa.md (tests/test_legal.py checks it) -->
| Sub-processor | What it does for Otto | Personal data it receives | Where | Transfer safeguard |
|---|---|---|---|---|
| Hetzner Online GmbH, Germany | Hosts the Otto server; daily server snapshots; encrypted off-site backups (Storage Box) | Everything Otto stores; backups are encrypted before they leave the server | Germany (Nuremberg and Falkenstein data centres) [VERIFY: Storage Box location] | Inside the EU |
| Cloudflare, Inc., USA | DNS, encrypted connections, firewall and rate limits, delivery of our pages, our team's sign-in to the owner console (Cloudflare Access) | Connection data of every visit, including IP addresses; our team's sign-in e-mail addresses | Global network; company in the USA | EU–US Data Privacy Framework; standard contractual clauses in Cloudflare's DPA |
| Google Ireland Limited, Ireland (with Google LLC, USA) | Authentication: Sign in with Google for the Otto app | The sign-in happens on Google's page; Google tells Otto the user's e-mail address, name and Google account ID | EU and USA | EU–US Data Privacy Framework; standard contractual clauses [REVIEW: Google acts as an independent controller for the user's Google account] |
| Anthropic, PBC, USA | Claude AI models: strategy, captions, ad texts, briefs, summaries | Brand profile, website text, the client's answers and instructions, drafts, performance summaries; this can include names quoted from the client's website | USA | Standard contractual clauses [VERIFY: DPF status, no training on API data, retention period] |
| Leonardo Interactive Pty Ltd (Leonardo.ai), Australia | Image generation as a fallback when Higgsfield is unavailable, including OpenAI's GPT Image models, to which Leonardo passes the prompt | Image prompts (descriptions of the brand, product and scene); reference images where used | [VERIFY: processing location]; OpenAI in the USA | Standard contractual clauses [VERIFY: generations private and not used for training] |
| ElevenLabs, USA [VERIFY: contracting entity] | Synthetic voice-over for reels | The voice-over script | USA [VERIFY: EU data residency option] | [VERIFY: DPF or standard contractual clauses] |
| Higgsfield AI, USA [VERIFY: contracting entity] | Image generation for posts, reel scenes and ads (OpenAI's GPT Image 2, to which Higgsfield passes the prompt); voice-over and video generation for some reels | Image prompts (descriptions of the brand, product and scene); reference images where used (e.g. the client's product photo); scripts and visual prompts | USA; OpenAI in the USA [VERIFY] | [VERIFY: DPA with standard contractual clauses; generations private and not used for training] |
| Telegram [VERIFY: contracting entity], only for clients who choose Telegram | Delivers approval cards, reports and alerts | Post previews and captions, report text, the client's Telegram user ID | [VERIFY] | [REVIEW: Telegram offers no data processing agreement; treat it as a channel the client chooses, or offer it outside the EU only] |
| [EMAIL PROVIDER], from the launch of e-mail approvals | Sends approval and report e-mails | Recipient e-mail address, message content | [VERIFY] | [VERIFY] |
| Stripe Payments Europe, Ltd., Ireland (with Stripe, Inc., USA) | Payment processing for Otto's own subscriptions: the payment form inside Otto's Billing page, subscriptions, invoices and receipts, VAT calculation (Stripe Tax) | Billing contacts of clients (name, e-mail, billing address, VAT ID), plan and payment history; card and bank details go to Stripe directly and never to Otto | EU and USA | EU–US Data Privacy Framework; standard contractual clauses in Stripe's DPA [REVIEW: Stripe is a processor for billing, invoicing and tax, and an independent controller for payment processing, fraud prevention and its legal duties (Stripe's DPA and privacy policy)] |
<!-- subprocessors:end -->

[ENGINEERING: until Otto moves to the Hetzner server (a pre-launch item in docs/HOSTING.md), production runs on an Amazon Web Services server shared with other projects. Move before the first EU client, or add AWS to this list with its region.]

## Services that are not our sub-processors

- **Meta** (Facebook, Instagram and Meta ads; Meta Platforms Ireland Ltd) and **Google** (Google Ads; Google Ireland Ltd). Otto publishes posts and runs campaigns in the client's own accounts, with the permissions the client grants. Meta and Google act under the client's own contract with them. Separately, when a visitor to Otto's own website accepts ad measurement, Otto sends Meta the events described in our [Privacy Policy](privacy.html#ad-measurement-with-meta); that concerns Otto's own advertising, not client data.
- **Whop** (legacy). The founding seats sold before 1 October 2026 were paid through Whop, which acted as an independent controller under its own terms; Whop still reports refunds and status changes of those seats to us. No new payment goes through Whop. [REVIEW: confirm under Whop's Seller Data Sharing Addendum; remove this line once no founding seat bought on Whop is active.]
- **GitHub** stores Otto's source code and runs our automated tests and deployments. It receives no client data; the tests use invented sample businesses.
- **OpenClaw** is agent software that runs on our own server. It is not a service provider; the AI models it calls are listed above.

## Changes to this list

We tell clients at least 30 days before a new sub-processor starts processing their personal data, by e-mail to the account address and by updating this page. A client can object within that time on reasonable data-protection grounds. If we cannot meet the objection, the client can end the affected service before the change and we refund fees paid for the time after it ends. In an emergency (for example to keep Otto running when a provider fails), we may make a change at shorter notice and tell clients at once.

To receive notices without being a client, or for questions, write to [PRIVACY EMAIL].
