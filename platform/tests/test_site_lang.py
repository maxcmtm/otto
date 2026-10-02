#!/usr/bin/env python3
"""The site's language (landing + onboarding): English is the page and the default for everyone; Nederlands and Deutsch are
an option the visitor picks, from same-origin dictionaries (assets/i18n/<page>.<lang>.json + common.<lang>.json) applied by
assets/i18n/site-lang.js to elements marked data-i18n / data-i18n-rich / data-i18n-attr, and to the scripts' own strings
(T / TN / TK calls). These tests keep the dictionaries and the pages in step:
  - every key a page uses exists in every dictionary, and every dictionary key is used;
  - the dictionaries are valid JSON, flat string → string, with no empty value and no markup or script;
  - placeholders ({name}) and [bracketed] parts match the English;
  - English is the default: nothing reads the browser's language or location to pick one;
  - no Hebrew, Cyrillic or other non-Latin script in what a visitor sees, in any page or dictionary;
  - the banned phrases stay out in every language; German says "Sie" (as the e-mails do), Dutch says "je".
Run: cd platform && python3 tests/test_site_lang.py"""
import json, re, unicodedata, unittest
from html.parser import HTMLParser
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
I18N = PLATFORM / "assets" / "i18n"
RUNTIME = I18N / "site-lang.js"
PAGES = {"landing": "landing.html", "onboarding": "onboarding.html"}
LANGS = ("nl", "de")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ATTRS = {"placeholder", "aria-label", "alt", "title", "content", "data-why"}


# ---------------------------------------------------------------------------------------------------------------- parsing

class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    def elements(self):
        return [k for k in self.kids if isinstance(k, Node)]

    def text(self):
        return "".join(k if isinstance(k, str) else k.text() for k in self.kids)

    def walk(self):
        yield self
        for k in self.elements():
            yield from k.walk()


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("#root", {}, None)
        self.raw = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if self.cur.tag not in ("script", "style"):
            self.cur.kids.append(data)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def plain(n):
    if not n.elements():
        return norm(n.text())
    texts = [k for k in n.kids if isinstance(k, str) and k.strip()]
    return norm(texts[-1]) if texts else ""


def rich(n):
    return norm("".join(k if isinstance(k, str) else "[" + k.text() + "]" for k in n.kids))


def page_html(page):
    return (PLATFORM / PAGES[page]).read_text()


def html_keys(page):
    """key → English, read from the page's markup the way site-lang.js reads it."""
    out = {}
    for n in Tree(page_html(page)).root.walk():
        if "data-i18n" in n.attrs:
            out.setdefault(n.attrs["data-i18n"], plain(n))
        if "data-i18n-rich" in n.attrs:
            out.setdefault(n.attrs["data-i18n-rich"], rich(n))
        for pair in (n.attrs.get("data-i18n-attr") or "").split():
            attr, _, key = pair.partition(":")
            out.setdefault(key, n.attrs.get(attr) or "")
    return out


def scripts(page):
    return "\n".join(m.group(1) for m in re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script>", page_html(page), re.S))


JS_STR = r"'((?:[^'\\]|\\.)*)'"


def unjs(s):
    return re.sub(r"\\(.)", r"\1", s)


def script_keys(page):
    """key → English for every T('k', 'English') / TK('k', 'English') / x.t('k', 'English'); TN('k', n, 'one', 'other')
    adds k.one and k.other."""
    js, out = scripts(page), {}
    for m in re.finditer(r"(?:\bT|\bTK|\.t)\(\s*'([a-z0-9][a-z0-9._-]*)'(?:\s*,\s*" + JS_STR + ")?", js):
        out.setdefault(m.group(1), unjs(m.group(2)) if m.group(2) is not None else None)
    for m in re.finditer(r"(?:\bTN|\.tn)\(\s*'([a-z0-9][a-z0-9._-]*)'\s*,[^,]+,\s*" + JS_STR + r"\s*,\s*" + JS_STR, js):
        out.setdefault(m.group(1) + ".one", unjs(m.group(2)))
        out.setdefault(m.group(1) + ".other", unjs(m.group(3)))
    return out


def used(page):
    keys = dict(script_keys(page))
    for k, v in html_keys(page).items():
        if keys.get(k) is None:
            keys[k] = v
    return keys


def dictionary(name, lang):
    return json.loads((I18N / f"{name}.{lang}.json").read_text())


PLACE = re.compile(r"\{(\w+)\}")
BRACKET = re.compile(r"\[(?:\d+\|)?[^\[\]]*\]")
NON_LATIN = ("HEBREW", "CYRILLIC", "ARABIC", "GREEK", "CJK", "HIRAGANA", "KATAKANA", "HANGUL", "THAI", "DEVANAGARI",
             "ARMENIAN", "GEORGIAN", "SYRIAC", "THAANA", "BENGALI", "TAMIL", "ETHIOPIC")
BANNED = ("autopilot", "auto-pilot", "automatische piloot", "automatischer pilot", "paste your website", "paste your site",
          "plak je website", "plak je site", "website einfügen", "fügen sie ihre website ein", "walk away")


def non_latin(text):
    return sorted({unicodedata.name(c, "?") for c in text if ord(c) > 0x2FF and any(s in unicodedata.name(c, "") for s in NON_LATIN)})


def visible(html):
    """Text and the attributes a visitor meets (no scripts, styles or comments)."""
    t = Tree(html).root
    parts = [t.text()]
    for n in t.walk():
        parts += [v for a, v in n.attrs.items() if a in ATTRS and v]
    return "\n".join(parts)


# ---------------------------------------------------------------------------------------------------------------- tests

class DictionariesTest(unittest.TestCase):
    def test_every_dictionary_is_valid_flat_text(self):
        for name in list(PAGES) + ["common"]:
            for lang in LANGS:
                f = I18N / f"{name}.{lang}.json"
                self.assertTrue(f.is_file(), f"{f.name} missing")
                d = dictionary(name, lang)
                self.assertIsInstance(d, dict, f.name)
                for k, v in d.items():
                    self.assertRegex(k, r"^[a-z0-9][a-z0-9._-]*$", f"{f.name}: odd key {k!r}")
                    self.assertIsInstance(v, str, f"{f.name}: {k} is not a string")
                    self.assertTrue(v.strip(), f"{f.name}: {k} is empty")
                    self.assertNotRegex(v, r"<\s*[A-Za-z/!?]|javascript:|\bon[a-z]+\s*=|&#?\w+;", f"{f.name}: {k} holds markup")
                    self.assertNotRegex(v, r"[\x00-\x1f\x7f]", f"{f.name}: {k} holds a control character")

    def test_languages_have_the_same_keys(self):
        for name in list(PAGES) + ["common"]:
            self.assertEqual(set(dictionary(name, "nl")), set(dictionary(name, "de")), f"{name}: nl and de differ")

    def test_every_key_a_page_uses_is_translated(self):
        for page in PAGES:
            want = set(used(page))
            for lang in LANGS:
                have = set(dictionary(page, lang)) | set(dictionary("common", lang))
                self.assertEqual(sorted(want - have), [], f"{page}.{lang}.json lacks these keys")

    def test_every_translation_is_used(self):
        every = set()
        for page in PAGES:
            keys = set(used(page))
            every |= keys
            for lang in LANGS:
                self.assertEqual(sorted(set(dictionary(page, lang)) - keys), [], f"{page}.{lang}.json: keys the page never uses")
                self.assertEqual(sorted(set(dictionary(page, lang)) & set(dictionary("common", lang))), [],
                                 f"{page}.{lang}.json repeats keys from common.{lang}.json")
        for lang in LANGS:
            self.assertEqual(sorted(set(dictionary("common", lang)) - every), [], f"common.{lang}.json: unused keys")

    def test_placeholders_and_brackets_match_the_english(self):
        for page in PAGES:
            en = used(page)
            for lang in LANGS:
                d = dict(dictionary("common", lang), **dictionary(page, lang))
                for k, e in en.items():
                    if e is None or k not in d:
                        continue
                    want = set(PLACE.findall(e)) - ({"n"} if k.endswith(".one") else set())
                    got = set(PLACE.findall(d[k])) - ({"n"} if k.endswith(".one") else set())
                    self.assertEqual(got, want, f"{page}.{lang}: {k} placeholders")
                    self.assertEqual(len(BRACKET.findall(d[k])), len(BRACKET.findall(e)), f"{page}.{lang}: {k} [parts]")
                    self.assertEqual(d[k].count("{b}"), e.count("{b}"), f"{page}.{lang}: {k} bold marks")

    def test_one_english_per_key(self):
        """A key used in the markup and in a script means the same English in both."""
        for page in PAGES:
            h, s = html_keys(page), script_keys(page)
            for k in set(h) & set(s):
                if s[k] is not None:
                    self.assertEqual(norm(s[k]), h[k], f"{page}: {k} has two Englishes")


class MarkupTest(unittest.TestCase):
    def test_marked_elements_have_the_shape_the_runtime_expects(self):
        for page in PAGES:
            for n in Tree(page_html(page)).root.walk():
                if "data-i18n" in n.attrs:
                    texts = [k for k in n.kids if isinstance(k, str) and k.strip()]
                    self.assertLessEqual(len(texts), 1, f"{page}: data-i18n={n.attrs['data-i18n']} has several text parts (use -rich)")
                    self.assertTrue(plain(n), f"{page}: data-i18n={n.attrs['data-i18n']} has no English")
                if "data-i18n-rich" in n.attrs:
                    for c in n.elements():
                        self.assertEqual(c.elements(), [], f"{page}: data-i18n-rich={n.attrs['data-i18n-rich']}: <{c.tag}> must hold text only")
                    self.assertEqual(len(BRACKET.findall(rich(n))), len(n.elements()), n.attrs["data-i18n-rich"])
                for pair in (n.attrs.get("data-i18n-attr") or "").split():
                    attr, _, key = pair.partition(":")
                    self.assertIn(attr, ATTRS, f"{page}: data-i18n-attr may not set {attr}")
                    self.assertTrue(key and n.attrs.get(attr), f"{page}: {pair} has no English")

    def test_no_words_in_css(self):
        """Text written by CSS (content: "No posts") can't be translated; it comes from an attribute the script fills."""
        for page in PAGES:
            for css in re.findall(r"<style>(.*?)</style>", page_html(page), re.S):
                self.assertNotRegex(css, r"content:\s*[\"'][^\"']*[A-Za-z]{2}", page)

    def test_the_switcher_is_there_and_quiet(self):
        for page in PAGES:
            html = page_html(page)
            self.assertIn('<script src="assets/i18n/site-lang.js?v=', html, page)
            sel = re.search(r"<select data-lang-select[^>]*>(.*?)</select>", html, re.S)
            self.assertTrue(sel, f"{page}: no language control in the nav / bar")
            self.assertEqual(re.findall(r'<option value="(\w+)" lang="\1">([^<]+)</option>', sel.group(1)),
                             [("en", "English"), ("nl", "Nederlands"), ("de", "Deutsch")], page)
            foot = re.search(r"<footer>.*?</footer>", html, re.S).group(0)
            self.assertEqual(re.findall(r'<a href="\?lang=(\w+)" data-lang="\1"[^>]*\blang="\1"[^>]*>([^<]+)</a>', foot),
                             [("en", "English"), ("nl", "Nederlands"), ("de", "Deutsch")], f"{page}: footer switcher")
        # no flags or emoji in the pages; none in the dictionaries either (nor dingbats)
        for f in [PLATFORM / p for p in PAGES.values()]:
            self.assertFalse(re.search("[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF]", f.read_text()), f"{f.name}: flag or emoji")
        for f in sorted(I18N.glob("*.json")):
            self.assertFalse(re.search("[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF☀-➿]", f.read_text()), f"{f.name}: flag or emoji")


class EnglishDefaultTest(unittest.TestCase):
    def test_nothing_picks_a_language_from_the_browser(self):
        """English unless the visitor chose: no navigator.language(s), Accept-Language or locale sniffing anywhere on the
        public pages (Intl formats in the CHOSEN language; resolvedOptions() is only read for the time zone)."""
        files = {"site-lang.js": RUNTIME.read_text(), "consent.js": (PLATFORM / "assets" / "consent.js").read_text()}
        files.update({p: scripts(p) for p in PAGES})
        for name, js in files.items():
            self.assertNotRegex(js, r"navigator\.languages?|\bn\.languages?\b|\bn\.language\b|accept-language|userLanguage|browserLanguage", name)
            self.assertNotRegex(js, r"resolvedOptions\(\)\.locale", name)
        rt = files["site-lang.js"]
        self.assertIn("DEF = 'en'", rt)
        self.assertIn("var lang = asked || stored() || DEF;", rt)
        for p in PAGES.values():
            self.assertRegex((PLATFORM / p).read_text(), r'<html lang="en"', p)

    def test_the_choice_travels_to_sign_in_and_onboarding(self):
        landing, onb = scripts("landing"), scripts("onboarding")
        self.assertIn("next = LG.carry(next)", landing)                      # landing → Google → onboarding
        self.assertIn("nxt = LG.carry(nxt)", onb)                            # onboarding's own sign-in screen
        self.assertIn("comms_lang: siteLang()", onb)                         # step 4 pre-selects the site language
        self.assertIn("if (!S.clangTouched) S.comms_lang = siteLang();", onb)
        self.assertRegex(RUNTIME.read_text(), r"function carry\(path, l\)")

    def test_no_hreflang_alternates(self):
        """The translation is client-side on the same URL: the HTML a crawler gets for ?lang=nl is English, so an hreflang
        pair would point search engines at a 'Dutch' URL that serves English (and the NL/DE text awaits native review)."""
        for p in PAGES.values():
            self.assertNotRegex((PLATFORM / p).read_text(), r'<link[^>]+hreflang', p)


class LanguageContentTest(unittest.TestCase):
    def test_no_non_latin_script_in_what_visitors_see(self):
        pages = ["landing.html", "onboarding.html", "index.html", "billing.html", "admin.html", "approve.html", "ads.html",
                 "analytics.html"] + [f"legal/{f.name}" for f in sorted((PLATFORM / "legal").glob("*.html"))]
        for p in pages:
            f = PLATFORM / p
            if f.is_file():
                self.assertEqual(non_latin(visible(f.read_text())), [], p)
                self.assertEqual(non_latin(f.read_text()), [], f"{p} (scripts included)")
        for f in sorted(I18N.glob("*.json")) + [PLATFORM / "assets" / "consent.js"]:
            self.assertEqual(non_latin(f.read_text()), [], f.name)

    def test_banned_phrases_in_no_language(self):
        texts = {p: visible(page_html(p)) + "\n" + scripts(p) for p in PAGES}
        texts.update({f.name: f.read_text() for f in sorted(I18N.glob("*.json"))})
        for name, t in texts.items():
            low = t.lower()
            for b in BANNED:
                self.assertNotIn(b, low, f"{name}: {b!r}")

    def test_registers_match_the_emails(self):
        """German as otto_i18n's default B2B register (Sie); Dutch informal (je), as the e-mails write."""
        for name in list(PAGES) + ["common"]:
            for k, v in dictionary(name, "de").items():
                self.assertNotRegex(v, r"\b(du|dich|dir|dein|deine|deinen|deinem|deiner|deines)\b", f"de {name}: {k} says du")
            for k, v in dictionary(name, "nl").items():
                self.assertNotRegex(v, r"\b(u|uw|Uw)\b", f"nl {name}: {k} says u")


if __name__ == "__main__":
    unittest.main()
