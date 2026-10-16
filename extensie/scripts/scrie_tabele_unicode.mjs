// Scrie extensie/src/calcul/unicode_tables.js din extensie/build/paritate/unicode.json (fixtura Python): tabelele care n-au echivalent exact în JS.
// Primește: opțional calea fixturii (implicit build/paritate/unicode.json). Dă înapoi: fișierul generat, cu LF și intervale compacte.
// Exportă renderTables pentru testul de prospețime (unicode.test.js: fișierul comis trebuie să fie identic cu ce ar scrie scriptul acum).
// Nu verifică tabelele față de JS (asta face unicode.test.js) și nu ghicește nimic: dacă fixtura lipsește, iese cu eroare.
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EXTENSION_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const DEFAULT_FIXTURE = path.join(EXTENSION_DIR, 'build', 'paritate', 'unicode.json');
export const TABLES_FILE = path.join(EXTENSION_DIR, 'src', 'calcul', 'unicode_tables.js');
// Câte numere încap pe un rând în fișierul generat: destul de dens ca fișierul să rămână scurt, destul de rar ca diff-ul să se citească.
const NUMBERS_PER_LINE = 12;

/** Numărul în hexazecimal cu litere mici (0x1d7ce): forma din fișierul generat, fără majuscule care ar semăna cu trimiteri la decizii. */
const hex = (value) => `0x${value.toString(16)}`;

/** Numerele în rânduri de câte NUMBERS_PER_LINE, ca fișierul generat să rămână lizibil în diff. */
function numberLines(values) {
  const lines = [];
  for (let start = 0; start < values.length; start += NUMBERS_PER_LINE) {
    lines.push(`  ${values.slice(start, start + NUMBERS_PER_LINE).map(hex).join(', ')},`);
  }
  return lines.join('\n');
}

/** [[de la, până la], ...] devine lista aplatizată [de la, până la, de la, până la, ...]. */
function flatRanges(ranges) {
  return ranges.flatMap(([from, to]) => [from, to]);
}

/** Lista CRESCĂTOARE de puncte de cod devine intervale [de la, până la] (capete incluse). */
function rangesFromCodes(codes) {
  const ranges = [];
  for (const code of codes) {
    const last = ranges[ranges.length - 1];
    if (last && last[1] + 1 === code) last[1] = code;
    else ranges.push([code, code]);
  }
  return ranges;
}

/** Împarte casefold în serii simple (cp+k se pliază în spre+k, câte `count`) și intrări complete (pliere în mai multe caractere). */
function splitCasefold(entries) {
  const runs = [];
  const full = [];
  for (const [code, folded] of entries) {
    if (folded.length !== 1) {
      full.push([code, ...folded]);
      continue;
    }
    const last = runs[runs.length - 1];
    if (last && last[0] + last[1] === code && last[2] + last[1] === folded[0]) last[1] += 1;
    else runs.push([code, 1, folded[0]]);
  }
  return { runs, full };
}

/** Textul complet al lui unicode_tables.js pentru conținutul fixturii `unicode` (un obiect deja citit din JSON). */
export function renderTables(unicode) {
  const { runs, full } = splitCasefold(unicode.casefold);
  const fullLines = full.map((row) => `  [${row.map(hex).join(', ')}],`).join('\n');
  return [
    '// GENERAT de extensie/scripts/scrie_tabele_unicode.mjs din extensie/build/paritate/unicode.json; nu edita de mână.',
    '// Regenerare: npm run paritate:genereaza, apoi npm run tabele:unicode (unicode.test.js cere fișierul identic cu ce ar scrie scriptul acum).',
    '// Tabelele vin din Python (unicodedata, str.casefold, re, str.isprintable), cu versiunea Unicode de mai jos; JavaScript nu are echivalent exact.',
    '// Intervalele sunt perechi aplatizate [de la, până la], cu capetele incluse; numerele sunt puncte de cod.',
    '',
    `export const UNIDATA_VERSION = '${unicode.unidata_version}';`,
    '',
    '// unicodedata.combining(ch) != 0: semnele combinate pe care normalize_text le scoate după NFKD.',
    'export const COMBINING_RANGES = [',
    numberLines(flatRanges(unicode.combining)),
    '];',
    '',
    '// str.isspace(), egal cu \\s din re: spațiile cu care lucrează strip(), split() și \\s.',
    'export const SPACE_RANGES = [',
    numberLines(flatRanges(rangesFromCodes(unicode.space))),
    '];',
    '',
    '// \\w din re (litere, cifre, alte caractere numerice și _).',
    'export const WORD_RANGES = [',
    numberLines(flatRanges(unicode.word)),
    '];',
    '',
    '// \\d din re (cifrele zecimale, categoria Nd).',
    'export const DIGIT_RANGES = [',
    numberLines(flatRanges(unicode.digit)),
    '];',
    '',
    '// Punctul de cod al lui 0 pentru fiecare bloc de 10 cifre zecimale consecutive (valoarea cifrei = cod - zero).',
    'export const DIGIT_ZEROS = [',
    numberLines(unicode.digit_zero),
    '];',
    '',
    '// not str.isprintable(): caracterele pe care repr() le scrie cu secvențe de scăpare.',
    'export const NONPRINTABLE_RANGES = [',
    numberLines(flatRanges(unicode.nonprintable)),
    '];',
    '',
    '// unicodedata.category(ch) != "Cn": punctele de cod atribuite în Unicode-ul lui Python. Restul rămân neschimbate la NFKD, chiar dacă un browser mai nou le cunoaște.',
    'export const ASSIGNED_RANGES = [',
    numberLines(flatRanges(unicode.assigned)),
    '];',
    '',
    '// str.casefold(), pliere de un singur caracter: tripletele aplatizate [de la, câte, spre] (cp+k se pliază în spre+k).',
    'export const CASEFOLD_SIMPLE_RUNS = [',
    numberLines(runs.flat()),
    '];',
    '',
    '// str.casefold(), pliere în mai multe caractere: [cp, rezultat...] (de exemplu ß devine ss).',
    'export const CASEFOLD_FULL = [',
    fullLines,
    '];',
    '',
  ].join('\n');
}

/** Punctul de intrare din linia de comandă: citește fixtura și scrie unicode_tables.js; fără fixtură iese cu eroare și cu instrucțiunea de generare. */
function main() {
  const source = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_FIXTURE;
  let unicode;
  try {
    unicode = JSON.parse(readFileSync(source, 'utf8'));
  } catch (error) {
    console.error(`Nu pot citi ${source}: ${error.message}. Rulează întâi npm run paritate:genereaza.`);
    process.exit(1);
  }
  writeFileSync(TABLES_FILE, renderTables(unicode), 'utf8');
  console.log(`Am scris ${TABLES_FILE} (Unicode ${unicode.unidata_version}).`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
