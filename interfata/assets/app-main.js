/* app-main.js — pornește pagina: inițializează fiecare modul app-*.js în ordine și apoi verifică aplicația.
 * Primește: nimic (modulele sunt deja încărcate de aplicatie.html, în ordinea scripturilor). Dă înapoi: nimic.
 * Fiecare modul se inițializează izolat: dacă unul are o problemă, restul paginii (și FAQ-ul) tot funcționează,
 * iar problema se vede în consolă cu numele modulului.
 * Ce NU face: nu conține logică proprie; fiecare treabă e în fișierul ei.
 */
(function (root) {
  'use strict';

  const App = root.App;

  /**
   * Rulează `start` și, dacă aruncă, scrie numele modulului în consolă fără să oprească celelalte module. App.<modul> se
   * caută abia în `start`, deci în interiorul lui try: un script care nu s-a încărcat (de exemplu o conexiune refuzată pe
   * Windows) lasă App.<modul> nedefinit, iar TypeError-ul e prins aici, nu oprește restul pornirii.
   */
  function safely(name, start) {
    try {
      start();
    } catch (error) {
      if (root.console && root.console.error) root.console.error('Cheltuieli eMAG: modulul ' + name + ' nu a pornit', error);
    }
  }

  function boot() {
    safely('screens', function () { App.screens.init(); });
    safely('threshold', function () { App.threshold.init(); });
    safely('start', function () { App.start.init(); });
    safely('run', function () { App.run.init(); });
    safely('history', function () { App.history.init(); });
    safely('session', function () { App.session.init(); });
    safely('download', function () { App.download.init(); });
    safely('report', function () { App.report.init(); });
    safely('update', function () { App.update.init(); });
    safely('faq', function () { App.faq.init(); });
    safely('lifecycle', function () { App.lifecycle.init(); });
    safely('pornire', function () { App.lifecycle.start(); });
  }

  if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window);
