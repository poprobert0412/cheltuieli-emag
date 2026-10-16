// Citirea și afișarea sumelor în lei, în format românesc (portul lui emag_spend/money_ro.py).
// Primește: text („1.449,27 Lei”, „-34,00 Lei”, „93.59 RON”, „GRATUIT”). Dă înapoi: sume întregi în BANI, ca să nu apară erori de rotunjire la adunări.
// Expresiile sunt cele din Python, rulate prin PyPattern (\d și \s cu înțelesul din Python: cifre din orice alfabet, spații Unicode); int() trece prin pyInt.
// Ce NU face: nu știe de comenzi sau retururi. Sumele peste 2^53 bani (90 de trilioane de lei) ridică RangeError în loc să iasă rotunjite.
import { cpSlice, pyDivmod, pyInt, pyStrip } from './python_compat.js';
import { PyPattern } from './python_regex.js';

// Suma în format românesc: puncte pentru mii, virgulă pentru zecimale.
const RO_AMOUNT = String.raw`-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}`;
const RO_AMOUNT_ONLY = new PyPattern(RO_AMOUNT);
const RO_AMOUNT_FULL = new PyPattern(String.raw`^(${RO_AMOUNT})\s*(?:Lei|lei|RON)?$`);
const RO_AMOUNT_ANY = new PyPattern(String.raw`(${RO_AMOUNT})\s*(?:Lei|lei|RON)`);
// Un singur punct urmat de exact 3 cifre se citește ca separator de mii („1.449”); altfel punctul e separator zecimal („93.59”).
const THOUSANDS_ONLY = new PyPattern(String.raw`\d{1,3}(?:\.\d{3})+`);
const DECIMAL_DOT = new PyPattern(String.raw`\d+(?:\.\d{1,2})?`);

/** Suma în bani doar dacă e un întreg sigur (sub 2^53); altfel RangeError, ca să nu iasă o valoare rotunjită în tăcere. */
function checkedBani(value) {
  if (!Number.isSafeInteger(value)) throw new RangeError(`suma ${value} depășește 2^53 bani și nu se poate reprezenta exact`);
  return value;
}

/** Cele două cifre de zecimale ale unei părți fracționare: primele două caractere din „frac” completat cu zerouri („5” devine 50). */
function fractionBani(frac) {
  return pyInt(cpSlice(`${frac}00`, 0, 2));
}

/** Transformă „1.449,27” sau „-34,00” în bani (144927 / -3400). Textul care nu e număr ridică ValueError ca int() din Python; „-0,00” dă 0, nu -0. */
export function roAmountToBani(text) {
  let cleaned = pyStrip(text).replaceAll('.', '').replaceAll(',', '.');
  const negative = cleaned.startsWith('-');
  if (negative) cleaned = cleaned.slice(1);
  const dot = cleaned.indexOf('.');
  const whole = dot < 0 ? cleaned : cleaned.slice(0, dot);
  const frac = dot < 0 ? '' : cleaned.slice(dot + 1);
  const bani = checkedBani(pyInt(whole || '0') * 100 + fractionBani(frac));
  return negative && bani !== 0 ? -bani : bani;
}

/** Suma, dacă TOT textul este o sumă („105,99 Lei”); altfel null. */
export function parseFullAmount(text) {
  const match = RO_AMOUNT_FULL.match(pyStrip(text));
  return match ? roAmountToBani(match.group(1)) : null;
}

/** Prima sumă urmată de „Lei” (sau „RON”) găsită oriunde în text; altfel null. */
export function findAmount(text) {
  const match = RO_AMOUNT_ANY.search(text);
  return match ? roAmountToBani(match.group(1)) : null;
}

/** Ultima sumă urmată de „Lei” din text (ex. „Total: 190,47 Lei”); altfel null. */
export function findLastAmount(text) {
  const matches = RO_AMOUNT_ANY.finditer(text);
  return matches.length > 0 ? roAmountToBani(matches[matches.length - 1].group(1)) : null;
}

/**
 * Suma dintr-un mesaj de retur: „93.59”, „129”, „249.9” sau „1.449,27”. Paginile de retur scriu uneori punct ca separator zecimal;
 * un singur punct urmat de exact 3 cifre se citește ca separator de mii („1.449”). Text gol sau neînțeles: null.
 */
export function parseRefundAmount(text) {
  const value = pyStrip(text);
  if (!value) return null;
  if (value.includes(',')) return RO_AMOUNT_ONLY.fullmatch(value) ? roAmountToBani(value) : null;
  if (THOUSANDS_ONLY.fullmatch(value)) return checkedBani(pyInt(value.replaceAll('.', '')) * 100);
  if (DECIMAL_DOT.fullmatch(value)) {
    const dot = value.indexOf('.');
    const whole = dot < 0 ? value : value.slice(0, dot);
    const frac = dot < 0 ? '' : value.slice(dot + 1);
    return checkedBani(pyInt(whole) * 100 + fractionBani(frac));
  }
  return null;
}

/** Cifrele unui întreg grupate câte trei cu puncte („1449” devine „1.449”), ca f"{n:,}" cu virgula înlocuită. */
function groupThousands(whole) {
  return String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** Afișare românească: 144927 devine „1.449,27 Lei”, -3400 devine „-34,00 Lei”. */
export function formatLei(bani) {
  if (!Number.isSafeInteger(bani)) throw new TypeError(`formatLei: ${String(bani)} nu este un număr întreg de bani`);
  const [whole, frac] = pyDivmod(Math.abs(bani), 100);
  return `${bani < 0 ? '-' : ''}${groupThousands(whole)},${String(frac).padStart(2, '0')} Lei`;
}
