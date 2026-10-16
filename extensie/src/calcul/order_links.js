// Adresele paginilor unei comenzi sau ale unui retur pe eMAG, construite doar din numere validate (portul lui emag_spend/order_links.py).
// Primește: numărul comenzii (text) sau numărul returului împreună cu calea lui din cont. Dă înapoi: adresa https către pagina din contul utilizatorului,
// sau null dacă numărul nu arată ca un număr real. Validarea e STRICTĂ: datele pot veni din orice sursă, iar un număr ciudat (litere, gol, „..”, „/”) nu produce niciodată un link.
// Ce NU face: nu deschide adrese, nu cere nimic din rețea, nu citește pagini.
import { BASE_URL, RETURN_LIST_PATH, orderDetailPath } from '../settings.js';
import { PyPattern, escapePython } from './python_regex.js';

// Numerele de comandă eMAG sunt doar cifre. 3–15 cifre: destul cât să acopere orice număr real (și pe cele scurte din date inventate),
// prea puțin ca să încapă text, „../” sau o cale în el. Clase ASCII explicite ([0-9], nu \d): \d acceptă și cifre din alte alfabete, iar acelea nu trebuie să ajungă într-o adresă.
export const ORDER_ID_PATTERN = '[0-9]{3,15}';
const ORDER_ID = new PyPattern(ORDER_ID_PATTERN);

// Adresa comenzii: baza și calea vin din settings.js (o singură sursă pentru căile eMAG).
export const ORDER_URL_PREFIX = BASE_URL + orderDetailPath('');

// Pagina unui retur are forma reală „/user/return-history/<x>/<număr retur>”; doar numărul returului NU ajunge pentru adresă, de aceea adresa se construiește
// din calea salvată în ReturnRequest.detail_path, după aceeași validare.
const RETURN_PATH = new PyPattern(`${escapePython(RETURN_LIST_PATH)}/([0-9]{1,15})/(${ORDER_ID_PATTERN})`);

/** True dacă `orderId` e un text format doar din 3–15 cifre ASCII (orice alt tip, inclusiv număr, dă false). */
export function isValidOrderId(orderId) {
  return typeof orderId === 'string' && ORDER_ID.fullmatch(orderId) !== null;
}

/** Adresa paginii comenzii pe eMAG, sau null dacă numărul nu e valid (fără parametri în adresă). */
export function orderUrl(orderId) {
  if (!isValidOrderId(orderId)) return null;
  return ORDER_URL_PREFIX + orderId;
}

/** Adresa returului pe eMAG, din calea lui salvată (`detailPath`), sau null dacă numărul sau calea nu sunt valide; numărul singur nu ajunge, adresa reală are un segment în plus. */
export function returnUrl(returnId, detailPath = null) {
  if (!isValidOrderId(returnId) || typeof detailPath !== 'string') return null;
  const match = RETURN_PATH.fullmatch(detailPath);
  if (match === null || match.group(2) !== returnId) return null;
  return BASE_URL + detailPath;
}
