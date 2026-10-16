// Ecranul „Analiza a fost oprită”: apare după „Oprește”; nu s-a creat niciun raport nou, iar analiza salvată înainte (dacă exista) a rămas neatinsă.
// Primește: clicurile pe „Înapoi la început” și „Descarcă jurnalul”. Dă înapoi: nimic; cheamă apelurile primite la init.
// Ce NU face: nu șterge nimic și nu alege ecranul următor (main.js). Butoanele sunt aceleași ca la eroare (error_screen.js).
import { bindEndButtons, setLogButton } from './error_screen.js';

/** Leagă butoanele ecranului „oprit”. */
export function initCancelledScreen(handlers) {
  bindEndButtons('screen-cancelled', handlers);
}

/** La intrarea pe ecran: „Descarcă jurnalul” apare doar dacă există un jurnal salvat. */
export function renderCancelled({ hasLog }) {
  setLogButton('screen-cancelled', hasLog);
}
