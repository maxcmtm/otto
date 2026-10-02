# What one €79 client costs Otto (estimate, 2 Oct 2026)

Starter: €79 a month excluding VAT, monthly subscription. Per paying client per month:

| Cost | Estimate | Basis |
|---|---|---|
| Claude API (otto_copy): ~66 organic posts + 20 ad copies + rewrites | €2.5–4 | claude-opus-5-5 at $4 / $20 per million tokens in / out; ~4 posts per call, ~7k tokens in (mostly cached) and ~4k out per call. The owner console's "AI copywriter" row shows the real spend per day |
| Post and ad images (statics) | €0 | otto_render HTML templates + the client's own site photos, on our server |
| Video ads (10) and reels (4) rendering | €0 | HyperFrames / ffmpeg on our server |
| Reel scene images (Leonardo, optional) | €2–5 | ~20 scene images a month; without a Leonardo key a reel reuses the post's cover |
| Reel voice-over (ElevenLabs, optional) | €0.5–1 | ~3,000 characters a month |
| E-mail (Resend) | €0–0.3 | free up to 3,000 e-mails a month (100 a day), then $20 a month for 50,000 |
| Server share (Hetzner CPX31 + backups + storage, ~€23 a month) | €2.3 at 10 clients · €0.5 at 50 | one CPX31 carries roughly 40–60 clients' renders; then a bigger box |
| Stripe | ≈ €2.4 | EEA card 1.5% + €0.25 (€1.44) + Billing 0.7% (€0.55) + Tax 0.5% (€0.40); SEPA Direct Debit is cheaper |
| **Total** | **≈ €9–12 at 10 clients · €7–10 at 50** | **gross margin ≈ 85–90% (≈ €67–72 a client a month)** |

Not Otto's cost: the client's ad budget (paid to Meta directly by the client) and VAT (added on top; reverse charge for EU businesses).

A trial that does not convert costs about €0.5–1 (its first week of copy and images).

Acquisition is the big number: at the launch budget (€100 a day) the plan expects about €30 per trial start; at 15–25% trial → paid
that is €120–200 per paying client, paid back in about 2–3 months of margin. Real numbers come from the owner console (funnel,
trials, Stripe) after the first two weeks of the campaign.

Fixed, not per client: domain (~€1 a month), Stripe Atlas or another selling entity (Atlas $500 once, then yearly fees), accountant.
