/* Otto privacy choices (landing page). One optional purpose: measuring Otto's own ads with Meta, done by our server
   (otto_track.py → Meta Conversions API), never by a Meta script in the browser. Rules this file keeps:
   - Nothing optional happens before a choice. "Reject" and "Accept" are the same size, the same style and side by side;
     there is no pre-ticked box, no "reject" hidden behind a second layer, and no cookie wall (the page stays usable).
   - The choice is remembered in one first-party cookie, otto_consent = "v1.granted" | "v1.denied" (180 days), which is
     strictly necessary for remembering it. The server forwards an event to Meta only when that cookie says "v1.granted".
   - With consent, and only when the visitor arrived from a Meta ad link (?fbclid=…), a second first-party cookie
     otto_fbc = "fb.1.<ms>.<fbclid>" (90 days) lets the server attribute the visit to that ad. It is deleted on "Reject".
   - Do Not Track / Global Privacy Control with no stored choice: treated as "Reject"; no banner is shown.
   - "Privacy choices" in the footer ([data-privacy-choices]) reopens the panel at any time; changing the answer applies at once.
   - In the page's language: English, unless the visitor chose Nederlands or Deutsch on the site (assets/i18n/site-lang.js
     sets <html lang> and fires "ottolang" on a switch, which relabels the banner). Never from the browser's language list.
   - It never covers the landing's sticky CTA dock: while it is open, the dock sits above it (--oc-h, consent.css).
   No network requests, no third-party code, no inline styles (consent.css), so the landing's CSP stays as it is. */
(function (W, d) {
  'use strict';
  var n = navigator;
  var KEY = 'otto_consent', FBC = 'otto_fbc', VERSION = 'v1';
  var KEEP = 180 * 24 * 3600, FBC_KEEP = 90 * 24 * 3600;
  var T = {
    en: {
      title: 'Can Otto measure its ads?',
      body: 'If you allow it, our server tells Meta when you scan a website or start signing up, so we can see which of our ads work. Nothing goes to Meta if you say no, and the page works the same either way.',
      more: 'How it works', reject: 'Reject', accept: 'Accept', close: 'Close',
      now_granted: 'Your current choice: ad measurement allowed.', now_denied: 'Your current choice: ad measurement not allowed.',
      gpc: 'Your browser sends a Do Not Track or Global Privacy Control signal, so Otto sends nothing to Meta whatever you choose here.',
      saved_granted: 'Saved: ad measurement allowed.', saved_denied: 'Saved: ad measurement not allowed.',
      footer: 'Privacy choices', label: 'Privacy choices'
    },
    nl: {
      title: 'Mag Otto zijn advertenties meten?',
      body: 'Als je dat goedvindt, laat onze server Meta weten wanneer je een website scant of je begint aan te melden. Zo zien we welke van onze advertenties werken. Zeg je nee, dan gaat er niets naar Meta. De pagina werkt in beide gevallen hetzelfde.',
      more: 'Hoe het werkt', reject: 'Weigeren', accept: 'Accepteren', close: 'Sluiten',
      now_granted: 'Je huidige keuze: meten toegestaan.', now_denied: 'Je huidige keuze: meten niet toegestaan.',
      gpc: 'Je browser stuurt een Do Not Track- of Global Privacy Control-signaal. Otto stuurt daarom niets naar Meta, wat je hier ook kiest.',
      saved_granted: 'Opgeslagen: meten toegestaan.', saved_denied: 'Opgeslagen: meten niet toegestaan.',
      footer: 'Privacykeuzes', label: 'Privacykeuzes'
    },
    de: {
      title: 'Darf Otto seine Anzeigen messen?',
      body: 'Wenn Sie zustimmen, teilt unser Server Meta mit, wann Sie eine Website scannen oder mit der Anmeldung beginnen. So sehen wir, welche unserer Anzeigen funktionieren. Sagen Sie Nein, geht nichts an Meta, und die Seite funktioniert genauso.',
      more: 'So funktioniert es', reject: 'Ablehnen', accept: 'Akzeptieren', close: 'Schließen',
      now_granted: 'Ihre aktuelle Wahl: Anzeigenmessung erlaubt.', now_denied: 'Ihre aktuelle Wahl: Anzeigenmessung nicht erlaubt.',
      gpc: 'Ihr Browser sendet ein Do-Not-Track- oder Global-Privacy-Control-Signal. Otto sendet deshalb nichts an Meta, egal was Sie hier wählen.',
      saved_granted: 'Gespeichert: Anzeigenmessung erlaubt.', saved_denied: 'Gespeichert: Anzeigenmessung nicht erlaubt.',
      footer: 'Datenschutzeinstellungen', label: 'Datenschutzeinstellungen'
    }
  };

  function pickLang() {                     // the page's language, which the visitor chose (English by default)
    var own = String(d.documentElement.getAttribute('lang') || '').toLowerCase().slice(0, 2);
    return T[own] ? own : 'en';
  }
  var L = T[pickLang()];
  var signal = n.globalPrivacyControl === true || n.doNotTrack === '1' || W.doNotTrack === '1';

  function readCookie(name) {
    var parts = String(d.cookie || '').split(/;\s*/);
    for (var i = 0; i < parts.length; i++) {
      var eq = parts[i].indexOf('=');
      if (eq > 0 && parts[i].slice(0, eq) === name) {
        try { return decodeURIComponent(parts[i].slice(eq + 1)); } catch (e) { return null; }
      }
    }
    return null;
  }
  function writeCookie(name, value, maxAge) {
    var secure = W.location.protocol === 'https:' ? '; Secure' : '';
    try { d.cookie = name + '=' + encodeURIComponent(value) + '; Max-Age=' + maxAge + '; Path=/; SameSite=Lax' + secure; } catch (e) {}
  }
  function stored() {
    var v = readCookie(KEY);
    return v === VERSION + '.granted' ? 'granted' : v === VERSION + '.denied' ? 'denied' : null;
  }
  function fbclid() {
    var m = /[?&]fbclid=([A-Za-z0-9_-]{10,500})(?:&|#|$)/.exec(W.location.search || '');
    return m ? m[1] : null;
  }
  function applyChoice(state) {
    if (state === 'granted') {
      var id = fbclid();
      if (id) writeCookie(FBC, 'fb.1.' + Date.now() + '.' + id, FBC_KEEP);
    } else {
      writeCookie(FBC, '', 0);                  // withdrawn or refused: the click id goes too
    }
  }

  var root = null, ui = {}, opener = null, current = stored();

  function el(tag, cls, text) {
    var e = d.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function build() {
    if (root) return root;
    root = el('section', 'oc');
    root.id = 'otto-consent';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'false');
    root.setAttribute('aria-labelledby', 'oc-title');
    root.setAttribute('aria-describedby', 'oc-body');
    root.hidden = true;
    var card = el('div', 'oc-card');
    var h = el('h2', 'oc-title', L.title); h.id = 'oc-title'; h.tabIndex = -1; ui.title = h;
    var p = el('p', 'oc-body', L.body); p.id = 'oc-body';
    var more = el('a', 'oc-more', L.more); more.href = 'legal/cookies.html#ad-measurement-with-meta-only-with-your-consent';
    p.appendChild(d.createTextNode(' ')); p.appendChild(more);
    ui.state = el('p', 'oc-state'); ui.state.setAttribute('aria-live', 'polite');
    ui.gpc = el('p', 'oc-note', L.gpc); ui.gpc.hidden = !signal;
    var row = el('div', 'oc-actions');
    ui.reject = el('button', 'oc-btn', L.reject); ui.reject.type = 'button'; ui.reject.setAttribute('data-choice', 'denied');
    ui.accept = el('button', 'oc-btn', L.accept); ui.accept.type = 'button'; ui.accept.setAttribute('data-choice', 'granted');
    row.appendChild(ui.reject); row.appendChild(ui.accept);
    ui.close = el('button', 'oc-close', L.close); ui.close.type = 'button'; ui.close.hidden = true;
    ui.close.setAttribute('aria-label', L.close);
    card.appendChild(ui.close); card.appendChild(h); card.appendChild(p); card.appendChild(ui.gpc); card.appendChild(ui.state); card.appendChild(row);
    root.appendChild(card);
    root.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-choice]');
      if (b) { choose(b.getAttribute('data-choice')); return; }
      if (e.target.closest && e.target.closest('.oc-close')) hide();
    });
    root.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && current) { e.preventDefault(); hide(); }    // the first question is only closed by answering it
    });
    d.body.appendChild(root);
    return root;
  }
  function relabel() {                       // the visitor switched the site's language: the banner and the footer link follow
    L = T[pickLang()];
    var links = d.querySelectorAll('[data-privacy-choices]');
    for (var i = 0; i < links.length; i++) if (!links[i].getAttribute('data-keep-label')) links[i].textContent = L.footer;
    if (!root) return;
    ui.title.textContent = L.title;
    var p = d.getElementById('oc-body'); p.firstChild.nodeValue = L.body; p.querySelector('.oc-more').textContent = L.more;
    ui.gpc.textContent = L.gpc; ui.reject.textContent = L.reject; ui.accept.textContent = L.accept;
    ui.close.textContent = L.close; ui.close.setAttribute('aria-label', L.close);
    if (!ui.state.hidden) refresh(false);
    measure();
  }
  d.addEventListener('ottolang', relabel);
  function refresh(saved) {
    ui.state.textContent = saved ? (current === 'granted' ? L.saved_granted : L.saved_denied)
      : current === 'granted' ? L.now_granted : current === 'denied' ? L.now_denied : '';
    ui.state.hidden = !ui.state.textContent;
    ui.accept.setAttribute('aria-pressed', current === 'granted' ? 'true' : 'false');
    ui.reject.setAttribute('aria-pressed', current === 'denied' ? 'true' : 'false');
    ui.close.hidden = !current;
    root.classList.toggle('is-panel', !!current);
  }
  function measure() {                       // the landing's sticky dock sits above the open banner (consent.css)
    if (!root || root.hidden) return;
    try { d.documentElement.style.setProperty('--oc-h', Math.ceil(root.firstChild.getBoundingClientRect().height) + 'px'); } catch (e) {}
  }
  function show(from) {
    build();
    opener = from || null;
    refresh(false);
    root.hidden = false;
    d.documentElement.classList.add('oc-open');
    measure();
    if (from) { try { ui.title.focus({ preventScroll: true }); } catch (e) { ui.title.focus(); } }   // neutral: neither answer pre-focused
  }
  function hide() {
    if (!root) return;
    root.hidden = true;
    d.documentElement.classList.remove('oc-open');
    try { d.documentElement.style.removeProperty('--oc-h'); } catch (e) {}
    if (opener && opener.focus) { try { opener.focus({ preventScroll: true }); } catch (e) {} }
    opener = null;
  }
  function choose(state) {
    if (state !== 'granted' && state !== 'denied') return;
    var first = !current;
    current = state;
    writeCookie(KEY, VERSION + '.' + state, KEEP);
    applyChoice(state);
    if (W.ottoTrack) { try { W.ottoTrack('cta', { id: 'consent:' + state + '@' + (first ? 'banner' : 'choices') }); } catch (e) {} }
    if (first) { hide(); return; }
    refresh(true);                               // reopened from the footer: say it was saved, keep the panel for a moment
    measure();
    setTimeout(hide, 1200);
  }

  W.ottoConsent = {
    state: function () { return current; },      // 'granted' | 'denied' | null (no choice yet)
    open: function () { show(d.activeElement); }
  };

  function start() {
    var links = d.querySelectorAll('[data-privacy-choices]');
    for (var i = 0; i < links.length; i++) {
      if (!links[i].getAttribute('data-keep-label')) links[i].textContent = L.footer;
      links[i].setAttribute('aria-haspopup', 'dialog');
      links[i].addEventListener('click', function (e) { e.preventDefault(); show(e.currentTarget); });
    }
    W.addEventListener('resize', measure, { passive: true });
    if (current) applyChoice(current);           // a returning visitor who allowed it: refresh the click id from this link
    else if (!signal) show(null);
  }
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', start);
  else start();
})(window, document);
