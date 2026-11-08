// Panou real din build, cu produs și istoric inventate; eMAG este interceptat, rețeaua externă blocată.
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { scenario } from './harness.js';

const PRODUCT_URL = 'https://www.emag.ro/veioza-exemplu-40-cm/pd/DEMO123/';
const PRODUCT_NAME = 'Veioză exemplu 40 cm, roșie';
const CAPTURES = path.resolve('../docs/extensie/capturi/2026-11-08-implementare');
const html = `<!doctype html><html><head><meta charset="utf-8"><link rel="canonical" href="${PRODUCT_URL}"><script type="application/ld+json">${JSON.stringify({ '@type': 'Product', name: PRODUCT_NAME, url: PRODUCT_URL, offers: { '@type': 'Offer', price: '239.99', priceCurrency: 'RON', url: PRODUCT_URL } })}</script></head><body><h1>${PRODUCT_NAME}</h1><aside><p>Alt produs 2 lei/lună</p></aside></body></html>`;

scenario('panou: produs principal, țintă criptată și navigare', {}, (ctx) => {
  let panel; let productPage; let app;
  test('pagina nouă nu citește eMAG fără acțiune și folosește CSP strict', async () => {
    const s = ctx.session;
    app = await s.openApp();
    await s.screen(app, 'ready');
    panel = await s.context.newPage();
    await panel.goto(`chrome-extension://${s.extensionId}/sidepanel.html`);
    await panel.waitForSelector('#read-product');
    assert.match(await panel.textContent('#panel-status'), /Deschide un produs/);
    assert.ok(await panel.isHidden('#product'));
    assert.equal(s.fake.state.requests.length, 0);
    assert.equal(await panel.locator('script:not([src])').count(), 0);
    const options = await panel.evaluate(() => chrome.sidePanel.getOptions({}));
    assert.equal(options.path, 'sidepanel.html');
    await panel.evaluate(() => document.addEventListener('securitypolicyviolation', (event) => { throw new Error(`${event.violatedDirective} ${event.blockedURI}`); }));
    await s.context.route('https://www.emag.ro/veioza-exemplu-40-cm/pd/DEMO123/**', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: html }));
    productPage = await s.context.newPage();
    await productPage.goto(PRODUCT_URL);
  });
  test('citește numai produsul activ și arată lipsa analizei fără date demo', async () => {
    await productPage.bringToFront();
    // Clic în DOM-ul panoului separat: fila produsului rămâne activă, ca în sidePanel nativ.
    await panel.evaluate(() => document.getElementById('read-product').click());
    await panel.waitForFunction(() => document.getElementById('product').hidden === false);
    await panel.waitForFunction(() => document.getElementById('panel-status').textContent === 'Nu există o analiză salvată.');
    assert.equal(await panel.textContent('#product-name'), PRODUCT_NAME);
    assert.match(await panel.textContent('#current-price'), /239,99/);
    assert.ok(await panel.isHidden('#match-label'));
  });
  test('comparația folosește registrul real după reduceri și refuză varianta cu altă dimensiune', async () => {
    const orders = await app.evaluate(async (name) => {
      const { makeOrder, makeSellerBlock, makeItem } = await import('./calcul/models.js');
      return [
        ['inventat-a', '2026-10-01', name, 22999],
        ['inventat-b', '2026-11-01', name, 28999],
        ['inventat-c', '2026-11-02', name.replace('40 cm', '60 cm'), 100],
      ].map(([order_id, placed_at, itemName, paid_bani]) => makeOrder({ order_id, placed_at, placed_text: placed_at,
        header_total_bani: paid_bani,
        blocks: [makeSellerBlock({ seller: 'Magazin inventat', status: 'DELIVERED', status_text: 'Livrat', has_storno: false,
          paid_bani, items: [makeItem(itemName, 35000, 1)] })] }));
    }, PRODUCT_NAME);
    await ctx.session.seedLastAnalysis(app, { orders, created_at: '2026-11-08 12:00:00' });
    await panel.waitForFunction(() => document.getElementById('match-label').hidden === false);
    assert.match(await panel.textContent('#last-price'), /289,99/);
    assert.match(await panel.textContent('#last-price'), /2026-11-01/);
    assert.match(await panel.textContent('#minimum-price'), /229,99/);
    assert.match(await panel.textContent('#difference'), /50,00 Lei sub/);
    assert.equal(await panel.textContent('#match-label'), 'Potrivire după denumire');
    mkdirSync(CAPTURES, { recursive: true });
    for (const theme of ['light', 'dark']) {
      await panel.evaluate((value) => {
        for (let i = 0; i < 3 && document.documentElement.dataset.theme !== value; i += 1) document.getElementById('theme-toggle').click();
      }, theme);
      await panel.setViewportSize({ width: 400, height: 900 });
      await panel.screenshot({ path: path.join(CAPTURES, `panou-chrome-400-comparatie-${theme}.png`), fullPage: true });
    }
  });
  test('salvează ținta criptată și actualizează aceeași identitate URL fără duplicat', async () => {
    await panel.locator('#target-price').fill('225,50');
    await productPage.bringToFront();
    await panel.evaluate(() => document.getElementById('target-form').requestSubmit());
    await panel.waitForFunction(() => document.getElementById('target-message').textContent === 'Ținta a fost salvată.');
    const saved = await panel.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
      const defaults = (await import('./generat/shopping_config.js')).default;
      const store = createShoppingStore({ defaults });
      try { return await store.read(); } finally { store.dispose(); }
    });
    assert.equal(saved.wishlist.length, 1);
    assert.equal(saved.wishlist[0].target_bani, 22550);
    assert.equal(saved.wishlist[0].selected, true);
    const stored = await panel.evaluate(() => chrome.storage.local.get());
    assert.ok(!JSON.stringify(stored).includes(PRODUCT_NAME), 'numele nu este stocat în clar');
    await panel.locator('#target-price').fill('210');
    await productPage.bringToFront();
    await panel.evaluate(() => document.getElementById('target-form').requestSubmit());
    await panel.waitForFunction(() => document.getElementById('target-message').textContent === 'Ținta a fost salvată.');
    const count = await panel.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
      const defaults = (await import('./generat/shopping_config.js')).default;
      const store = createShoppingStore({ defaults });
      try { return (await store.read()).wishlist.length; } finally { store.dispose(); }
    });
    assert.equal(count, 1);
  });
  test('suma invalidă este refuzată și starea rezistă la 320px în ambele teme', async () => {
    await panel.locator('#target-price').fill('2.999');
    await panel.evaluate(() => document.getElementById('target-form').requestSubmit());
    await panel.waitForFunction(() => document.getElementById('target-price').getAttribute('aria-invalid') === 'true');
    mkdirSync(CAPTURES, { recursive: true });
    for (const theme of ['light', 'dark']) {
      await panel.evaluate((value) => {
        for (let i = 0; i < 3 && document.documentElement.dataset.theme !== value; i += 1) document.getElementById('theme-toggle').click();
      }, theme);
      await panel.setViewportSize({ width: 320, height: 900 });
      assert.ok(await panel.evaluate(() => document.documentElement.scrollWidth <= innerWidth), theme);
      await panel.screenshot({ path: path.join(CAPTURES, `panou-chrome-320-${theme}.png`), fullPage: true });
    }
  });
  test('navigarea golește produsul și nu citește automat următoarea pagină', async () => {
    await productPage.goto(`${PRODUCT_URL}?varianta=noua`);
    await panel.waitForFunction(() => document.getElementById('product').hidden);
    assert.match(await panel.textContent('#panel-status'), /Fila s-a schimbat/);
  });
  test('tema aleasă persistă la reload; corupția datelor golește rezultatele și arată eroare', async () => {
    await panel.reload();
    assert.equal(await panel.getAttribute('html', 'data-theme'), 'dark');
    assert.equal(await panel.textContent('#theme-label'), 'Temă: întunecată');
    await productPage.bringToFront();
    await panel.evaluate(() => document.getElementById('read-product').click());
    await panel.waitForFunction(() => document.getElementById('match-label').hidden === false);
    const backup = await panel.evaluate(async () => {
      const { LAST_ANALYSIS_KEY } = await import('./stocare/last_analysis.js');
      const previous = (await chrome.storage.local.get(LAST_ANALYSIS_KEY))[LAST_ANALYSIS_KEY];
      const broken = { ...previous, ciphertext: `${previous.ciphertext[0] === 'A' ? 'B' : 'A'}${previous.ciphertext.slice(1)}` };
      await chrome.storage.local.set({ [LAST_ANALYSIS_KEY]: broken });
      return { key: LAST_ANALYSIS_KEY, previous };
    });
    await panel.waitForFunction(() => document.getElementById('product').hidden);
    assert.match(await panel.textContent('#panel-status'), /nu au putut fi citite/);
    await panel.evaluate(({ key, previous }) => chrome.storage.local.set({ [key]: previous }), backup);
  });
  test('ștergerea datelor golește și panoul, inclusiv rezultatele întârziate', async () => {
    await productPage.bringToFront();
    await panel.evaluate(() => document.getElementById('read-product').click());
    await panel.waitForFunction(() => document.getElementById('product').hidden === false);
    await panel.evaluate(async () => (await import('./stocare/last_analysis.js')).deleteAllData());
    await panel.waitForFunction(() => document.getElementById('product').hidden);
    assert.match(await panel.textContent('#panel-status'), /șterse/);
    assert.equal(await panel.inputValue('#target-price'), '');
    assert.equal(await panel.textContent('#read-product'), 'Reîncarcă panoul');
    await panel.locator('#read-product').click();
    await panel.waitForFunction(() => document.getElementById('read-product').textContent === 'Citește produsul');
    assert.ok(await panel.isHidden('#product'));
  });
  test('raportul complet reutilizează aplicația și API-ul nativ deschide context SIDE_PANEL', async () => {
    await panel.locator('#open-report').click();
    await app.waitForFunction(() => document.hasFocus());
    const windowId = await panel.evaluate(async () => (await chrome.windows.getCurrent()).id);
    // Buton exclusiv în harness pentru gestul de browser cerut de Chrome; nu intră în sursele extensiei.
    await panel.evaluate((id) => {
      const button = document.createElement('button');
      button.id = 'native-api-check';
      button.textContent = 'Probă API nativ';
      button.addEventListener('click', () => {
        chrome.sidePanel.open({ windowId: id }).then(() => { button.dataset.result = 'ok'; }, (error) => { button.dataset.result = error.message; });
      });
      document.body.append(button);
    }, windowId);
    await panel.locator('#native-api-check').click();
    await panel.waitForFunction(() => document.getElementById('native-api-check').dataset.result);
    assert.equal(await panel.getAttribute('#native-api-check', 'data-result'), 'ok');
    const contexts = await panel.evaluate(() => chrome.runtime.getContexts({ contextTypes: ['SIDE_PANEL'] }));
    assert.ok(contexts.some((context) => context.documentUrl.endsWith('/sidepanel.html')));
  });
});
