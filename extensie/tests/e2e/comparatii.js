// Comparații pentru testele cap-coadă: unde diferă două valori JSON sau două texte, ca un eșec să arate ce nu se potrivește, nu doar „valorile diferă”.
// Primește: valoarea așteptată (de la Python) și cea primită (de la extensie). Dă înapoi: o listă scurtă de diferențe (cale, valoare Python, valoare extensie) sau primul loc în care două texte se despart.
// `normalize` face o valoare să arate ca după un drum prin chrome.storage sau prin JSON: -0 devine 0 și cheile cu undefined dispar (aceeași copie pe ambele părți, deci nu ascunde nicio diferență de cifre).
// Ce NU face: nu decide ce se compară și nu aruncă erori; testele folosesc rezultatul în mesajul lor.
import { isDeepStrictEqual } from 'node:util';

// Câte diferențe se arată într-un mesaj: destule cât să se vadă tiparul, puține cât mesajul să rămână citibil.
const MAX_DIFFERENCES = 6;
// Câte caractere din valorile comparate se arată într-o diferență.
const SHOWN_CHARS = 80;
// Câte caractere de context se arată în jurul primei diferențe dintre două texte.
const CONTEXT_BEFORE = 20;
const CONTEXT_AFTER = 40;

/** Copia unei valori după un drum prin JSON (cum ajunge o valoare după chrome.storage). */
export function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

/** Primele diferențe dintre `expected` (Python) și `actual` (extensie), ca texte „cale: Python=... extensie=...”; lista goală înseamnă că valorile sunt egale. */
export function differences(expected, actual, where = '$', found = []) {
  if (found.length >= MAX_DIFFERENCES || isDeepStrictEqual(expected, actual)) return found;
  const isObject = (value) => value !== null && typeof value === 'object';
  if (!isObject(expected) || !isObject(actual) || Array.isArray(expected) !== Array.isArray(actual)) {
    found.push(`${where}: Python=${JSON.stringify(expected)?.slice(0, SHOWN_CHARS)} extensie=${JSON.stringify(actual)?.slice(0, SHOWN_CHARS)}`);
    return found;
  }
  for (const key of new Set([...Object.keys(expected), ...Object.keys(actual)])) differences(expected[key], actual[key], `${where}.${key}`, found);
  return found;
}

/** Prima poziție în care două texte diferă, cu puțin context și lungimile lor; gol dacă sunt identice. */
export function firstTextDifference(expected, actual) {
  if (expected === actual) return '';
  const length = Math.min(expected.length, actual.length);
  let at = 0;
  while (at < length && expected[at] === actual[at]) at += 1;
  const context = (text) => JSON.stringify(text.slice(Math.max(0, at - CONTEXT_BEFORE), at + CONTEXT_AFTER));
  return `la poziția ${at}: Python=${context(expected)} extensie=${context(actual)} (lungimi ${expected.length} și ${actual.length})`;
}
