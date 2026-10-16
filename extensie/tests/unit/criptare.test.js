// Contractul persistenței criptate: crypto/Web Locks reale, IndexedDB standard în memorie și chrome.storage cu commit atomic.
// Datele sunt inventate; se verifică anvelopa, cheia neexportabilă, migrarea, ștergerea și concurența fără date de profil reale.
// Defectele se provoacă la granițele API-urilor (cotă, clear, criptare), fără cale specială de test în producție.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { IDBFactory } from 'fake-indexeddb';
import { createKeyStore } from '../../src/stocare/key_store.js';
import { createPrivateStorage } from '../../src/stocare/private_storage.js';
import { StorageEncryptionError, decryptRecord } from '../../src/stocare/storage_encryption.js';
import { ENTRY_SCHEMA, LAST_ANALYSIS_KEY, StorageFull, deleteAllData, loadLastAnalysis, saveLastAnalysis } from '../../src/stocare/last_analysis.js';
import { RUN_LOG_KEY, RunLog, loadSavedRunLog } from '../../src/stocare/run_log.js';

/** Intrare mică inventată, aceeași formă JSON pe care o produce pipeline-ul. */
function entry(overrides = {}) {
  return { schema: ENTRY_SCHEMA, extension_version: '0.1.0', created_at: '2026-01-02 12:00:00', threshold_lei: 500,
    summary: { total: 12345 }, orders: [{ order_id: '100000001' }], returns: [], log_text: 'jurnal inventat\n', ...overrides };
}

/** Zona Chrome cu valori JSON și modificări atomice; controlul erorilor este la granița API-ului. */
function area() {
  let data = {};
  return {
    failSet: false, failClear: false, beforeSet: null, writes: 0,
    async get(name) { return structuredClone(name ? (name in data ? { [name]: data[name] } : {}) : data); },
    async set(items) {
      if (this.beforeSet) await this.beforeSet(items);
      if (this.failSet) throw new Error('QUOTA_BYTES quota exceeded');
      data = { ...data, ...JSON.parse(JSON.stringify(items)) };
      this.writes += 1;
    },
    async remove(name) { delete data[name]; },
    async clear() { if (this.failClear) throw new Error('clear failed'); data = {}; },
  };
}

/** Două file folosesc aceeași bază IndexedDB și același Web Lock, dar instanțe separate ale persistenței. */
function setup() {
  const indexedDB = new IDBFactory();
  const databaseName = crypto.randomUUID();
  const lockName = crypto.randomUUID();
  const keyStore = createKeyStore({ indexedDB, databaseName });
  const first = createPrivateStorage({ keyStore, lockName });
  const second = createPrivateStorage({ keyStore: createKeyStore({ indexedDB, databaseName }), lockName });
  return { storage: area(), keyStore, first, second };
}

/** Barieră explicită, fără sleep: testul știe când o scriere a început și când o poate lăsa să termine. */
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test('aceleași date au nonce și ciphertext diferite; cheia persistată este AES-256 neexportabilă', async () => {
  const { storage, keyStore, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const old = (await storage.get())[LAST_ANALYSIS_KEY];
  await saveLastAnalysis(entry(), storage, first);
  const newer = (await storage.get())[LAST_ANALYSIS_KEY];
  assert.notEqual(old.nonce, newer.nonce);
  assert.notEqual(old.ciphertext, newer.ciphertext);
  assert.equal(atob(newer.nonce).length, 12);
  const { key } = await keyStore.read();
  assert.equal(key.algorithm.length, 256);
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey('raw', key));
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
  assert.deepEqual(Object.keys(await storage.get()), [LAST_ANALYSIS_KEY], 'cheia nu intră în chrome.storage');
});

test('modificarea ciphertextului, nonce-ului, algoritmului sau schemei nu devine analiză goală', async () => {
  const { storage, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const original = (await storage.get())[LAST_ANALYSIS_KEY];
  const mutateBase64 = (value) => `${value.startsWith('A') ? 'B' : 'A'}${value.slice(1)}`;
  for (const changes of [{ ciphertext: mutateBase64(original.ciphertext) }, { nonce: mutateBase64(original.nonce) },
    { algorithm: 'AES-CBC' }, { schema: 99 }, { nonce: 'invalid' }, { extra: true }]) {
    await storage.set({ [LAST_ANALYSIS_KEY]: { ...original, ...changes } });
    await assert.rejects(loadLastAnalysis(storage, first), StorageEncryptionError);
  }
});

test('ciphertextul fără cheie e refuzat la citire și scriere, fără regenerare automată', async () => {
  const { storage, keyStore, first, second } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const state = await keyStore.read();
  await keyStore.write({ ...state, key: null });
  await assert.rejects(loadLastAnalysis(storage, second), /cheia locală.*lipsește/);
  await assert.rejects(second.write(storage, RUN_LOG_KEY, { schema: 1, text: 'nou' }), /cheia locală.*lipsește/);
  assert.equal((await keyStore.read()).key, null);
  assert.deepEqual(Object.keys(await storage.get()), [LAST_ANALYSIS_KEY]);
});

test('AAD refuză mutarea anvelopei analizei sub cheia jurnalului', async () => {
  const { storage, keyStore, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const envelope = (await storage.get())[LAST_ANALYSIS_KEY];
  const { key } = await keyStore.read();
  // Verificarea autenticității trebuie să pice înainte de validatorul formei jurnalului, altfel acel validator ar ascunde un AAD lipsă.
  await assert.rejects(decryptRecord(envelope, key, RUN_LOG_KEY), StorageEncryptionError);
  await storage.set({ [RUN_LOG_KEY]: envelope });
  await assert.rejects(loadSavedRunLog(storage, first), StorageEncryptionError);
});

test('conținut autentificat cu formă invalidă este eroare explicită', async () => {
  const { storage, first } = setup();
  await first.write(storage, LAST_ANALYSIS_KEY, { schema: 1, orders: [] });
  await assert.rejects(loadLastAnalysis(storage, first), /forma așteptată/);
});

test('schema1 pentru analiză și jurnal migrează fără pierderi la prima citire', async () => {
  const { storage, first } = setup();
  await storage.set({ [LAST_ANALYSIS_KEY]: entry(), [RUN_LOG_KEY]: { schema: 1, text: 'jurnal vechi inventat' } });
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
  assert.equal(await loadSavedRunLog(storage, first), 'jurnal vechi inventat');
  assert.equal((await storage.get())[LAST_ANALYSIS_KEY].schema, 2);
  assert.equal((await storage.get())[RUN_LOG_KEY].schema, 2);
});

test('migrarea care nu încape păstrează exact schema1 și raportează eșecul; reîncercarea poate reuși', async () => {
  const { storage, first } = setup();
  await storage.set({ [LAST_ANALYSIS_KEY]: entry() });
  const old = await storage.get();
  storage.failSet = true;
  await assert.rejects(loadLastAnalysis(storage, first), /migrarea criptată nu a reușit/);
  assert.deepEqual(await storage.get(), old);
  storage.failSet = false;
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
  assert.equal((await storage.get())[LAST_ANALYSIS_KEY].schema, 2);
});

test('cota plină la scriere păstrează exact anvelopa și analiza veche', async () => {
  const { storage, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const old = await storage.get();
  storage.failSet = true;
  await assert.rejects(saveLastAnalysis(entry({ created_at: '2026-02-01 12:00:00' }), storage, first), StorageFull);
  assert.deepEqual(await storage.get(), old);
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
});

test('două file creează o singură cheie și ambele date rămân decriptabile', async () => {
  const { storage, keyStore, first, second } = setup();
  const log = new RunLog({ storage, persistence: second, flushIntervalMs: 0 });
  log.info('inventat', 'primul pas');
  await Promise.all([saveLastAnalysis(entry(), storage, first), log.flush()]);
  assert.deepEqual(await loadLastAnalysis(storage, second), entry());
  assert.equal(await loadSavedRunLog(storage, first), log.text());
  assert.equal((await keyStore.read()).key.extractable, false);
});

test('ștergerea scoate cheia; o analiză nouă primește altă cheie', async () => {
  const { storage, keyStore, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const old = await keyStore.read();
  await deleteAllData(storage, first);
  assert.deepEqual(await storage.get(), {});
  assert.equal((await keyStore.read()).key, null);
  assert.notEqual((await keyStore.read()).generation, old.generation);
  await saveLastAnalysis(entry(), storage, first);
  assert.notDeepEqual((await keyStore.read()).key, old.key);
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
});

test('clear eșuat păstrează cheia și datele citibile', async () => {
  const { storage, keyStore, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  const old = await storage.get();
  const state = await keyStore.read();
  storage.failClear = true;
  await assert.rejects(deleteAllData(storage, first), /clear failed/);
  assert.deepEqual(await storage.get(), old);
  assert.equal((await keyStore.read()).generation, state.generation);
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
});

test('jurnalul vechi și flush-urile sale întârziate nu reapar după ștergere', async () => {
  const { storage, keyStore, first, second } = setup();
  const entered = deferred();
  const release = deferred();
  storage.beforeSet = async () => { entered.resolve(); await release.promise; };
  const log = new RunLog({ storage, persistence: second, flushIntervalMs: 0 });
  log.info('inventat', 'înainte');
  const pending = log.flush();
  await entered.promise;
  const deleting = deleteAllData(storage, first);
  release.resolve();
  await pending;
  await deleting;
  log.info('inventat', 'după ștergere');
  assert.equal(await log.flush(), false);
  assert.deepEqual(await storage.get(), {});
  assert.equal((await keyStore.read()).key, null);
});

test('o filă veche nu poate rescrie după ștergere nici după recitirea altor intrări', async () => {
  const { storage, first, second } = setup();
  await second.generation(storage);
  await saveLastAnalysis(entry(), storage, first);
  await deleteAllData(storage, first);
  await assert.rejects(saveLastAnalysis(entry(), storage, second), /șterse între timp/);
  assert.deepEqual(await storage.get(), {});
  assert.equal(await loadLastAnalysis(storage, second), null);
  assert.equal(await loadSavedRunLog(storage, second), null);
  await assert.rejects(saveLastAnalysis(entry(), storage, second), /șterse între timp/);
  await saveLastAnalysis(entry(), storage, first);
  assert.deepEqual(await loadLastAnalysis(storage, first), entry());
});

test('ștergerea recuperează și un key store corupt, fără să încerce decriptarea', async () => {
  const { storage, keyStore, first } = setup();
  await saveLastAnalysis(entry(), storage, first);
  await keyStore.write({ generation: 7, key: 'stricat' });
  await assert.rejects(loadLastAnalysis(storage, first), /cheia locală.*invalid/);
  await deleteAllData(storage, first);
  assert.deepEqual(await storage.get(), {});
  assert.equal((await keyStore.read()).key, null);
});
