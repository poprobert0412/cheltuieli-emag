// Normalizarea textului pentru comparații: fără diacritice, litere mici, spații unice (portul lui emag_spend/text_normalize.py).
// Primește: orice text (null și textul gol dau textul gol). Dă înapoi: textul normalizat, folosit la potrivirea numelor de produse și la regulile de categorii.
// Capcane tratate: NFKD vine din motorul JS, dar punctele de cod neatribuite în Unicode-ul lui Python (15.1) rămân neschimbate ca în Python, chiar dacă browserul are un Unicode mai nou;
// semnele combinate și casefold vin din tabelele Python (unicode_tables.js), iar spațiile sunt cele din Python (\s: include NEL și FS-US, nu include U+FEFF). Ce NU face: nu scoate punctuația.
import { classBody, complementRanges, isCombining, isPySpace, isUnicodeAssigned, pyCasefold } from './python_compat.js';
import { ASSIGNED_RANGES } from './unicode_tables.js';

// Punctele de cod neatribuite în Unicode-ul lui Python, ca o clasă de regex: textul obișnuit nu conține niciunul, deci verificarea e o singură trecere nativă.
const UNASSIGNED = new RegExp(`[${classBody(complementRanges(ASSIGNED_RANGES))}]`, 'u');

/**
 * NFKD ca în Python: un punct de cod pe care Python îl consideră neatribuit rămâne neschimbat și desparte textul în bucăți normalizate separat (are clasa de combinare 0, deci nu lasă
 * semnele de lângă el să se reordoneze peste el). Fără asta, un browser cu Unicode mai nou ar descompune sau ar reordona caractere pe care Python nu le știe (de exemplu U+A7F1).
 */
function nfkdAsInPython(text) {
  if (!UNASSIGNED.test(text)) return text.normalize('NFKD');
  let out = '';
  let run = '';
  for (const char of text) {
    if (isUnicodeAssigned(char.codePointAt(0))) {
      run += char;
    } else {
      out += run.normalize('NFKD') + char;
      run = '';
    }
  }
  return out + run.normalize('NFKD');
}

/**
 * Scoate diacriticele, unifică spațiile și trece la litere mici: „Țelină  Șampon” devine „telina sampon”. Același rezultat ca normalize_text din Python.
 * Ordinea contează și e cea din Python: NFKD, scoaterea semnelor combinate, spațiile unice și strip, abia apoi casefold (care poate produce semne combinate noi, de ex. İ).
 */
export function normalizeText(text) {
  if (text === null || text === undefined || text === '') return '';
  if (typeof text !== 'string') throw new TypeError(`normalize() argument 2 must be str, not ${typeof text}`);
  let out = '';
  let pendingSpace = false;
  for (const char of nfkdAsInPython(text)) {
    const code = char.codePointAt(0);
    if (isCombining(code)) continue;
    if (isPySpace(code)) {
      pendingSpace = out !== ''; // spațiile de la început se pierd, cele de la sfârșit nu se mai scriu
      continue;
    }
    if (pendingSpace) {
      out += ' ';
      pendingSpace = false;
    }
    out += char;
  }
  return pyCasefold(out);
}
