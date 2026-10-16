// Traduce expresii regulate Python (re, pe text) în expresii JavaScript cu steagul u și dă un obiect cu API-ul lui re (search, match, fullmatch, findall, finditer, sub, split).
// Primește: sursa Python și steagurile IGNORECASE / DOTALL. Dă înapoi: PyPattern; construcțiile pe care traducerea nu le poate garanta ridică UnsupportedPattern cu numele lor
// (steaguri inline, lookbehind, \A \Z, referințe numerice, comentarii, grupuri atomice, cuantificatori posesivi, condiționale, \N{}, octal, IGNORECASE cu \w \W \b \B,
// aserțiuni cu cuantificator, repetiții cu iterații opționale al căror corp poate fi gol, capturi care pot lipsi dintr-o iterație, referințe la grupuri care pot lipsi),
// iar ce e greșit și în Python ridică PatternSyntaxError cu mesajul și poziția din re.error (o construcție refuzată întâlnită înaintea greșelii e semnalată prima).
// Pozițiile potrivirilor sunt în puncte de cod, ca în Python; o potrivire goală nu începe niciodată la mijlocul unei perechi surogat (V8 raportează uneori una acolo).
// Ce NU face: nu compară cu Python (asta fac testele) și nu știe de categorii sau produse. Nicio stare nu rămâne între apeluri: lastIndex se pune înainte de fiecare execuție.
import { DIGIT_RANGES, SPACE_RANGES, WORD_RANGES } from './unicode_tables.js';
import { PY_BOUNDARY, PY_NON_BOUNDARY, classBody, complementRanges, pyRepr } from './python_compat.js';

/** Construcție validă în Python, dar în afara subsetului pe care JavaScript îl garantează identic; `construct` o numește. */
export class UnsupportedPattern extends Error {
  constructor(construct, source) {
    super(`Construcție neacceptată în expresia regulată ${JSON.stringify(source)}: ${construct}`);
    this.name = 'UnsupportedPattern';
    this.construct = construct;
  }
}

/** Expresie invalidă și în Python (re.error): mesajul are forma din Python, „<motiv> at position <n>”. */
export class PatternSyntaxError extends Error {
  constructor(message) {
    super(message);
    this.name = 'PatternSyntaxError';
  }
}

/** IndexError din Python (grup inexistent la group(), nume de grup necunoscut într-un șablon); rămâne RangeError pentru cine prinde RangeError. */
export class PyIndexError extends RangeError {
  constructor(message) {
    super(message);
    this.name = 'IndexError';
  }
}

/**
 * Mesajul lui re.error pentru un text (model sau șablon, dat ca puncte de cod) la `position`: „<motiv> at position <n>”, plus linia și coloana când textul are mai multe rânduri.
 * Linia = numărul de rânduri noi dinaintea poziției + 1; coloana = poziția față de ultimul rând nou dinainte (față de începutul textului, plus 1, dacă nu există).
 */
function syntaxErrorMessage(message, chars, position) {
  let text = `${message} at position ${position}`;
  if (chars.includes('\n')) {
    let line = 1;
    let lastNewline = -1;
    for (let index = 0; index < position && index < chars.length; index += 1) {
      if (chars[index] === '\n') {
        line += 1;
        lastNewline = index;
      }
    }
    text += ` (line ${line}, column ${position - lastNewline})`;
  }
  return text;
}

// MAXREPEAT din _sre (2^32 - 1): o repetiție de acest ordin sau mai mare ridică OverflowError în Python; motorul JS (V8) acceptă numere până acolo, deci nu mai e nevoie de altă limită.
const MAX_REPEAT_PYTHON = 4294967295;
// Caracterele cu înțeles într-o expresie regulată JS cu steagul u: se scriu cu backslash când sunt literale.
const JS_SYNTAX_CHARACTERS = new Set('^$\\.*+?()[]{}|/');
// Grupul pe care Python îl consideră o singură literă la IGNORECASE (I, i, İ, ı), dar JavaScript doar I cu i: traducerea le unește.
const DOTTED_AND_DOTLESS_I = [0x49, 0x69, 0x130, 0x131];
const CONTROL_ESCAPES = new Map([['a', 7], ['f', 12], ['n', 10], ['r', 13], ['t', 9], ['v', 11]]);
const CATEGORY_LETTERS = new Set(['d', 'D', 's', 'S', 'w', 'W']);
const ANCHOR_TYPES = new Set(['bol', 'eol', 'boundary', 'nonboundary']);
const GROUP_NAME = /^[\p{XID_Start}_][\p{XID_Continue}]*$/u;
const INLINE_FLAG_LETTERS = new Set('aiLmsux');
const OCTAL_DIGITS = new Set('01234567');
const DECIMAL_DIGITS = new Set('0123456789');
const HEX_DIGITS = new Set('0123456789abcdefABCDEF');
const ASCII_LETTER = /^[A-Za-z]$/;
const ASTRAL_OR_SURROGATE = /[\ud800-\udfff]/;

const CONSTRUCT = Object.freeze({
  inlineFlags: 'steaguri inline (?i)',
  lookbehind: 'lookbehind (?<=…) sau (?<!…)',
  startOfString: '\\A',
  endOfString: '\\Z',
  numericReference: 'referință numerică la un grup (\\1)',
  comment: 'comentariu (?#…)',
  atomic: 'grup atomic (?>…)',
  possessive: 'cuantificator posesiv',
  conditional: 'condițional (?(…)…|…)',
  namedCharacter: '\\N{…}',
  octal: 'escape octal \\0',
  quantifiedAssertion: 'aserțiune cu cuantificator',
  optionalCaptureInRepeat: 'grup de captură care poate lipsi dintr-o iterație a unei repetiții',
  emptyCaptureInRepeat: 'grup de captură într-o repetiție care poate potrivi textul gol',
  emptyBodyInRepeat: 'repetiție al cărei corp poate potrivi textul gol',
  ignoreCaseWordClass: 'IGNORECASE cu \\w, \\W, \\b sau \\B',
});

// ---------- intervale și mulțimi de puncte de cod (liste aplatizate [de la, până la]) ----------

/** Lista aplatizată [de la, până la, ...] devine lista de perechi [[de la, până la], ...]. */
function flatPairs(flat) {
  const pairs = [];
  for (let index = 0; index < flat.length; index += 2) pairs.push([flat[index], flat[index + 1]]);
  return pairs;
}

/** Sortează și unește perechile [de la, până la] care se suprapun sau se ating; întoarce lista aplatizată. */
function mergeRanges(pairs) {
  const sorted = [...pairs].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged = [];
  for (const [from, to] of sorted) {
    const last = merged[merged.length - 1];
    if (last && from <= last[1] + 1) last[1] = Math.max(last[1], to);
    else merged.push([from, to]);
  }
  return merged.flat();
}

/** True dacă `code` cade într-unul dintre intervalele aplatizate (căutare liniară; folosită doar la construirea modelului). */
function rangesContain(flat, code) {
  for (let index = 0; index < flat.length; index += 2) if (code >= flat[index] && code <= flat[index + 1]) return true;
  return false;
}

const CATEGORY_FLAT = {
  d: DIGIT_RANGES,
  s: SPACE_RANGES,
  w: WORD_RANGES,
  D: complementRanges(DIGIT_RANGES),
  S: complementRanges(SPACE_RANGES),
  W: complementRanges(WORD_RANGES),
};

// ---------- analiza arborelui ----------

/** Numerele grupurilor de captură din interiorul nodului. */
function groupsIn(node, found = new Set()) {
  if (node.t === 'group') {
    if (node.capture) found.add(node.index);
    groupsIn(node.body, found);
  } else if (node.t === 'look' || node.t === 'repeat') {
    groupsIn(node.body, found);
  } else if (node.t === 'seq') {
    node.items.forEach((item) => groupsIn(item, found));
  } else if (node.t === 'alt') {
    node.branches.forEach((branch) => groupsIn(branch, found));
  }
  return found;
}

/** Lungimea minimă a unei potriviri a nodului (referințele la grupuri, aserțiunile și ancorele nu consumă nimic sigur). */
function minLength(node) {
  switch (node.t) {
    case 'lit': case 'any': case 'set': return 1;
    case 'group': return minLength(node.body);
    case 'seq': return node.items.reduce((sum, item) => sum + minLength(item), 0);
    case 'alt': return Math.min(...node.branches.map(minLength));
    case 'repeat': return node.min * minLength(node.body);
    default: return 0;
  }
}

/**
 * Parcurge arborele și întoarce grupurile SIGUR setate după nod. Refuză ce ar da alt rezultat în JS: referințe la grupuri care pot lipsi
 * (în Python ele eșuează, în JS potrivesc textul gol) și grupuri de captură care pot să nu participe la o iterație dintr-o repetiție
 * (Python păstrează valoarea iterației de dinainte, JS o șterge) sau care participă cu text gol.
 */
function checkCaptures(node, defined, source) {
  switch (node.t) {
    case 'seq': {
      let current = defined;
      for (const item of node.items) current = checkCaptures(item, current, source);
      return current;
    }
    case 'alt': {
      const results = node.branches.map((branch) => checkCaptures(branch, defined, source));
      return new Set([...results[0]].filter((index) => results.every((result) => result.has(index))));
    }
    case 'group': {
      const inner = checkCaptures(node.body, defined, source);
      return node.capture ? new Set([...inner, node.index]) : inner;
    }
    case 'look': {
      const inner = checkCaptures(node.body, defined, source);
      return node.negative ? defined : inner;
    }
    case 'backref':
      if (!defined.has(node.index)) throw new UnsupportedPattern(`referință la un grup care poate lipsi (?P=${node.name})`, source);
      return defined;
    case 'repeat': {
      const inner = checkCaptures(node.body, defined, source);
      const captured = groupsIn(node.body);
      if (node.max > 1) {
        const always = checkCaptures(node.body, new Set(), source);
        if ([...captured].some((index) => !always.has(index))) throw new UnsupportedPattern(CONSTRUCT.optionalCaptureInRepeat, source);
      }
      // O iterație opțională (peste minim) care potrivește textul gol: JS o respinge, Python o primește o dată și apoi nu mai repetă. Rezultă capturi diferite
      // («(a*)?» dă «» în Python și undefined în JS) și uneori intervale diferite («(?:|a)+» pe «aa» dă 0-0 în Python, 0-2 în JS); un corp care nu poate fi gol nu are problema.
      const hasOptionalIterations = node.max > 1 || (node.max === 1 && node.min === 0);
      if (hasOptionalIterations && minLength(node.body) === 0) throw new UnsupportedPattern(captured.size > 0 ? CONSTRUCT.emptyCaptureInRepeat : CONSTRUCT.emptyBodyInRepeat, source);
      return node.min >= 1 ? inner : defined;
    }
    default:
      return defined;
  }
}

/** IGNORECASE: \w \W \b \B se potrivesc în Python pe caracterul exact, dar JS le închide sub plierea literelor (de exemplu U+0345 ar deveni cuvânt); refuzate. */
function checkIgnoreCase(node, source) {
  const walk = (current) => {
    if (current.t === 'boundary' || current.t === 'nonboundary') throw new UnsupportedPattern(CONSTRUCT.ignoreCaseWordClass, source);
    if (current.t === 'set' && current.items.some((item) => item.k === 'cat' && (item.name === 'w' || item.name === 'W'))) {
      throw new UnsupportedPattern(CONSTRUCT.ignoreCaseWordClass, source);
    }
    if (current.t === 'group' || current.t === 'look' || current.t === 'repeat') walk(current.body);
    else if (current.t === 'seq') current.items.forEach(walk);
    else if (current.t === 'alt') current.branches.forEach(walk);
  };
  walk(node);
}

// ---------- parserul (urmează sre_parse din CPython 3.13) ----------

/** Parserul modelelor Python (urmează sre_parse din CPython 3.13): citește sursa o dată și întoarce arborele, cu erorile și refuzurile de mai sus. */
class RegexParser {
  constructor(source) {
    this.source = source;
    this.chars = Array.from(source);
    this.pos = 0;
    this.groupCount = 0;
    this.groupNames = new Map();
    this.openGroups = new Set();
  }

  /** Eroarea de sintaxă în forma lui re.error: „<motiv> at position <n>”, plus linia și coloana când modelul are mai multe rânduri. */
  error(message, position) {
    return new PatternSyntaxError(syntaxErrorMessage(message, this.chars, position));
  }

  /** Eroarea pentru o construcție în afara subsetului acceptat. */
  unsupported(construct) {
    return new UnsupportedPattern(construct, this.source);
  }

  /** Caracterul curent (punct de cod), sau undefined la sfârșit. */
  peek() {
    return this.chars[this.pos];
  }

  /** Bucata din model între două poziții (puncte de cod), pentru mesajele de eroare. */
  text(from, to) {
    return this.chars.slice(from, to).join('');
  }

  /** Arborele întregului model; o paranteză închisă în plus e eroare ca în Python. */
  parse() {
    const tree = this.parseAlternation();
    if (this.pos < this.chars.length) throw this.error('unbalanced parenthesis', this.pos);
    return tree;
  }

  /** Ramurile separate prin | (ca _parse_sub din Python). */
  parseAlternation() {
    const branches = [this.parseSequence()];
    while (this.peek() === '|') {
      this.pos += 1;
      branches.push(this.parseSequence());
    }
    return branches.length === 1 ? branches[0] : { t: 'alt', branches };
  }

  /** O secvență de elemente până la |, ) sau sfârșit; cuantificatorii se aplică ultimului element. */
  parseSequence() {
    const items = [];
    for (;;) {
      const char = this.peek();
      if (char === undefined || char === '|' || char === ')') break;
      const start = this.pos;
      this.pos += 1;
      if (char === '\\') items.push(this.parseEscape(start));
      else if (char === '[') items.push(this.parseClass(start));
      else if (char === '(') items.push(this.parseGroup(start));
      else if (char === '.') items.push({ t: 'any' });
      else if (char === '^') items.push({ t: 'bol' });
      else if (char === '$') items.push({ t: 'eol' });
      else if (char === '*') this.applyRepeat(items, 0, Infinity, start);
      else if (char === '+') this.applyRepeat(items, 1, Infinity, start);
      else if (char === '?') this.applyRepeat(items, 0, 1, start);
      else if (char === '{') this.parseBraces(items, start);
      else items.push({ t: 'lit', cp: char.codePointAt(0) });
    }
    return items.length === 1 ? items[0] : { t: 'seq', items };
  }

  /** Acoladă: cuantificator {m,n} dacă are forma corectă, altfel un { literal (ca în Python). */
  parseBraces(items, start) {
    const here = this.pos;
    if (this.peek() === '}') {
      items.push({ t: 'lit', cp: 0x7b });
      return;
    }
    let low = '';
    let high = '';
    while (DECIMAL_DIGITS.has(this.peek())) low += this.chars[this.pos++];
    if (this.peek() === ',') {
      this.pos += 1;
      while (DECIMAL_DIGITS.has(this.peek())) high += this.chars[this.pos++];
    } else {
      high = low;
    }
    if (this.peek() !== '}') {
      items.push({ t: 'lit', cp: 0x7b });
      this.pos = here;
      return;
    }
    this.pos += 1;
    let min = 0;
    let max = Infinity;
    if (low) min = Number(low);
    if (high) max = Number(high);
    if (min >= MAX_REPEAT_PYTHON || (high && max >= MAX_REPEAT_PYTHON)) throw new RangeError('the repetition number is too large');
    if (high && max < min) throw this.error('min repeat greater than max repeat', here);
    this.applyRepeat(items, min, max, start);
  }

  /** Aplică un cuantificator ultimului element: „nothing to repeat” și „multiple repeat” ca în Python; leneș cu ?, posesiv (+) refuzat. */
  applyRepeat(items, min, max, start) {
    const last = items[items.length - 1];
    if (!last || ANCHOR_TYPES.has(last.t)) throw this.error('nothing to repeat', start);
    if (last.t === 'repeat') throw this.error('multiple repeat', start);
    let lazy = false;
    if (this.peek() === '?') {
      lazy = true;
      this.pos += 1;
    } else if (this.peek() === '+') {
      throw this.unsupported(CONSTRUCT.possessive);
    }
    if (last.t === 'look') throw this.unsupported(CONSTRUCT.quantifiedAssertion);
    items[items.length - 1] = { t: 'repeat', min, max, lazy, body: last };
  }

  /** Citește exact `count` cifre hexazecimale după \x, \u sau \U; altfel „incomplete escape”. */
  readHexDigits(count, escapeStart, label) {
    let digits = '';
    while (digits.length < count && HEX_DIGITS.has(this.peek())) digits += this.chars[this.pos++];
    if (digits.length !== count) throw this.error(`incomplete escape ${label}${digits}`, escapeStart);
    return digits;
  }

  /** Escape-uri comune claselor și textului liber: litere de control, \xhh, \uhhhh, \Uhhhhhhhh, semne de punctuație; întoarce codul sau null dacă nu e unul dintre ele. */
  parseLiteralEscape(char, escapeStart) {
    if (CONTROL_ESCAPES.has(char)) return CONTROL_ESCAPES.get(char);
    if (char === 'x') return parseInt(this.readHexDigits(2, escapeStart, '\\x'), 16);
    if (char === 'u') return parseInt(this.readHexDigits(4, escapeStart, '\\u'), 16);
    if (char === 'U') {
      const code = parseInt(this.readHexDigits(8, escapeStart, '\\U'), 16);
      if (code > 0x10ffff) throw this.error(`bad escape ${this.text(escapeStart, this.pos)}`, escapeStart);
      return code;
    }
    if (char === 'N') throw this.unsupported(CONSTRUCT.namedCharacter);
    if (!ASCII_LETTER.test(char) && !DECIMAL_DIGITS.has(char)) return char.codePointAt(0);
    return null;
  }

  /** Escape-ul de după backslash în afara claselor: categorii, limite, caractere de control, coduri, referințe; ce nu e permis ridică eroare sau refuz. */
  parseEscape(start) {
    const char = this.chars[this.pos];
    if (char === undefined) throw this.error('bad escape (end of pattern)', start);
    this.pos += 1;
    if (CATEGORY_LETTERS.has(char)) return { t: 'set', negate: false, items: [{ k: 'cat', name: char }] };
    if (char === 'b') return { t: 'boundary' };
    if (char === 'B') return { t: 'nonboundary' };
    if (char === 'A') throw this.unsupported(CONSTRUCT.startOfString);
    if (char === 'Z') throw this.unsupported(CONSTRUCT.endOfString);
    if (char === '0') throw this.unsupported(CONSTRUCT.octal);
    if (DECIMAL_DIGITS.has(char)) return this.parseGroupReference(char, start);
    const code = this.parseLiteralEscape(char, start);
    if (code === null) throw this.error(`bad escape \\${char}`, start);
    return { t: 'lit', cp: code };
  }

  /** \1 ... \99: Python hotărăște între grup, octal și eroare; aici fie eroarea lui, fie refuzul construcției. */
  parseGroupReference(first, start) {
    let digits = first;
    if (DECIMAL_DIGITS.has(this.peek())) {
      digits += this.chars[this.pos++];
      if (OCTAL_DIGITS.has(first) && OCTAL_DIGITS.has(digits[1]) && OCTAL_DIGITS.has(this.peek())) throw this.unsupported(CONSTRUCT.octal);
    }
    const group = Number(digits);
    if (group > this.groupCount) throw this.error(`invalid group reference ${group}`, start + 1);
    if (this.openGroups.has(group)) throw this.error('cannot refer to an open group', start);
    throw this.unsupported(CONSTRUCT.numericReference);
  }

  /** Escape-ul de după backslash într-o clasă (\b e backspace aici, referințele numerice nu sunt permise). */
  parseClassEscape(start) {
    const char = this.chars[this.pos];
    if (char === undefined) throw this.error('bad escape (end of pattern)', start);
    this.pos += 1;
    if (CATEGORY_LETTERS.has(char)) return { k: 'cat', name: char };
    if (char === 'b') return { k: 'cp', cp: 8 };
    const code = this.parseLiteralEscape(char, start);
    if (code === null) throw this.error(`bad escape \\${char}`, start);
    return { k: 'cp', cp: code };
  }

  /** Clasa [...] cu intervale și categorii, ca în Python: ] primul e literal, - la capăt e literal, interval greșit e eroare. */
  parseClass(start) {
    const items = [];
    let negate = false;
    if (this.peek() === '^') {
      negate = true;
      this.pos += 1;
    }
    for (;;) {
      const tokenStart = this.pos;
      const first = this.chars[this.pos];
      if (first === undefined) throw this.error('unterminated character set', start);
      this.pos += 1;
      if (first === ']' && items.length > 0) break;
      const low = first === '\\' ? this.parseClassEscape(tokenStart) : { k: 'cp', cp: first.codePointAt(0) };
      if (this.peek() === '-') {
        this.pos += 1;
        const secondStart = this.pos;
        const second = this.chars[this.pos];
        if (second === undefined) throw this.error('unterminated character set', start);
        this.pos += 1;
        if (second === ']') {
          items.push(low, { k: 'cp', cp: 0x2d });
          break;
        }
        const high = second === '\\' ? this.parseClassEscape(secondStart) : { k: 'cp', cp: second.codePointAt(0) };
        if (low.k !== 'cp' || high.k !== 'cp' || high.cp < low.cp) throw this.error(`bad character range ${this.text(tokenStart, this.pos)}`, tokenStart);
        items.push({ k: 'range', lo: low.cp, hi: high.cp });
      } else {
        items.push(low);
      }
    }
    return { t: 'set', negate, items };
  }

  /** Citește un nume până la `terminator` ca getuntil din Python (mesaje și poziții identice). */
  readName(terminator, what) {
    let name = '';
    for (;;) {
      const char = this.chars[this.pos];
      this.pos += 1;
      if (char === undefined) {
        if (!name) throw this.error(`missing ${what}`, this.chars.length);
        throw this.error(`missing ${terminator}, unterminated name`, this.chars.length - name.length);
      }
      if (char === terminator) {
        if (!name) throw this.error(`missing ${what}`, this.pos - 1);
        return name;
      }
      name += char;
    }
  }

  /** Consumă paranteza de închidere a grupului început la `start`, sau ridică „missing )”. */
  expectClosing(start) {
    if (this.peek() !== ')') throw this.error('missing ), unterminated subpattern', start);
    this.pos += 1;
  }

  /** Numele de grup trebuie să fie identificator Python, altfel „bad character in group name”. */
  checkName(name, nameStart) {
    if (!GROUP_NAME.test(name)) throw this.error(`bad character in group name ${pyRepr(name)}`, nameStart);
  }

  /** Grup după (: captură, necaptură, cu nume, referință la nume, aserțiune înainte; restul ridică eroarea Python sau refuzul construcției. */
  parseGroup(start) {
    let capture = true;
    let name = null;
    if (this.peek() === '?') {
      this.pos += 1;
      const char = this.chars[this.pos];
      if (char === undefined) throw this.error('unexpected end of pattern', this.pos);
      this.pos += 1;
      if (char === 'P') {
        const next = this.chars[this.pos];
        if (next === '<') {
          this.pos += 1;
          const nameStart = this.pos;
          name = this.readName('>', 'group name');
          this.checkName(name, nameStart);
        } else if (next === '=') {
          this.pos += 1;
          const nameStart = this.pos;
          const reference = this.readName(')', 'group name');
          this.checkName(reference, nameStart);
          if (!this.groupNames.has(reference)) throw this.error(`unknown group name ${pyRepr(reference)}`, nameStart);
          const index = this.groupNames.get(reference);
          if (this.openGroups.has(index)) throw this.error('cannot refer to an open group', nameStart);
          return { t: 'backref', name: reference, index };
        } else {
          if (next === undefined) throw this.error('unexpected end of pattern', this.pos);
          this.pos += 1;
          throw this.error(`unknown extension ?P${next}`, start + 1);
        }
      } else if (char === ':') {
        capture = false;
      } else if (char === '#') {
        for (;;) {
          if (this.pos >= this.chars.length) throw this.error('missing ), unterminated comment', start);
          if (this.chars[this.pos++] === ')') break;
        }
        throw this.unsupported(CONSTRUCT.comment);
      } else if (char === '=' || char === '!') {
        const body = this.parseAlternation();
        this.expectClosing(start);
        return { t: 'look', negative: char === '!', body };
      } else if (char === '<') {
        const next = this.chars[this.pos];
        if (next === undefined) throw this.error('unexpected end of pattern', this.pos);
        if (next !== '=' && next !== '!') throw this.error(`unknown extension ?<${next}`, start + 1);
        throw this.unsupported(CONSTRUCT.lookbehind);
      } else if (char === '(') {
        throw this.unsupported(CONSTRUCT.conditional);
      } else if (char === '>') {
        throw this.unsupported(CONSTRUCT.atomic);
      } else if (INLINE_FLAG_LETTERS.has(char) || char === '-') {
        this.skipInlineFlags(char);
        throw this.unsupported(CONSTRUCT.inlineFlags);
      } else {
        throw this.error(`unknown extension ?${char}`, start + 1);
      }
    }
    let index = 0;
    if (capture) {
      this.groupCount += 1;
      index = this.groupCount;
      if (name !== null) {
        if (this.groupNames.has(name)) {
          throw this.error(`redefinition of group name ${pyRepr(name)} as group ${index}; was group ${this.groupNames.get(name)}`, this.pos - name.length - 1);
        }
        this.groupNames.set(name, index);
      }
      this.openGroups.add(index);
    }
    const body = this.parseAlternation();
    this.expectClosing(start);
    if (capture) this.openGroups.delete(index);
    return { t: 'group', capture, index, name, body };
  }

  /** Parcurge steagurile unui (?aiLmsux-…) ca să dea eroarea lui Python când sunt greșite; dacă sunt corecte, apelantul refuză construcția. */
  skipInlineFlags(first) {
    let char = first;
    if (char !== '-') {
      for (;;) {
        char = this.chars[this.pos];
        if (char === undefined) throw this.error('missing -, : or )', this.chars.length);
        this.pos += 1;
        if (char === ')' || char === '-' || char === ':') break;
        if (!INLINE_FLAG_LETTERS.has(char)) throw this.error(/\p{L}/u.test(char) ? 'unknown flag' : 'missing -, : or )', this.pos - 1);
      }
    }
  }
}

// ---------- emiterea expresiei JS ----------

/** Scrie arborele ca sursă de expresie regulată JavaScript (steagul u), cu clasele Unicode din tabelele Python. */
class Emitter {
  constructor(ignoreCase, dotAll) {
    this.ignoreCase = ignoreCase;
    this.dotAll = dotAll;
  }

  /** Un caracter literal ca sursă JS (scăpat unde e nevoie); la IGNORECASE, grupul I i İ ı devine o clasă. */
  literal(code) {
    if (this.ignoreCase && DOTTED_AND_DOTLESS_I.includes(code)) return `[${classBody(DOTTED_AND_DOTLESS_I.slice().sort((a, b) => a - b).flatMap((value) => [value, value]))}]`;
    const char = String.fromCodePoint(code);
    if (JS_SYNTAX_CHARACTERS.has(char)) return `\\${char}`;
    if (/^[A-Za-z0-9_]$/.test(char) || (code >= 0x20 && code < 0x7f && char !== '-' && char !== '\\')) return char;
    if (char === '-') return '-';
    return `\\u{${code.toString(16)}}`;
  }

  /** O clasă ca sursă JS: unește elementele, adaugă grupul I i İ ı la IGNORECASE; categoriile (\d \s \w) vin din tabelele Python. */
  set(node) {
    const pairs = [];
    for (const item of node.items) {
      if (item.k === 'cp') pairs.push([item.cp, item.cp]);
      else if (item.k === 'range') pairs.push([item.lo, item.hi]);
      else pairs.push(...flatPairs(CATEGORY_FLAT[item.name]));
    }
    if (this.ignoreCase) {
      const flat = mergeRanges(pairs);
      if (DOTTED_AND_DOTLESS_I.some((code) => rangesContain(flat, code))) pairs.push(...DOTTED_AND_DOTLESS_I.map((code) => [code, code]));
    }
    return `[${node.negate ? '^' : ''}${classBody(mergeRanges(pairs))}]`;
  }

  /** Cuantificatorul în forma cea mai scurtă (*, +, ?, {n}, {n,}, {n,m}), cu ? la sfârșit pentru leneș. */
  quantifier(node) {
    let text;
    if (node.min === 0 && node.max === Infinity) text = '*';
    else if (node.min === 1 && node.max === Infinity) text = '+';
    else if (node.min === 0 && node.max === 1) text = '?';
    else if (node.max === Infinity) text = `{${node.min},}`;
    else if (node.min === node.max) text = `{${node.min}}`;
    else text = `{${node.min},${node.max}}`;
    return node.lazy ? `${text}?` : text;
  }

  /** Sursa JS pentru un nod al arborelui. */
  emit(node) {
    switch (node.t) {
      case 'lit': return this.literal(node.cp);
      case 'any': return this.dotAll ? '[^]' : '[^\\n]';
      case 'bol': return '^';
      case 'eol': return '(?:$|(?=\\n$))';
      case 'boundary': return PY_BOUNDARY;
      case 'nonboundary': return PY_NON_BOUNDARY;
      case 'set': {
        // \D \S \W izolate se scriu ca mulțime negată (sursă mai scurtă); în interiorul unei clase se folosesc intervalele complementare
        if (node.items.length === 1 && node.items[0].k === 'cat' && /[DSW]/.test(node.items[0].name) && !node.negate) {
          return `[^${classBody(CATEGORY_FLAT[node.items[0].name.toLowerCase()])}]`;
        }
        return this.set(node);
      }
      case 'group': return `${node.capture ? (node.name ? `(?<${node.name}>` : '(') : '(?:'}${this.emit(node.body)})`;
      case 'look': return `${node.negative ? '(?!' : '(?='}${this.emit(node.body)})`;
      case 'backref': return `\\k<${node.name}>`;
      case 'repeat': return this.emit(node.body) + this.quantifier(node);
      case 'seq': return node.items.map((item) => this.emit(item)).join('');
      case 'alt': return node.branches.map((branch) => this.emit(branch)).join('|');
      default: throw new Error(`nod necunoscut: ${node.t}`);
    }
  }
}

// ---------- șabloanele de înlocuire din sub ----------

/**
 * Tokenizatorul șabloanelor din re._parser (Python 3.13): un token e un caracter sau un backslash urmat de un caracter; `next` e tokenul curent (null la sfârșit),
 * iar `index` e poziția de după el. Pozițiile din erori se numără în puncte de cod, ca în Python.
 */
class TemplateTokenizer {
  constructor(template) {
    this.chars = Array.from(template);
    this.index = 0;
    this.next = null;
    this.advance();
  }

  /** Citește următorul token în `next`; un backslash la sfârșit ridică „bad escape (end of pattern)” (la fel ca în Python, deja când se consumă tokenul dinainte). */
  advance() {
    let index = this.index;
    if (index >= this.chars.length) {
      this.next = null;
      return;
    }
    let token = this.chars[index];
    if (token === '\\') {
      index += 1;
      if (index >= this.chars.length) throw new PatternSyntaxError(syntaxErrorMessage('bad escape (end of pattern)', this.chars, this.chars.length - 1));
      token += this.chars[index];
    }
    this.index = index + 1;
    this.next = token;
  }

  /** Tokenul curent, după care trece la următorul. */
  get() {
    const token = this.next;
    this.advance();
    return token;
  }

  /** Consumă tokenul curent dacă e `token`. */
  match(token) {
    if (this.next !== token) return false;
    this.advance();
    return true;
  }

  /** Poziția în șablon a tokenului curent. */
  tell() {
    return this.index - (this.next === null ? 0 : Array.from(this.next).length);
  }

  /** Eroarea de sintaxă la poziția curentă minus `offset`. */
  error(message, offset = 0) {
    return new PatternSyntaxError(syntaxErrorMessage(message, this.chars, this.tell() - offset));
  }

  /** Tokenii până la `terminator` (consumat), ca text; fără terminator sau fără nimic înaintea lui ridică erorile din Python. */
  getUntil(terminator, name) {
    let result = '';
    let length = 0;
    for (;;) {
      const token = this.next;
      this.advance();
      if (token === null) {
        if (result === '') throw this.error(`missing ${name}`);
        throw this.error(`missing ${terminator}, unterminated name`, length);
      }
      if (token === terminator) {
        if (result === '') throw this.error(`missing ${name}`, 1);
        return result;
      }
      result += token;
      length += Array.from(token).length;
    }
  }
}

// Secvențele din șablon care înseamnă un caracter (ESCAPES din re._parser): \a \b \f \n \r \t \v \\.
const TEMPLATE_ESCAPES = new Map([['a', '\x07'], ['b', '\b'], ['f', '\f'], ['n', '\n'], ['r', '\r'], ['t', '\t'], ['v', '\x0b'], ['\\', '\\']]);

/**
 * Descompune un șablon Python (\g<nume>, \1, \012, \n, \\...) în bucăți: text și referințe la grup ({ group: număr }). Port al lui parse_template din Python 3.13:
 * erorile apar în ordinea citirii, de la stânga la dreapta, cu mesajul și poziția din Python, și fără nicio potrivire (un nume necunoscut ridică IndexError).
 */
function parseTemplate(template, pattern) {
  const source = new TemplateTokenizer(template);
  const pieces = [];
  let literal = '';
  const addLiteral = () => {
    if (literal) pieces.push(literal);
    literal = '';
  };
  const addGroup = (index, offset) => {
    if (BigInt(index) > BigInt(pattern.groups)) throw source.error(`invalid group reference ${index}`, offset);
    addLiteral();
    pieces.push({ group: Number(index) });
  };
  for (let token = source.get(); token !== null; token = source.get()) {
    if (token[0] !== '\\') {
      literal += token;
      continue;
    }
    const c = token.slice(1);
    if (c === 'g') {
      if (!source.match('<')) throw source.error('missing <');
      const name = source.getUntil('>', 'group name');
      const nameLength = Array.from(name).length;
      if (/^[0-9]+$/.test(name)) {
        addGroup(BigInt(name), nameLength + 1); // fără zerouri din față, ca int(name) în Python; și numerele uriașe se scriu exact în mesaj
      } else {
        if (!GROUP_NAME.test(name)) throw source.error(`bad character in group name ${pyRepr(name)}`, nameLength + 1);
        if (!pattern.groupIndex.has(name)) throw new PyIndexError(`unknown group name ${pyRepr(name)}`);
        addGroup(pattern.groupIndex.get(name), nameLength + 1);
      }
    } else if (c === '0') { // escape octal: \0 urmat de cel mult încă două cifre octale
      let octal = '0';
      if (OCTAL_DIGITS.has(source.next)) {
        octal += source.get();
        if (OCTAL_DIGITS.has(source.next)) octal += source.get();
      }
      literal += String.fromCharCode(parseInt(octal, 8) & 0xff);
    } else if (DECIMAL_DIGITS.has(c)) { // \1 .. \99 referință la grup, sau \ddd octal (trei cifre octale, cea dintâi 1-3)
      let digits = c;
      let isOctal = false;
      if (DECIMAL_DIGITS.has(source.next)) {
        digits += source.get();
        if (OCTAL_DIGITS.has(c) && OCTAL_DIGITS.has(digits[1]) && OCTAL_DIGITS.has(source.next)) {
          digits += source.get();
          isOctal = true;
          const value = parseInt(digits, 8);
          if (value > 0o377) throw source.error(`octal escape value \\${digits} outside of range 0-0o377`, digits.length + 1);
          literal += String.fromCharCode(value);
        }
      }
      if (!isOctal) addGroup(Number(digits), digits.length);
    } else if (TEMPLATE_ESCAPES.has(c)) {
      literal += TEMPLATE_ESCAPES.get(c);
    } else if (ASCII_LETTER.test(c)) {
      throw source.error(`bad escape ${token}`, 2);
    } else {
      literal += token; // o secvență necunoscută care nu e literă (\&, \., \é) rămâne cu tot cu backslash
    }
  }
  addLiteral();
  return pieces;
}

// ---------- potrivirea și obiectul PyMatch ----------

/** Poziția în puncte de cod (ca în Python) pentru o poziție în unități UTF-16 (ca în JS). */
function codePointIndex(text, utf16Index) {
  if (!ASTRAL_OR_SURROGATE.test(text)) return utf16Index;
  let count = 0;
  for (const _ of text.slice(0, utf16Index)) count += 1;
  return count;
}

// Jumătățile unei perechi surogat (un caracter de dincolo de BMP se scrie în JS cu două unități UTF-16: prima în D800-DBFF, a doua în DC00-DFFF).
const LEAD_SURROGATE_FIRST = 0xd800;
const LEAD_SURROGATE_LAST = 0xdbff;
const TRAIL_SURROGATE_FIRST = 0xdc00;
const TRAIL_SURROGATE_LAST = 0xdfff;

/** True dacă `index` cade între cele două jumătăți ale unei perechi surogat din `text`: o poziție la care o potrivire nu poate începe, nici în Python, nici în specificația JS. */
function isInsideSurrogatePair(text, index) {
  if (index <= 0 || index >= text.length) return false;
  const unit = text.charCodeAt(index);
  const previous = text.charCodeAt(index - 1);
  return unit >= TRAIL_SURROGATE_FIRST && unit <= TRAIL_SURROGATE_LAST && previous >= LEAD_SURROGATE_FIRST && previous <= LEAD_SURROGATE_LAST;
}

/**
 * exec din poziția `from` cu un RegExp global, fără potriviri la mijlocul unei perechi surogat. De ce: V8 (Node 24) raportează uneori acolo o potrivire GOALĂ când expresia
 * începe cu o aserțiune (de exemplu /(?![^a]b)/u pe «😀b» dă indexul 1, nu 2), iar apoi finditer s-ar învârti la nesfârșit; se reia căutarea de după acel loc.
 */
function execFrom(regExp, text, from) {
  let position = from;
  for (;;) {
    regExp.lastIndex = position;
    const found = regExp.exec(text);
    if (found === null || !isInsideSurrogatePair(text, found.index)) return found;
    position = found.index + 1;
  }
}

/** TypeError dacă `text` nu e șir, ca re din Python. */
function assertText(text) {
  if (typeof text !== 'string') throw new TypeError(`expected string or bytes-like object, got '${text === null ? 'NoneType' : typeof text}'`);
}

/** O potrivire, cu aceleași metode ca re.Match: group, groups, groupdict, start, end, span (puncte de cod) și string. */
export class PyMatch {
  constructor(pattern, text, raw) {
    this.pattern = pattern;
    this.string = text;
    this.raw = raw;
  }

  /** Numărul grupului pentru un număr sau un nume; „no such group” dacă nu există. */
  groupNumber(which) {
    if (typeof which === 'string') {
      if (!this.pattern.groupIndex.has(which)) throw new PyIndexError('no such group');
      return this.pattern.groupIndex.get(which);
    }
    if (!Number.isInteger(which) || which < 0 || which > this.pattern.groups) throw new PyIndexError('no such group');
    return which;
  }

  /** Textul grupului (0 = toată potrivirea); `null` dacă grupul n-a participat. Cu mai multe argumente întoarce o listă. */
  group(...which) {
    if (which.length === 0) return this.raw[0];
    const values = which.map((entry) => this.raw[this.groupNumber(entry)] ?? null);
    return values.length === 1 ? values[0] : values;
  }

  /** Textele grupurilor 1..n (`defaultValue` pentru cele fără participare). */
  groups(defaultValue = null) {
    return Array.from({ length: this.pattern.groups }, (_, index) => this.raw[index + 1] ?? defaultValue);
  }

  /** Grupurile cu nume ca obiect {nume: text}. */
  groupdict(defaultValue = null) {
    const result = {};
    for (const [name, index] of this.pattern.groupIndex) result[name] = this.raw[index] ?? defaultValue;
    return result;
  }

  /** [început, sfârșit] în unități UTF-16 (pentru felii JS), sau [-1, -1] dacă grupul n-a participat. */
  utf16Span(which = 0) {
    const pair = this.raw.indices[this.groupNumber(which)];
    return pair ? [pair[0], pair[1]] : [-1, -1];
  }

  /** Începutul grupului în unități UTF-16. */
  utf16Start(which = 0) {
    return this.utf16Span(which)[0];
  }

  /** Sfârșitul grupului în unități UTF-16. */
  utf16End(which = 0) {
    return this.utf16Span(which)[1];
  }

  /** [început, sfârșit] în puncte de cod ca span() din Python; [-1, -1] dacă grupul n-a participat. */
  span(which = 0) {
    const [from, to] = this.utf16Span(which);
    return from < 0 ? [-1, -1] : [codePointIndex(this.string, from), codePointIndex(this.string, to)];
  }

  /** Începutul grupului în puncte de cod (ca start() din Python). */
  start(which = 0) {
    return this.span(which)[0];
  }

  /** Sfârșitul grupului în puncte de cod (ca end() din Python). */
  end(which = 0) {
    return this.span(which)[1];
  }
}

/** Expresie regulată Python tradusă în JS; vezi antetul modulului pentru ce se acceptă și ce se refuză. */
export class PyPattern {
  constructor(source, { ignoreCase = false, dotAll = false } = {}) {
    if (typeof source !== 'string') throw new TypeError('sursa expresiei trebuie să fie text');
    const parser = new RegexParser(source);
    const tree = parser.parse();
    if (ignoreCase) checkIgnoreCase(tree, source);
    checkCaptures(tree, new Set(), source);
    this.source = source;
    this.ignoreCase = ignoreCase;
    this.dotAll = dotAll;
    this.groups = parser.groupCount;
    this.groupIndex = new Map(parser.groupNames);
    this.jsSource = new Emitter(ignoreCase, dotAll).emit(tree);
    this.flags = `ud${ignoreCase ? 'i' : ''}`;
    this.cache = {};
    this.variant('global'); // construit acum: o expresie pe care JS nu o acceptă ridică eroarea la creare, nu la prima folosire
  }

  /** RegExp-ul cu steagurile suplimentare cerute (g sau y), creat o dată; lastIndex se pune la fiecare folosire. */
  variant(kind) {
    if (!this.cache[kind]) {
      if (kind === 'global') this.cache[kind] = new RegExp(this.jsSource, `${this.flags}g`);
      else if (kind === 'sticky') this.cache[kind] = new RegExp(this.jsSource, `${this.flags}y`);
      else this.cache[kind] = new RegExp(`(?:${this.jsSource})$`, `${this.flags}y`);
    }
    return this.cache[kind];
  }

  /** Rezultatul exec ca PyMatch (null rămâne null). */
  wrap(text, raw) {
    return raw === null ? null : new PyMatch(this, text, raw);
  }

  /** re.search: prima potrivire oriunde în text, sau null. */
  search(text) {
    assertText(text);
    return this.wrap(text, execFrom(this.variant('global'), text, 0));
  }

  /** re.match: potrivire ancorată la început. */
  match(text) {
    assertText(text);
    const regExp = this.variant('sticky');
    regExp.lastIndex = 0;
    return this.wrap(text, regExp.exec(text));
  }

  /** re.fullmatch: potrivirea trebuie să acopere tot textul (se reîncearcă alternativele până se potrivește sfârșitul). */
  fullmatch(text) {
    assertText(text);
    const regExp = this.variant('full');
    regExp.lastIndex = 0;
    return this.wrap(text, regExp.exec(text));
  }

  /** Potrivirea nevidă care începe exact la `position`, cu aceleași reîncercări de alternative ca în Python după o potrivire goală. */
  nonEmptyAt(text, position) {
    const before = codePointIndex(text, position);
    const regExp = new RegExp(`(?:${this.jsSource})(?<!^[^]{${before}})`, `${this.flags}y`);
    regExp.lastIndex = position;
    return regExp.exec(text);
  }

  /** Potrivirile succesive ca în finditer din Python 3.7+: după una goală se caută una nevidă în același loc înainte să se avanseze. */
  * rawMatches(text) {
    let position = 0;
    let mustAdvance = false;
    const regExp = this.variant('global');
    for (;;) {
      let found = null;
      let from = position;
      if (mustAdvance) {
        found = this.nonEmptyAt(text, position);
        from = position < text.length && text.codePointAt(position) > 0xffff ? position + 2 : position + 1;
      }
      if (!found) {
        if (from > text.length) return;
        found = execFrom(regExp, text, from);
        // Un motor care ar întoarce o potrivire dinaintea punctului de plecare ne-ar învârti la nesfârșit (și ar umple memoria): mai bine o eroare clară.
        if (found !== null && found.index < from) throw new Error(`motorul de expresii regulate a întors o potrivire la ${found.index}, înaintea poziției ${from} de la care se căuta`);
      }
      if (!found) return;
      yield found;
      const end = found.index + found[0].length;
      mustAdvance = end === found.index;
      position = end;
    }
  }

  /** re.finditer, ca listă de PyMatch. */
  finditer(text) {
    assertText(text);
    return [...this.rawMatches(text)].map((raw) => new PyMatch(this, text, raw));
  }

  /** re.findall: textele potrivirilor; cu un grup, textul grupului; cu mai multe, liste de grupuri (text gol pentru grupurile fără participare). */
  findall(text) {
    assertText(text);
    return [...this.rawMatches(text)].map((raw) => {
      if (this.groups === 0) return raw[0];
      if (this.groups === 1) return raw[1] ?? '';
      return Array.from({ length: this.groups }, (_, index) => raw[index + 1] ?? '');
    });
  }

  /** re.sub: `repl` e text cu referințe (\1, \g<nume>, \n, \\) sau funcție de PyMatch; `count` 0 = toate. */
  sub(repl, text, count = 0) {
    assertText(text);
    let expand;
    if (typeof repl === 'function') {
      expand = (match) => {
        const value = repl(match);
        if (typeof value !== 'string') throw new TypeError('funcția de înlocuire trebuie să întoarcă text');
        return value;
      };
    } else {
      assertText(repl);
      const pieces = parseTemplate(repl, this);
      expand = (match) => pieces.map((piece) => (typeof piece === 'string' ? piece : (match.group(piece.group) ?? ''))).join('');
    }
    let out = '';
    let last = 0;
    let done = 0;
    for (const raw of this.rawMatches(text)) {
      if (count > 0 && done >= count) break;
      out += text.slice(last, raw.index) + expand(new PyMatch(this, text, raw));
      last = raw.index + raw[0].length;
      done += 1;
    }
    return out + text.slice(last);
  }

  /** re.split: bucățile dintre potriviri, cu grupurile potrivirilor intercalate (null pentru cele fără participare); `maxsplit` 0 = fără limită. */
  split(text, maxsplit = 0) {
    assertText(text);
    const pieces = [];
    let last = 0;
    let splits = 0;
    for (const raw of this.rawMatches(text)) {
      if (maxsplit > 0 && splits >= maxsplit) break;
      pieces.push(text.slice(last, raw.index));
      for (let group = 1; group <= this.groups; group += 1) pieces.push(raw[group] ?? null);
      last = raw.index + raw[0].length;
      splits += 1;
    }
    pieces.push(text.slice(last));
    return pieces;
  }
}

// ---------- re.escape ----------

const ESCAPED_BY_RE_ESCAPE = new Set('()[]{}?*+-|^$\\.&~# \t\n\r\v\f');

/** re.escape din Python 3.7+: doar caracterele speciale primesc backslash (spațiul, #, &, ~ și - includse); literele, cifrele și Unicode-ul nu. */
export function escapePython(text) {
  let out = '';
  for (const char of text) out += ESCAPED_BY_RE_ESCAPE.has(char) ? `\\${char}` : char;
  return out;
}
