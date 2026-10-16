// Scriptul paginii de test html_lines.html: rulează html_lines.js în browser (DOMParser există doar acolo) pe paginile din fixtura html.json și pe cazurile scrise de mână.
// Primește: lista de cazuri { nume, html } de la adresa CASES_URL (o servește tests/paritate/html_lines.test.js). Dă înapoi: window.rezultateHtmlLines = [{ nume, linii, nume_produse }]
// (sau { nume, eroare } când un caz ridică o excepție) și atributul data-stare pe <html>: „gata” sau „eroare” (cu textul în window.eroareHtmlLines).
// Ce NU face: nu compară cu Python (o face testul, în Node, ca diferențele să se vadă pe pagină și pe linie) și nu schimbă nimic din modulul testat.
import { extractProductNames, htmlToLines } from '../../src/calcul/html_lines.js';

// Adresa de pe care testul servește cazurile (aceeași origine ca pagina).
const CASES_URL = '/cazuri.json';

/** Rezultatul unui caz: liniile și numele de produse, sau eroarea ca text (un caz care ridică excepție nu oprește celelalte). */
function runCase({ nume, html }) {
  try {
    return { nume, linii: htmlToLines(html), nume_produse: extractProductNames(html) };
  } catch (error) {
    return { nume, eroare: String(error?.stack ?? error) };
  }
}

/** Încarcă cazurile, le rulează pe toate și publică rezultatele în pagină. */
async function main() {
  const response = await fetch(CASES_URL);
  if (!response.ok) throw new Error(`${CASES_URL}: ${response.status}`);
  const { pagini } = await response.json();
  window.rezultateHtmlLines = pagini.map(runCase);
  document.documentElement.dataset.stare = 'gata';
}

main().catch((error) => {
  window.eroareHtmlLines = String(error?.stack ?? error);
  document.documentElement.dataset.stare = 'eroare';
});
