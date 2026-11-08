// Suprafețele web reale ale cumpărăturilor, în demo, pe WebKit și Firefox instalate.
// EXT_DIST_DIR: build propriu (implicit logs/functii-2026-11-08/ui-dist).
// AXE_CORE_PATH: biblioteca de audit deja instalată (implicit uneltele locale din logs).
// WEBKIT_EXECUTABLE: motor local (implicit webkit-2370 din LOCALAPPDATA).
// Serverul ascultă numai pe 127.0.0.1; fiecare cale trebuie să fie exact un fișier permis.
// Nu verifică API-uri Chrome, storage real sau sidepanel; nu modifică producția.
import assert from 'node:assert/strict';
import { after, before, describe, test } from 'node:test';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, firefox, webkit } from 'playwright-core';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const run = path.join(project, 'logs/functii-2026-11-08');
const dist = process.env.EXT_DIST_DIR ? path.resolve(process.env.EXT_DIST_DIR) : path.join(run, 'ui-dist');
const captures = path.join(project, 'docs/extensie/capturi/2026-11-08-implementare');
const axePath = process.env.AXE_CORE_PATH || path.join(run, 'browser-tools/node_modules/axe-core/axe.min.js');
const webkitExecutable = process.env.WEBKIT_EXECUTABLE || path.join(process.env.LOCALAPPDATA, 'ms-playwright/webkit-2370/Playwright.exe');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.json': 'application/json' };
const report = { engines: {}, checks: [], product: [], scanner: [], axe: [], issues: [], diagnostics: [], capture_issues: [], screenshots: [] };
let server; let base; let axe;

/** Enumeră numai căile reale ale fișierelor publice, fără normalizare care ar accepta aliasuri. */
async function publicFiles(dir, prefix = '') {
  const items = await fs.readdir(dir, { withFileTypes: true }); const result = [];
  for (const item of items) {
    if (item.name.startsWith('.') || item.isSymbolicLink()) continue;
    const relative = `${prefix}/${item.name}`;
    if (item.isDirectory()) result.push(...await publicFiles(path.join(dir, item.name), relative));
    else if (Object.hasOwn(mime, path.extname(item.name))) result.push(relative);
  }
  return result;
}

/** Creează doar intrarea demo a verificării, în build-ul de test. */
async function writeHarness() {
  await fs.writeFile(path.join(dist, 'shopping-surfaces.html'), `<!doctype html><html lang="ro" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cumpărături · verificare demo</title><link rel="icon" href="data:,"><link rel="stylesheet" href="partajat/app.css"><link rel="stylesheet" href="cumparaturi/shopping.css"><script src="partajat/demo-data.js" defer></script><script src="shopping-surfaces-entry.js" type="module"></script></head><body><main class="app-wrap"><h1>Cumpărături · date inventate</h1><section class="screen screen--report"><h2>Raportul tău</h2><div id="shopping-root"></div><div id="report-root"></div></section></main></body></html>`, 'utf8');
  await fs.writeFile(path.join(dist, 'shopping-surfaces-entry.js'), `import {mountShoppingApp} from './cumparaturi/shopping_app.js';\nimport raw from './generat/shopping_demo.js';\nimport defaults from './generat/shopping_config.js';\nconst entry={...raw,summary:window.EMAG_DEMO_DATA,created_at:window.EMAG_DEMO_DATA.meta.generated_at};\nwindow.surfaceApp=await mountShoppingApp(document.getElementById('shopping-root'),{entry,demo:true,defaults});\nwindow.surfaceReady=true;\n`, 'utf8');
}

before(async () => {
  await fs.mkdir(captures, { recursive: true }); await writeHarness(); axe = await fs.readFile(axePath, 'utf8');
  const allowed = new Set(await publicFiles(dist));
  server = http.createServer(async (req, res) => {
    const pathname = req.url.split('?')[0];
    if (req.method !== 'GET' || !allowed.has(pathname)) { res.writeHead(404); res.end(); return; }
    try {
      const bytes = await fs.readFile(path.join(dist, pathname.slice(1)));
      res.writeHead(200, { 'Content-Type': mime[path.extname(pathname)], 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'", 'Referrer-Policy': 'no-referrer' }); res.end(bytes);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve)); base = `http://127.0.0.1:${server.address().port}`;
  console.log(`SERVER DEMO ${base}/shopping-surfaces.html · fără cont și fără cereri externe`);
  for (const url of ['/.env', '/SHOPPING-SURFACES.html', '/shopping-surfaces.html::$DATA']) assert.equal((await fetch(base + url)).status, 404);
});

after(async () => {
  await new Promise((resolve) => server?.close(resolve));
  await fs.writeFile(path.join(run, '_meta/ui-motoare.json'), JSON.stringify(report, null, 2), 'utf8');
  console.log('SERVER DEMO OPRIT');
  if (report.screenshots.length) await makeContactSheet();
});

/** Scrie ca un utilizator; locatoarele primesc doar selectori stabili. */
async function enter(page, selector, value) {
  const node = page.locator(selector); await node.focus(); await node.press('ControlOrMeta+A'); await node.press('Backspace'); await node.pressSequentially(value);
}

/** Așteaptă montarea vederii, nu cereri care nu există în modul demo. */
async function section(page, name) {
  await page.click(`[data-section="${name}"]`); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
}

/** Verifică axe pe suprafața nouă, fără raportul de referință sau harness. */
async function accessibility(page, engine, width, theme, sectionName) {
  if (!await page.evaluate(() => Boolean(window.axe))) await page.evaluate(axe);
  const result = await page.evaluate(async () => window.axe.run(document.querySelector('#shopping-root'), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } }));
  report.axe.push({ engine, width, theme, section: sectionName, incomplete: result.incomplete.map(({ id, nodes }) => ({ id, count: nodes.length })), violations: result.violations.map(({ id, impact, nodes }) => ({ id, impact, nodes: nodes.map((node) => ({ target: node.target, failureSummary: node.failureSummary })) })) });
  assert.deepEqual(result.violations.map((item) => item.id), [], `${engine}/${width}/${theme}/${sectionName}: axe`);
}

/** Testează formularul, banii, selecția lunii, etichetele și PNG-ul exact. */
async function controls(page) {
  await section(page, 'campaign'); await page.locator('.shopping-editor summary').click();
  await enter(page, '[name="product-name"]', 'Boxă portabilă Mirova S2'); await enter(page, '[name="product-price"]', '219,99'); await enter(page, '[name="product-target"]', '225');
  await page.locator('.shopping-product-form button[type="submit"]').evaluate((button) => button.addEventListener('click', () => { window.surfaceFocusBeforeAdd = { inside: document.querySelector('#shopping-panel').contains(document.activeElement), tag: document.activeElement.tagName }; }, { once: true }));
  await page.locator('.shopping-product-form button[type="submit"]').click(); await page.waitForSelector('.shopping-item');
  const beforeAdd = await page.evaluate(() => window.surfaceFocusBeforeAdd);
  if (beforeAdd.inside) assert.equal(await page.evaluate(() => document.activeElement.dataset.section), 'campaign');
  else assert.equal(await page.evaluate(() => document.activeElement.tagName), beforeAdd.tag, 'clickul nativ fără focus nu îl mută artificial');
  await page.locator('.shopping-item-actions button').first().click(); await enter(page, '[name="product-target"]', '230'); await page.locator('[name="product-target"]').press('Enter');
  await page.waitForFunction(() => document.querySelector('.shopping-list')?.textContent.includes('230,00'));
  assert.equal(await page.evaluate(() => document.activeElement.dataset.section), 'campaign', 'Enter în editorul închis readuce focusul pe filă');
  assert.match(await page.textContent('.shopping-list'), /în țintă/); await page.locator('.shopping-check input').uncheck();
  await page.waitForFunction(() => document.querySelector('.shopping-list-budget')?.textContent.includes('0,00')); await page.locator('.shopping-check input').check();
  await section(page, 'budget'); await enter(page, '[name="budget"]', '-2'); await page.locator('.shopping-form button').focus();
  assert.equal(await page.getAttribute('[name="budget"]', 'aria-invalid'), 'true');
  await enter(page, '[name="budget"]', '6000');
  await page.locator('.shopping-form button').evaluate((button) => button.addEventListener('click', () => { window.surfaceFocusBeforeSave = document.activeElement.dataset.focus; }, { once: true }));
  await page.locator('.shopping-form button').click();
  await page.waitForFunction(() => document.querySelector('.shopping-metric--yellow')?.textContent.includes('1.390,49'));
  assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), await page.evaluate(() => window.surfaceFocusBeforeSave), 'focusul nativ al motorului se păstrează după click');
  await enter(page, '[name="budget"]', '6001'); await page.locator('[name="budget"]').press('Enter'); await page.waitForFunction(() => document.querySelector('.shopping-metric--yellow')?.textContent.includes('1.391,49'));
  assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), 'budget');
  await page.selectOption('[data-focus="month"]', '09'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view'); assert.equal(await page.inputValue('[name="budget"]'), '');
  await enter(page, '[name="budget"]', '1000'); await page.locator('[name="budget"]').press('Enter'); await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '1000,00');
  await page.selectOption('[data-focus="month"]', ''); await page.waitForFunction(() => document.querySelector('[name="budget"]')?.value === '6001,00');
  await section(page, 'tags');
}

/** Face o planșă din capturile nemodificate și închide browserul de compunere. */
async function makeContactSheet() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1832, height: 1000 } });
    const cells = await Promise.all(report.screenshots.map(async (item) => `<figure><figcaption>${item.engine} · ${item.section} · ${item.width}px · ${item.theme} · DEMO</figcaption><img alt="" src="data:image/png;base64,${(await fs.readFile(item.path)).toString('base64')}"></figure>`));
    await page.setContent(`<html lang="ro"><head><style>body{margin:0;padding:16px;background:#dfe2dc;font:14px Segoe UI,sans-serif}main{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}figure{margin:0;background:#fff;padding:8px;min-width:0}figcaption{font-weight:700;margin:0 0 8px}img{width:100%;height:auto;display:block}</style></head><body><main>${cells.join('')}</main></body></html>`);
    await page.locator('img').evaluateAll((images) => Promise.all(images.map((image) => image.decode())));
    const output = path.join(captures, 'plansa-webkit-firefox.png'); await page.screenshot({ path: output, fullPage: true }); console.log(`PLANȘĂ ${output}`);
  } finally { await browser.close(); }
}

for (const engine of ['WebKit', 'Firefox']) describe(engine, () => {
  let browser;
  before(async () => {
    browser = engine === 'WebKit' ? await webkit.launch({ headless: true, executablePath: webkitExecutable }) : await firefox.launch({ channel: 'moz-firefox', headless: true, firefoxUserPrefs: { 'ui.prefersReducedMotion': 1 } });
    report.engines[engine] = { version: browser.version(), executable: engine === 'WebKit' ? webkitExecutable : 'C:/Program Files/Mozilla Firefox/firefox.exe', protocol: engine === 'Firefox' ? 'WebDriver BiDi' : 'Playwright', extensionApi: false };
  });
  after(async () => browser?.close());
  for (const width of [1440, 1024, 390, 320]) for (const theme of ['light', 'dark']) test(`${width}px/${theme}: controls, layout, axe`, async () => {
    const issues = []; const context = await browser.newContext({ viewport: { width, height: width === 1024 ? 768 : 900 }, locale: 'ro-RO', ...(engine === 'WebKit' ? { reducedMotion: 'reduce', isMobile: width < 1024, hasTouch: width < 1024 } : {}) });
    try {
      const page = await context.newPage();
      await page.addInitScript(() => {
        window.surfaceStyles = []; window.surfaceViolations = [];
        new MutationObserver((changes) => { for (const change of changes) for (const node of change.addedNodes) if (node.nodeName === 'STYLE') window.surfaceStyles.push({ text: node.textContent, stage: window.surfaceStep }); }).observe(document, { childList: true, subtree: true });
        document.addEventListener('securitypolicyviolation', (event) => window.surfaceViolations.push({ directive: event.violatedDirective, source: event.sourceFile, line: event.lineNumber, sample: event.sample, stage: window.surfaceStep }));
      });
      page.on('console', (message) => { if (message.type() === 'error') issues.push(message.text()); }); page.on('pageerror', (error) => issues.push(error.message));
      page.on('requestfailed', (request) => issues.push(`requestfailed ${request.url()}`));
      await context.route('**/*', (route) => route.request().url().startsWith(base + '/') ? route.continue() : (issues.push(`extern ${route.request().url()}`), route.abort()));
      await page.goto(base + '/shopping-surfaces.html'); await page.waitForFunction(() => window.surfaceReady === true);
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      await page.evaluate(() => { window.surfaceStep = 'controls'; }); await controls(page);
      // O singură achiziție etichetată păstrează captura completă și filtrul real.
      await page.locator('.shopping-tag-form input').first().focus(); await page.locator('.shopping-tag-form input').first().pressSequentially('Pentru casă'); await page.locator('.shopping-tag-form button').first().click();
      await page.waitForFunction(() => !document.querySelector('.shopping-tag-form[aria-busy="true"]'));
      await page.selectOption('[data-focus="tag-filter"]', 'tag:Pentru casă'); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view'); assert.equal(await page.locator('.shopping-tag-item').count(), 1);
      await page.evaluate(() => { window.surfaceStep = 'layout-png'; });
      for (const name of ['campaign', 'budget', 'returns', 'tags', 'recap']) {
        await section(page, name);
        if (name === 'recap') {
          await page.selectOption('[data-focus="year"]', '2025'); await page.waitForSelector('#shopping-recap-card');
          const png = await page.locator('#shopping-recap-card').evaluate((canvas) => canvas.toDataURL('image/png'));
          assert.equal(Buffer.from(png.split(',')[1], 'base64').readUInt32BE(16), 880);
          await page.check('#shopping-hide-sum'); assert.ok(!(await page.getAttribute('#shopping-recap-card', 'aria-label')).includes('Plătit efectiv')); await page.uncheck('#shopping-hide-sum');
          const expected = await page.locator('#shopping-recap-card').evaluate((canvas) => canvas.toDataURL('image/png').split(',')[1]);
          const [download] = await Promise.all([page.waitForEvent('download'), page.click('#shopping-download-recap')]);
          assert.deepEqual(await fs.readFile(await download.path()), Buffer.from(expected, 'base64'));
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `${engine}/${width}/${theme}/${name}: overflow`);
      }
      report.diagnostics.push({ engine, width, theme, beforeAxe: await page.evaluate(() => ({ styles: window.surfaceStyles, csp: window.surfaceViolations })) });
      const productIssues = issues.slice();
      report.product.push({ engine, width, theme, controls: 'PASS', layout: 'PASS', focus: 'PASS', png: 'PASS', errors: productIssues });
      for (const name of ['campaign', 'budget', 'returns', 'tags', 'recap']) { await section(page, name); await accessibility(page, engine, width, theme, name); }
      const scannerIssues = issues.slice(productIssues.length); report.scanner.push({ engine, width, theme, errors: scannerIssues });
      const beforeCaptures = issues.length;
      if ((width === 1440 && theme === 'dark') || (width === 390 && theme === 'light')) {
        for (const name of ['campaign', 'budget', 'returns', 'tags', 'recap']) {
          await section(page, name);
          const imagePath = path.join(captures, `${engine.toLowerCase()}-${name}-${theme}-${width}.png`); await page.locator('#shopping-root').screenshot({ path: imagePath, caret: 'initial', animations: 'allow' }); report.screenshots.push({ engine, section: name, width, theme, path: imagePath });
        }
        // Firefox: Playwright injectează "body {}" pentru sincronizarea capturii,
        // inclusiv cu animations:allow/caret:initial. CSP-ul strict îl refuză.
        // Păstrăm separat proba exactă a uneltei, după testul curat al produsului.
        for (const text of issues.slice(beforeCaptures)) report.capture_issues.push({ engine, width, theme, text });
      }
      assert.deepEqual(productIssues, [], 'faza produs, înainte de axe și capturi (CSP strict)');
      assert.deepEqual(scannerIssues, [], 'faza scanner, înainte de capturi');
      report.checks.push({ engine, width, theme, result: 'PASS' });
    } catch (error) { report.checks.push({ engine, width, theme, result: 'FAIL', error: error.message }); throw error; }
    finally { report.issues.push(...issues.map((text) => ({ engine, width, theme, text }))); await context.close(); }
  });
});

test('WebKit native CSP probe', async () => {
  const browser = await webkit.launch({ headless: true, executablePath: webkitExecutable });
  try {
    const page = await browser.newPage(); await page.goto(base + '/shopping-surfaces.html'); await page.waitForFunction(() => window.surfaceReady);
    const result = await page.evaluate(async () => {
      window.surfaceApp.dispose(); document.body.replaceChildren();
      const violations = []; document.addEventListener('securitypolicyviolation', (event) => violations.push({ directive: event.violatedDirective, source: event.sourceFile }));
      const findings = [];
      for (const [tag, type] of [['button', ''], ['input', 'text'], ['input', 'date'], ['input', 'checkbox'], ['progress', ''], ['select', '']]) {
        const before = violations.length; const node = document.createElement(tag); if (type) node.type = type; if (tag === 'progress') { node.max = 100; node.value = 20; } document.body.append(node);
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        findings.push({ tag, type, violations: violations.slice(before) }); node.remove();
      }
      return findings;
    });
    report.nativeProbe = result; console.log('WEBKIT NATIVE PROBE ' + JSON.stringify(result));
  } finally { await browser.close(); }
});
