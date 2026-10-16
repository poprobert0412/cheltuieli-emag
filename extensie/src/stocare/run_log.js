// Jurnalul unei rulări, criptat pe parcurs în chrome.storage.local (CLAUDE.md §9): ce a făcut analiza, pas cu pas, ca să poți răspunde „ce s-a întâmplat la rularea de marți” fără s-o repeți.
// Primește: mesaje de la INFO în sus (info, warning, error), cu numele modulului. Dă înapoi: textul jurnalului, în formatul `%(asctime)s [%(name)s] %(levelname)s: %(message)s` al programului Python.
// Se scrie în stocare la fiecare `flush()` (după fiecare fază) și, între ele, la cel mult LOG_FLUSH_INTERVAL_MS după un rând nou: o rulare căzută la pasul 5 lasă pe disc pașii 1–4.
// Jurnalul rulării căzute rămâne sub cheia lui până la rularea următoare; la o rulare reușită intră în ultima analiză (last_analysis.js) și cheia se șterge.
// Scrierea automată așteaptă cu `sleep` din colectare/waiting.js (cronometru în Worker): pagina ascunsă peste 5 minute primește setTimeout doar o dată pe minut (măsurat în Edge 155), iar jurnalul trebuie să ajungă în stocare la timp.
// Ce NU face: nu decide ce se loghează (colectorul și scraperele) și nu ridică erori dacă stocarea e plină (scrie un rând despre asta și merge mai departe).
import { sleep } from '../colectare/waiting.js';
import { privateStorage } from './private_storage.js';

export const RUN_LOG_KEY = 'jurnal_rulare';
const LOG_SCHEMA = 1;
// Cât așteaptă RunLog după un rând nou înainte să-l scrie în stocare: destul cât zeci de rânduri să plece într-o singură scriere, puțin cât să nu se piardă mult dacă fila se închide.
const LOG_FLUSH_INTERVAL_MS = 2000;
// Plafonul de rânduri: o rulare obișnuită scrie sub 300; 2000 de rânduri (~200 KB) ține jurnalul mic față de cota de 10 MB a extensiei, chiar și la un cont cu multe avertismente.
const MAX_LOG_LINES = 2000;

/** Două cifre (sau trei, pentru milisecunde) cu zerouri în față. */
function pad(number, width = 2) {
  return String(number).padStart(width, '0');
}

/** Ora locală în formatul `asctime` din logging: 2026-10-14 09:05:07,042 (cu milisecunde după virgulă). */
function formatTime(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())},${pad(date.getMilliseconds(), 3)}`;
}

/** Jurnalul unei rulări: rânduri în memorie, scrise în stocare la `flush()` și, după un rând nou, la interval. */
export class RunLog {
  #storage;
  #persistence;
  #generation;
  #clock;
  #flushIntervalMs;
  #maxLines;
  #lines = [];
  #truncated = false;
  #scheduled = false;
  #queue = Promise.resolve(true);
  #persistFailed = false;
  #discarded = false;
  #version = 0; // crește la fiecare rând nou; scrierea sare peste o stare deja scrisă
  #writtenVersion = 0;

  /** `storage`: zona chrome.storage; `persistence`: persistența criptată; `clock`: ceasul; `flushIntervalMs` 0 dezactivează scrierea automată; `maxLines`: plafonul de rânduri. */
  constructor({ storage = null, persistence = privateStorage, clock = () => new Date(), flushIntervalMs = LOG_FLUSH_INTERVAL_MS, maxLines = MAX_LOG_LINES } = {}) {
    this.#storage = storage;
    this.#persistence = persistence;
    this.#generation = persistence.generation(storage ?? chrome.storage.local);
    this.#generation.catch(() => {}); // #write raportează eroarea; constructorul nu lasă o respingere neprinsă până la primul flush
    this.#clock = clock;
    this.#flushIntervalMs = flushIntervalMs;
    this.#maxLines = maxLines;
  }

  /** Un rând de nivel INFO. */
  info(module, text) {
    this.#add('INFO', module, text);
  }

  /** Un rând de nivel WARNING. */
  warning(module, text) {
    this.#add('WARNING', module, text);
  }

  /** Un rând de nivel ERROR. */
  error(module, text) {
    this.#add('ERROR', module, text);
  }

  /** Tot jurnalul de până acum: un rând pe linie, fiecare încheiat cu rând nou. */
  text() {
    return this.#lines.map((line) => `${line}\n`).join('');
  }

  /** Formatează un rând; sfârșiturile de rând din mesaj devin „ / ”, ca un mesaj să nu poată înșira rânduri false de jurnal. */
  #format(level, module, text) {
    return `${formatTime(this.#clock())} [${module}] ${level}: ${String(text).replace(/\r?\n/g, ' / ')}`;
  }

  /** Adaugă un rând (cu plafonul de rânduri: peste el se scrie o singură dată un rând care spune că restul se pierde) și programează scrierea în stocare. */
  #add(level, module, text) {
    if (this.#truncated) return;
    if (this.#lines.length >= this.#maxLines) {
      this.#truncated = true;
      this.#lines.push(this.#format('WARNING', 'run_log', `jurnalul a depășit ${this.#maxLines} rânduri; restul nu se mai scrie`));
    } else {
      this.#lines.push(this.#format(level, module, text));
    }
    this.#version += 1;
    this.#scheduleFlush();
  }

  /** Programează o scriere peste `flushIntervalMs` dacă nu e deja una programată (după ce se face, un rând nou programează alta). */
  #scheduleFlush() {
    if (this.#flushIntervalMs <= 0 || this.#scheduled || this.#discarded) return;
    this.#scheduled = true;
    sleep(this.#flushIntervalMs).then(() => {
      this.#scheduled = false;
      this.flush();
    });
  }

  /** O scriere în stocare; nu ridică excepții: la eșec notează un singur rând în jurnal și întoarce false. După `discard()` și când nu e nimic nou de scris nu scrie nimic. */
  async #write() {
    if (this.#discarded) return true;
    if (this.#version === this.#writtenVersion && !this.#persistFailed) return true;
    const version = this.#version;
    try {
      await this.#persistence.write(this.#storage ?? chrome.storage.local, RUN_LOG_KEY, { schema: LOG_SCHEMA, text: this.text() }, await this.#generation);
      this.#writtenVersion = version;
      this.#persistFailed = false;
      return true;
    } catch (error) {
      if (!this.#persistFailed) {
        this.#persistFailed = true;
        this.#lines.push(this.#format('WARNING', 'run_log', `jurnalul nu s-a putut salva în browser: ${String(error?.message ?? error)}`));
        this.#version += 1;
      }
      return false;
    }
  }

  /**
   * Renunță la jurnalul din stocare: oprește scrierile viitoare (și pe cea programată), apoi așteaptă ce era deja pornit. După asta cheia se poate șterge fără să reapară
   * (la o rulare reușită jurnalul intră în ultima analiză, iar copia de lucru trebuie să dispară).
   */
  async discard() {
    this.#discarded = true;
    await this.#queue;
  }

  /** Scrie jurnalul de acum în stocare; scrierile se pun la coadă (niciuna nu o depășește pe alta). Întoarce true dacă s-a scris. */
  flush() {
    this.#queue = this.#queue.then(() => this.#write());
    return this.#queue;
  }
}

/** Jurnalul salvat al ultimei rulări (reușite sau căzute), sau null dacă nu există. */
export async function loadSavedRunLog(storage = chrome.storage.local, persistence = privateStorage) {
  const record = await persistence.read(storage, RUN_LOG_KEY, (value) => value && value.schema === LOG_SCHEMA && typeof value.text === 'string');
  return record?.text ?? null;
}

/** Șterge jurnalul salvat (la o rulare reușită, jurnalul a intrat deja în ultima analiză). */
export async function clearSavedRunLog(storage = chrome.storage.local, persistence = privateStorage) {
  await persistence.remove(storage, RUN_LOG_KEY);
}
