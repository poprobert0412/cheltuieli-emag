// Paginile inventate pe care le servește eMAG-ul fals: aceleași pagini din fixtura de paritate (html.json) pe care Python le-a parsat (parsere.json), ca extensia să poată fi comparată cu el.
// Primește: fixturile html și parsere (tests/fixturi.js, generate de tests/paritate_export.py). Dă înapoi: paginile de comandă și de retur ale scenariului `din_pagini`, fiecare cu cheia ei (numărul comenzii, respectiv calea returului).
// Alegerea repetă filtrul generatorului (tests/paritate_export.py, `_analysis_fixture`): comenzile din paginile `comanda_*_inline` și retururile din paginile `retur_*_doua_linii`, parsate cu succes de Python.
// scenariu_python.js verifică apoi că alegerea dă exact aceleași comenzi ca scenariul din analiza.json; dacă generatorul își schimbă filtrul, testele pică acolo, nu în tăcere.
// Ce NU face: nu pornește niciun server și nu atinge rețeaua; nu știe de browser.
import { loadFixture } from '../fixturi.js';

// Numele paginilor alese de generator pentru scenariul `din_pagini`: o singură așezare a paginii de comandă (inline) și o singură variantă de retur (cu produsele pe două linii).
const ORDER_PAGE_NAME = /^comanda_.*_inline$/;
const RETURN_PAGE_NAME = /^retur_.*_doua_linii$/;

let cache = null;

/**
 * Paginile scenariului `din_pagini`: { orders, returns }, fiecare listă de { name, key, html } în ordinea din parsere.json.
 * `key` e numărul comenzii pentru comenzi și calea paginii de detalii pentru retururi, exact cum le-a dat Python. Citite o singură dată pe proces.
 */
export function loadPages() {
  if (cache !== null) return cache;
  const htmlByName = new Map(loadFixture('html').pagini.map((page) => [page.nume, page.html]));
  const cases = loadFixture('parsere').cazuri;
  const choose = (kind, namePattern) => cases
    .filter((fixtureCase) => fixtureCase.tip === kind && 'rezultat' in fixtureCase && namePattern.test(fixtureCase.nume))
    .map((fixtureCase) => {
      const html = htmlByName.get(fixtureCase.nume);
      if (html === undefined) throw new Error(`parsere.json citează pagina ${fixtureCase.nume}, dar html.json nu o are: regenerează fixturile (npm run paritate:genereaza)`);
      return { name: fixtureCase.nume, key: String(fixtureCase.id_sau_cale), html };
    });
  cache = { orders: choose('comanda', ORDER_PAGE_NAME), returns: choose('retur', RETURN_PAGE_NAME) };
  if (cache.orders.length === 0 || cache.returns.length === 0) {
    cache = null;
    throw new Error('fixtura de paritate nu are nicio pagină de comandă sau de retur după filtrul generatorului: regenerează fixturile sau actualizează filtrul din pagini_fixtura.js');
  }
  return cache;
}

/** Ultimul segment al unei căi („/user/return-history/1/3000123” devine „3000123”): numărul returului din adresa paginii lui. */
export function lastSegment(pathname) {
  return pathname.slice(pathname.lastIndexOf('/') + 1);
}
