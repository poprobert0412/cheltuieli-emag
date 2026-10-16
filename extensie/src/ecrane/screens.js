// Arată UN ecran din cele opt și are grijă de focus, titlul filei și anunțul pentru cititoarele de ecran (portul lui interfata/assets/app-screens.js, fără mașina de stări a aplicației locale).
// Primește: numele ecranului de arătat. Dă înapoi: nimic; ascunde celelalte secțiuni (atributul hidden), pune data-current-screen pe <html> și mută focusul pe titlul noului ecran.
// Focusul se mută pe titlu doar când omul era în ecranul care dispare (sau nicăieri); dacă citea întrebările frecvente, nu i-l furăm: schimbarea se anunță în zona live.
// La prima afișare a ecranului de start, focusul merge pe butonul mare, doar dacă nu s-a atins nimic până atunci.
// Ce NU face: nu desenează conținutul ecranelor (fiecare fișier din ecrane/ își desenează ecranul lui) și nu decide ce ecran urmează (main.js).

// Numele vine din manifest, conform alegerii lui Robert din 16 oct. 2026 (E15).
const APP_NAME = chrome.runtime.getManifest().name;
const TITLE_SUFFIX = ` · ${APP_NAME}`;
const DEFAULT_TITLE = `${APP_NAME} · extensia`;

let main = null;
let sections = {};
let current = null;
let resolvedOnce = false; // a trecut deja de ecranul „loading”?

/** Titlul (h2) al unui ecran: elementul cu tabindex="-1" din interiorul lui. */
function headingOf(section) {
  return section ? section.querySelector('[tabindex="-1"]') : null;
}

/** Titlul filei din titlul ecranului vizibil, ca fila din fundal să spună ce se întâmplă. */
export function refreshTitle() {
  const heading = headingOf(sections[current]);
  document.title = heading && heading.textContent ? heading.textContent + TITLE_SUFFIX : DEFAULT_TITLE;
}

/** Găsește secțiunile-ecran din pagină (fiecare <section data-screen="...">); ecranul „loading” rămâne cel vizibil. */
export function initScreens() {
  main = window.App.dom.byId('continut');
  sections = {};
  for (const section of window.App.dom.byId('screens').querySelectorAll('[data-screen]')) sections[section.getAttribute('data-screen')] = section;
  current = 'loading';
  refreshTitle();
}

/** Numele ecranului vizibil acum (null înainte de initScreens). */
export function currentScreen() {
  return current;
}

/** Arată ecranul `screen`; celelalte se ascund. Un nume necunoscut ridică RangeError (o greșeală de scriere nu trebuie să lase pagina goală). */
export function showScreen(screen) {
  if (!sections[screen]) throw new RangeError(`ecran necunoscut: ${screen}`);
  const previous = current;
  const active = document.activeElement;
  const leaving = previous ? sections[previous] : null;
  const focusWasInsideLeaving = !!leaving && leaving.contains(active);
  const focusWasNowhere = !active || active === document.body || active === main;

  for (const [name, section] of Object.entries(sections)) section.hidden = name !== screen;
  document.documentElement.setAttribute('data-current-screen', screen);
  current = screen;
  refreshTitle();

  if (screen === 'loading') return;
  const heading = headingOf(sections[screen]);
  if (!resolvedOnce) {
    resolvedOnce = true;
    const start = window.App.dom.byId('btn-start');
    if (screen === 'ready' && focusWasNowhere && start) start.focus({ preventScroll: true });
    return;
  }
  if (heading && (focusWasInsideLeaving || focusWasNowhere)) heading.focus();
  if (heading) window.App.dom.announce(heading.textContent);
}
