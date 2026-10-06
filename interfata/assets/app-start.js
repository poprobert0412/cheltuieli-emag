/* app-start.js — butoanele „Pornește analiza” și „Încearcă cu date inventate” de pe ecranul de start.
 * Primește: trimiterea formularului #start-form și clicul pe #btn-demo; pragul îl citește din App.threshold.
 * Dă înapoi, ca window.App.start: init(). La succes anunță mașina de stări (beginRun), iar ecranul „în lucru” apare
 * imediat; la 409 (rulează deja una) arată progresul ei; la altă eroare scrie mesajul aplicației lângă buton.
 * Cât cererea e în zbor, butoanele rămân pe loc dar nu mai pornesc nimic (aria-disabled, nu disabled: focusul nu se pierde).
 * La fel cât se instalează o versiune nouă (App.state `updateBusy`, pus de app-update.js; decis 5 oct. 2026, D18): butoanele
 * sunt dezactivate, iar un clic doar spune de ce. Un 409 cu alt cod decât „rulează deja o analiză” arată mesajul aplicației.
 * Ce NU face: nu desenează progresul (app-run.js) și nu validează pragul (app-threshold.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const BUSY_LABEL = 'Pornesc…';
  const RUN_IN_PROGRESS = 'run_in_progress'; // codul 409 pentru „rulează deja o analiză” (alte 409: actualizare în curs)
  const UPDATE_BUSY_MESSAGE = 'Se instalează o versiune nouă a programului. Analiza poate porni după ce aplicația repornește.';

  let busy = false;
  let errorBox = null;
  let buttons = [];

  /** Pune sau scoate starea „se pornește” pe un buton, păstrându-i textul de dinainte. */
  function setButtonBusy(button, on) {
    if (on) {
      button.setAttribute('data-label', button.textContent);
      button.textContent = BUSY_LABEL;
      button.setAttribute('aria-disabled', 'true');
      button.setAttribute('aria-busy', 'true');
    } else {
      if (button.hasAttribute('data-label')) button.textContent = button.getAttribute('data-label');
      button.removeAttribute('data-label');
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
    }
  }

  /** Butoanele de pornire sunt dezactivate cât o cerere e în zbor sau cât se instalează o actualizare. */
  function syncDisabled() {
    const blocked = busy || App.state.get().updateBusy;
    buttons.forEach(function (button) {
      if (blocked) button.setAttribute('aria-disabled', 'true');
      else button.removeAttribute('aria-disabled');
    });
  }

  function showError(message) {
    errorBox.className = 'field__hint start__error' + (message ? ' is-bad' : '');
    errorBox.textContent = message;
  }

  /** Pornește o rulare în modul cerut ('real' sau 'demo'). */
  function start(mode, button) {
    if (busy) return;
    if (App.state.get().updateBusy) {
      App.dom.announce(UPDATE_BUSY_MESSAGE);
      return;
    }
    showError('');
    const threshold = App.threshold.read();
    if (!threshold.ok) return; // read() a arătat eroarea lângă câmp și a mutat focusul
    busy = true;
    setButtonBusy(button, true);
    App.api.startRun(mode, threshold.value).then(function (reply) {
      if (!reply || typeof reply.run_id !== 'string') {
        throw new App.api.ApiError('parse', 202, 'bad_reply', 'Aplicația n-a spus ce rulare a pornit.');
      }
      App.state.beginRun(reply.run_id, mode);
      App.poll.kick();
    }).catch(function (error) {
      if (error && error.status === 409 && error.code === RUN_IN_PROGRESS) {
        App.dom.announce('Rulează deja o analiză. Îți arăt progresul ei.');
        App.poll.kick();
        return;
      }
      if (error && error.kind === 'auth') {
        App.poll.stop();
        App.state.setClosed('nokey');
        return;
      }
      showError(error && error.message ? error.message : 'Nu am putut porni analiza.');
    }).then(function () {
      busy = false;
      setButtonBusy(button, false);
      syncDisabled();
    });
  }

  /** Leagă formularul și butonul de demo. */
  function init() {
    const form = App.dom.byId('start-form');
    const startButton = App.dom.byId('btn-start');
    const demoButton = App.dom.byId('btn-demo');
    errorBox = App.dom.byId('start-error');
    if (!form || !startButton || !demoButton || !errorBox) return;
    buttons = [startButton, demoButton];
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      start('real', startButton);
    });
    demoButton.addEventListener('click', function () { start('demo', demoButton); });
    App.state.subscribe(function (now, before) {
      if (now.updateBusy !== before.updateBusy) syncDisabled();
    });
  }

  App.start = { init: init };
})(window);
