// Ecranul „Gata de start”: butonul „Pornește analiza” (cu pragul pentru achiziții mari), „Încearcă cu date inventate” și rândul „Ultima analiză” (portul lui app-start.js și app-history.js).
// Primește: trimiterea formularului, clicul pe demo și clicul pe „Deschide”; pragul îl citește din App.threshold (app-threshold.js). Dă înapoi: nimic; cheamă apelurile primite la init.
// Rândul „Ultima analiză” arată data, câte comenzi s-au citit și cât s-a plătit efectiv, ca rândurile din „Rulări anterioare” ale aplicației locale (E4: extensia păstrează doar ultima).
// Textul din date intră doar prin textContent. Ce NU face: nu pornește analiza (main.js) și nu validează pragul (app-threshold.js).
import { BIG_PURCHASE_THRESHOLD_LEI } from '../settings.js';

// Formele de plural românești ale cuvântului „comandă”, pentru rândul „Ultima analiză”.
const ORDER_FORMS = Object.freeze({ one: 'comandă', few: 'comenzi', other: 'de comenzi' });

/** Leagă formularul de pornire, butonul de demo și butonul „Deschide” al ultimei analize. */
export function initStartScreen({ onStart, onDemo, onOpenLast }) {
  const { dom, threshold } = window.App;
  dom.byId('start-form').addEventListener('submit', (event) => {
    event.preventDefault();
    showStartError('');
    const result = threshold.read();
    if (!result.ok) return; // read() a arătat eroarea lângă câmp și a mutat focusul
    onStart(result.value === null ? BIG_PURCHASE_THRESHOLD_LEI : result.value);
  });
  dom.byId('btn-demo').addEventListener('click', () => onDemo());
  dom.byId('btn-open-last').addEventListener('click', () => onOpenLast());
}

/** Mesajul de sub butonul de pornire (gol = ascuns). */
export function showStartError(message) {
  const box = window.App.dom.byId('start-error');
  box.className = `field__hint start__error${message ? ' is-bad' : ''}`;
  box.textContent = message;
}

/** Nota de după ștergerea datelor (gol = ascunsă); zonă live, deci cititorul de ecran o anunță. */
export function showDeletedNote(message) {
  window.App.dom.byId('deleted-note').textContent = message;
}

/** Arată rândul „Ultima analiză” pentru `entry` (intrarea salvată) sau îl ascunde dacă e null. */
export function showLastAnalysis(entry) {
  const { dom, format } = window.App;
  const block = dom.byId('last-block');
  block.hidden = entry === null;
  if (entry === null) return;
  const when = format.dateTime(entry.created_at);
  const orders = typeof entry.summary?.meta?.orders === 'number' ? entry.summary.meta.orders : entry.orders.length;
  const meta = [format.counted(orders, ORDER_FORMS)];
  if (typeof entry.summary?.paid?.spent_bani === 'number') meta.push(`plătit: ${format.lei(entry.summary.paid.spent_bani)}`);
  dom.byId('last-when').textContent = when;
  dom.byId('last-meta').textContent = meta.join(' · ');
  dom.byId('btn-open-last').setAttribute('aria-label', `Deschide raportul din ${when}`);
}
