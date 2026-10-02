#!/usr/bin/env python3
"""Render the legal pack (docs/legal/*.md) into static pages (platform/legal/*.html) in the landing's look.

    python3 tools/legal.py            (from platform/; tests/test_legal.py fails while a page is stale)

The markdown files are the source a lawyer edits; the pages are generated, never edited by hand. Supported: # / ## / ###
headings, paragraphs, "- " and "1. " lists (one nested level, indented two spaces), | tables |, "> " callouts, ---,
**bold**, *italic*, `code`, [links](url) and single-line <!-- comments --> (dropped). Square-bracket placeholders in
capitals ([VAT ID]) and reviewer notes ([REVIEW: …], [DECISION: …], [VERIFY: …], [ENGINEERING: …]) are highlighted on the
page, so nothing unfinished can go out unnoticed.

Publishing: docs/legal/facts.json holds the company facts (the placeholders' values: "COMPANY LEGAL NAME", "DOMAIN" …)
and "publish". Filled facts replace their placeholders in every mode. With "publish": true the reviewer notes and the draft
callout are left out, the pages may be indexed, and rendering stops with the list of missing facts while any placeholder is
still open — a published page never shows "[VAT ID]". `python3 tools/legal.py --missing` lists what is still open.

The pages run no script and load nothing from another host: a strict CSP, one stylesheet (assets/legal.css, which also
loads the self-hosted Mona Sans) and an inline SVG favicon. Paths are relative, so the same files work on the apex
(/legal/…), on app. and under /otto/legal/ on the old box.
"""
import html, re, sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
SRC = PLATFORM.parent / "docs" / "legal"
OUT = PLATFORM / "legal"

# page id → (nav label, meta description); the order is the nav order
PAGES = {
    "terms": ("Terms", "Otto's terms of service for businesses: subscriptions, approvals, ad spend, ownership and liability."),
    "privacy": ("Privacy", "What personal data Otto collects, why, how long it is kept, where it goes and your rights."),
    "dpa": ("DPA", "Otto's data processing agreement (GDPR Art. 28) with its security measures and sub-processors."),
    "subprocessors": ("Sub-processors", "The companies that process personal data for Otto, what for and where."),
    "cookies": ("Cookies", "What Otto's websites store in your browser, the one optional choice (ad measurement with Meta) and "
                           "which other hosts they contact."),
    "ai": ("AI transparency", "What in Otto's output is made with AI, how it is marked, and who approves it."),
    "company": ("Company", "Company information for Otto: legal name, address, registration and contact."),
}

CSP = ("default-src 'none'; script-src 'none'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'")
FAVICON = ("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E%3Crect width=%2732%27 "
           "height=%2732%27 rx=%278%27 fill=%27%232447F0%27/%3E%3Crect x=%278%27 y=%278%27 width=%2716%27 height=%2716%27 "
           "rx=%274%27 fill=%27none%27 stroke=%27white%27 stroke-width=%272%27 opacity=%27.9%27/%3E%3C/svg%3E")
NOTE_KINDS = ("REVIEW", "DECISION", "VERIFY", "ENGINEERING")
FACTS = SRC / "facts.json"
TOC_MIN = 5          # a table of contents for pages with at least this many sections

_NOTE = re.compile(r"\[(%s)\b:?\s*([^\[\]\n]*?)\s*\]" % "|".join(NOTE_KINDS))
_PH = re.compile(r"\[([A-Z0-9][^\[\]\na-z]*?)\]")
_LINK = re.compile(r"\[([^\[\]\n]+)\]\(([^()\s]+)\)")
_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_EM = re.compile(r"(?<![*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![*\w])")
_ITEM = re.compile(r"^( *)(-|\d+\.)\s+(.*)$")
_CLAUSE = re.compile(r"^(\d+\.\d+)\s+")


class MissingFacts(Exception):
    pass


def load_facts(path=None):
    """→ (publish, {placeholder: value}) from docs/legal/facts.json (absent → draft, no values)."""
    import json
    f = Path(path) if path else FACTS
    try:
        raw = json.loads(f.read_text())
    except (OSError, ValueError):
        return False, {}
    vals = {k: str(v).strip() for k, v in raw.items()
            if not k.startswith("_") and k != "publish" and isinstance(v, (str, int)) and str(v).strip()}
    return raw.get("publish") is True, vals


_DRAFT_CALLOUT = re.compile(r"^> \*\*Draft.*(?:\n>.*)*\n?", re.M)
_NOTE_ANY = re.compile(r"[ \t]*\[(%s)\b[^\[\]\n]*\]" % "|".join(NOTE_KINDS))


def prepare(md, publish=False, facts=None):
    """Fill the known facts; when publishing, drop reviewer notes and the draft callout, and refuse open placeholders."""
    for k, v in (facts or {}).items():
        md = md.replace(f"[{k}]", v)
    if not publish:
        return md
    md = _DRAFT_CALLOUT.sub("", md)
    md = _NOTE_ANY.sub("", md)
    md = re.sub(r"^Version: Draft [\d.]+ · [^·\n]+ · ", "Version 1.0 · ", md, flags=re.M)
    open_ = sorted({m.group(1) for m in _PH.finditer(_LINK.sub("", md))})
    if open_:
        raise MissingFacts(", ".join(open_))
    return md


def slug(text, seen):
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-") or "section"
    base, n = s, 2
    while s in seen:
        s, n = f"{base}-{n}", n + 1
    seen.add(s)
    return s


def inline(text):
    """One line of markdown → HTML. Code, links, notes and placeholders are cut out first so no rule rewrites another's
    output; bold / italic run last over what is left."""
    keep = []

    def put(h):
        keep.append(h)
        return f"\x00{len(keep) - 1}\x00"

    def emph(s):
        return _EM.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", s))

    def link(m):
        url = m.group(2).replace('"', "%22")
        ext = ' rel="noopener"' if re.match(r"https?://", url) else ""
        return put(f'<a href="{url}"{ext}>{emph(m.group(1))}</a>')

    s = html.escape(text, quote=False)
    s = _CODE.sub(lambda m: put(f"<code>{m.group(1)}</code>"), s)
    s = _LINK.sub(link, s)
    s = _NOTE.sub(lambda m: put(f'<mark class="note"><b>{m.group(1).title()}</b>'
                                f'{": " + emph(m.group(2)) if m.group(2) else ""}</mark>'), s)
    s = _PH.sub(lambda m: put(f'<span class="ph">[{m.group(1)}]</span>'), s)
    s = emph(s)
    while "\x00" in s:
        s = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)
    return s


def para(text):
    m = _CLAUSE.match(text)
    if m:
        return f'<p><span class="cl">{m.group(1)}</span> {inline(text[m.end():])}</p>'
    if text.startswith("Version:"):
        return f'<p class="meta">{inline(text)}</p>'
    return f"<p>{inline(text)}</p>"


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[1:]
    if len(rows) > 1 and set(rows[1].replace("|", "").strip()) <= set("-: "):     # the |---|---| separator line
        body = cells[2:]
    keyed = not any(head)          # "| | |" header: a two-column fact list, the first column labels its row
    out = ['<div class="table" role="region" aria-label="Table" tabindex="0"><table%s>' % (' class="facts"' if keyed else "")]
    out.append("<tbody>" if keyed else
               "<thead><tr>" + "".join(f'<th scope="col">{inline(c)}</th>' for c in head) + "</tr></thead><tbody>")
    for r in body:
        first = f'<th scope="row">{inline(r[0])}</th>' if keyed else f"<td>{inline(r[0])}</td>"
        out.append("<tr>" + first + "".join(f"<td>{inline(c)}</td>" for c in r[1:]) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def lst(items):
    """items: [(indent, marker, text)] → nested <ul>/<ol> (one nested level)."""
    def open_tag(marker):
        if marker == "-":
            return "<ul>", "</ul>"
        n = int(marker[:-1])
        return (f'<ol start="{n}">' if n != 1 else "<ol>"), "</ol>"

    top = []
    for indent, marker, text in items:
        if indent >= 2 and top:
            top[-1][2].append((marker, text))
        else:
            top.append((marker, text, []))
    o, c = open_tag(top[0][0])
    out = [o]
    for marker, text, kids in top:
        li = f"<li>{inline(text)}"
        if kids:
            ko, kc = open_tag(kids[0][0])
            li += ko + "".join(f"<li>{inline(t)}</li>" for _, t in kids) + kc
        out.append(li + "</li>")
    out.append(c)
    return "".join(out)


def render_body(md):
    """markdown → (title, body html)."""
    lines = md.splitlines()
    out, seen, toc, title = [], set(), [], ""
    buf, i = [], 0

    def flush():
        if buf:
            text = " ".join(x.strip() for x in buf).strip()
            if text:
                out.append(para(text))
            buf.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or (s.startswith("<!--") and s.endswith("-->")):
            flush(); i += 1; continue
        if s.startswith("# "):
            flush(); title = s[2:].strip(); out.append(f"<h1>{inline(title)}</h1>"); i += 1; continue
        if s.startswith("## ") or s.startswith("### "):
            flush()
            lvl = 2 if s.startswith("## ") else 3
            text = s[lvl + 1:].strip()
            hid = slug(text, seen)
            if lvl == 2:
                toc.append((hid, text))
            out.append(f'<h{lvl} id="{hid}">{inline(text)}</h{lvl}>'); i += 1; continue
        if s == "---":
            flush(); out.append("<hr>"); i += 1; continue
        if s.startswith(">"):
            flush()
            quote, paras = [], []
            while i < len(lines) and lines[i].strip().startswith(">"):
                t = lines[i].strip()[1:].strip()
                if t:
                    quote.append(t)
                elif quote:
                    paras.append(" ".join(quote)); quote = []
                i += 1
            if quote:
                paras.append(" ".join(quote))
            cls = "callout draft" if paras and paras[0].startswith("**Draft") else "callout"
            out.append(f'<div class="{cls}">' + "".join(f"<p>{inline(p)}</p>" for p in paras) + "</div>")
            continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i]); i += 1
            out.append(table(rows)); continue
        m = _ITEM.match(ln)
        if m and len(m.group(1)) < 2:
            flush()
            items = []
            while i < len(lines):
                m = _ITEM.match(lines[i])
                if m:
                    items.append((len(m.group(1)), m.group(2), m.group(3).strip()))
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    ind, mk, t = items[-1]
                    items[-1] = (ind, mk, t + " " + lines[i].strip())
                else:
                    break
                i += 1
            out.append(lst(items)); continue
        buf.append(ln); i += 1
    flush()
    if len(toc) >= TOC_MIN:
        nav = ('<nav class="toc" aria-label="On this page"><p class="toc-h">On this page</p><ol>'
               + "".join(f'<li><a href="#{h}">{inline(t)}</a></li>' for h, t in toc) + "</ol></nav>")
        first = next(k for k, x in enumerate(out) if x.startswith("<h2"))
        out.insert(first, nav)
    return title, "\n".join(out)


def page(name, md, publish=False, facts=None):
    title, body = render_body(prepare(md, publish, facts))
    facts = facts or {}
    label, desc = PAGES[name]
    plain = re.sub(r"<[^>]+>", "", inline(title))
    cur = ' aria-current="page"'
    nav = "".join(f'<a href="{p}.html"{cur if p == name else ""}>{l}</a>' for p, (l, _) in PAGES.items())
    robots = "" if publish else ("<!-- draft: keep out of search engines until a lawyer has approved the text; remove this line "
                                 "when publishing -->\n<meta name=\"robots\" content=\"noindex\">\n")
    mail = facts.get("CONTACT EMAIL")
    ask = html.escape(mail) if mail else '<span class="ph">[CONTACT EMAIL]</span>'
    foot = (f'<footer class="wrap foot"><span>Otto · legal, in force from {html.escape(facts.get("EFFECTIVE DATE", ""))}</span>'
            f"<span>Questions: {ask}</span></footer>") if publish else \
        f'<footer class="wrap foot"><span>Otto · legal pack, draft of 30 September 2026</span><span>Questions: {ask}</span></footer>'
    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<!-- Generated by platform/tools/legal.py from docs/legal/{name}.md: edit the markdown, then run python3 tools/legal.py -->
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{plain} · Otto</title>
<meta name="description" content="{html.escape(desc)}">
{robots}<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F5F7FB" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0C0D0F" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{FAVICON}">
<link rel="preload" href="../assets/landing/mona-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="../assets/legal.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap top-in"><a class="brand" href="../" aria-label="Otto, home"><span class="mark" aria-hidden="true"></span>Otto</a><span class="top-t">Legal</span></div>
  <nav class="wrap tabs" aria-label="Legal documents">{nav}</nav>
</header>
<main id="main" class="wrap doc" tabindex="-1">
{body}
<p class="up"><a href="#main">Back to top</a></p>
</main>
{foot}
</body>
</html>
"""


def render_all(src=SRC, facts_path=None):
    publish, facts = load_facts(facts_path or Path(src) / "facts.json")
    return {name: page(name, (Path(src) / f"{name}.md").read_text(), publish, facts) for name in PAGES}


def missing(src=SRC):
    """Placeholders still open across the pack (what facts.json needs before "publish": true)."""
    _, facts = load_facts(Path(src) / "facts.json")
    out = set()
    for name in PAGES:
        md = prepare((Path(src) / f"{name}.md").read_text(), False, facts)
        md = _DRAFT_CALLOUT.sub("", _NOTE_ANY.sub("", md))
        out |= {m.group(1) for m in _PH.finditer(_LINK.sub("", md))}
    return sorted(out)


def main():
    if "--missing" in sys.argv:
        print("\n".join(missing()) or "nothing open")
        return 0
    OUT.mkdir(exist_ok=True)
    try:
        pages = render_all()
    except MissingFacts as e:
        sys.exit(f"publish is on but these facts are missing in docs/legal/facts.json: {e}")
    for name, text in pages.items():
        (OUT / f"{name}.html").write_text(text)
        print(f"legal/{name}.html")


if __name__ == "__main__":
    sys.exit(main())
