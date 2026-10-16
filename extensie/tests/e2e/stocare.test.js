// Stocarea cap-coadă (E4): ultima analiză la redeschiderea paginii, „Șterge datele” (cu renunțare și cu eșec), o analiză nouă care o înlocuiește pe cea veche doar la succes și o analiză căzută care o lasă întreagă.
// Ultima analiză se salvează criptat prin modulul real de stocare (raportul demonstrativ marcat ca real) ca testele să nu aștepte o analiză întreagă; analizele pornite de aici au conturi mici ale eMAG-ului fals.
// Eșecurile de stocare se imită în pagina extensiei prin înlocuirea metodelor chrome.storage.local.clear și .set cu unele care aruncă ca Chrome („QUOTA_BYTES quota exceeded”).
// Ce NU face: nu verifică conținutul raportului (analiza.test.js) și nu testează dezinstalarea (șterge tot ce a păstrat extensia, fără cod al nostru).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { CODE_PAGE_CHANGED, CODE_STORAGE_FULL, classifyError } from '../../src/colectare/run_errors.js';
import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import { RUN_LOG_KEY } from '../../src/stocare/run_log.js';
import { genericOrderId } from './emag_fals.js';
import { RUN_TIMEOUT_MS, downloadFrom, scenario } from './harness.js';

// Un cont mic, cu două pagini de listă (una singură ar face extensia să aștepte la pagina 2: vezi emag_fals.js).
const SMALL_ACCOUNT = { orders: 3, pageSize: 2, returns: 1 };
// Câte fișiere descărcabile are o analiză salvată (nu una demonstrativă).
const REAL_DOWNLOADS = 7;
const SEED_DATE = '2026-10-01 12:00:00';
// EXT_CRYPTO_REVIEW_DIR: folder opțional pentru captura ecranului de recuperare, cu date inventate; implicit nu se scrie captură.
const REVIEW_DIR = process.env.EXT_CRYPTO_REVIEW_DIR || null;

scenario('jurnal criptat corupt fără analiză: recuperare prin ștergerea existentă', {}, (ctx) => {
  test('boot afișează eroarea și aceeași confirmare de ștergere; după ștergere pagina poate porni din nou', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.evaluate((key) => chrome.storage.local.set({ [key]: { schema: 2, algorithm: 'AES-GCM', nonce: 'stricat', ciphertext: 'stricat' } }), RUN_LOG_KEY);
    await page.reload();
    await s.screen(page, 'error', 5000);
    assert.match(await page.textContent('#error-message'), /cheia locală|criptat/);
    assert.equal(await page.locator('#data-block').count(), 1, 'blocul și confirmarea nu sunt duplicate');
    assert.ok(await page.isVisible('#screen-error #btn-delete-data'));
    if (REVIEW_DIR) {
      mkdirSync(REVIEW_DIR, { recursive: true });
      while (await page.getAttribute('#theme-toggle', 'data-mode') !== 'dark') await page.click('#theme-toggle');
      await page.locator('#screen-error').screenshot({ path: path.join(REVIEW_DIR, 'crypto-error-dark.png') });
    }
    await page.click('#btn-delete-data');
    assert.ok(await page.isVisible('#delete-confirm'));
    assert.ok(await page.evaluate(() => document.activeElement.id === 'btn-delete-cancel'));
    await page.click('#btn-delete-confirm');
    await s.screen(page, 'ready');
    assert.deepEqual(await s.storage(page), {});
    const keyExists = await page.evaluate(async () => {
      const { createKeyStore } = await import('./stocare/key_store.js');
      return (await createKeyStore().read()).key !== null;
    });
    assert.equal(keyExists, false);
    await page.reload();
    await s.screen(page, 'ready');
  });
});

scenario('ultima analiză la redeschiderea paginii', {}, (ctx) => {
  let page;

  test('cu o analiză salvată, pagina se deschide direct pe raportul ei, cu „Șterge datele” și toate descărcările', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    assert.ok(await page.isHidden('#last-block'), 'fără analiză salvată nu există rândul „Ultima analiză”');
    await s.seedLastAnalysis(page, { created_at: SEED_DATE });
    await page.reload();
    await s.screen(page, 'done');
    assert.ok((await page.textContent('#done-sub')).startsWith('Ultima analiză:'), await page.textContent('#done-sub'));
    assert.ok(await page.isVisible('#data-block'), '„Șterge datele” se vede la o analiză salvată');
    assert.equal(await page.locator('.downloads__list li:not([hidden])').count(), REAL_DOWNLOADS);
    assert.equal(await page.textContent('#btn-again'), 'Analiză nouă');
  });

  test('„Analiză nouă” duce la start, unde rândul „Ultima analiză” are data ei și butonul „Deschide”', async () => {
    const s = ctx.session;
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    assert.ok(await page.isVisible('#last-block'));
    const when = await page.textContent('#last-when');
    assert.ok(when.trim().length > 0, 'rândul are o dată');
    assert.equal(await page.getAttribute('#btn-open-last', 'aria-label'), `Deschide raportul din ${when}`);
  });

  test('„Deschide” aduce din nou raportul salvat', async () => {
    const s = ctx.session;
    await page.click('#btn-open-last');
    await s.screen(page, 'done');
    assert.ok((await page.locator('#report-root *').count()) > 0);
  });
});

scenario('„Șterge datele”', {}, (ctx) => {
  let page;

  test('butonul deschide confirmarea, cu focusul pe „Renunț”, iar „Renunț” o închide fără să șteargă nimic', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    await s.seedLastAnalysis(page);
    await page.reload();
    await s.screen(page, 'done');
    await page.click('#btn-delete-data');
    assert.ok(await page.isVisible('#delete-confirm'), 'confirmarea se deschide');
    assert.equal(await page.getAttribute('#btn-delete-data', 'aria-expanded'), 'true');
    assert.ok(await page.evaluate(() => document.activeElement.id === 'btn-delete-cancel'), 'focusul e pe acțiunea sigură („Renunț”)');
    await page.click('#btn-delete-cancel');
    assert.ok(await page.isHidden('#delete-confirm'), 'renunțarea închide confirmarea');
    assert.ok(LAST_ANALYSIS_KEY in (await s.decodedStorage(page)), 'și nu șterge nimic');
  });

  test('dacă stocarea refuză ștergerea, datele rămân, confirmarea rămâne deschisă și mesajul spune ce s-a întâmplat și ce faci', async () => {
    const s = ctx.session;
    await page.evaluate(() => {
      window.clearOriginal = chrome.storage.local.clear;
      chrome.storage.local.clear = async () => { throw new Error('QUOTA_BYTES quota exceeded (simulat)'); };
    });
    await page.click('#btn-delete-data');
    await page.click('#btn-delete-confirm');
    await page.waitForFunction(() => document.getElementById('delete-msg').textContent.startsWith('Nu am putut șterge datele'));
    const message = await page.textContent('#delete-msg');
    assert.ok(message.includes('Ce faci:') && message.includes('simulat'), message);
    assert.match(await page.getAttribute('#delete-msg', 'class'), /is-bad/, 'mesajul e marcat ca eroare');
    assert.ok(LAST_ANALYSIS_KEY in (await s.decodedStorage(page)), 'datele au rămas');
    assert.ok(await page.isVisible('#delete-confirm'), 'confirmarea a rămas deschisă');
  });

  test('„Da, șterge datele” golește stocarea, duce la start și spune că datele au fost șterse', async () => {
    const s = ctx.session;
    await page.evaluate(() => { chrome.storage.local.clear = window.clearOriginal; });
    await page.click('#btn-delete-confirm');
    await s.screen(page, 'ready');
    assert.deepEqual(await s.decodedStorage(page), {}, 'chrome.storage.local e gol');
    assert.ok((await page.textContent('#deleted-note')).includes('șterse'), 'nota de ștergere');
    assert.ok(await page.isHidden('#last-block'), 'nu mai există rândul „Ultima analiză”');
  });
});

scenario('o analiză nouă o înlocuiește pe cea veche doar când se termină cu bine', SMALL_ACCOUNT, (ctx) => {
  test('după o analiză reușită, în stocare rămâne o singură analiză, cea nouă, fără jurnalul de lucru', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.seedLastAnalysis(page, { created_at: SEED_DATE });
    await page.reload();
    await s.screen(page, 'done');
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await s.screen(page, 'done', RUN_TIMEOUT_MS);
    const stored = await s.decodedStorage(page);
    assert.deepEqual(Object.keys(stored), [LAST_ANALYSIS_KEY], 'doar ultima analiză; jurnalul de lucru a intrat în ea');
    assert.notEqual(stored[LAST_ANALYSIS_KEY].created_at, SEED_DATE, 'analiza veche a fost înlocuită');
    assert.equal(stored[LAST_ANALYSIS_KEY].orders.length, SMALL_ACCOUNT.orders);
    assert.equal(stored[LAST_ANALYSIS_KEY].returns.length, SMALL_ACCOUNT.returns);
  });
});

scenario('o analiză căzută păstrează analiza veche și își salvează jurnalul', { ...SMALL_ACCOUNT, noOrderMarker: new Set([genericOrderId(1, SMALL_ACCOUNT.orders)]) }, (ctx) => {
  test('analiza veche rămâne întreagă, jurnalul căzutei se poate descărca, iar „Înapoi la început” arată tot analiza veche', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.seedLastAnalysis(page, { created_at: SEED_DATE });
    await page.reload();
    await s.screen(page, 'done');
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await s.screen(page, 'error', RUN_TIMEOUT_MS);
    assert.ok((await page.textContent('#error-message')).startsWith(classifyError({ code: CODE_PAGE_CHANGED }).message.split(';')[0]));
    const stored = await s.decodedStorage(page);
    assert.equal(stored[LAST_ANALYSIS_KEY]?.created_at, SEED_DATE, 'ultima analiză e tot cea veche');
    assert.match(stored[RUN_LOG_KEY]?.text ?? '', /rularea a eșuat \(page_changed\)/, 'jurnalul rulării căzute e salvat separat');
    const log = await downloadFrom(page, '#screen-error [data-action="download-log"]');
    assert.equal(log.name, 'jurnal.txt');
    assert.equal(log.text, stored[RUN_LOG_KEY].text, 'jurnalul descărcat e cel salvat');
    await page.click('#screen-error [data-action="back"]');
    await s.screen(page, 'ready');
    assert.ok(await page.isVisible('#last-block'), 'rândul „Ultima analiză” e încă acolo');
  });
});

scenario('stocare plină: noua analiză nu încape', SMALL_ACCOUNT, (ctx) => {
  test('eroarea spune că nu s-a putut salva, iar analiza veche rămâne întreagă', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await s.seedLastAnalysis(page, { created_at: SEED_DATE });
    await page.reload();
    await s.screen(page, 'done');
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    // Cota plină se vede doar la scrierea analizei; jurnalul de lucru (altă cheie) se scrie mai departe.
    await page.evaluate((key) => {
      const original = chrome.storage.local.set.bind(chrome.storage.local);
      chrome.storage.local.set = async (items) => {
        if (key in items) throw new Error('QUOTA_BYTES quota exceeded (simulat)');
        return original(items);
      };
    }, LAST_ANALYSIS_KEY);
    await page.click('#btn-start');
    await s.screen(page, 'error', RUN_TIMEOUT_MS);
    assert.equal(await page.textContent('#error-message'), classifyError({ code: CODE_STORAGE_FULL }).message);
    assert.equal((await s.decodedStorage(page))[LAST_ANALYSIS_KEY]?.created_at, SEED_DATE, 'analiza veche a rămas întreagă');
    assert.match((await s.decodedStorage(page))[RUN_LOG_KEY]?.text ?? '', /rularea a eșuat \(storage_full\)/, 'jurnalul rulării căzute e salvat');
    assert.deepEqual(await s.heldLocks(page), [], 'lacătul e liber');
  });
});
