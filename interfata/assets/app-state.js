/* app-state.js — mașina de stări a ecranului: din ce știe pagina, alege UN singur ecran.
 * Primește: starea aplicației (din /api/state), motivul de închidere (aplicația nu răspunde, a fost oprită, lipsește cheia),
 * rularea pornită din pagină și rularea veche deschisă din listă. Dă înapoi, ca window.App.state: get() (o copie a stării cu
 * câmpul `screen`), subscribe(fn), și acțiunile care schimbă starea (setServer, setClosed, beginRun, dismiss, openRun, setUpdateBusy...).
 * Ecranele: loading, ready, working, done, error, cancelled, closed-needs-app, closed-stopped, closed-user, closed-nokey, closed-updated.
 * `updateBusy` (pus de app-update.js) = se instalează o versiune nouă: „Pornește analiza” nu pornește nimic cât e adevărat.
 * Ce NU face: nu atinge DOM-ul și nu face cereri; ecranele și cererile sunt treaba celorlalte fișiere app-*.js.
 * `computeScreen` e funcție pură, expusă ca să poată fi verificată direct în teste.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  // Stările în care aplicația lucrează (valorile din contractul GET /api/state).
  const ACTIVE_STATES = ['starting', 'waiting_login', 'fetching_orders', 'fetching_returns', 'analyzing'];
  const TERMINAL_SCREENS = { done: 'done', error: 'error', cancelled: 'cancelled' };
  // După ce aplicația a acceptat o rulare (202), primul /api/state poate încă arăta rularea veche. Cât ținem ecranul „în lucru”
  // așteptând ca starea să ajungă din urmă: câteva secunde ajung (aplicația își schimbă starea înainte să răspundă), iar o
  // limită există ca o rulare care nu apare niciodată să nu țină pagina pe „în lucru” la nesfârșit.
  const PENDING_RUN_TIMEOUT_MS = 10000;

  let model = freshModel();
  const listeners = [];

  /** Starea de început: nu știm nimic încă. */
  function freshModel() {
    return {
      server: null,           // ultimul răspuns de la /api/state
      version: null,          // versiunea aplicației (din /api/hello)
      closed: null,           // null sau 'needs-app' | 'stopped' | 'user' | 'nokey' | 'updated'
      connection: 'ok',       // 'ok' | 'retrying' (aplicația nu răspunde, mai încercăm)
      viewRun: null,          // rularea veche deschisă din listă: {id, kind, created_at}
      dismissedKey: null,     // starea terminală pe care omul a închis-o deja (ca să nu revină la următoarea interogare)
      pendingRunId: null,     // rularea acceptată de aplicație, încă nevăzută în /api/state
      pendingSince: 0,
      runMode: null,          // 'real' | 'demo' pentru rularea pornită din această pagină
      runModeRunId: null,     // numărul rulării pentru care e valabil runMode
      updateBusy: false,      // se descarcă sau se instalează o versiune nouă (app-update.js): analiza nu pornește
    };
  }

  /** Cheia unei stări terminale: stare + rulare + oră de start + cod de eroare. Se schimbă la fiecare rulare nouă. */
  function keyOf(server) {
    return [server.state, server.run_id, server.started_at, server.error ? server.error.code : ''].join('|');
  }

  /** Ecranul potrivit unui model (funcție pură; `now` în milisecunde). */
  function computeScreen(m, now) {
    if (m.closed) return 'closed-' + m.closed;
    if (!m.server) return 'loading';
    if (m.viewRun) return 'done';
    if (m.pendingRunId && now - m.pendingSince < PENDING_RUN_TIMEOUT_MS && m.server.run_id !== m.pendingRunId) return 'working';
    const state = m.server.state;
    if (ACTIVE_STATES.indexOf(state) >= 0) return 'working';
    if (Object.prototype.hasOwnProperty.call(TERMINAL_SCREENS, state) && keyOf(m.server) !== m.dismissedKey) return TERMINAL_SCREENS[state];
    return 'ready';
  }

  /** O copie a modelului, cu ecranul calculat. */
  function get() {
    const copy = Object.assign({}, model);
    copy.screen = computeScreen(model, Date.now());
    return copy;
  }

  /** Aplică o schimbare și anunță abonații cu starea nouă și cea de dinainte; fiecare abonat decide singur ce re-desenează. */
  function change(mutate) {
    const before = get();
    mutate(model);
    const after = get();
    listeners.slice().forEach(function (listener) { listener(after, before); });
  }

  /** Abonare la schimbări: fn(starea nouă, starea veche). Întoarce funcția de dezabonare. */
  function subscribe(fn) {
    listeners.push(fn);
    return function () {
      const index = listeners.indexOf(fn);
      if (index >= 0) listeners.splice(index, 1);
    };
  }

  /** Ultimul răspuns de la /api/state (deja verificat de app-poll.js). Aplicația a răspuns, deci conexiunea e bună. */
  function setServer(server) {
    change(function (m) {
      m.server = server;
      m.connection = 'ok';
      if (m.pendingRunId && server.run_id === m.pendingRunId) m.pendingRunId = null;
    });
  }

  /** Conexiunea cu aplicația: 'ok' sau 'retrying'. */
  function setConnection(kind) {
    if (model.connection === kind) return;
    change(function (m) { m.connection = kind; });
  }

  /** Aplicația nu mai poate fi folosită: motivul e 'needs-app', 'stopped', 'user', 'nokey' sau 'updated' (repornește după actualizare). */
  function setClosed(reason) {
    change(function (m) { m.closed = reason; });
  }

  /** Aplicația a răspuns din nou: scoate ecranul de „închis”. */
  function clearClosed() {
    change(function (m) { m.closed = null; m.connection = 'ok'; });
  }

  function setVersion(version) {
    change(function (m) { m.version = version; });
  }

  /** Actualizarea lucrează (true) sau nu (false); anunță abonații doar la schimbare. */
  function setUpdateBusy(busy) {
    if (model.updateBusy === !!busy) return;
    change(function (m) { m.updateBusy = !!busy; });
  }

  /** O rulare a fost acceptată de aplicație: arătăm „în lucru” imediat, fără să așteptăm următoarea interogare. */
  function beginRun(runId, mode) {
    change(function (m) {
      m.pendingRunId = runId;
      m.pendingSince = Date.now();
      m.runMode = mode;
      m.runModeRunId = runId;
      m.viewRun = null;
    });
  }

  /** Omul a citit starea terminală curentă (gata, eroare, anulat) și se întoarce la început. */
  function dismiss() {
    change(function (m) { if (m.server) m.dismissedKey = keyOf(m.server); });
  }

  /** Deschide un raport vechi din lista de rulări anterioare. */
  function openRun(info) {
    change(function (m) { m.viewRun = { id: info.id, kind: info.kind, created_at: info.created_at }; });
  }

  /** Închide raportul vechi și revine la ecranul de start. */
  function closeRun() {
    change(function (m) { m.viewRun = null; });
  }

  App.state = {
    computeScreen: computeScreen,
    keyOf: keyOf,
    get: get,
    subscribe: subscribe,
    setServer: setServer,
    setConnection: setConnection,
    setClosed: setClosed,
    clearClosed: clearClosed,
    setVersion: setVersion,
    setUpdateBusy: setUpdateBusy,
    beginRun: beginRun,
    dismiss: dismiss,
    openRun: openRun,
    closeRun: closeRun,
    ACTIVE_STATES: ACTIVE_STATES.slice(),
  };
})(window);
