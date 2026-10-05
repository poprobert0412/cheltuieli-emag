/* site-copy.js — butoanele „Copiază” de lângă comenzi și exemple.
 * Primește: butoane cu data-copy-from="#id" (nodul al cărui text se copiază). Dă înapoi: nimic;
 * copiază în clipboard și confirmă vizibil („Copiat”) și pentru cititoare de ecran.
 * navigator.clipboard.writeText se apelează direct în handlerul de clic (altfel browserul îl refuză);
 * dacă lipsește sau e refuzat, textul se selectează și se încearcă execCommand('copy'), apoi omul apasă Ctrl+C.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;
  var FEEDBACK_MS = 1800; // cât timp rămâne „Copiat” pe buton

  /** Selectează tot textul nodului (rezerva când clipboard-ul nu e disponibil). */
  function selectNode(node) {
    var range = doc.createRange();
    range.selectNodeContents(node);
    var selection = root.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /** Rezerva: selectează textul și încearcă execCommand('copy'); întoarce true dacă browserul a copiat. */
  function fallbackCopy(node) {
    selectNode(node);
    try { return !!doc.execCommand && doc.execCommand('copy'); } catch (e) { return false; }
  }

  /** Arată rezultatul pe buton și îl anunță; revine la eticheta inițială după o clipă. */
  function feedback(button, copied) {
    var original = button.getAttribute('data-label') || button.textContent;
    button.setAttribute('data-label', original);
    button.textContent = copied ? 'Copiat' : 'Selectat: Ctrl + C';
    button.setAttribute('data-copied', String(copied));
    Site.dom.announce(copied ? 'Comanda a fost copiată.' : 'Textul e selectat; apasă Ctrl și C ca să-l copiezi.');
    root.clearTimeout(button._copyTimer);
    button._copyTimer = root.setTimeout(function () {
      button.textContent = original;
      button.removeAttribute('data-copied');
    }, FEEDBACK_MS);
  }

  /** Tratează un clic pe un buton „Copiază”. */
  function onClick(button) {
    var node = doc.querySelector(button.getAttribute('data-copy-from'));
    if (!node) return;
    var text = node.textContent;
    if (root.navigator.clipboard && typeof root.navigator.clipboard.writeText === 'function') {
      var pending;
      try {
        pending = root.navigator.clipboard.writeText(text); // direct în handler: altfel browserul îl refuză
      } catch (e) { // unele browsere aruncă sincron în loc să respingă promisiunea
        feedback(button, fallbackCopy(node));
        return;
      }
      Promise.resolve(pending).then(
        function () { feedback(button, true); },
        function () { feedback(button, fallbackCopy(node)); }
      );
    } else {
      feedback(button, fallbackCopy(node));
    }
  }

  /** Leagă toate butoanele printr-un singur ascultător pe document. */
  function init() {
    doc.addEventListener('click', function (event) {
      var button = event.target.closest && event.target.closest('[data-copy-from]');
      if (button) onClick(button);
    });
  }

  Site.copy = { init: init };
})(window);
