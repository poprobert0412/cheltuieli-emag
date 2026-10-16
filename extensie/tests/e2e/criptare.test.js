// WebCrypto și IndexedDB reale în Edge/Chromium, într-un profil temporar: două file, restart persistent, tamper și cheie lipsă.
// Datele sunt inventate; rețeaua reală este blocată la DNS și fiecare browser este închis înainte de reutilizarea profilului.
// EXT_DIST_DIR poate alege copia construită izolată, la fel ca harness.js. Nu schimbă stocarea sau datele profilului utilizatorului.
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { chromium } from 'playwright-core';
import { BROWSER_CHANNEL, DIST_DIR } from './harness.js';

const BROWSER_TIMEOUT_MS = 30000;
const TEST_TIMEOUT_MS = 120000;
const ANALYSIS_KEY = 'ultima_analiza';
const LOG_KEY = 'jurnal_rulare';

test('criptarea persistă după restart; două file împart cheia, iar tamper/cheie lipsă oferă ștergere recuperabilă', { timeout: TEST_TIMEOUT_MS }, async (t) => {
  const profile = mkdtempSync(path.join(tmpdir(), 'emag-crypto-persistent-'));
  const sessions = [];
  let currentSession;
  let context = null;
  let appUrl;

  /** Deschide același profil și găsește originea extensiei; se colectează orice eroare de consolă sau de pagină. */
  async function launch() {
    context = await chromium.launchPersistentContext(profile, {
      channel: BROWSER_CHANNEL, headless: true, timeout: BROWSER_TIMEOUT_MS,
      args: [`--disable-extensions-except=${DIST_DIR}`, `--load-extension=${DIST_DIR}`, '--host-resolver-rules=MAP * ~NOTFOUND'],
    });
    const captured = { active: [], teardown: [], closing: false };
    sessions.push(captured);
    currentSession = captured;
    const note = (text) => (captured.closing ? captured.teardown : captured.active).push(text);
    context.on('console', (message) => { if (message.type() === 'error') note(message.text()); });
    context.on('weberror', (error) => note(error.error().message));
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker', { timeout: BROWSER_TIMEOUT_MS });
    appUrl = `chrome-extension://${new URL(worker.url()).host}/aplicatie.html`;
  }

  /** Ca harness-ul: verifică sesiunea activă înainte de închidere; diagnosticele teardown sunt raportate separat, fără filtrare după text. */
  async function closeActiveSession() {
    try {
      assert.deepEqual(currentSession.active, [], 'zero erori în sesiunea activă, înainte de închidere');
    } finally {
      currentSession.closing = true;
      await context.close();
      context = null;
      if (currentSession.teardown.length) t.diagnostic(`diagnostice la închiderea browserului: ${JSON.stringify(currentSession.teardown)}`);
    }
  }

  /** Pagina extensiei și ecranul așteptat după inițializarea stocării reale. */
  async function open(screen) {
    const page = await context.newPage();
    await page.goto(appUrl);
    await page.waitForSelector(`#screen-${screen}:not([hidden])`);
    return page;
  }

  try {
    await launch();
    let page = await open('ready');
    const other = await open('ready');
    const [saved, logText] = await Promise.all([
      page.evaluate(async () => {
        const { saveLastAnalysis } = await import('./stocare/last_analysis.js');
        const entry = { schema: 1, extension_version: chrome.runtime.getManifest().version,
          created_at: '2026-01-02 12:00:00', threshold_lei: 500, summary: structuredClone(window.EMAG_DEMO_DATA),
          orders: [{ order_id: '100000001', name: 'Produs inventat pentru criptare' }], returns: [], log_text: 'jurnal analiză inventată\n' };
        entry.summary.meta.demo = false;
        await saveLastAnalysis(entry);
        return entry;
      }),
      other.evaluate(async () => {
        const { RunLog } = await import('./stocare/run_log.js');
        const log = new RunLog({ flushIntervalMs: 0 });
        log.info('inventat', 'jurnal concurent inventat');
        if (!(await log.flush())) throw new Error('flush-ul real nu a reușit');
        return log.text();
      }),
    ]);
    const raw = await page.evaluate(() => chrome.storage.local.get());
    assert.equal(raw[ANALYSIS_KEY].schema, 2);
    assert.equal(raw[LOG_KEY].schema, 2);
    assert.doesNotMatch(JSON.stringify(raw), /Produs inventat|100000001|jurnal concurent|jurnal analiză/);
    const keyInfo = await page.evaluate(async () => {
      const { createKeyStore } = await import('./stocare/key_store.js');
      const { key } = await createKeyStore().read();
      let exported = false;
      try { await crypto.subtle.exportKey('raw', key); exported = true; } catch { /* cheia neexportabilă trebuie refuzată */ }
      return { extractable: key.extractable, bits: key.algorithm.length, exported };
    });
    assert.deepEqual(keyInfo, { extractable: false, bits: 256, exported: false });
    await closeActiveSession();

    await launch();
    page = await open('done');
    const decoded = await page.evaluate(async () => {
      const { loadLastAnalysis } = await import('./stocare/last_analysis.js');
      const { loadSavedRunLog } = await import('./stocare/run_log.js');
      return { entry: await loadLastAnalysis(), log: await loadSavedRunLog() };
    });
    assert.deepEqual(decoded, { entry: saved, log: logText });
    await page.evaluate(async (key) => {
      const data = await chrome.storage.local.get(key);
      const record = data[key];
      record.ciphertext = `${record.ciphertext.startsWith('A') ? 'B' : 'A'}${record.ciphertext.slice(1)}`;
      await chrome.storage.local.set(data);
    }, ANALYSIS_KEY);
    await page.reload();
    await page.waitForSelector('#screen-error:not([hidden])');
    assert.match(await page.textContent('#error-message'), /datele criptate nu se pot citi/);
    assert.ok(await page.isVisible('#screen-error #btn-delete-data'));

    await page.evaluate(async ({ key, record }) => {
      await chrome.storage.local.set({ [key]: record });
      const { createKeyStore } = await import('./stocare/key_store.js');
      const store = createKeyStore();
      const state = await store.read();
      await store.write({ ...state, key: null });
    }, { key: ANALYSIS_KEY, record: raw[ANALYSIS_KEY] });
    await page.reload();
    await page.waitForSelector('#screen-error:not([hidden])');
    assert.match(await page.textContent('#error-message'), /cheia locală.*lipsește/);
    const stillMissing = await page.evaluate(async () => {
      const { createKeyStore } = await import('./stocare/key_store.js');
      return (await createKeyStore().read()).key === null;
    });
    assert.equal(stillMissing, true, 'citirea nu regenerează cheia pierdută');
    await page.click('#btn-delete-data');
    await page.click('#btn-delete-confirm');
    await page.waitForSelector('#screen-ready:not([hidden])');
    assert.deepEqual(await page.evaluate(() => chrome.storage.local.get()), {});
    await closeActiveSession();

    await launch();
    page = await open('ready');
    const afterDelete = await page.evaluate(async () => {
      const { createKeyStore } = await import('./stocare/key_store.js');
      return { data: await chrome.storage.local.get(), keyMissing: (await createKeyStore().read()).key === null };
    });
    assert.deepEqual(afterDelete, { data: {}, keyMissing: true });
    assert.deepEqual(sessions.flatMap((session) => session.active), []);
  } finally {
    try {
      if (context) await closeActiveSession();
    } finally {
      const absolute = path.resolve(profile);
      assert.ok(absolute.startsWith(`${path.resolve(tmpdir())}${path.sep}`), 'se curăță numai profilul temporar creat de test');
      rmSync(absolute, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    }
  }
});
