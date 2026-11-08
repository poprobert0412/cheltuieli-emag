import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readActiveProduct } from '../../src/panou/active_product.js';

const url = 'https://www.emag.ro/produs-inventat/pd/DEMO123/';
/** API Chrome minimal care înregistrează injectările și permite navigarea concurentă. */
function api({ activeUrl = url, afterUrl = url, activeAfter = 1 } = {}) {
  let queries = 0;
  const calls = [];
  return { calls, tabs: { query: async () => [{ id: ++queries === 1 ? 1 : activeAfter, url: activeUrl }], get: async () => ({ id: 1, url: afterUrl }) }, scripting: { executeScript: async (options) => { calls.push(options); return [{ frameId: 0, result: { status: 'ok', name: 'Produs inventat', url: url.slice(0, -1), price_bani: 12345 } }]; } } };
}
test('nu injectează în afara produsului HTTPS și utilizează lumea izolată', async () => {
  const wrong = api({ activeUrl: 'https://www.emag.ro/history/shopping' });
  assert.equal((await readActiveProduct(wrong)).status, 'ineligible');
  assert.equal(wrong.calls.length, 0);
  const good = api();
  assert.equal((await readActiveProduct(good)).status, 'ok');
  assert.equal(good.calls[0].world, 'ISOLATED');
  assert.deepEqual(good.calls[0].target, { tabId: 1 });
});
test('navigarea și schimbarea filei active invalidează răspunsul', async () => {
  assert.equal((await readActiveProduct(api({ afterUrl: `${url}?nou` }))).status, 'stale');
  assert.equal((await readActiveProduct(api({ activeAfter: 2 }))).status, 'stale');
});
test('eroarea scripting este explicită și nu devine produs gol', async () => {
  const broken = api(); broken.scripting.executeScript = async () => { throw new Error('injection denied'); };
  await assert.rejects(readActiveProduct(broken), /injection denied/);
});
test('clic iconiță deschide panoul în gestul activ și restul păstrează aplicația', async () => {
  const calls = [];
  let onMessage;
  globalThis.chrome = {
    action: { onClicked: { addListener() {} } },
    tabs: { onRemoved: { addListener() {} }, create: async (options) => { calls.push(['app', options]); return { id: 2 }; } },
    runtime: { id: 'inventat', getURL: (name) => `chrome-extension://inventat/${name}`, getContexts: async () => [], onMessage: { addListener(listener) { onMessage = listener; } } },
    sidePanel: { open: (options) => { calls.push(['panel', options]); return Promise.resolve(); } },
    storage: { session: { set: async (value) => { calls.push(['authorization', value]); } } },
  };
  const { handleActionClick } = await import('../../src/background.js');
  const opening = handleActionClick({ id: 1, url });
  assert.equal(calls[0][0], 'panel', 'open este sincron înaintea primului await');
  await opening;
  assert.equal(calls[1][0], 'authorization');
  await handleActionClick({ id: 1, url: 'https://example.invalid/' });
  assert.equal(calls.at(-1)[0], 'app');
  assert.equal(onMessage({ type: 'panou-raport' }, { id: 'strain', url: 'chrome-extension://inventat/sidepanel.html' }, () => {}), false);
  assert.equal(onMessage({ type: 'panou-raport' }, { id: 'inventat', url: 'https://www.emag.ro/' }, () => {}), false);
  assert.equal(onMessage({ type: 'altceva' }, { id: 'inventat', url: 'chrome-extension://inventat/sidepanel.html' }, () => {}), false);
  delete globalThis.chrome;
});
