// Încărcătorul fixturilor de paritate, folosit de toate testele din tests/paritate/ (fixturile le scrie tests/paritate_export.py în extensie/build/paritate/).
// Primește: numele fixturii (setari, unicode, primitive, regex, regex_aleatoare, difflib, html, parsere, analiza). Dă înapoi: obiectul citit din JSON, validat pe schemă.
// Oferă și mici unelte de comparare: `attempt` (rezultatul sau eroarea unei funcții, în forma din fixturi), `same` (egalitate exactă, cu zero cu semn) și `sameError`.
// Ce NU face: nu generează fixturile (npm run paritate:genereaza) și nu ghicește nimic dacă lipsesc: spune ce să rulezi.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const FIXTURES_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'build', 'paritate');
// Forma fișierelor scrise de generator; un număr diferit înseamnă că generatorul și testele s-au desincronizat.
export const FIXTURE_SCHEMA = 1;

const cache = new Map();

/** Fixtura `name` (parsată o singură dată pe proces); ridică eroare cu instrucțiunea de generare dacă fișierul lipsește sau are altă schemă. */
export function loadFixture(name) {
  if (!cache.has(name)) {
    const file = path.join(FIXTURES_DIR, `${name}.json`);
    let text;
    try {
      text = readFileSync(file, 'utf8');
    } catch (error) {
      throw new Error(`Lipsește fixtura ${file}: rulează întâi npm run paritate:genereaza (${error.message})`);
    }
    const data = JSON.parse(text);
    if (data.schema !== FIXTURE_SCHEMA) throw new Error(`${file} are schema ${data.schema}, testele așteaptă ${FIXTURE_SCHEMA}: regenerează fixturile`);
    cache.set(name, data);
  }
  return cache.get(name);
}

/** `format_missing_paid_total` devine `formatMissingPaidTotal`: numele funcțiilor portate sunt numele Python în camelCase. */
export function snakeToCamel(name) {
  return name.replace(/_([a-z0-9])/g, (_, letter) => letter.toUpperCase());
}

/** Rulează `fn`: { out } cu rezultatul sau { error: { type, message } } cu eroarea ridicată, ca în fixturile Python. */
export function attempt(fn) {
  try {
    return { out: fn() };
  } catch (error) {
    return { error: { type: error?.name ?? 'Error', message: error?.message ?? String(error) } };
  }
}

/** Egalitate exactă (inclusiv -0 față de 0 și ordinea elementelor din liste); `describe()` se apelează doar la eșec, ca să spună intrarea. */
export function same(actual, expected, describe) {
  try {
    assert.deepStrictEqual(actual, expected);
  } catch (error) {
    error.message = `${describe()}\n${error.message}`;
    throw error;
  }
}

// Ce clase de eroare JS acceptăm pentru fiecare tip de eroare Python (mesajul trebuie oricum să fie identic).
const ERROR_TYPES = {
  ValueError: ['ValueError', 'RangeError', 'Error'],
  TypeError: ['TypeError'],
  KeyError: ['KeyError'],
  OverflowError: ['OverflowError', 'RangeError'],
  ZeroDivisionError: ['RangeError'],
  PatternError: ['PatternSyntaxError'],
  error: ['PatternSyntaxError'],
};

/** Verifică că `got` (rezultatul lui attempt) este eroarea `expected` din fixtură: mesaj identic, iar tipul din lista admisă pentru tipul Python. */
export function sameError(got, expected, describe) {
  same(got.error?.message, expected.message, () => `${describe()}\n(se aștepta eroarea ${expected.type}: ${expected.message}; s-a primit ${JSON.stringify(got)})`);
  const allowed = ERROR_TYPES[expected.type];
  if (allowed) {
    same(allowed.includes(got.error.type), true, () => `${describe()}\ntip de eroare ${got.error.type}, admis pentru ${expected.type}: ${allowed.join(', ')}`);
  }
}

/** Compară rezultatul lui attempt cu intrarea din fixtură (care are `out` sau `error`). */
export function sameOutcome(got, expected, describe) {
  if (expected.error) {
    sameError(got, expected.error, describe);
  } else {
    same(got, { out: expected.out }, describe);
  }
}
