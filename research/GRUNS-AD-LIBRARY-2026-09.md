# Grüns Meta Ad Library scan: angles, styles and the Otto creative standard

Date: 2026-09-29. Author: Claude Code (Otto ad research). Scope: every active Grüns ad in the US Meta Ad Library (Facebook page 107585658730958). This is competitor research only. Do not copy Grüns creative into Otto templates.

Files:
- `research/gruns-ads/taxonomy.json` holds every scanned ad with its angle, style, hooks, landing page, and creative group. It also has the angle and style counts, the angle x style matrix, and the family definitions.
- `research/gruns-ads/style-*.jpg` are 44 contact sheets: one per style with 3 or more creatives, plus 2 sheets for rare formats. Each has up to 12 thumbnails, labelled with the library id and angle.

## TL;DR

- **~830 active US ads. We scraped 823 cards (99%).** They use **674 unique creatives**, **75 headlines** and **63 landing pages**. Every card says "This ad has multiple versions", so each ad hides more variations than the Library shows.
- **We classified 32 angles in 6 families and 59 execution styles in 11 families.** Every creative was looked at: the image, or the poster frame plus two mid-video frames.
- **Video is 63% of unique creatives. UGC video is 45%**: talking head, text-over-video POV, and faceless voiceover b-roll. Static work spreads across 30+ formats.
- **GLP-1 is the biggest angle** (135 creatives, 20%, in 35 styles). Next come generic "all-in-one nutrition" creator testimonials (76) and gut/poop humor (71). Then weight/metabolism, women's life stages, price, fiber, limited flavors and "vs greens powder".
- **The core pattern: every angle runs in many styles.** The 18 angles with 10+ creatives each use a median of 9.5 styles and 6.5 of the 11 style families. The top 3 angles each use 8–9 families.
- **One headline carries many visuals.** "Grüns is too expensive — here's 61% off to prove otherwise" runs on 92 ads and 80 different creatives. "Don't Pay Full Price..." and "Trusted by 1M+" each sit on 50+ creatives in 20 styles. Grüns tests visuals, not headlines.
- **Refresh is brutal.** Nothing active started before 27 May 2026, so everything is under 4 months old. 58% of ads started in September. 287 ads launched on a single day (24 Sep).
- **The edge lives in the creative, not the copy.** In the visible primary text of the 823 cards, "poop" and "sorry" appear 0 times. The creatives say it constantly: 71 gut/poop creatives, plus apology letters and "F*ck your greens powder". (The API finds 41 "poop" and 23 "sorry" matches; these are probably hidden versions or fuzzy matches.)
- **Otto standard (section f):** at launch, 6 angles (one per angle family) x 6 styles each = 36 unique creatives. Each angle must cover 4+ style families, and each angle gets its own landing page. Then add 2 new creatives per angle every week, and one new angle every month.

## Method

1. Headless Chrome (puppeteer-core) loaded the public Ad Library page: `active_status=active, country=US, view_all_page_id=107585658730958`. It scrolled until growth stopped, at 823 cards. Nothing was clicked and no login was used.
2. For each card we captured: library id, start date, primary text, headline, CTA, landing-page URL, page name (partnership ads show the creator's page), image or video poster, "N ads use this creative and text", and the video URL.
3. We downloaded all 823 images and posters. For 432 video assets, ffmpeg pulled two extra frames (at about 35% and 70% of the runtime).
4. Near-duplicates were merged with a 256-bit perceptual hash plus the video asset id. That left 674 unique creatives.
5. We viewed all 674 on 31 labelled contact sheets and assigned each one a primary angle and a primary style by sight. "Angle" means the message the creative itself carries (on-image or on-screen text first, copy second). "Style" means the execution format. Hook types (apology, POV, reverse psychology and so on) were tagged from the classification notes.
6. The Meta Ad Library API (`ads_library_search`) gave copy-term counts across the whole active page.

Raw downloads and working files are kept outside the repo, in the session scratchpad (`adlib-scan/`).

## a) Totals

| Metric | Value |
|---|---|
| Active US ads (Ad Library estimate) | ~830 |
| Cards scraped (sample) | 823 (99% of active) |
| Ad objects behind those cards | 1,040. 621 cards are single; 187 cards are "2 ads use this creative and text"; 15 are "3 ads" |
| Unique creatives (after visual dedupe) | 674 (1.22 cards per creative) |
| Library media filter | video ~550 + image-with-text ~280 = ~830. The plain "image" filter returned no count |
| Sample media split (cards) | 478 video (58%) / 345 image (42%) |
| Unique creatives by media | 426 video (63%) / 248 image (37%) |
| Carousels visible | 0. All cards are flexible "multiple versions" ads showing one version |
| CTA | "Shop Now" on 823 of 823 |
| Distinct headlines | 75 |
| Distinct landing pages | 63 (for example /pages/glp-gwp-listicle, /pages/perimenopause, /pages/first-order-minions) |
| Partnership ads (run from a creator or celebrity page) | 137 ads (17%) from 65 pages. Examples: Jennifer Love Hewitt, Jenna Bush Hager, Julianne Hough, Jonathan Bennett, Vivian Tu (Your Rich BFF), Fat Perez |
| Sister brands on the same page | Nütrops (mushroom focus gummies) and Immün (immune gummies), 8 ads |
| Oldest active start date | 27 May 2026. Nothing is older than about 4 months |
| Angles / styles found | 32 angles (6 families), 59 styles (11 families) |

**Variants per concept**

- **One creative, many ads.** 70 creatives run as 2 or more cards. The biggest is the birthday price card ("$66.65 → $29.99, it's our birthday"): 1 creative, 72 cards, 143 ad objects. It is the most duplicated asset on the page.
- **One headline, many creatives:**

| Headline (ad link title) | Ads | Unique creatives | Styles |
|---|---|---|---|
| "Grüns is too expensive" — here's 61% off to prove otherwise | 92 | 80 | 12 (40 of the ads are partnership ads) |
| We're Lowering Our Prices | 80 | 9 | 4 |
| Don't Pay Full Price. You Literally Don't Have To. (61% off inside) | 66 | 54 | 20 |
| Trusted by 1M+ — Take 61% OFF | 56 | 52 | 20 |
| Nourish Your Gut with Grüns | 46 | 41 | 20 |
| Tastes Exactly Like Summer | 42 | 31 | 11 |
| Fuel the Grind on GLP-1 | 23 | 23 | 14 |
| Struggling to Get Enough Fiber? | 22 | 21 | 12 |
| Your Wellness Partner After 40 | 20 | 20 | 12 |

- **API copy-term counts** (estimated number of active US ads whose text matches the term; the index may include hidden versions and fuzzy matches): energy 531, fiber 527, 61% 452, gifts 435, sugar 339, taste 316, GLP-1 154, expensive 111, weight 72, hair 65, "Trusted by 1M" 62, poop 41, skin 35, cravings 35, kids 31, pills 30, greens powder 26, sorry 23, husband 19, muscle 17, Minions 15, bloating 14, Ozempic 3, birthday 2, Shrek 0. There are no Shrek ads active in the US right now. The licensed collab running now is Minions, and the co-branded Popsicle "Firecracker" flavor appears on price and flavor statics.

## b) Angles

32 angles, ranked by unique creatives. "Styles used" means distinct execution styles within the angle.

| Angle | Family | Unique creatives | Ads | Img / vid | Styles used | Oldest start | Example ad headline | Example on-creative hook |
|---|---|---|---|---|---|---|---|---|
| glp1 (GLP-1 users: constipation, hair loss, muscle, teeth, skin, coming off) | Audience | 135 | 152 | 68 / 67 | 35 | 2026-05-29 | Trusted by 1M+ — Take 61% OFF; Support Muscle While You Lose Weight | "Can't poop on GLP-1?"; "GLP-1 guys: lose the weight, not your hair" |
| all_in_one_nutrition (21 vitamins, 60 ingredients, fills gaps) | Experience | 76 | 87 | 3 / 73 | 14 | 2026-05-29 | "Grüns is too expensive" — here's 61% off to prove otherwise | creator testimonial "everything is in one"; "21 vitamins the wellness industry hates" |
| gut_poop (regularity, bloat, poop humor, travel digestion) | Problem | 71 | 78 | 37 / 34 | 24 | 2026-06-01 | Nourish Your Gut with Grüns; Fix the Hot Girl Tummy | "Hello, daily poops (finally)"; "Bye bye 2pm bloat" |
| womens_life_stage (perimenopause, menopause, postpartum, PCOS, after 40) | Audience | 33 | 33 | 19 / 14 | 14 | 2026-06-01 | Your Wellness Partner After 40; Your Postpartum Nutrition, Simplified | "Midlife night sweats hit hard"; postpartum iceberg |
| weight_metabolism (calorie deficit, cravings, cutting) | Problem | 33 | 33 | 15 / 18 | 17 | 2026-05-29 | Perfect Supplement for Weight Loss; Most men focus on calories—but miss this. | "Shedding pounds? Don't shed your nutrition" |
| price_offer (price drop, % off, gifts, sale) | Offer | 31 | 112 | 14 / 17 | 9 | 2026-08-11 | We're Lowering Our Prices; Don't Pay Full Price... | birthday card "$66.65 → $29.99" |
| fiber (fiber gap, fibermaxxing, broccoli equivalents) | Problem | 29 | 31 | 7 / 22 | 16 | 2026-05-29 | Struggling to Get Enough Fiber?; Most Men Don't Get Enough Fiber | "Fibermaxxing is the new proteinmaxxing"; "Your dad was right about fiber" |
| flavors_limited (Raspberry Lemonade return, pick your flavor, scarcity) | Experience | 28 | 38 | 11 / 17 | 9 | 2026-08-20 | Tastes Exactly Like Summer | "Back just for the summer"; "Whoever brought this flavor back deserves a raise" |
| vs_greens_powder (vs Bloom/AG1-type powders: mess, taste) | Enemy | 27 | 29 | 9 / 18 | 10 | 2026-06-01 | Ditch the Greens, Go with Grüns; All Gummies, No Mess | "F*ck your greens powder"; "Tired of eating grass?" |
| hair_skin_collagen (hair thinning, skin, collagen co-factors) | Problem | 21 | 27 | 4 / 17 | 11 | 2026-06-01 | The Truth About Collagen; Nutrition for Healthy Hair | "My top 5 horror movies, hair loss edition" |
| taste (tastes like candy or fruit snacks) | Experience | 20 | 22 | 4 / 16 | 8 | 2026-05-29 | Healthy Has Never Tasted So Good | "This is a huge bag of gummies"; "Good taste is not bad for you" |
| fertility_ttc (male and female fertility, preconception) | Audience | 18 | 19 | 6 / 12 | 11 | 2026-06-01 | A Simple Habit for the TTC Journey; Trying to Conceive? Nutrition Matters Too | "Don't ghost your balls. They need vitamins too." |
| men (reluctant husband, dads, men's energy) | Audience | 17 | 17 | 5 / 12 | 9 | 2026-06-01 | For the Guy Who Won't Take Vitamins; He Asked What Day It Was. I Handed Him a Gummy. | "Your husband's new favorite vitamin"; "We want 5 men who realized 'I'm just tired' isn't a personality" |
| collab_licensed (Minions limited edition) | Culture | 15 | 15 | 0 / 15 | 5 | 2026-08-06 | Daily Nutrition. Maximum Minion Energy. | creators revealing the Minions pack; creator dressed as a Minion |
| gut_health (microbiome, gut-brain, prebiotics) | Problem | 14 | 14 | 5 / 9 | 8 | 2026-06-01 | Nourish Your Gut with Grüns | "Your gut talks to your brain 24/7"; founder gut-score selfie |
| vs_other_supplements (pill stacks, abandoned vitamin cabinet) | Enemy | 14 | 15 | 5 / 9 | 9 | 2026-06-01 | Wellness You'll Actually Want | "You probably don't need 10 different supplements" |
| gamified_offer (flip to win, mystery flavor, slot machine, discount stunts) | Offer | 14 | 18 | 7 / 7 | 3 | 2026-09-23 | Don't Pay Full Price... | "Click to unlock the flavor"; "Every gummy he catches = 10% off for you" |
| convenience (grab and go, travel, purse) | Experience | 12 | 13 | 1 / 11 | 5 | 2026-06-18 | Nutrition in Your Bag; My Perfect 10 For Convenience | "Greens that go with you" |
| science_methylation (MTHFR, methylated B9/B12) | Problem | 9 | 9 | 5 / 4 | 7 | 2026-06-01 | Methylated Nutrients, Better Absorption | "I have the MTHFR gene mutation and B vitamins don't work for me" |
| energy (tired, coffee doesn't fix it) | Problem | 7 | 7 | 3 / 4 | 5 | 2026-06-12 | Fuel Your Health | "4 coffees. Still useless." vs "Same man. Actually fueled." |
| gummies_work (destigmatize the gummy, clinically tested) | Experience | 7 | 9 | 1 / 6 | 7 | 2026-06-03 | Gummies That Actually Work | "Yes, gummies work."; lighter test "pectin, not gelatin" |
| hate_veggies (picky eaters, "I don't eat vegetables") | Enemy | 7 | 7 | 0 / 7 | 3 | 2026-06-29 | (creator videos) | "Practicing for my Netflix documentary when someone asks how I get my vitamins" |
| kids_family (kids pack, family greens) | Audience | 6 | 6 | 2 / 4 | 3 | 2026-07-08 | Tastes Exactly Like Summer | "Family greens" kids + adult pack |
| simple_routine (consistency, one habit) | Experience | 6 | 6 | 2 / 4 | 5 | 2026-09-24 | Don't Pay Full Price... | "You're not inconsistent. Your routine is too complicated." |
| sister_brands (Nütrops focus, Immün immune) | Culture | 6 | 8 | 5 / 1 | 4 | 2026-05-27 | Achieve Clear Focus with Nütrops; 13-in-1 daily immune support. | "Adderall? Nah, mushrooms" |
| vs_other_gummies (copycats, candy gummies, Lisa Rinna jab) | Enemy | 5 | 5 | 4 / 1 | 3 | 2026-09-24 | Healthy Can Taste Good | "Copy cats"; "Sorry, other greens gummies" |
| fitness_athletes (runners, marathon, training) | Audience | 3 | 3 | 1 / 2 | 3 | 2026-09-24 | Save 61% OFF + FREE shipping (runners LP) | "Training for a marathon? Nutrition first" |
| social_proof (hype, TikTok Shop #1, survey stats) | Offer | 3 | 3 | 1 / 2 | 2 | 2026-06-29 | Save 52% OFF + FREE shipping | "Is Grüns worth the hype?"; "#1 product from TikTok Shop that I expected to hate" |
| guarantee (money-back) | Offer | 2 | 2 | 2 / 0 | 1 | 2026-09-28 | We're Lowering Our Prices | "Love them, or your money back" |
| collab_partner (Ladder strength app bundle) | Culture | 2 | 2 | 1 / 1 | 2 | 2026-09-28 | 30 Days Of Ladder, Free | "Fueled & strong" |
| brand_entertainment (pure brand fun, no product claim) | Culture | 2 | 2 | 0 / 2 | 2 | 2026-09-27 | Don't Pay Full Price... | "Day 1 of turning my co-workers into the Grüns logo" |
| results_timeline (what happens in 3 days / 2 weeks / 30 days) | Problem | 1 | 1 | 1 / 0 | 1 | 2026-08-20 | Tastes Exactly Like Summer | "Within 3 days... within 30 days" |

**Angle families** (unique creatives):

| Family | Unique creatives | Share |
|---|---|---|
| Audience / life stage | 212 | 31% |
| Problem / benefit | 185 | 27% |
| Product experience | 149 | 22% |
| Enemy / comparison | 53 | 8% |
| Offer / risk reversal | 50 | 7% (but 135 ads, 16%, because offers are re-used heavily) |
| Culture / partnerships | 25 | 4% |

**Inside GLP-1, the biggest angle:** nutrient gaps / general 57, constipation / poop 35, hair loss 20, muscle loss 12, teeth / oral 6, coming off GLP-1 4, skin 1. Grüns splits one audience into 6 problem sub-angles. Most have their own landing page: /glp-muscle-support-gwp, /nutrition-support-hair-loss, /nutrition-support-teeth, /post-glp-1.

**Offer is a layer as well as an angle.** Most statics in every angle carry an offer badge ("Up to 61% off + free gifts", "$29.99 your first order", "30-day money-back guarantee"). Only 45 creatives lead with the offer as their message.

## c) Styles / formats

59 execution styles in 11 families. Share = share of the 674 unique creatives. The contact sheet for each style is in `research/gruns-ads/`. Styles with fewer than 3 creatives are on `style-rare-formats-1.jpg` and `-2.jpg`.

**Style families** (unique creatives):

| Style family | Unique creatives | Share |
|---|---|---|
| UGC video | 305 | 45% |
| Static product | 87 | 13% |
| Static humor / editorial | 52 | 8% |
| Animated / produced video | 42 | 6% |
| Entertainment video | 37 | 5% |
| Static comparison | 31 | 5% |
| Static native screenshot | 29 | 4% |
| Static people photo | 27 | 4% |
| Static proof | 26 | 4% |
| Authority video | 26 | 4% |
| Talent | 12 | 2% |

| Style | Family | Unique creatives | Share | Ads | Image / video | Main angles paired | Example library ids | Contact sheet |
|---|---|---|---|---|---|---|---|---|
| ugc_talking_head | UGC video | 169 | 25.1% | 186 | 0 / 169 | all_in_one_nutrition (52), gut_poop (11), flavors_limited (11) | 1376579607909404, 2117015462239746 | style-ugc-talking-head.jpg |
| text_overlay_pov | UGC video | 53 | 7.9% | 55 | 0 / 53 | glp1 (18), gut_poop (6), fertility_ttc (5) | 4526636784277878, 4719067304987817 | style-text-overlay-pov.jpg |
| ugc_voiceover_broll | UGC video | 41 | 6.1% | 43 | 0 / 41 | glp1 (9), gut_poop (4), all_in_one_nutrition (4) | 1616827846768858, 2152014045718263 | style-ugc-voiceover-broll.jpg |
| day_in_the_life | UGC video | 12 | 1.8% | 14 | 0 / 12 | men (3), glp1 (3), flavors_limited (2) | 2312257592869502, 27503944615878247 | style-day-in-the-life.jpg |
| ugc_unboxing | UGC video | 9 | 1.3% | 10 | 0 / 9 | taste (4), all_in_one_nutrition (2), glp1 (2) | 1491833222705514, 774562878983332 | style-ugc-unboxing.jpg |
| listicle_video | UGC video | 9 | 1.3% | 10 | 0 / 9 | glp1 (4), weight_metabolism (2), gut_poop (1) | 1675302793620157, 933943322694671 | style-listicle-video.jpg |
| comment_reply_video | UGC video | 7 | 1.0% | 10 | 0 / 7 | collab_licensed (2), flavors_limited (2), glp1 (1) | 823358524132646, 1059858523110805 | style-comment-reply-video.jpg |
| ugc_mashup | UGC video | 3 | 0.4% | 3 | 0 / 3 | all_in_one_nutrition (1), glp1 (1), flavors_limited (1) | 3379161805588823, 2080832052501248 | style-ugc-mashup.jpg |
| review_montage_video | UGC video | 2 | 0.3% | 3 | 0 / 2 | gut_poop (2) | 1108637442119185, 3632389316913006 | style-rare-formats-2.jpg |
| expert_talking_head | Authority video | 10 | 1.5% | 13 | 0 / 10 | glp1 (3), collab_licensed (2), fertility_ttc (2) | 935112358972602, 1689526158858504 | style-expert-talking-head.jpg |
| street_interview | Authority video | 5 | 0.7% | 7 | 0 / 5 | all_in_one_nutrition (2), science_methylation (1), gummies_work (1) | 1387063406873302, 1018754604043534 | style-street-interview.jpg |
| educational_explainer | Authority video | 3 | 0.4% | 5 | 0 / 3 | hair_skin_collagen (3) | 832095849705047, 4252343115080655 | style-educational-explainer.jpg |
| product_demo | Authority video | 3 | 0.4% | 3 | 0 / 3 | gummies_work (1), fiber (1), vs_other_supplements (1) | 2251802288889628, 1640557607762598 | style-product-demo.jpg |
| founder | Authority video | 2 | 0.3% | 2 | 1 / 1 | gut_health (1), fiber (1) | 1844411100297040, 2017627532275372 | style-rare-formats-1.jpg |
| green_screen | Authority video | 2 | 0.3% | 2 | 0 / 2 | fiber (2) | 2239195223300626, 1365091365611953 | style-rare-formats-1.jpg |
| podcast_clip | Authority video | 1 | 0.1% | 1 | 0 / 1 | all_in_one_nutrition (1) | 977197525303756 | style-rare-formats-2.jpg |
| skit | Entertainment video | 12 | 1.8% | 15 | 0 / 12 | price_offer (5), vs_greens_powder (1), hate_veggies (1) | 1978697579486760, 1564732381579747 | style-skit.jpg |
| stunt_challenge | Entertainment video | 9 | 1.3% | 11 | 0 / 9 | gamified_offer (7), price_offer (2) | 1064324036358416, 1110698475238340 | style-stunt-challenge.jpg |
| couple_skit | Entertainment video | 6 | 0.9% | 6 | 0 / 6 | men (3), vs_greens_powder (2), gummies_work (1) | 2348506085967904, 1377567504403168 | style-couple-skit.jpg |
| meme_edit_video | Entertainment video | 5 | 0.7% | 5 | 0 / 5 | taste (1), brand_entertainment (1), weight_metabolism (1) | 1054689990708224, 2035484020809973 | style-meme-edit-video.jpg |
| behind_the_scenes | Entertainment video | 4 | 0.6% | 6 | 0 / 4 | price_offer (3), fiber (1) | 2289481358552509, 2212759519297028 | style-behind-the-scenes.jpg |
| mascot_costume | Entertainment video | 1 | 0.1% | 1 | 0 / 1 | all_in_one_nutrition (1) | 1757918965476707 | style-rare-formats-1.jpg |
| animated_character | Animated / produced video | 25 | 3.7% | 26 | 0 / 25 | glp1 (9), gut_poop (6), hair_skin_collagen (4) | 1374341107436169, 2455281881958294 | style-animated-character.jpg |
| motion_graphics | Animated / produced video | 8 | 1.2% | 8 | 0 / 8 | glp1 (3), fiber (1), gut_poop (1) | 1300143715069268, 883050361474887 | style-motion-graphics.jpg |
| produced_brand_video | Animated / produced video | 8 | 1.2% | 8 | 0 / 8 | fiber (2), men (2), glp1 (2) | 1095827669597435, 1141768575687408 | style-produced-brand-video.jpg |
| cgi_medical_animation | Animated / produced video | 1 | 0.1% | 1 | 0 / 1 | glp1 (1) | 28137513859283960 | style-rare-formats-1.jpg |
| creator_niche_integration | Talent (celebrity / niche creator) | 7 | 1.0% | 10 | 0 / 7 | all_in_one_nutrition (6), fiber (1) | 3543884372441196, 1800831691043413 | style-creator-niche-integration.jpg |
| celebrity_lifestyle | Talent (celebrity / niche creator) | 3 | 0.4% | 3 | 0 / 3 | convenience (3) | 2107386440150008, 4085019341789275 | style-celebrity-lifestyle.jpg |
| newsjack_celebrity | Talent (celebrity / niche creator) | 2 | 0.3% | 2 | 1 / 1 | vs_other_gummies (2) | 1045246315168682, 2342873969855411 | style-rare-formats-1.jpg |
| product_hero | Static product | 29 | 4.3% | 29 | 29 / 0 | glp1 (6), flavors_limited (5), gut_poop (4) | 1782250339468768, 1107802595001348 | style-product-hero.jpg |
| ingredient_callout | Static product | 24 | 3.6% | 25 | 24 / 0 | glp1 (6), weight_metabolism (3), womens_life_stage (3) | 1628525708786841, 2317298199104938 | style-ingredient-callout.jpg |
| price_card | Static product | 20 | 3.0% | 99 | 20 / 0 | price_offer (12), gamified_offer (6), gut_poop (1) | 28287334074293825, 1633407318152957 | style-price-card.jpg |
| macro_product | Static product | 14 | 2.1% | 17 | 14 / 0 | gut_poop (3), fiber (2), weight_metabolism (2) | 2837214583298615, 1955643948477674 | style-macro-product.jpg |
| review_quote | Static proof | 20 | 3.0% | 22 | 20 / 0 | glp1 (8), gut_poop (6), guarantee (2) | 28022992047403208, 2094537778089310 | style-review-quote.jpg |
| stats_claims | Static proof | 5 | 0.7% | 6 | 5 / 0 | glp1 (2), social_proof (1), gut_poop (1) | 2282664652473738, 1603218607833231 | style-stats-claims.jpg |
| press_quote | Static proof | 1 | 0.1% | 1 | 1 / 0 | all_in_one_nutrition (1) | 956023224095708 | style-rare-formats-2.jpg |
| before_after | Static comparison | 21 | 3.1% | 23 | 18 / 3 | glp1 (8), gut_poop (4), weight_metabolism (4) | 1733625331083478, 891505727303637 | style-before-after.jpg |
| us_vs_them | Static comparison | 10 | 1.5% | 10 | 9 / 1 | vs_greens_powder (4), vs_other_gummies (2), vs_other_supplements (1) | 1648360639769683, 2222929251970650 | style-us-vs-them.jpg |
| notes_app | Static native screenshot | 9 | 1.3% | 9 | 9 / 0 | glp1 (5), gut_poop (3), men (1) | 1757851642092440, 1969020220434963 | style-notes-app.jpg |
| imessage_notification | Static native screenshot | 4 | 0.6% | 5 | 4 / 0 | gut_poop (2), fiber (1), hair_skin_collagen (1) | 1397406922548821, 1302935344798928 | style-imessage-notification.jpg |
| social_screenshot | Static native screenshot | 4 | 0.6% | 5 | 4 / 0 | glp1 (3), fertility_ttc (1) | 2084852425494744, 1011008618529371 | style-social-screenshot.jpg |
| editorial_article | Static native screenshot | 3 | 0.4% | 5 | 3 / 0 | gut_health (1), vs_greens_powder (1), sister_brands (1) | 1611861723970580, 1061553430077434 | style-editorial-article.jpg |
| sticky_notes | Static native screenshot | 2 | 0.3% | 2 | 1 / 1 | glp1 (1), all_in_one_nutrition (1) | 1327525282257529, 1083650017861793 | style-rare-formats-2.jpg |
| billboard_mockup | Static native screenshot | 2 | 0.3% | 2 | 2 / 0 | vs_other_supplements (1), glp1 (1) | 1098873769736029, 4538366993113751 | style-rare-formats-1.jpg |
| search_bar | Static native screenshot | 1 | 0.1% | 1 | 1 / 0 | glp1 (1) | 2232133397739095 | style-rare-formats-2.jpg |
| receipt_mockup | Static native screenshot | 1 | 0.1% | 1 | 1 / 0 | glp1 (1) | 1755509135730725 | style-rare-formats-2.jpg |
| whiteboard | Static native screenshot | 1 | 0.1% | 1 | 1 / 0 | glp1 (1) | 4021660541469168 | style-rare-formats-2.jpg |
| confession_text_post | Static native screenshot | 1 | 0.1% | 1 | 1 / 0 | womens_life_stage (1) | 2220160505443076 | style-rare-formats-1.jpg |
| listicle | Static native screenshot | 1 | 0.1% | 1 | 1 / 0 | science_methylation (1) | 1656393942682392 | style-rare-formats-1.jpg |
| meme | Static humor / editorial | 11 | 1.6% | 16 | 10 / 1 | glp1 (6), gut_poop (3), flavors_limited (2) | 1514879236817894, 2246799579500639 | style-meme.jpg |
| illustration | Static humor / editorial | 11 | 1.6% | 11 | 11 / 0 | gut_poop (4), womens_life_stage (3), fiber (1) | 2305203203341124, 1617206136032970 | style-illustration.jpg |
| typographic_statement | Static humor / editorial | 11 | 1.6% | 11 | 11 / 0 | glp1 (4), gut_poop (2), vs_greens_powder (2) | 2354659615280432, 1414139674019412 | style-typographic-statement.jpg |
| infographic | Static humor / editorial | 10 | 1.5% | 10 | 10 / 0 | womens_life_stage (4), glp1 (3), results_timeline (1) | 1749927693112367, 1098182115942586 | style-infographic.jpg |
| apology_letter | Static humor / editorial | 5 | 0.7% | 7 | 5 / 0 | glp1 (4), fiber (1) | 1725626181994219, 1557036029376172 | style-apology-letter.jpg |
| mascot_scene | Static humor / editorial | 3 | 0.4% | 3 | 3 / 0 | gut_poop (2), glp1 (1) | 1119345473765802, 1558632799612483 | style-mascot-scene.jpg |
| visual_metaphor | Static humor / editorial | 1 | 0.1% | 1 | 1 / 0 | fertility_ttc (1) | 998054019658078 | style-rare-formats-2.jpg |
| ugc_photo | Static people photo | 17 | 2.5% | 20 | 17 / 0 | womens_life_stage (4), flavors_limited (3), glp1 (3) | 3443157605869714, 1097538766099727 | style-ugc-photo.jpg |
| lifestyle_photo | Static people photo | 8 | 1.2% | 8 | 8 / 0 | womens_life_stage (2), gummies_work (1), flavors_limited (1) | 968209949444690, 2289386161833049 | style-lifestyle-photo.jpg |
| problem_photo | Static people photo | 2 | 0.3% | 2 | 2 / 0 | glp1 (1), gut_poop (1) | 1097848052650875, 1395750929418099 | style-rare-formats-2.jpg |

**Style glossary**

- UGC video
  - ugc_talking_head: creator to camera, handheld or selfie, with burned-in captions.
  - text_overlay_pov: silent or music-only selfie clip with a long block of on-screen text ("POV: ...", "GLP-1 side effects are SO real...").
  - ugc_voiceover_broll: faceless hands, product, kitchen or bathroom b-roll with voiceover and kinetic captions.
  - ugc_unboxing: mailer opening and first taste.
  - comment_reply_video: TikTok "reply to comment" sticker opening.
  - ugc_mashup: multi-creator split-screen montage.
  - listicle_video: numbered reasons ("#2 those cravings?").
  - day_in_the_life: routine, GRWM or vacation vlog.
  - review_montage_video: 5-star review cards over b-roll.
- Authority video
  - expert_talking_head: nurse in scrubs, fertility doctor in white coat, trainer ("myth vs fact").
  - founder: Chad Janis podcast clip, founder gut-score selfie.
  - educational_explainer: whiteboard drawing ("collagen crew, zinc foreman").
  - podcast_clip, green_screen (creator in front of a news headline or infographic), street_interview (mic in a parking lot or park).
  - product_demo: lighter test on gelatin vs pectin, jars of equivalent veggies, pouring out a supplement stack.
- Entertainment video
  - skit: produced store or office sketches.
  - couple_skit: "pov my bf thought my vitamin gummies were candy", Jonathan Bennett and husband.
  - stunt_challenge: "eating habaneros to get a Grüns discount", arm wrestling, ladder watermelon catch, "every gummy he catches = 10% off".
  - meme_edit_video: glitch or video-game HUD edits, "he risked it all for Grüns".
  - mascot_costume: bear costume in the street.
  - behind_the_scenes: warehouse packing orders, "box me up fam".
- Animated / produced video
  - animated_character: Pixar-style 3D, claymation, 2D cartoon, talking poop, fruit or sperm characters, pixel game.
  - motion_graphics: kinetic type, animated bear.
  - cgi_medical_animation: 3D anatomy with nutrient particles.
  - produced_brand_video: cinematic spots such as "Ruining your cut" or surreal "if you wake up every morning".
- Talent
  - celebrity_lifestyle: Julianne Hough rehearsal and kitchen.
  - creator_niche_integration: a golf creator on the course, a finance creator using compounding language.
  - newsjack_celebrity: Lisa Rinna copycat jab.
- Static product
  - product_hero: bag or bear plus headline, often with a checklist.
  - macro_product: "the product shown huge", a giant gummy bear filling the frame.
  - ingredient_callout: arrows or labels on the product, ingredient lists, annotated supplement-facts panel, fiber-equivalent icons.
  - price_card: strikethrough price, % off, gift kit, mystery flavor, slot machine.
- Static proof
  - review_quote: customer quote as the headline, verified-buyer card, handwritten review note.
  - stats_claims: "84% reported improvement".
  - press_quote: GLAMOUR quote.
- Static comparison
  - before_after: split frames with/without, hairbrush, bald/full hair, bloated/flat, real mirror-selfie body transformation, line-drawn "me on a calorie deficit".
  - us_vs_them: check-vs-cross chart against a powder tub, "2 ways to get your greens", fiber bar chart gummies vs kale vs broccoli.
- Static native screenshot
  - notes_app: Apple Notes story or list.
  - imessage_notification: lock-screen calendar plus iMessage, retro Nokia SMS, chat bubbles.
  - search_bar: phone search history "how to poop on a glp1".
  - social_screenshot: IG story Q&A, Reddit-style thread.
  - sticky_notes: post-its on packs or a window.
  - receipt_mockup: a receipt with gifts at $0.00.
  - whiteboard, confession_text_post, editorial_article (fake news article or newspaper front page), billboard_mockup, listicle (fact cards).
- Static humor / editorial
  - meme: Barbie/Ken "me on a GLP-1 pooping once a week vs daily", line-drawing "why are you so quiet".
  - illustration: cartoons and comics.
  - mascot_scene: 3D bear on a toilet.
  - typographic_statement: "F*CK YOUR GREENS POWDER", "DON'T BUY THESE GUMMIES", "BAD NEWS if you're on a GLP-1".
  - apology_letter: "WE'RE SO SORRY", "This is a bit awkward".
  - visual_metaphor: flower-arranged uterus.
  - infographic: symptom grids, timelines, Venn, iceberg.
- Static people photo
  - ugc_photo: phone photo of a hand or selfie with TikTok-style captions.
  - lifestyle_photo: staged model shots.
  - problem_photo: bloated belly, dentures.

**How Max's list maps to what Grüns runs:**

| Max's list | What Grüns runs |
|---|---|
| Before/after | 21 creatives |
| Us vs them | 10 |
| Reviews | 20 review quotes, 5 stats cards, 2 review-montage videos |
| Google search screenshot | 1 static search-history screenshot; Google also appears inside an explainer video. Rare |
| Notes-app | 9 |
| UGC | 305 UGC videos plus 17 UGC photos |
| Shares / social posts | 4 social screenshots plus 7 comment-reply videos |
| Product photos | 29 hero |
| Product shown huge | 14 macro |
| Ingredients image | 24 callouts |

Also present: iMessage (4), memes (11), apology letters (5), press (1), founder (2), and animated characters (25). No tweet screenshots and no collab character-art statics are active in the US right now. The Minions collab runs only as creator video.

## d) Angle x style matrix (the core insight)

**By style family.** Unique creatives; "." means none. The last column counts how many of the 11 style families the angle uses.

| Angle | UGC vid | Auth vid | Ent vid | Anim vid | Talent | St product | St proof | St compare | St native | St humor | St people | Families used |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| glp1 | 48 | 3 | . | 15 | . | 14 | 10 | 8 | 13 | 19 | 5 | 9 |
| all_in_one_nutrition | 59 | 4 | 2 | 1 | 6 | 2 | 1 | . | 1 | . | . | 8 |
| gut_poop | 24 | . | 2 | 7 | . | 8 | 7 | 4 | 5 | 12 | 2 | 9 |
| womens_life_stage | 9 | . | . | 5 | . | 3 | 2 | . | 1 | 7 | 6 | 7 |
| weight_metabolism | 11 | . | 1 | 4 | . | 8 | 1 | 5 | . | 1 | 2 | 8 |
| price_offer | 6 | . | 11 | . | . | 13 | . | . | . | . | 1 | 4 |
| fiber | 13 | 4 | 1 | 3 | 1 | 2 | . | 2 | 1 | 2 | . | 9 |
| flavors_limited | 17 | . | . | . | . | 5 | . | . | . | 2 | 4 | 4 |
| vs_greens_powder | 14 | . | 3 | . | . | 1 | . | 5 | 1 | 2 | 1 | 7 |
| hair_skin_collagen | 10 | 3 | . | 4 | . | 2 | . | . | 1 | . | 1 | 6 |
| taste | 15 | . | 1 | . | . | 2 | 1 | . | . | . | 1 | 5 |
| fertility_ttc | 9 | 2 | . | 1 | . | 2 | . | . | 1 | 2 | 1 | 7 |
| men | 6 | . | 4 | 2 | . | 1 | . | . | 1 | 2 | 1 | 7 |
| collab_licensed | 12 | 2 | 1 | . | . | . | . | . | . | . | . | 3 |
| gut_health | 8 | 2 | . | . | . | 2 | 1 | . | 1 | . | . | 5 |
| vs_other_supplements | 8 | 1 | . | . | . | 1 | . | 3 | 1 | . | . | 5 |
| gamified_offer | . | . | 7 | . | . | 6 | . | . | . | . | 1 | 3 |
| convenience | 8 | . | . | . | 3 | 1 | . | . | . | . | . | 3 |
| science_methylation | 3 | 1 | . | . | . | 2 | . | 1 | 1 | 1 | . | 6 |
| energy | 3 | 1 | . | . | . | 1 | . | 1 | . | 1 | . | 5 |
| gummies_work | 2 | 3 | 1 | . | . | . | . | . | . | . | 1 | 4 |
| hate_veggies | 6 | . | 1 | . | . | . | . | . | . | . | . | 2 |
| kids_family | 4 | . | . | . | . | 2 | . | . | . | . | . | 2 |
| simple_routine | 4 | . | . | . | . | 2 | . | . | . | . | . | 2 |
| sister_brands | 1 | . | . | . | . | 4 | . | . | 1 | . | . | 3 |
| vs_other_gummies | . | . | . | . | 2 | 1 | . | 2 | . | . | . | 3 |
| fitness_athletes | 2 | . | . | . | . | 1 | . | . | . | . | . | 2 |
| social_proof | 2 | . | . | . | . | . | 1 | . | . | . | . | 2 |
| guarantee | . | . | . | . | . | . | 2 | . | . | . | . | 1 |
| collab_partner | 1 | . | . | . | . | 1 | . | . | . | . | . | 2 |
| brand_entertainment | . | . | 2 | . | . | . | . | . | . | . | . | 1 |
| results_timeline | . | . | . | . | . | . | . | . | . | 1 | . | 1 |
| TOTAL | 305 | 26 | 37 | 42 | 12 | 87 | 26 | 31 | 29 | 52 | 27 | |

**Fine-grained: top 12 angles x top 14 styles** (unique creatives)

| Angle | ugc_talking_head | text_overlay_pov | ugc_voiceover_broll | product_hero | animated_character | ingredient_callout | before_after | price_card | review_quote | ugc_photo | macro_product | day_in_the_life | skit | meme |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| glp1 | 10 | 18 | 9 | 6 | 9 | 6 | 8 | . | 8 | 3 | 2 | 3 | . | 6 |
| all_in_one_nutrition | 52 | . | 4 | . | . | 2 | . | . | . | . | . | . | 1 | . |
| gut_poop | 11 | 6 | 4 | 4 | 6 | . | 4 | 1 | 6 | 1 | 3 | . | 1 | 3 |
| womens_life_stage | 3 | 2 | 3 | . | 3 | 3 | . | . | 2 | 4 | . | . | . | . |
| weight_metabolism | 4 | 1 | 4 | 3 | 2 | 3 | 4 | . | 1 | 1 | 2 | . | . | . |
| price_offer | 5 | . | 1 | 1 | . | . | . | 12 | . | 1 | . | . | 5 | . |
| fiber | 7 | 2 | 4 | . | . | . | 1 | . | . | . | 2 | . | . | . |
| flavors_limited | 11 | 1 | . | 5 | . | . | . | . | . | 3 | . | 2 | . | 2 |
| vs_greens_powder | 10 | 4 | . | . | . | . | 1 | . | . | 1 | 1 | . | 1 | . |
| hair_skin_collagen | 2 | 3 | 3 | 1 | 4 | 1 | . | . | . | 1 | . | 1 | . | . |
| taste | 9 | 2 | . | 1 | . | 1 | . | . | 1 | . | . | . | . | . |
| fertility_ttc | 2 | 5 | 2 | 1 | 1 | 1 | . | . | . | . | . | . | . | . |

The full 32 x 59 matrix is in `taxonomy.json` under `matrix`. The family version is under `family_matrix`.

How to read it:

- **Big angles are spread across formats, not stacked in one.**
  - GLP-1 uses 9 of 11 families. No single style exceeds 13% of GLP-1 creatives; text-overlay POV is the largest at 18 of 135.
  - Gut/poop uses 9 families: from notes-app lists and iMessage lock screens to a 3D bear on a toilet, Barbie memes, and cartoon "poop police".
- **Some angles are deliberately narrow.**
  - "all_in_one_nutrition" is almost only creator talking heads (52 of 76). This is the creator-whitelisting bucket that sits under the price-objection headline.
  - "gamified_offer" is only price cards and stunt videos.
  - "collab_licensed" (Minions) is creator video only.
- **Comparison formats go where there is a clear enemy.** us_vs_them clusters on vs_greens_powder, vs_other_gummies and vs_other_supplements. before_after clusters on physical-change angles: GLP-1 hair and skin, bloat, weight.
- **Native screenshots and humor carry the embarrassing topics.** The notes app, iMessage, search bar, memes and apology letters are used almost only for GLP-1 and poop. Lo-fi formats make "taboo" topics feel like a friend talking, not a brand.

## e) Patterns

1. **Styles per angle.**
   - Median unique creatives per angle: 14; mean: 21.
   - The 18 angles with 10+ creatives use 3 to 35 styles (median 9.5) and 3 to 9 style families (median 6.5).
   - Even small test angles open with 3–5 styles. PCOS, for example, runs as a UGC selfie, a 3D uterus character, a listicle video, faceless b-roll and a lifestyle photo.
2. **Iteration model: one message, many visuals.**
   - Headlines are few (75) and reused. The visuals rotate underneath.
   - The same headline sits on up to 80 creatives in up to 20 styles.
   - Near-identical creatives get re-cut, not re-thought. Examples:
     - the same Barbie meme as a portrait, a full-body version, a Ken version and a video;
     - "Hello, daily poops" with and without an offer badge;
     - "Sorry to whoever sees this" as a typed note, a handwritten note and an Apple Notes version.
3. **A landing page per angle.** 63 landing pages. GLP-1 alone uses 21 (listicle, flip-to-win, muscle, hair, teeth, post-GLP-1, men). Life stages each have one: perimenopause, menopause, postpartum, PCOS, male and female fertility. So do partner and celebrity pages (/jenna-bush-hager, /vivian-tu, /fat-perez).
4. **Launch cadence.** Big batches, not a drip:

   | Period | Ads started |
   |---|---|
   | Late May–June build-out | 183 |
   | July | 19 |
   | 17 Aug birthday price drop | 73 in one day |
   | 20–21 Aug Raspberry Lemonade return | 37 |
   | 24 Sep | 287 |
   | 28 Sep | 108 |

   479 of 823 active ads (58%) started in September.
5. **What runs longest.**
   - Nothing active is older than about 4 months, so Grüns clearly retires creative on a cycle.
   - The survivors from late May and June (183 ads, 22%) skew to:
     - GLP-1 (28% of survivors vs 19% of September launches);
     - text-overlay POV (13%) and faceless voiceover b-roll (10%);
     - before/after (6%), macro product and ingredient callouts (4% each);
     - typographic statements, memes and animated characters.
   - Oldest examples:
     - 1508855464308079 (fiber text-overlay video, 29 May)
     - 1568451768213057 (fiber voiceover b-roll, 29 May)
     - 1553813810087444 (GLP-1 listicle video, 29 May)
     - 1505906931026556 (taste unboxing, 29 May)
     - 1509162034080958 ("Fibermaxxing is the new proteinmaxxing" static, 1 Jun)
     - 1302935344798928 (iMessage lock-screen static, 1 Jun)
     - 1648360639769683 (pills vs product split static, 1 Jun)
   - The September wave is mostly creator talking heads (28%). That is a creator-whitelisting push under the price-objection headline.
6. **Copy is clean; the creative is edgy.**
   - Visible primary texts are long, benefit-list, compliant copy: "21 vitamins & minerals, 6g fiber, prebiotics...", 159 subscription disclaimers, 81 "1 million".
   - Provocative words ("poop", "sorry", "F*ck", "don't buy") appear on the image or in the video. They never appear in the visible primary text. This keeps the ad text safe for review while the thumbnail does the stopping.
7. **Hooks rotate as their own dimension.** From the classification notes:

   | Hook type | Unique creatives |
   |---|---|
   | Question / problem | 51 |
   | Numbered list | 18 |
   | POV | 15 |
   | Apology / pattern interrupt | 14 |
   | Confession ("nobody warned me", "I don't usually share this") | 10 |
   | Comment reply | 9 |
   | Reverse psychology ("don't buy these gummies") | 7 |
   | Call-out ("we're looking for men on a GLP-1 who...") | 3 |

   The apology, reverse-psychology and call-out hooks appear across static and video.
8. **Talent and culture as a layer.**
   - 17% of ads run from 65 partner pages. Celebrities do lifestyle and talking heads. Niche creators do their own format: golf course, finance "compounding", Minion cosplay.
   - Culture pieces: licensed IP (Minions), a co-branded flavor (Popsicle Firecracker), an app bundle (Ladder), a retail moment ("Primetime sale") and a newsjack (Lisa Rinna copycat).
9. **Seasonal / limited drops create their own burst.** The Raspberry Lemonade return ("Tastes Exactly Like Summer") got 31 creatives in 11 styles, all launched 20–24 Aug. Most were creator videos plus one set of summer statics: memes, beach UGC photos, product collage.

## f) Otto standard: the minimum creative matrix for every new client

Grüns runs 32 angles x 59 styles with 674 creatives. An Otto client needs the same shape at a smaller size. The rules below come straight from the patterns above.

**1. Angles: 6 at launch, one per angle family. Grow to 8–10 by week 6.**

| Slot | What it is | Grüns equivalent |
|---|---|---|
| A. Pain | The problem said bluntly, in the customer's words | gut_poop, fiber, weight |
| B. Identity | One specific person or life stage with a specific problem | glp1, perimenopause, men / husbands, fertility |
| C. Enemy | What they use today and why it fails | vs_greens_powder, vs_other_supplements, hate_veggies |
| D. Experience | How it feels to use: taste, ease, speed, format | taste, convenience, gummies_work, simple_routine |
| E. Offer | Price drop, bundle, gift, guarantee; gamified if possible | price_offer, gamified_offer, guarantee |
| F. Moment | Seasonal, limited, collab, newsjack or partner bundle (month 1 may use a second Identity angle instead) | flavors_limited, Minions, Ladder, Primetime sale |

Why 6: Grüns covers all 6 families, and its 18 serious angles each hold 10+ creatives. Six is the smallest set that still covers every family.

**2. Styles: 6 per angle at launch (36 creatives), covering at least 4 style families per angle.**

Mandatory slots for every angle:

| # | Slot | Rotate between | Why (Grüns evidence) |
|---|---|---|---|
| 1 | UGC talking-head video | real customer, AI avatar, founder, expert in uniform | 25% of all Grüns creatives; the largest style in 5 of the top 10 angles |
| 2 | Faceless video | text-overlay POV or voiceover b-roll | 14% of creatives; over-represented among the 4-month survivors |
| 3 | Product static | product hero, macro "product huge", ingredient / supplement-facts callout | 13% of creatives; present in 25 of 32 angles |
| 4 | Comparison static | before/after or us-vs-them (pick the one that fits the angle) | 31 creatives; the default for enemy and physical-change angles |
| 5 | Native screenshot static | Notes app, iMessage / lock screen, search bar, social post or comment, sticky notes, receipt | used on the most sensitive, highest-volume angles |
| 6 | Proof or humor static | review quote / stats card, or meme / illustration / typographic statement / apology letter | 78 creatives combined; carries the pattern-interrupt hooks |

On top of the 6 slots:

- **Offer angle (E):** also gets 1 price card, and the offer badge goes on every static in every angle. Grüns puts "61% off + free gifts" on most statics.
- **One entertainment or animated video per client at launch.** Choose a skit, stunt, animated character or motion graphic. Put it on the Pain or Offer angle. Grüns has 79 of these; animated characters alone are 25 creatives.
- **Media mix.** Target 50% video / 50% static at launch, then move toward 60% video by month 2. Grüns is 63% video by unique creative, but statics are cheaper to test angles with.

**3. Ads per angle.**

| Item | Standard |
|---|---|
| Unique creatives per angle at launch | 6 (36 total). Grüns median is 14 per angle, but that is after 4 months of accumulation |
| Headlines per angle | 1–2. Reuse the same headline across all 6 creatives so the test is about the visual. Grüns runs 75 headlines for 674 creatives |
| Primary texts per angle | 2–3, compliant benefit copy. Keep the edgy wording in the creative only |
| Hook types across the launch batch | At least 5 of: question / problem, POV, numbered list, confession, apology / pattern interrupt, reverse psychology, comment reply, call-out |
| Landing page | One landing page or LP variant per angle. Grüns runs 63; 21 for GLP-1 alone |

**4. Refresh cadence.**

| When | What |
|---|---|
| Weekly | +2 new creatives per angle (12 per week at 6 angles). Each new pair uses at least one style that angle has not run yet. Re-cut winners before inventing new ones: new crop, with/without the offer badge, different hook line on the same visual |
| Monthly | +1 new angle (a new Identity sub-segment or a new Enemy) and 1 Moment angle (season, drop, collab, retail event) |
| Every 4 months | Nothing should run longer than about 4 months without a replacement tested beside it. Grüns' oldest active ad is 4 months old |
| Batch launches | Ship in batches, not one-offs. Grüns launched 287 ads on one day |

**5. Floor for micro budgets.** If a client's daily budget cannot support 36 creatives, drop to 4 angles (Pain, Identity, Enemy, Offer) x 5 styles = 20 creatives. Keep slots 1, 2, 3, 4 and 5 from the table above. Never go below 4 angles and 4 style families. That would break Max's rule and the Grüns pattern.

**6. What not to copy.**

- The creatives themselves and Grüns' brand phrases ("Trusted by 1M+", "61% off + free gifts", "GLP-1's new bestie").
- Scale items that need Grüns' budget: licensed IP, celebrity partnerships, a 65-creator whitelisting program, 800+ live ads.

Otto can copy the structure: angle families x style families, one headline across many visuals, one LP per angle, and batch refresh.

## Limitations

- **Sample.** 823 of ~830 active US cards, from the public Library UI. Each card shows one version of a flexible ad, so hidden versions (other images, texts or headlines) were not classified. The US Library gives no spend or impression data. "What works" is inferred from longevity, reuse and batch size.
- **Video classification.** Videos were judged from the poster plus two frames and burned-in captions; audio was not heard. Generic creator testimonials were assigned to an angle from their visible captions. Most fell under all_in_one_nutrition, so that angle is probably partly a catch-all.
- **Counting.** One analyst chose one primary angle and one primary style per creative. Creatives often mix, for example a macro product plus a review quote. Hook tags are keyword-derived from notes and are indicative only.
- **API counts** are estimated totals from `ads_library_search`. They match copy text, may include hidden versions and fuzzy matches, and are not exact.
