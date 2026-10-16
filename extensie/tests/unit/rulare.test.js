// Teste unitare pentru extensie/src/rulare/: o analiză din cap în coadă (lacăt, jurnal, colectare, analiză, salvare) și încărcarea analizei cu configurările generate la build.
// Colectarea, analiza și stocarea se înlocuiesc cu funcții false care notează ordinea apelurilor: aici se verifică legarea (ce se întâmplă la succes, la eroare, la oprire, când lacătul e ocupat
// sau când o regulă de categorii e greșită), nu calculele (acelea au paritatea lor cu Python). Ceasul e fals, ca data analizei să fie cunoscută.
// Câteva teste folosesc piese reale, din tests/unit/piese_reale.js: validatorul raportului (interfata/assets/dashboard.js, într-un context node:vm) ca rezumatul salvat să fie cel pe care îl acceptă ecranul,
// și analiza reală (calcul/*, cu config/*.json) ca rândurile ei să ajungă în jurnalul rulării. Ce NU face: nu pornește Chrome și nu citește pagini eMAG.
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import 'fake-indexeddb/auto';

import { PyFloat } from '../../src/calcul/python_compat.js';
import { plainSummary } from '../../src/calcul/spend_analysis.js';
import { PHASE_ANALYZING, Progress, RunCancelled } from '../../src/colectare/progress.js';
import { SessionExpired } from '../../src/colectare/page_fetcher.js';
import { RunBusy } from '../../src/stocare/run_lock.js';
import { StorageFull } from '../../src/stocare/last_analysis.js';
import { RunLog, loadSavedRunLog } from '../../src/stocare/run_log.js';
import { loadAnalysis } from '../../src/rulare/analysis_loader.js';
import { runPipeline } from '../../src/rulare/run_pipeline.js';
import { loadReportAssets, realAnalysisLoaders } from './piese_reale.js';

const APP_TAB = 11;
const WORK_TAB = 500;
const NOW = new Date(2026, 9, 14, 9, 30, 45, 123);

/** chrome.storage fals, minim: doar ce cere RunLog. */
function silentStorage() {
  return { async set() {}, async get() { return {}; }, async remove() {} };
}

/** Dependențe false pentru runPipeline, cu jurnalul apelurilor în `calls`. Orice cheie se poate înlocui. */
function makeDeps(overrides = {}) {
  const calls = [];
  const deps = {
    acquireRunLock: async (tab) => { calls.push(['acquire', tab]); },
    releaseRunLock: async (tab) => { calls.push(['release', tab]); },
    registerWorkTab: async (tab, work) => { calls.push(['register', tab, work]); },
    loadAnalysis: async () => {
      calls.push(['loadAnalysis']);
      return {
        analyze: (orders, returns, thresholdBani, generatedAt, log) => {
          calls.push(['analyze', orders, returns, thresholdBani, generatedAt, log]);
          return { summary: { meta: { generated_at: generatedAt } }, lines: [] };
        },
        plainSummary, // funcția reală: e pură, iar testele de mai jos cer exact ce face ea
      };
    },
    collectAll: async (options) => {
      calls.push(['collect', options.openerTabId, options.maxOrders]);
      options.onWorkTab(WORK_TAB);
      return { orders: [{ order_id: '100000001' }], returns: [{ return_id: '55' }] };
    },
    saveLastAnalysis: async (entry) => { calls.push(['save', entry]); },
    clearSavedRunLog: async () => { calls.push(['clearLog']); },
    ...overrides,
  };
  return { deps, calls };
}

/** O rulare pregătită: opțiunile, notarea apelurilor și instantaneele de progres; `overrides` schimbă opțiunile, `depOverrides` dependențele. */
function makeRun(overrides = {}, depOverrides = {}) {
  const { deps, calls } = makeDeps(depOverrides);
  const snapshots = [];
  const progress = new Progress({ onChange: (snapshot) => snapshots.push(snapshot) });
  const log = new RunLog({ storage: silentStorage(), flushIntervalMs: 0, clock: () => NOW });
  const options = { thresholdLei: 500, appTabId: APP_TAB, progress, log, extensionVersion: '0.1.0', clock: () => NOW, deps, ...overrides };
  return { options, calls, snapshots, log, progress, run: () => runPipeline(options) };
}

const names = (calls) => calls.map(([name]) => name);

describe('runPipeline: lacăt, jurnal, colectare, analiză, salvare', () => {
  test('succes: ordinea e lacăt, încărcarea analizei (înainte de colectare), colectare, analiză, salvare, ștergerea jurnalului de lucru, eliberarea lacătului', async () => {
    const { run, calls } = makeRun();
    await run();
    assert.deepEqual(names(calls), ['acquire', 'loadAnalysis', 'collect', 'register', 'analyze', 'save', 'clearLog', 'release']);
  });

  test('intrarea salvată are forma din E4: versiune, dată, prag, analiză, comenzi, retururi, jurnal', async () => {
    const { run, calls } = makeRun();
    const entry = await run();
    assert.deepEqual(calls.find(([name]) => name === 'save')[1], entry);
    assert.equal(entry.schema, 1);
    assert.equal(entry.extension_version, '0.1.0');
    assert.equal(entry.created_at, '2026-10-14 09:30:45');
    assert.equal(entry.threshold_lei, 500);
    assert.deepEqual(entry.orders, [{ order_id: '100000001' }]);
    assert.deepEqual(entry.returns, [{ return_id: '55' }]);
    assert.deepEqual(entry.summary, { meta: { generated_at: '2026-10-14 09:30' } });
    assert.match(entry.log_text, /\[run_pipeline\] INFO: pornesc rularea \(prag 500 lei, versiunea 0\.1\.0\)/);
    assert.match(entry.log_text, /1 comenzi și 1 retururi/);
  });

  test('pragul se rotunjește în bani ca round() din Python: 0,025 lei înseamnă 2 bani (jumătatea la par), nu 3', async () => {
    const { run, calls } = makeRun({ thresholdLei: 0.025 });
    await run();
    assert.equal(calls.find(([name]) => name === 'analyze')[3], 2);
    const { run: runWhole, calls: wholeCalls } = makeRun({ thresholdLei: 999.5 });
    await runWhole();
    assert.equal(wholeCalls.find(([name]) => name === 'analyze')[3], 99950);
  });

  test('colectarea primește fila aplicației ca vecină a filei de lucru și limita de comenzi; fila de lucru ajunge în evidența lacătului și la apelant', async () => {
    const seen = [];
    const { run, calls } = makeRun({ maxOrders: 3, onWorkTab: (id) => seen.push(id) });
    await run();
    assert.deepEqual(calls.find(([name]) => name === 'collect'), ['collect', APP_TAB, 3]);
    assert.deepEqual(calls.find(([name]) => name === 'register'), ['register', APP_TAB, WORK_TAB]);
    assert.deepEqual(seen, [WORK_TAB]);
  });

  test('faza „analyzing” începe înainte de calcul', async () => {
    const { run, snapshots } = makeRun();
    await run();
    assert.ok(snapshots.some((snapshot) => snapshot.phase === PHASE_ANALYZING));
  });

  test('lacătul ocupat: RunBusy și nimic altceva (nici analiză încărcată, nici colectare, nici eliberare)', async () => {
    const { run, calls } = makeRun({}, { acquireRunLock: async () => { throw new RunBusy(); } });
    await assert.rejects(run(), RunBusy);
    assert.deepEqual(calls, []);
  });

  test('o regulă greșită oprește rularea ÎNAINTE de colectare, iar lacătul se eliberează', async () => {
    const { run, calls } = makeRun({}, { loadAnalysis: async () => { throw new Error('categorii.json: în categoria \'X\', «patterns» trebuie să fie o listă de texte'); } });
    await assert.rejects(run(), /categorii\.json/);
    assert.deepEqual(names(calls), ['acquire', 'release']);
  });

  test('sesiune expirată în colectare: nimic nu se salvează, jurnalul de lucru rămâne, lacătul se eliberează, eroarea ajunge la apelant', async () => {
    const { run, calls, log } = makeRun({}, { collectAll: async () => { throw new SessionExpired('redirecționat la login'); } });
    await assert.rejects(run(), SessionExpired);
    assert.deepEqual(names(calls), ['acquire', 'loadAnalysis', 'release']);
    assert.match(log.text(), /ERROR: rularea a eșuat \(session_expired\): redirecționat la login/);
  });

  test('oprire cerută: RunCancelled, fără salvare, cu un rând în jurnal care spune că omul a oprit rularea', async () => {
    const { run, calls, log } = makeRun({}, { collectAll: async () => { throw new RunCancelled(); } });
    await assert.rejects(run(), RunCancelled);
    assert.ok(!names(calls).includes('save'));
    assert.ok(names(calls).includes('release'));
    assert.match(log.text(), /INFO: rularea a fost oprită la cererea ta/);
    assert.doesNotMatch(log.text(), /ERROR/);
  });

  test('stocare plină la salvare: analiza veche rămâne (salvarea nu a reușit), jurnalul de lucru se păstrează, lacătul se eliberează', async () => {
    const { run, calls } = makeRun({}, { saveLastAnalysis: async () => { throw new StorageFull(); } });
    await assert.rejects(run(), StorageFull);
    assert.ok(!names(calls).includes('clearLog'));
    assert.deepEqual(names(calls).at(-1), 'release');
  });

  test('o eroare la eliberarea lacătului nu acoperă rezultatul rulării', async () => {
    const { run } = makeRun({}, { releaseRunLock: async () => { throw new Error('storage indisponibil'); } });
    const entry = await run();
    assert.equal(entry.schema, 1);
  });

  test('la succes jurnalul de lucru dispare din stocare și nu reapare (flush-ul din finally nu-l mai scrie)', async () => {
    const store = new Map();
    const storage = {
      async set(items) { for (const [key, value] of Object.entries(items)) store.set(key, JSON.parse(JSON.stringify(value))); },
      async get() { return {}; },
      async remove(key) { store.delete(key); },
    };
    const { options } = makeRun({}, { clearSavedRunLog: async () => storage.remove('jurnal_rulare') });
    options.log = new RunLog({ storage, flushIntervalMs: 5, clock: () => NOW });
    await runPipeline(options);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.deepEqual([...store.keys()], [], 'jurnalul de lucru nu trebuie să rămână după o rulare reușită');
  });

  test('jurnalul se scrie în stocare la sfârșit, oricum se termină rularea (flush în finally)', async () => {
    const writes = [];
    const storage = {
      async set(items) { writes.push(items); },
      async get() { return writes.at(-1) ?? {}; },
      async remove() {},
    };
    const { options } = makeRun({}, { collectAll: async () => { throw new SessionExpired('x'); } });
    options.log = new RunLog({ storage, flushIntervalMs: 0, clock: () => NOW });
    await assert.rejects(runPipeline(options), SessionExpired);
    assert.ok(writes.length >= 1);
    assert.equal(Object.values(writes.at(-1))[0].schema, 2, 'jurnalul persistat este criptat');
    assert.match(await loadSavedRunLog(storage), /rularea a eșuat/);
  });
});

// ---------- încărcarea analizei ----------

/** Încărcătoare false pentru analiză: clasificatorul are categoriile date, restul notează cu ce au fost chemate. */
function fakeAnalysisLoaders({ categories = ['Alcool', 'Televizoare', 'Altele'], defaultCategory = 'Necategorizat' } = {}) {
  const calls = [];
  /** Clasificator fals: ține doar numele categoriilor și notează cu ce a fost construit. */
  class FakeClassifier {
    constructor(rules, source) { calls.push(['Classifier', rules, source]); this.categoryNames = categories; this.defaultCategory = defaultCategory; }
  }
  const config = { categorii: { r: 1 }, avertismente: { a: 1 }, culori: { c: 1 }, restituiri: { s: 1 } };
  return {
    calls,
    loaders: {
      config: async () => ({ default: config }),
      spendAnalysis: async () => ({ analyze: (...args) => { calls.push(['analyze', ...args]); return { summary: {}, lines: [] }; } }),
      classifier: async () => ({ Classifier: FakeClassifier }),
      warningDetails: async () => ({ loadWarningTexts: (data, source) => { calls.push(['loadWarningTexts', data, source]); return { texte: 1 }; } }),
      productKey: async () => ({ loadColorWords: (data, source) => { calls.push(['loadColorWords', data, source]); return { culori: 1 }; } }),
      refundModes: async () => ({ loadRefundModes: (data, source) => { calls.push(['loadRefundModes', data, source]); return { moduri: 1 }; } }),
    },
  };
}

describe('loadAnalysis: configurările generate la build, verificate înainte de colectare', () => {
  test('fiecare configurare ajunge la încărcătorul ei, cu numele fișierului din config/ ca sursă (ca path.name din Python)', async () => {
    const { loaders, calls } = fakeAnalysisLoaders();
    await loadAnalysis(loaders);
    assert.deepEqual(calls.find(([name]) => name === 'Classifier'), ['Classifier', { r: 1 }, 'categorii.json']);
    assert.deepEqual(calls.find(([name]) => name === 'loadWarningTexts'), ['loadWarningTexts', { a: 1 }, 'avertismente.json']);
    assert.deepEqual(calls.find(([name]) => name === 'loadColorWords'), ['loadColorWords', { c: 1 }, 'culori.json']);
    assert.deepEqual(calls.find(([name]) => name === 'loadRefundModes'), ['loadRefundModes', { s: 1 }, 'restituiri.json']);
  });

  test('analyze trimite analizei clasificatorul, pragul, data, categoriile evidențiate, celelalte configurări și jurnalul rulării', async () => {
    const { loaders, calls } = fakeAnalysisLoaders();
    const analysis = await loadAnalysis(loaders);
    const log = new RunLog({ storage: silentStorage(), flushIntervalMs: 0, clock: () => NOW });
    analysis.analyze([{ o: 1 }], [{ r: 1 }], 50000, '2026-10-14 09:30', log);
    const call = calls.find(([name]) => name === 'analyze');
    assert.deepEqual(call.slice(1, 3), [[{ o: 1 }], [{ r: 1 }]]);
    assert.equal(call[4], 50000);
    assert.equal(call[5], '2026-10-14 09:30');
    const { log: passedLog, ...options } = call[6];
    assert.deepEqual(options, { highlightCategories: ['Alcool', 'Televizoare'], warningTexts: { texte: 1 }, colorWords: { culori: 1 }, refundModes: { moduri: 1 } });
    assert.equal(passedLog, log, 'jurnalul primit de analyze trebuie să ajungă neschimbat la analiză');
  });

  test('plainSummary e funcția modulului analizei (aceeași, nu o copie locală): ea știe unde apar PyFloat în rezumat', async () => {
    const { loaders } = fakeAnalysisLoaders();
    const marker = () => 'copie simplă';
    const base = await loaders.spendAnalysis();
    loaders.spendAnalysis = async () => ({ ...base, plainSummary: marker });
    const analysis = await loadAnalysis(loaders);
    assert.equal(analysis.plainSummary, marker);
  });

  test('fără jurnal (de exemplu la recalcularea pentru produse.csv) analiza primește log: null, nu o valoare lipsă', async () => {
    const { loaders, calls } = fakeAnalysisLoaders();
    const analysis = await loadAnalysis(loaders);
    analysis.analyze([], [], 50000, '2026-10-14 09:30');
    assert.equal(calls.find(([name]) => name === 'analyze')[6].log, null);
  });

  test('o categorie evidențiată care nu există în reguli oprește rularea, cu mesajul din Python (altfel raportul ar arăta 0,00 Lei la ea)', async () => {
    const { loaders } = fakeAnalysisLoaders({ categories: ['Alcool', 'Altele'] });
    await assert.rejects(loadAnalysis(loaders), /categoria evidențiată «Televizoare» nu există în categorii\.json/);
  });

  test('„Necategorizat” (categoria implicită) cunoaște și ea totaluri, deci poate fi evidențiată', async () => {
    const { loaders } = fakeAnalysisLoaders({ categories: ['Alcool'], defaultCategory: 'Televizoare' });
    await loadAnalysis(loaders);
  });
});

// ---------- rezumatul salvat și afișat: numai tipuri JSON simple ----------

/** Rezumatul de demonstrație cu procentele de preț ca PyFloat (cum le dă analiza reală: float în Python); întoarce și numerele lor, în ordine, ca să se verifice că nu se schimbă. */
function withPyFloatPercentages(summary) {
  const copy = structuredClone(summary);
  const numbers = [];
  for (const product of copy.price_history.products) {
    if (typeof product.last_vs_prev_pct === 'number') {
      numbers.push(product.last_vs_prev_pct);
      product.last_vs_prev_pct = new PyFloat(product.last_vs_prev_pct);
    }
  }
  return { summary: copy, numbers };
}

/** Ce face chrome.storage cu un obiect: îl păstrează ca JSON, deci o instanță de clasă devine obiectul ei de proprietăți. */
const throughStorage = (value) => JSON.parse(JSON.stringify(value));

describe('runPipeline: rezumatul salvat și afișat are numai tipuri JSON simple (fără PyFloat)', () => {
  const { validate, demoSummary } = loadReportAssets();
  const { summary: summaryWithPyFloat, numbers } = withPyFloatPercentages(demoSummary());
  const analyzeWithPyFloat = async () => ({ analyze: () => ({ summary: summaryWithPyFloat, lines: [] }), plainSummary });

  test('premisa: validatorul real al raportului refuză un rezumat cu PyFloat, și cel citit înapoi din chrome.storage, și le acceptă pe cele cu numere', () => {
    assert.equal(validate(demoSummary()).ok, true, 'rezumatul de demonstrație trebuie să fie valid');
    assert.equal(validate(summaryWithPyFloat).ok, false);
    assert.equal(validate(throughStorage(summaryWithPyFloat)).ok, false);
    assert.ok(numbers.length > 0, 'rezumatul de probă are procente de preț');
  });

  test('intrarea întoarsă (ce desenează ecranul chiar după rulare) trece de validatorul raportului', async () => {
    const { run } = makeRun({}, { loadAnalysis: analyzeWithPyFloat });
    const entry = await run();
    const result = validate(entry.summary);
    assert.equal(result.ok, true, JSON.stringify(result.errors));
  });

  test('intrarea salvată, citită înapoi din chrome.storage (ce desenează ecranul la redeschidere), trece de validatorul raportului', async () => {
    const { run, calls } = makeRun({}, { loadAnalysis: analyzeWithPyFloat });
    await run();
    const saved = calls.find(([name]) => name === 'save')[1];
    const result = validate(throughStorage(saved.summary));
    assert.equal(result.ok, true, JSON.stringify(result.errors));
  });

  test('numerele procentelor rămân aceleași (PyFloat devine valoarea lui, nimic nu se rotunjește sau se pierde)', async () => {
    const { run } = makeRun({}, { loadAnalysis: analyzeWithPyFloat });
    const entry = await run();
    assert.deepEqual(entry.summary.price_history.products.map((product) => product.last_vs_prev_pct).filter((value) => value !== undefined && value !== null), numbers);
  });

  test('rezumatul primit de la analiză rămâne neatins: copia simplă se face pentru salvare, nu pe obiectul analizei', async () => {
    const { run } = makeRun({}, { loadAnalysis: analyzeWithPyFloat });
    await run();
    assert.ok(summaryWithPyFloat.price_history.products.some((product) => product.last_vs_prev_pct instanceof PyFloat));
  });
});

// ---------- jurnalul rulării primește rândurile analizei reale ----------

describe('runPipeline: mesajele analizei intră în jurnalul rulării (CLAUDE.md §9)', () => {
  test('analiza primește jurnalul rulării, același obiect care scrie jurnal.txt', async () => {
    const { run, calls, options } = makeRun();
    await run();
    assert.equal(calls.find(([name]) => name === 'analyze')[5], options.log);
  });

  test('cu analiza reală, rândurile ei (potrivirea retururilor, totalul plătit) apar în jurnalul intrării salvate', async () => {
    const { run } = makeRun({}, {
      loadAnalysis: () => loadAnalysis(realAnalysisLoaders()),
      collectAll: async () => ({ orders: [], returns: [] }),
    });
    const entry = await run();
    assert.match(entry.log_text, /\[return_matcher\] INFO: retururi aplicate: 0 unități/);
    assert.match(entry.log_text, /\[spend_analysis\] INFO: analiză: 0 comenzi, plătit efectiv 0 bani/);
  });
});
