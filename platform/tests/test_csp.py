#!/usr/bin/env python3
"""Every executable inline <script> in the served pages must be allowed by that page's CSP hash, or the browser refuses
to run it (the page silently stops working). Refresh the hashes with: cd platform && python3 tools/csp.py"""
import base64, hashlib, re, sys, unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM / "tools"))
import csp  # noqa: E402


class CspTest(unittest.TestCase):
    def test_inline_scripts_match_their_hashes(self):
        for name in csp.PAGES:
            html = (PLATFORM / name).read_text()
            meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
            self.assertTrue(meta, f"{name} has no CSP meta")
            allowed = set(re.findall(r"'sha256-[^']+'", meta.group(1)))
            for m in csp.EXEC.finditer(html):
                h = "'sha256-%s'" % base64.b64encode(hashlib.sha256(m.group(2).encode()).digest()).decode()
                self.assertIn(h, allowed, f"{name}: an inline script changed; run `python3 tools/csp.py` in platform/")

    def test_vendored_libraries_match_their_sri(self):
        """The landing's animation code is served from assets/vendor/ (no request to a CDN), byte for byte the pinned files."""
        self.assertEqual(csp.vendor_problems(PLATFORM), [])
        html = (PLATFORM / "landing.html").read_text()
        for rel, sri in csp.VENDOR.items():
            self.assertIn(sri, html, f"landing.html does not pin {rel}")
            self.assertIn(rel[len("assets/vendor/"):], html, f"landing.html does not load {rel}")

    def test_pages_load_nothing_from_other_hosts(self):
        """No served page pulls code, styles or fonts from a third-party host (links the visitor clicks are fine; the legal
        pages may name hosts in their text)."""
        third = ("cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com", "unpkg.com", "cdnjs.cloudflare.com")
        for name in csp.PAGES:                                   # pages with code: not even in a script string
            html = (PLATFORM / name).read_text()
            for host in third:
                self.assertNotIn(host, html, f"{name} still loads from {host}")
        for name in list(csp.PAGES) + [f"legal/{f.name}" for f in sorted((PLATFORM / "legal").glob("*.html"))]:
            html = (PLATFORM / name).read_text()
            for m in re.finditer(r'<(script|link|img|source|video|audio|iframe)\b[^>]*?\b(?:src|href)="((?:https?:)?//[^"]*)"', html):
                tag = html[m.start():html.index(">", m.start()) + 1]
                ok = (m.group(1) == "link" and re.search(r'rel="(canonical|alternate)"', tag)) or \
                    (m.group(1) == "script" and m.group(2) in csp.EXTERNAL.get(name, []))
                self.assertTrue(ok, f"{name} loads {m.group(2)}")
            for m in re.finditer(r'url\(\s*["\']?((?:https?:)?//[^"\')]+)', html):
                self.fail(f"{name} loads {m.group(1)} from CSS")

    def test_only_the_billing_page_talks_to_stripe(self):
        """Stripe.js (js.stripe.com) and Stripe's frames are allowed on billing.html only; every other page keeps
        frame-src 'none' and connect-src 'self'."""
        for name in csp.PAGES:
            pol = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', (PLATFORM / name).read_text()).group(1)
            if name == "billing.html":
                for want in ("https://js.stripe.com", "https://checkout.stripe.com", "https://api.stripe.com", "https://hooks.stripe.com"):
                    self.assertIn(want, pol)
                self.assertNotIn("'unsafe-eval'", pol)
                self.assertFalse(re.search(r"script-src[^;]*\*(?!\.js\.stripe\.com)", pol), "no wildcard script host")
            else:
                self.assertNotIn("stripe", pol, f"{name} must not allow Stripe")
                self.assertIn("frame-src 'none'", pol)
                self.assertIn("connect-src 'self';", pol)

if __name__ == "__main__":
    unittest.main()
