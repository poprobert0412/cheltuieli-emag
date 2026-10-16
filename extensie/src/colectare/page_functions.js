// Funcțiile injectate în fila eMAG de lucru (chrome.scripting.executeScript, lumea izolată): citesc pagina randată și cer paginile de detalii (E5).
// Primește: nimic din afară, doar argumente serializabile. Dă înapoi: valori simple (liste, obiecte, numere, texte), ca rezultatul să treacă înapoi prin Chrome.
// Reguli: fiecare funcție e AUTONOMĂ (Chrome o trimite ca text, deci nu poate folosi nimic din afara ei: nici constante, nici alte funcții din acest fișier) și NU aruncă niciodată
// (o funcție care aruncă în pagină dă rezultat null, indistinct de „n-a întors nimic”); erorile se întorc ca date. Selectorii și expresiile sunt cele din order_list_scraper.py,
// return_list_scraper.py și browser_session.py. Aici e SINGURUL fetch al extensiei, doar pe căi relative (https://www.emag.ro e originea filei).
// Ce NU face: nu tastează în câmpuri, nu citește cookie-uri sau parole, nu apasă decât „Vezi mai mult” din lista de retururi.

/** Starea login-ului: pagina de cont are „Comenzile mele” și „Log out” (ca browser_session._is_logged_in); `adresa_de_login` = adresa paginii conține „login”. */
export function pageLoginState() {
  const text = document.body ? document.body.innerText : '';
  return {
    logat: text.includes('Comenzile mele') && text.includes('Log out'),
    adresa_de_login: /login/i.test(location.href),
  };
}

/** Numerele comenzilor din linkurile paginii de listă, fără duplicate, în ordinea din pagină (ca _READ_IDS_JS). */
export function pageOrderIds() {
  const ids = [...document.querySelectorAll('a[href*="/history/shoppingdetails/"]')]
    .map((a) => (a.getAttribute('href').match(/shoppingdetails\/(\d+)/) || [])[1])
    .filter(Boolean);
  return [...new Set(ids)];
}

/** Ultima pagină din paginarea listei de comenzi (cel mai mare număr din paginare) sau 1 dacă nu se vede paginare (ca _LAST_PAGE_JS). */
export function pageLastPageHint() {
  const numbers = [...document.querySelectorAll('[class*="pagination"] *')]
    .filter((e) => e.children.length === 0)
    .map((e) => e.textContent.trim())
    .filter((t) => /^\d+$/.test(t))
    .map(Number);
  return numbers.length ? Math.max(...numbers) : 1;
}

/** True dacă pagina are măcar un link spre un retur (așteptarea din return_list_scraper.py: wait_for_selector). */
export function pageHasReturnLinks() {
  return document.querySelector("a[href*='/user/return-history/']") !== null;
}

/** Căile paginilor de detalii ale returnurilor din lista randată: /user/return-history/<x>/<număr retur>, fără duplicate (ca _LINKS_JS). */
export function pageReturnPaths() {
  return [...new Set([...document.querySelectorAll('a[href*="/user/return-history/"]')].map((a) => new URL(a.href, location.href).pathname))]
    .filter((p) => /\/user\/return-history\/\d+\/\d+$/.test(p));
}

/** Starea butonului „Vezi mai mult” (.js-return-history-view-more): există și e vizibil (cutie nenulă, fără visibility:hidden), ca is_visible din Playwright. */
export function pageLoadMoreState() {
  const button = document.querySelector('.js-return-history-view-more');
  if (!button) return { exista: false, vizibil: false };
  const box = button.getBoundingClientRect();
  return { exista: true, vizibil: box.width > 0 && box.height > 0 && getComputedStyle(button).visibility !== 'hidden' };
}

/** Apasă primul „Vezi mai mult”; întoarce true dacă a existat. */
export function pageClickLoadMore() {
  const button = document.querySelector('.js-return-history-view-more');
  if (!button) return false;
  button.click();
  return true;
}

/**
 * Cere o pagină eMAG din fila eMAG (aceeași origine, sesiunea omului) și întoarce { status, finalUrl, html } sau { eroare } la cădere de rețea ori depășirea termenului.
 * Doar căi care încep cu UN singur „/” (relative la originea filei); o adresă completă sau „//gazdă” e refuzată. Redirecturile se urmează, iar `finalUrl` arată unde s-a ajuns (login = sesiune expirată).
 * Capcană: la un redirect spre ALTĂ gazdă fetch-ul cade (CORS) și se întoarce { eroare }, nu o adresă de login.
 */
export async function pageFetch(path, timeoutMs) {
  if (typeof path !== 'string' || path[0] !== '/' || path[1] === '/') return { eroare: 'cale nepermisă' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { credentials: 'same-origin', redirect: 'follow', signal: controller.signal });
    const html = response.status === 200 ? await response.text() : '';
    return { status: response.status, finalUrl: response.url, html };
  } catch (error) {
    return { eroare: error && error.name === 'AbortError' ? 'timeout' : String((error && error.message) || error) };
  } finally {
    clearTimeout(timer);
  }
}
