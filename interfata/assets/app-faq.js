/* app-faq.js — deschide întrebarea din FAQ la care trimite un link intern (#faq-...) sau adresa paginii.
 * Primește: clicuri pe linkuri către #faq-... și hash-ul paginii. Dă înapoi, ca window.App.faq: init().
 * FAQ-ul stă întreg în aplicatie.html, ca <details> native (se deschid și se citesc și fără acest fișier); aici doar se
 * deschide întrebarea țintă și focusul merge pe titlul ei, ca omul care a apăsat „Ce fac dacă nu merge?” să o vadă deschisă.
 * Ce NU face: nu generează textele și nu ține minte ce e deschis (nu scrie în adresă, ca să nu se amestece cu cheia de acces).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const FAQ_PREFIX = '#faq-';

  /** Deschide întrebarea cu id-ul dat și o aduce în ecran; false dacă id-ul nu e o întrebare din FAQ. */
  function openItem(id) {
    const item = App.dom.byId(id);
    if (!item || item.tagName !== 'DETAILS' || !item.classList.contains('faq__item')) return false;
    item.open = true;
    const summary = item.querySelector('summary');
    if (summary) {
      summary.scrollIntoView({ block: 'start' });
      summary.focus({ preventScroll: true });
    }
    return true;
  }

  /** Deschide întrebarea din hash-ul adresei, dacă hash-ul e o întrebare din FAQ. */
  function openFromHash() {
    const hash = root.location.hash;
    if (hash.indexOf(FAQ_PREFIX) === 0) openItem(hash.slice(1));
  }

  /** Leagă clicurile pe linkurile către FAQ și schimbările de hash. */
  function init() {
    root.document.addEventListener('click', function (event) {
      const link = event.target.closest ? event.target.closest('a[href^="#faq-"]') : null;
      if (!link) return;
      if (openItem(link.getAttribute('href').slice(1))) event.preventDefault();
    });
    root.addEventListener('hashchange', openFromHash);
    openFromHash();
  }

  App.faq = { init: init, openItem: openItem };
})(window);
