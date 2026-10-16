// Oprirea și soarta filelor cap-coadă: „Oprește” în timpul analizei, a doua filă a aplicației („busy”), fila eMAG de lucru închisă de om, filele rămase orfane și clicul pe iconița extensiei.
// Fiecare scenariu pornește o analiză pe un cont fals mai mare, cu detalii întârziate, ca analiza să încapă „în lucru” cât timp testul face ce vrea să verifice. Se verifică mereu aceleași urme: ecranul, fila de lucru, lacătul,
// ultima analiză salvată înainte (care trebuie să rămână neatinsă), jurnalul rulării oprite și că nu mai pleacă cereri după oprire.
// Ce NU face: nu testează login-ul (login.test.js) și nu dă clic pe iconița din bara browserului (Playwright nu o poate apăsa); în schimb rulează funcția pe care o cheamă clicul, importată din background.js.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { CODE_WORK_TAB_CLOSED, classifyError } from '../../src/colectare/run_errors.js';
import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import { RUN_LOG_KEY } from '../../src/stocare/run_log.js';
import {
  SCREEN_TIMEOUT_MS, downloadFrom, scenario, waitFor,
} from './harness.js';

// Contul fals al acestor scenarii: destule comenzi, cu detalii lente, ca analiza să nu se termine singură cât testul o oprește sau o întrerupe. Lista are doar două pagini, ca detaliile să înceapă repede
// (progresul „Comenzi: N din M” apare abia după ce s-a citit toată lista).
const SLOW_ACCOUNT = { orders: 40, pageSize: 20, detailDelayMs: 400 };
const SLOWER_ACCOUNT = { orders: 40, pageSize: 20, detailDelayMs: 300 };
// Cât durează până o a doua filă a aplicației iese singură din „busy” (reverifică la câteva secunde) sau până worker-ul închide o filă de lucru orfană.
const RECHECK_TIMEOUT_MS = 15_000;
const CLEANUP_TIMEOUT_MS = 15_000;

scenario('„Oprește” în timpul analizei', SLOW_ACCOUNT, (ctx) => {
  let page;
  let oldCreatedAt;

  test('„Oprește” arată „Se oprește…” și mesajul de oprire, apoi ecranul „Analiza a fost oprită”', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    oldCreatedAt = await s.seedLastAnalysis(page);
    await page.reload();
    await s.screen(page, 'done');
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    await s.startRun(page);
    await page.click('#btn-cancel');
    assert.equal(await page.textContent('#btn-cancel'), 'Se oprește…');
    assert.equal(await page.getAttribute('#btn-cancel', 'aria-disabled'), 'true', 'butonul nu se mai poate apăsa');
    assert.ok((await page.textContent('#work-detail')).startsWith('Opresc analiza'), 'mesajul de lângă bară spune că se oprește');
    await s.screen(page, 'cancelled', SCREEN_TIMEOUT_MS);
  });

  test('analiza salvată înainte a rămas neatinsă, iar jurnalul rulării oprite e salvat separat', async () => {
    const s = ctx.session;
    const stored = await s.decodedStorage(page);
    assert.equal(stored[LAST_ANALYSIS_KEY]?.created_at, oldCreatedAt, 'ultima analiză e cea de dinainte');
    assert.match(stored[RUN_LOG_KEY]?.text ?? '', /rularea a fost oprită la cererea ta/, 'jurnalul rulării oprite');
  });

  test('fila de lucru s-a închis, lacătul e liber și nu s-au mai cerut toate cele 40 de detalii', async () => {
    const s = ctx.session;
    assert.equal((await s.workTabs(page)).length, 0);
    assert.deepEqual(await s.heldLocks(page), []);
    assert.ok(s.fake.state.detailCount < SLOW_ACCOUNT.orders, `s-au cerut ${s.fake.state.detailCount} din ${SLOW_ACCOUNT.orders} detalii: după oprire nu mai pleacă cereri`);
  });

  test('„Descarcă jurnalul” dă jurnalul rulării oprite, iar „Înapoi la început” păstrează rândul „Ultima analiză”', async () => {
    const s = ctx.session;
    assert.ok(await page.isVisible('#screen-cancelled [data-action="download-log"]'));
    const log = await downloadFrom(page, '#screen-cancelled [data-action="download-log"]');
    assert.equal(log.name, 'jurnal.txt');
    assert.equal(log.text, (await s.decodedStorage(page))[RUN_LOG_KEY].text);
    await page.click('#screen-cancelled [data-action="back"]');
    await s.screen(page, 'ready');
    assert.ok(await page.isVisible('#last-block'), 'rândul „Ultima analiză” e încă acolo');
  });
});

scenario('a doua filă a aplicației', SLOWER_ACCOUNT, (ctx) => {
  test('cât rulează o analiză, a doua filă arată „busy”, iar când aceea se oprește trece singură pe ecranul de start', async () => {
    const s = ctx.session;
    const first = await s.openApp();
    await s.screen(first, 'ready');
    await s.startRun(first);
    assert.equal((await s.heldLocks(first)).length, 1, 'analiza ține lacătul');
    const second = await s.openApp();
    await s.screen(second, 'busy');
    assert.equal(await second.textContent('#busy-t'), 'O analiză rulează deja');
    await second.click('#btn-recheck');
    assert.deepEqual(await s.visibleScreens(second), ['busy'], '„Verifică din nou” cât rulează rămâne pe „busy”');
    await first.click('#btn-cancel');
    await s.screen(first, 'cancelled');
    await s.screen(second, 'ready', RECHECK_TIMEOUT_MS);
  });
});

scenario('fila eMAG de lucru închisă de om', SLOWER_ACCOUNT, (ctx) => {
  test('analiza se oprește cu eroarea „fila eMAG a fost închisă”, cu jurnalul salvat și lacătul liber', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.startRun(page);
    const [workTab] = await s.workTabs(page);
    await page.evaluate((tabId) => chrome.tabs.remove(tabId), workTab.id);
    await s.screen(page, 'error');
    assert.equal(await page.textContent('#error-message'), classifyError({ code: CODE_WORK_TAB_CLOSED }).message, 'mesajul erorii „fila de lucru închisă”');
    assert.match((await s.decodedStorage(page))[RUN_LOG_KEY]?.text ?? '', /rularea a eșuat \(work_tab_closed\)/, 'jurnalul rulării căzute');
    assert.deepEqual(await s.heldLocks(page), [], 'lacătul e liber');
    assert.ok(!(LAST_ANALYSIS_KEY in (await s.decodedStorage(page))), 'nu s-a salvat nicio analiză');
    assert.ok(await page.isVisible('#screen-error [data-action="download-log"]'), '„Descarcă jurnalul” e vizibil la eroare');
    await page.click('#screen-error a[data-faq-link]');
    assert.ok(await page.evaluate(() => document.getElementById('faq-nu-merge').open), 'linkul „Ce fac dacă nu merge?” deschide întrebarea');
  });
});

scenario('file rămase orfane', SLOWER_ACCOUNT, (ctx) => {
  test('o pagină reîncărcată în timpul analizei închide fila de lucru rămasă și arată ecranul de start', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.startRun(page);
    assert.equal((await s.workTabs(page)).length, 1, 'în timpul rulării există o filă de lucru');
    await page.reload(); // analiza se pierde, iar fila de lucru rămâne orfană până o curăță pagina nouă
    await s.screen(page, 'ready', CLEANUP_TIMEOUT_MS);
    await waitFor(async () => (await s.workTabs(page)).length === 0, { timeoutMs: CLEANUP_TIMEOUT_MS, what: 'închiderea filei de lucru orfane' });
    assert.deepEqual(await s.lockRecord(page), {}, 'evidența lacătului e curățată');
    assert.deepEqual(await s.heldLocks(page), [], 'lacătul e liber');
  });

  test('închiderea filei aplicației în timpul analizei închide fila de lucru (worker-ul), iar altă filă iese din „busy”', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.startRun(page);
    const other = await s.openApp();
    await s.screen(other, 'busy');
    await page.close();
    await waitFor(async () => (await s.workTabs(other)).length === 0, { timeoutMs: CLEANUP_TIMEOUT_MS, what: 'închiderea filei de lucru de către worker' });
    await s.screen(other, 'ready', RECHECK_TIMEOUT_MS);
    assert.deepEqual(await s.lockRecord(other), {}, 'evidența lacătului e curățată de worker');
  });
});

scenario('clicul pe iconița extensiei', {}, (ctx) => {
  test('worker-ul extensiei are ascultătorii pentru clic și pentru închiderea filelor', async () => {
    const listeners = await ctx.session.worker.evaluate(() => ({
      click: chrome.action.onClicked.hasListeners(),
      tabRemoved: chrome.tabs.onRemoved.hasListeners(),
    }));
    assert.deepEqual(listeners, { click: true, tabRemoved: true });
  });

  test('clicul aduce în față aceeași filă a aplicației, sau deschide una nouă dacă nu există', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    const appTabId = await page.evaluate(async () => (await chrome.tabs.getCurrent()).id);
    // O filă a extensiei cu altă adresă decât aplicația (getContexts caută adresa exactă), din care se cheamă funcția clicului.
    const helper = await s.openApp({ search: '?ajutor' });
    const click = () => helper.evaluate(async () => {
      const module = await import(chrome.runtime.getURL('background.js'));
      const id = await module.openOrFocusApp();
      let tab = await chrome.tabs.get(id);
      for (let attempt = 0; attempt < 30 && !tab.url; attempt += 1) { // o filă nou creată are adresa abia după câteva zeci de milisecunde
        await new Promise((resolve) => { setTimeout(resolve, 100); });
        tab = await chrome.tabs.get(id);
      }
      return { id, url: tab.url, active: tab.active };
    });
    const same = await click();
    assert.equal(same.id, appTabId, 'cu aplicația deschisă, clicul nu deschide altă filă');
    assert.equal(same.active, true, 'o aduce în față');
    await page.close();
    const created = await click();
    assert.equal(created.url, s.appUrl, 'fără aplicație deschisă, clicul deschide pagina aplicației');
    assert.equal(created.active, true);
    assert.notEqual(created.id, appTabId);
    assert.equal((await click()).id, created.id, 'încă un clic nu deschide a doua filă');
  });
});
