/* app-main.js — pornește pagina: inițializează fiecare modul app-*.js în ordine și apoi verifică aplicația.
 * Primește: nimic (modulele sunt deja încărcate de aplicatie.html, în ordinea scripturilor). Dă înapoi: nimic.
 * Fiecare modul se inițializează izolat: dacă unul are o problemă, restul paginii (și FAQ-ul) tot funcționează,
 * iar problema se vede în consolă cu numele modulului.
 * Ce NU face: nu conține logică proprie; fiecare treabă e în fișierul ei.
 */
(function (root) {
  'use strict';

  const App = root.App;

  /** Rulează `init` și, dacă aruncă, scrie numele modulului în consolă fără să oprească celelalte module. */
  function safely(name, init) {
    try {
      init();
    } catch (error) {
      if (root.console && root.console.error) root.console.error('Cheltuieli eMAG: modulul ' + name + ' nu a pornit', error);
    }
  }

  function boot() {
    safely('screens', App.screens.init);
    safely('threshold', App.threshold.init);
    safely('start', App.start.init);
    safely('run', App.run.init);
    safely('history', App.history.init);
    safely('session', App.session.init);
    safely('download', App.download.init);
    safely('report', App.report.init);
    safely('update', App.update.init);
    safely('faq', App.faq.init);
    safely('lifecycle', App.lifecycle.init);
    safely('pornire', App.lifecycle.start);
  }

  if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window);
