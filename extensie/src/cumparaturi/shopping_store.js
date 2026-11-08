// Preferințe/listă/etichete criptate separat de ultima analiză; demo rămâne exclusiv în memorie.
// Fiecare store capturează generația inițială, inclusiv când cheia de preferințe încă nu există.
// Ștergerea invalidează consumatorul; quota și corupția se propagă apelantului și abonaților.
// La citire sau actualizare, schema1 migrează sub același lacăt folosind orele config, fără pierderea datelor personale ale listei.
import { privateStorage } from '../stocare/private_storage.js';
import { initialShoppingState, migrateShoppingState, validateShoppingState, SHOPPING_SCHEMA } from './shopping_schema.js';

export const SHOPPING_STORAGE_KEY = 'preferinte_cumparaturi';

/** Construiește store-ul; dependențele injectabile păstrează exact tranzacția reală în testele de concurență. */
export function createShoppingStore({ demo = false, defaults, storage = globalThis.chrome?.storage.local,
  persistence = privateStorage, changes = globalThis.chrome?.storage.onChanged } = {}) {
  const initial = initialShoppingState(defaults);
  let memory = structuredClone(initial);
  let disposed = false;
  let invalidated = false;
  let queue = Promise.resolve();
  const listeners = new Set();
  const expected = demo ? null : persistence.generation(storage);
  // Capture immediately without leaving a rejected initialization promise unobserved.
  expected?.catch(() => {});
  const storedState = (state) => Boolean(validateShoppingState(state, { allowLegacy: true }));

  /** Refuză apelurile după demontare/ștergere, în loc să recreeze accidental datele șterse. */
  function active() {
    if (disposed) throw new Error('preferințe: consumator închis');
    if (invalidated) throw new Error('datele au fost șterse între timp; reîncarcă pagina');
  }

  /** Fiecare abonat primește copia sa; un consumator nu poate modifica starea altuia. */
  function emit(state, error = null) {
    for (const listener of listeners) {
      // Un abonat eșuat nu anulează un commit reușit și nu lasă promise rejection neobservat.
      try { Promise.resolve(listener(state === null ? null : structuredClone(state), error)).catch((failure) => console.error(failure)); }
      catch (failure) { console.error(failure); }
    }
  }

  /** Citește ultima stare, fără cache real care s-ar învechi între panou și aplicație. */
  async function read() {
    active();
    if (demo) return structuredClone(memory);
    let value = await persistence.read(storage, SHOPPING_STORAGE_KEY, storedState);
    if (value !== null && value.schema !== SHOPPING_SCHEMA) {
      value = await persistence.update(storage, SHOPPING_STORAGE_KEY, storedState,
        (current) => current === null ? structuredClone(initial) : migrateShoppingState(current, defaults), expected);
    }
    active();
    return structuredClone(value ?? initial);
  }

  /** Aplică mutatorul pe cea mai nouă stare sub lacăt; un eșec nu schimbă starea precedentă. */
  function update(mutator) {
    const action = async () => {
      active();
      try {
        if (typeof mutator !== 'function') throw new TypeError('preferințe: mutator invalid');
        const modify = async (current) => {
          active();
          const draft = structuredClone(current === null ? initial : migrateShoppingState(current, defaults));
          const returned = await mutator(draft);
          active();
          return validateShoppingState(returned === undefined ? draft : returned);
        };
        const next = demo ? await modify(memory) : await persistence.update(storage, SHOPPING_STORAGE_KEY,
          storedState, modify, expected);
        if (demo) { memory = structuredClone(next); emit(memory); }
        return structuredClone(next);
      } catch (error) { emit(null, error); throw error; }
    };
    // Serializarea locală contează și în demo, unde nu există Web Lock.
    const result = queue.then(action);
    queue = result.catch(() => {});
    return result;
  }

  /** Evenimentul Chrome transportă doar notificarea; conținutul este autentificat din nou de persistență. */
  function changed(items, areaName) {
    if (disposed || demo || areaName !== 'local' || !Object.hasOwn(items, SHOPPING_STORAGE_KEY)) return;
    if (items[SHOPPING_STORAGE_KEY].newValue === undefined) {
      invalidated = true;
      emit(null);
      return;
    }
    read().then((value) => { if (!disposed && !invalidated) emit(value); }, (error) => { if (!disposed) emit(null, error); });
  }

  if (!demo) changes?.addListener(changed);
  return {
    read, update,
    /** Abonează; întoarce dezabonarea fără să creeze o copie persistentă a stării. */
    subscribe(listener) { active(); listeners.add(listener); return () => listeners.delete(listener); },
    /** Oprește ascultătorul și golește orice stare demonstrativă păstrată în memorie. */
    dispose() { disposed = true; changes?.removeListener(changed); listeners.clear(); memory = null; },
  };
}
