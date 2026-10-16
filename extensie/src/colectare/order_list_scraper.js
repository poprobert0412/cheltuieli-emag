// Strânge numerele tuturor comenzilor din lista paginată din contul eMAG (portul lui emag_spend/order_list_scraper.py).
// Primește: id-ul filei de lucru (logate), o limită opțională de comenzi, raportorul de progres, un jurnal. Dă înapoi: numerele de comandă, fără duplicate, în ordinea din listă (cele mai noi primele).
// Lista e randată de JavaScript, deci se așteaptă să se încarce comenzile reale (nu cele 3 schelete cu număr 000000000): citire stabilă = două citiri identice la rând.
// Dacă apare o comandă nouă în timpul parcurgerii, paginile se deplasează cu o poziție și unele numere apar de două ori; dublurile se elimină, nu se pierde nicio comandă.
// Se oprește cooperant când omul cere (între pagini și în așteptarea randării). Ce NU face: nu descarcă detaliile comenzilor.
import { BASE_URL, LIST_RENDER_TIMEOUT_SECONDS, MAX_LIST_PAGES, ORDER_LIST_FIRST_PAGE_PATH, orderListPagePath } from '../settings.js';
import { PageChanged } from './page_changed.js';
import { SessionExpired } from './page_fetcher.js';
import { pageLastPageHint, pageOrderIds } from './page_functions.js';
import { isOutsideAccount } from './session_check.js';
import { NAVIGATION_TIMEOUT_MS, tabIo } from './work_tab.js';

const MODULE = 'order_list_scraper';
// Numărul scheletelor pe care eMAG le arată cât lista se încarcă (nouă zerouri): nu e o comandă reală.
const PLACEHOLDER_ORDER_ID = '0'.repeat(9);
// Pauza dintre două citiri ale listei randate: 700 ms ca în Python; pe contul real lista s-a stabilizat în ~1,6 s (probă 14.10.2026).
const STABLE_READ_INTERVAL_MS = 700;
const LOG_EVERY_PAGES = 10;

/** True dacă cele două liste au aceleași elemente în aceeași ordine. */
function sameList(a, b) {
  return a !== null && a.length === b.length && a.every((value, index) => value === b[index]);
}

/**
 * Numerele de comandă după ce lista s-a randat complet (stabil două citiri la rând, fără schelete); după LIST_RENDER_TIMEOUT_SECONDS întoarce ce a apucat să citească.
 * Oprirea cerută de om se verifică la fiecare citire (cel mult ~0,7 s întârziere).
 */
async function readRenderedIds(tabId, progress, io) {
  const deadline = io.now() + LIST_RENDER_TIMEOUT_SECONDS * 1000;
  let previous = null;
  for (;;) {
    progress.raiseIfCancelled();
    const ids = (await io.runInTab(tabId, pageOrderIds)) ?? [];
    const real = ids.filter((id) => id !== PLACEHOLDER_ORDER_ID);
    if (real.length > 0 && real.length === ids.length && sameList(previous, real)) return real;
    previous = real;
    if (io.now() > deadline) return real;
    await io.sleep(STABLE_READ_INTERVAL_MS);
  }
}

/** Deschide pagina `pageNo` din listă și întoarce comenzile ei; o redirecționare spre login sau spre altă gazdă înseamnă sesiune expirată. */
async function openListPage(tabId, pageNo, progress, io) {
  const path = pageNo === 1 ? ORDER_LIST_FIRST_PAGE_PATH : orderListPagePath(pageNo);
  const finalUrl = await io.navigate(tabId, BASE_URL + path, NAVIGATION_TIMEOUT_MS);
  if (isOutsideAccount(finalUrl)) throw new SessionExpired(`redirecționat la login la pagina ${pageNo} a listei de comenzi`);
  return readRenderedIds(tabId, progress, io);
}

/** Toate numerele de comandă din cont (sau primele `maxOrders`; null sau 0 = fără limită). */
export async function collectOrderIds(tabId, maxOrders, progress, log, io = tabIo) {
  const first = await openListPage(tabId, 1, progress, io);
  if (first.length === 0) throw new PageChanged('lista de comenzi', 'nicio comandă pe prima pagină a listei (sesiune expirată sau pagină schimbată?)');
  const allIds = [...first];
  const seen = new Set(first);
  let lastHint = Number(await io.runInTab(tabId, pageLastPageHint)) || 1;
  log.info(MODULE, `lista de comenzi: pagina 1 are ${first.length} comenzi, paginare până la ${lastHint}`);

  let pageNo = 2;
  while (pageNo <= MAX_LIST_PAGES) {
    if (maxOrders && allIds.length >= maxOrders) break;
    if (pageNo > lastHint && lastHint > 1) break; // paginarea e cunoscută și am parcurs-o: nu mai cerem pagini goale
    progress.raiseIfCancelled();
    progress.message(`Caut comenzile în cont: pagina ${pageNo}${lastHint > 1 ? ` din ${lastHint}` : ''}`);
    let ids = await openListPage(tabId, pageNo, progress, io);
    if (ids.length === 0 && pageNo <= lastHint) ids = await openListPage(tabId, pageNo, progress, io); // a doua încercare, pagina poate fi lentă
    if (ids.length === 0) {
      if (pageNo > lastHint) break; // paginare necunoscută: am sondat o pagină în plus și e goală
      throw new PageChanged('lista de comenzi', `pagina ${pageNo} din ${lastHint} a listei nu s-a încărcat`);
    }
    const fresh = ids.filter((id) => !seen.has(id));
    if (fresh.length === 0 && pageNo > lastHint) break;
    for (const orderId of fresh) {
      seen.add(orderId);
      allIds.push(orderId);
    }
    lastHint = Math.max(lastHint, Number(await io.runInTab(tabId, pageLastPageHint)) || 1);
    if (pageNo % LOG_EVERY_PAGES === 0) log.info(MODULE, `lista de comenzi: pagina ${pageNo}/${lastHint}, ${allIds.length} comenzi până acum`);
    pageNo += 1;
  }
  log.info(MODULE, `lista de comenzi: ${allIds.length} comenzi unice pe ${pageNo - 1} pagini`);
  return maxOrders ? allIds.slice(0, maxOrders) : allIds;
}
