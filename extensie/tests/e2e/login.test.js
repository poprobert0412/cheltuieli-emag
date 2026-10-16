// Login-ul cap-coadă: contul nu e logat când pornește analiza, extensia așteaptă în fila eMAG de lucru, iar omul se loghează acolo (sau oprește analiza).
// Ecranul „Loghează-te în eMAG” apare cu textul din setări și cu butonul care aduce fila de lucru în față; parola și codul 2FA le scrie omul în fila eMAG, deci eMAG-ul fals doar își schimbă starea
// (`state.loggedIn`) cum ar face după un login adevărat. După login analiza continuă singură până la raport. „Oprește” de pe ecranul de login închide fila și nu salvează nimic.
// Ce NU face: nu testează expirarea după 10 minute (LOGIN_WAIT_SECONDS, verificată unitar cu un ceas fals) și nu tastează nimic în câmpuri (extensia nu atinge câmpurile paginii eMAG).
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loginWaitText } from '../../src/colectare/run_errors.js';
import { LOGIN_POLL_SECONDS } from '../../src/settings.js';
import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import {
  RUN_TIMEOUT_MS, SCREEN_TIMEOUT_MS, scenario, sleep, waitFor,
} from './harness.js';

const FAKE_ACCOUNT = { loggedIn: false, orders: 12, returns: 3 };
// Cât stăm pe ecranul de login ca să fim siguri că extensia a interogat pagina măcar o dată (la fiecare LOGIN_POLL_SECONDS) fără să se fi schimbat nimic.
const WAIT_BEFORE_LOGIN_MS = LOGIN_POLL_SECONDS * 1000 * 1.5;
// După „Oprește” din login, oprirea se vede la următoarea interogare a paginii (cel mult LOGIN_POLL_SECONDS), plus închiderea filei.
const CANCEL_TIMEOUT_MS = SCREEN_TIMEOUT_MS;

scenario('login: nelogat la pornire, logat de om în timpul așteptării', FAKE_ACCOUNT, (ctx) => {
  let page;
  let workTab;

  test('ecranul de login apare, cu textul din setări și cu fila eMAG de lucru deschisă în fundal', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await s.screen(page, 'login');
    assert.ok(await page.evaluate(() => document.activeElement.id === 'login-t'), 'focusul trece pe titlul ecranului de login');
    assert.ok((await page.textContent('#screen-login .callout__text')).includes(loginWaitText()), 'textul spune cât așteaptă extensia, din setări');
    const tabs = await s.workTabs(page);
    assert.equal(tabs.length, 1, 'o singură filă eMAG de lucru');
    assert.equal(tabs[0].active, false, 'fila de lucru stă în fundal');
    [workTab] = tabs;
    assert.equal(await page.getAttribute('#btn-show-tab', 'aria-disabled'), null, '„Deschide fila eMAG” e activ');
  });

  test('„Deschide fila eMAG” aduce fila de lucru în față, iar evidența lacătului ține ambele file', async () => {
    const s = ctx.session;
    await page.click('#btn-show-tab');
    await waitFor(async () => (await s.workTabs(page))[0]?.active === true, { what: 'fila de lucru adusă în față' });
    const [record] = Object.values(await s.lockRecord(page));
    assert.equal(record.workTabId, workTab.id, 'evidența lacătului are fila de lucru');
    assert.ok(Number.isInteger(record.appTabId), 'evidența lacătului are și fila aplicației');
  });

  test('cât omul nu s-a logat, rămâne ecranul de login', async () => {
    const s = ctx.session;
    await sleep(WAIT_BEFORE_LOGIN_MS);
    assert.deepEqual(await s.visibleScreens(page), ['login']);
  });

  test('după ce omul se loghează, analiza continuă singură și se termină cu raportul', async () => {
    const s = ctx.session;
    s.fake.state.loggedIn = true; // omul s-a logat în fila lui
    await s.screen(page, 'done', RUN_TIMEOUT_MS);
    const entry = (await s.decodedStorage(page))[LAST_ANALYSIS_KEY];
    assert.equal(entry.orders.length, FAKE_ACCOUNT.orders);
    assert.equal(entry.returns.length, FAKE_ACCOUNT.returns);
    assert.match(entry.log_text, /\[session_check\] INFO: login reușit/, 'jurnalul spune că omul s-a logat');
    assert.equal((await s.workTabs(page)).length, 0, 'fila de lucru s-a închis');
    assert.deepEqual(await s.heldLocks(page), [], 'lacătul e liber');
  });
});

scenario('login: „Oprește” de pe ecranul de login', FAKE_ACCOUNT, (ctx) => {
  test('oprirea închide fila de lucru, eliberează lacătul și nu salvează nicio analiză', async () => {
    const s = ctx.session;
    const page = await s.openApp();
    await s.screen(page, 'ready');
    await page.click('#btn-start');
    await s.screen(page, 'login');
    await page.click('#btn-login-cancel');
    assert.equal(await page.textContent('#btn-login-cancel'), 'Se oprește…', 'butonul spune că se oprește');
    assert.equal(await page.getAttribute('#btn-login-cancel', 'aria-disabled'), 'true', 'și nu se mai poate apăsa');
    await s.screen(page, 'cancelled', CANCEL_TIMEOUT_MS);
    assert.equal((await s.workTabs(page)).length, 0, 'fila de lucru s-a închis');
    assert.deepEqual(await s.heldLocks(page), [], 'lacătul e liber');
    assert.deepEqual(await s.lockRecord(page), {}, 'nicio evidență de lacăt');
    assert.ok(!(LAST_ANALYSIS_KEY in (await s.decodedStorage(page))), 'nu s-a salvat nicio analiză');
  });
});
