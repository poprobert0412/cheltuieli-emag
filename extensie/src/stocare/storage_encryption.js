// Criptare JSON autentificată pentru datele locale ale extensiei: AES-GCM prin WebCrypto, fără biblioteci criptografice.
// Primește: valoarea JSON, CryptoKey neexportabil și numele intrării; întoarce anvelopa JSON sau valoarea decriptată.
// Un nonce nou pentru fiecare scriere și AAD legat de intrare împiedică reutilizarea nonce-ului și mutarea analizei peste jurnal.
// Nu creează și nu păstrează cheia, nu citește stocarea și nu protejează împotriva celui care controlează profilul browserului.
export const ENCRYPTED_SCHEMA = 2;
// Parametri tehnici AES-GCM: cheie de 256 biți, nonce de 96 biți și etichetă de autentificare de 128 biți (WebCrypto/NIST).
export const AES_KEY_BITS = 256;
const NONCE_BYTES = 12;
const TAG_BITS = 128;
const ALGORITHM = 'AES-GCM';
const INVALID_FORMAT_MESSAGE = 'datele criptate au un format necunoscut sau incomplet';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

/** Date criptate indisponibile sau modificate; trebuie recuperate prin ștergere explicită, niciodată prin regenerarea cheii. */
export class StorageEncryptionError extends Error {
  /** Păstrează motivul tehnic fără datele salvate sau cheia. */
  constructor(message, options) {
    super(message, options);
    this.name = 'StorageEncryptionError';
    this.code = 'storage_encryption';
  }
}

/** Octeți ca Base64: chrome.storage păstrează doar JSON, nu ArrayBuffer. */
function toBase64(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** Base64 canonic înapoi în octeți; o anvelopă alterată este eroare, nu valoare goală. */
function fromBase64(value) {
  if (typeof value !== 'string' || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new StorageEncryptionError(INVALID_FORMAT_MESSAGE);
  }
  const bytes = Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
  if (toBase64(bytes) !== value) throw new StorageEncryptionError(INVALID_FORMAT_MESSAGE);
  return bytes;
}

/** Recunoaște inclusiv o anvelopă cu schema alterată, ca să nu fie tratată ca o intrare veche necunoscută. */
export function isEncryptedRecord(value) {
  return value !== null && typeof value === 'object'
    && (value.schema === ENCRYPTED_SCHEMA || 'ciphertext' in value || 'nonce' in value || 'algorithm' in value);
}

/** Date autentificate legate de versiunea formatului și de cheia chrome.storage; nu sunt secrete. */
function authenticatedData(recordName) {
  return encoder.encode(JSON.stringify([ENCRYPTED_SCHEMA, ALGORITHM, recordName]));
}

/** Criptează o valoare JSON folosind un nonce aleator proaspăt, fără să exporte cheia. */
export async function encryptRecord(value, key, recordName, provider = globalThis.crypto) {
  const nonce = provider.getRandomValues(new Uint8Array(NONCE_BYTES));
  const ciphertext = await provider.subtle.encrypt(
    { name: ALGORITHM, iv: nonce, additionalData: authenticatedData(recordName), tagLength: TAG_BITS },
    key, encoder.encode(JSON.stringify(value)),
  );
  return { schema: ENCRYPTED_SCHEMA, algorithm: ALGORITHM, nonce: toBase64(nonce), ciphertext: toBase64(new Uint8Array(ciphertext)) };
}

/** Verifică anvelopa și autenticitatea înainte de parsarea JSON; orice modificare ridică StorageEncryptionError. */
export async function decryptRecord(envelope, key, recordName, provider = globalThis.crypto) {
  try {
    if (!envelope || envelope.schema !== ENCRYPTED_SCHEMA || envelope.algorithm !== ALGORITHM
      || Object.keys(envelope).sort().join(',') !== 'algorithm,ciphertext,nonce,schema') {
      throw new StorageEncryptionError(INVALID_FORMAT_MESSAGE);
    }
    const nonce = fromBase64(envelope.nonce);
    const ciphertext = fromBase64(envelope.ciphertext);
    if (nonce.length !== NONCE_BYTES || ciphertext.length < TAG_BITS / 8) throw new StorageEncryptionError(INVALID_FORMAT_MESSAGE);
    const plain = await provider.subtle.decrypt(
      { name: ALGORITHM, iv: nonce, additionalData: authenticatedData(recordName), tagLength: TAG_BITS }, key, ciphertext,
    );
    return JSON.parse(decoder.decode(plain));
  } catch (error) {
    if (error instanceof StorageEncryptionError) throw error;
    throw new StorageEncryptionError('datele criptate nu se pot citi: cheia sau conținutul nu corespund', { cause: error });
  }
}
