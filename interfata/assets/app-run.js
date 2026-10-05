/* app-run.js — ecranul „în lucru”: cei 4 pași, bara de progres cu numere, mesajul mare de login și butonul „Oprește”.
 * Primește: starea de la App.state (starea aplicației: starting, waiting_login, fetching_orders, fetching_returns, analyzing;
 * progres {done, total}; mesajul ei). Dă înapoi, ca window.App.run: init().
 * Pașii: 1 Conectare, 2 Comenzi, 3 Retururi, 4 Calcul; cei dinaintea celui activ sunt „gata”. La o rulare cu date inventate
 * (pornită din această pagină) pașii 1–3 sunt „nu e nevoie”: nu se citește nimic din cont.
 * Fără salturi de layout: variantele mesajului stau suprapuse în aceeași celulă (înălțime = a celei mai înalte), iar textul se schimbă pe loc.
 * Cititoare de ecran: schimbările de pas și, din sfert în sfert de progres, cifrele se anunță în zona live (nu la fiecare secundă).
 * Ce NU face: nu pornește rulări (app-start.js) și nu interoghează aplicația (app-poll.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  const STEP_KEYS = ['login', 'orders', 'returns', 'calc'];
  const STEP_NAMES = ['Conectare', 'Comenzi', 'Retururi', 'Calcul'];
  // Pasul activ pentru fiecare stare a aplicației (valorile din contractul GET /api/state).
  const ACTIVE_STEP = { starting: 0, waiting_login: 0, fetching_orders: 1, fetching_returns: 2, analyzing: 3 };
  const STATUS_TEXT = { pending: 'în așteptare', active: 'în lucru', done: 'gata', skipped: 'nu e nevoie' };
  const NOUNS = { fetching_orders: 'Comenzi', fetching_returns: 'Retururi' };
  // Cifrele de progres se anunță cititoarelor de ecran din 25 în 25 la sută, nu la fiecare interogare (ar vorbi încontinuu).
  const ANNOUNCE_EVERY_PERCENT = 25;
  const FULL_PERCENT = 100;

  // Mesajele mari stau în aplicatie.html (câte un .callout__item per stare); aici se alege doar care se vede și cum arată cutia.
  const CALLOUT_KINDS = { waiting_login: 'login', retrying: 'warn' }; // restul stărilor: 'info'

  let lastStep = -1;
  let lastState = '';
  let lastBucket = -1;
  let cancelBusy = false;

  /** True dacă rularea de acum e cea cu date inventate pornită din această pagină. */
  function isDemoRun(snap) {
    if (snap.runMode !== 'demo' || snap.runModeRunId === null) return false;
    return snap.pendingRunId === snap.runModeRunId || (snap.server !== null && snap.server.run_id === snap.runModeRunId);
  }

  /** Starea aplicației ca nume de pas; înainte să știm ceva (rulare abia acceptată) e „starting”. */
  function effectiveState(snap) {
    return snap.server && Object.prototype.hasOwnProperty.call(ACTIVE_STEP, snap.server.state) ? snap.server.state : 'starting';
  }

  /** Pune starea fiecărui pas în listă: marcajul, textul de stare și aria-current pe cel activ. */
  function renderSteps(activeIndex, demo) {
    STEP_KEYS.forEach(function (key, index) {
      const item = root.document.querySelector('#steps [data-step="' + key + '"]');
      if (!item) return;
      let status = 'pending';
      if (demo && index < 3) status = 'skipped';
      else if (index < activeIndex) status = 'done';
      else if (index === activeIndex) status = 'active';
      item.setAttribute('data-status', status);
      if (status === 'active') item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
      item.querySelector('.step__status').textContent = STATUS_TEXT[status];
    });
  }

  /** Mesajul mare: login, citire, calcul; sau „conexiunea s-a întrerupt” cât aplicația nu răspunde. */
  function renderCallout(state, snap, demo) {
    let key = state;
    if (snap.connection === 'retrying') key = 'retrying';
    else if (state === 'analyzing' && demo) key = 'analyzing_demo';
    App.dom.byId('work-callout').setAttribute('data-kind', CALLOUT_KINDS[key] || 'info');
    Array.prototype.forEach.call(root.document.querySelectorAll('#work-callout .callout__item'), function (item) {
      if (item.getAttribute('data-state') === key) item.setAttribute('data-active', ''); else item.removeAttribute('data-active');
    });
  }

  /** Bara și eticheta ei: cu total cunoscut „Comenzi: 325 din 416”, fără total „citite până acum”, la calcul indeterminată. */
  function renderProgress(state, server) {
    const box = App.dom.byId('progress');
    const bar = App.dom.byId('progress-bar');
    const fill = App.dom.byId('progress-fill');
    const label = App.dom.byId('progress-label');
    const noun = NOUNS[state];
    const progress = server ? server.progress : { done: 0, total: null };
    let mode = 'idle';
    let text = state === 'waiting_login' ? 'Aștept să te loghezi…' : 'Pornesc…';
    let percent = -1;

    if (noun && progress.total !== null && progress.total > 0) {
      const done = Math.min(Math.max(progress.done, 0), progress.total);
      percent = Math.round(done / progress.total * FULL_PERCENT);
      mode = 'determinate';
      text = noun + ': ' + App.format.count(done) + ' din ' + App.format.count(progress.total);
    } else if (noun) {
      mode = 'indeterminate';
      text = progress.done > 0 ? noun + ': ' + App.format.count(progress.done) + ' citite până acum' : noun + ': încep…';
    } else if (state === 'analyzing') {
      mode = 'indeterminate';
      text = 'Calculez raportul…';
    }

    box.setAttribute('data-mode', mode);
    label.textContent = text;
    if (mode === 'determinate') {
      bar.setAttribute('aria-valuenow', String(percent));
      bar.setAttribute('aria-valuetext', text);
      fill.style.transform = 'scaleX(' + (percent / FULL_PERCENT) + ')';
    } else {
      bar.removeAttribute('aria-valuenow');
      bar.removeAttribute('aria-valuetext');
      fill.style.transform = '';
    }
    return { percent: percent, text: text, mode: mode, counted: !!noun };
  }

  /** Anunță schimbarea de pas, intrarea în așteptarea login-ului și, din sfert în sfert, progresul. */
  function announceChanges(state, activeIndex, progressInfo) {
    if (state === 'waiting_login' && lastState !== 'waiting_login') {
      App.dom.announce('S-a deschis o fereastră de browser. Loghează-te acolo în contul tău eMAG; eu aștept.');
    } else if (activeIndex !== lastStep && lastStep !== -1) {
      App.dom.announce('Pasul ' + (activeIndex + 1) + ' din ' + STEP_NAMES.length + ': ' + STEP_NAMES[activeIndex] + '.');
    }
    if (progressInfo.percent >= 0) {
      const bucket = Math.floor(progressInfo.percent / ANNOUNCE_EVERY_PERCENT);
      if (bucket !== lastBucket && lastBucket !== -1 && activeIndex === lastStep) App.dom.announce(progressInfo.text);
      lastBucket = bucket;
    } else {
      lastBucket = -1;
    }
    lastStep = activeIndex;
    lastState = state;
  }

  /** Desenează tot ecranul „în lucru” din starea curentă. */
  function render(snap) {
    const state = effectiveState(snap);
    const demo = isDemoRun(snap);
    const activeIndex = demo ? STEP_KEYS.length - 1 : ACTIVE_STEP[state]; // la demo singurul pas care lucrează e „Calcul”
    renderSteps(activeIndex, demo);
    renderCallout(state, snap, demo);
    const progressInfo = renderProgress(state, snap.server);
    // Mesajul aplicației se arată doar unde spune ceva în plus: la căutarea paginilor din listă („pagina 3 din 12”, fără total) și după „Oprește”.
    // În rest repetă titlul de mai sus sau cifrele din bară.
    const detailAdds = (progressInfo.counted && progressInfo.mode === 'indeterminate') || cancelBusy;
    App.dom.byId('work-detail').textContent = detailAdds && snap.server && snap.server.message ? snap.server.message : '';
    announceChanges(state, activeIndex, progressInfo);
  }

  /** La intrarea pe ecran: uită ce s-a anunțat la rularea de dinainte și readuce butonul „Oprește” la starea de început. */
  function enter() {
    lastStep = -1;
    lastState = '';
    lastBucket = -1;
    cancelBusy = false;
    const button = App.dom.byId('btn-cancel');
    button.textContent = 'Oprește';
    button.removeAttribute('aria-disabled');
    button.removeAttribute('aria-busy');
  }

  /** Cere oprirea rulării; butonul rămâne pe loc, dar nu mai cere încă o dată. */
  function cancel() {
    if (cancelBusy) return;
    cancelBusy = true;
    const button = App.dom.byId('btn-cancel');
    button.textContent = 'Se oprește…';
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-busy', 'true');
    App.dom.announce('Opresc analiza…');
    App.api.cancelRun().then(function () {
      App.poll.kick();
    }).catch(function (error) {
      cancelBusy = false;
      button.textContent = 'Oprește';
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
      App.dom.byId('work-detail').textContent = error && error.message ? error.message : 'Nu am putut cere oprirea.';
    });
  }

  /** Ecranul de eroare: mesajul aplicației, în română, așa cum l-a trimis (text, nu HTML). */
  function renderError(snap) {
    const fromServer = snap.server && snap.server.error && snap.server.error.message ? snap.server.error.message : '';
    const fallback = snap.server && snap.server.message ? snap.server.message : 'Aplicația nu a spus ce s-a întâmplat. Jurnalul din folderul logs poate ajuta.';
    App.dom.byId('error-message').textContent = fromServer || fallback;
  }

  /** Leagă ecranul de stare, butonul „Oprește” și butoanele „Înapoi la început” din ecranele de eroare și de anulare. */
  function init() {
    App.dom.byId('btn-cancel').addEventListener('click', cancel);
    Array.prototype.forEach.call(root.document.querySelectorAll('[data-action="back"]'), function (button) {
      button.addEventListener('click', function () { App.state.dismiss(); });
    });
    App.state.subscribe(function (now, before) {
      if (now.screen === 'error') renderError(now);
      if (now.screen !== 'working') return;
      if (before.screen !== 'working') enter();
      render(now);
    });
  }

  App.run = { init: init };
})(window);
