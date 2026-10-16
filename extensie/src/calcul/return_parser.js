// Citește o pagină de detalii retur eMAG și o transformă într-un ReturnRequest (portul lui emag_spend/return_parser.py).
// Primește: calea paginii și liniile ei de text (html_lines.js). Dă înapoi: ReturnRequest (cheile din to_dict) cu numărul returului, comenzile la care se referă, produsele, pașii parcurși,
// suma restituită și modul de restituire. NU citește secțiunea „Detalii de contact” (nume, e-mail, telefon, adresă) și nici codurile PIN/QR: parserul se uită doar la secțiunile de mai jos.
// Ridică ValueError (PyValueError) dacă pagina nu e un retur (sesiune expirată). Ce NU face: nu potrivește returul cu produsele comenzii (return_matcher).
import { PyValueError, pyStrip } from './python_compat.js';
import { makeReturnRequest } from './models.js';
import { parseRefundAmount } from './money_ro.js';
import { PyPattern, escapePython } from './python_regex.js';
import { normalizeText } from './text_normalize.js';

// Literele românești din numele lunii dintr-o dată de pas, atât cu virgulă (ș ț, forma corectă) cât și cu sedilă (paginile le amestecă); scrise din coduri, fiindcă literele cu sedilă nu au voie în surse.
const ROMANIAN_LETTERS = String.fromCodePoint(0x103, 0xe2, 0xee, 0x219, 0x21b, 0x15f, 0x163);

// Expresiile sunt cele din Python, cu aceleași steaguri, rulate prin PyPattern (\d și \s cu înțelesul din Python, IGNORECASE ca în re).
const RETURN_HEADER = new PyPattern(String.raw`^Retur\s*#(\d+)`, { ignoreCase: true });
const REFUND = new PyPattern(String.raw`Suma de\s*([\d.,]+)\s*(?:RON|Lei|lei)`, { ignoreCase: true });
const ORDER_REF = new PyPattern(String.raw`#(\d{5,})`);
const STEP_DATE_ANYWHERE = new PyPattern(String.raw`Data:\s*\d{1,2}\s+[A-Za-z${ROMANIAN_LETTERS}]+[^|]*`, { ignoreCase: true });

// Expresia unei etichete, construită o singură dată pe etichetă (PyPattern construiește tabele de clase, deci nu se reface la fiecare apel).
const labelPatterns = new Map();

/** Indexul primei linii egale (normalizat) cu `text`, de la `start`; null dacă nu există. */
function indexOfLine(lines, text, start = 0) {
  const wanted = normalizeText(text);
  for (let index = start; index < lines.length; index += 1) {
    if (normalizeText(lines[index]) === wanted) return index;
  }
  return null;
}

/** Expresia care scoate eticheta de la începutul unei linii (cu spațiile și „:” de lângă ea), din cache. */
function labelPattern(label) {
  if (!labelPatterns.has(label)) labelPatterns.set(label, new PyPattern(String.raw`^\s*${escapePython(label)}\s*:?\s*`, { ignoreCase: true }));
  return labelPatterns.get(label);
}

/** Valoarea unei etichete: pe aceeași linie după etichetă (cu sau fără „:”) sau pe linia următoare; șir gol dacă eticheta lipsește. */
function valueAfterLabel(lines, label) {
  const wanted = normalizeText(label);
  const pattern = labelPattern(label);
  for (let index = 0; index < lines.length; index += 1) {
    if (normalizeText(lines[index]).startsWith(wanted)) {
      const rest = pyStrip(pattern.sub('', lines[index], 1));
      if (rest) return rest;
      return index + 1 < lines.length ? pyStrip(lines[index + 1]) : '';
    }
  }
  return '';
}

/** Construiește ReturnRequest din liniile paginii de retur; ValueError (PyValueError) dacă pagina nu are „Retur #” (sesiune expirată?). */
export function parseReturn(detailPath, lines) {
  let header = null;
  for (const line of lines) {
    header = RETURN_HEADER.match(line);
    if (header) break;
  }
  if (!header) throw new PyValueError(`pagina ${detailPath} nu conține 'Retur #' (sesiune expirată?)`);

  const productsAt = indexOfLine(lines, 'Detalii comanda');
  const statusAt = indexOfLine(lines, 'Status retur');
  const contactAt = indexOfLine(lines, 'Detalii de contact', statusAt ?? 0);
  let productNames = [];
  if (productsAt !== null && statusAt !== null) productNames = lines.slice(productsAt + 1, statusAt);

  const steps = [];
  let refundBani = null;
  if (statusAt !== null) {
    const section = lines.slice(statusAt + 1, contactAt !== null ? contactAt : lines.length);
    section.forEach((line, index) => {
      if (STEP_DATE_ANYWHERE.search(line)) {
        const before = pyStrip(STEP_DATE_ANYWHERE.split(line)[0]);
        if (before) { // titlul și data pe aceeași linie
          steps.push(before);
        } else if (index > 0 && !STEP_DATE_ANYWHERE.search(section[index - 1])) {
          steps.push(section[index - 1]); // titlul pe linia de dinainte
        }
      }
    });
    const refundMatch = REFUND.search(section.join(' '));
    if (refundMatch) refundBani = parseRefundAmount(refundMatch.group(1));
  }

  const orderIds = [];
  const ordersAt = lines.findIndex((line) => normalizeText(line).startsWith('produse din comanda'));
  if (ordersAt >= 0) {
    for (const line of lines.slice(ordersAt)) {
      if (normalizeText(line).startsWith('istoricul tau')) break;
      for (const ref of ORDER_REF.finditer(line)) { // numărul poate fi lipit de alt text pe aceeași linie
        const orderId = ref.group(1);
        if (!orderIds.includes(orderId)) orderIds.push(orderId);
      }
    }
  }

  // Doar pașii CU DATĂ sunt încheiați: la un retur neprocesat, pagina listează și pașii viitori („... Receptionare produs, Restituire suma”) fără dată; ei nu înseamnă restituire.
  const normalizedSteps = steps.map((step) => normalizeText(step));
  const completed = normalizedSteps.some((step) => step.includes('restituire suma'));
  const cancelled = !completed && normalizedSteps.some((step) => step.includes('cerere anulata'));

  return makeReturnRequest({
    return_id: header.group(1),
    detail_path: detailPath,
    order_ids: orderIds,
    product_names: productNames,
    steps,
    refund_bani: refundBani,
    refund_mode: valueAfterLabel(lines, 'Modalitate restituire'),
    completed,
    cancelled,
  });
}
