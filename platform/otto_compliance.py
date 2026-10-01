#!/usr/bin/env python3
"""Otto compliance — per-brand banned phrases + required disclaimer, plus the country × industry baselines
(otto_baselines.py), checked before anything reaches the owner or spends money.

  otto_compliance.py check <brand> "<text>" [--ads]   # prints violations (exit 1 if any)
  otto_compliance.py post <post-id>                   # check one post from data.json
  otto_compliance.py rules <brand>                    # the brand's own rules + which baselines apply
  otto_compliance.py baselines <brand>                # countries, industries, applicable baselines, clearances (JSON)
  otto_compliance.py table                            # every baseline rule (id, countries, industries, severity, source)
  otto_compliance.py clear <brand> <key> "<value>"    # record a brand clearance (e.g. keuringsraad "KOAG/KAG K-1234/26");
                                                      # --remove deletes it
  otto_compliance.py review <post-id|cp-id> <rule-id>[,<rule-id>] [--by <who>] [--note "…"]
                                                      # a person checked this item: releases those needs-review / disclose
                                                      # holds for the current text (any edit re-opens them)

Rules: brands/<slug>/compliance.json
  {"banned": ["plain phrase", "re:<regex>", ...], "required_disclaimer": "<text>" | null,
   "disclaimer_on": ["posts"] (default; add "ads" to require it in ad bodies too), "notes": "...",
   "countries": ["NL"] (optional: overrides brands[].countries for compliance), "industries": ["supplements"] (optional:
   overrides the detected industry tags), "clearances": {"keuringsraad": "KOAG/KAG …", "prior_price_30d": "…"},
   "baselines_off": {"<rule-id>": "why it does not apply to this brand"}}
Plain phrases match case-insensitively on word boundaries; "re:" entries are Python regexes (case-insensitive).
No compliance.json yet (a brand just onboarded): a health / therapy / CBD / clinic brand — judged from its scan industry and
profile — gets the HEALTH_BASELINE rules (cure/heal claims and personal-attribute call-outs in the EU languages + Hebrew),
so a restricted brand is never checked against nothing. A compliance.json that is unreadable, not an object, has a
"banned" that is not a list, a "re:" rule that does not compile, a disclaimer that is not text, or malformed
countries / industries / clearances / baselines_off holds everything (fails closed): a rule the owner meant to set is
never silently dropped.

Country baselines (otto_baselines.RULES) apply automatically by the brand's market — compliance.json "countries" →
brands[].countries → the site's country domain (.nl, .ie, .be; .eu = EU) → the scan's currency (EUR = EU-wide rules only) →
the site language — and by industry tags from the scan (industry label = strong; title / description / profile keywords =
weak; category rules need strong evidence). Campaigns add their audience countries (a Dutch campaign targeting Flanders
gets the Belgian rules). Severities: block (rewrite), needs-review (held with the reason until a person checks it — per
item with `review`, or brand-wide when the rule names a clearance), disclose (held until the disclosure is in the text).
Every one of them is a violation to the callers, so nothing that needs review ever passes silently.
The required disclaimer, the FDA/DSHEA line and the EU / Dutch / German equivalents ("niet bedoeld om ziekten te …
genezen", "Lees voor gebruik de bijsluiter") are removed from the text before the scan: a disclaimer is never a claim.
Callers: otto_telegram.send_cards (a violating card is not sent), otto_publish (a violating approved post goes back to
draft), otto_ads.launch (a violating campaign is put on compliance hold), otto_render (the ad QA gate). They file one
recommendation per blocked item (file_block → add_rec_once) with the reason and the fix.
"""
import hashlib, json, re, sys

import ap
import otto_baselines as BL

# Meta personal-attributes policy + health-claim rules (EU health-claims / HWG-style) for brands that have no rules file yet
HEALTH_BASELINE = [
    r"re:\bcur(e|es|ed|ing)\b", r"re:\bheal(s|ed|ing)?\b", r"re:\bguaranteed (results|cure|to work)\b",
    r"re:\bdo you suffer\b", r"re:\bare you suffering\b", r"re:\bare you (depressed|anxious|traumati[sz]ed|struggling with)\b",
    r"re:\byour (anxiety|depression|trauma|adhd|ptsd|panic attacks|illness|disease)\b",
    r"re:\b(heilt|heilen|heilung|geheilt|heilend)\b", r"re:\bleiden sie (an|unter)\b",
    r"re:\b(curar|curamos|curou)\b", r"re:\bsofre de\b", r"re:\b(geneest|genezen|genezing)\b", r"re:\blijdt u aan\b",
    r"re:\b(guarisce|guarire|guarigione)\b", r"re:\bsoffri di\b", r"re:\b(guérit|guérir|guérison)\b", r"re:\bsouffrez-vous\b",
    r"re:(?<![֐-׿])[והלשבכמ]?(מרפא|מרפאים|מרפאה את|לרפא|תרפא|נרפא|נרפאה|ריפוי)(?![֐-׿])",
    r"re:האם (אתה|את|אתם|אתן) (סובל|סובלת|סובלים|סובלות|מתמודד|מתמודדת|מתמודדים|מתמודדות)",
    r"re:(?<![֐-׿])(אתה|את|אתם|אתן) (סובל|סובלת|סובלים|סובלות) מ",
]
HEALTH = re.compile(r"cbd|hemp|cannab|clinic|medical|dental|dentist|zahnarzt|zahnmedizin|arztpraxis|therap|psycholog|mental health|"
                    r"supplement|pharma|physio|aesthetic|med ?spa|תרפי|טיפול|מרפא|קליניק|פסיכו", re.I)
SEVERITIES = ("block", "needs-review", "disclose")
SHOP_PLATFORM = re.compile(r"shopify|woocommerce|magento|bigcommerce|shopware|prestashop|lightspeed|ccv ?shop", re.I)
CURRENCY_COUNTRY = ap.CURRENCY_COUNTRY


def _compile_baselines():
    """otto_baselines.RULES → compiled rules. A broken table holds everything (see check_texts), never drops a rule."""
    out, errors = [], []
    for r in BL.RULES:
        try:
            if r.get("severity") not in SEVERITIES:
                raise ValueError(f"severity {r.get('severity')!r}")
            c = dict(r)
            for k in ("patterns", "when", "require"):
                c[k] = [re.compile(p, re.I) for lang, ps in (r.get(k) or {}).items() for p in ps]
            c["contexts"] = r.get("contexts") or ["posts", "ads"]
            c["sources"] = r["source"] if isinstance(r.get("source"), list) else [r.get("source")]
            if c["severity"] == "block" and c.get("clear_with"):
                raise ValueError("a block rule cannot be cleared")
            out.append(c)
        except (re.error, ValueError, KeyError, TypeError) as e:
            errors.append(f"{r.get('id', '?')}: {e}")
    return out, "; ".join(errors) or None


BASELINES, BASELINE_ERROR = _compile_baselines()
DISCLAIMERS = [re.compile(p, re.I) for p in BL.DISCLAIMERS]


def baseline(bid):
    """Which baseline applies to a brand with no compliance.json: "health" or None (from the scan industry + profile head)."""
    s = ap.scan_of(bid)
    prof = ap.BRANDS / bid / "brand-profile.md"
    text = " ".join([s.get("industry") or "", (s.get("identity") or {}).get("title") or "",
                     (s.get("identity") or {}).get("description") or "", prof.read_text()[:3000] if prof.exists() else ""])
    return "health" if HEALTH.search(text) else None


_DATA = {}


def _data():
    """data.json, re-read only when it changed (check_texts runs once per post in the cron loops)."""
    try:
        st = ap.DATA.stat()
        key = (str(ap.DATA), st.st_mtime_ns, st.st_size)
        if _DATA.get("key") != key:
            _DATA.update(key=key, d=ap.load())
        return _DATA["d"] if isinstance(_DATA.get("d"), dict) else {}
    except Exception:                                    # noqa: BLE001 — a missing / half-written file: no brand record
        return {}


def industries(bid, raw=None, scan=None):
    """Industry tags → evidence ("compliance.json" | "industry" (scan label) | "keywords" | "platform")."""
    raw = raw if raw is not None else {}
    over = raw.get("industries")
    if isinstance(over, list) and over:
        return {str(t).strip().lower(): "compliance.json" for t in over if str(t).strip()}
    s = scan if scan is not None else ap.scan_of(bid)
    label = str(s.get("industry") or "")
    ident = s.get("identity") or {}
    prof = ap.BRANDS / bid / "brand-profile.md"
    line = ""
    if prof.exists():
        m = re.search(r"Industry:\**\s*(.+)", prof.read_text()[:4000])
        line = m.group(1) if m else ""
    words = " ".join([str(ident.get("title") or ""), str(ident.get("description") or ""), line])
    tags = {}
    for tag, strong, weak in BL.INDUSTRY_TAGS:
        if strong and label and re.search(strong, label, re.I):
            tags[tag] = "industry"
        elif weak and re.search(weak, words, re.I):
            tags.setdefault(tag, "keywords")
    if SHOP_PLATFORM.search(str(s.get("platform") or "")):
        tags.setdefault("goods", "platform")
    return tags


def countries(bid, raw=None, d=None, scan=None):
    """(ISO codes, source) of the brand's market for compliance. "EU" = only known to sell in euros. [] = unknown."""
    raw = raw if raw is not None else {}
    over = raw.get("countries")
    if isinstance(over, list) and over:
        return [str(c).strip().upper() for c in over if str(c).strip()], "compliance.json"
    b = ap.brand(d if d is not None else _data(), bid) or {}
    if b.get("countries"):
        return [str(c).strip().upper() for c in b["countries"] if str(c).strip()], "brand"
    s = scan if scan is not None else ap.scan_of(bid)
    for url in (b.get("url"), s.get("final_url"), s.get("url")):
        host = re.sub(r"^[a-z]+://", "", str(url or "").lower()).split("/")[0].split(":")[0].rstrip(".")
        if host.endswith(".eu"):
            return ["EU"], "domain"
        cc = ap.guess_country(url or "") if url else None
        if cc:
            return [cc], "domain"
    cur = ap.currency_code((s.get("commerce") or {}).get("currency")) or ap.currency_code(b.get("currency"))
    if cur == "EUR":
        return ["EU"], "currency"
    if cur in CURRENCY_COUNTRY:
        return [CURRENCY_COUNTRY[cur]], "currency"
    for lang in s.get("languages") or []:
        if lang in ap.LANG_COUNTRY:
            return [ap.LANG_COUNTRY[lang]], "language"
    return [], "unknown"


def _raw(bid):
    f = ap.BRANDS / bid / "compliance.json"
    if not f.exists():
        return None
    try:
        raw = json.loads(f.read_text())
    except Exception as e:
        return {"banned": [], "error": f"compliance.json unreadable: {e}"}
    return raw if isinstance(raw, dict) else {"banned": [], "error": "compliance.json is not a JSON object"}


def rules(bid, d=None, scan=None):
    raw = _raw(bid)
    if raw is None:
        raw = {"banned": HEALTH_BASELINE, "baseline": "health"} if baseline(bid) else {}
    errors = [raw["error"]] if raw.get("error") else []
    banned = raw.get("banned") or []
    if not isinstance(banned, list):
        errors.append('compliance.json "banned" must be a list')
        banned = []
    pats = []
    for rule in banned:
        rule = str(rule)
        if rule.startswith("re:"):
            try:
                pats.append((rule, re.compile(rule[3:], re.I)))
            except re.error as e:
                print(f"compliance: bad regex in {bid}: {rule} ({e})", file=sys.stderr)
                errors.append(f"bad rule {rule[:60]} ({e})")
        elif rule.strip():
            pats.append((rule, re.compile(r"(?<!\w)" + re.escape(rule.strip()) + r"(?!\w)", re.I)))
    disc = raw.get("required_disclaimer")
    if disc is not None and not isinstance(disc, str):
        errors.append("required_disclaimer must be text")
        disc = None
    on = raw.get("disclaimer_on") or ["posts"]
    on = [on] if isinstance(on, str) else [str(x) for x in on] if isinstance(on, list) else ["posts"]
    shape = {"countries": list, "industries": list, "clearances": dict, "baselines_off": dict}
    for k, typ in shape.items():
        if k in raw and raw[k] is not None and not isinstance(raw[k], typ):
            errors.append(f'compliance.json "{k}" must be a {"list" if typ is list else "JSON object"}')
    clean = {k: raw.get(k) if isinstance(raw.get(k), typ) else typ() for k, typ in shape.items()}
    ccs, csrc = countries(bid, clean, d, scan)
    return {"patterns": pats, "required_disclaimer": disc, "disclaimer_on": on,
            "error": "; ".join(errors) or None, "baseline": raw.get("baseline"),
            "countries": ccs, "countries_source": csrc, "industries": industries(bid, clean, scan),
            "clearances": {str(k): v for k, v in clean["clearances"].items() if v not in (None, "", False)},
            "baselines_off": {str(k): str(v) for k, v in clean["baselines_off"].items()}}


# ---------------------------------------------------------------------------------------------------------------
# which baselines apply
# ---------------------------------------------------------------------------------------------------------------

def _country_hit(rule, ccs):
    not_c = set(rule.get("not_countries") or [])
    for c in ccs:
        if c in not_c:
            continue
        if c in rule["countries"]:
            return c
        if "EU" in rule["countries"] and (c in BL.EU or c == "EU"):
            return "EU" if c == "EU" else c
    return None


def _category(rule):
    return not rule["patterns"] and not rule["require"]


def _industry_hit(rule, tags):
    if any(t in tags for t in rule.get("not_industries") or []):
        return False
    inds = rule.get("industries") or ["*"]
    if "*" in inds:
        return True
    hits = [t for t in inds if t in tags]
    if not hits:
        return False
    if _category(rule) and rule.get("strong", True):         # "hold everything" needs the scan label or an explicit tag
        return any(tags[t] in ("industry", "compliance.json") for t in hits)
    return True


def applicable(r, ccs=None):
    """[(compiled rule, country)] for a rules() result (countries default to the brand's)."""
    ccs = list(dict.fromkeys(ccs if ccs is not None else r["countries"]))
    out = []
    for rule in BASELINES:
        c = _country_hit(rule, ccs)
        if c and _industry_hit(rule, r["industries"]):
            out.append((rule, c))
    return out


# ---------------------------------------------------------------------------------------------------------------
# checking
# ---------------------------------------------------------------------------------------------------------------

# The DSHEA disclaimer is the text the law requires next to a structure/function claim; it names "diagnose, treat,
# cure, or prevent" by design. Either spelling of the agency counts, and the disclaimer is never read as a claim.
DSHEA = re.compile(r"\*?\s*these statements have not been evaluated by the (?:u\.?s\.? )?(?:food (?:and|&) drug "
                   r"administration|fda)\s*\.?\s*this product is not intended to diagnose,? treat,? cure,? or prevent any "
                   r"disease\.?", re.I)


def _sha(texts):
    return hashlib.sha1("\n".join(t.strip() for t in texts if isinstance(t, str)).encode("utf-8")).hexdigest()[:16]


def _excerpt(text, m):
    s = max(0, m.start() - 30)
    return text[s:m.end() + 30].replace("\n", " ").strip()


def _search(rule, text):
    for pat in rule["patterns"]:
        for m in pat.finditer(text):
            if rule.get("negatable") and (BL.NEGATION.search(text[max(0, m.start() - 40):m.start()])
                                          or BL.NEG_INSIDE.search(m.group(0))):
                continue                                    # "does not cure", "geneest geen verkoudheid"
            return m
    return None


def _viol(rule, country, match="", excerpt="", severity=None, title=None):
    return {"rule": title or rule["title"], "id": rule["id"], "severity": severity or rule["severity"], "match": match,
            "excerpt": excerpt, "why": rule.get("why", ""), "fix": rule.get("fix", ""), "source": rule["sources"][0],
            "sources": rule["sources"], "country": country, "baseline": True}


def _evaluate(rule, country, texts, scan, ctx, r, audience):
    """Violations of one baseline rule for these texts (list; usually 0 or 1)."""
    if rule.get("when"):
        always = any(t in r["industries"] for t in rule.get("always_for") or [])
        if not always and not any(p.search(scan) for p in rule["when"]):
            return []
    cleared = bool(rule.get("clear_with") and r["clearances"].get(rule["clear_with"]))
    out = []
    ages = (audience or {}).get("age") if ctx == "ads" and isinstance(audience, dict) else None
    lo = ages[0] if isinstance(ages, (list, tuple)) and ages and isinstance(ages[0], (int, float)) else None
    if rule.get("min_age") and lo is not None and lo < rule["min_age"]:
        out.append(_viol(rule, country, f"age {lo}+", f"audience starts at {lo}; must be {rule['min_age']}+", "block",
                         f"{rule['title']} (audience under {rule['min_age']})"))
    if rule["patterns"]:
        m = _search(rule, scan)
        if m and not (cleared and rule["severity"] != "block"):
            out.append(_viol(rule, country, m.group(0), _excerpt(scan, m)))
        return out
    if cleared:
        return out
    if rule["require"]:
        w = rule.get("require_within")
        ok = any(p.search(t[:w] if w else t) for t in texts for p in rule["require"])
        if not ok:
            out.append(_viol(rule, country, "", f"missing — {rule.get('fix', '')[:100]}"))
        return out
    if rule.get("min_age") and lo is not None:                # an ad targeted at the right age satisfies the age rule
        return out
    out.append(_viol(rule, country))                          # category rule: every text of this brand / context
    return out


def _reviewed(item, rid, sha):
    rv = (item or {}).get("compliance_review") if isinstance(item, dict) else None
    e = rv.get(rid) if isinstance(rv, dict) else None
    return isinstance(e, dict) and e.get("sha") == sha


def check_texts(bid, texts, context="posts", item=None, countries=None, audience=None, review_texts=None):
    """→ list of {"rule", "match", "excerpt", "severity", …}; empty list = clean. Baseline violations also carry "id",
    "why", "fix", "source", "country". item = the post / campaign (its compliance_review releases needs-review /
    disclose rules for the reviewed text); countries / audience = the campaign's targeting."""
    r = rules(bid)
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    blob = "\n".join(texts)
    out = []
    if r["error"] and blob:                          # fail closed: a broken rules file must not wave everything through
        out.append({"rule": "compliance.json unreadable" if "unreadable" in r["error"] else "compliance.json invalid",
                    "match": "", "excerpt": r["error"][:120], "severity": "block"})
    disc = (r["required_disclaimer"] or "").strip()
    scan = DSHEA.sub(" ", blob)
    for pat in DISCLAIMERS:
        scan = pat.sub(" ", scan)
    if disc:
        scan = re.sub(re.escape(disc), " ", scan, flags=re.I)
        present = disc.lower() in blob.lower() or bool(DSHEA.fullmatch(disc.strip()) and DSHEA.search(blob))
        if context in r["disclaimer_on"] and not present:
            out.append({"rule": "required_disclaimer", "match": "", "excerpt": f"missing: “{disc[:80]}”", "severity": "disclose"})
    for rule, pat in r["patterns"]:
        m = pat.search(scan)
        if m:
            out.append({"rule": rule, "match": m.group(0), "excerpt": _excerpt(scan, m), "severity": "block"})
    if not blob.strip():
        return out
    if BASELINE_ERROR:
        out.append({"rule": "compliance baselines invalid", "match": "", "excerpt": BASELINE_ERROR[:120], "severity": "block"})
    ctx = "ads" if context in ("ads", "hooks") else "posts"
    ccs = list(r["countries"]) + [str(c).upper() for c in countries or [] if str(c).strip()]
    sha = _sha(review_texts if review_texts is not None else texts)
    for rule, country in applicable(r, ccs):
        if not rule.get("active", True) or rule["id"] in r["baselines_off"] or ctx not in rule["contexts"]:
            continue
        if context == "hooks" and rule["severity"] == "disclose":
            continue                                  # a single headline is not where a disclosure lives; the campaign is checked
        for v in _evaluate(rule, country, texts, scan, ctx, r, audience):
            if v["severity"] != "block" and _reviewed(item, rule["id"], sha):
                continue
            out.append(v)
    return out


def post_texts(p):
    out = [p.get("hook"), p.get("caption")]
    out += [s for s in (p.get("slides") or []) if isinstance(s, str)]
    out += [sc.get("text") for sc in (p.get("script") or []) if isinstance(sc, dict)]
    tags = p.get("hashtags")
    if isinstance(tags, list):
        out.append(" ".join(str(t) for t in tags))
    return [t for t in out if t]


def check_post(p):
    return check_texts(p["brand"], post_texts(p), "posts", item=p)


def campaign_texts(c):
    cr = c.get("creative") or {}
    cc = c.get("creatives") or {}
    out = [c.get("name")]
    for k in ("headlines", "descriptions"):
        out += [t for t in cr.get(k) or [] if isinstance(t, str)]
    for k in ("titles", "bodies", "descriptions"):
        out += [t for t in cc.get(k) or [] if isinstance(t, str)]
    for img in cc.get("images") or []:
        out.append(img.get("text"))
    for car in cc.get("carousels") or []:
        out += [k.get("text") for k in car.get("cards") or []]
    for con in cc.get("concepts") or []:              # ad-matrix creatives: every style's ad texts
        for ad in con.get("ads") or []:
            out += [ad.get(k) for k in ("primary", "headline", "description") if isinstance(ad.get(k), str)]
    return [t for t in out if t]


def check_campaign(c, extra_texts=()):
    aud = c.get("audience") if isinstance(c.get("audience"), dict) else {}
    own = campaign_texts(c)
    return check_texts(c["brand"], own + [t for t in extra_texts if t], "ads", item=c,
                       countries=aud.get("countries") or [], audience=aud, review_texts=own)


def describe(violations, n=3):
    def one(v):
        ex = (v.get("excerpt") or "")[:70]
        return f"“{v['match'] or v['rule']}”" + (f" ({ex})" if ex else "")
    return "; ".join(one(v) for v in violations[:n])


def file_block(d, bid, subject, violations, source, **fields):
    """One recommendation per held item (deduped by title), saying why and what to do."""
    blocks = [v for v in violations if v.get("severity", "block") == "block"]
    review = [v for v in violations if v.get("severity") == "needs-review"]
    disclose = [v for v in violations if v.get("severity") == "disclose"]
    parts = []
    if blocks:
        parts.append(f"Blocked before it reached you: {describe(blocks)}.")
    if review:
        parts.append("Needs review: " + "; ".join(f"{v['rule']}" + (f" — {v['fix']}" if v.get("fix") else "")
                                                   for v in review[:3]) + ".")
    if disclose:
        parts.append("Missing disclosure: " + "; ".join(f"{v['rule']}" + (f" — {v['fix']}" if v.get("fix") else "")
                                                          for v in disclose[:3]) + ".")
    ccs = sorted({v["country"] for v in violations if v.get("baseline")})
    parts.append(f"Rules: brands/{bid}/compliance.json" + (f" + {', '.join(ccs)} baselines (otto_compliance.py baselines {bid})"
                                                           if ccs else "") + ".")
    return ap.add_rec_once(d, "P1", f"Compliance hold: {subject[:70]}", " ".join(parts),
                           "Keeps the ad account and the brand out of policy trouble", "Review" if review and not blocks else "Rewrite",
                           brand=bid, source=source, compliance=[v.get("id") or v["rule"] for v in violations][:6], **fields)


# ---------------------------------------------------------------------------------------------------------------
# what applies to a brand (onboarding response, owner console, CLI)
# ---------------------------------------------------------------------------------------------------------------

def summary(bid, d=None, scan=None, countries=None):
    """Which baselines apply to a brand and what they will hold, for the onboarding response and the console.
    scan / countries: in-memory hints (onboarding before its files are written)."""
    d = d if d is not None else _data()
    r = rules(bid, d, scan)
    ccs = [str(c).upper() for c in countries] if countries else r["countries"]
    rows, standing = [], []
    for rule, country in applicable(r, ccs):
        cleared = r["clearances"].get(rule.get("clear_with") or "") if rule.get("clear_with") else None
        row = {"id": rule["id"], "title": rule["title"], "country": country, "severity": rule["severity"],
               "contexts": rule["contexts"], "source": rule["sources"][0],
               "status": "off" if rule["id"] in r["baselines_off"] else "pending" if not rule.get("active", True)
               else "cleared" if cleared else "active"}
        if rule.get("clear_with"):
            row["clear_with"] = rule["clear_with"]
        if row["status"] == "off":
            row["off_reason"] = r["baselines_off"][rule["id"]]
        rows.append(row)
        every = not rule.get("when") or any(t in r["industries"] for t in rule.get("always_for") or [])
        if row["status"] == "active" and every and not rule["patterns"]:     # holds every post / ad until done
            standing.append({"id": rule["id"], "title": rule["title"], "contexts": rule["contexts"], "severity": rule["severity"],
                             "clear_with": rule.get("clear_with"), "fix": rule.get("fix")})
    counts = {s: sum(1 for x in rows if x["severity"] == s and x["status"] == "active") for s in SEVERITIES}
    out = {"countries": ccs, "countries_source": "onboarding" if countries else r["countries_source"],
           "industries": sorted(r["industries"]), "industry_evidence": r["industries"],
           "brand_rules": len(r["patterns"]), "health_baseline": r["baseline"] == "health",
           "required_disclaimer": bool(r["required_disclaimer"]), "clearances": sorted(r["clearances"]),
           "baselines": rows, "counts": counts, "standing_holds": standing, "error": r["error"] or BASELINE_ERROR}
    posts = [p for p in (d.get("posts") or []) if isinstance(p, dict) and p.get("brand") == bid]
    ai = [(ref, rec) for p in posts for ref, rec in ((p.get("media_ai") or {}).items() if isinstance(p.get("media_ai"), dict) else [])
          if isinstance(rec, dict) and rec.get("generated")]
    out["ai_media"] = {"generated": len(ai), "marked": sum(1 for _, rec in ai if rec.get("marked")),
                       "unmarked": [ref for ref, rec in ai if not rec.get("marked")][:10]}
    return out


# ---------------------------------------------------------------------------------------------------------------
# operator actions: brand clearances, per-item reviews
# ---------------------------------------------------------------------------------------------------------------

def clear(bid, key, value=None, remove=False):
    """Record (or remove) a brand clearance in compliance.json. Refuses to touch an unreadable file."""
    f = ap.BRANDS / bid / "compliance.json"
    raw = _raw(bid)
    if raw is not None and raw.get("error"):
        raise ValueError(f"{f} is unreadable — fix it by hand first ({raw['error']})")
    if raw is None:
        raw = {"banned": list(HEALTH_BASELINE) if baseline(bid) else [], "required_disclaimer": None,
               "notes": "Created by otto_compliance.py clear."}
    known = {r.get("clear_with") for r in BL.RULES if r.get("clear_with")}
    if key not in known:
        raise ValueError(f"unknown clearance {key!r} (known: {', '.join(sorted(known))})")
    cl = raw.get("clearances") if isinstance(raw.get("clearances"), dict) else {}
    if remove:
        cl.pop(key, None)
    else:
        if not str(value or "").strip():
            raise ValueError("a clearance needs a value (the number, the date, how it is done)")
        cl[key] = f"{str(value).strip()} · {ap.now_iso()[:10]}"
    raw["clearances"] = cl
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    return cl


def review(item_id, rule_ids, by="admin", note=""):
    """A person reviewed a post / campaign against these rules: record it for the current text, and lift the hold when
    nothing else is left. → (kind, remaining violations)."""
    ids = [x.strip() for x in rule_ids if x.strip()]
    known = {r["id"]: r for r in BL.RULES}
    bad = [x for x in ids if x not in known]
    if bad:
        raise ValueError(f"unknown rule id(s): {', '.join(bad)}")
    blocks = [x for x in ids if known[x]["severity"] == "block"]
    if blocks:
        raise ValueError(f"{', '.join(blocks)} is a block rule: change the text instead of reviewing it")
    with ap.transaction() as d:
        p, c = ap.post(d, item_id), ap.campaign(d, item_id)
        it = p if p is not None else c
        if it is None:
            raise ValueError(f"no post or campaign {item_id}")
        texts = post_texts(it) if p is not None else campaign_texts(it)
        rv = it.get("compliance_review") if isinstance(it.get("compliance_review"), dict) else {}
        for x in ids:
            rv[x] = {"by": by, "at": ap.now_iso(), "note": note[:300], "sha": _sha(texts)}
        it["compliance_review"] = rv
        left = check_post(it) if p is not None else check_campaign(it)
        if not left:
            if p is not None and p.get("compliance_block"):
                p.pop("compliance_block", None)
                if p.get("status") == "draft":
                    p["status"] = "pending_approval"        # back to the owner for approval
            if c is not None and c.get("compliance_hold"):
                c["compliance_hold"] = False
                c.pop("compliance", None)
        return ("post" if p is not None else "campaign"), left


def table():
    rows = []
    for r in BL.RULES:
        rows.append({"id": r["id"], "countries": r["countries"], "industries": r.get("industries") or ["*"],
                     "not_industries": r.get("not_industries") or [], "severity": r["severity"],
                     "contexts": r.get("contexts") or ["posts", "ads"], "clear_with": r.get("clear_with"),
                     "active": r.get("active", True), "title": r["title"],
                     "source": r["source"] if isinstance(r["source"], list) else [r["source"]]})
    return rows


def main():
    a = sys.argv[1:]
    opt = lambda k, dflt="": a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else dflt
    if len(a) >= 3 and a[0] == "check":
        words = [x for x in a[2:] if x != "--ads"]
        v = check_texts(a[1], [" ".join(words)], "ads" if "--ads" in a else "posts")
        print(json.dumps(v, ensure_ascii=False, indent=1) if v else "clean")
        sys.exit(1 if v else 0)
    elif len(a) >= 2 and a[0] == "post":
        p = ap.post(ap.load(), a[1])
        assert p, f"unknown post {a[1]}"
        v = check_post(p)
        print(json.dumps(v, ensure_ascii=False, indent=1) if v else "clean")
        sys.exit(1 if v else 0)
    elif len(a) >= 2 and a[0] == "rules":
        r = rules(a[1])
        print(json.dumps({"banned": [x for x, _ in r["patterns"]], "required_disclaimer": r["required_disclaimer"],
                          "disclaimer_on": r["disclaimer_on"], "error": r["error"], "baseline": r["baseline"],
                          "countries": r["countries"], "industries": r["industries"], "clearances": r["clearances"],
                          "baselines": [x["id"] for x, _ in applicable(r)]}, ensure_ascii=False, indent=1))
    elif len(a) >= 2 and a[0] == "baselines":
        print(json.dumps(summary(a[1]), ensure_ascii=False, indent=1))
    elif a[:1] == ["table"]:
        print(json.dumps(table(), ensure_ascii=False, indent=1))
    elif len(a) >= 3 and a[0] == "clear":
        try:
            cl = clear(a[1], a[2], " ".join(x for x in a[3:] if x != "--remove"), remove="--remove" in a)
        except ValueError as e:
            sys.exit(f"compliance: {e}")
        print(json.dumps(cl, ensure_ascii=False, indent=1))
    elif len(a) >= 3 and a[0] == "review":
        try:
            kind, left = review(a[1], a[2].split(","), by=opt("--by", "admin"), note=opt("--note"))
        except ValueError as e:
            sys.exit(f"compliance: {e}")
        print(f"{kind} {a[1]}: reviewed {a[2]}" + (" · clean, hold lifted" if not left else f" · still held: {describe(left)}"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
