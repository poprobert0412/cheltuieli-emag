/* app-history.js — lista „Rulări anterioare” de pe ecranul de start (din GET /api/runs, adică folderul iesiri/).
 * Primește: lista de rulări de la aplicație [{id, created_at, kind, orders, kept_bani, has_report}, opțional spent_bani], cele mai noi întâi.
 * Dă înapoi, ca window.App.history: init(), load() (Promise cu lista), lookup(id) (Promise cu rularea sau null).
 * Fiecare rând: data, „Demo” la cele cu date inventate, numărul de comenzi, cât ai plătit efectiv (`spent_bani`, din analizele
 * noi) sau, la rulările vechi, cât ai păstrat la preț de listă (`kept_bani`), și butonul „Deschide” (doar dacă există raport).
 * Lista se reîncarcă de fiecare dată când ecranul de start reapare (o rulare nouă a adăugat un rând).
 * Ce NU face: nu citește fișiere de pe disc (doar aplicația o face) și nu desenează raportul (app-report.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  // Câte rânduri se arată o dată: lista poate crește oricât, dar ecranul de start rămâne scurt; restul se cere cu „Arată încă”.
  const PAGE_SIZE = 10;
  const ORDER_FORMS = { one: 'comandă', few: 'comenzi', other: 'de comenzi' };
  const RUN_FORMS = { one: 'rulare', few: 'rulări', other: 'de rulări' };

  let runs = null;    // null = încă necitită
  let shown = PAGE_SIZE;
  let pending = null; // cererea în zbor, ca două cereri să nu se calce

  /** True dacă elementul listei are forma din contract (restul se ignoră, nu strică lista). */
  function isRun(item) {
    return !!item && typeof item === 'object' && typeof item.id === 'string' && item.id !== '';
  }

  /** Un rând al listei, construit din noduri (numele și datele vin din aplicație: doar textContent). */
  function rowFor(run) {
    const h = App.dom.h;
    const when = App.format.dateTime(run.created_at);
    const meta = [];
    if (typeof run.orders === 'number') meta.push(App.format.counted(run.orders, ORDER_FORMS));
    if (typeof run.spent_bani === 'number') meta.push('plătit: ' + App.format.lei(run.spent_bani));
    else if (typeof run.kept_bani === 'number') meta.push('păstrat: ' + App.format.lei(run.kept_bani));
    const demo = run.kind === 'demo';
    const action = run.has_report === true
      ? h('button', {
        class: 'btn btn--small',
        type: 'button',
        'aria-label': 'Deschide raportul din ' + when + (demo ? ' (date inventate)' : ''),
        onclick: function () { App.report.openPast(run); },
      }, 'Deschide')
      : h('span', { class: 'run__none' }, 'fără raport');
    return h('li', { class: 'run' },
      h('div', { class: 'run__main' },
        h('p', { class: 'run__when' }, when, demo ? h('span', { class: 'tag' }, 'Demo') : null),
        meta.length ? h('p', { class: 'run__meta' }, meta.join(' · ')) : null),
      action);
  }

  function setStatus(text, bad) {
    const status = App.dom.byId('hist-status');
    status.className = 'status' + (bad ? ' is-bad' : '');
    status.textContent = text;
  }

  /** Desenează lista din ce avem în memorie. */
  function render() {
    const list = App.dom.clear(App.dom.byId('hist-list'));
    const more = App.dom.byId('hist-more');
    App.dom.byId('hist-retry').hidden = true;
    if (!runs || runs.length === 0) {
      setStatus('Nu ai rulări anterioare. După prima analiză apare aici.', false);
      more.hidden = true;
      return;
    }
    setStatus(App.format.counted(runs.length, RUN_FORMS) + ', cele mai noi primele.', false);
    runs.slice(0, shown).forEach(function (run) { list.appendChild(rowFor(run)); });
    more.hidden = runs.length <= shown;
  }

  /** Cere lista de la aplicație; o singură cerere odată. Nu respinge niciodată: la eroare arată mesajul și butonul „Încearcă din nou”. */
  function load() {
    if (pending) return pending;
    if (runs === null) setStatus('Se încarcă lista…', false);
    pending = App.api.listRuns().then(function (list) {
      runs = Array.isArray(list) ? list.filter(isRun) : [];
      shown = PAGE_SIZE;
      render();
      return runs;
    }, function (error) {
      App.dom.clear(App.dom.byId('hist-list'));
      App.dom.byId('hist-more').hidden = true;
      App.dom.byId('hist-retry').hidden = false;
      setStatus('Nu am putut citi lista de rulări: ' + (error && error.message ? error.message : 'eroare necunoscută') + '.', true);
      return [];
    }).then(function (result) {
      pending = null;
      return result;
    });
    return pending;
  }

  /** Rularea cu id-ul dat (din memorie sau, dacă lipsește, după o reîncărcare a listei); null dacă nu există. */
  function lookup(id) {
    const find = function (list) {
      for (let i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
      return null;
    };
    if (runs !== null) {
      const known = find(runs);
      if (known) return Promise.resolve(known);
    }
    return load().then(find);
  }

  /** Leagă butoanele listei și reîncarcă lista la fiecare intrare pe ecranul de start. */
  function init() {
    App.dom.byId('hist-more').addEventListener('click', function () {
      shown += PAGE_SIZE;
      render();
    });
    App.dom.byId('hist-retry').addEventListener('click', load);
    App.state.subscribe(function (now, before) {
      if (now.screen === 'ready' && before.screen !== 'ready') load();
    });
  }

  App.history = { init: init, load: load, lookup: lookup };
})(window);
