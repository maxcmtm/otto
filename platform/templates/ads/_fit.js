/* Shrink-to-fit for ad copy, run after webfonts load.
   1. [data-fitw] (single-line figures such as a big number or a price) shrink in 4px steps down to data-min until
      they fit their own width.
   2. [data-fit="<priority>"] shrink (priority 1 first) in 2px steps down to data-min while any [data-box]
      overflows or the element wraps past data-lines.
   Adds html.fitted when done, and html.overflow if the copy still does not fit at the minimum sizes. */
(function () {
  // overflow = a child's layout box past the box's content edge, or horizontal scroll. Glyph ink that pokes out of
  // a line box (descenders, big serif quotes) is not overflow, so scrollHeight alone is not used.
  function over(el) {
    if (el.scrollWidth > el.clientWidth + 1) return true;
    var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    var bottom = r.top + el.clientTop + el.clientHeight - parseFloat(cs.paddingBottom || 0);
    for (var i = 0; i < el.children.length; i++) {
      var c = el.children[i], cr = c.getBoundingClientRect();
      if (!cr.height && !cr.width) continue;
      if (cr.bottom + parseFloat(getComputedStyle(c).marginBottom || 0) > bottom + 1) return true;
    }
    return false;
  }
  function lines(el) {
    var cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight);
    if (!lh) lh = parseFloat(cs.fontSize) * 1.1;
    return Math.round(el.getBoundingClientRect().height / lh);
  }
  function fs(el) { return parseFloat(getComputedStyle(el).fontSize); }
  function run() {
    var wides = Array.prototype.slice.call(document.querySelectorAll('[data-fitw]'));
    wides.forEach(function (el) {
      var min = +el.dataset.min || 60, g = 0, p = el.parentElement;
      el.style.flex = 'none';
      while (p.scrollWidth > p.clientWidth + 1 && fs(el) > min && g++ < 200)
        el.style.fontSize = (fs(el) - 4) + 'px';
    });
    var boxes = Array.prototype.slice.call(document.querySelectorAll('[data-box]'));
    var fits = Array.prototype.slice.call(document.querySelectorAll('[data-fit]'));
    fits.sort(function (a, b) { return (+a.dataset.fit || 9) - (+b.dataset.fit || 9); });
    var guard = 0, done = false;
    while (!done && guard++ < 500) {
      done = true;
      for (var i = 0; i < fits.length; i++) {
        var el = fits[i], f = fs(el), min = +el.dataset.min || 22, maxl = +el.dataset.lines || 0;
        if (maxl && lines(el) > maxl && f > min) { el.style.fontSize = (f - 2) + 'px'; done = false; }
      }
      if (!done) continue;
      if (boxes.some(over)) {
        for (var j = 0; j < fits.length; j++) {
          var e2 = fits[j], f2 = fs(e2);
          if (f2 > (+e2.dataset.min || 22)) { e2.style.fontSize = (f2 - 2) + 'px'; done = false; break; }
        }
      }
    }
    if (boxes.some(over)) document.documentElement.classList.add('overflow');
    document.documentElement.classList.add('fitted');
  }
  // No requestAnimationFrame: headless Chrome under a virtual-time budget does not reliably produce frames.
  // Reading layout starts the webfont loads; fonts.ready then waits for them; geometry reads force layout.
  var started = false;
  function start() {
    if (started) return;
    started = true;
    void document.body.offsetHeight;
    var ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
    ready.then(function () { try { run(); } catch (e) { document.documentElement.classList.add('fitted', 'fit-error'); } });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
