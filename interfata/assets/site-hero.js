/* site-hero.js — piesa „bon / extras” din hero, construită din datele demonstrative (nu din imagine).
 * Primește: window.EMAG_DEMO_DATA (paid.funnel = lanțul în bani plătiți, orders, meta) și piesa #ticket din index.html.
 * Dă înapoi: nimic; completează rândurile, bara proporțională și numărătoarea la intrare în ecran
 * (oprită la prefers-reduced-motion). Valorile finale sunt și în text pentru cititoarele de ecran.
 * Nu calculează nimic: arată exact ce a calculat programul în datele demo.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var COUNT_DURATION_MS = 1100; // cât durează numărarea (toate rândurile deodată)
  var VISIBLE_RATIO = 0.35; // cât din piesă trebuie să se vadă ca să pornească numărătoarea
  // Segmentele barei, în ordine: starea (pentru culoare) și cheia ei din paid.funnel (păstrat = plătit efectiv).
  var BAR_PARTS = [['kept', 'spent_bani'], ['returned', 'returned_bani'], ['cancelled', 'cancelled_bani'], ['pending', 'pending_bani'], ['unknown', 'unknown_bani']];
  var ORDERED_KEY = 'ordered_bani'; // rândul din care se scad celelalte
  var ADDED_KEYS = ['fees_bani']; // rândurile care se adună (transportul și taxele comenzilor livrate)
  var TOTAL_KEY = 'spent_bani'; // rândul care se deduce din celelalte în timpul numărării

  /** Pune în fiecare cifră două noduri: unul animat (ascuns de cititoare) și unul cu valoarea finală (doar pentru ele). */
  function prepareValue(el, text) {
    var h = Site.dom.h;
    Site.dom.clear(el);
    var visible = h('span', { 'aria-hidden': 'true' }, text);
    el.appendChild(visible);
    el.appendChild(h('span', { class: 'sr-only' }, text));
    return visible;
  }

  /**
   * Numără toate rândurile cu ACELAȘI progres, iar „plătit efectiv” se deduce din celelalte la fiecare cadru: bonul se leagă
   * în orice clipă (comandat − anulat − returnat − în curs + transport și taxe = plătit efectiv), nu doar la final.
   * La final scrie valorile exacte.
   */
  function countUp(animated) {
    var byKey = {};
    animated.forEach(function (item) { byKey[item.key] = item; });
    var start = null;
    function frame(now) {
      if (start === null) start = now;
      var t = Math.min(1, (now - start) / COUNT_DURATION_MS);
      var progress = 1 - Math.pow(1 - t, 3);
      var shown = {};
      var balance = 0; // ce se scade (−) și ce se adaugă (+) la comandat, la progresul acestui cadru
      animated.forEach(function (item) {
        if (item.key === ORDERED_KEY || item.key === TOTAL_KEY) return;
        shown[item.key] = Math.round(item.value * progress);
        balance += ADDED_KEYS.indexOf(item.key) >= 0 ? shown[item.key] : -shown[item.key];
      });
      if (byKey[ORDERED_KEY]) shown[ORDERED_KEY] = Math.round(byKey[ORDERED_KEY].value * progress);
      if (byKey[TOTAL_KEY]) shown[TOTAL_KEY] = Math.max(0, (shown[ORDERED_KEY] || 0) + balance);
      animated.forEach(function (item) {
        var value = t < 1 ? shown[item.key] : item.value;
        item.visible.textContent = Site.fmt.lei(value);
      });
      if (t < 1) root.requestAnimationFrame(frame);
    }
    animated.forEach(function (item) { item.visible.textContent = Site.fmt.lei(0); });
    root.requestAnimationFrame(frame);
  }

  /** Desenează bara proporțională (un segment per stare, lățimea după valoare). */
  function buildBar(bar, funnel) {
    var h = Site.dom.h;
    Site.dom.clear(bar);
    BAR_PARTS.forEach(function (part) {
      var bani = funnel[part[1]] || 0;
      if (bani > 0) bar.appendChild(h('i', { class: 'ticket__seg ticket__seg--' + part[0], style: 'flex-grow:' + bani }));
    });
  }

  /** Completează piesa din datele demo; întoarce lista (element vizibil, valoare) pentru numărătoare. */
  function fill(ticket, data) {
    var funnel = data.paid.funnel;
    var meta = data.meta || {};
    var animated = [];
    ticket.querySelectorAll('[data-key]').forEach(function (el) {
      var bani = funnel[el.getAttribute('data-key')];
      if (typeof bani !== 'number') return;
      var row = el.closest('[data-state]');
      if (row && row.hasAttribute('hidden') && bani > 0) row.removeAttribute('hidden');
      animated.push({ key: el.getAttribute('data-key'), visible: prepareValue(el, Site.fmt.lei(bani)), value: bani });
    });
    var orders = data.orders && typeof data.orders.total === 'number' ? data.orders.total : null;
    doc.getElementById('ticket-units').textContent = Site.fmt.units(funnel.spent_units) + ' păstrate' + (orders === null ? '' : ' din ' + Site.fmt.int(orders) + ' comenzi');
    if (meta.first_order && meta.last_order) {
      doc.getElementById('ticket-meta').textContent = 'extras de calcul · ' + Site.fmt.dateShort(meta.first_order) + ' – ' + Site.fmt.dateShort(meta.last_order);
    }
    buildBar(doc.getElementById('ticket-bar'), funnel);
    return animated;
  }

  /** Pornește numărătoarea când piesa intră în ecran (sau imediat, dacă se vede deja); o singură dată. */
  function whenVisible(ticket, run) {
    if (!('IntersectionObserver' in root)) { run(); return; }
    var observer = new IntersectionObserver(function (entries) {
      if (entries.some(function (e) { return e.isIntersecting; })) { observer.disconnect(); run(); }
    }, { threshold: VISIBLE_RATIO });
    observer.observe(ticket);
  }

  /** Construiește piesa din hero. Dacă datele demo lipsesc, lasă un mesaj clar în loc de cifre goale. */
  function init() {
    var ticket = doc.getElementById('ticket');
    if (!ticket) return;
    var data = root.EMAG_DEMO_DATA;
    if (!data || !data.paid || !data.paid.funnel) {
      doc.getElementById('ticket-foot').textContent = 'Datele demonstrative nu s-au încărcat (assets/demo-data.js lipsește sau e dintr-o versiune veche).';
      return;
    }
    var animated = fill(ticket, data);
    if (Site.dom.prefersReducedMotion()) return; // cifrele finale sunt deja scrise
    ticket.setAttribute('data-count', 'ready');
    whenVisible(ticket, function () {
      ticket.setAttribute('data-count', 'running');
      countUp(animated);
    });
  }

  Site.hero = { init: init };
})(window);
