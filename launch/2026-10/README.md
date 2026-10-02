# Otto launch kit: Meta ads in the Netherlands and Ireland, from Saturday 3 October 2026

Everything needed to start Otto's own paid Meta campaign in **NL and IE at €50 a day each (€100 a day total)**. The ads
are in **English in both markets**, and the offer is the **free 7-day trial** (sign in with Google, no card, nothing charged
automatically). The ads show no prices because the monthly prices are not approved yet. Nothing here has been created in
any Meta account. Plan and rules: `docs/GO-TO-MARKET-NL-IE.md`. Machine-readable spec: `campaign.json`.

| | NL | IE |
|---|---|---|
| Campaign | `OTTO · NL · Launch · 2026-10` | `OTTO · IE · Launch · 2026-10` |
| Ads | 36: 18 faceless videos (9:16; notes and texts also 4:5) + 18 statics (4:5, plus 9:16 and 1:1 where the template has them) | 36, same mix |
| In the import files | 35 (the carousel is built by hand, step 6) | 35 |
| Ad sets (concepts) | a1 Reels without the filming · a2 The 07:35 message · a3 Local, not translated · a4 You run it, Otto posts · a5 7 days free · a6 The busy season, planned | a1 Reels without the filming · a2 The 7:35 message · a3 Local, not generic · a4 You run it, Otto posts · a5 7 days free · a6 Christmas, sorted early |

## 1. Files

| File | What it is |
|---|---|
| `import/otto-{nl,ie}-part1.xlsx` | Bulk-import file 1 for each market: the campaign, ad sets a1–a3 and their ads (9 videos). `.csv` = the same rows in Ads Manager's own export format (UTF-16, tabs). |
| `import/otto-{nl,ie}-part2.xlsx` | Bulk-import file 2: ad sets a4–a6 and their ads (9 videos), added to the campaign that part 1 created. |
| `import/media/{nl,ie}-part{1,2}/` | Exactly the images and videos each part uses. Select the whole folder in the import dialog. |
| `meta-bulk-import.xlsx` | Review copy: all 70 imported ads on one sheet, plus the media list (which 4:5 / 9:16 / 1:1 file belongs to each ad) and the manual steps. |
| `creatives/{nl,ie}/static/` · `creatives/{nl,ie}/video/` | Every render. File names are `<ad id>-4x5.jpg`, `-9x16.jpg`, `-1x1.jpg`, `-9x16.mp4`, `-4x5.mp4`, plus the `.jpg` poster next to each video. |
| `sheets/` | Contact sheets for review: `{nl,ie}-statics-{4x5,9x16,1x1}.jpg`, `{nl,ie}-videos.jpg` (four key frames per video), and `video/*-sheet.jpg` (one sheet per video). |
| `compliance-report.md` | Every text checked, with its result (`qa/compliance-*.json` holds the raw data and `qa/check-*.txt` the engine's matrix check). |
| `build.py` | Rebuilds the import files once the domain and Meta ids are known. |
| `render.py` | Re-renders, re-checks and re-sheets everything from the matrices (`check`, `statics`, `videos`, `sheets`, `compliance`, `all`). |
| Sources | `brands/otto/ads-2026-10-{nl,ie}.json` (copy and render data) · `brands/otto/video/2026-10-{nl,ie}/` (video kit files) · `brands/otto/video/presentation-2026-10-{nl,ie}.json` |

## 2. Must be true before you import

1. **The landing is live on the real domain**, with Google sign-in working there and the consent banner on.
2. **Conversions API is on.** `$OTTO_SECRETS/meta-capi.json` holds the dataset (pixel) id and the token, `python3 otto_track.py capi-status` says forwarding is ON, and `test_event_code` has been **removed**.
3. **One real sign-up.** On the live domain, press Accept on the banner, then sign in with Google once (a team account is fine). Events Manager should then show **CompleteRegistration** received from the **Server** within about 20 minutes. Until that happens, Ads Manager marks the event "no recent activity". It still lets you pick it, but the warning is gone once one real event has arrived.
4. **Meta setup.** The ad account is in EUR, Otto's Facebook Page and Instagram professional account are connected, and the domain is verified in Business settings → Brand safety → Domains.
5. **A custom audience for the exclusion.** Audiences → Create → Custom audience → Website → your dataset → event **CompleteRegistration** → 180 days → name it `Otto · signed up · 180 days`.

## 3. Upload, step by step (about 15 minutes)

1. **Build the files (1 min).** Run this from `launch/2026-10/`:
   `python3 build.py --domain <your-domain> --page-id <Page id> --instagram-id <Instagram account id> --pixel-id <dataset id> --exclude "<audience id>:Otto · signed up · 180 days"`
   You'll find the ids in Business settings (Pages, Instagram accounts), Events Manager (dataset) and Audiences (the audience id).
2. **Import NL part 1 (3 min).** In Ads Manager, open the ad account, then **Export & import (the ⋯ menu above the table) → Import ads in bulk**. Upload `import/otto-nl-part1.xlsx`. When the dialog asks for media, select every file in `import/media/nl-part1/` (8 images, 9 videos). Ads Manager creates everything as drafts.
3. **Check the drafts (3 min), then publish.**
   - Campaign: **Leads**, **Advantage+ campaign budget €50/day**, bid strategy **Highest volume**.
   - Ad sets: conversion location **Website**, dataset = yours, event **Complete registration**, performance goal **Maximise number of conversions**.
   - Audience: location **Netherlands** (people living in or recently in), **Advantage+ audience on**, under audience controls **minimum age 25**, the exclusion audience in place. Optionally add the concept's interest suggestions from §5.
   - Placements: **Advantage+ placements**. Ad-set spending limit: **daily minimum €4**.
   - Ads: Page and Instagram identity correct; the **destination URL** shows the domain, and URL parameters read `utm_source=meta&utm_medium=paid&utm_campaign=otto_nl_launch&utm_content=<ad id>`.
   - **Advantage+ creative:** select all ads → Edit → turn **every** enhancement off. That covers text improvements, visual touch-ups, add overlays, music, 3D animation, image brightness and contrast, translations, show summaries / spotlights / reveal details, relevant comments and site links. **Optimise website destination: off** (it can send people to other pages). The ads say exactly what the compliance check passed, and no AI-made people or text get added.
   - Then **Publish**. The campaign stays **Off** (imported as PAUSED) until step 7.
4. **Import NL part 2 (2 min).** Copy the new campaign's id (Campaigns tab → Columns → Customise → *Campaign ID*, or from the URL `…selected_campaign_ids=<id>`). Then:
   `python3 build.py … --campaign-id nl=<NL campaign id>` (keep the other flags). Import `import/otto-nl-part2.xlsx` with the files in `import/media/nl-part2/`. Ad sets a4–a6 are added to the same campaign. Check them as in step 3 and publish.
5. **Repeat steps 2–4 for IE (6 min):** `otto-ie-part1.xlsx` + `media/ie-part1/`, then `--campaign-id nl=…,ie=<IE id>` and `otto-ie-part2.xlsx` + `media/ie-part2/`. The location is **Ireland**.
6. **Optional on day 1 (2 min per market): the carousel.** Add it in ad set **NL · a3** (`nl-a3-carousel`, 5 cards) and **IE · a6** (`ie-a6-carousel`, 6 cards). Choose New ad → Carousel, then add the cards `creatives/<mk>/static/<id>-c1-4x5.jpg` … in order. Copy the headline, primary text and CTA from the "manual steps" sheet of `meta-bulk-import.xlsx`, and set the same URL parameters with `utm_content=<id>`. Bulk import can't attach carousel cards by file name, so this one is done by hand.
7. **Saturday 3 October, morning: switch both campaigns On.** Nothing else changes for 72 hours (§7).

**Why two import files per market:** the import dialog takes at most 10 videos (≤ 10 MB each) per import, and each market has 18. Every video here is under 5 MB.

**Optional before publishing, ~20 s per ad: placement customisation.** Each import row carries one asset: the 4:5 image for statics, the 9:16 video for videos. Bulk import can only add a second image by its Meta image hash, which doesn't exist until the image is uploaded. Without customisation, Meta shows the 4:5 static in Stories/Reels on a padded background and crops the 9:16 video in Feeds. If there's time, open a static ad → Media → *Customise placements* → *Stories and Reels* → the `-9x16.jpg`. For notes and texts videos, open *Feeds* → the `-4x5.mp4`. The pairs are listed on the "media" sheet. It's worth doing for the 13–14 statics per market that have a 9:16 version.

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
- *A brand-new dataset has no history for any event.* That isn't a blocker. Meta lets you pick a standard event before it has fired and starts delivery broad, learning from the first conversions. The one real sign-up in §2.3 removes the "no recent activity" warning. Conversions API events optimise exactly like pixel events.
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
| Audience | **Advantage+ audience on**, no language restriction. Optional suggestions per concept: NL a1/a6 Restaurants, Coffeehouses, Hospitality industry · a2/a4/a5 Shopify, E-commerce, Small business owners, Facebook page admins · a3 Hairdresser, Beauty salon, Nail salon. IE a1/a6 Restaurants, Bed and breakfast, Hotels, Tourism · a2/a4 Plumbing, Construction, Electrician, Small business owners · a3/a5 Physical therapy, Dentistry, Small business owners. Check each option exists in Ads Manager, because Meta merged many in 2025–26 |
| Exclusions | Custom audience `Otto · signed up · 180 days` (CompleteRegistration). At account level: Otto's team and pilot brands' page admins. Detailed-targeting exclusions no longer exist |
| Placements | Advantage+ placements (all). Feeds get the 4:5 static or the video's feed crop. Stories/Reels get the 9:16 video, and the 9:16 static after the optional placement customisation |
| Ads per ad set | 6: 3 faceless videos and 3 statics (a3 NL and a6 IE: 5 in the import + the carousel by hand) |
| Copy | The engine's rule: each ad runs one of the concept's 1–2 headlines and 2–3 primary texts, rotated over its visuals, so the test is about the visual. Multiple text options and dynamic creative are off |
| Destination | `https://{DOMAIN}/` + URL parameters `utm_source=meta&utm_medium=paid&utm_campaign=otto_<nl|ie>_launch&utm_content=<ad id>` (the landing records the utm_* tags first-party) |
| Ad names | The matrix cell id (`nl-a2-texts-v`, `ie-a5-offer` …), so Meta, the UTMs and the matrix line up |
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

The ad-level and concept-level pauses already apply from day 7 (§7). Paying customers only exist from about day 8, after the first trials end.

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
1. **Delivery:** every ad set has spent something. If an ad set has spent €0, look for a disapproval or a missing asset. Fix disapproved ads by changing only the flagged words, run `render.py compliance` again, and resubmit.
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

- **English in both markets** (owner's rule). The NL copy is written for Dutch small businesses: euro, Haarlem and Utrecht, Sinterklaas, King's Day, the terrace season, 24-hour times (07:35), and the 07:35 report "in English, Dutch or German: your choice". KVK and btw are left out because no price is shown and neither would help. The Dutch November matrix (`ads-2026-11-nl.json`) is kept only as an optional later test.
- **Dutch text appears in one place:** concept a3 NL ("Local, not translated"). Its product card and its three videos show Otto's Review screen with a sample café post written in Dutch; the card labels it "Sample post, written in Dutch". That screen is the proof of the concept's claim that Otto writes your posts in Dutch. Every other NL phone shows a new English cut-out of the same screen (`brands/otto/assets/otto-phone-review-nl-en-cutout.png`). If you want zero Dutch anywhere, swap `review_nl` → `review_nl_en` on a3 in the generator / matrix and re-render the three a3 cells.
- **No creator cells.** UGC talking heads are briefs for real owners only (`creator-briefs-2026-11.md`) and join later as their own cells. The matrix rules drop the creator slot (`rules.slots`, 5 styles per concept), and one extra faceless video per concept keeps video at **50 %** (18 of 36).
- **No prices.** The founding-pilot €197 line from November is removed everywhere. The only euro figures are the sample report numbers in the a2 chat videos ("€18 on ads, 4 enquiries"), shown on a screen labelled "Sample".
- **The moment concept (a6) moved from "December, planned in November" to "the busy season, planned ahead",** because people now sign up in October. The chat sample is dated 26 October and shows "Your November is ready to review".
- **Campaign status PAUSED on import**, so nothing spends before you've checked the drafts.

## 9. Open items

- The **domain** is not bought yet. Until it is, every link reads `{DOMAIN}` and the import files are not importable. Run `build.py --domain …`.
- **Page id, Instagram id, dataset id, exclusion audience id:** they come from the Meta setup (GTM §11, items 1–2).
- **Monthly prices and Stripe:** trials can't convert to paid until the Stripe prices exist (GTM §1.2 item 6). A trial that starts on 3 Oct ends on 10 Oct.
- The **bulk-import column names** follow a real Ads Manager export (Oct 2021) plus Meta's help pages; the newest columns couldn't be verified. If Ads Manager rejects a column, export any one ad (Export & import → Export selected), paste our rows under its headers, and import again.
- Placement customisation (9:16 statics, 4:5 videos) and the two carousels are manual steps (see §3).
