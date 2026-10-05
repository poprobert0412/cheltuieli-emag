/* site-reveal.js — apariție discretă (urcare + estompare) a pașilor, când ajung în ecran.
 * Primește: elementele cu clasa .reveal. Dă înapoi: nimic; adaugă clasa .is-in când intră în ecran,
 * iar CSS-ul face animația (doar transform/opacity, oprită la prefers-reduced-motion).
 * Conținutul e vizibil IMPLICIT: se animă doar elementele aflate sub marginea de jos la încărcare, iar
 * fără IntersectionObserver sau cu mișcare redusă nu se întâmplă nimic. Niciun element nu rămâne ascuns.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var ENTER_MARGIN = '0px 0px -8% 0px'; // elementul se animă puțin după ce a intrat în ecran, nu înainte

  /** Pornește observatorul pentru elementele .reveal care încă nu se văd. */
  function init() {
    if (Site.dom.prefersReducedMotion() || !('IntersectionObserver' in root)) return;
    var below = Array.prototype.filter.call(root.document.querySelectorAll('.reveal'), function (el) {
      return el.getBoundingClientRect().top > root.innerHeight; // ce se vede deja nu se animă (ar clipi)
    });
    if (!below.length) return;
    var observer = new root.IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: ENTER_MARGIN });
    below.forEach(function (el) { observer.observe(el); });
  }

  Site.reveal = { init: init };
})(window);
