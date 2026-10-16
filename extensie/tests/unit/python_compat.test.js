// Teste unitare scrise de mână pentru extensie/src/calcul/python_compat.js: valoarea Python e notată în comentariu la fiecare caz.
// Verifică capcanele din specificație (rotunjirea jumătății la par, // și % pe negative, ordinea pe puncte de cod, strip/split, int(), json, csv, repr),
// cu zero cu semn (Object.is) și cu caractere de dincolo de BMP. Paritatea pe mii de cazuri generate de Python e în tests/paritate/primitive.test.js.
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  PY_BOUNDARY, PY_DIGIT, PY_NOT_WORD, PY_SPACE, PY_WORD, PyFloat, PyValueError, compareCodePoints, compareKeys, cpLength, cpSlice, floorDiv, floorDivBig, isPySpace,
  isUnicodeAssigned, maxBy, minBy, pyCasefold, pyCsvRow, pyDivmod, pyFloatRepr, pyInt, pyJsonDumps, pyLstrip, pyMod, pyRepr, pyRound, pyRoundInt, pyRstrip, pySplit, pyStrip, sortedBy,
  withoutNegativeZero,
} from '../../src/calcul/python_compat.js';

const NBSP = '\u{a0}';
const NEL = '\u{85}';
const GRIN = String.fromCodePoint(0x1f600);
const PRIVATE_USE = '\u{e000}';
const NONCHARACTER = '\u{ffff}';

describe('floorDiv, pyMod, pyDivmod: // și % din Python (podea, semnul împărțitorului)', () => {
  const cases = [
    // [a, b, a // b, a % b] în Python
    [7, 2, 3, 1], [-7, 2, -4, 1], [7, -2, -4, -1], [-7, -2, 3, -1], [0, 5, 0, 0], [0, -5, 0, 0], [6, 3, 2, 0], [-6, 3, -2, 0], [6, -3, -2, 0],
    [1, 7, 0, 1], [-1, 7, -1, 6], [1, -7, -1, -6], [-1, -7, 0, -1], [-3400, 100, -34, 0], [-99, 100, -1, 1],
    [9007199254740991, 2, 4503599627370495, 1], [-9007199254740991, 2, -4503599627370496, 1], [9007199254740991, 3, 3002399751580330, 1],
    [-9007199254740991, 9007199254740990, -2, 9007199254740989],
  ];
  for (const [a, b, quotient, remainder] of cases) {
    test(`${a} // ${b} = ${quotient} și ${a} % ${b} = ${remainder}`, () => {
      assert.equal(floorDiv(a, b), quotient);
      assert.equal(pyMod(a, b), remainder);
      assert.deepEqual(pyDivmod(a, b), [quotient, remainder]);
    });
  }
  test('rezultatul nu e niciodată zero negativ (în Python întregii nu au -0)', () => {
    assert.ok(Object.is(floorDiv(0, -5), 0));
    assert.ok(Object.is(pyMod(-6, 3), 0));
    assert.ok(Object.is(pyMod(0, -4), 0));
  });
  test('împărțirea la zero ridică RangeError, iar neîntregii sunt refuzați', () => {
    assert.throws(() => floorDiv(5, 0), RangeError);
    assert.throws(() => pyMod(5, 0), RangeError);
    assert.throws(() => floorDiv(5.5, 2), RangeError);
    assert.throws(() => floorDiv(2 ** 53, 2), RangeError);
  });
  test('floorDivBig: aceeași podea pe BigInt (// din Python pe numere mari)', () => {
    assert.equal(floorDivBig(-7n, 2n), -4n);
    assert.equal(floorDivBig(7n, -2n), -4n);
    assert.equal(floorDivBig(-6n, 3n), -2n);
    assert.equal(floorDivBig(10n ** 30n + 1n, 10n ** 15n), 10n ** 15n);
    assert.throws(() => floorDivBig(1n, 0n), RangeError);
  });
});

describe('withoutNegativeZero: întregii din Python nu au zero cu semn', () => {
  test('capcanele din JavaScript care dau -0 (negare, înmulțire, Math.round) sunt reale, iar helperul le curăță', () => {
    const zero = 0;
    const negative = -3;
    assert.ok(Object.is(-zero, -0), 'negarea lui 0 dă -0 în JavaScript (în Python, -0 este 0)');
    assert.ok(Object.is(zero * negative, -0), '0 * -3 dă -0 în JavaScript (în Python, 0)');
    assert.ok(Object.is(Math.round(-0.4), -0), 'Math.round(-0.4) dă -0 în JavaScript (în Python, round(-0.4) este 0)');
    for (const trap of [-zero, zero * negative, Math.round(-0.4), -0]) assert.ok(Object.is(withoutNegativeZero(trap), 0));
  });
  test('orice altă valoare rămâne neschimbată (negative, zecimale, NaN, infinit)', () => {
    for (const value of [0, 7, -5, 0.5, -0.25, Number.MAX_SAFE_INTEGER, -Number.MAX_SAFE_INTEGER, Infinity, -Infinity, Number.NaN]) {
      assert.ok(Object.is(withoutNegativeZero(value), value), String(value));
    }
  });
});

describe('pyRound: round(x, n) din Python (jumătatea la par, pe valoarea binară exactă)', () => {
  const cases = [
    // [x, n, round(x, n) în Python]; toFixed din JS ar da altfel la 12.25 (12.3) și 8.675
    [12.25, 1, 12.2], [12.35, 1, 12.3], [0.125, 2, 0.12], [2.675, 2, 2.67], [1.005, 2, 1.0], [8.675, 2, 8.68], [0.045, 2, 0.04], [1.45, 1, 1.4], [1.55, 1, 1.6],
    [-12.25, 1, -12.2], [1234.5678, -2, 1200.0], [1250.0, -2, 1200.0], [1350.0, -2, 1400.0], [-0.5, 0, -0.0], [0.5, 0, 0.0], [1.5, 0, 2.0], [2.5, 0, 2.0],
    [-1.5, 0, -2.0], [-0.4, 0, -0.0], [5e-324, 1, 0.0], [-5e-324, 1, -0.0], [1e22, 2, 1e22], [123456789.125, 2, 123456789.12], [0.30000000000000004, 1, 0.3],
    [4503599627370495.5, 0, 4503599627370496.0], [-2.5, 0, -2.0], [99.995, 2, 100.0], [0.995, 2, 0.99], [3.14159, 3, 3.142], [7, 1, 7],
  ];
  for (const [x, ndigits, expected] of cases) {
    test(`round(${x}, ${ndigits}) = ${expected} (cu semnul zeroului)`, () => {
      assert.equal(pyRound(x, ndigits), expected);
    });
  }
  test('ndigits implicit e 0; valorile nefinite se întorc neschimbate; ndigits extreme (323 / -309) ca în CPython', () => {
    assert.equal(pyRound(2.5), 2);
    assert.equal(pyRound(Infinity, 2), Infinity);
    assert.ok(Number.isNaN(pyRound(NaN, 2)));
    assert.equal(pyRound(1.7976931348623157e308, 400), 1.7976931348623157e308);
    assert.equal(pyRound(123.456, -400), 0);
    assert.ok(Object.is(pyRound(-123.456, -400), -0));
  });
  test('rezultatul care nu încape într-un double ridică eroare ca în Python (OverflowError)', () => {
    assert.throws(() => pyRound(1.7976931348623157e308, -308), { message: 'rounded value too large to represent' });
  });
  test('ndigits trebuie să fie întreg', () => {
    assert.throws(() => pyRound(1.5, 0.5), TypeError);
  });
});

describe('pyRoundInt: round(x) din Python (întreg, jumătatea la par)', () => {
  const cases = [
    // [x, round(x) în Python]
    [0.5, 0], [1.5, 2], [2.5, 2], [-0.5, 0], [-1.5, -2], [-2.5, -2], [0.4999999999999999, 0], [2.5000000000000004, 3], [12.0, 12], [4503599627370495.5, 4503599627370496],
    [1e22, 1e22], [499.99999999999994, 500], [0, 0],
  ];
  for (const [x, expected] of cases) {
    test(`round(${x}) = ${expected}`, () => {
      assert.equal(pyRoundInt(x), expected);
    });
  }
  test('niciodată -0 (întregul Python nu are semn la zero) și refuză nefinitele', () => {
    assert.ok(Object.is(pyRoundInt(-0.5), 0));
    assert.ok(Object.is(pyRoundInt(-0), 0));
    assert.throws(() => pyRoundInt(Infinity), /infinity/);
    assert.throws(() => pyRoundInt(NaN), /NaN/);
  });
});

describe('compareCodePoints: ordinea textului din Python (pe puncte de cod, nu pe unități UTF-16)', () => {
  test('cazuri simple', () => {
    assert.equal(compareCodePoints('a', 'b'), -1);
    assert.equal(compareCodePoints('b', 'a'), 1);
    assert.equal(compareCodePoints('ab', 'a'), 1);
    assert.equal(compareCodePoints('a', 'ab'), -1);
    assert.equal(compareCodePoints('', ''), 0);
    assert.equal(compareCodePoints('', 'a'), -1);
    assert.equal(compareCodePoints('Zebra', 'abc'), -1);
  });
  test('U+FFFF < U+10000 în Python, dar "\\uffff" > "\\ud800\\udc00" în JavaScript', () => {
    assert.ok(NONCHARACTER > '\u{10000}', 'presupunerea testului: operatorul < din JS compară unități UTF-16');
    assert.equal(compareCodePoints(NONCHARACTER, '\u{10000}'), -1);
    assert.equal(compareCodePoints('\u{10000}', NONCHARACTER), 1);
  });
  test('zona privată (U+E000) vine înaintea emoji-ului (U+1F600) în Python', () => {
    assert.equal(compareCodePoints(PRIVATE_USE, GRIN), -1);
    assert.equal(compareCodePoints('a' + GRIN, 'a' + PRIVATE_USE), 1);
  });
  test('refuză ce nu e text (Python ridică TypeError)', () => {
    assert.throws(() => compareCodePoints('a', 1), TypeError);
    assert.throws(() => compareCodePoints(null, 'a'), TypeError);
  });
});

describe('compareKeys: compararea cheilor-tuplu din sorted(..., key=)', () => {
  test('liste, numere, text, boolean; lista mai scurtă e mai mică', () => {
    assert.equal(compareKeys([1, 'a'], [1, 'b']), -1);
    assert.equal(compareKeys([2], [1, 'z']), 1);
    assert.equal(compareKeys([], [0]), -1);
    assert.equal(compareKeys([1, [2, 3]], [1, [2, 4]]), -1);
    assert.equal(compareKeys([true], [false]), 1);
    assert.equal(compareKeys([1], [true]), 0);
    assert.equal(compareKeys([0.5, 1], [0.5, 1]), 0);
    assert.equal(compareKeys('a', 'b'), -1);
    assert.equal(compareKeys(3, 2), 1);
  });
  test('textul se compară pe puncte de cod', () => {
    assert.equal(compareKeys([NONCHARACTER], ['\u{10000}']), -1);
  });
  test('tipuri amestecate: TypeError, ca în Python, dar numai dacă elementele diferă înainte', () => {
    assert.throws(() => compareKeys([1], ['a']), TypeError);
    assert.throws(() => compareKeys(['a'], [null]), TypeError);
    assert.throws(() => compareKeys([[1]], [1]), TypeError);
    assert.equal(compareKeys([null], [null]), 0);
    assert.equal(compareKeys([1, 'a'], [2, 5]), -1);
  });
});

describe('sortedBy, maxBy, minBy: sorted/max/min cu key=', () => {
  test('sorted e stabil, iar reverse=True păstrează ordinea egalilor', () => {
    const items = [['b', 1], ['a', 1], ['c', 0]];
    // Python: [['c', 0], ['b', 1], ['a', 1]] și, cu reverse=True, [['b', 1], ['a', 1], ['c', 0]]
    assert.deepEqual(sortedBy(items, (item) => item[1]), [['c', 0], ['b', 1], ['a', 1]]);
    assert.deepEqual(sortedBy(items, (item) => item[1], { reverse: true }), [['b', 1], ['a', 1], ['c', 0]]);
    assert.deepEqual(items, [['b', 1], ['a', 1], ['c', 0]], 'lista de intrare nu se schimbă');
  });
  test('fără funcție de cheie se sortează elementele; textul pe puncte de cod', () => {
    assert.deepEqual(sortedBy(['b', GRIN, PRIVATE_USE, 'a', 'B']), ['B', 'a', 'b', PRIVATE_USE, GRIN]);
    assert.deepEqual(sortedBy([3, 1, 2]), [1, 2, 3]);
  });
  test('cheia se calculează o singură dată pe element', () => {
    let calls = 0;
    sortedBy([3, 1, 2], (value) => { calls += 1; return value; });
    assert.equal(calls, 3);
  });
  test('chei-tuplu: (-valoare, nume)', () => {
    const rows = [{ name: 'b', n: 2 }, { name: 'a', n: 2 }, { name: 'c', n: 5 }];
    assert.deepEqual(sortedBy(rows, (row) => [-row.n, row.name]).map((row) => row.name), ['c', 'a', 'b']);
  });
  test('max(..., key=) întoarce primul maxim; min la fel; liste goale: ValueError', () => {
    const items = [['a', 1], ['b', 2], ['c', 2]];
    assert.deepEqual(maxBy(items, (item) => item[1]), ['b', 2]);
    assert.deepEqual(minBy([['x', 1], ['y', 1]], (item) => item[1]), ['x', 1]);
    assert.throws(() => maxBy([], (item) => item), { name: 'ValueError', message: 'max() iterable argument is empty' });
    assert.throws(() => minBy([], (item) => item), PyValueError);
  });
});

describe('pyStrip, pyLstrip, pyRstrip, pySplit: spațiile Unicode din Python, nu cele din JavaScript', () => {
  test('strip fără argument scoate NEL, separatorii de control FS-US și spațiile exotice', () => {
    assert.equal(pyStrip(NEL + ' x\u{1c}'), 'x'); // Python: 'x'
    assert.equal(pyStrip(' ' + NBSP + '\u{3000}x '), 'x');
    assert.equal(pyStrip('\u{2028}x\u{2029}'), 'x');
  });
  test('BOM (U+FEFF) și ZWSP (U+200B) NU sunt spații în Python, deși trim() din JS scoate BOM-ul', () => {
    assert.equal(pyStrip('\u{feff}x\u{feff}'), '\u{feff}x\u{feff}'); // Python: textul rămâne neschimbat, cu BOM-urile lui
    assert.equal(pyStrip('x\u{200b}'), 'x\u{200b}');
    assert.equal('\u{feff}x'.trim(), 'x', 'presupunerea testului: trim() din JS scoate BOM-ul');
  });
  test('cu argument: caractere întregi (și de dincolo de BMP)', () => {
    assert.equal(pyStrip(' ,a, ', ' ,'), 'a');
    assert.equal(pyRstrip('a, ,', ' ,'), 'a');
    assert.equal(pyLstrip(',, a', ' ,'), 'a');
    assert.equal(pyStrip(GRIN + 'a' + GRIN, GRIN), 'a');
    assert.equal(pyStrip('xx', ''), 'xx');
    assert.equal(pyStrip('', ' '), '');
  });
  test('split fără argument: serii de spații, fără șiruri goale', () => {
    assert.deepEqual(pySplit('a  b\tc' + NBSP + 'd'), ['a', 'b', 'c', 'd']);
    assert.deepEqual(pySplit(''), []);
    assert.deepEqual(pySplit('   '), []);
    assert.deepEqual(pySplit('\u{200b}'), ['\u{200b}']);
    assert.deepEqual(pySplit(NEL + 'a' + NEL), ['a']);
  });
  test('isPySpace', () => {
    for (const code of [0x9, 0xa, 0xb, 0xc, 0xd, 0x1c, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]) {
      assert.ok(isPySpace(code), `U+${code.toString(16)}`);
    }
    for (const code of [0x0, 0x8, 0x21, 0x7f, 0x84, 0x86, 0xa1, 0x180e, 0x200b, 0x200c, 0x200d, 0x2060, 0xfeff, 0x3001]) {
      assert.ok(!isPySpace(code), `U+${code.toString(16)}`);
    }
  });
});

describe('cpLength, cpSlice: lungime și felii în puncte de cod, ca în Python', () => {
  test('emoji-ul numără ca un singur caracter', () => {
    assert.equal(cpLength('a' + GRIN + 'b'), 3);
    assert.equal(cpSlice('a' + GRIN + 'bc', 1, 3), GRIN + 'b');
    assert.equal(cpSlice('abc', 0, 2), 'ab');
    assert.equal(cpSlice('abc', 1), 'bc');
    assert.equal(cpSlice('', 0, 2), '');
    assert.equal(cpSlice('ab', 0, 5), 'ab');
  });
});

describe('pyInt: int(text) din Python', () => {
  test('cifre zecimale din alte alfabete, spații, semn, underscore între cifre', () => {
    assert.equal(pyInt('123'), 123);
    assert.equal(pyInt('007'), 7);
    assert.equal(pyInt(' 12 '), 12);
    assert.equal(pyInt('+5'), 5);
    assert.equal(pyInt('-7'), -7);
    assert.equal(pyInt('1_000'), 1000);
    assert.equal(pyInt('\u{661}\u{662}\u{663}'), 123); // Python: int('١٢٣') = 123
    assert.equal(pyInt(String.fromCodePoint(0x1d7cf, 0x1d7d0)), 12); // cifre matematice îngroșate
    assert.equal(pyInt('\u{ff19}\u{ff19}'), 99);
    assert.equal(pyInt(NBSP + '5' + NBSP), 5);
    assert.equal(pyInt('0'), 0);
    assert.ok(Object.is(pyInt('-0'), 0));
  });
  test('erorile au mesajul Python (ValueError cu repr-ul textului)', () => {
    for (const text of ['1__0', '_1', '1_', '- 7', '', ' ', 'abc', '1.5', '5\u{1c}', '\u{1c}5', '1e3', '0x10']) {
      assert.throws(() => pyInt(text), { name: 'ValueError', message: `invalid literal for int() with base 10: ${pyRepr(text)}` }, JSON.stringify(text));
    }
    assert.throws(() => pyInt('abc'), { message: "invalid literal for int() with base 10: 'abc'" });
  });
  test('FS-US nu sunt spații pentru int() (doar ASCII-ul obișnuit și spațiile >= U+007F), dar NEL e', () => {
    assert.equal(pyInt('5' + NEL), 5);
    assert.throws(() => pyInt('5\u{1c}'), PyValueError);
  });
  test('peste 2^53 nu se poate reprezenta exact: RangeError, nu un număr greșit', () => {
    assert.equal(pyInt('9007199254740991'), 9007199254740991);
    assert.equal(pyInt('-9007199254740991'), -9007199254740991);
    assert.throws(() => pyInt('9007199254740992'), RangeError);
    assert.throws(() => pyInt('99999999999999999999'), RangeError);
  });
});

describe('pyFloatRepr: repr(float) din Python', () => {
  const cases = [
    [0.1, '0.1'], [1e16, '1e+16'], [1e15, '1000000000000000.0'], [1.5e-5, '1.5e-05'], [0.0001, '0.0001'], [123456.789, '123456.789'], [-0, '-0.0'],
    [5e-324, '5e-324'], [1.7976931348623157e308, '1.7976931348623157e+308'], [12.2, '12.2'], [100, '100.0'], [1e22, '1e+22'], [1.2345678901234567e-5, '1.2345678901234568e-05'],
    [123456789012345680, '1.2345678901234568e+17'], [0.00012345, '0.00012345'], [0, '0.0'], [-3, '-3.0'], [2 ** 53, '9007199254740992.0'], [1e-5, '1e-05'], [-1e-7, '-1e-07'],
  ];
  for (const [x, expected] of cases) {
    test(`repr(${expected})`, () => {
      assert.equal(pyFloatRepr(x), expected);
    });
  }
  test('nefinitele: inf, -inf, nan', () => {
    assert.equal(pyFloatRepr(Infinity), 'inf');
    assert.equal(pyFloatRepr(-Infinity), '-inf');
    assert.equal(pyFloatRepr(NaN), 'nan');
  });
});

describe('pyJsonDumps: json.dumps(valoare, ensure_ascii=False, indent=1) octet cu octet', () => {
  test('obiecte, liste, goale, imbricate (Python afișează [] și {} fără rând nou)', () => {
    const value = { a: [1, 2], b: {}, c: [], d: 'a"b\\c\n\t\u{1}é' + GRIN };
    assert.equal(pyJsonDumps(value), '{\n "a": [\n  1,\n  2\n ],\n "b": {},\n "c": [],\n "d": "a\\"b\\\\c\\n\\t\\u0001é' + GRIN + '"\n}');
    assert.equal(pyJsonDumps([]), '[]');
    assert.equal(pyJsonDumps({}), '{}');
    assert.equal(pyJsonDumps(null), 'null');
    assert.equal(pyJsonDumps([true, false, null, 'x', -5]), '[\n true,\n false,\n null,\n "x",\n -5\n]');
  });
  test('indent: null = separatorii impliciți din Python (", " și ": ")', () => {
    assert.equal(pyJsonDumps({ a: [1, { b: null }], c: true }, { indent: null }), '{"a": [1, {"b": null}], "c": true}');
    assert.equal(pyJsonDumps([], { indent: null }), '[]');
  });
  test('Map păstrează ordinea inserării chiar și pentru chei ca "2024" (un obiect JS le-ar muta în față)', () => {
    const map = new Map([['necunoscut', 1], ['2024', 2]]);
    assert.equal(pyJsonDumps(map), '{\n "necunoscut": 1,\n "2024": 2\n}');
    assert.deepEqual(Object.keys({ necunoscut: 1, 2024: 2 }), ['2024', 'necunoscut'], 'presupunerea testului: obiectele JS reordonează cheile numerice');
  });
  test('numerele cu fracții sunt refuzate implicit (TypeError), nu scrise greșit', () => {
    assert.throws(() => pyJsonDumps([0.5]), TypeError);
    assert.throws(() => pyJsonDumps(-0), TypeError);
    assert.throws(() => pyJsonDumps(2 ** 53), TypeError);
    assert.throws(() => pyJsonDumps(NaN, { fractions: true }), TypeError);
    assert.throws(() => pyJsonDumps(Infinity, { fractions: true }), TypeError);
  });
  test('fractions: true scrie fracțiile ca repr(float) din Python', () => {
    assert.equal(pyJsonDumps([0.5, 12.2, 1e-5, -0, 3], { indent: null, fractions: true }), '[0.5, 12.2, 1e-05, -0.0, 3]'); // Python: [0.5, 12.2, 1e-05, -0.0, 3]
  });
  test('refuză ce nu e JSON: undefined, funcții, chei care nu sunt text', () => {
    assert.throws(() => pyJsonDumps(undefined), TypeError);
    assert.throws(() => pyJsonDumps({ a: () => 1 }), TypeError);
    assert.throws(() => pyJsonDumps(new Map([[1, 2]])), TypeError);
    assert.throws(() => pyJsonDumps(new Date()), TypeError);
  });
});

describe('pyCsvRow: un rând csv.writer(delimiter=";") cu CRLF', () => {
  test('ghilimele doar la ;  "  CR  LF; null = gol; numerele ca text; formulele nu se ating', () => {
    // Python: 'a;"b;c";"d""e";"f\ng"; h;;;5\r\n'
    assert.equal(pyCsvRow(['a', 'b;c', 'd"e', 'f\ng', ' h', '', null, 5]), 'a;"b;c";"d""e";"f\ng"; h;;;5\r\n');
    assert.equal(pyCsvRow(['=1+1']), '=1+1\r\n');
    assert.equal(pyCsvRow(['a\rb']), '"a\rb"\r\n');
    assert.equal(pyCsvRow([true, false]), 'True;False\r\n');
    assert.equal(pyCsvRow([-5, 0]), '-5;0\r\n');
  });
  test('un rând cu un singur câmp gol se scrie ""', () => {
    assert.equal(pyCsvRow(['']), '""\r\n');
    assert.equal(pyCsvRow(['', '']), ';\r\n');
  });
  test('numerele cu fracții sunt refuzate (în Python ar fi repr(float))', () => {
    assert.throws(() => pyCsvRow([0.5]), TypeError);
  });
});

describe('pyRepr: repr() din Python', () => {
  const cases = [
    ['abc', "'abc'"], ["it's", '"it\'s"'], ['say "hi"', "'say \"hi\"'"], ['it\'s "x"', "'it\\'s \"x\"'"], ['\n\t\\', "'\\n\\t\\\\'"], [NBSP, "'\\xa0'"], ['é' + GRIN, "'é" + GRIN + "'"],
    ['\u{200b}', "'\\u200b'"], ['\u{10ffff}', "'\\U0010ffff'"], ['\u{0}\u{7f}', "'\\x00\\x7f'"], ['\u{378}', "'\\u0378'"], ['', "''"],
  ];
  for (const [value, expected] of cases) {
    test(`repr(${expected})`, () => {
      assert.equal(pyRepr(value), expected);
    });
  }
  test('liste, None, bool, întregi, dict', () => {
    assert.equal(pyRepr(['a', "b'c"]), "['a', \"b'c\"]"); // Python: ['a', "b'c"]
    assert.equal(pyRepr([]), '[]');
    assert.equal(pyRepr(null), 'None');
    assert.equal(pyRepr(true), 'True');
    assert.equal(pyRepr(false), 'False');
    assert.equal(pyRepr(-5), '-5');
    assert.equal(pyRepr([null, true, 3]), '[None, True, 3]');
    assert.equal(pyRepr({ k: 'v' }), "{'k': 'v'}");
    assert.equal(pyRepr(new Map([['a', [1, 'b']]])), "{'a': [1, 'b']}");
    assert.equal(pyRepr(0.5), '0.5');
  });
  test('numere zecimale: exponentul cu două cifre, zero negativ, infinit și NaN ca în Python (nu ca String() din JavaScript)', () => {
    const cases = [
      [1e-7, '1e-07'], [1.5e-10, '1.5e-10'], [1e-5, '1e-05'], [0.0001, '0.0001'], [0.1 + 0.2, '0.30000000000000004'], [123456789.125, '123456789.125'], [2.5, '2.5'],
      [1e22, '1e+22'], [-0, '-0.0'], [Infinity, 'inf'], [-Infinity, '-inf'], [Number.NaN, 'nan'], [0, '0'], [7, '7'],
    ];
    for (const [value, expected] of cases) assert.equal(pyRepr(value), expected, `repr(${String(value)})`);
  });
  test('o surogat singur se scrie ca în Python', () => {
    assert.equal(pyRepr(String.fromCharCode(0xd800)), "'\\ud800'");
  });
  test('undefined și funcțiile nu au repr în Python', () => {
    assert.throws(() => pyRepr(undefined), TypeError);
  });
});

describe('PyFloat: un număr care în Python e float, chiar dacă are valoare întreagă (5.0, nu 5)', () => {
  test('json.dumps scrie floaturile cu repr(float), în liste și dicționare, cu și fără indentare', () => {
    const floats = [5, 0, -0, 12.5].map((value) => new PyFloat(value));
    assert.equal(pyJsonDumps(floats), '[\n 5.0,\n 0.0,\n -0.0,\n 12.5\n]'); // Python: json.dumps([5.0, 0.0, -0.0, 12.5], indent=1)
    assert.equal(pyJsonDumps({ pct: new PyFloat(5), n: 3 }, { indent: null }), '{"pct": 5.0, "n": 3}');
    assert.equal(pyJsonDumps({ pct: new PyFloat(5), n: 3, xs: [new PyFloat(1), new PyFloat(2.5)] }), '{\n "pct": 5.0,\n "n": 3,\n "xs": [\n  1.0,\n  2.5\n ]\n}');
  });
  test('NaN și infinitul se scriu ca în json.dumps (NaN, Infinity, -Infinity)', () => {
    assert.equal(pyJsonDumps(new PyFloat(Number.NaN)), 'NaN');
    assert.equal(pyJsonDumps(new PyFloat(Infinity)), 'Infinity');
    assert.equal(pyJsonDumps(new PyFloat(-Infinity)), '-Infinity');
    assert.equal(pyJsonDumps([new PyFloat(Number.NaN)]), '[\n NaN\n]');
  });
  test('repr și csv.writer folosesc tot repr(float)', () => {
    assert.equal(pyRepr([new PyFloat(5), new PyFloat(1e16), null]), '[5.0, 1e+16, None]');
    assert.equal(pyRepr({ k: new PyFloat(5) }), "{'k': 5.0}");
    assert.equal(pyCsvRow([new PyFloat(5), new PyFloat(12.5), new PyFloat(1e16), new PyFloat(Number.NaN), new PyFloat(-0), 'x', null]), '5.0;12.5;1e+16;nan;-0.0;x;\r\n');
  });
  test('un număr simplu rămâne int (5 -> 5), iar PyFloat nu primește altceva decât numere', () => {
    assert.equal(pyJsonDumps([5, new PyFloat(5)], { indent: null }), '[5, 5.0]');
    assert.throws(() => new PyFloat('5'), TypeError);
    assert.throws(() => new PyFloat(null), TypeError);
  });
});

describe('isUnicodeAssigned: punctele de cod atribuite în Unicode-ul lui Python (unicodedata.category != "Cn")', () => {
  test('litere, emoji, surogate, uz privat: atribuite; non-caractere, goluri și ce depășește U+10FFFF: neatribuite', () => {
    for (const code of [0x41, 0xe9, 0x219, 0x1f600, 0xd800, 0xdfff, 0xe000, 0x10fffd]) assert.equal(isUnicodeAssigned(code), true, `U+${code.toString(16)} e atribuit`);
    for (const code of [0x378, 0xfffe, 0xffff, 0x10fffe, 0x10ffff, 0xa7f1, 0x110000, -1]) assert.equal(isUnicodeAssigned(code), false, `U+${code.toString(16)} nu e atribuit`);
  });
});

describe('pyCasefold: str.casefold() din Python (per caracter, fără context)', () => {
  test('ß, ligaturi, sigma, i cu punct', () => {
    assert.equal(pyCasefold('Straße'), 'strasse');
    assert.equal(pyCasefold('\u{1e9e}'), 'ss');
    assert.equal(pyCasefold('\u{fb01}'), 'fi');
    assert.equal(pyCasefold('ΣΑΣ'), 'σασ'); // fără sigma finală (Python: 'σασ')
    assert.equal(pyCasefold('\u{130}'), 'i\u{307}');
    assert.equal(pyCasefold('ABC xyz'), 'abc xyz');
    assert.equal(pyCasefold(GRIN + 'A'), GRIN + 'a');
    assert.equal(pyCasefold(''), '');
  });
});

describe('PY_SPACE, PY_DIGIT, PY_WORD, PY_NOT_WORD, PY_BOUNDARY: clasele \\s \\d \\w \\W \\b din Python, pentru regex-uri JS cu steagul u', () => {
  const inClass = (body, char) => new RegExp(`^[${body}]$`, 'u').test(char);
  test('PY_SPACE', () => {
    for (const char of [' ', '\t', '\n', NEL, NBSP, '\u{1c}', '\u{3000}', '\u{2028}']) assert.ok(inClass(PY_SPACE, char), JSON.stringify(char));
    for (const char of ['a', '\u{feff}', '\u{200b}', '_', '1']) assert.ok(!inClass(PY_SPACE, char), JSON.stringify(char));
  });
  test('PY_DIGIT: cifrele zecimale din orice alfabet, nu și ²', () => {
    for (const char of ['0', '9', '\u{663}', '\u{968}', String.fromCodePoint(0x1d7cf), '\u{ff11}']) assert.ok(inClass(PY_DIGIT, char), JSON.stringify(char));
    for (const char of ['a', '\u{b2}', '\u{bd}', '\u{2460}', ' ']) assert.ok(!inClass(PY_DIGIT, char), JSON.stringify(char));
  });
  test('PY_WORD: litere, cifre, alte caractere numerice (², ½) și _; nu și semnele combinate', () => {
    for (const char of ['a', 'Z', '_', '5', 'é', 'ș', '\u{663}', '\u{b2}', '\u{bd}', '\u{4e2d}', 'ß', String.fromCodePoint(0x1d400)]) assert.ok(inClass(PY_WORD, char), JSON.stringify(char));
    for (const char of ['-', ' ', '.', '\u{301}', '\u{200b}', GRIN, '$']) assert.ok(!inClass(PY_WORD, char), JSON.stringify(char));
  });
  test('PY_NOT_WORD e complementul, inclusiv surogatele și zona de după U+10FFFF nu există', () => {
    for (const char of ['-', ' ', '.', '\u{301}', GRIN, '\u{d800}']) assert.ok(inClass(PY_NOT_WORD, char), JSON.stringify(char));
    for (const char of ['a', '_', '5', 'é']) assert.ok(!inClass(PY_NOT_WORD, char), JSON.stringify(char));
  });
  test('PY_BOUNDARY = \\b: trecerea între caracter de cuvânt și alt caracter', () => {
    const pattern = new RegExp(`${PY_BOUNDARY}gin${PY_BOUNDARY}`, 'u');
    assert.ok(pattern.test('un gin bun'));
    assert.ok(pattern.test('gin'));
    assert.ok(pattern.test('gin-tonic'));
    assert.ok(!pattern.test('begin'));
    assert.ok(!pattern.test('gin_x'));
    assert.ok(!pattern.test('ginÎ'.toLowerCase()), 'litera non-ASCII e caracter de cuvânt');
    assert.ok(!pattern.test('gin5'));
    assert.ok(pattern.test('gin' + GRIN));
  });
});
