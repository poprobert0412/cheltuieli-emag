// Teste unitare pentru extensie/src/colectare/page_functions.js: funcțiile pe care Chrome le trimite ca TEXT în fila eMAG (chrome.scripting.executeScript).
// Cea mai importantă verificare: fiecare funcție e AUTONOMĂ. O funcție injectată nu poate folosi nimic din afara ei (nici constante, nici alte funcții din fișier): se rulează aici din textul ei,
// într-un context gol (node:vm), în care o variabilă din modul ar da ReferenceError, exact ca în pagină. Apoi se verifică logica pe un DOM de mână și, la pageFetch, regula de siguranță:
// doar căi relative la originea filei, niciodată o adresă completă sau „//gazdă”. Selectorii sunt cei din programul Python (order_list_scraper.py, return_list_scraper.py).
// Ce NU face: nu pornește un browser; funcțiile pe pagini reale se probează în Edge (pasul de verificare separat).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import vm from 'node:vm';

import * as pageFunctions from '../../src/colectare/page_functions.js';

const ORDER_LINKS = 'a[href*="/history/shoppingdetails/"]';
const RETURN_LINKS = 'a[href*="/user/return-history/"]';
const RETURN_LINKS_ANY = "a[href*='/user/return-history/']";
const PAGINATION_LEAVES = '[class*="pagination"] *';
const LOAD_MORE = '.js-return-history-view-more';

/** Un nod de DOM de mână, cu doar ce citesc funcțiile (atribute, copii, text, cutie, clic). */
function node({ href = null, text = '', children = [], box = { width: 10, height: 10 } } = {}) {
  return {
    href,
    textContent: text,
    children,
    clicked: false,
    getAttribute: (name) => (name === 'href' ? href : null),
    getBoundingClientRect: () => box,
    click() { this.clicked = true; },
  };
}

/** Document de mână: selectorii se caută după textul exact (un selector neașteptat dă eroare, ca să se vadă dacă s-a schimbat). */
function fakeDocument({ selectors = {}, bodyText = '' } = {}) {
  const find = (selector) => {
    if (!(selector in selectors)) throw new Error(`selector neașteptat: ${selector}`);
    return selectors[selector];
  };
  return {
    body: { innerText: bodyText },
    querySelectorAll: (selector) => find(selector),
    querySelector: (selector) => find(selector)[0] ?? null,
  };
}

/**
 * Rulează `func` din textul ei într-un context gol, doar cu globalele date: ce nu e dat și nu e încorporat în limbaj dă ReferenceError (ca în pagină, unde funcția n-are modulul).
 * Întoarce rezultatul (așteptat dacă e promisiune), trecut prin JSON ca în Chrome.
 */
async function runAsInjected(func, args = [], globals = {}) {
  const sandbox = vm.createContext({ URL, AbortController, setTimeout, clearTimeout, ...globals });
  const injected = vm.runInContext(`(${func.toString()})`, sandbox);
  const result = await injected(...args);
  // Chrome întoarce rezultatul prin JSON; trecerea prin JSON dă și obiecte obișnuite (cele din contextul vm au alt prototip și nu se compară cu deepStrictEqual).
  return result === undefined ? undefined : JSON.parse(JSON.stringify(result));
}

const NAMES = Object.keys(pageFunctions);

describe('page_functions: fiecare funcție se poate trimite ca text (autonomă)', () => {
  test('modulul exportă exact funcțiile cunoscute, nimic în plus (o constantă exportată ar încuraja folosirea ei în funcții)', () => {
    assert.deepEqual(NAMES.sort(), [
      'pageClickLoadMore', 'pageFetch', 'pageHasReturnLinks', 'pageLastPageHint', 'pageLoadMoreState', 'pageLoginState', 'pageOrderIds', 'pageReturnPaths',
    ]);
  });

  test('textul fiecărei funcții rulează într-un context gol, fără ReferenceError', async () => {
    const document = fakeDocument({
      selectors: { [ORDER_LINKS]: [], [RETURN_LINKS]: [], [RETURN_LINKS_ANY]: [], [PAGINATION_LEAVES]: [], [LOAD_MORE]: [] },
    });
    const location = { href: 'https://www.emag.ro/history/shopping?time=older' };
    const getComputedStyle = () => ({ visibility: 'visible' });
    const fetch = async () => ({ status: 200, url: 'https://www.emag.ro/x', text: async () => 'ok' });
    for (const name of NAMES) {
      const args = name === 'pageFetch' ? ['/x', 1000] : [];
      await assert.doesNotReject(runAsInjected(pageFunctions[name], args, { document, location, getComputedStyle, fetch }), name);
    }
  });

  test('o funcție care ar folosi o variabilă din modul se vede imediat (capcana pe care o prinde testul de mai sus)', async () => {
    const MODULE_CONSTANT = 7;
    const leaky = () => MODULE_CONSTANT;
    await assert.rejects(runAsInjected(leaky), { name: 'ReferenceError', message: /MODULE_CONSTANT/ });
  });
});

describe('page_functions: citirea paginilor randate', () => {
  test('pageOrderIds: numerele din linkurile spre detalii, fără duplicate, în ordinea din pagină; scheletul 000000000 se întoarce (îl filtrează scraperul)', async () => {
    const document = fakeDocument({
      selectors: {
        [ORDER_LINKS]: [
          node({ href: '/history/shoppingdetails/100000002' }), node({ href: '/history/shoppingdetails/100000001?ref=x' }),
          node({ href: 'https://www.emag.ro/history/shoppingdetails/100000002' }), node({ href: '/history/shoppingdetails/000000000' }),
          node({ href: '/history/shoppingdetails/' }),
        ],
      },
    });
    assert.deepEqual(await runAsInjected(pageFunctions.pageOrderIds, [], { document }), ['100000002', '100000001', '000000000']);
  });

  test('pageLastPageHint: cel mai mare număr din frunzele paginării; 1 dacă nu e niciun număr', async () => {
    const leaves = [node({ text: ' 1 ' }), node({ text: '2' }), node({ text: '12' }), node({ text: 'Următoarea' }), node({ text: '' }), node({ text: '99', children: [node()] })];
    const withPagination = fakeDocument({ selectors: { [PAGINATION_LEAVES]: leaves } });
    assert.equal(await runAsInjected(pageFunctions.pageLastPageHint, [], { document: withPagination }), 12);
    const without = fakeDocument({ selectors: { [PAGINATION_LEAVES]: [node({ text: 'Înapoi' })] } });
    assert.equal(await runAsInjected(pageFunctions.pageLastPageHint, [], { document: without }), 1);
  });

  test('pageReturnPaths: doar căile de forma /user/return-history/<x>/<număr>, fără duplicate, din adrese relative sau complete', async () => {
    const location = { href: 'https://www.emag.ro/user/return-history' };
    const document = fakeDocument({
      selectors: {
        [RETURN_LINKS]: [
          node({ href: '/user/return-history/1/55' }), node({ href: 'https://www.emag.ro/user/return-history/2/77?x=1' }), node({ href: '/user/return-history/1/55' }),
          node({ href: '/user/return-history/new' }), node({ href: '/user/return-history/' }), node({ href: '/user/return-history/1/abc' }),
        ],
      },
    });
    assert.deepEqual(await runAsInjected(pageFunctions.pageReturnPaths, [], { document, location }), ['/user/return-history/1/55', '/user/return-history/2/77']);
  });

  test('pageHasReturnLinks: adevărat dacă există orice link spre un retur (așteptarea din Python: wait_for_selector)', async () => {
    const yes = fakeDocument({ selectors: { [RETURN_LINKS_ANY]: [node({ href: '/user/return-history/x' })] } });
    const no = fakeDocument({ selectors: { [RETURN_LINKS_ANY]: [] } });
    assert.equal(await runAsInjected(pageFunctions.pageHasReturnLinks, [], { document: yes }), true);
    assert.equal(await runAsInjected(pageFunctions.pageHasReturnLinks, [], { document: no }), false);
  });

  test('pageLoginState: logat doar cu „Comenzile mele” ȘI „Log out”; adresa de login se vede din adresa paginii', async () => {
    const run = (bodyText, href) => runAsInjected(pageFunctions.pageLoginState, [], { document: fakeDocument({ bodyText }), location: { href } });
    assert.deepEqual(await run('Contul meu\nComenzile mele\nLog out', 'https://www.emag.ro/history/shopping'), { logat: true, adresa_de_login: false });
    assert.deepEqual(await run('Comenzile mele', 'https://www.emag.ro/history/shopping'), { logat: false, adresa_de_login: false });
    assert.deepEqual(await run('Log out', 'https://www.emag.ro/x'), { logat: false, adresa_de_login: false });
    assert.deepEqual(await run('Autentificare', 'https://www.emag.ro/user/login?ref=1'), { logat: false, adresa_de_login: true });
  });

  test('pageLoginState nu dă eroare pe o pagină fără body (în timpul unei navigări)', async () => {
    const document = { body: null };
    assert.deepEqual(await runAsInjected(pageFunctions.pageLoginState, [], { document, location: { href: 'about:blank' } }), { logat: false, adresa_de_login: false });
  });
});

describe('page_functions: butonul „Vezi mai mult”', () => {
  const visible = () => ({ visibility: 'visible' });

  test('pageLoadMoreState: inexistent, ascuns (cutie goală sau visibility:hidden) sau vizibil, ca is_visible din Playwright', async () => {
    const state = (button, style = visible) => runAsInjected(pageFunctions.pageLoadMoreState, [], {
      document: fakeDocument({ selectors: { [LOAD_MORE]: button ? [button] : [] } }), getComputedStyle: style,
    });
    assert.deepEqual(await state(null), { exista: false, vizibil: false });
    assert.deepEqual(await state(node({ box: { width: 0, height: 0 } })), { exista: true, vizibil: false });
    assert.deepEqual(await state(node({ box: { width: 100, height: 0 } })), { exista: true, vizibil: false });
    assert.deepEqual(await state(node(), () => ({ visibility: 'hidden' })), { exista: true, vizibil: false });
    assert.deepEqual(await state(node()), { exista: true, vizibil: true });
  });

  test('pageClickLoadMore: apasă primul buton și spune dacă a existat unul', async () => {
    const button = node();
    assert.equal(await runAsInjected(pageFunctions.pageClickLoadMore, [], { document: fakeDocument({ selectors: { [LOAD_MORE]: [button] } }) }), true);
    assert.equal(button.clicked, true);
    assert.equal(await runAsInjected(pageFunctions.pageClickLoadMore, [], { document: fakeDocument({ selectors: { [LOAD_MORE]: [] } }) }), false);
  });
});

describe('pageFetch: singurul fetch al extensiei, doar pe căi relative la originea filei eMAG', () => {
  /** fetch de mână care notează apelurile; `reply` e răspunsul sau o funcție (url, options) -> promisiune. */
  function recorder(reply) {
    const calls = [];
    const fetch = (url, options) => {
      calls.push({ url, options });
      return typeof reply === 'function' ? reply(url, options) : Promise.resolve(reply);
    };
    return { fetch, calls };
  }

  test('refuză adresele complete, „//gazdă”, căile fără „/” la început și valorile care nu sunt text; fetch nu se cheamă deloc', async () => {
    for (const path of ['https://evil.invalid/x', 'http://www.emag.ro/x', '//evil.invalid/x', 'history/shoppingdetails/1', '', null, undefined, 42, {}]) {
      const { fetch, calls } = recorder({ status: 200, url: 'x', text: async () => '' });
      const result = await runAsInjected(pageFunctions.pageFetch, [path, 1000], { fetch });
      assert.deepEqual(result, { eroare: 'cale nepermisă' }, String(path));
      assert.equal(calls.length, 0, `fetch chemat pentru ${String(path)}`);
    }
  });

  test('o cale relativă se cere cu cookie-urile originii (same-origin), urmând redirecturile, cu semnal de anulare; 200 întoarce corpul', async () => {
    const { fetch, calls } = recorder({ status: 200, url: 'https://www.emag.ro/history/shoppingdetails/1', text: async () => '<html>pagina</html>' });
    const result = await runAsInjected(pageFunctions.pageFetch, ['/history/shoppingdetails/1', 30000], { fetch });
    assert.deepEqual(result, { status: 200, finalUrl: 'https://www.emag.ro/history/shoppingdetails/1', html: '<html>pagina</html>' });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/history/shoppingdetails/1');
    assert.equal(calls[0].options.credentials, 'same-origin');
    assert.equal(calls[0].options.redirect, 'follow');
    assert.ok(calls[0].options.signal && typeof calls[0].options.signal.aborted === 'boolean');
  });

  test('un status diferit de 200 întoarce statusul fără corp (nu se citește o pagină de eroare)', async () => {
    let bodyRead = false;
    const { fetch } = recorder({ status: 503, url: 'https://www.emag.ro/x', text: async () => { bodyRead = true; return 'eroare'; } });
    assert.deepEqual(await runAsInjected(pageFunctions.pageFetch, ['/x', 1000], { fetch }), { status: 503, finalUrl: 'https://www.emag.ro/x', html: '' });
    assert.equal(bodyRead, false);
  });

  test('adresa finală arată unde s-a ajuns după redirecturi (login = sesiune expirată)', async () => {
    const { fetch } = recorder({ status: 200, url: 'https://www.emag.ro/user/login?ref=x', text: async () => 'login' });
    const result = await runAsInjected(pageFunctions.pageFetch, ['/history/shoppingdetails/1', 1000], { fetch });
    assert.equal(result.finalUrl, 'https://www.emag.ro/user/login?ref=x');
  });

  test('căderea rețelei se întoarce ca date ({ eroare }), nu ca excepție (o excepție în pagină ar da rezultat null)', async () => {
    const { fetch } = recorder(() => Promise.reject(new TypeError('Failed to fetch')));
    assert.deepEqual(await runAsInjected(pageFunctions.pageFetch, ['/x', 1000], { fetch }), { eroare: 'Failed to fetch' });
  });

  test('termenul depășit anulează cererea și întoarce „timeout”; cronometrul se oprește oricum', async () => {
    const cleared = [];
    const { fetch } = recorder((url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(Object.assign(new Error('The operation was aborted'), { name: 'AbortError' })));
    }));
    const trackedClear = (timer) => { cleared.push(timer); clearTimeout(timer); };
    assert.deepEqual(await runAsInjected(pageFunctions.pageFetch, ['/x', 20], { fetch, clearTimeout: trackedClear }), { eroare: 'timeout' });
    assert.equal(cleared.length, 1);
  });

  test('cronometrul de termen se oprește și după un răspuns reușit (nu rămâne nimic agățat în pagină)', async () => {
    const cleared = [];
    const { fetch } = recorder({ status: 200, url: 'https://www.emag.ro/x', text: async () => 'ok' });
    await runAsInjected(pageFunctions.pageFetch, ['/x', 60000], { fetch, clearTimeout: (timer) => { cleared.push(timer); clearTimeout(timer); } });
    assert.equal(cleared.length, 1);
  });
});
