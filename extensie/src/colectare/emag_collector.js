// Colectează comenzile și retururile din contul eMAG, prin fila de lucru (portul lui emag_spend/emag_collector.py; partea cu browserul).
// Primește: o limită opțională de comenzi (teste rapide), raportorul de progres, jurnalul, apeluri pentru ecrane (`onNeedLogin`, `onWorkTab`) și, în teste, parsere și o filă false.
// Dă înapoi: { orders, returns } deja parsate. Orchestrează work_tab, session_check, order_list_scraper, return_list_scraper și page_fetcher; nu calculează nimic și nu salvează nimic.
// Parserele (html_lines, order_parser, return_parser) se încarcă abia aici, cu import dinamic cu cale literală: pagina pornește fără ele și le aduce la „Pornește analiza”; o pagină pe care parserul o refuză devine PageChanged.
// Fila de lucru se închide ÎNTOTDEAUNA la final (și la eroare sau oprire): nu rămâne nicio filă eMAG deschisă de extensie.
import { orderDetailPath } from '../settings.js';
import { PageChanged } from './page_changed.js';
import { collectOrderIds } from './order_list_scraper.js';
import { fetchEach } from './page_fetcher.js';
import { NO_LOG, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS } from './progress.js';
import { collectReturnPaths } from './return_list_scraper.js';
import { ensureLoggedIn } from './session_check.js';
import { tabIo } from './work_tab.js';

export { PageChanged };

const MODULE = 'emag_collector';

/** Primul rând al unui mesaj de eroare, pentru motivul din PageChanged (restul, ca „Call log”, n-are ce căuta pe ecran). */
function firstLine(error) {
  return String(error?.message ?? error).trim().split(/\r?\n/)[0] || String(error?.name ?? 'eroare');
}

/** Învelește un parser: orice eroare a lui devine PageChanged cu calea paginii (parserele aruncă ValueError când lipsește „Comanda nr.” sau „Retur #”). */
function guarded(parse) {
  return (path, html) => {
    try {
      return parse(path, html);
    } catch (error) {
      throw new PageChanged(path, firstLine(error));
    }
  };
}

/** Parserele reale, încărcate la prima folosire: numărul comenzii e ultimul segment din cale, ca în _parse_order_page din Python. */
async function loadParsers() {
  const [{ htmlToLines, extractProductNames }, { parseOrder }, { parseReturn }] = await Promise.all([
    import('../calcul/html_lines.js'),
    import('../calcul/order_parser.js'),
    import('../calcul/return_parser.js'),
  ]);
  return {
    parseOrderPage: (path, html) => parseOrder(path.slice(path.lastIndexOf('/') + 1), htmlToLines(html), extractProductNames(html)),
    parseReturnPage: (path, html) => parseReturn(path, htmlToLines(html)),
  };
}

/**
 * Deschide fila de lucru, așteaptă login-ul și citește toate comenzile și retururile.
 * `onNeedLogin` se cheamă o dată când omul trebuie să se logheze; `onWorkTab(id)` anunță fila de lucru imediat ce există (ecranele și lacătul o rețin);
 * `openerTabId` așază fila lângă cea a aplicației; `parsers` și `io` sunt pentru teste.
 */
export async function collectAll({
  maxOrders = null, progress, log = NO_LOG, onNeedLogin = () => {}, onWorkTab = () => {}, openerTabId, parsers = null, io = tabIo,
}) {
  const readers = parsers ?? await loadParsers();
  const parseOrderPage = guarded(readers.parseOrderPage);
  const parseReturnPage = guarded(readers.parseReturnPage);
  let tabId = null;
  try {
    tabId = await io.openWorkTab(openerTabId === undefined ? undefined : { openerTabId });
    onWorkTab(tabId);
    log.info(MODULE, 'fila de lucru eMAG deschisă');
    await ensureLoggedIn(tabId, progress, { onNeedLogin, log }, io);

    progress.phase(PHASE_FETCHING_ORDERS);
    const orderIds = await collectOrderIds(tabId, maxOrders, progress, log, io);
    const orderPaths = orderIds.map((orderId) => orderDetailPath(orderId));
    progress.message('Citesc detaliile fiecărei comenzi.');
    const orders = await fetchEach(tabId, orderPaths, parseOrderPage, 'comenzi', progress, log, io);

    progress.phase(PHASE_FETCHING_RETURNS);
    const returnPaths = await collectReturnPaths(tabId, progress, log, io);
    progress.message('Citesc detaliile fiecărui retur.');
    const returns = await fetchEach(tabId, returnPaths, parseReturnPage, 'retururi', progress, log, io);
    return { orders, returns };
  } finally {
    if (tabId !== null) {
      try {
        await io.closeTab(tabId);
        log.info(MODULE, 'fila de lucru eMAG închisă');
      } catch (error) {
        log.warning(MODULE, `fila de lucru nu s-a putut închide: ${firstLine(error)}`);
      }
    }
  }
}
