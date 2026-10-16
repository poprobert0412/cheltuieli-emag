// Deschide întrebarea din întrebările frecvente la care trimite un link intern (#faq-...), de exemplu „Ce fac dacă nu merge?” din ecranul de eroare (portul lui app-faq.js).
// Primește: clicuri pe linkuri către #faq-... și adresa paginii. Dă înapoi: nimic; deschide întrebarea țintă și mută focusul pe titlul ei.
// Întrebările stau întregi în aplicatie.html, ca <details> native (se deschid și se citesc și fără acest fișier). Nu ține minte ce e deschis și nu scrie în adresa paginii.
// Ce NU face: nu generează textele întrebărilor.
const FAQ_PREFIX = '#faq-';

/** Deschide întrebarea cu id-ul dat și o aduce în ecran; false dacă id-ul nu e o întrebare din FAQ. */
function openItem(id) {
  const item = document.getElementById(id);
  if (!item || item.tagName !== 'DETAILS' || !item.classList.contains('faq__item')) return false;
  item.open = true;
  const summary = item.querySelector('summary');
  if (summary) {
    summary.scrollIntoView({ block: 'start' });
    summary.focus({ preventScroll: true });
  }
  return true;
}

/** Leagă clicurile pe linkurile către FAQ și deschide întrebarea din hash-ul adresei, dacă e una. */
export function initFaqLinks() {
  document.addEventListener('click', (event) => {
    const link = event.target.closest ? event.target.closest('a[href^="#faq-"]') : null;
    if (link && openItem(link.getAttribute('href').slice(1))) event.preventDefault();
  });
  const openFromHash = () => {
    if (window.location.hash.startsWith(FAQ_PREFIX)) openItem(window.location.hash.slice(1));
  };
  window.addEventListener('hashchange', openFromHash);
  openFromHash();
}
