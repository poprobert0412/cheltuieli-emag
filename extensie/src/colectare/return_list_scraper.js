// Strânge adresele paginilor de detalii ale tuturor retururilor din cont (portul lui emag_spend/return_list_scraper.py).
// Primește: id-ul filei de lucru (logate), raportorul de progres, un jurnal. Dă înapoi: căile de forma "/user/return-history/<x>/<număr retur>", fără duplicate.
// Lista se încarcă pe bucăți: se apasă „Vezi mai mult” până nu mai apare butonul sau nu se mai adaugă nimic; se oprește cooperant când omul cere.
// Un cont fără niciun retur nu are nicio legătură de așteptat: după timpul de randare lista e goală (cu avertisment în jurnal). Redirecționarea spre login se vede imediat și oprește rularea ca sesiune expirată.
// Ce NU face: nu descarcă detaliile returului; singurul lucru pe care îl apasă în pagina eMAG este butonul „Vezi mai mult”.
import { BASE_URL, LIST_RENDER_TIMEOUT_SECONDS, MAX_RETURN_LOAD_MORE_CLICKS, RETURN_LIST_PATH } from '../settings.js';
import { SessionExpired } from './page_fetcher.js';
import { pageClickLoadMore, pageHasReturnLinks, pageLoadMoreState, pageReturnPaths } from './page_functions.js';
import { isOutsideAccount } from './session_check.js';
import { NAVIGATION_TIMEOUT_MS, tabIo } from './work_tab.js';

const MODULE = 'return_list_scraper';
// Cât așteptăm să crească lista după o apăsare pe „Vezi mai mult” (15 s ca în Python; pe contul real lista a crescut în ~0,6 s, probă 14.10.2026).
const GROW_TIMEOUT_MS = 15_000;
// Pauza dintre două citiri ale listei, cât așteptăm randarea sau creșterea: 0,5 s ca în Python.
const POLL_INTERVAL_MS = 500;

/** Așteaptă să apară măcar un link spre un retur (cel mult LIST_RENDER_TIMEOUT_SECONDS); true dacă a apărut. Oprirea cerută se verifică la fiecare citire. */
async function waitForReturnLinks(tabId, progress, io) {
  const deadline = io.now() + LIST_RENDER_TIMEOUT_SECONDS * 1000;
  for (;;) {
    progress.raiseIfCancelled();
    if (await io.runInTab(tabId, pageHasReturnLinks)) return true;
    if (io.now() >= deadline) return false;
    await io.sleep(POLL_INTERVAL_MS);
  }
}

/** Așteaptă să crească numărul de retururi față de `before`; întoarce numărul nou (oprirea cerută se verifică la fiecare citire). */
async function waitForGrowth(tabId, before, progress, io) {
  const deadline = io.now() + GROW_TIMEOUT_MS;
  while (io.now() < deadline) {
    progress.raiseIfCancelled();
    const count = ((await io.runInTab(tabId, pageReturnPaths)) ?? []).length;
    if (count > before) return count;
    await io.sleep(POLL_INTERVAL_MS);
  }
  return before;
}

/** Căile paginilor de detalii pentru toate retururile ([] la un cont fără retururi); SessionExpired dacă fila a ajuns la login. */
export async function collectReturnPaths(tabId, progress, log, io = tabIo) {
  progress.raiseIfCancelled();
  const finalUrl = await io.navigate(tabId, BASE_URL + RETURN_LIST_PATH, NAVIGATION_TIMEOUT_MS);
  if (isOutsideAccount(finalUrl)) throw new SessionExpired('redirecționat la login la lista de retururi');
  if (!await waitForReturnLinks(tabId, progress, io)) {
    // Fără linkuri: ori contul nu are retururi, ori pagina s-a schimbat. Redirectul la login s-a verificat deja după navigare.
    log.warning(MODULE, `lista de retururi: niciun retur găsit în ${LIST_RENDER_TIMEOUT_SECONDS}s; contul nu are retururi sau pagina s-a schimbat (verifică în cont dacă ai retururi)`);
    return [];
  }
  let count = ((await io.runInTab(tabId, pageReturnPaths)) ?? []).length;
  for (let click = 0; click < MAX_RETURN_LOAD_MORE_CLICKS; click += 1) {
    progress.raiseIfCancelled();
    progress.message(`Caut retururile în cont: ${count} găsite până acum`);
    const button = await io.runInTab(tabId, pageLoadMoreState);
    if (!button || !button.exista || !button.vizibil) break;
    await io.runInTab(tabId, pageClickLoadMore);
    const grown = await waitForGrowth(tabId, count, progress, io);
    if (grown === count) break;
    count = grown;
  }
  const paths = (await io.runInTab(tabId, pageReturnPaths)) ?? [];
  log.info(MODULE, `lista de retururi: ${paths.length} retururi`);
  return paths;
}
