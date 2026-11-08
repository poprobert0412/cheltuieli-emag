// Fluxurile reale de cumpărături pe extensia construită, cu date inventate și rețeaua blocată.
// EXT_DIST_DIR alege build-ul; SHOPPING_SCREENSHOTS=1 salvează dovezile în folderul etapei aprobate.
// SHOPPING_CLOCK_BEFORE=1 capturează build-ul vechi înaintea aserțiunii noi, care rămâne roșie.
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { scenario } from './harness.js';
import { decodePng } from '../unit/png_decoder.js';

const CAPTURES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/extensie/capturi/2026-11-08-implementare');

/** Scrie prin tastatură pentru a verifica aceleași evenimente ca utilizatorul. */
async function enter(page, selector, value) { const node = page.locator(selector); await node.focus(); await node.press('ControlOrMeta+A'); await node.press('Backspace'); await node.pressSequentially(value); }

/** Așteaptă încheierea montării secțiunii. */
async function section(page, name) { await page.click(`[data-section="${name}"]`); await page.waitForSelector('#shopping-panel:not([aria-busy="true"]) .shopping-view'); }

scenario('cumpărături: formulare, etichete, PNG și demo izolat', {}, (ctx) => {
  let page;
  test('deschide demo-ul și păstrează raportul implicit', async () => {
    page = await ctx.session.openApp(); await ctx.session.screen(page, 'ready'); await page.click('#btn-demo'); await ctx.session.screen(page, 'done');
    await page.waitForSelector('[data-section="campaign"]:not([disabled])');
    assert.equal(await page.isVisible('#report-root'), true); assert.equal(await page.getAttribute('[data-section="report"]', 'aria-pressed'), 'true');
  });
  test('lista: validează la blur, salvează, editează și selectează', async () => {
    await section(page, 'campaign'); await page.locator('.shopping-editor summary').click();
    await enter(page, '[name="product-name"]', 'Căști inventate <img src=x>');
    await enter(page, '[name="product-url"]', 'javascript:alert(1)'); await page.locator('[name="product-price"]').focus();
    assert.equal(await page.getAttribute('[name="product-url"]', 'aria-invalid'), 'true');
    await enter(page, '[name="product-url"]', 'https://www.emag.ro/casti-inventate/pd/EXEMPLU12/');
    await enter(page, '[name="product-price"]', '219,99'); await enter(page, '[name="product-target"]', '199,99');
    await page.locator('.shopping-product-form button[type="submit"]').click();
    await page.waitForSelector('.shopping-item'); assert.match(await page.textContent('.shopping-list'), /Căști inventate <img src=x>/);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.section), 'campaign', 'formularul închis readuce focusul pe fila activă');
    assert.equal(await page.locator('.shopping-list img').count(), 0); assert.match(await page.textContent('.shopping-list-budget'), /219,99/);
    await page.locator('.shopping-item-actions button').first().click();
    await enter(page, '[name="product-target"]', '225'); await page.locator('.shopping-product-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.shopping-list')?.textContent.includes('225,00'));
    assert.match(await page.textContent('.shopping-list'), /în țintă/);
    await page.locator('.shopping-item-actions button').first().click();
    await enter(page, '[name="product-name"]', 'Căști wireless Noria H2'); await page.locator('.shopping-product-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.shopping-list')?.textContent.includes('Căști wireless Noria H2'));
    await page.locator('.shopping-check input').uncheck(); await page.waitForFunction(() => document.querySelector('.shopping-list-budget')?.textContent.includes('0,00'));
    await page.locator('.shopping-check input').check();
  });
  test('buget anual și lunar folosesc date reale, fără implicit financiar', async () => {
    await section(page, 'budget'); assert.equal(await page.inputValue('[name="budget"]'), '');
    await enter(page, '[name="budget"]', '6000'); await page.locator('.shopping-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.shopping-metric--yellow')?.textContent.includes('1.390,49'));
    assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), 'submit-budget', 'click Salvează păstrează focusul pe butonul înlocuit');
    await enter(page, '[name="budget"]', '6001'); await page.locator('[name="budget"]').press('Enter');
    await page.waitForFunction(() => document.querySelector('.shopping-metric--yellow')?.textContent.includes('1.391,49'));
    assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), 'budget', 'Enter păstrează focusul în câmp');
    await enter(page, '[name="budget"]', '6000'); await page.locator('[name="budget"]').press('Enter');
    await page.waitForFunction(() => document.querySelector('.shopping-metric--yellow')?.textContent.includes('1.390,49'));
    assert.match(await page.textContent('.shopping-grid'), /2.814,95/);
    await page.selectOption('[data-focus="month"]', '09'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
    await enter(page, '[name="budget"]', '1000'); await page.locator('.shopping-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '1000,00');
    await page.selectOption('[data-focus="month"]', ''); await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '6000,00');
  });
  test('etichetele se salvează pe achiziție și filtrul funcționează', async () => {
    await section(page, 'tags');
    const name = await page.locator('.shopping-tag-item .shopping-item-name').first().textContent();
    const first = page.locator('.shopping-tag-form input').first(); await first.focus(); await first.pressSequentially('Vacanță inventată');
    await page.locator('.shopping-tag-form button').first().click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-focus="tag-filter"] option')].some((o) => o.value === 'tag:Vacanță inventată'));
    await page.selectOption('[data-focus="tag-filter"]', 'tag:Vacanță inventată'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
    assert.equal(await page.locator('.shopping-tag-item').count(), 1); assert.equal(await page.locator('.shopping-tag-item .shopping-item-name').textContent(), name);
    assert.match(await page.textContent('.shopping-metric'), /82.865,71/);
    await enter(page, '.shopping-tag-form input', '__untagged'); await page.locator('.shopping-tag-form button').click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-focus="tag-filter"] option')].some((o) => o.value === 'tag:__untagged'));
    await page.selectOption('[data-focus="tag-filter"]', 'tag:__untagged'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
    assert.equal(await page.locator('.shopping-tag-item').count(), 1, 'eticheta liberă __untagged este distinctă de filtrul intern');
    assert.equal(await page.locator('.shopping-tag-item .shopping-item-name').textContent(), name);
    await page.selectOption('[data-focus="tag-filter"]', 'untagged'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
    assert.ok((await page.locator('.shopping-tag-item').count()) > 1);
  });
  test('retururi: arată analiza și numai linkuri eMAG validate', async () => {
    await section(page, 'returns'); assert.equal(await page.locator('.shopping-return').count(), 2); assert.match(await page.textContent('.shopping-view'), /2026-10-04/);
    assert.equal(await page.locator('.shopping-return a').count(), 0, 'demo nu deschide retururi fictive');
  });
  test('PNG-ul are exact pixelii cardului vizibil și suma ascunsă dispare', async () => {
    await section(page, 'recap'); await page.selectOption('[data-focus="year"]', '2025'); await page.waitForSelector('#shopping-recap-card');
    await page.check('#shopping-hide-sum'); assert.ok(!(await page.getAttribute('#shopping-recap-card', 'aria-label')).includes('Plătit efectiv'));
    const expected = await page.locator('#shopping-recap-card').evaluate((canvas) => canvas.toDataURL('image/png').split(',')[1]);
    const [download] = await Promise.all([page.waitForEvent('download'), page.click('#shopping-download-recap')]);
    const png = readFileSync(await download.path());
    const actualPixels = decodePng(png); const previewPixels = decodePng(Buffer.from(expected, 'base64'));
    for (let y = 0; y < actualPixels.height; y += 1) for (let x = 0; x < actualPixels.width; x += 1) assert.deepEqual(actualPixels.pixel(x, y), previewPixels.pixel(x, y), `pixel ${x},${y}`);
    assert.equal(png.readUInt32BE(16), 880); assert.equal(png.readUInt32BE(20), 748); assert.equal(download.suggestedFilename(), 'bilant-2025.png');
  });
  test('secțiuni fără overflow la 320px, focus tastatură și capturi în ambele teme', async () => {
    if (process.env.SHOPPING_SCREENSHOTS) mkdirSync(CAPTURES, { recursive: true });
    for (const theme of ['light', 'dark']) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      for (const width of [320, 1180]) {
        await page.setViewportSize({ width, height: 900 });
        for (const name of ['campaign', 'budget', 'returns', 'tags', 'recap']) {
          await section(page, name);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `${name}/${theme}/${width}: overflow`);
          if (process.env.SHOPPING_SCREENSHOTS && (width === 1180 || theme === 'light')) await page.locator('#shopping-root').screenshot({ path: path.join(CAPTURES, `${name}-${theme}-${width}.png`), animations: 'disabled' });
        }
      }
    }
    await page.locator('[data-section="campaign"]').focus(); await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.section), 'budget');
  });
  test('demo nu persistă; o nouă intrare începe cu lista goală', async () => {
    assert.deepEqual(await ctx.session.storage(page), {});
    await page.click('#btn-again'); await ctx.session.screen(page, 'ready'); await page.click('#btn-demo'); await page.waitForSelector('[data-section="campaign"]:not([disabled])');
    await section(page, 'campaign'); assert.equal(await page.locator('.shopping-item').count(), 0); assert.deepEqual(await ctx.session.storage(page), {});
  });
});

scenario('cumpărături: persistență criptată, sincronizare și ștergere între pagini', {}, (ctx) => {
  let first; let second;
  test('salvează în aplicația reală și vede aceeași listă în altă pagină', async () => {
    const s = ctx.session; first = await s.openApp(); await s.screen(first, 'ready');
    const raw = await first.evaluate(async () => (await import('./generat/shopping_demo.js')).default);
    await s.seedLastAnalysis(first, raw); await first.reload(); await s.screen(first, 'done'); await first.waitForSelector('[data-section="campaign"]:not([disabled])');
    await section(first, 'campaign'); await first.locator('.shopping-editor summary').click();
    await enter(first, '[name="product-name"]', 'Boxă portabilă inventată'); await enter(first, '[name="product-target"]', '180'); await first.locator('.shopping-product-form button[type="submit"]').click(); await first.waitForSelector('.shopping-item');
    assert.equal(await first.evaluate(async () => JSON.stringify(await chrome.storage.local.get()).includes('Boxă portabilă inventată')), false, 'numele nu este stocat în clar');
    second = await s.openApp(); await s.screen(second, 'done'); await second.waitForSelector('[data-section="campaign"]:not([disabled])'); await section(second, 'campaign');
    assert.match(await second.textContent('.shopping-list'), /Boxă portabilă inventată/);
    await second.locator('.shopping-item-actions button').first().click(); await enter(second, '[name="product-target"]', '190'); await second.locator('.shopping-product-form button[type="submit"]').click();
    await first.waitForFunction(() => document.querySelector('.shopping-list')?.textContent.includes('190,00'));
  });
  test('bugetul și eticheta supraviețuiesc reîncărcării și ajung în cealaltă pagină', async () => {
    await section(first, 'budget'); await enter(first, '[name="budget"]', '6000'); await first.locator('.shopping-form button[type="submit"]').click(); await first.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '6000,00');
    await section(second, 'budget'); assert.equal(await second.inputValue('[name="budget"]'), '6000,00');
    await section(first, 'tags'); await first.locator('.shopping-tag-form input').first().focus(); await first.locator('.shopping-tag-form input').first().pressSequentially('Muncă'); await first.locator('.shopping-tag-form button').first().click();
    await first.waitForFunction(() => !document.querySelector('.shopping-tag-form[aria-busy="true"]'));
    await section(second, 'tags'); await second.waitForFunction(() => document.querySelector('.shopping-tag-form input')?.value === 'Muncă');
    await first.reload(); await ctx.session.screen(first, 'done'); await first.waitForSelector('[data-section="campaign"]:not([disabled])'); await section(first, 'campaign');
    assert.match(await first.textContent('.shopping-list'), /190,00/);
    await section(first, 'budget'); assert.equal(await first.inputValue('[name="budget"]'), '6000,00');
    await section(first, 'tags'); assert.equal(await first.locator('.shopping-tag-form input').first().inputValue(), 'Muncă');
  });
  test('retururile reale au numai legături de cont validate', async () => {
    await section(first, 'returns'); assert.equal(await first.locator('.shopping-return a').count(), 2);
    for (const href of await first.locator('.shopping-return a').evaluateAll((links) => links.map((a) => a.href))) assert.match(href, /^https:\/\/www\.emag\.ro\/user\/return-history\/\d+\/\d+$/);
  });
  test('montarea anulată nu poate goli montarea nouă sau lăsa navigație veche', async () => {
    const result = await first.evaluate(async () => {
      const { mountShoppingApp } = await import('./cumparaturi/shopping_app.js'); const { default: defaults } = await import('./generat/shopping_config.js');
      const entry = { ...(await import('./generat/shopping_demo.js')).default, summary: window.EMAG_DEMO_DATA };
      const outer = document.createElement('div'); const host = document.createElement('div'); outer.append(host); document.body.append(outer);
      const controller = new AbortController(); const pending = mountShoppingApp(host, { entry, demo: true, defaults, signal: controller.signal }); controller.abort();
      const fresh = await mountShoppingApp(host, { entry, demo: true, defaults }); const old = await pending; old.dispose();
      const count = host.querySelectorAll('.shopping-nav').length; fresh.dispose(); const after = host.childElementCount; outer.remove(); return { count, after };
    });
    assert.deepEqual(result, { count: 1, after: 0 });
  });
  test('ștergerea curăță ambele pagini și refuză rescrierea prin consumator vechi', async () => {
    await second.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js'); const { default: defaults } = await import('./generat/shopping_config.js');
      window.__oldShopping = createShoppingStore({ defaults }); await window.__oldShopping.read();
    });
    await first.click('#btn-delete-data'); await first.click('#btn-delete-confirm'); await ctx.session.screen(first, 'ready'); await ctx.session.screen(second, 'ready');
    assert.equal(await second.locator('.shopping-nav').count(), 0); assert.deepEqual(await ctx.session.storage(first), {});
    const rejected = await second.evaluate(async () => { try { await window.__oldShopping.update((draft) => { draft.budgets['2026'] = 1; }); return false; } catch { return true; } finally { window.__oldShopping.dispose(); delete window.__oldShopping; } });
    assert.equal(rejected, true); assert.deepEqual(await ctx.session.storage(first), {});
  });
});

scenario('buget fără comenzi: anul curent și anii salvați', {}, (ctx) => {
  test('setează și păstrează un buget înaintea primei comenzi din an', async () => {
    const s = ctx.session; const page = await s.openApp(); await s.screen(page, 'ready');
    const empty = await page.evaluate(async () => {
      const { loadAnalysis } = await import('./rulare/analysis_loader.js'); const engine = await loadAnalysis();
      const threshold = window.EMAG_DEMO_DATA.meta.threshold_bani;
      return engine.plainSummary(engine.analyze([], [], threshold, window.EMAG_DEMO_DATA.meta.generated_at).summary);
    });
    await s.seedLastAnalysis(page, { orders: [], returns: [], summary: empty });
    const year = await page.evaluate(async () => {
      const current = new Intl.DateTimeFormat('ro-RO', { year: 'numeric', timeZone: 'Europe/Bucharest' }).format(new Date());
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js'); const { default: defaults } = await import('./generat/shopping_config.js');
      const store = createShoppingStore({ defaults });
      try { await store.update((draft) => { draft.budgets[String(Number(current) - 2)] = 120000; draft.budgets[`${Number(current) - 1}-01`] = 45000; }); } finally { store.dispose(); }
      return current;
    });
    await page.reload(); await s.screen(page, 'done'); await page.waitForSelector('[data-section="budget"]:not([disabled])'); await section(page, 'budget');
    assert.equal(await page.locator('[name="budget"]').count(), 1, 'bugetul este editabil și fără ani de comenzi');
    assert.deepEqual(await page.locator('[data-focus="year"] option').evaluateAll((items) => items.map((item) => item.value)), [year, String(Number(year) - 1), String(Number(year) - 2)]);
    assert.equal(await page.inputValue('[name="budget"]'), '', 'nu există sumă implicită');
    assert.match(await page.textContent('.shopping-metric--yellow'), /0,00 Lei plătit efectiv/);
    await enter(page, '[name="budget"]', '1500'); await page.locator('.shopping-form button').click(); await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '1500,00');
    assert.match(await page.textContent('.shopping-metric--yellow'), /1.500,00 Lei/);
    await page.reload(); await s.screen(page, 'done'); await page.waitForSelector('[data-section="budget"]:not([disabled])'); await section(page, 'budget');
    assert.equal(await page.inputValue('[name="budget"]'), '1500,00');
    await page.selectOption('[data-focus="year"]', String(Number(year) - 2)); await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '1200,00');
    await page.selectOption('[data-focus="year"]', String(Number(year) - 1)); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view'); await page.selectOption('[data-focus="month"]', '01');
    await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '450,00');
  });
});

scenario('Black Friday: ore RO și capăt exclusiv', {}, (ctx) => {
  let page;
  test('include exact începutul, exclude înaintea lui și ora de sfârșit', async () => {
    const s = ctx.session; page = await s.openApp(); await s.screen(page, 'ready');
    const fixture = await page.evaluate(async () => {
      const raw = (await import('./generat/shopping_demo.js')).default;
      const instants = ['2031-02-14T01:00', '2031-02-14T07:59:59', '2031-02-14T08:00', '2031-02-14T08:01', '2031-02-15T09:59:59', '2031-02-15T10:00', '2031-02-14', null];
      const orders = instants.map((placed_at, index) => {
        const order = structuredClone(raw.orders[0]); const block = structuredClone(order.blocks[0]);
        block.seller = 'Magazin Inventat SRL'; block.items = [{ name: 'Produs inventat pentru interval', line_total_bani: 10000, qty: 1 }];
        block.products_total_bani = 10000; block.vouchers_bani = []; block.shipping_bani = 0; block.services_bani = []; block.other_bani = []; block.paid_bani = 10000;
        return { ...order, order_id: String(920000000 + index), placed_at, placed_text: placed_at ?? '', header_total_bani: 10000, blocks: [block], warnings: [] };
      });
      const { loadAnalysis } = await import('./rulare/analysis_loader.js'); const engine = await loadAnalysis();
      const summary = engine.plainSummary(engine.analyze(orders, [], window.EMAG_DEMO_DATA.meta.threshold_bani, window.EMAG_DEMO_DATA.meta.generated_at).summary);
      return { orders, returns: [], summary };
    });
    await s.seedLastAnalysis(page, fixture); await page.reload(); await s.screen(page, 'done'); await page.waitForSelector('[data-section="campaign"]:not([disabled])'); await section(page, 'campaign');
    await page.locator('[name="from"]').fill('2031-02-14'); await page.locator('[name="to"]').fill('2031-02-15');
    if (process.env.SHOPPING_CLOCK_BEFORE) {
      await page.locator('.shopping-campaign-settings button').click(); await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-metric strong')?.textContent === '7');
      mkdirSync(CAPTURES, { recursive: true });
      for (const theme of ['light', 'dark']) {
        await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
        for (const width of [1180, 320]) { await page.setViewportSize({ width, height: 900 }); await page.locator('#shopping-root').screenshot({ path: path.join(CAPTURES, `campaign-ore-inainte-${theme}-${width}.png`), animations: 'disabled' }); }
      }
    }
    assert.equal(await page.locator('[name="start-time"]').count(), 1); assert.equal(await page.getAttribute('[name="start-time"]', 'type'), 'text');
    assert.equal(await page.getAttribute('[name="start-time"]', 'placeholder'), 'HH:mm');
    await enter(page, '[name="start-time"]', '08:00'); await enter(page, '[name="end-time"]', '10:00'); await page.locator('.shopping-campaign-settings button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-metric strong')?.textContent === '3');
    assert.match(await page.textContent('.shopping-campaign-recap'), /300,00 Lei/);
    assert.match(await page.textContent('.shopping-campaign-recap'), /Comenzi fără oră sigură, neincluse: 1/);
    assert.match(await page.textContent('.shopping-campaign-recap'), /Comenzi fără dată, neincluse: 1/);
    assert.match(await page.textContent('.shopping-campaign-timezone'), /Ora României.*Sfârșitul ales nu intră/);
    await enter(page, '[name="end-time"]', '10:01'); await page.locator('[name="end-time"]').press('Enter');
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-metric strong')?.textContent === '4');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), 'end-time');
    await enter(page, '[name="end-time"]', '10:00'); await page.locator('[name="end-time"]').press('Enter');
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-metric strong')?.textContent === '3');
  });
  test('validează orele la blur și refuză sfârșitul egal cu începutul', async () => {
    await enter(page, '[name="start-time"]', '24:00'); await page.locator('[name="end-time"]').focus();
    assert.equal(await page.getAttribute('[name="start-time"]', 'aria-invalid'), 'true');
    await page.locator('.shopping-campaign-settings button').click(); assert.equal(await page.evaluate(() => document.activeElement.name), 'start-time');
    await enter(page, '[name="start-time"]', '08:00'); await page.locator('[name="to"]').fill('2031-02-14'); await enter(page, '[name="end-time"]', '08:00'); await page.locator('[name="campaign-budget"]').focus();
    assert.equal(await page.getAttribute('[name="end-time"]', 'aria-invalid'), 'true'); assert.match(await page.textContent('#shopping-end-time-error'), /după început/);
    await page.locator('.shopping-campaign-settings button').click(); assert.equal(await page.evaluate(() => document.activeElement.name), 'end-time');
    await page.locator('[name="to"]').fill('2031-02-15'); await enter(page, '[name="end-time"]', '10:00'); await page.locator('[name="end-time"]').press('Enter');
    await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
  });
  test('orele lipsă cer completare și nu afișează un zero financiar', async () => {
    await page.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js'); const { default: defaults } = await import('./generat/shopping_config.js'); const store = createShoppingStore({ defaults });
      try { await store.update((draft) => { draft.campaign.start_time = null; draft.campaign.end_time = null; }); } finally { store.dispose(); }
    });
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap')?.textContent.includes('Alege ora de început'));
    assert.equal(await page.locator('.shopping-campaign-recap .shopping-metric').count(), 0); assert.equal(await page.inputValue('[name="start-time"]'), '');
    await enter(page, '[name="start-time"]', '08:00'); await enter(page, '[name="end-time"]', '10:00'); await page.locator('.shopping-campaign-settings button').click();
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-metric strong')?.textContent === '3');
  });
  test('păstrează câmpurile 24h și focusul la 320px, în ambele teme', async () => {
    for (const theme of ['light', 'dark']) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      for (const width of [1180, 320]) {
        await page.setViewportSize({ width, height: 900 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
        assert.equal(await page.inputValue('[name="start-time"]'), '08:00'); assert.equal(await page.inputValue('[name="end-time"]'), '10:00');
        await page.locator('[name="start-time"]').focus(); await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => document.activeElement.name), 'to');
        if (process.env.SHOPPING_SCREENSHOTS) { mkdirSync(CAPTURES, { recursive: true }); await page.locator('#shopping-root').screenshot({ path: path.join(CAPTURES, `campaign-ore-${theme}-${width}.png`), animations: 'disabled' }); }
      }
    }
  });
});
