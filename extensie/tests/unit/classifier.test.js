// Clasificatorul de categorii (src/calcul/classifier.js): modelele din config/categorii.json trec toate prin PyPattern, regulile greșite sau în afara subsetului portabil sunt refuzate cu mesaj
// care numește categoria, validările au mesajele din ValueError-ul Python, iar classify() dă aceeași categorie și același model ca Python pe reguli inventate (corpusul din regex.json se verifică în tests/paritate/analiza.test.js).
// Cazurile de validare sunt scrise de mână; mesajul Python al fiecăruia a fost obținut rulând Classifier(reguli, source="reguli.json") din emag_spend/classifier.py.
// Ce NU face: nu testează PyPattern în sine (python_regex.test.js) și nici regulile personale (nu intră în v1).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { Classifier } from '../../src/calcul/classifier.js';
import { PyPattern } from '../../src/calcul/python_regex.js';
import { normalizeText } from '../../src/calcul/text_normalize.js';

const CONFIG_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'config');
const REPO_RULES = JSON.parse(readFileSync(path.join(CONFIG_DIR, 'categorii.json'), 'utf8').replace(/^\u{feff}/u, ''));

/** Mesajul ValueError așteptat: tipul și textul exact (Python scrie ValueError, extensia PyValueError cu același nume). */
function throwsValueError(action, message) {
  assert.throws(action, (error) => {
    assert.equal(error.name, 'ValueError');
    assert.equal(error.message, message);
    return true;
  });
}

// [nume, reguli, mesajul ValueError din Python | null dacă regulile sunt valide]
const RULE_VALIDATION_CASES = [
  ['categories nu e lista', { categories: 'x' }, 'reguli.json: «categories» trebuie să fie o listă de categorii'],
  ['categories obiect', { categories: {} }, 'reguli.json: «categories» trebuie să fie o listă de categorii'],
  ['categories null', { categories: null }, 'reguli.json: «categories» trebuie să fie o listă de categorii'],
  ['intrare nu e obiect', { categories: ['x'] }, 'reguli.json: fiecare categorie trebuie să fie un obiect cu «name» și «patterns»'],
  ['intrare null', { categories: [null] }, 'reguli.json: fiecare categorie trebuie să fie un obiect cu «name» și «patterns»'],
  ['fara nume', { categories: [{ patterns: ['a'] }] }, 'reguli.json: o categorie din reguli nu are nume'],
  ['nume gol', { categories: [{ name: '', patterns: ['a'] }] }, 'reguli.json: o categorie din reguli nu are nume'],
  ['nume alb', { categories: [{ name: '   ', patterns: ['a'] }] }, 'reguli.json: o categorie din reguli nu are nume'],
  ['nume numar', { categories: [{ name: 5, patterns: ['a'] }] }, 'reguli.json: o categorie din reguli nu are nume'],
  ['nume null', { categories: [{ name: null, patterns: ['a'] }] }, 'reguli.json: o categorie din reguli nu are nume'],
  ['nume duplicat', { categories: [{ name: 'A', patterns: ['a'] }, { name: 'A', patterns: ['b'] }] }, "reguli.json: categorie duplicată în reguli: 'A'"],
  ['nume duplicat dupa strip', { categories: [{ name: 'A', patterns: ['a'] }, { name: ' A ', patterns: ['b'] }] }, "reguli.json: categorie duplicată în reguli: 'A'"],
  ['patterns text', { categories: [{ name: 'A', patterns: 'a' }] }, "reguli.json: în categoria 'A', «patterns» trebuie să fie o listă de texte"],
  ['patterns cu numar', { categories: [{ name: 'A', patterns: ['a', 1] }] }, "reguli.json: în categoria 'A', «patterns» trebuie să fie o listă de texte"],
  ['patterns null', { categories: [{ name: 'A', patterns: null }] }, "reguli.json: în categoria 'A', «patterns» trebuie să fie o listă de texte"],
  ['pattern gol', { categories: [{ name: 'A', patterns: ['a', ''] }] }, "reguli.json: categoria 'A' are un model gol în «patterns» (ar potrivi orice produs)"],
  ['pattern alb', { categories: [{ name: 'A', patterns: ['a', '  \t'] }] }, "reguli.json: categoria 'A' are un model gol în «patterns» (ar potrivi orice produs)"],
  ['exclude text', { categories: [{ name: 'A', patterns: ['a'], exclude: 'x' }] }, "reguli.json: în categoria 'A', «exclude» trebuie să fie o listă de texte"],
  ['exclude cu numar', { categories: [{ name: 'A', patterns: ['a'], exclude: [2] }] }, "reguli.json: în categoria 'A', «exclude» trebuie să fie o listă de texte"],
  ['exclude gol', { categories: [{ name: 'A', patterns: ['a'], exclude: [' '] }] }, "reguli.json: categoria 'A' are un model gol în «exclude» (ar potrivi orice produs)"],
  ['fara patterns', { categories: [{ name: 'A' }] }, "reguli.json: categoria 'A' nu are niciun model în 'patterns'"],
  ['patterns lista goala', { categories: [{ name: 'A', patterns: [] }] }, "reguli.json: categoria 'A' nu are niciun model în 'patterns'"],
  ['paranteza deschisa', { categories: [{ name: 'A', patterns: ['(a'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': missing ), unterminated subpattern at position 0"],
  ['paranteza inchisa', { categories: [{ name: 'A', patterns: ['a)'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': unbalanced parenthesis at position 1"],
  ['clasa neinchisa', { categories: [{ name: 'A', patterns: ['[a'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': unterminated character set at position 0"],
  ['nimic de repetat', { categories: [{ name: 'A', patterns: ['*a'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': nothing to repeat at position 0"],
  ['repetitie multipla', { categories: [{ name: 'A', patterns: ['a**'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': multiple repeat at position 2"],
  ['escape gresit', { categories: [{ name: 'A', patterns: ['\\q'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': bad escape \\q at position 0"],
  ['nume de grup gresit', { categories: [{ name: 'A', patterns: ['(?P<1a>x)'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': bad character in group name '1a' at position 4"],
  ['interval invers', { categories: [{ name: 'A', patterns: ['a{2,1}'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': min repeat greater than max repeat at position 2"],
  ['exclude cu eroare', { categories: [{ name: 'A', patterns: ['a'], exclude: ['(b'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': missing ), unterminated subpattern at position 0"],
  ['model pe mai multe randuri', { categories: [{ name: 'A', patterns: ['a\n(b'] }] }, "reguli.json: expresie regulată greșită în categoria 'A': missing ), unterminated subpattern at position 2 (line 2, column 1)"],
  ['a doua categorie are eroarea', { categories: [{ name: 'A', patterns: ['a'] }, { name: 'B', patterns: ['b)'] }] }, "reguli.json: expresie regulată greșită în categoria 'B': unbalanced parenthesis at position 1"],
  ['potriveste textul gol', { categories: [{ name: 'A', patterns: ['a*'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['exclude potriveste textul gol', { categories: [{ name: 'A', patterns: ['a'], exclude: ['b*'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['ancora ^ potriveste textul gol', { categories: [{ name: 'A', patterns: ['^'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['ancora $ potriveste textul gol', { categories: [{ name: 'A', patterns: ['$'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['grup gol potriveste textul gol', { categories: [{ name: 'A', patterns: ['(?:)'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['alternativa goala', { categories: [{ name: 'A', patterns: ['a|'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['limita de cuvant nu potriveste gol', { categories: [{ name: 'A', patterns: ['\\b'] }] }, null],
  ['lookahead gol', { categories: [{ name: 'A', patterns: ['(?=a)|b?'] }] }, "reguli.json: categoria 'A' are un model care potrivește orice text (ar potrivi orice produs)"],
  ['valid minimal', { categories: [{ name: 'A', patterns: ['a'] }] }, null],
  ['valid fara categories', {}, null],
  ['valid cu default', { default_category: 'Altceva', categories: [] }, null],
  ['valid nume cu spatii', { categories: [{ name: '  Alcool  ', patterns: ['x'] }] }, null],
];

// Modele valide în Python pe care extensia le refuză (nu le poate garanta identice în JavaScript): [model, construcția numită în mesaj]
const UNSUPPORTED_PATTERN_CASES = [
  ['(?i)casti', 'steaguri inline (?i)'],
  ['(?s:a.b)', 'steaguri inline (?i)'],
  ['(?<=a)b', 'lookbehind (?<=…) sau (?<!…)'],
  ['(?<!a)b', 'lookbehind (?<=…) sau (?<!…)'],
  ['\\Aabc', '\\A'],
  ['abc\\Z', '\\Z'],
  ['(a)\\1', 'referință numerică la un grup (\\1)'],
  ['(?#comentariu)a', 'comentariu (?#…)'],
  ['(?>a)b', 'grup atomic (?>…)'],
  ['a*+', 'cuantificator posesiv'],
  ['(a)(?(1)b|c)', 'condițional (?(…)…|…)'],
  ['\\N{LATIN SMALL LETTER A}', '\\N{…}'],
  ['\\012', 'escape octal \\0'],
];

// Reguli inventate (valoarea de mai jos e ieșirea lui Classifier.classify din Python pe fiecare nume): prima categorie care se potrivește câștigă, excluderile anulează, numele se normalizează.
const SMALL_RULES = { default_category: 'Necategorizat', categories: [{ name: 'Alcool', patterns: ['\\bwhisk(?:y|ey)\\b', '\\bvin\\b'], exclude: ['fara alcool'] }, { name: 'Televizoare', patterns: ['\\btelevizor'] }, { name: 'Casti', patterns: ['\\bcasti\\b'] }, { name: 'Primul', patterns: ['\\bcasti\\b', '\\bboxe\\b'] }, { name: 'Ordine', patterns: ['x', '\\btelevizor'] }] };
// [nume de produs, [categoria, modelul care a potrivit] din Python]
const CLASSIFY_CASES = [
  ['Whisky Test 0.7L', ['Alcool', '\\bwhisk(?:y|ey)\\b']],
  ['Vin rosu Test', ['Alcool', '\\bvin\\b']],
  ['Vin Test fara alcool', ['Necategorizat', '']],
  ['Televizor Smart 55"', ['Televizoare', '\\btelevizor']],
  ['CĂȘTI Bluetooth', ['Casti', '\\bcasti\\b']],
  ['Boxe Test', ['Primul', '\\bboxe\\b']],
  ['Ceva necunoscut', ['Necategorizat', '']],
  ['', ['Necategorizat', '']],
  ['\u{162}ărană Îți', ['Necategorizat', '']],
  ['televizor fara alcool', ['Televizoare', '\\btelevizor']],
  ['Televizor x', ['Televizoare', '\\btelevizor']],
  ['Straße', ['Necategorizat', '']],
];

describe('config/categorii.json trece prin PyPattern', () => {
  test('toate modelele (patterns și exclude) se traduc fără UnsupportedPattern', () => {
    let count = 0;
    for (const category of REPO_RULES.categories) {
      for (const source of [...category.patterns, ...(category.exclude ?? [])]) {
        assert.doesNotThrow(() => new PyPattern(source), `categoria ${category.name}: ${source}`);
        count += 1;
      }
    }
    assert.ok(count >= 400, `doar ${count} modele: fișierul de reguli s-a golit?`);
  });

  test('Classifier se construiește din ele: 24 de categorii în ordinea fișierului, categoria implicită din fișier', () => {
    const classifier = new Classifier(REPO_RULES, 'categorii.json');
    assert.deepEqual(classifier.categoryNames, REPO_RULES.categories.map((category) => category.name));
    assert.equal(classifier.categoryNames.length, 24);
    assert.equal(classifier.defaultCategory, 'Necategorizat');
  });
});

describe('modele valide în Python, refuzate de extensie cu numele categoriei', () => {
  for (const [source, construct] of UNSUPPORTED_PATTERN_CASES) {
    test(`${JSON.stringify(source)} ca model`, () => {
      const rules = { categories: [{ name: 'Casti și audio', patterns: [source] }] };
      assert.throws(() => new Classifier(rules, 'reguli.json'), (error) => {
        assert.equal(error.name, 'ValueError');
        assert.ok(error.message.startsWith(`reguli.json: expresie regulată neacceptată de extensie în categoria 'Casti și audio': ${construct} (modelul `), error.message);
        return true;
      });
    });
  }

  test('același refuz într-un model de excludere', () => {
    const rules = { categories: [{ name: 'Alcool', patterns: ['vin'], exclude: ['(?i)fara alcool'] }] };
    assert.throws(() => new Classifier(rules, 'reguli.json'), /categoria 'Alcool': steaguri inline \(\?i\)/);
  });
});

describe('validarea regulilor: aceleași mesaje ca ValueError din Python', () => {
  for (const [name, rules, message] of RULE_VALIDATION_CASES) {
    test(name, () => {
      if (message === null) assert.doesNotThrow(() => new Classifier(rules, 'reguli.json'));
      else throwsValueError(() => new Classifier(rules, 'reguli.json'), message);
    });
  }

  test('o rădăcină care nu e obiect e refuzată cu mesajul pe care Python îl are la citirea fișierului', () => {
    throwsValueError(() => new Classifier([], 'reguli.json'), "reguli.json: trebuie să conțină un obiect cu cheia 'categories'");
    throwsValueError(() => new Classifier(null, 'reguli.json'), "reguli.json: trebuie să conțină un obiect cu cheia 'categories'");
  });

  test('sursa implicită a mesajelor', () => {
    throwsValueError(() => new Classifier({ categories: 'x' }), 'regulile de categorii: «categories» trebuie să fie o listă de categorii');
  });

  test('numele categoriei se curăță de spații (strip), iar categoria implicită vine din reguli', () => {
    const classifier = new Classifier({ default_category: 'Altceva', categories: [{ name: '  Alcool  ', patterns: ['x'] }] }, 'reguli.json');
    assert.deepEqual(classifier.categoryNames, ['Alcool']);
    assert.equal(classifier.defaultCategory, 'Altceva');
    assert.equal(new Classifier({}, 'reguli.json').defaultCategory, 'Necategorizat');
    assert.deepEqual(new Classifier({}, 'reguli.json').categoryNames, []);
  });
});

describe('classify(): categoria și modelul ca în Python', () => {
  const classifier = new Classifier(SMALL_RULES, 'reguli.json');

  test('categoryNames și defaultCategory', () => {
    assert.deepEqual(classifier.categoryNames, ['Alcool', 'Televizoare', 'Casti', 'Primul', 'Ordine']);
    assert.equal(classifier.defaultCategory, 'Necategorizat');
  });

  for (const [name, expected] of CLASSIFY_CASES) {
    test(JSON.stringify(name), () => {
      assert.deepEqual(classifier.classify(name), expected);
    });
  }

  test('un nume nenormalizat (majuscule, diacritice, spații) dă același rezultat ca cel normalizat', () => {
    for (const [name] of CLASSIFY_CASES) assert.deepEqual(classifier.classify(`  ${name.toUpperCase()}  `), classifier.classify(normalizeText(name).toUpperCase()));
  });

  test('regulile nu păstrează stare între apeluri (același nume de două ori)', () => {
    assert.deepEqual(classifier.classify('Casti Test'), classifier.classify('Casti Test'));
    assert.deepEqual(classifier.classify('Whisky Test 0.7L'), ['Alcool', '\\bwhisk(?:y|ey)\\b']);
  });
});
