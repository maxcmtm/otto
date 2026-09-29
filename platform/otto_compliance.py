#!/usr/bin/env python3
"""Otto compliance — per-brand banned phrases + required disclaimer, checked before anything reaches
the owner or spends money.

  otto_compliance.py check <brand> "<text>"      # prints violations (exit 1 if any)
  otto_compliance.py post <post-id>              # check one post from data.json
  otto_compliance.py rules <brand>

Rules: brands/<slug>/compliance.json
  {"banned": ["plain phrase", "re:<regex>", ...], "required_disclaimer": "<text>" | null,
   "disclaimer_on": ["posts"] (default; add "ads" to require it in ad bodies too), "notes": "..."}
Plain phrases match case-insensitively on word boundaries; "re:" entries are Python regexes (case-insensitive).
No compliance.json yet (a brand just onboarded): a health / therapy / CBD / clinic brand — judged from its scan industry and
profile — gets the HEALTH_BASELINE rules (cure/heal claims and personal-attribute call-outs in the EU languages + Hebrew),
so a restricted brand is never checked against nothing. An unreadable compliance.json holds everything (fails closed).
The required disclaimer is removed from the text before the banned scan, so a disclaimer that says
"does not treat or cure" never trips its own rule.
Callers: otto_telegram.send_cards (a violating card is not sent) and otto_ads.launch (a violating campaign
is put on compliance hold). Both file one recommendation per blocked item (add_rec_once).
"""
import json, re, sys

import ap

# Meta personal-attributes policy + health-claim rules (EU health-claims / HWG-style) for brands that have no rules file yet
HEALTH_BASELINE = [
    r"re:\bcur(e|es|ed|ing)\b", r"re:\bheal(s|ed|ing)?\b", r"re:\bguaranteed (results|cure|to work)\b",
    r"re:\bdo you suffer\b", r"re:\bare you suffering\b", r"re:\bare you (depressed|anxious|traumati[sz]ed|struggling with)\b",
    r"re:\byour (anxiety|depression|trauma|adhd|ptsd|panic attacks|illness|disease)\b",
    r"re:\b(heilt|heilen|heilung|geheilt|heilend)\b", r"re:\bleiden sie (an|unter)\b",
    r"re:\b(curar|curamos|curou)\b", r"re:\bsofre de\b", r"re:\b(geneest|genezen|genezing)\b", r"re:\blijdt u aan\b",
    r"re:\b(guarisce|guarire|guarigione)\b", r"re:\bsoffri di\b", r"re:\b(guérit|guérir|guérison)\b", r"re:\bsouffrez-vous\b",
    r"re:(?<![\u0590-\u05FF])[והלשבכמ]?(מרפא|מרפאים|מרפאה את|לרפא|תרפא|נרפא|נרפאה|ריפוי)(?![\u0590-\u05FF])",
    r"re:האם (אתה|את|אתם|אתן) (סובל|סובלת|סובלים|סובלות|מתמודד|מתמודדת|מתמודדים|מתמודדות)",
    r"re:(?<![\u0590-\u05FF])(אתה|את|אתם|אתן) (סובל|סובלת|סובלים|סובלות) מ",
]
HEALTH = re.compile(r"cbd|hemp|cannab|clinic|medical|dental|dentist|zahnarzt|zahnmedizin|arztpraxis|therap|psycholog|mental health|"
                    r"supplement|pharma|physio|aesthetic|med ?spa|תרפי|טיפול|מרפא|קליניק|פסיכו", re.I)


def baseline(bid):
    """Which baseline applies to a brand with no compliance.json: "health" or None (from the scan industry + profile head)."""
    s = ap.scan_of(bid)
    prof = ap.BRANDS / bid / "brand-profile.md"
    text = " ".join([s.get("industry") or "", (s.get("identity") or {}).get("title") or "",
                     (s.get("identity") or {}).get("description") or "", prof.read_text()[:3000] if prof.exists() else ""])
    return "health" if HEALTH.search(text) else None


def rules(bid):
    f = ap.BRANDS / bid / "compliance.json"
    raw = {}
    if f.exists():
        try:
            raw = json.loads(f.read_text())
        except Exception as e:
            raw = {"banned": [], "error": f"compliance.json unreadable: {e}"}
    elif baseline(bid):
        raw = {"banned": HEALTH_BASELINE, "baseline": baseline(bid)}
    pats = []
    for rule in raw.get("banned") or []:
        rule = str(rule)
        if rule.startswith("re:"):
            try:
                pats.append((rule, re.compile(rule[3:], re.I)))
            except re.error as e:
                print(f"compliance: bad regex in {bid}: {rule} ({e})", file=sys.stderr)
        elif rule.strip():
            pats.append((rule, re.compile(r"(?<!\w)" + re.escape(rule.strip()) + r"(?!\w)", re.I)))
    return {"patterns": pats, "required_disclaimer": raw.get("required_disclaimer"),
            "disclaimer_on": raw.get("disclaimer_on") or ["posts"], "error": raw.get("error"), "baseline": raw.get("baseline")}


def check_texts(bid, texts, context="posts"):
    """→ list of {"rule", "match", "excerpt"}; empty list = clean."""
    r = rules(bid)
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    blob = "\n".join(texts)
    out = []
    if r["error"] and blob:                          # fail closed: a broken rules file must not wave everything through
        out.append({"rule": "compliance.json unreadable", "match": "", "excerpt": r["error"][:120]})
    disc = (r["required_disclaimer"] or "").strip()
    scan = blob
    if disc:
        scan = re.sub(re.escape(disc), " ", scan, flags=re.I)
        if context in r["disclaimer_on"] and disc.lower() not in blob.lower():
            out.append({"rule": "required_disclaimer", "match": "", "excerpt": f"missing: “{disc[:80]}”"})
    for rule, pat in r["patterns"]:
        m = pat.search(scan)
        if m:
            s = max(0, m.start() - 30)
            out.append({"rule": rule, "match": m.group(0), "excerpt": scan[s:m.end() + 30].replace("\n", " ").strip()})
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
    return check_texts(p["brand"], post_texts(p), "posts")


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
    return [t for t in out if t]


def check_campaign(c, extra_texts=()):
    return check_texts(c["brand"], campaign_texts(c) + [t for t in extra_texts if t], "ads")


def describe(violations, n=3):
    return "; ".join(f"“{v['match'] or v['rule']}” ({v['excerpt'][:70]})" for v in violations[:n])


def file_block(d, bid, subject, violations, source, **fields):
    """One recommendation per blocked item (deduped by title)."""
    return ap.add_rec_once(d, "P1", f"Compliance hold: {subject[:70]}",
                           f"Blocked before it reached you: {describe(violations)}. Rules: brands/{bid}/compliance.json.",
                           "Keeps the ad account and the brand out of policy trouble", "Rewrite",
                           brand=bid, source=source, compliance=[v["rule"] for v in violations][:6], **fields)


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "check":
        v = check_texts(a[1], [" ".join(a[2:])])
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
                          "disclaimer_on": r["disclaimer_on"], "error": r["error"], "baseline": r["baseline"]}, ensure_ascii=False, indent=1))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
