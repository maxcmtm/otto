# Otto pricing for the European market — research + recommendation
Date: 2026-09-28 · Author: Claude Code (local) · Decision owner: Max · Status: **proposal, numbers editable in `platform/landing.html` → `PRICING`**

## 1. What the market charges (Sept 2026)

**The direct anchor — Native.no (read live from native.no, 28.09):**
| Tier | Price | Included |
|---|---|---|
| Pro | **$79/mo** (+$39 per extra brand) | 1 brand, 50 posts/mo ready for approval, all channels (FB/IG/LinkedIn + 10), approval or full autopilot, analytics |
| Max | **$249/mo** | 3 brands, 50×3 posts, 5× AI usage |
| Agency | **$499/mo** (+$69/workspace) | 10 workspaces, ads on each client's ad account, named account manager |
| Enterprise | custom | forward-deployed marketers, central control |
Yearly = −20 %. Cost-comparison page anchors against agencies ($1.5–5k+) and an in-house hire ($4.5–6k).

**AI social tools (scheduler + AI writing, not autopilot):** Ocoya $15–79, FeedHive $15–22+, SocialBee $29–99 (agency from $179), Predis ~$29–249, Blaze ~$27+. These do part of the job and leave the owner driving; they cap the *bottom* of the market at ~€15–30 and signal "cheap tool", not "department".

**Agencies / freelancers in Europe:** small-business packages €900–2,800/mo; Germany: €1,500–2,000 for freelancer / low-depth agency, €3,000–6,000 for 2–3 platforms with content + community + reporting; junior hourly €90–150. Paid-social management adds ~€1,500–2,500/network/month. This is what Otto replaces, and it is 10–40× the SaaS price band.

## 2. Positioning that sets the price
Otto is not a scheduler (the €15–99 band) and not an agency (the €900–6,000 band). It is the only product that **runs the loop and comes to the owner with decisions** (Telegram cards, morning briefing, drop alerts, weekly competitor sweep, winners → next plan). The honest comparison class is Native, and Otto ships more at each rung. Price *at or slightly under* Native per rung, in euros, with a visibly fuller middle tier — the STRUCTURE.md line still holds: *"Everything Native gates at $499 — plus a human on the phone — at €149."*

VAT: quote **excl. VAT** (B2B, reverse-charge in the EU; Whop handles VAT/OSS). Currency: **EUR**, no cents (€69 not €69.90 — premium, not retail).

## 3. Recommended ladder (monthly, excl. VAT · yearly −20 %)
| Tier | Monthly | Yearly (per mo) | For | Included | Native equivalent |
|---|---|---|---|---|---|
| **Starter** | **€69** | €55 | one brand | 1 brand · 50 posts/mo · FB + IG (+ LinkedIn on request) · Telegram approvals + dashboard · on-brand visuals · morning briefing + drop alerts · monthly competitor sweep · +€39 per extra brand | Pro $79 (≈ €73) — we're under it with alerts + competitors + Telegram they don't have |
| **Growth** ⭐ | **€149** | €119 | growing businesses | everything in Starter · 3 brands · weekly competitor sweep + ad-library winners · analytics loop (winners → next plan) · LinkedIn included · ads-on-autopilot inside a ceiling you set (when M2 live) · AI reels (when M3 live) · human on the phone < 2 h · +€39 per extra brand | Max $249 (≈ €230) — 35 % under, and includes what Native gates at Agency (ads) |
| **Agency** | **€399** | €319 | agencies / multi-location | 10 workspaces, each with its own brand + Telegram + ad account · Growth features in every workspace · white-label weekly reports · named account manager · +€49 per extra workspace | Agency $499 (≈ €460) — under, with cheaper extra workspaces (€49 vs $69) |
| Enterprise | custom | — | chains, groups | central control of every location, custom volumes, SLA, contract billing | Enterprise |

**Founding (today, live on Whop): €197 one-time.** Keep it as the only purchasable offer until the loop is proven on Happy Garden + CMTM. Position it as *"a founding seat: Growth features during the pilot, grandfathered terms when plans open."* Do **not** promise a specific lifetime discount yet — decide the founding→subscription bridge when plans open (options: 3 months of Growth included, or Growth at the Starter price for year one).

Why these exact numbers: €69 sits under Native's $79 *and* under the €70–80 psychological line for EU SMBs; €149 is the wedge (the comparison table writes itself: "agency €1,500+, in-house €4,000+, Otto €149"); €399 keeps agency buyers (who bill clients €900+ each) at < €40/client. Unit economics: LLM + image cost per brand ≈ €8–15/mo at 50 posts (GPT Image 2 ~$0.20/image × 50 = $10; copy tokens small; Kling reels later ~$0.10/s), so Starter is ~80 % gross margin before support.

## 4. What to A/B once there is traffic
- €69 vs €79 Starter (does "cheaper than Native" matter, or is parity + more features enough?)
- Yearly −20 % vs "2 months free" wording (same math, different feel)
- Growth as the pre-selected card (it is in Native's pricing psychology: middle tier "BEST FOR GROWTH")

## 5. Landing implementation
`platform/landing.html` → `const PRICING = {...}` (one object: tiers, prices, per-brand add-on, yearly discount, founding). The section renders 3 tiers + the Founding card, with a monthly/yearly toggle. Every tier CTA goes to the founding checkout until subscriptions exist on Whop ("Reserve at founding price").

Sources: native.no (live, 28.09.2026); Apaya "Best AI social media management tools 2026"; Zapier "best AI tools for social media management 2026"; Weber Media "Social media agency costs 2026 (Germany)"; eclincher / newmedia.com "Social media management pricing 2026"; Picmim "AI social media manager vs agency cost 2026".
