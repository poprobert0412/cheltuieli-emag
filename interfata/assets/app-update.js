/* app-update.js — versiunea programului și actualizarea „ca la o aplicație” (decis 5 oct. 2026, D18).
 * Primește: GET /api/update ({current, check: {status, latest, notes, page_url, message...}, apply: {state, message, to_version}})
 * și starea paginii (App.state: ecranul, analiza în curs). Dă înapoi, ca window.App.update: init().
 * Arată: sub titlu, discret, versiunea curentă și ce a aflat verificarea (verific / la zi / eroare); banda „Versiune nouă: X (ai Y)”
 * cu „Ce e nou” (text simplu: textContent + white-space: pre-line, niciodată HTML) și butonul „Actualizează acum”; stările aplicării
 * (descarc, verific amprenta, instalez) în zona live a benzii; la „gata”, ecranul „Versiunea nouă e instalată” (aplicația repornește
 * într-o filă nouă); la eroare, mesajul și linkul spre pagina lansărilor (doar o adresă https://github.com/..., verificată aici).
 * Butonul e dezactivat cât rulează o analiză; cât lucrează actualizarea, „Pornește analiza” e dezactivat (App.state.setUpdateBusy).
 * Ce NU face: nu descarcă și nu instalează nimic (aplicația o face) și nu cere rețeaua direct (doar prin App.api).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  const CHECK_POLL_MS = 2000; // cât verificarea e în lucru: răspunsul vine în câteva secunde (aplicația o oprește după 15 s)
  // Cât lucrează actualizarea: o dată pe secundă, ca pagina să apuce „gata” înainte ca aplicația să se oprească (pauza ei e de 3 s).
  const APPLY_POLL_MS = 1000;
  const FAILURES_BEFORE_GIVING_UP = 3; // eșecuri la rând după care pagina nu mai întreabă (app-poll.js spune dacă aplicația s-a oprit)
  const WORKING_STATES = ['descarc', 'verific', 'instalez'];
  const RELEASES_HOST = 'github.com'; // singura gazdă spre care pagina face un link, la cererea omului (pagina lansărilor)
  const UPDATE_LABEL = 'Actualizează acum';
  const RETRY_LABEL = 'Încearcă din nou';
  const WORKING_LABEL = 'Se actualizează…';
  // Textele rândului de sub titlu; la „noua” rândul tace (o spune banda), la „eroare” și „dezactivat” vine mesajul de mai jos.
  const CHECK_TEXTS = {
    verific: 'Verific dacă există o versiune nouă…',
    'la-zi': 'E ultima versiune.',
  };
  const RUN_BLOCKS_TEXT = 'Poți actualiza după ce se termină analiza.';
  const FALLBACK_WORKING_TEXT = 'Actualizez programul…';
  const FALLBACK_ERROR_TEXT = 'Actualizarea nu a reușit. Programul a rămas la versiunea de acum.';

  let els = {};
  let info = null;        // ultimul răspuns bun de la GET /api/update
  let started = false;    // prima cerere a plecat (după ce aplicația a răspuns la „cine ești?”)
  let inFlight = false;   // o cerere GET /api/update în zbor
  let pressing = false;   // „Actualizează acum” trimis, fără răspuns încă
  let stopped = false;    // pagina nu mai întreabă (închisă, cheie refuzată, actualizare gata)
  let failures = 0;
  let timer = null;
  let requestNote = null; // mesajul unui refuz la apăsare (ex. „rulează o analiză”), până la următoarea stare
  // Ce e desenat acum în rândul de sub titlu și în linkul benzii: se redesenează doar la schimbare, ca un link cu focus
  // (navigare cu tastatura) să nu fie înlocuit sub mâna omului la fiecare întrebare a paginii.
  let shownMeta = null;
  let shownLink = null;

  /** Aduce răspunsul la forma știută de pagină; null dacă nu seamănă (atunci nu se arată nimic despre actualizare). */
  function normalize(raw) {
    if (!raw || typeof raw !== 'object' || !raw.check || typeof raw.check !== 'object' || !raw.apply || typeof raw.apply !== 'object') return null;
    const text = function (value) { return typeof value === 'string' ? value : ''; };
    return {
      current: text(raw.current),
      check: {
        status: text(raw.check.status),
        latest: text(raw.check.latest),
        notes: text(raw.check.notes),
        page_url: text(raw.check.page_url),
        message: text(raw.check.message),
      },
      apply: { state: text(raw.apply.state) || 'inactiv', message: text(raw.apply.message), to_version: text(raw.apply.to_version) },
    };
  }

  /** Adresa paginii lansărilor, doar dacă e https://github.com/... (fără utilizator, parolă sau port); altfel null. */
  function releasesPage(address) {
    if (!address) return null;
    let parsed = null;
    try {
      parsed = new root.URL(address);
    } catch (error) {
      return null;
    }
    const plain = parsed.protocol === 'https:' && parsed.hostname === RELEASES_HOST && !parsed.username && !parsed.password && !parsed.port;
    return plain ? parsed.href : null;
  }

  /** True cât rulează o analiză (ecranul „în lucru” sau o stare activă de la aplicație). */
  function analysisRuns(state) {
    if (state.screen === 'working') return true;
    return !!state.server && App.state.ACTIVE_STATES.indexOf(state.server.state) >= 0;
  }

  function isWorking() {
    return !!info && WORKING_STATES.indexOf(info.apply.state) >= 0;
  }

  /** Linkul spre pagina lansărilor (se deschide în filă nouă, fără referrer), sau null dacă adresa nu e una permisă. */
  function releasesLink(address) {
    const page = releasesPage(address);
    if (!page) return null;
    const h = App.dom.h;
    return h('a', { href: page, target: '_blank', rel: 'noopener noreferrer' }, 'pagina lansărilor',
      h('span', { class: 'sr-only' }, ' (se deschide într-o filă nouă)'));
  }

  /** Rândul discret de sub titlu: ce a aflat verificarea (versiunea curentă o scrie app-lifecycle.js alături). */
  function renderMeta() {
    const line = els.check;
    const key = info ? [info.check.status, info.check.message, info.check.page_url].join('|') : '';
    if (key === shownMeta) return;
    shownMeta = key;
    App.dom.clear(line);
    if (!info) { line.hidden = true; return; }
    const status = info.check.status;
    if (status === 'eroare') {
      line.appendChild(root.document.createTextNode(info.check.message || 'Nu am putut verifica dacă există o versiune nouă.'));
      const link = releasesLink(info.check.page_url);
      if (link) line.appendChild(App.dom.h('span', null, ' Poți verifica pe ', link, '.'));
    } else if (status === 'dezactivat') {
      line.appendChild(root.document.createTextNode('Verificarea versiunilor noi e oprită.'));
    } else if (Object.prototype.hasOwnProperty.call(CHECK_TEXTS, status)) {
      line.appendChild(root.document.createTextNode(CHECK_TEXTS[status]));
    }
    line.hidden = !line.firstChild;
  }

  /** Banda „Versiune nouă”: vizibilă la o versiune nouă (și cât lucrează sau a eșuat aplicarea), doar pe ecranele obișnuite. */
  function renderBand(state) {
    const screen = state.screen;
    const usable = screen !== 'loading' && screen.indexOf('closed-') !== 0;
    const apply = info ? info.apply.state : 'inactiv';
    const show = !!info && usable && (info.check.status === 'noua' || isWorking() || apply === 'eroare');
    els.band.hidden = !show;
    if (!show) return;
    els.latest.textContent = info.apply.to_version || info.check.latest;
    els.current.textContent = info.current;
    els.notes.textContent = info.check.notes;
    els.notesBox.hidden = info.check.notes === '';

    const working = isWorking() || pressing;
    const runBlocks = analysisRuns(state);
    els.button.textContent = working ? WORKING_LABEL : (apply === 'eroare' ? RETRY_LABEL : UPDATE_LABEL);
    if (working || runBlocks) els.button.setAttribute('aria-disabled', 'true');
    else els.button.removeAttribute('aria-disabled');
    if (working) els.button.setAttribute('aria-busy', 'true');
    else els.button.removeAttribute('aria-busy');
    els.runHint.hidden = !runBlocks || working;

    let text = '';
    let bad = false;
    if (requestNote) {
      text = requestNote;
      bad = true;
    } else if (isWorking()) {
      text = info.apply.message || FALLBACK_WORKING_TEXT;
    } else if (apply === 'eroare') {
      text = info.apply.message || FALLBACK_ERROR_TEXT;
      bad = true;
    }
    if (els.status.textContent !== text) els.status.textContent = text; // aceeași frază nu se rescrie: cititorul de ecran n-o repetă
    els.status.className = 'status update__status' + (bad ? ' is-bad' : '');

    const linkKey = apply === 'eroare' ? info.check.page_url : '';
    if (linkKey !== shownLink) {
      shownLink = linkKey;
      App.dom.clear(els.linkBox);
      const link = linkKey ? releasesLink(linkKey) : null;
      if (link) els.linkBox.appendChild(App.dom.h('span', null, 'Poți descărca versiunea nouă și de mână, de pe ', link, '.'));
      els.linkBox.hidden = !link;
    }
  }

  function render() {
    const state = App.state.get();
    renderMeta();
    renderBand(state);
  }

  function schedule(delay) {
    root.clearTimeout(timer);
    timer = stopped ? null : root.setTimeout(refresh, delay);
  }

  /** Cât mai întreabă pagina: repede cât lucrează actualizarea, mai rar cât verificarea e în lucru, deloc în rest. */
  function nextDelay() {
    if (isWorking()) return APPLY_POLL_MS;
    if (info && info.check.status === 'verific') return CHECK_POLL_MS;
    return null;
  }

  function stop() {
    stopped = true;
    root.clearTimeout(timer);
    timer = null;
  }

  /** Actualizarea s-a instalat: aplicația se oprește și repornește singură; pagina asta arată ecranul de final. */
  function finished() {
    const hadFocus = els.band.contains(root.document.activeElement); // banda dispare: focusul nu are voie să se piardă
    stop();
    shownMeta = 'gata';
    App.dom.clear(els.check);
    els.check.hidden = true; // ce a aflat verificarea nu mai e adevărat: versiunea nouă tocmai s-a instalat
    App.state.setUpdateBusy(false);
    App.poll.stop();
    App.state.setClosed('updated');
    const heading = App.dom.byId('updated-t');
    if (hadFocus && heading) heading.focus();
  }

  /** Ia un răspuns bun: desenează, anunță schimbările de stare și decide dacă mai întreabă. */
  function accept(raw) {
    const next = normalize(raw);
    if (next === null) { stop(); return; }
    const before = info ? info.apply.state : 'inactiv';
    info = next;
    failures = 0;
    if (info.apply.state !== before) requestNote = null;
    App.state.setUpdateBusy(isWorking() || info.apply.state === 'gata');
    if (info.apply.state === 'gata') { finished(); return; }
    render();
    const delay = nextDelay();
    if (delay !== null) schedule(delay);
  }

  /** O întrebare GET /api/update. */
  function refresh() {
    if (stopped || inFlight) return;
    inFlight = true;
    App.api.getUpdate().then(accept, function (error) {
      if (error && error.kind === 'auth') {
        stop();
        App.poll.stop();
        App.state.setClosed('nokey');
        return;
      }
      failures += 1;
      if (failures >= FAILURES_BEFORE_GIVING_UP || (error && error.kind === 'http')) stop();
      else schedule(isWorking() ? APPLY_POLL_MS : CHECK_POLL_MS);
    }).then(function () { inFlight = false; });
  }

  /** „Actualizează acum” (sau „Încearcă din nou” după o eroare). */
  function press() {
    const state = App.state.get();
    if (pressing || isWorking()) return;
    if (analysisRuns(state)) {
      App.dom.announce(RUN_BLOCKS_TEXT);
      return;
    }
    pressing = true;
    requestNote = null;
    render();
    App.api.applyUpdate().then(function (reply) {
      pressing = false;
      const next = info && reply ? normalize({ check: info.check, apply: reply.apply }) : null;
      if (next) info.apply = next.apply;
      App.state.setUpdateBusy(isWorking());
      render();
      stopped = false; // o întrebare oprită înainte (ex. după erori de rețea) pornește din nou: acum chiar e ceva de urmărit
      failures = 0;
      schedule(APPLY_POLL_MS);
    }, function (error) {
      pressing = false;
      if (error && error.kind === 'auth') {
        stop();
        App.poll.stop();
        App.state.setClosed('nokey');
        return;
      }
      requestNote = error && error.message ? error.message : FALLBACK_ERROR_TEXT;
      render();
      if (error && error.kind === 'http') schedule(0); // starea s-ar fi putut schimba (ex. altă apăsare a pornit-o)
    });
  }

  /** Leagă butonul și pornește prima întrebare când aplicația a răspuns (versiunea e cunoscută). */
  function init() {
    els = {
      check: App.dom.byId('update-check'),
      band: App.dom.byId('update'),
      latest: App.dom.byId('update-latest'),
      current: App.dom.byId('update-current'),
      notesBox: App.dom.byId('update-notes-box'),
      notes: App.dom.byId('update-notes'),
      button: App.dom.byId('btn-update'),
      runHint: App.dom.byId('update-run-hint'),
      status: App.dom.byId('update-status'),
      linkBox: App.dom.byId('update-link'),
    };
    els.button.addEventListener('click', press);
    App.state.subscribe(function (now, before) {
      if (now.closed && !before.closed) stop();
      if (!now.closed && before.closed && started) { // „Verifică din nou” a găsit aplicația: pagina întreabă din nou
        stopped = false;
        failures = 0;
        refresh();
      }
      if (!started && now.version && !now.closed) {
        started = true;
        refresh();
      }
      if (info) renderBand(now);
    });
  }

  App.update = { init: init, releasesPage: releasesPage };
})(window);
