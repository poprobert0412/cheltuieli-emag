// Forma unică a preferințelor de cumpărături; validează la granița stocării, fără valori financiare implicite.
// Primește date JSON și întoarce aceeași stare validă ori TypeError; nu citește DOM sau stocare.
// Schema2 adaugă orele/fusul campaniei; schema1 este acceptată numai la granița migrării fără pierderi.
import { isShoppingDate, SHOPPING_TIME_ZONE, validateCampaign } from './campaign_time.js';
export { isShoppingDate, isShoppingTime, validateCampaign } from './campaign_time.js';

export const SHOPPING_SCHEMA = 2;
// Limite tehnice pentru un rând lizibil și URL-uri web; nu sunt plafoane financiare.
export const SHOPPING_LIMITS = Object.freeze({ name: 500, tag: 80, url: 2048, id: 2048 });
const UNSAFE_TEXT = /[\p{Cc}\p{Cf}]/u;
const BAD_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/** Canonizează numai pagini de produs eMAG HTTPS; elimină parametrii/hash-ul care nu identifică produsul. */
export function canonicalShoppingProductUrl(value) {
  if (typeof value !== 'string' || value.length > SHOPPING_LIMITS.url || UNSAFE_TEXT.test(value) || value !== value.trim()) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.hostname !== 'www.emag.ro' || url.username || url.password || url.port
        || !/^\/[^/]+\/pd\/[a-zA-Z0-9]+\/?$/.test(url.pathname)) return null;
    return `${url.origin}${url.pathname.replace(/\/$/, '')}`;
  } catch { return null; }
}

/** Verifică un URL de produs fără să-l modifice; scrierea formei canonice este responsabilitatea formularului. */
export function isValidShoppingUrl(value) { return canonicalShoppingProductUrl(value) !== null; }

/** Obiect simplu, cu exact câmpurile documentate; exclude cheile care ar modifica prototipuri. */
function object(value, keys, where) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw new TypeError(`${where}: obiect invalid`);
  if (Object.keys(value).some((key) => BAD_KEYS.has(key) || (keys && !keys.includes(key)))) throw new TypeError(`${where}: câmp necunoscut`);
  if (keys && keys.some((key) => !Object.hasOwn(value, key))) throw new TypeError(`${where}: câmp lipsă`);
}

/** Text liber cu limită tehnică, fără caractere de control/invizibile; HTML este text, randat cu textContent. */
function text(value, limit, where, empty = false) {
  if (typeof value !== 'string' || value.length > limit || (!empty && !value.trim()) || UNSAFE_TEXT.test(value)) throw new TypeError(`${where}: text invalid`);
}

/** Sumele utilizatorului sunt întregi reprezentabili exact; null înseamnă nesetat, niciodată zero implicit. */
function money(value, where, nullable = true) {
  if (nullable && value === null) return;
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(`${where}: suma trebuie să fie un întreg nenegativ în bani`);
}

/** Verifică întreaga schemă înainte de salvare; corupția nu este înlocuită cu preferințe goale. */
export function validateShoppingState(value, { allowLegacy = false } = {}) {
  object(value, ['schema', 'campaign', 'wishlist', 'budgets', 'tags'], 'preferințe');
  const legacy = allowLegacy && value.schema === 1;
  if (value.schema !== SHOPPING_SCHEMA && !legacy) throw new TypeError('preferințe: schemă necunoscută');
  object(value.campaign, legacy ? ['from', 'to', 'budget_bani'] : ['from', 'to', 'start_time', 'end_time', 'time_zone', 'budget_bani'], 'campanie');
  if (legacy) {
    if (!isShoppingDate(value.campaign.from) || !isShoppingDate(value.campaign.to) || value.campaign.from > value.campaign.to) throw new TypeError('campanie: interval invalid');
  } else validateCampaign(value.campaign);
  money(value.campaign.budget_bani, 'campanie');
  if (!Array.isArray(value.wishlist)) throw new TypeError('listă: format invalid');
  const ids = new Set();
  for (const row of value.wishlist) {
    object(row, ['id', 'name', 'url', 'price_bani', 'target_bani', 'observed_at', 'selected'], 'produs');
    text(row.id, SHOPPING_LIMITS.id, 'identificator');
    if (ids.has(row.id)) throw new TypeError('produs: identificator duplicat');
    ids.add(row.id);
    text(row.name, SHOPPING_LIMITS.name, 'denumire');
    if (row.url !== '' && !isValidShoppingUrl(row.url)) throw new TypeError('produs: URL eMAG invalid');
    money(row.price_bani, 'preț'); money(row.target_bani, 'țintă');
    if (row.observed_at !== null && (typeof row.observed_at !== 'string'
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(row.observed_at)
        || !isShoppingDate(row.observed_at.slice(0, 10)) || !Number.isFinite(Date.parse(row.observed_at)))) throw new TypeError('produs: data observării invalidă');
    if (typeof row.selected !== 'boolean') throw new TypeError('produs: selecție invalidă');
  }
  object(value.budgets, null, 'bugete');
  for (const [key, amount] of Object.entries(value.budgets)) {
    if (!/^\d{4}(?:-(?:0[1-9]|1[0-2]))?$/.test(key)) throw new TypeError('buget: perioadă invalidă');
    money(amount, 'buget', false);
  }
  object(value.tags, null, 'etichete');
  for (const [key, tag] of Object.entries(value.tags)) {
    text(key, SHOPPING_LIMITS.id, 'cheie achiziție'); text(tag, SHOPPING_LIMITS.tag, 'etichetă', true);
  }
  return value;
}

/** Construiește starea inițială numai din configurația furnizată de build. */
export function initialShoppingState(defaults) {
  return validateShoppingState({ schema: SHOPPING_SCHEMA, campaign: { ...defaults.campaign,
    start_time: defaults.campaign.start_time ?? null, end_time: defaults.campaign.end_time ?? null,
    time_zone: defaults.campaign.time_zone ?? SHOPPING_TIME_ZONE, budget_bani: null }, wishlist: [], budgets: {}, tags: {} });
}

/** Migrează schema1 fără pierderea datelor; intervalele vechi incompatibile cer ore explicite, nu date inventate. */
export function migrateShoppingState(value, defaults) {
  validateShoppingState(value, { allowLegacy: true });
  if (value.schema === SHOPPING_SCHEMA) return value;
  const campaign = { ...value.campaign, start_time: defaults.campaign.start_time ?? null,
    end_time: defaults.campaign.end_time ?? null, time_zone: defaults.campaign.time_zone ?? SHOPPING_TIME_ZONE };
  try { validateCampaign(campaign); }
  catch { campaign.start_time = null; campaign.end_time = null; }
  return validateShoppingState({ ...value, schema: SHOPPING_SCHEMA, campaign });
}
