// Audit axe pe panoul real Edge, cu produs inventat și rețea blocată de harness.
// AXE_CORE_PATH trebuie să indice biblioteca axe-core instalată separat pentru testare.
// EXT_DIST_DIR alege pachetul verificat; testul nu schimbă extensia ori profilul personal.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { scenario } from '../e2e/harness.js';

const axe = readFileSync(process.env.AXE_CORE_PATH, 'utf8');
const PRODUCT_URL = 'https://www.emag.ro/produs-inventat-lumina/pd/TESTAXE/';
const PRODUCT_NAME = 'Lampă inventată de birou';
const productMarkup = `<!doctype html><html><head><meta charset="utf-8"><link rel="canonical" href="${PRODUCT_URL}"><script type="application/ld+json">${JSON.stringify({ '@type': 'Product', name: PRODUCT_NAME, url: PRODUCT_URL, offers: { '@type': 'Offer', price: '149.50', priceCurrency: 'RON', url: PRODUCT_URL } })}</script></head><body><h1>${PRODUCT_NAME}</h1></body></html>`;

/** Verifică ambele teme la lățimea panoului, inclusiv erorile deja afișate. */
async function auditPanel(panel) {
  await panel.evaluate(axe);
  for (const theme of ['light', 'dark']) {
    await panel.evaluate((wanted) => {
      for (let n = 0; n < 3 && document.documentElement.dataset.theme !== wanted; n += 1) document.getElementById('theme-toggle').click();
    }, theme);
    for (const width of [320, 400]) {
      await panel.setViewportSize({ width, height: 900 });
      const result = await panel.evaluate(() => window.axe.run({ runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } }));
      assert.deepEqual(result.violations.map(({ id, nodes }) => ({ id, targets: nodes.map((node) => node.target) })), [], `${theme}/${width}`);
      assert.deepEqual(result.incomplete.map(({ id }) => id), [], `${theme}/${width}: verificări incomplete`);
    }
  }
}

scenario('panou: accesibilitate în browserul extensiei', {}, (ctx) => {
  let panel;
  test('starea inițială are controale accesibile în ambele teme', async () => {
    panel = await ctx.session.context.newPage();
    await panel.goto(`chrome-extension://${ctx.session.extensionId}/sidepanel.html`);
    await panel.waitForSelector('#read-product');
    await auditPanel(panel);
  });
  test('produsul și eroarea prețului-țintă păstrează etichete, contrast și ținte de apăsare', async () => {
    await ctx.session.context.route(PRODUCT_URL, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: productMarkup }));
    const page = await ctx.session.context.newPage();
    await page.goto(PRODUCT_URL);
    await page.bringToFront();
    await panel.evaluate(() => document.getElementById('read-product').click());
    await panel.waitForFunction(() => !document.getElementById('product').hidden);
    await panel.evaluate(() => document.getElementById('target-form').requestSubmit());
    await panel.waitForSelector('#target-price[aria-invalid="true"]');
    await auditPanel(panel);
  });
});
