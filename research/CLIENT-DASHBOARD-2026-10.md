# Otto's client dashboard: what to show so €79 feels worth it
Date: 2026-10-02 · Author: Claude Code (research and design only, no code changed) · Builds on `research/COMPETITORS-2026-09.md`,
`docs/NATIVE-PARITY.md`, `platform/STRUCTURE.md` (24.09, partly superseded) and `docs/MESSAGE-2026-10.md`.
All web sources were accessed on 02.10.2026 unless another date is given. "Unverified" means not confirmed from a primary source.

## TL;DR
- **Otto already collects most of the numbers a client wants, and shows few of them.** These all sit in `data.json` or
  `brands/`: the growth ledger, per-campaign ad numbers, Google search terms, the monthly review text, the 20-ad matrix, the
  brand profile and the onboarding goal. The app shows a Results *card* on Today and yesterday's paid totals inside Settings.
  It never shows an ad.
- **Nobody below about $1,000 a month gives a small business its leads.** Native, Holo, Predis, Ocoya, Metricool, Later and
  Buffer have no leads screen. Blaze puts calls, forms, DMs and reviews behind its $999 All-in-One. Meta's own Leads Center
  keeps form data for 90 days and sends no alert for each new lead. Otto's Starter ads already run Meta lead forms, so the
  enquiries exist; nobody looks at them.
- **Native has a strong Home and Ads view, but no leads, no scheduled report, no export, no cost per lead, no competitor
  tracking and no goals.** Those are the openings. A Results screen on its own only matches Native. Leads, the 07:35 report
  and "what it brought" set Otto apart.
- **Competitors are moving towards one plain-language sentence that says what the numbers mean.** Examples: Buffer Takeaways,
  Metricool Studio, Holo's reports, Blaze's weekly e-mail, Native's "the week you just had". Otto's 07:35 sentence already
  does this, so the app should open with it.
- **Trials are won or lost in week 1, and week 1 is empty today.** The trial sees "0 Scheduled · 0 Published · 1 Brand" and
  "Results start after the first published week". It should see the work instead: posts, reels, the 20 ads, the plan, and a
  connect checklist.
- **Proposed app:** five tabs (Today · Review · Calendar · Results · Leads) and an account menu (Brand · Plan & billing ·
  Connections · Notifications · Account). The Posts tab becomes a list view inside Calendar.

## 0. Top 8 recommendations
| # | Recommendation | Priority · effort |
|---|---|---|
| 1 | **Make Results a tab.** Organic and paid in one view; week, month and last month against the previous period of the same length; one chart with a metric switch; best posts; a campaign table; the "what happened" sentences and the monthly review. Almost all of it comes from data Otto already has. | P0 · M |
| 2 | **Open Today with the 07:35 sentence and a "Yesterday" strip** (reached · enquiries · spent · cost per enquiry). Read it from the same model as the e-mail, so the app and the report always show the same numbers. | P0 · S |
| 3 | **Show the work.** Add a "This month's work" ledger to Today and Results: posts 31 of 50, stories 4 of 12, reels 2 of 4, 20 ads live, ad budget used. Build the week-1 screens on it. | P0 · S |
| 4 | **Show the ads.** Put the month's 20 ads in Review as a grid (angle × style) before the paid plan is approved. Once they run, rank them by results in Results (Meta reports results per ad). | P0 (grid) · M · P1 (results) · S |
| 5 | **Add a Leads tab (CRM-lite).** Every enquiry from Otto's lead-form ads, later also website forms and DMs. Each shows the ad it came from, a status (New / Contacted / Won / Not a fit), a value, and one-tap Call · WhatsApp · E-mail, with an alert the moment it arrives. Leads are stored beyond Meta's 90 days. | P1 · S code, L Meta approvals (start now) |
| 6 | **Add a "what Otto brought" line:** Otto plus ad spend this month, against the enquiries won and the value the owner typed in. | P1 · S |
| 7 | **Before and after.** At connect, pull the Instagram account numbers and the 30 days before Otto. Mark "With Otto since" on the chart. Move off the Facebook metrics Meta retired in November 2025. | P1 · S–M |
| 8 | **A Brand page and a better competitor card.** Show the brand profile, the owner's onboarding answers and what Otto learned (all of it exists but is hidden after onboarding). Add competitors' changes and their active Meta ads, which the Ad Library API returns for EU and UK delivery. | P1 · M |

Also needed at launch: the Today banner's "Connect" button leads to a Settings row that has no button. Give it a Connect sheet (S).

---

## 1. What competitors show their clients

### 1.1 Native (native.no), Otto's main competitor
Sources: Native's changelog (157 entries, 16.03–24.09.2026), its guides and blog, the "how it works" mockup, Trustpilot,
hanspetter.info (18.03.2026). Native is a web app only; there is no app in the App Store or Google Play.

| Area | What a Native client gets |
|---|---|
| **Navigation** | Tabs: Suggestions, Home, Create, Calendar, Inbox, Analytics, Memory. Also Designer, a Creations library, Products, a photo library, Autopilot settings, Branding → Ads (Campaigns / Configure), Manage plan (cancel flow with a save offer), and a setup checklist. |
| **Home** | "The week you just had" plus the top post. A week / month / quarter / year switch. A posting streak. A ranked list of everything published, ads and organic together. A comparison for each metric. A "winner" card (best ad or best post). **Every tile links to the post or campaign behind the number.** ROAS sits behind a toggle. **Charts mark the day Native started** (before / after). Numbers come from platform page insights, including Google Business. When a number has no source, Home says so instead of showing zero. Below that: the Autopilot week, a countdown to the next post, and "Ad pack ready" / "making your ads" cards. |
| **First numbers** (Numbers screen, May 2026) | Total views, likes, comments, shares and average engagement. Posts per day (7 / 30 / 90 / all). Views by channel (donut). Top posts. A chat box ("What's my best performing post?"). The marketing mockup also shows "14 new customers, +24% vs last month", "2 leads waiting for you to confirm — Became a customer / Didn't", estimated revenue, people reached and customers gained per week. **Unverified in the product.** |
| **Analytics** | Reach, likes, engagement and comments per channel and per post, including posts from before Native. A chat to ask questions about the numbers. YouTube. A "ticket" page for each post: a countdown, then its performance. Results feed the next content. |
| **Ads** (Meta only) | Per ad: spend, reach, clicks, CPC, cost per view, days live. Compared with last week, with the client's average, and as a top-10 rank. Audience down to city, age, gender, devices and placements; video retention. A plain-language status ("What is happening with this ad?"). Pause, resume, rename; edit campaigns and ad sets. Goals: Traffic, Engagement, Awareness, Sales, Website leads. Create a pixel in the app. A daily spend cap for the account. Autopilot history. Approval in "Review first" mode, one ad at a time by swiping. An ad pack PDF. 5 new ads a week by default. |
| **Inbox** | Messages, comments and reviews across IG, FB, LinkedIn, X, Threads, Bluesky, Google Business and WhatsApp (added 02.10). Labels, spam, read receipts, search, filters. Shows WhatsApp's 24-hour window. AI-drafted replies to Google reviews. |
| **Leads / CRM** | Nothing beyond the mockup. No lead status, pipeline or value. No capture from Meta lead forms. |
| **Reports** | **No weekly or monthly performance report.** No PDF or CSV export of analytics and no shareable report. Only operational e-mails: pre-publish, ad pack ready, published, reconnect. |
| **Memory (brand)** | Brand DNA, tone, archetypes, rules, style references, pillars. Products from Shopify, WooCommerce or a feed. A photo library with usage and a "needs new photos" warning. "View sources" on each post. |
| **Competitors, goals** | Competitors are researched once at onboarding. No tracking, no benchmarking, no business goals or KPIs. |
| **Feedback** | Trustpilot 2.8/5 from 10 reviews: poor AI posts, bugs, support, pricing. An independent test (hanspetter.info, 18.03.2026) said Native had no understanding of the business's actual goals. Native's own changelog admits earlier gaps: no way to get from a number to the post behind it, mislabelled budgets, ads in review shown as active, "confident zero" numbers. It also says every brand asks in its first month whether Native is working. |

**What Native lacks and Otto can own:**
- lead tracking
- a scheduled performance report (nothing like the 07:35)
- export or shareable reports
- cost per lead (Native judges ads on clicks and CPC)
- competitor tracking and goals
- AI video, Google Ads and a mobile app

**What Otto must match:**
- Home with a period switch
- a winner card
- every number linked to the post or ad behind it
- the day Otto started marked on the chart
- ad results with comparisons
- "not in yet" instead of zero
- a brand memory page
- a photo library

### 1.2 AI marketing and social tools (what the logged-in app shows)
| Product · price | Modules | First numbers | CRM, leads, inbox | Reports | Praise | Complaints / missing |
|---|---|---|---|---|---|---|
| **Blaze** · Starter **$79** (includes automated ad campaigns), Growth $149, All-in-One $999 | Home (setup checklist, recent posts, credits), Calendar, Approvals, Campaigns (goal + cadence), Meta Ads, Insights, Brand Kit | Top posts, metrics per platform, 7- and 30-day windows; data arrives a few business days late; Meta spend, link clicks and results (unverified) | **Only at $999:** AI receptionist for calls, forms and DMs, lead qualification, review requests and replies, GBP | Weekly e-mail summary (best content, next steps); a monthly "leads and ROI" report only at $999 | Easy to start, hands-off (Trustpilot 4.6, 1,298 reviews) | Generic or repetitive writing; $80–150 hard to justify |
| **Holo** · Starter $20, Scale $48 (analytics and autopilot only on Scale) | Studio, Workspace (a board of drafts to approve), Brand DNA (includes a competitor analysis), Chat, Calendar | "Performance overview" in marketing images: purchases, spend, clicks, CTR, search position, Klaviyo revenue, follower growth, profile visits, ROAS (unverified in the app) | None | Daily, weekly and monthly reports on "what moved and what to do next" | A week of posts in 10 minutes (Trustpilot 4.4, 1,133 reviews) | Credits drain fast; batch approval with no preview; **the ads dashboard showed wrong spend** |
| **Predis.ai** · $24 / $55 / $212 | Generators, Brand Kits, calendar, auto-posting, approvals (top tier), competitor analysis, an engagement score predicted before publishing | Basic: post performance, engagement rate, best times | None | Competitor reports only | Some say the competitor analysis alone is worth the price | Limited customisation, complex, billing at the end of trials |
| **Ocoya** · $29 / $79 / $199 | Publishing, Campaigns, Design Studio, **Social Inbox**, Workflows, Bio pages, Analytics | Posts per platform, engagement rate, follower growth, hashtags | Inbox for FB/IG DMs, comments and mentions; an AI agent trained on the FAQs drafts or sends replies; Open / Assigned / Resolved | Export for client reviews | Analytics easy to reach (Capterra 4.6) | Users want more depth; no competitor tracking, no demographics |
| **Metricool** (the SMB analytics standard) · Free / about €16–20 / about €43–67 | Planning, Analytics, Inbox, Reporting (Studio, Campaign dashboards), Ads, SmartLinks, Hashtags, Competitors | Followers by network; interactions, number of posts and a post list; Ads: impressions, clicks, CPM, CPC, spent (Meta, Google, TikTok); best-time heatmap; **% change against the previous period of equal length** | Inbox on every plan, including **Google reviews**; link in bio; no CRM | PDF/PPT plus an automatic monthly e-mail from Starter; "Studio" builds AI reports from a plain-language request; white-label only for 50+ brands | Deeper metrics than Later, Hootsuite or Buffer (Trustpilot 4.1, 670 reviews) | Clunky, dated UI; heatmap accuracy doubted; thin free tier |
| **Later** · $18.75 / $37.50 / $82.50 (billed yearly) | Calendar, Analytics (Custom on Scale), Social Inbox (beta), Linkin.bio, UGC, Listening and Benchmarking (Scale) | Followers, views, reach; per profile: impressions, engagement rate, saves, link clicks; 7- and 30-day toggles | Linkin.bio e-mail sign-up form on every plan, the only lead capture at entry price | Downloadable, shareable and scheduled reports on Scale only | Detailed Instagram charts | Almost no analytics on lower tiers; Trustpilot 1.5 (billing) |
| **Buffer** · Free; $5 / $10 per channel | Publish, Insights (rebuilt April 2026), Community (inbox, including Google reviews), Start Page | All channels: followers, posts, a metrics chart, a sortable table, **Takeaways** (insight + one-tap action); single channel: posts, reactions, comments, views, shares, saves, follows, reach, engagement rate, each with % change | Inbox with AI reply suggestions; no CRM | CSV, Markdown, branded PDF; "Share as post" turns stats into a 1080×1080 image | Simplicity, the top praise on Reddit | Capterra (May 2025): "Analytics are basic unless you upgrade"; users outgrow it |

### 1.3 Ads analytics, SMB CRM, and Meta's free baseline
| Product · price | What the owner sees first | Leads / CRM | Reports | Complaints |
|---|---|---|---|---|
| **Madgicx** (Meta ads analytics) | KPI cards: spend, revenue, ROAS, CPA, outbound clicks / CTR, CPM; a business dashboard; creative insights; an AI Marketer that audits the account and offers one-click fixes; an ask-AI chat | None | One-click report: share link, PDF, scheduled e-mail, white-label | Surprise charges after the trial or after cancelling; learning curve; Meta only |
| **AdCreative.ai** | Creative generation and scoring; creative insights (top creatives, fatigue alerts) | None | A dashboard shared by link | Refunds, unexpected charges |
| **Owner.com** (restaurants, $249/mo + 5% or $499 flat, month-to-month) | Total sales, orders, Google rankings, new loyalty members, new reviews, order sources, new vs returning | A customer list, loyalty, automations | — | — |
| **Podium** ($399–599/mo, annual) | Appointments booked, calls, payments, lead sources, reviews | Inbox (SMS, webchat, GBP, FB), an AI employee, payments | — | Auto-renewal complaints |
| **Birdeye** ($299–449 per location per month, annual) | A "Birdeye Score", reviews, listings | Smart inbox, webchat, payments | — | Cancellation complaints |
| **Hootsuite / Sprout** (about $199–399 per seat) | A social suite for teams | Social inbox, CRM integrations | Rich | Team pricing, not for a €79 SMB |
| **Meta, free** | Business Suite Insights (overview, results, audience, content, benchmarking, ads, goals) | **Leads Center**: stages Intake / Qualified / Converted / Lost, notes, CSV; **no instant alert per lead, no automation, form data kept 90 days** | — | **Meta Business Agent (03.06.2026)** qualifies leads in WhatsApp, IG and Messenger and sends a morning briefing. That overlaps Otto's 07:35 report. |

### 1.4 What makes a client feel the €79 is worth it every week
1. **Proof of work before proof of results.** Native has a posting streak and an "ad pack ready" card; Blaze has a setup
   checklist. A trial has no results for days, so the work itself has to be visible.
2. **One sentence and one winner.** Native's "the week you just had" and its winner card, Buffer Takeaways, Holo's "what
   moved". The owner wants the conclusion, not a dashboard.
3. **Money words, in order.** Spend → enquiries → cost per enquiry → won. Below $999 nobody shows leads, and Native judges ads
   on CPC. This is the gap that is easiest to see.
4. **Compare with the client's own past, and mark the day it started.** Native marks its start date; Metricool and Buffer
   compare with the previous period. Nobody has credible small-business benchmarks.
5. **Every number opens the thing behind it.** Native shipped this after users complained.
6. **Honest numbers.** Say "not in yet" instead of zero. Native fixed its "confident zero"; Holo showed wrong spend; Blaze
   lags by days and says so. Trust breaks on one wrong number.
7. **The report comes to them.** Otto's 07:35, Blaze's weekly e-mail and Metricool's monthly PDF all arrive on their own;
   Native has none. Meta's Business Agent now sends a morning briefing for free, so Otto's report must carry what Meta's
   cannot: the leads with their status, the posts to approve, and the competitors.
8. **No contract surprises.** Madgicx, Podium and Birdeye draw complaints about auto-renewals and charges. Otto's "monthly,
   cancel in the app" belongs on the Plan page.

---

## 2. Otto's client app today (audit, 02.10.2026)

**How the audit was done:**
- **Walkthrough:** `otto-walk` on localhost:8790, signed in as the existing test trial, at phone and desktop width. The trial
  is Grüns on day 1 of 7, with 62 posts in "Copy in progress" and nothing connected.
- **Code:** the code paths that fill each screen once data exists.
- **Mockups, not the product:** `analytics.html`, `ads.html` and `approve.html` are early mockups with invented numbers.
  Each one redirects to `index.html` unless `?mockup` is in the address. The real client app is `index.html` alone.

### 2.1 Screens as they are
| Tab | What a client sees | Filled by |
|---|---|---|
| **Today** | Main column, top to bottom: the date; the trial line ("7 days left · Add a card"); an activity pill ("Drafting 61 upcoming posts", which opens today's timeline); banners (connect Meta, or a post failed); a hero sentence ("3 posts need you" or "You're all caught up"); a stat row **Scheduled · Published · Reach this month** (the brand count when there is no reach); "Needs you" (3 swipe rows); "Up next" (3). Side column: the **Results** card and one **Suggestion** card. | posts[], growth[], recommendations[] |
| Results (a card on Today, not a tab) | Per brand: **Reach** this month in large type, with the change from last month. A 7-day reach line for this month against last month. Reach by month as 6 bars. KPIs **Engagement · Posts published · Followers**, plus **Leads and sales · Paid spend · Cost per result** when the brand has paid ads. A footer: "Best pillar · With Otto since · Updated". Empty: "Results start after the first published week." | growth[brand] (otto_growth.py rollup, daily at 05:10) |
| **Review** | Pending posts (swipe, the A / S / C keys, or hold to approve all); a "Slot passed" group; "With Otto" (posts being rewritten) | posts[status=pending_approval] |
| **Calendar** | A month grid with dots (post, reel, needs you, published) and ad-campaign bands; a sheet for each day | posts[], campaigns[] |
| **Posts** | Filters: All / Scheduled / Published / Drafts. A published row shows "Reach n". **Ad campaigns** appear as static rows (name, network, €/day, dates, status). The post sheet shows the media, caption, pillar, format, reach, saves and the owner's note. | posts[], campaigns[] |
| **Settings** | **Plan:** what is included, plus this month's use ("62 of 66 posts · 4 of 4 reels · €0 of €1,000 ad budget"). **Approvals:** Email / Telegram / App only. **Language.** **Connections:** a status pill only, no connect button. **Paid:** per network, "yesterday €x · n leads or purchases · €y each". **Signals:** approved and skipped counts per pillar; competitors with names, promotions, "n changes" and the date checked. **Activity:** one line per job. **Account. About.** | plan_view, connections[], ads[brand].daily, taste_log[], competitors[] |
| 07:35 report (e-mail or Telegram, not the app) | A greeting and a one-line summary ("Yesterday: €18 on ads, 4 enquiries. 3 posts wait."). Tiles: Spent · Enquiries or Sales · cost per result · within budget. Spend per day as a chart. Yesterday's posts with reach, clicks, reactions and saves, and "Best yesterday". Today's schedule. Approvals with one-tap buttons. P0 / P1 cards. Drop alerts. | otto_report.model() |

**Week 1 for a trial, as seen in the walkthrough:**
- the activity pill "Drafting 61 upcoming posts"
- a banner "Connect Instagram and Facebook so Otto can publish", whose Connect button leads to Settings
- in Settings, Connections shows "Not connected" with no action
- "You're all caught up"
- the stat row 0 · 0 · 1
- the Results card "Results start after the first published week"
- one suggestion, "Connect Google Ads"

Nothing in the app shows the brand profile Otto built, the competitors it found, or the ads it planned.

### 2.2 The data behind it
| Data | Written by | In client_view | Shown in the app |
|---|---|---|---|
| posts[].metrics: reach, saves, likes, comments, shares, replies; clicks for FB only | otto_insights.py (weekly, plus a refresh of yesterday's posts at 07:35) | yes | Reach on a row; reach and saves in the post sheet |
| metrics[brand]: sums of recent posts, followers, page_reach_week; `leads` is always 0 | otto_insights.py | yes | no (only through growth) |
| metrics_history.jsonl (one snapshot a day) | otto_watch.py snapshot at 07:30 | no (it is a file) | feeds growth.daily and the drop alerts |
| growth[brand]: 6 months of reach, engagement, clicks, posts, followers, spend, results_meta / results_google, cpl, by_pillar and decisions; month-on-month %, best_pillar, a 90-day daily series, and the **review text** | otto_growth.py rollup | yes | The Results card. **The review text, clicks and by_pillar are not shown.** The review only goes out by Telegram on the 1st. |
| ads[brand].daily: 90 days, per network; yesterday plus 7-day totals; **per-campaign rows with spend, reach, link clicks, CTR, results, CPL and ROAS**; Google's top search terms | otto_ads.py report at 07:15 | yes | Only yesterday's totals, in Settings → Paid. **Campaign rows, 7-day totals and search terms are unused.** |
| campaigns[]: plan, flights, budgets, planned creatives, compliance hold | otto_ads.py plan / launch | yes | Static rows and calendar bands. **Creatives are never shown.** |
| The monthly ad matrix brands/<id>/ads-YYYY-MM.json: concepts × styles, with copy | otto_styles / otto_copy | no | **Never.** The client approves "the October paid plan: 4 campaigns, ≈€600" as a text card. |
| recommendations[] (client-visible only) | engine scripts | yes | one card on Today |
| competitors[brand] (names, promotions, number of changes, last sweep), plus competitor-research.md and angles.json | otto_competitors.py (monthly on Content and Starter, weekly on Growth) | the summary only | one line per brand in Settings → Signals |
| taste_log[] | ap.decide | yes | Settings → Signals |
| The brand profile (scan.json, brand-profile.md, strategy.json) and the onboarding answers (goal, ad budget band, customer questions, never-say words) | otto_scan, otto_onboard, otto_strategy | the onboarding block travels in the brand object | **never after onboarding** |
| winning-posts.md and the "Double down on <pillar>" recommendation | otto_insights.py | the recommendation only | as a Suggestion |

**Owner-only data (never reaches a client):**
- `leads.json`: Otto's *own* sales leads, i.e. domains scanned on Otto's landing, with status and notes in the console.
- `events.jsonl` and Meta CAPI: otto_track's analytics for Otto's landing.
- The admin snapshot: funnel, trials, MRR, churn, AI spend.
- Fleet and agents, actions.log, retention notices.

The console's lead list is a CRM for Otto's own sales. Nothing like it exists for a client's customers.

**Data that does not exist anywhere for a client:**
- Who the enquiries are: names, phone, e-mail, which ad.
- DMs and comments, and reviews.
- Website visits and contact-form submissions.
- Instagram account insights: follows, profile link taps, accounts engaged.
- Results per ad (creative). Ad insights are pulled at campaign level only, while the landing page promises "Ad spend, clicks
  and enquiries, ad set by ad set".
- Lead value, won customers, revenue.
- A shareable or PDF report.
- Goals.

### 2.3 Data quality risks found in the code
- **Facebook Page metrics Meta retired.** Meta stopped serving the Page "impressions" and "page fans" metrics on 15.11.2025
  (replaced by `page_media_view` / `page_total_media_view_unique`, `post_media_view`, `page_follows`). `otto_insights.pull_page`
  still asks for `page_impressions_unique`, and `pull_post` asks for `post_impressions_unique` (its comment says "on Meta's
  deprecation track"). The code requests each metric separately and survives a failure, so the risk is quiet: Facebook reach
  may come back empty. **Check this with a real token before the first client's report.**
- **Followers come from the Facebook Page** (`followers_count`). Instagram followers and Instagram account insights are not
  pulled. The Instagram metrics `website_clicks` and `profile_views` were removed in January 2025; the replacements are
  `profile_links_taps` and `follows_and_unfollows`, and `views` replaced `impressions` in April 2025.
- **Organic "clicks" exist only for Facebook posts** (`post_clicks`).
- `metrics[brand].leads` is carried forward and never set.
- **Paid "results" are action counts.** `otto_ads.OBJECTIVE_RESULTS` takes the first present of `lead`, `onsite_conversion.lead_grouped`
  and `offsite_conversion.fb_pixel_lead`. That is right: `lead` is the total, and the parts must not be added. Splitting form
  leads from website leads needs the two sub-types.

---

## 3. Proposed information architecture

### 3.1 Principles
1. **Three questions, in this order:**
   - What needs me? (Today, Review)
   - What did Otto do, and what did it bring? (Results)
   - Who wants to buy? (Leads)

   Everything else goes under the account menu.
2. **One sentence before any number.** Each screen opens with a plain-language line built from the numbers, for example
   "You got 14 enquiries at €5.10 each, 6 more than by this point in October". The sentences come from templates, so nothing
   is invented.
3. **Never empty.** Before results exist, show the work (made, scheduled, designed), the plan and the baseline. A sample is
   always labelled "Sample".
4. **The same numbers everywhere.** The 07:35 e-mail, Today and Results read one model (otto_report.model plus growth), so the
   app never disagrees with the morning report.
5. **The owner's words.** "People reached", "Enquiries", "Cost per enquiry", "Link taps". No CPL, CTR, CPM or ROAS on the
   first screen.
6. **Compare with yourself.** Every number is compared with the previous period of the same length and, after connecting,
   with the 30 days before Otto. No invented industry benchmarks.
7. **Every number opens what is behind it** (the post, the ad, the lead). **Every decision is one tap** in the app, the e-mail
   and Telegram.
8. **"Not in yet", never a false zero.** Meta's numbers can lag by up to 48 hours.

### 3.2 Navigation
- **Phone tab bar (5) and desktop sidebar:** Today · Review · Calendar · Results · Leads.
- **Account menu** (initials, top right on the phone, at the foot of the sidebar on desktop): Brand · Plan & billing ·
  Connections · Notifications (approvals, reports, new-lead alerts, language) · Account.

What changes:
- **Posts stops being a tab.** Calendar gets a Month | List switch, and List keeps the All / Scheduled / Published / Drafts
  filter that Posts has today.
- **Settings splits** into the account-menu pages above; nothing in it is lost.
- **Review holds every decision:** posts, the month's ads as a set, and later reply drafts.

### 3.3 Screens

#### Today
| Module | Shows | Source | Status |
|---|---|---|---|
| Header | The date; the trial or plan line; a payment problem | /auth/me, plan_view | exists |
| Blocking banner (one at most) | Reconnect / a post failed / a payment failed | connections[], posts[] | exists |
| Hero sentence and button | The 07:35 summary ("Yesterday: €18 on ads, 4 enquiries. 3 posts need you.") and "Review 3" | otto_report.summary() through the API | new endpoint, S |
| Yesterday strip | Reached · Enquiries (or Sales) · Spent · Cost per enquiry, each against the 7-day average. Organic-only plans: Reached · Engagements · New followers · Link taps | otto_report.model(), growth.daily | the data exists |
| New leads (when there are any) | Up to 3, each with Call or Reply | leads[] | new (P1) |
| Needs you · Up next | As today | posts[] | exists |
| This month's work | Posts n of 50, stories n of 12, reels n of 4, ads live (20), ad budget used | plan_view.usage, campaigns[], the matrix | mostly exists |
| Suggestion | One card | recommendations[] | exists |

**Week 1:**
- The hero reads "Otto is writing your first week", with a real progress line from the server (posts drafted of planned, an
  estimated time). This follows Max's progress rule.
- A connect checklist replaces the Yesterday strip.
- "This month's work" already shows what has been made.

#### Review
- **Posts:** as today.
- **New group, "Your ads for <month>":** the matrix as a grid, with angles as rows and styles as columns, and a preview in each
  cell. One "Approve the ads and budget" button, which is the existing approve_plan card. A "Change" on each ad for its copy.
- **Week 1 (trial):** the same grid, with the line "They start when you choose a plan; nothing is spent in the trial."
- **Source:** brands/<id>/ads-YYYY-MM.json, campaigns[].creatives, and otto_render previews. New: the previews must be
  rendered before approval; today rendering happens at launch. Effort M.

#### Calendar
- The month grid as today, plus a **List** view (today's Posts tab).
- Ad flights stay as bands. Tapping a band opens the campaign with its ads and yesterday's numbers.

#### Results
| Module | Numbers | Source | Status |
|---|---|---|---|
| Period switch | Week · Month · Last month, against the previous period of the same length. Mid-month that means "the same days last month", which also fixes the −100 % on the 1st noted in LAUNCH-READINESS. | growth.months, growth.daily | rework of existing |
| What happened | 2–3 template sentences: the result, the change, the best format or ad. On the 1st, growth.review. | growth, ads.daily | the data exists |
| Winner | The best post and the best ad of the period, each opening its detail | posts[].metrics, ad insights | partly exists |
| Main chart | One line with a metric switch: Enquiries · Reached · Spent. The previous period is dotted. A "With Otto since" marker, and the baseline before it. | growth.daily, metrics_history | exists (the baseline is P1) |
| Organic | People reached · Engagements · New followers · Link taps | posts[].metrics, metrics[], IG insights (P1) | partly exists |
| Paid | Spent (against the plan) · Enquiries or Sales · Cost per enquiry · Clicks to your site | ads.daily meta/google, yesterday and week | exists |
| Best posts | The top 3 by Otto's score (reach + 10×saves + 5×clicks), with the reason ("most saves") | posts[].metrics, otto_insights.score | exists |
| Your ads | Ads ranked by results: preview, angle · style, spend, enquiries, cost each, Live or "Paused by Otto" | Marketing API insights at level=ad | P1 |
| Campaigns (until ad level exists) | Per campaign: spend, results, cost each, status | ads.daily[].meta.campaigns | exists, unused |
| Google (Growth plan) | Spend, clicks, conversions, top search terms | ads.daily[].google | exists, unused |
| Where enquiries came from | Lead form · Website · DM · Call | leads[].source | P1 |
| Competitors this month | 1–2 lines: an offer started, how many ads they run | competitors[], ads_archive | exists / P1 |
| Footer | "Numbers from Meta, updated 07:15. Meta can take up to two days." Share or PDF of the month. | — | P1 |

**Empty states:**
- **Not connected:** the connect checklist, "made for you this week", and what will be measured.
- **Connected, nothing published yet:** the 30-day baseline ("Your last 30 days before Otto").
- **First week out:** each post's numbers as they arrive ("Numbers come in a day or two after a post"), and no percentages
  ("No earlier period yet").
- **Trial:** the paid block says the ads are ready and start with a plan.

#### Leads (CRM-lite)
| Module | Shows | Source |
|---|---|---|
| Month line | "14 enquiries · 3 new" | leads[] |
| Filter | New · Contacted · Won · All ("Not a fit" sits inside All) | leads[].status |
| Money line | "Won €2,400 · Otto + ads this month €291", shown only once at least one lead has a value | leads[].value, the plan price, ad spend |
| Row | Name or handle; a source chip (Lead form · "<ad name>" / Website form / Instagram DM / Call); time; the first line of the message; status | leads[] |
| Row actions | Call (tel:) · WhatsApp (wa.me) · E-mail (mailto:) · Mark contacted | in the browser |
| Lead sheet | Contact details; the form answers; the ad (thumbnail, angle, style); a timeline (arrived, you were told, contacted); status, value and note; a drafted first reply to copy | leads[], campaigns[], otto_copy |
| Export | CSV | — |

**The lead object (new, per brand, client-visible):**

```json
{
  "id": "…", "brand": "…",
  "source": "lead_form | website | ig_dm | fb_dm | call | manual",
  "source_ref": {"ad_id": "…", "adset_id": "…", "form_id": "…", "page_url": "…"},
  "name": "…", "email": "…", "phone": "…", "answers": {}, "message": "…",
  "created_at": "…", "notified_at": "…", "contacted_at": "…",
  "status": "new | contacted | won | lost", "value": 0, "currency": "EUR", "note": "…",
  "consent": {"text": "…", "url": "…"}
}
```

Rules for storing leads:
- **Store each lead as soon as it arrives.** Meta keeps form data for 90 days. Keeping it longer is itself a selling point
  against Leads Center.
- **Keep it out of the copy of the data inside `index.html`.** LAUNCH-READINESS already warns that every write copies all of
  `data.json` there.
- **Retention follows otto_retention.** Leads are deleted with the brand's data, with a shorter default for leads (about 12
  months) stated in the privacy policy and the DPA.

**Empty states:**
- **A plan without ads:** "Enquiries from your website and DMs arrive here", plus the website-form card and "Add paid campaigns".
- **Starter, before the first lead:** "Your ads ask people for their name and number. Every enquiry shows up here and in your
  e-mail within minutes", plus one row labelled "Sample".
- **Trial:** the same, plus "Ads start when you choose a plan".

#### Brand (account menu)
- **Your brand, as Otto read it:** logo, colours, fonts, tone lines, products and prices, customer words (scan.json,
  brand-profile.md), each with "Fix", as in onboarding step 2. This exists in onboarding but not in the app.
- **Your answers:** goal, ad budget, what customers ask, never-say words (brands[].onboarding). Editable.
- **What Otto learned:** approved and skipped posts by pillar (taste_log, moved here from Settings → Signals).
- **Competitors:** the list (add or remove), the last check, what changed, their active ads (P1).
- **Photos (P2):** upload your own; Otto uses them first. Native has this.

#### Plan & billing
- The plan and what it includes, this month's use as bars (plan_view.usage), payment method, invoices, VAT ID, and cancel.
  This is billing.html as it is.
- Show an upgrade line only where it is true ("Google Search ads and creator briefs are in Growth"). Prices other than €79
  stay hidden until Max publishes them.
- Say plainly: monthly, cancel here any time.

#### Connections and Notifications
- **Connections:** each service with its status, last sync, what it unlocks, and an action (Connect / Reconnect / How).
- **Notifications:** the approvals channel and the language (both moved from Settings); the 07:35 report on or off; new-lead
  alerts by e-mail or Telegram; the monthly review.

### 3.4 One glossary (shown on tap, used everywhere)
| Word in the app | Means | Source field |
|---|---|---|
| People reached | Accounts that saw a post or ad at least once (not views) | IG `reach`, FB media-view reach, ads `reach` |
| Engagements | Likes + comments + shares + saves | likes, comments, shares, saved |
| New followers | Followers at the end of the period minus followers at the start | IG `followers_count` / `follows_and_unfollows`, FB `page_follows` |
| Link taps | Taps on the link in your Instagram profile, plus clicks on links in Facebook posts | IG `profile_links_taps`, FB `post_clicks` |
| Enquiries | People who sent their details through an ad form or your website, or asked in a DM | Meta `lead` actions, leads[] |
| Sales | Purchases your site reported to Meta | purchase actions |
| Spent | What Meta or Google charged to your card (not Otto's fee) | spend |
| Cost per enquiry | Spent ÷ enquiries from ads | cpl |
| Won | Enquiries you marked as customers; the value is yours to fill in | leads[].status, value |

---

## 4. "Worth paying" features, ranked by value ÷ effort
**Effort:** S = up to 2 days · M = 3–7 days · L = 2+ weeks or an outside approval (App Review, Business Verification, an API
access form).
**Value** = what a small owner notices in the first two weeks (the trial) and every Monday after.

**Meta approvals gate most of P1.** Leads, Instagram messaging and the Marketing API's higher tiers all need App Review,
Business Verification and Access Verification (as a Tech Provider, about 5 days after Business Verification). Publishing and
insights need the same review. **Put `leads_retrieval` and `pages_manage_metadata` into the first App Review submission**, so
Leads is not blocked on a second review.

### P0 — before or at launch (small; mostly screens over data that already exists)
| # | Feature | Why it sells the €79 | Data | Effort |
|---|---|---|---|---|
| 1 | **"This month's work" ledger** on Today and Results: posts, stories and reels made, scheduled and out, against the plan (50 · 12 · 4); ads designed and live (20); ad budget used | The work is the product before results exist, and it is the only proof a trial gets. Native shows a posting streak and "ad pack ready". | plan_view.usage (exists), posts[], campaigns[], the matrix count | S |
| 2 | **Week-1 screens that show work, not "nothing yet":** a connect checklist with progress, "made for you this week", what will be measured, labelled samples | Trials decide in 7 days. Today a trial sees 0 · 0 · 1 and "Results start after the first published week". | exists, plus copy | S |
| 3 | **Results as a tab** (§3.3), with the winner card and every number opening its post or ad | Every competitor has this screen. Otto hides a rich growth ledger in a side card and its paid numbers in Settings. This is parity with Native's Home. | growth[], ads[].daily (campaign rows, 7-day totals, search terms), posts[].metrics — all exist | M (front end) |
| 4 | **The 07:35 sentence and a "Yesterday" strip** at the top of Today | A sentence the owner reads in 3 seconds, worded exactly as in the e-mail | otto_report.model() / summary() exposed through the API | S |
| 5 | **Show the ads:** "Your ads for November" in Review (20 previews, angle × style); approve the paid plan with the ads in view | Max's pitch is "lots of varied ads", yet the client approves "4 campaigns, ≈€600" as text and never sees an ad. Native swipes through its ads one by one. | the ads-YYYY-MM.json matrix plus otto_render previews before launch | M |
| 6 | **A Connect button that does something.** At launch: a Connect sheet with the steps (partner access in Business Manager, or book a 10-minute call) and live status. Facebook Login for Business later. | Today it is a dead end on day 1 of a 7-day trial. | connections[] (exists), plus copy. OAuth is L. | S (interim) |

### P1 — weeks 1–3
| # | Feature | Why | Data / integration | Effort |
|---|---|---|---|---|
| 7 | **Leads v1 from Meta lead forms** (§3.3) | Starter ads already optimise for leads through an on-ad form. Today the people end up in Meta's Leads Center: 90 days, no alerts. No competitor below $999 shows leads. | Page webhook `leadgen`, then GET the lead; poll `/{form_id}/leads` as a backup. Permissions: `leads_retrieval`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`, `ads_management` (+ `ads_read`, `business_management`, `pages_manage_ads`). Store immediately. Leads Access Manager must grant Otto access. | S code · L approvals |
| 8 | **An alert for every new lead** (e-mail or Telegram: the name, what they asked, tap to call) | Speed to lead decides whether an enquiry becomes a job. Leads Center sends no alert per lead. | leads[], otto_email, otto_telegram | S (after 7) |
| 9 | **Won and value → "what Otto brought":** "Otto + ads this month €291 · you marked 4 enquiries won, €2,400" | The ROI line that makes €79 obvious. The owner fills in the value; Otto invents nothing. | leads[].status / value | S (after 7) |
| 10 | **Results per ad:** each ad (angle × style) with spend, enquiries, cost each and status; a "best angle" sentence | The landing page promises numbers "ad set by ad set", and a matrix is only worth showing with its winners. Native ranks ads too. | Marketing API insights at `level=ad` (+ adset): spend, reach, inline link clicks, `actions` / `cost_per_action_type` (`lead` = the total). Default attribution is 7-day click + 1-day view; say so. | S |
| 11 | **Instagram account numbers, a 30-day baseline at connect, and a move off the retired Facebook metrics** | Before and after is the most convincing chart there is (Native marks its start day). It also fixes the reach risk in §2.3. | IG `reach`, `views`, `follows_and_unfollows`, `profile_links_taps`, `accounts_engaged`, `total_interactions`; FB `page_media_view`, `page_follows`, `page_post_engagements`; metrics_history. Up to 48 h lag. | S–M |
| 12 | **Share or PDF of the month:** the review e-mail as a signed link plus a PDF on the 1st | Owners forward it to a partner or the accountant. Native has no export; Metricool and Madgicx sell on it. | growth.review and the report HTML | S–M |
| 13 | **Website form snippet:** one script tag that turns the site's contact form into Leads and tags visits from Otto's posts and ads (UTM) | Many local service enquiries come through the website form, not the ad form | JS POST to `/otto-lead` with a key per site; a honeypot, not reCAPTCHA; no browser storage; otto_track's privacy design. The client is the controller and Otto the processor (DPA, Art. 28). Replying rests on Art. 6(1)(b)/(f); marketing opt-in is separate. About 12 months' retention. | S |
| 14 | **A better competitor card:** what changed (offers, prices, headlines) plus their active Meta ads (how many, and the longest-running, which are their winners) | Owners react to competitors more than to their own reach. Native researches competitors once; Metricool tracks only follower numbers. | otto_competitors.py (exists) plus the Ad Library API `ads_archive`: commercial ads are returned when `ad_reached_countries` is EU or UK (DSA), for one year | M |
| 15 | **A goal line:** the onboarding goal ("More leads or bookings") and a cost-per-enquiry target on Results | Turns numbers into "on track / not yet" without invented benchmarks. This is the gap the independent Native test called out (goals). | brands[].onboarding.goal (exists, unused), ads[].targets.cpl (exists) | S |
| 16 | **Conversations started, per ad** (for click-to-Messenger / Instagram / WhatsApp ads) | A first signal that DMs bring business, before the inbox exists | `onsite_conversion.messaging_conversation_started_7d` per ad from the Marketing API | S |

### P2 — later
| # | Feature | Why later | Effort |
|---|---|---|---|
| 17 | **Inbox:** Instagram and Facebook DMs and comments with drafted replies; a DM asking for a price becomes a lead (the `referral` field carries the ad_id for click-to-Messenger / Instagram ads) | Real value, but it needs `instagram_manage_messages` / `instagram_manage_comments` with Advanced Access and `pages_messaging`, a 24-hour reply window (7 days with the HUMAN_AGENT tag), and a reply surface to keep alive | M code · L approvals |
| 18 | **Google Business Profile:** reviews with drafted replies; calls, website clicks, directions, bookings and keywords | Needs an access application (the profile verified for 60+ days) and sensitive-scope verification: 2–6+ weeks. Matters most for local services. | M code · L approvals |
| 19 | **Click-to-WhatsApp enquiries in Leads** | Only through the WhatsApp Cloud API as a Tech Provider (Embedded Signup, coexistence with the WhatsApp Business app). Strong in NL. | L |
| 20 | **Send lead status back to Meta** (Conversions API for CRM), so Meta finds more "won"-type leads | Meta wants about 200 leads a month to optimise on it; most Starter clients will not reach that | M |
| 21 | **Photo library** (upload your own photos; Otto uses them first) | Native has shipped it. It matters for trust, not for the dashboard. | M |
| 22 | **Team:** invite a colleague (members[] exists) | Small owners rarely share access; cheap to add when someone asks | S |
| 23 | **Shop orders** (Shopify / WooCommerce) for sales and revenue | Only for shops; Meta purchase events cover the first months | M |

---

## 5. Wireframes (phone first; on desktop the second column of Today and Results sits on the right)
Names, numbers and businesses below are illustrative placeholders for the layout, not real data. In the product, a sample
shown to a client is labelled "Sample".

### 5.1 Today, a normal Tuesday in month 2
```
Tuesday 12 November                                   (M)
Today
Good morning. Yesterday: €18 on ads, 4 enquiries.
3 posts need you.                          [ Review 3 ]

┌─ Yesterday ─────────────────────────────────────────┐
│ 2,140         4            €18          €4.50       │
│ reached       enquiries    spent        per enquiry │
│ +12% vs avg   2 new today  within €20   7-day €5.10 │
└──────────────────────────────── See results › ──────┘

New leads                                        See all 6
 ● A. de Vries · Lead form · "Spring kitchen" ad · 2 h
   "Need a quote for a kitchen before Christmas"   [Call]
 ● Instagram DM · @handle · 5 h                    [Reply]

Needs you                                        See all 3
 [thumb] "Three things to check before…" · IG · Today 18:00
         Change   Skip   Approve

Up next
 [thumb] Reel · "4 days, one kitchen" · Wed 09:00

This month's work
 Posts        ████████████░░░░░░  31 of 50
 Stories      ██████░░░░░░░░░░░░   4 of 12
 Reels        █████████░░░░░░░░░   2 of 4
 Ads          20 live (4 angles × 5 styles) · €212 of €600

Suggestion
 Double down on "Before / after" next week
 It brought 9 of your last 12 enquiries.      Not now  [Do it]
```

### 5.2 Results, mid-month with data
```
Results                       [ Week | Month | Last month ]
November so far, against the same days in October

What happened
 You got 14 enquiries at €5.10 each, 6 more than by this
 point in October. Reels reached the most new people.
 The "Before / after" ads brought 9 of the 14.

 Winner  [reel] "4 days, one kitchen" · 6,200 reached · 41 saves  ›

 Enquiries ▾        ┌──────────────────────────────────┐
                    │ ¦     ╱‾‾╲      ╱‾‾‾‾             │  — Nov
                    │ ¦____╱    ╲____╱     - - - Oct    │
                    └─¦────────────────────────────────┘
                With Otto since 3 Oct            30 Nov

 Organic                             Paid
 18,400 reached       +22%           €212 spent        of €600 planned
 1,130 engagements    +9%            14 enquiries      +75%
 +86 followers        +31            €5.10 per enquiry 18% lower
 140 link taps        +40%           610 clicks to your site

Best posts                                        See all
 1 [reel]     "4 days, one kitchen" · 6,200 reached · 41 saves
 2 [carousel] "3 signs your boiler…" · 2,900 reached · most saves
 3 [post]     "Meet our tiler" · 1,700 reached · most comments

Your ads                                          See all 20
 1 [img] Before / after · Photo     9 enquiries · €3.80 each   Live
 2 [vid] Price promise · Video      3 enquiries · €7.10 each   Live
 3 [img] Reviews · Quote card       1 enquiry   · €16.20       Paused by Otto
 Otto moves budget to the ads that bring enquiries at the lowest cost.

Where enquiries came from
 Ad lead form 11 · Website form 2 · Instagram DM 1

Competitors this month
 Competitor A started a "20% off" offer · runs 12 ads    Brand ›

[ Share this month ]
Numbers from Meta, updated 07:15. Meta can take up to two days.
```

### 5.3 Results in week 1 (trial, Instagram not connected yet)
```
Results
Your numbers start when Instagram and Facebook are connected.

Connect to start measuring                       1 of 3 done
 ✓ Website read · brand profile ready                 [See]
 ○ Instagram + Facebook — so Otto can publish and measure   [Connect]
 ○ Meta ad account — so your 20 ads can run after the trial [How]

Made for you this week
 14 posts · 3 stories · 1 reel · 20 ads designed      [See them]

What you'll see here
 People reached, new followers, link taps, enquiries and what
 each enquiry cost. The same numbers come every morning at 07:35.

(After connecting, before the first post)
 Your last 30 days before Otto
 3 posts · 1,240 reached · +12 followers · 18 link taps
 Every week is compared with this.
```

### 5.4 Leads
```
Leads                                   November · 14 enquiries
[ New 3 | Contacted 6 | Won 4 | All ]

 Won €2,400 · Otto + ads this month €291
 You mark leads as won; the value is yours to fill in.

 ● A. de Vries                                      2 h ago
   Lead form · "Spring kitchen" ad
   "Need a quote for a kitchen before Christmas"
   [Call]  [WhatsApp]  [E-mail]          Mark contacted ›
 ● M. O'Neill                                       Yesterday
   Website form · /contact
   "Do you do bathrooms in Utrecht?"
   [Call]  [E-mail]
 ○ @handle                                          Mon
   Instagram DM · replied to your reel
                                               Export CSV
```

Lead sheet (opened from a row):
```
A. de Vries                                    New  ▾
 06 ·· ·· ·· ·· · name@example.nl
 [Call] [WhatsApp] [E-mail]
 From    Lead form on "Spring kitchen" ad (Before / after · Photo)
 Asked   Kitchen · before Christmas · budget €10–15k
 When    Tue 12 Nov 08:14 · you were told at 08:14 by e-mail
 Status  New → Contacted → Won (value €____) / Not a fit
 Note    ______________________
 Reply draft, in your voice   "Hi, thanks for…"        [Copy]
```

---

## 6. What Otto should NOT build
| Don't build | Why |
|---|---|
| **Report builders, custom dashboards, white-label PDFs** | Agency and enterprise features (Metricool Custom, Madgicx white-label). A small owner wants one page that is already right. |
| **Separate analytics tabs per network** (Instagram, Facebook, Google) | Keep one Results view; the network is a chip on a row. |
| **Impressions, views, frequency, CPM, CTR or ROAS on the main screen** | Reach, enquiries, spend and cost per enquiry are enough. The rest goes one tap deep, or nowhere. ROAS only for shops with purchase tracking, behind a toggle as Native does. |
| **Best-time heatmaps, hashtag analytics, follower demographics, audience maps down to the city** | Otto picks the slot, the words and the audience. Showing those knobs invites the owner to do Otto's job, and heatmap accuracy is a known complaint (Metricool). |
| **Social listening, sentiment scores, share-of-voice percentages** | Expensive, noisy, not acted on. The analytics mockup's "attention share 61% ▲3.1" is the example to drop. |
| **A full CRM** (pipelines with many stages, deals, tasks, sequences, contact enrichment, lead scoring) | Four statuses, a value and a note are enough. Owners who outgrow them get a CSV export, later a Zapier hook. Podium and Birdeye charge €300–600 a month on contracts for the big version. |
| **Industry benchmarks without real data** ("you beat 72% of salons") | Compare the client with their own past. Only Buffer has an in-app benchmark, and only for LinkedIn. |
| **An "ask your numbers" AI chat**, for now | Native and Madgicx have one. The "what happened" sentences answer the question before it is asked; revisit after launch. |
| **Competitor follower counts and engagement-rate tables** | Vanity. Offers, prices and the ads they keep running are what an owner reacts to. |
| **Credits or metered analytics** | Holo, Blaze and Predis draw complaints about credits; the €79 should feel all-inclusive. |
| **Gamification** (badges, scores) | Native's posting streak is about as far as it should go: a fact, not a game. |

---

## 7. Integration notes (from the feasibility research, Graph API v26.0)
| Integration | What it gives | Permissions and approval | Gotchas | Effort |
|---|---|---|---|---|
| **Meta Lead Ads** | Each lead in real time: name, contact details, answers, ad_id, form_id | Webhook `leadgen` on the Page. `leads_retrieval`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`, `ads_management` (+ `ads_read`, `business_management`, `pages_manage_ads`). App Review, Business Verification, Access Verification (Tech Provider). | Form data lives 90 days at Meta, so store it on arrival. Poll as a backup. The client's Leads Access Manager must include Otto. The privacy-policy URL on the form must be the client's. | S code · L approvals |
| **Marketing API ad insights** | Per ad: spend, reach, frequency, CPM, CTR, inline link clicks, `actions` and `cost_per_action_type` | `ads_read` / `ads_management`. Limited and Full access tiers (Full = 500 calls in 15 days with <15% errors). | `lead` is the total; `onsite_conversion.lead_grouped` (forms) and `offsite_conversion.fb_pixel_lead` (website) are parts of it, never added to it. Default attribution 7-day click + 1-day view. | S |
| **Organic insights** | IG: `reach`, `views`, `follows_and_unfollows`, `profile_links_taps`, `accounts_engaged`, `total_interactions`. FB: `page_media_view`, `page_follows`, `page_post_engagements`. | The same app as publishing | IG `impressions` was removed in April 2025, and `website_clicks` / `profile_views` in January 2025 (use UTM links and Otto's own tracking). FB `page_impressions*` and `page_fans` were retired on 15.11.2025. Up to 48 h lag. | S–M |
| **Instagram DMs and comments; Messenger** | Message and comment webhooks; replies; the `referral` field with ad_id for click-to-Messenger / Instagram ads | `instagram_manage_messages` / `instagram_manage_comments` (Advanced Access), `pages_messaging` | A 24-hour window (7 days with HUMAN_AGENT) | M each |
| **Click-to-WhatsApp** | A WhatsApp conversation tied to its ad | WhatsApp Cloud API as a Tech Provider, Embedded Signup, coexistence with the WhatsApp Business app | Fallback: the number of conversations started per ad, from the Marketing API (S) | L |
| **Conversions API for CRM** | Lead stages sent back to Meta | Pixel / dataset access | Needs about 200 leads a month to help optimisation | M |
| **Google Business Profile API** | Reviews (list, reply, Pub/Sub notifications); performance: calls, website clicks, directions, bookings, search keywords | An access application (profile verified for 60+ days) and sensitive-scope verification | 2–6+ weeks of approvals | M code · L approvals |
| **Website form snippet** | Contact-form enquiries in Leads; visits from Otto's links | A key per site; POST to an Otto endpoint | Honeypot, not reCAPTCHA; no browser storage. The client is the controller and Otto the processor (DPA, Art. 28). Replying rests on Art. 6(1)(b)/(f); a marketing opt-in is separate. About 12 months' retention. | S |
| **Meta Ad Library API** (competitor ads) | Competitors' active ads, start dates, creatives, EU reach | `ads_archive` with an access token; identity confirmation for API access | Commercial (non-political) ads are returned only for EU or UK delivery, for one year. That suits NL and IE. | M |

---

## Sources
Accessed 02.10.2026 unless a date is given.

**Otto (local):**
- Pages: `platform/index.html`, `analytics.html`, `ads.html`, `approve.html`, `onboarding.html`, `landing.html`
- Engine: `otto_api.py` (client_view), `otto_insights.py`, `otto_growth.py`, `otto_ads.py`, `otto_report.py`, `otto_i18n.py`,
  `otto_watch.py`, `otto_track.py`, `otto_competitors.py`, `otto_admin.py` (leads.json), `otto_retention.py`
- Config: `plans.json`, `STRUCTURE.md`
- Docs: `docs/UNIT-ECONOMICS.md`, `docs/LAUNCH-READINESS.md`
- The `otto-walk` walkthrough (`~/.otto-walk/`)

**Native:**
- native.no: changelog (157 entries, 16.03–24.09.2026), guides, blog, "how it works" mockup
- trustpilot.com/review/native.no
- hanspetter.info (18.03.2026)
- research/COMPETITORS-2026-09.md

**AI marketing and social tools:**
- Holo: tryholo.ai, tryholo.ai/pricing, trustpilot.com/review/tryholo.ai, bloggerpilot.com/en/holo-im-praxistest/
  (24.10.2025)
- Blaze: blaze.ai/pricing, blaze.ai/blaze-autopilot, help.blaze.ai/en/articles/9535151-getting-started-with-blaze (26.05.2026),
  help.blaze.ai/en/articles/12313537 (22.07.2026), trustpilot.com/review/blaze.ai,
  work-management.org/marketing/blaze-ai-review/ (18.05.2026)
- Predis: predis.ai/pricing/, predis.ai/llm-info/, predis.ai/social-media-competitor-analysis/,
  socialrails.com/blog/predis-review (01.01.2026), trustpilot.com/review/predis.ai
- Ocoya: ocoya.com/pricing, ocoya.com/features/engage, firebearstudio.com/blog/ocoya-review.html (26.02.2026),
  capterra.com/p/232714/Ocoya/
- Metricool: metricool.com/pricing/, help.metricool.com/summary-metrics-6zo4n, help.metricool.com/analytics-028fw,
  help.metricool.com/how-to-add-competitors-in-metricool-sgjjg, help.metricool.com/how-to-generate-reports-szc5k (snippet),
  help.metricool.com/what-is-campaign-dashboards-334yd (snippet), capterra.com/p/203702/Metricool/,
  trustpilot.com/review/metricool.com
- Later: later.com/pricing/, later.com/social-media-analytics/, later.com/blog/social-analytics-dashboard-leaders-dont-ignore/
  (21.01.2026), help.later.com articles on analytics by plan, custom analytics, link-in-bio analytics, listening and
  benchmarking, and the social inbox (403, read from search snippets), capterra.com/p/152254/Later/reviews/,
  trustpilot.com/review/later.com
- Buffer: buffer.com/pricing, support.buffer.com/en-us/articles/using-insights-in-buffer-x4gLauQU5a,
  support.buffer.com/en-us/articles/getting-started-with-buffers-analytics-features-UVAe3hwLD8,
  napoleoncat.com/blog/buffer-reviews-on-reddit/ (27.08.2026), capterra.com/p/143492/Buffer/

**Ads analytics, SMB CRM and Meta's free tools:**
- Products and pricing pages, help centres and reviews of Madgicx, AdCreative.ai, Owner.com, Podium, Birdeye and
  Hootsuite / Sprout
- Meta Business Suite Insights and Leads Center help pages
- Meta Business Agent announcement (03.06.2026)

**Meta and Google platform docs:**
- Meta Graph API v26.0 docs: Webhooks for Pages (`leadgen`), Lead Ads retrieval, App Review, Business Verification and Access
  Verification, Marketing API insights and access tiers, Instagram Platform messaging and comments, Messenger Platform,
  WhatsApp Cloud API, Conversions API for CRM
- Instagram user insights: developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights/
- Facebook Page insights deprecations: developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/ and the Pages
  API changelog; ppc.land, "Meta deprecates additional Page Insights API metrics from November 15"
- Instagram metric deprecations of January 2025: docs.emplifi.io, "Instagram Media and Profile Insights Metrics Deprecation
  (January, 2025)"
- Meta Ad Library API: developers.facebook.com/docs/graph-api/reference/ads_archive/;
  adlibrary.com/posts/eu-dsa-ad-repositories-developers
- Google Business Profile APIs: developers.google.com/my-business (access, reviews, notifications, performance)
