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
| Cloudflare, Inc., USA | DNS, encrypted connections, firewall and rate limits, delivery of our pages, sign-in to the Otto app (Cloudflare Access) | Connection data of every visit, including IP addresses; sign-in e-mail addresses | Global network; company in the USA | EU–US Data Privacy Framework; standard contractual clauses in Cloudflare's DPA |
| Anthropic, PBC, USA | Claude AI models: strategy, captions, ad texts, briefs, summaries | Brand profile, website text, the client's answers and instructions, drafts, performance summaries; this can include names quoted from the client's website | USA | Standard contractual clauses [VERIFY: DPF status, no training on API data, retention period] |
| Leonardo Interactive Pty Ltd (Leonardo.ai), Australia | Image generation, including OpenAI's GPT Image models, to which Leonardo passes the prompt | Image prompts (descriptions of the brand, product and scene); reference images where used | [VERIFY: processing location]; OpenAI in the USA | Standard contractual clauses [VERIFY: generations private and not used for training] |
| ElevenLabs, USA [VERIFY: contracting entity] | Synthetic voice-over for reels | The voice-over script | USA [VERIFY: EU data residency option] | [VERIFY: DPF or standard contractual clauses] |
| Higgsfield AI, USA [VERIFY: contracting entity] | Voice-over and video generation for some reels (ElevenLabs voices used through Higgsfield) | Scripts and visual prompts | USA [VERIFY] | [VERIFY: DPA with standard contractual clauses] |
| Telegram [VERIFY: contracting entity], only for clients who choose Telegram | Delivers approval cards, reports and alerts | Post previews and captions, report text, the client's Telegram user ID | [VERIFY] | [REVIEW: Telegram offers no data processing agreement; treat it as a channel the client chooses, or offer it outside the EU only] |
| [EMAIL PROVIDER], from the launch of e-mail approvals | Sends approval and report e-mails | Recipient e-mail address, message content | [VERIFY] | [VERIFY] |
<!-- subprocessors:end -->

[ENGINEERING: until Otto moves to the Hetzner server (a pre-launch item in docs/HOSTING.md), production runs on an Amazon Web Services server shared with other projects. Move before the first EU client, or add AWS to this list with its region.]

## Services that are not our sub-processors

- **Meta** (Facebook, Instagram and Meta ads; Meta Platforms Ireland Ltd) and **Google** (Google Ads; Google Ireland Ltd). Otto publishes posts and runs campaigns in the client's own accounts, with the permissions the client grants. Meta and Google act under the client's own contract with them.
- **Whop** (payments). Whop processes payments as an independent controller under its own terms. [REVIEW: confirm under Whop's Seller Data Sharing Addendum.]
- **GitHub** stores Otto's source code and runs our automated tests and deployments. It receives no client data; the tests use invented sample businesses.
- **OpenClaw** is agent software that runs on our own server. It is not a service provider; the AI models it calls are listed above.

## Changes to this list

We tell clients at least 30 days before a new sub-processor starts processing their personal data, by e-mail to the account address and by updating this page. A client can object within that time on reasonable data-protection grounds. If we cannot meet the objection, the client can end the affected service before the change and we refund fees paid for the time after it ends. In an emergency (for example to keep Otto running when a provider fails), we may make a change at shorter notice and tell clients at once.

To receive notices without being a client, or for questions, write to [PRIVACY EMAIL].
