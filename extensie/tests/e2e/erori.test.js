// Erorile analizei cap-coadă: o pagină care nu mai arată cum se așteaptă extensia, rețeaua care cade după toate încercările și sesiunea care expiră în timpul citirii listelor.
// Pentru fiecare, eMAG-ul fals se poartă greșit într-un singur loc (un detaliu fără „Comanda nr.”, un detaliu care dă HTTP 500, o listă la care fila ajunge pe o adresă de login), iar testul cere ecranul de eroare cu mesajul pe care îl dă
// colectare/run_errors.js pentru acel cod, jurnalul rulării căzute salvat, fila de lucru închisă, lacătul liber și nicio analiză salvată. O redirecționare adevărată nu poate fi servită de eMAG-ul fals (Playwright nu o interceptează),
// deci sesiunea expirată se imită ca pagina să-și schimbe singură adresa într-una de login; același efect pentru colector (redirecturile propriu-zise se testează unitar, pe o filă falsă).
// Ce NU face: nu testează fila închisă de om (oprire.test.js) și nu verifică textele de eroare în sine (le verifică testele unitare ale lui run_errors.js).
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  CODE_NETWORK, CODE_PAGE_CHANGED, CODE_SESSION_EXPIRED, classifyError,
} from '../../src/colectare/run_errors.js';
import { FETCH_RETRIES } from '../../src/settings.js';
import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import { RUN_LOG_KEY } from '../../src/stocare/run_log.js';
import { genericOrderId } from './emag_fals.js';
import { SCREEN_TIMEOUT_MS, RUN_TIMEOUT_MS, scenario } from './harness.js';

// Contul fals al scenariilor: destule comenzi cât problema să apară la mijloc, nu la început.
const ORDERS = 15;
// Indicele comenzii care se poartă greșit (a șasea din listă).
const BROKEN_ORDER_INDEX = 5;
const BROKEN_ORDER_ID = genericOrderId(BROKEN_ORDER_INDEX, ORDERS);
// Lista de comenzi pe 3 pagini, iar sesiunea „expiră” când extensia deschide a doua.
const SESSION_EXPIRES_AT_PAGE = 2;

/**
 * Ce trebuie să se vadă după o rulare căzută: ecranul de eroare cu mesajul cerut (egal cu `message`, sau care începe cu `messageStart`), jurnalul rulării căzute cu `logPattern`,
 * fila de lucru închisă, lacătul liber, nicio analiză salvată și butonul „Descarcă jurnalul”. Întoarce pagina, pentru verificări în plus.
 */
async function expectFailedRun(session, page, { message, messageStart, logPattern, timeoutMs = RUN_TIMEOUT_MS }) {
  await session.screen(page, 'error', timeoutMs);
  const shown = await page.textContent('#error-message');
  if (message !== undefined) assert.equal(shown, message, 'mesajul de pe ecranul de eroare');
  if (messageStart !== undefined) assert.ok(shown.startsWith(messageStart) && shown.includes('Ce faci:'), `mesajul de pe ecranul de eroare: ${shown}`);
  const stored = await session.decodedStorage(page);
  assert.match(stored[RUN_LOG_KEY]?.text ?? '', logPattern, 'jurnalul rulării căzute e salvat');
  assert.ok(!(LAST_ANALYSIS_KEY in stored), 'nu s-a salvat nicio analiză');
  assert.equal((await session.workTabs(page)).length, 0, 'fila de lucru s-a închis');
  assert.deepEqual(await session.heldLocks(page), [], 'lacătul e liber');
  assert.ok(await page.isVisible('#screen-error [data-action="download-log"]'), '„Descarcă jurnalul” e vizibil');
}

scenario('pagină schimbată: un detaliu de comandă fără „Comanda nr.”', { orders: ORDERS, noOrderMarker: new Set([BROKEN_ORDER_ID]) }, (ctx) => {
  test('analiza se oprește cu eroarea „pagina nu arată cum se așteaptă extensia”', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await expectFailedRun(s, page, {
      messageStart: classifyError({ code: CODE_PAGE_CHANGED }).message.split(';')[0],
      logPattern: /rularea a eșuat \(page_changed\)/,
    });
  });
});

scenario('rețea: un detaliu de comandă dă HTTP 500 la toate încercările', { orders: ORDERS, failDetail: new Set([BROKEN_ORDER_ID]) }, (ctx) => {
  test('analiza se oprește cu eroarea de rețea, după încercările din setări, cu motivul în mesaj', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await expectFailedRun(s, page, {
      message: classifyError({ code: CODE_NETWORK, reason: 'HTTP 500' }).message,
      logPattern: /rularea a eșuat \(network\)/,
    });
    const log = (await s.decodedStorage(page))[RUN_LOG_KEY].text;
    assert.equal((log.match(new RegExp(`încercarea \\d/${FETCH_RETRIES} a eșuat \\(HTTP 500\\)`, 'g')) ?? []).length, FETCH_RETRIES, `jurnalul are cele ${FETCH_RETRIES} încercări eșuate`);
    const requests = s.fake.state.requests.filter((request) => request.path === `/history/shoppingdetails/${BROKEN_ORDER_ID}`);
    assert.equal(requests.length, FETCH_RETRIES, `pagina a fost cerută de ${FETCH_RETRIES} ori, nu mai mult`);
    // Chrome scrie în consola paginii orice răspuns HTTP de eroare, deci și pe cel provocat aici; nu e o problemă a extensiei și se scoate din listă (orice altă eroare rămâne și pică ultimul test).
    s.consumeIssues(/Failed to load resource: the server responded with a status of 500/);
  });
});

scenario('sesiune expirată: fila ajunge pe login la a doua pagină a listei de comenzi', { orders: 25, pageSize: 10, expireListAtPage: SESSION_EXPIRES_AT_PAGE }, (ctx) => {
  test('analiza se oprește cu „sesiunea eMAG a expirat”, iar jurnalul spune la ce pagină', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await expectFailedRun(s, page, {
      message: classifyError({ code: CODE_SESSION_EXPIRED }).message,
      logPattern: new RegExp(`rularea a eșuat \\(session_expired\\): redirecționat la login la pagina ${SESSION_EXPIRES_AT_PAGE} a listei de comenzi`),
      timeoutMs: SCREEN_TIMEOUT_MS,
    });
  });
});

scenario('sesiune expirată: fila ajunge pe login la lista de retururi', { orders: 4, pageSize: 2, returns: 3, expireReturnList: true }, (ctx) => {
  test('comenzile se citesc, apoi analiza se oprește cu „sesiunea eMAG a expirat” la retururi', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await expectFailedRun(s, page, {
      message: classifyError({ code: CODE_SESSION_EXPIRED }).message,
      logPattern: /rularea a eșuat \(session_expired\): redirecționat la login la lista de retururi/,
    });
    assert.equal(s.fake.state.detailCount, 4, 'comenzile fuseseră citite înainte să expire sesiunea');
    assert.equal(s.fake.state.returnDetailCount, 0, 'niciun retur nu a mai fost cerut');
  });
});
