// Verifică invalidarea între file: ștergerea câștigă în fața citirilor vechi, iar o rulare proprie nu este întreruptă.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { watchSavedAnalysis } from '../../src/ecrane/saved_analysis_watch.js';
import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';

/** Eveniment de stocare controlat, fără browser. */
function event() {
  const listeners = new Set();
  return {
    addListener: (fn) => listeners.add(fn), removeListener: (fn) => listeners.delete(fn),
    fire: (entries = { [LAST_ANALYSIS_KEY]: {} }, area = 'local') => { for (const fn of listeners) fn(entries, area); },
  };
}

/** O citire a cărei terminare este controlată de test. */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

/** Lasă să se încheie lanțul de promisiuni al evenimentului. */
const settled = () => new Promise((resolve) => setImmediate(resolve));

test('ștergerea invalidează imediat și exclude rezultatul vechii citiri', async () => {
  const changes = event();
  const reads = [deferred(), deferred()];
  const loaded = [];
  let invalidations = 0;
  let next = 0;
  const stop = watchSavedAnalysis({ changes, read: () => reads[next++].promise, onInvalidate: () => { invalidations += 1; }, onLoad: (entry) => loaded.push(entry), onError: assert.fail });
  changes.fire();
  changes.fire();
  assert.equal(invalidations, 2);
  await settled();
  reads[1].resolve(null);
  await settled();
  reads[0].resolve({ old: true });
  await settled();
  assert.deepEqual(loaded, [null]);
  stop();
});

test('ignoră alte chei și zona session, nu întrerupe rularea proprie, oprește ascultarea la ieșire', async () => {
  const changes = event();
  let running = true;
  let invalidations = 0;
  const loaded = [];
  const stop = watchSavedAnalysis({ changes, read: async () => 'nou', canReload: () => !running, onInvalidate: () => { invalidations += 1; }, onLoad: (entry) => loaded.push(entry), onError: assert.fail });
  changes.fire();
  running = false;
  changes.fire({ altceva: {} });
  changes.fire(undefined, 'session');
  assert.equal(invalidations, 0);
  changes.fire();
  await settled();
  assert.deepEqual(loaded, ['nou']);
  stop();
  changes.fire();
  assert.equal(invalidations, 1);
});

test('un eșec de citire ajunge la UI, dar nimic nu se aplică după dezabonare', async () => {
  const changes = event();
  const read = deferred();
  const errors = [];
  const stop = watchSavedAnalysis({ changes, read: () => read.promise, onInvalidate() {}, onLoad: assert.fail, onError: (error) => errors.push(error.message) });
  changes.fire();
  read.reject(new Error('stocare inaccesibilă'));
  await settled();
  assert.deepEqual(errors, ['stocare inaccesibilă']);
  changes.fire();
  stop();
  await settled();
  assert.equal(errors.length, 1);
});
