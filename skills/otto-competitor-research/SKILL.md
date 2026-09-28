---
name: otto-competitor-research
description: "Otto's competitor intelligence engine — scan competitors' paid ads (Facebook/Meta Ad Library, TikTok Creative Center, Google Ads Transparency) and organic social (IG/TikTok/FB/YT) to extract winning angles, hooks, offers and creative patterns per brand. Use when onboarding a new Otto customer, refreshing a brand's content plan, or when asked to research what competitors are running."
---

# Otto Competitor Research

**Goal:** for each Otto brand, know at any moment what its competitors are running, what seems to work, and which angles/hooks/formats to steal-and-improve. Output feeds the creative engine (`otto-creative-engine`) and the monthly content plan.

**Output file (source of truth):** `autopilot/brands/<slug>/competitor-research.md` — refreshed weekly (M6 loop) or on demand.

## Step 1 — Build the competitor list
1. From `brands/<slug>/brand-profile.md` (competitors section) if present.
2. Expand via web_search: "<niche> + <market/language> brands", marketplaces, "best <product> <country>".
3. Keep 5-8 names max: 2-3 direct (same product+market), 2-3 aspirational (bigger, same niche), 1-2 adjacent (same audience, different product).
4. For each: website, FB page, IG handle, TikTok handle. Record in the output file header.

## Step 2 — Paid ads sweep (per competitor)

### Meta / Facebook Ad Library (free, no key — default path)
- URL pattern: `https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=<CC>&q=<brand name>&search_type=keyword_unordered` — or better, find the page ID and use `view_all_page_id=<id>`.
- Use the `browser` tool (Ad Library renders via JS; web_fetch gets little). Snapshot, scroll 2-3 times, screenshot the grid.
- For each active ad capture: start date (longevity = the #1 proxy for "it works"; anything running 30+ days is a proven winner), format (image/video/carousel), hook (first line), offer/CTA, landing URL, # of ad variants with same creative (many variants = scaling).
- EU targets: the DSA transparency view also shows reach ranges — record them.
- Official Ad Library API (free, zero ToS risk) works for EU-served ads — our niches are EU, so it fits: requires FB developer account, then `https://graph.facebook.com/v21.0/ads_archive?...`. Use when we need structured bulk data instead of browsing.

### TikTok Creative Center (free, no key)
- Top Ads: `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en` — filter by region + industry; also keyword search competitor names.
- Capture: hook style (first 2 seconds), format (UGC/talking head/demo), sound usage, CTR/engagement badges shown.
- Even when a competitor isn't there, the industry top-ads = format benchmarks for our reels (M3 Kling pipeline).

### Google Ads Transparency Center (free, no key)
- `https://adstransparency.google.com/?region=<CC>&domain=<competitor.com>` — shows search/display/YouTube ads per advertiser. Capture headlines + angles for search intent language.

### Scaled/automated path (when volume justifies keys — per research/creative-and-competitor-stack.md)
- **Apify** (`apify/facebook-ads-scraper`, TikTok Creative Center actors; REST or MCP at mcp.apify.com) — weekly creative sweeps, ~$1.30-1.70/1k records.
- **ScrapeCreators** (scrapecreators.com, $47/25k credits) — high-frequency polling of posts+engagement+ad libraries across TikTok/IG/YT/FB/X.
- Keys live in per-client secrets dirs (ARCHITECTURE.md isolation rules). Not yet provisioned — browser path is the working default.

## Step 3 — Organic sweep (per competitor)
- IG: profile grid via browser — last 12 posts: format mix, posting frequency, which posts have outlier engagement (likes/comments vs their normal), recurring content pillars.
- TikTok: profile — outlier videos (views >> follower count), hook patterns.
- FB page: what they push, community size, engagement rate.
- Record only OUTLIERS + patterns, not everything. An outlier = the audience voted.

## Step 4 — Synthesize → competitor-research.md
Structure the output file:
```
# Competitor Research — <Brand> · <date>
## Competitors tracked (name · site · FB/IG/TT · type: direct/aspirational/adjacent)
## Paid: what's running now
Per competitor: active ads count, longest-running ad (date + why it likely wins),
dominant angles, offers seen, formats.
## Longevity winners (30+ days active) — the steal-and-improve list
Ad → hook → angle → why it works → how WE do it better on-brand.
## Organic outliers
Post → format → hook → engagement signal → lesson.
## Gaps & opportunities
Angles nobody runs, objections nobody answers, formats missing in this niche.
## Action → content plan
3-5 concrete creative briefs for otto-creative-engine (angle + hook + format + visual direction).
```

## Rules
- **Never copy creatives.** Extract the angle/structure/psychology; regenerate 100% on-brand (palette/voice from brand-profile.md).
- Longevity + variant-count > likes. Paid signal beats vanity metrics.
- Restricted niches (CBD, mental health): competitors' compliant phrasing is gold — record exactly how they word claims that pass Meta review.
- Log every research pass in the brand's file with a date; the weekly M6 loop diffs against last pass ("new ad spotted", "killed ad" — a killed ad after 5 days = failed angle, also a lesson).
- Screenshots of standout ads → `brands/<slug>/competitors/` for visual reference (never as generation input).
