// Port fidel al lui difflib.SequenceMatcher și get_close_matches din CPython 3.13, cu isjunk = None și autojunk = True (cum le folosește return_matcher.py).
// Primește: două secvențe (text, numărat în puncte de cod ca în Python, sau liste de elemente comparabile cu ===). Dă înapoi: ratio, quick_ratio, real_quick_ratio
// cu aceleași numere (același șir de operații în virgulă mobilă) și blocurile potrivite [[i, j, n], ...] cu santinela finală [lungime a, lungime b, 0].
// De ce un port și nu o formulă nouă: pragul 0,88 la potrivirea retururilor decide ce retur scade din ce produs; o diferență de un bloc ar muta o sumă din an în an.
// Ce NU face: nu are isjunk (e None în tot proiectul), nu are opcodes și nu compară texte care nu sunt secvențe.
import { PyValueError, compareKeys, floorDiv, pyRepr } from './python_compat.js';

// Peste acest număr de elemente în b, cele care apar de mai mult de n // 100 + 1 ori sunt „populare” și ies din potrivire (autojunk din difflib).
const AUTOJUNK_MIN_LENGTH = 200;

/** Textul devine listă de puncte de cod (len() și indexarea din Python numără caractere, nu unități UTF-16); o listă rămâne cum e. */
function toSequence(value) {
  if (typeof value === 'string') return Array.from(value, (char) => char.codePointAt(0));
  return Array.from(value);
}

/** Ordinea blocurilor [i, j, n] ca la sort() pe tupluri din Python: după i, apoi j, apoi n. */
function compareTriples(left, right) {
  return (left[0] - right[0]) || (left[1] - right[1]) || (left[2] - right[2]);
}

/** 2,0 * potriviri / lungime, sau 1,0 pentru două secvențe goale (_calculate_ratio din difflib). */
function calculateRatio(matches, length) {
  return length ? (2.0 * matches) / length : 1.0;
}

export class SequenceMatcher {
  constructor(a = '', b = '') {
    this.autojunk = true;
    this.a = [];
    this.b = [];
    this.matchingBlocks = null;
    this.fullBCount = null;
    this.setSeqs(a, b);
  }

  /** Pune ambele secvențe. */
  setSeqs(a, b) {
    this.setSeq1(a);
    this.setSeq2(b);
  }

  /** Pune prima secvență (a); rezultatele calculate pentru cea veche se șterg. */
  setSeq1(a) {
    this.a = toSequence(a);
    this.matchingBlocks = null;
  }

  /** Pune a doua secvență (b) și îi reface indexul de poziții; aici se aplică autojunk. */
  setSeq2(b) {
    this.b = toSequence(b);
    this.matchingBlocks = null;
    this.fullBCount = null;
    this.chainB();
  }

  /** b2j: pentru fiecare element al lui b, pozițiile lui; elementele populare (autojunk) se scot. */
  chainB() {
    const b2j = new Map();
    this.b.forEach((element, index) => {
      const positions = b2j.get(element);
      if (positions) positions.push(index);
      else b2j.set(element, [index]);
    });
    const length = this.b.length;
    if (this.autojunk && length >= AUTOJUNK_MIN_LENGTH) {
      const limit = floorDiv(length, 100) + 1;
      const popular = [];
      for (const [element, positions] of b2j) if (positions.length > limit) popular.push(element);
      for (const element of popular) b2j.delete(element);
    }
    this.b2j = b2j;
  }

  /**
   * Cel mai lung bloc comun al lui a[alo:ahi] și b[blo:bhi], ca [i, j, n]; la egalitate, cel mai devreme în a, apoi în b.
   * Fără isjunk, extinderile „peste elementele junk” din difflib sunt no-op (setul bjunk e gol), deci lipsesc.
   */
  findLongestMatch(alo = 0, ahi = null, blo = 0, bhi = null) {
    const { a, b, b2j } = this;
    const aEnd = ahi === null ? a.length : ahi;
    const bEnd = bhi === null ? b.length : bhi;
    let bestI = alo;
    let bestJ = blo;
    let bestSize = 0;
    let j2len = new Map(); // j2len[j] = lungimea celui mai lung bloc fără elemente populare care se termină cu a[i-1] și b[j]
    const nothing = [];
    for (let i = alo; i < aEnd; i += 1) {
      const newJ2len = new Map();
      for (const j of b2j.get(a[i]) ?? nothing) {
        if (j < blo) continue;
        if (j >= bEnd) break;
        const k = (j2len.get(j - 1) ?? 0) + 1;
        newJ2len.set(j, k);
        if (k > bestSize) {
          bestI = i - k + 1;
          bestJ = j - k + 1;
          bestSize = k;
        }
      }
      j2len = newJ2len;
    }
    // Blocul găsit nu conține elemente populare; le adăugăm la capete, ca să nu se piardă potrivirea lor de lângă el.
    while (bestI > alo && bestJ > blo && a[bestI - 1] === b[bestJ - 1]) {
      bestI -= 1;
      bestJ -= 1;
      bestSize += 1;
    }
    while (bestI + bestSize < aEnd && bestJ + bestSize < bEnd && a[bestI + bestSize] === b[bestJ + bestSize]) bestSize += 1;
    return [bestI, bestJ, bestSize];
  }

  /** Blocurile potrivite [[i, j, n], ...] în ordine, cu cele adiacente unite și cu santinela [len(a), len(b), 0] la sfârșit. */
  getMatchingBlocks() {
    if (this.matchingBlocks !== null) return this.matchingBlocks;
    const lengthA = this.a.length;
    const lengthB = this.b.length;
    const queue = [[0, lengthA, 0, lengthB]];
    const blocks = [];
    while (queue.length > 0) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const block = this.findLongestMatch(alo, ahi, blo, bhi);
      const [i, j, k] = block;
      if (k) {
        blocks.push(block);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    blocks.sort(compareTriples);
    let i1 = 0;
    let j1 = 0;
    let k1 = 0;
    const nonAdjacent = [];
    for (const [i2, j2, k2] of blocks) {
      if (i1 + k1 === i2 && j1 + k1 === j2) {
        k1 += k2; // același bloc continuat: se lungește primul
      } else {
        if (k1) nonAdjacent.push([i1, j1, k1]);
        i1 = i2;
        j1 = j2;
        k1 = k2;
      }
    }
    if (k1) nonAdjacent.push([i1, j1, k1]);
    nonAdjacent.push([lengthA, lengthB, 0]);
    this.matchingBlocks = nonAdjacent;
    return nonAdjacent;
  }

  /** Cât de asemănătoare sunt secvențele, între 0 și 1: 2 * elemente potrivite / (len(a) + len(b)). */
  ratio() {
    const matches = this.getMatchingBlocks().reduce((sum, block) => sum + block[2], 0);
    return calculateRatio(matches, this.a.length + this.b.length);
  }

  /** Limită superioară a lui ratio: elementele comune numărate ca mulțimi, fără ordine. */
  quickRatio() {
    if (this.fullBCount === null) {
      this.fullBCount = new Map();
      for (const element of this.b) this.fullBCount.set(element, (this.fullBCount.get(element) ?? 0) + 1);
    }
    const available = new Map();
    let matches = 0;
    for (const element of this.a) {
      const count = available.has(element) ? available.get(element) : (this.fullBCount.get(element) ?? 0);
      available.set(element, count - 1);
      if (count > 0) matches += 1;
    }
    return calculateRatio(matches, this.a.length + this.b.length);
  }

  /** Limita cea mai ieftină: nu pot fi mai multe potriviri decât elementele secvenței mai scurte. */
  realQuickRatio() {
    const lengthA = this.a.length;
    const lengthB = this.b.length;
    return calculateRatio(Math.min(lengthA, lengthB), lengthA + lengthB);
  }
}

/**
 * get_close_matches din difflib: până la `n` dintre `possibilities` cu ratio >= cutoff față de `word`, cele mai bune primele.
 * Cuvântul este secvența b (autojunk se aplică lui); la scor egal câștigă textul mai mare, ca la heapq.nlargest pe perechi (scor, text).
 */
export function getCloseMatches(word, possibilities, n = 3, cutoff = 0.6) {
  if (!(n > 0)) throw new PyValueError(`n must be > 0: ${pyRepr(n)}`);
  if (!(cutoff >= 0.0 && cutoff <= 1.0)) throw new PyValueError(`cutoff must be in [0.0, 1.0]: ${pyRepr(cutoff)}`);
  const result = [];
  const matcher = new SequenceMatcher();
  matcher.setSeq2(word);
  for (const candidate of possibilities) {
    matcher.setSeq1(candidate);
    if (matcher.realQuickRatio() >= cutoff && matcher.quickRatio() >= cutoff && matcher.ratio() >= cutoff) result.push([matcher.ratio(), candidate]);
  }
  const ordered = result
    .map((pair, index) => ({ pair, index }))
    .sort((left, right) => compareKeys(right.pair, left.pair) || left.index - right.index);
  return ordered.slice(0, n).map((entry) => entry.pair[1]);
}
