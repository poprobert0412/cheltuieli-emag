// Calculează cât s-a cheltuit efectiv, pe categorii, ani, vânzători și produse (portul lui emag_spend/spend_analysis.py).
// Primește: comenzile, retururile, clasificatorul, pragul „achiziție mare” (bani, pe prețul de listă pe bucată), ora generării și, în `options`, textele avertismentelor, culorile și modurile
// de restituire gata încărcate (loadWarningTexts, loadColorWords, loadRefundModes; în extensie nu se citește niciun fișier), categoriile evidențiate și, opțional, `log` (info/warning, ca RunLog).
// Dă înapoi: { summary, lines } = `summary` (arbore JSON simplu, sume în BANI, procentele ca PyFloat, ca JSON-ul să le scrie „5.0” ca Python) + registrul de linii (LineOutcome) pentru CSV.
// PyFloat nu se salvează în chrome.storage și nu trece de verificările din dashboard.js (cer numere): `plainSummary(summary)` dă copia cu numere simple, pentru salvare și pentru ecran.
// Cifra principală e cheia `paid` (paid_totals.js): banii plătiți efectiv. Rândurile au și sume plătite (`paid_*`), lângă cele la preț de listă (cheile vechi, păstrate pentru rapoartele vechi).
// Ce NU face: nu citește pagini, nu scrie fișiere și nu modifică comenzile sau retururile primite.
import { DELIVERED, IN_PROGRESS, PAID_ONLY, UNKNOWN } from './block_status.js';
import { buildLines } from './line_ledger.js';
import { yearOf, computePaidTotals } from './paid_totals.js';
import { buildPriceHistory } from './price_history.js';
import { applyReturns } from './return_matcher.js';
import { PyFloat, compareCodePoints, cpLength, cpSlice, floorDiv, maxBy, sortedBy, withoutNegativeZero } from './python_compat.js';
import { normalizeText } from './text_normalize.js';
import {
  buildWarningsDetail, completedReturnsWithoutAmount, currentOrderWarnings, returnsWithoutResult,
} from './warning_details.js';
import {
  formatFunnelNotClosing, formatHeaderMismatches, formatHighlightCategoryMissing, formatPendingReturns, formatRefundsWithoutAmount, formatUncategorized, formatUnknownStatus,
} from './warning_messages.js';

const LOG_MODULE = 'spend_analysis';
// Câte categorii apar separat în graficul pe ani; restul se strâng la „Altele”. 6 + „Altele” = 7 serii, sub plafonul de lizibilitate al paletei de culori.
export const YEARLY_CHART_TOP_CATEGORIES = 6;
export const OTHER_LABEL = 'Altele';
export const TOP_PRODUCTS_LIMIT = 25;
export const TOP_SELLERS_LIMIT = 12;
export const UNCATEGORIZED_SAMPLE_LIMIT = 40;
export const HIGHLIGHT_ITEMS_LIMIT = 80;
// Sufixul unui rând care nu e produs („Transport și taxe”...) când o categorie din reguli are exact același nume: în graficul pe ani seriile se deosebesc după nume,
// iar două serii cu același nume s-ar aduna într-una.
export const EXTRA_NAME_CLASH_SUFFIX = ' (rând separat)';
// Câte caractere are ziua „AAAA-LL-ZZ” din data ISO a comenzii.
const DAY_LENGTH = 10;
// Cheia sub care se numără, în `reconciliation.refund_modes`, retururile finalizate la care pagina nu scrie niciun mod de restituire.
const NO_REFUND_MODE_KEY = 'necunoscut';

// Totalurile unei categorii: la preț de listă (cheile vechi) și plătite, după reduceri (paid_*).
const CATEGORY_KEYS = [
  'ordered_bani', 'ordered_units', 'kept_bani', 'kept_units', 'returned_bani', 'returned_units', 'cancelled_bani', 'cancelled_units', 'pending_bani',
  'paid_ordered_bani', 'paid_kept_bani', 'paid_returned_bani', 'paid_cancelled_bani', 'paid_pending_bani',
];
// Sumele plătite ale unui an (YearTotals din paid_totals.js): ordered − cancelled − returned − pending − unknown + fees = spent.
const PAID_YEAR_KEYS = ['paid_ordered_bani', 'paid_returned_bani', 'paid_cancelled_bani', 'paid_pending_bani', 'paid_unknown_bani', 'paid_fees_bani', 'spent_bani'];
// Stările unei linii: [numele stării, câmpul cu bucăți, suma la preț de listă, suma plătită].
const STATE_PARTS = [
  ['kept', 'kept_qty', 'kept_bani', 'kept_paid_bani'],
  ['returned', 'returned_qty', 'returned_bani', 'returned_paid_bani'],
  ['cancelled', 'cancelled_qty', 'cancelled_bani', 'cancelled_paid_bani'],
  ['pending', 'pending_qty', 'pending_bani', 'pending_paid_bani'],
  ['unknown', 'unknown_qty', 'unknown_bani', 'unknown_paid_bani'],
];
// Rezultatele posibile ale unei comenzi, în ordinea din rezumat.
const ORDER_OUTCOMES = ['kept_all', 'kept_partial', 'returned_all', 'cancelled_all', 'in_progress', 'paid_only', 'unknown', 'no_items'];

/** Suma unei liste de întregi (sum() din Python). */
function sumOf(values) {
  return values.reduce((total, value) => total + value, 0);
}

/** Obiect cu aceleași chei, toate zero (dict.fromkeys(keys, 0) din Python). */
function zeros(keys) {
  return Object.fromEntries(keys.map((key) => [key, 0]));
}

/** Valoarea pentru `key` din Map, sau o valoare nouă creată de `make` și pusă în Map (defaultdict din Python). */
function getOrCreate(map, key, make) {
  if (!map.has(key)) map.set(key, make());
  return map.get(key);
}

/** Data mai târzie dintre două date ISO (max(a, b) din Python pe texte: ordinea punctelor de cod, prima la egalitate). */
function laterDate(first, second) {
  return compareCodePoints(second, first) > 0 ? second : first;
}

/**
 * Lanțul comandat -> anulat -> returnat -> în curs -> păstrat, la PREȚ DE LISTĂ, în bani și bucăți. Cheia veche `funnel`, păstrată pentru rapoartele vechi și ca informație secundară
 * (lanțul în bani plătiți e în `paid`). Comandat = valoarea tuturor produselor din comenzi (fără serviciile plătite fără livrare, ex. asigurări, listate separat);
 * păstrat = comandat − anulat − returnat − în curs = livrate/ridicate și rămase la client.
 */
function funnelOf(lines) {
  const priced = lines.filter((line) => line.paid_only_qty === 0);
  const total = (select) => sumOf(priced.map(select));
  return {
    ordered_bani: total((line) => line.line_total_bani),
    cancelled_bani: total((line) => line.cancelled_bani),
    returned_bani: total((line) => line.returned_bani),
    pending_bani: total((line) => line.pending_bani),
    unknown_bani: total((line) => line.unknown_bani),
    kept_bani: total((line) => line.kept_bani),
    ordered_units: total((line) => line.qty),
    cancelled_units: total((line) => line.cancelled_qty),
    returned_units: total((line) => line.returned_qty),
    pending_units: total((line) => line.pending_qty),
    unknown_units: total((line) => line.unknown_qty),
    kept_units: total((line) => line.kept_qty),
  };
}

/** Totalurile unei categorii fără niciun produs (toate zero). */
function emptyCategory(name) {
  return { name, ...zeros(CATEGORY_KEYS) };
}

/** Totaluri pe categorii, sortate descrescător după suma plătită pe produsele păstrate. */
function byCategory(lines) {
  const acc = new Map();
  for (const line of lines) {
    if (line.paid_only_qty) continue;
    const row = getOrCreate(acc, line.category, () => zeros(CATEGORY_KEYS));
    row.ordered_bani += line.line_total_bani;
    row.ordered_units += line.qty;
    row.kept_bani += line.kept_bani;
    row.kept_units += line.kept_qty;
    row.returned_bani += line.returned_bani;
    row.returned_units += line.returned_qty;
    row.cancelled_bani += line.cancelled_bani;
    row.cancelled_units += line.cancelled_qty;
    row.pending_bani += line.pending_bani;
    row.paid_ordered_bani += line.paid_value_bani;
    row.paid_kept_bani += line.kept_paid_bani;
    row.paid_returned_bani += line.returned_paid_bani;
    row.paid_cancelled_bani += line.cancelled_paid_bani;
    row.paid_pending_bani += line.pending_paid_bani;
  }
  const rows = [...acc].map(([name, values]) => ({ name, ...values }));
  return sortedBy(rows, (row) => [-row.paid_kept_bani, -row.kept_bani, row.name]);
}

/** Totaluri pe ani (după data plasării comenzii), crescător: la preț de listă și în bani plătiți (paid_totals.js). */
function byYear(orders, lines, paid) {
  const acc = new Map();
  const rowOf = (year) => getOrCreate(acc, year, () => ({ orders: 0, orders_with_kept: 0, ordered_bani: 0, kept_bani: 0, kept_units: 0, returned_bani: 0, cancelled_bani: 0 }));
  for (const order of orders) rowOf(yearOf(order.placed_at)).orders += 1;
  const keptOrders = new Set(); // perechile (an, comandă) cu cel puțin o bucată păstrată, ca text JSON exact
  for (const line of lines) {
    if (line.paid_only_qty) continue;
    const year = yearOf(line.placed_at);
    const row = rowOf(year);
    row.ordered_bani += line.line_total_bani;
    row.kept_bani += line.kept_bani;
    row.kept_units += line.kept_qty;
    row.returned_bani += line.returned_bani;
    row.cancelled_bani += line.cancelled_bani;
    const pair = JSON.stringify([year, line.order_id]);
    if (line.kept_qty > 0 && !keptOrders.has(pair)) {
      keptOrders.add(pair);
      row.orders_with_kept += 1;
    }
  }
  return sortedBy([...acc.keys()]).map((year) => {
    const spent = paid.by_year.get(year);
    return {
      year,
      ...acc.get(year),
      ...(spent !== undefined ? {
        paid_ordered_bani: spent.ordered_bani,
        paid_returned_bani: spent.returned_bani,
        paid_cancelled_bani: spent.cancelled_bani,
        paid_pending_bani: spent.pending_bani,
        paid_unknown_bani: spent.unknown_bani,
        paid_fees_bani: spent.fees_bani,
        spent_bani: spent.spent_bani,
      } : zeros(PAID_YEAR_KEYS)),
    };
  });
}

/**
 * Matricea an × serie din { an -> { serie -> bani } } (Map-uri), ca obiecte simple, cu seriile în ordinea dată și 0 unde lipsește o valoare.
 * Capcană JS: o cheie făcută doar din cifre (anul „2024”, sau o serie cu nume numeric) se ordonează crescător numeric, înaintea celorlalte; la ani de 4 cifre coincide cu sorted()
 * din Python, iar dashboard.js caută `values[an]` după lista `years`, nu după ordinea cheilor.
 */
function matrixValues(years, seriesNames, matrix) {
  return Object.fromEntries(years.map((year) => [year, Object.fromEntries(seriesNames.map((series) => [series, matrix.get(year).get(series) ?? 0]))]));
}

/** Matrice an × categorie (valoare păstrată la preț de listă) pentru graficul stivuit al rapoartelor vechi. */
function byYearCategory(lines, categories) {
  const byListValue = sortedBy(categories, (category) => [-category.kept_bani, category.name]);
  const top = byListValue.filter((category) => category.kept_bani > 0).map((category) => category.name).slice(0, YEARLY_CHART_TOP_CATEGORIES);
  const years = sortedBy([...new Set(lines.filter((line) => line.paid_only_qty === 0).map((line) => yearOf(line.placed_at)))]);
  const matrix = new Map(years.map((year) => [year, new Map()]));
  let hasOther = false;
  for (const line of lines) {
    if (line.paid_only_qty || line.kept_bani === 0) continue;
    const series = top.includes(line.category) ? line.category : OTHER_LABEL;
    hasOther = hasOther || series === OTHER_LABEL;
    const row = matrix.get(yearOf(line.placed_at));
    row.set(series, (row.get(series) ?? 0) + line.kept_bani);
  }
  const seriesNames = [...top, ...(hasOther ? [OTHER_LABEL] : [])];
  return { years, series: seriesNames, values: matrixValues(years, seriesNames, matrix) };
}

/**
 * Matrice an × serie în bani plătiți efectiv: cele mai mari categorii și rândurile care nu sunt produse („Transport și taxe”...), restul la „Altele”.
 * Suma unui an = plătitul efectiv al anului (dacă nicio serie nu e negativă).
 */
function paidByYearCategory(lines, categories, paid) {
  const taken = new Set(categories.map((category) => category.name));
  const extras = paid.summary.extra_rows.map((row) => [row.name + (taken.has(row.name) ? EXTRA_NAME_CLASH_SUFFIX : ''), row.key, row.bani]);
  const ranking = categories.filter((category) => category.paid_kept_bani > 0).map((category) => [category.name, category.paid_kept_bani]);
  ranking.push(...extras.filter(([, , bani]) => bani > 0).map(([name, , bani]) => [name, bani]));
  const top = sortedBy(ranking, (entry) => [-entry[1], entry[0]]).slice(0, YEARLY_CHART_TOP_CATEGORIES).map(([name]) => name);
  const years = sortedBy([...paid.by_year.keys()]);
  const matrix = new Map(years.map((year) => [year, new Map()]));
  let usedOther = false;
  /** Adaugă `bani` la seria `name` (sau la „Altele”, dacă nu e printre primele) în anul dat. */
  const add = (year, name, bani) => {
    const series = top.includes(name) ? name : OTHER_LABEL;
    usedOther = usedOther || series === OTHER_LABEL;
    const row = matrix.get(year);
    row.set(series, (row.get(series) ?? 0) + bani);
  };
  for (const line of lines) {
    if (!line.paid_only_qty && line.kept_paid_bani) add(yearOf(line.placed_at), line.category, line.kept_paid_bani);
  }
  for (const [name, key] of extras) {
    for (const [year, bani] of paid.extraValues(key)) if (bani) add(year, name, bani);
  }
  const seriesNames = [...top, ...(usedOther ? [OTHER_LABEL] : [])];
  return { years, series: seriesNames, values: matrixValues(years, seriesNames, matrix) };
}

/** Comanda cea mai recentă dintre cele văzute (Map: număr -> dată ISO): după dată, apoi după număr (mai lung = mai nou). */
function latestOrder(ordersSeen) {
  return maxBy([...ordersSeen.keys()], (orderId) => [ordersSeen.get(orderId), cpLength(orderId), orderId]);
}

/**
 * Produsele cu cea mai mare sumă PLĂTITĂ pe bucățile păstrate, grupate după nume, cu comanda lor cea mai recentă. Se ordonează după suma totală pe nume, nu după prețul pe bucată:
 * un produs ieftin cumpărat des poate trece înaintea unuia scump cumpărat o dată. `order_id` = comanda cea mai recentă în care a fost păstrat (linkul din raport), `order_count` = în câte comenzi;
 * `bani` = aceeași sumă la preț de listă (cheia veche).
 */
function topProducts(lines) {
  const groups = new Map();
  const ordersByKey = new Map();
  for (const line of lines) {
    if (line.paid_only_qty || line.kept_qty === 0) continue;
    const key = normalizeText(line.name);
    const row = getOrCreate(groups, key, () => ({ name: line.name, category: line.category, units: 0, bani: 0, paid_bani: 0 }));
    row.units += line.kept_qty;
    row.bani += line.kept_bani;
    row.paid_bani += line.kept_paid_bani;
    const seen = getOrCreate(ordersByKey, key, () => new Map());
    seen.set(line.order_id, laterDate(seen.get(line.order_id) ?? '', line.placed_at || ''));
  }
  const rows = [...groups].map(([key, row]) => ({ ...row, order_id: latestOrder(ordersByKey.get(key)), order_count: ordersByKey.get(key).size }));
  return sortedBy(rows, (row) => [-row.paid_bani, -row.bani, row.name]).slice(0, TOP_PRODUCTS_LIMIT);
}

/** Vânzătorii cu cea mai mare sumă plătită pe produsele păstrate (fără transport și taxe). */
function bySeller(lines) {
  const groups = new Map();
  for (const line of lines) {
    if (line.paid_only_qty || (line.kept_bani === 0 && line.kept_paid_bani === 0)) continue;
    const row = getOrCreate(groups, line.seller, () => ({ seller: line.seller, units: 0, bani: 0, paid_bani: 0 }));
    row.units += line.kept_qty;
    row.bani += line.kept_bani;
    row.paid_bani += line.kept_paid_bani;
  }
  return sortedBy([...groups.values()], (row) => [-row.paid_bani, -row.bani, row.seller]).slice(0, TOP_SELLERS_LIMIT);
}

/** Produsele cu preț de LISTĂ pe bucată STRICT peste prag, cu starea fiecărei părți (sumă de listă și sumă plătită). */
function bigItems(lines, thresholdBani) {
  const rows = [];
  for (const line of lines) {
    if (line.paid_only_qty || line.qty <= 0) continue;
    if (line.line_total_bani <= thresholdBani * line.qty) continue;
    const unit = floorDiv(line.line_total_bani * 2 + line.qty, line.qty * 2);
    for (const [state, qtyAttr, baniAttr, paidAttr] of STATE_PARTS) {
      const qty = line[qtyAttr];
      if (qty > 0) {
        rows.push({
          order_id: line.order_id,
          date: cpSlice(line.placed_at || '', 0, DAY_LENGTH),
          name: line.name,
          seller: line.seller,
          category: line.category,
          qty,
          unit_bani: unit,
          amount_bani: line[baniAttr],
          paid_amount_bani: line[paidAttr],
          state,
          returned_from_cancelled: line.returned_from_cancelled_qty !== 0 && state === 'returned',
        });
      }
    }
  }
  const sorted = sortedBy(rows, (row) => [-row.unit_bani, row.date, row.order_id]);
  const totals = {};
  for (const [state] of STATE_PARTS) totals[`${state}_bani`] = sumOf(sorted.filter((row) => row.state === state).map((row) => row.amount_bani));
  for (const [state] of STATE_PARTS) totals[`${state}_units`] = sumOf(sorted.filter((row) => row.state === state).map((row) => row.qty));
  for (const [state] of STATE_PARTS) totals[`${state}_paid_bani`] = sumOf(sorted.filter((row) => row.state === state).map((row) => row.paid_amount_bani));
  return { threshold_bani: thresholdBani, items: sorted, ...totals };
}

/** Pentru fiecare categorie cerută explicit: totalurile și lista produselor, pe stări (sumă de listă și plătită), ca obiect { categorie -> { totals, items, items_total } }. */
function highlightsOf(lines, categories, names) {
  const result = new Map();
  const byName = new Map(categories.map((category) => [category.name, category]));
  for (const name of names) {
    const totals = byName.get(name) ?? emptyCategory(name);
    const items = [];
    for (const line of lines) {
      if (line.category !== name || line.paid_only_qty) continue;
      for (const [state, qtyAttr, baniAttr, paidAttr] of STATE_PARTS) {
        const qty = line[qtyAttr];
        if (qty > 0) {
          items.push({
            order_id: line.order_id,
            date: cpSlice(line.placed_at || '', 0, DAY_LENGTH),
            name: line.name,
            qty,
            amount_bani: line[baniAttr],
            paid_amount_bani: line[paidAttr],
            state,
          });
        }
      }
    }
    const sorted = sortedBy(items, (row) => [row.date, row.order_id, row.name]);
    result.set(name, { totals, items: sorted.slice(0, HIGHLIGHT_ITEMS_LIMIT), items_total: sorted.length });
  }
  return Object.fromEntries(result);
}

/** Câte comenzi s-au păstrat integral/parțial, s-au returnat, anulat etc. */
function orderOutcomes(orders, lines) {
  const byOrder = new Map();
  for (const line of lines) getOrCreate(byOrder, line.order_id, () => []).push(line);
  const counts = new Map();
  for (const order of orders) {
    const group = byOrder.get(order.order_id) ?? [];
    const total = (select) => sumOf(group.map(select));
    const kept = total((line) => line.kept_qty);
    const returned = total((line) => line.returned_qty);
    const cancelled = total((line) => line.cancelled_qty);
    const pending = total((line) => line.pending_qty);
    const unknown = total((line) => line.unknown_qty);
    const paidOnly = total((line) => line.paid_only_qty);
    let outcome;
    if (group.length === 0) outcome = 'no_items';
    else if (paidOnly && !(kept || returned || cancelled || pending || unknown)) outcome = 'paid_only';
    else if (pending) outcome = 'in_progress';
    else if (unknown) outcome = 'unknown';
    else if (kept && !returned && !cancelled) outcome = 'kept_all';
    else if (kept) outcome = 'kept_partial';
    else if (returned) outcome = 'returned_all';
    else outcome = 'cancelled_all';
    counts.set(outcome, (counts.get(outcome) ?? 0) + 1);
  }
  return { total: orders.length, ...Object.fromEntries(ORDER_OUTCOMES.map((key) => [key, counts.get(key) ?? 0])) };
}

/** Blocuri de un anumit status, cu produsele și suma plătită (pentru secțiunea „excluse”). */
function excludedBlocks(orders, status) {
  const rows = [];
  for (const order of orders) {
    for (const block of order.blocks) {
      if (block.status === status) {
        rows.push({
          order_id: order.order_id,
          date: cpSlice(order.placed_at || '', 0, DAY_LENGTH),
          seller: block.seller,
          names: block.items.map((item) => item.name),
          products_bani: sumOf(block.items.map((item) => item.line_total_bani)),
          paid_bani: block.paid_bani || 0,
          status_text: block.status_text,
        });
      }
    }
  }
  return rows;
}

/** Cifre de control: ce s-a plătit efectiv, vouchere, taxe, restituiri. */
function reconciliationOf(orders, returns) {
  const delivered = orders.flatMap((order) => order.blocks.filter((block) => block.status === DELIVERED));
  const headerMismatches = [];
  for (const order of orders) {
    if (order.header_total_bani === null) continue;
    const paidSum = sumOf(order.blocks.map((block) => block.paid_bani || 0));
    if (paidSum !== order.header_total_bani) headerMismatches.push({ order_id: order.order_id, header_bani: order.header_total_bani, blocks_bani: paidSum });
  }
  const completed = returns.filter((ret) => ret.completed);
  const modes = new Map();
  for (const ret of completed) {
    const mode = ret.refund_mode || NO_REFUND_MODE_KEY;
    modes.set(mode, (modes.get(mode) ?? 0) + 1);
  }
  const storno = new Set();
  for (const order of orders) if (order.blocks.some((block) => block.has_storno)) storno.add(order.order_id);
  return {
    paid_delivered_bani: sumOf(delivered.map((block) => block.paid_bani || 0)),
    vouchers_delivered_bani: withoutNegativeZero(-sumOf(delivered.map((block) => sumOf(block.vouchers_bani)))),
    shipping_delivered_bani: sumOf(delivered.map((block) => block.shipping_bani || 0)),
    services_delivered_bani: sumOf(delivered.map((block) => sumOf(block.services_bani) + sumOf(block.other_bani))),
    returns_total: returns.length,
    returns_completed: completed.length,
    returns_cancelled: returns.filter((ret) => ret.cancelled).length,
    returns_pending: returnsWithoutResult(returns).length, // aceleași selecții ca în warnings_detail
    refunds_bani: sumOf(completed.map((ret) => ret.refund_bani || 0)),
    refunds_without_amount: completedReturnsWithoutAmount(returns).length,
    refund_modes: Object.fromEntries(modes),
    header_total_mismatches: headerMismatches,
    orders_with_storno: sortedBy([...storno]),
  };
}

/** Produsele fără categorie (după nume), cu valoarea de listă și comanda lor cea mai recentă (pentru link). */
function uncategorizedOf(lines, defaultCategory) {
  const groups = new Map();
  const ordersByName = new Map();
  for (const line of lines) {
    if (line.category === defaultCategory && !line.paid_only_qty) {
      const row = getOrCreate(groups, line.name, () => ({ units: 0, bani: 0 }));
      row.units += line.qty;
      row.bani += line.line_total_bani;
      const seen = getOrCreate(ordersByName, line.name, () => new Map());
      seen.set(line.order_id, laterDate(seen.get(line.order_id) ?? '', line.placed_at || ''));
    }
  }
  const rows = [...groups].map(([name, values]) => ({ name, ...values, order_id: latestOrder(ordersByName.get(name)), order_count: ordersByName.get(name).size }));
  return sortedBy(rows, (row) => [-row.bani, row.name]);
}

/**
 * Rulează toată analiza și întoarce { summary, lines }. O categorie din `highlightCategories` care nu există în regulile clasificatorului primește un avertisment
 * (totalul ei ar apărea 0, un rezultat greșit care pare normal). `warningTexts`, `colorWords` și `refundModes` sunt obligatorii: în extensie nu există fișierele din care le-ar citi Python.
 */
export function analyze(orders, returns, classifier, thresholdBani, generatedAt, { highlightCategories = [], warningTexts, colorWords, refundModes, log = null } = {}) {
  if (!warningTexts || !colorWords || !refundModes) {
    throw new TypeError('analyze(): warningTexts, colorWords și refundModes sunt obligatorii (configurările vin ca obiecte, din loadWarningTexts, loadColorWords și loadRefundModes)');
  }
  const lines = buildLines(orders);
  for (const line of lines) {
    [line.category, line.rule] = classifier.classify(line.name);
  }
  const matchReport = applyReturns(lines, returns, log);
  const paid = computePaidTotals(orders, lines, returns, matchReport, refundModes);

  const funnel = funnelOf(lines);
  const categories = byCategory(lines);
  const dates = sortedBy(orders.filter((order) => order.placed_at).map((order) => order.placed_at));
  const reconciliation = reconciliationOf(orders, returns);

  const warnings = [];
  for (const order of orders) warnings.push(...currentOrderWarnings(order)); // fără zgomotul vechi din cache-uri salvate de o versiune anterioară
  warnings.push(...matchReport.warnings, ...paid.warnings);
  const knownCategories = new Set([...classifier.categoryNames, classifier.defaultCategory]); // și „Necategorizat” are totaluri reale
  for (const name of highlightCategories) if (!knownCategories.has(name)) warnings.push(formatHighlightCategoryMissing(name));
  const parts = sumOf(['cancelled_bani', 'returned_bani', 'pending_bani', 'unknown_bani', 'kept_bani'].map((key) => funnel[key]));
  if (parts !== funnel.ordered_bani) warnings.push(formatFunnelNotClosing(funnel.ordered_bani, parts));
  for (const block of excludedBlocks(orders, UNKNOWN)) warnings.push(formatUnknownStatus(block.order_id, block.seller, block.status_text));
  if (reconciliation.returns_pending) warnings.push(formatPendingReturns(reconciliation.returns_pending));
  if (reconciliation.refunds_without_amount) warnings.push(formatRefundsWithoutAmount(reconciliation.refunds_without_amount));
  if (reconciliation.header_total_mismatches.length > 0) warnings.push(formatHeaderMismatches(reconciliation.header_total_mismatches.length));

  const uncategorizedRows = uncategorizedOf(lines, classifier.defaultCategory);
  if (uncategorizedRows.length > 0) warnings.push(formatUncategorized(uncategorizedRows.length));

  const paidSummary = { ...paid.summary, by_year_category: paidByYearCategory(lines, categories, paid) };
  const summary = {
    meta: {
      generated_at: generatedAt,
      threshold_bani: thresholdBani,
      first_order: dates.length > 0 ? cpSlice(dates[0], 0, DAY_LENGTH) : null,
      last_order: dates.length > 0 ? cpSlice(dates[dates.length - 1], 0, DAY_LENGTH) : null,
      orders: orders.length,
      blocks: sumOf(orders.map((order) => order.blocks.length)),
      lines: lines.length,
    },
    funnel,
    paid: paidSummary,
    orders: orderOutcomes(orders, lines),
    by_category: categories,
    by_year: byYear(orders, lines, paid),
    by_year_category: byYearCategory(lines, categories),
    top_products: topProducts(lines),
    by_seller: bySeller(lines),
    big: bigItems(lines, thresholdBani),
    highlights: highlightsOf(lines, categories, highlightCategories),
    paid_only: excludedBlocks(orders, PAID_ONLY),
    in_progress: excludedBlocks(orders, IN_PROGRESS),
    reconciliation,
    returns: {
      matched_units: matchReport.matched_units,
      matched_from_cancelled_units: matchReport.matched_from_cancelled_units,
      unmatched_refund_bani: matchReport.unmatched_refund_bani,
    },
    uncategorized: uncategorizedRows.slice(0, UNCATEGORIZED_SAMPLE_LIMIT),
    uncategorized_count: uncategorizedRows.length,
    price_history: buildPriceHistory(lines, colorWords),
    warnings,
    warnings_detail: buildWarningsDetail(warnings, orders, returns, reconciliation.header_total_mismatches, warningTexts, log),
  };
  log?.info(LOG_MODULE, `analiză: ${orders.length} comenzi, plătit efectiv ${paid.summary.spent_bani} bani (păstrat la preț de listă ${funnel.kept_bani} bani), ${warnings.length} avertismente`);
  return { summary, lines };
}

/**
 * Copia rezumatului numai din tipuri JSON simple: fiecare PyFloat devine numărul lui (singurul loc din rezumat e `price_history.products[].last_vs_prev_pct`).
 * De ce: chrome.storage ar salva un PyFloat ca obiect, iar dashboard.js cere numere; raportul și analiza.json se scriu din rezumatul cu PyFloat, ca „5.0” să rămână „5.0”.
 */
export function plainSummary(value) {
  if (value instanceof PyFloat) return value.value;
  if (Array.isArray(value)) return value.map(plainSummary);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, plainSummary(item)]));
  return value;
}
