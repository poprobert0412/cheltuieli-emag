// Șabloanele str.format din Python: analiza lor (string.Formatter().parse) și completarea câmpurilor simple (str.format cu argumente cu nume), cu aceleași erori ca în CPython.
// Primește: un șablon text și, la completare, un obiect cu valorile câmpurilor (text sau întreg). Dă înapoi: tupluri [text, nume câmp, specificator, conversie] sau textul completat.
// De ce: config/avertismente.json are șabloane Python (`{seller}`, `{{`), validate la încărcare cu mesajele Python; portul urmează MarkupIterator_next și parse_field din CPython 3.13 (Objects/stringlib/unicode_format.h).
// Ce NU face: nu evaluează specificatori (`{x:>5}`), conversii (`{x!r}`), atribute (`{x.real}`) sau indexuri (`{x[0]}`): la completare le refuză cu o eroare clară (extensia nu are nevoie de ele).
import { PyValueError, pyRepr, pyInt } from './python_compat.js';
import { PyKeyError } from './models.js';
import { PyIndexError } from './python_regex.js';

// Cea mai mare valoare a lui Py_ssize_t pe 64 de biți: un index de câmp mai mare dă „Too many decimal digits in format string”.
const PY_SSIZE_T_MAX = 2n ** 63n - 1n;
const DECIMAL_DIGITS = /^\p{Nd}+$/u;

/** Câmpul care începe după `{`: numele (până la `}`, `:` sau `!`), conversia și specificatorul; întoarce [nume, specificator, conversie, poziția de după `}`]. Port al lui parse_field. */
function parseField(chars, start) {
  let position = start;
  let c = '';
  while (position < chars.length) {
    c = chars[position];
    position += 1;
    if (c === '{') throw new PyValueError("unexpected '{' in field name");
    if (c === '[') {
      while (position < chars.length && chars[position] !== ']') position += 1; // se oprește la ']' fără să-l consume
      continue;
    }
    if (c === '}' || c === ':' || c === '!') break;
  }
  const name = chars.slice(start, position - 1).join('');
  let conversion = null;
  if (c === '!' || c === ':') {
    if (c === '!') {
      if (position >= chars.length) throw new PyValueError('end of string while looking for conversion specifier');
      conversion = chars[position];
      position += 1;
      if (position < chars.length) {
        c = chars[position];
        position += 1;
        if (c === '}') return [name, '', conversion, position];
        if (c !== ':') throw new PyValueError("expected ':' after conversion specifier");
      }
    }
    const specStart = position;
    let depth = 1;
    while (position < chars.length) {
      c = chars[position];
      position += 1;
      if (c === '{') {
        depth += 1;
      } else if (c === '}') {
        depth -= 1;
        if (depth === 0) return [name, chars.slice(specStart, position - 1).join(''), conversion, position];
      }
    }
    throw new PyValueError("unmatched '{' in format spec");
  }
  if (c !== '}') throw new PyValueError("expected '}' before end of string");
  return [name, '', conversion, position];
}

/**
 * string.Formatter().parse(template): tupluri [text literal, nume câmp, specificator, conversie]. Fără câmp: [text, null, null, null]; câmp fără specificator: specificatorul e '' și
 * conversia null. Generator, ca în CPython: o eroare apare când parcurgerea ajunge la ea (list(...) o prinde pe prima, str.format poate da altă eroare înaintea ei).
 */
export function* formatterParse(template) {
  const chars = Array.from(template);
  let position = 0;
  while (position < chars.length) {
    const start = position;
    let c = '';
    let markupFollows = false;
    while (position < chars.length) {
      c = chars[position];
      position += 1;
      if (c === '{' || c === '}') {
        markupFollows = true;
        break;
      }
    }
    const atEnd = position >= chars.length;
    let length = position - start;
    if (c === '}' && (atEnd || chars[position] !== c)) throw new PyValueError("Single '}' encountered in format string");
    if (atEnd && c === '{') throw new PyValueError("Single '{' encountered in format string");
    if (!atEnd) {
      if (chars[position] === c) { // acoladă dublată: un singur caracter literal, fără câmp după el
        position += 1;
        markupFollows = false;
      } else {
        length -= 1;
      }
    }
    const literal = chars.slice(start, start + length).join('');
    if (!markupFollows) {
      yield [literal, null, null, null];
      continue;
    }
    const [name, spec, conversion, after] = parseField(chars, position);
    position = after;
    yield [literal, name, spec, conversion];
  }
}

/** Valoarea întreagă a numelui de câmp dacă e format doar din cifre zecimale Unicode, null dacă nu (get_integer din CPython); prea multe cifre: ValueError. */
function fieldIndex(first) {
  if (first === '' || !DECIMAL_DIGITS.test(first)) return null;
  let value = 0n;
  for (const digit of first) {
    value = value * 10n + BigInt(pyInt(digit));
    if (value > PY_SSIZE_T_MAX) throw new PyValueError('Too many decimal digits in format string');
  }
  return value;
}

/**
 * str.format(**values) pentru șabloane cu câmpuri simple `{nume}` și acolade dublate: aceleași erori ca în Python (ValueError la sintaxă, KeyError la un nume lipsă, IndexError la un câmp
 * gol sau numeric, fiindcă nu există argumente poziționale). Valorile text sau întregi se scriu cu str(). Specificator, conversie, atribut sau index: Error (neacceptat).
 */
export function pyFormat(template, values) {
  let out = '';
  for (const [literal, name, spec, conversion] of formatterParse(template)) {
    out += literal;
    if (name === null) continue;
    const firstEnd = name.search(/[.[]/);
    const first = firstEnd === -1 ? name : name.slice(0, firstEnd);
    const index = fieldIndex(first);
    if (first === '') throw new PyIndexError('Replacement index 0 out of range for positional args tuple');
    if (index !== null) throw new PyIndexError(`Replacement index ${index} out of range for positional args tuple`);
    if (!Object.hasOwn(values, first)) throw new PyKeyError(first);
    if (firstEnd !== -1 || spec !== '' || conversion !== null) {
      throw new Error(`formatare neacceptată în extensie: câmpul ${pyRepr(name)} are atribut, index, specificator sau conversie`);
    }
    out += String(values[first]);
  }
  return out;
}
