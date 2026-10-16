// Ecranul „O analiză rulează deja”: apare când alt exemplar al paginii extensiei ține lacătul „o singură analiză odată” (stocare/run_lock.js).
// Primește: funcția `isStillBusy` (întreabă lacătul) și `onFree` (se cheamă când lacătul s-a eliberat). Dă înapoi: nimic; verifică singură la BUSY_RECHECK_MS și la clicul pe „Verifică din nou”.
// Pagina nu rămâne blocată: cum rularea din cealaltă filă se termină, pagina trece singură pe ecranul de start (sau pe raportul salvat). Reverificarea pornește doar cât ecranul e vizibil, cu pauza din colectare/waiting.js (cronometru în Worker).
// Ce NU face: nu pornește o analiză și nu atinge lacătul (doar îl întreabă).
import { sleep } from '../colectare/waiting.js';

// La câte secunde se reverifică lacătul: 3 s e destul de repede ca omul să nu aștepte degeaba, destul de rar ca să nu încarce nimic (e o întrebare locală, fără rețea).
const BUSY_RECHECK_MS = 3000;

// Generația reverificării programate: orice oprire sau reprogramare o schimbă, iar o pauză terminată dintr-o generație veche nu mai face nimic (pauza din Worker nu se poate anula).
let generation = 0;
let checking = false;
let handlers = null;

/** Oprește reverificarea programată (pauza deja pornită se termină, dar nu mai are efect). */
export function stopBusyWatch() {
  generation += 1;
}

/** Programează următoarea reverificare peste BUSY_RECHECK_MS. */
function scheduleRecheck() {
  generation += 1;
  const mine = generation;
  sleep(BUSY_RECHECK_MS).then(() => {
    if (mine === generation) recheck();
  });
}

/** O reverificare: dacă lacătul s-a eliberat, anunță `onFree`; altfel programează următoarea. Nu rulează două deodată. */
async function recheck() {
  if (checking || handlers === null) return;
  checking = true;
  stopBusyWatch();
  try {
    if (await handlers.isStillBusy()) scheduleRecheck();
    else handlers.onFree();
  } finally {
    checking = false;
  }
}

/** Leagă butonul „Verifică din nou”. */
export function initBusyScreen(callbacks) {
  handlers = callbacks;
  window.App.dom.byId('btn-recheck').addEventListener('click', () => recheck());
}

/** Pornește reverificarea automată (la intrarea pe ecran). */
export function startBusyWatch() {
  scheduleRecheck();
}
