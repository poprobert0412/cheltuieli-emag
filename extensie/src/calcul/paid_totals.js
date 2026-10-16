// Banii plătiți efectiv: cifra principală a raportului, lanțul în bani plătiți și rândurile care nu sunt produse (portul lui emag_spend/paid_totals.py).
// Primește: comenzile, registrul de linii (cu `paid_total_bani` de la line_ledger.js și retururile aplicate de return_matcher.js), retururile, raportul potrivirii și modurile de restituire.
// Completează pe linii `credit_returned_qty`. Dă înapoi: PaidTotals = cheia `paid` din analiza.json + sumele pe ani + avertismentele (moduri de restituire necunoscute).
// Reguli: plătit efectiv = „Total platit” al blocurilor livrate/ridicate − banii primiți înapoi la retururile lor + partea plătită a produselor returnate cu voucher sau sold din blocuri
// marcate „anulat”; retur cu bani înapoi: se scade suma restituită afișată (fără sumă, cu produse nepotrivite sau întins pe blocuri cu stări diferite: partea plătită a produselor, estimare);
// retur cu voucher sau sold: nu se scade nimic. Invariant verificat: produse păstrate + transport și taxe + retururi cu credit + diferențe la restituiri = plătit efectiv.
// Ce NU face: nu citește fișiere, nu grupează pe categorii (spend_analysis.js) și nu scrie text.
import { PAID_FROM_COMPONENTS, blockPayment } from './block_payment.js';
import { DELIVERED, IN_PROGRESS, PAID_ONLY, UNKNOWN } from './block_status.js';
import { cpSlice } from './python_compat.js';
import { splitProportionally } from './proportional_split.js';
import { PAID_CHECK_BLOCKS, PAID_CHECK_CHAIN, formatPaidNotClosing, formatUnknownRefundMode } from './warning_messages.js';

// Rândurile care nu sunt produse: apar după categorii și ca serii în graficul pe ani, ca suma lor să fie plătitul efectiv.
export const EXTRA_FEES = 'fees';
export const EXTRA_CREDIT_RETURNS = 'credit_returns';
export const EXTRA_REFUND_DIFFERENCES = 'refund_differences';
export const EXTRA_ROW_NAMES = Object.freeze({
  [EXTRA_FEES]: 'Transport și taxe',
  [EXTRA_CREDIT_RETURNS]: 'Retururi cu voucher sau sold eMAG',
  [EXTRA_REFUND_DIFFERENCES]: 'Diferențe la restituiri',
});
export const UNKNOWN_YEAR = 'necunoscut';
// Câmpul din `YearTotals` din care vine valoarea pe ani a fiecărui rând care nu e produs.
const EXTRA_ATTRIBUTE = Object.freeze({
  [EXTRA_FEES]: 'fees_bani',
  [EXTRA_CREDIT_RETURNS]: 'credit_bani',
  [EXTRA_REFUND_DIFFERENCES]: 'differences_bani',
});
// Câte caractere din data ISO a comenzii formează anul („2024-03-10T10:00” -> „2024”).
const YEAR_LENGTH = 4;

/** Anul din data ISO a comenzii, sau „necunoscut” (aceeași regulă ca în spend_analysis.js). */
export function yearOf(placedAt) {
  return placedAt ? cpSlice(placedAt, 0, YEAR_LENGTH) : UNKNOWN_YEAR;
}

/** Sumele unui an; între ele: ordered − cancelled − returned − pending − unknown + fees = spent. Câmpurile sunt în ordinea din Python. */
class YearTotals {
  constructor() {
    this.ordered_bani = 0;
    this.cancelled_bani = 0;
    this.returned_bani = 0;
    this.pending_bani = 0;
    this.unknown_bani = 0;
    this.fees_bani = 0;
    this.kept_bani = 0;
    this.credit_bani = 0;
    this.differences_bani = 0;
  }

  /** Plătit efectiv în acest an: produse păstrate + transport și taxe + retururi cu credit + diferențe. */
  get spent_bani() {
    return this.kept_bani + this.fees_bani + this.credit_bani + this.differences_bani;
  }
}

/** Rezultatul: `summary` (cheia `paid` din analiza.json), sumele pe ani (Map: an -> YearTotals, în ordinea în care apar) și avertismentele găsite. */
export class PaidTotals {
  constructor(summary, byYear, warnings) {
    this.summary = summary;
    this.by_year = byYear;
    this.warnings = warnings;
  }

  /** Valoarea pe ani a unui rând care nu e produs (EXTRA_*), ca Map an -> bani. */
  extraValues(key) {
    const attribute = EXTRA_ATTRIBUTE[key];
    return new Map([...this.by_year].map(([year, values]) => [year, values[attribute]]));
  }
}

/** Completează `credit_returned_qty` pe fiecare linie: unitățile ei returnate cu voucher sau sold eMAG. */
export function markCreditReturns(lines, returns, modes) {
  const creditIds = new Set(returns.filter((ret) => modes.isCredit(ret.refund_mode)).map((ret) => ret.return_id));
  for (const line of lines) line.credit_returned_qty = line.return_ids.filter((returnId) => creditIds.has(returnId)).length;
}

/** Pentru fiecare retur (Map: număr -> părți), liniile lui; pe o linie, partea plătită a returnatului se împarte exact între retururi. */
function returnParts(lines) {
  const parts = new Map();
  for (const line of lines) {
    if (line.return_ids.length === 0) continue;
    const counts = new Map();
    for (const returnId of line.return_ids) counts.set(returnId, (counts.get(returnId) ?? 0) + 1);
    const ids = [...counts.keys()];
    const shares = splitProportionally(line.returned_paid_bani, ids.map((id) => counts.get(id)));
    ids.forEach((returnId, index) => {
      if (!parts.has(returnId)) parts.set(returnId, []);
      parts.get(returnId).push({ line, units: counts.get(returnId), paid_bani: shares[index] });
    });
  }
  return parts;
}

/** Suma unei liste de întregi (sum() din Python). */
function sumOf(values) {
  return values.reduce((total, value) => total + value, 0);
}

/** Calculează cheia `paid` (vezi antetul modulului pentru reguli). `lines` trebuie să aibă retururile deja aplicate. */
export function computePaidTotals(orders, lines, returns, matchReport, modes) {
  markCreditReturns(lines, returns, modes);
  const years = new Map();
  /** Totalurile anului; ca defaultdict(_Year), o primă citire creează intrarea (și anul apare apoi în by_year chiar cu zerouri). */
  const yearTotals = (placedAt) => {
    const year = yearOf(placedAt);
    if (!years.has(year)) years.set(year, new YearTotals());
    return years.get(year);
  };
  const warnings = [];
  for (const ret of returns) {
    if (ret.completed && !modes.isKnown(ret.refund_mode)) warnings.push(formatUnknownRefundMode(ret.return_id, ret.refund_mode));
  }

  // ---- produsele, pe stări (în bani plătiți) ----
  const units = { ordered: 0, cancelled: 0, pending: 0, unknown: 0, kept: 0, returned: 0, credit: 0 };
  let listKept = 0;
  for (const line of lines.filter((candidate) => candidate.paid_only_qty === 0)) {
    const year = yearTotals(line.placed_at);
    year.ordered_bani += line.paid_value_bani;
    year.cancelled_bani += line.cancelled_paid_bani;
    year.pending_bani += line.pending_paid_bani;
    year.unknown_bani += line.unknown_paid_bani;
    year.kept_bani += line.kept_paid_bani;
    listKept += line.kept_list_bani;
    units.ordered += line.qty;
    units.cancelled += line.cancelled_qty;
    units.pending += line.pending_qty;
    units.unknown += line.unknown_qty;
    units.kept += line.kept_qty;
    units.returned += line.returned_qty - line.credit_returned_qty;
    units.credit += line.credit_returned_qty;
  }

  // ---- blocurile: transportul și taxele celor livrate, sumele celor rămase în afara calculului ----
  let paidDelivered = 0;
  let rebuiltBani = 0;
  let rebuiltBlocks = 0;
  const outside = { in_progress_bani: 0, paid_only_bani: 0, unknown_bani: 0 };
  for (const order of orders) {
    for (const block of order.blocks) {
      const payment = blockPayment(block);
      if (block.status === DELIVERED) {
        paidDelivered += payment.paid_bani;
        yearTotals(order.placed_at).fees_bani += payment.fees_bani;
        if (payment.source === PAID_FROM_COMPONENTS) {
          rebuiltBlocks += 1;
          rebuiltBani += payment.paid_bani;
        }
      } else if (block.status === IN_PROGRESS) {
        outside.in_progress_bani += payment.paid_bani;
      } else if (block.status === PAID_ONLY) {
        outside.paid_only_bani += payment.paid_bani;
      } else if (block.status === UNKNOWN) {
        outside.unknown_bani += payment.paid_bani;
      }
    }
  }

  // ---- retururile: bani înapoi (scădeți) sau credit (rămân cheltuiți) ----
  const byId = new Map(returns.map((ret) => [ret.return_id, ret]));
  const partial = new Set(matchReport.partially_matched_return_ids);
  const refunds = {
    credit_on_delivered_bani: 0, credit_added_bani: 0, cancelled_cash_bani: 0, cancelled_cash_shown_bani: 0, cash_bani: 0, estimated_bani: 0, estimated_returns: 0, unattributed_bani: 0,
  };
  for (const [returnId, parts] of returnParts(lines)) {
    const ret = byId.get(returnId) ?? null;
    const delivered = parts.filter((part) => part.line.block_status === DELIVERED);
    const elsewhere = parts.filter((part) => part.line.block_status !== DELIVERED);
    const onDelivered = sumOf(delivered.map((part) => part.paid_bani));
    const onElsewhere = sumOf(elsewhere.map((part) => part.paid_bani));
    if (ret !== null && modes.isCredit(ret.refund_mode)) {
      for (const part of parts) yearTotals(part.line.placed_at).credit_bani += part.paid_bani; // banii n-au revenit în cont: rămân cheltuiți, pe anul comenzii
      refunds.credit_on_delivered_bani += onDelivered;
      refunds.credit_added_bani += onElsewhere;
      continue;
    }
    for (const part of elsewhere) yearTotals(part.line.placed_at).returned_bani += part.paid_bani; // bloc marcat „anulat”: plata și restituirea se anulează reciproc
    refunds.cancelled_cash_bani += onElsewhere;
    const shown = ret !== null ? ret.refund_bani : null;
    if (delivered.length === 0) {
      if (shown !== null) refunds.cancelled_cash_shown_bani += shown;
      continue;
    }
    const exact = shown !== null && elsewhere.length === 0 && !partial.has(returnId);
    const attributed = exact ? shown : onDelivered;
    // suma restituită se împarte pe liniile returului proporțional cu partea lor plătită, ca fiecare an să se închidă exact
    const weights = delivered.map((part) => part.paid_bani);
    const shares = sumOf(weights) !== 0 ? splitProportionally(attributed, weights) : [attributed, ...new Array(delivered.length - 1).fill(0)];
    delivered.forEach((part, index) => {
      const year = yearTotals(part.line.placed_at);
      year.returned_bani += shares[index];
      year.differences_bani += part.paid_bani - shares[index];
    });
    refunds.cash_bani += attributed;
    if (!exact) {
      refunds.estimated_bani += onDelivered;
      refunds.estimated_returns += 1;
      if (shown !== null) refunds.unattributed_bani += shown - onDelivered - onElsewhere; // suma afișată acoperă și produse nepotrivite sau din alt bloc: rămâne neatribuită
    }
  }

  // ---- totaluri și verificarea lanțului ----
  const total = new YearTotals();
  for (const values of years.values()) {
    for (const name of Object.keys(total)) total[name] += values[name];
  }
  const spentByChain = total.ordered_bani - total.cancelled_bani - total.returned_bani - total.pending_bani - total.unknown_bani + total.fees_bani;
  if (spentByChain !== total.spent_bani) warnings.push(formatPaidNotClosing(PAID_CHECK_CHAIN, spentByChain, total.spent_bani));
  const spentByBlocks = paidDelivered - refunds.cash_bani + refunds.credit_added_bani;
  if (spentByBlocks !== total.spent_bani) warnings.push(formatPaidNotClosing(PAID_CHECK_BLOCKS, spentByBlocks, total.spent_bani));

  const extraRows = [
    [EXTRA_FEES, total.fees_bani], [EXTRA_CREDIT_RETURNS, total.credit_bani], [EXTRA_REFUND_DIFFERENCES, total.differences_bani],
  ].filter(([, bani]) => bani !== 0).map(([key, bani]) => ({ key, name: EXTRA_ROW_NAMES[key], bani }));
  const summary = {
    spent_bani: total.spent_bani,
    spent_units: units.kept,
    list_kept_bani: listKept,
    discounts_kept_bani: listKept - total.kept_bani,
    products_kept_bani: total.kept_bani,
    fees_bani: total.fees_bani,
    credit_returns_bani: total.credit_bani,
    credit_returns_units: units.credit,
    refund_differences_bani: total.differences_bani,
    extra_rows: extraRows,
    funnel: {
      ordered_bani: total.ordered_bani,
      cancelled_bani: total.cancelled_bani,
      returned_bani: total.returned_bani,
      pending_bani: total.pending_bani,
      unknown_bani: total.unknown_bani,
      fees_bani: total.fees_bani,
      spent_bani: total.spent_bani,
      ordered_units: units.ordered,
      cancelled_units: units.cancelled,
      returned_units: units.returned,
      credit_units: units.credit,
      pending_units: units.pending,
      unknown_units: units.unknown,
      spent_units: units.kept,
    },
    reconciliation: {
      paid_delivered_bani: paidDelivered,
      rebuilt_blocks: rebuiltBlocks,
      rebuilt_bani: rebuiltBani,
      cash_refunds_bani: refunds.cash_bani,
      estimated_refunds_bani: refunds.estimated_bani,
      estimated_refunds: refunds.estimated_returns,
      credit_returns_delivered_bani: refunds.credit_on_delivered_bani,
      credit_returns_added_bani: refunds.credit_added_bani,
      refund_differences_bani: total.differences_bani,
      spent_bani: total.spent_bani,
      in_progress_bani: outside.in_progress_bani,
      paid_only_bani: outside.paid_only_bani,
      unknown_bani: outside.unknown_bani,
      cancelled_cash_returns_bani: refunds.cancelled_cash_bani,
      cancelled_cash_refunds_shown_bani: refunds.cancelled_cash_shown_bani,
      unattributed_refunds_bani: refunds.unattributed_bani + matchReport.unmatched_refund_bani,
    },
  };
  return new PaidTotals(summary, years, warnings);
}
