#!/usr/bin/env python3
"""Otto strategy file — the structured brain every script reads instead of pattern-matching markdown.

  otto_strategy.py init  <brand>          # scaffold brands/<slug>/strategy.json from the profile, scan and competitor angles
  otto_strategy.py check <brand>          # list the gaps (fields still "(?)") → the ≤4 onboarding questions
  otto_strategy.py concepts <brand> [n]   # print n concept briefs (angle × persona × stage × 3 hooks) for the planner / ads

strategy.json (agent fills the inferred parts; owner answers the ASK items once):
{
  "brand", "currency", "language", "tz",
  "personas":   [{"id","label","situation","awareness":"unaware|problem|solution|product|most","words":[verbatim phrases]}],
  "pains":      [{"text","persona","source"}],            # customer's own words, with source (review url / call note)
  "objections": [{"text","answer","proof_id"}],
  "offers":     [{"id","name","price","terms","deadline":null,"stage":"hot"}],
  "proof_bank": [{"id","claim","source"}],               # only claims with a source may appear in copy or video
  "cta_by_stage":     {"cold":..., "warm":..., "hot":...},
  "landing_by_stage": {"cold": url, "warm": url, "hot": url},
  "events":     [{"date","name","use"}],                  # launches, open days, seasonal peaks
  "targets":    {"cpl": null, "cpa": null, "roas": null}, # ASK at onboarding
  "angles":     [{"id","angle","persona","stage","source":"competitor|profile|test","status":"idea|testing|winner|loser"}],
  "ask":        [questions still open, max 4]
}
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
BRANDS = HERE.parent / "brands"
HOOKS = HERE.parent / "skills" / "otto-creative-engine" / "hooks"
Q = "(?)"


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def bullets(md, heading):
    m = re.search(r"^##[^\n]*" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^## |\Z)", md, re.S | re.M | re.I)
    if not m:
        return []
    out = []
    for ln in m.group(1).splitlines():
        t = re.sub(r"\*\*|__|`", "", ln).strip().lstrip("-*•0123456789. ").strip()
        if 6 < len(t) < 300 and Q not in t:
            out.append(t)
    return out


def quotes(md):
    return list(dict.fromkeys(re.findall(r"[\"“„]([^\"”“„]{12,200})[\"”“]", md)))[:12]


def init(bid):
    bdir = BRANDS / bid
    md = (bdir / "brand-profile.md").read_text() if (bdir / "brand-profile.md").exists() else ""
    scan = load_json(bdir / "scan.json", {})
    angles = load_json(bdir / "angles.json", {}).get("angles", [])
    url = (scan.get("final_url") or "").split("?")[0]
    langs = scan.get("languages") or []
    cur = (scan.get("commerce") or {}).get("currency") or ("ILS" if "he" in langs else "EUR")
    personas = []
    for i, line in enumerate(bullets(md, "Avatars")[:4], 1):
        label = line.split("—")[0].split(":")[0].strip()[:60]
        personas.append({"id": f"p{i}", "label": label, "situation": line[:200], "awareness": Q, "words": [q for q in quotes(line)][:3]})
    pains = [{"text": t, "persona": Q, "source": "brand-profile.md"} for t in bullets(md, "Pain")[:8]]
    objections = []
    for t in bullets(md, "Objections")[:8]:
        parts = re.split(r"\s*(?:→|->|—)\s*", t, maxsplit=1)
        objections.append({"text": parts[0][:160], "answer": parts[1][:240] if len(parts) > 1 else Q, "proof_id": Q})
    proof = [{"id": f"pr{i}", "claim": t[:200], "source": url or "site"} for i, t in enumerate((scan.get("trust") or [])[:8], 1)]
    proof += [{"id": f"rv{i}", "claim": f"“{q}”", "source": "customer review (verify consent)"} for i, q in enumerate((scan.get("quotes") or [])[:4], 1)]
    offers = [{"id": f"o{i}", "name": Q, "price": p, "terms": Q, "deadline": None, "stage": "hot"} for i, p in enumerate((scan.get("commerce") or {}).get("prices", [])[:3], 1)]
    ang = [{"id": f"a{i}", "angle": a.get("angle", "")[:200], "persona": Q, "stage": Q, "source": a.get("source", "competitor"), "status": "idea"} for i, a in enumerate(angles, 1)]
    ang += [{"id": f"a{len(ang)+i}", "angle": t[:200], "persona": Q, "stage": Q, "source": "profile", "status": "idea"} for i, t in enumerate(bullets(md, "Winning angles")[:6], 1)]
    s = {"brand": bid, "currency": cur, "language": (langs or ["en"])[0], "tz": "Asia/Jerusalem" if "he" in langs else "Europe/Berlin",
         "personas": personas, "pains": pains, "objections": objections, "offers": offers, "proof_bank": proof,
         "cta_by_stage": {"cold": Q, "warm": Q, "hot": Q}, "landing_by_stage": {"cold": url or Q, "warm": url or Q, "hot": url or Q},
         "events": [], "targets": {"cpl": None, "cpa": None, "roas": None}, "angles": ang, "ask": []}
    s["ask"] = gaps(s)[:4]
    out = bdir / "strategy.json"
    if out.exists():
        old = load_json(out, {})
        for k, v in old.items():           # never overwrite what the agent/owner already filled
            if v not in (None, "", [], {}, Q):
                s[k] = v
    out.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    print(f"{bid}: strategy.json · {len(personas)} personas · {len(pains)} pains · {len(objections)} objections · {len(proof)} proof · {len(s['angles'])} angles · ask {len(s['ask'])}")
    return s


def gaps(s):
    q = []
    if not s["targets"].get("cpl") and not s["targets"].get("cpa"):
        q.append("What is a lead or a sale worth to you — the most you'd pay for one?")
    if not s["offers"] or all(o.get("name") in (None, Q) for o in s["offers"]):
        q.append("What is the one offer you want new customers to take first (price, terms, any real deadline)?")
    if not s["objections"] or all(o.get("answer") in (None, Q) for o in s["objections"]):
        q.append("What do people ask or worry about most before they buy?")
    if len(s["proof_bank"]) < 3:
        q.append("What proof can we show (reviews you have permission to quote, certificates, numbers you can back)?")
    if s["cta_by_stage"].get("hot") in (None, Q):
        q.append("Where should a ready-to-buy customer land: shop page, booking link, WhatsApp, or form?")
    return q


def check(bid):
    s = load_json(BRANDS / bid / "strategy.json", None)
    if not s:
        sys.exit(f"no strategy.json for {bid} — run init")
    holes = [k for k, v in s.items() if v == Q] + [f"{k}[{i}].{f}" for k in ("personas", "objections", "offers", "angles")
                                                   for i, it in enumerate(s.get(k, [])) for f, v in it.items() if v == Q]
    print(f"{bid}: {len(holes)} open field(s)"); [print("  ·", h) for h in holes[:30]]
    print("onboarding questions (≤4):"); [print("  ?", x) for x in gaps(s)[:4]]


def concepts(bid, n=4):
    s = load_json(BRANDS / bid / "strategy.json", None)
    hooks = load_json(HOOKS / "_universal.json", {"types": []})["types"]
    if not s:
        sys.exit(f"no strategy.json for {bid} — run init")
    ang = [a for a in s.get("angles", []) if a.get("status") in ("winner", "testing", "idea")] or [{"angle": p["text"], "id": "p"} for p in s.get("pains", [])]
    per = s.get("personas") or [{"id": "p1", "label": "core buyer"}]
    for i, a in enumerate(ang[:n]):
        persona = per[i % len(per)]
        stage = a.get("stage") if a.get("stage") not in (None, Q) else ("cold" if i % 3 == 0 else "warm" if i % 3 == 1 else "hot")
        hs = [h for h in hooks if stage in h["stage"]][:3] or hooks[:3]
        print(f"\nConcept {i+1}: {a['angle'][:120]}\n  persona: {persona['label']} · stage: {stage} · CTA: {s['cta_by_stage'].get(stage)} · landing: {s['landing_by_stage'].get(stage)}")
        for h in hs:
            print(f"  hook [{h['id']}] {h['template']}   (e.g. {h['example']})")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "init":
        init(a[1])
    elif len(a) >= 2 and a[0] == "check":
        check(a[1])
    elif len(a) >= 2 and a[0] == "concepts":
        concepts(a[1], int(a[2]) if len(a) > 2 else 4)
    else:
        print(__doc__)
