#!/usr/bin/env python3
"""Write (or refresh) the Content-Security-Policy <meta> in each page: sha256 hashes of every executable inline <script>
(JSON / JSON-LD data blocks are not executed, so not hashed) + the page's fixed sources. Re-run after editing any inline script:
    python3 tools/csp.py            (from platform/; tests/test_csp.py fails while a hash is stale)"""
import base64, hashlib, re, sys
from pathlib import Path

# The landing's animation libraries are self-hosted (assets/vendor/, the exact files jsDelivr served for these pinned
# versions, byte for byte) and load with subresource integrity, so no page makes a request to another host for code.
# Same-origin files are covered by 'self'; CSP host sources cannot name a relative path, so nothing is added per file.
# VENDOR is the manifest: local path (relative to platform/) → the SRI hash landing.html pins it with; main() and
# tests/test_csp.py check that every file is present and still matches.
VENDOR = {
    "assets/vendor/gsap@3.15.0/dist/gsap.min.js": "sha384-XmJ9SoHtVOHoQUcKvFAzVXwdkKo1Ie3bhmSoIAkcdsHGaIrVJIkmozyq0FJeb/Ly",
    "assets/vendor/gsap@3.15.0/dist/ScrollTrigger.min.js": "sha384-wl5TeDVvOWt30Pbf8aSo2ZrzsOjddu3avOBvHe+p+OhJt9gP6w9YXmDkN5DK2/dF",
    "assets/vendor/lenis@1.3.26/dist/lenis.min.js": "sha384-jqpi9VmOdhyLoLURgjCn7EpnG9BbnHW57ibIZoeaIU+erWDH3k8fQQg0xH2ySjnw",
    "assets/vendor/three@0.186.1/build/three.module.js": "sha384-m8JoFX52V6NGv2usipnlLJKnJfL7IE8dbniPDDCSGSQv3Hm4n6PjfV6syVwfuoRc",
    "assets/vendor/three@0.186.1/build/three.core.js": "sha384-mdKeCwPEcbDvzaxwhm+MVuLoMou+E7jQqrs4tmu/n8HBYPGI1kZt0MkJxlMR4zFM",
    "assets/vendor/three@0.186.1/examples/jsm/renderers/CSS3DRenderer.js":
        "sha384-6I827Bd2N6ydzREj76AdVsj8rVhZzdZShpXYLd4SUcLOD1RNUdg6qrGM3K4qmBXF",
    "assets/vendor/three@0.186.1/examples/jsm/environments/RoomEnvironment.js":
        "sha384-/H49oz0ZtMgJNgMZ+OhhuMuKBOsaiC3kY0/PZSvgJJXAOJJwmSBJjzlV5lJul3MB",
}
BASE = ["default-src 'self'", "style-src 'self' 'unsafe-inline'", "font-src 'self'", "connect-src 'self'", "object-src 'none'",
        "base-uri 'self'", "form-action 'self'", "frame-src 'none'", "worker-src 'none'", "manifest-src 'self'"]
PAGES = {
    "landing.html":    {"script": [], "img-src": "'self' data: https:", "media-src": "'self'"},
    "onboarding.html": {"script": [], "img-src": "'self' data: https:", "media-src": "'none'"},
    "index.html":      {"script": [], "img-src": "'self' data: blob: https:", "media-src": "'self' blob: https:"},
    "admin.html":      {"script": [], "img-src": "'self' data:", "media-src": "'none'"},
    # the early design mockups (they send a client on to the app unless ?mockup): same-origin only
    "approve.html":    {"script": [], "img-src": "'self' data:", "media-src": "'none'"},
    "ads.html":        {"script": [], "img-src": "'self' data:", "media-src": "'none'"},
    "analytics.html":  {"script": [], "img-src": "'self' data:", "media-src": "'none'"},
}
EXEC = re.compile(r'<script((?:\s+type="(?:importmap|module|text/javascript)")?)>(.*?)</script>', re.S)
META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">\n')
NOTE = ('<!-- CSP: script-src lists the sha256 of every inline script element in this page. After editing one, the browser refuses it'
        ' and its console prints the new hash: replace the old one here (or recompute all of them). -->\n')
OLD_NOTES = [re.compile(r'<!-- CSP: script-src lists the sha256 of every inline .*? -->\n', re.S)]


def policy(html, cfg):
    hashes = ["'sha256-%s'" % base64.b64encode(hashlib.sha256(m.group(2).encode()).digest()).decode() for m in EXEC.finditer(html)]
    parts = list(BASE[:1]) + ["script-src 'self' " + " ".join(hashes + cfg["script"])] + BASE[1:] + \
        ["img-src " + cfg["img-src"], "media-src " + cfg["media-src"]]
    return "; ".join(parts), len(hashes)


def sri(path):
    return "sha384-" + base64.b64encode(hashlib.sha384(Path(path).read_bytes()).digest()).decode()


def vendor_problems(root):
    """Vendored files that are missing or no longer match the SRI hash the landing pins them with."""
    out = []
    for rel, want in VENDOR.items():
        f = Path(root) / rel
        if not f.is_file():
            out.append(f"{rel} is missing")
        elif sri(f) != want:
            out.append(f"{rel} does not match its SRI hash {want}")
    return out


def main(root):
    bad = vendor_problems(root)
    if bad:
        sys.exit("vendored files: " + "; ".join(bad))
    for name, cfg in PAGES.items():
        p = Path(root) / name
        html = META.sub("", p.read_text())
        for rx in OLD_NOTES:
            html = rx.sub("", html)
        pol, n = policy(html, cfg)
        tag = NOTE + '<meta http-equiv="Content-Security-Policy" content="%s">\n' % pol
        html = html.replace('<meta charset="utf-8">\n', '<meta charset="utf-8">\n' + tag, 1)
        assert tag in html, name
        p.write_text(html)
        print(f"{name}: {n} inline script hash{'es' * (n != 1)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent))
