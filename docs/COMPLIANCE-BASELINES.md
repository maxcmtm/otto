# Compliance baselines by country and industry

Date: 2026-09-30 · Owner: Max · Code: `platform/otto_baselines.py` (the rules, as data) and `platform/otto_compliance.py`
(the engine). Tests: `platform/tests/test_country_compliance.py`. Launch plan: `research/EU-LAUNCH-AND-PRICING-2026-09.md` §6.3, §8.

Every post and ad is checked against three things:

- the brand's own `brands/<id>/compliance.json`;
- the health baseline, for health brands that have no rules file;
- the **country baselines** below, which apply automatically.

A violation of any severity puts the item on hold, and a recommendation says why and what to do:

- **block**: the copy must change.
- **needs-review**: a person checks it, either per item or once for the whole brand when the rule names a clearance.
- **disclose**: the required disclosure is missing from the text.

Nothing that needs review passes silently.

## How a brand's market and industry are found

- **Countries** are found in this order:
  1. compliance.json `"countries"`;
  2. `brands[].countries`;
  3. the site's country domain (`.nl`, `.ie`, `.be`; `.eu` means EU);
  4. the scan's currency (EUR gives the EU-wide rules only);
  5. the site language.
  - Nothing found: no country rules apply. US and Israeli brands get none.
  - A campaign adds its audience countries, so a Dutch campaign that also targets Flanders gets the Belgian rules.
- **Industry tags** come from the scan's industry label (strong evidence), or from the title, description and profile
  "Industry:" line (keyword evidence).
  - A shop platform (Shopify and similar) adds `goods`.
  - compliance.json `"industries": [...]` replaces detection.
  - Rules that hold *every* post of a brand (for example Keuringsraad) need strong evidence.
- Check what applies with `python3 platform/otto_compliance.py baselines <brand>`. The same summary is returned in the
  onboarding response (`compliance`) and in the owner console's brand drill-down (`brands[].compliance`).

## Releasing a hold

| What | Command | Effect |
|---|---|---|
| Brand-wide clearance | `otto_compliance.py clear <brand> keuringsraad "KOAG/KAG K-…"` (also `prior_price_30d`, `age_gate_18`, `nix18_in_visuals`, `big_details_linked`) | Writes compliance.json `"clearances"`; the rule stops holding that brand's posts. |
| One item reviewed | `otto_compliance.py review <post-id or cp-id> <rule-id>[,…] --by max --note "…"` | Recorded on the item with a hash of its text. If nothing else holds it, the hold is lifted (the post goes back to `pending_approval`). Any edit reopens the hold. Block rules cannot be reviewed away. |
| Rule does not fit this brand | compliance.json `"baselines_off": {"<rule-id>": "why"}` | Skipped, and shown in the summary with the reason. |

There is no button in the app for these yet, because `otto_api.py` and `index.html` belong to another engineer.

## The rules

Patterns are in English and Dutch. The Belgian ban also has French patterns.

### EU-wide (every EU/EEA brand, and brands that only sell in EUR)

| Rule | Severity | Industries | What it holds | Source |
|---|---|---|---|---|
| `eu-disease-claim` | block | all except clinics and B2B | "helpt tegen verkoudheid", "geneest eczeem", "voorkomt botontkalking", "prevents colds", "heals eczema", "wondermiddel" | Reg. 1169/2011 art. 7(3)–(4); UCPD Annex I No. 17; Keuringsraad |
| `eu-health-claim-wording` | needs-review | supplements, CBD | "boost your immune system", "detox", "superfood", "klinisch bewezen", "ontstekingsremmend" | Reg. 1924/2006 art. 10(1), 10(3); EU register |
| `eu-food-weightloss-doctor` | block | supplements, CBD, food | "5 kilo afvallen", "lose 5kg", "aanbevolen door artsen" | Reg. 1924/2006 art. 12; ASAI 8.14; CAG art. 7, 17 |
| `eu-prescription-medicine` | block | all | Botox, botulinum, Ozempic, Wegovy, Mounjaro, "anti-wrinkle injections", "afslankprik" | Dir. 2001/83 art. 88; NL Geneesmiddelenwet art. 85 and IGJ; IE S.I. 541/2007 reg. 9 and HPRA |
| `eu-urgency-scarcity` | needs-review (per item) | all except B2B | "laatste kans", "nog maar 3 stuks", "alleen vandaag", "only today", "almost sold out" | UCPD Annex I No. 7 |
| `eu-price-reduction-30d` | needs-review, clear `prior_price_30d` | goods | "van €49 voor €29", "20% korting", "was €", "sale", "Black Friday" | PID art. 6a and Commission guidance; CJEU C-330/23; NL BPP art. 5a; IE reg. 5A (goods only) |
| `eu-price-incl-vat` | needs-review | all except B2B | "excl. btw", "plus VAT", "exclusief servicekosten" | UCPD art. 7(4)(c); NL BPP art. 1a, BW 6:193e; IE CPA 2007 s.46 |
| `eu-free-trial-price` | disclose | all except B2B | "eerste maand gratis" / "free trial" without the price afterwards | UCPD art. 7 and Annex I No. 20 |
| `eu-generic-green-claim` | needs-review | all | "milieuvriendelijk", "duurzaam", "eco-friendly", "biodegradable", "net zero" | Dir. 2024/825 (from 27.09.2026); NL BW 6:193g; Code voor Duurzaamheidsreclame |
| `eu-offset-neutral-claim` | block | all | "CO2-neutraal", "klimaatneutraal", "carbon neutral" | Dir. 2024/825, Annex I 4c; BW 6:193g(ae) |
| `eu-cosmetic-free-from` | needs-review | cosmetics, aesthetic | "parabenenvrij", "chemical-free", "hypoallergeen" | Reg. 655/2013; Commission technical document on cosmetic claims |
| `eu-influencer-disclosure` | disclose (label within the first 120 characters) | all; not NL/IE, which have their own rules | creator signals ("use my code", "#collab", "#spon") without #ad or Anzeige | UCPD art. 7(2), Annex I No. 11, 22 |
| `eu-gambling` | block | gambling | everything: gambling is not an Otto vertical | Ksa; GRAI; ASAI s.10 |

### Netherlands

| Rule | Severity | Industries | What it holds | Source |
|---|---|---|---|---|
| `nl-kag-preapproval` | needs-review, clear `keuringsraad` | supplements, CBD (strong evidence), posts | **every post**: "Health product ad in NL: needs Keuringsraad pre-approval" | CAG 2019; Keuringsraad FAQ; NVWA work agreements |
| `nl-kag-ad-preapproval` | needs-review (per campaign) | supplements, CBD, ads | **every ad**: each digital ad is pre-vetted | CAG 2019 |
| `nl-kag-number` | disclose | supplements, CBD | the text lacks "KOAG/KAG …" | Keuringsraad: the number goes on every advertisement |
| `nl-alcohol-nix18` | disclose, clear `nix18_in_visuals` | all, when the text is about alcohol; always for alcohol brands | "NIX18" missing (the logo belongs in the image) | Reclamecode voor Alcoholhoudende Dranken 2024 art. 23(2), 32 |
| `nl-alcohol-age-gate` | needs-review, clear `age_gate_18`; ads under 18 are blocked | as above | the account is not age-gated 18+; an ad audience below 18 | RvA art. 23(3)–(4) |
| `alcohol-themes` (NL + IE) | block | as above | "gratis biertje", "2 voor 1 cocktails", "1+1", "healthy beer", "boosts your confidence" | RvA art. 6–8, 19, 25(3); ASAI 9.5 |
| `alcohol-excess` (NL + IE) | block | all | "onbeperkt drinken", "bottomless", "all you can drink", "adten", drinking games | RvA art. 1; ASAI 9.8 |
| `nl-alcohol-offtrade-discount` | block | alcohol, goods, when about alcohol | more than 25% off, "3 halen 2 betalen", "1+1". "Tweede fles halve prijs" is allowed. | Alcoholwet art. 2a; NVWA |
| `nl-aesthetic-big` | disclose, clear `big_details_linked` | aesthetic | the doctor's title and BIG number are missing | Code Cosmetische Behandelingen door Artsen art. 5 |
| `nl-aesthetic-before-after` | needs-review | aesthetic | "voor en na", "before and after" | IGJ; CCBA |
| `aesthetic-minors` (NL, IE, BE) | block; ads must be 18+ | aesthetic | "eindexamenfeest", "tieners", "debs", "prom"; an ad audience below 18 | CCBA art. 3; ASAI s.7 |
| `health-guarantee` (NL, IE, BE) | block | supplements, CBD, cosmetics, aesthetic, clinics, fitness | "gegarandeerd resultaat", "zonder bijwerkingen", "100% veilig", "guaranteed results", "no side effects" | CAG art. 20, 23; CCBA art. 4; ASAI 11.10 |
| `nl-influencer-disclosure` | disclose (upfront) | all | creator signals without "AD", "Reclame", "Advertentie" or "(Betaalde) samenwerking met @…". #spon and #adv do not count. | Reclamecode Social Media & Influencer Marketing 2026 art. 3 |
| `eu-gambling-offer` (NL, IE, BE) | block | all | "gratis spins", "stortingsbonus", "free spins", "place your bets" | Ksa; GRA 2024 |

### Ireland

| Rule | Severity | Industries | What it holds | Source |
|---|---|---|---|---|
| `ie-influencer-disclosure` | disclose (upfront) | all | creator signals without #Ad, #Fógra or "Paid partnership". #sp, #spon and #collab do not count. | CCPC/ASA Influencer Marketing Guidance (2023); ASAI 3.31–3.34 |
| `ie-alcohol-responsible` | disclose | all, when about alcohol | no "enjoy responsibly" / drinkaware message | ASAI 9.4 |
| `ie-alcohol-age-gate` | needs-review, clear `age_gate_18` | alcohol brands | pages not age-gated; an ad audience below 18 | ASAI 9.7(f), 9.9 |
| `ie-alcohol-health-warnings` | **pending (not enforced)** | alcohol | the s.13 health warnings | Public Health (Alcohol) Act 2018 s.13(1)–(3), (7)–(11): not commenced as of 17.09.2026 |
| `ie-weight-loss-period` | block | all | "lose 5kg in 2 weeks", "drop a dress size in" | ASAI 12.13–12.14, 12.17 |
| `ie-cure-rejuvenation` | needs-review | clinics, cosmetics, aesthetic, supplements, CBD, fitness | "cure", "rejuvenation" | ASAI 11.9 |

The ASAI Code in force is the 7th edition (Revision 2021). The 8th edition was in consultation until 9.05.2026 and has no
effective date yet. No Irish rule restricts cosmetic-procedure marketing to under-18s. `aesthetic-minors` applies there
as Otto policy (Meta already limits these ads to 18+).

### Belgium (for when Flanders is added)

| Rule | Severity | Industries | What it holds | Source |
|---|---|---|---|---|
| `be-aesthetic-ban` | block | all | fillers, lipfillers, liposuctie, "esthetische geneeskunde", "médecine esthétique", botox (through the EU rule) | Law of 23 May 2013 art. 20/1 (inserted 2014); Constitutional Court 1/2016 |
| `be-aesthetic-practice` | block | aesthetic | everything: only neutral practice information is allowed, with no prices and with titles, and Otto does not write it | same |

## False-positive guards (tested)

These pass: "Treat yourself…", "cat treats", "Beat the cold with our winter stew", "Een warme soep tegen de kou",
"Helpt tegen vlekken", "Voorkomt kalkaanslag", "Niet meer gokken welke maat", "groene thee", "Bikes for sale",
"Gebruik kortingscode WELKOM10" (the brand's own post), "Tweede fles halve prijs" (not held by the 25% alcohol
rule; it is still a price reduction), and clinics saying what they treat.

The FDA/DSHEA line and its EU equivalents are removed before the scan and are never read as claims:

- "not intended to diagnose, treat, cure or prevent any disease"
- "niet bedoeld om ziekten te … genezen"
- "nicht dazu bestimmt … zu heilen"
- the supplement "geen vervanging van een gevarieerd voedingspatroon" line
- "Lees voor gebruik de bijsluiter"

Negated claims pass ("geneest geen verkoudheid", "does not cure"), but "not only … cures" does not.

## Limits

- **Text only.** The NIX18 logo, before/after *images*, AI "results" imagery and retouching are not checked in pixels.
  The rules say so in their fix text.
- **Not encoded:** the Dutch food-to-children rules (Reclamecode voor Voedingsmiddelen 2026, art. 8: nothing aimed at
  under-16s), the Kinder- en Jeugdreclamecode, OTC-medicine ads (KOAG, "Lees de bijsluiter"), and Germany and the UK
  (next markets).
- **Meta audience rules** (under 25% minors for alcohol, RvA art. 20) are left to Meta's own age targeting. Otto's
  default ad audience starts at 25.

## Decisions for Max

1. **Keuringsraad.** NL supplement and CBD brands are held until a KOAG/KAG number is recorded, and every NL ad for them
   is held per campaign. This matches the launch plan ("supplements held unless the client has a Keuringsraad number").
   Keep it?
2. **Urgency and price reductions** hold posts for review. Price reductions can be cleared once per shop
   (`prior_price_30d`); urgency is reviewed per item. Is that too strict for the e-commerce vertical, and should any of
   it become a warning instead?
3. **happygarden** has no `brands[].countries`, so it gets the EU-wide rules through its EUR prices. Set its real
   markets (RO/HU/DE/ES)?
4. **"Duurzaam"** is held for review, because the Dutch sustainability code never allows it without a specification,
   even when it means "long-lasting". The fix text suggests "gaat jaren mee".
