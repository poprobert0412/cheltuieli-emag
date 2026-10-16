// Contextul raportului în pagina extensiei și în HTML autonom: texte adecvate platformei, date identice și zero rețea.
// Desktop rămâne implicit; trecerea se face prin opțiuni, niciodată prin adresa paginii.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { downloadFrom, scenario } from './harness.js';

const EXTENSION_CATEGORIES = 'Extensia folosește categoriile incluse. Regulile personale sunt disponibile în programul pentru calculator.';
const EXTENSION_UNCATEGORIZED = 'Verifică produsele rămase fără categorie. Extensia nu permite adăugarea regulilor personale.';
const EXTENSION_RETURNS = 'Modurile de restituire sunt cele incluse în extensie.';
const EXTENSION_ERROR = 'Pornește din nou analiza. Dacă problema persistă, descarcă jurnalul și raportează eroarea fără datele comenzilor.';
const GUIDANCE_SELECTOR = '.ed-caption,.ed-method,.ed-hint,.ed-error-list,.ed-wg-text';

/** Fragmentele desktop rămase: diagnostic scurt, fără să verse raportul demonstrativ întreg în jurnalul testelor. */
function desktopInstructions(text) {
  return text.match(/.{0,60}(?:config\/|--prag|--din-cache|iesiri).{0,80}/g) || [];
}

scenario('context: raportul extensiei și exportul autonom păstrează aceleași date', {}, (ctx) => {
  let page;

  test('demo-ul extensiei folosește instrucțiunile aprobate și pragul fără CLI', async () => {
    const s = ctx.session;
    page = await s.openApp();
    await s.screen(page, 'ready');
    assert.match(await page.textContent('#start-form'), /Analiza și jurnalul se păstrează criptat în acest browser/);
    await page.click('#btn-demo');
    await s.screen(page, 'done');
    const text = await page.textContent('#report-root');
    assert.ok(text.includes(EXTENSION_CATEGORIES));
    assert.ok(text.includes(EXTENSION_RETURNS));
    assert.ok(text.includes('Pragul se schimbă înainte de pornirea analizei.'));
    assert.deepEqual(desktopInstructions((await page.locator(`#report-root :is(${GUIDANCE_SELECTOR})`).allTextContents()).join(' ')), []);
  });

  test('două instanțe pe aceeași pagină păstrează separat contextul desktop și extension', async () => {
    const result = await page.evaluate(() => {
      const data = structuredClone(window.EMAG_DEMO_DATA);
      data.uncategorized = [{ name: 'Produs inventat fără categorie', units: 1, bani: 100 }];
      data.uncategorized_count = 1;
      const before = JSON.stringify(data);
      const roots = [document.createElement('div'), document.createElement('div')];
      roots.forEach(root => document.body.append(root));
      const instances = [window.EmagDashboard.mount(roots[0], data), window.EmagDashboard.mount(roots[1], data, { context: 'extension' })];
      const output = {
        desktop: roots[0].textContent, extension: roots[1].textContent,
        guidance: [...roots[1].querySelectorAll('.ed-caption,.ed-method,.ed-hint,.ed-error-list,.ed-wg-text')].map(node => node.textContent).join(' '),
        rawMessages: (data.warnings_detail || []).filter(group => group.kind === 'other').flatMap(group => group.items.map(item => item.text)),
        intact: before === JSON.stringify(data), amounts: roots.map(root => root.querySelector('.ed-amount').textContent),
      };
      instances.forEach(instance => instance.unmount());
      roots.forEach(root => root.remove());
      return output;
    });
    assert.ok(result.desktop.includes('config/categorii.personal.json'));
    assert.ok(result.desktop.includes('--din-cache'));
    assert.ok(result.desktop.includes('config/restituiri.json'));
    assert.ok(result.extension.includes(EXTENSION_UNCATEGORIZED));
    assert.deepEqual(desktopInstructions(result.guidance), []);
    for (const rawMessage of result.rawMessages) assert.ok(result.extension.includes(rawMessage), 'mesajele brute ale avertismentelor rămân vizibile, identice');
    assert.equal(result.intact, true);
    assert.equal(result.amounts[0], result.amounts[1]);
  });

  test('erorile raportului extensiei cer reluarea analizei, fără căi desktop', async () => {
    const text = await page.evaluate(() => {
      const root = document.createElement('div');
      document.body.append(root);
      const instance = window.EmagDashboard.mount(root, null, { context: 'extension' });
      const text = root.textContent;
      instance.unmount();
      root.remove();
      return text;
    });
    assert.ok(text.includes(EXTENSION_ERROR));
    assert.doesNotMatch(text, /iesiri|aplicația locală/);
  });

  test('HTML-ul descărcat funcționează autonom offline, cu numele din manifest și datele nemodificate', async () => {
    const s = ctx.session;
    const { text } = await downloadFrom(page, 'button[data-file="raport.html"]');
    assert.doesNotMatch(text, /\/\*__[A-Z_]+__\*\//);
    assert.doesNotMatch(text, /<noscript>[\s\S]*rezumat\.txt[\s\S]*<\/noscript>/);
    const expected = await page.evaluate(() => ({ data: window.EMAG_DEMO_DATA, name: chrome.runtime.getManifest().name }));
    const exported = await s.context.newPage();
    try {
      await exported.setContent(text);
      await exported.waitForSelector('[data-ed-state="ready"]');
      assert.equal(await exported.title(), expected.name);
      assert.equal(await exported.textContent('.rp-top h1'), expected.name);
      assert.ok((await exported.textContent('#raport')).includes(EXTENSION_CATEGORIES));
      assert.deepEqual(desktopInstructions((await exported.locator(`#raport :is(${GUIDANCE_SELECTOR})`).allTextContents()).join(' ')), []);
      assert.deepEqual(JSON.parse(await exported.textContent('#date-analiza')), JSON.parse(JSON.stringify(expected.data)));
      assert.equal(s.fake.state.requests.length, 0);
    } finally {
      await exported.close();
    }
  });
});
