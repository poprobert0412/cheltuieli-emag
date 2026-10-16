// Persistența privată: leagă cheia IndexedDB, AES-GCM și commitul atomic al unei intrări chrome.storage.local.
// Primește zona de stocare și date JSON validate; oferă citire, scriere, ștergere și generații pentru jurnal.
// Toată operația ține același Web Lock între file, inclusiv migrarea schema1 și ștergerea; o generație veche nu poate rescrie date șterse.
// Migrarea înlocuiește plaintext doar după criptare și printr-un singur set; la eșec intrarea veche rămâne și se raportează eroare.
// Nu validează analiza sau jurnalul (validatorul vine de la consumator) și nu exportă ori regenerează chei la citirea ciphertextului.
import { createKeyStore } from './key_store.js';
import { AES_KEY_BITS, StorageEncryptionError, decryptRecord, encryptRecord, isEncryptedRecord } from './storage_encryption.js';

export const STORAGE_LOCK_NAME = 'cheltuieli-emag-date-private';

/** Construiește persistența cu dependențe standard injectabile; implicitele sunt API-urile reale ale extensiei. */
export function createPrivateStorage({ keyStore = createKeyStore(), locks = null, crypto = null, lockName = STORAGE_LOCK_NAME } = {}) {
  const generations = new WeakMap();
  const provider = () => crypto ?? globalThis.crypto;

  /** Serializare între toate filele originii; cheia nu rămâne memorată după eliberarea lacătului. */
  function exclusive(action) {
    return (locks ?? globalThis.navigator.locks).request(lockName, async () => action(await keyStore.read()));
  }

  /** Generația pe care a cunoscut-o acest consumator; capturată înainte de a programa un flush întârziat. */
  function generation(storage) {
    if (!generations.has(storage)) {
      const pending = exclusive((state) => state.generation);
      generations.set(storage, pending);
    }
    return generations.get(storage);
  }

  /** Refuză scrierile unei file sau ale unui jurnal care preced ultima ștergere explicită. */
  function checkGeneration(state, expected) {
    if (state.generation !== expected) throw new StorageEncryptionError('datele au fost șterse între timp; reîncarcă pagina înainte de o analiză nouă');
  }

  /** Creează cheia numai la scriere/migrare și numai când nu există ciphertext care ar avea nevoie de cheia pierdută. */
  async function ensureKey(state, storage) {
    if (state.key !== null) return state.key;
    const existing = await storage.get();
    if (Object.values(existing ?? {}).some(isEncryptedRecord)) throw new StorageEncryptionError('cheia locală a datelor criptate lipsește');
    const key = await provider().subtle.generateKey({ name: 'AES-GCM', length: AES_KEY_BITS }, false, ['encrypt', 'decrypt']);
    await keyStore.write({ ...state, key });
    return key;
  }

  /** Citește și autentifică; schema1 validă se migrează înainte de a întoarce datele. Nu ascunde o migrare eșuată. */
  async function read(storage, name, validate) {
    return exclusive(async (state) => {
      const stored = (await storage.get(name))?.[name];
      // Recitirea jurnalului nu reautorizează o filă veche să salveze analiza de dinainte de ștergere; numai propria ștergere sau reload schimbă generația cunoscută.
      if (!generations.has(storage)) generations.set(storage, Promise.resolve(state.generation));
      if (stored === undefined) return null;
      if (isEncryptedRecord(stored)) {
        if (state.key === null) throw new StorageEncryptionError('cheia locală a datelor criptate lipsește');
        const value = await decryptRecord(stored, state.key, name, provider());
        if (!validate(value)) throw new StorageEncryptionError('datele decriptate nu au forma așteptată');
        return value;
      }
      if (!validate(stored)) return null;
      try {
        const key = await ensureKey(state, storage);
        await storage.set({ [name]: await encryptRecord(stored, key, name, provider()) });
      } catch (error) {
        throw new StorageEncryptionError('migrarea criptată nu a reușit; datele vechi au rămas în stocare', { cause: error });
      }
      return stored;
    });
  }

  /** Criptează și comite o singură intrare; cota plină lasă intrarea anterioară intactă. */
  async function write(storage, name, value, expectedGeneration = generation(storage)) {
    const expected = await expectedGeneration;
    return exclusive(async (state) => {
      checkGeneration(state, expected);
      const key = await ensureKey(state, storage);
      await storage.set({ [name]: await encryptRecord(value, key, name, provider()) });
    });
  }

  /** Scoate o intrare fără să atingă cheia comună; o filă veche nu poate șterge jurnalul unei generații noi. */
  async function remove(storage, name) {
    const expected = await generation(storage);
    return exclusive(async (state) => {
      checkGeneration(state, expected);
      await storage.remove(name);
    });
  }

  /** Șterge datele, apoi cheia și schimbă generația sub același lacăt; la eșecul clear cheia rămâne utilizabilă. */
  async function clear(storage) {
    // Ștergerea trebuie să poată recupera inclusiv un key store corupt, fără să-i valideze sau citească cheia.
    return (locks ?? globalThis.navigator.locks).request(lockName, async () => {
      await storage.clear();
      const next = provider().randomUUID();
      await keyStore.write({ generation: next, key: null });
      generations.set(storage, Promise.resolve(next));
    });
  }

  return { read, write, remove, clear, generation };
}

export const privateStorage = createPrivateStorage();
