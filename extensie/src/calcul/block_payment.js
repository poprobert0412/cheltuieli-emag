// Ce s-a plătit într-un bloc de vânzător și cum se împarte: produsele, pe linii (după reduceri), și transportul cu taxele (portul lui emag_spend/block_payment.py).
// Primește: un bloc de vânzător (forma din models.js). Dă înapoi: suma blocului, partea produselor pe fiecare linie, transportul și taxele, reducerile care revin produselor și de unde vine suma.
// Reguli: la un bloc taxat (livrat, în curs, status necunoscut, plătit fără livrare) suma e „Total platit”; dacă pagina nu o arată, se calculează din componente (produse + reduceri + transport
// + servicii + alte taxe). Transportul și taxele nu se împart pe produse. Reducerile (vouchere, card cadou, linii negative de tip „Custom Discount”) se împart pe produse proporțional cu prețul lor
// de listă, în bani întregi (proportional_split.js); un voucher mai mare decât produsele acoperă și din transport. La un bloc ANULAT nu s-a plătit nimic: valoarea produselor e prețul minus reducerile.
// Ce NU face: nu știe de retururi și nu adună pe categorii (paid_totals.js, spend_analysis.js).
import { CANCELLED } from './block_status.js';
import { splitProportionally } from './proportional_split.js';

// De unde vine suma blocului: „Total platit” afișat de eMAG; calculată din componente (bloc taxat fără „Total platit”);
// sau, la un bloc anulat, valoarea produselor după reduceri (ce s-ar fi plătit), fără transport.
export const PAID_SHOWN = 'total_platit';
export const PAID_FROM_COMPONENTS = 'componente';
export const NOT_CHARGED = 'anulat';

/** Suma unei liste de întregi (sum() din Python): 0 pentru lista goală. */
function sumOf(values) {
  return values.reduce((total, value) => total + value, 0);
}

/** Transportul, serviciile operaționale și celelalte taxe afișate în bloc. */
function declaredFees(block) {
  return (block.shipping_bani || 0) + sumOf(block.services_bani) + sumOf(block.other_bani);
}

/**
 * Suma blocului și împărțirea ei pe produse (după reduceri) și pe transport cu taxe (vezi antetul modulului). Rezultatul e înghețat, cu cheile din BlockPayment:
 * paid_bani, source, list_bani, products_paid_bani, fees_bani, discount_bani, line_paid_bani (în ordinea din block.items). Invariant: sum(line_paid_bani) + fees_bani == paid_bani.
 */
export function blockPayment(block) {
  const listValues = block.items.map((item) => Math.max(0, item.line_total_bani));
  const listTotal = sumOf(listValues);
  const linesTotal = sumOf(block.items.map((item) => item.line_total_bani)); // cu liniile negative (reduceri scrise ca produs)
  const vouchers = sumOf(block.vouchers_bani);
  let paid;
  let source;
  let fees;
  let productsPaid;
  if (block.status === CANCELLED) {
    productsPaid = Math.min(Math.max(linesTotal + vouchers, 0), listTotal);
    paid = productsPaid;
    source = NOT_CHARGED;
    fees = 0;
  } else {
    const declared = declaredFees(block);
    if (block.paid_bani !== null) {
      paid = block.paid_bani;
      source = PAID_SHOWN;
    } else {
      paid = linesTotal + vouchers + declared;
      source = PAID_FROM_COMPONENTS;
    }
    // Produsele primesc ce rămâne după taxe, cel mult prețul lor de listă: un voucher mai mare decât produsele scade și din transport,
    // iar o sumă plătită peste produse + taxe (o taxă nerecunoscută) rămâne la taxe.
    productsPaid = Math.min(Math.max(paid - declared, 0), listTotal);
    fees = paid - productsPaid;
  }
  const discount = listTotal - productsPaid;
  const shares = splitProportionally(discount, listValues);
  return Object.freeze({
    paid_bani: paid,
    source,
    list_bani: listTotal,
    products_paid_bani: productsPaid,
    fees_bani: fees,
    discount_bani: discount,
    line_paid_bani: Object.freeze(listValues.map((value, index) => value - shares[index])),
  });
}
