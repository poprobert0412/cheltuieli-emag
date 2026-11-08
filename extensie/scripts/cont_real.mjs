// cont_real.mjs — rulează extensia pe contul eMAG REAL al lui Robert, cu sesiunea salvată de program (.profil_browser),
// dintr-o copie temporară a profilului, ștearsă la final oricum s-ar termina rularea.
// Primește: modul `acceptanta`; EXT_DIST_DIR alege build-ul (implicit extensie/dist), EMAG_PROFILE_DIR profilul dedicat,
// EMAG_ACCEPTANCE_PRODUCT_URL pagina produsului pentru panou (fără implicit). Rezultatele reale rămân în iesiri/acceptanta/.
// Extensia colectează tot, probează cele șase funcții, apoi Python colectează din nou în aceeași copie și compară rezultatele.
// `proba` a rulat o singură dată, pe 14.10.2026 (rezultatul e în §11 al specificației); extensia de probă a fost ștearsă.
// Dă înapoi: doar verdicte, numărători și durate; codul 0 cere toate probele trecute. Jurnalele detaliate sunt private.
// E25: Robert a cerut pe 08.11.2026 testarea pe cont înainte de commit/push; coordonatorul întreține acest runner local, fără CI.
// Nu citește cookie-uri sau credențiale, nu completează formulare eMAG; editează doar preferințe de probă în copia extensiei.
import { chromium } from 'playwright-core';
import { appendFileSync, cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyShoppingAcceptance } from './shopping_acceptance.mjs';
import { runAcceptanceProcess } from './acceptance_process.mjs';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
// Același profil ca programul: EMAG_PROFILE_DIR, altfel <proiect>/.profil_browser (emag_spend/settings.py).
const PROFILE_SOURCE = process.env.EMAG_PROFILE_DIR || path.join(PROJECT_ROOT, '.profil_browser');
const EXTENSION_DIST = path.resolve(process.env.EXT_DIST_DIR || path.join(PROJECT_ROOT, 'extensie', 'dist'));
// Același folder ca rularea programului din regula lui Robert (`ruleaza.py --iesire iesiri/acceptanta`); iesiri/ e ignorat de git.
const ACCEPTANCE_ROOT = path.join(PROJECT_ROOT, 'iesiri', 'acceptanta');
const EXTENSION_FOLDER_PREFIX = 'extensie-';
// Fișierele descărcate din ecranul „Raportul tău”; primele trei intră în comparație, restul rămân pentru citit de mână.
const DOWNLOADED_FILES = ['comenzi.json', 'retururi.json', 'analiza.json', 'produse.csv', 'istoric_preturi.csv', 'raport.html', 'jurnal.txt'];
const PYTHON = process.platform === 'win32' ? path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe') : path.join(PROJECT_ROOT, '.venv', 'bin', 'python');
// Memoriile cache nu se copiază: n-au sesiunea, doar ocupă loc. Fișierele-lacăt nu se copiază: copia nu e „în uz”.
const SKIPPED_FOLDERS = new Set(['Cache', 'Code Cache', 'GPUCache', 'GrShaderCache', 'ShaderCache', 'GPUPersistentCache',
  'Crashpad', 'BrowserMetrics']);
const LOCK_FILE = /^(Singleton.*|lockfile)$/i;
// Pe contul lui Robert programul citește totul în 2½–3 minute; 15 minute acoperă un cont mult mai mare sau un eMAG lent.
const ANALYSIS_TIMEOUT_MS = 15 * 60 * 1000;
const WORKER_TIMEOUT_MS = 20000;
const READY_TIMEOUT_MS = 30000;
const SCREEN_POLL_MS = 1000;
// Ecranele finale; login-ul rămâne deschis pentru autentificare manuală până la termenul aplicației.
const FINAL_SCREENS = new Set(['done', 'error', 'cancelled']);
const PROFILE_PREFIX = 'cheltuieli-emag-cont-real-';
let pipelineLog;

/** Scrie fiecare pas imediat; mesajele sunt numai verdicte și numărători, fără date din cont. */
function log(message) {
  const line = `${new Date().toISOString()} [acceptance] INFO: ${message}`;
  if (pipelineLog) appendFileSync(pipelineLog, `${line}\n`, 'utf8');
  console.log(message);
}

/** Șterge numai folderul temporar creat de acest runner, după verificarea căii absolute și a legăturilor. */
function removeProfile(parent) {
  const target = path.resolve(parent);
  const temp = realpathSync(tmpdir());
  if (lstatSync(target).isSymbolicLink() || path.dirname(realpathSync(target)) !== temp || !path.basename(target).startsWith(PROFILE_PREFIX)) {
    throw new Error('temporary_profile_path_rejected');
  }
  rmSync(target, { recursive: true, force: true });
}

/** Copia profilului, fără memoriile cache și fără lacăte, într-un folder temporar nou; întoarce folderul părinte (de șters). */
function copyProfile() {
  if (!existsSync(PROFILE_SOURCE)) throw new Error(`lipsește profilul programului: ${PROFILE_SOURCE}`);
  const parent = mkdtempSync(path.join(tmpdir(), PROFILE_PREFIX));
  try {
    cpSync(PROFILE_SOURCE, path.join(parent, 'profil'), {
      recursive: true,
      filter: (source) => !SKIPPED_FOLDERS.has(path.basename(source)) && !LOCK_FILE.test(path.basename(source)),
    });
  } catch (error) { removeProfile(parent); throw error; }
  return parent;
}

/** Singura colectare Python din folderul nou al acceptanței; o rulare veche nu poate fi aleasă accidental. */
function freshProgramRun(folder) {
  const runs = readdirSync(folder)
    .map((name) => path.join(folder, name))
    .filter((candidate) => statSync(candidate).isDirectory() && existsSync(path.join(candidate, 'comenzi.json')));
  if (runs.length !== 1) throw new Error('fresh_reference_run_missing_or_ambiguous');
  return runs[0];
}

/** Subproces cu ieșirea completă pe disc, nu în chat; timeout-ul blochează acceptanța. */
function pythonCheck(args, target, profileDir) {
  return runAcceptanceProcess({ executable: PYTHON, args, cwd: PROJECT_ROOT, logPath: target, timeoutMs: ANALYSIS_TIMEOUT_MS,
    env: { ...process.env, EMAG_PROFILE_DIR: profileDir, EMAG_BROWSER_CHANNEL: 'msedge', PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' } });
}

/** Ora locală ca „AAAA-LL-ZZ_HH-MM-SS”, ca numele rulărilor programului. */
function stamp(date = new Date()) {
  const two = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}_${two(date.getHours())}-${two(date.getMinutes())}-${two(date.getSeconds())}`;
}

/** Edge vizibil (ca programul: fără „Headless” în agentul browserului), cu extensia dată încărcată din folder. */
async function launchWithExtension(profileDir, extensionDir) {
  const context = await chromium.launchPersistentContext(profileDir, {
    channel: 'msedge',
    headless: false,
    viewport: null,
    acceptDownloads: true,
    args: [`--disable-extensions-except=${extensionDir}`, `--load-extension=${extensionDir}`],
  });
  try {
    let [worker] = context.serviceWorkers();
    if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: WORKER_TIMEOUT_MS });
    return { context, extensionId: worker.url().split('/')[2] };
  } catch (error) { await context.close(); throw error; }
}

/** Ecranul vizibil acum în aplicația extensiei (data-screen), sau null. */
function visibleScreen(page) {
  return page.evaluate(() => document.querySelector('section.screen:not([hidden])')?.dataset.screen ?? null);
}

/** Apasă butonul de descărcare și salvează fișierul în `folder`; întoarce calea. */
async function download(page, selector, folder, name) {
  const [file] = await Promise.all([page.waitForEvent('download'), page.click(selector)]);
  const target = path.join(folder, name);
  await file.saveAs(target);
  return target;
}

/** Colectare nouă în ambele motoare și cele șase funcții; întoarce 0 numai dacă toate trec. */
async function runAcceptance(profileDir, outFolder) {
  if (!existsSync(path.join(EXTENSION_DIST, 'manifest.json'))) throw new Error('extension_build_missing');
  const { context, extensionId } = await launchWithExtension(profileDir, EXTENSION_DIST);
  let screen; let loginAnnounced = false; let features;
  const started = Date.now();
  try {
    const page = await context.newPage();
    await page.goto(`chrome-extension://${extensionId}/aplicatie.html`);
    await page.waitForFunction(() => document.querySelector('section.screen:not([hidden])')?.dataset.screen === 'ready', null, { timeout: READY_TIMEOUT_MS });
    await page.click('#btn-start');
    while (!FINAL_SCREENS.has(screen = await visibleScreen(page))) {
      if (screen === 'login' && !loginAnnounced) {
        log('LOGIN_REQUIRED: autentifică-te manual în fila eMAG din fereastra Edge de probă; analiza continuă automat.');
        await page.click('#btn-show-tab'); loginAnnounced = true;
      }
      if (Date.now() - started > ANALYSIS_TIMEOUT_MS) throw new Error(`analiza nu s-a terminat în ${ANALYSIS_TIMEOUT_MS / 60000} minute (ecranul: ${screen})`);
      await page.waitForTimeout(SCREEN_POLL_MS);
    }
    log(`extensia: ecranul final „${screen}” după ${Math.round((Date.now() - started) / 1000)} s`);
    if (screen !== 'done') {
      const logButton = `#screen-${screen} [data-action="download-log"]`;
      if (await page.isVisible(logButton)) await download(page, logButton, outFolder, 'jurnal.txt');
      return 1;
    }
    for (const name of DOWNLOADED_FILES) await download(page, `[data-file="${name}"]`, outFolder, name);
    const entry = await page.evaluate(async () => (await import('./stocare/last_analysis.js')).loadLastAnalysis());
    log(`colectare extensie: ${entry.orders.length} comenzi, ${entry.returns.length} retururi`);
    features = await verifyShoppingAcceptance({ context, page, extensionId, outFolder, entry, productUrl: process.env.EMAG_ACCEPTANCE_PRODUCT_URL });
    for (const [name, value] of Object.entries(features)) log(`${name}: ${value.status}`);
  } finally {
    await context.close();
  }
  const referenceRoot = path.join(outFolder, 'referinta-python'); mkdirSync(referenceRoot);
  log('referința Python: începe o colectare nouă în copia profilului');
  const collected = await pythonCheck(['ruleaza.py', '--iesire', referenceRoot], path.join(outFolder, '_meta', 'program.log'), profileDir);
  log(`colectare Python: ${collected ? 'passed' : 'failed'}`);
  const compared = collected && await pythonCheck([path.join('tests', 'compara_extensie.py'), freshProgramRun(referenceRoot), outFolder], path.join(outFolder, '_meta', 'comparatie.log'), profileDir);
  log(`paritate cont real: ${compared ? 'passed' : 'failed'}`);
  const passed = compared && Object.keys(features).length >= 6 && Object.values(features).every((value) => value.status === 'passed');
  writeFileSync(path.join(outFolder, '_meta', 'rezultat.json'), `${JSON.stringify({ passed, collection: collected, parity: compared, features }, null, 2)}\n`, 'utf8');
  return passed ? 0 : 1;
}

async function main() {
  const mode = process.argv[2];
  if (mode === 'proba') throw new Error('proba s-a făcut pe 14.10.2026 (rezultatul e în §11 al specificației), iar extensia de probă a fost ștearsă');
  if (mode !== 'acceptanta') throw new Error(`mod necunoscut: ${mode} (singurul mod: acceptanta)`);
  const outFolder = path.join(ACCEPTANCE_ROOT, `${EXTENSION_FOLDER_PREFIX}${stamp()}`);
  mkdirSync(path.join(outFolder, '_meta'), { recursive: true });
  pipelineLog = path.join(outFolder, '_meta', 'pipeline.log');
  log(`acceptanța: ${outFolder}`);
  const parent = copyProfile();
  try {
    process.exitCode = await runAcceptance(path.join(parent, 'profil'), outFolder);
  } finally {
    removeProfile(parent);
    log('copia profilului a fost ștearsă');
  }
}

main().catch((error) => {
  if (pipelineLog) appendFileSync(pipelineLog, `${new Date().toISOString()} [acceptance] ERROR: ${error?.stack ?? String(error)}\n`, 'utf8');
  const code = /^[a-z_]+(?::[a-z_]+)*$/.test(error?.message ?? '') ? error.message : 'acceptance_operation_failed';
  log(`eroare: ${code}`);
  process.exitCode = 1;
});
