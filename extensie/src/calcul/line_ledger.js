// Construiește registrul de linii (LineOutcome) din comenzile citite (portul lui emag_spend/line_ledger.py).
// Primește: lista de comenzi. Dă înapoi: câte o LineOutcome pentru fiecare produs, cu starea de pornire dedusă din statusul blocului (livrat -> păstrat, anulat -> anulat, în curs -> în curs,
// plătit fără livrare, necunoscut) și cu valoarea plătită a liniei (prețul minus partea ei din reducerile blocului, block_payment.js).
// Retururile se aplică ulterior (return_matcher.js). Ce NU face: nu calculează totaluri.
import { blockPayment } from './block_payment.js';
import { CANCELLED, DELIVERED, IN_PROGRESS, PAID_ONLY, UNKNOWN } from './block_status.js';
import { LineOutcome } from './models.js';

// Câmpul cu bucăți în care intră cantitatea unei linii, după statusul blocului. Un status care nu e aici (o valoare nouă, necunoscută încă) se numără ca „necunoscut”,
// niciodată ca „păstrat”: o cifră în plus la cheltuieli ar arăta normal și ar fi greșită.
const STATE_FIELD = new Map([
  [DELIVERED, 'kept_qty'],
  [CANCELLED, 'cancelled_qty'],
  [IN_PROGRESS, 'pending_qty'],
  [PAID_ONLY, 'paid_only_qty'],
  [UNKNOWN, 'unknown_qty'],
]);
const FALLBACK_STATE_FIELD = 'unknown_qty';

/** O linie de registru pentru fiecare produs din fiecare bloc de comandă, cu valoarea ei plătită. */
export function buildLines(orders) {
  const lines = [];
  for (const order of orders) {
    for (const block of order.blocks) {
      const payment = blockPayment(block);
      block.items.forEach((item, index) => {
        const line = new LineOutcome({
          order_id: order.order_id,
          placed_at: order.placed_at,
          seller: block.seller,
          name: item.name,
          qty: item.qty,
          line_total_bani: item.line_total_bani,
          block_status: block.status,
          paid_total_bani: payment.line_paid_bani[index],
        });
        line[STATE_FIELD.get(block.status) ?? FALLBACK_STATE_FIELD] = item.qty;
        lines.push(line);
      });
    }
  }
  return lines;
}
