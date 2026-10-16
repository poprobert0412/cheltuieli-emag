// Pornește pagina aplicației: leagă ecranele între ele și hotărăște pe care îl arată (portul lui app-main.js și al mașinii de stări din app-state.js, fără serverul local).
// Primește: nimic din afară; la deschidere întreabă lacătul (rulează o analiză în altă filă?) și stocarea (există o analiză salvată?). Dă înapoi: nimic; desenează ecranele.
// Ecranele: loading, busy, ready, login, working, done (raportul salvat sau demonstrativ), error, cancelled. Parserele, analiza și exporturile se încarcă abia la „Pornește analiza” sau la descărcare,
// deci pagina pornește repede, iar demo-ul nu le încarcă. Ce NU face: nu citește pagini eMAG (rulare/run_pipeline.js) și nu desenează nimic din conținutul ecranelor (fiecare fișier din ecrane/ își desenează ecranul lui).
import { PHASE_WAITING_LOGIN, Progress, RunCancelled } from '../colectare/progress.js';
import { CODE_BUSY, classifyError } from '../colectare/run_errors.js';
import { showTab } from '../colectare/work_tab.js';
import { downloadText } from '../exporturi/descarcare.js';
import { mimeTypeOf } from '../exporturi/export_files.js';
import { runPipeline } from '../rulare/run_pipeline.js';
import { deleteAllData, loadLastAnalysis } from '../stocare/last_analysis.js';
import { isRunActive, sweepStaleRecord } from '../stocare/run_lock.js';
import { RunLog, loadSavedRunLog } from '../stocare/run_log.js';
import { StorageEncryptionError } from '../stocare/storage_encryption.js';
import { initBusyScreen, startBusyWatch, stopBusyWatch } from './busy_screen.js';
import { initCancelledScreen, renderCancelled } from './cancelled_screen.js';
import { fillDynamicTexts } from './dynamic_texts.js';
import { initDownloadButtons } from './download_buttons.js';
import { initErrorScreen, renderError, setLogMessage } from './error_screen.js';
import { initFaqLinks } from './faq_links.js';
import { enterLogin, initLoginScreen, setShowTabEnabled } from './login_screen.js';
import { hideReport, initReportScreen, showDataDeletionOnError, showReport } from './report_screen.js';
import { currentScreen, initScreens, showScreen } from './screens.js';
import {
  initStartScreen, showDeletedNote, showLastAnalysis, showStartError,
} from './start_screen.js';
import { enterWorking, initWorkingScreen, renderWorking } from './working_screen.js';

const LOG_FILE_NAME = 'jurnal.txt';

// Ce știe pagina acum: fila ei, ultima analiză, analiza în curs (cu raportorul de progres și fila de lucru) și ce raport se arată.
const state = { appTabId: null, lastEntry: null, run: null, report: null };

/** Trece pe ecranul `name`: scoate raportul dacă îl părăsește și oprește reverificarea ecranului „busy”. */
function go(name) {
  if (currentScreen() === 'done' && name !== 'done') hideReport();
  if (currentScreen() === 'busy' && name !== 'busy') stopBusyWatch();
  if (name !== 'error') showDataDeletionOnError(false);
  showScreen(name);
}

/** Ecranul „busy”: o altă filă rulează o analiză; pagina reverifică singură. */
function showBusy() {
  go('busy');
  startBusyWatch();
}

/** Ecranul de start, cu rândul „Ultima analiză” dacă există una. */
function showReady() {
  showLastAnalysis(state.lastEntry);
  state.report = null;
  go('ready');
}

/** Raportul ultimei analize salvate. Ecranul se arată întâi, ca graficele să-și măsoare locul vizibil. */
function showSavedReport() {
  state.report = { kind: 'saved' };
  go('done');
  showReport({ kind: 'saved', summary: state.lastEntry.summary, createdAt: state.lastEntry.created_at });
}

/** Raportul demonstrativ (comenzi inventate, gata calculat în demo-data.js): nu citește nimic din cont și nu se salvează. */
function showDemoReport() {
  state.report = { kind: 'demo' };
  go('done');
  showReport({ kind: 'demo', summary: window.EMAG_DEMO_DATA, createdAt: null });
}

/** Ce raport se arată acum, în forma cerută de descărcări; null dacă nu e niciunul. */
function currentSource() {
  if (state.report?.kind === 'demo') return { kind: 'demo', summary: window.EMAG_DEMO_DATA };
  if (state.report?.kind === 'saved' && state.lastEntry) return { kind: 'saved', entry: state.lastEntry };
  return null;
}

/** Alegerea ecranului la deschidere: „busy” dacă o analiză rulează în altă filă, altfel raportul salvat sau ecranul de start. */
async function routeAtStart() {
  if (await isRunActive()) {
    showBusy();
    return;
  }
  await sweepStaleRecord(); // fila de lucru rămasă de la o filă moartă (pagina reîncărcată în timpul unei analize)
  state.lastEntry = await loadLastAnalysis();
  await loadSavedRunLog(); // validează/migrează și jurnalul singur; o cheie lipsă sau un jurnal corupt trebuie să ofere recuperarea prin ștergere
  if (state.lastEntry) showSavedReport();
  else showReady();
}

/** True dacă există un jurnal salvat de descărcat (rularea căzută sau oprită). */
async function hasSavedLog() {
  try {
    return (await loadSavedRunLog()) !== null;
  } catch {
    return false;
  }
}

/** Salvează jurnalul rulării căzute sau oprite ca jurnal.txt; mesajul de stare apare în secțiunea `sectionId`. */
async function downloadSavedLog(sectionId) {
  try {
    const text = await loadSavedRunLog();
    if (text === null) {
      setLogMessage(sectionId, 'Nu am găsit niciun jurnal salvat.', true);
      return;
    }
    downloadText(LOG_FILE_NAME, text, mimeTypeOf(LOG_FILE_NAME));
    setLogMessage(sectionId, `A pornit descărcarea fișierului ${LOG_FILE_NAME}. Îl găsești în folderul de descărcări al browserului.`, false);
  } catch (error) {
    setLogMessage(sectionId, `Nu am putut descărca ${LOG_FILE_NAME}: ${error && error.message ? error.message : 'eroare necunoscută'}.`, true);
  }
}

/** Ecranul potrivit unei rulări terminate cu eroare: „oprit” la RunCancelled, „busy” la lacăt ocupat, altfel ecranul de eroare cu mesajul din run_errors.js. */
async function showFailure(error) {
  if (error instanceof RunCancelled) {
    renderCancelled({ hasLog: await hasSavedLog() });
    go('cancelled');
    return;
  }
  if (error && error.code === CODE_BUSY) {
    showBusy();
    return;
  }
  const hasLog = await hasSavedLog();
  renderError({ message: classifyError(error).message, hasLog });
  go('error');
  showDataDeletionOnError(error instanceof StorageEncryptionError || hasLog);
}

/** Aduce fila aplicației în față (după login, omul e în fila eMAG; analiza continuă aici). Eșecul nu e grav: omul poate reveni singur. */
function bringAppTabBack() {
  if (document.visibilityState === 'hidden' && state.appTabId !== null) showTab(state.appTabId).catch(() => {});
}

/** Reacție la schimbările de progres: login-ul are ecranul lui, restul se desenează pe ecranul „în lucru”. */
function onProgress(snapshot) {
  if (state.run === null) return;
  if (snapshot.phase === PHASE_WAITING_LOGIN) {
    if (currentScreen() !== 'login') {
      enterLogin(state.run.workTabId !== null);
      go('login');
    }
    return;
  }
  if (currentScreen() === 'login') {
    bringAppTabBack();
    go('working');
  }
  renderWorking(snapshot);
}

/** Pornește analiza contului cu pragul dat (în lei) și arată ce iese: raportul, „oprit”, „busy” sau eroarea. */
async function startAnalysis(thresholdLei) {
  if (state.run !== null) return;
  showStartError('');
  const progress = new Progress({ onChange: onProgress });
  state.run = { progress, workTabId: null };
  enterWorking();
  renderWorking(progress.snapshot());
  go('working');
  try {
    const entry = await runPipeline({
      thresholdLei,
      appTabId: state.appTabId,
      progress,
      log: new RunLog(),
      onWorkTab: (workTabId) => {
        if (state.run !== null) state.run.workTabId = workTabId;
        setShowTabEnabled(true);
      },
    });
    state.lastEntry = entry;
    progress.finish();
    state.run = null;
    showSavedReport();
  } catch (error) {
    progress.finish();
    state.run = null;
    await showFailure(error);
  }
}

/** „Oprește”: cere oprirea; analiza se termină cu RunCancelled la următorul punct sigur (cel mult câteva secunde). */
function cancelRun() {
  if (state.run !== null) state.run.progress.cancel();
}

/** „Deschide fila eMAG” de pe ecranul de login. */
function showWorkTab() {
  if (state.run !== null && state.run.workTabId !== null) showTab(state.run.workTabId).catch(() => {});
}

/** „Da, șterge datele”: golește stocarea extensiei și întoarce omul pe ecranul de start; la eșec datele rămân, iar confirmarea rămâne deschisă cu mesajul „ce s-a întâmplat + Ce faci”. */
async function deleteData() {
  const message = window.App.dom.byId('delete-msg');
  try {
    await deleteAllData();
  } catch (error) {
    message.className = 'field__hint session__note is-bad';
    message.textContent = `Nu am putut șterge datele (${error && error.message ? error.message : 'eroare necunoscută'}). `
      + 'Ce faci: încearcă din nou; dacă se repetă, reîncarcă pagina extensiei și apasă din nou «Șterge datele».';
    return;
  }
  state.lastEntry = null;
  showReady();
  const done = 'Datele salvate au fost șterse din acest browser.';
  showDeletedNote(done);
  window.App.dom.announce(done);
}

/** Pune versiunea extensiei (din manifest) sub titlu. */
function showVersion() {
  const version = window.App.dom.byId('app-version');
  version.textContent = `versiunea ${chrome.runtime.getManifest().version}`;
  version.hidden = false;
}

/** Leagă modulele și alege ecranul de început; o eroare la pornire (stocare, lacăt) se arată ca ecran de eroare, nu ca pagină goală. */
async function boot() {
  initScreens();
  fillDynamicTexts();
  initFaqLinks();
  window.App.threshold.init();
  showVersion();
  initStartScreen({
    onStart: (thresholdLei) => startAnalysis(thresholdLei),
    onDemo: () => showDemoReport(),
    onOpenLast: () => { if (state.lastEntry) showSavedReport(); },
  });
  initLoginScreen({ onShowTab: showWorkTab, onCancel: cancelRun });
  initWorkingScreen({ onCancel: cancelRun });
  initReportScreen({
    onNewAnalysis: () => { showDeletedNote(''); showReady(); },
    onDeleteData: () => deleteData(),
  });
  initDownloadButtons({ getSource: currentSource });
  initErrorScreen({ onBack: () => { showDeletedNote(''); showReady(); }, onDownloadLog: () => downloadSavedLog('screen-error') });
  initCancelledScreen({ onBack: () => { showDeletedNote(''); showReady(); }, onDownloadLog: () => downloadSavedLog('screen-cancelled') });
  initBusyScreen({ isStillBusy: isRunActive, onFree: () => routeAtStart().catch((error) => showFailure(error)) });
  const tab = await chrome.tabs.getCurrent();
  state.appTabId = tab ? tab.id : null;
  try {
    await routeAtStart();
  } catch (error) {
    await showFailure(error);
  }
}

boot().catch((error) => {
  // Nu ar trebui să se ajungă aici (routeAtStart își prinde erorile); dacă totuși, se vede în consolă, nu se pierde.
  console.error(`${chrome.runtime.getManifest().name}: pornirea paginii a eșuat`, error);
});
