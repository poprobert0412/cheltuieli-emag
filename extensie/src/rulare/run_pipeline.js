// Rulează o analiză din cap în coadă: lacăt -> verificarea regulilor -> colectare -> analiză -> salvare (portul lui emag_spend/run_pipeline.py pentru extensie).
// Primește: pragul pentru „achiziție mare” (în lei), id-ul filei aplicației, raportorul de progres, jurnalul și apeluri pentru ecrane (`onNeedLogin`, `onWorkTab`). Dă înapoi: intrarea salvată ca ultimă analiză (E4).
// Regulile de categorii, textele, culorile și modurile de restituire se verifică ÎNAINTE de colectare: o greșeală oprește rularea în secunde, nu după minute. O analiză nouă o înlocuiește pe cea veche
// abia când s-a terminat cu bine; la orice eroare, oprire sau cotă plină ultima analiză rămâne întreagă, iar jurnalul rulării rămâne salvat separat (CLAUDE.md §9). Lacătul se eliberează oricum se termină.
// Rezumatul din intrare (cel salvat ȘI cel desenat chiar după rulare) e copia cu numere simple, `analysis.plainSummary`: analiza dă procentele ca PyFloat, pe care chrome.storage nu le păstrează ca numere,
// iar dashboard.js le refuză. Jurnalul rulării merge și în analiză, ca rândurile ei să ajungă în jurnal.txt.
// Ce NU face: nu desenează nimic (ecranele), nu rulează demo-ul (nu citește nimic din cont) și nu descarcă fișiere.
import { pyRoundInt } from '../calcul/python_compat.js';
import { collectAll } from '../colectare/emag_collector.js';
import { PHASE_ANALYZING, RunCancelled } from '../colectare/progress.js';
import { classifyError } from '../colectare/run_errors.js';
import { ENTRY_SCHEMA, saveLastAnalysis } from '../stocare/last_analysis.js';
import { acquireRunLock, registerWorkTab, releaseRunLock } from '../stocare/run_lock.js';
import { clearSavedRunLog } from '../stocare/run_log.js';
import { loadAnalysis } from './analysis_loader.js';

const MODULE = 'run_pipeline';

// Dependențele reale; testele dau altele. Se caută abia la folosire (chrome.* nu se atinge la import).
const REAL_DEPS = Object.freeze({
  acquireRunLock, releaseRunLock, registerWorkTab, loadAnalysis, collectAll, saveLastAnalysis, clearSavedRunLog,
});

/** Două cifre cu zerouri în față. */
function pad(number) {
  return String(number).padStart(2, '0');
}

/** Data și ora locală ca text, fără fus: „2026-10-14 09:30:45” (cu secunde) sau „2026-10-14 09:30”; aceeași formă ca în run_info.json din programul Python. */
function formatLocal(date, withSeconds) {
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}${withSeconds ? `:${pad(date.getSeconds())}` : ''}`;
}

/** Primul rând al mesajului unei erori, pentru jurnal. */
function firstLine(error) {
  return String(error?.message ?? error).trim().split(/\r?\n/)[0] || String(error?.name ?? 'eroare');
}

/** Rulează `action` și înghite eroarea ei, cu un rând în jurnal: curățenia de la final nu are voie să acopere rezultatul sau eroarea rulării. */
async function quietly(action, log, what) {
  try {
    await action();
  } catch (error) {
    log.warning(MODULE, `${what}: ${firstLine(error)}`);
  }
}

/**
 * Rulează analiza contului și întoarce intrarea salvată. `thresholdLei` e pragul în lei; `appTabId` fila aplicației (lacătul și fila de lucru vecină);
 * `extensionVersion` și `clock` se pot da în teste. Aruncă RunBusy dacă rulează deja o analiză, RunCancelled la oprire, StorageFull dacă nu încape și orice altă eroare a colectării sau a analizei.
 */
export async function runPipeline({
  thresholdLei, appTabId, progress, log, onNeedLogin = () => {}, onWorkTab = () => {}, maxOrders = null,
  extensionVersion = chrome.runtime.getManifest().version, clock = () => new Date(), deps = {},
}) {
  const d = { ...REAL_DEPS, ...deps };
  await d.acquireRunLock(appTabId);
  try {
    log.info(MODULE, `pornesc rularea (prag ${thresholdLei} lei, versiunea ${extensionVersion})`);
    const thresholdBani = pyRoundInt(thresholdLei * 100);
    const analysis = await d.loadAnalysis();
    await log.flush();

    const { orders, returns } = await d.collectAll({
      maxOrders,
      progress,
      log,
      onNeedLogin,
      openerTabId: appTabId,
      onWorkTab: (workTabId) => {
        quietly(() => d.registerWorkTab(appTabId, workTabId), log, 'fila de lucru nu a putut fi trecută în evidență');
        onWorkTab(workTabId);
      },
    });
    await log.flush();

    progress.phase(PHASE_ANALYZING);
    const finished = clock();
    const { summary: analysed } = analysis.analyze(orders, returns, thresholdBani, formatLocal(finished, false), log);
    const summary = analysis.plainSummary(analysed);
    log.info(MODULE, `analiză gata: ${orders.length} comenzi și ${returns.length} retururi`);
    const entry = {
      schema: ENTRY_SCHEMA,
      extension_version: extensionVersion,
      created_at: formatLocal(finished, true),
      threshold_lei: thresholdLei,
      summary,
      orders,
      returns,
      log_text: log.text(),
    };
    await d.saveLastAnalysis(entry);
    await log.discard(); // jurnalul rulării a intrat în ultima analiză: copia de lucru nu mai trebuie scrisă (nici de cronometrul de scriere, nici de flush-ul din finally) ...
    await d.clearSavedRunLog(); // ... și se șterge
    return entry;
  } catch (error) {
    if (error instanceof RunCancelled) log.info(MODULE, 'rularea a fost oprită la cererea ta');
    else log.error(MODULE, `rularea a eșuat (${classifyError(error).code}): ${firstLine(error)}`);
    throw error;
  } finally {
    await quietly(() => log.flush(), log, 'jurnalul nu s-a putut scrie');
    await quietly(() => d.releaseRunLock(appTabId), log, 'lacătul nu s-a putut elibera');
  }
}
