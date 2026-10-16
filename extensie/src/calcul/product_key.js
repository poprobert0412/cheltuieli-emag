// Cheia „același produs”: numele normalizat, fără cuvintele-culoare din config/culori.json (portul lui emag_spend/product_key.py).
// Primește: numele unui produs și lista de culori (obiectul din config/culori.json, generat în modul la build). Dă înapoi o cheie: cuvintele rămase (lipite cu spațiu), culorile scoase,
// numele normalizat (pentru potrivirea numelor trunchiate), dacă numele e trunchiat și prefixul lui. „... alb” și „... negru” au aceeași cheie; capacitatea și dimensiunea (128GB, 43", 55")
// rămân în cheie, deci sunt produse diferite. Se scot doar cuvinte întregi. Dacă după scoaterea culorilor n-ar rămâne nimic, cheia păstrează numele întreg.
// Ce NU face: nu compară prețuri și nu grupează cumpărări (price_history.js).
import { PyValueError, pyRepr, pyRstrip, sortedBy } from './python_compat.js';
import { PyPattern } from './python_regex.js';
import { TRUNCATION_MARKER } from './return_matcher.js';
import { normalizeText } from './text_normalize.js';

// Cuvintele unui nume: litere și cifre (și din alte alfabete); punctuația, „_” și „[...]” nu sunt cuvinte.
const WORD = new PyPattern(String.raw`[^\W_]+`);
// Caracterele scoase de la capătul prefixului după tăierea semnului de trunchiere (rstrip(" ,") din Python).
const PREFIX_TRAILING_CHARS = ' ,';

/** Adevărat pentru un obiect JSON (dict în Python): nu null, nu listă. */
function isDict(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Lista de culori, gata de căutat în cuvintele unui nume (intrările cu mai multe cuvinte primele). */
export class ColorWords {
  #byFirstWord = new Map();

  /** Normalizează intrările (texte); ValueError la o intrare care nu conține niciun cuvânt. Frazele duplicate se păstrează o singură dată. */
  constructor(entries) {
    const phrases = new Map(); // cheia = frazele ca listă JSON (cuvintele nu conțin spații, dar o listă nu se confundă cu alta)
    for (const entry of entries) {
      const words = WORD.findall(normalizeText(entry));
      if (words.length === 0) throw new PyValueError(`intrare de culoare fără niciun cuvânt: ${pyRepr(entry)}`);
      phrases.set(JSON.stringify(words), words);
    }
    // frazele lungi se încearcă primele (la lungime egală, în ordinea textului: ordinea de inserare din set nu contează)
    for (const phrase of sortedBy([...phrases.values()], (words) => [-words.length, words])) {
      if (!this.#byFirstWord.has(phrase[0])) this.#byFirstWord.set(phrase[0], []);
      this.#byFirstWord.get(phrase[0]).push(phrase);
    }
  }

  /** Câte culori (fraze) sunt în listă. */
  get length() {
    return [...this.#byFirstWord.values()].reduce((total, phrases) => total + phrases.length, 0);
  }

  /** [cuvintele fără culori, culorile scoase]; se potrivesc doar cuvinte întregi, iar o culoare cu mai multe cuvinte se scoate ca una singură. */
  strip(words) {
    const kept = [];
    const removed = [];
    let index = 0;
    while (index < words.length) {
      const phrase = (this.#byFirstWord.get(words[index]) ?? []).find(
        (candidate) => candidate.length <= words.length - index && candidate.every((word, offset) => words[index + offset] === word),
      );
      if (phrase === undefined) {
        kept.push(words[index]);
        index += 1;
      } else {
        removed.push(phrase.join(' '));
        index += phrase.length;
      }
    }
    return [kept, removed];
  }
}

/**
 * Validează obiectul din config/culori.json (cheia 'culori' = listă de texte) și întoarce ColorWords; ValueError cu `source` (numele configurării) dacă forma nu e cea așteptată.
 * Mesajele sunt cele din ValueError-ul Python, cu `source` (implicit numele fișierului din config/) în locul căii fișierului.
 */
export function loadColorWords(data, source = 'culori.json') {
  const colors = isDict(data) && Object.hasOwn(data, 'culori') ? data.culori : null;
  if (!Array.isArray(colors) || !colors.every((color) => typeof color === 'string')) {
    throw new PyValueError(`${source}: trebuie să conțină un obiect cu cheia 'culori' = listă de texte`);
  }
  try {
    return new ColorWords(colors);
  } catch (error) {
    if (error instanceof PyValueError) throw new PyValueError(`${source}: ${error.message}`);
    throw error;
  }
}

/** Cheia produsului `name`: cuvintele numelui normalizat, fără culori (sau întregi dacă n-ar rămâne nimic). Obiect cu cheile ProductKey: key, colors, normalized, truncated, prefix. */
export function makeProductKey(name, colorWords) {
  const normalized = normalizeText(name);
  const words = WORD.findall(normalized);
  let [kept, removed] = colorWords.strip(words);
  if (kept.length === 0) { // numele e doar o culoare: o cheie goală ar uni orice cu orice
    kept = words;
    removed = [];
  }
  return Object.freeze({
    key: kept.join(' '),
    colors: Object.freeze(removed),
    normalized,
    truncated: TRUNCATION_MARKER.search(normalized) !== null,
    prefix: pyRstrip(TRUNCATION_MARKER.sub('', normalized), PREFIX_TRAILING_CHARS),
  });
}
