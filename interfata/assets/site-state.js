/* site-state.js — starea paginii în adresă (location.hash), cu hashchange și popstate.
 * Gramatică: "#token" sau "#token/subtoken", doar litere mici, cifre și cratime (fără #cheie=valoare).
 * Primește: înregistrări (potrivire + handler) de la celelalte module. Dă înapoi: nimic; apelează handler-ele
 * la încărcare și la fiecare schimbare de adresă. Handler-ele trebuie să fie idempotente.
 * Nu știe ce înseamnă token-urile: asta decid modulele care se înregistrează.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var TOKEN = /^[a-z0-9-]*$/;
  var handlers = [];
  var lastRaw = null; // ultima adresă procesată: popstate + hashchange vin împreună și se deduplică

  /** Descompune un hash în { token, sub, raw }; un hash invalid dă token gol. */
  function parse(hash) {
    var raw = String(hash == null ? root.location.hash : hash).replace(/^#/, '');
    try { raw = decodeURIComponent(raw); } catch (e) { /* rămâne textul brut; validarea de mai jos îl respinge */ }
    var cut = raw.indexOf('/');
    var token = cut < 0 ? raw : raw.slice(0, cut);
    var sub = cut < 0 ? '' : raw.slice(cut + 1);
    if (!TOKEN.test(token) || !TOKEN.test(sub)) return { token: '', sub: '', raw: '' };
    return { token: token, sub: sub, raw: raw };
  }

  /** Înregistrează un handler: `test` = text (token exact), RegExp (pe token) sau funcție(parsed) -> bool. */
  function register(test, fn) {
    var match = typeof test === 'function' ? test
      : test instanceof RegExp ? function (p) { return test.test(p.token); }
      : function (p) { return p.token === test; };
    handlers.push({ match: match, fn: fn });
  }

  /** Rulează handler-ele potrivite pentru adresa curentă; `source` = load | hashchange | popstate. */
  function dispatch(source) {
    var parsed = parse();
    if (source !== 'load' && parsed.raw === lastRaw) return;
    lastRaw = parsed.raw;
    handlers.forEach(function (entry) {
      try {
        if (entry.match(parsed)) entry.fn(parsed, { source: source });
      } catch (error) {
        if (root.console) root.console.error('site-state: handler căzut', error);
      }
    });
  }

  /** Schimbă adresa cu intrare nouă în istoric (declanșează hashchange). */
  function navigate(hash) {
    var wanted = String(hash || '').replace(/^#/, '');
    if (parse().raw === wanted) return;
    root.location.hash = wanted ? '#' + wanted : '';
  }

  /** Schimbă adresa fără intrare nouă în istoric și fără hashchange (pentru starea derivată din derulare). */
  function replace(hash) {
    var wanted = String(hash || '').replace(/^#/, '');
    var url = root.location.pathname + root.location.search + (wanted ? '#' + wanted : '');
    try { root.history.replaceState(null, '', url); } catch (e) { return; }
    lastRaw = parse().raw;
  }

  /** Pornește ascultarea și procesează adresa de la încărcare. Se apelează o singură dată, la final. */
  function start() {
    root.addEventListener('hashchange', function () { dispatch('hashchange'); });
    root.addEventListener('popstate', function () { dispatch('popstate'); });
    dispatch('load');
  }

  Site.state = { parse: parse, register: register, navigate: navigate, replace: replace, start: start };
})(window);
