/* site.js — pornește site-ul: leagă datele din raport de text, apelează fiecare modul, în ordine, și așază pagina la #hash.
 * Primește: modulele window.Site.* (încărcate înaintea lui) și window.EMAG_DEMO_DATA / EmagDashboard.
 * Dă înapoi: nimic. Completează locurile marcate data-bind (prag, limită de mărime, categorii evidențiate) și versiunea
 * din subsol, ca nicio cifră care se poate schimba să nu fie scrisă de mână în text.
 * Un modul care pică sau lipsește nu oprește celelalte: eroarea merge în consolă, pagina rămâne citibilă.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  /** „A”, „A și B”, „A, B și C”. */
  function joinNames(names) {
    if (names.length < 2) return names.join('');
    return names.slice(0, -1).join(', ') + ' și ' + names[names.length - 1];
  }

  /** Valorile pentru locurile data-bind; lipsa datelor lasă textul de rezervă din HTML. */
  function bindValues() {
    var data = root.EMAG_DEMO_DATA;
    var values = {};
    if (data && data.big && typeof data.big.threshold_bani === 'number') {
      values.threshold = String(Math.round(data.big.threshold_bani / 100));
    }
    if (data && data.highlights && typeof data.highlights === 'object') {
      var names = Object.keys(data.highlights); // categoriile evidențiate vin din setările programului, prin datele demo
      if (names.length) values.highlights = joinNames(names);
    }
    if (Site.viewer && Site.viewer.MAX_BYTES) values['max-size'] = Site.fmt.bytes(Site.viewer.MAX_BYTES);
    return values;
  }

  /** Înlocuiește conținutul elementelor [data-bind] cu valorile calculate. */
  function applyBindings() {
    var values = bindValues();
    Array.prototype.forEach.call(doc.querySelectorAll('[data-bind]'), function (el) {
      var key = el.getAttribute('data-bind');
      if (Object.prototype.hasOwnProperty.call(values, key)) el.textContent = values[key];
    });
  }

  /** Versiunea componentei raport din subsol, citită din EmagDashboard.version. */
  function showVersion() {
    var el = doc.getElementById('foot-version');
    if (!el) return;
    var api = root.EmagDashboard;
    el.textContent = api && api.version ? 'Componenta raport: versiunea ' + api.version + '.' : 'Componenta raport: neîncărcată (assets/dashboard.js lipsește).';
  }

  /**
   * Firefox derulează la #hash o singură dată, înainte ca JS să umple simulatorul (~1650 px deasupra secțiunilor de mai jos);
   * Chrome repetă saltul la `load`. După ce toate modulele au desenat, derulăm din nou la țintă, o singură dată.
   * Se sare peste reîncărcare și „înapoi” (browserul își restaurează singur derularea) și peste adresele #secțiune/stare,
   * pe care modulele respective le așază singure.
   */
  function settleHash() {
    var parsed = Site.state.parse();
    if (!parsed.token || parsed.sub) return;
    var target = doc.getElementById(parsed.token);
    if (!target) return;
    var entries = root.performance && root.performance.getEntriesByType ? root.performance.getEntriesByType('navigation') : [];
    if (entries.length && entries[0].type !== 'navigate') return;
    target.scrollIntoView();
  }

  /** Punctul de intrare al unui modul. Căutarea lui Site.<nume> se face la apel, în interiorul try din safely(), nu înainte. */
  function entryPoint(name) {
    if (name === 'bind') return applyBindings;
    if (name === 'version') return showVersion;
    if (name === 'hash') return settleHash;
    return name === 'state' ? Site.state.start : Site[name].init;
  }

  // Ordinea de pornire: temă și meniu primele, adresa (state) după toate modulele care se înregistrează la ea, apoi așezarea la #hash.
  var STARTUP = ['theme', 'nav', 'bind', 'version', 'hero', 'flow', 'annotations', 'simulator', 'viewer', 'reveal', 'copy', 'faq', 'problems', 'state', 'hash'];

  /**
   * Rulează un modul izolat: o eroare nu trebuie să oprească restul paginii. Un script lipsă, blocat sau stricat lasă
   * Site.<nume> nedefinit; TypeError-ul rezultat e prins aici, la fel ca orice eroare din interiorul modulului.
   */
  function safely(name) {
    try {
      entryPoint(name)();
    } catch (error) {
      if (root.console) root.console.error('site: modulul „' + name + '” a căzut', error);
    }
  }

  /** Pornirea propriu-zisă, după ce DOM-ul e gata. */
  function start() {
    doc.documentElement.classList.add('js'); // rezervă: scriptul inline din <head> pune deja clasa, dar un CSP strict l-ar bloca
    STARTUP.forEach(safely);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
