/* app-download.js — butoanele de descărcare de pe ecranul cu raportul: raport.html, produse.csv, istoric_preturi.csv, rezumat.txt.
 * Primește: clicul pe un buton cu data-file și rularea afișată (din App.state). Dă înapoi, ca window.App.download: init().
 * Fișierul se cere cu fetch + cheia în antet (App.api.getFile), se face Blob și se salvează printr-un link temporar cu
 * atributul download: așa cheia nu apare niciodată într-o adresă sau într-un link simplu. Linkul temporar nu are adresă de
 * rețea, doar una blob: din memoria paginii, revocată după ce browserul a apucat să înceapă descărcarea.
 * Ce NU face: nu alege fișiere în afara listei albe a aplicației (o verifică și App.api) și nu deschide fișierul descărcat.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  // Cât ținem adresa blob: vie după clic. Firefox are nevoie de câteva secunde ca să înceapă salvarea; după aceea se eliberează memoria.
  const REVOKE_DELAY_MS = 10000;

  let busy = false;
  let message = null;

  function setMessage(text, bad) {
    message.className = 'field__hint' + (bad ? ' is-bad' : '');
    message.textContent = text;
  }

  /** Numărul rulării afișate acum: cea deschisă din listă sau cea abia terminată. */
  function currentRunId() {
    const snap = App.state.get();
    if (snap.viewRun) return snap.viewRun.id;
    return snap.server && snap.server.run_id ? snap.server.run_id : null;
  }

  /** Salvează un Blob sub numele dat, printr-un link temporar cu download. */
  function save(blob, name) {
    const url = root.URL.createObjectURL(blob);
    const link = App.dom.h('a', { href: url, download: name, hidden: true });
    root.document.body.appendChild(link);
    link.click();
    link.remove();
    root.setTimeout(function () { root.URL.revokeObjectURL(url); }, REVOKE_DELAY_MS);
  }

  /** Descarcă fișierul butonului apăsat. */
  function download(button) {
    if (busy) return;
    const name = button.getAttribute('data-file');
    const id = currentRunId();
    if (!id) {
      setMessage('Nu știu din ce rulare să descarc. Închide raportul și deschide-l din nou.', true);
      return;
    }
    busy = true;
    button.setAttribute('aria-busy', 'true');
    setMessage('Pregătesc ' + name + '…', false);
    App.api.getFile(id, name).then(function (blob) {
      save(blob, name);
      setMessage('A pornit descărcarea fișierului ' + name + '. Îl găsești în folderul de descărcări al browserului.', false);
    }).catch(function (error) {
      setMessage('Nu am putut descărca ' + name + ': ' + (error && error.message ? error.message : 'eroare necunoscută') + '.', true);
    }).then(function () {
      busy = false;
      button.removeAttribute('aria-busy');
    });
  }

  /** Leagă butoanele de descărcare. */
  function init() {
    message = App.dom.byId('dl-msg');
    Array.prototype.forEach.call(root.document.querySelectorAll('button[data-file]'), function (button) {
      button.addEventListener('click', function () { download(button); });
    });
  }

  App.download = { init: init };
})(window);
