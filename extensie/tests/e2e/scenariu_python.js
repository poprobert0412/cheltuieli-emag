// Scenariul `din_pagini` al fixturii analiza.json: ce pagini servește eMAG-ul fals și ce a dat programul Python pe ele (comenzile și retururile parsate, rezumatul, cele patru fișiere de export).
// Primește: fixturile analiza, html și parsere (tests/fixturi.js). Dă înapoi: opțiunile pentru eMAG-ul fals (numerele comenzilor, căile retururilor, paginile lor) și ieșirile Python de comparat.
// Verifică singur că alegerea paginilor (pagini_fixtura.js) dă exact comenzile și retururile din scenariu, în aceeași ordine: o nepotrivire înseamnă că generatorul și testul s-au desincronizat și oprește testul, nu îl lasă să compare altceva.
// Ce NU face: nu compară nimic cu extensia (asta face analiza.test.js) și nu pornește browserul.
import assert from 'node:assert/strict';

import { loadFixture } from '../fixturi.js';
import { loadPages } from './pagini_fixtura.js';

const SCENARIO_NAME = 'din_pagini';
// Ce primește extensia dacă cere o pagină care nu e în scenariu: o pagină obișnuită, fără „Comanda nr.” (testul pică oricum, dar cu un mesaj despre cererea în plus).
const MISSING_PAGE_HTML = '<html><body><p>pagină inexistentă în scenariu</p></body></html>';

/**
 * Scenariul `din_pagini`: { expected, fakeOptions }. `expected` e intrarea din analiza.json (comenzi, retururi, rezumat, linii_csv, istoric_csv, comenzi_json, retururi_json, prag_bani...);
 * `fakeOptions` se dă lui createFakeEmag. Aruncă o eroare cu instrucțiunea de reparare dacă fixturile nu se potrivesc între ele.
 */
export function loadPythonScenario() {
  const expected = loadFixture('analiza').scenarii.find((scenario) => scenario.nume === SCENARIO_NAME);
  assert.ok(expected, `analiza.json nu are scenariul ${SCENARIO_NAME}: regenerează fixturile (npm run paritate:genereaza)`);
  const pages = loadPages();
  const orderIds = expected.comenzi.map((order) => String(order.order_id));
  const returnPaths = expected.retururi.map((item) => item.detail_path);
  assert.deepEqual(pages.orders.map((page) => page.key), orderIds, 'comenzile paginilor alese nu sunt cele din scenariul Python: generatorul și pagini_fixtura.js s-au desincronizat');
  assert.deepEqual(pages.returns.map((page) => page.key), returnPaths, 'retururile paginilor alese nu sunt cele din scenariul Python: generatorul și pagini_fixtura.js s-au desincronizat');
  const orderHtml = new Map(pages.orders.map((page) => [page.key, page.html]));
  const returnHtml = new Map(pages.returns.map((page) => [page.key, page.html]));
  return {
    expected,
    fakeOptions: {
      orderIds,
      returnPaths,
      orderHtml: (orderId) => orderHtml.get(orderId) ?? MISSING_PAGE_HTML,
      returnHtml: (pathname) => returnHtml.get(pathname) ?? MISSING_PAGE_HTML,
    },
  };
}
