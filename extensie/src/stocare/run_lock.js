// Lacătul „o singură analiză odată”: a doua filă a extensiei află că rulează deja una și nu pornește alta.
// Primește: id-ul filei aplicației (la luarea lacătului) și id-ul filei de lucru (după ce există). Dă înapoi: lacătul luat sau RunBusy; plus întrebarea „rulează o analiză în altă filă?”.
// Două straturi: (1) un Web Lock (navigator.locks, ifAvailable) — atomic între filele extensiei și eliberat singur de browser când fila care îl ține se închide, se mută sau cade, deci nu poate rămâne „vechi”;
// (2) o evidență în chrome.storage.session { appTabId, workTabId, startedAt } — ca worker-ul din fundal să știe ce filă de lucru să închidă când fila aplicației dispare (handleTabClosed).
// Dacă Web Lock-ul e liber dar evidența există, evidența e rămasă de la o filă moartă: fila de lucru rămasă orfană se închide și evidența se înlocuiește.
// Ce NU face: nu pornește și nu oprește analiza și nu deschide file (închide doar fila de lucru orfană). Modulul se importă și în worker, deci nu atinge chrome.* la import.
import { CODE_BUSY } from '../colectare/run_errors.js';

const DEFAULT_LOCK_NAME = 'cheltuieli-emag-analiza';
const RUN_LOCK_KEY = 'lacat_analiza';

/** Rulează deja o analiză într-o altă filă a extensiei (sau în aceeași); tip propriu, ca ecranul „busy” să-l recunoască. */
export class RunBusy extends Error {
  /** Mesajul implicit merge în jurnal; omul vede mesajul din run_errors.js sau ecranul „busy”. */
  constructor(message = 'rulează deja o analiză') {
    super(message);
    this.name = 'RunBusy';
    this.code = CODE_BUSY;
  }
}

/**
 * Construiește lacătul. Parametrii sunt pentru teste (nume propriu, spațiu fals, Web Locks false, închidere falsă de filă); în extensie rămân implicitele,
 * căutate abia la folosire, ca modulul să se poată importa și fără chrome.*.
 */
export function createRunLock({ lockName = DEFAULT_LOCK_NAME, session = null, locks = null, removeTab = null } = {}) {
  const sessionArea = () => session ?? chrome.storage.session;
  const lockManager = () => locks ?? globalThis.navigator.locks;
  const closeOrphan = removeTab ?? (async (tabId) => {
    try {
      await chrome.tabs.remove(tabId);
    } catch {
      // Fila nu mai există: scopul (să nu rămână o filă de lucru orfană) e atins.
    }
  });
  let held = null; // { appTabId, release } cât această pagină ține lacătul

  /** Evidența curentă din chrome.storage.session sau null. */
  async function readRecord() {
    const stored = await sessionArea().get(RUN_LOCK_KEY);
    return stored?.[RUN_LOCK_KEY] ?? null;
  }

  /** Ia Web Lock-ul dacă e liber (altfel RunBusy); întoarce funcția care îl eliberează. Lacătul rămâne ținut cât promisiunea din callback nu e îndeplinită. */
  function takeWebLock() {
    return new Promise((resolve, reject) => {
      lockManager().request(lockName, { ifAvailable: true }, (lock) => {
        if (lock === null) {
          reject(new RunBusy());
          return undefined;
        }
        return new Promise((releaseLock) => resolve(() => releaseLock()));
      }).catch(reject);
    });
  }

  /** Închide fila de lucru din evidență (dacă are) și șterge evidența; întoarce true dacă exista una. Se cheamă doar când se știe că stăpânul ei nu mai există. */
  async function clearRecord() {
    const record = await readRecord();
    if (!record) return false;
    if (record.workTabId !== null && record.workTabId !== undefined) await closeOrphan(record.workTabId);
    await sessionArea().remove(RUN_LOCK_KEY);
    return true;
  }

  /** Ia lacătul pentru fila aplicației `appTabId`; RunBusy dacă o analiză rulează deja. */
  async function acquireRunLock(appTabId) {
    const release = await takeWebLock();
    held = { appTabId, release };
    try {
      await clearRecord(); // lacătul era liber, deci evidența veche e de la o filă moartă
      await sessionArea().set({ [RUN_LOCK_KEY]: { appTabId, workTabId: null, startedAt: new Date().toISOString() } });
    } catch (error) {
      held = null;
      release();
      throw error;
    }
  }

  /** Eliberează lacătul dacă îl ține `appTabId` și șterge evidența lui; pentru altă filă nu face nimic. */
  async function releaseRunLock(appTabId) {
    if (held === null || held.appTabId !== appTabId) return;
    const { release } = held;
    held = null;
    try {
      const record = await readRecord();
      if (record && record.appTabId === appTabId) await sessionArea().remove(RUN_LOCK_KEY);
    } finally {
      release();
    }
  }

  /** Trece fila de lucru în evidență, doar pentru fila care ține lacătul (worker-ul o închide dacă fila aplicației dispare). */
  async function registerWorkTab(appTabId, workTabId) {
    const record = await readRecord();
    if (!record || record.appTabId !== appTabId) return;
    await sessionArea().set({ [RUN_LOCK_KEY]: { ...record, workTabId } });
  }

  /** True dacă o analiză rulează acum (lacătul e ținut de o filă a extensiei). */
  async function isRunActive() {
    const { held: heldLocks } = await lockManager().query();
    return heldLocks.some((entry) => entry.name === lockName);
  }

  /**
   * La deschiderea paginii aplicației: dacă lacătul e liber dar evidența există, fila aplicației care ținea analiza a dispărut fără să curețe (reîncărcată, mutată, căzută):
   * închide fila de lucru rămasă orfană și șterge evidența. Întoarce true dacă a curățat ceva.
   */
  async function sweepStaleRecord() {
    if (await isRunActive()) return false;
    return clearRecord();
  }

  /**
   * Apelat de worker când se închide o filă: dacă era fila aplicației care rula analiza, închide fila de lucru și șterge evidența. Întoarce true dacă a curățat ceva.
   * Capcană: lacătul Web Lock se eliberează singur, odată cu pagina; aici se curăță doar ce rămâne în urma ei.
   */
  async function handleTabClosed(tabId) {
    const record = await readRecord();
    if (!record || record.appTabId !== tabId) return false;
    return clearRecord();
  }

  return { RUN_LOCK_KEY, acquireRunLock, releaseRunLock, registerWorkTab, isRunActive, sweepStaleRecord, handleTabClosed };
}

// Lacătul real al extensiei: folosit de pagina aplicației și de worker.
export const {
  acquireRunLock, releaseRunLock, registerWorkTab, isRunActive, sweepStaleRecord, handleTabClosed,
} = createRunLock();
