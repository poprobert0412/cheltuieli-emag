// Paritatea tabelelor Unicode și a lucrurilor care depind de ele: (1) src/calcul/unicode_tables.js comis e identic cu ce ar scrie scriptul din fixtura Python de acum (prospețime);
// (2) NFKD din motorul JS dă pe fiecare punct de cod ce dă Python; (3) casefold, semnele combinate, spațiile, \w \d \s (prin PyPattern) și cifrele din int() coincid cu Python pe TOT intervalul.
// Dacă ICU-ul din Node e mai nou decât Unicode-ul din Python, punctele de cod apărute între versiuni sunt numite în diagnostic; diferențele pe puncte de cod cunoscute de ambele pică testul.
// Ce NU face: nu testează logica modulelor care folosesc tabelele (primitive.test.js).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { TABLES_FILE, renderTables } from '../../scripts/scrie_tabele_unicode.mjs';
import { UNIDATA_VERSION } from '../../src/calcul/unicode_tables.js';
import { isCombining, isPySpace, pyCasefold, pyInt, pyRepr } from '../../src/calcul/python_compat.js';
import { PyPattern } from '../../src/calcul/python_regex.js';
import { normalizeText } from '../../src/calcul/text_normalize.js';
import { loadFixture } from '../fixturi.js';

const unicode = loadFixture('unicode');
const MAX_CODE_POINT = 0x10ffff;
const SURROGATES_START = 0xd800;
const SURROGATES_END = 0xdfff;
// Câte puncte de cod arătăm într-un mesaj de eroare (restul se numără): destul cât să se vadă tiparul.
const MAX_SHOWN = 15;

/** Punctul de cod scris ca U+00E9, pentru mesajele de eroare. */
const hex = (code) => `U+${code.toString(16).toUpperCase().padStart(4, '0')}`;
/** True pentru jumătățile de surogat: ele nu sunt caractere și nu au rost în textul comparat cu Python. */
const isSurrogate = (code) => code >= SURROGATES_START && code <= SURROGATES_END;

/** True dacă `code` cade într-unul dintre intervalele [de la, până la] din fixtura Python. */
function inRanges(ranges, code) {
  return ranges.some(([from, to]) => code >= from && code <= to);
}

/** Pică testul dacă lista de diferențe nu e goală, numind câteva dintre ele (restul se numără). */
function expectNoDifferences(differences, label) {
  const shown = differences.slice(0, MAX_SHOWN).join('; ');
  assert.equal(differences.length, 0, `${label}: ${differences.length} diferențe, de exemplu ${shown}`);
}

describe('tabelele generate', () => {
  test('unicode_tables.js comis e identic cu ce ar scrie scriptul acum din fixtura Python (prospețime)', () => {
    const committed = readFileSync(TABLES_FILE, 'utf8');
    assert.ok(committed === renderTables(unicode),
      `unicode_tables.js nu corespunde fixturii (Python cu Unicode ${unicode.unidata_version}); regenerează cu npm run tabele:unicode (cu Python-ul proiectului, 3.13)`);
    assert.equal(UNIDATA_VERSION, unicode.unidata_version);
  });
});

describe('NFKD: String.prototype.normalize din JS față de unicodedata.normalize din Python', () => {
  test('pe fiecare punct de cod cunoscut de Python (atribuit în versiunea lui Unicode), rezultatul e identic', (t) => {
    const expected = new Map(unicode.nfkd.map(([code, folded]) => [code, String.fromCodePoint(...folded)]));
    const differences = [];
    const newer = [];
    for (let code = 0; code <= MAX_CODE_POINT; code += 1) {
      if (isSurrogate(code)) continue;
      const char = String.fromCodePoint(code);
      const want = expected.get(code) ?? char;
      const got = char.normalize('NFKD');
      if (got === want) continue;
      if (inRanges(unicode.assigned, code)) differences.push(`${hex(code)} -> JS ${JSON.stringify(got)}, Python ${JSON.stringify(want)}`);
      else newer.push(code);
    }
    t.diagnostic(`Unicode în Python (unicodedata): ${unicode.unidata_version}; în Node (process.versions.unicode): ${process.versions.unicode}`);
    if (newer.length > 0) {
      t.diagnostic(`${newer.length} puncte de cod apărute după Unicode ${unicode.unidata_version} au descompunere în JS și sunt necunoscute lui Python: ${newer.slice(0, MAX_SHOWN).map(hex).join(', ')}${newer.length > MAX_SHOWN ? ', ...' : ''}`);
    }
    expectNoDifferences(differences, 'NFKD pe puncte de cod cunoscute de ambele');
  });
});

describe('normalize_text nu depinde de Unicode-ul motorului JS', () => {
  test('un punct de cod neatribuit în Unicode-ul lui Python rămâne neschimbat și desparte textul, chiar dacă motorul JS îl descompune', (t) => {
    // Punctele de cod apărute în Unicode după versiunea lui Python (în Node 17, în Python 3.13 doar 15.1) au descompunere în JS, dar Python le lasă cum sunt: ele nu au majuscule,
    // semne combinate sau descompuneri (generatorul verifică regula pe tot intervalul), deci normalize_text trebuie să le păstreze, iar semnele combinate de după ele să se scoată ca în Python.
    const skewed = [];
    for (let code = 0; code <= MAX_CODE_POINT; code += 1) {
      if (isSurrogate(code) || inRanges(unicode.assigned, code)) continue;
      const char = String.fromCodePoint(code);
      if (char.normalize('NFKD') !== char) skewed.push(code);
    }
    t.diagnostic(`${skewed.length} puncte de cod neatribuite în Python (Unicode ${unicode.unidata_version}), dar descompuse de motorul JS (Unicode ${process.versions.unicode})`);
    for (const code of [...skewed, 0x378, 0xfffe, 0x10fffe, 0x10ffff]) {
      const char = String.fromCodePoint(code);
      assert.equal(normalizeText(char), char, `${hex(code)} neatribuit trebuie să rămână neschimbat`);
      assert.equal(normalizeText(`x${char}y`), `x${char}y`, `${hex(code)} între litere`);
      assert.equal(normalizeText(`A${char}\u{301}E\u{301}`), `a${char}e`, `${hex(code)}: semnele combinate de după el se scot, ca în Python (a, ${hex(code)}, e)`);
    }
  });
});

describe('casefold, semne combinate, spații', () => {
  test('pyCasefold(chr) = chr.casefold() pe tot intervalul', () => {
    const expected = new Map(unicode.casefold.map(([code, folded]) => [code, String.fromCodePoint(...folded)]));
    const differences = [];
    for (let code = 0; code <= MAX_CODE_POINT; code += 1) {
      if (isSurrogate(code)) continue;
      const char = String.fromCodePoint(code);
      const want = expected.get(code) ?? char;
      if (pyCasefold(char) !== want) differences.push(`${hex(code)} -> ${JSON.stringify(pyCasefold(char))}, Python ${JSON.stringify(want)}`);
    }
    expectNoDifferences(differences, 'casefold');
  });
  test('isCombining(cp) = (unicodedata.combining(chr) != 0) pe tot intervalul', () => {
    const differences = [];
    for (let code = 0; code <= MAX_CODE_POINT; code += 1) {
      if (isCombining(code) !== inRanges(unicode.combining, code)) differences.push(hex(code));
    }
    expectNoDifferences(differences, 'combining');
  });
  test('isPySpace(cp) = chr.isspace() pe tot intervalul', () => {
    const spaces = new Set(unicode.space);
    const differences = [];
    for (let code = 0; code <= MAX_CODE_POINT; code += 1) {
      if (isPySpace(code) !== spaces.has(code)) differences.push(hex(code));
    }
    expectNoDifferences(differences, 'space');
  });
});

describe('\\w, \\d, \\s prin PyPattern, față de re din Python, punct de cod cu punct de cod', () => {
  const surrogateFree = [];
  for (let code = 0; code <= MAX_CODE_POINT; code += 1) if (!isSurrogate(code)) surrogateFree.push(code);
  const everything = surrogateFree.map((code) => String.fromCodePoint(code)).join(''); // fără spread: 1,1 milioane de argumente ar depăși limita apelului

  for (const [source, negatedSource, ranges] of [['\\w', '\\W', unicode.word], ['\\d', '\\D', unicode.digit], ['\\s', '\\S', null]]) {
    test(`${source} și ${negatedSource}`, () => {
      const inClass = ranges ? (code) => inRanges(ranges, code) : (code) => unicode.space.includes(code);
      const matched = new PyPattern(source).findall(everything).map((char) => char.codePointAt(0));
      const matchedNegated = new PyPattern(negatedSource).findall(everything).map((char) => char.codePointAt(0));
      const expected = surrogateFree.filter(inClass);
      const expectedNegated = surrogateFree.filter((code) => !inClass(code));
      assert.equal(matched.length, expected.length, `${source}: număr diferit de puncte de cod`);
      assert.deepEqual(matched, expected, `${source}: aceleași puncte de cod`);
      assert.deepEqual(matchedNegated, expectedNegated, `${negatedSource}: aceleași puncte de cod`);
    });
  }
  test('surogatele singure sunt non-cuvânt, non-cifră, non-spațiu (\\W \\D \\S le potrivesc)', () => {
    for (const code of [SURROGATES_START, 0xdbff, 0xdc00, SURROGATES_END]) {
      const char = String.fromCharCode(code);
      assert.equal(new PyPattern('\\W').search(char) !== null, true, hex(code));
      assert.equal(new PyPattern('\\w').search(char), null, hex(code));
      assert.equal(new PyPattern('\\D').search(char) !== null, true, hex(code));
      assert.equal(new PyPattern('\\S').search(char) !== null, true, hex(code));
    }
  });
});

describe('int() și repr()', () => {
  test('fiecare cifră zecimală Unicode (în blocuri de 10) se citește cu valoarea ei', () => {
    assert.ok(unicode.digit_zero.length >= 60);
    for (const zero of unicode.digit_zero) {
      for (let value = 0; value < 10; value += 1) {
        assert.equal(pyInt(String.fromCodePoint(zero + value)), value, `${hex(zero + value)}`);
      }
    }
  });
  test('repr(): caracterele tipăribile rămân ca atare, cele netipăribile se scriu cu \\x \\u \\U', () => {
    const differences = [];
    for (let code = 0x80; code <= MAX_CODE_POINT; code += 997) { // pas prim: acoperă puncte din toate blocurile fără să dureze
      const char = String.fromCodePoint(code);
      const printable = !inRanges(unicode.nonprintable, code);
      const text = pyRepr(char);
      if (printable !== (text === `'${char}'`)) differences.push(`${hex(code)} -> ${text}`);
    }
    expectNoDifferences(differences, 'repr');
    for (const [from, to] of unicode.nonprintable.slice(0, 40)) {
      assert.match(pyRepr(String.fromCodePoint(from)), /^'\\[xuU]/, hex(from));
      assert.match(pyRepr(String.fromCodePoint(to)), /^'\\[xuU]/, hex(to));
    }
  });
});
