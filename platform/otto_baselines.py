#!/usr/bin/env python3
"""Otto compliance baselines — country × industry advertising rules that apply to every brand automatically, as data.

Read by otto_compliance (merged with brands/<id>/compliance.json). Nothing here runs on its own; `otto_compliance.py table`
prints it and `otto_compliance.py baselines <brand>` shows what applies to one brand.

A rule:
  id           stable id ("nl-kag-preapproval") — used in reviews, clearances and baselines_off
  countries    ISO codes, or "EU" (every EU/EEA country, plus a brand whose market is only known to be the euro area)
  not_countries  countries whose own rule supersedes this one (the generic EU influencer rule is not applied to NL/IE)
  industries   ["*"] or tags from INDUSTRY_TAGS; not_industries excludes tags ("clinic": health services may say they treat)
  strong       a category rule (no patterns) only fires on an industry tag from the scan's industry label or an explicit
               compliance.json "industries" — never on a keyword guess
  contexts     "posts" and/or "ads" (default both; Google headline "hooks" are checked as ads, without disclose rules)
  severity     block         the copy must change (a claim the law forbids)
               needs-review  held with a clear reason until a person checks it (or the brand holds the clearance)
               disclose      held until the required disclosure is in the text
  patterns     {"en": [...], "nl": [...], "fr": [...]} regexes (case-insensitive); any match = a violation. No patterns and
               no require = a category rule (every text of that brand/context).
  when         trigger: the rule is only considered when one of these matches (e.g. the text is about alcohol);
               always_for lists industry tags for which the trigger is taken as met
  require      (disclose) at least one must match — within require_within characters of the start of a text block when set
  negatable    a match right after "not / niet / geen / never …" is not a claim ("does not cure")
  clear_with   a compliance.json "clearances" key that releases a needs-review / disclose rule for the whole brand
               (e.g. the Keuringsraad approval number); per post/campaign releases are recorded with `otto_compliance.py review`
  min_age      ads: the campaign audience's minimum age must be at least this (block otherwise); posts: needs the
               account-level age gate (clear_with)
  active       False = documented but not enforced yet (law not commenced)
  title / why / fix / source   what the owner and Max see on the hold
Sources were read on 30.09.2026 (docs/COMPLIANCE-BASELINES.md has the tables by country); edit the table, not the engine.
"""
import re

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
      "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}

# industry tags: (tag, regex over the scan's industry label = strong evidence, regex over title / description / the
# profile's Industry line = keyword evidence). compliance.json "industries": [...] replaces detection.
INDUSTRY_TAGS = [
    ("clinic", r"clinic|medical",
     r"\b(clinic|kliniek|dental|dentist|tandarts\w*|orthodont\w*|physio\w*|fysio\w*|huisarts\w*|gp practice|doctor|"
     r"artsenpraktijk|therap(y|ist|ie|eut)\w*|psycholo\w*|osteopa\w*|chiropract\w*|podolo\w*|mondhygi\w*|zahnarzt\w*)"),
    ("supplements", r"supplement|nutrition",
     r"\b(supplements?|voedingssupplement(en)?|multivitamin\w*|vitamin(e|s)?|probiotic\w*|probiotica|collage(e)?n|"
     r"protein powder|eiwitpoeder|greens powder|superfoods?|adaptogen\w*|kruidenpreparat\w*|nahrungserg\w*)"),
    ("cbd", r"cbd|hemp|cannab", r"\b(cbd|hennep|hemp|cannabidiol|cannabinoid\w*)"),
    ("cosmetics", r"beauty|spa",
     r"\b(skin ?care|huidverzorging|cosmetics?|cosmetica|serums?|make-?up|haircare|haarverzorging|parfum|perfume)"),
    ("aesthetic", None,
     r"\b(botox|fillers?|lip ?fillers?|hyaluron\w*|med ?spa|aesthetic (medicine|clinic|doctor|treatments?)|"
     r"esthetische (geneeskunde|kliniek|arts|behandelingen)|cosmetische (arts|chirurgie|kliniek)|cosmetic (surgery|doctor|clinic)|"
     r"plastische chirurgie|plastic surgery|injectables|anti-?rimpel\w*|skin ?boosters?|liposuct\w*)"),
    ("alcohol", None,
     r"\b(brewery|brouwerij|bierbrouwerij|winery|wijnhuis|wijnhandel|wijnbar|wine bar|wine shop|slijterij|liquor|distillery|"
     r"distilleerderij|craft beer|speciaalbier\w*|gin|whiske?y|vodka|wodka|rum|cocktail ?bar|biercaf\w*|wijnimport\w*|off-licen[cs]e)\b"),
    ("gambling", None,
     r"\b(casino|betting|sportsbook|sports betting|bookmaker|poker|slots|gokken|kansspel(en)?|sportweddenschap\w*|"
     r"wedkantoor|loterij|lottery|bingo)\b"),
    ("goods", r"e-commerce|retail|supplement|nutrition|cbd", r"\b(webshop|web shop|online ?shop|onlinewinkel)\b"),
    ("hospitality", r"restaurant|food|hotel|travel",
     r"\b(restaurant|caf[eé]|bistro|brasserie|hotel|b&b|bed and breakfast|hostel|lunchroom|pizzeria|eetcaf[eé])\b"),
    ("food", r"restaurant|food|supplement|nutrition|cbd",
     r"\b(food|voeding|chocola(de|te)|snoep|candy|snacks?|koffie|coffee|thee|tea|bakkerij|bakery|juice|smoothies?|granola)\b"),
    ("fitness", r"fitness|gym", None),
    ("b2b", r"saas|software|marketing|agency", None),
]

# --- phrase building blocks ---------------------------------------------------------------------------------------------
DIS_EN = (r"(?:diseases?|illness(?:es)?|cancers?|tumou?rs?|diabetes|hypertension|high blood pressure|heart disease|"
          r"cardiovascular disease|strokes?|depression|anxiety(?: disorders?)?|panic attacks?|insomnia|sleep disorders?|"
          r"migraines?|headaches?|arthritis|osteoarthritis|rheumatism|joint pain|back pain|chronic pain|muscle pain|"
          r"period pain|nerve pain|inflammation|infections?|influenza|flu|colds|common colds?|"
          r"a cold(?=\s*(?:[.,!?;:)]|$|or\b|and\b|faster|quicker|symptoms))|covid(?:-19)?|coronavirus|viruses|virus|"
          r"eczema|psoriasis|acne|rosacea|allerg(?:y|ies)|hay ?fever|asthma|constipation|diarrh(?:o)?ea|ibs|"
          r"irritable bowel(?: syndrome)?|acid reflux|heartburn|ulcers?|osteoporosis|alzheimer'?s|dementia|adhd|autism|"
          r"candida|thrush|cystitis|utis?|urinary tract infections?|hair loss|alopecia|obesity|erectile dysfunction|"
          r"impotence|endometriosis|fibromyalgia|high cholesterol|gout|sciatica|tinnitus|cold sores|herpes)")
DIS_NL = (r"(?:ziekten|ziektes|ziekte|aandoeningen|aandoening|kanker|tumoren|tumor|diabetes|suikerziekte|hoge bloeddruk|"
          r"hypertensie|hart- en vaatziekten|hartziekten?|hartinfarct|beroerte|depressies?|angststoornis(?:sen)?|angst|"
          r"paniekaanvallen|slapeloosheid|insomnia|slaapstoornis(?:sen)?|slaapproblemen|migraine|hoofdpijn|artrose|artritis|"
          r"reuma|gewrichtspijn|rugpijn|spierpijn|menstruatiepijn|zenuwpijn|chronische pijn|ontstekingen|ontsteking|"
          r"infecties|infectie|griep|influenza|verkoudheid|verkoudheden|covid(?:-19)?|corona(?:virus)?|virussen|virus|"
          r"eczeem|psoriasis|acne|rosacea|allergie[eë]n|allergie|hooikoorts|astma|obstipatie|verstopping|diarree|"
          r"prikkelbare darm(?:syndroom)?|pds|maagzuur|reflux|maagzweer|maagklachten|darmklachten|gewrichtsklachten|"
          r"overgangsklachten|menstruatieklachten|huidklachten|luchtwegklachten|blaasontsteking|osteoporose|botontkalking|"
          r"alzheimer|dementie|adhd|candida|schimmelinfecties?|haaruitval|kaalheid|overgewicht|obesitas|erectieproblemen|"
          r"impotentie|jicht|tinnitus|koortslip)")
GAP = r"(?:\s+[\w'’-]+){0,3}?\s+"                      # up to three words between a claim verb and the condition
TREAT_EN = r"treat(?:s|ed|ing)?(?!\s+(?:yourself|you|them|us|her|him|me|your\s*(?:self|family|friends|kids|mum|mom|dad|team|loved)))"
VERB_EN = (r"\b(?:cur(?:e|es|ed|ing)|heal(?:s|ed|ing)?|" + TREAT_EN + r"|prevent(?:s|ed|ing)?|prevention of|"
           r"fight(?:s|ing)?|combat(?:s|ting|ing)?|beat(?:s|ing)?|reliev(?:e|es|ing)|relief (?:from|of)|revers(?:e|es|ing)|"
           r"protect(?:s|ing)? (?:you )?against|protection against|get(?:s)? rid of|stop(?:s)?|"
           r"(?:reduces?|lowers?) (?:the )?risk of)")
VERB_NL = (r"\b(?:geneest|genezen|genezing van|heelt|behandelt|behandelen|behandeling (?:van|tegen|bij)|voorkomt|"
           r"ter voorkoming van|helpt (?:bij )?het voorkomen van|bestrijdt|bestrijden|bestrijding van|verhelpt|verhelpen|"
           r"verlicht|verlichten|verlichting (?:van|bij)|helpt tegen|helpen tegen|werkt tegen|werken tegen|helpt bij|helpen bij|"
           r"beschermt tegen|beschermen tegen|bescherming tegen|af van|vermindert de kans op|verkleint de kans op|"
           r"verlaagt het risico op)")

ALC_EN = (r"\b(?:beers?|pints?|lagers?|ales|stouts?|ciders?|wines?|prosecco|champagne|cava|cocktails?|gin|whiske?y|rum|vodka|"
          r"tequila|liqueurs?|spritz|aperol|mojitos?|margaritas?|sangria|mimosas?|happy hour|booze)\b")
ALC_NL = (r"\b(?:bier\w*|speciaalbier\w*|pils(?:je|jes)?|wijn\w*|prosecco|champagne|"
          r"cava|cocktails?|gin(?:-?tonic)?|whiske?y|rum|wodka|vodka|tequila|likeuren?|jenever|borrel(?:tje)?|happy hour|"
          r"spritz|aperol|mojito'?s?|sangria)\b")

S = {   # sources (read 30.09.2026)
    "1924": "https://eur-lex.europa.eu/eli/reg/2006/1924/oj/eng",
    "register": "https://food.ec.europa.eu/food-safety/labelling-and-nutrition/nutrition-and-health-claims/eu-register-health-claims_en",
    "1169": "https://eur-lex.europa.eu/eli/reg/2011/1169/oj/eng",
    "ucpd": "https://eur-lex.europa.eu/eli/dir/2005/29/oj/eng",
    "pid": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52021XC1229(06)",
    "aldi": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62023CJ0330",
    "2024_825": "https://eur-lex.europa.eu/eli/dir/2024/825/oj/eng",
    "2001_83": "https://eur-lex.europa.eu/eli/dir/2001/83/oj/eng",
    "cosm_claims": "https://ec.europa.eu/docsroom/documents/24847",
    "cag": "https://keuringsraad.nl/wp-content/uploads/2025/10/CAG-2019-def.pdf",
    "kr_faq": "https://keuringsraad.nl/vraag-antwoord/",
    "kr_medical": "https://keuringsraad.nl/faq/wat-zijn-medische-claims/",
    "nl_codes": "https://www.reclamecode.nl/nederlandse-reclame-code/bijzondere-reclamecodes/",
    "gmw": "https://wetten.overheid.nl/BWBR0021505/",
    "igj_cosm": "https://www.igj.nl/zorgsectoren/cosmetische-zorg/geneesmiddelen-medische-hulpmiddelen-cosmetische-praktijk",
    "alcoholwet": "https://wetten.overheid.nl/BWBR0002458/",
    "nvwa_alc": "https://www.nvwa.nl/onderwerpen/alcoholverkoop/kortingen",
    "ksa": "https://kansspelautoriteit.nl/belangrijkste-regels-voor-kansspelreclame",
    "nl_gamble_2026": "https://www.rijksoverheid.nl/actueel/nieuws/2026/06/12/kabinet-scherpt-beleid-online-kansspelen-flink-aan",
    "bpp": "https://wetten.overheid.nl/BWBR0015104/",
    "acm_prices": "https://www.acm.nl/system/files/documents/acm-leidraad-prijsweergave-en-vergelijkingen.pdf",
    "nl_green": "https://zoek.officielebekendmakingen.nl/stb-2026-152.html",
    "asai": "https://adstandards.ie/wp-content/uploads/2024/03/ASAI-CODE_7th-Edition_Revision_2021.pdf",
    "ie_influencer": "https://adstandards.ie/wp-content/uploads/2024/11/ASA-Influencer-Guidance.pdf",
    "hpra": "https://www.hpra.ie/regulation/human-medicine/patients-and-healthcare-professionals/promoting-medicines-to-the-public-on-social-media",
    "phaa": "https://www.irishstatutebook.ie/eli/isbc/2018_24.html",
    "grai": "https://www.grai.ie/guidance-on-advertising-obligations",
    "ccpc_price": "https://www.ccpc.ie/information-for-businesses/selling-goods-and-services/pricing-and-price-reductions/price-reductions",
    "ie_cpa46": "https://www.irishstatutebook.ie/eli/2007/act/19/section/46/enacted/en/html",
    "fsai": "https://www.fsai.ie/enforcement-and-legislation/legislation/food-legislation/food-supplements",
    "be_2013": "https://www.ejustice.just.fgov.be/cgi_loi/change_lg.pl?language=nl&la=N&cn=2013052321&table_name=wet",
}

URGENCY = {
    "en": [r"\b(?:only today|today only|last chance|ends (?:tonight|today|at midnight|soon)|final hours|"
           r"only \d+ (?:left|remaining|spots? left|places? left)|almost sold out|nearly sold out|selling fast|limited stock|"
           r"last few (?:spots|places|items|pieces|seats)|only a few left|don'?t miss out|(?:24|48)[- ]hours? only)\b"],
    "nl": [r"\b(?:alleen vandaag|vandaag alleen|alleen nog vandaag|laatste kans|op\s?=\s?op|op is op|bijna uitverkocht|"
           r"nog (?:maar|slechts) \d+ (?:stuks|plekken|plaatsen|beschikbaar)|nog maar enkele|laatste (?:uren|plekken|stuks)|"
           r"eindigt (?:vanavond|vandaag|om middernacht|binnenkort)|wees er snel bij|mis het niet)\b"],
}

RULES = [
    # =========================================================================================== EU-wide
    {"id": "eu-disease-claim", "countries": ["EU"], "industries": ["*"], "not_industries": ["clinic", "b2b"],
     "severity": "block", "negatable": True,
     "title": "Disease claim: a product may not claim to prevent, treat or cure a disease",
     "why": "Food (incl. supplements) may not be presented as preventing, treating or curing a human disease (Reg. 1169/2011 "
            "art. 7(3)-(4)); claiming any product cures illnesses is a blacklisted unfair practice (UCPD Annex I No. 17). "
            "A cosmetic with a medicinal claim is regulated as a medicine.",
     "fix": "Drop the condition; use authorised wording such as 'Vitamine C draagt bij tot de normale werking van het "
            "immuunsysteem' / 'contributes to the normal function of the immune system'.",
     "source": [S["1169"], S["ucpd"], S["kr_medical"]],
     "patterns": {"en": [VERB_EN + GAP + DIS_EN + r"\b", r"\b(?:miracle cure|cure-?all|wonder cure|heals everything)\b"],
                  "nl": [VERB_NL + GAP + DIS_NL + r"\b", r"\btegen\s+(?:pijn|" + DIS_NL + r")\b",
                         r"\b(?:wondermiddel|wondermiddeltje|medicijn tegen alles|geneest alles)\b"]}},
    {"id": "eu-health-claim-wording", "countries": ["EU"], "industries": ["supplements", "cbd"], "severity": "needs-review",
     "negatable": True,
     "title": "Health claim wording that is not on the EU register",
     "why": "Only health claims authorised in the EU register may be used, in their authorised meaning; general benefits "
            "('good for you', 'superfood', 'boosts immunity', 'detox') need an authorised specific claim next to them "
            "(Reg. 1924/2006 art. 10(1), 10(3); ASAI 8.8-8.11; Keuringsraad claims database).",
     "fix": "Use the register wording (e.g. 'contributes to the normal function of the immune system') or remove the claim.",
     "source": [S["1924"], S["register"], S["asai"]],
     "patterns": {"en": [r"\b(?:boost(?:s|ing)?\s+(?:your\s+|the\s+)?(?:immune system|immunity|metabolism)|immune[- ]boost(?:ing|er|ers)?|"
                         r"strengthens?\s+(?:your\s+)?(?:immune system|immunity)|detox(?:es|ing|ify|ifying)?|cleanses? (?:your )?(?:body|liver|gut)|"
                         r"superfoods?|clinically proven|scientifically proven|proven to (?:work|help|boost|improve|reduce)|"
                         r"anti-?inflammatory|antiviral|burns? fat|fat[- ]burn(?:ing|er|ers)|"
                         r"natural alternative to (?:medication|medicine|antibiotics|painkillers)|"
                         r"good for your (?:health|body|gut|heart|immune system))\b"],
                  "nl": [r"\b(?:boost\s+(?:je\s+|jouw\s+|uw\s+)?(?:immuunsysteem|weerstand|metabolisme|stofwisseling)|"
                         r"versterkt\s+(?:je\s+|jouw\s+|uw\s+|de\s+)?(?:immuunsysteem|weerstand)|verhoogt\s+(?:je\s+|jouw\s+|uw\s+|de\s+)?weerstand|"
                         r"ontgift(?:en|ing|end|t)?|detox|zuivert (?:je |het )?(?:lichaam|lever|bloed)|superfoods?|klinisch bewezen|"
                         r"wetenschappelijk bewezen|bewezen (?:effectief|werkzaam)|ontstekingsremmend|antiviraal|vetverbrand(?:end|ing|er)|"
                         r"verbrandt vet|natuurlijk alternatief voor (?:medicijnen|geneesmiddelen|antibiotica|pijnstillers)|"
                         r"goed voor (?:je|jouw|uw) (?:gezondheid|lichaam|darmen|hart|weerstand))\b"]}},
    {"id": "eu-food-weightloss-doctor", "countries": ["EU"], "industries": ["supplements", "cbd", "food"], "severity": "block",
     "title": "Food claim with an amount of weight loss or a doctor's recommendation",
     "why": "Food and supplement claims may not state the rate or amount of weight loss, nor refer to recommendations of "
            "individual doctors or health professionals (Reg. 1924/2006 art. 12(b)-(c); ASAI 8.14(c),(f); CAG art. 7, 17).",
     "fix": "Remove the kilo figure / the 'recommended by doctors' line.",
     "source": [S["1924"], S["asai"], S["cag"]],
     "patterns": {"en": [r"\b(?:lose|lost|drop|shed|burn off)\s+(?:up to\s+)?\d+(?:[.,]\d+)?\s?(?:kg|kilos?|kilograms?|lbs?|pounds|stone)\b",
                         r"\b\d+\s?(?:kg|kilos?|lbs?|pounds)\s+(?:lighter|down|in\s+\d+\s+(?:days?|weeks?))",
                         r"\b(?:recommended|endorsed|approved) by (?:doctors|dietitians|dieticians|nutritionists|pharmacists|gps|physicians|dentists)\b",
                         r"\b(?:doctor|dietitian|nutritionist|pharmacist|gp)[- ](?:recommended|approved|endorsed)\b"],
                  "nl": [r"\b\d+(?:[.,]\d+)?\s?(?:kg|kilo'?s?)\s+(?:afvallen|kwijt|lichter|verliezen|eraf)\b",
                         r"\b(?:afvallen|verliezen|kwijtraken)\s+(?:tot\s+)?\d+\s?(?:kg|kilo'?s?)\b",
                         r"\b(?:aanbevolen|aangeraden|goedgekeurd)\s+door\s+(?:artsen|huisartsen|di[eë]tisten|apothekers|tandartsen|specialisten|dokters)\b",
                         r"\bdoor\s+(?:artsen|huisartsen|di[eë]tisten|apothekers|dokters)\s+(?:aanbevolen|aangeraden)\b"]}},
    {"id": "eu-prescription-medicine", "countries": ["EU"], "industries": ["*"], "severity": "block",
     "title": "Prescription-only medicine in public advertising (Botox, Ozempic …)",
     "why": "Public advertising of prescription-only medicines is banned (Directive 2001/83 art. 88(1); NL Geneesmiddelenwet "
            "art. 85 — the IGJ says cosmetic practices may not use POM brand names at all; IE S.I. 541/2007 reg. 9, HPRA "
            "names botulinum toxin, semaglutide and tirzepatide; ASAI 11.16).",
     "fix": "Describe the practice and the consultation, never the medicine: no brand or generic name, no 'anti-wrinkle injections'.",
     "source": [S["2001_83"], S["gmw"], S["igj_cosm"], S["hpra"]],
     "patterns": {"en": [r"\b(?:botox|botulinum|bocouture|azzalure|dysport|xeomin|vistabel|ozempic|wegovy|mounjaro|zepbound|saxenda|"
                         r"semaglutide|tirzepatide|liraglutide|viagra|cialis|sildenafil|tadalafil|finasteride|roaccutane|isotretinoin|"
                         r"anti-?wrinkle injections?|wrinkle[- ]relaxing injections?|weight[- ]loss (?:jabs?|injections?)|fat[- ]loss jabs?)\b"],
                  "nl": [r"\b(?:botuline\w*|anti-?rimpel ?injecties?|rimpelinjecties?|afslankprik|afvalprik|afslankspuit|afvalspuit)\b"]}},
    {"id": "eu-urgency-scarcity", "countries": ["EU"], "industries": ["*"], "not_industries": ["b2b"], "severity": "needs-review",
     "title": "Urgency or scarcity claim — must be true",
     "why": "Falsely stating that a product is available only for a very limited time or on particular terms to force a quick "
            "decision is blacklisted (UCPD Annex I No. 7; IE CPA 2007 s.55(1)(n); NL CCBA art. 2a bans time pressure for "
            "cosmetic treatments outright).",
     "fix": "Keep it only with the real end date or stock level, then record the review "
            "(otto_compliance.py review <id> eu-urgency-scarcity).",
     "source": [S["ucpd"], S["nl_codes"]], "patterns": URGENCY},
    {"id": "eu-price-reduction-30d", "countries": ["EU"], "industries": ["goods"], "severity": "needs-review",
     "clear_with": "prior_price_30d",
     "title": "Price reduction: the reference price must be the lowest price of the last 30 days",
     "why": "Every announced price reduction is measured against the lowest price of the 30 days before it (Price Indication "
            "Directive art. 6a; CJEU C-330/23 Aldi Süd: also for % discounts; NL BPP art. 5a; IE S.I. 597/2022 reg. 5A, "
            "goods only). A general '20% off everything' post is fine when the shop shows the 30-day prior price per product.",
     "fix": "Use the 30-day lowest price as the 'was' price. When the shop does this for every product (e.g. Shopify "
            "compare-at maintained), record it once: otto_compliance.py clear <brand> prior_price_30d \"<how>\".",
     "source": [S["pid"], S["aldi"], S["bpp"], S["acm_prices"], S["ccpc_price"]],
     "patterns": {"en": [r"\bwas\s*[€£]\s?\d", r"\bwas\s+\d+(?:[.,]\d+)?\s?(?:€|eur)\b",
                         r"\b(?:now|only)\s*[€£]\s?\d+(?:[.,]\d+)?\s*\(?\s*(?:was|instead of|rrp)\b",
                         r"\b(?:previously|normally|usually|regular price|reg\.)\s*[€£]\s?\d", r"\b\d{1,2}\s?%\s?off\b",
                         r"\bsave\s+\d{1,2}\s?%", r"(?<![\w-])-\s?\d{1,2}\s?%", r"(?<!for )(?<!te )\bsale\b",
                         r"\bblack friday\b", r"\bcyber monday\b", r"\bhalf[- ]price\b"],
                  "nl": [r"\bvan\s*€\s?\d+(?:[.,]\d+|[.,]-)?\s*(?:voor|nu)\s*€",
                         r"\bnu\s*€\s?\d+(?:[.,]\d+|[.,]-)?\s*\(?\s*(?:i\.?p\.?v\.?|in plaats van|was)\b",
                         r"\b(?:was|normaal|voorheen|oude prijs|adviesprijs)\s*:?\s*€\s?\d", r"\b\d{1,2}\s?%\s?korting\b",
                         r"\bkorting van\s+\d{1,2}\s?%", r"\buitverkoop\b", r"\bopruiming\b", r"\bhalve prijs\b"]}},
    {"id": "eu-price-incl-vat", "countries": ["EU"], "industries": ["*"], "not_industries": ["b2b"], "severity": "needs-review",
     "title": "Consumer price without VAT or with unavoidable fees left out",
     "why": "Prices to consumers include VAT and every unavoidable charge; leaving them out of an invitation to purchase is "
            "misleading (UCPD art. 7(4)(c); NL BPP art. 1a + BW 6:193e(c), ACM: booking/service/cleaning fees in the price; "
            "IE CPA 2007 s.46(3)(c)).",
     "fix": "Show the all-in consumer price; 'excl. btw' only in B2B-only ads.",
     "source": [S["ucpd"], S["bpp"], S["acm_prices"], S["ie_cpa46"]],
     "patterns": {"en": [r"\b(?:excl\.?|excluding|ex\.?|plus|\+)\s*vat\b",
                         r"\b(?:booking|service|cleaning|admin(?:istration)?) fees? (?:not included|extra|apply)\b"],
                  "nl": [r"\b(?:excl\.?|exclusief|ex\.?|plus|\+)\s*(?:btw|b\.t\.w\.)",
                         r"\b(?:excl\.?|exclusief)\s+(?:service|boekings|schoonmaak|reserverings|administratie)kosten\b"]}},
    {"id": "eu-free-trial-price", "countries": ["EU"], "industries": ["*"], "not_industries": ["b2b"], "severity": "disclose",
     "title": "Free trial or intro offer: say what it costs afterwards",
     "why": "'Free' is only free when nothing but unavoidable costs is paid (UCPD Annex I No. 20); the recurring price after "
            "a trial or intro price is material information (UCPD art. 7; NL BW 6:193e; IE CPA 2007 s.46).",
     "fix": "Add the price after the trial, e.g. 'daarna €19,95 per maand, maandelijks opzegbaar' / 'then €19.95 a month'.",
     "source": [S["ucpd"], S["ie_cpa46"]],
     "when": {"en": [r"\b(?:free trial|try (?:it )?(?:for )?free|first (?:month|box|week|lesson|class) (?:is )?free|\d+[- ]days? free)\b"],
              "nl": [r"\b(?:gratis proef(?:periode|les|abonnement)?|proefabonnement|eerste (?:maand|box|week|les) (?:is )?gratis|"
                     r"\d+ dagen gratis|probeer (?:het )?(?:\d+ dagen )?gratis)\b"]},
     "require": {"en": [r"\b(?:then|after(?:wards)?|thereafter)\b[^.!?\n]{0,40}(?:€|£|eur)\s?\d",
                        r"(?:€|£)\s?\d+(?:[.,]\d+)?\s*(?:/|per|a)\s*(?:month|week|year|mo)\b"],
                 "nl": [r"\b(?:daarna|hierna|vervolgens|na afloop|na de proef\w*)\b[^.!?\n]{0,40}€\s?\d",
                        r"€\s?\d+(?:[.,]\d+|[.,]-)?\s*(?:/|per|p/)\s*(?:maand|mnd|week|jaar)\b"]}},
    {"id": "eu-generic-green-claim", "countries": ["EU"], "industries": ["*"], "severity": "needs-review",
     "title": "Generic environmental claim ('eco-friendly', 'duurzaam') — banned since 27.09.2026 unless specified or certified",
     "why": "Generic environmental claims without recognised excellent environmental performance, and sustainability labels "
            "not based on a certification scheme, are blacklisted from 27.09.2026 (Directive 2024/825, UCPD Annex I 2a, 4a; "
            "NL BW 6:193g(ab)-(ad) and Code voor Duurzaamheidsreclame art. 3.1: 'duurzaam', 'bewust', 'verantwoord' never "
            "without a specification).",
     "fix": "Say exactly what and how much ('verpakking van 100% gerecycled karton'), or show the EU Ecolabel / ISO 14024 label. "
            "'Duurzaam' meaning long-lasting: write 'gaat jaren mee' instead.",
     "source": [S["2024_825"], S["nl_green"], S["nl_codes"]],
     "patterns": {"en": [r"\b(?:eco-?friendly|environmentally friendly|planet-?friendly|earth-?friendly|nature-?friendly|"
                         r"climate-?friendly|green(?:er)? (?:choice|alternative|product)|biodegradable|low[- ]carbon|"
                         r"sustainabl[ey]|conscious (?:choice|brand|living)|responsibly (?:made|produced)|net[- ]zero)\b"],
                  "nl": [r"\b(?:milieuvriendelijk\w*|milieubewust\w*|natuurvriendelijk\w*|klimaatvriendelijk\w*|ecologisch verantwoord\w*|"
                         r"zacht voor het milieu|koolstofarm\w*|biologisch afbreekbaar\w*|biogebaseerd\w*|duurzaam|duurzame|duurzamer|"
                         r"bewuste keuze|verantwoord (?:geproduceerd|gemaakt)|groene keuze|kies (?:voor )?groen|netto nul)\b"]}},
    {"id": "eu-offset-neutral-claim", "countries": ["EU"], "industries": ["*"], "severity": "block",
     "title": "'Climate neutral' / 'CO2-neutraal' claim based on offsetting",
     "why": "Claiming a neutral, reduced or positive climate impact based on offsetting is blacklisted from 27.09.2026 "
            "(Directive 2024/825, UCPD Annex I 4c; NL BW 6:193g(ae); CDR art. 3.1(3)).",
     "fix": "State the verified reduction of the product's own emissions instead, or remove it.",
     "source": [S["2024_825"], S["nl_green"]],
     "patterns": {"en": [r"\b(?:climate|carbon|co2)[- ](?:neutral|positive|negative|compensated)\b|\bcarbon[- ]offset(?:s|ting)?\b"],
                  "nl": [r"\b(?:klimaatneutraal|klimaatpositief|co2[- ]?neutra(?:al|le)|co2[- ]?gecompenseerd\w*|"
                         r"gecompenseerde (?:co2|uitstoot)|we compenseren (?:onze|de|alle) (?:co2|uitstoot))\b"]}},
    {"id": "eu-cosmetic-free-from", "countries": ["EU"], "industries": ["cosmetics", "aesthetic"], "severity": "needs-review",
     "title": "Cosmetic 'free from' / 'hypoallergenic' / 'chemical-free' claim",
     "why": "'Free from' claims that denigrate legally permitted ingredients (parabens, phenoxyethanol), 'chemical-free' and "
            "unproven 'hypoallergenic' fail the common criteria for cosmetic claims (Reg. 655/2013; Commission technical "
            "document on cosmetic claims 2017; NL Reclamecode Cosmetische Producten art. 2-3).",
     "fix": "Drop the 'free from', or keep a substantiated factual claim (e.g. 'parfumvrij' when it is).",
     "source": [S["cosm_claims"], S["nl_codes"]],
     "patterns": {"en": [r"\b(?:paraben[- ]?free|free (?:from|of) parabens|phenoxyethanol[- ]free|chemical[- ]free|"
                         r"toxin[- ]free|non-?toxic|hypoallergenic)\b"],
                  "nl": [r"\b(?:parabe(?:en|nen)[- ]?vrij|zonder parabenen|zonder phenoxyethanol|chemicali[eë]nvrij|"
                         r"zonder chemicali[eë]n|gifvrij|niet giftig|hypoallergeen)\b"]}},
    {"id": "eu-influencer-disclosure", "countries": ["EU"], "not_countries": ["NL", "IE"], "industries": ["*"],
     "severity": "disclose", "require_within": 120,
     "title": "Creator / partner post without an advertising label",
     "why": "Paid, gifted or affiliate content must say it is advertising, upfront (UCPD art. 7(2), Annex I No. 11, 22; "
            "Commission Influencer Legal Hub).",
     "fix": "Start the text with 'Ad |' / '#ad' (or the local word: Anzeige, Werbung, publicité, publicidad).",
     "source": [S["ucpd"]],
     "when": {"en": [r"(?:use|with)\s+my\s+(?:discount\s+)?code|\bmy\s+code\s+\w+|#gifted|#collab\b|\bcollab with\b|"
                     r"in (?:paid )?partnership with|#ambassador|brand ambassador|affiliate link|#affiliate|"
                     r"\bi (?:earn|get|receive) (?:a )?commission|#spon\b|#sp\b|\bpr (?:package|stay|invite|trip)\b"]},
     "require": {"en": [r"(?:^|[\s(\[])#?ad\b", r"#advert\w*|\badvertisement\b|\bpaid partnership\b|\bsponsored\b|#anzeige|"
                        r"\banzeige\b|#werbung|\bwerbung\b|publicit[eé]|publicidad|pubblicit[aà]|#reklame|\breklame\b"]}},
    {"id": "eu-gambling", "countries": ["EU"], "industries": ["gambling"], "severity": "block", "strong": False,
     "title": "Gambling marketing — Otto does not run it",
     "why": "NL: untargeted gambling ads banned since 1.7.2023, online ads only with ≥95% reach of 24+, sponsorship banned "
            "since 1.7.2025, a total online ban is being drafted (Besluit werving, reclame en verslavingspreventie kansspelen; "
            "Ksa); IE: Gambling Regulation Act 2024 advertising rules are pending and ASAI s.10 applies; Otto cannot verify "
            "licences or audience age.",
     "fix": "Not a vertical Otto serves.", "source": [S["ksa"], S["nl_gamble_2026"], S["grai"], S["asai"]]},
    {"id": "eu-gambling-offer", "countries": ["NL", "IE", "BE"], "industries": ["*"], "severity": "block",
     "title": "Gambling offer in the copy (bonus, free spins, bets)",
     "why": "Gambling promotion is restricted to licensed operators with verified adult targeting (NL Ksa: none at all "
            "without a licence; IE GRA 2024 / ASAI s.10).",
     "fix": "Remove the gambling offer.", "source": [S["ksa"], S["grai"]],
     "patterns": {"en": [r"\b(?:free spins|deposit bonus|welcome bonus|casino bonus|online casino|live casino|sportsbook|"
                         r"odds boost|bet now|place your bets?)\b"],
                  "nl": [r"\b(?:gratis spins|stortingsbonus|welkomstbonus|casinobonus|online casino|sportweddenschap\w*|wed nu|"
                         r"zet nu in)\b"]}},

    # =========================================================================================== Netherlands
    {"id": "nl-kag-preapproval", "countries": ["NL"], "industries": ["supplements", "cbd"], "strong": True,
     "contexts": ["posts"], "severity": "needs-review", "clear_with": "keuringsraad",
     "title": "Health product ad in NL: needs Keuringsraad pre-approval",
     "why": "Advertising for health products (food supplements, herbal products) in the Netherlands is pre-vetted by the "
            "Keuringsraad under the Code voor de Aanprijzing van Gezondheidsproducten (CAG 2019); brand pages get a KOAG/KAG "
            "number, trade members must use it and many media demand it, and the NVWA takes no action on pre-vetted ads.",
     "fix": "Get the brand page approved and record the number: otto_compliance.py clear <brand> keuringsraad \"KOAG/KAG …\".",
     "source": [S["cag"], S["kr_faq"]]},
    {"id": "nl-kag-ad-preapproval", "countries": ["NL"], "industries": ["supplements", "cbd"], "strong": True,
     "contexts": ["ads"], "severity": "needs-review",
     "title": "Health product ad in NL: needs Keuringsraad pre-approval",
     "why": "Each digital advertisement for a health product is pre-vetted by the Keuringsraad before it runs (CAG 2019; "
            "Keuringsraad social media guidance).",
     "fix": "Submit the ad texts + visuals to the Keuringsraad, then record its number on the campaign: "
            "otto_compliance.py review <cp-id> nl-kag-ad-preapproval --note \"KOAG/KAG …\".",
     "source": [S["cag"], S["kr_faq"]]},
    {"id": "nl-kag-number", "countries": ["NL"], "industries": ["supplements", "cbd"], "strong": True, "severity": "disclose",
     "title": "Health product ad in NL: show the KOAG/KAG approval number",
     "why": "The Keuringsraad approval number must be shown on every advertisement except labels, instructions and TV/radio.",
     "fix": "Add 'KOAG/KAG <nummer>' to the text.", "source": [S["kr_faq"]],
     "require": {"nl": [r"\b(?:KOAG\s*/\s*KAG|KOAG|KAG)\b", r"\btoelatingsnummer\b"]}},
    {"id": "nl-alcohol-nix18", "countries": ["NL"], "industries": ["*"], "severity": "disclose", "clear_with": "nix18_in_visuals",
     "always_for": ["alcohol"], "when": {"en": [ALC_EN], "nl": [ALC_NL]},
     "title": "Alcohol ad in NL: show the NIX18 logo",
     "why": "Every alcohol advertisement in the Netherlands shows the NIX18 logo in the image (≥1.25% of a social post, "
            "≥0.75% of video frames for 10 s); a caption mention only counts for influencers (Reclamecode voor "
            "Alcoholhoudende Dranken 2024 art. 23(2), 32).",
     "fix": "Put the NIX18 logo in the visual and 'NIX18' in the text, or record that the brand's templates carry it: "
            "otto_compliance.py clear <brand> nix18_in_visuals \"<how>\".",
     "source": [S["nl_codes"]], "require": {"en": [r"#?\bNIX\s?18\b"]}},
    {"id": "nl-alcohol-age-gate", "countries": ["NL"], "industries": ["*"], "severity": "needs-review", "clear_with": "age_gate_18",
     "min_age": 18, "always_for": ["alcohol"], "when": {"en": [ALC_EN], "nl": [ALC_NL]},
     "title": "Alcohol content in NL: 18+ age gate and 18+ targeting",
     "why": "Alcohol posts use the platform's 18+ age filter (organic and ads) and ads target 18+ only (RvA art. 23(3)-(4)); "
            "no alcohol ads on TikTok (art. 23(7)).",
     "fix": "Set the Instagram/Facebook account to 18+ and record it: otto_compliance.py clear <brand> age_gate_18 \"<date>\".",
     "source": [S["nl_codes"]]},
    {"id": "alcohol-themes", "countries": ["NL", "IE"], "industries": ["*"], "severity": "block",
     "always_for": ["alcohol"], "when": {"en": [ALC_EN], "nl": [ALC_NL]},
     "title": "Alcohol promotion: free or unlimited drinks, 2-for-1, health or success claims",
     "why": "NL RvA: no 'gratis', horeca offers not below half price and one discounted drink per person (art. 19, 25(3)), no "
            "health, performance or social/sexual success themes (art. 6-8), no excessive drinking (art. 1); IE ASAI 9.5, 9.8: "
            "no social/sexual success, no irresponsible or excessive drinking promotions.",
     "fix": "Promote the product, the place or the pairing — not the quantity, the price cut or an effect.",
     "source": [S["nl_codes"], S["asai"]],
     "patterns": {"en": [r"\bfree (?:drinks?|pints?|beers?|shots?|cocktails?|prosecco|glass of (?:wine|prosecco|bubbly))\b",
                         r"\b(?:2|two)[- ]for[- ](?:1|one)\b", r"\bbuy one,? get one free\b", r"\bbogof\b",
                         r"\bhealthy (?:beers?|wines?|cocktails?|drinks?)\b", r"\bgood for your (?:heart|health)\b",
                         r"\b(?:boosts?|gives you) (?:your )?(?:confidence|courage|performance)\b",
                         r"\bmakes you (?:more )?(?:attractive|sexy|popular)\b"],
                  "nl": [r"\bgratis (?:drankjes?|biertjes?|wijntjes?|glas|glaasje|shots?|cocktails?|borrel|prosecco|consumpties?)\b",
                         r"\b(?:drankjes?|biertjes?|wijntjes?|cocktails?|shots?) gratis\b",
                         r"\b(?:2|twee) (?:voor|halen) (?:1|één|een)\b", r"\b1\s?\+\s?1\b",
                         r"\bgezond(?:e|er)? (?:biertje|wijntje|drankje)\b", r"\bgoed voor je (?:hart|gezondheid)\b",
                         r"\bmeer zelfvertrouwen\b"]}},
    {"id": "alcohol-excess", "countries": ["NL", "IE"], "industries": ["*"], "severity": "block",
     "title": "Promotion of excessive drinking (unlimited, bottomless, drinking games)",
     "why": "Alcohol marketing may not encourage excessive or irresponsible drinking (NL RvA art. 1; IE ASAI 9.8); these "
            "offers are alcohol promotions by themselves.",
     "fix": "Drop the unlimited / bottomless / game angle; promote the food, the music, the place.",
     "source": [S["nl_codes"], S["asai"]],
     "patterns": {"en": [r"\b(?:unlimited|bottomless|endless) (?:drinks|prosecco|mimosas|cocktails|beers?|wine|brunch|booze)\b",
                         r"\ball[- ]you[- ]can[- ]drink\b", r"\bfree (?:pints|beers|shots|booze)\b", r"\bdown (?:it )?in one\b",
                         r"\bdrinking games?\b"],
                  "nl": [r"\bonbeperkt (?:drinken|bier|wijn|cocktails|prosecco)\b", r"\bbottomless\b", r"\badten\b",
                         r"\bin één teug\b", r"\b(?:coma)?zuipen\b", r"\bdrinkspel\w*\b"]}},
    {"id": "nl-alcohol-offtrade-discount", "countries": ["NL"], "industries": ["alcohol", "goods"], "severity": "block",
     "when": {"en": [ALC_EN], "nl": [ALC_NL]},
     "title": "Alcohol sold for home use at more than 25% off",
     "why": "Selling alcohol for consumption elsewhere below 75% of the usual price — or creating that impression — is "
            "banned; multibuys count (Alcoholwet art. 2a; NVWA).",
     "fix": "Keep alcohol discounts at 25% or less (a 'tweede halve prijs' is exactly 25%).",
     "source": [S["alcoholwet"], S["nvwa_alc"]],
     "patterns": {"en": [r"\b(?:2[6-9]|[3-9]\d)\s?%\s?(?:off|discount)\b", r"(?<![\w-])-\s?(?:2[6-9]|[3-9]\d)\s?%",
                         r"\b3 for 2\b", r"(?<!second )\bhalf[- ]price\b"],
                  "nl": [r"\b(?:2[6-9]|[3-9]\d)\s?%\s?(?:korting|goedkoper)\b", r"\b3 (?:halen|voor) 2\b", r"\b2\s?\+\s?1\b",
                         r"\b1\s?\+\s?1\b", r"(?<!tweede )(?<!2e )(?<!tweede fles )(?<!2e fles )\bhalve prijs\b",
                         r"\btweede (?:fles )?gratis\b"]}},
    {"id": "nl-aesthetic-big", "countries": ["NL"], "industries": ["aesthetic"], "severity": "disclose",
     "clear_with": "big_details_linked",
     "title": "Cosmetic medical treatment ad in NL: name the doctor's title and BIG number",
     "why": "Advertising for cosmetic medical treatments states the doctor's title, function and BIG registration number, or "
            "links to them (Code Cosmetische Behandelingen door Artsen (CCBA) art. 5).",
     "fix": "Add e.g. 'Dr. A. Jansen, cosmetisch arts KNMG, BIG 12345678901', or record that the profile links to the BIG "
            "details: otto_compliance.py clear <brand> big_details_linked \"<url>\".",
     "source": [S["nl_codes"]], "require": {"nl": [r"\bBIG\b[- ]?(?:nummer|nr|registratie|geregistreerd|register)?"]}},
    {"id": "nl-aesthetic-before-after", "countries": ["NL"], "industries": ["aesthetic"], "severity": "needs-review",
     "title": "Before/after for a cosmetic treatment in NL",
     "why": "The IGJ does not allow before/after images or positive client reviews that promote a prescription treatment; for "
            "other treatments results must be realistic and typical (IGJ; CCBA).",
     "fix": "Remove the before/after, or confirm the treatment is not a prescription medicine and the result is typical.",
     "source": [S["igj_cosm"], S["nl_codes"]],
     "patterns": {"en": [r"\bbefore\s*(?:and|&|/)\s*after\b|\bbefore-after\b"], "nl": [r"\bvoor\s*(?:en|&|/|-)\s*na\b|\bvoor-?\s?en\s?na\b"]}},
    {"id": "aesthetic-minors", "countries": ["NL", "IE", "BE"], "industries": ["aesthetic"], "severity": "block", "min_age": 18,
     "contexts": ["ads", "posts"],
     "title": "Cosmetic treatment marketing aimed at under-18s",
     "why": "Cosmetic treatments are not marketed to minors (NL CCBA art. 3; IE ASAI s.7 — children are under 18; Meta limits "
            "these ads to 18+). Irish clinics are known to target the Debs.",
     "fix": "Remove the teen / school-event angle; ads target 18+ only.", "source": [S["nl_codes"], S["asai"]],
     "patterns": {"en": [r"\b(?:teens?|teenagers?|debs|prom|school formal|back to school|under[- ]18s?|16\+|17[- ]year[- ]olds?)\b"],
                  "nl": [r"\b(?:tieners?|pubers?|eindexamen\w*|examenfeest|galafeest|schoolfeest|onder de 18|16\+)\b"]}},
    {"id": "health-guarantee", "countries": ["NL", "IE", "BE"], "industries": ["supplements", "cbd", "cosmetics", "aesthetic", "clinic", "fitness"],
     "severity": "block", "negatable": False,
     "title": "Guarantee, 'risk-free' or 'no side effects' claim for a health or beauty product or treatment",
     "why": "Health products may not promise guaranteed or permanent results or deny side effects (NL CAG art. 20, 23); "
            "cosmetic doctors may not say 'zonder risico' or offer money-back guarantees (CCBA art. 4.2-4.3); ASAI 11.10: "
            "nothing 'works in every case'.",
     "fix": "Describe typical results and who it suits; never guarantee.", "source": [S["cag"], S["nl_codes"], S["asai"]],
     "patterns": {"en": [r"\b(?:guaranteed (?:results?|to work|weight loss|success)|results guaranteed|(?:100%|completely|totally) "
                         r"(?:safe|risk[- ]free)|risk[- ]free (?:treatment|procedure)|no side[- ]effects|without (?:any )?side[- ]effects|"
                         r"works (?:for everyone|in every case|every time)|permanent results)\b"],
                  "nl": [r"\b(?:gegarandeerd(?:e)? (?:resultaat|resultaten|succes|effect)|resultaat gegarandeerd|werkzaamheid "
                         r"gegarandeerd|blijvend resultaat|zonder (?:enige )?bijwerkingen|geen bijwerkingen|100% veilig|volkomen "
                         r"veilig|zonder risico'?s?|risicoloos|werkt (?:bij iedereen|altijd)|niet goed,? geld terug)\b"]}},

    {"id": "nl-influencer-disclosure", "countries": ["NL"], "industries": ["*"], "severity": "disclose", "require_within": 120,
     "title": "Creator / partner post in NL without an advertising label upfront",
     "why": "Content by influencers, creators or UGC makers for a brand (paid, gifted, discount code, affiliate) says so in "
            "the first word or sentence: 'AD', 'Reclame', 'Advertentie', '(Betaalde) samenwerking' with the brand named, "
            "'gekregen van @…', 'Ik ontvang commissie'; #spon / #adv / #sponsored are no longer on the list (Reclamecode "
            "Social Media & Influencer Marketing 2026 art. 3; video uploaders: Commissariaat voor de Media).",
     "fix": "Start the text with 'AD |' or 'Betaalde samenwerking met @merk'.", "source": [S["nl_codes"]],
     "when": {"en": [r"(?:use|with)\s+my\s+(?:discount\s+)?code|#gifted|#collab\b|#ambassador|affiliate|#spon\b|#adv\b|#sponsored"],
              "nl": [r"(?:met|gebruik)\s+mijn\s+(?:kortings)?code|mijn\s+kortingscode|\bik ontvang (?:een )?commissie|"
                     r"#samenwerking|#gesponsord|gesponsord door|ambassadeur van|gekregen van @|uitgenodigd door @"]},
     "require": {"nl": [r"(?:^|[\s(\[])(?:#?ad|reclame|advertentie|advertorial)\b", r"(?:^|[\s#(\[])(?:#?reclame|#?advertentie)",
                        r"\b(?:betaald\s+)?partnerschap\b", r"\b(?:betaalde\s+)?(?:promotie|samenwerking)\s+(?:met\s+)?@?\w",
                        r"\bgekregen van\b", r"\buitgenodigd door\b", r"\bik ontvang (?:een )?commissie\b"]}},

    # =========================================================================================== Ireland
    {"id": "ie-influencer-disclosure", "countries": ["IE"], "industries": ["*"], "severity": "disclose", "require_within": 120,
     "title": "Creator / partner post in Ireland without #Ad upfront",
     "why": "Influencer marketing must carry #Ad (or #Fógra / the platform's 'Paid partnership'; #Gifted only for unsolicited "
            "gifts) as the first word; #sp, #spon and #collab are not enough (CCPC/ASA Influencer Marketing Guidance 2023; "
            "ASAI 3.31-3.34).",
     "fix": "Start the text with '#Ad'.", "source": [S["ie_influencer"], S["asai"]],
     "when": {"en": [r"(?:use|with)\s+my\s+(?:discount\s+)?code|\bmy\s+code\s+\w+|#collab\b|\bcollab with\b|"
                     r"in (?:paid )?partnership with|#ambassador|brand ambassador|#brandambassador|affiliate link|#affiliate|"
                     r"\bi (?:earn|get|receive) (?:a )?commission|#spon\b|#sp\b|#sponsored|\bsponsored by\b|"
                     r"\bpr (?:package|stay|invite|trip|drop)\b|#pr(?:stay|invite|drop)?\b"]},
     "require": {"en": [r"(?:^|[\s(\[])#ad\b", r"(?:^|[\s(\[])ad\s*[|\-–:]", r"#f[óo]gra\b", r"\bpaid partnership\b", r"#gifted\b"]}},
    {"id": "ie-alcohol-responsible", "countries": ["IE"], "industries": ["*"], "severity": "disclose",
     "always_for": ["alcohol"], "when": {"en": [ALC_EN]},
     "title": "Alcohol ad in Ireland: add a responsible-drinking message",
     "why": "Alcohol marketing communications include a responsible-drinking message (ASAI 9.4); people shown are over 25 "
            "(9.7(a)); digital media promoting an alcohol brand are age-gated (9.7(f)).",
     "fix": "Add e.g. 'Please enjoy responsibly. drinkaware.ie'.", "source": [S["asai"]],
     "require": {"en": [r"\bdrink (?:responsibly|sensibly)\b|\benjoy (?:\w+ )?responsibly\b|drinkaware|askaboutalcohol|#drinkresponsibly"]}},
    {"id": "ie-alcohol-age-gate", "countries": ["IE"], "industries": ["alcohol"], "strong": False, "severity": "needs-review",
     "clear_with": "age_gate_18", "min_age": 18,
     "title": "Alcohol brand in Ireland: age-gated pages and 18+ targeting",
     "why": "Digital media that mainly promote an alcohol brand are age-gated (ASAI 9.7(f)); promotions are 18+ (9.9).",
     "fix": "Set the accounts to 18+ and record it: otto_compliance.py clear <brand> age_gate_18 \"<date>\".",
     "source": [S["asai"]]},
    {"id": "ie-alcohol-health-warnings", "countries": ["IE"], "industries": ["*"], "severity": "disclose", "active": False,
     "status": "pending: Public Health (Alcohol) Act 2018 s.13(1)-(3) and (7)-(11) not commenced (Irish Statute Book, 17.09.2026)",
     "always_for": ["alcohol"], "when": {"en": [ALC_EN]},
     "title": "Alcohol ad health warnings (Public Health (Alcohol) Act 2018 s.13) — not in force yet",
     "why": "Once commenced, alcohol ads must carry warnings on the danger of alcohol, drinking in pregnancy and fatal cancers, "
            "plus an HSE website, and may only contain the listed content (s.13(2), (7)).",
     "fix": "Nothing yet; switch on (active) when the Minister commences s.13.", "source": [S["phaa"]],
     "require": {"en": [r"\bcancer\b[^.]{0,80}\bpregnan"]}},
    {"id": "ie-weight-loss-period", "countries": ["IE"], "industries": ["*"], "severity": "block",
     "title": "Specific weight loss in a stated period",
     "why": "Marketing may not claim a specific amount of weight loss within a stated period; more than 1 kg a week is not "
            "compatible with good practice (ASAI 12.13-12.14, 12.17).",
     "fix": "Remove the kilo/period promise.", "source": [S["asai"]],
     "patterns": {"en": [r"\b(?:lose|drop|shed)\s+(?:up to\s+)?\d+(?:[.,]\d+)?\s?(?:kg|kilos?|lbs?|pounds|stone)\s+(?:in|within)\s+"
                         r"(?:just\s+|only\s+)?\d+\s+(?:days?|weeks?|months?)\b",
                         r"\b(?:drop|lose)\s+a\s+(?:dress\s+)?size\s+in\b", r"\b\d+\s?(?:kg|lbs?|pounds)\s+(?:a|per)\s+week\b"]}},
    {"id": "ie-cure-rejuvenation", "countries": ["IE"], "industries": ["clinic", "cosmetics", "aesthetic", "supplements", "cbd", "fitness"],
     "severity": "needs-review", "negatable": True,
     "title": "'Cure' or 'rejuvenation' claim in Ireland",
     "why": "'Cure' and 'rejuvenation' claims are not generally acceptable in health and beauty marketing (ASAI 11.9); "
            "medicinal claims only for HPRA/EMA-authorised products or CE-marked devices (11.1).",
     "fix": "Describe the treatment and typical outcome instead.", "source": [S["asai"]],
     "patterns": {"en": [r"\bcur(?:e|es|ed|ing)\b", r"\brejuvenat(?:e|es|ing|ion)\b"]}},

    # =========================================================================================== Belgium (Flanders spillover)
    {"id": "be-aesthetic-ban", "countries": ["BE"], "industries": ["*"], "severity": "block",
     "title": "Belgium: advertising for aesthetic medicine and cosmetic surgery is banned",
     "why": "Anyone is forbidden to advertise non-surgical aesthetic medicine or cosmetic surgery in Belgium; only factual "
            "practice information by the practitioner, without prices or discounts and with professional titles, is allowed "
            "(Law of 23 May 2013 art. 20/1; upheld by the Constitutional Court 1/2016). Penalty: prison 8 days-6 months "
            "and/or €250-5,000.",
     "fix": "Do not target Belgium with this content (exclude BE from the audience).", "source": [S["be_2013"]],
     "patterns": {"en": [r"\b(?:fillers?|lip ?fillers?|dermal fillers?|hyaluronic (?:acid )?(?:fillers?|injections?)|liposuction|lipo|"
                         r"breast (?:augmentation|enlargement|lift)|tummy tuck|facelift|rhinoplasty|blepharoplasty|eyelid surgery|"
                         r"aesthetic (?:medicine|treatments?|procedures?|surgery)|cosmetic (?:surgery|procedures?|treatments?)|"
                         r"injectables|skin ?boosters?|profhilo|thread ?lift|mesotherapy|cryolipolysis|coolsculpting)\b"],
                  "nl": [r"\b(?:lipvergroting|lippen opvullen|rimpelbehandeling\w*|liposuctie|borstvergroting|borstcorrectie|"
                         r"buikwandcorrectie|ooglidcorrectie|neuscorrectie|esthetische (?:geneeskunde|chirurgie|behandelingen?|ingrepen?)|"
                         r"cosmetische (?:chirurgie|ingrepen?|behandelingen?)|plastische chirurgie|draadlift|mesotherapie|cryolipolyse)\b"],
                  "fr": [r"\b(?:m[ée]decine esth[ée]tique|chirurgie esth[ée]tique|injections? (?:de )?(?:botox|acide hyaluronique)|"
                         r"comblement des rides|augmentation mammaire|liposuccion|rhinoplastie|bl[ée]pharoplastie)\b"]}},
    {"id": "be-aesthetic-practice", "countries": ["BE"], "industries": ["aesthetic"], "strong": False, "severity": "block",
     "title": "Belgium: an aesthetic practice may only publish practice information",
     "why": "The Belgian ban covers all advertising for the procedures (Law of 23 May 2013 art. 20/1); Otto does not write "
            "marketing for aesthetic practices aimed at Belgium.",
     "fix": "Exclude Belgium from this brand's countries and audiences.", "source": [S["be_2013"]]},
]

# Legally required texts that name the words a claim would use: never read as claims (removed before the scan).
DISCLAIMERS = [
    r"\*?\s*these statements have not been evaluated by the (?:u\.?s\.? )?(?:food (?:and|&) drug administration|fda)\s*\.?\s*"
    r"this product is not intended to diagnose,? treat,? cure,? or prevent any disease\.?",
    r"(?:this product is )?not intended to (?:diagnose|treat|cure|prevent|mitigate)(?:,?\s*(?:or\s+)?(?:diagnose|treat|cure|prevent|mitigate))*"
    r"\s+any (?:disease|illness|condition)s?\.?",
    r"(?:dit (?:product|supplement) is )?niet bedoeld (?:om|voor)(?: een| enige| het)? (?:ziekten?|ziektes|aandoeningen?)\s+(?:te\s+)?"
    r"(?:(?:te\s+)?(?:diagnosticeren|behandelen|genezen|voorkomen|verhelpen)[,\s]*(?:of\s+)?)+\.?",
    r"(?:dieses produkt ist )?nicht dazu bestimmt,?\s+(?:eine\s+)?krankheit(?:en)?\s+(?:zu\s+)?"
    r"(?:(?:zu\s+)?(?:diagnostizieren|behandeln|heilen|verhindern|lindern)[,\s]*(?:oder\s+)?)+\.?",
    r"(?:food )?supplements? should not be used as a substitute for a varied (?:and balanced )?diet(?: and a healthy lifestyle)?\.?",
    r"een voedingssupplement is geen vervanging (?:van|voor) een gevarieerd(?:e)? (?:en evenwichtig(?:e)? )?"
    r"voedingspatroon(?: en een gezonde levensstijl)?\.?",
    r"lees voor gebruik (?:altijd )?de bijsluiter\.?",
]

# a negation between the claim verb and the condition: "geneest geen verkoudheid", "does not really cure"
NEG_INSIDE = re.compile(r"\b(?:not|never|no|niet|nooit|geen)\b", re.I)
# a negation within a few words before a claim, in the same clause: "does not cure", "can't treat", "geneest geen"
NEGATION = re.compile(r"(?:\b(?:not|never|no|cannot|niet|nooit|geen|kein|keine|nicht)\b|n't)"
                      r"(?!\s+(?:only|just|alleen|enkel|meer|more)\b)[^.!?\n,;:]{0,20}$", re.I)
