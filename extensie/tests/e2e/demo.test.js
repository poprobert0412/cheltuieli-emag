// Scenariul „demo” cap-coadă: ecranul de start și raportul demonstrativ („Încearcă cu date inventate”), fără cont, fără login și fără nicio cerere spre eMAG.
// Pornește extensia din dist/ în browser, cu eMAG-ul fals pe www.emag.ro și rețeaua reală blocată (harness.js). Verifică ecranul de start (versiunea din manifest, pragul, minutele de login din setări),
// raportul desenat din date inventate, cele două descărcări permise la demo (raport.html, analiza.json), că demo-ul nu salvează nimic și, ca „control negativ”, că pagina extensiei nu poate face cereri (connect-src 'none').
// Ce NU face: nu citește contul (analiza.test.js) și nu testează designul ecranelor (verificat vizual la aprobarea lui).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

import { loginWaitText } from '../../src/colectare/run_errors.js';
import { BIG_PURCHASE_THRESHOLD_LEI } from '../../src/settings.js';
import {
  DIST_DIR, downloadFrom, scenario, waitFor,
} from './harness.js';

// Blocul JSON cu analiza din raport.html autonom (marcajul din templates/raport.html) și marcajele pe care generatorul trebuie să le înlocuiască toate.
const REPORT_DATA_BLOCK = /<script id="date-analiza" type="application\/json">([\s\S]*?)<\/script>/;
const REPORT_PLACEHOLDER = /\/\*__[A-Z_]+__\*\//;
// Cât de multe elemente trebuie să aibă raportul desenat ca să socotim că s-a desenat (un raport gol sau cu eroare are doar câteva).
const MIN_REPORT_ELEMENTS = 50;
// Descărcările permise la demo: restul butoanelor sunt ascunse (comenzile și retururile citite nu există).
const DEMO_DOWNLOADS = 2;

/** Versiunea din manifestul extensiei construite. */
function manifestVersion() {
  return JSON.parse(readFileSync(path.join(DIST_DIR, 'manifest.json'), 'utf8')).version;
}

scenario('demo: raportul demonstrativ, fără cont și fără rețea', {}, (ctx) => {
  let page;

  test('ecranul de start e singurul vizibil, cu versiunea, pragul implicit și minutele de login din setări', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    assert.deepEqual(await s.visibleScreens(page), ['ready']);
    assert.ok((await page.textContent('#app-version')).includes(manifestVersion()), 'versiunea din manifest apare sub titlu');
    assert.ok((await page.textContent('#faq-login')).includes(loginWaitText()), 'minutele de login din întrebările frecvente vin din setări');
    assert.ok(await page.isHidden('#last-block'), 'fără analiză salvată nu există rândul „Ultima analiză”');
    assert.equal(await page.inputValue('#threshold'), String(BIG_PURCHASE_THRESHOLD_LEI), 'pragul implicit vine din setări');
  });

  test('„Încearcă cu date inventate” desenează raportul, cu doar două descărcări și fără „Șterge datele”', async () => {
    const s = ctx.session;
    await page.click('#btn-demo');
    await s.screen(page, 'done');
    assert.ok((await page.locator('#report-root *').count()) > MIN_REPORT_ELEMENTS, 'raportul demonstrativ se desenează');
    assert.ok((await page.textContent('#done-sub')).includes('date inventate'), 'subtitlul spune că e o rulare de probă');
    assert.equal(await page.locator('.downloads__list li:not([hidden])').count(), DEMO_DOWNLOADS);
    assert.ok(await page.isHidden('#data-block'), '„Șterge datele” nu există la demo');
    assert.equal(await page.textContent('#btn-again'), 'Înapoi la început');
    assert.ok(await page.evaluate(() => document.activeElement && document.activeElement.id === 'done-t'), 'focusul trece pe titlul ecranului nou');
    assert.equal((await page.textContent('#report-status')).trim(), '', 'raportul nu arată niciun mesaj de eroare');
  });

  test('analiza.json descărcat are datele demo, cu indentare de un spațiu ca în Python', async () => {
    const file = await downloadFrom(page, 'button[data-file="analiza.json"]');
    const demo = await page.evaluate(() => window.EMAG_DEMO_DATA);
    assert.equal(file.name, 'analiza.json');
    assert.deepEqual(JSON.parse(file.text), JSON.parse(JSON.stringify(demo)));
    assert.match(file.text, /^\{\n "[a-z_]+": /, 'indentare de un spațiu (json.dumps(indent=1))');
  });

  test('raport.html descărcat e o pagină completă, fără marcaje rămase, cu datele demo în blocul JSON', async () => {
    const file = await downloadFrom(page, 'button[data-file="raport.html"]');
    const demo = await page.evaluate(() => window.EMAG_DEMO_DATA);
    const block = REPORT_DATA_BLOCK.exec(file.text);
    assert.equal(file.name, 'raport.html');
    assert.ok(file.text.startsWith('<!doctype html>'), 'pagină HTML completă');
    assert.doesNotMatch(file.text, REPORT_PLACEHOLDER, 'toate marcajele șablonului au fost înlocuite');
    assert.ok(block, 'blocul JSON cu analiza există');
    assert.deepEqual(JSON.parse(block[1]), JSON.parse(JSON.stringify(demo)));
  });

  test('înapoi la start, iar demo-ul nu a salvat nimic în browser', async () => {
    const s = ctx.session;
    await page.click('#btn-again');
    await s.screen(page, 'ready');
    assert.deepEqual(Object.keys(await s.storage(page)), [], 'chrome.storage.local rămâne gol');
    assert.deepEqual(await s.lockRecord(page), {}, 'niciun lacăt de analiză');
    assert.equal((await s.tabs(page)).filter((tab) => tab.url.startsWith('https://www.emag.ro')).length, 0, 'nicio filă eMAG nu s-a deschis');
    assert.equal(s.fake.state.requests.length, 0, 'demo-ul nu face nicio cerere spre eMAG');
  });

  test('control negativ: o cerere făcută din pagina extensiei e blocată de connect-src, înainte să plece', async () => {
    const s = ctx.session;
    const outcome = await page.evaluate(() => fetch('https://www.emag.ro/proba-control').then(() => 'permisă', () => 'blocată'));
    assert.equal(outcome, 'blocată');
    await waitFor(() => s.cspViolations.some((text) => text.startsWith('connect-src')), { what: 'încălcarea connect-src raportată de pagină' });
    await waitFor(() => s.issues.some((text) => /Content Security Policy|connect-src/i.test(text)), { what: 'eroarea de consolă despre încălcare' });
    assert.ok(s.consumeCspViolations(/^connect-src/).length > 0, 'încălcarea connect-src e raportată');
    assert.ok(s.consumeIssues(/Content Security Policy|connect-src/i).length > 0, 'browserul scrie și o eroare de consolă despre ea');
    assert.deepEqual(s.fake.state.requests, [], 'cererea blocată nu a ajuns la eMAG');
  });
});
