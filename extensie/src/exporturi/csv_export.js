// Registrul complet de produse ca text CSV pe care îl deschizi în Excel (portul lui emag_spend/csv_export.py).
// Primește: liniile de registru (LineOutcome) și pragul pentru „achiziție mare” în bani. Dă înapoi: textul lui produse.csv (separator „;”, zecimale cu virgulă, rânduri CRLF, BOM UTF-8 la început), nu scrie fișiere.
// Coloana link_comanda = adresa comenzii pe eMAG (doar pentru numere valide, order_links.js); platit_linie_lei / platit_pastrat_lei = sumele plătite, după partea produsului din reducerile blocului.
// Celulele de TEXT vin din pagini controlate de vânzători: dacă încep cu = + - @ sau TAB/CR, Excel le-ar citi ca formulă (CSV injection), deci textCell pune un apostrof în față; sumele generate de program (și cele negative) nu se ating.
// textCell și leiCell le folosește și price_history_csv.js. Ce NU face: nu calculează liniile și nu descarcă nimic (descarcare.js).
import { orderUrl } from '../calcul/order_links.js';
import { cpSlice, pyCsvRow, pyDivmod, pyLstrip } from '../calcul/python_compat.js';

// Primul caracter al fișierului: Excel îl cere ca să citească diacriticele ca UTF-8 (utf-8-sig în Python).
const UTF8_BOM = '\u{feff}';

const HEADER = [
  'comanda', 'link_comanda', 'data', 'an', 'vanzator', 'produs', 'categorie', 'regula_categorie',
  'cantitate', 'valoare_linie_lei', 'platit_linie_lei', 'pastrat_lei', 'platit_pastrat_lei', 'returnat_lei', 'anulat_lei', 'in_curs_lei',
  'bucati_pastrate', 'bucati_returnate', 'bucati_anulate', 'bucati_in_curs',
  'status_bloc', 'retur_id', 'peste_prag',
];

// Caracterele cu care o celulă începe ca formulă în Excel / LibreOffice (lista OWASP pentru CSV injection). Mulțime de caractere, nu șir: o celulă goală nu are primul caracter, deci nu e formulă.
const FORMULA_STARTS = new Set(['=', '+', '-', '@', '\t', '\r']);
// Câte caractere din data ISO „2026-05-26T10:07” intră în coloana „data” (ziua) și în „an”.
const DATE_LENGTH = 10;
const YEAR_LENGTH = 4;

/**
 * Text sigur de deschis în Excel: un apostrof în față dacă ar începe ca formulă (și după spațiile din față, cele ale lui Python: includ U+0085 și U+001C-U+001F, nu U+FEFF).
 * Se aplică doar câmpurilor de text din cont, nu sumelor: „-12,00” generat de program rămâne număr.
 */
export function textCell(value) {
  const text = String(value);
  if (FORMULA_STARTS.has(text.slice(0, 1)) || FORMULA_STARTS.has(pyLstrip(text).slice(0, 1))) return `'${text}`;
  return text;
}

/** Suma în lei cu virgulă zecimală, fără separator de mii (144927 devine „1449,27”); RangeError dacă `bani` nu e un întreg sigur. */
export function leiCell(bani) {
  const [whole, frac] = pyDivmod(Math.abs(bani), 100);
  return `${bani < 0 ? '-' : ''}${whole},${String(frac).padStart(2, '0')}`;
}

/**
 * Textul lui produse.csv: câte un rând pe produs; `peste_prag` = „da” dacă valoarea liniei depășește STRICT pragul înmulțit cu cantitatea (prețul pe bucată peste prag).
 * Compararea e exactă (BigInt), ca întregii din Python; liniile cu cantitate zero nu sunt niciodată peste prag.
 */
export function linesCsv(lines, thresholdBani) {
  const rows = [pyCsvRow(HEADER)];
  for (const line of lines) {
    const above = line.qty > 0 && BigInt(line.line_total_bani) > BigInt(thresholdBani) * BigInt(line.qty);
    rows.push(pyCsvRow([
      textCell(line.order_id),
      textCell(orderUrl(line.order_id) ?? ''),
      cpSlice(line.placed_at || '', 0, DATE_LENGTH),
      cpSlice(line.placed_at || '', 0, YEAR_LENGTH),
      textCell(line.seller),
      textCell(line.name),
      textCell(line.category),
      textCell(line.rule),
      line.qty,
      leiCell(line.line_total_bani),
      leiCell(line.paid_value_bani),
      leiCell(line.kept_bani),
      leiCell(line.kept_paid_bani),
      leiCell(line.returned_bani),
      leiCell(line.cancelled_bani),
      leiCell(line.pending_bani),
      line.kept_qty,
      line.returned_qty,
      line.cancelled_qty,
      line.pending_qty,
      textCell(line.block_status),
      textCell(line.return_ids.join(',')),
      above ? 'da' : '',
    ]));
  }
  return UTF8_BOM + rows.join('');
}
