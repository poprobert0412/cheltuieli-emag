// Pauze și ceas pentru colectare: `sleep(ms)` și `now()`.
// Primește: un număr de milisecunde. Dă înapoi: o promisiune care se îndeplinește după pauză, respectiv ora curentă în milisecunde.
// Pauzele se fac într-un Worker (timer_worker.js), nu cu setTimeout din pagină. Măsurat pe 14.10.2026 în Edge 155: o pagină a extensiei ascunsă mai mult de 5 minute (omul lucrează în altă filă)
// primește setTimeout și setInterval doar o dată pe minut (și cu un Web Lock ținut), pe când cronometrul dintr-un Worker merge nereduse; cu setTimeout, citirea listelor ar fi durat ore.
// Scraperele, descărcarea și jurnalul primesc `sleep` și `now` prin obiectul `io` / import, deci testele pun un ceas fals. Fără Worker (Node) sau dacă nu se poate crea, pauza cade pe setTimeout.
// Ce NU face: nu verifică oprirea cerută de om (o face apelantul, după fiecare pauză) și nu știe de file sau de pagini.

// Pauzele în așteptare: id -> { resolve, ms, startedAt }; răspunsul Worker-ului le termină una câte una.
const pending = new Map();
let nextId = 1;
// undefined = încă neîncercat; null = indisponibil (rezerva pe setTimeout); altfel Worker-ul pe care îl împart toate pauzele paginii.
let timerWorker;

/** Worker-ul gol a căzut: pauzele în așteptare se termină pe setTimeout, cu timpul care le mai rămâne, și de acum încolo pauzele merg pe setTimeout. */
function giveUpOnWorker() {
  timerWorker = null;
  for (const [id, entry] of pending) {
    pending.delete(id);
    setTimeout(entry.resolve, Math.max(0, entry.ms - (Date.now() - entry.startedAt)));
  }
}

/** Worker-ul cronometru al paginii (creat la prima pauză) sau null dacă nu există ori nu se poate crea. */
function workerOrNull() {
  if (timerWorker !== undefined) return timerWorker;
  try {
    if (typeof Worker !== 'function') {
      timerWorker = null;
      return null;
    }
    const created = new Worker(new URL('./timer_worker.js', import.meta.url));
    created.onmessage = (event) => {
      const entry = pending.get(event.data);
      if (!entry) return;
      pending.delete(event.data);
      entry.resolve();
    };
    created.onerror = () => giveUpOnWorker();
    timerWorker = created;
  } catch {
    timerWorker = null;
  }
  return timerWorker;
}

/** Așteaptă `ms` milisecunde, cu cronometrul din Worker (nereduse când pagina e ascunsă); pe setTimeout dacă nu există Worker. */
export function sleep(ms) {
  const worker = workerOrNull();
  if (worker === null) {
    return new Promise((resolve) => {
      setTimeout(resolve, ms);
    });
  }
  return new Promise((resolve) => {
    const id = nextId;
    nextId += 1;
    pending.set(id, { resolve, ms, startedAt: Date.now() });
    worker.postMessage({ id, ms });
  });
}

/** Ora curentă în milisecunde (pentru termene: login, randarea listei, creșterea listei de retururi). */
export function now() {
  return Date.now();
}
