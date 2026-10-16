// Analiza completă cap-coadă, în browser, pe un eMAG fals: întâi pe un cont generic (fluxul și fișierele), apoi pe paginile scenariului `din_pagini`, cu rezultatele comparate cu cele ale programului Python.
// „Pornește analiza” deschide o filă eMAG de lucru în fundal, citește lista de comenzi (paginată, randată cu întârziere), cere câte 3 detalii deodată, citește retururile prin „Vezi mai mult”, calculează, salvează și desenează raportul; la final fila de lucru se închide.
// Scenariul Python cere egalitate exactă: comenzile și retururile citite, rezumatul întreg (la valoare), numărul de linii, plătitul efectiv și cele patru fișiere de export (produse.csv, istoric_preturi.csv, comenzi.json, retururi.json) la octet cu cele scrise de Python.
// Ce NU face: nu testează erori, oprire sau login (celelalte fișiere *.test.js) și nu are conturi reale (paginile sunt inventate de tests/html_builders.py și de tests/paritate_export.py).
import assert from 'node:assert/strict';
import { isDeepStrictEqual } from 'node:util';
import { test } from 'node:test';

import { FETCH_CONCURRENCY } from '../../src/settings.js';
import { ENTRY_SCHEMA, LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import { RUN_LOG_KEY } from '../../src/stocare/run_log.js';
import { differences, firstTextDifference, normalize } from './comparatii.js';
import {
  RUN_TIMEOUT_MS, WORKING_SCREEN_TIMEOUT_MS, downloadFrom, scenario, waitFor,
} from './harness.js';
import { loadPythonScenario } from './scenariu_python.js';

// Dimensiunea contului generic: 25 de comenzi pe 3 pagini de câte 10 și 12 retururi, dintre care 2 apar abia după „Vezi mai mult”.
const GENERIC_ORDERS = 25;
const GENERIC_PAGE_SIZE = 10;
const GENERIC_RETURNS = 12;
const GENERIC_LIST_PAGES = Math.ceil(GENERIC_ORDERS / GENERIC_PAGE_SIZE);
// Fișierele descărcabile ale unei analize reale, în ordinea butoanelor.
const REAL_DOWNLOADS = ['produse.csv', 'istoric_preturi.csv', 'comenzi.json', 'retururi.json', 'jurnal.txt', 'raport.html', 'analiza.json'];
const BOM = Buffer.from([0xef, 0xbb, 0xbf]);
const REPORT_DATA_BLOCK = /<script id="date-analiza" type="application\/json">([\s\S]*?)<\/script>/;
const REPORT_PLACEHOLDER = /\/\*__[A-Z_]+__\*\//;
const MIN_REPORT_ELEMENTS = 50;
// Un rând de jurnal în formatul din Python: ora cu milisecunde, [modulul], nivelul.
const LOG_LINE = /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \[[a-z_]+\] (?:INFO|WARNING|ERROR): /m;
// Întârzierile eMAG-ului fals la scenariul Python: mici, ca cele 32 de comenzi și 17 retururi să se termine repede.
const PYTHON_FAKE_DELAYS = { listDelayMs: 200, detailDelayMs: 15, returnGrowDelayMs: 200 };
// Paginile și ieșirile Python ale scenariului din_pagini; o fixtură lipsă sau desincronizată oprește fișierul cu mesajul ei.
const python = loadPythonScenario();

/** Ultima analiză salvată în chrome.storage.local, citită din pagina `page` (undefined dacă nu există). */
async function savedEntry(session, page) {
  return (await session.decodedStorage(page))[LAST_ANALYSIS_KEY];
}

scenario('analiza completă pe un cont generic (25 de comenzi, 12 retururi)', { orders: GENERIC_ORDERS, pageSize: GENERIC_PAGE_SIZE, returns: GENERIC_RETURNS }, (ctx) => {
  let page;
  let tabsBefore;
  let entry;

  test('„Pornește analiza” arată imediat ecranul „în lucru” și deschide o filă eMAG de lucru, inactivă', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    tabsBefore = (await s.tabs(page)).length;
    await page.click('#btn-start');
    await s.screen(page, 'working', WORKING_SCREEN_TIMEOUT_MS);
    const [workTab] = await waitFor(async () => {
      const found = await s.workTabs(page);
      return found.length === 1 ? found : null;
    }, { what: 'fila eMAG de lucru' });
    assert.equal(workTab.active, false, 'fila de lucru stă în fundal');
    await waitFor(async () => (await s.heldLocks(page)).length === 1, { what: 'lacătul „o singură analiză odată” ținut cât rulează analiza' });
  });

  test('analiza se termină singură, iar pauzele merg prin Worker-ul cronometru', async (t) => {
    const s = ctx.session;
    const started = Date.now();
    await s.screen(page, 'done', RUN_TIMEOUT_MS);
    t.diagnostic(`analiza s-a terminat în ${Date.now() - started} ms după ecranul „în lucru”`);
    const workers = page.workers().map((worker) => worker.url());
    assert.equal(workers.length, 1, `un singur Worker în pagină: ${JSON.stringify(workers)}`);
    assert.ok(workers[0].endsWith('/colectare/timer_worker.js'), `Worker-ul e cronometrul din colectare: ${workers[0]}`);
  });

  test('ultima analiză e salvată: schema, comenzile în ordinea listei, retururile și jurnalul în formatul din Python', async () => {
    const s = ctx.session;
    entry = await savedEntry(s, page);
    assert.ok(entry, 'există o intrare salvată');
    assert.equal(entry.schema, ENTRY_SCHEMA);
    assert.deepEqual(entry.orders.map((order) => order.order_id), Array.from({ length: GENERIC_ORDERS }, (_, index) => s.fake.orderIdAt(index)), 'comenzile, în ordinea din listă (cele mai noi primele)');
    assert.equal(entry.returns.length, GENERIC_RETURNS);
    assert.match(entry.log_text, LOG_LINE);
    assert.match(entry.log_text, /\[run_pipeline\] INFO: pornesc rularea/);
    assert.match(entry.log_text, /\[spend_analysis\] INFO: /, 'jurnalul are și rândurile analizei');
    assert.match(entry.log_text, /\[return_matcher\] INFO: /, 'jurnalul are și rândurile potrivirii retururilor');
    assert.ok(!(RUN_LOG_KEY in (await s.decodedStorage(page))), 'jurnalul de lucru al rulării a fost șters după succes (a intrat în analiza salvată)');
  });

  test('cererile spre eMAG: cel mult 3 detalii deodată, fiecare pagină cerută o dată, listele pe paginile 1–3', async () => {
    const { state } = ctx.session.fake;
    assert.ok(state.maxDetailInFlight <= FETCH_CONCURRENCY, `cel mult ${FETCH_CONCURRENCY} detalii în zbor, au fost ${state.maxDetailInFlight}`);
    assert.ok(state.maxDetailInFlight >= 2, `cererile chiar rulează în paralel (cel mult ${state.maxDetailInFlight} deodată)`);
    assert.equal(state.detailCount, GENERIC_ORDERS, 'câte o cerere pentru fiecare comandă');
    assert.equal(state.returnDetailCount, GENERIC_RETURNS, 'câte o cerere pentru fiecare retur');
    assert.deepEqual([...new Set(state.listPagesServed)].sort((a, b) => a - b), Array.from({ length: GENERIC_LIST_PAGES }, (_, index) => index + 1), 'paginile listei de comenzi');
  });

  test('la final fila de lucru s-a închis, lacătul e liber și nu rămâne nicio evidență', async () => {
    const s = ctx.session;
    const tabs = await s.tabs(page);
    assert.equal(tabs.some((tab) => tab.url.startsWith('https://www.emag.ro')), false, 'nicio filă eMAG rămasă');
    assert.equal(tabs.length, tabsBefore, 'același număr de file ca înainte de analiză');
    assert.deepEqual(await s.lockRecord(page), {}, 'evidența lacătului a dispărut');
    assert.deepEqual(await s.heldLocks(page), [], 'niciun lacăt ținut');
  });

  test('ecranul raportului: „Ultima analiză”, toate cele 7 descărcări și raportul desenat din analiza reală', async () => {
    const s = ctx.session;
    assert.ok((await page.textContent('#done-sub')).startsWith('Ultima analiză:'), await page.textContent('#done-sub'));
    assert.equal(await page.locator('.downloads__list li:not([hidden])').count(), REAL_DOWNLOADS.length);
    const validation = await page.evaluate((summary) => window.EmagDashboard.validate(summary), entry.summary);
    assert.equal(validation.ok, true, `rezumatul salvat trece de validatorul raportului: ${JSON.stringify(validation.errors)}`);
    assert.ok((await page.locator('#report-root *').count()) > MIN_REPORT_ELEMENTS, 'raportul se desenează');
    assert.equal((await page.textContent('#report-status')).trim(), '', 'fără mesaj de eroare');
    assert.equal(s.fake.state.unknown.length, 0);
  });

  test('descărcările: numele, BOM-ul la CSV, forma JSON-urilor, jurnalul și raportul cu analiza salvată', async () => {
    const files = {};
    for (const name of REAL_DOWNLOADS) {
      files[name] = await downloadFrom(page, `button[data-file="${name}"]`);
      assert.equal(files[name].name, name, `numele fișierului descărcat (${name})`);
    }
    for (const csv of ['produse.csv', 'istoric_preturi.csv']) {
      assert.ok(files[csv].bytes.subarray(0, BOM.length).equals(BOM), `${csv} începe cu BOM (EF BB BF), ca Excel să citească diacriticele`);
    }
    const rows = files['produse.csv'].text.split(/\r?\n/).filter((row) => row !== '');
    assert.equal(rows.length - 1, entry.summary.meta.lines, 'produse.csv are un rând pe fiecare linie din analiză, plus antetul');
    const orders = JSON.parse(files['comenzi.json'].text);
    assert.deepEqual(orders.map((order) => order.order_id), entry.orders.map((order) => order.order_id), 'comenzi.json are comenzile salvate, în aceeași ordine');
    assert.match(files['comenzi.json'].text, /^\[\n \{\n  "order_id": /, 'indentare de un spațiu ca în Python, cheile din to_dict');
    assert.equal(JSON.parse(files['retururi.json'].text).length, GENERIC_RETURNS);
    assert.equal(files['jurnal.txt'].text, entry.log_text, 'jurnal.txt e jurnalul salvat');
    assert.deepEqual(normalize(JSON.parse(files['analiza.json'].text)), normalize(entry.summary), 'analiza.json e rezumatul salvat');
    const block = REPORT_DATA_BLOCK.exec(files['raport.html'].text);
    assert.ok(block, 'raport.html are blocul JSON cu analiza');
    assert.deepEqual(JSON.parse(block[1]), normalize(entry.summary), 'raport.html poartă rezumatul salvat');
    assert.doesNotMatch(files['raport.html'].text, REPORT_PLACEHOLDER, 'toate marcajele șablonului au fost înlocuite');
  });

  test('după reîncărcare apare raportul salvat, desenat din chrome.storage', async () => {
    const s = ctx.session;
    await page.reload();
    await s.screen(page, 'done');
    assert.ok((await page.textContent('#done-sub')).startsWith('Ultima analiză:'));
    assert.ok((await page.locator('#report-root *').count()) > MIN_REPORT_ELEMENTS, 'raportul se desenează');
    assert.equal((await page.textContent('#report-status')).trim(), '', 'fără mesaj de eroare');
  });
});

scenario('paritate cu Python: analiza paginilor din scenariul din_pagini', { ...python.fakeOptions, ...PYTHON_FAKE_DELAYS }, (ctx) => {
  const { expected } = python;
  let page;
  let entry;
  let expectedSummary;

  test('analiza pe paginile inventate se termină', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await s.screen(page, 'done', RUN_TIMEOUT_MS);
    entry = await savedEntry(s, page);
    assert.ok(entry, 'există o intrare salvată');
    assert.equal(s.fake.state.detailCount, expected.comenzi.length, 'câte o cerere pentru fiecare comandă din scenariu');
    assert.equal(s.fake.state.returnDetailCount, expected.retururi.length, 'câte o cerere pentru fiecare retur din scenariu');
  });

  test('comenzile și retururile citite sunt cele pe care le-a parsat Python (la valoare)', () => {
    assert.ok(isDeepStrictEqual(normalize(entry.orders), normalize(expected.comenzi)), `comenzi: ${differences(normalize(expected.comenzi), normalize(entry.orders)).join(' | ')}`);
    assert.ok(isDeepStrictEqual(normalize(entry.returns), normalize(expected.retururi)), `retururi: ${differences(normalize(expected.retururi), normalize(entry.returns)).join(' | ')}`);
  });

  test('plătitul efectiv, numărul de linii și rezumatul întreg sunt cele din Python', () => {
    const mine = normalize(entry.summary);
    expectedSummary = normalize(expected.rezumat);
    assert.equal(mine.paid.spent_bani, expectedSummary.paid.spent_bani, 'paid.spent_bani');
    assert.equal(mine.meta.lines, expected.linii.length, 'numărul de linii din registru');
    assert.equal(expectedSummary.meta.lines, expected.linii.length);
    mine.meta.generated_at = 'ora generării diferă prin natura lucrurilor';
    expectedSummary.meta.generated_at = mine.meta.generated_at;
    assert.ok(isDeepStrictEqual(mine, expectedSummary), `rezumat: ${differences(expectedSummary, mine).join(' | ')}`);
    assert.equal(entry.threshold_lei * 100, expected.prag_bani, 'pragul pentru achiziții mari (în bani)');
  });

  test('rezumatul salvat trece de validatorul raportului, iar raportul se desenează fără eroare', async () => {
    const validation = await page.evaluate((summary) => window.EmagDashboard.validate(summary), entry.summary);
    assert.equal(validation.ok, true, JSON.stringify(validation.errors));
    assert.ok((await page.locator('#report-root *').count()) > MIN_REPORT_ELEMENTS);
    assert.equal((await page.textContent('#report-status')).trim(), '');
  });

  test('produse.csv, istoric_preturi.csv, comenzi.json și retururi.json descărcate sunt identice la octet cu fișierele Python', async () => {
    const wanted = {
      'produse.csv': expected.linii_csv, 'istoric_preturi.csv': expected.istoric_csv, 'comenzi.json': expected.comenzi_json, 'retururi.json': expected.retururi_json,
    };
    for (const [name, text] of Object.entries(wanted)) {
      const file = await downloadFrom(page, `button[data-file="${name}"]`);
      assert.ok(file.bytes.equals(Buffer.from(text, 'utf8')), `${name} diferă de fișierul Python ${firstTextDifference(text, file.text)}`);
    }
  });

  test('analiza.json și raport.html descărcate poartă rezumatul din Python (la valoare, fără ora generării)', async () => {
    const analysis = normalize(JSON.parse((await downloadFrom(page, 'button[data-file="analiza.json"]')).text));
    analysis.meta.generated_at = expectedSummary.meta.generated_at;
    assert.ok(isDeepStrictEqual(analysis, expectedSummary), `analiza.json: ${differences(expectedSummary, analysis).join(' | ')}`);
    const report = await downloadFrom(page, 'button[data-file="raport.html"]');
    const block = REPORT_DATA_BLOCK.exec(report.text);
    assert.ok(block, 'raport.html are blocul JSON cu analiza');
    const reported = normalize(JSON.parse(block[1]));
    reported.meta.generated_at = expectedSummary.meta.generated_at;
    assert.ok(isDeepStrictEqual(reported, expectedSummary), `raport.html: ${differences(expectedSummary, reported).join(' | ')}`);
  });

  test('după reîncărcare raportul se desenează din nou, iar jurnalul are rândurile analizei', async () => {
    const s = ctx.session;
    await page.reload();
    await s.screen(page, 'done');
    assert.ok((await page.locator('#report-root *').count()) > MIN_REPORT_ELEMENTS);
    assert.equal((await page.textContent('#report-status')).trim(), '');
    assert.match(entry.log_text, new RegExp(`\\[spend_analysis\\] INFO: analiză: ${expected.comenzi.length} comenzi`));
    assert.match(entry.log_text, /\[return_matcher\] INFO: /);
  });
});
