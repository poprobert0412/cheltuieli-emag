// Teste unitare scrise de mână pentru extensie/src/calcul/python_regex.js (traducerea expresiilor regulate Python în JS): rezultatele
// din tabel sunt cele ale lui re din Python 3.13, calculate o dată; fiecare construcție refuzată și fiecare mesaj de eroare sunt probate separat.
// Paritatea pe expresiile reale (config/categorii.json și expresiile interne ale modulelor) e în tests/paritate/primitive.test.js.
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { PatternSyntaxError, PyPattern, UnsupportedPattern, escapePython } from '../../src/calcul/python_regex.js';

const GRIN = String.fromCodePoint(0x1f600);

/** O potrivire ca date simple (interval în puncte de cod, grupuri, grupuri cu nume), în forma din tabelul de mai jos; null rămâne null. */
function describeMatch(match) {
  return match === null ? null : { span: [match.start(), match.end()], groups: match.groups(), groupdict: match.groupdict() };
}

// [sursa, steaguri (i = IGNORECASE, s = DOTALL), metoda, textul, argumente în plus, rezultatul din Python]
const PYTHON_CASES = [
  ['a$', '', 'search', 'a\n', [], { span: [0, 1], groups: [], groupdict: {} }],
  ['a$', '', 'fullmatch', 'a\n', [], null],
  ['a$', '', 'match', 'a', [], { span: [0, 1], groups: [], groupdict: {} }],
  ['^a', '', 'search', 'ba', [], null],
  ['a$', '', 'search', 'a\n\n', [], null],
  ['.', '', 'search', '\n', [], null],
  ['.', '', 'search', '\r', [], { span: [0, 1], groups: [], groupdict: {} }],
  ['.', '', 'search', '\u{2028}', [], { span: [0, 1], groups: [], groupdict: {} }],
  ['.', 's', 'search', '\n', [], { span: [0, 1], groups: [], groupdict: {} }],
  ['a.c', '', 'search', 'a\nc', [], null],
  ['a.c', 's', 'search', 'a\nc', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['\\d+', '', 'search', 'x\u{663}\u{664}y', [], { span: [1, 3], groups: [], groupdict: {} }],
  ['[\\d.]+', '', 'findall', 'a1.5b\u{663}.', [], ['1.5', '\u{663}.']],
  ['\\D', '', 'findall', 'a1\u{663}', [], ['a']],
  ['[^\\W_]+', '', 'findall', 'foo_bar baz9 \u{e9}_1 \u{b2}x', [], ['foo', 'bar', 'baz9', '\u{e9}', '1', '\u{b2}x']],
  ['\\s', '', 'findall', 'a b\u{85}c\u{1c}d\u{feff}e\u{a0}', [], [' ', '\u{85}', '\u{1c}', '\u{a0}']],
  ['\\S+', '', 'findall', 'a b\u{85}c\u{feff}', [], ['a', 'b', 'c\u{feff}']],
  ['\\w+', '', 'findall', 'a_1 \u{b2} \u{bd} \u{301}x', [], ['a_1', '\u{b2}', '\u{bd}', 'x']],
  ['\\W', '', 'findall', 'a-b c', [], ['-', ' ']],
  ['\\bgin\\b', '', 'search', 'un gin bun', [], { span: [3, 6], groups: [], groupdict: {} }],
  ['\\bgin\\b', '', 'search', 'begin', [], null],
  ['\\bgin\\b', '', 'search', 'gin_x', [], null],
  ['\\bgin\\b', '', 'search', 'gin-tonic', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['\\bgin\\b', '', 'search', 'gin\u{1f600}', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['\\bgin\\b', '', 'search', 'gin\u{ee}', [], null],
  ['\\Bin', '', 'search', 'gin', [], { span: [1, 3], groups: [], groupdict: {} }],
  ['\\Bin', '', 'search', 'in', [], null],
  ['[]a]+', '', 'findall', 'a]b', [], ['a]']],
  ['[^]a]+', '', 'findall', 'a]b', [], ['b']],
  ['[a-]+', '', 'findall', 'a-b', [], ['a-']],
  ['[-a]+', '', 'findall', 'a-b', [], ['a-']],
  ['[a\\-z]+', '', 'findall', 'a-z b', [], ['a-z']],
  ['[\\]]', '', 'findall', 'a]', [], [']']],
  ['[\\\\]', '', 'findall', 'a\\b', [], ['\\']],
  ['[a-c\\d]+', '', 'findall', 'abc123d', [], ['abc123']],
  ['[\u{1f600}-\u{1f64f}]+', '', 'findall', 'a\u{1f600}\u{1f601}b', [], ['\u{1f600}\u{1f601}']],
  ['(a)(b)?', '', 'search', 'ac', [], { span: [0, 1], groups: ['a', null], groupdict: {} }],
  ['(?P<x>a)(?P=x)', '', 'search', 'aa', [], { span: [0, 2], groups: ['a'], groupdict: { x: 'a' } }],
  ['(?P<x>a)(?P=x)', '', 'search', 'ab', [], null],
  // un grup din lookahead pozitiv rămâne setat după el (referința îl vede); unul din lookahead negativ nu se setează niciodată
  ['(?=(?P<x>a))(?P=x)', '', 'search', 'aa', [], { span: [0, 1], groups: ['a'], groupdict: { x: 'a' } }],
  ['(?!(?P<x>a))b', '', 'search', 'ab', [], { span: [1, 2], groups: [null], groupdict: { x: null } }],
  ['(?:a|b)+c', '', 'search', 'xabac', [], { span: [1, 5], groups: [], groupdict: {} }],
  ['a(?=b)', '', 'findall', 'ab ac', [], ['a']],
  ['a(?!b)', '', 'findall', 'ab ac', [], ['a']],
  ['a{2}', '', 'findall', 'aaaaa', [], ['aa', 'aa']],
  ['a{2,}', '', 'findall', 'aaaaa', [], ['aaaaa']],
  ['a{,3}', '', 'findall', 'aaaaa', [], ['aaa', 'aa', '']],
  ['a{1,2}?', '', 'findall', 'aaa', [], ['a', 'a', 'a']],
  ['a{', '', 'search', 'a{', [], { span: [0, 2], groups: [], groupdict: {} }],
  ['a{x}', '', 'search', 'a{x}', [], { span: [0, 4], groups: [], groupdict: {} }],
  ['a{}', '', 'search', 'a{}', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['a{1', '', 'search', 'a{1', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['a{1,x}', '', 'search', 'a{1,x}', [], { span: [0, 6], groups: [], groupdict: {} }],
  ['a{,}', '', 'search', 'aaa', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['a*?b', '', 'search', 'aab', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['a+?', '', 'findall', 'aaa', [], ['a', 'a', 'a']],
  ['lei', 'i', 'search', 'LEI', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['lei', 'i', 'search', 'LE\u{130}', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['lei', 'i', 'search', 'le\u{131}', [], { span: [0, 3], groups: [], groupdict: {} }],
  ['[a-z]+', 'i', 'findall', 'xI\u{130}\u{131}y', [], ['xI\u{130}\u{131}y']],
  ['[^a-z]', 'i', 'findall', 'xI\u{130}\u{131}1', [], ['1']],
  ['i', 'i', 'findall', 'iI\u{130}\u{131}', [], ['i', 'I', '\u{130}', '\u{131}']],
  ['\u{130}', 'i', 'findall', 'iI\u{130}\u{131}', [], ['i', 'I', '\u{130}', '\u{131}']],
  ['[\u{131}]', 'i', 'findall', 'iI\u{130}\u{131}', [], ['i', 'I', '\u{130}', '\u{131}']],
  ['k', 'i', 'findall', 'kK\u{212a}', [], ['k', 'K', '\u{212a}']],
  ['s', 'i', 'findall', 'sS\u{17f}', [], ['s', 'S', '\u{17f}']],
  ['[A-Za-z\u{103}\u{e2}]+', 'i', 'findall', 'xyz\u{102}\u{c2} abc', [], ['xyz\u{102}\u{c2}', 'abc']],
  ['\u{df}', 'i', 'findall', '\u{df}\u{1e9e}ss', [], ['\u{df}', '\u{1e9e}']],
  ['\\d+', '', 'finditer', 'a\u{1f600}12 b34', [], [{ span: [2, 4], groups: [], groupdict: {} }, { span: [6, 8], groups: [], groupdict: {} }]],
  ['b', '', 'search', '\u{1f600}\u{1f600}b', [], { span: [2, 3], groups: [], groupdict: {} }],
  ['(\\d+)-(\\d+)', '', 'findall', '1-2 3-4', [], [['1', '2'], ['3', '4']]],
  ['\\d+', '', 'findall', '1 22 333', [], ['1', '22', '333']],
  ['(\\d)(\\d)?', '', 'findall', '12 3', [], [['1', '2'], ['3', '']]],
  ['\\s+', '', 'sub', 'a  b\tc', [' '], 'a b c'],
  ['\\s+', '', 'sub', 'a  b\tc', ['', 1], 'ab\tc'],
  ['(\\d+)', '', 'sub', 'a1b22', ['<\\1>'], 'a<1>b<22>'],
  ['(?P<n>\\d+)', '', 'sub', 'a1b22', ['[\\g<n>]'], 'a[1]b[22]'],
  ['\\d', '', 'sub', 'a1b2', ['\\\\'], 'a\\b\\'],
  ['\\d', '', 'sub', 'a1b2', ['\\n'], 'a\nb\n'],
  ['\\d', '', 'sub', 'a1b2', ['\\&'], 'a\\&b\\&'],
  ['x', '', 'sub', 'axbxc', ['-', 1], 'a-bxc'],
  ['\\s*,\\s*', '', 'split', 'a , b,c', [], ['a', 'b', 'c']],
  ['(,)', '', 'split', 'a,b', [], ['a', ',', 'b']],
  ['x', '', 'split', 'axb', [], ['a', 'b']],
  ['x', '', 'split', '', [], ['']],
  // potriviri goale: Python 3.7+ caută, după o potrivire goală, una NEGOALĂ în același loc înainte să avanseze
  ['x*', '', 'finditer', 'axb', [], [{ span: [0, 0], groups: [], groupdict: {} }, { span: [1, 2], groups: [], groupdict: {} }, { span: [2, 2], groups: [], groupdict: {} }, { span: [3, 3], groups: [], groupdict: {} }]],
  ['x*', '', 'sub', 'axb', ['-'], '-a--b-'],
  ['x*', '', 'split', 'axb', [], ['', 'a', '', 'b', '']],
  ['|a', '', 'findall', 'a', [], ['', 'a', '']],
  ['x*?', '', 'findall', 'xx', [], ['', 'x', '', 'x', '']],
  ['(a)|b', '', 'findall', 'ab', [], ['a', '']],
  ['(a)|(b)', '', 'findall', 'ab', [], [['a', ''], ['', 'b']]],
  // potriviri goale lângă caractere de dincolo de BMP (perechi surogat): V8 raportează uneori o potrivire goală la MIJLOCUL perechii, unde Python nu poate începe una
  ['(?![^a]b)', '', 'search', '\u{1f600}b', [], { span: [1, 1], groups: [], groupdict: {} }],
  ['(?![^a]b)', '', 'findall', '\u{1f600}b', [], ['', '']],
  ['(?![^a]b)', '', 'finditer', '\u{1f600}b', [], [{ span: [1, 1], groups: [], groupdict: {} }, { span: [2, 2], groups: [], groupdict: {} }]],
  ['(?![^a]b)', '', 'finditer', '\u{1f600}bb', [], [{ span: [2, 2], groups: [], groupdict: {} }, { span: [3, 3], groups: [], groupdict: {} }]],
  ['(?![^a]b)', '', 'sub', '\u{1f600}b', ['-'], '\u{1f600}-b-'],
  ['(?![^a]b)', '', 'split', '\u{1f600}b', [], ['\u{1f600}', 'b', '']],
  ['(?!\\W?b\\D*)', '', 'finditer', '\u{1f600}b\u{1f600}\n\u{663}\u{131}\u{e9}', [], [2, 3, 4, 5, 6, 7].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
  ['(?!\\W?b\\D*)', '', 'sub', '\u{1f600}b\u{1f600}\n\u{663}\u{131}\u{e9}', ['-'], '\u{1f600}b-\u{1f600}-\n-\u{663}-\u{131}-\u{e9}-'],
  ['\\B', '', 'finditer', '\u{1f600}\u{1f600}', [], [0, 1, 2].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
  ['\\B', '', 'sub', '\u{1f600}\u{1f600}', ['-'], '-\u{1f600}-\u{1f600}-'],
  ['(?!\\w)', '', 'finditer', '\u{1f600}a\u{1f600}', [], [0, 2, 3].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
  ['(?![^a]a)', '', 'split', 'a\u{1f600}a', [], ['', 'a\u{1f600}', 'a', '']],
  // surogatele singure (neîmperecheate) sunt caractere de sine stătătoare: între două jumătăți de început, între două de sfârșit sau în ordinea inversă SE poate potrivi
  ['(?!a)', '', 'finditer', String.fromCharCode(0xd800, 0xd800), [], [0, 1, 2].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
  ['(?!a)', '', 'finditer', String.fromCharCode(0xdc00, 0xdc00), [], [0, 1, 2].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
  ['(?!a)', '', 'finditer', String.fromCharCode(0xdc00, 0xd800), [], [0, 1, 2].map((at) => ({ span: [at, at], groups: [], groupdict: {} }))],
];

describe('PyPattern: rezultatele lui re din Python 3.13 pe cazuri alese', () => {
  for (const [source, flags, method, text, extra, expected] of PYTHON_CASES) {
    test(`${method} /${source}/${flags} pe ${JSON.stringify(text)}`, () => {
      const pattern = new PyPattern(source, { ignoreCase: flags.includes('i'), dotAll: flags.includes('s') });
      let actual;
      if (method === 'finditer') actual = pattern.finditer(text).map(describeMatch);
      else if (method === 'findall') actual = pattern.findall(text);
      else if (method === 'sub') actual = pattern.sub(extra[0], text, extra[1] ?? 0);
      else if (method === 'split') actual = pattern.split(text);
      else actual = describeMatch(pattern[method](text));
      assert.deepStrictEqual(actual, expected);
    });
  }
});

describe('PyPattern: erori de sintaxă, cu mesajul și poziția din Python (re.error)', () => {
  const errors = [
    ['(', 'missing ), unterminated subpattern at position 0'], [')', 'unbalanced parenthesis at position 0'], ['a)', 'unbalanced parenthesis at position 1'],
    ['(a', 'missing ), unterminated subpattern at position 0'], ['[', 'unterminated character set at position 0'], ['[a', 'unterminated character set at position 0'],
    ['[z-a]', 'bad character range z-a at position 1'], ['a**', 'multiple repeat at position 2'], ['*a', 'nothing to repeat at position 0'], ['+', 'nothing to repeat at position 0'],
    ['?', 'nothing to repeat at position 0'], ['{1}', 'nothing to repeat at position 0'], ['a{2,1}', 'min repeat greater than max repeat at position 2'],
    ['\\q', 'bad escape \\q at position 0'], ['(?P<n', 'missing >, unterminated name at position 4'], ['(?P<1a>x)', "bad character in group name '1a' at position 4"],
    ['(?Px)', 'unknown extension ?Px at position 1'], ['(?P=zz)', "unknown group name 'zz' at position 4"],
    ['(?P<n>a)(?P<n>b)', "redefinition of group name 'n' as group 2; was group 1 at position 12"], ['(?<n>a)', 'unknown extension ?<n at position 1'],
    ['(?z)', 'unknown extension ?z at position 1'], ['\\', 'bad escape (end of pattern) at position 0'], ['[\\d-a]', 'bad character range \\d-a at position 1'],
    ['a{1,2}{3}', 'multiple repeat at position 6'], ['(?:', 'missing ), unterminated subpattern at position 0'], ['x|*', 'nothing to repeat at position 2'],
    ['^*', 'nothing to repeat at position 1'], ['$+', 'nothing to repeat at position 1'], ['\\b*', 'nothing to repeat at position 2'],
    ['(?P>x)', 'unknown extension ?P> at position 1'], ['(?P<>x)', 'missing group name at position 4'], ['(?P=)', 'missing group name at position 4'],
    ['(?P<n>', 'missing ), unterminated subpattern at position 0'], ['(?', 'unexpected end of pattern at position 2'], ['(?P', 'unexpected end of pattern at position 3'],
    ['[a-', 'unterminated character set at position 0'], ['\\xz', 'incomplete escape \\x at position 0'], ['\\x4', 'incomplete escape \\x4 at position 0'],
    ['\\u12', 'incomplete escape \\u12 at position 0'], ['\\U0011ffff', 'bad escape \\U0011ffff at position 0'], ['(?=a', 'missing ), unterminated subpattern at position 0'],
    ['(?!', 'missing ), unterminated subpattern at position 0'], ['\\8', 'invalid group reference 8 at position 1'], ['(\\2)', 'invalid group reference 2 at position 2'],
    ['(?P<a>(?P=a))', 'cannot refer to an open group at position 10'], ['a|*b', 'nothing to repeat at position 2'], ['(*)', 'nothing to repeat at position 1'],
    ['a**?', 'multiple repeat at position 2'], ['a*??', 'multiple repeat at position 3'],
    ['(?i', 'missing -, : or ) at position 3'], ['(?#x', 'missing ), unterminated comment at position 0'],
  ];
  for (const [source, message] of errors) {
    test(`/${source}/ -> ${message}`, () => {
      assert.throws(() => new PyPattern(source), (error) => error instanceof PatternSyntaxError && error.message === message, `mesaj greșit pentru ${source}`);
    });
  }
  test('o repetiție uriașă ridică RangeError (OverflowError în Python)', () => {
    assert.throws(() => new PyPattern('a{99999999999}'), { message: 'the repetition number is too large' });
  });
  test('un șablon de înlocuire cu secvență necunoscută cere eroare ca în Python', () => {
    assert.throws(() => new PyPattern('\\d').sub('\\q', 'a1'), (error) => error instanceof PatternSyntaxError && error.message === 'bad escape \\q at position 0');
  });
});

describe('PyPattern: construcțiile valide în Python, dar în afara subsetului portabil, sunt refuzate cu numele lor', () => {
  const refused = [
    ['(?i)a', 'steaguri inline (?i)'], ['(?i:a)', 'steaguri inline (?i)'], ['(?s)a', 'steaguri inline (?i)'], ['(?-i:a)', 'steaguri inline (?i)'], ['(?x) a', 'steaguri inline (?i)'],
    ['(?a)a', 'steaguri inline (?i)'], ['(?L)a', 'steaguri inline (?i)'], ['(?<=a)b', 'lookbehind (?<=…) sau (?<!…)'], ['(?<!a)b', 'lookbehind (?<=…) sau (?<!…)'],
    ['\\Aa', '\\A'], ['a\\Z', '\\Z'], ['(a)\\1', 'referință numerică la un grup (\\1)'], ['(?#c)a', 'comentariu (?#…)'], ['(?>a)', 'grup atomic (?>…)'],
    ['a*+', 'cuantificator posesiv'], ['a++', 'cuantificator posesiv'], ['a?+', 'cuantificator posesiv'], ['a{1,2}+', 'cuantificator posesiv'],
    ['(a)(?(1)b|c)', 'condițional (?(…)…|…)'], ['\\N{DIGIT ONE}', '\\N{…}'], ['\\0', 'escape octal \\0'], ['\\012', 'escape octal \\0'], ['(?=a)*', 'aserțiune cu cuantificator'],
    ['(?:(a)|b)+', 'grup de captură care poate lipsi dintr-o iterație a unei repetiții'],
    // aceeași regulă pentru repetiții cu număr mic de iterații (nu doar + și *): «(?:(a)|b){2}» pe «ab» păstrează «a» în Python și îl uită în JS
    ['(?:(a)|b){2}', 'grup de captură care poate lipsi dintr-o iterație a unei repetiții'], ['(?:(a)|b){1,2}', 'grup de captură care poate lipsi dintr-o iterație a unei repetiții'],
    ['(?:(a)|b){,2}?', 'grup de captură care poate lipsi dintr-o iterație a unei repetiții'], ['(a*)*', 'grup de captură într-o repetiție care poate potrivi textul gol'],
    ['(?P<x>a)?(?P=x)', 'referință la un grup care poate lipsi (?P=x)'], ['(?:(?P<x>a)|b)(?P=x)', 'referință la un grup care poate lipsi (?P=x)'],
    // în Python o referință la un grup nesetat eșuează (aici nu s-ar potrivi nimic pe «aa»), în JS ar potrivi textul gol
    ['(?!(?P<x>a))(?P=x)', 'referință la un grup care poate lipsi (?P=x)'],
    ['()+', 'grup de captură într-o repetiție care poate potrivi textul gol'],
    // o repetiție cu iterații opționale al cărei corp poate potrivi textul gol: JS respinge o iterație goală după minim, Python o primește o dată și apoi se oprește
    // (alte capturi: «(a*)?» dă «» în Python și undefined în JS; uneori alte intervale: «(?:|a)+» pe «aa» dă 0-0 în Python și 0-2 în JS)
    ['(a*)?', 'grup de captură într-o repetiție care poate potrivi textul gol'], ['(\\B){0,1}x', 'grup de captură într-o repetiție care poate potrivi textul gol'],
    ['(a|)+', 'grup de captură într-o repetiție care poate potrivi textul gol'],
    ['(?:|a)+', 'repetiție al cărei corp poate potrivi textul gol'], ['(?:|a)*', 'repetiție al cărei corp poate potrivi textul gol'],
    ['(?:x*|a)+', 'repetiție al cărei corp poate potrivi textul gol'], ['(?:|a)?', 'repetiție al cărei corp poate potrivi textul gol'],
    ['(?:|a){0,1}', 'repetiție al cărei corp poate potrivi textul gol'], ['(?:|a)+?', 'repetiție al cărei corp poate potrivi textul gol'],
  ];
  for (const [source, construct] of refused) {
    test(`/${source}/ -> ${construct}`, () => {
      assert.throws(() => new PyPattern(source), (error) => error instanceof UnsupportedPattern && error.construct === construct && error.message.includes(construct),
        `construcția ${source} trebuia refuzată ca «${construct}»`);
    });
  }
  test('un grup de captură care e sigur setat în fiecare iterație e acceptat', () => {
    assert.doesNotThrow(() => new PyPattern('(?:(a)b)+'));
    assert.doesNotThrow(() => new PyPattern('(\\d)+'));
    assert.doesNotThrow(() => new PyPattern('(?P<x>a)(?P=x)'));
    assert.doesNotThrow(() => new PyPattern('(?P<x>a)b(?P=x)|c'));
    assert.doesNotThrow(() => new PyPattern('(?=(?P<x>a))(?P=x)'), 'grupul dintr-un lookahead pozitiv e setat după el');
  });
  test('repetițiile al căror corp nu poate fi gol, sau care au o singură iterație obligatorie, sunt acceptate', () => {
    for (const source of ['(?:a|b)?', '(\\d)?', '(?:ab)*', '(a)?', '(?:\\s*,\\s*)*x', '(?:|a){1}', '(a*){1}', '(a*){0}', 'a*', '(?:a|b*)', '\\d+(?:\\.\\d{1,2})?']) {
      assert.doesNotThrow(() => new PyPattern(source), source);
    }
  });
});

describe('PyPattern.sub: șabloanele de înlocuire, rezultatul și erorile (mesaj, poziție, ordine) ca în parse_template din Python 3.13', () => {
  const syntaxError = (message) => ({ name: 'PatternSyntaxError', message });
  const indexError = (message) => ({ name: 'IndexError', message });
  // [expresie, șablon, text, count, rezultatul din Python: text sau eroare]; erorile apar în ordinea citirii șablonului, de la stânga la dreapta, iar o eroare de grup apare și fără nicio potrivire
  const rows = [
    ['(a)(b)?', '\\1\\2', 'ab', 0, 'ab'], ['(a)(b)?', '\\1[\\2]', 'a', 0, 'a[]'], ['(a)', '\\1\\1', 'aa', 0, 'aaaa'], ['(a)', '<\\g<0>>', 'aa', 1, '<a>a'],
    ['(a)', '\\g<0>\\g<1>', 'a', 0, 'aa'], ['(?P<x>a)', '\\g<x>-\\g<1>', 'a', 0, 'a-a'],
    ['(a)', '\\2', 'a', 0, syntaxError('invalid group reference 2 at position 1')], ['x', '\\g<1>', '', 0, syntaxError('invalid group reference 1 at position 3')],
    ['x', 'ab\\g<1>', 'xx', 0, syntaxError('invalid group reference 1 at position 5')], ['(a)', '\\g<007>', 'a', 0, syntaxError('invalid group reference 7 at position 3')],
    ['(a)', '\\g<99999999999999999999999>', 'a', 0, syntaxError('invalid group reference 99999999999999999999999 at position 3')],
    ['(a)', '\\18', 'a', 0, syntaxError('invalid group reference 18 at position 1')], ['(a)', '\\10', 'a', 0, syntaxError('invalid group reference 10 at position 1')],
    ['(a)', '\\8', 'a', 0, syntaxError('invalid group reference 8 at position 1')], ['(a)', '\\9', 'a', 0, syntaxError('invalid group reference 9 at position 1')],
    ['(?P<x>a)', '\\g<y>', 'a', 0, indexError("unknown group name 'y'")], ['(?P<x>a)', '\\g<y>', '', 0, indexError("unknown group name 'y'")],
    ['(a)', '\\2\\g<nope>\\g<1', 'a', 0, syntaxError('invalid group reference 2 at position 1')], ['(a)', '\\g<nope>\\q', 'a', 0, indexError("unknown group name 'nope'")],
    ['(a)', '\\q\\g<nope>', 'a', 0, syntaxError('bad escape \\q at position 0')],
    ['(a)', '\\g<', 'a', 0, syntaxError('missing group name at position 3')], ['(a)', 'x\\g<', 'a', 0, syntaxError('missing group name at position 4')],
    ['(a)', '\\g<>', 'a', 0, syntaxError('missing group name at position 3')], ['(a)', '\\g<1', 'a', 0, syntaxError('missing >, unterminated name at position 3')],
    ['(a)', `\\g<${GRIN}\\f\\3\\1`, 'a', 0, syntaxError('missing >, unterminated name at position 3')],
    ['(a)', '\\g', 'a', 0, syntaxError('missing < at position 2')], ['(a)', '\\gx', 'a', 0, syntaxError('missing < at position 2')],
    ['(a)', `\\g${GRIN}`, 'a', 0, syntaxError('missing < at position 2')], ['(a)', `\\g\\${GRIN}`, 'a', 0, syntaxError('missing < at position 2')],
    ['(a)', '\\g<-1>', 'a', 0, syntaxError("bad character in group name '-1' at position 3")], ['(a)', '\\g< 1>', 'a', 0, syntaxError("bad character in group name ' 1' at position 3")],
    ['(a)', '\\g<1a>', 'a', 0, syntaxError("bad character in group name '1a' at position 3")], ['(a)', `\\g<${GRIN}>`, 'a', 0, syntaxError(`bad character in group name '${GRIN}' at position 3`)],
    ['(a)', '\\g<\u{661}>', 'a', 0, syntaxError("bad character in group name '\u{661}' at position 3")],
    ['(a)', 'line1\n\\q', 'a', 0, syntaxError('bad escape \\q at position 6 (line 2, column 1)')], ['(a)', 'line1\n\\g<9>', 'a', 0, syntaxError('invalid group reference 9 at position 9 (line 2, column 4)')],
    ['(a)', 'ab\ncd\\g<', 'a', 0, syntaxError('missing group name at position 8 (line 2, column 6)')],
    ['(a)', 'x\\', 'a', 0, syntaxError('bad escape (end of pattern) at position 1')], ['(a)', '\\', 'a', 0, syntaxError('bad escape (end of pattern) at position 0')],
    ['(a)', 'ab\\', '', 0, syntaxError('bad escape (end of pattern) at position 2')],
    ['(a)', '\\0', 'a', 0, '\x00'], ['(a)', '\\01', 'a', 0, '\x01'], ['(a)', '\\012', 'a', 0, '\n'], ['(a)', '\\0123', 'a', 0, '\n3'], ['(a)', '\\08', 'a', 0, '\x008'],
    ['(a)', '\\377', 'a', 0, '\xff'], ['(a)', '\\101', 'a', 0, 'A'], ['(a)', '\\400', 'a', 0, syntaxError('octal escape value \\400 outside of range 0-0o377 at position 0')],
    ['(a)', '\\777', 'a', 0, syntaxError('octal escape value \\777 outside of range 0-0o377 at position 0')], ['(a)', '\\1234', 'a', 0, 'S4'],
    ['(a)', '\\801', 'a', 0, syntaxError('invalid group reference 80 at position 1')], ['(a)', '\\901', 'a', 0, syntaxError('invalid group reference 90 at position 1')],
    ['(a)', '\\81', 'a', 0, syntaxError('invalid group reference 81 at position 1')],
    ['(a)', '\\a\\b\\f\\n\\r\\t\\v\\\\', 'a', 0, '\x07\b\f\n\r\t\x0b\\'], ['(a)', `\\&\\.\\ \\\u{e9}\\${GRIN}`, 'a', 0, `\\&\\.\\ \\\u{e9}\\${GRIN}`],
    ['(a)', '\\x41', 'a', 0, syntaxError('bad escape \\x at position 0')], ['(a)', `\\${'u0041'}`, 'a', 0, syntaxError('bad escape \\u at position 0')],
    ['(a)', '\\N{DIGIT ONE}', 'a', 0, syntaxError('bad escape \\N at position 0')], ['(a)', '\\A\\Z', 'a', 0, syntaxError('bad escape \\A at position 0')],
  ];
  for (const [pattern, template, text, count, expected] of rows) {
    test(`/${pattern}/.sub(${JSON.stringify(template)}, ${JSON.stringify(text)}, ${count})`, () => {
      const run = () => new PyPattern(pattern).sub(template, text, count);
      if (typeof expected === 'string') assert.equal(run(), expected);
      else assert.throws(run, (error) => error.name === expected.name && error.message === expected.message, `se aștepta ${expected.name}: ${expected.message}`);
    });
  }
});

describe('PyPattern: API-ul de potrivire', () => {
  test('match ancorează la început, fullmatch la ambele capete, search caută oriunde', () => {
    const pattern = new PyPattern('a|ab');
    assert.equal(pattern.match('xab'), null);
    assert.deepEqual(describeMatch(pattern.match('ab')), { span: [0, 1], groups: [], groupdict: {} });
    assert.deepEqual(describeMatch(pattern.fullmatch('ab')), { span: [0, 2], groups: [], groupdict: {} }); // reîncearcă alternativa lungă
    assert.deepEqual(describeMatch(pattern.search('xab')), { span: [1, 2], groups: [], groupdict: {} });
  });
  test('PyMatch: group după număr și nume, groups cu valoare implicită, span, string', () => {
    const match = new PyPattern('(?P<a>x)(y)?(?P<c>z)').search('..xz..');
    assert.equal(match.group(0), 'xz');
    assert.equal(match.group(1), 'x');
    assert.equal(match.group(2), null);
    assert.equal(match.group('a'), 'x');
    assert.equal(match.group('c'), 'z');
    assert.deepEqual(match.groups(), ['x', null, 'z']);
    assert.deepEqual(match.groups('-'), ['x', '-', 'z']);
    assert.deepEqual(match.groupdict(), { a: 'x', c: 'z' });
    assert.deepEqual(match.span(), [2, 4]);
    assert.deepEqual(match.span(2), [-1, -1]);
    assert.equal(match.start(2), -1);
    assert.equal(match.string, '..xz..');
    assert.throws(() => match.group(9), (error) => error.name === 'IndexError' && error instanceof RangeError && error.message === 'no such group');
    assert.throws(() => match.group('zzz'), (error) => error.name === 'IndexError' && error instanceof RangeError && error.message === 'no such group'); // IndexError în Python
    assert.equal(match.group(3), 'z'); // ultimul grup existent (Python: 'z')
    assert.throws(() => match.group(4), /no such group/); // primul număr de după ultimul grup (Python: IndexError)
    assert.throws(() => match.group(-1), /no such group/);
    assert.throws(() => match.span(4), /no such group/);
    assert.throws(() => match.start(4), /no such group/);
  });
  test('pozițiile sunt în puncte de cod, ca în Python, nu în unități UTF-16', () => {
    const match = new PyPattern('b').search(GRIN + GRIN + 'b');
    assert.deepEqual([match.start(), match.end()], [2, 3]);
    assert.equal(match.utf16Start(), 4);
    assert.equal(match.utf16End(), 5);
  });
  test('o potrivire goală începe la marginea unui caracter, niciodată la mijlocul unei perechi surogat', () => {
    const match = new PyPattern('(?![^a]b)').search(GRIN + 'b'); // V8 dă indexul 1 (mijlocul perechii); Python și specificația JS: după pereche
    assert.deepEqual([match.start(), match.utf16Start(), match.utf16End()], [1, 2, 2]);
    for (const found of new PyPattern('\\B').finditer(GRIN + GRIN)) assert.ok(found.utf16Start() % 2 === 0, `potrivire la mijlocul perechii: ${found.utf16Start()}`);
  });
  test('un motor care întoarce o potrivire înaintea punctului de plecare dă o eroare clară, nu o buclă fără sfârșit', () => {
    const pattern = new PyPattern('x*');
    const stuck = { lastIndex: 0, exec: () => Object.assign([''], { index: 1 }) };
    pattern.variant = () => stuck;
    assert.throws(() => pattern.findall('abc'), /înaintea poziției/);
  });
  test('groups și groupIndex descriu modelul', () => {
    const pattern = new PyPattern('(?P<a>x)(y)(?:z)');
    assert.equal(pattern.groups, 2);
    assert.deepEqual([...pattern.groupIndex], [['a', 1]]);
    assert.equal(pattern.source, '(?P<a>x)(y)(?:z)');
  });
  test('același model folosit din interiorul unei funcții de înlocuire nu își strică starea', () => {
    const pattern = new PyPattern('\\d+');
    const result = pattern.sub((match) => `<${pattern.sub('X', match.group(0))}>`, 'a1b22c');
    assert.equal(result, 'a<X>b<X>c');
  });
  test('sub cu funcție, cu count, subn-ul nu există; split cu maxsplit', () => {
    const pattern = new PyPattern('\\d');
    assert.equal(pattern.sub((match) => String(Number(match.group(0)) + 1), 'a1b2c3', 2), 'a2b3c3');
    assert.deepEqual(new PyPattern(',').split('a,b,c', 1), ['a', 'b,c']);
  });
  test('text care nu e șir: TypeError', () => {
    assert.throws(() => new PyPattern('a').search(5), TypeError);
    assert.throws(() => new PyPattern('a').search(null), TypeError);
  });
  test('modelul nu păstrează stare între apeluri (search repetat dă același rezultat)', () => {
    const pattern = new PyPattern('a');
    for (let index = 0; index < 3; index += 1) assert.deepEqual(describeMatch(pattern.search('xa')), { span: [1, 2], groups: [], groupdict: {} });
    for (let index = 0; index < 3; index += 1) assert.deepEqual(pattern.findall('aaa'), ['a', 'a', 'a']);
    for (let index = 0; index < 3; index += 1) assert.equal(pattern.match('ab') !== null, true);
  });
});

describe('PyPattern: clasele \\w \\W, \\d \\D, \\s \\S împart tot Unicode-ul (fără surogate) în două, cu și fără IGNORECASE', () => {
  // Verificarea față de tabelele Python, punct de cod cu punct de cod, e în tests/paritate/unicode.test.js; aici doar partiția: nimic în ambele, nimic în niciuna.
  const surrogateFree = [];
  for (let code = 0; code <= 0x10ffff; code += 1) if (code < 0xd800 || code > 0xdfff) surrogateFree.push(String.fromCodePoint(code));
  const everything = surrogateFree.join('');
  for (const [positive, negative, ignoreCaseOptions] of [['\\w', '\\W', [false]], ['\\d', '\\D', [false, true]], ['\\s', '\\S', [false, true]]]) {
    for (const ignoreCase of ignoreCaseOptions) {
      test(`${positive} + ${negative} = toate cele ${surrogateFree.length} de puncte de cod (ignoreCase=${ignoreCase})`, () => {
        const matchedPositive = new PyPattern(positive, { ignoreCase }).findall(everything);
        const matchedNegative = new PyPattern(negative, { ignoreCase }).findall(everything);
        assert.equal(matchedPositive.length + matchedNegative.length, surrogateFree.length);
        assert.ok(matchedPositive.length > 0 && matchedNegative.length > 0);
      });
    }
  }
  test('\\w \\W \\b \\B cu IGNORECASE sunt refuzate: JS le închide sub plierea literelor (U+0345 ar deveni caracter de cuvânt), Python nu', () => {
    for (const source of ['\\w', '\\W', '\\b', '\\B', '[\\w]', '[^\\W]', 'a\\b', '(?:x|\\w+)', '(?=\\b)']) {
      assert.throws(() => new PyPattern(source, { ignoreCase: true }),
        (error) => error instanceof UnsupportedPattern && error.construct === 'IGNORECASE cu \\w, \\W, \\b sau \\B', source);
      assert.doesNotThrow(() => new PyPattern(source), `fără IGNORECASE ${source} e acceptat`);
    }
  });
});

describe('escapePython: re.escape din Python 3.7+', () => {
  test('doar caracterele speciale primesc backslash (spațiul, diez, tilda, &, - incluse), literele și Unicode-ul nu', () => {
    assert.equal(escapePython('a b-c_d'), 'a\\ b\\-c_d');
    assert.equal(escapePython('(x)[y]{z}?*+|^$\\.&~# '), '\\(x\\)\\[y\\]\\{z\\}\\?\\*\\+\\|\\^\\$\\\\\\.\\&\\~\\#\\ ');
    assert.equal(escapePython('\t\n\r\u{b}\u{c}'), '\\\t\\\n\\\r\\\u{b}\\\u{c}');
    assert.equal(escapePython('é' + GRIN + '§'), 'é' + GRIN + '§');
    assert.equal(escapePython(''), '');
    assert.equal(escapePython('{order_id}'), '\\{order_id\\}');
  });
  test('textul scăpat se potrivește exact cu el însuși și cu nimic altceva', () => {
    for (const text of ['a.b', 'a b', '(x)', '[...]', '{a}', 'x+y', '^$', 'a\\b', 'a-b', '#x', 'a&b', 'a~b', '?', '*', '|', '/user/return-history']) {
      const pattern = new PyPattern(escapePython(text));
      assert.notEqual(pattern.fullmatch(text), null, JSON.stringify(text));
      assert.equal(pattern.fullmatch(`${text}x`), null);
    }
  });
});

describe('PyPattern: IGNORECASE ca în Python (inclusiv grupul I i İ ı)', () => {
  test('grupul I, i, İ, ı e un singur grup în Python, dar JS le desparte: traducerea le unește', () => {
    for (const source of ['i', '[i]', '[a-z]', '[A-Z]', '\u{130}', '[\u{131}]', '[^a-z]', '[^i]', '[^\u{131}]']) {
      const pattern = new PyPattern(source, { ignoreCase: true });
      const hits = ['i', 'I', '\u{130}', '\u{131}'].map((char) => pattern.search(char) !== null);
      const expected = source.startsWith('[^') ? [false, false, false, false] : [true, true, true, true]; // toate patru sau niciunul
      assert.deepEqual(hits, expected, source);
    }
  });
  test('Kelvin (K) și s lung (ſ) sunt echivalente cu k și s în ambele limbaje', () => {
    assert.notEqual(new PyPattern('k', { ignoreCase: true }).search('\u{212a}'), null);
    assert.notEqual(new PyPattern('S', { ignoreCase: true }).search('\u{17f}'), null);
  });
  test('fără IGNORECASE literele mari și mici sunt diferite', () => {
    assert.equal(new PyPattern('lei').search('LEI'), null);
    assert.equal(new PyPattern('i').search('\u{131}'), null);
  });
});
