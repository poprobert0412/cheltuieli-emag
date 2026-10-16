// Istoricul prețurilor la același produs ca text CSV pe care îl deschizi în Excel (portul lui emag_spend/price_history_csv.py).
// Primește: dicționarul `price_history` din rezumatul analizei. Dă înapoi: textul lui istoric_preturi.csv: câte un rând pe cumpărare, grupate pe produs, cu linkul comenzii.
// Același format ca produse.csv (separator „;”, zecimale cu virgulă, CRLF, BOM UTF-8) și aceeași protecție contra formulelor din celulele de text (textCell). Fără produse repetate, textul are doar capul de tabel.
// Ce NU face: nu calculează nimic, formatează ce a calculat price_history (color_variants e boolean acolo), și nu scrie fișiere.
import { orderUrl } from '../calcul/order_links.js';
import { pyCsvRow } from '../calcul/python_compat.js';
import { leiCell, textCell } from './csv_export.js';

// Primul caracter al fișierului: Excel îl cere ca să citească diacriticele ca UTF-8 (utf-8-sig în Python).
const UTF8_BOM = '\u{feff}';

const HEADER = [
  'produs', 'categorie', 'data', 'comanda', 'link_comanda', 'vanzator', 'nume_in_comanda',
  'bucati_pastrate', 'pret_bucata_lei', 'pret_minim_lei', 'peste_minim_lei', 'variante_culoare',
];

/** Textul lui istoric_preturi.csv; `peste_minim_lei` = (preț − minimul produsului) × bucăți (negativ când prețul e sub minimul de referință). */
export function priceHistoryCsv(priceHistory) {
  const rows = [pyCsvRow(HEADER)];
  for (const product of priceHistory.products) {
    for (const purchase of product.purchases) {
      rows.push(pyCsvRow([
        textCell(product.name),
        textCell(product.category),
        purchase.date || '',
        textCell(purchase.order_id),
        textCell(orderUrl(purchase.order_id) ?? ''),
        textCell(purchase.seller),
        textCell(purchase.name),
        purchase.qty,
        leiCell(purchase.unit_bani),
        leiCell(product.min_unit_bani),
        leiCell((purchase.unit_bani - product.min_unit_bani) * purchase.qty),
        product.color_variants ? 'da' : '',
      ]));
    }
  }
  return UTF8_BOM + rows.join('');
}
