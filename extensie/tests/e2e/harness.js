// Harness-ul testelor cap-coadă: pornește browserul cu extensia din dist/ încărcată și cu eMAG-ul fals în loc de www.emag.ro, adună tot ce ar trebui să lipsească dintr-o rulare curată și oferă ajutoare pentru ecrane.
// Primește: opțiunile eMAG-ului fals (emag_fals.js) și, din mediu, EXT_TEST_CHANNEL (canalul browserului: implicit „msedge” pe Windows, „chromium” în rest) și EXT_DIST_DIR (alt folder cu extensia construită, de exemplu o copie mutată pentru verificarea testelor).
// Rețeaua reală nu există: browserul pornește cu --host-resolver-rules=MAP * ~NOTFOUND, www.emag.ro e servit de context.route, iar orice altă gazdă este oprită și notată. Fiecare scenariu cere la sfârșit zero erori de consolă, zero încălcări CSP și zero cereri spre alte gazde.
// Profilul browserului e un folder temporar, șters după fiecare scenariu. Testele rulează pe dist/: `npm run test:e2e` îl reconstruiește înainte; rulat direct, harness-ul refuză un dist/ care nu mai e copia surselor (comparație de conținut, nu de date: pe Windows copierea păstrează data fișierului).
// Ce NU face: nu știe ce verifică testele (acelea sunt în *.test.js) și nu schimbă nimic în extensie.
import assert from 'node:assert/strict';
import {
  existsSync, mkdtempSync, readFileSync, readdirSync, rmSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';

import { LAST_ANALYSIS_KEY } from '../../src/stocare/last_analysis.js';
import { createFakeEmag } from './emag_fals.js';

const EXTENSION_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const PROJECT_ROOT = path.resolve(EXTENSION_ROOT, '..');
// Folderul extensiei construite. EXT_DIST_DIR îl schimbă (o copie cu o defecțiune provocată, ca testele să se vadă picând); implicit extensie/dist.
export const DIST_DIR = process.env.EXT_DIST_DIR ? path.resolve(process.env.EXT_DIST_DIR) : path.join(EXTENSION_ROOT, 'dist');
// Canalul browserului: Edge pe Windows (Chromium-ul descărcat de Playwright nu pornește din aplicația Claude și Chrome oficial nu încarcă extensii din linia de comandă), Chromium în CI.
export const BROWSER_CHANNEL = process.env.EXT_TEST_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium');
// Nicio adresă nu se rezolvă: o cerere scăpată de context.route eșuează la rezolvarea numelui, nu ajunge pe internet.
const NO_NETWORK_ARGS = ['--host-resolver-rules=MAP * ~NOTFOUND'];
const APP_PAGE = 'aplicatie.html';
const PROFILE_PREFIX = 'cheltuieli-emag-e2e-';
// Termene: pornirea browserului cu extensia (câteva secunde local, mai mult pe o mașină încărcată), închiderea lui, un ecran care trebuie să apară și o analiză întreagă (cea mai lungă durează ~20 s local).
// Un scenariu întreg are 4 minute: destul pentru cele mai lungi, puțin cât un test blocat să pice cu un mesaj, nu să țină jobul până la termenul lui.
export const LAUNCH_TIMEOUT_MS = 60_000;
const CLOSE_TIMEOUT_MS = 20_000;
export const SCREEN_TIMEOUT_MS = 20_000;
// Ecranul „în lucru” trebuie să apară imediat după clicul pe „Pornește analiza”, înainte să se facă vreo citire.
export const WORKING_SCREEN_TIMEOUT_MS = 5_000;
export const RUN_TIMEOUT_MS = 90_000;
const SCENARIO_TIMEOUT_MS = 240_000;
const POLL_INTERVAL_MS = 100;
// Câte încercări are ștergerea profilului: pe Windows browserul mai ține câteva zeci de milisecunde fișierele după închidere.
const REMOVE_RETRIES = 10;
const REMOVE_RETRY_DELAY_MS = 200;
// Ce copiază build.mjs în dist/ fără să schimbe un octet: sursele din src/ (fără fișierele ascunse), manifestul și fișierele partajate din interfata/assets/ (în dist/partajat/).
const SHARED_FOLDER = 'partajat';

/** Pauză de `ms` milisecunde. */
export const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/** Repetă `check` până întoarce o valoare adevărată (o întoarce) sau până trece `timeoutMs` (aruncă eroare cu `what`). */
export async function waitFor(check, { timeoutMs = SCREEN_TIMEOUT_MS, what = 'condiția așteptată' } = {}) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`termen depășit (${timeoutMs} ms) cât așteptam: ${what}`);
    await sleep(POLL_INTERVAL_MS);
  }
}

/** Toate fișierele de sub `folder`, ca căi relative cu `/`, fără cele ascunse (cum le sare build.mjs). */
function filesUnder(folder, prefix = '') {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name.startsWith('.')) return [];
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    return entry.isDirectory() ? filesUnder(path.join(folder, entry.name), relative) : [relative];
  });
}

/** Primul fișier din `pairs` ([sursă, copie]) a cărui copie lipsește sau diferă de sursă; null dacă toate sunt identice. */
function firstStaleCopy(pairs) {
  const stale = pairs.find(([source, copy]) => !existsSync(source) || !existsSync(copy) || !readFileSync(source).equals(readFileSync(copy)));
  return stale ? stale[0] : null;
}

/** Refuză un dist/ care nu mai e copia surselor: un test care citește un artefact vechi dă și treceri, și eșecuri false. Nu se verifică dacă EXT_DIST_DIR arată spre o copie aleasă cu intenție. */
function assertBuildIsFresh() {
  if (process.env.EXT_DIST_DIR) return;
  assert.ok(existsSync(path.join(DIST_DIR, 'manifest.json')), `lipsește ${DIST_DIR}: rulează întâi npm run build (sau npm run test:e2e, care îl construiește)`);
  const sourceRoot = path.join(EXTENSION_ROOT, 'src');
  const pairs = [
    [path.join(EXTENSION_ROOT, 'manifest.json'), path.join(DIST_DIR, 'manifest.json')],
    ...filesUnder(sourceRoot).map((name) => [path.join(sourceRoot, name), path.join(DIST_DIR, name)]),
  ];
  const sharedCopies = path.join(DIST_DIR, SHARED_FOLDER);
  if (existsSync(sharedCopies)) pairs.push(...filesUnder(sharedCopies).map((name) => [path.join(PROJECT_ROOT, 'interfata', 'assets', name), path.join(sharedCopies, name)]));
  const stale = firstStaleCopy(pairs);
  assert.equal(stale, null, `dist/ nu mai corespunde sursei ${stale ? path.relative(PROJECT_ROOT, stale) : ''}: rulează npm run build (sau npm run test:e2e, care îl construiește) înainte de teste`);
}

/** Un mesaj de consolă care strică o rulare curată: orice eroare, plus avertismentele venite din codul extensiei. */
function consoleMessageIsIssue(message) {
  if (message.type() === 'error') return true;
  return message.type() === 'warning' && (message.location().url ?? '').startsWith('chrome-extension://');
}

/** Ce se scrie în lista de probleme despre un mesaj de consolă: tipul, textul și locul din care vine. */
function describeConsoleMessage(message) {
  const { url } = message.location();
  return `consolă ${message.type()}: ${message.text()}${url ? ` (${url})` : ''}`;
}

/** Șterge un folder (profilul browserului) cu mai multe încercări; un folder rămas în urmă nu strică testul. */
function removeFolder(folder) {
  try {
    rmSync(folder, { recursive: true, force: true, maxRetries: REMOVE_RETRIES, retryDelay: REMOVE_RETRY_DELAY_MS });
  } catch {
    // Rămâne un folder temporar al sistemului; nu merită să strice un test care a trecut.
  }
}

/**
 * Pornește o sesiune: browserul cu extensia încărcată, eMAG-ul fals pe www.emag.ro și colectorii de probleme.
 * Întoarce obiectul `session` cu ajutoarele pentru teste (vezi sfârșitul funcției); `close()` îl oprește și șterge profilul.
 */
async function startSession(fakeOptions) {
  assertBuildIsFresh();
  const fake = createFakeEmag(fakeOptions);
  const profileDir = mkdtempSync(path.join(tmpdir(), PROFILE_PREFIX));
  let context;
  try {
    context = await chromium.launchPersistentContext(profileDir, {
      channel: BROWSER_CHANNEL,
      headless: true,
      timeout: LAUNCH_TIMEOUT_MS,
      args: [`--disable-extensions-except=${DIST_DIR}`, `--load-extension=${DIST_DIR}`, ...NO_NETWORK_ARGS],
    });
  } catch (error) {
    removeFolder(profileDir);
    throw error;
  }
  const issues = []; // erori de consolă, excepții neprinse, cereri eșuate
  const cspViolations = []; // „directivă: adresă blocată”, din paginile extensiei
  const addIssue = (text) => { if (!issues.includes(text)) issues.push(text); };
  context.on('console', (message) => { if (consoleMessageIsIssue(message)) addIssue(describeConsoleMessage(message)); });
  context.on('weberror', (webError) => addIssue(`excepție neprinsă: ${webError.error().message}`));
  await context.route('**/*', fake.handle);

  let worker;
  try {
    [worker] = context.serviceWorkers();
    if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: LAUNCH_TIMEOUT_MS });
  } catch (error) {
    await closeSession(context, profileDir);
    throw new Error(`extensia din ${DIST_DIR} nu a pornit în ${LAUNCH_TIMEOUT_MS} ms (canalul ${BROWSER_CHANNEL}): ${error.message}`);
  }
  const extensionId = new URL(worker.url()).host;
  const appUrl = `chrome-extension://${extensionId}/${APP_PAGE}`;
  worker.on('console', (message) => { if (consoleMessageIsIssue(message)) addIssue(describeConsoleMessage(message)); });

  /** Deschide pagina aplicației într-o filă nouă, cu colectorul de încălcări CSP pus înainte de orice script al paginii. */
  async function openApp({ search = '' } = {}) {
    const page = await context.newPage();
    await page.exposeBinding('__raporteazaCsp', (_source, text) => { cspViolations.push(text); });
    await page.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', (event) => window.__raporteazaCsp(`${event.violatedDirective}: ${event.blockedURI}`));
    });
    await page.goto(`${appUrl}${search}`);
    return page;
  }

  /** Așteaptă ecranul `name` (secțiunea cu data-screen="name", nedeclarată hidden); întoarce elementul. */
  const screen = (page, name, timeout = SCREEN_TIMEOUT_MS) => page.waitForSelector(`section[data-screen="${name}"]:not([hidden])`, { timeout });
  /** Numele ecranelor vizibile acum (trebuie să fie exact unul). */
  const visibleScreens = (page) => page.evaluate(() => [...document.querySelectorAll('section[data-screen]')].filter((section) => !section.hidden).map((section) => section.getAttribute('data-screen')));
  /** Tot ce ține extensia în chrome.storage.local. */
  const storage = (page) => page.evaluate(() => chrome.storage.local.get());
  /** Datele citite prin modulele reale, pentru verificarea conținutului după decriptare; storage() rămâne vederea brută a anvelopelor. */
  const decodedStorage = (page) => page.evaluate(async () => {
    const { LAST_ANALYSIS_KEY: analysisKey, loadLastAnalysis } = await import('./stocare/last_analysis.js');
    const { RUN_LOG_KEY: logKey, loadSavedRunLog } = await import('./stocare/run_log.js');
    const result = await chrome.storage.local.get();
    if (analysisKey in result) result[analysisKey] = await loadLastAnalysis();
    if (logKey in result) result[logKey] = { schema: 1, text: await loadSavedRunLog() };
    return result;
  });
  /** Evidența lacătului din chrome.storage.session (goală când nu rulează nicio analiză). */
  const lockRecord = (page) => page.evaluate(() => chrome.storage.session.get());
  /** Numele Web Lock-urilor ținute acum de paginile extensiei (un lacăt pe durata unei analize, niciunul în rest). */
  const heldLocks = (page) => page.evaluate(async () => (await navigator.locks.query()).held.map((lock) => lock.name));
  /** Filele browserului: { id, url, active }; adresa se vede doar pentru www.emag.ro (extensia are permisiune doar acolo), altfel e gol. */
  const tabs = (page) => page.evaluate(async () => (await chrome.tabs.query({})).map((tab) => ({ id: tab.id, url: tab.url ?? '', active: tab.active })));
  /** Filele eMAG de lucru deschise acum: { id, active }. */
  const workTabs = (page) => page.evaluate(async () => (await chrome.tabs.query({ url: 'https://www.emag.ro/*' })).map((tab) => ({ id: tab.id, active: tab.active })));

  /** Salvează prin modulul real o analiză inventată criptată (raportul demonstrativ marcat ca real); întoarce data ei. */
  const seedLastAnalysis = (page, overrides = {}) => page.evaluate(async ({ key, extra }) => {
    const entry = {
      schema: 1,
      extension_version: chrome.runtime.getManifest().version,
      created_at: '2026-10-01 12:00:00',
      threshold_lei: 500,
      summary: structuredClone(window.EMAG_DEMO_DATA),
      orders: [],
      returns: [],
      log_text: '2026-10-01 12:00:00,000 [inventat] INFO: jurnal inventat\n',
      ...extra,
    };
    entry.summary.meta.demo = false;
    const { saveLastAnalysis } = await import('./stocare/last_analysis.js');
    await saveLastAnalysis(entry);
    return entry.created_at;
  }, { key: LAST_ANALYSIS_KEY, extra: overrides });

  /** Apasă „Pornește analiza” în `page` și așteaptă până se vede progresul comenzilor („Comenzi: N din M”): de aici fila de lucru există și analiza chiar lucrează. */
  async function startRun(page) {
    await page.click('#btn-start');
    await screen(page, 'working', WORKING_SCREEN_TIMEOUT_MS);
    await waitFor(async () => (await workTabs(page)).length > 0, { what: 'fila eMAG de lucru' });
    await waitFor(async () => /Comenzi: \d+ din \d+/.test(await page.textContent('#progress-label')), { timeoutMs: RUN_TIMEOUT_MS, what: 'bara de progres a comenzilor (după citirea listei de comenzi)' });
  }

  /** Scoate din lista de probleme pe cele care se potrivesc cu `pattern` și le întoarce: pentru cele pe care testul le provoacă intenționat. */
  function consumeIssues(pattern) {
    const matched = issues.filter((text) => pattern.test(text));
    for (const text of matched) issues.splice(issues.indexOf(text), 1);
    return matched;
  }

  /** La fel pentru încălcările CSP. */
  function consumeCspViolations(pattern) {
    const matched = cspViolations.filter((text) => pattern.test(text));
    for (const text of matched) cspViolations.splice(cspViolations.indexOf(text), 1);
    return matched;
  }

  /** Ce trebuie să lipsească dintr-o rulare curată: erori de consolă și excepții, încălcări CSP, cereri spre alte gazde sau care nu sunt GET, căi pe care eMAG-ul fals nu le știe. */
  function assertClean() {
    const { state } = fake;
    assert.deepEqual(issues, [], 'erori de consolă sau excepții neprinse');
    assert.deepEqual(cspViolations, [], 'încălcări ale politicii de conținut (CSP)');
    assert.deepEqual(state.foreign, [], 'cereri spre alte gazde decât www.emag.ro (sau spre www.emag.ro fără https)');
    assert.deepEqual(state.requests.filter((request) => request.method !== 'GET'), [], 'cereri spre eMAG care nu sunt GET (extensia doar citește)');
    assert.deepEqual(state.unknown, [], 'căi pe care eMAG-ul fals nu le știe');
    assert.deepEqual(state.handlerErrors, [], 'erori în eMAG-ul fals');
  }

  return {
    fake, context, worker, extensionId, appUrl, issues, cspViolations,
    openApp, screen, visibleScreens, storage, decodedStorage, lockRecord, heldLocks, tabs, workTabs, seedLastAnalysis, startRun, consumeIssues, consumeCspViolations, assertClean,
    close: () => closeSession(context, profileDir),
  };
}

/** Închide browserul (cu termen: un browser care nu se închide nu ține testul) și șterge profilul temporar. */
async function closeSession(context, profileDir) {
  let timer;
  try {
    await Promise.race([
      context.close(),
      new Promise((resolve) => { timer = setTimeout(resolve, CLOSE_TIMEOUT_MS); }),
    ]);
  } catch {
    // Browserul s-a închis deja sau a căzut: profilul se șterge oricum.
  } finally {
    clearTimeout(timer);
  }
  removeFolder(profileDir);
}

/**
 * Un scenariu = un browser și un eMAG fals proprii, pornite înainte de testele grupului și oprite după ele; testele din grup rulează în ordine și își împart sesiunea (`ctx.session`).
 * Ultimul test al fiecărui scenariu cere ca tot ce s-a întâmplat să fi fost curat (zero erori de consolă, zero încălcări CSP, nicio cerere spre alte gazde).
 * `fakeOptions` poate fi o funcție (se cheamă la pornire, deci o fixtură lipsă pică scenariul cu mesaj, nu încărcarea fișierului).
 */
export function scenario(name, fakeOptions, define) {
  describe(name, { timeout: SCENARIO_TIMEOUT_MS }, () => {
    const ctx = { session: null };
    before(async () => {
      ctx.session = await startSession(typeof fakeOptions === 'function' ? fakeOptions() : fakeOptions);
    }, { timeout: LAUNCH_TIMEOUT_MS * 2 });
    after(async () => {
      if (ctx.session) await ctx.session.close();
    }, { timeout: CLOSE_TIMEOUT_MS * 2 });
    define(ctx);
    test('zero erori de consolă, zero încălcări CSP, nicio cerere spre alte gazde, doar citiri (GET) spre eMAG', () => {
      ctx.session.assertClean();
    });
  });
}

/** Apasă pe butonul `selector` și întoarce fișierul descărcat: { name, bytes, text }; așteaptă ca butoanele de descărcare să fie din nou libere (aria-busy), ca următoarea descărcare să nu fie ignorată. */
export async function downloadFrom(page, selector) {
  const [download] = await Promise.all([page.waitForEvent('download'), page.click(selector)]);
  const bytes = readFileSync(await download.path());
  await page.waitForFunction(() => document.querySelector('button[data-file][aria-busy="true"]') === null);
  return { name: download.suggestedFilename(), bytes, text: bytes.toString('utf8') };
}
