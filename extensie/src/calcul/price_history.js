// Istoricul prețurilor la același produs, din produsele cumpărate în cel puțin două comenzi (portul lui emag_spend/price_history.py).
// Primește: registrul de linii (după retururi) și lista de culori (ColorWords). Dă înapoi: `price_history` din analiza.json (`summary` + `products`, sortate descrescător după diferența
// față de cel mai mic preț plătit), sume în BANI. Contează doar unitățile PĂSTRATE; preț pe bucată = total linie / cantitate, rotunjit întreg; liniile cu preț <= 0 (cadouri) se ignoră.
// „Același produs” = aceeași cheie (product_key.js); un nume trunchiat „[...]” se alătură unei grupe doar dacă potrivirea e unică. Procentul e float în Python, deci iese ca PyFloat.
// Ce NU face: nu spune „ai pierdut/ai câștigat” (prețul include promoții).
import { PyFloat, cpLength, cpSlice, floorDiv, maxBy, minBy, pyRound, sortedBy, withoutNegativeZero } from './python_compat.js';
import { makeProductKey } from './product_key.js';
import { MIN_TRUNCATED_PREFIX } from './return_matcher.js';

// Un produs intră în istoric doar dacă are unități păstrate în cel puțin atâtea comenzi diferite: o singură comandă nu are un „preț de data trecută” cu care să se compare.
export const MIN_ORDERS_PER_PRODUCT = 2;
// Procentele de variație se rotunjesc la o zecimală (ex. 7,4%): mai multe ar sugera o precizie pe care prețuri cu promoții și vânzători diferiți nu o au.
export const PERCENT_DECIMALS = 1;
// Cât din data ISO se folosește la ordonarea cronologică („2024-03-10T10:00” -> primele 16 caractere, cu ora) și la afișarea zilei (primele 10).
const SORT_DATE_LENGTH = 16;
const DAY_LENGTH = 10;

/** Suma unei liste de întregi (sum() din Python). */
function sumOf(values) {
  return values.reduce((total, value) => total + value, 0);
}

/** Prețul pe bucată în bani: total linie / cantitate, rotunjit la cel mai apropiat ban (aritmetică întreagă; apelată doar cu cantitate pozitivă). */
function unitBani(line) {
  return floorDiv(line.line_total_bani * 2 + line.qty, line.qty * 2);
}

/** Liniile cu cel puțin o unitate păstrată, preț pe bucată pozitiv și nume cu cel puțin un cuvânt, ca { line, product_key, unit_bani }. */
function purchasesOf(lines, colorWords) {
  const found = [];
  for (const line of lines) {
    if (line.kept_qty <= 0 || line.qty <= 0 || line.line_total_bani <= 0) continue;
    const unit = unitBani(line);
    const productKey = makeProductKey(line.name, colorWords);
    if (unit > 0 && productKey.key !== '') found.push({ line, product_key: productKey, unit_bani: unit }); // un preț care se rotunjește la 0 bani e tot un cadou
  }
  return found;
}

/**
 * True dacă numele trunchiat începe la fel ca numele (sau cheia) vreunui membru al grupei, cu un prefix de cel puțin MIN_TRUNCATED_PREFIX caractere
 * (ca la retururi: unul mai scurt ar potrivi produse diferite).
 */
function truncatedPrefixMatches(truncated, members) {
  const { prefix } = truncated.product_key;
  const keyPrefix = truncated.product_key.key;
  return members.some((member) => (cpLength(prefix) >= MIN_TRUNCATED_PREFIX && member.product_key.normalized.startsWith(prefix))
    || (cpLength(keyPrefix) >= MIN_TRUNCATED_PREFIX && member.product_key.key.startsWith(keyPrefix)));
}

/**
 * Grupează cumpărările după cheie (Map: cheie -> cumpărări); un nume trunchiat se alătură grupei care se potrivește, dacă e una singură.
 * Ambiguu sau fără potrivire: rămâne în grupa lui (mai bine două grupe decât produse unite greșit).
 */
function groupByProduct(purchases) {
  const groups = new Map();
  const add = (key, purchase) => {
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(purchase);
  };
  for (const purchase of purchases) if (!purchase.product_key.truncated) add(purchase.product_key.key, purchase);
  for (const purchase of purchases) {
    if (!purchase.product_key.truncated) continue;
    const matching = [...groups].filter(([, members]) => members.some((member) => !member.product_key.truncated) && truncatedPrefixMatches(purchase, members)).map(([key]) => key);
    add(matching.length === 1 ? matching[0] : purchase.product_key.key, purchase);
  }
  return groups;
}

/** Cumpărările de la cea mai veche la cea mai nouă (fără dată = cele mai vechi; apoi după număr de comandă); sortare stabilă. */
function chronological(purchases) {
  return sortedBy(purchases, (purchase) => [cpSlice(purchase.line.placed_at || '', 0, SORT_DATE_LENGTH), cpLength(purchase.line.order_id), purchase.line.order_id]);
}

/** Cel mai recent nume complet (netrunchiat); dacă toate sunt trunchiate, cel mai recent. */
function displayName(purchases) {
  for (let index = purchases.length - 1; index >= 0; index -= 1) {
    if (!purchases[index].product_key.truncated) return purchases[index].line.name;
  }
  return purchases[purchases.length - 1].line.name;
}

/** Intrarea unui produs: cumpărările, extremele de preț și comparațiile cerute (cheile în ordinea din Python). */
function productEntry(key, purchases) {
  const ordered = chronological(purchases);
  const units = ordered.map((purchase) => purchase.unit_bani);
  const keptUnits = sumOf(ordered.map((purchase) => purchase.line.kept_qty));
  const low = minBy(units);
  const last = ordered[ordered.length - 1];
  const previous = [...ordered].reverse().find((purchase) => purchase.line.order_id !== last.line.order_id);
  const delta = last.unit_bani - previous.unit_bani;
  return {
    key,
    name: displayName(ordered),
    category: last.line.category,
    purchases: ordered.map((purchase) => ({
      date: cpSlice(purchase.line.placed_at || '', 0, DAY_LENGTH) || null,
      order_id: purchase.line.order_id,
      seller: purchase.line.seller,
      name: purchase.line.name,
      qty: purchase.line.kept_qty,
      unit_bani: purchase.unit_bani,
    })),
    kept_units: keptUnits,
    first_unit_bani: ordered[0].unit_bani,
    last_unit_bani: last.unit_bani,
    min_unit_bani: low,
    max_unit_bani: maxBy(units),
    last_vs_prev_unit_bani: delta,
    last_vs_prev_pct: new PyFloat(pyRound((delta * 100) / previous.unit_bani, PERCENT_DECIMALS)), // prețul precedent e > 0 (liniile <= 0 sunt ignorate)
    last_vs_prev_impact_bani: withoutNegativeZero(delta * last.line.kept_qty),
    overpaid_vs_min_bani: sumOf(ordered.map((purchase) => withoutNegativeZero((purchase.unit_bani - low) * purchase.line.kept_qty))),
    // nume trunchiate nu intră: ele pot pierde culoarea din coadă fără ca produsul să fi variat
    color_variants: new Set(ordered.filter((purchase) => !purchase.product_key.truncated).map((purchase) => JSON.stringify(purchase.product_key.colors))).size > 1,
  };
}

/** Totalurile pe toate produsele din istoric (impactul ultimei cumpărări, ca sume pozitive). */
function summaryOf(products) {
  const cheaper = products.filter((product) => product.last_vs_prev_unit_bani < 0);
  const pricier = products.filter((product) => product.last_vs_prev_unit_bani > 0);
  return {
    products: products.length,
    purchases: sumOf(products.map((product) => product.purchases.length)),
    units: sumOf(products.map((product) => product.kept_units)),
    overpaid_vs_min_bani: sumOf(products.map((product) => product.overpaid_vs_min_bani)),
    last_vs_prev: {
      cheaper_products: cheaper.length,
      pricier_products: pricier.length,
      same_products: products.length - cheaper.length - pricier.length,
      cheaper_bani: withoutNegativeZero(-sumOf(cheaper.map((product) => product.last_vs_prev_impact_bani))),
      pricier_bani: sumOf(pricier.map((product) => product.last_vs_prev_impact_bani)),
    },
  };
}

/** Istoricul prețurilor la același produs (cheia `price_history` din analiza.json): { summary, products }. */
export function buildPriceHistory(lines, colorWords) {
  const groups = groupByProduct(purchasesOf(lines, colorWords));
  const products = [...groups]
    .filter(([, members]) => new Set(members.map((member) => member.line.order_id)).size >= MIN_ORDERS_PER_PRODUCT)
    .map(([key, members]) => productEntry(key, members));
  const sorted = sortedBy(products, (product) => [-product.overpaid_vs_min_bani, product.key]);
  return { summary: summaryOf(sorted), products: sorted };
}
