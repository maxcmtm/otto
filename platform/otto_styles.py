#!/usr/bin/env python3
"""Otto ad styles — the catalogue of ad executions and the angle × style matrix every Facebook campaign runs.

  otto_styles.py list                 # the catalogue: style → template, family, sizes, video kit, fields, needs + the slots
  (the matrix CLI is in otto_creative.py: matrix <brand> <YYYY-MM> --plan | --check | --render <out_dir>)

Why: accounts that sell on Meta test many angles × many executions. Grüns (research/GRUNS-AD-LIBRARY-2026-09.md,
research/gruns-ads/taxonomy.json: 823 ads, 674 unique creatives, 32 angles, 59 styles) runs every serious angle in a median
9.5 styles / 6.5 of 11 style families, 63 % of creatives are video (45 % UGC video), and 1-2 headlines per angle sit on many
visuals. Otto prepares every client the same way:

  brands/<id>/ads-<YYYY-MM>.json
  {"brand", "month", "preset": "launch" | "micro", "rules": {…optional overrides…},
   "angles": [{"id", "name", "family": pain|identity|enemy|experience|offer|moment, "angle" (strategist note, never
               rendered), "source", "persona", "stage", "kinds", "ad_set",
               "headlines": [1-2, reused across the angle's visuals], "primaries": [2-3], "description", "cta",
               "ads": [{"id", "style", "slot", "format": "image" | "video" | "creator", "size": "feed" | ["feed", "story"],
                        "data": {…the template's fields…},                                        image cells
                        "video": {"kit": "notes", "data": "video/2026-10/a1-notes_app.json"},    video cells (ad-kit / reel
                                 data relative to brands/<id>/; otto_motion renders it and sets the cell's "file")
                        "creator": {"persona", "hook", "script", "shot_list", "length", "disclosure",
                                    "name", "consent"},                                          creator cells ("file" =
                                 the real creator's footage, set when it arrives)
                        "brief", "added": "YYYY-MM-DD",
                        "primary" / "headline" / "description" / "cta" (optional per-cell overrides of the angle's copy),
                        "status": "dropped" (optional — the copywriter parks a cell) | "hold" + "hold_reason"
                                  ("licence pending": reported by --check, never launched, out of coverage)}]}]}

One angle = one concept = one Meta ad set whose ads are the styles (otto_ads.launch_meta), so Meta tests executions
inside a concept and concepts against each other. The copy is angle-level on purpose — the test is about the visual:
cell i runs headline i mod len(headlines) and primary i mod len(primaries). `angle` and `brief` are never rendered.

Formats: image (a template in templates/ads/), video (faceless: the HyperFrames ad kit in motion/ad-kit — text-overlay POV —
or the otto_motion reel — voiceover b-roll; fully automatic), creator (a UGC talking head by a REAL creator: Otto writes
the brief, script and shot list, the cell fills when the footage arrives with the creator's name and consent. Never an
AI-generated person presented as a customer — FTC / Meta deception; until the footage exists the cell is "planned",
which coverage counts and --check does not fail).

Coverage (coverage(), rules below, tunable per matrix via "preset" + "rules"). LAUNCH (from the Grüns scan, §f):
  6 angles, one per angle family (pain, identity, enemy, experience, offer, moment — month 1 may run a second identity
  angle instead of a moment) · ≥1 angle from competitor research · 6 styles per angle in ≥4 style families, filling the
  slots: creator (UGC talking head) · faceless video · product · comparison (before_after / us_vs_them) · native screenshot
  (notes_app / text_message / search / social_post) · proof or humor (review_cards / quote / big_number / editorial …) ·
  a price card (offer) on the offer angle and on hot-stage angles · ≥50 % video (creator + faceless; one static slot per
  angle runs as its motion version) and ≥2 video + ≥2 static per angle · story 9:16 on ≥50 % of cells · ≥10 styles overall ·
  1-2 headlines and 2-3 primary texts per angle (check_matrix).
MICRO (daily budget under MICRO_BELOW_DAILY_EUR): 4 angles (pain, identity, enemy, offer) × 5 styles (slots creator,
  faceless, product, comparison, native), never fewer than 4 style families per angle.
Refresh (refresh_gaps, after launch): +2 new creatives per angle per week, each on a style the angle has not run.
plan_matrix(bid) writes nothing: it returns a deterministic skeleton — angles assigned to families, styles picked per slot
by fit (angle kind, stage) and by what the brand really has (no review styles without verbatim reviews, no product styles
without a product image, no offer without a real offer), maximising variety, each cell with a brief for the copywriter.
Reviews must be verbatim from proof_bank; no ad names a competitor from competitors.json; every cell's texts (a creator's
script included) pass otto_compliance before anything renders (otto_creative.build).
"""
import json, math, os, re, sys
from datetime import date, timedelta
from pathlib import Path

import ap

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATES = Path(os.environ.get("OTTO_TEMPLATES") or HERE / "templates" / "ads")
SIZES = {"feed": (1080, 1350), "story": (1080, 1920), "square": (1080, 1080)}
# style families of the catalogue (a video cell counts as "faceless_video" or "ugc_video": cell_family(); research: 11 families)
FAMILIES = ("native", "people", "proof", "comparison", "product", "offer", "editorial", "ugc_video")
ANGLE_FAMILIES = ("pain", "identity", "enemy", "experience", "offer", "moment")
KINDS = ("competitor", "objection", "proof", "benefit", "offer", "audience", "education")
STAGES = ("cold", "warm", "hot")
FORMATS = ("image", "video", "creator")
META_CTAS = {"SHOP_NOW", "LEARN_MORE", "SIGN_UP", "ORDER_NOW", "BUY_NOW", "GET_OFFER", "SUBSCRIBE", "BOOK_TRAVEL", "CONTACT_US",
             "APPLY_NOW", "DOWNLOAD", "GET_QUOTE", "SEE_MORE", "WATCH_MORE", "SEND_MESSAGE", "WHATSAPP_MESSAGE", "BOOK_NOW"}


def _st(template, family, sizes, stages, kinds, required, optional="", needs=(), video=None, desc="", cards=None):
    s = {"template": template, "family": family, "sizes": sizes.split(), "stages": stages.split(), "kinds": kinds.split(),
         "fields": {"required": required.split(), "optional": optional.split()}, "needs": list(needs), "video": video, "desc": desc}
    if cards:
        s["cards"] = cards
    return s


# style → how it renders (template), what it is for (family, stages, angle kinds), what the copywriter fills (fields), what the
# brand must have for it (needs), its motion version (video: an ad-kit style in motion/ad-kit, or "reel" = otto_motion)
STYLES = {
    # native screenshot — looks like something a person made on their phone, not an ad
    "notes_app": _st("notes_app", "native", "feed story square", "cold warm", "audience benefit objection education",
                     "title items", "mode date_label footer photo headline theme tag cta", (), "notes",
                     "A phone Notes list in the customer's own words ('things I stopped buying', 'why I switched')."),
    "search": _st("search", "native", "feed story square", "cold warm hot", "objection competitor education proof audience",
                  "query", "mode suggestions results photo headline headline_pos theme tag cta", (), "search",
                  "A search page: the query people really type, as autocomplete or results with the brand's listing."),
    "text_message": _st("text_message", "native", "feed story square", "cold warm", "audience objection benefit proof competitor",
                        "contact messages", "photo time receipt initials portrait headline theme tag cta", (), "texts",
                        "A phone chat: a friend recommending it in plain words, or clearly the brand replying (support, order)."),
    "social_post": _st("social_post", "native", "feed square story", "cold warm", "audience proof benefit competitor",
                       "name text", "handle verified avatar_logo portrait initials photo time replies reposts likes ui headline "
                       "theme tag cta", (), None,
                       "A shared text post: the brand posting, or a real customer quoted verbatim (with consent)."),
    # people photo
    "ugc_caption": _st("ugc_caption", "people", "story feed square", "cold warm", "audience benefit proof objection",
                       "photo captions", "caption_pos handle logo photo_pos", ("person_photo",), None,
                       "A real person photo with short-video text stickers, first person (a still, never generated)."),
    # proof
    "review_cards": _st("review_cards", "proof", "feed story square", "cold warm hot", "proof objection competitor audience",
                        "reviews", "summary headline layout photo photo_pos footnote theme tag", ("reviews:2",), None,
                        "1-3 verbatim review cards ({text, name, detail, title, rating, verified}) with the star summary."),
    "quote": _st("quote", "proof", "feed story", "cold warm hot", "proof objection audience competitor",
                 "quote name", "detail rating note portrait photo theme cta tag", ("reviews",), None,
                 "One verbatim customer review, set big."),
    "big_number": _st("big_number", "proof", "feed story", "cold warm", "proof benefit education offer",
                      "number label", "suffix kicker body source theme photo cta tag", ("number",), "big",
                      "One sourced proof figure set huge (6 g, 4.8 stars, 100,000+)."),
    # comparison
    "us_vs_them": _st("us_vs_them", "comparison", "feed square story", "cold warm hot", "competitor objection offer",
                      "headline us them rows", "footnote kicker theme us_photo them_photo", (), "versus",
                      "The brand against a generic category ('powder greens'), row by row. Never a competitor's name."),
    "comparison": _st("comparison", "comparison", "feed square", "cold warm", "competitor objection education offer",
                      "title columns rows", "kicker footnote photo theme cta tag", (), "versus",
                      "The brand's option vs the category's usual way, as a table."),
    "before_after": _st("before_after", "comparison", "feed square", "cold warm", "objection competitor benefit",
                        "before after", "kicker before_label after_label photo_after photo_before cta tag", (), None,
                        "The situation before and after (a routine, a chore), never bodies or symptoms."),
    # product
    "product_hero": _st("product_hero", "product", "feed story square", "warm hot", "benefit offer proof",
                        "headline photo", "callouts price price_note rating rating_line kicker tag cta theme callout_style",
                        ("product_image",), "reel",
                        "The product photo with 2-4 callouts, the price and a rating line."),
    "macro_hero": _st("macro_hero", "product", "feed story square", "cold warm", "benefit education audience",
                      "photo word", "sub kicker cta crop theme zoom no_disc photo_pos", ("product_image",), "big",
                      "The product shown huge (macro crop) with one word."),
    "ingredients": _st("ingredients", "product", "feed square story", "cold warm", "education proof benefit objection",
                       "headline photo items", "kicker footnote cta tag theme", ("product_image", "ingredients"), "reel",
                       "The product at the centre, 3-6 ingredients around it ({name, note, photo}), one line each."),
    # offer
    "offer": _st("offer", "offer", "feed story square", "warm hot", "offer",
                 "name cta", "price price_note was features terms kicker photo theme", ("offer",), None,
                 "The price card: the real offer, what is included, one CTA. A transparent packshot stands whole beside it."),
    "event": _st("event", "offer", "feed story", "warm hot", "offer audience",
                 "title date cta", "time details kicker photo theme", ("event",), None,
                 "A dated event card (launch, open day, seasonal drop). Real dates only."),
    # editorial / humor
    "editorial": _st("editorial", "editorial", "feed story square", "cold warm hot",
                     "benefit audience education proof competitor objection offer",
                     "headline", "sub kicker tag cta photo layout", ("photo",), "reel",
                     "Photo + one headline: the control, or a meme-style statement."),
    "carousel": _st("carousel_cover", "editorial", "feed square", "cold warm", "education benefit objection proof",
                    "cover slides end", "", (), None, "3-6 cards: the hook, 1-4 points, one ask.",
                    cards=["carousel_cover", "carousel_inner", "carousel_cta"]),
    "myth_fact": _st("myth_fact", "editorial", "feed square", "cold warm", "objection education proof",
                     "myth fact", "kicker source theme cta tag", ("proof",), None,
                     "A common belief struck out and the sourced fact."),
    "checklist": _st("checklist", "editorial", "feed square", "warm hot", "education audience benefit",
                     "title items", "kicker footnote theme cta tag", (), None,
                     "N things to check before buying, every one of which the brand passes."),
    "founder_note": _st("founder_note", "editorial", "feed square", "cold warm", "audience benefit objection",
                        "body name", "role headline kicker portrait theme cta tag", ("founder",), None,
                        "A short, true letter from the founder."),
    # UGC video — a real creator on camera (format "creator"; Otto writes the brief, the footage is the creator's)
    "ugc_talking_head": _st(None, "ugc_video", "story feed", "cold warm hot", " ".join(KINDS),
                            "hook script shot_list", "persona length notes disclosure name consent handle", (), None,
                            "A real creator talking to camera. Otto writes brief + script + shot list; filled when the "
                            "footage arrives. Never an AI person presented as a customer."),
}
# carousel data: {"cover": {headline*, kicker, sub, photo}, "slides": [{title*, body, points, photo}] (1-4), "end": {headline*, cta*, sub}}
CAROUSEL_REQUIRED = {"cover": ["headline"], "slides": ["title"], "end": ["headline", "cta"]}
# styles whose template is still being built: a style may be in the catalogue before its file lands in templates/ads/
# (build() skips its cells as "pending" until then). All ten native/proof/product templates landed 2026-09-29.
PENDING = set()
ALIASES = {"notes": "notes_app", "google": "search", "google_search": "search", "texts": "text_message", "text": "text_message",
           "imessage": "text_message", "share": "social_post", "shared_post": "social_post", "tweet": "social_post",
           "ugc_photo": "ugc_caption", "ugc": "ugc_talking_head", "talking_head": "ugc_talking_head", "creator": "ugc_talking_head",
           "reviews": "review_cards", "review": "quote", "testimonial": "quote", "vs": "us_vs_them", "versus": "us_vs_them",
           "product": "product_hero", "product_photo": "product_hero", "product_huge": "macro_hero", "macro": "macro_hero",
           "price_card": "offer", "stat": "big_number", "number": "big_number", "static": "editorial", "meme": "editorial"}
# faceless motion versions: the HyperFrames ad kit (motion/ad-kit: text-overlay POV) and the otto_motion reel (voiceover b-roll).
# There is deliberately no "ugc" kit: a person talking is the creator format — real footage, never generated.
VIDEO_KITS = {"notes": "ad-kit", "search": "ad-kit", "texts": "ad-kit", "versus": "ad-kit", "big": "ad-kit", "reel": "otto_motion"}
NEEDS = {"photo": "a brand photo (brands/<id>/assets/, the scanned site images or a post image)",
         "product_image": "a product cutout / packshot (brands/<id>/assets/ or strategy.json assets.product)",
         "person_photo": "a real person photo (strategy.json assets.people or a site photo of a person)",
         "reviews": "verbatim reviews in strategy.json proof_bank (rv* ids or quoted claims)",
         "number": "a sourced number in strategy.json proof_bank",
         "offer": "a real offer with a price in strategy.json offers",
         "ingredients": "ingredient facts in strategy.json proof_bank",
         "event": "a dated event in the month (strategy.json events)",
         "founder": "a true founder story (strategy.json founder)",
         "proof": "a sourced claim in strategy.json proof_bank"}
# the per-angle slots (research §f table 2). A static slot is filled by its style whether the cell runs as the image or
# as the style's motion version — that is how 6 creatives per angle reach the 50 % video mix.
SLOTS = {
    "creator": {"desc": "UGC talking-head video by a real creator", "formats": ["creator"]},
    "faceless": {"desc": "faceless video — text-overlay POV (ad kit) or voiceover b-roll (reel)", "formats": ["video"]},
    "product": {"desc": "product static (product_hero / macro_hero / ingredients)", "families": ["product"]},
    "comparison": {"desc": "comparison static (before_after / us_vs_them)", "styles": ["before_after", "us_vs_them", "comparison"]},
    "native": {"desc": "native screenshot static (notes_app / text_message / search / social_post)",
               "styles": ["notes_app", "text_message", "search", "social_post"]},
    "proof_humor": {"desc": "proof or humor static (review_cards / quote / big_number / editorial / myth_fact …)",
                    "families": ["proof", "editorial"]},
    "price": {"desc": "price card (offer)", "styles": ["offer"]},
}
# Defaults from the Grüns ad-library scan (research/GRUNS-AD-LIBRARY-2026-09.md §f, research/gruns-ads/taxonomy.json,
# 2026-09-29). Every value is tunable per matrix ("rules") or per call (coverage(m, rules)).
LAUNCH_RULES = {
    "min_angles": 6,                    # concepts (= Meta ad sets); Grüns covers all 6 angle families
    "angle_families": ["pain", "identity", "enemy", "experience", "offer", "moment"],
    "family_substitutes": {"moment": "identity"},       # month 1 may run a second identity angle instead of a moment
    "min_competitor_angles": 1, "competitor_sources": ["competitor", "competitor-research"],
    "min_styles_per_angle": 6,          # 36 creatives at launch (Grüns median 14 per angle after 4 months)
    "min_style_families_per_angle": 4,  # Grüns big angles: median 6.5 of 11 families
    "slots": ["creator", "faceless", "product", "comparison", "native", "proof_humor"],
    "price_card_families": ["offer"],   # angle families that also carry a price card
    "offer_for_hot": True,              # so does every hot-stage angle (Max's rule)
    "min_video_share": 0.5,             # creator + faceless video; Grüns is 63 % video, launch target 50 / 50
    "min_video_per_angle": 2, "min_statics_per_angle": 2,
    "min_story_share": 0.5,             # cells with a 9:16 version (Stories / Reels placements)
    "min_styles_total": 10,
    "min_native": 2, "min_proof": 1, "min_product": 1,          # distinct styles of that family across the matrix
    "headlines_per_angle": [1, 2],      # reused across the angle's visuals: Grüns runs 75 headlines on 674 creatives
    "primaries_per_angle": [2, 3],
    "refresh_per_angle_week": 2,        # after launch: +2 new creatives per angle per week, on styles the angle has not run
}
MICRO_RULES = dict(LAUNCH_RULES, min_angles=4, angle_families=["pain", "identity", "enemy", "offer"], family_substitutes={},
                   min_styles_per_angle=5, slots=["creator", "faceless", "product", "comparison", "native"], min_styles_total=8,
                   min_proof=0)                          # research §f.5: keep slots 1-5, drop proof / humor
# SCALE (plans.json "scale"): the launch families and slots with 8 executions per concept (the plan sets the weekly refresh)
SCALE_RULES = dict(LAUNCH_RULES, min_styles_per_angle=8, min_styles_total=14, refresh_per_angle_week=2)
PRESETS = {"launch": LAUNCH_RULES, "micro": MICRO_RULES, "scale": SCALE_RULES}
# below this daily budget (in EUR) 36 creatives are too thin (~€1 per creative per day): the micro floor applies.
# Judgement call, tunable; EUR_PER is a rough rate table, only the fallback for a currency otto_whop.FX_EUR lacks.
MICRO_BELOW_DAILY_EUR = 36.0
EUR_PER = {"EUR": 1, "USD": 1.08, "GBP": 0.85, "CHF": 0.95, "ILS": 4.0, "PLN": 4.3, "CZK": 25.0, "HUF": 395.0, "RON": 5.0,
           "SEK": 11.3, "NOK": 11.6, "DKK": 7.46, "BGN": 1.96, "CAD": 1.5, "AUD": 1.65}
KIND_RE = {  # angle text → kinds (a strategist can also set "kind"/"kinds" on the angle)
    "offer": re.compile(r"\d+\s?%\s?(off|rabatt|korting|desconto)|\bup to \d+\s?%|\b(sale|discount|deal|coupon|code|bundle|"
                        r"trial|save|price|pricing|subscription|subscribe|"
                        r"money[- ]back|guarantee|free shipping|first order|limited|restock|rabatt|angebot|gratis)\b|[$€£₪]|"
                        r"הנחה|מבצע|מחיר", re.I),
    "objection": re.compile(r"\?|\b(vs\.?|versus|instead of|without|trap|myth|actually|even|worth it|skeptic\w*|hate\w*|worr\w*|"
                            r"too (expensive|much|hard)|no (mess|shaker|pills?|powder|chalk|grit|mixing|contract|commitment))\b", re.I),
    "proof": re.compile(r"\b\d[\d.,]*\s?(%|g|mg|x|k|\+|stars?|reviews?|customers?|members?|patients?|graduates?|days?|weeks?|"
                        r"years?|vitamins?)(?!\w)|\b(reviews?|rated|study|studies|clinical|tested|survey|proof|results?|lab|"
                        r"certif\w*|award\w*|verbatim|testimonial\w*)\b|ביקורות|עדות|המלצ", re.I),
    "education": re.compile(r"\b(how|why|what|explain\w*|guide|learn|myth|fact|science|ingredients?|by the numbers?|plainly|picker|"
                            r"transparency|101)\b|איך|למה", re.I),
    "audience": re.compile(r"\bfor (the |people|parents|moms?|dads?|busy|guys?|women|men|kids|anyone|those)|\b(parents?|moms?|"
                           r"guy who|people who|call-out|persona)\b|למי|להורים", re.I),
}
FAMILY_RE = {  # angle text → angle family (research §f slots A-F; an explicit "family" on the angle wins)
    "offer": KIND_RE["offer"],
    "moment": re.compile(r"\b(season\w*|limited|drop|collab\w*|partner(ship)?|edition|halloween|christmas|xmas|holiday\w*|"
                         r"black friday|cyber monday|summer|winter|spring|autumn|new year|valentine\w*|mother'?s day|"
                         r"back to school|launch\w*|restock\w*|sell(s|ing)? out|licen[cs]\w*|newsjack\w*|open day|webinar)\b|"
                         r"חג|עונ|מהדורה|יום פתוח", re.I),
    "enemy": re.compile(r"\b(vs\.?|versus|instead of|replac\w*|switch\w*|ditch\w*|powders?|pills?|shakers?|other (brands?|"
                        r"supplements?|gummies|products?)|leading brands?|the stack|bottles|hate\w* (veggies|vegetables|greens)|"
                        r"alternatives?|competitors?|tub)\b", re.I),
    "identity": re.compile(r"\bfor (the |people|parents|moms?|dads?|busy|guys?|women|men|kids|anyone|those|athletes?|runners?|"
                           r"students?|seniors?)|\b(parents?|moms?|dads?|kids|men|women|husbands?|wives|guy who|people (on|who)|"
                           r"athletes?|over \d+|glp-?1|menopaus\w*|pregnan\w*|students?|seniors?|retirees?|nurses?|"
                           r"teachers?|reservists?)\b|להורים|לאמהות|לגברים|לנשים|למי|מילואים|בוגר", re.I),
    "pain": re.compile(r"\b(pain|problems?|struggl\w*|tired|fatigue|bloat\w*|gut|digest\w*|poops?|constipat\w*|fib(er|re)|"
                       r"energy|sleep|stress|skin|hair|weight|cravings?|gaps?|deficien\w*|hard to|can'?t|missing|lack\w*|"
                       r"worr\w*|burn(ed|t)? ?out|anxi\w*)\b|כאב|קושי|בעיה", re.I),
    "experience": re.compile(r"\b(tastes?|flavou?rs?|delicious|easy|easier|simple|simplified|convenien\w*|on the go|grab|ritual|"
                             r"habit|routine|one pack|a day|feels?|texture|format|gumm(y|ies)|absorb\w*|fun|enjoy\w*|mess|"
                             r"no mixing|in your bag)\b|טעים|קל", re.I),
}
FAMILY_STAGE = {"pain": "cold", "identity": "cold", "enemy": "cold", "experience": "warm", "offer": "hot", "moment": "hot"}
STATUS_ORDER = {"winner": 0, "testing": 1, "idea": 2}
PRODUCT_RE = re.compile(r"pack(shot)?|pouch|bottle|jar|tube|box\b|product|nobg|no-bg|cutout|render|shoptile|sachet|packag|tin\b", re.I)
PERSON_RE = re.compile(r"\b(woman|women|man|men|person|people|girl|boy|mom|dad|mother|father|customer|founder|team|smiling|"
                       r"holding|selfie|portrait|model|face|hands?)\b", re.I)
AI_PERSON = re.compile(r"\b(ai|a\.i\.|avatar|generated|synthetic|virtual|deepfake|digital human)\b", re.I)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
Q = "(?)"


# ---------------------------------------------------------------- catalogue lookups

def resolve(style):
    """Style name or alias → catalogue key (None when unknown)."""
    s = re.sub(r"[^a-z0-9_]", "", str(style or "").strip().lower().replace("-", "_").replace(" ", "_"))
    s = ALIASES.get(s, s)
    return s if s in STYLES else None


def templates(style):
    st = STYLES[resolve(style) or style]
    return list(st.get("cards") or ([st["template"]] if st["template"] else []))


def template_ready(name):
    return (TEMPLATES / f"{name}.html").exists()


def ready(style):
    """Every template the style renders with is on disk (a creator style needs none)."""
    return all(template_ready(t) for t in templates(style))


def kit_dirs():
    roots = [Path(os.environ.get("OTTO_MOTION_ROOT") or REPO / "motion"), REPO / "motion"]
    return [r / "ad-kit" for r in dict.fromkeys(roots)]


def video_ready(kit):
    """The motion version exists: an ad-kit style (motion/ad-kit/templates/styles/<kit>.html) or the otto_motion reels."""
    if VIDEO_KITS.get(kit) == "otto_motion":
        return (HERE / "otto_motion.py").exists()
    return any((d / "templates" / "styles" / f"{kit}.html").exists() for d in kit_dirs())


def fmt(cell):
    f = str(cell.get("format") or "").lower()
    if f in ("video", "creator"):
        return f
    return "creator" if resolve(cell.get("style")) == "ugc_talking_head" and not f else "image"


def is_video(cell):
    return fmt(cell) in ("video", "creator")


def cell_family(cell):
    """creator → ugc_video, a (faceless) video cell → faceless_video, an image cell → its style's family."""
    if fmt(cell) == "creator":
        return "ugc_video"
    if fmt(cell) == "video":
        return "faceless_video"
    st = resolve(cell.get("style"))
    return STYLES[st]["family"] if st else None


def cell_sizes(cell):
    s = cell.get("size") or ("story" if is_video(cell) else "feed")
    return [s] if isinstance(s, str) else [x for x in s if isinstance(x, str)]


PARKED = ("dropped", "hold")          # a cell / angle with one of these never renders, never launches, never counts


def live_cells(angle):
    return [c for c in angle.get("ads") or [] if isinstance(c, dict) and c.get("status") not in PARKED]


def live_angles(matrix):
    return [a for a in (matrix or {}).get("angles") or [] if isinstance(a, dict) and a.get("status") not in PARKED]


def held_cells(matrix):
    """[(angle, cell, reason)] for every cell on hold: "status": "hold" on the cell (or on its angle), with the reason in
    "hold_reason" / "status_note" ("licence pending"). A held cell is reported by --check, never rendered or launched, and
    left out of coverage, the video share and the size line until the hold is lifted."""
    out = []
    for a in (matrix or {}).get("angles") or []:
        if not isinstance(a, dict) or a.get("status") == "dropped":
            continue
        for c in a.get("ads") or []:
            if not isinstance(c, dict) or c.get("status") == "dropped":
                continue
            if c.get("status") == "hold" or a.get("status") == "hold":
                src = c if c.get("status") == "hold" else a
                why = str(src.get("hold_reason") or src.get("status_note") or "").strip()
                out.append((a, c, (why or "on hold") + ("" if src is c else f" (angle {a.get('id')} on hold)")))
    return out


def ad_copy(angle, cell, i=0):
    """The copy an ad runs: the cell's override, else the angle's headlines / primaries rotated over its cells (1-2 headlines
    and 2-3 primaries reused across the visuals — the test is about the visual)."""
    hs = [h for h in (angle or {}).get("headlines") or [] if isinstance(h, str) and h.strip()]
    ps = [p for p in (angle or {}).get("primaries") or [] if isinstance(p, str) and p.strip()]
    return {"primary": str(cell.get("primary") or (ps[i % len(ps)] if ps else "")),
            "headline": str(cell.get("headline") or (hs[i % len(hs)] if hs else "")),
            "description": str(cell.get("description") or (angle or {}).get("description") or ""),
            "cta": str(cell.get("cta") or (angle or {}).get("cta") or "")}


def matrix_path(bid, ym):
    return ap.BRANDS / bid / f"ads-{ym}.json"


def load_matrix(bid, ym):
    """The month's matrix, None when there is none. Raises ValueError when the file is unreadable (never silently empty)."""
    f = matrix_path(bid, ym)
    if not f.exists():
        return None
    try:
        m = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"{f.name} unreadable: {e}")
    if not isinstance(m, dict) or not isinstance(m.get("angles"), list):
        raise ValueError(f"{f.name} has no angles[] list")
    return m


def save_matrix(bid, ym, m):
    f = matrix_path(bid, ym)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, f)
    return f


def size_text(m):
    """'6 concepts × 6–7 styles = 38 ads (19 video, 6 creator)' — the line the monthly plan card carries."""
    ang = [a for a in live_angles(m) if live_cells(a)]
    per = [len(live_cells(a)) for a in ang]
    total = sum(per)
    vids = sum(1 for a in ang for c in live_cells(a) if is_video(c))
    crea = sum(1 for a in ang for c in live_cells(a) if fmt(c) == "creator")
    rng = f"{min(per)}" if per and min(per) == max(per) else f"{min(per)}–{max(per)}" if per else "0"
    return (f"{len(ang)} concept{'s' if len(ang) != 1 else ''} × {rng} style{'s' if rng != '1' else ''} = {total} ads"
            + (f" ({vids} video{f', {crea} creator' if crea else ''})" if vids else ""))


def preset_for_budget(daily, currency="EUR"):
    """'micro' when the flight's daily budget is below MICRO_BELOW_DAILY_EUR, else 'launch'. EUR through ap.to_eur — the table
    the plan's ad-spend band uses (otto_whop.FX_EUR), so the matrix size and the band never disagree; EUR_PER only for a
    currency that table does not have."""
    try:
        daily = float(daily)
    except (TypeError, ValueError):
        return "launch"
    cur = str(currency or "EUR").upper()
    eur = ap.to_eur(daily, cur)
    if eur is None:
        eur = daily / EUR_PER.get(cur, 1.0)
    return "micro" if eur < MICRO_BELOW_DAILY_EUR else "launch"


# ---------------------------------------------------------------- coverage

def rules_for(matrix, rules=None):
    r = dict(PRESETS.get((matrix or {}).get("preset") or "launch", LAUNCH_RULES))
    r.update((matrix or {}).get("rules") or {})
    r.update(rules or {})
    return r


def _need(share, total):
    return math.ceil(share * total - 1e-9)


def slot_fits(slot, cell):
    """Can this cell fill that slot? creator / faceless by format; the static slots by style (image or its motion version)."""
    spec = SLOTS.get(slot) or {}
    st = resolve(cell.get("style"))
    if not st:
        return False
    if spec.get("formats"):
        return fmt(cell) in spec["formats"]
    if fmt(cell) == "creator":
        return False
    return st in spec.get("styles", []) or STYLES[st]["family"] in spec.get("families", [])


def angle_slots(a, r):
    """The slots this angle must fill: the preset's, plus a price card on offer-family / hot-stage angles."""
    slots = list(r["slots"])
    if a.get("family") in r.get("price_card_families", []) or (r.get("offer_for_hot") and a.get("stage") == "hot"):
        slots.append("price")
    return slots


def missing_slots(cells, slots):
    """Slots no distinct cell fills (max bipartite matching, Kuhn — a cell fills one slot)."""
    owner = {}

    def take(si, seen):
        for ci, c in enumerate(cells):
            if ci in seen or not slot_fits(slots[si], c):
                continue
            seen.add(ci)
            if ci not in owner or take(owner[ci], seen):
                owner[ci] = si
                return True
        return False

    return [slots[si] for si in range(len(slots)) if not take(si, set())]


def coverage(matrix, rules=None):
    """Human-readable gaps against the rules (the matrix's preset, its own "rules", then `rules`). [] = full coverage.
    Counts every cell that is not dropped or on hold, written or not (a creator cell waiting for footage counts: it is
    planned; a held cell does not — its slot shows as a gap until the hold is lifted)."""
    r = rules_for(matrix, rules)
    gaps, used, total, story, video, slot_miss = [], set(), 0, 0, 0, {}
    angles = live_angles(matrix)
    if len(angles) < r["min_angles"]:
        gaps.append(f"{len(angles)} angle(s) — need ≥{r['min_angles']} concepts")
    fams = [a.get("family") for a in angles]
    for fam in r["angle_families"]:
        if fam in fams:
            continue
        sub = r.get("family_substitutes", {}).get(fam)
        if sub and fams.count(sub) >= 2:
            continue
        gaps.append(f"no {fam} angle{f' (or a second {sub} angle)' if sub else ''} — one angle per family: "
                    f"{', '.join(r['angle_families'])}")
    for a in angles:
        cells = live_cells(a)
        tag = f"angle {a.get('id', '?')} “{str(a.get('name') or a.get('angle') or '')[:40]}”"
        unknown = [str(c.get("style")) for c in cells if not resolve(c.get("style"))]
        if unknown:
            gaps.append(f"{tag}: unknown style(s) {', '.join(unknown)} (see otto_styles.py list)")
        st = {resolve(c.get("style")) for c in cells} - {None}
        if len(st) < r["min_styles_per_angle"]:
            gaps.append(f"{tag}: {len(st)} style(s) — need ≥{r['min_styles_per_angle']} per concept")
        cf = {cell_family(c) for c in cells} - {None}
        if len(cf) < r["min_style_families_per_angle"]:
            gaps.append(f"{tag}: {len(cf)} style families ({', '.join(sorted(cf))}) — need ≥{r['min_style_families_per_angle']}")
        for slot in missing_slots(cells, angle_slots(a, r)):
            slot_miss.setdefault(slot, []).append(str(a.get("id", "?")))
        vids = sum(1 for c in cells if is_video(c))
        if vids < r["min_video_per_angle"]:
            gaps.append(f"{tag}: {vids} video cell(s) — need ≥{r['min_video_per_angle']}")
        if len(cells) - vids < r["min_statics_per_angle"]:
            gaps.append(f"{tag}: {len(cells) - vids} static cell(s) — keep ≥{r['min_statics_per_angle']} (statics test angles cheaply)")
        used |= st
        total += len(cells)
        story += sum(1 for c in cells if "story" in cell_sizes(c))
        video += vids
    for slot, ids in slot_miss.items():                    # one line per slot, naming the angles that miss it
        gaps.append(f"no {SLOTS[slot]['desc']} on angle{'s' if len(ids) > 1 else ''} {', '.join(ids)}")
    if len(used) < r["min_styles_total"]:
        gaps.append(f"{len(used)} distinct style(s) across the matrix — need ≥{r['min_styles_total']}")
    for fam, key in (("native", "min_native"), ("proof", "min_proof"), ("product", "min_product")):
        have = sorted(s for s in used if STYLES[s]["family"] == fam)
        if len(have) < r.get(key, 0):
            gaps.append(f"{len(have)} {fam} style(s){' (' + ', '.join(have) + ')' if have else ''} — need ≥{r[key]} of "
                        f"{', '.join(fam_styles(fam))}")
    comp_angles = [a for a in angles if a.get("source") in r["competitor_sources"]]
    if len(comp_angles) < r["min_competitor_angles"]:
        gaps.append(f"{len(comp_angles)} angle(s) from competitor research — need ≥{r['min_competitor_angles']} "
                    f"(source {' / '.join(r['competitor_sources'])})")
    if total and story < _need(r["min_story_share"], total):
        gaps.append(f"story (9:16) versions on {story} of {total} cells — need ≥{_need(r['min_story_share'], total)}")
    if total and video < _need(r["min_video_share"], total):
        gaps.append(f"{video} of {total} cells are video — need ≥{_need(r['min_video_share'], total)}")
    return gaps


def fam_styles(fam):
    return [s for s, v in STYLES.items() if v["family"] == fam]


def copy_gaps(matrix, rules=None):
    """Angle-level copy rules: 1-2 headlines reused across the angle's visuals, 2-3 primary texts."""
    r = rules_for(matrix, rules)
    (hmin, hmax), (pmin, pmax) = r["headlines_per_angle"], r["primaries_per_angle"]
    out = []
    for a in live_angles(matrix):
        cells = live_cells(a)
        copies = [ad_copy(a, c, i) for i, c in enumerate(cells)]
        hs = {x["headline"].strip().lower() for x in copies if x["headline"].strip()}
        ps = {x["primary"].strip().lower() for x in copies if x["primary"].strip()}
        tag = f"angle {a.get('id', '?')}"
        if len(hs) < hmin:
            out.append(f"{tag}: no headline — write {hmin}-{hmax} and reuse them across its visuals")
        elif len(hs) > hmax:
            out.append(f"{tag}: {len(hs)} headlines across its visuals — keep {hmin}-{hmax} (the test is about the visual)")
        if len(ps) < min(pmin, len(cells)):
            out.append(f"{tag}: {len(ps)} primary text(s) — write {pmin}-{pmax}")
        elif len(ps) > pmax:
            out.append(f"{tag}: {len(ps)} primary texts — keep {pmin}-{pmax}")
    return out


def launched_on(bid, ym):
    """The day the month's concept-structured evergreen went live (data.json), None before."""
    try:
        d = ap.load()
    except Exception:
        return None
    days = [str(c.get("launched_at") or "")[:10] for c in d.get("campaigns", [])
            if c.get("brand") == bid and c.get("plan") == ym and (c.get("remote") or {}).get("structure") == "concepts"]
    days = [x for x in days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)]
    return date.fromisoformat(min(days)) if days else None


def refresh_gaps(matrix, today=None, launched=None, rules=None):
    """After launch: every angle gets rules.refresh_per_angle_week new creatives (cells with "added" in the last 7 days),
    each on a style the angle had not run before. [] before the first week is over."""
    r = rules_for(matrix, rules)
    today = today or date.today()
    launched = launched or (date.fromisoformat(matrix["launched"]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str((matrix or {}).get("launched") or "")) else None)
    if not launched or today < launched + timedelta(days=7):
        return []
    since = today - timedelta(days=7)
    out = []
    for a in live_angles(matrix):
        old, new = [], []
        for c in live_cells(a):
            try:
                added = date.fromisoformat(str(c.get("added")))
            except ValueError:
                added = None
            (new if added and since < added <= today else old).append(c)
        fresh = [c for c in new if resolve(c.get("style")) not in {resolve(o.get("style")) for o in old}]
        if len(new) < r["refresh_per_angle_week"]:
            out.append(f"angle {a.get('id')}: {len(new)} new creative(s) in the last 7 days — add {r['refresh_per_angle_week']} "
                       "(re-cut a winner first; at least one on a style the angle has not run)")
        elif not fresh:
            out.append(f"angle {a.get('id')}: this week's new creatives all repeat styles it already runs — make one a new style")
    return out


# ---------------------------------------------------------------- brand context (what the brand really has)

def _json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def _norm(t):
    t = re.sub(r"[“”„«»\"*]", "", str(t or ""))
    t = re.sub(r"[‘’`´]", "'", t)
    return re.sub(r"\s+", " ", t).strip(" .!?,;:-—–").lower()


def _is_review(p):
    claim = str(p.get("claim") or "").strip()
    return str(p.get("id", "")).startswith("rv") or claim[:1] in "“\"„«"


INGREDIENT_RE = re.compile(r"ingredient|vitamin|mineral|fib(er|re)|protein|extract|probiotic|prebiotic|collagen|magnesium|zinc|"
                           r"omega|\bcbd\b|terpen|botanical|contains|made with|\d+\s?mg\b", re.I)


def _host(u):
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", str(u or "").strip().lower())
    return m.group(1) if m else ""


def _asset_ref(p):
    """Local file → the reference the renderer resolves ('assets/…' inside OTTO_ASSETS, else an absolute path)."""
    try:
        import otto_paths
        return otto_paths.rel_of(p) if Path(p).resolve().is_relative_to(otto_paths.ASSETS.resolve()) else str(Path(p).resolve())
    except Exception:
        return str(p)


def _images(bid, s, d=None):
    """[(ref, name + alt text, kind hint)] for every image the brand has: strategy.json assets, brands/<id>/assets/,
    <assets>/site/<id>/, the scanned site images (<assets>/site/index.json, only when its host is the brand's), post images."""
    out, seen = [], set()

    def add(ref, blob, hint=""):
        if ref and ref not in seen:
            seen.add(ref); out.append((ref, blob, hint))

    for hint, refs in ((s.get("assets") or {}).items() if isinstance(s.get("assets"), dict) else []):
        for r in refs if isinstance(refs, list) else [refs]:
            add(str(r), str(r), {"product": "product", "products": "product", "people": "person", "person": "person"}.get(hint, ""))
    try:
        import otto_paths
        site = otto_paths.ASSETS / "site"
    except Exception:
        site = None
    roots = [ap.BRANDS / bid / "assets"] + ([site / bid] if site else [])
    for root in roots:
        if root.is_dir():
            for f in sorted(root.rglob("*")):
                if f.suffix.lower() in IMG_EXT and "logo" not in f.name.lower():
                    add(_asset_ref(f), f.stem)
    if site and (site / "index.json").exists():
        host = _host((ap.scan_of(bid) or {}).get("final_url") or (ap.scan_of(bid) or {}).get("url"))
        idx = _json(site / "index.json", [])
        by_stem = {f.stem: f for f in sorted(site.iterdir()) if f.is_file() and f.suffix.lower() in IMG_EXT} if site.is_dir() else {}
        for row in idx if isinstance(idx, list) else []:
            if not (isinstance(row, list) and row and host and _host(row[0]) == host):
                continue
            stem = Path(str(row[0]).split("?")[0]).stem
            f = by_stem.get(stem)
            if f and "logo" not in f.name.lower():
                add(_asset_ref(f), f"{stem} {row[1] if len(row) > 1 else ''}")
    for p in (d or {}).get("posts", []):
        if p.get("brand") == bid and p.get("image"):
            add(p["image"], p.get("hook") or "", "post")
    return out


def _is_cutout(ref):
    try:
        import otto_render
        return otto_render.is_cutout(otto_render.resolve_asset(ref))
    except Exception:
        return False


def brand_assets(bid, s=None, d=None, ym=None):
    """What the brand can back up: photos (product / person / any), verbatim reviews, sourced numbers, ingredient facts,
    real offers, dated events, a founder story."""
    s = s if s is not None else _json(ap.BRANDS / bid / "strategy.json", {})
    proof = [p for p in s.get("proof_bank") or [] if isinstance(p, dict) and p.get("claim") and Q not in str(p.get("claim"))]
    reviews = [p for p in proof if _is_review(p)]
    facts = [p for p in proof if not _is_review(p)]
    imgs = _images(bid, s, d)
    product, people, photos, probes = [], [], [], 0
    for ref, blob, hint in imgs:
        photos.append(ref)
        if hint == "person" or (hint != "product" and PERSON_RE.search(blob)):
            people.append(ref)                           # a person holding the pack is a person photo, not a packshot
        elif hint == "product" or (hint != "post" and PRODUCT_RE.search(blob)):
            product.append(ref)
        elif hint != "post" and ref.lower().endswith((".png", ".webp")) and probes < 30:
            probes += 1
            if _is_cutout(ref):                          # a transparent packshot is a product image whatever it is called
                product.append(ref)
    offers = [o for o in s.get("offers") or [] if isinstance(o, dict) and o.get("price") not in (None, "", Q)]
    events = [e for e in s.get("events") or [] if isinstance(e, dict) and e.get("date") and (not ym or str(e["date"]).startswith(ym))]
    founder = bool(s.get("founder")) or any("founder" in str(p.get("claim", "")).lower() for p in facts)
    return {"photos": photos, "product": product, "people": people, "reviews": reviews,
            "numbers": [p for p in facts if re.search(r"\d", str(p["claim"]))], "ingredients": [p for p in facts if INGREDIENT_RE.search(str(p["claim"]))],
            "proof": facts, "offers": offers, "events": events, "founder": founder}


def needs_met(style, assets):
    """→ (ok, [missing need descriptions])."""
    missing = []
    for n in STYLES[style]["needs"]:
        key, _, cnt = n.partition(":")
        have = {"photo": assets["photos"], "product_image": assets["product"], "person_photo": assets["people"],
                "reviews": assets["reviews"], "number": assets["numbers"], "offer": assets["offers"],
                "ingredients": assets["ingredients"], "event": assets["events"], "founder": [1] if assets["founder"] else [],
                "proof": assets["proof"]}.get(key, [])
        if len(have) < int(cnt or 1):
            missing.append(NEEDS.get(key, key) + (f" (≥{cnt})" if cnt else ""))
    return not missing, missing


# ---------------------------------------------------------------- angles → concepts

def angle_kinds(a):
    """Which kinds of angle this is (explicit "kind"/"kinds" win): competitor by source, the rest from the text; always benefit."""
    exp = a.get("kinds") or a.get("kind")
    if exp:
        ks = [k for k in (exp if isinstance(exp, list) else [exp]) if k in KINDS]
        if ks:
            return ks
    t = str(a.get("angle") or "")
    ks = ["competitor"] if a.get("source") in ("competitor", "competitor-research") else []
    ks += [k for k, rx in KIND_RE.items() if rx.search(t)]
    if a.get("stage") == "hot" and "offer" not in ks:
        ks.append("offer")
    return ks + ["benefit"]


def short_name(text, n=48):
    """The angle's label: text before ':' / ' — ' / '(' (a question keeps its '?'), cut at a word."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().strip("\"“”'")
    m = re.match(r"^(.{6,}?\?)\s", t)
    t = m.group(1) if m else re.split(r":\s|\s[—–-]\s|\s\(", t, maxsplit=1)[0]
    t = t.strip(" .,;")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _words(t):
    return {w for w in re.findall(r"[^\W\d_]{4,}", str(t or "").lower())}


def _dup(a, b):
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / float(min(len(wa), len(wb))) >= 0.6 or _norm(a)[:40] == _norm(b)[:40]


def family_scores(a):
    """Angle → {family: score}. An explicit "family" wins; else pattern hits in the text, a competitor source leans enemy,
    a hot stage leans offer."""
    exp = str(a.get("family") or "").strip().lower()
    t = str(a.get("angle") or "")
    sc = {f: float(len(rx.findall(t))) for f, rx in FAMILY_RE.items()}
    if a.get("source") in ("competitor", "competitor-research"):
        sc["enemy"] += 0.5
    if a.get("stage") == "hot":
        sc["offer"] += 1
    if exp in ANGLE_FAMILIES:
        sc[exp] += 1 if a.get("_synth") else 100          # a synthesised stand-in never outranks a strategist's angle
    return sc


def angle_pool(bid, s, aj):
    """Every candidate angle, best first: strategy.json angles (not losers; winners first), then angles.json research angles
    (written ad copy first, by rank), then the pains (customer words), personas (identity), offers and the month's events."""
    pool = []
    for i, a in enumerate(s.get("angles") or [], 1):
        if isinstance(a, dict) and a.get("angle") and a.get("status") != "loser":
            pool.append(dict(a, id=str(a.get("id") or f"a{i}")))
    pool.sort(key=lambda a: STATUS_ORDER.get(a.get("status"), 3))
    extra = [a for a in (aj.get("angles") or []) if isinstance(a, dict) and a.get("angle")]
    extra = sorted(enumerate(extra), key=lambda x: (0 if isinstance(x[1].get("ad"), dict) else 1, x[1].get("rank") or 99, x[0]))
    for i, a in extra:
        if not any(_dup(a["angle"], p["angle"]) for p in pool):
            pool.append(dict(a, id=f"r{a.get('rank') or i + 1}", status=a.get("status") or "idea"))
    for i, p in enumerate(s.get("pains") or [], 1):
        if isinstance(p, dict) and p.get("text") and Q not in p["text"] and not any(_dup(p["text"], x["angle"]) for x in pool):
            pool.append({"id": f"pain{i}", "angle": p["text"], "persona": p.get("persona"), "source": "profile",
                         "family": "pain", "_synth": True})
    for i, p in enumerate(s.get("personas") or [], 1):
        if isinstance(p, dict) and p.get("label") and Q not in str(p.get("label")):
            pool.append({"id": f"who{i}", "angle": f"For {p['label']}: {str(p.get('situation') or '')[:160]}".strip(": "),
                         "persona": p.get("id"), "source": "profile", "family": "identity", "_synth": True})
    for i, o in enumerate(s.get("offers") or [], 1):
        if isinstance(o, dict) and o.get("price") not in (None, "", Q):
            name = o.get("name") if o.get("name") not in (None, "", Q) else "Offer"
            pool.append({"id": f"offer{i}", "angle": f"{name}: {o['price']}", "source": "profile", "stage": "hot",
                         "family": "offer", "_synth": True})
            break
    for i, e in enumerate(s.get("events") or [], 1):
        if isinstance(e, dict) and e.get("name") and e.get("date"):
            pool.append({"id": f"moment{i}", "angle": f"{e['name']} ({e['date']}): {str(e.get('use') or '')[:140]}",
                         "source": "profile", "stage": "hot", "family": "moment", "_synth": True, "_date": str(e["date"])})
    if not pool:
        try:
            import otto_creative
            for i, a in enumerate(otto_creative.profile_angles(bid), 1):
                pool.append({"id": f"f{i}", "angle": a["angle"], "source": "profile"})
        except Exception:
            pass
    return pool


def pick_angles(bid, s, aj, n_angles=6, rules=None, ym=None):
    """One angle per angle family (rules.angle_families), the strongest candidate for each: pairs are taken best score
    first (a written angle beats a synthesised one; scarce families first on ties). A family nothing fits: its substitute
    (moment → a second identity angle), then the best remaining angles, so the angle count holds and coverage names the
    missing family. At least rules.min_competitor_angles come from competitor research. → [(angle, family)]."""
    r = rules_for({}, rules)
    pool = [a for a in angle_pool(bid, s, aj) if not (a.get("_date") and ym and not a["_date"].startswith(ym))]
    fams = list(r["angle_families"])[:n_angles]
    scores = [family_scores(a) for a in pool]
    fit = lambda i, f: scores[i][f] > 0
    rarity = {f: sum(1 for i in range(len(pool)) if fit(i, f)) for f in fams}
    pairs = sorted(((scores[i][f] - (3 if pool[i].get("_synth") else 0), -rarity[f], -i, f, i)
                    for i in range(len(pool)) for f in fams if fit(i, f)), reverse=True)
    chosen, used = {}, set()
    for _, _, _, f, i in pairs:
        if f not in chosen and i not in used:
            chosen[f] = i
            used.add(i)
    out = [(pool[chosen[f]], f) for f in fams if f in chosen]
    for f in [f for f in fams if f not in chosen]:              # substitutes, then the best remaining angle
        sub = r.get("family_substitutes", {}).get(f)
        cands = [i for i in range(len(pool)) if i not in used]
        if sub:
            cands.sort(key=lambda i: (-scores[i][sub], i))
            if cands and scores[cands[0]][sub] > 0:
                used.add(cands[0])
                out.append((pool[cands[0]], sub))
                continue
        if cands:
            i = min(cands, key=lambda i: (1 if pool[i].get("_synth") else 0, i))
            used.add(i)
            best = max(ANGLE_FAMILIES, key=lambda x: (scores[i][x], -ANGLE_FAMILIES.index(x)))
            out.append((pool[i], best if scores[i][best] > 0 else "experience"))
    while len(out) < n_angles and len(used) < len(pool):         # more angles than families were asked for
        i = min((i for i in range(len(pool)) if i not in used), key=lambda i: (1 if pool[i].get("_synth") else 0, i))
        used.add(i)
        out.append((pool[i], max(ANGLE_FAMILIES, key=lambda x: (scores[i][x], -ANGLE_FAMILIES.index(x)))))
    comp = lambda a: a.get("source") in r["competitor_sources"]
    for j in [j for j in range(len(pool)) if j not in used and comp(pool[j])]:
        if sum(1 for a, _ in out if comp(a)) >= r["min_competitor_angles"]:
            break
        # swap the weakest non-competitor angle of the family this competitor angle fits best
        k = max(range(len(out)), key=lambda k: (not comp(out[k][0]), scores[j][out[k][1]], k))
        if not comp(out[k][0]):
            out[k] = (pool[j], out[k][1])
            used.add(j)
    return out


BRIEF = {
    "notes_app": "Notes list in {who}'s own voice{words}; 3-6 items, no brand-speak.",
    "search": "The real query people type about this; autocomplete or the results page with the brand's listing{rating}.",
    "text_message": "Chat between two friends: one asks, the other recommends it in plain words (no invented results; a quoted "
                    "customer is verbatim from proof_bank) — or clearly the brand replying.",
    "social_post": "A customer's shared post: first person, casual, one proof detail.",
    "ugc_caption": "Real person photo {person} (never a packshot): 1-3 spoken-style captions, first person, no results claims.",
    "review_cards": "1-3 verbatim reviews ({reviews}) + the star summary.",
    "quote": "One verbatim review ({reviews}).",
    "big_number": "One sourced number ({numbers}).",
    "us_vs_them": "Brand vs the generic category (never a competitor's name), 3-5 rows.",
    "comparison": "Table: the brand vs the category's usual way, 3-5 rows, yes/no where possible.",
    "before_after": "The routine before and after — never bodies or symptoms.",
    "product_hero": "Product photo {product} with 2-4 callouts{price}.",
    "macro_hero": "Product {product} cropped huge, one word.",
    "ingredients": "Product {product} at the centre, 3-6 ingredients with one-line notes ({ingredients}).",
    "offer": "The price card: {offer} (recurring price next to any intro price).",
    "event": "The dated event: {event}.",
    "editorial": "Photo + one headline: the control, or a meme-style statement.",
    "carousel": "Cover hook, 1-4 points, one ask.",
    "myth_fact": "The myth this angle answers, struck out; the fact from {proof}.",
    "checklist": "3-5 checks the brand really passes.",
    "founder_note": "A short true founder letter (ask the owner).",
    "ugc_talking_head": "Creator brief for a REAL creator ({who}): hook in the first 2 s, a 20-40 s script in their words, "
                        "a shot list (face to camera, the product in hand), Paid partnership + #ad. Never an AI person.",
}


def _best_proof(text, items, n=2):
    tw = _words(text)
    ranked = sorted(enumerate(items), key=lambda x: (-len(tw & _words(x[1].get("claim"))), x[0]))
    return [p for _, p in ranked[:n]]


def _brief(style, a, persona, s, assets, fmt_="image", kit=None, path=None):
    ids = lambda xs: ", ".join(str(p.get("id") or _norm(p.get("claim"))[:30]) for p in xs) or "proof_bank"
    words = (persona or {}).get("words") or []
    offer = (assets["offers"] or [{}])[0]
    fill = {"who": (persona or {}).get("label") or "the customer",
            "words": f" (their words: “{words[0][:60]}”)" if words else "",
            "rating": ", rating from proof_bank" if assets["numbers"] else "",
            "person": Path(assets["people"][0]).name if assets["people"] else "",
            "product": Path(assets["product"][0]).name if assets["product"] else "",
            "price": f", price {offer.get('price')}" if offer.get("price") and a["stage"] == "hot" else "",
            "reviews": ids(_best_proof(a["angle"], assets["reviews"], 3)),
            "numbers": ids(_best_proof(a["angle"], assets["numbers"], 1)),
            "ingredients": ids(_best_proof(a["angle"], assets["ingredients"], 1)),
            "proof": ids(_best_proof(a["angle"], assets["proof"], 1)),
            "offer": f"{offer.get('name') or ''} {offer.get('price') or ''}".strip()[:80],
            "event": " ".join(str((assets["events"] or [{}])[0].get(k) or "") for k in ("name", "date")).strip()}
    text = BRIEF[style].format(**fill)
    cta = (s.get("cta_by_stage") or {}).get(a["stage"])
    head = f"{a['family']} · {short_name(a['angle'], 40)} · {a['stage']}" + (f" · {(persona or {}).get('label')}" if persona else "")
    if fmt_ == "video":
        text = (f"FACELESS VIDEO ({kit}, 9:16 — {'text-overlay POV' if VIDEO_KITS.get(kit) == 'ad-kit' else 'voiceover b-roll'}): "
                f"{text} Write the kit data JSON to brands/<id>/{path}.")
    return (f"{head}: {text}" + (f" CTA: {cta}." if cta and cta != Q else ""))[:360]


def _persona(s, key):
    per = [p for p in s.get("personas") or [] if isinstance(p, dict)]
    k = str(key or "").strip().lower()
    return next((p for p in per if k and k in (str(p.get("id", "")).lower(), str(p.get("label", "")).lower())), None)


def _prefill(style, assets):
    """Render data the brand already has: the product image for product styles, a person photo for UGC, a photo for editorial."""
    if STYLES[style]["family"] == "product" and assets["product"]:
        return {"photo": assets["product"][0]}
    if style == "ugc_caption" and assets["people"]:
        return {"photo": assets["people"][0]}
    if style == "editorial" and assets["photos"]:
        return {"photo": (assets["people"] or [p for p in assets["photos"] if p not in assets["product"]] or assets["photos"])[0]}
    return {}


# which static cell of an angle runs as its motion version to reach the video mix (comparison → versus kit first)
CONVERT_ORDER = ["comparison", "proof_humor", "product", "native", "extra"]


def plan_matrix(bid, n_per_angle=None, ym=None, n_angles=None, rules=None, d=None, preset="launch"):
    """Deterministic skeleton matrix for a brand (nothing is written).
    1. Angles: one per angle family (pick_angles), stage from the angle or its family (offer / moment → hot).
    2. Per angle, one style per slot (creator, faceless, product, comparison, native, proof/humor, + a price card on the
       offer angle and hot angles), each the best fit (angle kind, stage) among the styles the brand can back up, a style
       used elsewhere scoring lower (variety), distinct inside the angle. A slot nothing can fill gets the best other
       style and coverage names the gap. n_per_angle > slots adds styles for variety.
    3. Video mix: static cells run as their motion version (comparison → versus, proof → big, product → big / reel, …),
       one per angle per round, until rules.min_video_share — keeping ≥ min_statics_per_angle statics.
    Each cell carries a brief; the angle carries empty headlines / primaries for the copywriter (angles.json "ad" copy
    prefills them when the angle came from there)."""
    r = rules_for({"preset": preset}, rules)
    bdir = ap.BRANDS / bid
    s = _json(bdir / "strategy.json", {})
    aj = _json(bdir / "angles.json", {})
    if d is None:
        try:
            d = ap.load()
        except Exception:
            d = {}
    assets = brand_assets(bid, s, d, ym)
    usable, excluded = [], {}
    for st in STYLES:
        ok, miss = needs_met(st, assets)
        if ok:
            usable.append(st)
        else:
            excluded[st] = "needs " + "; ".join(miss)
    order = list(STYLES)
    picked = pick_angles(bid, s, aj, n_angles or r["min_angles"], r, ym)
    used, out_angles = {}, []
    for ai, (a0, family) in enumerate(picked):
        stage = a0.get("stage") if a0.get("stage") in STAGES else FAMILY_STAGE.get(family, STAGES[ai % 3])
        a = {"id": re.sub(r"[^A-Za-z0-9_-]", "", str(a0["id"])) or f"a{ai + 1}", "name": short_name(a0["angle"]),
             "family": family, "angle": str(a0["angle"])[:400], "source": a0.get("source") or "profile", "stage": stage}
        per = _persona(s, a0.get("persona"))
        a["persona"] = (per or {}).get("id") or ""
        a["kinds"] = angle_kinds(dict(a0, stage=stage))
        kinds = set(a["kinds"])
        chosen = []                                             # [(slot, style, format)]

        def score(st):
            S = STYLES[st]
            ov = len(kinds & set(S["kinds"]))
            sc = (3 + 0.5 * min(ov, 3)) if ov else 0.0
            sc += 2 if stage in S["stages"] else -1.5
            sc -= 1.5 * used.get(st, 0)
            sc -= 2.0 * sum(1 for _, x, _ in chosen if STYLES[x]["family"] == S["family"])
            if st not in used and len(used) < r["min_styles_total"]:
                sc += 1
            if "competitor" in kinds and S["family"] == "comparison":
                sc += 1                                        # a competitor angle is argued side by side
            return sc

        def pick(cands, pov=False):
            cands = [x for x in cands if x in usable and x not in [c[1] for c in chosen]]
            bonus = lambda st: 2.5 if pov and VIDEO_KITS.get(STYLES[st]["video"]) == "ad-kit" and STYLES[st]["family"] == "native" else 0
            return max(cands, key=lambda st: (score(st) + bonus(st), -((order.index(st) - 3 * ai) % len(order)))) if cands else None

        slots = angle_slots(a, r)
        # most constrained first: creator, price, product, comparison, proof/humor, native, then faceless (native kits first)
        for slot in sorted(slots, key=lambda x: ["creator", "price", "product", "comparison", "proof_humor", "native",
                                                 "faceless"].index(x) if x in SLOTS else 99):
            spec = SLOTS[slot]
            if slot == "creator":
                chosen.append((slot, "ugc_talking_head", "creator"))
                continue
            if slot == "faceless":                              # text-overlay POV kits (native) lead, variety spreads them
                best = pick([x for x in STYLES if STYLES[x]["video"] in VIDEO_KITS], pov=True)
                if best:
                    chosen.append((slot, best, "video"))
                continue
            cands = [x for x in STYLES if x in spec.get("styles", []) or STYLES[x]["family"] in spec.get("families", [])]
            best = pick(cands)
            if best:
                chosen.append((slot, best, "image"))
        n = n_per_angle or len(slots)
        while len(chosen) < n:                                  # empty slots / extra variety: the best other style
            best = pick([x for x in STYLES if x != "ugc_talking_head" and STYLES[x]["template"]])
            if not best:
                break
            chosen.append(("extra", best, "image"))
        chosen = chosen[:n]
        for _, st, _ in chosen:
            used[st] = used.get(st, 0) + 1
        a["ad_set"] = f"{a['id']} · {a['name']}"
        ad = a0.get("ad") if isinstance(a0.get("ad"), dict) else {}
        a["headlines"] = [ad["headline"]] if ad.get("headline") else []
        a["primaries"] = [ad["primary"]] if ad.get("primary") else []
        a["description"], a["cta"] = str(ad.get("description") or ""), ""
        a["ads"] = []
        for slot, st, f in chosen:
            S = STYLES[st]
            c = {"id": f"{a['id']}-{st}", "style": st, "slot": slot, "format": f}
            if f == "creator":
                c.update(size="story", creator={"persona": (per or {}).get("label") or "", "hook": "", "script": [],
                                                "shot_list": [], "length": "20-40 s",
                                                "disclosure": "Paid partnership label + #ad; real footage by a real creator"},
                         brief=_brief(st, a, per, s, assets))
            elif f == "video":
                path = f"video/{ym or 'YYYY-MM'}/{c['id']}.json"
                c.update(size="story", video={"kit": S["video"], "data": path}, data={},
                         brief=_brief(st, a, per, s, assets, "video", S["video"], path))
            else:
                sizes = ["feed"] + (["story"] if "story" in S["sizes"] else [])
                c.update(template=S["template"] if not S.get("cards") else "carousel", size=sizes if len(sizes) > 1 else sizes[0],
                         data=_prefill(st, assets), brief=_brief(st, a, per, s, assets))
            a["ads"].append(c)
        a["_persona"] = per
        out_angles.append(a)
    # video mix: static cells run as their motion version, round-robin over the angles
    total = sum(len(a["ads"]) for a in out_angles)
    need = _need(r["min_video_share"], total)
    nvid = lambda xs: sum(1 for c in xs if c["format"] in ("video", "creator"))

    def convertible(a):
        cs = [c for c in a["ads"] if c["format"] == "image" and c["slot"] != "price" and STYLES[c["style"]]["video"] in VIDEO_KITS]
        return sorted(cs, key=lambda c: CONVERT_ORDER.index(c["slot"]) if c["slot"] in CONVERT_ORDER else 9)

    progressed = True
    while nvid(c for a in out_angles for c in a["ads"]) < need and progressed:
        progressed = False
        for a in out_angles:
            cs = convertible(a)
            if not cs or len(a["ads"]) - nvid(a["ads"]) <= r["min_statics_per_angle"]:
                continue
            c = cs[0]
            S = STYLES[c["style"]]
            path = f"video/{ym or 'YYYY-MM'}/{c['id']}.json"
            c.pop("template", None)
            c.update(format="video", size="story", data={}, video={"kit": S["video"], "data": path},
                     brief=_brief(c["style"], a, a["_persona"], s, assets, "video", S["video"], path))
            progressed = True
            if nvid(x for b in out_angles for x in b["ads"]) >= need:
                break
    for a in out_angles:
        a.pop("_persona", None)
    return {"brand": bid, "month": ym or "", "preset": preset, "angles": out_angles,
            "assets": {"product": assets["product"][:3], "people": assets["people"][:3], "reviews": len(assets["reviews"]),
                       "offers": len(assets["offers"])},
            "excluded": excluded}


# ---------------------------------------------------------------- per-cell validation + compliance

def brand_context(bid):
    """Once per brand: verbatim review texts (proof_bank + scan quotes) and competitor names (competitors.json)."""
    s = _json(ap.BRANDS / bid / "strategy.json", {})
    texts = [str(p.get("claim")) for p in s.get("proof_bank") or [] if isinstance(p, dict) and p.get("claim")]
    texts += [str(q) for q in (ap.scan_of(bid) or {}).get("quotes") or []]
    comps = _json(ap.BRANDS / bid / "competitors.json", [])
    comps = comps.get("items", []) if isinstance(comps, dict) else comps
    own = _norm((ap.scan_of(bid) or {}).get("identity", {}).get("title") or bid)
    names = []
    for it in comps if isinstance(comps, list) else []:
        n = str((it or {}).get("name") or "") if isinstance(it, dict) else str(it)
        for part in [re.sub(r"\s*\([^)]*\)", "", n)] + re.findall(r"\(([^)]+)\)", n):
            part = part.strip()
            if len(part) >= 3 and _norm(part) != own and _norm(part) not in own.split():
                names.append(part)
    return {"bid": bid, "proof": _norm(" ¶ ".join(texts)), "competitors": list(dict.fromkeys(names)), "strategy": s,
            "own": own + " " + _norm(bid)}


def _filled(v):
    return bool(v.strip()) if isinstance(v, str) else bool(v) if isinstance(v, (list, dict)) else v is not None


def missing_fields(style, data):
    data = data if isinstance(data, dict) else {}
    if style == "carousel":
        miss = [f"cover.{k}" for k in CAROUSEL_REQUIRED["cover"] if not _filled((data.get("cover") or {}).get(k))]
        slides = [x for x in data.get("slides") or [] if isinstance(x, dict)]
        miss += ["slides"] if not slides else [f"slides[{i}].title" for i, x in enumerate(slides) if not _filled(x.get("title"))]
        miss += [f"end.{k}" for k in CAROUSEL_REQUIRED["end"] if not _filled((data.get("end") or {}).get(k))]
        return miss
    miss = [k for k in STYLES[style]["fields"]["required"] if not _filled(data.get(k))]
    if style == "search" and not miss:
        want = "results" if data.get("mode") == "result" else "suggestions" if data.get("mode") == "autocomplete" else None
        if want and not _filled(data.get(want)) or not want and not (_filled(data.get("results")) or _filled(data.get("suggestions"))):
            miss.append(want or "suggestions or results")
    return miss


ASSET_KEY = re.compile(r"(^|_)(photo|image|img|logo|portrait)(_(?!pos$)[a-z0-9]+)?$", re.I)
NOT_COPY_KEYS = re.compile(r"(^|_)(pos|layout|theme|mode|crop|size|url|href|site|highlight|rating|caption_pos|date|style|"
                           r"angle|id|formats?|music|scene|ground|brief)$", re.I)          # switches + ad-kit planning fields


def data_texts(v, key=""):
    """Every string a viewer can read in render data (asset paths, urls and layout switches excluded)."""
    if isinstance(v, dict):
        return [t for k, x in v.items() if not ASSET_KEY.search(str(k)) and not NOT_COPY_KEYS.search(str(k)) for t in data_texts(x, k)]
    if isinstance(v, list):
        return [t for x in v for t in data_texts(x, key)]
    if isinstance(v, str) and v.strip() and not re.match(r"^(/|https?:|file:|assets/|[\w.-]+/[\w./-]*\.\w{2,4}$)", v.strip()):
        return [v]
    return []


def video_data_path(bid, cell):
    ref = (cell.get("video") or {}).get("data")
    if not isinstance(ref, str) or not ref.strip():
        return None
    p = Path(ref).expanduser()
    for c in ([p] if p.is_absolute() else [ap.BRANDS / bid / ref, REPO / ref, HERE / ref]):
        if c.is_file():
            return c
    return None


def cell_texts(bid, cell, angle=None, i=0):
    """Every text a viewer of this ad reads: its copy (the cell's or the angle's), the render data, the kit data of a
    video cell, a creator's hook / script / on-screen text."""
    cp = ad_copy(angle, cell, i)
    out = [cp[k] for k in ("primary", "headline", "description")]
    out += data_texts(cell.get("data") or {})
    vd = (cell.get("video") or {}).get("data")
    if isinstance(vd, dict):
        out += data_texts(vd)
    elif fmt(cell) == "video":
        p = video_data_path(bid, cell)
        if p:
            out += data_texts(_json(p, {}))
    if fmt(cell) == "creator":
        cr = cell.get("creator") or {}
        out += data_texts({k: cr.get(k) for k in ("hook", "script", "on_screen", "caption")})
    return [t for t in out if t and t.strip()]


def review_texts(style, data):
    data = data if isinstance(data, dict) else {}
    if style == "quote":
        return [data.get("quote")] if isinstance(data.get("quote"), str) else []
    if style == "review_cards":
        return [x.get("text") for x in data.get("reviews") or [] if isinstance(x, dict) and isinstance(x.get("text"), str)]
    return []


def verbatim(text, ctx):
    """True when every piece of the review (split at … / ...) is word-for-word in the proof bank or the scanned quotes."""
    pieces = [_norm(x) for x in re.split(r"…|\.\.\.", str(text or ""))]
    pieces = [x for x in pieces if len(x) >= 3]
    return bool(pieces) and all(x in ctx["proof"] for x in pieces)


def _media_file(bid, ref):
    """A rendered / delivered media file ("assets/…", brands/<id>/…, or absolute) → local Path, None when missing."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    p = Path(ref).expanduser()
    cands = [p] if p.is_absolute() else [ap.BRANDS / bid / ref, REPO / ref, HERE / ref]
    if ref.startswith("assets/"):
        try:
            import otto_paths
            cands.insert(0, otto_paths.local_path(ref))
        except Exception:
            pass
    return next((c for c in cands if c.is_file()), None)


# third-party platforms and retailers never named in ad copy (competitors.json names are checked too). One plain word that is
# also an English word ("Target") only counts capitalised and not at the start of a sentence. A matrix can allow a name
# ("rules": {"allowed_names": ["Amazon"]}) when the brand really sells there and says so.
PLATFORM_NAMES = ["Reddit", "Amazon", "TikTok", "YouTube", "Google", "Instagram", "Facebook", "Walmart", "Target",
                  "Costco", "eBay", "Etsy", "Temu", "Shein", "AliExpress", "Sephora", "Ulta", "Whole Foods", "Trader Joe's",
                  "CVS", "Walgreens", "Kroger", "iHerb", "Pinterest", "Snapchat", "Twitter",
                  "רדיט", "אמזון", "טיקטוק", "יוטיוב", "גוגל", "אינסטגרם", "פייסבוק", "עלי אקספרס"]
AMBIGUOUS_NAMES = {"Target"}


def named_platforms(text, allowed=(), own=""):
    """Third-party platform / retailer names in a text → [name]."""
    out, ok = [], {_norm(x) for x in allowed or ()}
    for name in PLATFORM_NAMES:
        if _norm(name) in ok or (own and _norm(name) in own.split()):
            continue
        if name in AMBIGUOUS_NAMES:
            hit = any(not re.search(r"(^|[.!?:]\s*|\n\s*)$", text[:m.start()])
                      for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text))
        else:
            rx = re.sub(r"(?<=[a-z])(?=[A-Z])", r"\\s?", re.escape(name).replace(r"\ ", r"\s?"))   # TikTok, Tik Tok
            hit = bool(re.search(r"(?<!\w)" + rx + r"(?!\w)", text, re.I))
        if hit:
            out.append(name)
    return out


def copy_problems(texts, spoken=()):
    """Placeholders ("[TBD]", "{{name}}", "(?)", a bare "TBD") and internal data (CPL, lead counts, budget figures) in any
    text a viewer reads → ["placeholder '[TBD]' in 'Big [TBD] sale'", …] (otto_render's rules; they block the cell).
    spoken = a real creator's hook / script lines: a fill-in there ("[name] eats them") is theirs to say, so only internal
    data counts."""
    try:
        import otto_render
    except Exception:
        return []
    out, spoken = [], set(spoken)
    for t in texts:
        for x in otto_render.copy_issues(str(t)):
            x = x.split(": ", 1)[-1]
            if t in spoken and x.startswith("placeholder"):
                continue
            out.append(x)
    return list(dict.fromkeys(out))


def asset_found(bid, ref):
    """An image reference in render data resolves: a url, a file the renderer finds ("assets/…", repo-relative, absolute) or
    a bare file name of the brand's (brands/<id>/assets/, <assets>/site/<id>/, <assets>/site/ — otto_creative._cell_asset)."""
    ref = str(ref or "").strip()
    if not ref or re.match(r"^(https?|data):", ref):
        return True
    if ref.startswith("file:"):
        from urllib.parse import unquote, urlparse
        return Path(unquote(urlparse(ref).path)).is_file()
    if _media_file(bid, ref):
        return True
    if "/" not in ref:
        try:
            import otto_paths
            site = otto_paths.ASSETS / "site"
        except Exception:
            site = None
        return any(p.is_file() for p in [ap.BRANDS / bid / "assets" / ref] + ([site / bid / ref, site / ref] if site else []))
    return False


def missing_assets(bid, data, key=""):
    """Image references in render data that do not resolve → ["photo: pack.png", "us.photo: …"]."""
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            out += missing_assets(bid, v, f"{key}.{k}" if key else str(k))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out += missing_assets(bid, v, f"{key}[{i}]")
    elif isinstance(data, str) and ASSET_KEY.search(key.split(".")[-1].split("[")[0]) and not asset_found(bid, data):
        out.append(f"{key}: {data}")
    return out


def validate_cell(cell, ctx, angle=None, i=0):
    """→ {"errors", "warnings", "unwritten", "scripted", "planned"} for one cell. errors block the cell; unwritten = the
    copy is not done yet; scripted = a video cell whose copy / beats are written but whose kit JSON motion has not generated
    yet (a production gap, not a writing one); planned = a creator cell whose brief is written and whose real footage has
    not arrived."""
    errors, warnings, unwritten, planned, scripted = [], [], [], [], []
    style = resolve(cell.get("style"))
    if not style:
        return {"errors": [f"unknown style {cell.get('style')!r}"], "warnings": [], "unwritten": [], "scripted": [], "planned": []}
    S = STYLES[style]
    f = str(cell.get("format") or fmt(cell)).lower()
    if f not in FORMATS:
        errors.append(f"format {f!r} (image | video | creator)")
    if (style == "ugc_talking_head") != (fmt(cell) == "creator"):
        errors.append("a talking head is format creator (real footage) and format creator is style ugc_talking_head")
    sizes = cell_sizes(cell)
    bad = [x for x in sizes if x not in SIZES]
    if bad or not sizes:
        errors.append(f"size {bad or sizes} (feed | story | square)")
    tpl = cell.get("template")
    if tpl and tpl not in templates(style) + (["carousel"] if style == "carousel" else []):
        errors.append(f"template {tpl!r} does not render style {style} ({', '.join(templates(style)) or 'none'})")
    if cell.get("slot") and cell["slot"] not in SLOTS and cell["slot"] != "extra":
        warnings.append(f"unknown slot {cell['slot']!r}")
    if fmt(cell) == "creator":
        cr = cell.get("creator") if isinstance(cell.get("creator"), dict) else {}
        blob = " ".join(str(cr.get(k) or "") for k in ("source", "kind", "type", "made_with", "notes"))
        if cr.get("ai") or cr.get("generated") or AI_PERSON.search(blob):
            errors.append("an AI-generated person can't be presented as a real customer (FTC / Meta) — use a faceless video")
        miss = [k for k in ("hook", "script", "shot_list") if not _filled(cr.get(k))]
        if miss:
            unwritten.append("creator brief missing " + ", ".join(miss))
        if cell.get("file"):
            if not (_filled(cr.get("name")) and cr.get("consent") is True):
                errors.append("creator footage without the creator's name and consent: true")
            elif not _media_file(ctx["bid"], cell["file"]):
                planned.append(f"creator footage {cell['file']} is not on disk")
        elif not miss:
            planned.append("waiting for the creator's footage (brief written)")
    elif fmt(cell) == "video":
        kit = (cell.get("video") or {}).get("kit") or S["video"]
        if not kit:
            errors.append(f"style {style} has no video version")
        elif kit == "ugc":
            errors.append("there is no generated UGC: a person talking is format creator (real footage)")
        elif kit not in VIDEO_KITS:
            errors.append(f"unknown video kit {kit!r} ({', '.join(VIDEO_KITS)})")
        vd = (cell.get("video") or {}).get("data")
        vp = video_data_path(ctx["bid"], cell)
        rendered = bool(cell.get("file")) and _media_file(ctx["bid"], cell["file"]) is not None
        if cell.get("file") and not rendered:
            errors.append(f"video file {cell['file']} is not on disk")
        if cell.get("poster") and not _media_file(ctx["bid"], cell["poster"]):
            errors.append(f"poster {cell['poster']} is not on disk")
        if rendered:
            pass                                          # the finished video is the deliverable: no kit JSON needed any more
        elif not (isinstance(vd, dict) and vd) and not vp:
            if _filled(cell.get("data")) and data_texts(cell.get("data")):   # copy + beats written, kit JSON not yet
                scripted.append(f"copy written, kit JSON {vd or '(no video.data path)'} not generated yet (motion)")
            else:
                unwritten.append(f"video data not written ({vd or 'no path'})")
        elif vp:                                          # an ad-kit ad file: {"id", "style": <kit>, "formats", <style data>, "endcard"}
            kd = _json(vp, None)
            if not isinstance(kd, dict):
                errors.append(f"video data {vp.name} is not a JSON object")
            elif kd.get("style") and kit and kd["style"] != kit:
                errors.append(f"video data {vp.name} is for kit {kd['style']!r}, the cell says {kit!r}")
    else:
        for x in sizes:
            if x in SIZES and x not in S["sizes"]:
                warnings.append(f"{x} is not a tuned size for {style} ({'/'.join(S['sizes'])})")
        miss = missing_fields(style, cell.get("data"))
        if miss:
            unwritten.append("missing " + ", ".join(miss))
        for x in missing_assets(ctx["bid"], cell.get("data") or {}):
            errors.append(f"image not found — {x}")
    cp = ad_copy(angle, cell, i)
    if not cp["primary"].strip():
        unwritten.append("no primary text (the angle's primaries or the cell's)")
    if len(cp["headline"]) > 40:
        warnings.append("headline over 40 chars (Meta truncates)")
    if cp["cta"] and cp["cta"].upper() not in META_CTAS:
        errors.append(f"cta {cp['cta']!r} is not a Meta button type")
    for q in review_texts(style, cell.get("data")):
        if not verbatim(q, ctx):
            errors.append(f"review not verbatim from proof_bank: “{str(q)[:60]}”")
    texts = cell_texts(ctx["bid"], cell, angle, i)
    blob = "\n".join(texts)
    for name in ctx["competitors"]:
        loose = bool(re.search(r"\d|\s", name))            # "AG1", "Athletic Greens": any case; one plain word: as capitalised
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", blob, re.I if loose else 0):
            errors.append(f"names competitor “{name}” — compare against the category, not a brand")
    for name in named_platforms(blob, ctx.get("allowed_names"), ctx.get("own", "")):
        errors.append(f"names “{name}” — no third-party platform or retailer names in ad copy (not even a search suggestion)")
    cr = cell.get("creator") if fmt(cell) == "creator" and isinstance(cell.get("creator"), dict) else {}
    for x in copy_problems(texts, data_texts({k: cr.get(k) for k in ("hook", "script")})):
        errors.append(f"copy not ready: {x}")
    return {"errors": errors, "warnings": warnings, "unwritten": unwritten, "scripted": scripted, "planned": planned}


def check_matrix(bid, ym=None, matrix=None, today=None):
    """Coverage gaps, copy gaps (headlines / primaries per angle), refresh gaps (after launch) + every cell's status:
    ready | planned (creator brief written, footage not in) | scripted (video copy / beats written, the kit JSON not
    generated yet — a motion production gap) | unwritten (a writing gap) | invalid | violation (otto_compliance) | pending
    (template not on disk) | hold (parked on purpose, e.g. licence pending: never launched, left out of coverage).
    Video cells are ready once their kit data is written (otto_motion renders them later)."""
    import otto_compliance as comp
    m = matrix if matrix is not None else load_matrix(bid, ym)
    if m is None:
        return {"gaps": ["no matrix"], "copy": [], "refresh": [], "cells": [], "size": "0 ads"}
    ctx = dict(brand_context(bid), allowed_names=rules_for(m).get("allowed_names") or [])
    rows, seen = [], set()
    for a in live_angles(m):
        for i, c in enumerate(live_cells(a)):
            v = validate_cell(c, ctx, a, i)
            cid = str(c.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", cid) or cid in seen:     # ids name the files and the Meta ads
                v["errors"].insert(0, f"cell id {cid!r} is {'a duplicate' if cid in seen else 'missing or not file-safe'}")
            seen.add(cid)
            texts = cell_texts(bid, c, a, i)
            viol = comp.check_texts(bid, texts, "ads") if texts else []
            style = resolve(c.get("style"))
            if v["errors"]:
                st = "invalid"
            elif viol:
                st = "violation"
            elif v["unwritten"]:
                st = "unwritten"
            elif v["scripted"]:
                st = "scripted"
            elif v["planned"]:
                st = "planned"
            elif fmt(c) == "image" and not ready(style):
                st = "pending"
            else:
                st = "ready"
            reasons = (v["errors"] + ([f"compliance: {comp.describe(viol)}"] if viol else []) + v["unwritten"] + v["scripted"]
                       + v["planned"])
            if st == "pending":
                reasons.append(f"template {', '.join(t for t in templates(style) if not template_ready(t))} not on disk yet")
            if st == "ready" and fmt(c) == "video" and not c.get("file"):
                reasons.append("video not rendered yet (otto_motion)")
            rows.append({"angle": a.get("id"), "id": c.get("id"), "style": style or c.get("style"), "format": fmt(c),
                         "status": st, "reasons": reasons, "warnings": v["warnings"], "violations": viol,
                         "copy": ad_copy(a, c, i)})
    for a, c, why in held_cells(m):                    # on hold: listed, never validated into "ready", never launched
        cid = str(c.get("id") or "")
        seen.add(cid)
        rows.append({"angle": a.get("id"), "id": c.get("id"), "style": resolve(c.get("style")) or c.get("style"),
                     "format": fmt(c), "status": "hold", "reasons": [f"on hold: {why}"], "warnings": [], "violations": [],
                     "copy": ad_copy(a, c, 0)})
    launched = launched_on(bid, m.get("month") or ym) if (m.get("month") or ym) else None
    return {"gaps": coverage(m), "copy": copy_gaps(m), "refresh": refresh_gaps(m, today, launched), "cells": rows,
            "size": size_text(m)}


# ---------------------------------------------------------------- CLI

def main():
    a = sys.argv[1:]
    if a[:1] == ["list"]:
        for name, s in STYLES.items():
            state = "ready" if ready(name) else "pending" if name in PENDING else "MISSING"
            tpl = "/".join(templates(name)) or "(real creator footage)"
            print(f"{name:16} {s['family']:10} {tpl:44} {'/'.join(s['sizes']):18} video:{s['video'] or '-':7} {state}")
            flds = s["fields"]
            print(f"{'':16} fields: {' '.join(k + '*' for k in flds['required'])} {' '.join(flds['optional'])}")
            if s["needs"]:
                print(f"{'':16} needs: {'; '.join(NEEDS.get(n.partition(':')[0], n) for n in s['needs'])}")
            print(f"{'':16} {s['desc']}")
        kits = [f"{k} ({v}, {'ready' if video_ready(k) else 'pending'})" for k, v in VIDEO_KITS.items()]
        print("\nfaceless video kits: " + ", ".join(kits))
        print("\nslots per angle (launch: " + ", ".join(LAUNCH_RULES["slots"]) + "; micro: " + ", ".join(MICRO_RULES["slots"]) + "):")
        for k, v in SLOTS.items():
            print(f"  {k:12} {v['desc']}")
        print("angle families: " + ", ".join(ANGLE_FAMILIES))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
