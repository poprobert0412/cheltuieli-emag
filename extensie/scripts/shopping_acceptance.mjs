// Acceptanța celor șase funcții în contextul temporar deja autentificat al runnerului.
// Primește context/pagină, analiza curentă și un folder privat; întoarce numai verdicte, verificări și numărători.
// Nu autentifică, nu citește profil/cookie-uri, nu face capturi și nu tipărește produse, identificatori ori sume.
// Preferințele de probă sunt restaurate în finally; oracolul pe ore este independent de calendarul aplicației.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

// Limite tehnice: timpul de montare al raportului și domeniul global al offseturilor de fus orar.
const UI_TIMEOUT_MS = 30_000;
const MAX_UTC_OFFSET_HOURS = 14;
const HOUR_MS = 3_600_000;
const RETURN_KINDS = new Set(['pending_return_without_result', 'completed_return_without_refund']);
class AcceptanceCheckError extends Error {}

/** Eșec fără valori din cont în mesaj sau în stack-ul unei biblioteci. */
function requireCheck(condition, code) { if (!condition) throw new AcceptanceCheckError(code); }

/** Formatare independentă în fusul configurat, fără fusul sistemului de operare. */
function wallTime(milliseconds, timeZone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(milliseconds)).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

/** Convertește o oră locală numai când există exact o instanță, inclusiv la schimbarea DST. */
function localInstant(stamp, zone) {
  const nominal = Date.parse(`${stamp}Z`);
  if (!Number.isFinite(nominal)) return null;
  const found = [];
  for (let offset = -MAX_UTC_OFFSET_HOURS; offset <= MAX_UTC_OFFSET_HOURS; offset += 1) {
    const instant = nominal + offset * HOUR_MS;
    if (wallTime(instant, zone) === stamp) found.push(instant);
  }
  return found.length === 1 ? found[0] : null;
}

/** Oracol precis al momentului unei comenzi; ziua fără oră nu este transformată în miezul nopții. */
function independentTimestamp(value, zone) {
  const match = typeof value === 'string' && /^(\d{4}-\d{2}-\d{2})T((?:[01]\d|2[0-3]):[0-5]\d)(?::([0-5]\d)(?:\.(\d{1,3}))?)?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$/.exec(value);
  if (!match) return null;
  const [, day, time, seconds = '00', fraction = '', offset] = match;
  if (new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) return null;
  if (offset) { const parsed = Date.parse(value); return Number.isFinite(parsed) ? parsed : null; }
  const instant = localInstant(`${day}T${time}:${seconds}`, zone);
  return instant === null ? null : instant + Number(fraction.padEnd(3, '0'));
}

/** Adună alocările motorului complet pentru o selecție independentă de comenzi. */
function allocationTotals(orders, allocations) {
  const ledger = new Map(allocations);
  let paid = 0; let pending = 0;
  for (const order of orders) {
    const row = ledger.get(order.order_id);
    requireCheck(Number.isSafeInteger(row?.spent_bani) && Number.isSafeInteger(row?.in_progress_bani), 'ledger_allocation_missing');
    paid += row.spent_bani; pending += row.in_progress_bani;
  }
  requireCheck(Number.isSafeInteger(paid) && Number.isSafeInteger(pending), 'ledger_total_overflow');
  return { orders: orders.length, paid, pending };
}

/** Oracol exportat pentru fixture-uri: selecție strictă [început,sfârșit), fără reutilizarea shoppingCampaign. */
export function campaignOracle(orders, allocations, campaign) {
  const start = localInstant(`${campaign.from}T${campaign.start_time}:00`, campaign.time_zone);
  const end = localInstant(`${campaign.to}T${campaign.end_time}:00`, campaign.time_zone);
  requireCheck(start !== null && end !== null && start < end, 'campaign_boundary_invalid');
  const selected = []; let missingTimes = 0; let missingDates = 0;
  for (const order of orders) {
    const instant = independentTimestamp(order.placed_at, campaign.time_zone);
    if (instant !== null) { if (instant >= start && instant < end) selected.push(order); continue; }
    const day = typeof order.placed_at === 'string' ? order.placed_at.slice(0, 10) : '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) missingDates += 1;
    else if (day >= campaign.from && (day < campaign.to || (day === campaign.to && campaign.end_time !== '00:00'))) missingTimes += 1;
  }
  return { ...allocationTotals(selected, allocations), missingTimes, missingDates };
}

/** Montează secțiunea prin controalele reale și refuză o eroare afișată. */
async function section(page, name) {
  await page.locator(`[data-section="${name}"]:not([disabled])`).click();
  await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view', { timeout: UI_TIMEOUT_MS });
  requireCheck(await page.locator('#shopping-panel .shopping-error').count() === 0, 'ui_section_error');
}

/** Scrie prin tastatură pentru a folosi aceleași validări ca utilizatorul. */
async function enter(page, selector, value) {
  const input = page.locator(selector); await input.focus(); await input.press('ControlOrMeta+A'); await input.press('Backspace'); await input.pressSequentially(value);
}

/** Citește preferințele autentificate, fără a le scoate în jurnal. */
async function preferences(page) {
  return page.evaluate(async () => {
    const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
    const defaults = (await import('./generat/shopping_config.js')).default;
    const store = createShoppingStore({ defaults });
    try { return await store.read(); } finally { store.dispose(); }
  });
}

/** Reîncarcă aplicația și așteaptă analiza reală salvată, fără altă colectare. */
async function reloadReport(page) {
  await page.reload();
  await page.waitForSelector('[data-section="report"]:not([disabled])', { timeout: UI_TIMEOUT_MS });
}

/** Compară o valoare DOM cu suma formatată de componenta reală, fără a o returna în raport. */
async function domMoneyEquals(page, selector, amount) {
  return page.evaluate(async ({ selector, amount }) => {
    const { formatLei } = await import('./calcul/money_ro.js');
    return document.querySelector(selector)?.textContent === formatLei(amount);
  }, { selector, amount });
}

/** Verifică șase funcții pe analiza curentă; blocajele externe rămân blocked, bugurile aruncă erori redactate. */
export async function verifyShoppingAcceptance({ context, page, extensionId, outFolder, entry, productUrl }) {
  requireCheck(entry && Array.isArray(entry.orders) && Array.isArray(entry.returns) && !entry.summary?.meta?.demo, 'real_entry_required');
  const results = {}; let feature = 'initialization'; let phase = 'initialization'; let backup; let storedBefore; let panel; let productPage;
  const pngFolder = path.join(outFolder, 'cumpărături'); mkdirSync(pngFolder, { recursive: true });
  const persist = () => writeFileSync(path.join(pngFolder, 'verdicturi.json'), `${JSON.stringify(results, null, 2)}\n`, 'utf8');
  try {
    await page.waitForSelector('[data-section="campaign"]:not([disabled])', { timeout: UI_TIMEOUT_MS });
    backup = await preferences(page);
    storedBefore = await page.evaluate(async () => {
      const { SHOPPING_STORAGE_KEY } = await import('./cumparaturi/shopping_store.js');
      return Object.hasOwn(await chrome.storage.local.get(SHOPPING_STORAGE_KEY), SHOPPING_STORAGE_KEY);
    });
    const data = await page.evaluate(async (currentEntry) => {
      const { loadAnalysis } = await import('./rulare/analysis_loader.js');
      const { createShoppingInsights } = await import('./cumparaturi/shopping_insights.js');
      const cfg = (await import('./generat/shopping_config.js')).default;
      const engine = await loadAnalysis();
      const threshold = currentEntry.summary.meta.threshold_bani ?? Math.round(currentEntry.threshold_lei * 100);
      const result = engine.analyze(currentEntry.orders, currentEntry.returns, threshold, currentEntry.created_at);
      const insights = await createShoppingInsights(currentEntry);
      const campaign = await insights.campaign(cfg.campaign);
      const allocations = [...result.paid_by_order].map(([id, row]) => [id, { spent_bani: row.spent_bani, in_progress_bani: row.in_progress_bani }]);
      return { cfg, campaign, allocations, purchases: insights.purchases, years: insights.years, summary: insights.summary };
    }, entry);

    feature = 'black_friday';
    const expected = campaignOracle(entry.orders, data.allocations, data.cfg.campaign);
    requireCheck(data.campaign.available && data.campaign.meta.orders === expected.orders && data.campaign.paid.spent_bani === expected.paid
      && data.campaign.paid.reconciliation.in_progress_bani === expected.pending && data.campaign.meta.missing_times === expected.missingTimes
      && data.campaign.meta.missing_dates === expected.missingDates, 'campaign_oracle_mismatch');
    await section(page, 'campaign');
    for (const [name, value] of [['from', data.cfg.campaign.from], ['to', data.cfg.campaign.to], ['start-time', data.cfg.campaign.start_time], ['end-time', data.cfg.campaign.end_time]]) {
      await page.locator(`[name="${name}"]`).fill(value);
    }
    await page.locator('.shopping-campaign-settings button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('.shopping-campaign-recap .shopping-grid'));
    const campaignUi = await page.locator('.shopping-campaign-recap .shopping-metric strong').allTextContents();
    requireCheck(campaignUi[0] === String(expected.orders), 'campaign_ui_count_mismatch');
    requireCheck(await domMoneyEquals(page, '.shopping-campaign-recap .shopping-metric:nth-child(2) strong', expected.paid), 'campaign_ui_paid_mismatch');
    requireCheck(await domMoneyEquals(page, '.shopping-campaign-recap .shopping-metric:nth-child(3) strong', expected.pending), 'campaign_ui_pending_mismatch');
    results.black_friday = { status: 'passed', checks: { independent_filter: true, ui_totals: true, orders: expected.orders, missing_times: expected.missingTimes } };
    persist();

    feature = 'budgets';
    const sampleDay = entry.orders.find((order) => /^\d{4}-\d{2}-\d{2}/.test(order.placed_at ?? ''))?.placed_at.slice(0, 10);
    if (!sampleDay) results.budgets = { status: 'blocked', checks: { reason: 'dated_order_missing' } };
    else {
      const year = sampleDay.slice(0, 4); const month = sampleDay.slice(5, 7);
      await section(page, 'budget'); await page.selectOption('[data-focus="year"]', year);
      await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
      for (const selectedMonth of ['', month]) {
        await page.selectOption('[data-focus="month"]', selectedMonth);
        await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
        const prefix = selectedMonth ? `${year}-${selectedMonth}` : year;
        const expectedPeriod = allocationTotals(entry.orders.filter((order) => order.placed_at?.startsWith(prefix)), data.allocations);
        // Somma de probă derivată din analiză: cu un ban sub cost testează soldul negativ, fără prag financiar inventat.
        const budget = Math.max(0, expectedPeriod.paid - 1);
        await enter(page, '[name="budget"]', (budget / 100).toFixed(2));
        await page.locator('.shopping-form--inline button[type="submit"]').click();
        const key = selectedMonth ? `${year}-${selectedMonth}` : year;
        await page.waitForFunction(async ({ key, budget }) => {
          const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
          const defaults = (await import('./generat/shopping_config.js')).default; const store = createShoppingStore({ defaults });
          try { return (await store.read()).budgets[key] === budget; } finally { store.dispose(); }
        }, { key, budget });
        await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
        requireCheck(await domMoneyEquals(page, '.shopping-metric--yellow > strong', budget - expectedPeriod.paid), 'budget_remaining_mismatch');
        requireCheck(await domMoneyEquals(page, '.shopping-grid .shopping-metric:first-child > strong', expectedPeriod.pending), 'budget_pending_mismatch');
        await reloadReport(page); await section(page, 'budget'); await page.selectOption('[data-focus="year"]', year);
        await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view'); await page.selectOption('[data-focus="month"]', selectedMonth);
        await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
        requireCheck(await page.inputValue('[name="budget"]') === (budget / 100).toFixed(2).replace('.', ','), 'budget_reload_mismatch');
      }
      results.budgets = { status: 'passed', checks: { annual: true, monthly: true, independent_totals: true, reload: true } };
    }
    persist();

    feature = 'returns'; await section(page, 'returns');
    const expectedReturns = (data.summary.warnings_detail ?? []).filter((group) => RETURN_KINDS.has(group.kind)).reduce((sum, group) => sum + group.items.length, 0);
    requireCheck(await page.locator('.shopping-return').count() === expectedReturns, 'return_count_mismatch');
    const safeLinks = await page.locator('.shopping-return a').evaluateAll((links) => links.every((link) => {
      const value = new URL(link.href);
      return value.protocol === 'https:' && value.hostname === 'www.emag.ro' && !value.username && !value.password && !value.port
        && (/^\/user\/return-history\//.test(value.pathname) || /^\/history\/shoppingdetails\//.test(value.pathname));
    }));
    requireCheck(safeLinks, 'return_link_invalid');
    results.returns = { status: 'passed', checks: { count_match: true, safe_links: true, cases: expectedReturns, no_actions: true } };
    persist();

    feature = 'tags';
    if (!data.purchases.length) results.tags = { status: 'blocked', checks: { reason: 'kept_purchase_missing' } };
    else {
      const marker = `Probă acceptanță ${crypto.randomUUID()}`;
      await section(page, 'tags');
      requireCheck(await page.locator('.shopping-tag-item').count() === data.purchases.length, 'tag_initial_count_mismatch');
      await enter(page, '.shopping-tag-form input >> nth=0', marker);
      await page.locator('.shopping-tag-form button[type="submit"]').first().click();
      await page.waitForFunction((value) => [...document.querySelectorAll('[data-focus="tag-filter"] option')].some((option) => option.value === `tag:${value}`), marker);
      await page.selectOption('[data-focus="tag-filter"]', `tag:${marker}`); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
      requireCheck(await page.locator('.shopping-tag-item').count() === 1, 'tag_filter_mismatch');
      requireCheck(await domMoneyEquals(page, '.shopping-metric > strong', data.summary.paid.spent_bani), 'tag_total_changed');
      await reloadReport(page); await section(page, 'tags');
      requireCheck(await page.locator('.shopping-tag-item').count() === data.purchases.length, 'tag_reload_count_mismatch');
      await page.selectOption('[data-focus="tag-filter"]', `tag:${marker}`); await page.waitForSelector('#shopping-panel:not([aria-busy]) .shopping-view');
      requireCheck(await page.locator('.shopping-tag-item').count() === 1, 'tag_reload_filter_mismatch');
      results.tags = { status: 'passed', checks: { filter: true, reload: true, total_unchanged: true, purchases: data.purchases.length } };
    }
    persist();

    feature = 'recap';
    if (!data.years.length) results.recap = { status: 'blocked', checks: { reason: 'year_missing' } };
    else {
      await section(page, 'recap'); const pngs = [];
      for (const hide of [false, true]) {
        await page.locator('#shopping-hide-sum').setChecked(hide);
        const preview = await page.locator('#shopping-recap-card').evaluate((canvas) => canvas.toDataURL('image/png').split(',')[1]);
        const accessible = await page.getAttribute('#shopping-recap-card', 'aria-label');
        requireCheck(hide ? !accessible.includes('Plătit efectiv:') : accessible.includes('Plătit efectiv:'), 'recap_hide_sum_mismatch');
        const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#shopping-download-recap').click()]);
        const target = path.join(pngFolder, hide ? 'bilant-fara-suma.png' : 'bilant-cu-suma.png'); await download.saveAs(target);
        const bytes = readFileSync(target); requireCheck(bytes.equals(Buffer.from(preview, 'base64')), 'recap_preview_download_mismatch');
        requireCheck(bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), 'recap_png_invalid'); pngs.push(bytes);
      }
      requireCheck(!pngs[0].equals(pngs[1]), 'recap_hidden_image_unchanged');
      results.recap = { status: 'passed', checks: { preview_matches_download: true, hide_sum: true, downloads: pngs.length } };
    }
    persist();

    feature = 'sidepanel';
    if (!productUrl) results.sidepanel = { status: 'blocked', checks: { reason: 'product_url_missing' } };
    else {
      const eligible = await page.evaluate(async (value) => (await import('./cumparaturi/shopping_schema.js')).canonicalShoppingProductUrl(value), productUrl);
      requireCheck(Boolean(eligible), 'acceptance_product_url_invalid');
      phase = 'sidepanel_navigation';
      panel = await context.newPage(); await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
      productPage = await context.newPage();
      const response = await productPage.goto(eligible, { waitUntil: 'domcontentloaded', timeout: UI_TIMEOUT_MS }).catch(() => null);
      if (!response || response.status() >= 400) results.sidepanel = { status: 'blocked', checks: { reason: 'product_navigation_unavailable' } };
      else {
      phase = 'sidepanel_read';
      await productPage.bringToFront(); await panel.evaluate(() => document.getElementById('read-product').click());
      await panel.waitForFunction(() => !document.getElementById('read-product').disabled, null, { timeout: UI_TIMEOUT_MS });
      if (await panel.isHidden('#product')) results.sidepanel = { status: 'blocked', checks: { reason: 'product_extraction_unavailable' } };
      else {
        const priceKnown = await panel.evaluate(() => document.getElementById('current-price').textContent !== 'Necunoscut');
        if (!priceKnown) results.sidepanel = { status: 'blocked', checks: { reason: 'current_price_unknown' } };
        else {
          phase = 'sidepanel_comparison';
          const comparisonOk = await panel.evaluate(async () => {
            const { readActiveProduct } = await import('./panou/active_product.js');
            const { loadLastAnalysis } = await import('./stocare/last_analysis.js');
            const { createShoppingInsights } = await import('./cumparaturi/shopping_insights.js');
            const { compareProduct } = await import('./panou/product_comparison.js');
            const { formatLei } = await import('./calcul/money_ro.js');
            const product = await readActiveProduct(); const insights = await createShoppingInsights(await loadLastAnalysis());
            const result = compareProduct(product, insights.purchases);
            if (result.status === 'no-history') return document.getElementById('match-label').hidden;
            const last = document.getElementById('last-price').firstChild?.textContent;
            const minimum = document.getElementById('minimum-price').firstChild?.textContent;
            return !document.getElementById('match-label').hidden && last === (result.last ? formatLei(result.last.unit_bani) : 'Necunoscut') && minimum === formatLei(result.minimum.unit_bani);
          });
          requireCheck(comparisonOk, 'sidepanel_comparison_mismatch');
          phase = 'sidepanel_save_target';
          const target = Math.max(1, Math.abs(data.summary.paid.spent_bani));
          // Fila de harness redă panoul fără a activa o filă nouă la tastare, cum face panoul nativ.
          await panel.evaluate((value) => {
            const input = document.getElementById('target-price'); input.value = value;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            document.getElementById('target-form').requestSubmit();
          }, (target / 100).toFixed(2));
          await panel.waitForFunction(() => document.getElementById('target-message').textContent || document.getElementById('product').hidden);
          if (await panel.isHidden('#product')) {
            const state = await panel.evaluate(() => {
              const text = document.getElementById('panel-status').textContent;
              if (text.startsWith('Fila s-a schimbat')) return 'tab_changed';
              if (text.startsWith('Datele au fost șterse')) return 'data_deleted';
              if (text.startsWith('Datele salvate nu au putut fi citite')) return 'storage_error';
              return 'product_invalidated';
            });
            throw new AcceptanceCheckError(`sidepanel_target_${state}`);
          }
          requireCheck(await panel.textContent('#target-message') === 'Ținta a fost salvată.', 'sidepanel_target_rejected');
          const saved = await preferences(page); requireCheck(saved.wishlist.some((item) => item.url === eligible && item.target_bani === target && item.selected), 'sidepanel_target_mismatch');
          results.sidepanel = { status: 'passed', checks: { live_product: true, comparison: true, target_saved: true } };
        }
      }
      }
    }
    persist();
    return results;
  } catch (failure) {
    const code = failure instanceof AcceptanceCheckError ? failure.message : 'browser_operation_failed';
    results[feature] = { status: 'failed', checks: { failure: code, phase } };
    const error = new Error(`acceptanta_cumparaturi:${feature}:${phase}:${code}`); error.results = results; throw error;
  } finally {
    if (panel) await panel.close().catch(() => {}); if (productPage) await productPage.close().catch(() => {});
    let restoreFailed = false;
    if (backup) {
      try {
        const restored = await page.evaluate(async ({ previous, existed }) => {
          const { createShoppingStore, SHOPPING_STORAGE_KEY } = await import('./cumparaturi/shopping_store.js');
          const defaults = (await import('./generat/shopping_config.js')).default; const store = createShoppingStore({ defaults });
          try {
            if (existed) return JSON.stringify(await store.update(() => previous)) === JSON.stringify(previous);
            const { privateStorage } = await import('./stocare/private_storage.js'); await privateStorage.remove(chrome.storage.local, SHOPPING_STORAGE_KEY);
            return !Object.hasOwn(await chrome.storage.local.get(SHOPPING_STORAGE_KEY), SHOPPING_STORAGE_KEY);
          } finally { store.dispose(); }
        }, { previous: backup, existed: storedBefore });
        requireCheck(restored, 'preferences_restore_mismatch');
      } catch { restoreFailed = true; results.restore = { status: 'failed', checks: { preferences_restored: false } }; }
    }
    persist();
    if (restoreFailed) { const error = new Error('acceptanta_cumparaturi:restore:failed'); error.results = results; throw error; }
  }
}
