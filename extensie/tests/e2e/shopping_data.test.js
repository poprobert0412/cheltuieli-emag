// Persistența reală între două pagini de extensie: criptare, evenimente, reload și ștergere; fără cont real.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { scenario } from './harness.js';

scenario('preferințe cumpărături între două contexte reale', {}, (ctx) => {
  let first; let second;

  test('actualizările concurente nu se suprascriu și evenimentele sunt decriptate', async () => {
    first = await ctx.session.openApp(); second = await ctx.session.openApp();
    for (const page of [first, second]) await page.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
      window.dataTestStore = createShoppingStore({ defaults: { campaign: { from: '2026-11-06', to: '2026-11-07' } } });
      window.dataTestObserved = 'încă nimic';
      window.dataTestStore.subscribe((state, error) => { window.dataTestObserved = error ? { error: error.message } : state; });
      await window.dataTestStore.read();
    });
    await Promise.all([
      first.evaluate(() => window.dataTestStore.update((state) => { state.tags.inventat = 'Cadou'; })),
      second.evaluate(() => window.dataTestStore.update((state) => { state.budgets['2026-11'] = 12345; })),
    ]);
    await first.waitForFunction(() => window.dataTestObserved?.tags?.inventat === 'Cadou' && window.dataTestObserved?.budgets?.['2026-11'] === 12345);
    const saved = await second.evaluate(() => window.dataTestStore.read());
    assert.equal(saved.tags.inventat, 'Cadou'); assert.equal(saved.budgets['2026-11'], 12345);
    const raw = await ctx.session.storage(first);
    assert.equal(raw.preferinte_cumparaturi.schema, 2); assert.equal(JSON.stringify(raw).includes('Cadou'), false);
  });

  test('reload păstrează preferințele, analiza nouă nu le înlocuiește', async () => {
    await second.reload();
    const saved = await second.evaluate(async () => {
      const { createShoppingStore } = await import('./cumparaturi/shopping_store.js');
      window.dataTestStore = createShoppingStore({ defaults: { campaign: { from: '2026-11-06', to: '2026-11-07' } } });
      return window.dataTestStore.read();
    });
    assert.equal(saved.tags.inventat, 'Cadou');
    await ctx.session.seedLastAnalysis(second);
    assert.equal((await first.evaluate(() => window.dataTestStore.read())).budgets['2026-11'], 12345);
  });

  test('ștergerea în alt tab golește abonații și scriitorul vechi rămâne invalid', async () => {
    await second.evaluate(async () => { const { deleteAllData } = await import('./stocare/last_analysis.js'); await deleteAllData(); });
    await first.waitForFunction(() => window.dataTestObserved === null);
    const error = await first.evaluate(async () => {
      try { await window.dataTestStore.update((state) => { state.tags.inventat = 'vechi'; }); return null; }
      catch (failure) { return failure.message; }
    });
    assert.match(error, /șterse/); assert.deepEqual(await ctx.session.storage(first), {});
    await first.evaluate(() => window.dataTestStore.dispose()); await second.evaluate(() => window.dataTestStore.dispose());
  });
});
