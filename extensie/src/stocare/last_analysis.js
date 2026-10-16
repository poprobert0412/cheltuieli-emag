// Ultima analiză salvată în browser (E4): o singură intrare în chrome.storage.local, cu butonul „Șterge datele”.
// Primește: intrarea { schema, extension_version, created_at, threshold_lei, summary, orders, returns, log_text }. Dă înapoi aceeași intrare; în stocare rămâne numai anvelopa AES-GCM.
// Datele schema1 existente se migrează la citire; ciphertextul stricat sau fără cheie ridică eroare, nu este tratat ca stocare goală.
// O analiză nouă o înlocuiește pe cea veche abia când e gata și încape: `set` e un singur apel, deci o scriere eșuată (cota plină) lasă intrarea veche întreagă.
// Ce se păstrează criptat: cifrele raportului, numerele comenzilor/retururilor, produsele și jurnalul. Parserele nu extrag numele titularului, adresa, telefonul sau e-mailul; NU se păstrează HTML-ul paginilor, cookie-uri, parola;
// o cheie cu un astfel de nume într-o intrare se refuză, ca o greșeală viitoare de port să nu ducă date de felul ăsta în stocare.
// Ce NU face: nu calculează nimic și nu șterge lacătul din chrome.storage.session (acela e al analizei în curs). Jurnalul rulării în curs stă separat (run_log.js).
import { CODE_STORAGE_FULL } from '../colectare/run_errors.js';
import { privateStorage } from './private_storage.js';

export const LAST_ANALYSIS_KEY = 'ultima_analiza';
export const ENTRY_SCHEMA = 1;
// Numele de chei care n-au ce căuta într-o intrare salvată (E4: „nu se păstrează niciodată HTML-ul paginilor, cookie-uri, parola”).
const FORBIDDEN_KEYS = new Set(['html', 'cookie', 'cookies', 'password', 'parola']);
// Fragmentul din mesajul lui Chrome când spațiul s-a umplut: „QUOTA_BYTES quota exceeded”.
const QUOTA_PATTERN = /quota/i;

/** Spațiul extensiei din browser s-a umplut: noua analiză nu încape (cea veche a rămas neatinsă). */
export class StorageFull extends Error {
  /** `message` e de obicei textul lui Chrome („QUOTA_BYTES quota exceeded”); omul vede mesajul din run_errors.js. */
  constructor(message = 'spațiul extensiei din browser e plin') {
    super(message);
    this.name = 'StorageFull';
    this.code = CODE_STORAGE_FULL;
  }
}

/** True pentru un obiect obișnuit (nu listă, nu Map, nu instanță de clasă). */
function isPlainObject(value) {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * Copie care trece prin JSON fără pierderi: Map devine obiect (altfel Chrome îl păstrează ca {}), listele și obiectele se copiază adânc,
 * cheile interzise, valorile care nu au formă JSON (funcții, NaN, instanțe de clasă) ridică TypeError cu calea lor. Cheile cu valoare undefined dispar, ca în JSON.
 */
function jsonSafe(value, where = 'intrare') {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError(`${where}: numărul ${String(value)} nu are formă JSON`);
    return value;
  }
  if (Array.isArray(value)) return value.map((item, index) => jsonSafe(item, `${where}[${index}]`));
  const entries = value instanceof Map ? [...value.entries()] : isPlainObject(value) ? Object.entries(value) : null;
  if (entries === null) throw new TypeError(`${where}: o valoare de tip ${typeof value} nu se poate salva`);
  const copy = {};
  for (const [rawKey, item] of entries) {
    const key = String(rawKey);
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) throw new TypeError(`${where}.${key}: o astfel de cheie nu are voie în datele salvate (E4)`);
    if (item !== undefined) copy[key] = jsonSafe(item, `${where}.${key}`);
  }
  return copy;
}

/** True dacă `entry` are forma intrării salvate (schema 1, câmpurile cu tipurile lor). */
function isValidEntry(entry) {
  return isPlainObject(entry)
    && entry.schema === ENTRY_SCHEMA
    && typeof entry.extension_version === 'string'
    && typeof entry.created_at === 'string'
    && typeof entry.threshold_lei === 'number' && Number.isFinite(entry.threshold_lei)
    && entry.summary !== null && typeof entry.summary === 'object' && !Array.isArray(entry.summary)
    && Array.isArray(entry.orders)
    && Array.isArray(entry.returns)
    && typeof entry.log_text === 'string';
}

/** Salvează `entry` ca ultimă analiză (o înlocuiește pe cea veche); TypeError pentru o intrare greșită, StorageFull dacă nu încape. */
export async function saveLastAnalysis(entry, storage = chrome.storage.local, persistence = privateStorage) {
  if (!isValidEntry(entry)) throw new TypeError('intrarea ultimei analize nu are forma așteptată (schema 1: versiune, dată, prag, analiză, comenzi, retururi, jurnal)');
  const safe = jsonSafe(entry);
  try {
    await persistence.write(storage, LAST_ANALYSIS_KEY, safe);
  } catch (error) {
    if (QUOTA_PATTERN.test(String(error?.message ?? error))) throw new StorageFull(String(error?.message ?? error));
    throw error;
  }
}

/** Ultima analiză decriptată (cu migrare schema1), sau null dacă lipsește; criptarea/migrarea eșuată ridică eroare explicită. */
export async function loadLastAnalysis(storage = chrome.storage.local, persistence = privateStorage) {
  return persistence.read(storage, LAST_ANALYSIS_KEY, isValidEntry);
}

/** „Șterge datele”: golește datele și cheia lor; generația nouă oprește scrierile vechi din alte file. */
export async function deleteAllData(storage = chrome.storage.local, persistence = privateStorage) {
  await persistence.clear(storage);
}
