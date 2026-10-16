// Teste unitare scrise de mână pentru extensie/src/calcul/sequence_matcher.js (portul lui difflib.SequenceMatcher și get_close_matches din CPython 3.13).
// Valorile sunt cele din Python, calculate o dată; cazurile cu „autojunk” (peste 200 de elemente) arată că porțiunile populare ies din potrivire, ca în Python.
// Paritatea pe mii de perechi generate de Python e în tests/paritate/primitive.test.js (difflib.json).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { SequenceMatcher, getCloseMatches } from '../../src/calcul/sequence_matcher.js';

const GRIN = String.fromCodePoint(0x1f600);

/** Cele trei rapoarte și blocurile potrivite ale perechii (a, b), în forma din tabelul de cazuri. */
function measure(a, b) {
  const matcher = new SequenceMatcher(a, b);
  return { ratio: matcher.ratio(), quick: matcher.quickRatio(), real: matcher.realQuickRatio(), blocks: matcher.getMatchingBlocks() };
}

describe('SequenceMatcher: rapoartele și blocurile potrivite din Python', () => {
  const cases = [
    // [a, b, ratio, quick_ratio, real_quick_ratio, get_matching_blocks()] în Python
    ['abcd', 'bcde', 0.75, 0.75, 1.0, [[1, 0, 3], [4, 4, 0]]],
    ['', '', 1.0, 1.0, 1.0, [[0, 0, 0]]],
    ['a', '', 0.0, 0.0, 0.0, [[1, 0, 0]]],
    ['', 'a', 0.0, 0.0, 0.0, [[0, 1, 0]]],
    ['a', 'a', 1.0, 1.0, 1.0, [[0, 0, 1], [1, 1, 0]]],
    ['abxcd', 'abcd', 0.8888888888888888, 0.8888888888888888, 0.8888888888888888, [[0, 0, 2], [3, 2, 2], [5, 4, 0]]],
    ['private Thread currentThread;', 'private volatile Thread currentThread;', 0.8656716417910447, 0.8656716417910447, 0.8656716417910447, [[0, 0, 6], [6, 15, 23], [29, 38, 0]]],
    ['aaaa', 'aaab', 0.75, 0.75, 1.0, [[0, 0, 3], [4, 4, 0]]],
    ['The quick brown fox', 'The quick brown dog', 0.8947368421052632, 0.8947368421052632, 1.0, [[0, 0, 16], [17, 17, 1], [19, 19, 0]]],
    ['abc'.repeat(70), `${'abc'.repeat(70)}d`, 0.997624703087886, 0.997624703087886, 0.997624703087886, [[0, 0, 210], [210, 211, 0]]],
    // „autojunk”: b are 200 sau mai multe elemente, iar 'a' apare de mai mult de n // 100 + 1 ori, deci devine „popular” și nu mai sprijină potrivirea
    [`${'a'.repeat(200)}b`, `${'a'.repeat(200)}c`, 0.9950248756218906, 0.9950248756218906, 1.0, [[0, 0, 200], [201, 201, 0]]],
    [`b${'a'.repeat(199)}`, `${'a'.repeat(199)}c`, 0.0, 0.995, 1.0, [[200, 200, 0]]],
    [`x${'ab'.repeat(150)}`, `${'ab'.repeat(150)}y`, 0.0, 0.9966777408637874, 1.0, [[301, 301, 0]]],
    ['Sampon anticadere Lumio 400 ml', 'Sampon anticadere Lumio 400ml', 0.9830508474576272, 0.9830508474576272, 0.9830508474576272, [[0, 0, 27], [28, 27, 2], [30, 29, 0]]],
    // un emoji e un singur element, ca în Python (len('😀a😀b') = 4)
    [`${GRIN}a${GRIN}b`, `a${GRIN}b`, 0.8571428571428571, 0.8571428571428571, 0.8571428571428571, [[1, 0, 3], [4, 3, 0]]],
    ['\u{e9}', 'e\u{301}', 0.0, 0.0, 0.6666666666666666, [[1, 2, 0]]],
    ['televizor led smart norvik 43nv5200 108 cm full hd clasa f', 'televizor led smart norvik 43nv5200, 108 cm, full hd, clasa f', 0.9747899159663865, 0.9747899159663865, 0.9747899159663865,
      [[0, 0, 35], [35, 36, 7], [42, 44, 8], [50, 53, 8], [58, 61, 0]]],
  ];
  for (const [a, b, ratio, quick, real, blocks] of cases) {
    test(`ratio(${JSON.stringify(a.slice(0, 24))}, ${JSON.stringify(b.slice(0, 24))}) = ${ratio}`, () => {
      assert.deepEqual(measure(a, b), { ratio, quick, real, blocks });
    });
  }
  test('setSeq1 și setSeq2 schimbă secvențele fără să păstreze rezultatele vechi', () => {
    const matcher = new SequenceMatcher('abcd', 'bcde');
    assert.equal(matcher.ratio(), 0.75);
    matcher.setSeq1('xyz');
    assert.equal(matcher.ratio(), 0.0);
    matcher.setSeq2('xyz');
    assert.equal(matcher.ratio(), 1.0);
    assert.equal(matcher.quickRatio(), 1.0);
  });
  test('secvențele pot fi și liste (de numere sau de text), ca în Python', () => {
    assert.equal(new SequenceMatcher([1, 2, 3, 4], [2, 3, 4, 5]).ratio(), 0.75);
    assert.equal(new SequenceMatcher(['a', 'b'], ['a', 'c']).ratio(), 0.5);
  });
});

describe('getCloseMatches: get_close_matches din Python (cuvântul e secvența b, scor descrescător, la scor egal textul mai mare câștigă)', () => {
  test('exemplul din documentația Python', () => {
    assert.deepEqual(getCloseMatches('appel', ['ape', 'apple', 'peach', 'puppy']), ['apple', 'ape']);
  });
  test('n = 1 și egalități de scor: câștigă textul mai mare după puncte de cod', () => {
    assert.deepEqual(getCloseMatches('abcd3', ['abcd1', 'abcd2', 'abcd3', 'abcd4', 'abcd0'], 1, 0.8), ['abcd3']);
    assert.deepEqual(getCloseMatches('abcd3', ['abcd1', 'abcd2', 'abcd4', 'abcd0'], 2, 0.8), ['abcd4', 'abcd2']);
    assert.deepEqual(getCloseMatches('abcd3', ['abcd1', 'abcd2', 'abcd4', 'abcd0'], 5, 0.8), ['abcd4', 'abcd2', 'abcd1', 'abcd0']);
  });
  test('fără candidați sau sub prag: listă goală; pragul de la potrivirea retururilor (0,88)', () => {
    assert.deepEqual(getCloseMatches('word', [], 1, 0.88), []);
    assert.deepEqual(getCloseMatches('televizor norvik 55', ['televizor norvik 55 inch', 'televizor norvik 50', 'xx'], 1, 0.88), ['televizor norvik 50']);
  });
  test('parametri greșiți: aceleași mesaje ca ValueError din Python', () => {
    assert.throws(() => getCloseMatches('a', ['a'], 0, 0.5), { message: 'n must be > 0: 0' });
    assert.throws(() => getCloseMatches('a', ['a'], -1, 0.5), { message: 'n must be > 0: -1' });
    assert.throws(() => getCloseMatches('a', ['a'], 1, -0.1), { message: 'cutoff must be in [0.0, 1.0]: -0.1' });
    assert.throws(() => getCloseMatches('a', ['a'], 1, 1.5), { message: 'cutoff must be in [0.0, 1.0]: 1.5' });
  });
  test('valorile implicite sunt n = 3 și cutoff = 0,6', () => {
    assert.deepEqual(getCloseMatches('abcd', ['abcd', 'abce', 'abcf', 'abcg', 'xxxx']), ['abcd', 'abcg', 'abcf']);
    assert.deepEqual(getCloseMatches('abcd', ['abce', 'abcf', 'abcg', 'xxxx']), ['abcg', 'abcf', 'abce']);
  });
});
