/* app-lifecycle.js — viața aplicației văzută din pagină: verificarea la pornire, „Verifică din nou” și „Închide aplicația”.
 * Primește: adresa paginii (protocol, cheie în #t=) și răspunsul GET /api/hello. Dă înapoi, ca window.App.lifecycle:
 * init(), start(). La pornire: pagină deschisă din folder (nu http:) sau aplicație care nu răspunde -> „are nevoie de aplicația
 * locală”; cheie lipsă sau refuzată -> „nu mai are cheia de acces”; răspuns bun -> pornește interogarea stării (app-poll.js).
 * „Închide aplicația” cere oprirea serverului (POST /api/shutdown) și arată „Aplicația a fost închisă”; o cădere a conexiunii
 * chiar în clipa aceea înseamnă că serverul s-a oprit deja, deci tot „închisă” e.
 * Mai pune data-served="app"|"file" pe <html>: linkurile spre site-ul explicativ (index.html) există doar în „file”, pentru că aplicația locală
 * servește numai fișierele cerute de aplicatie.html; în „app” se arată în loc cum se deschide site-ul (deschide_interfata.bat).
 * Ce NU face: nu interoghează starea rulărilor (app-poll.js) și nu pornește analize (app-start.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  // Ce trebuie să răspundă GET /api/hello ca să știm că pagina vorbește cu aplicația potrivită (contractul API, versiunea 1).
  const EXPECTED_APP = 'cheltuieli-emag';
  const EXPECTED_API_VERSION = 1;

  let rechecking = false;
  let shuttingDown = false;

  /** Arată versiunea aplicației în subsol. */
  function showVersion(version) {
    const box = App.dom.byId('app-version');
    if (!box || typeof version !== 'string' || version === '') return;
    box.textContent = 'Versiunea aplicației: ' + version + '.';
    box.hidden = false;
  }

  /**
   * Întreabă aplicația „cine ești?”. La răspuns bun scoate ecranul de „închis” și pornește interogarea stării.
   * `keepReason`: la „Verifică din nou” un eșec nu schimbă motivul afișat (rămâne „s-a oprit”), doar anunță.
   */
  function check(keepReason) {
    return App.api.hello().then(function (info) {
      if (!info || info.app !== EXPECTED_APP || info.api !== EXPECTED_API_VERSION) {
        if (!keepReason) App.state.setClosed('needs-app');
        return false;
      }
      showVersion(info.version);
      App.state.setVersion(typeof info.version === 'string' ? info.version : null);
      App.state.clearClosed();
      App.poll.start();
      return true;
    }, function (error) {
      if (!keepReason) App.state.setClosed(error && error.kind === 'auth' ? 'nokey' : 'needs-app');
      else if (error && error.kind === 'auth') App.state.setClosed('nokey');
      return false;
    });
  }

  /** Pornirea paginii: protocolul, cheia, apoi /api/hello. */
  function start() {
    if (root.location.protocol !== 'http:') {
      App.state.setClosed('needs-app');
      return;
    }
    if (!App.api.init()) {
      App.state.setClosed('nokey');
      return;
    }
    check(false);
  }

  /** „Verifică din nou”: o singură întrebare către aplicație. */
  function recheck(button) {
    if (rechecking) return;
    rechecking = true;
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-busy', 'true');
    check(true).then(function (ok) {
      if (!ok) App.dom.announce('Aplicația încă nu răspunde.');
    }).then(function () {
      rechecking = false;
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
    });
  }

  /** „Închide aplicația”. */
  function shutdown(button) {
    if (shuttingDown) return;
    shuttingDown = true;
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-busy', 'true');
    const closed = function () {
      App.poll.stop();
      App.state.setClosed('user');
    };
    App.api.shutdown().then(closed, function (error) {
      if (error && error.kind === 'network') { closed(); return; }
      shuttingDown = false;
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
      App.dom.announce(error && error.message ? error.message : 'Nu am putut opri aplicația.');
    });
  }

  /** Leagă butoanele; „Verifică din nou” există doar când pagina e servită de o aplicație (http:), nu deschisă din folder. */
  function init() {
    const servedByApp = root.location.protocol === 'http:';
    root.document.documentElement.setAttribute('data-served', servedByApp ? 'app' : 'file'); // CSS alege linkul sau textul alternativ spre site-ul explicativ
    Array.prototype.forEach.call(root.document.querySelectorAll('[data-action="recheck"]'), function (button) {
      button.hidden = !servedByApp;
      button.addEventListener('click', function () { recheck(button); });
    });
    const closeButton = App.dom.byId('btn-shutdown');
    closeButton.addEventListener('click', function () { shutdown(closeButton); });
  }

  App.lifecycle = { init: init, start: start };
})(window);
