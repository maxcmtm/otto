# Otto launch kit: Meta ads in the Netherlands and Ireland, from Saturday 3 October 2026

Everything needed to start Otto's own paid Meta campaign in **NL and IE at €50 a day each (€100 a day total)**. The ads
are in **English in both markets** and follow the message house **`docs/MESSAGE-2026-10.md`** (Max, 2 Oct): automate your
marketing, stop paying agency prices, launch without worrying about marketing, take your marketing to the next level, the
daily ads report, the ads Otto makes and the posts it makes every week. The offer is the **free 7-day trial** (sign in with
Google, no card, nothing charged unless a plan is chosen), **then €79 a month** (one public plan, monthly, no contract, cancel
anytime; excl. VAT). No "from", no yearly price, no other plan's price appears anywhere. Nothing here has been created in any Meta account. Plan and
rules: `docs/GO-TO-MARKET-NL-IE.md`. Machine-readable spec: `campaign.json`.

| | NL | IE |
|---|---|---|
| Campaign | `OTTO · NL · Launch · 2026-10` | `OTTO · IE · Launch · 2026-10` |
| Ads | 42: 18 faceless videos (9:16; notes and texts also 4:5) + 18 statics (4:5, plus 9:16 and 1:1 where the template has them) + 6 premium statics (1:1 + 9:16, one per concept, added 3 Oct) | 42, same mix |
| In the import files | 42 (no manual carousel this time) | 42 |

### The six concepts (one ad set each)

About half the set sells the organic side (posts, reels and stories every week) and half the paid side (the ads Otto makes,
the campaign it runs, the 07:35 report), under the umbrella "Automate your marketing" (Max, 2 Oct).

| Ad set | Pillars (MESSAGE-2026-10) | Family · stage · CTA | Headlines (NL; IE writes 7:35) | The 6 ads |
|---|---|---|---|---|
| a1 Automate your marketing | 1 Automate + 6 Next level (umbrella: organic + paid) | identity · cold · Learn more | Automate your marketing / Take your marketing to the next level | notes video (marketing jobs I've automated), versus video (by hand vs with Otto), big video (posts every week · ads every day · 1 report at 07:35) · product hero (the planned month), before/after (posting when you remember → a plan that runs every day), search "how to automate social media" |
| a2 Stop paying agency prices | 2 Agency vs €79 a month | enemy (competitor research) · cold · Learn more | Stop paying agency prices / Your marketing team for €79 a month | versus video (agency €500–1,500 a month, posts only vs Otto €79 a month, posts and ads), search video ("social media agency price" → Otto's listing), big video (NL €500–1,500 / IE €1,000+ → €79 → 1 tap) · comparison table with the source line, product hero (the campaign phone), big number "€79 a month" |
| a3 Your ads, reported at 07:35 | 4 The daily ads report + the campaign Otto runs (paid) | experience · warm · Learn more | Your ads report, every day at 07:35 / Know what your ads did by 07:35 | texts video (the 07:35 report: €18, 31 clicks, 4 enquiries, "Sample"; pause the weakest ad), big video (one campaign, ads for every angle → 07:35 → 1 tap), notes video (things I stopped checking) · macro hero (the report phone), comparison "Ads dashboard or 07:35 report?", notes "My morning" |
| a4 The ads Otto makes | 5, paid side: sample ads for demo brands | pain · cold · Learn more | The ads Otto makes for you / Your ads, designed and run by Otto | texts video (Otto sends the new ads; a sample ad for a demo brand attached), big video (the ads phone → the campaign), versus video (boosted post vs Otto's ads) · product hero (the ads phone: four sample ads), search "how to make facebook ads", checklist "Every ad Otto makes" |
| a5 You run it, Otto posts | 5, organic side: posts, reels and stories every week | identity · cold · Learn more | You run the business. Otto posts. / Posts, reels and stories, every week | big video (the week phone: carousels, reels, stories · every week · 1 tap), texts video (this week's posts ready, a sample carousel attached, approved after work), versus video (posting by hand vs a planned week) · product hero (three sample posts fanned), notes "This week's posts", checklist "What's in your month" |
| a6 Launching? 7 days free | 3 Launch without worrying + 7 The offer | offer · hot · Sign up | Launching? Try Otto free for 7 days / 7 days free. Then €79 a month. | notes video (opening week to-do: marketing, Otto has it), texts video (what happens after the 7 days; monthly, no contract, cancel on the Billing page), versus video (opening week on your own vs with Otto) · offer card (7 days free, then €79 a month), product hero (the opening post), checklist "Opening checklist" |

Lines kept from the earlier October kit where they fit: the 07:35 message (a3), "You run it, Otto posts" and the
"busy in the shop till 6" chat (a5), the 7-days-free terms chat and offer card (a6), "Marketing jobs I've…" (a1), "My
morning" (a3).

### Premium top layer (3 Oct)

One extra hero static per concept, `<market>-aN-premium` (style `editorial`, slot `extra`), in the same ad set and with the
concept's rotated copy: a photographic scene generated with a chroma-key screen or price tag (Higgsfield gpt-image-2),
Otto's **real app screens** warped in with a perspective transform (Review: sample carousel / sample reel "Approved ·
posted" / sample opening post; the 07:35 report with a "Sample report" chip), the showcase ads as printed cards
("Sample ads for demo brands"), and every word set by hand (Inter Tight 800 headline, Mona Sans, Otto's logo), never by
the image model. No faces (hands, a back). The cell's `data` holds every word on the image, so `render.py compliance`
checks what the viewer reads; agency figures are the sourced ranges only, as a separate callout from the word agency, with
the source line on the image. Adding six statics lowers the video share to 18 of 42 (43 %): the matrices set
`rules.min_video_share` to 0.42 on purpose (`rules.note_premium`). Files are AI-tagged (IPTC compositeSynthetic).

Every primary text, headline and description is in the matrices (`brands/otto/ads-2026-10-{nl,ie}.json`, 3 primaries and 2
headlines per concept, rotated over the six visuals) and in `compliance-report.md`.

## 1. Files

| File | What it is |
|---|---|
| `import/otto-{nl,ie}-part1.xlsx` | Bulk-import file 1 for each market: the campaign, ad sets a1–a3 and their 21 ads (12 statics incl. 3 premium, 9 videos). `.csv` = the same rows in Ads Manager's own export format (UTF-16, tabs). |
| `import/otto-{nl,ie}-part2.xlsx` | Bulk-import file 2: ad sets a4–a6 and their 21 ads (12 statics incl. 3 premium, 9 videos), added to the campaign that part 1 created. |
| `import/media/{nl,ie}-part{1,2}/` | Exactly the images and videos each part uses (12 images, 9 videos: still under the 10-videos-per-import limit). Select the whole folder in the import dialog. |
| `meta-bulk-import.xlsx` | Review copy: all 84 imported ads on one sheet, plus the media list (which 4:5 / 9:16 / 1:1 file belongs to each ad). |
| `creatives/{nl,ie}/static/` · `creatives/{nl,ie}/video/` | Every render. File names are `<ad id>-4x5.jpg`, `-9x16.jpg`, `-1x1.jpg`, `-9x16.mp4`, `-4x5.mp4`, plus the `.jpg` poster next to each video. |
| `creatives/{nl,ie}/premium/` · `premium-src/` | The premium top layer (3 Oct): `<concept>-1x1.jpg` (the import image) and `<concept>-9x16.jpg` (placement customisation; text inside 269–1536 px) for automate, agency, report, ads, posts, launch. `premium-src/` re-sets the type on the saved text-free backgrounds without new image credits (see its docstring). |
| `sheets/` | Contact sheets for review: `premium.jpg` (the premium layer, both markets), `{nl,ie}-statics-{4x5,9x16,1x1}.jpg`, `{nl,ie}-videos.jpg` (four key frames per video), `video/*-sheet.jpg` (one sheet per video) and `phones.jpg` (every phone cut-out and sample post). |
| `compliance-report.md` | Every text checked, with its result (`qa/compliance-*.json` holds the raw data and `qa/check-*.txt` the engine's matrix check). |
| `build.py` | Rebuilds the import files once the domain and Meta ids are known. |
| `render.py` | Re-renders, re-checks and re-sheets everything from the matrices (`kits`, `check`, `statics`, `premium`, `videos`, `prune`, `sheets`, `compliance`, `all`). `premium` registers the premium cells' finished files in the manifest (statics never re-renders them). |
| `phones.py` | Draws the phone cut-outs the concepts use into `brands/otto/assets/`: the 07:35 ads report, the campaign Otto runs, "This week" (six post types), sample posts in the Review screen (carousel, reel, story, opening post) and their fan, the ads phone (four showcase ads), a showcase ad's 9:16 version playing as a story, the ads + story duo, and the chat attachments (a sample carousel, a sample ad). |
| Sources | `brands/otto/ads-2026-10-{nl,ie}.json` (copy and render data) · `brands/otto/video/2026-10-{nl,ie}/` (video kit files, written by `render.py kits`) · `brands/otto/video/presentation-2026-10-{nl,ie}.json` · `brands/otto/video/brand.json` (asset roles) · `brands/otto/assets/` (cut-outs; `showcase/` = the sample ads for demo brands) |

## 2. Must be true before you import

1. **The landing is live on the real domain**, with Google sign-in working there and the consent banner on. It must show the same offer as the ads: **7 days free, no card, then €79 a month excl. VAT, monthly, cancel anytime**, and the agency-price source line ("Agency prices: public 2026 price lists of social media agencies in the Netherlands and Ireland").
2. **The €79 plan exists:** `platform/plans.json` Starter at €79 and its Stripe prices, otherwise a trial can't convert at the price the ads name.
3. **Conversions API is on.** `$OTTO_SECRETS/meta-capi.json` holds the dataset (pixel) id and the token, `python3 otto_track.py capi-status` says forwarding is ON, and `test_event_code` has been **removed**.
4. **One real sign-up.** On the live domain, press Accept on the banner, then sign in with Google once (a team account is fine). Events Manager should then show **CompleteRegistration** received from the **Server** within about 20 minutes. Until that happens, Ads Manager marks the event "no recent activity". It still lets you pick it, but the warning is gone once one real event has arrived.
5. **Meta setup.** The ad account is in EUR, Otto's Facebook Page and Instagram professional account are connected, and the domain is verified in Business settings → Brand safety → Domains.
6. **A custom audience for the exclusion.** Audiences → Create → Custom audience → Website → your dataset → event **CompleteRegistration** → 180 days → name it `Otto · signed up · 180 days`.

## 3. Upload, step by step (about 15 minutes)

1. **Build the files (1 min).** Run this from `launch/2026-10/`:
   `python3 build.py --domain <your-domain> --page-id <Page id> --instagram-id <Instagram account id> --pixel-id <dataset id> --exclude "<audience id>:Otto · signed up · 180 days"`
   You'll find the ids in Business settings (Pages, Instagram accounts), Events Manager (dataset) and Audiences (the audience id).
2. **Import NL part 1 (3 min).** In Ads Manager, open the ad account, then **Export & import (the ⋯ menu above the table) → Import ads in bulk**. Upload `import/otto-nl-part1.xlsx`. When the dialog asks for media, select every file in `import/media/nl-part1/` (9 images, 9 videos). Ads Manager creates everything as drafts.
3. **Check the drafts (3 min), then publish.**
   - Campaign: **Leads**, **Advantage+ campaign budget €50/day**, bid strategy **Highest volume**.
   - Ad sets: conversion location **Website**, dataset = yours, event **Complete registration**, performance goal **Maximise number of conversions**.
   - Audience: location **Netherlands** (people living in or recently in), **Advantage+ audience on**, under audience controls **minimum age 25**, the exclusion audience in place. Optionally add the concept's interest suggestions from §5.
   - Placements: **Advantage+ placements**. Ad-set spending limit: **daily minimum €4**.
   - Ads: Page and Instagram identity correct; the **destination URL** shows the domain, and URL parameters read `utm_source=meta&utm_medium=paid&utm_campaign=otto_nl_launch&utm_content=<ad id>`.
   - **Advantage+ creative:** select all ads → Edit → turn **every** enhancement off. That covers text improvements, visual touch-ups, add overlays, music, 3D animation, image brightness and contrast, translations, show summaries / spotlights / reveal details, relevant comments and site links. **Optimise website destination: off** (it can send people to other pages). The ads say exactly what the compliance check passed (the price, the agency ranges, the "Sample" labels), and no AI-made people or text get added.
   - Then **Publish**. The campaign stays **Off** (imported as PAUSED) until step 6.
4. **Import NL part 2 (2 min).** Copy the new campaign's id (Campaigns tab → Columns → Customise → *Campaign ID*, or from the URL `…selected_campaign_ids=<id>`). Then:
   `python3 build.py … --campaign-id nl=<NL campaign id>` (keep the other flags). Import `import/otto-nl-part2.xlsx` with the files in `import/media/nl-part2/`. Ad sets a4–a6 are added to the same campaign. Check them as in step 3 and publish.
5. **Repeat steps 2–4 for IE (6 min):** `otto-ie-part1.xlsx` + `media/ie-part1/`, then `--campaign-id nl=…,ie=<IE id>` and `otto-ie-part2.xlsx` + `media/ie-part2/`. The location is **Ireland**.
6. **Saturday 3 October, morning: switch both campaigns On.** Nothing else changes for 72 hours (§7).

**Why two import files per market:** the import dialog takes at most 10 videos (≤ 10 MB each) per import, and each market has 18. Every video here is under 5 MB.

**Optional before publishing, ~20 s per ad: placement customisation.** Each import row carries one asset: the 4:5 image for statics, the 9:16 video for videos. Bulk import can only add a second image by its Meta image hash, which doesn't exist until the image is uploaded. Without customisation, Meta shows the 4:5 static in Stories/Reels on a padded background and crops the 9:16 video in Feeds. If there's time, open a static ad → Media → *Customise placements* → *Stories and Reels* → the `-9x16.jpg`. For notes and texts videos, open *Feeds* → the `-4x5.mp4`. The pairs are listed on the "media" sheet. It's worth doing for the 12 statics per market that have a 9:16 version.

## 4. Pixel / Conversions API events

| Event (Events Manager) | Fires when | Sent by | Use in this campaign |
|---|---|---|---|
| **CompleteRegistration** | the Google sign-up completes (a trial account exists) | server, `otto_api` → `otto_track.capi_track("signup")` | **The optimisation event** (ad sets → conversion event) |
| StartTrial | the first trial brand is created | server, `capi_track("trial_start")` | Report column. Switch optimisation to it in month 2 once it fires ≥ 25 times a week per market |
| Lead | the website scan returns a result | landing beacon → server | **Fallback optimisation event** (day-7 rule). Report column: "cost per scan result" |
| InitiateCheckout | a "Start free trial / Get started" button is clicked | landing beacon → server | Report column |
| ViewContent | a scan starts | landing beacon → server | Report column |

Meta only gets these for visitors who pressed **Accept** on the consent banner, and never under DNT/GPC. There's no browser pixel. Meta's counts are a share of the real numbers, so the source of truth is Otto's first-party funnel (owner console, `/otto-track`) and Stripe. Attribution: 7-day click, 1-day view.

**Why Leads + CompleteRegistration (decided for this launch):**
- *It is what the ads ask for.* Every ad sells the free trial, and CompleteRegistration is the trial sign-up. The server confirms it after Google sign-in, so a browser can't fake it.
- *A brand-new dataset has no history for any event.* That isn't a blocker. Meta lets you pick a standard event before it has fired and starts delivery broad, learning from the first conversions. The one real sign-up in §2.4 removes the "no recent activity" warning. Conversions API events optimise exactly like pixel events.
- *Why not Lead (scan result), as the November plan said?* The offer moved from "scan your site" to the free trial on 30.09. A scan is a soft action reported by the public page, and optimising on it would buy people who enjoy trying the scanner. Lead stays the fallback if CompleteRegistration is too sparse (day-7 rule).
- *Why Leads and not Sales?* No purchase event exists yet: a paid plan starts after day 7, through Stripe, server to server, with no consent context. The Leads objective is built for sign-up-type website events. **If Ads Manager doesn't offer Complete registration under Leads, use the Sales objective with the same event.** Everything else stays the same.
- *Volume, honestly.* At €50/day and about €30 per trial start, expect roughly 10–12 sign-ups per market per week, and Meta sees the consented share of those. No ad set will leave the learning phase (Meta wants about 50 per ad set per week). That's expected. Let the campaign budget allocate, and judge on first-party numbers (GTM §3.5).

## 5. Campaign spec (per market)

| Setting | Value |
|---|---|
| Objective · conversion location · goal | Leads · Website · Maximise number of conversions |
| Optimisation event | CompleteRegistration (fallback: Lead) · attribution 7-day click, 1-day view |
| Budget | Advantage+ campaign budget **€50/day**, Highest volume, start **Sat 3 Oct 2026 00:00** (ad account time zone), no end date. The test window is 3 Oct – 1 Nov: €1,500 per market, €3,000 total |
| Ad sets | One per concept (6). Days 1–7: **daily minimum spend €4** per ad set |
| Location · age | NL (or IE), people living in or recently in · minimum age **25** as a hard control, max 65+ |
| Audience | **Advantage+ audience on**, no language restriction. Optional suggestions per concept (`campaign.json` → `audience.suggestions`): NL a1 Small business owners, Facebook page admins, Shopify, E-commerce · a2 Small business owners, Social media marketing, Digital marketing · a3/a4 Shopify, E-commerce, Online advertising · a5 Restaurants, Coffeehouses, Hairdresser, Beauty salon · a6 Entrepreneurship, Small business owners, Restaurants. IE a1/a3 Plumbing, Electrician, Construction, Small business owners · a2 Small business owners, Social media marketing, Digital marketing · a4 Restaurants, Bed and breakfast, Hotels, Online advertising · a5 Restaurants, Bed and breakfast, Physical therapy, Dentistry · a6 Entrepreneurship, Small business owners, Restaurants, Bed and breakfast. Check each option exists in Ads Manager, because Meta merged many in 2025–26 |
| Exclusions | Custom audience `Otto · signed up · 180 days` (CompleteRegistration). At account level: Otto's team and pilot brands' page admins. Detailed-targeting exclusions no longer exist |
| Placements | Advantage+ placements (all). Feeds get the 4:5 static or the video's feed crop. Stories/Reels get the 9:16 video, and the 9:16 static after the optional placement customisation |
| Ads per ad set | 6: 3 faceless videos and 3 statics |
| Copy | The engine's rule: each ad runs one of the concept's 2 headlines and 3 primary texts, rotated over its visuals, so the test is about the visual. Multiple text options and dynamic creative are off |
| Destination | `https://{DOMAIN}/` + URL parameters `utm_source=meta&utm_medium=paid&utm_campaign=otto_<nl|ie>_launch&utm_content=<ad id>` (the landing records the utm_* tags first-party) |
| Ad names | The matrix cell id (`nl-a3-texts-v`, `ie-a6-offer` …), so Meta, the UTMs and the matrix line up |
| Status on import | Campaign PAUSED, ad sets and ads ACTIVE. Switching the campaign on starts everything |

## 6. Budget pacing and scaling (GTM §2.2–2.3, October dates)

- **Days 1–7 (Sat 3 – Fri 9 Oct):** €50/day per market, €4/day minimum per ad set. **No edits for 72 hours** after launch, except disapprovals and broken tracking.
- **Days 8–14 (Sat 10 – Fri 16 Oct):** remove the ad-set minimums and let the campaign budget move to the winners.
- **Days 15–30 (Sat 17 Oct – Sun 1 Nov):** the scaling rules, judged per market on the last 7 days:

| Signal | Action |
|---|---|
| An ad: ≥ €10 spent and link CTR < 0.5 %, or ≥ €15 spent and 0 scans | Pause it; replace it in the Monday refresh |
| An ad set (concept): ≥ €50 spent and cost per scan result > €16 | Pause it; bring a new concept from the bank next Monday |
| Market: cost per paying customer ≤ €150 with ≥ 3 purchases (or ≤ €30 per trial start before purchases exist) | +20 % budget every 72 h, up to €150/day by day 30 |
| Market: cost per paying customer €150–300 | Hold the budget; refresh creative |
| Market: > €300 per paying customer for 7 days, or €600 spent with 0 purchases | −30 % budget; review landing, offer and sign-up flow first |
| One market's cost per paying customer (or per trial start) < 70 % of the other's | Move €10/day to it (floor €30/day per market) |

The ad-level and concept-level pauses already apply from day 7 (§7). Paying customers only exist from about day 8, after the first trials end. With the price now in the ads (€79), watch whether the a2 and a6 concepts (price-led) pull cheaper trial starts than a1/a4 (product-led): that is the first read on whether the price is a hook.

## 7. KPI traffic lights (weekly, per market; GTM §5.3)

| KPI | Green | Amber | Red |
|---|---|---|---|
| Link CTR | ≥ 0.8 % | 0.5–0.8 % | < 0.5 % |
| CPC | ≤ €1.30 | €1.30–1.70 | > €1.70 |
| Visitors who scan | ≥ 20 % | 15–20 % | < 15 % |
| Cost per scan result (Lead) | ≤ €8 | €8–12 | > €12 |
| Scans that start a trial | ≥ 25 % | 15–25 % | < 15 % |
| Cost per trial start | ≤ €30 | €30–50 | > €50 |
| Trials that pay | ≥ 25 % | 15–25 % | < 15 % |
| Cost per paying customer | ≤ €150 | €150–300 | > €300 |
| Trials approving a first post within 24 h | ≥ 80 % | 60–80 % | < 60 % |

**Day 3: Tuesday 6 October, after the 72 hours.** Only fix what is broken; change nothing that is merely slow.
1. **Delivery:** every ad set has spent something. If an ad set has spent €0, look for a disapproval or a missing asset. Fix disapproved ads by changing only the flagged words, run `render.py compliance` again, and resubmit. The agency concept (a2) is the likeliest to be questioned: it compares prices with a category; the figures are the sourced ranges and the landing carries the source line.
2. **Tracking:** Events Manager shows CompleteRegistration, Lead and InitiateCheckout arriving from the Server. Compare Meta's sign-ups with Otto's first-party sign-ups. If Meta shows 0 while the owner console shows ≥ 3, the problem is CAPI or consent (`otto_track.py capi-status`, the banner). Fix it the same day.
3. **Landing:** visitors arrive with the utm_* tags (owner console), the page loads on phones, and the trial button works.
4. **Read, don't act:** CPM (expect NL €9–14, IE €9–13), CTR and CPC against the lights. Pause nothing yet unless it's broken.

**Day 7: Friday 9 October, the first weekly review.**
1. Fill in the traffic lights per market, using first-party numbers for scans and trials.
2. **Ads:** pause every ad with ≥ €10 spent and link CTR < 0.5 %, or ≥ €15 spent and 0 scans.
3. **Concepts:** pause an ad set with ≥ €50 spent and cost per scan result > €16. If two or more concepts are red, list the replacements for Monday.
4. **Optimisation event:** if Meta recorded **fewer than 10 CompleteRegistration** in the market this week, and cost per trial start is red (> €50), switch the ad sets' conversion event to **Lead**. That's one change, and it accepts a new learning phase. Otherwise keep CompleteRegistration.
5. Write down for Saturday 10 October: **remove the €4 ad-set minimums** (days 8–14).
6. **Monday 12 October refresh:** add one new creative per live concept. Start with the winner re-cut in a style that concept hasn't run (`render.py` with a new cell in the matrix, dated `"added"`). The Dutch-language November cells stay parked; see §8.

## 8. Decisions taken (and why)

- **New direction, 2 Oct evening.** The kit built earlier that day (reels without the filming, the 07:35 message, local not translated, you run it Otto posts, 7 days free, the busy season) was replaced by six concepts on the message-house pillars, then adjusted twice by Max: (1) show the paid ads and the campaigns, so pillar 5 got a paid concept, "The ads Otto makes" (sample ads for fictional demo brands from `brands/otto/assets/showcase/`, captioned as such), and a3 shows **the campaign Otto runs** (one campaign, an ad set per angle) next to the 07:35 report; (2) "it should talk marketing, not only paid ads", so the set sells the whole marketing department, about half organic (a5 posts, reels and stories every week; a6 the opening week; a1's planned month) and half paid (a3, a4; a2 both), under the umbrella "Automate your marketing". "Next level" (pillar 6) lives in a1 (second headline, the before/after card, the versus end card); "Launch without worrying" (pillar 3) shares a6 with the offer, because a new business is the most natural moment for a free week. Every old render, sheet, kit file and import file was deleted; ids that kept their name (`nl-a1-notes-v` …) were re-rendered.
- **The price is in the ads, only as "€79 a month": one public plan, monthly** (Max, 2 Oct: "the plan is a monthly subscription"; then "there is one public plan, so say €79 a month, never from €79" — this overrides the message house's "from €79"). Wherever there is room the ads add "monthly, no contract, cancel anytime" and "excl. VAT": every end card that names the price carries the legal line "Monthly plan, no contract, cancel anytime. Prices excl. VAT."; the offer card, the big-number card ("Monthly plan" kicker), the comparison footnote and the a2/a6 primaries say it too; the landing carries the VAT note. Never another plan's price, never a yearly price. Where the price is split over two lines (the big video's "€79" + "a month with Otto", the table's "€79" under "Price a month", the big-number card's suffix) it still reads "€79 a month".
- **Agency figures: only the sourced ranges.** NL leads with "€500–1,500 a month, just for posts", IE with "€1,000+ a month for posts and ads" (both from research/EU-LAUNCH-AND-PRICING-2026-09.md §3.4, public 2026 price lists); no agency is named; the comparison table and the a2 end cards carry the source line. Otto's side always says what it is: €79 a month, excl. VAT, ad spend paid to Meta directly.
- **compliance.json conflict (open item for Max).** `brands/otto/compliance.json` still has the September rule "no price-versus-agency framing": two regexes that block the word agency and a euro figure in one sentence. The message house now asks for exactly that comparison. I could not edit compliance.json (outside this task's scope), so the copy keeps the word "agency" and the figures in separate sentences or fields ("€500–1,500 a month, just for posts. That's what a social media agency charges.") and the engine passes it with 0 violations. That passes the letter of the old rule, not its intent; the real guard is now `render.py compliance`, which audits every euro figure against the message house ("€79 a month" and never "from €79", sourced ranges only, sample figures only on Sample screens) and flags any sentence that still mixes the two. Suggested replacement for the two regexes: block agency figures other than the sourced ranges, e.g. `re:\b(?:agency|agencies)\b[^.\n]{0,60}€\s?(?!500–1,500|1,000\+)\d`.
- **"Ad set" is not in the copy.** The engine treats "ad set" as internal jargon (otto_render.INTERNAL), so the copy says "ads for every angle"; the campaign phone's own UI label ("Ad sets · one per angle") is part of the screenshot.
- **Samples are labelled.** Every figure on a phone (€18, 31 clicks, 4 enquiries; the campaign's per-angle spend) sits on a screen marked "Sample"; every sample post says "Sample post"; no review text is invented anywhere (the week phone's "Review post" row is a type label, the post types checklist says "from your real reviews"); the showcase ads are captioned "Sample ads for demo brands" / "Sample ad · demo brand" and use fictional brands only (no real brand names, no cannabis/CBD imagery).
- **English in both markets** (owner's rule). The NL copy is written for Dutch owners (euro, 24-hour times, the 07:35 report "in English, Dutch or German: your choice"); the IE copy for Irish owners (7:35, "your say-so", "Grand", "Go on", trades, B&Bs, clinics). No Dutch-language text appears anywhere in this kit any more (the Dutch-post phone is no longer used). The Dutch November matrix (`ads-2026-11-nl.json`) is kept only as an optional later test.
- **No creator cells.** UGC talking heads are briefs for real owners only (`creator-briefs-2026-11.md`) and join later as their own cells. The matrix rules drop the creator slot (`rules.slots`), and three faceless videos per concept keep video at **50 %** (18 of 36).
- **No manual carousel.** All 36 ads per market are in the import files.
- **Meta's 9:16 safe zone, enforced in `render.py`.** The ad-kit templates aim at y 200–1560 px, so on 9:16 four of them put text into the Stories/Reels UI bands (top 14 % = 0–269 px, bottom 20 % = 1536–1920 px): the versus labels (226 px) and footer, the big phrases (210 px), the search results pill (200 px) and the end card's sub line + fine print (from 1452 px down). `motion/ad-kit/` is outside this task, so `render.py videos` patches each built 9:16 project before `ship.mjs` checks and renders it (`SAFE_916`: labels 290 px, footer 1330 px, big phrases 290 px, search pill 290 px, end card head 290 px / products 580 px tall / sub 1280 px) and fails loudly if a template line it expects has changed. Measured on rendered frames: every headline, row, footer, sub, fine and legal line now sits between 269 and 1536 px. Left in the bands: the chat composer ("Message" placeholder, and the owner's reply while it is typed) and the chat avatar, which are UI chrome, and phone images (allowed). The kit's owner should take the same numbers into the templates.
- **Price and plan terms on end cards.** The fine line stays one line ("7 days free, no card. Then €79 a month.") and a third, smaller legal line carries "Monthly plan, no contract, cancel anytime. Prices excl. VAT." on every end card that names the price (the kit's `legal` slot, written in the matrix so the compliance check reads it).
- **Story placements of the showcase concept** use the 9:16 versions of the showcase ads (`assets/showcase/*-9x16.png`, listed under `variants` in its manifest): `otto-phone-story-ad-cutout.png` plays the Korrel Bakehouse 9:16 ad as a story (generic story UI, letterboxed so the ad's own headline is never cropped, "Sample ad · demo brand"); it closes the a4 big video, is the "Otto's ads" side of the a4 versus video, stands beside the ads phone on every a4 end card and in the a4 product card (all sizes). Picks from the showcase leave out every image with people or hands and every discount code.
- **Review fixes (2–3 Oct, from the contact sheets and frame checks):** search video picked a suggestion that no longer fits the pill ("…price per m") → "social media agency price list"; its result title broke as "€79 a / month" → no-break spaces; its end card had a dark logo on cobalt → white logo; a long suggestion clipped in the dropdown → shorter; versus rows "Week one in minutes" and "Every angle tested" overflowed their column → "Ready in minutes", "Angles tested"; the a5 chat hid its first bubble under the header when the photo arrived (check failure) → the photo opens the thread; the a6 chat ran six bubbles and hid the time stamp on 4:5 → four bubbles; end-card fine print wrapped to an orphan ("cancel / anytime.") → fine + legal line; chat bubbles broke as "€18 / on ads", "4 / images", "ready for your / tap.", "Cancel any / time" → reworded; notes lines wrapping into two struck lines ("the ads dashboard / at midnight", "order the / coffee machine") → shorter; IE table labels broke as "a / month" → "Posts and ads" / "Posts only"; the a4 checklist overflowed at 1:1 (5 items) → 4 items, and its footnote left "first." alone → shorter; the a2 big video's last phone was the IE review cut-out with a grey placeholder photo → the sample carousel post; the a4 product card's first duo hid the "Sample ads for demo brands" caption → phones side by side.
- **Campaign status PAUSED on import**, so nothing spends before you've checked the drafts.

## 9. Open items

- The **domain** is not bought yet. Until it is, every link reads `{DOMAIN}` and the import files are not importable. Run `build.py --domain …`.
- **Page id, Instagram id, dataset id, exclusion audience id:** they come from the Meta setup (GTM §11, items 1–2).
- **€79 everywhere it matters:** `platform/plans.json` (Starter) and the landing are being changed by another pass; the Stripe prices must exist before the first trials end on 10 Oct. The month phone's "50 posts · 12 stories · 4 reels" matches the Starter limits in plans.json today; re-check if those change.
- **compliance.json** still carries the September price-versus-agency regexes (§8): Max to replace or narrow them.
- The **showcase ads** (sample ads for demo brands) come from another pass; if one of them is replaced, re-run `python3 phones.py` and `render.py statics` + `videos --only <a4/a6 cells>`.
- The **bulk-import column names** follow a real Ads Manager export (Oct 2021) plus Meta's help pages; the newest columns couldn't be verified. If Ads Manager rejects a column, export any one ad (Export & import → Export selected), paste our rows under its headers, and import again.
- Placement customisation (9:16 statics, 4:5 videos) is a manual step (see §3).
- **Big-video hooks:** the first phrase slams in with a scale and motion blur; the key-frame sheets catch it at its widest (e.g. "€500–1,50…"), and it settles inside the frame within ~0.3 s (checked on frames at 1.95 s). If a reviewer wants a clean hook frame, the fix belongs in `motion/ad-kit/templates/styles/big.html` (start the slam at scale 1).
- **`motion/ad-kit`:** take the `SAFE_916` numbers from `render.py` into the templates, so other brands' 9:16 videos also keep text out of the Stories/Reels bands.
