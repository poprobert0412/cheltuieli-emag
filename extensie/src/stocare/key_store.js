// Cheia locală neexportabilă a extensiei, păstrată ca CryptoKey în IndexedDB, separat de chrome.storage.local.
// Primește dependențele standard IndexedDB; citește/scrie cheia și generația de ștergere într-o tranzacție.
// Citirea nu generează o cheie; după ștergere rămâne doar generația, ca filele vechi să nu rescrie datele șterse.
// Nu criptează și nu coordonează filele: private_storage.js ține Web Lock-ul pentru operația completă.
import { AES_KEY_BITS, StorageEncryptionError } from './storage_encryption.js';

export const KEY_DATABASE_NAME = 'cheltuieli-emag-cheie-locala';
const DATABASE_VERSION = 1;
const STORE_NAME = 'chei';
const STATE_KEY = 'stare';
const INITIAL_GENERATION = 'initial';

/** Key store cu aceleași API-uri în browser și în teste; fiecare tranzacție își închide conexiunea. */
export function createKeyStore({ databaseName = KEY_DATABASE_NAME, indexedDB = null } = {}) {
  /** Deschide baza locală și schema ei, fără să creeze chei criptografice. */
  function open() {
    return new Promise((resolve, reject) => {
      const request = (indexedDB ?? globalThis.indexedDB).open(databaseName, DATABASE_VERSION);
      request.onupgradeneeded = () => { request.result.createObjectStore(STORE_NAME); };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new StorageEncryptionError('baza cheii locale este blocată de o altă filă'));
      request.onsuccess = () => resolve(request.result);
    });
  }

  /** Execută o singură cerere și așteaptă commitul; un request reușit fără commit nu este o scriere reușită. */
  async function transaction(mode, action) {
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, mode);
        const request = action(tx.objectStore(STORE_NAME));
        tx.oncomplete = () => resolve(request.result);
        tx.onabort = () => reject(tx.error ?? request.error ?? new StorageEncryptionError('tranzacția cheii locale a fost anulată'));
        tx.onerror = () => {}; // onabort raportează eroarea finală a tranzacției
      });
    } finally {
      db.close();
    }
  }

  /** Starea persistată sau starea inițială; o cheie alterată nu se înlocuiește automat. */
  async function read() {
    const state = await transaction('readonly', (store) => store.get(STATE_KEY));
    if (state === undefined) return { generation: INITIAL_GENERATION, key: null };
    if (!state || typeof state.generation !== 'string'
      || (state.key !== null && (!(state.key instanceof CryptoKey) || state.key.extractable
        || state.key.algorithm.name !== 'AES-GCM' || state.key.algorithm.length !== AES_KEY_BITS
        || [...state.key.usages].sort().join(',') !== 'decrypt,encrypt'))) {
      throw new StorageEncryptionError('cheia locală are un format invalid');
    }
    return state;
  }

  /** Persistă împreună cheia și generația; apelantul ține Web Lock-ul până după commit. */
  async function write(state) {
    await transaction('readwrite', (store) => store.put(state, STATE_KEY));
  }

  return { read, write };
}
