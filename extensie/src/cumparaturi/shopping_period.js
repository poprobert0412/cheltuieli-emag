// Proiecții din atribuirile motorului complet: zile inclusive sau campanie cu ore [start,end); retururile nu se repotrivesc după filtrare.
// Intrările fără comenzi brute oferă exclusiv totalul anual existent; lipsa detaliilor rămâne explicită.
import { isShoppingDate } from './shopping_schema.js';
import { orderLocalDate, orderTimestamp, validateCampaign } from './campaign_time.js';

/** Suma unui câmp deja calculat de motor; nu reconstituie prețuri ori rambursări. */
function sum(rows, key) { return rows.reduce((total, row) => total + row[key], 0); }

/** Sumar compact pentru un interval fără detalii; valoarea anuală provine numai din by_year. */
function annualFallback(summary, from, to) {
  const wholeYears = from.endsWith('-01-01') && to.endsWith('-12-31');
  const rows = (summary.by_year ?? []).filter((row) => /^\d{4}$/.test(String(row.year))
    && String(row.year) >= from.slice(0, 4) && String(row.year) <= to.slice(0, 4));
  const available = wholeYears && rows.length > 0 && rows.every((row) => Number.isSafeInteger(row.spent_bani));
  return {
    available, detail_available: false,
    meta: { from, to, orders: available && rows.every((row) => Number.isSafeInteger(row.orders)) ? sum(rows, 'orders') : null, missing_dates: null },
    paid: available ? { spent_bani: sum(rows, 'spent_bani'), funnel: {
      pending_bani: rows.every((row) => Number.isSafeInteger(row.paid_pending_bani)) ? sum(rows, 'paid_pending_bani') : null,
    }, reconciliation: { in_progress_bani: null } } : null,
    funnel: null, by_category: [], by_year: available ? structuredClone(rows) : [],
  };
}

/** Filtrează pe data comenzii; retururile, inclusiv cele ulterioare intervalului, au fost atribuite deja de motor. */
export function shoppingPeriod(source, from, to) {
  if (!isShoppingDate(from) || !isShoppingDate(to) || from > to) throw new TypeError('interval de cumpărături invalid');
  if (source.orders === null) return annualFallback(source.summary, from, to);
  const selected = source.orders.filter((order) => order.placed_at && order.placed_at.slice(0, 10) >= from && order.placed_at.slice(0, 10) <= to);
  return selectionSummary(source, selected, { from, to, missing_dates: source.orders.filter((order) => !order.placed_at).length });
}

/** Campanie [început,sfârșit), pe instanțe precise; zilele fără oră sunt excluse și numărate separat. */
export function shoppingCampaign(source, campaign) {
  const bounds = validateCampaign(campaign);
  const meta = { from: campaign.from, to: campaign.to, start_time: campaign.start_time, end_time: campaign.end_time,
    time_zone: campaign.time_zone, start_ms: bounds.start_ms, end_ms: bounds.end_ms, missing_dates: null, missing_times: null, orders: null };
  if (bounds.time_required || source.orders === null) return {
    available: false, detail_available: false, time_required: bounds.time_required, meta, paid: null, funnel: null, by_category: [], by_year: [],
  };
  meta.missing_dates = 0; meta.missing_times = 0;
  const selected = source.orders.filter((order) => {
    const instant = orderTimestamp(order.placed_at);
    if (instant !== null) return instant >= bounds.start_ms && instant < bounds.end_ms;
    const day = orderLocalDate(order.placed_at);
    if (day === null) meta.missing_dates += 1;
    else if (day >= campaign.from && (day < campaign.to || (day === campaign.to && campaign.end_time !== '00:00'))) meta.missing_times += 1;
    return false;
  });
  return { ...selectionSummary(source, selected, meta), time_required: false };
}

/** Adună exclusiv atribuiri și cantități deja calculate; selecția zilnică și cea pe ore folosesc aceeași cale. */
function selectionSummary({ lines, paid_by_order }, selected, meta) {
  const ids = new Set(selected.map((order) => order.order_id));
  const parts = selected.map((order) => paid_by_order.get(order.order_id));
  const selectedLines = lines.filter((line) => ids.has(line.order_id) && !line.paid_only_qty);
  const totals = Object.fromEntries(['ordered_bani', 'cancelled_bani', 'returned_bani', 'pending_bani', 'unknown_bani',
    'fees_bani', 'kept_bani', 'credit_bani', 'differences_bani', 'spent_bani', 'in_progress_bani'].map((key) => [key, sum(parts, key)]));
  const kept = sum(selectedLines, 'kept_qty');
  const returned = sum(selectedLines, 'returned_qty');
  const credit = sum(selectedLines, 'credit_returned_qty');
  const categories = new Map();
  for (const line of selectedLines) {
    if (!categories.has(line.category)) categories.set(line.category, { name: line.category, paid_kept_bani: 0, kept_units: 0 });
    const row = categories.get(line.category);
    row.paid_kept_bani += line.kept_paid_bani; row.kept_units += line.kept_qty;
  }
  const years = [...new Set(selected.map((order) => order.placed_at.slice(0, 4)))].sort();
  return {
    available: true, detail_available: true,
    meta: { ...meta, orders: selected.length },
    paid: {
      spent_bani: totals.spent_bani, spent_units: kept, products_kept_bani: totals.kept_bani,
      fees_bani: totals.fees_bani, credit_returns_bani: totals.credit_bani, credit_returns_units: credit,
      refund_differences_bani: totals.differences_bani,
      funnel: { ordered_bani: totals.ordered_bani, cancelled_bani: totals.cancelled_bani, returned_bani: totals.returned_bani,
        pending_bani: totals.pending_bani, unknown_bani: totals.unknown_bani, fees_bani: totals.fees_bani, spent_bani: totals.spent_bani,
        ordered_units: sum(selectedLines, 'qty'), returned_units: returned - credit, credit_units: credit, spent_units: kept },
      reconciliation: { in_progress_bani: totals.in_progress_bani },
    },
    funnel: { ordered_units: sum(selectedLines, 'qty'), kept_units: kept, returned_units: returned, pending_bani: sum(selectedLines, 'pending_bani') },
    by_category: [...categories.values()].sort((a, b) => b.paid_kept_bani - a.paid_kept_bani),
    by_year: years.map((year) => {
      const yearOrders = selected.filter((order) => order.placed_at.startsWith(year));
      const yearIds = new Set(yearOrders.map((order) => order.order_id));
      const yearParts = yearOrders.map((order) => paid_by_order.get(order.order_id));
      return { year, orders: yearOrders.length, spent_bani: sum(yearParts, 'spent_bani'), paid_pending_bani: sum(yearParts, 'pending_bani'),
        kept_units: sum(selectedLines.filter((line) => yearIds.has(line.order_id)), 'kept_qty') };
    }),
  };
}
