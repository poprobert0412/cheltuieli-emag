// eMAG-ul fals al testelor cap-coadă: răspunde la cererile browserului de test spre https://www.emag.ro/** (servite prin context.route) și nu iese niciodată în rețeaua reală.
// Primește: opțiuni (câte comenzi și retururi, întârzieri, starea de login, pagini exacte din fixturi, comenzi cu probleme, expirarea sesiunii). Dă înapoi: { state, handle }; `handle(route)` se dă lui context.route.
// Imită ce citește extensia: o listă de comenzi randată de JavaScript (întâi 3 schelete, apoi comenzile reale, cu paginare), paginile de detalii (pagini adevărate din fixturile de paritate, ca parserele reale să le poată citi),
// lista de retururi cu „Vezi mai mult” și starea „nelogat” (aceeași adresă, fără „Comenzile mele” și „Log out”). Nu folosește redirecționări: Playwright nu intercepta urmarea lor (probat 13.10.2026), iar o redirecționare ar pleca în rețeaua reală.
// Sesiunea expirată se imită cum o vede extensia: pagina își schimbă singură adresa într-una de login (history.replaceState), deci fila ajunge pe o adresă de login fără nicio redirecționare.
// Ce NU face: nu verifică nimic (testele citesc `state`), nu ține cookie-uri și nu răspunde la nimic în afara gazdei www.emag.ro (orice altă gazdă e oprită și notată).
import { lastSegment, loadPages } from './pagini_fixtura.js';

export const FAKE_HOST = 'www.emag.ro';
// Numărul pe care îl arată eMAG în locul unei comenzi cât lista se încarcă (nouă zerouri): extensia îl ignoră și așteaptă comenzile reale.
const SKELETON_ORDER_ID = '000000000';
const SKELETON_COUNT = 3;
// Numerele comenzilor generice (inventate, nelegate de fixturi): scad de la cea mai nouă la cea mai veche, ca în lista reală (cele mai noi primele).
const FIRST_FAKE_ORDER_ID = 100_000_000;
// Numărul primului retur generic din lista de retururi (inventat) și folderul din adresa lui, cum arată adresele reale.
const FIRST_FAKE_RETURN_NUMBER = 5000;
const RETURN_PATH_PREFIX = '/user/return-history/1/';
// Valorile implicite: un cont mic, cu 3 pagini de listă, ca analiza să dureze câteva secunde.
const DEFAULT_ORDERS = 25;
// Cel puțin atâtea pagini de listă are orice cont fals (vezi verificarea din createFakeEmag).
const MIN_LIST_PAGES = 2;
const DEFAULT_PAGE_SIZE = 10;
const DEFAULT_RETURNS = 12;
const DEFAULT_RETURN_PAGE_SIZE = 10;
const DEFAULT_LIST_DELAY_MS = 350;
const DEFAULT_DETAIL_DELAY_MS = 40;
const DEFAULT_RETURN_GROW_DELAY_MS = 300;
// Protocoalele locale ale browserului (pagina extensiei, date, blob): nu sunt cereri spre vreo gazdă, deci trec mai departe.
const LOCAL_PROTOCOLS = new Set(['chrome-extension:', 'data:', 'blob:', 'about:']);
// Mesajul prin care Playwright spune că fila sau browserul s-au închis cât răspundeam: la sfârșitul unui test e normal și nu e o eroare a eMAG-ului fals.
const CLOSED_PATTERN = /closed|disposed|Target page|Request is already handled|has been aborted/i;
const LOGGED_IN_NAV = '<nav><a href="/user/contul-meu">Contul meu</a> <a href="/history/shopping">Comenzile mele</a> <a href="/user/logout">Log out</a></nav>';
const LOGGED_OUT_NAV = '<nav><a href="/user/login">Autentificare</a></nav>';
// Adresa de login la care ajunge fila când sesiunea „expiră”.
const LOGIN_ADDRESS = '/user/login?next=%2Fhistory%2Fshopping';

/** Numărul comenzii generice cu indicele `index` (de la 0, cea mai nouă prima) într-un cont cu `orderCount` comenzi: testele îl folosesc ca să țintească o comandă anume. */
export function genericOrderId(index, orderCount) {
  return String(FIRST_FAKE_ORDER_ID + (orderCount - index));
}

/** Pagină HTML completă cu `body` între etichetele <body>. */
function documentWith(title, body) {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title></head><body>${body}</body></html>`;
}

/** Script care schimbă adresa paginii într-una de login, ca fila să ajungă pe login fără redirecționare. */
function expireSessionScript() {
  return `<script>history.replaceState(null, '', ${JSON.stringify(LOGIN_ADDRESS)});</script>`;
}

/**
 * Creează eMAG-ul fals. Opțiuni: `orders`, `pageSize`, `returns`, `returnPageSize` (cât de mare e contul), `loggedIn`, `listDelayMs`, `detailDelayMs`, `returnGrowDelayMs` (cât durează randările și răspunsurile),
 * `failDetail` (numere de comenzi al căror detaliu dă HTTP 500), `noOrderMarker` (numere de comenzi al căror detaliu nu mai are „Comanda nr.”), `expireListAtPage` (pagina listei la care fila ajunge pe login),
 * `expireReturnList` (lista de retururi ajunge pe login), `orderIds` + `orderHtml` și `returnPaths` + `returnHtml` (exact paginile dorite, ca în scenariul Python).
 * `state.loggedIn` se poate schimba în timpul testului (omul „se loghează”). Notează fiecare cerere în `state.requests` și orice cerere spre altă gazdă în `state.foreign`.
 */
export function createFakeEmag({
  orders = DEFAULT_ORDERS, pageSize = DEFAULT_PAGE_SIZE, returns = DEFAULT_RETURNS, returnPageSize = DEFAULT_RETURN_PAGE_SIZE, loggedIn = true,
  listDelayMs = DEFAULT_LIST_DELAY_MS, detailDelayMs = DEFAULT_DETAIL_DELAY_MS, returnGrowDelayMs = DEFAULT_RETURN_GROW_DELAY_MS,
  failDetail = new Set(), noOrderMarker = new Set(), expireListAtPage = null, expireReturnList = false,
  orderIds = null, orderHtml = null, returnPaths = null, returnHtml = null,
} = {}) {
  const orderCount = orderIds ? orderIds.length : orders;
  const returnCount = returnPaths ? returnPaths.length : returns;
  const pageCount = Math.ceil(orderCount / pageSize);
  // La o singură pagină de listă paginarea nu se vede, iar extensia sondează pagina 2 și așteaptă LIST_RENDER_TIMEOUT_SECONDS (25 s) să se încarce ceva: un test cu așa un cont ar sta jumătate de minut degeaba.
  if (pageCount < MIN_LIST_PAGES) throw new Error(`eMAG-ul fals: contul are ${pageCount} pagini de listă (${orderCount} comenzi, ${pageSize} pe pagină); trebuie cel puțin ${MIN_LIST_PAGES}, altfel extensia așteaptă degeaba la pagina 2`);
  const state = {
    loggedIn,
    requests: [], // { method, path } pentru fiecare cerere spre www.emag.ro
    foreign: [], // „METODĂ adresă” pentru orice cerere spre altă gazdă sau fără https
    unknown: [], // căile pe care eMAG-ul fals nu le știe (altele decât favicon)
    handlerErrors: [], // erori neașteptate din eMAG-ul fals (nu cele de după închiderea browserului)
    detailInFlight: 0,
    maxDetailInFlight: 0,
    detailCount: 0,
    returnDetailCount: 0,
    listPagesServed: [],
    orders: orderCount,
    returns: returnCount,
  };
  const { orders: orderPages, returns: returnPagesFromFixture } = loadPages();
  const [orderTemplate] = orderPages;
  const [returnTemplate] = returnPagesFromFixture;
  const orderIdAt = (index) => (orderIds ? String(orderIds[index]) : genericOrderId(index, orderCount));
  const returnPathAt = (index) => (returnPaths ? returnPaths[index] : `${RETURN_PATH_PREFIX}${FIRST_FAKE_RETURN_NUMBER + index + 1}`);
  const orderPage = orderHtml ?? ((orderId) => orderTemplate.html.replaceAll(orderTemplate.key, orderId));
  const returnPage = returnHtml ?? ((pathname) => returnTemplate.html.replaceAll(lastSegment(returnTemplate.key), lastSegment(pathname)));

  /** Antetul de cont: cu „Comenzile mele” și „Log out” când omul e logat, altfel doar linkul de autentificare. */
  function nav() {
    return state.loggedIn ? LOGGED_IN_NAV : LOGGED_OUT_NAV;
  }

  /** Pagina `number` din lista de comenzi: schelete la început, comenzile reale după `listDelayMs`; nelogat, o pagină de autentificare care se întreabă singură dacă omul s-a logat. */
  function listPage(number) {
    const from = (number - 1) * pageSize;
    const ids = Array.from({ length: Math.max(0, Math.min(pageSize, orderCount - from)) }, (_, offset) => orderIdAt(from + offset));
    const skeletons = Array.from({ length: SKELETON_COUNT }, () => `<a href="/history/shoppingdetails/${SKELETON_ORDER_ID}">comanda</a>`).join('');
    const real = ids.map((id) => `<a href="/history/shoppingdetails/${id}">Comanda ${id}</a>`).join('');
    const pagination = `<div class="pagination">${Array.from({ length: pageCount }, (_, index) => `<span>${index + 1}</span>`).join('')}</div>`;
    const expire = expireListAtPage === number ? expireSessionScript() : '';
    if (state.loggedIn) {
      return documentWith('Comenzile mele', `${expire}${nav()}<h1>Comenzile mele</h1><div id="lista">${skeletons}</div>${pagination}`
        + `<script>setTimeout(function () { document.getElementById('lista').innerHTML = ${JSON.stringify(real)}; }, ${listDelayMs});</script>`);
    }
    const loggedInBody = `${LOGGED_IN_NAV}<h1>Comenzile mele</h1><div id="lista">${real}</div>${pagination}`;
    return documentWith('Autentificare', `${LOGGED_OUT_NAV}<h1>Autentificare</h1><p>Scrie datele contului ca să continui.</p>`
      + `<script>(function poll() { fetch('/api/logat').then(function (r) { return r.json(); }).then(function (j) {`
      + ` if (j.logat) { document.body.innerHTML = ${JSON.stringify(loggedInBody)}; } else { setTimeout(poll, 300); } }); })();</script>`);
  }

  /** Lista de retururi: primele `returnPageSize` legături, apoi „Vezi mai mult” care adaugă restul după `returnGrowDelayMs` și dispare. */
  function returnsPage() {
    const link = (index) => `<a href="${returnPathAt(index)}">Retur ${index + 1}</a>`;
    const first = Array.from({ length: Math.min(returnPageSize, returnCount) }, (_, index) => link(index)).join('');
    const rest = Array.from({ length: Math.max(0, returnCount - returnPageSize) }, (_, index) => link(returnPageSize + index)).join('');
    const hasMore = returnCount > returnPageSize;
    const button = hasMore ? '<button class="js-return-history-view-more" type="button">Vezi mai mult</button>' : '';
    const script = hasMore
      ? `<script>document.querySelector('.js-return-history-view-more').addEventListener('click', function () { var b = this; setTimeout(function () {`
        + ` document.getElementById('retururi').insertAdjacentHTML('beforeend', ${JSON.stringify(rest)}); b.remove(); }, ${returnGrowDelayMs}); });</script>`
      : '';
    const expire = expireReturnList ? expireSessionScript() : '';
    const content = state.loggedIn ? `${expire}${nav()}<h1>Retururi</h1><div id="retururi">${first}</div>${button}${script}` : '<h1>Autentificare</h1>';
    return documentWith('Retururi', content);
  }

  /** Răspunde la o cerere deja acceptată pentru gazda www.emag.ro. */
  async function respond(route, url, request) {
    const html = (body, status = 200) => route.fulfill({ status, contentType: 'text/html; charset=utf-8', headers: { 'cache-control': 'no-store' }, body });
    const { pathname } = url;
    if (pathname === '/favicon.ico') return route.fulfill({ status: 204 });
    if (pathname === '/api/logat') {
      return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'cache-control': 'no-store' }, body: JSON.stringify({ logat: state.loggedIn }) });
    }
    if (pathname === '/history/shopping') {
      state.listPagesServed.push(1);
      return html(listPage(1));
    }
    const list = /^\/history\/shopping\/(\d+)$/.exec(pathname);
    if (list) {
      state.listPagesServed.push(Number(list[1]));
      return html(listPage(Number(list[1])));
    }
    const detail = /^\/history\/shoppingdetails\/(\d+)$/.exec(pathname);
    if (detail) {
      state.detailInFlight += 1;
      state.maxDetailInFlight = Math.max(state.maxDetailInFlight, state.detailInFlight);
      await new Promise((resolve) => { setTimeout(resolve, detailDelayMs); });
      state.detailInFlight -= 1;
      state.detailCount += 1;
      if (failDetail.has(detail[1])) return html('<html><body>Eroare</body></html>', 500);
      if (noOrderMarker.has(detail[1])) return html('<html><body><p>Pagina s-a schimbat</p></body></html>');
      return html(orderPage(detail[1]));
    }
    if (pathname === '/user/return-history') return html(returnsPage());
    if (/^\/user\/return-history\/\d+\/\d+$/.test(pathname)) {
      state.returnDetailCount += 1;
      return html(returnPage(pathname));
    }
    state.unknown.push(`${request.method()} ${pathname}${url.search}`);
    return html('<html><body>nu există</body></html>', 404);
  }

  /** Se dă lui context.route pentru toate adresele: www.emag.ro primește răspunsurile de mai sus, orice altă gazdă este oprită și notată. */
  async function handle(route) {
    const request = route.request();
    try {
      const url = new URL(request.url());
      if (LOCAL_PROTOCOLS.has(url.protocol)) {
        await route.continue();
        return;
      }
      if (url.hostname !== FAKE_HOST || url.protocol !== 'https:') {
        state.foreign.push(`${request.method()} ${request.url()}`);
        await route.abort('blockedbyclient');
        return;
      }
      state.requests.push({ method: request.method(), path: `${url.pathname}${url.search}` });
      await respond(route, url, request);
    } catch (error) {
      if (!CLOSED_PATTERN.test(String(error?.message ?? error))) state.handlerErrors.push(String(error?.stack ?? error));
    }
  }

  return { state, handle, orderIdAt };
}
