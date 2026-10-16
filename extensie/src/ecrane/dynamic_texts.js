// Completează în pagină numerele care vin din settings.js, ca textele să nu se despartă de valorile din cod (CLAUDE.md §4: nicio valoare scrisă în două locuri).
// Primește: pagina (elementele cu data-login-wait și data-fetch-concurrency). Dă înapoi: nimic; le pune textul curent: „10 minute” și numărul de pagini cerute odată.
// Ce NU face: nu traduce și nu formatează altceva; textul de rezervă din HTML (valorile de azi) rămâne doar pentru cazul în care scriptul nu rulează.
import { loginWaitText } from '../colectare/run_errors.js';
import { FETCH_CONCURRENCY } from '../settings.js';

/** Pune în fiecare element marcat valoarea din setări. */
export function fillDynamicTexts(root = document) {
  for (const element of root.querySelectorAll('[data-login-wait]')) element.textContent = loginWaitText();
  for (const element of root.querySelectorAll('[data-fetch-concurrency]')) element.textContent = String(FETCH_CONCURRENCY);
}
