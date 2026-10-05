/* app-start.js — butoanele „Pornește analiza” și „Încearcă cu date inventate” de pe ecranul de start.
 * Primește: trimiterea formularului #start-form și clicul pe #btn-demo; pragul îl citește din App.threshold.
 * Dă înapoi, ca window.App.start: init(). La succes anunță mașina de stări (beginRun), iar ecranul „în lucru” apare
 * imediat; la 409 (rulează deja una) arată progresul ei; la altă eroare scrie mesajul aplicației lângă buton.
 * Cât cererea e în zbor, butoanele rămân pe loc dar nu mai pornesc nimic (aria-disabled, nu disabled: focusul nu se pierde).
 * Ce NU face: nu desenează progresul (app-run.js) și nu validează pragul (app-threshold.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const BUSY_LABEL = 'Pornesc…';

  let busy = false;
  let errorBox = null;

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

  function showError(message) {
    errorBox.className = 'field__hint start__error' + (message ? ' is-bad' : '');
    errorBox.textContent = message;
  }

  /** Pornește o rulare în modul cerut ('real' sau 'demo'). */
  function start(mode, button) {
    if (busy) return;
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
      if (error && error.status === 409) {
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
    });
  }

  /** Leagă formularul și butonul de demo. */
  function init() {
    const form = App.dom.byId('start-form');
    const startButton = App.dom.byId('btn-start');
    const demoButton = App.dom.byId('btn-demo');
    errorBox = App.dom.byId('start-error');
    if (!form || !startButton || !demoButton || !errorBox) return;
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      start('real', startButton);
    });
    demoButton.addEventListener('click', function () { start('demo', demoButton); });
  }

  App.start = { init: init };
})(window);
