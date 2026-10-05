/* site-flow.js — butonul de pauză al animației din diagrama de flux.
 * Primește: figura #flow și butonul #flow-pause. Dă înapoi: nimic; comută atributul data-paused,
 * pe care CSS-ul îl folosește ca să oprească pachetele care circulă între noduri.
 * Animația în sine e doar CSS (transform/opacity) și se oprește singură la prefers-reduced-motion.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});

  /** Leagă butonul: Oprește/Pornește animația, cu aria-pressed și etichetă actualizate. */
  function init() {
    var flow = root.document.getElementById('flow');
    var button = root.document.getElementById('flow-pause');
    if (!flow || !button) return;
    button.addEventListener('click', function () {
      var paused = flow.getAttribute('data-paused') !== 'true';
      flow.setAttribute('data-paused', String(paused));
      button.setAttribute('aria-pressed', String(paused));
      button.textContent = paused ? 'Pornește animația' : 'Oprește animația';
    });
  }

  Site.flow = { init: init };
})(window);
