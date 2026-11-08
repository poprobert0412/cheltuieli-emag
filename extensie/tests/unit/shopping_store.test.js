// Store-ul folosește Web Locks/criptare reale și IndexedDB în memorie; datele sunt inventate.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { IDBFactory } from 'fake-indexeddb';
import { createKeyStore } from '../../src/stocare/key_store.js';
import { createPrivateStorage } from '../../src/stocare/private_storage.js';
import { createShoppingStore, SHOPPING_STORAGE_KEY } from '../../src/cumparaturi/shopping_store.js';
import { initialShoppingState, isValidShoppingUrl, validateShoppingState } from '../../src/cumparaturi/shopping_schema.js';

const defaults = { campaign: { from: '2026-11-06', to: '2026-11-07' } };
const product = { id: 'inventat', name: 'Produs inventat', url: 'https://www.emag.ro/produs-inventat/pd/ABC/',
  price_bani: 12345, target_bani: null, observed_at: null, selected: true };

/** Două contexte independente împart zona Chrome și cheia/lacătul; evenimentele sunt ca cele Chrome. */
function setup() {
  let data = {};
  const listeners = new Set();
  const changes = { addListener: (fn) => listeners.add(fn), removeListener: (fn) => listeners.delete(fn) };
  const notify = (items) => { for (const fn of listeners) fn(structuredClone(items), 'local'); };
  const storage = {
    failSet: false,
    async get(name) { return structuredClone(name ? (Object.hasOwn(data, name) ? { [name]: data[name] } : {}) : data); },
    async set(items) {
      if (this.failSet) throw new Error('QUOTA_BYTES quota exceeded');
      const event = Object.fromEntries(Object.entries(items).map(([key, value]) => [key, { oldValue: data[key], newValue: value }]));
      data = { ...data, ...structuredClone(items) }; notify(event);
    },
    async clear() { const event = Object.fromEntries(Object.entries(data).map(([key, value]) => [key, { oldValue: value }])); data = {}; notify(event); },
  };
  const indexedDB = new IDBFactory();
  const databaseName = crypto.randomUUID(); const lockName = crypto.randomUUID();
  const persistence = () => createPrivateStorage({ keyStore: createKeyStore({ indexedDB, databaseName }), lockName });
  const first = persistence(); const second = persistence();
  const make = (instance = first, selectedDefaults = defaults) => createShoppingStore({ defaults: selectedDefaults, storage, persistence: instance, changes });
  return { storage, changes, make, first, second, listeners };
}

test('actualizările simultane din două contexte se păstrează criptat fără lost-update', async () => {
  const env = setup(); const a = env.make(); const b = env.make(env.second);
  try {
    await Promise.all([a.update((state) => { state.wishlist.push(product); }), b.update((state) => { state.budgets['2026-11'] = 98765; })]);
    const result = await a.read();
    assert.equal(result.wishlist[0].name, product.name); assert.equal(result.budgets['2026-11'], 98765);
    const raw = (await env.storage.get())[SHOPPING_STORAGE_KEY];
    assert.equal(raw.schema, 2); assert.equal(JSON.stringify(raw).includes(product.name), false);
    result.wishlist.length = 0; assert.equal((await b.read()).wishlist.length, 1);
  } finally { a.dispose(); b.dispose(); }
});

test('ștergerea din alt context notifică golirea și refuză scriitorul vechi inclusiv după read', async () => {
  const env = setup(); const a = env.make(); const b = env.make(env.second);
  const seen = []; a.subscribe((state, error) => seen.push({ state, error }));
  await a.update((state) => { state.tags.achizitie = 'Lucru'; });
  await env.second.clear(env.storage);
  assert.ok(seen.some((event) => event.state === null && !event.error));
  await assert.rejects(a.read(), /șterse/);
  await assert.rejects(a.update((state) => { state.tags.achizitie = 'Vechi'; }), /șterse/);
  assert.deepEqual(await env.storage.get(), {});
  a.dispose(); b.dispose(); assert.equal(env.listeners.size, 0);
});

test('ștergerea înaintea primei salvări invalidează și un store fără intrare persistentă', async () => {
  const env = setup(); const a = env.make();
  await a.read(); await env.second.clear(env.storage);
  await assert.rejects(a.update((state) => { state.tags.test = 'Vechi'; }), /șterse/);
  assert.deepEqual(await env.storage.get(), {}); a.dispose();
});

test('quota și corupția nu șterg preferințe și nu devin stare goală', async () => {
  const env = setup(); const store = env.make();
  await store.update((state) => { state.budgets['2026'] = 12345; });
  const previous = await env.storage.get(); env.storage.failSet = true;
  await assert.rejects(store.update((state) => { state.budgets['2026'] = 99999; }), /quota/);
  assert.deepEqual(await env.storage.get(), previous); env.storage.failSet = false;
  await env.storage.set({ [SHOPPING_STORAGE_KEY]: { schema: 99 } });
  await assert.rejects(store.read(), /schemă|câmp/);
  await assert.rejects(store.update(() => {}), /schemă|câmp/); store.dispose();
});

test('demo are actualizări seriale numai în memorie și nu accesează persistența', async () => {
  const persistence = new Proxy({}, { get() { throw new Error('demo nu accesează persistența'); } });
  const store = createShoppingStore({ demo: true, defaults, persistence });
  let notifications = 0; const unsubscribe = store.subscribe(() => { notifications += 1; });
  await Promise.all([store.update(async (state) => { state.tags.a = 'Prima'; }), store.update((state) => { state.tags.b = 'A doua'; })]);
  assert.deepEqual((await store.read()).tags, { a: 'Prima', b: 'A doua' }); assert.equal(notifications, 2);
  unsubscribe(); store.dispose(); await assert.rejects(store.read(), /închis/);
  const fresh = createShoppingStore({ demo: true, defaults }); assert.deepEqual((await fresh.read()).tags, {}); fresh.dispose();
});

test('validarea refuză bani fracționari/nesiguri, date invalide, caractere control și URL străin', () => {
  const change = (mutate) => { const state = initialShoppingState(defaults); mutate(state); return state; };
  for (const amount of [-1, 1.5, NaN, Number.MAX_SAFE_INTEGER + 1, '120']) {
    assert.throws(() => validateShoppingState(change((state) => { state.campaign.budget_bani = amount; })), /suma/);
  }
  assert.throws(() => validateShoppingState(change((state) => { state.campaign.from = '2026-02-30'; })), /interval/);
  assert.throws(() => validateShoppingState(change((state) => { state.tags.key = 'abc\u202Edef'; })), /text/);
  assert.throws(() => validateShoppingState(change((state) => { state.wishlist = [{ ...product }, { ...product }]; })), /duplicat/);
  assert.throws(() => validateShoppingState(change((state) => { state.wishlist = [{ ...product, observed_at: '2026-02-30T00:00:00Z' }]; })), /observării/);
  assert.doesNotThrow(() => validateShoppingState(change((state) => { state.wishlist = [{ ...product, url: '', price_bani: null }]; })));
  const credentialUrl = new URL(product.url);
  credentialUrl.username = 'exemplu';
  for (const url of ['javascript:alert(1)', 'https://www.emag.ro.evil.invalid/pd/x', credentialUrl.href, 'http://www.emag.ro/pd/x']) assert.equal(isValidShoppingUrl(url), false);
  assert.equal(isValidShoppingUrl(product.url), true);
});

test('schema1 migrează atomic la orele config fără pierderea listei, etichetelor sau bugetelor', async () => {
  const env = setup();
  const legacy = { schema: 1, campaign: { from: '2031-05-09', to: '2031-05-10', budget_bani: 76543 },
    wishlist: [product], budgets: { '2031-05': 45678 }, tags: { inventat: 'Cadou' } };
  const configured = { campaign: { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' } };
  await env.first.write(env.storage, SHOPPING_STORAGE_KEY, legacy);
  const a = env.make(env.first, configured); const b = env.make(env.second, configured);
  const [migrated] = await Promise.all([a.read(), b.update((state) => { state.tags.altul = 'Lucru'; })]);
  assert.equal(migrated.schema, 2); assert.equal(migrated.campaign.start_time, '08:20');
  const saved = await a.read();
  assert.deepEqual(saved.wishlist, legacy.wishlist); assert.deepEqual(saved.budgets, legacy.budgets);
  assert.equal(saved.tags.inventat, 'Cadou'); assert.equal(saved.tags.altul, 'Lucru');
  assert.equal(saved.campaign.budget_bani, 76543); assert.equal(saved.campaign.from, legacy.campaign.from); assert.equal(saved.campaign.to, legacy.campaign.to);
  assert.equal((await env.first.read(env.storage, SHOPPING_STORAGE_KEY, () => true)).schema, 2);
  a.dispose(); b.dispose();
});

test('migrarea incompatibilă cere ambele ore; quota lasă intrarea veche intactă', async () => {
  const env = setup();
  const legacy = { schema: 1, campaign: { from: '2031-05-09', to: '2031-05-09', budget_bani: 76543 }, wishlist: [product], budgets: {}, tags: { inventat: 'Cadou' } };
  const configured = { campaign: { from: '2031-05-09', to: '2031-05-10', start_time: '08:20', end_time: '00:00', time_zone: 'Europe/Bucharest' } };
  await env.first.write(env.storage, SHOPPING_STORAGE_KEY, legacy);
  const store = env.make(env.first, configured); const before = await env.storage.get();
  env.storage.failSet = true;
  await assert.rejects(store.read(), /quota/); assert.deepEqual(await env.storage.get(), before);
  env.storage.failSet = false;
  const migrated = await store.read();
  assert.equal(migrated.campaign.start_time, null); assert.equal(migrated.campaign.end_time, null);
  assert.equal(migrated.campaign.from, legacy.campaign.from); assert.equal(migrated.campaign.to, legacy.campaign.to);
  assert.deepEqual(migrated.wishlist, legacy.wishlist); assert.deepEqual(migrated.tags, legacy.tags);
  assert.throws(() => validateShoppingState({ ...migrated, campaign: { ...migrated.campaign, start_time: '08:20' } }), /ore/);
  store.dispose();
});
