// Stratul de compatibilitate cu Python: funcții care fac JavaScript-ul să dea EXACT ce dă Python în capcanele din specificație (§6).
// Primește: numere, texte, liste și chei de sortare. Dă înapoi: aceleași rezultate ca round(), //, %, sorted/max/min cu key=, str.strip/split,
// int(), json.dumps, csv.writer, repr, str.casefold și clasele \s \d \w \b din re. Tabelele Unicode vin generate din Python (unicode_tables.js).
// Regula de port: orice // % round, comparare sau sortare de text și orice strip/split din Python trec prin funcțiile de aici, niciodată prin operatorul JS.
// Ce NU face: nu știe de comenzi, sume sau pagini. Întregii sunt numere sigure (Number.isSafeInteger); peste 2^53 funcțiile refuză, nu rotunjesc în tăcere.
// Un float Python cu valoare întreagă (5.0) se scrie la json, repr și csv ca atare doar dacă e învelit în PyFloat; JS nu face diferența între 5 și 5.0.
import {
  ASSIGNED_RANGES, CASEFOLD_FULL, CASEFOLD_SIMPLE_RUNS, COMBINING_RANGES, DIGIT_RANGES, DIGIT_ZEROS, NONPRINTABLE_RANGES, SPACE_RANGES, WORD_RANGES,
} from './unicode_tables.js';

/** ValueError din Python (mesajele lui sunt parte din ieșirea de comparat). */
export class PyValueError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ValueError';
  }
}

/** OverflowError din Python: rezultatul nu încape într-un double. */
export class PyOverflowError extends RangeError {
  constructor(message) {
    super(message);
    this.name = 'OverflowError';
  }
}

// round(x, n) din CPython: pentru n peste 323 numărul rămâne neschimbat, pentru n sub -308 devine 0.0 cu semnul lui (float.__round__).
const NDIGITS_MAX = 323;
const NDIGITS_MIN = -308;
// Cel mai mare punct de cod Unicode: complementele claselor se calculează până aici.
const MAX_CODE_POINT = 0x10ffff;
// Câte spații adaugă json.dumps(indent=1) pe nivel de imbricare: același aspect ca fișierele scrise de run_store.py.
const DEFAULT_JSON_INDENT = 1;

/**
 * -0 devine 0: întregii din Python nu au zero cu semn, dar negarea, înmulțirea și împărțirea din JS pot produce -0 (`-x`, `0 * -3`, `Math.round(-0.4)`).
 * De pus pe orice ÎNTREG rezultat din asemenea operații; pe un float nu, fiindcă Python păstrează -0.0.
 */
export function withoutNegativeZero(value) {
  return value === 0 ? 0 : value;
}

/** RangeError dacă `value` nu e un întreg sigur (între -2^53 și 2^53): peste această limită JavaScript rotunjește în tăcere. */
function assertSafeInteger(value, label) {
  if (!Number.isSafeInteger(value)) throw new RangeError(`${label}: ${String(value)} nu este un întreg sigur (între -2^53 și 2^53)`);
}

// ---------- căutare în intervale (tabelele sunt perechi aplatizate [de la, până la]) ----------

/** Căutare binară în intervale aplatizate [de la, până la], CRESCĂTOARE și fără suprapuneri: True dacă `code` cade într-unul. */
function inFlatRanges(flat, code) {
  let low = 0;
  let high = flat.length / 2 - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (code < flat[2 * middle]) high = middle - 1;
    else if (code > flat[2 * middle + 1]) low = middle + 1;
    else return true;
  }
  return false;
}

const SPACE_CODES = new Set();
for (let index = 0; index < SPACE_RANGES.length; index += 2) {
  for (let code = SPACE_RANGES[index]; code <= SPACE_RANGES[index + 1]; code += 1) SPACE_CODES.add(code);
}

/** True dacă punctul de cod e spațiu pentru Python (str.isspace, \s): include NEL, FS-US și U+3000; NU include U+FEFF și U+200B. */
export function isPySpace(code) {
  return SPACE_CODES.has(code);
}

/** True dacă unicodedata.combining(chr(code)) != 0 (semn combinat, scos de normalize_text după NFKD). */
export function isCombining(code) {
  return inFlatRanges(COMBINING_RANGES, code);
}

/** True dacă punctul de cod e atribuit în Unicode-ul lui Python (unicodedata.category != "Cn"); surogatele și uzul privat sunt atribuite, non-caracterele și golurile nu. */
export function isUnicodeAssigned(code) {
  return inFlatRanges(ASSIGNED_RANGES, code);
}

/** Valoarea cifrei zecimale (0-9) a punctului de cod, sau -1 dacă nu e cifră zecimală (unicodedata.decimal). */
function decimalValue(code) {
  let low = 0;
  let high = DIGIT_ZEROS.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (code < DIGIT_ZEROS[middle]) high = middle - 1;
    else if (code > DIGIT_ZEROS[middle] + 9) low = middle + 1;
    else return code - DIGIT_ZEROS[middle];
  }
  return -1;
}

// ---------- împărțire întreagă și rest ----------

/** a // b din Python pe întregi: rotunjire spre minus infinit, nu spre zero. RangeError la împărțire la zero sau la neîntregi. */
export function floorDiv(a, b) {
  assertSafeInteger(a, 'floorDiv');
  assertSafeInteger(b, 'floorDiv');
  if (b === 0) throw new RangeError('împărțire întreagă la zero');
  const remainder = a % b; // exact pentru întregi sigure, cu semnul lui a
  let quotient = (a - remainder) / b; // multiplu exact al lui b: câtul e exact
  if (remainder !== 0 && (remainder < 0) !== (b < 0)) quotient -= 1;
  return withoutNegativeZero(quotient);
}

/** a % b din Python pe întregi: restul are semnul împărțitorului. */
export function pyMod(a, b) {
  assertSafeInteger(a, 'pyMod');
  assertSafeInteger(b, 'pyMod');
  if (b === 0) throw new RangeError('rest la împărțire la zero');
  let remainder = a % b;
  if (remainder !== 0 && (remainder < 0) !== (b < 0)) remainder += b;
  return withoutNegativeZero(remainder);
}

/** divmod(a, b) din Python pe întregi: [a // b, a % b]. */
export function pyDivmod(a, b) {
  return [floorDiv(a, b), pyMod(a, b)];
}

/** a // b din Python pe BigInt (pentru produse care depășesc 2^53, de exemplu total * pondere). */
export function floorDivBig(a, b) {
  if (b === 0n) throw new RangeError('împărțire întreagă la zero');
  const quotient = a / b; // BigInt trunchiază spre zero
  return (a % b !== 0n) && ((a < 0n) !== (b < 0n)) ? quotient - 1n : quotient;
}

// ---------- rotunjire ----------

const DOUBLE_VIEW = new DataView(new ArrayBuffer(8));

/** x ca fracție exactă numărător / numitor (BigInt): valoarea binară a double-ului, fără nicio rotunjire. */
function exactRational(x) {
  DOUBLE_VIEW.setFloat64(0, x);
  const high = DOUBLE_VIEW.getUint32(0);
  const low = DOUBLE_VIEW.getUint32(4);
  const exponentField = (high >>> 20) & 0x7ff;
  const fraction = (BigInt(high & 0xfffff) << 32n) | BigInt(low);
  const mantissa = exponentField === 0 ? fraction : fraction | (1n << 52n); // subnormalele nu au bitul ascuns
  const exponent = (exponentField === 0 ? 1 : exponentField) - 1075;
  const signed = (high >>> 31) === 1 ? -mantissa : mantissa;
  return exponent >= 0 ? { numerator: signed << BigInt(exponent), denominator: 1n } : { numerator: signed, denominator: 1n << BigInt(-exponent) };
}

/**
 * round(x, n) din Python pe float: valoarea binară EXACTĂ a lui x, rotunjită la n zecimale cu jumătatea la par (12,25 -> 12,2; toFixed dă 12,3).
 * Păstrează zero cu semn (round(-0.4, 0) = -0.0) și ridică PyOverflowError dacă rezultatul nu încape într-un double.
 */
export function pyRound(x, ndigits = 0) {
  if (!Number.isInteger(ndigits)) throw new TypeError('ndigits trebuie să fie un întreg');
  if (!Number.isFinite(x)) return x;
  if (ndigits > NDIGITS_MAX) return x;
  if (ndigits < NDIGITS_MIN) return 0 * x; // 0.0 cu semnul lui x
  const { numerator, denominator } = exactRational(x);
  const scale = 10n ** BigInt(Math.abs(ndigits));
  const num = ndigits >= 0 ? numerator * scale : numerator;
  const den = ndigits >= 0 ? denominator : denominator * scale;
  let quotient = floorDivBig(num, den);
  const twiceRemainder = 2n * (num - quotient * den); // 0 <= rest < den
  if (twiceRemainder > den || (twiceRemainder === den && (quotient & 1n) === 1n)) quotient += 1n;
  const value = Number(ndigits >= 0 ? `${quotient}e-${ndigits}` : `${quotient}e${-ndigits}`);
  if (!Number.isFinite(value)) throw new PyOverflowError('rounded value too large to represent');
  return value === 0 && (x < 0 || Object.is(x, -0)) ? -0 : value;
}

/** round(x) din Python (fără ndigits): întreg, jumătatea la par (0,5 -> 0; 2,5 -> 2); niciodată -0. NaN și infinitul ridică eroare ca în Python. */
export function pyRoundInt(x) {
  if (Number.isNaN(x)) throw new PyValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(x)) throw new PyOverflowError('cannot convert float infinity to integer');
  return withoutNegativeZero(pyRound(x, 0));
}

// ---------- puncte de cod ----------

// FĂRĂ steagul u: așa clasa vede unitățile UTF-16, deci și jumătățile unui emoji (cu u, perechea ar fi un singur punct de cod și nu s-ar potrivi).
const SURROGATE = /[\ud800-\udfff]/;

/** Câte puncte de cod are textul (len() din Python): un emoji numără 1, nu 2. */
export function cpLength(text) {
  if (!SURROGATE.test(text)) return text.length;
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** text[start:end] din Python: felie în puncte de cod (indicii negativi ca în Python, `end` lipsă = până la capăt). */
export function cpSlice(text, start = 0, end = undefined) {
  if (!SURROGATE.test(text)) return text.slice(start, end);
  return Array.from(text).slice(start, end).join('');
}

/** Numele tipului Python al unei valori JS (int, float, str, bool, list, NoneType), pentru mesaje de eroare ca ale lui Python. */
function pythonTypeName(value) {
  if (value === null) return 'NoneType';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (typeof value === 'bigint') return 'int';
  return typeof value;
}

// ---------- comparare și sortare ----------

/** Ordinea textului din Python: pe puncte de cod (JS compară unități UTF-16 și greșește când U+E000-U+FFFF stă lângă emoji). Întoarce -1, 0 sau 1. */
export function compareCodePoints(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') {
    throw new TypeError(`'<' not supported between instances of '${pythonTypeName(a)}' and '${pythonTypeName(b)}'`);
  }
  if (!SURROGATE.test(a) && !SURROGATE.test(b)) return a < b ? -1 : (a > b ? 1 : 0);
  const left = a[Symbol.iterator]();
  const right = b[Symbol.iterator]();
  for (;;) {
    const x = left.next();
    const y = right.next();
    if (x.done || y.done) return x.done === y.done ? 0 : (x.done ? -1 : 1);
    const codeX = x.value.codePointAt(0);
    const codeY = y.value.codePointAt(0);
    if (codeX !== codeY) return codeX < codeY ? -1 : 1;
  }
}

/**
 * Compară două chei ca tuplurile Python: liste element cu element (cea mai scurtă e mai mică la prefix egal), numere și boolean după valoare,
 * text pe puncte de cod, null doar cu null. Tipuri amestecate ridică TypeError, dar numai dacă elementele anterioare au fost egale.
 */
export function compareKeys(left, right) {
  if (Array.isArray(left) && Array.isArray(right)) {
    const shared = Math.min(left.length, right.length);
    for (let index = 0; index < shared; index += 1) {
      const order = compareKeys(left[index], right[index]);
      if (order !== 0) return order;
    }
    return left.length < right.length ? -1 : (left.length > right.length ? 1 : 0);
  }
  const numeric = (value) => typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint';
  if (numeric(left) && numeric(right)) {
    if (Number.isNaN(left) || Number.isNaN(right)) throw new RangeError('NaN nu are loc într-o cheie de sortare');
    return left < right ? -1 : (left > right ? 1 : 0);
  }
  if (typeof left === 'string' && typeof right === 'string') return compareCodePoints(left, right);
  if (left === null && right === null) return 0;
  throw new TypeError(`'<' not supported between instances of '${pythonTypeName(left)}' and '${pythonTypeName(right)}'`);
}

/**
 * sorted(items, key=keyFn, reverse=reverse) din Python: stabil, cheia se calculează o dată pe element, `reverse` păstrează ordinea egalilor. Lista de intrare rămâne neschimbată.
 * Stabilitatea o dă Array.prototype.sort (garantată din ES2019); `reverse` inversează comparația, nu lista, tocmai ca egalii să rămână în ordinea de intrare.
 */
export function sortedBy(items, keyFn = (item) => item, { reverse = false } = {}) {
  const decorated = Array.from(items, (item) => ({ item, key: keyFn(item) }));
  decorated.sort((a, b) => (reverse ? compareKeys(b.key, a.key) : compareKeys(a.key, b.key)));
  return decorated.map((entry) => entry.item);
}

/** Primul element cu cheia cea mai mare (wantedOrder 1) sau cea mai mică (-1); listă goală: ValueError cu `emptyMessage`. */
function extremeBy(items, keyFn, wantedOrder, emptyMessage) {
  let best;
  let bestKey;
  let seen = false;
  for (const item of items) {
    const key = keyFn(item);
    if (!seen || compareKeys(key, bestKey) === wantedOrder) {
      best = item;
      bestKey = key;
      seen = true;
    }
  }
  if (!seen) throw new PyValueError(emptyMessage);
  return best;
}

/** max(items, key=keyFn) din Python: PRIMUL element maxim (la egalitate rămâne cel mai devreme). Listă goală: ValueError. */
export function maxBy(items, keyFn = (item) => item) {
  return extremeBy(items, keyFn, 1, 'max() iterable argument is empty');
}

/** min(items, key=keyFn) din Python: PRIMUL element minim. Listă goală: ValueError. */
export function minBy(items, keyFn = (item) => item) {
  return extremeBy(items, keyFn, -1, 'min() iterable argument is empty');
}

// ---------- strip, split, int ----------

/** Scoate de la capete spațiile Python (dacă `chars` lipsește) sau caracterele din `chars`, pe puncte de cod. */
function stripText(text, chars, fromLeft, fromRight) {
  const characters = Array.from(text);
  const stripSet = chars === undefined || chars === null ? null : new Set(Array.from(chars, (char) => char.codePointAt(0)));
  const stripped = (char) => (stripSet ? stripSet.has(char.codePointAt(0)) : isPySpace(char.codePointAt(0)));
  let start = 0;
  let end = characters.length;
  if (fromLeft) while (start < end && stripped(characters[start])) start += 1;
  if (fromRight) while (end > start && stripped(characters[end - 1])) end -= 1;
  return characters.slice(start, end).join('');
}

/** str.strip() din Python: fără `chars` scoate spațiile Unicode ale Python (nu și U+FEFF), cu `chars` scoate caracterele date (puncte de cod). */
export function pyStrip(text, chars) {
  return stripText(text, chars, true, true);
}

/** str.lstrip() din Python. */
export function pyLstrip(text, chars) {
  return stripText(text, chars, true, false);
}

/** str.rstrip() din Python. */
export function pyRstrip(text, chars) {
  return stripText(text, chars, false, true);
}

/** str.split() fără argument: desparte pe serii de spații Unicode din Python, fără șiruri goale. */
export function pySplit(text) {
  const parts = [];
  let current = '';
  for (const char of text) {
    if (isPySpace(char.codePointAt(0))) {
      if (current) parts.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  if (current) parts.push(current);
  return parts;
}

const ASCII_SPACES = new Set([0x20, 0x09, 0x0a, 0x0b, 0x0c, 0x0d]); // Py_ISSPACE din CPython (FS-US NU sunt aici)
const ASCII_DIGIT = /^[0-9]$/;

/**
 * int(text) din Python pe cifre zecimale (inclusiv din alte alfabete), cu semn, spații și underscore între cifre; altfel ValueError cu repr-ul textului.
 * Întregii peste 2^53 nu se pot reprezenta exact: RangeError, nu un număr greșit. Ca în CPython, spațiile Unicode contează doar de la U+0080 în sus.
 */
export function pyInt(text) {
  const invalid = () => new PyValueError(`invalid literal for int() with base 10: ${pyRepr(text)}`);
  let ascii = '';
  for (const char of text) {
    const code = char.codePointAt(0);
    if (code < 127) ascii += char;
    else if (isPySpace(code)) ascii += ' ';
    else if (decimalValue(code) >= 0) ascii += String(decimalValue(code));
    else throw invalid();
  }
  let index = 0;
  while (index < ascii.length && ASCII_SPACES.has(ascii.charCodeAt(index))) index += 1;
  let negative = false;
  if (ascii[index] === '+') index += 1;
  else if (ascii[index] === '-') {
    negative = true;
    index += 1;
  }
  let digits = '';
  let previous = '';
  while (index < ascii.length && (ASCII_DIGIT.test(ascii[index]) || ascii[index] === '_')) {
    if (ascii[index] === '_') {
      if (digits === '' || previous === '_') throw invalid(); // fără underscore la început sau dublu
    } else {
      digits += ascii[index];
    }
    previous = ascii[index];
    index += 1;
  }
  if (digits === '' || previous === '_') throw invalid(); // fără cifre sau cu underscore la sfârșit
  while (index < ascii.length && ASCII_SPACES.has(ascii.charCodeAt(index))) index += 1;
  if (index !== ascii.length) throw invalid();
  const value = BigInt(digits);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new RangeError(`int(${pyRepr(text)}) depășește 2^53 și nu se poate reprezenta exact în JavaScript`);
  return withoutNegativeZero(negative ? -Number(value) : Number(value));
}

// ---------- repr, json, csv ----------

/**
 * Un număr care în Python este float, chiar dacă are valoare întreagă (5.0, nu 5): pyJsonDumps, pyRepr și pyCsvRow îl scriu cu repr(float) ("5.0", "1e+16", "nan"),
 * nu ca întreg. JS nu face diferența între 5 și 5.0, deci apelantul învelește în PyFloat, doar la scriere, numerele care în Python sunt float (de exemplu procentul din round(x, 1)).
 * Nu intră în calcule și nu e cheie de sortare: valoarea e în `value`.
 */
export class PyFloat {
  constructor(value) {
    if (typeof value !== 'number') throw new TypeError(`PyFloat primește un număr, nu ${value === null ? 'null' : typeof value}`);
    this.value = value;
  }
}

/**
 * repr(float) din Python (cel mai scurt text care se citește înapoi la același număr, notație științifică sub 1e-4 și de la 1e16): 5 -> '5.0', 1e16 -> '1e+16'.
 * JS nu face diferența între 5 și 5.0, deci apelantul hotărăște când un număr întreg e float (funcția asta îl scrie mereu ca float; la json, repr și csv vezi PyFloat).
 */
export function pyFloatRepr(x) {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
  const sign = x < 0 ? '-' : '';
  const [mantissa, exponentText] = Math.abs(x).toExponential().split('e'); // cifrele cele mai scurte care se citesc înapoi la același double
  const digits = mantissa.replace('.', '');
  const decimalPoint = Number(exponentText) + 1; // poziția virgulei față de începutul cifrelor, ca decpt din CPython
  if (decimalPoint > 16 || decimalPoint <= -4) {
    const exponent = decimalPoint - 1;
    const body = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    return `${sign}${body}e${exponent < 0 ? '-' : '+'}${String(Math.abs(exponent)).padStart(2, '0')}`;
  }
  if (decimalPoint <= 0) return `${sign}0.${'0'.repeat(-decimalPoint)}${digits}`;
  if (decimalPoint >= digits.length) return `${sign}${digits}${'0'.repeat(decimalPoint - digits.length)}.0`;
  return `${sign}${digits.slice(0, decimalPoint)}.${digits.slice(decimalPoint)}`;
}

/** True pentru obiecte obișnuite (dicționare), fals pentru instanțe de clase, Date etc., care nu au formă JSON. */
function isPlainObject(value) {
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * json.dumps(value, ensure_ascii=False, indent=1) din Python, octet cu octet: [] și {} fără rând nou, "key": value, aceleași scăpări în text.
 * Opțiuni: indent (număr de spații, sau null = separatorii impliciți ", " și ": "), fractions (permite numere cu fracții, scrise ca repr(float); un float cu valoare
 * întreagă iese ca întreg, JS nu face diferența). Fără fractions, un număr care nu e întreg sigur ridică TypeError. Dicționarele cu chei din date sunt Map.
 */
export function pyJsonDumps(value, { indent = DEFAULT_JSON_INDENT, fractions = false } = {}) {
  const padding = (level) => (indent === null ? '' : ' '.repeat(indent * level));
  const itemSeparator = indent === null ? ', ' : ',';

  /** Un număr ca în json.dumps; refuză ce JSON-ul Python nu poate scrie exact (NaN, infinit, peste 2^53, fracții fără opțiunea fractions). */
  function dumpNumber(number) {
    if (!Number.isFinite(number)) throw new TypeError(`json: numărul ${String(number)} nu are formă JSON`);
    if (Object.is(number, -0)) {
      if (!fractions) throw new TypeError('json: zero negativ înseamnă float în Python; cere fractions: true');
      return '-0.0';
    }
    if (Number.isInteger(number)) {
      if (!Number.isSafeInteger(number)) throw new TypeError(`json: ${number} depășește 2^53 și nu se poate scrie exact`);
      return String(number);
    }
    if (!fractions) throw new TypeError(`json: ${number} are fracții; cere fractions: true`);
    return pyFloatRepr(number);
  }

  /** Un PyFloat ca în json.dumps: repr(float), iar NaN și infinitul ca NaN, Infinity, -Infinity (allow_nan e implicit în Python). */
  function dumpFloat(number) {
    if (Number.isNaN(number)) return 'NaN';
    if (number === Infinity) return 'Infinity';
    if (number === -Infinity) return '-Infinity';
    return pyFloatRepr(number);
  }

  /** Scrie recursiv un nod la nivelul de indentare `level`, cu separatorii lui json.dumps. */
  function dump(node, level) {
    if (node === null) return 'null';
    if (node === true) return 'true';
    if (node === false) return 'false';
    if (typeof node === 'string') return JSON.stringify(node);
    if (typeof node === 'number') return dumpNumber(node);
    if (node instanceof PyFloat) return dumpFloat(node.value);
    const inner = indent === null ? '' : `\n${padding(level + 1)}`;
    const closing = indent === null ? '' : `\n${padding(level)}`;
    const separator = `${itemSeparator}${indent === null ? '' : `\n${padding(level + 1)}`}`;
    if (Array.isArray(node)) {
      if (node.length === 0) return '[]';
      return `[${inner}${node.map((item) => dump(item, level + 1)).join(separator)}${closing}]`;
    }
    let entries;
    if (node instanceof Map) entries = [...node.entries()];
    else if (typeof node === 'object' && isPlainObject(node)) entries = Object.entries(node);
    else throw new TypeError(`json: ${typeof node} nu poate fi scris ca JSON`);
    if (entries.length === 0) return '{}';
    const rows = entries.map(([key, item]) => {
      if (typeof key !== 'string') throw new TypeError('json: cheile trebuie să fie text');
      return `${JSON.stringify(key)}: ${dump(item, level + 1)}`;
    });
    return `{${inner}${rows.join(separator)}${closing}}`;
  }

  return dump(value, 0);
}

/**
 * Un rând ca la csv.writer(delimiter=';'): ghilimele doar când câmpul are ;  "  CR sau LF (ghilimelele din interior se dublează), null = gol,
 * rând încheiat cu CRLF; un rând cu un singur câmp gol se scrie "". Numerele trebuie să fie întregi, booleanii ies ca True/False.
 */
export function pyCsvRow(fields) {
  const cells = fields.map((field) => {
    let text;
    if (field === null || field === undefined) text = '';
    else if (typeof field === 'string') text = field;
    else if (typeof field === 'boolean') text = field ? 'True' : 'False';
    else if (typeof field === 'number' && Number.isSafeInteger(field)) text = String(field);
    else if (field instanceof PyFloat) text = pyFloatRepr(field.value);
    else throw new TypeError(`csv: câmpul ${String(field)} nu e text, boolean, întreg sau PyFloat`);
    return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  });
  if (cells.length === 1 && cells[0] === '') cells[0] = '""';
  return `${cells.join(';')}\r\n`;
}

/** Scăparea Python pentru un caracter netipăribil: \xNN, \uNNNN sau \UNNNNNNNN, cu cifre hexazecimale mici. */
function hexEscape(code) {
  if (code <= 0xff) return `\\x${code.toString(16).padStart(2, '0')}`;
  if (code <= 0xffff) return `\\u${code.toString(16).padStart(4, '0')}`;
  return `\\U${code.toString(16).padStart(8, '0')}`;
}

/** repr() de text: ghilimelele alese ca în Python, scăpări pentru ce nu e tipăribil (tabela NONPRINTABLE_RANGES). */
function stringRepr(text) {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  let out = '';
  for (const char of text) {
    const code = char.codePointAt(0);
    if (char === quote || char === '\\') out += `\\${char}`;
    else if (char === '\t') out += '\\t';
    else if (char === '\n') out += '\\n';
    else if (char === '\r') out += '\\r';
    else if (code < 0x20 || code === 0x7f) out += hexEscape(code);
    else if (code < 0x7f) out += char;
    else if (inFlatRanges(NONPRINTABLE_RANGES, code)) out += hexEscape(code);
    else out += char;
  }
  return quote + out + quote;
}

/** repr() din Python pe text (ghilimele alese ca în Python, scăpări \x \u \U pentru ce nu e tipăribil), liste, dicționare (Map sau obiect), None, True/False, întregi și fracții. */
export function pyRepr(value) {
  if (value === null) return 'None';
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (typeof value === 'string') return stringRepr(value);
  if (typeof value === 'number') return Number.isInteger(value) && !Object.is(value, -0) ? String(value) : pyFloatRepr(value);
  if (typeof value === 'bigint') return String(value);
  if (value instanceof PyFloat) return pyFloatRepr(value.value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(', ')}]`;
  const entries = value instanceof Map ? [...value.entries()] : (value && typeof value === 'object' ? Object.entries(value) : null);
  if (entries) return `{${entries.map(([key, item]) => `${pyRepr(key)}: ${pyRepr(item)}`).join(', ')}}`;
  throw new TypeError(`repr: ${typeof value} nu are echivalent în Python`);
}

// ---------- casefold ----------

const CASEFOLD = new Map();
for (let index = 0; index < CASEFOLD_SIMPLE_RUNS.length; index += 3) {
  const [from, count, target] = CASEFOLD_SIMPLE_RUNS.slice(index, index + 3);
  for (let step = 0; step < count; step += 1) CASEFOLD.set(from + step, String.fromCodePoint(target + step));
}
for (const [code, ...folded] of CASEFOLD_FULL) CASEFOLD.set(code, String.fromCodePoint(...folded));

/** str.casefold() din Python: pliere per caracter, fără context (ß devine ss, Σ devine σ chiar la sfârșit de cuvânt), după tabela din Python. */
export function pyCasefold(text) {
  let out = '';
  for (const char of text) out += CASEFOLD.get(char.codePointAt(0)) ?? char;
  return out;
}

// ---------- clasele \s \d \w \W \b din re, ca surse pentru regex-uri JS cu steagul u ----------

/** Un punct de cod ca atare (litere și cifre) sau ca \u{cod}, pentru corpul unei clase regex. */
function classChar(code) {
  if ((code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a)) return String.fromCharCode(code);
  // litere și cifre de dincolo de ASCII merg ca atare (sursa rămâne scurtă); orice altceva, ca \u{cod}, ca să nu depindă de vreun caracter invizibil
  if (code >= 0x80 && inFlatRanges(WORD_RANGES, code)) return String.fromCodePoint(code);
  return `\\u{${code.toString(16)}}`;
}

/** Corpul unei clase regex (fără paranteze drepte) din intervale aplatizate [de la, până la], CRESCĂTOARE și fără suprapuneri; folosit și de python_regex.js. */
export function classBody(flat) {
  const parts = [];
  for (let index = 0; index < flat.length; index += 2) {
    parts.push(flat[index] === flat[index + 1] ? classChar(flat[index]) : `${classChar(flat[index])}-${classChar(flat[index + 1])}`);
  }
  return parts.join('');
}

/** Complementul intervalelor aplatizate pe tot Unicode-ul (0..10FFFF), tot aplatizat; folosit și de python_regex.js pentru \D \S \W. */
export function complementRanges(flat) {
  const out = [];
  let next = 0;
  for (let index = 0; index < flat.length; index += 2) {
    if (flat[index] > next) out.push(next, flat[index] - 1);
    next = flat[index + 1] + 1;
  }
  if (next <= MAX_CODE_POINT) out.push(next, MAX_CODE_POINT);
  return out;
}

/** Corpul clasei \s din Python (fără paranteze drepte): include NEL și FS-US, pe care \s din JS nu le are, și nu include U+FEFF, pe care \s din JS îl are. */
export const PY_SPACE = classBody(SPACE_RANGES);
/** Corpul clasei \d din Python: toate cifrele zecimale Unicode (categoria Nd). */
export const PY_DIGIT = classBody(DIGIT_RANGES);
/** Corpul clasei \w din Python: litere, cifre și alte caractere numerice (², ½), plus _. NU include semnele combinate. */
export const PY_WORD = classBody(WORD_RANGES);
/** Corpul clasei \W din Python: complementul lui PY_WORD pe tot intervalul Unicode, inclusiv surogatele. */
export const PY_NOT_WORD = classBody(complementRanges(WORD_RANGES));
/** Sursa lui \b din Python ca lookaround pe PY_WORD: trecerea între caracter de cuvânt și altceva (sau marginea textului). */
export const PY_BOUNDARY = `(?:(?<=[${PY_WORD}])(?![${PY_WORD}])|(?<![${PY_WORD}])(?=[${PY_WORD}]))`;
/** Sursa lui \B din Python 3.13: non-limită, dar nu pe textul gol (3.14 a schimbat asta); testul "text nevid" e (?<=[^])|(?=[^]). */
export const PY_NON_BOUNDARY = `(?:(?<=[^])|(?=[^]))(?:(?<=[${PY_WORD}])(?=[${PY_WORD}])|(?<![${PY_WORD}])(?![${PY_WORD}]))`;
