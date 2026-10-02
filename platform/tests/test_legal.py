#!/usr/bin/env python3
"""The legal pages (platform/legal/*.html) are generated from docs/legal/*.md by tools/legal.py: they must be up to date,
run no script, load nothing from another host (the cookie notice says so), and be linked from the landing and from
onboarding next to the button that starts setup. Re-render with: cd platform && python3 tools/legal.py"""
import re, sys, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM / "tools"))
import legal  # noqa: E402


class LegalPagesTest(unittest.TestCase):
    def test_pages_are_up_to_date(self):
        for name, text in legal.render_all().items():
            p = PLATFORM / "legal" / f"{name}.html"
            self.assertTrue(p.exists(), f"legal/{name}.html missing: run `python3 tools/legal.py` in platform/")
            self.assertEqual(p.read_text(), text, f"legal/{name}.html is stale: run `python3 tools/legal.py` in platform/")

    def test_strict_csp_no_scripts_no_third_parties(self):
        for name in legal.PAGES:
            html = (PLATFORM / "legal" / f"{name}.html").read_text()
            meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
            self.assertTrue(meta, name)
            csp = meta.group(1)
            for d in ("default-src 'none'", "script-src 'none'", "style-src 'self'", "base-uri 'none'", "form-action 'none'"):
                self.assertIn(d, csp, f"{name}: CSP lacks {d}")
            self.assertNotIn("unsafe-inline", csp)
            self.assertNotRegex(html, r"<script\b", name)
            self.assertNotRegex(html, r"\sstyle=", f"{name}: inline style (the CSP refuses it)")
            self.assertNotRegex(html, r"\son[a-z]+=", f"{name}: inline event handler")
            # every resource the page loads (<link href>, src=) is on our own host
            for m in re.finditer(r'<link\b[^>]*\bhref="([^"]+)"|\bsrc="([^"]+)"', html):
                url = m.group(1) or m.group(2)
                self.assertFalse(re.match(r"(https?:)?//", url), f"{name}: loads {url} from another host")
            if not legal.load_facts()[0]:              # draft until docs/legal/facts.json says "publish": true
                self.assertIn("Draft — must be reviewed by a qualified lawyer in the EU before publishing", html, name)

    def test_nav_and_cross_links_resolve(self):
        for name in legal.PAGES:
            html = (PLATFORM / "legal" / f"{name}.html").read_text()
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            for href in re.findall(r'<a href="([^"]+)"', html):
                if re.match(r"(https?:|mailto:)", href) or href == "../":
                    continue
                page, _, frag = href.partition("#")
                if page:
                    self.assertIn(page[:-5] if page.endswith(".html") else page, legal.PAGES, f"{name}: link to {href}")
                    if frag:
                        target = (PLATFORM / "legal" / page).read_text()
                        self.assertIn(f'id="{frag}"', target, f"{name}: {href} has no such section")
                elif frag:
                    self.assertIn(frag, ids, f"{name}: #{frag} has no such section")

    def test_subprocessor_tables_match(self):
        """The sub-processors page and Annex III of the DPA list the same companies, word for word."""
        def table(f):
            s = (legal.SRC / f).read_text()
            m = re.search(r"<!-- subprocessors:start.*?-->\n(.*?)<!-- subprocessors:end -->", s, re.S)
            self.assertTrue(m, f"{f}: subprocessors markers missing")
            return m.group(1).strip()
        self.assertEqual(table("subprocessors.md"), table("dpa.md"))

    def test_landing_and_onboarding_link_the_legal_pages(self):
        landing = (PLATFORM / "landing.html").read_text()
        for name in legal.PAGES:
            self.assertIn(f'href="legal/{name}.html"', landing, f"landing footer lacks legal/{name}.html")
        onb = (PLATFORM / "onboarding.html").read_text()
        step4 = re.search(r'<section class="st" id="s4".*?</section>', onb, re.S).group(0)
        consent = re.search(r'<p class="act-legal" id="consent">(.*?)</p>', step4, re.S)
        self.assertTrue(consent, "step 4 (its button starts setup) has no consent line")
        for page in ("terms", "dpa"):
            self.assertIn(f'href="legal/{page}.html"', consent.group(1))
        self.assertIn('id="go5" aria-describedby="consent"', step4)
        step5 = re.search(r'<section class="st" id="s5".*?</section>', onb, re.S).group(0)
        self.assertIn('href="legal/terms.html"', step5)
        self.assertIn('href="legal/dpa.html"', step5)


if __name__ == "__main__":
    unittest.main()


class PublishModeTest(unittest.TestCase):
    """docs/legal/facts.json "publish": true → no draft callout, no reviewer notes, no placeholder, indexable; and it refuses
    to render while a fact is missing."""

    def facts(self, tmp, publish=True, drop=None):
        import json, tempfile
        vals = {k: "Example value" for k in legal.missing()}
        vals.update({"CONTACT EMAIL": "hello@otto.example", "EFFECTIVE DATE": "3 October 2026"})
        _, known = legal.load_facts()
        vals.update(known)
        if drop:
            vals.pop(drop, None)
        f = Path(tmp) / "facts.json"
        f.write_text(json.dumps(dict(vals, publish=publish)))
        return f

    def test_published_pages_are_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pages = legal.render_all(facts_path=self.facts(tmp))
        for name, html in pages.items():
            self.assertNotIn("Draft —", html, name)
            self.assertNotIn('class="note"', html, name)
            self.assertNotIn('class="ph"', html, name)
            self.assertNotIn("noindex", html, name)
            self.assertNotIn("<p></p>", html, name)
            self.assertNotRegex(html, r"\[(REVIEW|DECISION|VERIFY|ENGINEERING)\b", name)
            self.assertIn("hello@otto.example", html, name)
        self.assertIn("Version 1.0", pages["terms"])

    def test_publish_refuses_open_placeholders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(legal.MissingFacts) as cm:
                legal.render_all(facts_path=self.facts(tmp, drop="VAT ID"))
        self.assertIn("VAT ID", str(cm.exception))

    def test_draft_mode_keeps_notes_and_placeholders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pages = legal.render_all(facts_path=self.facts(tmp, publish=False, drop="VAT ID"))
        self.assertIn("Draft —", pages["company"])
        self.assertIn('<span class="ph">[VAT ID]</span>', pages["company"])
        self.assertIn("noindex", pages["company"])
