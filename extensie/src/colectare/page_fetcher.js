// Cere pagini eMAG (detalii comenzi, detalii retururi) din fila de lucru, cu sesiunea omului (portul lui emag_spend/page_fetcher.py, E5).
// Primește: id-ul filei, o listă de căi, o funcție care transformă (cale, html) într-un rezultat, o etichetă pentru jurnal, raportorul de progres și jurnalul. Dă înapoi: rezultatele, în ordinea căilor.
// Cere puține pagini simultan (settings.FETCH_CONCURRENCY), reîncearcă cu pauză la erori de rețea și oprește rularea dacă sesiunea a expirat (redirecționare la login).
// HTML-ul nu se păstrează: se parsează pe loc (de `handler`) și se aruncă, ca să nu rămână în memorie și ca datele personale din pagină să nu ajungă în stocare.
// Oprirea cerută de om se verifică înainte de fiecare cerere; la prima eroare sau la oprire nu mai pornește nicio cerere nouă, iar cele pornite se termină înainte să se întoarcă eroarea.
import { FETCH_BACKOFF_SECONDS, FETCH_CONCURRENCY, FETCH_RETRIES, FETCH_TIMEOUT_MS } from '../settings.js';
import { pageFetch } from './page_functions.js';
import { RunCancelled } from './progress.js';
import { CODE_NETWORK, CODE_SESSION_EXPIRED } from './run_errors.js';
import { isLoginAddress } from './session_check.js';
import { PageNotAccessible, WorkTabClosed, tabIo } from './work_tab.js';

const MODULE = 'page_fetcher';
// Din câte în câte pagini descărcate se scrie o linie în jurnal (și la final): destul cât să se vadă mersul, fără sute de rânduri.
const LOG_EVERY_PAGES = 25;

/** Sesiunea eMAG a expirat în timpul descărcării (redirecționare spre login). */
export class SessionExpired extends Error {
  /** `message` spune unde s-a văzut redirecționarea (de obicei calea cerută); implicit doar faptul că sesiunea a expirat. */
  constructor(message = 'sesiunea eMAG a expirat') {
    super(message);
    this.name = 'SessionExpired';
    this.code = CODE_SESSION_EXPIRED;
  }
}

/** O pagină nu s-a putut descărca după toate încercările (rețea căzută, HTTP diferit de 200, termen depășit). */
export class FetchFailed extends Error {
  /** `path`: pagina cerută; `reason`: ultimul motiv, scurt (ex. „HTTP 500”, „timeout”). */
  constructor(path, reason) {
    super(`nu am putut descărca ${path}: ${reason}`);
    this.name = 'FetchFailed';
    this.code = CODE_NETWORK;
    this.path = path;
    this.reason = reason;
  }
}

/** HTML-ul unei pagini, cu reîncercări; SessionExpired la redirect spre login, FetchFailed (sau PageNotAccessible) după ultima încercare. */
async function fetchHtml(tabId, path, progress, log, io) {
  let lastReason = 'necunoscută';
  let lastError = null;
  for (let attempt = 1; attempt <= FETCH_RETRIES; attempt += 1) {
    lastError = null;
    try {
      const reply = await io.runInTab(tabId, pageFetch, [path, FETCH_TIMEOUT_MS]);
      if (!reply || typeof reply !== 'object') {
        lastReason = 'fără răspuns din pagină';
      } else if (reply.eroare) {
        lastReason = String(reply.eroare);
      } else {
        if (isLoginAddress(reply.finalUrl) && !path.toLowerCase().includes('login')) throw new SessionExpired(`redirecționat la login pentru ${path}`);
        if (reply.status === 200) return reply.html;
        lastReason = `HTTP ${reply.status}`;
      }
    } catch (error) {
      if (error instanceof SessionExpired || error instanceof WorkTabClosed || error instanceof RunCancelled) throw error;
      lastReason = String(error?.message ?? error);
      lastError = error;
    }
    log.warning(MODULE, `${path}: încercarea ${attempt}/${FETCH_RETRIES} a eșuat (${lastReason})`);
    if (attempt < FETCH_RETRIES) {
      await io.sleep(FETCH_BACKOFF_SECONDS * attempt * 1000);
      progress.raiseIfCancelled();
    }
  }
  if (lastError instanceof PageNotAccessible) throw lastError;
  throw new FetchFailed(path, lastReason);
}

/**
 * Descarcă fiecare cale și aplică `handler(cale, html)`; păstrează ordinea căilor.
 * La prima eroare (sau la oprirea cerută, RunCancelled) nu mai pornește nicio cerere și așteaptă să se termine cele pornite: altfel ar continua pe o filă care se închide.
 */
export async function fetchEach(tabId, paths, handler, label, progress, log, io = tabIo) {
  const total = paths.length;
  const results = new Array(total);
  let next = 0;
  let done = 0;
  let failure = null;
  progress.advance(0, total);

  /** Un lucrător: ia următoarea cale, o descarcă, o parsează pe loc și raportează progresul; se oprește când nu mai sunt căi sau când un altul a eșuat. */
  async function worker() {
    while (failure === null) {
      const index = next;
      next += 1;
      if (index >= total) return;
      try {
        progress.raiseIfCancelled();
        const html = await fetchHtml(tabId, paths[index], progress, log, io);
        if (failure !== null) return; // un alt lucrător a eșuat între timp: pagina asta nu se mai procesează
        results[index] = await handler(paths[index], html);
        done += 1;
        progress.advance(done, total);
        if (done % LOG_EVERY_PAGES === 0 || done === total) log.info(MODULE, `${label}: ${done}/${total} descărcate`);
      } catch (error) {
        if (failure === null) failure = error;
        return;
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(FETCH_CONCURRENCY, total) }, () => worker()));
  if (failure !== null) throw failure;
  return results;
}
