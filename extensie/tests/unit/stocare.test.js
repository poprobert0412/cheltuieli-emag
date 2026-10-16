// Teste unitare pentru extensie/src/stocare/: ultima analiză (E4), jurnalul rulării și lacătul „o singură analiză odată”, pe un chrome.storage fals.
// Spațiul fals imită ce contează: valorile trec prin JSON (Map devine {}, undefined dispare, ca în Chrome) și are o cotă de octeți ca să se vadă „stocare plină”.
// Lacătul folosește Web Locks reale (Node 24 le are, ca paginile extensiei): două pagini ale aceleiași origini nu pot ține lacătul deodată.
// Ce NU face: nu pornește Chrome (comportamentul din browser se probează în Edge, într-un pas separat).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import 'fake-indexeddb/auto';

import { CODE_BUSY, CODE_STORAGE_FULL } from '../../src/colectare/run_errors.js';
import {
  ENTRY_SCHEMA, LAST_ANALYSIS_KEY, StorageFull, deleteAllData, loadLastAnalysis, saveLastAnalysis,
} from '../../src/stocare/last_analysis.js';
import {
  RUN_LOG_KEY, RunLog, clearSavedRunLog, loadSavedRunLog,
} from '../../src/stocare/run_log.js';
import { RunBusy, createRunLock } from '../../src/stocare/run_lock.js';

// ---------- unelte de test ----------

/** chrome.storage.<zonă> fals: valorile trec prin JSON ca în Chrome; `quotaBytes` simulează „QUOTA_BYTES quota exceeded”. */
function makeFakeStorage({ quotaBytes = Infinity, failWith = null, setDelaysMs = [] } = {}) {
  const data = new Map();
  const delays = [...setDelaysMs];
  const sizeOf = (entries) => [...entries].reduce((sum, [key, value]) => sum + key.length + JSON.stringify(value).length, 0);
  return {
    data,
    writes: 0,
    async get(keys) {
      const wanted = keys == null ? [...data.keys()] : typeof keys === 'string' ? [keys] : keys;
      const result = {};
      for (const key of wanted) if (data.has(key)) result[key] = JSON.parse(JSON.stringify(data.get(key)));
      return result;
    },
    async set(items) {
      if (failWith) throw new Error(failWith);
      const delay = delays.shift() ?? 0; // o scriere lentă urmată de una rapidă: fără coadă, cea veche ar ajunge ultima
      if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
      const next = new Map(data);
      for (const [key, value] of Object.entries(items)) next.set(key, JSON.parse(JSON.stringify(value)));
      if (sizeOf(next) > quotaBytes) throw new Error('QUOTA_BYTES quota exceeded');
      for (const [key, value] of next) data.set(key, value);
      this.writes += 1;
    },
    async remove(keys) {
      for (const key of typeof keys === 'string' ? [keys] : keys) data.delete(key);
    },
    async clear() {
      data.clear();
    },
  };
}

/** O intrare de ultimă analiză, cu date inventate (fără nume reale, fără HTML). */
function sampleEntry(overrides = {}) {
  return {
    schema: ENTRY_SCHEMA,
    extension_version: '0.1.0',
    created_at: '2026-10-14 09:30:00',
    threshold_lei: 500,
    summary: { meta: { generated_at: '2026-10-14 09:30', orders: 2 }, funnel: { ordered_bani: 12345 } },
    orders: [{ order_id: '100000001', placed_text: '1 ian. 2026', placed_at: '2026-01-01 10:00:00', header_total_bani: 12345, blocks: [], warnings: [] }],
    returns: [],
    log_text: '2026-10-14 09:29:00,001 [run_pipeline] INFO: pornesc rularea\n',
    ...overrides,
  };
}

let lockCounter = 0;
/**
 * Un lacăt cu nume propriu fiecărui test (Web Locks e global procesului: testele nu trebuie să se calce). `other` e „cealaltă pagină”: altă instanță a modulului
 * (fiecare filă a extensiei își încarcă propria copie), cu același nume de lacăt și aceeași evidență în chrome.storage.session.
 */
function freshLock(options = {}) {
  lockCounter += 1;
  const removedTabs = [];
  const session = options.session ?? makeFakeStorage();
  const shared = { lockName: `test-lacat-${lockCounter}`, session, removeTab: async (id) => { removedTabs.push(id); } };
  return { lock: createRunLock({ ...shared, ...options }), other: createRunLock({ ...shared, ...options }), session, removedTabs };
}

// ---------- ultima analiză ----------

describe('last_analysis: o singură intrare, înlocuită abia când noua analiză se termină cu bine (E4)', () => {
  test('în chrome.storage rămâne numai datele criptate, fără comenzile sau jurnalul în clar', async () => {
    const storage = makeFakeStorage();
    await saveLastAnalysis(sampleEntry(), storage);
    const stored = storage.data.get(LAST_ANALYSIS_KEY);
    assert.equal(stored.schema, 2);
    assert.equal(stored.algorithm, 'AES-GCM');
    assert.ok(!JSON.stringify(stored).includes('100000001'));
    assert.ok(!JSON.stringify(stored).includes('pornesc rularea'));
  });

  test('salvare și citire: aceeași intrare, sub cheia „ultima_analiza”', async () => {
    const storage = makeFakeStorage();
    const entry = sampleEntry();
    await saveLastAnalysis(entry, storage);
    assert.equal(LAST_ANALYSIS_KEY, 'ultima_analiza');
    assert.deepEqual([...storage.data.keys()], [LAST_ANALYSIS_KEY]);
    assert.deepEqual(await loadLastAnalysis(storage), entry);
  });

  test('fără nimic salvat, loadLastAnalysis întoarce null', async () => {
    assert.equal(await loadLastAnalysis(makeFakeStorage()), null);
  });

  test('o intrare stricată sau de altă schemă se tratează ca „nimic salvat”, nu ca eroare', async () => {
    const broken = [
      'text', 42, [], { ...sampleEntry(), schema: 99 }, { ...sampleEntry(), summary: null }, { ...sampleEntry(), orders: {} },
      { ...sampleEntry(), threshold_lei: 'cinci sute' }, { ...sampleEntry(), log_text: 5 },
    ];
    for (const value of broken) {
      const storage = makeFakeStorage();
      storage.data.set(LAST_ANALYSIS_KEY, value);
      assert.equal(await loadLastAnalysis(storage), null, JSON.stringify(value));
    }
  });

  test('schema criptată incompletă este eroare explicită, nu o analiză absentă', async () => {
    const storage = makeFakeStorage();
    storage.data.set(LAST_ANALYSIS_KEY, { schema: 2 });
    await assert.rejects(loadLastAnalysis(storage), /cheia locală|datele criptate/);
  });

  test('o intrare invalidă nu se salvează (TypeError) și nu strică ce era salvat', async () => {
    const storage = makeFakeStorage();
    await saveLastAnalysis(sampleEntry(), storage);
    await assert.rejects(saveLastAnalysis({ ...sampleEntry(), summary: undefined }, storage), TypeError);
    await assert.rejects(saveLastAnalysis({ ...sampleEntry(), schema: 99 }, storage), TypeError);
    assert.deepEqual(await loadLastAnalysis(storage), sampleEntry());
  });

  test('Map-urile din analiză se salvează ca obiecte obișnuite (altfel Chrome le-ar păstra ca {})', async () => {
    const storage = makeFakeStorage();
    const summary = { by_year: new Map([['2025', { bani: 100 }], ['2026', { bani: 200 }]]), list: [new Map([['a', 1]])] };
    await saveLastAnalysis(sampleEntry({ summary }), storage);
    const loaded = await loadLastAnalysis(storage);
    assert.deepEqual(loaded.summary, { by_year: { 2025: { bani: 100 }, 2026: { bani: 200 } }, list: [{ a: 1 }] });
  });

  test('o analiză nouă o înlocuiește pe cea veche; una care nu încape o lasă neatinsă și aruncă StorageFull', async () => {
    const storage = makeFakeStorage({ quotaBytes: 2000 });
    const old = sampleEntry();
    await saveLastAnalysis(old, storage);
    const huge = sampleEntry({ orders: Array.from({ length: 200 }, (_, i) => ({ order_id: String(100000000 + i), blocks: [] })) });
    await assert.rejects(saveLastAnalysis(huge, storage), (error) => {
      assert.ok(error instanceof StorageFull);
      assert.equal(error.code, CODE_STORAGE_FULL);
      return true;
    });
    assert.deepEqual(await loadLastAnalysis(storage), old, 'analiza veche a rămas');
    const newer = sampleEntry({ created_at: '2026-10-15 10:00:00' });
    await saveLastAnalysis(newer, storage);
    assert.deepEqual(await loadLastAnalysis(storage), newer);
  });

  test('altă eroare de scriere se aruncă nemodificată', async () => {
    const storage = makeFakeStorage({ failWith: 'Extension context invalidated' });
    await assert.rejects(saveLastAnalysis(sampleEntry(), storage), /Extension context invalidated/);
  });

  test('deleteAllData golește tot: ultima analiză și jurnalul rulării', async () => {
    const storage = makeFakeStorage();
    await saveLastAnalysis(sampleEntry(), storage);
    storage.data.set(RUN_LOG_KEY, { schema: 1, text: 'x' });
    await deleteAllData(storage);
    assert.equal(storage.data.size, 0);
    assert.equal(await loadLastAnalysis(storage), null);
  });

  test('intrarea nu păstrează HTML-ul paginilor: o cheie „html” în comenzi ar fi o scurgere și se refuză', async () => {
    const storage = makeFakeStorage();
    const leaky = sampleEntry({ orders: [{ order_id: '100000001', html: '<html>pagina întreagă</html>' }] });
    await assert.rejects(saveLastAnalysis(leaky, storage), TypeError);
    assert.equal(storage.data.size, 0);
  });
});

// ---------- jurnalul rulării ----------

describe('RunLog: format ca în Python, scris pe parcurs, nu doar la final', () => {
  /** Ceas fals care înaintează cu 1,5 s la fiecare citire, de la o oră de început. */
  function fakeClock() {
    let t = new Date(2026, 9, 14, 9, 5, 7, 42).getTime();
    return () => {
      const date = new Date(t);
      t += 1500;
      return date;
    };
  }

  test('fiecare rând: „ora [modul] NIVEL: mesaj”, cu milisecunde după virgulă, ca %(asctime)s din logging', () => {
    const log = new RunLog({ storage: makeFakeStorage(), clock: fakeClock(), flushIntervalMs: 0 });
    log.info('order_list_scraper', 'lista de comenzi: pagina 1 are 10 comenzi');
    log.warning('page_fetcher', '/p/1: încercarea 1/3 a eșuat (timeout)');
    log.error('run_pipeline', 'rularea a eșuat');
    assert.equal(log.text(), [
      '2026-10-14 09:05:07,042 [order_list_scraper] INFO: lista de comenzi: pagina 1 are 10 comenzi',
      '2026-10-14 09:05:08,542 [page_fetcher] WARNING: /p/1: încercarea 1/3 a eșuat (timeout)',
      '2026-10-14 09:05:10,042 [run_pipeline] ERROR: rularea a eșuat',
      '',
    ].join('\n'));
  });

  test('un mesaj pe mai multe rânduri rămâne pe un singur rând al jurnalului (nu se pot înșira rânduri false)', () => {
    const log = new RunLog({ storage: makeFakeStorage(), clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'primul\n2026-10-14 09:00:00,000 [x] ERROR: fals');
    assert.equal(log.text().split('\n').filter(Boolean).length, 1);
  });

  test('flush() scrie jurnalul sub cheia „jurnal_rulare”, iar loadSavedRunLog îl citește înapoi', async () => {
    const storage = makeFakeStorage();
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'pasul 1');
    assert.equal(await log.flush(), true);
    assert.equal(RUN_LOG_KEY, 'jurnal_rulare');
    assert.equal(await loadSavedRunLog(storage), log.text());
  });

  test('o rulare căzută lasă pe disc pașii de până la ultimul flush (pașii 1–4 rămân, 5 e pierdut)', async () => {
    const storage = makeFakeStorage();
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    for (let step = 1; step <= 4; step += 1) {
      log.info('m', `pasul ${step}`);
      await log.flush();
    }
    log.info('m', 'pasul 5'); // fila se închide aici, fără flush
    const saved = await loadSavedRunLog(storage);
    assert.match(saved, /pasul 4/);
    assert.doesNotMatch(saved, /pasul 5/);
  });

  test('flush-urile suprapuse se pun la coadă: la final e scris tot jurnalul, chiar dacă prima scriere e lentă', async () => {
    const storage = makeFakeStorage({ setDelaysMs: [40, 0] });
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'a');
    const first = log.flush();
    log.info('m', 'b');
    const second = log.flush();
    await Promise.all([first, second]);
    assert.equal(await loadSavedRunLog(storage), log.text());
    assert.match(log.text(), /INFO: b/);
  });

  test('rândurile scrise în același interval pleacă într-o singură scriere (nu o scriere pe rând)', async () => {
    const storage = makeFakeStorage();
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 20 });
    for (let i = 1; i <= 8; i += 1) log.info('m', `rând ${i}`);
    await new Promise((resolve) => setTimeout(resolve, 120));
    assert.equal(storage.writes, 1);
    assert.match(await loadSavedRunLog(storage), /rând 8/);
    log.info('m', 'încă unul');
    await new Promise((resolve) => setTimeout(resolve, 120));
    assert.equal(storage.writes, 2, 'un rând nou după scriere programează alta');
  });

  test('un rând scris cât se face o scriere lentă nu se pierde: următorul flush îl scrie (nu se socotește scris doar pentru că a venit în timpul unei scrieri)', async () => {
    const storage = makeFakeStorage({ setDelaysMs: [40] });
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'înainte');
    const slow = log.flush();
    await new Promise((resolve) => setTimeout(resolve, 5));
    log.info('m', 'în timpul scrierii');
    await slow;
    assert.doesNotMatch(await loadSavedRunLog(storage), /în timpul scrierii/);
    await log.flush();
    assert.match(await loadSavedRunLog(storage), /în timpul scrierii/);
  });

  test('flush() fără nimic nou de scris nu scrie din nou în stocare', async () => {
    const storage = makeFakeStorage();
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'a');
    assert.equal(await log.flush(), true);
    assert.equal(await log.flush(), true);
    assert.equal(storage.writes, 1);
    log.info('m', 'b');
    await log.flush();
    assert.equal(storage.writes, 2);
  });

  test('scriere automată la interval: un rând nou ajunge în stocare fără flush explicit', async () => {
    const storage = makeFakeStorage();
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 10 });
    log.info('m', 'automat');
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.match(await loadSavedRunLog(storage), /automat/);
  });

  test('un jurnal peste limită se taie cu un rând care spune asta, ca să nu umple cota extensiei', () => {
    const log = new RunLog({ storage: makeFakeStorage(), clock: fakeClock(), flushIntervalMs: 0, maxLines: 5 });
    for (let i = 1; i <= 20; i += 1) log.info('m', `rând ${i}`);
    const lines = log.text().split('\n').filter(Boolean);
    assert.equal(lines.length, 6);
    assert.match(lines[5], /jurnalul a depășit 5 rânduri/);
    assert.match(lines[4], /rând 5/);
  });

  test('o scriere care eșuează nu oprește rularea: flush() întoarce false și jurnalul spune asta o singură dată', async () => {
    const storage = makeFakeStorage({ failWith: 'QUOTA_BYTES quota exceeded' });
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'ceva');
    assert.equal(await log.flush(), false);
    assert.equal(await log.flush(), false);
    const notes = log.text().split('\n').filter((line) => line.includes('nu s-a putut salva'));
    assert.equal(notes.length, 1);
  });

  test('discard() oprește scrierile viitoare (cronometrul și flush-urile), ca jurnalul de lucru șters să nu reapară', async () => {
    const storage = makeFakeStorage({ setDelaysMs: [30] });
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 10 });
    log.info('m', 'înainte');
    const pending = log.flush(); // scriere în curs (lentă)
    log.info('m', 'după pornirea scrierii'); // programează o scriere automată
    await log.discard(); // așteaptă scrierea începută, anulează cronometrul
    await clearSavedRunLog(storage);
    log.info('m', 'târziu');
    await log.flush();
    await pending;
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.equal(await loadSavedRunLog(storage), null, 'nicio scriere după discard');
    assert.equal(storage.data.size, 0);
  });

  test('clearSavedRunLog șterge jurnalul salvat; fără jurnal salvat, loadSavedRunLog întoarce null', async () => {
    const storage = makeFakeStorage();
    assert.equal(await loadSavedRunLog(storage), null);
    const log = new RunLog({ storage, clock: fakeClock(), flushIntervalMs: 0 });
    log.info('m', 'x');
    await log.flush();
    await clearSavedRunLog(storage);
    assert.equal(await loadSavedRunLog(storage), null);
  });
});

// ---------- lacătul ----------

describe('run_lock: o singură analiză odată, cu Web Locks, și evidența filei de lucru în chrome.storage.session', () => {
  test('acquireRunLock ia lacătul și scrie evidența (fila aplicației, fără fila de lucru încă)', async () => {
    const { lock, session } = freshLock();
    await lock.acquireRunLock(11);
    const record = (await session.get(lock.RUN_LOCK_KEY))[lock.RUN_LOCK_KEY];
    assert.equal(record.appTabId, 11);
    assert.equal(record.workTabId, null);
    assert.match(record.startedAt, /^\d{4}-\d{2}-\d{2}T/);
    await lock.releaseRunLock(11);
  });

  test('a doua analiză cât prima rulează: RunBusy cu codul „busy”, și de la altă pagină, și de la aceeași', async () => {
    const { lock, other } = freshLock();
    await lock.acquireRunLock(11);
    await assert.rejects(other.acquireRunLock(12), (error) => {
      assert.ok(error instanceof RunBusy);
      assert.equal(error.code, CODE_BUSY);
      return true;
    });
    await assert.rejects(lock.acquireRunLock(11), RunBusy);
    await lock.releaseRunLock(11);
    await other.acquireRunLock(12);
    await other.releaseRunLock(12);
  });

  test('după releaseRunLock lacătul se poate lua din nou, iar evidența dispare', async () => {
    const { lock, session } = freshLock();
    await lock.acquireRunLock(11);
    await lock.releaseRunLock(11);
    assert.deepEqual(await session.get(lock.RUN_LOCK_KEY), {});
    await lock.acquireRunLock(12);
    await lock.releaseRunLock(12);
  });

  test('releaseRunLock cu id-ul altei file nu eliberează lacătul (nu-l ia nimeni altcineva de sub mână)', async () => {
    const { lock } = freshLock();
    await lock.acquireRunLock(11);
    await lock.releaseRunLock(99);
    await assert.rejects(lock.acquireRunLock(12), RunBusy);
    await lock.releaseRunLock(11);
  });

  test('isRunActive: adevărat (și pentru o altă pagină) cât lacătul e ținut, fals înainte și după', async () => {
    const { lock, other } = freshLock();
    assert.equal(await other.isRunActive(), false);
    await lock.acquireRunLock(11);
    assert.equal(await other.isRunActive(), true);
    await lock.releaseRunLock(11);
    assert.equal(await other.isRunActive(), false);
  });

  test('registerWorkTab trece fila de lucru în evidență doar pentru fila care ține lacătul', async () => {
    const { lock, session } = freshLock();
    await lock.acquireRunLock(11);
    await lock.registerWorkTab(99, 500);
    assert.equal((await session.get(lock.RUN_LOCK_KEY))[lock.RUN_LOCK_KEY].workTabId, null);
    await lock.registerWorkTab(11, 500);
    assert.equal((await session.get(lock.RUN_LOCK_KEY))[lock.RUN_LOCK_KEY].workTabId, 500);
    await lock.releaseRunLock(11);
  });

  test('lacăt vechi: evidența rămasă de la o filă care nu mai există (lacătul liber) se înlocuiește, iar fila de lucru rămasă orfană se închide', async () => {
    const session = makeFakeStorage();
    const { lock, removedTabs } = freshLock({ session });
    await session.set({ [lock.RUN_LOCK_KEY]: { appTabId: 7, workTabId: 321, startedAt: '2026-10-14T08:00:00.000Z' } });
    await lock.acquireRunLock(11);
    assert.deepEqual(removedTabs, [321]);
    assert.equal((await session.get(lock.RUN_LOCK_KEY))[lock.RUN_LOCK_KEY].appTabId, 11);
    await lock.releaseRunLock(11);
  });

  test('handleTabClosed (apelat de worker): închiderea filei aplicației închide fila de lucru și șterge evidența', async () => {
    const { lock, session, removedTabs } = freshLock();
    await lock.acquireRunLock(11);
    await lock.registerWorkTab(11, 500);
    assert.equal(await lock.handleTabClosed(12), false, 'altă filă: nimic de făcut');
    assert.deepEqual(removedTabs, []);
    assert.equal(await lock.handleTabClosed(11), true);
    assert.deepEqual(removedTabs, [500]);
    assert.deepEqual(await session.get(lock.RUN_LOCK_KEY), {});
    await lock.releaseRunLock(11);
  });

  test('handleTabClosed fără fila de lucru încă (analiza abia pornea) doar șterge evidența', async () => {
    const { lock, session, removedTabs } = freshLock();
    await lock.acquireRunLock(11);
    assert.equal(await lock.handleTabClosed(11), true);
    assert.deepEqual(removedTabs, []);
    assert.deepEqual(await session.get(lock.RUN_LOCK_KEY), {});
    await lock.releaseRunLock(11);
  });

  test('sweepStaleRecord (la deschiderea paginii): lacăt liber și evidență rămasă înseamnă o filă moartă: fila de lucru orfană se închide și evidența se șterge', async () => {
    const session = makeFakeStorage();
    const { lock, removedTabs } = freshLock({ session });
    await session.set({ [lock.RUN_LOCK_KEY]: { appTabId: 7, workTabId: 321, startedAt: '2026-10-14T08:00:00.000Z' } });
    assert.equal(await lock.sweepStaleRecord(), true);
    assert.deepEqual(removedTabs, [321]);
    assert.deepEqual(await session.get(lock.RUN_LOCK_KEY), {});
    assert.equal(await lock.sweepStaleRecord(), false, 'a doua oară nu mai e nimic de curățat');
  });

  test('sweepStaleRecord nu atinge evidența unei analize care rulează (lacătul e ținut de o altă pagină)', async () => {
    const { lock, other, session, removedTabs } = freshLock();
    await lock.acquireRunLock(11);
    await lock.registerWorkTab(11, 500);
    assert.equal(await other.sweepStaleRecord(), false);
    assert.deepEqual(removedTabs, []);
    assert.equal((await session.get(lock.RUN_LOCK_KEY))[lock.RUN_LOCK_KEY].workTabId, 500);
    await lock.releaseRunLock(11);
  });

  test('o eroare la scrierea evidenței eliberează lacătul (nu rămâne ocupat fără stăpân)', async () => {
    const { lock } = freshLock({ session: makeFakeStorage({ failWith: 'Extension context invalidated' }) });
    await assert.rejects(lock.acquireRunLock(11), /Extension context invalidated/);
    assert.equal(await lock.isRunActive(), false);
  });
});
