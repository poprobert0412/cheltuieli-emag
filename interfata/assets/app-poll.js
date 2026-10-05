/* app-poll.js — întreabă aplicația „în ce stare ești?” (GET /api/state) și dă răspunsul mașinii de stări.
 * Primește: nimic; folosește App.api și App.state. Dă înapoi, ca window.App.poll: start(), stop(), kick() (o interogare acum).
 * Ritmul: ~1 s cât rulează o analiză, mai rar când nu rulează nimic sau fila e ascunsă (aplicația oprește singură serverul
 * după o perioadă fără cereri, deci o filă deschisă tot întreabă). La erori de rețea pauza crește (1, 2, 4, 8 s); după
 * FAILURES_BEFORE_STOPPED eșecuri la rând, ecranul spune „Aplicația s-a oprit” și interogarea se oprește (butonul
 * „Verifică din nou” o repornește). O cheie refuzată (401) duce direct la „Pagina nu mai are cheia de acces”.
 * Ce NU face: nu pornește și nu oprește rulări (asta fac app-start.js și app-run.js) și nu desenează nimic.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  const POLL_ACTIVE_MS = 1000;        // cât rulează o analiză: progresul trebuie să pară viu
  const POLL_IDLE_MS = 2500;          // nimic în lucru: ținem pagina la zi și aplicația trează
  const POLL_HIDDEN_MS = 5000;        // fila nu se vede: mai rar, dar tot cerem
  const ERROR_BACKOFF_BASE_MS = 1000; // după primul eșec: 1 s, apoi 2, 4, 8
  const ERROR_BACKOFF_MAX_MS = 8000;  // plafonul pauzei la erori: o cădere scurtă a rețelei se vindecă singură
  const FAILURES_BEFORE_STOPPED = 3;  // trei eșecuri la rând (~3 s cu pauzele de mai sus) = aplicația nu mai e acolo

  let running = false;
  let inFlight = false;
  let kickAgain = false;
  let failures = 0;
  let generation = 0; // crește la fiecare stop/start: un răspuns întârziat dintr-o interogare veche e ignorat
  let timer = null;

  /** Aduce răspunsul la forma pe care o știe restul paginii; null dacă nu seamănă a stare de aplicație. */
  function normalize(raw) {
    if (!raw || typeof raw !== 'object' || typeof raw.state !== 'string') return null;
    const progress = raw.progress && typeof raw.progress === 'object' ? raw.progress : {};
    return {
      state: raw.state,
      message: typeof raw.message === 'string' ? raw.message : '',
      progress: {
        phase: typeof progress.phase === 'string' ? progress.phase : '',
        done: typeof progress.done === 'number' ? progress.done : 0,
        total: typeof progress.total === 'number' ? progress.total : null,
      },
      run_id: typeof raw.run_id === 'string' ? raw.run_id : null,
      started_at: typeof raw.started_at === 'string' ? raw.started_at : null,
      error: raw.error && typeof raw.error === 'object'
        ? { code: typeof raw.error.code === 'string' ? raw.error.code : '', message: typeof raw.error.message === 'string' ? raw.error.message : '' }
        : null,
      session_saved: raw.session_saved === true,
    };
  }

  /** Cât așteptăm până la următoarea interogare. */
  function nextDelay() {
    if (failures > 0) return Math.min(ERROR_BACKOFF_BASE_MS * Math.pow(2, failures - 1), ERROR_BACKOFF_MAX_MS);
    if (root.document.hidden) return POLL_HIDDEN_MS;
    return App.state.get().screen === 'working' ? POLL_ACTIVE_MS : POLL_IDLE_MS;
  }

  function schedule(delay) {
    root.clearTimeout(timer);
    timer = running ? root.setTimeout(tick, delay) : null;
  }

  /** O interogare a stării și tot ce urmează din răspuns sau din eșec. */
  function tick() {
    if (!running) return;
    if (inFlight) { kickAgain = true; return; }
    inFlight = true;
    const mine = generation;
    App.api.getState().then(function (raw) {
      if (mine !== generation) return;
      const state = normalize(raw);
      if (state === null) throw new App.api.ApiError('parse', 200, 'bad_state', 'Aplicația a trimis o stare pe care pagina nu o înțelege.');
      failures = 0;
      App.state.setServer(state);
    }).catch(function (error) {
      if (mine !== generation) return;
      if (error && error.kind === 'auth') {
        stop();
        App.state.setClosed('nokey');
        return;
      }
      failures += 1;
      if (failures >= FAILURES_BEFORE_STOPPED) {
        stop();
        App.state.setClosed('stopped');
      } else {
        App.state.setConnection('retrying');
      }
    }).then(function () {
      if (mine !== generation) return; // oprit sau repornit între timp: starea de acum aparține interogării noi
      inFlight = false;
      if (!running) return;
      if (kickAgain) { kickAgain = false; schedule(0); } else schedule(nextDelay());
    });
  }

  /** Pornește interogarea (prima cerere pleacă imediat). */
  function start() {
    if (running) return;
    running = true;
    failures = 0;
    generation += 1;
    inFlight = false;
    kickAgain = false;
    schedule(0);
  }

  /** Oprește interogarea; un răspuns întârziat dintr-o cerere în zbor e ignorat. */
  function stop() {
    running = false;
    generation += 1;
    inFlight = false;
    kickAgain = false;
    root.clearTimeout(timer);
    timer = null;
  }

  /** Cere starea acum (după o acțiune a omului sau când fila redevine vizibilă). */
  function kick() {
    if (!running) return;
    if (inFlight) { kickAgain = true; return; }
    schedule(0);
  }

  root.document.addEventListener('visibilitychange', function () {
    if (!root.document.hidden) kick();
  });

  App.poll = { start: start, stop: stop, kick: kick };
})(window);
