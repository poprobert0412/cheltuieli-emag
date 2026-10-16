// Clasifică numele unui produs într-o categorie, după regulile din config/categorii.json (portul lui emag_spend/classifier.py).
// Primește: obiectul de reguli (citit din config/categorii.json, generat în modul la build) și, la classify, numele produsului. Dă înapoi: [categorie, modelul care a potrivit].
// Regulile sunt DATE (expresii regulate pe numele normalizat), nu cod; prima categorie care se potrivește câștigă, iar o categorie poate avea modele de EXCLUDERE. Un produs fără potrivire
// primește categoria implicită („Necategorizat”). Modelele trec prin PyPattern (python_regex.js): un model în afara subsetului acceptat (steaguri inline, lookbehind...) e refuzat la încărcare,
// cu numele categoriei, ca să nu dea alte categorii decât în Python. Regulile personale (categorii.personal.json) nu intră în v1. Ce NU face: nu citește fișiere și nu scrie nimic.
import { PyValueError, pyRepr, pyStrip } from './python_compat.js';
import { PatternSyntaxError, PyPattern, UnsupportedPattern } from './python_regex.js';
import { normalizeText } from './text_normalize.js';

const DEFAULT_CATEGORY = 'Necategorizat';

/** Adevărat pentru un obiect JSON (dict în Python): nu null, nu listă. */
function isDict(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Valoarea cheii `key` dintr-un obiect, sau `fallback` dacă lipsește (dict.get din Python; cheia prezentă cu null rămâne null). */
function getOr(object, key, fallback) {
  return Object.hasOwn(object, key) ? object[key] : fallback;
}

/** Verifică că `value` e o listă de texte nevide; ValueError cu sursa și categoria altfel. */
function patternList(value, source, category, key) {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new PyValueError(`${source}: în categoria ${pyRepr(category)}, «${key}» trebuie să fie o listă de texte`);
  }
  if (value.some((item) => pyStrip(item) === '')) {
    throw new PyValueError(`${source}: categoria ${pyRepr(category)} are un model gol în «${key}» (ar potrivi orice produs)`);
  }
  return value;
}

/** Compilează un model; o eroare de sintaxă (re.error în Python) sau o construcție în afara subsetului acceptat devine ValueError cu numele categoriei. */
function compilePattern(text, source, category) {
  try {
    return new PyPattern(text);
  } catch (error) {
    if (error instanceof PatternSyntaxError) throw new PyValueError(`${source}: expresie regulată greșită în categoria ${pyRepr(category)}: ${error.message}`);
    if (error instanceof UnsupportedPattern) {
      throw new PyValueError(`${source}: expresie regulată neacceptată de extensie în categoria ${pyRepr(category)}: ${error.construct} (modelul ${pyRepr(text)})`);
    }
    throw error;
  }
}

/**
 * Compilează lista 'categories' în [{ name, patterns, excludes }]; ValueError cu `source` (numele configurării) dacă ceva e greșit.
 * Refuză și modelele care potrivesc textul gol (ar potrivi ORICE produs: toate ar ajunge într-o singură categorie, un rezultat greșit care pare normal).
 */
function compileCategories(rules, source) {
  const entries = getOr(rules, 'categories', []);
  if (!Array.isArray(entries)) throw new PyValueError(`${source}: «categories» trebuie să fie o listă de categorii`);
  const compiled = [];
  const seen = new Set();
  for (const entry of entries) {
    if (!isDict(entry)) throw new PyValueError(`${source}: fiecare categorie trebuie să fie un obiect cu «name» și «patterns»`);
    const rawName = getOr(entry, 'name', null);
    const name = typeof rawName === 'string' ? pyStrip(rawName) : '';
    if (name === '') throw new PyValueError(`${source}: o categorie din reguli nu are nume`);
    if (seen.has(name)) throw new PyValueError(`${source}: categorie duplicată în reguli: ${pyRepr(name)}`);
    seen.add(name);
    const patternTexts = patternList(getOr(entry, 'patterns', []), source, name, 'patterns');
    const excludeTexts = patternList(getOr(entry, 'exclude', []), source, name, 'exclude');
    const patterns = patternTexts.map((text) => compilePattern(text, source, name));
    const excludes = excludeTexts.map((text) => compilePattern(text, source, name));
    if (patterns.length === 0) throw new PyValueError(`${source}: categoria ${pyRepr(name)} nu are niciun model în 'patterns'`);
    if ([...patterns, ...excludes].some((pattern) => pattern.search('') !== null)) {
      throw new PyValueError(`${source}: categoria ${pyRepr(name)} are un model care potrivește orice text (ar potrivi orice produs)`);
    }
    compiled.push({ name, patterns, excludes });
  }
  return compiled;
}

/** Aplică regulile de categorii pe numele produselor. */
export class Classifier {
  #defaultCategory;

  #categories;

  /** Compilează regulile (obiectul din config/categorii.json); ValueError cu `source` în mesaj dacă regulile sunt greșite sau un model nu poate fi tradus fidel. */
  constructor(rules, source = 'regulile de categorii') {
    if (!isDict(rules)) throw new PyValueError(`${source}: trebuie să conțină un obiect cu cheia 'categories'`);
    this.#defaultCategory = getOr(rules, 'default_category', DEFAULT_CATEGORY);
    this.#categories = compileCategories(rules, source);
  }

  /** Categoria pentru produsele fără potrivire (cheia `default_category` din reguli, implicit „Necategorizat”). */
  get defaultCategory() {
    return this.#defaultCategory;
  }

  /** Numele categoriilor, în ordinea regulilor, fără dubluri. */
  get categoryNames() {
    return [...new Set(this.#categories.map((category) => category.name))];
  }

  /** [categoria, modelul care a potrivit]; categoria implicită și modelul gol dacă nu se potrivește nimic. Numele se normalizează întâi (fără diacritice, litere mici). */
  classify(productName) {
    const text = normalizeText(productName);
    for (const { name, patterns, excludes } of this.#categories) {
      const matched = patterns.find((pattern) => pattern.search(text) !== null);
      if (matched !== undefined && !excludes.some((pattern) => pattern.search(text) !== null)) return [name, matched.source];
    }
    return [this.#defaultCategory, ''];
  }
}
