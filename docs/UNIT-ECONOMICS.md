# What one €79 client costs Otto (estimate, 2 Oct 2026; image prices 3 Oct 2026)

Starter: €79 a month excluding VAT, monthly subscription. Per paying client per month:

| Cost | Estimate | Basis |
|---|---|---|
| Claude API (otto_copy): ~66 organic posts + the month's ad copy (micro matrix: 4 concepts × 5 styles, angles, rewrites) | €2.5–4 | claude-opus-5-5 at $4 / $20 per million tokens in / out; posts: ~4 per call, ~7k tokens in (mostly cached) and ~4k out per call; ads: ~5–6 calls a month, ~12k cached + ~1k fresh in and ~3–4k out per call ≈ $0.5 a month. The owner console's "AI copywriter" row shows the real spend per day |
| Post and ad images (statics) | €0 | otto_render HTML templates + the client's own site photos, on our server |
| Video ads (10) and reels (4) rendering | €0 | HyperFrames / ffmpeg on our server |
| Reel scene images (Higgsfield Cloud API, GPT Image 2) | €1–1.5 | ~20–28 scene images a month (4 reels × 5–7 scenes) at **$0.060 each** (9:16, 2k, quality medium — the engine's default; verified with Higgsfield's estimate endpoint on 3 Oct 2026, incl. its current 15% discount). Leonardo (~$0.20 an image) is only the fallback; without either key a reel reuses the post's cover. The owner console's "AI images" row shows the real images and spend per day |
| AI post visuals (genvisuals, only for a post without a picture) | €0–0.5 | GPT Image 2 at 2k medium: **$0.076** a 3:4 feed image, **$0.100** square, **$0.060** 9:16 story. Other GPT Image 2 prices (same source): 1k low square $0.014 · 2k high 3:4 $0.277 · 2k high square $0.373 · 4k high square $0.614; reference images add ≈ $0.01 each |
| Reel voice-over (ElevenLabs, optional) | €0.5–1 | ~3,000 characters a month |
| E-mail (Resend) | €0–0.3 | free up to 3,000 e-mails a month (100 a day), then $20 a month for 50,000 |
| Server share (Hetzner CPX31 + backups + storage, ~€23 a month) | €2.3 at 10 clients · €0.5 at 50 | one CPX31 carries roughly 40–60 clients' renders; then a bigger box |
| Stripe | ≈ €2.4 | EEA card 1.5% + €0.25 (€1.44) + Billing 0.7% (€0.55) + Tax 0.5% (€0.40); SEPA Direct Debit is cheaper |
| **Total** | **≈ €8.5–11.5 at 10 clients · €7–9.5 at 50** | **gross margin ≈ 85–90% (≈ €68–72 a client a month)** |

Not Otto's cost: the client's ad budget (paid to Meta directly by the client) and VAT (added on top; reverse charge for EU businesses).

A trial that does not convert costs about €1–1.5 (its first week of copy and images, and the ad copy of its month).

Acquisition is the big number: at the launch budget (€100 a day) the plan expects about €30 per trial start; at 15–25% trial → paid
that is €120–200 per paying client, paid back in about 2–3 months of margin. Real numbers come from the owner console (funnel,
trials, Stripe) after the first two weeks of the campaign.

Fixed, not per client: domain (~€1 a month), Stripe Atlas or another selling entity (Atlas $500 once, then yearly fees), accountant.
