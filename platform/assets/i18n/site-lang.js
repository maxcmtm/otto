/* Otto site language (landing + onboarding). English is the page: the HTML is the English source that crawlers, visitors
   without JavaScript and every first visit read. Nederlands and Deutsch are an option the VISITOR picks (footer, nav, menu)
   or a link carries (?lang=nl / ?lang=de); it is never decided by the browser's language, the IP or the country.
   The choice is remembered on this site (localStorage "otto.lang"), and the trial links carry it to sign-in and onboarding.

   Markup (the English stays in the HTML):
     data-i18n="key"           the element's text (with element children, only its one direct text node: icons stay)
     data-i18n-rich="key"      text whose [bracketed] parts fill the element's child elements in order (<b>, <a>, <span>…),
                               which keep their attributes; the dictionary never holds markup
     data-i18n-attr="attr:key attr:key"   placeholder, aria-label, alt, title, content (meta), data-why
   Script strings: OttoLang.t(key, english, vars) / tn(key, n, one, other, vars); numbers and dates through Intl in the
   chosen locale. Dictionaries: assets/i18n/<page>.<lang>.json + common.<lang>.json (same origin; CSP connect-src 'self').
   After a switch (and after the first load in nl/de) the document gets an "ottolang" event: page scripts re-render what
   they wrote themselves.
   Caching: /assets is cached for a day (infra/Caddyfile), so after changing a dictionary or this file bump the ?v= on the
   <script src="assets/i18n/site-lang.js?v=…"> tag in landing.html and onboarding.html (the dictionaries are fetched with
   the same v). */
(function (W, d) {
  'use strict';
  var LANGS = ['en', 'nl', 'de'], DEF = 'en', KEY = 'otto.lang';
  var LOCALE = { en: 'en-GB', nl: 'nl-NL', de: 'de-DE' };
  var ATTRS = { placeholder: 1, 'aria-label': 1, alt: 1, title: 1, content: 1, 'data-why': 1 };
  var h = d.documentElement, me = d.currentScript;
  var page = (me && me.getAttribute('data-page')) || 'landing';
  var src = (me && me.src) || '';
  var dir = src ? src.replace(/[?#].*$/, '').replace(/[^\/]*$/, '') : 'assets/i18n/';
  var ver = (/[?&]v=([\w.-]+)/.exec(src) || [])[1] || '';
  var own = function (o, k) { return o != null && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined; };
  var valid = function (l) { l = String(l || '').toLowerCase(); return LANGS.indexOf(l) > -1 ? l : null; };
  function stored() { try { return valid(W.localStorage.getItem(KEY)); } catch (e) { return null; } }
  function remember(l) { try { if (l === DEF) W.localStorage.removeItem(KEY); else W.localStorage.setItem(KEY, l); } catch (e) {} }
  function fromUrl() { var m = /[?&]lang=([A-Za-z]{2})(?:[&#]|$)/.exec(W.location.search || ''); return m ? valid(m[1]) : null; }

  var asked = fromUrl();
  var lang = asked || stored() || DEF;          // English unless this visitor chose otherwise
  if (asked) remember(asked);
  var DICT = {}, EN = null, cur = null, loading = {};

  /* nl / de on arrival: the page's head script already holds the first paint (html.lang-wait, at most 1.2 s) so it doesn't
     flash English; the same here for a page without that script */
  if (lang !== DEF) {
    h.setAttribute('lang', lang);
    h.classList.add('lang-wait');
    var st = d.createElement('style');
    st.textContent = 'html.lang-wait body{opacity:0}';
    d.head.appendChild(st);
    setTimeout(function () { h.classList.remove('lang-wait'); }, 1200);
  }

  function fetchJSON(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; });
  }
  function load(l) {
    if (l === DEF) return Promise.resolve({});
    if (DICT[l]) return Promise.resolve(DICT[l]);
    if (loading[l]) return loading[l];
    var q = ver ? '?v=' + encodeURIComponent(ver) : '';
    loading[l] = Promise.all([fetchJSON(dir + 'common.' + l + '.json' + q), fetchJSON(dir + page + '.' + l + '.json' + q)]).then(function (r) {
      var out = {}, k;
      for (k in r[0]) if (own(r[0], k) != null) out[k] = r[0][k];
      for (k in r[1]) if (own(r[1], k) != null) out[k] = r[1][k];
      delete loading[l];
      if (Object.keys(out).length) DICT[l] = out;        // an empty answer is not cached: the next switch asks again
      return out;
    });
    return loading[l];
  }
  if (lang !== DEF) load(lang);                   // start the request now, while the page parses

  /* ---------- strings ---------- */
  function fill(s, v) {
    s = String(s == null ? '' : s);
    if (!v) return s;
    return s.replace(/\{(\w+)\}/g, function (m, k) { var x = own(v, k); return x == null ? m : String(x); }).replace(/ {2,}/g, ' ').trim();
  }
  function t(key, en, v) {
    var dict = lang === DEF ? null : DICT[lang], s = dict ? own(dict, key) : undefined;
    return fill(typeof s === 'string' && s ? s : en, v);
  }
  function plural(n) { try { return new Intl.PluralRules(LOCALE[lang]).select(n) === 'one' ? 'one' : 'other'; } catch (e) { return n === 1 ? 'one' : 'other'; } }
  function num(n, o) { try { return new Intl.NumberFormat(LOCALE[lang], o).format(n); } catch (e) { return String(n); } }
  function tn(key, n, one, other, v) {
    var c = plural(n), vv = { n: num(n) }, k;
    if (v) for (k in v) vv[k] = v[k];
    return t(key + '.' + c, c === 'one' ? one : other, vv);
  }
  function money(n, cur, dec) {
    dec = dec == null ? (Math.round(n) === n ? 0 : 2) : dec;
    try { return new Intl.NumberFormat(LOCALE[lang], { style: 'currency', currency: cur || 'EUR', minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n); }
    catch (e) { return '€' + n; }
  }
  function date(x, o) { try { return new Intl.DateTimeFormat(LOCALE[lang], o).format(x); } catch (e) { return x.toDateString(); } }
  function list(a) { try { return new Intl.ListFormat(LOCALE[lang], { type: 'conjunction' }).format(a); } catch (e) { return a.join(lang === 'nl' ? ' en ' : lang === 'de' ? ' und ' : ' and '); } }
  function lname(code, fallback) {
    try { var s = new Intl.DisplayNames([LOCALE[lang]], { type: 'language' }).of(code); if (s && s !== code) return s.charAt(0).toUpperCase() + s.slice(1); } catch (e) {}
    return fallback || String(code || '').toUpperCase();
  }
  /* a same-origin path that keeps the visitor's language: /onboarding.html?site=x → /onboarding.html?site=x&lang=nl */
  function carry(path, l) {
    l = l || lang;
    var hash = '', i = path.indexOf('#');
    if (i > -1) { hash = path.slice(i); path = path.slice(0, i); }
    path = path.replace(/([?&])lang=[^&]*(&|$)/, function (m, a, b) { return b ? a : ''; }).replace(/[?&]$/, '');
    if (l !== DEF) path += (path.indexOf('?') > -1 ? '&' : '?') + 'lang=' + l;
    return path + hash;
  }

  /* ---------- the document ---------- */
  function each(root, sel, fn) {
    if (root.nodeType === 1 && root.matches(sel)) fn(root);
    Array.prototype.forEach.call(root.querySelectorAll(sel), fn);
  }
  function textNode(el) {
    var n = null;
    Array.prototype.forEach.call(el.childNodes, function (c) { if (c.nodeType === 3 && /\S/.test(c.nodeValue)) n = c; });
    return n;
  }
  function plain(el) {
    if (!el.firstElementChild) return el.textContent.replace(/\s+/g, ' ').trim();
    var n = textNode(el); return n ? n.nodeValue.replace(/\s+/g, ' ').trim() : '';
  }
  function rich(el) {
    var s = '';
    Array.prototype.forEach.call(el.childNodes, function (c) {
      if (c.nodeType === 3) s += c.nodeValue; else if (c.nodeType === 1) s += '[' + c.textContent + ']';
    });
    return s.replace(/\s+/g, ' ').trim();
  }
  function pairs(el) {
    return String(el.getAttribute('data-i18n-attr') || '').split(/\s+/).filter(Boolean).map(function (p) {
      var i = p.indexOf(':'); return [p.slice(0, i), p.slice(i + 1)];
    }).filter(function (p) { return own(ATTRS, p[0]) && p[1]; });
  }
  /* the English, read once from the HTML before anything is translated */
  function collect() {
    if (EN) return;
    EN = {};
    each(d, '[data-i18n]', function (el) { var k = el.getAttribute('data-i18n'); if (!own(EN, k)) EN[k] = plain(el); });
    each(d, '[data-i18n-rich]', function (el) { var k = el.getAttribute('data-i18n-rich'); if (!own(EN, k)) EN[k] = rich(el); });
    each(d, '[data-i18n-attr]', function (el) { pairs(el).forEach(function (p) { if (!own(EN, p[1])) EN[p[1]] = el.getAttribute(p[0]) || ''; }); });
  }
  function val(k) {
    var dict = lang === DEF ? null : DICT[lang], s = dict ? own(dict, k) : undefined;
    return typeof s === 'string' && s ? s : own(EN, k);
  }
  function setText(el, s) {
    if (!el.firstElementChild) { if (el.textContent !== s) el.textContent = s; return; }
    var n = textNode(el);
    if (!n) { el.appendChild(d.createTextNode(s)); return; }
    var m = /^(\s*)[\s\S]*?(\s*)$/.exec(n.nodeValue);
    n.nodeValue = m[1] + s + m[2];
  }
  function setRich(el, s) {
    var tpl = Array.prototype.slice.call(el.children), seq = 0, frag = d.createDocumentFragment(), re = /\[(?:(\d+)\|)?([^\[\]]*)\]/g, m, at = 0;
    while ((m = re.exec(s))) {
      if (m.index > at) frag.appendChild(d.createTextNode(s.slice(at, m.index)));
      var i = m[1] != null ? +m[1] : seq++, base = tpl[i];
      if (base) { var c = base.cloneNode(false); c.textContent = m[2]; frag.appendChild(c); } else frag.appendChild(d.createTextNode(m[2]));
      at = re.lastIndex;
    }
    if (at < s.length) frag.appendChild(d.createTextNode(s.slice(at)));
    el.textContent = '';
    el.appendChild(frag);
  }
  function apply(root) {
    collect();
    root = root || d;
    each(root, '[data-i18n]', function (el) { var s = val(el.getAttribute('data-i18n')); if (s != null) setText(el, s); });
    each(root, '[data-i18n-rich]', function (el) { var s = val(el.getAttribute('data-i18n-rich')); if (s != null && s !== rich(el)) setRich(el, s); });
    each(root, '[data-i18n-attr]', function (el) { pairs(el).forEach(function (p) { var s = val(p[1]); if (s != null) el.setAttribute(p[0], s); }); });
  }
  function source(el) {
    collect();
    var k = el && el.getAttribute && el.getAttribute('data-i18n');
    return k && own(EN, k) != null ? EN[k] : (el ? el.textContent : '');
  }

  /* ---------- the switcher: [data-lang] links (footer, menu) and select[data-lang-select] (nav, setup bar) ---------- */
  function hrefFor(l) {
    var p = new URLSearchParams(W.location.search);
    if (l === DEF) p.delete('lang'); else p.set('lang', l);
    var q = p.toString();
    return W.location.pathname + (q ? '?' + q : '') + W.location.hash;
  }
  function paint() {
    each(d, 'a[data-lang]', function (a) {
      var l = a.getAttribute('data-lang');
      a.href = hrefFor(l);
      if (l === lang) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });
    each(d, 'select[data-lang-select]', function (s) {
      if (s.value !== lang) s.value = lang;
      var cur = s.parentNode && s.parentNode.querySelector('[data-lang-current]'), o = s.options[s.selectedIndex];
      if (cur && o) cur.textContent = o.textContent;            // the visible label: the language's own name
    });
  }
  function wire() {
    d.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[data-lang]');
      if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button > 0) return;
      e.preventDefault();
      set(a.getAttribute('data-lang'), a.getAttribute('data-lang-from') || 'footer');
    });
    d.addEventListener('change', function (e) {
      var s = e.target;
      if (s && s.matches && s.matches('select[data-lang-select]')) set(s.value, s.getAttribute('data-lang-from') || 'nav');
    });
  }
  function show(l) {
    lang = l;
    h.setAttribute('lang', l);
    apply(d);
    paint();
    h.classList.remove('lang-wait');
    var ev; try { ev = new CustomEvent('ottolang', { detail: { lang: l } }); } catch (e) { ev = d.createEvent('CustomEvent'); ev.initCustomEvent('ottolang', false, false, { lang: l }); }
    d.dispatchEvent(ev);
  }
  function set(l, from) {
    l = valid(l) || DEF;
    if (W.ottoTrack && from) { try { W.ottoTrack('cta', { id: ('lang:' + l + '@' + from).slice(0, 48) }); } catch (e) {} }
    var done = function () { remember(l); try { W.history.replaceState(W.history.state, '', hrefFor(l)); } catch (e) {} };
    if (l === lang && cur === l) { done(); paint(); return Promise.resolve(l); }
    return load(l).then(function (dict) {
      if (l !== DEF && !Object.keys(dict).length) { paint(); return lang; }   // couldn't load it: stay as we are
      done(); collect(); show(l); cur = l;
      return l;
    });
  }

  var readyResolve, ready = new Promise(function (r) { readyResolve = r; });
  function start() {
    collect();
    wire();
    paint();
    if (lang === DEF) { cur = DEF; readyResolve(DEF); return; }
    load(lang).then(function (dict) {
      var l = Object.keys(dict).length ? lang : DEF;     // the dictionary didn't arrive (offline, blocked): English, honestly labelled
      show(l); cur = l; readyResolve(l);
    });
  }
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', start); else start();

  W.OttoLang = {
    get lang() { return lang; },
    get locale() { return LOCALE[lang]; },
    langs: LANGS.slice(),
    t: t, tn: tn, num: num, money: money, date: date, list: list, lname: lname, carry: carry,
    apply: apply, source: source, set: set, ready: ready,
    on: function (fn) { d.addEventListener('ottolang', function (e) { fn(e.detail && e.detail.lang); }); }
  };
})(window, document);
