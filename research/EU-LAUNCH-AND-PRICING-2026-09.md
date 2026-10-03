# Otto in Europe: where to launch and how to price (September 2026)

Date: 2026-09-30 · Author: Claude Code (market strategist pass) · Decision owner: Max · Status: recommendation, ready for decision

Builds on: `docs/PRICING-EU.md` (28.09), `research/COMPETITORS-2026-09.md` (29.09), `docs/OTTO-MASTER-PLAN.md`,
`docs/HOSTING.md`, `platform/plans.json`, `platform/otto_styles.py`. It supersedes the price ladder in `PRICING-EU.md`.

Conventions
- Web sources were accessed on 30.09.2026 unless a date is shown. Source IDs in brackets, e.g. [P1], resolve in section 10.
- Prices exclude VAT. FX is the ECB reference rate of 29.09.2026: €1 = $1.1355 = £0.85718 = CHF 0.9461 [X1].
- **(est.)** = my own estimate or calculation. **(3p)** = a third-party write-up, not the vendor or an official statistic.
  **(unv.)** = a single weak source or a search snippet; check it before relying on it.

---

## 1. The answer on one page

> **Note (2 Oct 2026): Starter set to €79 by Max on 2 Oct 2026**, a monthly subscription (no yearly price, cancel anytime).
> The €99 / €990 figures below are the September proposal, kept as history; `platform/plans.json` is the source of truth.

| Question | Recommendation |
|---|---|
| Organic-only cheap tier, or most things in the first tier? | **Most things in the first tier.** Every plan runs organic content and Meta ads. Plans differ by how much ad money Otto manages, how many creatives it makes each month and how much human time is included. There is no organic-only plan on the pricing page. |
| Prices (monthly, excl. VAT) | **Starter €99 · Growth €249 · Scale €499 · Agency from €499** (5 client workspaces). UK, when it opens: £85 · £215 · £425. **Update: Starter set to €79 by Max on 2 Oct 2026**, a monthly subscription with no yearly price (`platform/plans.json`, `docs/MESSAGE-2026-10.md`); the other prices are still drafts. |
| Ad-spend logic | A flat price. Managed ad spend is capped per plan at €1,000, €5,000 and €15,000 a month. There is no percentage below €15,000 a month, and 2% of spend above it. Meta and Google bill the client directly, so Otto never holds ad money. |
| Yearly | Two months free: €990, €2,490 or €4,990 a year. |
| Founding seats (€197 once) | Keep selling until monthly plans go live, capped at 50 seats, then close. Each founder then gets Growth at €179 a month (or Starter at €79), locked for 12 months. Their setup, history and taste log carry over. |
| Launch countries (months 0–3) | **Netherlands first, Ireland second.** |
| Next countries (months 3–6) | **Germany (with Austria), then the UK.** Flanders runs as a spillover of the Dutch campaigns. Portugal is an optional low-cost test. |
| First verticals | Netherlands: Shopify and e-commerce (not supplements), hospitality, salons and local services. Ireland: trades and local services, hospitality and tourism, dental and physio clinics. |
| Must ship before launch | Email and in-app approvals, with WhatsApp next (Telegram is a minority app in Europe); a legal pack with a data processing agreement; a cookie banner; machine-readable marking of AI output; EUR plans on Whop; Dutch and Irish compliance baselines; native Dutch review; the move to the Hetzner server. |

**Why, in brief.** Native now includes Meta ads in its $79 entry plan [P1][P2], so an organic-only Otto plan
would look like less for more. The paid layer is also where an owner sees money come in during week one, and it adds only
about €6–20 per brand per month to Otto's costs (est., section 5). The Netherlands has the best English in Europe [C7];
Dutch content is in the engine; EUR and iDEAL work on Whop [W4]; four in ten firms already pay for online ads [C5]; and
Native barely advertises there: 2 of its 86 ads reached Germany, France, the Netherlands, Sweden, Denmark, Spain and
Italy combined on 29.09 [O2][A9]. Ireland is where every part of Otto works as built (English, EUR), and where Native has
already sold the category to owners.

### Decision 1.10 (1 Oct 2026): Stripe instead of Whop

Max: "I don't think it's smart to move the users to Whop … we build everything ourselves; I'll arrange Stripe as the payment
processor." Every "Whop" in this report now reads **Stripe, with Otto as the seller**: clients pay inside Otto's own Billing
page (Stripe's embedded form), manage plan, card, VAT ID and invoices there, and get invoices / receipts from Stripe in
Otto's branding. Whop stays only for the founding seats already sold on it. Implementation and setup: `docs/BILLING.md`.

| Per payment, EUR customer | Stripe card (EEA) | Stripe SEPA / iDEAL | Whop (§5.1, conservative) |
|---|---|---|---|
| Fees | 1.5 % + €0.25, + Billing 0.7 % + Tax 0.5 % [S1] | €0.35 / €0.29, + 1.2 % [S1][S2] | ≈ 7.2 % + €0.26 [W1] |
| Growth €249 / month | €6.97 (2.8 %) | €3.34 (1.3 %) | €18.19 (7.3 %) |
| Starter €99 / month | €2.92 (2.9 %) | €1.54 (1.6 %) | €7.39 (7.5 %) |

Premium / business cards cost 2.8 % + €0.25 at Stripe (Growth: €10.21, 4.1 %). Net effect on §5: the payment line drops
from about 7 % to about 2–4 % of revenue. What changes: Whop was merchant of record for EU / UK VAT; now Otto is the seller
and Stripe Tax computes the VAT (B2B reverse charge with a valid VAT ID). The selling entity must be in a Stripe-supported
country (Israel is not [S3]) — a decision for Max and the accountant before launch. §9's "ask Whop about reverse charge"
becomes "confirm the reverse-charge invoice wording with the accountant".

---

## 2. Max's two options, answered

Max asked whether to sell a cheap organic-only plan with a bigger plan for campaign management, or to put most things
into the first plan so it feels very worth it.

| | A. Organic-only entry (e.g. €49–69), plus a bigger plan for campaigns | B. Most things in the first plan |
|---|---|---|
| Against Native | Looks weaker. Native Pro is $79 (≈ €70) and includes Meta "Ads Autopilot" on every plan [P1][P2]. Blaze Starter ($79) includes automated ad campaigns [P3]. | At parity or better from the first plan. |
| Price band it lands in | The €12–40 band for AI content tools, where prices are collapsing: Holo $12–20 [P17], Predis $19–32 (3p) [P5], Ocoya $29 [P4], Metricool €20 [P19], Buffer $5 per channel [P7]. Free alternatives include Google Pomelli, Canva Grow and Meta's own generative AI; Meta says more than 9M small businesses use at least one of its AI creative tools [P15]. | €99 sits between the tools and human services. An agency's entry organic package costs €300–1,500 a month in the launch markets (section 3.4). |
| Time to visible value | Organic takes 60–90 days to show results [O2], so owners may churn before they see value. | Ads show numbers in week one, and the 07:35 daily report is in every plan. |
| Cost to Otto | Lower (no ad matrix). | Adds €6–20 per brand per month for the micro ad matrix (est., section 5). |
| Upgrade logic | A feature gate ("unlock ads"). | A scale gate: when the client's own ad budget grows, they move up a plan. Small businesses already accept spend bands (AdEspresso, Bïrch, Madgicx) [P11][P12][P13]. |
| Main risk | Commodity pricing: "just another AI post tool". | Support load from ads at €99 (policy rejections, pixel setup). Soft caps and async-only support keep this in check. |

**My pick: B, with A's cost logic.** The part of option A that is right is that campaign management costs Otto more, so it
should cost the client more. The right way to charge for it is by scale (managed spend, creative volume and human time),
not by removing ads from the entry plan. An owner with no ad budget buys Starter and leaves ads off; Otto's margin on that
client is then 50–68% (section 5.2).

Keep the organic-only plan (`content` in `plans.json`) as a non-public fallback. After 60 days of data, test it at €69 as
a downsell in the cancel flow only, never on the pricing page.

---

## 3. What the market charges

### 3.1 AI marketing tools (list prices per month)

| Product | Entry → top plan | Paid ads | Priced on ad spend? | Note | Src |
|---|---|---|---|---|---|
| **Native** (Oslo) | Pro $79 (≈ €70) · Max $249 · Agency $499 (+$69 per workspace) · Enterprise custom; yearly −20% | **Ads Autopilot on all plans.** Meta only; it writes the copy, makes a static 4:5 image, manages budget and bids, and pauses losing ads. Google is "rolling out, not live". | No. Native says it never holds spend or takes a percentage; no spend cap is stated. | Pro = 1 brand, 50 posts, 13 channels; priced in USD | [P1][P2] |
| **Blaze** (US) | Starter $79 · Growth $149 · done-for-you $999 | Automated FB/IG campaigns (beta, 3p); the done-for-you plan adds managed Google search ads | No | Credit-based: a video costs 15 credits | [P3] |
| Holo (Vilnius) | $20 ($12 on 6-month billing) · $48 | Ad creatives only | No | 770 active Meta ads across Europe, in local languages [A9] | [P17] |
| Predis.ai | $32 · $79 · $249 (3p; sources conflict) | Ad creatives only | No | | [P5] |
| Simplified | $79 · $119 · $239 (unv. order) | Meta and Google ad creatives with A/B variants | No | | [P21] |
| Ocoya / Marky / SocialBee | $29–199 / $39–229 / $29–449 | None | – | Schedulers with AI writing | [P4][P18][P20] |
| Metricool (Spain) | Free · €20 · €54 per brand | Ad reporting only | – | Priced in EUR | [P19] |
| Buffer | $5–10 per channel | None | – | | [P7] |
| Hootsuite | $99–399 per user (billed yearly) | Create and boost FB/IG/X/LinkedIn ads | No | Priced per seat | [P6] |
| Jasper | $69 per seat | None | – | Copy only | [P8] |
| AdCreative.ai | $39 · $249 · $999 (3p) | Creatives, pushed to ad platforms | No (credits) | Video from $249 | [P9] |
| Pencil | $14 · $55 | Creatives, priced per generation | No | | [P10] |
| Canva | Pro €12, Business €17 per user (3p) | Canva Grow makes ads from a URL and publishes to Meta, TikTok and LinkedIn; in the EU "in the coming months" | No | Ad refresh only on Business and up | [P14] |
| Meta Advantage+ | Free (you pay for media only) | Default for sales, leads and app campaigns; generated images, image-to-video, text variants | – | A fully automated "URL + budget" product is targeted for end-2026, not confirmed live | [P15] |
| Google PMax / AI Max / Ask Advisor | Free | Asset Studio builds copy, images and video from a website; a Gemini agent builds campaigns | – | | [P16] |

No product in the small-business price band combines organic posts, reels, video ad creatives, Meta and Google management
and a daily report. Native comes closest, and because its entry plan now includes Meta ads, that sets the floor for Otto's
entry plan.

### 3.2 Ad-management software: how spend is priced

| Model | Examples | Effective rate at small-business spend |
|---|---|---|
| Flat fee, spend cap per tier | AdEspresso $49 up to $1k of spend, $99 unlimited [P13]. Bïrch Pro $99 up to $10k, $249 up to $30k [P12]. Madgicx from about $55–99 depending on spend band (3p) [P11]. | At $1k of spend: AdEspresso 4.9%, Bïrch 9.9% (est.) |
| Flat fee plus overage above a band | Bïrch monthly overage of 0.33–1.00% of spend (3p) [P12]. Optmyzr charges $3.50 per $1k above its bracket and auto-upgrades after two months over [P25]. WebFX (agency): $750 flat up to $5k of spend, then the higher of $975 or 15% [P27]. | WebFX at $2k of spend: 37.5% (est.) |
| Pure % of spend | Agencies 10–20% (section 3.4). Smartly 2–5% with a minimum of about €5k (3p) [P31]. Zeely up to 12% plus a subscription [P24]. | An agency at €1k of spend: €100–200, usually with a €300–1,000 minimum |
| Per ad account | AdAmigo $99 per ad account (aimed at under $2k of spend) or $349 [P22] | – |
| Flat, spend explicitly not charged | Native $79–499 [P2] · Ryze $89 [P23] · Adzooma $69 / $179 [P26] | Native Pro at $1k of spend: 7.9%, organic included (est.) |

### 3.3 What small businesses accept

- **Budgets are small, and price decides.**
  - 52% of small businesses spend under $1,000 a month on all marketing.
  - Price is the top reason for choosing a marketing partner.
  - Only 34% use outside marketing partners, down from 60%.
  - Source: LocaliQ 2026, 300+ owners, 87% of them in the US or Canada [P28].
  - In the UK, 77% of small-business owners run their own social media (Censuswide for Markel, 501 respondents) [H84].
- **Typical Meta budgets.**
  - Netherlands: €1,000–3,000 a month, with a floor of €300 [H12].
  - Ireland: €300–1,500 a month or more [H24].
  - UK firms with 2–10 staff: £1,000–2,500 [H18].
  - German Meta agencies say ad spend should be 2–3 times the management fee [H6]. Google Ads management is not worth it below about €1,500 a month of spend [H7].
  - So a €1,000 cap for Starter covers a typical starting budget, and €5,000 for Growth covers most small businesses.
- **Flat pricing beats a percentage for small advertisers.**
  - Below about $10k a month of spend, flat-priced software is cheaper than %-of-spend tools (3p) [P30].
  - Spend-band tools draw billing complaints, and small spenders pay the highest effective rate: Bïrch costs about 1% of spend at $10k versus 0.36% at $500k (3p) [P11][P12].
  - Native markets "never a percentage" [P2]. Otto should do the same: a flat fee, generous bands and no surprise bills.
- **Most firms do not advertise online at all.**
  - 32.6% of EU firms with 10+ staff paid for online ads in 2024 [C5]. Among micro firms the share is far lower: Portugal 13.8%, Spain 8.6% [C5].
  - The entry plan must therefore also work, and still be worth it, with ads switched off.

### 3.4 The human alternative, by country (€ per month unless noted)

| Country | Organic: agency entry package | Organic: freelancer | Paid social management | In-house social media manager | Src |
|---|---|---|---|---|---|
| **Netherlands** | €500–1,500 (1–2 platforms, 8–12 posts) | €300–750 a month; median €55/h | €500–2,500, or 10–20% of spend | €3,000–5,000 a month, fully loaded | [H9][H11][H12] |
| **Ireland** | From €900 (6 of 10 agencies listed); range €450–4,500 | Productised services €215–650 | Google Ads €400–1,500, or 10–20% | €40,000 a year | [H21][H22][H23][H25] |
| **Germany** | €500–2,000 | €75/h average; senior €623 a day on Malt | Meta: freelancers under €500, small agencies €500–1,500, agencies €1,500–3,500, or 10–20%; onboarding €400–2,000 | €38,600 a year | [H1][H2][H4][H6][H8] |
| Austria | €800–1,500 typical (from €250) | – | No Austrian source; use the German row (est.) | – | [H71] |
| **UK** | £400–1,500 (€467–1,750), regional agency | £300–600 (€350–700) | Freelancer £300–800 below £3k of spend; agency £750–2,500 (€875–2,917) or 10–20%, whichever is higher | £35,913 (€41.9k) a year | [H16][H17][H18][H20] |
| Belgium | €400–800 light; €1,200–3,000 full | – | 10–20% with a €400–600 minimum, or €300–1,500 flat | – | [H76][H77] |
| Portugal | €300–600 | €150–400; Zaask average €250 | €200–500, or 15–20% | about €24,000 a year (low confidence) | [H44][H45][H46][H47] |
| Spain | €150–900 packages; €300–700 standard | €132–210 a day on Malt | €300–800, or 10–20% (unv.) | €26,250 a year | [H48][H49][H50][H51][H54] |
| France | €500–900; median small-business agency budget €5,000 a year, ≈ €420 a month (unv.) | €256–446 a day on Malt | 10–20% of spend | – | [H55][H56][H57][H58] |
| Italy | €500–1,200 | – | 10–20% (5–10% above €20k of spend) | – | [H62] |
| Poland | €115–550 | – | €275–573 flat, up to 5k zł of spend | – | [H66][H67][H68] |
| Sweden | €442–883 | – | €707–1,590 at a small agency | – | [H29][H30] |
| Denmark | €401–669 | – | €401–1,338, or 10–25% | – | [H32] |
| Norway | €460–1,380 | – | 15–20%, or €635–1,104 flat | – | [H37][H38] |
| Finland | €800–2,500 (light upkeep €500–900) | – | A few hundred to about €1,000 | – | [H40] |
| Switzerland | Community management CHF 4,400–6,700 (≈ €4,650–7,080) (unv.) | – | CHF 600–1,700 (unv.) | CHF 76,800 a year | [H73][H75] |
| Israel (reference) | ₪2,500–7,000 (€720–2,017) | ₪800–3,000 | ₪2,000–8,000 (€576–2,305) | – | [H79][H80] |

In the Netherlands, Ireland and Germany, a small business replacing an agency pays €500–2,000 for organic, plus
€500–3,500 or 10–20% of spend for paid, often with a €400–2,000 setup fee. Against those ranges (est.):
- Starter (€99) is 80–95% below the agency entry price for organic alone.
- Growth (€249) is 75–90% below the combined agency cost of organic plus paid.

---

## 4. Recommended price ladder

### 4.1 Plans (EUR, excl. VAT)

| | **Starter** | **Growth** (pre-selected) | **Scale** | **Agency** |
|---|---|---|---|---|
| Monthly | **€99** | **€249** | **€499** | **from €499** |
| Yearly (two months free) | €990 (≈ €82.50 a month) | €2,490 (≈ €207.50) | €4,990 (≈ €415.83) | €4,990 |
| For | One business, with ads off or ad spend up to about €1k a month | Businesses spending €1k–5k a month on ads | Up to €15k a month on ads, or e-commerce brands that need creative volume | Agencies and multi-location groups |
| Brands | 1 | 1 | 1 | 5 client workspaces, each at Starter level |
| Organic each month | 50 feed posts and carousels, 12 stories, **4 reels** | Same, with **8 reels** | Same, with 8 reels | Starter, per workspace |
| Channels | Facebook and Instagram (LinkedIn and Google Business Profile once shipped) | Adds **Google Search ads** | Same as Growth | Same as Starter |
| Approvals | App and email, Telegram; WhatsApp once shipped | Same | Same | Same, plus client approval links |
| Morning briefing, drop alerts, month in review | Yes | Yes | Yes | Yes |
| Competitor watch | Monthly sweep | Weekly sweep plus ad-library winners | Weekly | Monthly, per workspace |
| Meta ads | **Yes**: boosts of the best posts, plus one always-on concept campaign | Concept-structured campaigns (one ad set per concept) | Same, with a faster refresh | Starter, per workspace |
| Ad creatives each month | **20** (4 concepts × 5 styles, ~10 video), a new set every month | **36 at launch** (6 × 6, ~18 video) plus **~26 refreshed** (1 per concept per week) | **48** (6 × 8, ~24 video) plus ~52 refreshed (2 per concept per week) | 20 per workspace |
| Creator-video briefs | – | Yes | Yes | – |
| Daily 07:35 paid report, CPL guard | Yes | Yes | Yes | Yes |
| Managed ad spend (soft cap) | Up to €1,000 a month | Up to €5,000 | Up to €15,000; above that, 2% of the excess | €1,000 per workspace |
| Human time | Async support, reply within one business day | A named strategist reviews each month's plan and ad matrix; reply within 4 business hours | Same, plus a monthly 30-minute call; same-day reply | Partner support, white-label reports |
| Add-ons | +€59 per extra brand | +€149 per extra brand at Growth level | +€149 per extra brand | +€79 per extra workspace; +€149 to lift a workspace to Growth |

**The plans match the engine.** The engine switches to a 4 × 5 "micro" ad matrix whenever the daily ad budget is under
€36 (≈ €1,095 a month; `otto_styles.MICRO_BELOW_DAILY_EUR`) [O3]. Starter's €1,000 cap (≈ €33 a day) sits under that
floor, so:
- Starter always runs the micro matrix.
- Growth runs the 6 × 6 `launch` preset.
- Scale runs the `scale` preset (6 × 8, faster refresh).

The plan a client buys and what the engine produces for them agree.

### 4.2 How the ads upgrade works

1. **Flat price inside each band.** Otto takes no percentage below €15,000 a month. It never holds ad money: Meta and Google bill the client's own ad account.
2. **Soft caps, not a hard stop.**
   - In the first month the budget runs above the plan's band, Otto still plans the full budget and says so on the plan card.
   - After two months in a row above the band, Otto plans at the cap and offers the next plan.
   - Optmyzr uses the same two-month rule [P25], and it avoids the surprise bills that draw complaints about spend-banded tools [P11].
   - Today `plans.json` plans at the cap straight away, so the one-month grace is a small code change.
3. **Above €15,000 a month: 2% of the spend above €15,000,** or a custom plan. That is far below agency fees (10–20%) and Smartly (2–5%) [P31]. Bïrch's overages are lower (0.33–1%) [P12], but Bïrch is a tool; Otto also makes the creatives.
4. **Effective rate at the top of each band:** Starter 9.9%, Growth 5.0%, Scale 3.3% of spend, with organic included (est.).

### 4.3 Yearly billing, refunds and trial

- **Yearly = two months free (≈ −17%).** Native gives −20% [P1]. Two months free keeps about 2–3 points more gross margin on yearly plans than −20% (est., section 5.2). The wording is worth an A/B test.
- **No free trial. Instead, a 14-day money-back guarantee on the first payment**, as proposed in `COMPETITORS-2026-09.md` §7 [O2]. The free step remains the live scan plus a preview of the first week.
- Monthly billing, cancel any time. Show "excl. VAT" next to every price; price in EUR everywhere except the UK.
- A/B tests once the pricing page has about 1,000 visitors:
  - Starter at €99 vs €79.
  - Growth at €249 vs €199.
  - "Two months free" vs "−20%".

### 4.4 The founding-seat bridge

Today, the €197 one-time founding seat buys a pilot month with Growth features. This is stated on the landing page, and
`plans.json` has `founding` inherit from `growth` [O6]. The landing FAQ promises that founding terms carry over. This
section makes that promise concrete.

1. **Keep selling the seat at €197 until subscriptions go live.** Cap it at 50 seats, and only show a "seats left" count if it is true.
2. **When plans open, or when a founder's pilot month ends,** each founder chooses between:
   - Growth at **€179 a month, locked for 12 months** (list €249, −28%), or
   - Starter at **€79 a month, locked for 12 months** (list €99, −20%).

   Their brand, history, taste log and campaigns carry over. Nobody onboards again.
3. **No automatic charge.** A one-time Whop purchase cannot turn into a subscription without the owner's consent, so each founder gets one card or email with the two choices.
4. **Why €179 and not €149.** A founding Growth plan at €149 runs at a gross margin of −7% to 47% (20% at the midpoint); at €179 it runs at 9–55% (32% at the midpoint). The higher figure is acceptable for 50 or fewer accounts that give feedback and case studies. After 60 days, ask each founder for a testimonial, but do not require one.
5. **Close the €197 offer on the day monthly plans go live,** with a dated notice.

### 4.5 UK prices (GBP), for months 3–6

Whop bills a subscription in the currency the customer checked out in; its adaptive pricing works only for one-time
payments [W5]. The UK therefore needs its own GBP plans:

| | Starter | Growth | Scale | Agency |
|---|---|---|---|---|
| Monthly | £85 | £215 | £425 | £425 |
| Yearly (two months free) | £850 | £2,150 | £4,250 | £4,250 |
| Managed ad spend | £850 | £4,250 | £12,500 | £850 per workspace |

These prices are roughly at parity with EUR at €1 = £0.857. Whop collects and remits UK VAT when its "collect and remit"
tax mode is on [W3].

### 4.6 What changes from `PRICING-EU.md` and `plans.json`

| Item | `PRICING-EU.md` (28.09) | `plans.json` today | Recommended | Why |
|---|---|---|---|---|
| Entry plan | Starter €69, organic only | `content`: organic only, the default for new brands | **Starter €99**, including Meta ads (micro matrix), 4 reels and the daily report | Native includes ads at $79 [P2]. With ads included, €69 leaves only a 3–49% margin (est., 5.2). |
| Middle plan | Growth €149 | `growth`: launch preset, €3,000 cap, 20 video ads | **Growth €249**, €5,000 cap, launch preset plus 1 refreshed creative per concept per week | A human strategist and the full matrix cost €86–167 a month (5.2). At €149, the margin is −7% to 47%. |
| Top plan | – | `scale`: 3 brands, €10,000 cap | **Scale €499**: 1 brand, €15,000 cap, `scale` preset, refresh of 2 per concept per week | Three brands with a paid layer each would cost about €160–330 a month (est.) |
| Agency | €399 for 10 workspaces | `agency`: inherits `scale`, 10 brands | **From €499 for 5 workspaces at Starter level**, +€79 per extra workspace | Ten workspaces with a paid layer each cost about €280–510 a month (est.), so €399 loses money |
| Yearly | −20% | – | Two months free | Margin |
| Founding | €197 once | `founding` inherits `growth` | Keep until plans open, then Growth €179 or Starter €79, locked 12 months | Section 4.4 |
| Organic only | – | `content` | Non-public fallback; after 60 days, test it at €69 as a cancel-flow downsell | Section 2 |

Suggested `plans.json` values. These are for whoever implements them; they replace the placeholders, and no code was
changed in this pass.

| Key | `starter` (new) | `growth` | `scale` | `agency` | `content` (non-public) |
|---|---|---|---|---|---|
| inherits | `content`, with ads on | `starter` | `growth` | `starter` | – |
| monthly_eur / yearly_eur | 99 / 990 | 249 / 2490 | 499 / 4990 | 499 / 4990 | null (test 69 later) |
| brands | 1 | 1 | 1 | 5 | 1 |
| posts_per_month (all organic items) | 66 | 70 | 70 | 66 per brand | 66 |
| reels_per_month | 4 | 8 | 8 | 4 | 4 |
| ads_meta / ads_google | true / false | true / true | true / true | true / false | false / false |
| ad_matrix_preset | micro | launch | scale | micro | none |
| ad_spend_managed_eur_month | 1000 | 5000 | 15000 | 1000 per brand | 0 |
| video_ads_per_month | 10 | 31 | 50 | 10 | 0 |
| refresh_per_angle_week | 0 | 1 | 2 | 0 | 0 |
| creator_briefs | false | true | true | false | false |
| competitor_sweep | monthly | weekly | weekly | monthly | monthly |

Also change `defaults.new` from `content` to `starter` once the Starter plan exists on Whop.

---

## 5. Unit economics

### 5.1 Cost assumptions (per brand per month)

| Line | Assumption | Basis |
|---|---|---|
| Organic content: 50 feed posts plus 12 stories (LLM plus images at ~$0.20 each) | €10–15 | Max's figure. `LAUNCH-READINESS.md`: about $0.20 per image, about $13 per brand per month at 66 images [O5] |
| Reel (30–60 s motion) | €1–2 each: 5–8 new scene images, €0.10–0.50 of voice, render compute (est.) | Server render time is not measured yet [O5] |
| Micro ad matrix: 20 creatives, ~10 video | Voice €1–5 plus LLM €5–15 = **€6–20** (est.) | Statics cost compute only |
| Launch matrix plus weekly refresh: ~62 creatives, ~31 video | Voice €3–16 plus LLM €10–30 = **€13–46** | Max's figures; refresh volume from `otto_styles` [O3] |
| Scale matrix plus refresh: ~100 creatives, ~50 video | **€26–81** (est.) | |
| Infrastructure | €25 a month for the whole server [O4]. If a video takes 2–4 minutes to render, one box handles roughly 200+ paid brands (est.). Allocated at €1–3 per brand. | |
| Human time | €35 an hour, fully loaded (est.): Starter 0.25–0.5 h, Growth 1–2 h, Scale 2–3 h | The biggest variable |
| Payments (Whop) | 2.7% + $0.30, plus 1.5% for international cards, plus 1% currency conversion, plus 2% when Whop collects tax. About **7.2% + €0.26** (conservative). | [W1] |
| Meta and Google APIs; ad spend | €0. The client's own ad account pays for the media. | |

### 5.2 Gross margin by plan

| Plan | Price | Cost (range) | Gross margin (range / midpoint) | Yearly price per month | Yearly margin (midpoint) |
|---|---|---|---|---|---|
| Starter | €99 | €37–69 | 30–62% / **46%** | €82.50 | 37% |
| Starter, ads switched off | €99 | €31–49 | 50–68% | – | – |
| Growth | €249 | €86–167 | 33–65% / **49%** | €207.50 | 41% |
| Scale | €499 | €153–256 | 49–69% / **59%** | €415.83 | 52% |
| Agency (5 workspaces) | €499 | €176–291 | 42–65% / **53%** | €415.83 | 45% |
| Founding Growth at €149 | €149 | €79–160 | −7–47% / 20% | – | – |
| Founding Growth at €179 | €179 | €81–162 | 9–55% / 32% | – | – |
| (Old) Starter €69 with ads | €69 | €35–67 | 3–49% | – | – |

**Machine cost alone gives healthy margins.** Without human time, margins would be 48–71% on Starter, 61–79% on Growth
and 70–83% on Scale (est.). Human time and the payment fee decide whether Otto reaches a typical software margin.

### 5.3 Customer acquisition cost and payback

**Otto's own Meta costs.**
- Lebesgue's 2026 e-commerce CPMs, converted to EUR [A1]: Netherlands €7.56, Ireland €7.27, Germany €7.97, UK €10.40, Portugal €5.30.
- Reaching business owners costs more than reaching consumers. At an assumed 1.2–1.8× (est.) that gives: Netherlands €9–14, Ireland €9–13, Germany €10–14, UK €13–19.

**Funnel (est.).**
- Link click-through rate of 0.8–1.0%. For comparison, B2B Facebook CTR is 0.79% [A5]; Superads reports 1.87–2.34% across all objectives [A3]. That gives a cost per click of €0.9–1.7.
- 15–25% of visitors complete a scan.
- 5–10% of scans convert to a paying customer. For comparison, 18.2% of opt-in trials convert to paid [A8]; a scan is a lighter step, so the rate should be lower.
- That puts the cost per paying customer at **€36–227**.

**What to plan with: €150–300 per customer.** For comparison: e-commerce software has an average acquisition cost of
$274 [A6], and a B2B lead from Facebook costs about $145 [A5].

**Payback.**
- With a 60/35/5 mix of Starter, Growth and Scale, average revenue is €171.50 per account per month, and contribution at midpoint margins is about €85 a month (est.).
- That pays back a €150–300 acquisition cost in **1.8–3.5 months**. The B2B software median is 16 months, and 11 months for contracts under $5k a year [A7].
- Churn, not acquisition cost, is the number to watch.

**Launch test budget.**
- €50 a day per country for 30 days: €3,000 across the Netherlands and Ireland.
- Run the three concepts in `COMPETITORS-2026-09.md` §6: the 7:35 message, "your website as a reel", and "local, not translated".
- At €150–300 per customer, that buys 10–20 paying customers (est.).

### 5.4 What moves the margin

1. **Human time.** Every 30 minutes per client per month costs €17.50: 18% of Starter's price, 7% of Growth's. Keep Starter support async, and automate first-line answers.
2. **Payment fees.** Whop's ~7.2% + €0.26 is the second-largest cost line. Review the payment setup at about €20k of monthly revenue; a direct processor plus a separate tax engine may be cheaper (unv.).
3. **Image cost.** Images at ~$0.20 each drive the organic cost. A cheaper model for stories and backgrounds could cut organic cost by up to half (est.).
4. **Yearly billing:** offer two months free, not −20%.
5. **Don't price Starter below about €89 while it includes ads.** At €69 with ads, the margin is only 3–49%.

---

## 6. Country selection

### 6.1 Method

Each country is scored 1–5 on nine criteria (5 = best for Otto). The weights add up to 100. Scores are my judgement from
the data in 6.2 and 6.3.

| Criterion | Weight | What it measures | Data |
|---|---|---|---|
| Market size | 15 | Small businesses, times the share that advertise online; Shopify stores | [C1]–[C5][C11][C12] |
| Willingness to pay | 15 | Local agency and freelancer prices; GDP per head | 3.4, [C8] |
| Product fit today | 15 | Tolerance for an English UI (EF EPI), whether the content language is in the engine, whether the team can check content quality | [C7] |
| Regulatory friction (inverted) | 15 | Health claims, aesthetics ads, warning-letter risk, GDPR and cookie enforcement | 6.3 |
| Client's ad money (inverted CPM) | 10 | Meta CPM: how far the client's budget goes | [A1]–[A4] |
| Otto's acquisition cost | 10 | CPM for Otto's own ads, plus competing noise | [A1][A9] |
| Competition (inverted) | 10 | Native, Holo and Blaze ads in the country; local tools | [A9] |
| Payments and VAT | 5 | EUR or not, Whop tax coverage, local payment methods | [W1]–[W5] |
| Digital and AI readiness | 5 | Firms using AI; firms using social media | [C5][C10] |

### 6.2 Data by country

In the table below: "micro" = 0–9 staff, "small" = 10–49 staff. The "Online ads" and "AI use" columns are shares of
firms with 10+ staff. FB/IG reach is the share of adults Meta can reach with ads. The CPM is Lebesgue's 2026
e-commerce figure, converted to EUR.

| Country | Micro firms | Small firms | Online ads (year) | AI use 2025 | FB / IG reach | EF EPI 2025 | GDP per head 2025 | Shopify stores | Meta CPM | Currency, winter UTC |
|---|---|---|---|---|---|---|---|---|---|---|
| **Netherlands** | 2.36M | 53.5k | 41.5% (24) | 33.2% | 49.9% / 54.2% | 624, #1 | $73.8k | 77.6k | €7.56 | EUR, +1 |
| **Ireland** | 379k | 25.6k | 42.1% (24) | 19.6% | 62.9% / 62.9% | native | $130.7k (inflated by multinationals) | 14.5k | €7.27 | EUR, +0 |
| **Germany** | 2.74M | 415k | 38.5% (24) | 26.0% | 32.7% / 44.2% | 615, #4 | $60.4k | 121.3k | €7.97 | EUR, +1 |
| Austria | 580k | 40.4k | 31.5% (18) | 30.0% | 40.3% / 44.3% | 616, #3 | $63.2k | 13.5k | €7.60 | EUR, +1 |
| **UK** | 5.42M | 220k | 31.5% (18) | n/a | 69.9% / 62.6% | native | $57.6k | 239k (BuiltWith) | €10.40 | GBP, +0 |
| Belgium | 896k | 28.2k | 30.2% (18) | 34.5% | 65.3% / 53.7% | 608, #9 | $61.0k | 21.1k | €7.01 | EUR, +1 |
| Portugal | 1.41M | 47.4k | 23.6% (24) | 11.5% | 71.2% / 71.8% | 612, #6 | $32.2k | 16.6k | €5.30 | EUR, +0 |
| Spain | 3.33M | 163k | 28.0% (24) | 20.3% | 50.3% / 65.4% | 540, #36 | $38.3k | 65.6k | €5.86 | EUR, +1 |
| France | 5.25M | 167k | 27.8% (24) | 18.2% | 58.7% / 53.7% | 539, #38 | $48.9k | 117.9k | €6.12 | EUR, +1 |
| Italy | 4.41M | 209k | 20.6% (18) | 16.4% | 56.5% / 58.8% | 513, #59 | $43.3k | 63.2k | €5.34 | EUR, +1 |
| Poland | 2.71M | 93.1k | 23.2% (24) | 8.4% | 60.3% / 39.5% | 600, #15 | $28.4k | 16.7k | €4.89 | PLN, +1 |
| Sweden | 832k | 33.3k | 44.3% (18) | 35.0% | 66.5% / 65.3% | 609, #8 | $62.7k | 26.1k | €7.15 | SEK, +1 |
| Denmark | 348k | 25.9k | 46.6% (18) | 42.0% | 69.9% / 55.5% | 611, #7 | $77.0k | 20.1k | €7.70 | DKK, +1 |
| Norway | 445k | 25.6k | 46.8% (24) | 28.9% | 67.3% / 57.4% | 613, #5 | $94.5k | n/a | €6.44 | NOK, +1 |
| Finland | 457k | 17.6k | 49.8% (24) | 37.8% | 51.9% / 51.9% | 603, #12 | $56.5k | 8.2k | €6.80 | EUR, +2 |
| Switzerland | 562k (2023) | 52.5k (2023) | n/a | n/a | 40.0% / 51.5% | 564, #30 | $115.6k | n/a | €7.40 | CHF, +1 |
| Israel (reference) | 647k (2023) | 40.3k (2023) | n/a | n/a | 77.1% / 74.0% | 524, #46 | $60.3k | n/a | €6.59 | ILS, +2 |
| EU27 | 31.2M (2023) | 1.57M | 32.6% (24) | 20.0% | – | – | – | – | – | – |

Sources:
- Firm counts: Eurostat 2024 [C1]; UK DBT 2025 [C2]; Swiss FSO 2023 [C3]; Israel CBS 2023 [C4].
- Online ads: Eurostat [C5]. Five countries have no 2024 figure, so the 2018 figure is shown ("(18)").
- AI use: Eurostat 2025 [C10].
- FB/IG reach: DataReportal 2026 [C6].
- EF EPI [C7]; GDP per head: IMF, nominal [C8].
- Shopify stores: Storeleads, June 2026 [C11], and BuiltWith for the UK [C12]. The two use different methods, so compare them loosely.
- Meta CPM: Lebesgue [A1]. Other sources run higher: Superads' medians are UK $17.38, Germany €14.8, Netherlands $14.2 [A3].

Other facts that shaped the scores:
- **Messaging apps.** 98% of people in the Netherlands and 83% in Germany use instant messaging (EU 82%) [C15]. WhatsApp is the default; Telegram is a minority app (unv.). That is why Otto's approvals must move beyond Telegram.
- **LinkedIn members.** Netherlands 14.0M, UK 48.0M, Germany 24.0M, Ireland 3.7M [C6]. In the Netherlands in particular, the founder's LinkedIn is a real channel.
- **Buying software.** 39.8% of Dutch firms with 10+ staff buy CRM software, second only to Finland (39.9%) [C9].
- **Where competitors advertise.** Native's active Meta ads reach Great Britain (81), the US (78), Ireland (56) and Australia (34), with none in Germany or Norway; on 29.09 only 2 of its 86 ads reached Germany, France, the Netherlands, Sweden, Denmark, Spain and Italy combined [O2]. Holo runs 770 active ads that reach almost every European market, e.g. the UK 558, Spain 238, Germany 223, the Netherlands 163. Blaze has 0 active ads. [A9]
- **Local tools.**
  - Germany: Fanpage Karma, Swat.io and Uberall.
  - Spain: Metricool.
  - France: Agorapulse and Swello.
  - Poland: NapoleonCat and Brand24.
  - Switzerland: localsearch digitalONE, the closest local done-for-you rival.
  - No local done-for-you "AI social plus ads" player was found in the Netherlands or Ireland [A9] (partly unv.).

### 6.3 Friction: regulation, payments and language

Regulation is scored 1–5, where 5 = highest friction. For GDPR, "n" is the number of cases in the CMS Enforcement Tracker,
based on a dataset download of 30.09.2026 [R1].

| Country | Health and supplement claims | Aesthetics and medical ads | Warning letters, litigation | GDPR and cookies | Language law | Payments and VAT |
|---|---|---|---|---|---|---|
| **Netherlands** | 5: supplement ads are pre-cleared by the Keuringsraad, and approval numbers are the norm [R4] | 3 | 2 | 3 (n=44; the Dutch DPA warned 200+ sites over cookie banners) [R24] | None for B2B | EUR; iDEAL and SEPA on Whop; Whop remits VAT |
| **Ireland** | 3 (EU claims register) | 3 | 1 | 2 (n=39, almost all big tech) | None | EUR; Whop remits VAT |
| **Germany** | 5: warning letters from the Wettbewerbszentrale, which filed 241 court cases in 2025 (+18.1%) [R10] | 5: before/after images are banned, and since 31.07.2025 that includes fillers that reshape the nose or chin [R8] | 5: Impressum rules (§5 DDG) also apply to business social profiles [R9] | 3 (n=218, median fine €16k; private damage claims) | None for B2B | EUR; SEPA and PayPal on Whop; the German e-invoicing mandate covers German-established sellers only [V5] |
| Austria | 4 | 4 (unv.) | 4 (Impressum under ECG and MedienG) [R21] | 2 (n=40; noyb is based in Vienna) | None | EUR |
| **UK** | 4: only claims on the GB register; the ASA monitors with AI tools [R5] | 4: no Botox (prescription-only medicine) advertising, not even in hashtags; cosmetic-procedure ads must not target under-18s [R6][R7] | 2 | 2 (n=28) | None | GBP plans; Whop remits UK VAT [W3] |
| Belgium | 3–4 | **5: all advertising of cosmetic surgery and non-surgical aesthetic medicine is banned** [R11] | 3 | 2 (n=52) | Consumer information in the region's language (unv.) | EUR; Bancontact on Whop |
| Portugal | 2 | 3 (unv.) | 1 | 1 (n=7) | Consumer information in Portuguese (unv.) | EUR; MB Way is not on Whop |
| Spain | 4 | 4: health centres' ads need prior authorisation [R20] | 2 | **5** (n=1,079, median fine €5k; 41% of the data regulator's sanctions hit small firms) [R3] | Consumer terms in Spanish (unv.) | EUR |
| France | 4 | 5: influencers may not promote aesthetic procedures; a decree of 23.09.2026 lets authorities withdraw a clinic's licence over its communications [R19] | 3 | **5** (n=83, median fine €400k; CNIL: 21 cookie cases in 2025) [R2] | **Loi Toubon: ads and user instructions must be in French** [R13] | EUR |
| Italy | 4 | 4: promotional elements are banned in health advertising [R18] | 2 | **5** (n=600, median fine €10k) | None general | EUR |
| Poland | 3 | 4 (unv.) | 2 | 3 (n=116) | Polish required for B2C; B2B may use English [R14] | PLN; BLIK is not on Whop |
| Sweden, Denmark, Finland | 3 | 3–4 | 1–2 | 2–3 (Sweden fined a pharmacy SEK 37m over the Meta pixel) [R23] | None | SEK/DKK on Whop, EUR for Finland |
| Norway | 3 | 5: before/after ban, plus a mandatory label on retouched ads [R12] | 2 | 3 (n=58) | None | NOK; **outside Whop's VAT remittance**; the VOEC scheme applies to consumer sales [V4] |
| Switzerland | 3 (unv.) | 3 (unv.) | 2 | 1 (not under GDPR) | None | CHF; **outside Whop's VAT remittance**; registration is required above CHF 100k worldwide turnover, with a fiscal representative [V3] |
| Israel (reference) | 3 | 3 | 4 (class actions; unv.) | 2–3 (unv.) | None for B2B | ILS on Whop; 18% domestic VAT (unv.) |

Rules that apply in every EU country:
- **VAT.**
  - Business customers (B2B) pay by reverse charge.
  - Consumers, and firms without a VAT ID, pay VAT through the non-Union OSS scheme, with no threshold for a non-EU seller [V1].
  - In "collect and remit" mode, Whop is the merchant of record for VAT in the EU and UK only. For everything else, the Israeli entity is the supplier [W2][W3].
  - Whop's documents do not say how reverse charge is shown on invoices, so confirm that with Whop.
- **EU AI Act Art. 50** applies from 2 August 2026 [R15].
  - Machine-readable marking of generated output is the provider's duty, which means Otto's.
  - Systems already on the market before 2 August 2026 have until 2 December 2026.
  - Disclosing deepfakes, and AI-written text on public-interest topics such as health, is the client's duty, unless a human reviewed the text editorially.
- **Meta restricted categories.**
  - Since January 2025, Meta classifies health and wellness domains into three levels (3p) [R16].
  - At the middle level, Lead, AddToCart and Purchase events are blocked, so Meta cannot optimise lower-funnel campaigns for these clients.
  - Supplement and clinic accounts therefore get pushed towards traffic objectives or Meta's instant forms.
- **Political ads.** Since 6 October 2025, Meta runs no political or social-issue ads in the EU. Ads that touch those themes risk rejection [R17].

### 6.4 Scores

Criterion scores are 1–5 (5 = best for Otto). The total is the weighted score out of 100.

| Rank | Country | Size (15) | Pay (15) | Fit (15) | Regulation (15) | Client CPM (10) | Otto acquisition (10) | Competition (10) | Payments (5) | Readiness (5) | **Score** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Netherlands** | 3 | 4 | 4.5 | 3 | 3 | 4 | 4 | 5 | 5 | **75.5** |
| 2 | Portugal | 2.5 | 2 | 4 | 4.5 | 5 | 4.5 | 4 | 4 | 2 | 72.0 |
| 3 | **Germany** | 5 | 5 | 3 | 1.5 | 3 | 3 | 3 | 5 | 4 | 70.5 |
| 4 | Belgium | 2.5 | 3.5 | 4 | 2.5 | 3.5 | 3.5 | 4 | 5 | 4.5 | 69.0 |
| 5 | **UK** | 5 | 4 | 5 | 3 | 2 | 2 | 1 | 3 | 4 | 68.0 |
| 6 | **Ireland** | 1 | 4 | 5 | 4 | 3 | 3 | 2 | 5 | 4 | 67.0 |
| 7 | Austria | 2 | 4 | 3 | 2.5 | 3 | 3.5 | 4 | 5 | 4 | 64.5 |
| – | Israel (reference) | 2 | 3 | 4 | 3 | 4 | 4 | 3 | 3 | 3 | 64.0 |
| 8 | Finland | 1 | 3.5 | 2 | 4 | 3.5 | 3.5 | 4 | 5 | 5 | 63.5 |
| 9 | Italy | 5 | 2.5 | 1 | 2.25 | 5 | 4 | 3 | 5 | 2 | 63.2 |
| 10 | Switzerland | 2 | 5 | 3 | 4 | 2.5 | 2.5 | 3 | 2 | 3 | 63.0 |
| 11 | Sweden | 2 | 4 | 2 | 3 | 3 | 3.5 | 4 | 3 | 5 | 62.0 |
| 12 | Spain | 4.5 | 2 | 2 | 2.25 | 4.5 | 4 | 2.5 | 4 | 3 | 61.2 |
| 13 | Denmark | 1.5 | 4 | 2 | 3 | 3 | 3.5 | 4 | 3 | 5 | 60.5 |
| 14 | France | 5 | 3 | 1.5 | 1.75 | 4 | 3.5 | 2 | 5 | 2.5 | 60.2 |
| 15 | Norway | 1.5 | 5 | 2 | 3 | 3.5 | 3 | 2.5 | 2 | 4.5 | 59.0 |
| 16 | Poland | 3.5 | 1 | 2 | 3 | 5 | 4.5 | 2 | 2.5 | 1 | 55.0 |

"Fit" is capped at 2 for the Nordics and Poland because their languages are not in the engine today (the engine writes
EN, DE, NL, PT, ES, FR, IT and HE). It is capped at 1–2 for Spain, France and Italy because EF rates their English as
"moderate" [C7]; France also requires French for ads and user instructions [R13]. EF EPI measures self-selected test
takers, so owners of trade businesses will be weaker in English than the index suggests (est.).

### 6.5 Reading the scores, and where I override them

- **Netherlands, launch first (75.5).**
  - Best English in Europe; Dutch content already in the engine; EUR, with iDEAL and SEPA on Whop.
  - 41.5% of firms pay for online ads; 77.6k Shopify stores; 39.8% of firms buy CRM software, second in Europe only to Finland (39.9%) [C9].
  - Native barely advertises there [O2][A9]. The one real friction is supplements (Keuringsraad pre-clearance), so skip that vertical at launch.
- **Ireland, launch second (67), overriding Portugal (72).**
  - Ireland scores sixth only because it is small (25.6k small firms). Otherwise it is the market where 100% of Otto works as built today.
  - Online ad adoption is 42.1%, and the going rate for an agency is €900 a month [H22].
  - The team can check every word Otto writes in month one, while the loop is still being proven.
  - Native's presence (56 active ads [A9]) means owners already understand the category. Otto answers the comparison they already make with reels, Google and the daily report.
  - Irish results and case studies carry straight into the UK.
- **Portugal (72), optional low-cost test only.**
  - It has cheap media (CPM €5.30), the lowest regulatory friction and good English.
  - But only 23.6% of firms pay for online ads [C5], AI adoption is 11.5% [C10], and local social management costs €250–600 [H44][H45].
  - Growth upgrades, where Otto's margin and differentiation live, depend on ad budgets.
  - Use it for hospitality and English-speaking owners if a cheap test is wanted.
- **Germany with Austria, months 3–6 (70.5 and 64.5).**
  - The biggest pool of money: 415k small firms, 121k Shopify stores and the highest freelance rates.
  - It also has the highest friction: health-advertising law (HWG), warning letters under competition law (UWG) and the Impressum. Owners expect a German UI and German legal pages.
  - Start it once the loop is proven and the German UI ships. Austria rides along in the same language.
- **Belgium (69): run it as a spillover, not a launch.** Flanders reads Dutch, so the Dutch campaigns can target it. Exclude aesthetics, because Belgium bans all advertising for cosmetic procedures [R11].
- **UK, months 3–6 (68).**
  - The largest English-speaking market: 5.4M micro firms and 239k Shopify stores.
  - But it is Native's biggest market (81 active ads), Holo runs 558 ads there, and the CPM is the highest in Europe (+38% vs the Netherlands).
  - Enter after the Irish proof, with GBP plans and the ASA rules built into the compliance baseline.
- **Nordics, months 6–12 (59–63.5).** These countries have the highest AI readiness (42% of Danish firms use AI [C10]), but Swedish, Danish, Norwegian and Finnish are not engine languages yet. Norway is also Native's home market and outside Whop's VAT remittance.
- **Spain, Italy and France, month 9 or later (60–63).** They are big markets with cheap media, but they need a localised UI. They also have the most active cookie and GDPR enforcement in Europe, and France requires French by law.
- **Poland, last (55).** It has the lowest willingness to pay (agencies €115–550 a month) and 8.4% AI adoption.
- **Israel (64, reference).** Hebrew and right-to-left layouts work, and Max's network is there. Keep serving Israeli clients (Whop supports ILS plans [W1]), but Israel is not part of the EU launch.

---

## 7. Launch plan by country

| | **Netherlands** | **Ireland** | Germany + Austria | UK | Flanders (BE) | Portugal (optional) |
|---|---|---|---|---|---|---|
| When | Month 0 | Month 0–1 | Month 3–4 | Month 4–6 | Month 1, as spillover | Any time, as a small test |
| Verticals first | 1) Shopify and e-commerce (not supplements); 2) hospitality: restaurants, cafés, hotels and B&Bs; 3) non-medical salons (hair, nails, massage) and local services | 1) Trades and local services (Native has proved the demand); 2) hospitality and tourism; 3) dental and physio clinics; education and training providers | 1) Shopify and e-commerce (121k + 13.5k stores); 2) hospitality and tourism (strong in Austria); 3) trades and local services; courses | 1) Trades and local services; 2) hospitality; 3) e-commerce | Same as the Netherlands | Hospitality and tourism; English-speaking owners |
| Avoid at first | Supplements (Keuringsraad pre-clearance); injectables | Prescription-medicine aesthetics (Botox); supplements unless claims are on the register | Aesthetics (HWG, the fillers ruling) and supplements (UWG) until the German baseline is proven | Aesthetics (Botox ban, under-18 rules) and supplements (GB register) | **All aesthetics** (Belgian ban) | – |
| How to reach them | Otto's own Meta ads in Dutch (Instagram reaches slightly more adults than Facebook); founder LinkedIn (14M members); Shopify and web agencies as Agency-plan partners | Meta ads in English (Facebook and Instagram equal at 62.9%); LinkedIn; Chambers Ireland and Local Enterprise Office networks. Check whether the Trading Online Voucher can pay for Otto (unv.) | Instagram-first Meta ads in German (IG 44.2% vs FB 32.7%); Google Search; Shopify agencies; "hosted in Germany" as a trust line | Meta (Facebook leads at 69.9%); founder LinkedIn (48M members); position against Native with reels, Google, the daily report and a human | Dutch ads targeted at Flanders | Meta at €5.30 CPM |
| Price and payment | EUR; iDEAL, SEPA and cards | EUR; cards and SEPA | EUR; SEPA Direct Debit, PayPal and cards | GBP plans; cards | EUR; Bancontact | EUR; cards and SEPA |
| UI / content / support language | EN / NL / EN | EN (Irish English) / EN / EN | **DE** / DE / DE | EN (British English) / EN / EN | EN / NL / EN | EN / PT / EN |
| Time zone | Europe/Amsterdam (UTC+1) | Europe/Dublin (UTC+0) | Europe/Berlin, Europe/Vienna (UTC+1) | Europe/London (UTC+0) | Europe/Brussels | Europe/Lisbon (UTC+0) |

Support hours: Israel is one hour ahead of CET in winter and two hours ahead of Dublin and London. A 09:00–18:00 CET
support window, staffed from Israel, covers every launch market.

---

## 8. Product changes before each country

| Change | NL | IE | DE/AT | UK | Why |
|---|---|---|---|---|---|
| Email and in-app approvals with push as the default; Telegram opt-in | Before launch | Before launch | Before launch | Before launch | Telegram is a minority app; 98% of Dutch people use instant messaging [C15] |
| WhatsApp approvals | Month 2 | Month 2 | **Before launch** | Before launch | WhatsApp is the default messenger (COMPETITORS §4 [O2]) |
| UI, onboarding, emails and approval cards | English OK | English OK | **German required** | English (British spelling) | EF EPI; buyer expectation (est.) |
| Legal pack: Terms (B2B), Privacy, data processing agreement (GDPR Art. 28) and sub-processor list, refund policy | Before launch | Before launch | German versions: AGB, Datenschutzerklärung, AVV, plus an **Impressum** on Otto's site | UK versions | Dutch and German buyers ask for the processing agreement (est.); Impressum rules [R9] |
| Cookie banner where rejecting is as easy as accepting | Before any paid traffic | Same | Same | Same | Dutch DPA campaign; CNIL; Spanish regulator [R1][R2][R3] |
| Machine-readable marking of AI images and video (C2PA / IPTC metadata) | Before launch | Before launch | Before launch | Recommended | AI Act Art. 50(2); grace until 2.12.2026 only for systems already on the market [R15] |
| Whop plans in EUR (monthly and yearly), local payment methods on, "collect and remit" tax mode; confirm reverse-charge invoice wording | Before launch | Before launch | SEPA Direct Debit, PayPal | **GBP plans** | [W1]–[W5] |
| Pricing page: subscriptions, "excl. VAT", founding bridge; remove "€197 once" when plans go live | Before launch | Before launch | German page | GBP page | Section 4 |
| Brand defaults from the website domain (time zone, language, currency; `ap.brand_countries`) | Check `.nl` | Check `.ie` and Irish English | Check `.de` / `.at` | `.co.uk`, British English | LAUNCH-READINESS fix #4 [O5] |
| Compliance baseline per country | Supplements held unless the client has a Keuringsraad number; EU claims register | ASAI code and EU register; no prescription medicines; 18+ for cosmetic procedures | HWG: no before/after for aesthetic procedures, including fillers; EU register; UWG. Onboarding checks the client's profiles for an Impressum link | GB claims register; CAP 12.12 (no Botox, not even hashtags); under-18 rules (under-18s must be under 25% of the audience) | [R4]–[R10] |
| Meta health and wellness restriction: plan clinics and supplements around instant forms or traffic objectives, and tell the owner up front | Yes | Yes | Yes | Yes | [R16] |
| Native-speaker review of the first month for each new client, until approval and edit rates prove quality | Dutch reviewer (≈1 h per client, est.) | – | German reviewer | – | The team cannot judge Dutch or German copy |
| Move production to the Hetzner EU server before paying customers | Before launch | Before launch | Say "hosted in Germany" | – | `HOSTING.md` [O4] |
| One-month grace on the ad-spend cap (section 4.2); `defaults.new` → `starter` | Before plans launch | Same | Same | Same | Section 4.6 |

---

## 9. Risks and open items

1. **Human time decides the margin.** Keep Starter async-only, and measure hours per client from day one. If Growth needs more than 2 hours a month per client, raise the price or narrow what the strategist does.
2. **Whop.**
   - Whop is merchant of record only for card settlement, and for EU and UK VAT when its "collect and remit" mode is on; Norway and Switzerland are not covered [W2][W3].
   - Fees are about 7.2% + $0.30.
   - Its handling of B2B reverse charge is not documented. **Ask Whop before launch.**
3. **Scope of Meta's health restrictions in the EU and UK** comes from secondary sources only [R16]. Test with one clinic before selling that vertical at scale.
4. **CPM benchmarks** are third-party e-commerce data, and the 1.2–1.8× multiplier for reaching business owners is my estimate. Replace both with Otto's own numbers after the first €3,000 test.
5. **Native could follow quickly.** It already writes posts in 183 languages [O2] and could add EUR pricing or video. Otto's lasting edges are reels and video ads, Google, the daily report and a human in the owner's time zone. Ship them as the headline, not as fine print.
6. **Reel render time on the server is not measured** [O5]. The capacity figure (~200 paid brands per box) depends on it.
7. **The UK DMCC subscription rules** (consumer contracts only) start in January 2027 or spring 2027; sources conflict [R22]. Build a clean cancel flow anyway.
8. **Unverified items** to check before relying on them:
   - Ireland's Trading Online Voucher.
   - Aesthetics advertising rules in Austria, Denmark and Poland.
   - Telegram penetration by country.
   - Canva Grow's EU launch date.
9. **Owner decisions needed:**
   - Approve the ladder, or pick from the A/B pairs: Starter €99 vs €79; Growth €249 vs €199.
   - The founding bridge: €179 or €149.
   - The €3,000 launch test budget.
   - A Dutch reviewer.
   - The Whop reverse-charge question.

---

## 10. Sources

All accessed 30.09.2026 unless a date is shown. "3p" = third-party write-up; "s" = figure read from a search result
because the page blocked direct access.

**Pricing: tools and ad software**
- [P1] Native pricing (page updated Aug 2026): https://native.no/pricing
- [P2] Native Ads Autopilot: https://native.no/ads-on-autopilot
- [P3] Blaze: https://www.blaze.ai/pricing
- [P4] Ocoya: https://www.ocoya.com/pricing
- [P5] Predis (3p): https://aiproductivity.ai/pricing/predis (Aug 2026); https://socialrails.com/blog/predis-pricing (01.01.2026)
- [P6] Hootsuite: https://www.hootsuite.com/plans ; https://napoleoncat.com/blog/hootsuite-pricing/ (18.08.2026)
- [P7] Buffer: https://buffer.com/pricing
- [P8] Jasper: https://www.jasper.ai/pricing
- [P9] AdCreative.ai (3p): https://www.tryatria.com/blog/adcreative-ai-pricing (11.08.2026)
- [P10] Pencil: https://www.trypencil.com/pricing
- [P11] Madgicx: https://madgicx.com/pricing ; https://academy.madgicx.com/lessons/choose-madgicx-plan ; https://www.get-ryze.ai/blog/madgicx-pricing-2026 (Aug 2026, 3p)
- [P12] Bïrch: https://bir.ch/pricing ; https://soku.ai/alternatives/birch-revealbot/review (14.09.2026, 3p)
- [P13] AdEspresso: https://adespresso.com/pricing/
- [P14] Canva (3p): https://designrr.io/canva-pricing (Jun 2026); https://omr.com/en/reviews/product/canva-pro/pricing (Sep 2026); Canva Grow 2.0 press release, Business Wire (25.06.2026)
- [P15] Meta Q2 2026 earnings call transcript, fool.com (call 29.07.2026); https://hawky.ai/blog/meta-ads-updates-2026 (24.07.2026, 3p)
- [P16] Google Marketing Live 2026: https://business.google.com/ca-en/accelerate/googlemarketinglive/
- [P17] Holo: https://tryholo.ai/pricing
- [P18] Marky: https://www.mymarky.ai/pricing
- [P19] Metricool: https://metricool.com/pricing/
- [P20] SocialBee: https://socialbee.com/pricing/
- [P21] Simplified: https://simplified.com/pricing
- [P22] AdAmigo: https://www.adamigo.ai/pricing
- [P23] Ryze: https://www.get-ryze.ai/pricing
- [P24] Zeely: https://zeely.ai/pricing
- [P25] Optmyzr: https://www.optmyzr.com/pricing/ ; https://help.optmyzr.com/en/articles/11503422 (Sep 2026)
- [P26] Adzooma: https://www.adzooma.com/pricing
- [P27] WebFX: https://www.webfx.com/ppc/pricing/
- [P28] LocaliQ Small Business Marketing Trends 2026: https://localiq.com/blog/small-business-marketing-trends-report-2026/
- [P30] adlibrary (3p, 08.05.2026): https://adlibrary.com/posts/ai-advertising-platform-pricing
- [P31] Smartly (3p, 22.08.2026): https://www.tryatria.com/blog/smartly-io-pricing

**Human alternatives**
- [H1] freelancermap Freelancer-Kompass 2026 (s): https://www.freelancermap.de/marktstudie
- [H2] Malt DE rate barometer (s): https://www.malt.de/t/tarifbarometer/kommunikation/social-media-manager
- [H4] https://agenturfinder.com/social-media-agentur-preise/ (2026)
- [H6] https://ledistagency.de/blog/meta-ads-agentur-kosten (14.05.2026)
- [H7] https://ledistagency.de/blog/google-ads-agentur-kosten (27.07.2026)
- [H8] StepStone (s): https://www.stepstone.de/gehalt/Social-Media-Manager-in.html
- [H9] https://uurtariefcheck.nl/uurtarief/social-media-manager/ (14.09.2026)
- [H11] https://searchlab.nl/kosten/wat-kost-social-media-marketing-uitbesteden (17.03.2026)
- [H12] https://www.empowers.nl/blogs/social-ads/meta-ads-uitbesteden-bureau-jou (29.03.2026)
- [H16] https://wise.com/gb/blog/cost-of-outsourcing-social-media (28.04.2026)
- [H17] https://www.beeviral.co.uk/blog/how-much-does-social-media-management-cost-in-the-uk-2026-honest-guide (03.04.2026)
- [H18] https://www.lilachbullock.com/what-does-running-facebook-ads-cost/ (2026)
- [H20] Glassdoor UK (s): https://www.glassdoor.co.uk/Salaries/social-media-manager-salary-SRCH_KO0,20.htm
- [H21] https://www.socialmediamanager.ie/social-media-pricing (undated)
- [H22] https://brandfire.ie/agencies-in-ireland/social-media-agencies (06.08.2026)
- [H23] https://agiledigitalstrategy.com/ppc/google-ads-cost-ireland-2026/ (04.08.2026)
- [H24] https://www.bubblehub.ie/blog/how-much-do-facebook-ads-cost (20.09.2026)
- [H25] Glassdoor IE (s): https://www.glassdoor.ie/Salaries/social-media-manager-salary-SRCH_KO0,20.htm
- [H29] https://www.swivrr.se/priser/vad-kostar-social-media ; [H30] https://www.swivrr.se/priser/vad-kostar-meta-ads
- [H32] https://www.bureauoversigten.dk/artikler/priser/hvad-koster-social-media-marketing (08.03.2026)
- [H37] https://elevera.no/blogg/sosiale-medier-bedrift-pris (12.04.2026) ; [H38] https://visionmedia.no/blog/facebook-ads-pris
- [H40] https://someapuri.fi/blog/somemarkkinoinnin-hinta (17.07.2026)
- [H44] https://www.borange.pt/quanto-custa-gestao-redes-sociais/ ; [H45] https://www.zaask.pt/quanto-custa/gestao-de-redes-sociais ; [H46] https://cliquecerto.pt/blog-quanto-custa-agencia-marketing (20.06.2026) ; [H47] https://pt.indeed.com/career/social-media/salaries (20.09.2026, 10 salaries)
- [H48] https://calculadora.malt.es/sub-category/community-manager ; [H49] https://www.venderporinternet.org/precios-y-tarifas-de-un-community-manager/ ; [H50] https://losmonoscreativos.com/precios-para-gestion-de-redes-sociales-espana/ ; [H51] (s) https://osyrismarketingdigital.com/blog/agencia-meta-ads-que-hace-como-elegir-precios ; [H54] Glassdoor ES (s): https://www.glassdoor.es/Sueldos/community-manager-sueldo-SRCH_KO0,17.htm
- [H55] Malt FR (s): https://www.malt.fr/t/barometre-tarifs/communication/community-manager ; [H56] https://www.ckc-net.com/blog/cout-gestion-reseaux-sociaux-agence (Apr 2026) ; [H57] (s) https://www.lafabriquedunet.fr/agences/pages/agences-social-media/tarifs ; [H58] https://www.aep-digital.com/tarif-gestion-campagnes-facebook-ads/ (25.02.2026)
- [H62] https://www.migliore-agenzia.com/it/blog/costo-gestione-social-media-agenzia-2026 (26.03.2026)
- [H66] https://napoleoncat.com/pl/blog/prowadzenie-social-media/ (2025 prices) ; [H67] https://kcmobile.pl/artykuly/ile-kosztuje-prowadzenie-social-media-cennik-2026/ (12.09.2026) ; [H68] https://kcmobile.pl/artykuly/ile-kosztuje-reklama-facebook-cennik-2026/ (09.04.2026)
- [H71] https://www.herold.at/ratgeber/social-ads/social-media-betreuung-kosten-oesterreich/ (15.06.2026)
- [H73] (s) https://www.gryps.ch/produkte/social-media-management-40/kosten/ ; [H75] https://www.jobs.ch/en/salary/?canton=ch&term=social+media+manager
- [H76] https://agence-limitless.com/blog/2026/01/22/cout-agence-reseaux-sociaux-belgique/ ; [H77] https://yelram.be/blog/marketing-digital/cout-facebook-ads-belgique/ (01.06.2026)
- [H79] https://ckdigital360.co.il/sushial-media/nihul-social-media-le-esek-israel-2026/ (Jul 2026) ; [H80] https://airdigital.co.il/facebook-ads-cost-israel-2026/ (03.05.2026)
- [H84] Censuswide for Markel: https://www.markeluk.com/knowledge-centre/trades-and-social-media-uk

**Country data**
- [C1] Eurostat sbs_sc_ovw (updated 15.09.2026): https://ec.europa.eu/eurostat/databrowser/view/sbs_sc_ovw/default/table
- [C2] UK DBT Business population estimates 2025 (02.10.2025): https://www.gov.uk/government/statistics/business-population-estimates-2025/business-population-estimates-for-the-uk-and-regions-2025-statistical-release
- [C3] Swiss FSO STATENT 2023 via HSG/OBT KMU-Studie 2026: https://kmu.unisg.ch/fileadmin/user_upload/HSG_ROOT/Institut_KMU/Forschung/KMU_in_Zahlen/2026_OBT_KMU_in_Zahlen/2026_KMU_in_Zahlen_OBT_KMU_Studie_2026.pdf
- [C4] Israel CBS Business Demography 2023: https://www.cbs.gov.il/he/publications/doclib/2024/business_demo2023/t4_2023.pdf
- [C5] Eurostat isoc_cismt (updated 27.02.2026): https://ec.europa.eu/eurostat/databrowser/view/isoc_cismt/default/table ; news of 14.08.2025: https://ec.europa.eu/eurostat/web/products-eurostat-news/w/ddn-20250814-2 ; news of 12.06.2026: https://ec.europa.eu/eurostat/web/products-eurostat-news/w/ddn-20260612-2
- [C6] DataReportal "Digital 2026 <country>" (published 05–08.11.2025), e.g. https://datareportal.com/reports/digital-2026-netherlands (same pattern for each country)
- [C7] EF English Proficiency Index 2025: https://www.ef.com/wwen/epi/
- [C8] IMF World Economic Outlook, April 2026 (14.04.2026), NGDPDPC
- [C9] Eurostat isoc_cicce_use: https://ec.europa.eu/eurostat/databrowser/view/isoc_cicce_use/default/table
- [C10] Eurostat, Use of AI in enterprises 2025 (news of 11.12.2025): https://ec.europa.eu/eurostat/web/products-eurostat-news/w/ddn-20251211-2 ; https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Use_of_artificial_intelligence_in_enterprises ; country figures (3p, 26.05.2026): https://www.implicator.ai/denmark-leads-europe-in-business-ai-use-at-42-eurostat-data-shows/ ; Italy 16.4%: Istat "Imprese e ICT, anno 2025" https://www.istat.it/wp-content/uploads/2025/12/Statreport_ICT2025.pdf ; Portugal 11.54%: https://www.essential-business.pt/2025/12/15/ai-take-up-in-portugal-low-compared-to-eu-average-but-gaining-traction/
- [C11] Storeleads via eightx (18.06.2026): https://eightx.co/blog/eu-shopify-landscape
- [C12] BuiltWith via DemandSage (05.08.2026): https://www.demandsage.com/shopify-statistics/
- [C15] Destatis on Eurostat instant-messaging use, Q1 2025: https://www.destatis.de/Europa/EN/Topic/Science-technology-digital-society/Digital_communication.html

**Ad costs, acquisition cost, competition**
- [A1] Lebesgue, Facebook CPM by country (27.07.2026): https://lebesgue.io/facebook-ads/facebook-cpm-by-country
- [A2] AdAmigo, Meta CPM/CPC benchmarks by country 2026 (10.09.2026, method not disclosed): https://www.adamigo.ai/blog/meta-ads-cpm-cpc-benchmarks-by-country-2026
- [A3] Superads (Sep 2025–Aug 2026): https://www.superads.ai/facebook-ads-costs/cpm-cost-per-mille (and country pages)
- [A4] Adligator (31.03.2026): https://adligator.com/blog/meta-ads-cpm-by-country-benchmarks
- [A5] Metadata.io B2B advertising benchmarks: https://metadata.io/b2b-advertising-benchmarks
- [A6] First Page Sage, B2B CAC by industry (updated 26.01.2026): https://firstpagesage.com/marketing/average-customer-acquisition-cost-cac-by-industry-b2b-edition-fc/
- [A7] Aleph x Benchmarkit, CAC payback 2026 (01.06.2026): https://www.getaleph.com/answers/cac-payback-period-saas-2026
- [A8] Trial conversion: https://www.shno.co/marketing-statistics/free-trial-conversion-statistics (citing First Page Sage) ; https://chartmogul.com/reports/saas-conversion-report/
- [A9] Meta Ad Library, read-only query of active ads by delivery country (30.09.2026): Native AI page 106149298508454, Holo page 636402359553778, Blaze page 122109377948001614 ; plus `research/COMPETITORS-2026-09.md` (29.09.2026) and company sites (swat.io, fanpagekarma.com, uberall.com, localsearch.ch, e-goi.com)

**Regulation**
- [R1] CMS GDPR Enforcement Tracker (dataset 30.09.2026): https://www.enforcementtracker.com/ ; report of 21.05.2026: https://cms.law/en/int/publication/GDPR-Enforcement-Tracker-Report/numbers-and-figures
- [R2] CNIL 2025 sanctions (09.02.2026): https://www.cnil.fr/en/sanctions-and-corrective-measures-cnils-actions-2025
- [R3] AEPD 2025 (3p): https://lawwwing.com/en/aepd-penalties-2025/
- [R4] Keuringsraad FAQ: https://keuringsraad.nl/vraag-antwoord/ ; Code for health product advertising (CAG 2019): https://keuringsraad.nl/wp-content/uploads/2025/10/CAG-2019-def.pdf
- [R5] ASA food and health claims: https://www.asa.org.uk/advice-online/food-health-claims.html
- [R6] ASA botulinum toxin (29.10.2025): https://www.asa.org.uk/advice-online/beauty-and-cosmetics-botulinum-toxin-products.html
- [R7] ASA cosmetic interventions, under-18s: https://www.asa.org.uk/news/strict-new-rules-for-ads-for-cosmetic-interventions.html
- [R8] BGH I ZR 170/24 (31.07.2025): https://www.lto.de/recht/nachrichten/n/izr17024-bgh-vorher-nachher-bildern-schoenheitsoperation-dr-rick-und-nick-aesthetify
- [R9] §5 DDG: https://www.gesetze-im-internet.de/ddg/__5.html ; §13 UWG: https://www.gesetze-im-internet.de/uwg_2004/__13.html ; Impressum on social media: https://www.odclegal.de/blog/impressum-social-media
- [R10] Wettbewerbszentrale annual report 2025: https://www.wettbewerbszentrale.de/ueber-uns/die-wettbewerbszentrale/verbandsstruktur/jahresberichte-der-wettbewerbszentrale/jahresbericht-2025-auf-einen-blick/
- [R11] Belgian law of 23 May 2013: https://www.ejustice.just.fgov.be/cgi_loi/change_lg.pl?language=fr&la=F&cn=2013052321&table_name=loi
- [R12] Norway: https://lovdata.no/dokument/SF/forskrift/2005-07-01-749/KAPITTEL_1-4 ; https://lovdata.no/dokument/SF/forskrift/2022-06-17-1114 ; https://www.forbrukertilsynet.no/avdekket-stort-omfang-av-ulovlig-reklame-for-kosmetiske-inngrep
- [R13] Loi Toubon and SaaS (3p): https://blog.lina.law/english-saas-contract-french-customer-en
- [R14] Polish Language Act: https://efnil.org/projects/language-legislation-europe-lle/poland-pologne/
- [R15] AI Act Art. 50, Commission FAQ (24.07.2026): https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act ; AI Omnibus: https://digital-strategy.ec.europa.eu/en/news/ai-omnibus-enters-force ; Code of Practice (06.2026): https://www.jonesday.com/en/insights/2026/06/european-commission-publishes-final-code-of-practice-on-marking-and-labelling-aigenerated-content
- [R16] Meta health and wellness restrictions (3p): https://stape.io/news/meta-data-sharing-restrictions-healthcare (03.03.2026) ; https://www.click.co.uk/insights/metas-new-advertising-restrictions-impacts-health-and-wellness-brands/ (06.02.2025)
- [R17] Meta stops political ads in the EU: https://www.socialmediatoday.com/news/meta-cuts-off-political-ads-europe-new-regulations/802154/
- [R18] Italy health advertising: https://www.studiolegalestefanelli.it/it/approfondimenti/divieto-pubblicita-sanitaria-promozionale/
- [R19] France Decree 2026-891 (3p): https://kohenavocats.com/clinique-chirurgie-esthetique-publicites-interdites-decret-23-septembre-2026-retrait-autorisation/
- [R20] Spain RD 1907/1996: https://www.boe.es/buscar/act.php?id=BOE-A-1996-18085
- [R21] Austria Impressum (3p): https://trustyourwebsite.com/at/de/guides/impressumspflicht-oesterreich
- [R23] IMY, Apoteket and Apohem Meta pixel fines (30.08.2024): https://www.imy.se/nyheter/sanktionsavgifter-mot-apoteket-och-apohem-for-overforing-av-personuppgifter-till-meta/
- [R24] Dutch DPA cookie-banner warnings (3p): https://privacy-web.nl/en/nieuws/ap-driekwart-websites-past-misleidende-cookiebanner-aan-na-waarschuwing-onderzoek-gestart-naar-weigeraars/
- [R22] UK DMCC subscriptions: https://www.legal500.com/intelligence/united-kingdom/consumer-protection/the-dmcca-subscription-contracts-the-timeline-just-got-shorter (14.09.2026) ; https://www.lewissilkin.com/en/insights/2026/04/02/consumer-law-update-subscriptions-regime-delayed-again-to-spring-2027-102mops

**Payments and VAT**
- [S1] Stripe pricing, Netherlands (accessed 01.10.2026): https://stripe.com/en-nl/pricing
- [S2] Stripe local payment methods pricing (accessed 01.10.2026): https://stripe.com/en-nl/pricing/local-payment-methods
- [S3] Stripe supported countries (accessed 01.10.2026): https://stripe.com/global
- [W1] Whop fees: https://docs.whop.com/payments-and-billing/fees/fees
- [W2] Whop Seller Terms (updated 14.07.2026): https://whop.com/seller-terms/
- [W3] Whop taxes: https://docs.whop.com/payments-and-billing/fees/taxes
- [W4] Whop local payment methods: https://docs.whop.com/payments-and-billing/local-payment-methods
- [W5] Whop adaptive pricing: https://docs.whop.com/payments-and-billing/fees/adaptive-pricing
- [V1] Non-Union OSS (Revenue.ie): https://www.revenue.ie/en/vat/vat-ecommerce/non-union-scheme/index.aspx
- [V3] Switzerland, foreign companies (ESTV): https://www.estv.admin.ch/estv/en/home/value-added-tax/vat-tax-liability/foreign-companies.html
- [V4] Norway VOEC (3p): https://braekhus.no/en/vat-voec-and-reverse-charge-when-selling-services-in-norway/
- [V5] German e-invoicing FAQ (BMF): https://www.bundesfinanzministerium.de/Content/DE/FAQ/e-rechnung.html

**FX and internal**
- [X1] ECB euro reference rates, 29.09.2026: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
- [O2] `research/COMPETITORS-2026-09.md` (29.09.2026)
- [O3] `platform/otto_styles.py`: LAUNCH_RULES (6 × 6, refresh 2 per concept per week), MICRO_RULES (4 × 5), SCALE_RULES (6 × 8), MICRO_BELOW_DAILY_EUR = 36
- [O4] `docs/HOSTING.md` (Hetzner CPX31 plus backups, about €25 a month)
- [O5] `docs/LAUNCH-READINESS.md` (image cost; reel render not verified on the server; time zone defaults from the domain)
- [O6] `platform/landing.html` (founding CTA "€197 once", FAQ on founding terms) and `platform/plans.json` (`founding` inherits `growth`)
