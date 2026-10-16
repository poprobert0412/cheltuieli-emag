// Raportarea progresului unei rulări: faza curentă, „făcute din total”, mesajul propriu și cererea de oprire (portul lui emag_spend/progress.py + partea activă din app_runner.py).
// Primește: apeluri de la colector și de la scrapere (`phase`, `advance`, `message`, `raiseIfCancelled`) și de la ecrane (`cancel`). Dă înapoi: instantanee ale stării, către ascultătorul `onChange`.
// Oprirea e cooperantă: codul întreabă `raiseIfCancelled()` în punctele sigure (între pagini, în așteptarea login-ului) și primește RunCancelled, ca fila de lucru să se închidă curat prin blocurile `finally`.
// Numele fazelor sunt cele din aplicația locală (starea din GET /api/state), ca ecranele să folosească aceleași valori.
// Ce NU face: nu desenează nimic (ecranul „în lucru” o face) și nu scrie în jurnal.

export const PHASE_STARTING = 'starting';
export const PHASE_WAITING_LOGIN = 'waiting_login';
export const PHASE_FETCHING_ORDERS = 'fetching_orders';
export const PHASE_FETCHING_RETURNS = 'fetching_returns';
export const PHASE_ANALYZING = 'analyzing';
// Fazele pe care le poate cere codul de colectare și de analiză (PHASE_STARTING e doar starea de început).
export const PIPELINE_PHASES = Object.freeze([PHASE_WAITING_LOGIN, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_ANALYZING]);

/** Utilizatorul a cerut oprirea: nu e o eroare, ci o ieșire controlată (fila de lucru se închide, nu rămâne nimic agățat). */
export class RunCancelled extends Error {
  /** Mesajul implicit e cel din Python („la cererea ta”); apare în jurnal, nu pe ecran (oprirea are ecranul ei). */
  constructor(message = 'rularea a fost oprită la cererea ta') {
    super(message);
    this.name = 'RunCancelled';
  }
}

/** Jurnal care nu scrie nimic: pentru teste și pentru apeluri fără jurnal. Are aceleași metode ca RunLog (stocare/run_log.js). */
export const NO_LOG = Object.freeze({
  info() {},
  warning() {},
  error() {},
});

/**
 * Starea unei rulări, ținută într-un singur loc: ecranul „în lucru” o citește prin `onChange(snapshot)`, iar colectorul o scrie.
 * După `finish()` apelurile târzii (lucrători rămași în urmă) nu mai schimbă nimic.
 */
export class Progress {
  #phase = PHASE_STARTING;
  #done = 0;
  #total = null;
  #message = '';
  #cancelRequested = false;
  #finished = false;
  #onChange;

  /** `onChange` primește câte o copie a stării la fiecare schimbare; lipsa lui face din obiect un raportor inactiv. */
  constructor({ onChange = null } = {}) {
    this.#onChange = onChange;
  }

  /** O copie a stării de acum: { phase, done, total, message, cancelRequested }. */
  snapshot() {
    return { phase: this.#phase, done: this.#done, total: this.#total, message: this.#message, cancelRequested: this.#cancelRequested };
  }

  /** Anunță ascultătorul (dacă există) cu o copie a stării de acum. */
  #emit() {
    if (this.#onChange) this.#onChange(this.snapshot());
  }

  /** Începe faza `name` (una din PIPELINE_PHASES; altele se ignoră); contorul pornește de la 0, iar mesajul propriu se șterge. */
  phase(name, total = null) {
    if (this.#finished || !PIPELINE_PHASES.includes(name)) return;
    this.#phase = name;
    this.#message = '';
    this.#done = 0;
    this.#total = total;
    this.#emit();
  }

  /** Anunță că s-au făcut `done` pași din `total` (null = nu se știe încă) în faza curentă. */
  advance(done, total = null) {
    if (this.#finished) return;
    this.#done = done;
    this.#total = total;
    this.#emit();
  }

  /** Textul propriu pe care omul îl vede lângă bara de progres, până la următoarea fază. */
  message(text) {
    if (this.#finished) return;
    this.#message = text;
    this.#emit();
  }

  /** Cere oprirea rulării; se vede la următorul `raiseIfCancelled()`, nu pe loc. */
  cancel() {
    if (this.#finished) return;
    this.#cancelRequested = true;
    this.#emit();
  }

  /** True după `cancel()`. */
  get cancelRequested() {
    return this.#cancelRequested;
  }

  /** Aruncă RunCancelled dacă oprirea a fost cerută; se cheamă doar în puncte unde oprirea e sigură. */
  raiseIfCancelled() {
    if (this.#cancelRequested) throw new RunCancelled();
  }

  /** Rularea s-a încheiat (bine, cu eroare sau oprită): apelurile următoare nu mai au efect. */
  finish() {
    this.#finished = true;
  }
}
