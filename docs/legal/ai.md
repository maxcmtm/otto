# AI transparency statement

> **Draft — must be reviewed by a qualified lawyer in the EU before publishing.**
>
> Words in [SQUARE BRACKETS] are placeholders to fill in. Notes marked Review, Decision, Verify or Engineering are for the reviewing lawyer and for Max; remove every one of them before publishing.

Version: Draft 0.1 · 30 September 2026 · In force from [EFFECTIVE DATE]

Otto is an AI marketing service: most of what it makes is made with AI. This page says what is made with AI and what is not, how AI-made images, video and voice are marked, and who decides what gets published. It is written with Article 50 of the EU AI Act (Regulation (EU) 2024/1689) in mind, whose transparency duties apply from 2 August 2026.

## The short version

- Otto's captions, ad texts, plans and scripts are written with AI. Many images, and the voice-overs in reels, are generated with AI.
- A person approves every post and every paid campaign before it goes out: the business that publishes it.
- Otto does not invent customers. Reviews are quoted word for word from the business's own website, and people talking to camera in "creator" videos are real people who agreed to appear.
- AI-generated images and videos carry a machine-readable label in the file (details below).

## What is made with AI, and what is not

| Part of Otto's output | Made with AI? | How |
|---|---|---|
| Strategy, monthly plan, captions, ad headlines and texts, video scripts, creator briefs | Yes | Written by Anthropic's Claude models from the business's website, answers and past decisions. Checked automatically against the business's list of words to avoid and, for health brands, against rules on health claims. |
| Images for posts and reels | Often | Generated with Leonardo.ai (including OpenAI's GPT Image models). |
| Ad images built from templates | Partly | Layouts designed by our team, filled with the business's own logo, photos, prices and reviews; some templates also use an AI-generated image. |
| Reels and faceless video ads | Yes, partly | Put together automatically from images (often AI-generated), captions, motion templates and royalty-free music. |
| Voice-overs | Yes | Synthetic voices from ElevenLabs, sometimes through Higgsfield. They are stock synthetic voices; Otto does not clone anyone's voice. [VERIFY: the configured voice IDs are stock voices.] |
| Reviews and customer quotes | No | Copied word for word from the business's own website. Otto never writes a review or a testimonial. |
| Creator videos (a person talking to camera) | No | Filmed by a real creator. Otto writes the brief, the script and the shot list; the video is only used once the footage arrives with the creator's name and consent. |
| Logos, product photos, prices, offers | No | The business's own, from its website or uploads. |

## No AI people presented as real

Otto never presents an AI-generated person as a real customer, patient or user, and never puts invented words in a real person's mouth. This is built into Otto: its ad planner rejects any plan that would show an AI-generated person as a customer. Otto also does not make images, video or audio that show a real person, or that could be taken for a real event, without that being clear (a "deepfake"). A business may not use Otto for that under our [Terms](terms.html) (section 7).

## How AI-made images, video and voice are marked

Under Article 50(2) of the AI Act, the provider of an AI system that generates images, video or audio must make sure the output is marked in a machine-readable way as AI-generated. Otto does this as follows:

- Images created by an image model keep the signed C2PA Content Credentials the model's provider adds (for example OpenAI's), unchanged: Otto does not edit or re-save those bytes in a way that breaks the signature.
- Where Otto itself produces or assembles a file that contains AI-generated material (a carousel slide made on a generated image, a reel with generated scenes, any video with a synthetic voice or generated music), the file carries the IPTC "digital source type" in its metadata (fully generated, or a composite that includes generated material). Videos also carry the same information in their container tags and in a small record kept next to the file.
- Cards Otto builds from the business's own real photos plus text are not AI-generated media and are not marked as such; the text on them is covered below.
- [ENGINEERING: Otto's own composites carry unsigned IPTC metadata today, not signed C2PA credentials or a watermark. The Commission's Code of Practice expects signed metadata plus a watermark; that needs a signing certificate and a C2PA tool. Decide before the first EU client; the grace period to 2 December 2026 applies only to systems already on the market before 2 August 2026 (research/EU-LAUNCH-AND-PRICING-2026-09.md §6.3, docs/AI-TRANSPARENCY.md).]
- Meta reads these labels and may show "AI info" on the post or ad. Businesses should publish Otto's files as they are and must not strip their metadata (the Terms say so).
- A visible "AI" note on the image itself is not added by default. [DECISION: the recommended default is a visible note always for realistic synthetic people (Otto does not make these today), and on for health, beauty and food images; off for narrator voices and template cards. See docs/AI-TRANSPARENCY.md.]
- For images or video that look realistic enough to be taken for a real scene, Otto also adds a small visible "Made with AI" note unless the business decides otherwise. [DECISION: default on or off; the business, as the one publishing, carries the duty in Article 50(4) to disclose deepfakes.]
- Captions and ad texts are plain text. The business reviews and approves every one before it is published and is responsible for it as the publisher. [REVIEW: does Article 50(2) require machine-readable marking of short marketing texts, and what does the Commission's Code of Practice on marking and labelling expect? Otto does not write news or other texts on matters of public interest.]

## Who approves what

- **The business approves everything.** Every post waits for approval in the Otto app, by e-mail or in Telegram, and every paid campaign starts only after the business has approved that month's paid plan. If the business does not answer, nothing is published. A business can choose to let some kinds of posts publish without approving each one; that is off unless it switches it on, and it can switch it off at any time.
- **Our team looks at some of the work.** On the Growth and Scale plans, a strategist reviews the monthly plan and the ad set-up. For Dutch-language clients, a native speaker reviews the first month. [VERIFY: the Dutch reviewer is in place.]
- **Automatic checks** run on every text before it reaches the business: the business's own list of words to avoid, and rules on health claims for health brands. They help, but they are not legal advice.

## Talking to Otto

When a business deals with Otto in the app, by e-mail or in Telegram, it is dealing with an AI system, which is clear from the product itself. Messages written by a person on our team are signed with that person's name. [VERIFY] Otto does not talk to a business's customers: it does not answer comments or messages on the business's behalf. If that changes, those customers will be told they are talking to AI.

## Roles under the AI Act

Otto is the **provider** of the Otto system, which is built on general-purpose AI models from Anthropic, OpenAI (through Leonardo), Leonardo, ElevenLabs and Higgsfield. The business that uses Otto and publishes its output is the **deployer**. [REVIEW: confirm this split, in particular whether Otto is also a deployer where it runs campaigns for the client, and whether Otto becomes a provider of a general-purpose AI system.] Otto's uses are not "high-risk" under Annex III of the AI Act. Otto does not target ads by sensitive characteristics: its ad targeting uses only location and age.

Our team is trained in how Otto's AI works and where it fails (AI Act Article 4), and we give businesses guidance on what to check before approving.

## Questions and concerns

If you think something Otto made is misleading, is not marked as it should be, or shows you without your consent, write to [CONTACT EMAIL]. We look at it within [2 BUSINESS DAYS] and, where needed, ask the business to remove it.
