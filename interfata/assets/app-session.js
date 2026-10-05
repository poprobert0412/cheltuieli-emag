/* app-session.js — „Sesiunea salvată”: starea ei și ștergerea cu confirmare scrisă IN PAGINĂ (nu cu fereastra confirm()).
 * Primește: `session_saved` din starea aplicației (App.state) și cuvântul scris de om în #session-word.
 * Dă înapoi, ca window.App.session: init(). Șterge prin POST /api/session/delete, cu aceleași garanții ca `--sterge-sesiunea`.
 * Confirmarea: omul scrie DA (litere mari sau mici, spațiile din jur nu contează); pagina trimite mereu „DA”, exact cum cere
 * aplicația. Cuvânt greșit = mesaj lângă câmp, nimic trimis. Butonul de confirmare rămâne activ până pornește cererea.
 * Textul „Ești conectat de data trecută” înseamnă că există o sesiune salvată pe disc, nu că eMAG o mai recunoaște.
 * Ce NU face: nu șterge nimic singură (ștergerea o face aplicația) și nu atinge folderul .profil_browser.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const CONFIRM_WORD = 'DA';
  const SAVED_TEXT = 'Ești conectat de data trecută';
  const NOT_SAVED_TEXT = 'Nu există sesiune salvată';

  let statusEl = null;
  let deleteButton = null;
  let form = null;
  let input = null;
  let message = null;
  let confirmButton = null;
  let note = null;
  let busy = false;
  let shownSaved = null; // ce am afișat ultima dată (true/false); null = încă nimic

  function setMessage(text, kind) {
    message.className = 'field__hint' + (kind ? ' is-' + kind : '');
    message.textContent = text;
  }

  /** Cuvântul scris e DA (fără să conteze literele mari/mici și spațiile din jur)? */
  function accepted(text) {
    return String(text).trim().toUpperCase() === CONFIRM_WORD;
  }

  function closeConfirm(restoreFocus) {
    form.hidden = true;
    deleteButton.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-invalid');
    setMessage('', '');
    if (restoreFocus && !deleteButton.hidden) deleteButton.focus();
  }

  function openConfirm() {
    form.hidden = false;
    deleteButton.setAttribute('aria-expanded', 'true');
    input.value = '';
    setMessage('', '');
    input.focus();
  }

  /** Afișează starea sesiunii (din aplicație); arată butonul de ștergere doar când e ceva de șters. */
  function renderStatus(saved) {
    if (saved === shownSaved) return;
    shownSaved = saved;
    statusEl.setAttribute('data-saved', saved ? 'true' : 'false');
    statusEl.textContent = saved ? SAVED_TEXT : NOT_SAVED_TEXT;
    deleteButton.hidden = !saved;
    if (saved) note.textContent = ''; // o sesiune nouă (după un login) nu mai are de ce să poarte mesajul ștergerii vechi
    if (!saved && !form.hidden) closeConfirm(false);
  }

  /** Trimite ștergerea dacă omul a scris DA. */
  function submit(event) {
    event.preventDefault();
    if (busy) return;
    if (!accepted(input.value)) {
      input.setAttribute('aria-invalid', 'true');
      setMessage('Scrie ' + CONFIRM_WORD + ' ca să confirmi ștergerea.', 'bad');
      input.focus();
      return;
    }
    busy = true;
    confirmButton.setAttribute('aria-disabled', 'true');
    confirmButton.setAttribute('aria-busy', 'true');
    setMessage('Șterg sesiunea…', '');
    App.api.deleteSession().then(function (reply) {
      const said = reply && typeof reply.message === 'string' ? reply.message : ''; // textul aplicației (ce s-a șters, ce urmează)
      closeConfirm(false);
      renderStatus(false);
      note.textContent = said;
      statusEl.focus(); // butonul „Șterge” a dispărut: focusul rămâne pe starea sesiunii, nu se pierde
      App.dom.announce(said || 'Sesiunea salvată a fost ștearsă. Data viitoare te loghezi din nou.');
      App.poll.kick();
    }).catch(function (error) {
      setMessage(error && error.message ? error.message : 'Nu am putut șterge sesiunea.', 'bad');
    }).then(function () {
      busy = false;
      confirmButton.removeAttribute('aria-disabled');
      confirmButton.removeAttribute('aria-busy');
    });
  }

  /** Leagă controalele și se abonează la starea aplicației. */
  function init() {
    statusEl = App.dom.byId('session-status');
    note = App.dom.byId('session-note');
    deleteButton = App.dom.byId('btn-session-delete');
    form = App.dom.byId('session-confirm');
    input = App.dom.byId('session-word');
    message = App.dom.byId('session-msg');
    confirmButton = App.dom.byId('btn-session-confirm');
    deleteButton.addEventListener('click', function () { if (form.hidden) openConfirm(); else closeConfirm(true); });
    App.dom.byId('btn-session-cancel').addEventListener('click', function () { closeConfirm(true); });
    form.addEventListener('submit', submit);
    input.addEventListener('input', function () {
      input.removeAttribute('aria-invalid');
      if (message.classList.contains('is-bad')) setMessage('', '');
    });
    App.state.subscribe(function (now) {
      if (now.server) renderStatus(now.server.session_saved);
    });
  }

  App.session = { init: init };
})(window);
