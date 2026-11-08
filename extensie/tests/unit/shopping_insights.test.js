// Perioadele sunt verificate pe motorul și configurațiile reale, cu comenzi/retururi inventate.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createShoppingInsights } from '../../src/cumparaturi/shopping_insights.js';
import { loadAnalysis } from '../../src/rulare/analysis_loader.js';
import { makeItem, makeOrder, makeSellerBlock, makeReturnRequest } from '../../src/calcul/models.js';
import { realAnalysisLoaders } from './piese_reale.js';

const loader = () => loadAnalysis(realAnalysisLoaders());

/** Comandă minimă inventată, cu prețul plătit independent de prețul de listă. */
function order(id, date, { name = 'Produs inventat', qty = 1, amount = 10000, paid = amount, status = 'DELIVERED', items } = {}) {
  return makeOrder({ order_id: id, placed_at: date, placed_text: date ?? '', header_total_bani: paid,
    blocks: [makeSellerBlock({ seller: 'Vânzător inventat', status, status_text: status, has_storno: false,
      paid_bani: paid, items: items ?? [makeItem(name, amount, qty)] })] });
}

/** Cerere care poate acoperi două comenzi și două perioade, fără a dubla rambursarea afișată. */
function refund(ids, names, amount, mode = 'Vreau banii inapoi') {
  return makeReturnRequest({ return_id: 'R-inventat', detail_path: '/retur/inventat', order_ids: ids,
    product_names: names, steps: [], refund_bani: amount, refund_mode: mode, completed: true, cancelled: false });
}

/** Intrare compatibilă cu stocarea, rezumatul este recalculat prin loader-ul real. */
function entry(orders, returns = []) {
  return { orders, returns, summary: { meta: { orders: orders.length, threshold_bani: 50000 } }, threshold_lei: 500, created_at: '2026-11-08 12:00:00' };
}

test('o singură achiziție folosește suma plătită pe unitate după reducere și interval inclusiv', async () => {
  const insights = await createShoppingInsights(entry([order('A', '2026-11-06T11:30:00', { qty: 2, amount: 20000, paid: 15000 })]), { loader });
  assert.equal(insights.purchases.length, 1); assert.equal(insights.purchases[0].paid_bani, 15000); assert.equal(insights.purchases[0].unit_bani, 7500);
  const period = await insights.period('2026-11-06', '2026-11-06'); assert.equal(period.paid.spent_bani, 15000); assert.equal(period.meta.orders, 1);
  assert.equal((await insights.period('2026-11-07', '2026-11-07')).paid.spent_bani, 0);
  await assert.rejects(insights.period('2026-02-30', '2026-11-07'), /invalid/);
});

test('id-urile liniilor identice sunt distincte și rămân stabile când prima linie este returnată', async () => {
  const source = order('A', '2026-11-06', { amount: 20000, items: [makeItem('Produs inventat', 10000, 1), makeItem('Produs inventat', 10000, 1)] });
  const before = await createShoppingInsights(entry([source]), { loader });
  const after = await createShoppingInsights(entry([source], [refund(['A'], ['Produs inventat'], 10000)]), { loader });
  assert.notEqual(before.purchases[0].id, before.purchases[1].id); assert.equal(after.purchases[0].id, before.purchases[1].id);
});

for (const mode of ['Vreau banii inapoi', 'Emitere voucher']) {
  test(`retur comun pe două luni: perioadele se închid la ban (${mode})`, async () => {
    const orders = [order('A', '2026-10-31', { name: 'Produs alfa inventat', amount: 10000 }), order('B', '2026-11-06', { name: 'Produs beta inventat', amount: 30000 })];
    const insights = await createShoppingInsights(entry(orders, [refund(['A', 'B'], ['Produs alfa inventat', 'Produs beta inventat'], 36001, mode)]), { loader });
    const october = await insights.period('2026-10-01', '2026-10-31'); const november = await insights.period('2026-11-01', '2026-11-30');
    assert.equal(october.paid.spent_bani + november.paid.spent_bani, insights.summary.paid.spent_bani);
    assert.equal(insights.summary.paid.spent_bani, mode === 'Emitere voucher' ? 40000 : 3999);
    assert.equal(october.paid.funnel.returned_bani + november.paid.funnel.returned_bani, insights.summary.paid.funnel.returned_bani);
    assert.equal(insights.purchases.length, 0);
  });
}

test('retur mixt livrat/anulat și retur parțial păstrează estimările motorului pe perioade', async () => {
  for (const status of ['CANCELLED', 'DELIVERED']) {
    const orders = [order('A', '2026-10-31', { name: 'Produs alfa inventat' }), order('B', '2026-11-06', { name: 'Produs beta inventat', status })];
    const names = ['Produs alfa inventat', 'Produs beta inventat', ...(status === 'DELIVERED' ? ['Articol complet diferit fără corespondent'] : [])];
    const insights = await createShoppingInsights(entry(orders, [refund(['A', 'B'], names, 25000)]), { loader });
    const a = await insights.period('2026-10-01', '2026-10-31'); const b = await insights.period('2026-11-01', '2026-11-30');
    assert.equal(a.paid.spent_bani + b.paid.spent_bani, insights.summary.paid.spent_bani);
    assert.equal(a.paid.funnel.returned_bani + b.paid.funnel.returned_bani, insights.summary.paid.funnel.returned_bani);
  }
});

test('date lipsă sunt excluse explicit din perioade, dar rămân în total; pending este separat', async () => {
  const source = entry([order('A', null), order('B', '2026-11-06', { status: 'IN_PROGRESS', paid: 7000 })]);
  const insights = await createShoppingInsights(source, { loader });
  const period = await insights.period('2026-01-01', '2026-12-31');
  assert.equal(period.paid.spent_bani, 0); assert.equal(period.meta.missing_dates, 1); assert.equal(insights.summary.paid.spent_bani, 10000);
  assert.equal(period.paid.reconciliation.in_progress_bani, 7000); assert.equal(period.paid.funnel.pending_bani, 7000);
  assert.equal(insights.purchases[0].date, null);
  const engine = await loader(); const result = engine.analyze(source.orders, source.returns, 50000, source.created_at);
  assert.equal(result.paid_by_order.get('A').spent_bani + period.paid.spent_bani, insights.summary.paid.spent_bani);
});

test('intervale în ani diferiți păstrează și taxele pe comandă, fără reatribuirea returului', async () => {
  const orders = [order('A', '2025-12-31', { name: 'Produs alfa inventat', amount: 10000, paid: 11000 }),
    order('B', '2026-01-01', { name: 'Produs beta inventat', amount: 30000, paid: 32000 })];
  const insights = await createShoppingInsights(entry(orders, [refund(['A', 'B'], ['Produs alfa inventat', 'Produs beta inventat'], 19001)]), { loader });
  const a = await insights.period('2025-01-01', '2025-12-31'); const b = await insights.period('2026-01-01', '2026-12-31');
  assert.equal(a.paid.spent_bani + b.paid.spent_bani, 23999);
  assert.equal(a.paid.fees_bani, 1000); assert.equal(b.paid.fees_bani, 2000);
  assert.equal(a.paid.spent_bani, insights.summary.by_year.find((row) => row.year === '2025').spent_bani);
  assert.equal(b.paid.spent_bani, insights.summary.by_year.find((row) => row.year === '2026').spent_bani);
});

test('fără raw, totalurile anuale există, lunile sunt indisponibile și nu devin zero', async () => {
  const insights = await createShoppingInsights({ summary: { meta: { orders: 2 }, by_year: [{ year: '2026', spent_bani: 12345, orders: 2 }] }, orders: [], returns: [] }, { loader: () => { throw new Error('nu trebuie încărcat'); } });
  assert.deepEqual(insights.purchases, []); assert.deepEqual(insights.years, ['2026']);
  assert.equal((await insights.period('2026-01-01', '2026-12-31')).paid.spent_bani, 12345);
  const month = await insights.period('2026-11-01', '2026-11-30'); assert.equal(month.available, false); assert.equal(month.paid, null);
});

test('campania include începutul și exclude finalul, comenzile înainte de start și zilele fără oră', async () => {
  const campaign = { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' };
  const stamps = ['2031-05-09T01:00', '2031-05-09T08:19:59', '2031-05-09T08:20',
    '2031-05-09T23:59:59', '2031-05-10T00:00', '2031-05-10T00:01', '2031-05-09', null];
  const insights = await createShoppingInsights(entry(stamps.map((stamp, index) => order(`Inventat-${index}`, stamp))), { loader });
  const result = await insights.campaign(campaign);
  assert.equal(result.meta.orders, 2); assert.equal(result.paid.spent_bani, 20000);
  assert.equal(result.meta.missing_times, 1); assert.equal(result.meta.missing_dates, 1);
  assert.equal(result.meta.time_zone, 'Europe/Bucharest'); assert.equal(result.time_required, false);
  assert.equal((await insights.period('2031-05-09', '2031-05-09')).meta.orders, 5);
  const missing = await insights.campaign({ ...campaign, start_time: null, end_time: null });
  assert.equal(missing.available, false); assert.equal(missing.time_required, true); assert.equal(missing.paid, null);
});

test('campania convertește offseturile în RO și refuză atribuirea orelor invalide', async () => {
  const campaign = { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' };
  const stamps = ['2031-05-09T05:19:59Z', '2031-05-09T05:20:00Z', '2031-05-09T21:00:00Z', '2031-05-09T08:20+24:99'];
  const insights = await createShoppingInsights(entry(stamps.map((stamp, index) => order(`Inventat-${index}`, stamp))), { loader });
  const result = await insights.campaign(campaign);
  assert.equal(result.meta.orders, 1); assert.equal(result.paid.spent_bani, 10000); assert.equal(result.meta.missing_times, 1);
});

test('filtrarea pe ore păstrează alocarea returului comun și nu dublează rambursarea', async () => {
  const campaign = { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' };
  const orders = [order('Inventat-A', '2031-05-09T01:00', { name: 'Produs alfa inventat', amount: 10000 }),
    order('Inventat-B', '2031-05-09T08:20', { name: 'Produs beta inventat', amount: 30000 })];
  for (const mode of ['Vreau banii inapoi', 'Emitere voucher']) {
    const insights = await createShoppingInsights(entry(orders, [refund(['Inventat-A', 'Inventat-B'], ['Produs alfa inventat', 'Produs beta inventat'], 36001, mode)]), { loader });
    const before = await insights.campaign({ ...campaign, to: campaign.from, start_time: '00:00', end_time: '08:20' });
    const after = await insights.campaign(campaign);
    assert.equal(before.paid.spent_bani + after.paid.spent_bani, insights.summary.paid.spent_bani);
    assert.equal(before.paid.funnel.returned_bani + after.paid.funnel.returned_bani, insights.summary.paid.funnel.returned_bani);
  }
});

test('campania fără comenzi brute rămâne indisponibilă inclusiv cu ore valide', async () => {
  const insights = await createShoppingInsights({ summary: { meta: { orders: 2 }, by_year: [{ year: '2031', spent_bani: 12345 }] }, orders: [], returns: [] });
  const result = await insights.campaign({ from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' });
  assert.equal(result.available, false); assert.equal(result.paid, null); assert.equal(result.meta.missing_times, null);
});
