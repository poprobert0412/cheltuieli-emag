// cont_real.mjs — rulează extensia pe contul eMAG REAL al lui Robert, cu sesiunea salvată de program (.profil_browser),
// dintr-o copie temporară a profilului, ștearsă la final oricum s-ar termina rularea.
// Primește: modul, ca singur argument. `acceptanta`: extensia din dist/ face analiza întreagă, fișierele ei se descarcă în
// iesiri/acceptanta/extensie-<data>_<ora>/ și se compară cu ultima rulare a programului din iesiri/acceptanta/ (tests/compara_extensie.py).
// `proba` a rulat o singură dată, pe 14.10.2026 (rezultatul e în §11 al specificației); extensia de probă a fost ștearsă.
// Dă înapoi: pe ieșirea standard doar numărători, durate și căile cheilor care diferă; codul 0 doar dacă totul e identic.
// Rulează DOAR cu permisiunea lui Robert (decis 14.10.2026): setările lui permit exact `node extensie/scripts/cont_real.mjs proba`
// și `node extensie/scripts/cont_real.mjs acceptanta`. Nu rulează în CI. Îl scrie și îl schimbă doar Opus.
// Ce NU face: nu citește cookie-uri, nu tastează în pagini, nu trimite nimic în afara calculatorului, nu atinge profilul original.
import { chromium } from 'playwright-core';
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
// Același profil ca programul: EMAG_PROFILE_DIR, altfel <proiect>/.profil_browser (emag_spend/settings.py).
const PROFILE_SOURCE = process.env.EMAG_PROFILE_DIR || path.join(PROJECT_ROOT, '.profil_browser');
const EXTENSION_DIST = path.join(PROJECT_ROOT, 'extensie', 'dist');
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
// Ecranele la care rularea automată se oprește: raportul, eroarea, oprirea și login-ul (sesiunea programului a expirat).
const FINAL_SCREENS = new Set(['done', 'error', 'cancelled', 'login']);

/** Copia profilului, fără memoriile cache și fără lacăte, într-un folder temporar nou; întoarce folderul părinte (de șters). */
function copyProfile() {
  if (!existsSync(PROFILE_SOURCE)) throw new Error(`lipsește profilul programului: ${PROFILE_SOURCE}`);
  const parent = mkdtempSync(path.join(tmpdir(), 'cheltuieli-emag-cont-real-'));
  cpSync(PROFILE_SOURCE, path.join(parent, 'profil'), {
    recursive: true,
    filter: (source) => !SKIPPED_FOLDERS.has(path.basename(source)) && !LOCK_FILE.test(path.basename(source)),
  });
  return parent;
}

/** Cea mai nouă rulare a programului din iesiri/acceptanta (foldere <data>_<ora>, sortabile după nume), sau null. */
function newestProgramRun() {
  if (!existsSync(ACCEPTANCE_ROOT)) return null;
  const runs = readdirSync(ACCEPTANCE_ROOT)
    .filter((name) => !name.startsWith(EXTENSION_FOLDER_PREFIX) && statSync(path.join(ACCEPTANCE_ROOT, name)).isDirectory())
    .filter((name) => existsSync(path.join(ACCEPTANCE_ROOT, name, 'comenzi.json')))
    .sort();
  return runs.length ? path.join(ACCEPTANCE_ROOT, runs[runs.length - 1]) : null;
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
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: WORKER_TIMEOUT_MS });
  return { context, extensionId: worker.url().split('/')[2] };
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

/** Modul `acceptanta`: analiza întreagă în extensie, fișierele descărcate, apoi comparația cu programul. Întoarce codul de ieșire. */
async function runAcceptance(profileDir) {
  if (!existsSync(path.join(EXTENSION_DIST, 'manifest.json'))) throw new Error('lipsește extensie/dist: rulează întâi „npm run build:strict” în extensie/');
  const programRun = newestProgramRun();
  if (!programRun) throw new Error('lipsește rularea programului: rulează întâi „.venv/Scripts/python.exe ruleaza.py --iesire iesiri/acceptanta”');
  const outFolder = path.join(ACCEPTANCE_ROOT, `${EXTENSION_FOLDER_PREFIX}${stamp()}`);
  const { context, extensionId } = await launchWithExtension(profileDir, EXTENSION_DIST);
  let screen;
  const started = Date.now();
  try {
    const page = await context.newPage();
    await page.goto(`chrome-extension://${extensionId}/aplicatie.html`);
    await page.waitForFunction(() => document.querySelector('section.screen:not([hidden])')?.dataset.screen === 'ready', null, { timeout: READY_TIMEOUT_MS });
    await page.click('#btn-start');
    while (!FINAL_SCREENS.has(screen = await visibleScreen(page))) {
      if (Date.now() - started > ANALYSIS_TIMEOUT_MS) throw new Error(`analiza nu s-a terminat în ${ANALYSIS_TIMEOUT_MS / 60000} minute (ecranul: ${screen})`);
      await page.waitForTimeout(SCREEN_POLL_MS);
    }
    console.log(`extensia: ecranul final „${screen}” după ${Math.round((Date.now() - started) / 1000)} s`);
    mkdirSync(outFolder, { recursive: true });
    if (screen === 'login') {
      console.log('sesiunea salvată de program a expirat: e nevoie de un login în program (login.bat), apoi de o rulare nouă');
      await page.click('#btn-login-cancel');
      return 1;
    }
    if (screen !== 'done') {
      console.log(`mesajul extensiei: ${await page.textContent('#error-message').catch(() => '(fără mesaj)')}`);
      const logButton = `#screen-${screen} [data-action="download-log"]`;
      if (await page.isVisible(logButton)) console.log(`jurnalul: ${await download(page, logButton, outFolder, 'jurnal.txt')}`);
      return 1;
    }
    for (const name of DOWNLOADED_FILES) await download(page, `[data-file="${name}"]`, outFolder, name);
    console.log(`fișierele extensiei: ${outFolder}`);
  } finally {
    await context.close();
  }
  console.log(`rularea programului comparată: ${programRun}`);
  const comparison = spawnSync(PYTHON, [path.join('tests', 'compara_extensie.py'), programRun, outFolder], {
    cwd: PROJECT_ROOT,
    stdio: 'inherit',
    env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' },
  });
  if (comparison.error) throw comparison.error;
  return comparison.status ?? 1;
}

async function main() {
  const mode = process.argv[2];
  if (mode === 'proba') throw new Error('proba s-a făcut pe 14.10.2026 (rezultatul e în §11 al specificației), iar extensia de probă a fost ștearsă');
  if (mode !== 'acceptanta') throw new Error(`mod necunoscut: ${mode} (singurul mod: acceptanta)`);
  const parent = copyProfile();
  try {
    process.exitCode = await runAcceptance(path.join(parent, 'profil'));
  } finally {
    rmSync(parent, { recursive: true, force: true });
    console.log('copia profilului a fost ștearsă');
  }
}

main().catch((error) => {
  console.error(`eroare: ${error && error.message ? error.message : error}`);
  process.exitCode = 1;
});
