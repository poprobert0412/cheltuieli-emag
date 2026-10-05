/* site-faq.js — întrebările frecvente: linkuri directe (#faq-<id>) și adresa care urmează întrebarea deschisă.
 * Primește: elementele <details id="faq-…"> din #intrebari. Dă înapoi: nimic; deschide întrebarea din adresă și,
 * când omul deschide una, scrie adresa ei (replaceState: fără intrare nouă în istoric, fără salt de pagină).
 * Nu schimbă textele și nu închide celelalte întrebări: pot fi deschise mai multe.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;
  var PREFIX = 'faq-';

  /** Deschide întrebarea din adresă (#faq-<id>); un id necunoscut lasă totul închis. */
  function onState(parsed) {
    var details = doc.getElementById(parsed.token);
    if (details && details.tagName === 'DETAILS' && !details.open) details.open = true;
  }

  /** Adresa urmează ultima întrebare deschisă; la închiderea ei, adresa revine la secțiune. */
  function onToggle(event) {
    var details = event.target;
    if (!details || details.tagName !== 'DETAILS' || !details.id || details.id.indexOf(PREFIX) !== 0) return;
    if (details.open) Site.state.replace(details.id);
    else if (Site.state.parse().token === details.id) Site.state.replace('intrebari');
  }

  /** Pornește: ascultă „toggle” (nu face bubble, deci în faza de captură) și se înregistrează la adresă. */
  function init() {
    doc.addEventListener('toggle', onToggle, true);
    Site.state.register(function (parsed) { return parsed.token.indexOf(PREFIX) === 0; }, onState);
  }

  Site.faq = { init: init };
})(window);
